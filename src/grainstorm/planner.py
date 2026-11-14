"""Transparent, assumption-driven crop-sequence water and nitrogen planner.

This first planner is a scenario calculator, not a crop-growth or yield model.
All crop water and net mineral-nitrogen values are supplied by the user so
that the program does not hide unsupported agronomic assumptions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from grainstorm.fao56 import dual_coefficient_day, validate_dual_config


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return result


def _read_scenario(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        scenario = json.load(stream)
    if not isinstance(scenario, dict):
        raise ValueError("Scenario file must contain a JSON object.")
    return scenario


def _month_day(value: Any, label: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) != 5 or value[2] != "-":
        raise ValueError(f"{label} must use MM-DD format.")
    try:
        parsed = date.fromisoformat(f"2000-{value}")
    except ValueError as exc:
        raise ValueError(f"{label} must use a valid MM-DD date.") from exc
    if value == "02-29":
        raise ValueError(f"{label} cannot use 02-29 in a recurring annual window.")
    return parsed.month, parsed.day


def _planting_windows(crop: dict[str, Any], crop_name: str) -> list[dict[str, Any]]:
    raw = crop.get("planting_windows")
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{crop_name}.planting_windows must be a non-empty array when supplied.")
    windows = []
    for index, item in enumerate(raw):
        label = f"{crop_name}.planting_windows[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object.")
        start = _month_day(item.get("start_month_day"), f"{label}.start_month_day")
        end = _month_day(item.get("end_month_day"), f"{label}.end_month_day")
        name = item.get("label", f"Window {index + 1}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}.label must be a non-empty string when supplied.")
        windows.append({"start": start, "end": end, "label": name.strip(),
                        "start_month_day": item["start_month_day"],
                        "end_month_day": item["end_month_day"]})
    return windows


def _window_intervals(windows: list[dict[str, Any]], year: int) -> list[tuple[date, date, dict[str, Any]]]:
    intervals = []
    for start_year in range(year - 1, year + 3):
        for window in windows:
            start = date(start_year, *window["start"])
            end_year = start_year if window["start"] <= window["end"] else start_year + 1
            end = date(end_year, *window["end"])
            intervals.append((start, end, window))
    return sorted(intervals, key=lambda item: item[0])


def _schedule_planting(earliest: date, windows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if not windows:
        return {"date": earliest, "status": "not_provided", "calendar_wait_days": 0,
                "matched_window": None}
    intervals = _window_intervals(windows, earliest.year)
    for start, end, window in intervals:
        if start <= earliest <= end:
            return {"date": earliest, "status": "within_window", "calendar_wait_days": 0,
                    "matched_window": {"label": window["label"],
                                       "start_date": start.isoformat(), "end_date": end.isoformat()}}
    if mode == "fixed_gap":
        return {"date": earliest, "status": "outside_window", "calendar_wait_days": 0,
                "matched_window": None}
    next_interval = next(((start, end, window) for start, end, window in intervals if start > earliest), None)
    if next_interval is None:
        raise ValueError("Could not resolve the next recurring planting window.")
    start, end, window = next_interval
    return {"date": start, "status": "shifted_to_window",
            "calendar_wait_days": (start - earliest).days,
            "matched_window": {"label": window["label"],
                               "start_date": start.isoformat(), "end_date": end.isoformat()}}


def _optional_number(value: Any, label: str, *, minimum: float | None = None) -> float | None:
    return None if value is None else _number(value, label, minimum=minimum)


def _input_assessment(config: dict[str, Any]) -> dict[str, Any]:
    field = config.get("field", {})
    catalog = config.get("crop_catalog", {})
    scenarios = config.get("scenarios", [])
    missing: list[str] = []
    domains: dict[str, Any] = {}
    soil_test = field.get("soil_test")
    soil_fields = ("mineral_n_kg_ha", "available_p_kg_ha", "exchangeable_k_kg_ha",
                   "organic_matter_percent", "ph")
    soil_missing = [name for name in soil_fields if not isinstance(soil_test, dict) or soil_test.get(name) is None]
    domains["soil_test"] = {"status": "complete" if not soil_missing else "partial",
                            "missing": soil_missing}
    if soil_missing:
        missing.extend(f"field.soil_test.{name}" for name in soil_missing)
    crop_details = {}
    for crop_id, crop in catalog.items():
        crop_missing = []
        if not crop.get("planting_windows"):
            crop_missing.append("planting_windows")
        if not crop.get("nutrient_budget") and not crop.get("agronomy"):
            crop_missing.append("nutrient_budget_or_agronomy")
        if not crop.get("economics"):
            crop_missing.append("economics")
        if not crop.get("root_depth_m"):
            crop_missing.append("root_depth_m")
        crop_details[crop_id] = {"status": "complete" if not crop_missing else "partial",
                                 "missing": crop_missing}
        missing.extend(f"crop_catalog.{crop_id}.{name}" for name in crop_missing)
    domains["crops"] = crop_details
    transitions = {f"{sequence[index]}->{sequence[index + 1]}"
                   for scenario in scenarios if isinstance(scenario, dict)
                   for sequence in [scenario.get("crops", [])]
                   for index in range(max(0, len(sequence) - 1))}
    rotation_catalog = config.get("rotation_effect_catalog", {})
    missing_transitions = sorted(transition for transition in transitions if transition not in rotation_catalog)
    domains["rotation_effects"] = {
        "status": "complete" if not missing_transitions else "partial",
        "missing_transitions": missing_transitions,
    }
    missing.extend(f"rotation_effect_catalog.{transition}" for transition in missing_transitions)
    management = field.get("management")
    domains["management"] = {"status": "complete" if isinstance(management, dict) else "not_provided"}
    if not isinstance(management, dict):
        missing.append("field.management")
    resolution = config.get("input_resolution")
    return {
        "status": "complete" if not missing else "partial",
        "provided_features_are_calculated": True,
        "missing_inputs": missing,
        "domains": domains,
        "note": (
            "Caller inputs are used first; generated planning baselines and their provenance are listed in input_resolution."
            if resolution else
            "Missing optional inputs are not guessed; affected outputs remain incomplete or not evaluated."
        ),
        "input_resolution": resolution,
    }


def _nutrient_change(crop: dict[str, Any], crop_name: str, nutrient: str) -> tuple[float | None, dict[str, float] | None]:
    budget = crop.get("nutrient_budget")
    agronomy = crop.get("agronomy")
    if budget is not None and agronomy is not None:
        raise ValueError(f"{crop_name} must use nutrient_budget or agronomy, not both.")
    if budget is None and agronomy is not None:
        if not isinstance(agronomy, dict):
            raise ValueError(f"{crop_name}.agronomy must be an object.")
        source = agronomy.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"{crop_name}.agronomy.source is required.")
        removal = agronomy.get("nutrient_removal_kg_per_tonne", {})
        if not isinstance(removal, dict):
            raise ValueError(f"{crop_name}.agronomy.nutrient_removal_kg_per_tonne must be an object.")
        if nutrient in removal:
            economics = crop.get("economics")
            expected_yield = agronomy.get("expected_yield_t_ha")
            if expected_yield is None and isinstance(economics, dict):
                expected_yield = economics.get("expected_yield_t_ha")
            if expected_yield is None:
                raise ValueError(
                    f"{crop_name}.agronomy.expected_yield_t_ha or economics.expected_yield_t_ha "
                    "is required to derive nutrient removal."
                )
            yield_t_ha = _number(expected_yield, f"{crop_name}.expected_yield_t_ha", minimum=0)
            total_removal = yield_t_ha * _number(removal[nutrient], f"{crop_name}.{nutrient}_removal", minimum=0)
            applied_map = agronomy.get("fertilizer_applied_kg_ha", {})
            recovery_map = agronomy.get("fertilizer_recovery_fraction", {})
            residue_map = agronomy.get("residue_release_kg_ha", {})
            loss_map = agronomy.get("other_losses_kg_ha", {})
            for label, value in (("fertilizer_applied_kg_ha", applied_map),
                                 ("fertilizer_recovery_fraction", recovery_map),
                                 ("residue_release_kg_ha", residue_map),
                                 ("other_losses_kg_ha", loss_map)):
                if not isinstance(value, dict):
                    raise ValueError(f"{crop_name}.agronomy.{label} must be an object.")
            applied = _number(applied_map.get(nutrient, 0), f"{crop_name}.{nutrient}_fertilizer", minimum=0)
            if applied and nutrient not in recovery_map:
                raise ValueError(f"{crop_name}.agronomy.fertilizer_recovery_fraction.{nutrient} is required.")
            recovery = _number(recovery_map.get(nutrient, 0), f"{crop_name}.{nutrient}_recovery", minimum=0)
            if recovery > 1:
                raise ValueError("fertilizer recovery fractions must be between 0 and 1.")
            fertilizer = applied * recovery
            residue = _number(residue_map.get(nutrient, 0), f"{crop_name}.{nutrient}_residue", minimum=0)
            losses = _number(loss_map.get(nutrient, 0), f"{crop_name}.{nutrient}_losses", minimum=0)
            fixation = 0.0
            uptake_from_soil = total_removal
            if nutrient == "n":
                fixation = _number(agronomy.get("biological_fixation_n_kg_ha", 0),
                                   f"{crop_name}.biological_fixation_n_kg_ha", minimum=0)
                uptake_from_soil = max(0.0, total_removal - fixation)
            net = fertilizer + residue - uptake_from_soil - losses
            detail = {
                "fertilizer_applied_kg_ha": applied,
                "fertilizer_recovery_fraction": recovery,
                "fertilizer": fertilizer,
                "residue_release": residue,
                "crop_total_removal_kg_ha": total_removal,
                "crop_uptake_from_soil": uptake_from_soil,
                "other_losses": losses,
                "net_change_kg_ha": net,
                "source": source.strip(),
                "note": agronomy.get("note"),
                "calculation": "yield × removal coefficient; fertilizer contribution is applied × recovery",
            }
            if nutrient == "n":
                detail["biological_fixation"] = fixation
            return net, detail
    if budget is None:
        if nutrient == "n":
            return _number(crop.get("net_soil_n_change_kg_ha"),
                           f"{crop_name}.net_soil_n_change_kg_ha"), None
        return 0.0, None
    if not isinstance(budget, dict):
        raise ValueError(f"{crop_name}.nutrient_budget must be an object.")
    raw = budget.get(nutrient)
    if raw is None:
        if nutrient == "n":
            return _number(crop.get("net_soil_n_change_kg_ha"),
                           f"{crop_name}.net_soil_n_change_kg_ha"), None
        return 0.0, None
    if not isinstance(raw, dict):
        raise ValueError(f"{crop_name}.nutrient_budget.{nutrient} must be an object.")
    allowed = {"fertilizer", "residue_release", "crop_uptake_from_soil", "other_losses"}
    if nutrient == "n":
        allowed.add("biological_fixation")
    unknown = set(raw) - allowed - {"source", "note"}
    if unknown:
        raise ValueError(f"Unsupported {nutrient.upper()} budget field: {sorted(unknown)[0]}.")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{crop_name}.nutrient_budget.{nutrient}.source is required.")
    values = {key: _number(raw.get(key, 0), f"{crop_name}.{nutrient}.{key}", minimum=0)
              for key in allowed}
    additions = values["fertilizer"] + values["residue_release"]
    net = additions - values["crop_uptake_from_soil"] - values["other_losses"]
    return net, {**values, "net_change_kg_ha": net, "source": source.strip(),
                 "note": raw.get("note")}


def _economics(crop: dict[str, Any], crop_name: str, area_ha: float) -> dict[str, Any] | None:
    raw = crop.get("economics")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{crop_name}.economics must be an object.")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{crop_name}.economics.source is required.")
    currency = raw.get("currency")
    if not isinstance(currency, str) or len(currency.strip()) != 3 or not currency.strip().isalpha():
        raise ValueError(f"{crop_name}.economics.currency must be a three-letter currency code.")
    yield_t_ha = _number(raw.get("expected_yield_t_ha"), f"{crop_name}.expected_yield_t_ha", minimum=0)
    price = _number(raw.get("price_per_tonne"), f"{crop_name}.price_per_tonne", minimum=0)
    marketable_fraction = _number(raw.get("marketable_yield_fraction", 1),
                                  f"{crop_name}.marketable_yield_fraction", minimum=0)
    if marketable_fraction > 1:
        raise ValueError(f"{crop_name}.marketable_yield_fraction must be between 0 and 1.")
    raw_items = raw.get("cost_items", [])
    if not isinstance(raw_items, list):
        raise ValueError(f"{crop_name}.economics.cost_items must be an array.")
    if raw.get("variable_cost_per_ha") is None and not raw_items:
        raise ValueError(f"{crop_name}.economics requires variable_cost_per_ha or cost_items.")
    if raw.get("variable_cost_per_ha") is not None and raw_items:
        raise ValueError(f"{crop_name}.economics must use variable_cost_per_ha or cost_items, not both.")
    if raw_items and raw.get("cost_completeness_confirmed") is not True:
        raise ValueError(f"{crop_name}.economics.cost_completeness_confirmed must be true for itemized costs.")
    cost_items = []
    variable_cost = _number(raw.get("variable_cost_per_ha", 0),
                            f"{crop_name}.variable_cost_per_ha", minimum=0)
    if raw.get("variable_cost_per_ha") is not None:
        cost_items.append({"name": "Other variable production costs", "category": "other",
                           "amount_per_ha": variable_cost,
                           "amount_for_field": variable_cost * area_ha,
                           "source": source.strip()})
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError(f"{crop_name}.economics.cost_items[{index}] must be an object.")
        name, item_source = item.get("name"), item.get("source")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{crop_name}.economics.cost_items[{index}].name is required.")
        if not isinstance(item_source, str) or not item_source.strip():
            raise ValueError(f"{crop_name}.economics.cost_items[{index}].source is required.")
        per_ha_raw, field_raw = item.get("amount_per_ha"), item.get("amount_for_field")
        if (per_ha_raw is None) == (field_raw is None):
            raise ValueError(f"{crop_name}.economics.cost_items[{index}] requires exactly one of amount_per_ha or amount_for_field.")
        amount_field = (_number(per_ha_raw, f"{crop_name}.cost_items[{index}].amount_per_ha", minimum=0) * area_ha
                        if per_ha_raw is not None else
                        _number(field_raw, f"{crop_name}.cost_items[{index}].amount_for_field", minimum=0))
        cost_items.append({
            "name": name.strip(), "category": item.get("category", "other"),
            "amount_per_ha": round(amount_field / area_ha, 2),
            "amount_for_field": round(amount_field, 2), "source": item_source.strip(),
            "note": item.get("note"),
        })
    additional_income_ha = _number(raw.get("additional_income_per_ha", 0),
                                   f"{crop_name}.additional_income_per_ha", minimum=0)
    marketable_yield = yield_t_ha * marketable_fraction
    gross_ha = marketable_yield * price
    total_cost_field = sum(item["amount_for_field"] for item in cost_items)
    total_cost_ha = total_cost_field / area_ha
    revenue_field = gross_ha * area_ha
    additional_income_field = additional_income_ha * area_ha
    margin_field = revenue_field + additional_income_field - total_cost_field
    margin_ha = margin_field / area_ha
    roi = None if total_cost_field == 0 else margin_field / total_cost_field * 100
    break_even_price = None if marketable_yield == 0 else total_cost_ha / marketable_yield
    break_even_yield = None if price == 0 or marketable_fraction == 0 else total_cost_ha / price / marketable_fraction
    return {
        "expected_yield_t_ha": yield_t_ha,
        "marketable_yield_fraction": marketable_fraction,
        "marketable_yield_t_ha": round(marketable_yield, 4),
        "price_per_tonne": price,
        "variable_cost_per_ha": round(total_cost_ha, 2),
        "cost_items": cost_items,
        "cost_completeness_confirmed": True,
        "total_crop_cost_per_ha": round(total_cost_ha, 2),
        "total_crop_cost_for_field": round(total_cost_field, 2),
        "gross_revenue_per_ha": round(gross_ha, 2),
        "gross_revenue_for_field": round(revenue_field, 2),
        "additional_income_per_ha": round(additional_income_ha, 2),
        "additional_income_for_field": round(additional_income_field, 2),
        "estimated_margin_per_ha": round(margin_ha, 2),
        "expected_production_t_for_field": round(yield_t_ha * area_ha, 2),
        "marketable_production_t_for_field": round(marketable_yield * area_ha, 2),
        "estimated_margin_for_field": round(margin_field, 2),
        "return_on_cost_percent": None if roi is None else round(roi, 2),
        "break_even_price_per_tonne": None if break_even_price is None else round(break_even_price, 2),
        "break_even_yield_t_ha": None if break_even_yield is None else round(break_even_yield, 4),
        "currency": currency.strip().upper(),
        "source": source.strip(),
        "basis": "user-supplied baseline; not adjusted for modeled stress",
    }


def _rank_scenarios(results: list[dict[str, Any]], raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"status": "not_requested", "ranked_scenarios": []}
    if not isinstance(raw, dict):
        raise ValueError("ranking must be an object.")
    if raw.get("enabled", False) is False:
        return {"status": "not_requested", "ranked_scenarios": []}
    if not isinstance(raw.get("weights"), dict):
        raise ValueError("ranking.weights must be supplied when ranking is enabled.")
    directions = {
        "net_margin": "high", "irrigation": "low", "unmet_water": "low",
        "nutrient_shortfall": "low", "pest_disease": "high",
    }
    weights = {key: _number(value, f"ranking.weights.{key}", minimum=0)
               for key, value in raw["weights"].items()}
    unknown = set(weights) - set(directions)
    if unknown:
        raise ValueError(f"Unsupported ranking criterion: {sorted(unknown)[0]}.")
    weights = {key: value for key, value in weights.items() if value > 0}
    if not weights:
        raise ValueError("At least one ranking weight must be greater than zero.")
    metric_key = {
        "net_margin": "estimated_total_margin_for_field",
        "irrigation": "total_irrigation_m3_for_field",
        "unmet_water": "total_unmet_water_mm",
        "nutrient_shortfall": "total_nutrient_shortfall_kg_ha",
        "pest_disease": "pest_disease_rotation_score",
    }
    candidates, excluded = [], []
    for result in results:
        missing = [criterion for criterion in weights if result.get(metric_key[criterion]) is None]
        if result["calendar_feasible"] is not True:
            missing.append("calendar_feasibility")
        if missing:
            excluded.append({"name": result["name"], "reasons": sorted(set(missing))})
        else:
            candidates.append(result)
    if not candidates:
        return {"status": "insufficient_inputs", "ranked_scenarios": [], "excluded": excluded,
                "weights": weights}
    ranges = {criterion: [result[metric_key[criterion]] for result in candidates]
              for criterion in weights}
    ranked = []
    total_weight = sum(weights.values())
    for result in candidates:
        parts = {}
        score = 0.0
        for criterion, weight in weights.items():
            values = ranges[criterion]
            value = result[metric_key[criterion]]
            if max(values) == min(values):
                normalized = 1.0
            elif directions[criterion] == "high":
                normalized = (value - min(values)) / (max(values) - min(values))
            else:
                normalized = (max(values) - value) / (max(values) - min(values))
            parts[criterion] = {"value": value, "normalized": round(normalized, 4), "weight": weight}
            score += normalized * weight
        ranked.append({"name": result["name"], "score": round(100 * score / total_weight, 2),
                       "criteria": parts})
    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
    return {"status": "complete", "ranked_scenarios": ranked, "excluded": excluded,
            "weights": weights,
            "warning": "Decision score from caller-selected weights; not an agronomic recommendation."}


def simulate_scenarios(config: dict[str, Any]) -> dict[str, Any]:
    """Compare crop sequences using explicit daily rainfall and crop inputs."""
    field = config.get("field", {})
    catalog = config.get("crop_catalog", {})
    weather_rows = config.get("weather", [])
    scenarios = config.get("scenarios", [])

    if not isinstance(field, dict) or not isinstance(catalog, dict):
        raise ValueError("field and crop_catalog must be JSON objects.")
    if not isinstance(weather_rows, list) or not isinstance(scenarios, list):
        raise ValueError("weather and scenarios must be JSON arrays.")
    if not scenarios:
        raise ValueError("Add at least one crop sequence under scenarios.")

    soil_test = field.get("soil_test")
    if soil_test is not None:
        if not isinstance(soil_test, dict):
            raise ValueError("field.soil_test must be an object.")
        for required in ("source", "sample_date", "depth_cm"):
            if soil_test.get(required) in (None, ""):
                raise ValueError(f"field.soil_test.{required} is required when soil_test is supplied.")
        try:
            date.fromisoformat(str(soil_test["sample_date"]))
        except ValueError as exc:
            raise ValueError("field.soil_test.sample_date must use YYYY-MM-DD format.") from exc
        _number(soil_test["depth_cm"], "field.soil_test.depth_cm", minimum=0.000001)
    else:
        soil_test = {}

    def soil_value(field_key: str, test_key: str) -> Any:
        if field.get(field_key) is not None and soil_test.get(test_key) is not None:
            raise ValueError(f"Supply {field_key} or soil_test.{test_key}, not both.")
        return field.get(field_key) if field.get(field_key) is not None else soil_test.get(test_key)

    management = field.get("management")
    if management is not None:
        if not isinstance(management, dict):
            raise ValueError("field.management must be an object.")
        if not isinstance(management.get("source"), str) or not management["source"].strip():
            raise ValueError("field.management.source is required.")

    area_ha = _number(field.get("area_ha"), "field.area_ha", minimum=0.000001)
    capacity = _number(
        field.get("soil_water_capacity_mm"),
        "field.soil_water_capacity_mm",
        minimum=0,
    )
    initial_water = _number(
        field.get("initial_soil_water_mm"),
        "field.initial_soil_water_mm",
        minimum=0,
    )
    initial_n = _number(
        soil_value("initial_mineral_n_kg_ha", "mineral_n_kg_ha"),
        "field.initial_mineral_n_kg_ha",
        minimum=0,
    )
    initial_p = _optional_number(soil_value("initial_available_p_kg_ha", "available_p_kg_ha"),
                                 "field.initial_available_p_kg_ha", minimum=0)
    initial_k = _optional_number(soil_value("initial_exchangeable_k_kg_ha", "exchangeable_k_kg_ha"),
                                 "field.initial_exchangeable_k_kg_ha", minimum=0)
    initial_om = _optional_number(soil_value("initial_organic_matter_percent", "organic_matter_percent"),
                                  "field.initial_organic_matter_percent", minimum=0)
    initial_ph = _optional_number(soil_value("initial_soil_ph", "ph"), "field.initial_soil_ph", minimum=0)
    if initial_om is not None and initial_om > 100:
        raise ValueError("field.initial_organic_matter_percent cannot exceed 100.")
    if initial_ph is not None and initial_ph > 14:
        raise ValueError("field.initial_soil_ph cannot exceed 14.")
    capacity_depth = _optional_number(field.get("soil_water_capacity_depth_m"),
                                      "field.soil_water_capacity_depth_m", minimum=0.000001)
    fallow_kc = _optional_number(field.get("fallow_kc"), "field.fallow_kc", minimum=0)
    if initial_water > capacity:
        raise ValueError("Initial soil water cannot exceed soil water capacity.")

    irrigation = field.get("irrigation")
    if irrigation is not None and not isinstance(irrigation, dict):
        raise ValueError("field.irrigation must be an object.")
    irrigation = irrigation or {}
    if irrigation:
        irrigation_source = irrigation.get("source")
        if not isinstance(irrigation_source, str) or not irrigation_source.strip():
            raise ValueError("field.irrigation.source is required.")
    else:
        irrigation_source = None
    trigger = _number(
        irrigation.get("trigger_fraction", field.get("irrigation_trigger_fraction", 0.5)),
        "field.irrigation_trigger_fraction",
        minimum=0,
    )
    if trigger > 1:
        raise ValueError("irrigation_trigger_fraction must be between 0 and 1.")
    irrigation_enabled = irrigation.get("enabled", field.get("irrigation_enabled", False))
    if not isinstance(irrigation_enabled, bool):
        raise ValueError("field.irrigation_enabled must be true or false.")
    irrigation_efficiency = _number(irrigation.get("application_efficiency", 1),
                                    "field.irrigation.application_efficiency", minimum=0.000001)
    if irrigation_efficiency > 1:
        raise ValueError("field.irrigation.application_efficiency must be between 0 and 1.")
    max_irrigation_mm = _optional_number(irrigation.get("max_withdrawal_mm"),
                                         "field.irrigation.max_withdrawal_mm", minimum=0)
    irrigation_cost_per_m3 = _number(irrigation.get("variable_cost_per_m3", 0),
                                     "field.irrigation.variable_cost_per_m3", minimum=0)
    irrigation_currency = irrigation.get("currency")
    if irrigation_cost_per_m3:
        if not isinstance(irrigation_currency, str) or len(irrigation_currency.strip()) != 3:
            raise ValueError("field.irrigation.currency must be supplied with irrigation cost.")
        irrigation_currency = irrigation_currency.strip().upper()
    raw_decisions = irrigation.get("decisions", [])
    if not isinstance(raw_decisions, list):
        raise ValueError("field.irrigation.decisions must be an array.")
    irrigation_decisions = {}
    for index, decision in enumerate(raw_decisions):
        if not isinstance(decision, dict):
            raise ValueError(f"field.irrigation.decisions[{index}] must be an object.")
        try:
            decision_day = date.fromisoformat(decision["date"]).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"field.irrigation.decisions[{index}].date must use YYYY-MM-DD.") from exc
        action = decision.get("action")
        if action not in {"accept", "skip", "replace"}:
            raise ValueError("Irrigation decision action must be accept, skip or replace.")
        source = decision.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Every irrigation decision requires source.")
        amount = decision.get("amount_mm")
        if action == "replace":
            amount = _number(amount, "irrigation decision amount_mm", minimum=0)
        elif amount is not None:
            raise ValueError("amount_mm is only valid for a replace irrigation decision.")
        crop_filter = decision.get("crop_id")
        if crop_filter is not None and (not isinstance(crop_filter, str) or not crop_filter):
            raise ValueError("Irrigation decision crop_id must be a non-empty string.")
        key = (decision_day, crop_filter)
        if key in irrigation_decisions:
            raise ValueError("Duplicate irrigation decision for the same date and crop.")
        irrigation_decisions[key] = {
            "action": action, "amount_mm": amount, "source": source.strip(),
            "note": decision.get("note"), "crop_id": crop_filter,
        }
    rotation_effect_catalog = config.get("rotation_effect_catalog", {})
    if not isinstance(rotation_effect_catalog, dict):
        raise ValueError("rotation_effect_catalog must be an object.")

    weather: dict[date, float] = {}
    weather_et0: dict[date, float | None] = {}
    for row_number, row in enumerate(weather_rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"weather row {row_number} must be an object.")
        try:
            day = date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"weather row {row_number} needs an ISO date.") from exc
        if day in weather:
            raise ValueError(f"Duplicate weather date: {day}.")
        weather[day] = _number(row.get("rain_mm"), f"rain_mm on {day}", minimum=0)
        raw_et0 = row.get("et0_mm")
        weather_et0[day] = (
            None if raw_et0 in (None, "")
            else _number(raw_et0, f"et0_mm on {day}", minimum=0)
        )

    results = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not scenario.get("crops"):
            raise ValueError("Each scenario needs a name and a non-empty crops list.")
        crop_sequence = scenario["crops"]
        if not isinstance(crop_sequence, list) or not all(isinstance(item, str) and item for item in crop_sequence):
            raise ValueError("Each scenario.crops value must be a non-empty crop ID array.")
        schedule_mode = scenario.get("schedule_mode", "fixed_gap")
        if schedule_mode not in {"fixed_gap", "next_planting_window"}:
            raise ValueError("scenario.schedule_mode must be fixed_gap or next_planting_window.")
        raw_gaps = scenario.get("gaps_after_crops_days", [0] * (len(crop_sequence) - 1))
        if not isinstance(raw_gaps, list) or len(raw_gaps) != len(crop_sequence) - 1:
            raise ValueError("scenario.gaps_after_crops_days must contain one value between each pair of crops.")
        gap_values = []
        for index, raw_gap in enumerate(raw_gaps):
            gap = _number(raw_gap, f"scenario.gaps_after_crops_days[{index}]", minimum=0)
            if not gap.is_integer():
                raise ValueError("scenario.gaps_after_crops_days values must be whole numbers.")
            gap_values.append(int(gap))
        try:
            earliest_start = date.fromisoformat(scenario.get("start_date", config.get("start_date", "")))
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario.start_date must use YYYY-MM-DD format.") from exc
        raw_horizon = scenario.get("planning_end_date")
        try:
            planning_end = None if raw_horizon is None else date.fromisoformat(raw_horizon)
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario.planning_end_date must use YYYY-MM-DD format.") from exc
        if planning_end is not None and planning_end < earliest_start:
            raise ValueError("scenario.planning_end_date cannot be before start_date.")

        water_mm = initial_water
        mineral_n = initial_n
        available_p = initial_p
        exchangeable_k = initial_k
        organic_matter = initial_om
        soil_ph = initial_ph
        sequence = []
        irrigation_events = []
        unmet_water_mm = 0.0
        total_rain_mm = 0.0
        missing_dates = []
        schedule_issues = []
        schedule_warnings = []
        every_crop_has_windows = True
        fallow_periods = []
        rotation_effects = []
        scenario_margin = 0.0
        scenario_gross_revenue = 0.0
        scenario_additional_income = 0.0
        scenario_crop_cost = 0.0
        scenario_currency = None
        economics_complete = True
        pest_score = 0.0
        pest_effects_complete = True
        total_nutrient_shortfall = 0.0
        scenario_irrigation_withdrawal = 0.0
        scenario_effective_irrigation = 0.0

        for crop_index, crop_name in enumerate(crop_sequence):
            if crop_name not in catalog:
                raise ValueError(f"Crop '{crop_name}' is missing from crop_catalog.")
            crop = catalog[crop_name]
            if not isinstance(crop, dict):
                raise ValueError(f"crop_catalog.{crop_name} must be an object.")
            gap_before = 0 if crop_index == 0 else gap_values[crop_index - 1]
            if crop_index > 0:
                earliest_start = sequence[-1]["_harvest_date"] + timedelta(days=gap_before + 1)
            windows = _planting_windows(crop, crop_name)
            if not windows:
                every_crop_has_windows = False
                schedule_warnings.append({
                    "code": "planting_window_not_provided",
                    "crop": crop_name,
                    "message": f"No local planting window was supplied for {crop_name}; its calendar fit is not fully evaluated.",
                })
            planting = _schedule_planting(earliest_start, windows, schedule_mode)
            crop_start = planting["date"]
            if planting["status"] == "outside_window":
                schedule_issues.append({
                    "code": "outside_planting_window",
                    "crop": crop_name,
                    "date": crop_start.isoformat(),
                    "message": f"{crop_name} would be planted outside every supplied local planting window.",
                })
            if crop_index > 0:
                fallow_start = sequence[-1]["_harvest_date"] + timedelta(days=1)
                fallow_days = max(0, (crop_start - fallow_start).days)
                fallow_rain = 0.0
                fallow_et = 0.0
                if fallow_days and fallow_kc is None:
                    schedule_warnings.append({
                        "code": "fallow_water_balance_not_configured",
                        "crop": crop_name,
                        "days": fallow_days,
                        "message": "Set field.fallow_kc to simulate rainfall and evaporation between crops.",
                    })
                if fallow_days and fallow_kc is not None:
                    for offset in range(fallow_days):
                        day = fallow_start + timedelta(days=offset)
                        if day not in weather:
                            missing_dates.append(day.isoformat())
                            continue
                        rain = weather[day]
                        et0 = weather_et0[day]
                        if et0 is None:
                            raise ValueError(f"ET0 is missing on {day} during a fallow period.")
                        water_mm = min(capacity, water_mm + rain)
                        evaporation = min(water_mm, et0 * fallow_kc)
                        water_mm -= evaporation
                        fallow_rain += rain
                        fallow_et += evaporation
                fallow_periods.append({
                    "after_crop": crop_sequence[crop_index - 1],
                    "before_crop": crop_name,
                    "start_date": fallow_start.isoformat(),
                    "end_date": (crop_start - timedelta(days=1)).isoformat() if fallow_days else None,
                    "days": fallow_days,
                    "configured_gap_days": gap_before,
                    "calendar_wait_days": planting["calendar_wait_days"],
                    "water_balance_status": "modeled" if fallow_kc is not None else "not_configured",
                    "rain_mm": round(fallow_rain, 2) if fallow_kc is not None else None,
                    "evapotranspiration_mm": round(fallow_et, 2) if fallow_kc is not None else None,
                })

                transition_key = f"{crop_sequence[crop_index - 1]}->{crop_name}"
                effect = rotation_effect_catalog.get(transition_key)
                if effect is None:
                    pest_effects_complete = False
                    rotation_effects.append({"transition": transition_key, "status": "not_evaluated"})
                else:
                    if not isinstance(effect, dict):
                        raise ValueError(f"rotation_effect_catalog.{transition_key} must be an object.")
                    source = effect.get("source")
                    if not isinstance(source, str) or not source.strip():
                        raise ValueError(f"rotation_effect_catalog.{transition_key}.source is required.")
                    score = _number(effect.get("pest_disease_break_score"),
                                    f"rotation_effect_catalog.{transition_key}.pest_disease_break_score")
                    if not -2 <= score <= 2:
                        raise ValueError("pest_disease_break_score must be between -2 and 2.")
                    pest_score += score
                    rotation_effects.append({"transition": transition_key, "status": "evaluated",
                                             "pest_disease_break_score": score,
                                             "source": source.strip(), "note": effect.get("note")})
            variety = crop.get("variety")
            if variety is not None and not isinstance(variety, dict):
                raise ValueError(f"{crop_name}.variety must be an object.")
            if variety is not None:
                for required in ("name", "maturity_days", "source"):
                    if variety.get(required) in (None, ""):
                        raise ValueError(f"{crop_name}.variety.{required} is required.")
            water_model_warning = crop.get("water_model_warning")
            if water_model_warning:
                schedule_warnings.append({
                    "code": "water_model_limitation", "crop": crop_name,
                    "message": str(water_model_warning),
                })
            duration_input = crop.get("duration_days")
            if duration_input is None and variety is not None:
                duration_input = variety.get("maturity_days")
            duration_value = _number(duration_input, f"{crop_name}.duration_days", minimum=1)
            if not duration_value.is_integer():
                raise ValueError(f"{crop_name}.duration_days must be a whole number.")
            duration = int(duration_value)
            stage_kc = crop.get("stage_kc")
            stage_days = crop.get("stage_days")
            dual_config = None
            if crop.get("water_model") is not None:
                dual_config = validate_dual_config(crop["water_model"])
            if stage_kc is not None or stage_days is not None or dual_config is not None:
                if dual_config is None and (not isinstance(stage_kc, list) or len(stage_kc) != 4):
                    raise ValueError(f"{crop_name}.stage_kc must contain four FAO stage values.")
                if not isinstance(stage_days, list) or len(stage_days) != 4:
                    raise ValueError(f"{crop_name}.stage_days must contain four whole-day lengths.")
                if stage_kc is not None:
                    if not isinstance(stage_kc, list) or len(stage_kc) != 4:
                        raise ValueError(f"{crop_name}.stage_kc must contain four FAO stage values.")
                    stage_kc = [
                        _number(value, f"{crop_name}.stage_kc", minimum=0)
                        for value in stage_kc
                    ]
                stage_days_numeric = [
                    _number(value, f"{crop_name}.stage_days", minimum=1)
                    for value in stage_days
                ]
                if any(not value.is_integer() for value in stage_days_numeric):
                    raise ValueError(f"{crop_name}.stage_days values must be whole numbers.")
                stage_days = [int(value) for value in stage_days_numeric]
                if sum(stage_days) != duration:
                    raise ValueError(f"{crop_name} stage_days must sum to duration_days.")
                total_need = None
            else:
                total_need = _number(crop.get("water_need_mm"), f"{crop_name}.water_need_mm", minimum=0)
            n_change, n_budget = _nutrient_change(crop, crop_name, "n")
            p_change, p_budget = _nutrient_change(crop, crop_name, "p")
            k_change, k_budget = _nutrient_change(crop, crop_name, "k")
            if p_budget is not None and available_p is None:
                raise ValueError("field.initial_available_p_kg_ha is required for a P budget.")
            if k_budget is not None and exchangeable_k is None:
                raise ValueError("field.initial_exchangeable_k_kg_ha is required for a K budget.")
            root_depth = _optional_number(crop.get("root_depth_m"), f"{crop_name}.root_depth_m", minimum=0.000001)
            if root_depth is not None and capacity_depth is None:
                raise ValueError("field.soil_water_capacity_depth_m is required when a crop has root_depth_m.")
            effective_capacity = capacity
            if root_depth is not None:
                effective_capacity = capacity * min(root_depth / capacity_depth, 1.0)
            profile_fraction = 0.0 if capacity == 0 else water_mm / capacity
            accessible_water = min(effective_capacity, profile_fraction * effective_capacity)
            inaccessible_water = max(0.0, water_mm - accessible_water)
            water_mm = accessible_water
            crop_end = crop_start + timedelta(days=duration - 1)
            if planning_end is not None and crop_end > planning_end:
                schedule_issues.append({
                    "code": "planning_horizon_exceeded",
                    "crop": crop_name,
                    "planned_harvest_date": crop_end.isoformat(),
                    "planning_end_date": planning_end.isoformat(),
                    "days_over": (crop_end - planning_end).days,
                    "message": f"{crop_name} harvest falls after the supplied planning horizon.",
                })
            crop_water_start = water_mm
            crop_rain = 0.0
            crop_irrigation = 0.0
            crop_effective_irrigation = 0.0
            crop_unmet = 0.0
            crop_need_total = 0.0
            surface_depletion = (
                float(dual_config["initial_surface_depletion_mm"])
                if dual_config is not None else None
            )
            dual_totals = {"kcb": 0.0, "ks": 0.0, "ke": 0.0, "stress_days": 0}

            for day_index in range(duration):
                day = crop_start + timedelta(days=day_index)
                if day not in weather:
                    missing_dates.append(day.isoformat())
                    continue

                rain = weather[day]
                et0 = weather_et0[day]
                crop_rain += rain
                total_rain_mm += rain
                water_mm = min(effective_capacity, water_mm + rain)
                if surface_depletion is not None:
                    surface_depletion = max(0.0, surface_depletion - rain)

                threshold = effective_capacity * (1 - trigger)
                recommended_withdrawal = 0.0
                if irrigation_enabled and water_mm < threshold:
                    effective_needed = threshold - water_mm
                    recommended_withdrawal = effective_needed / irrigation_efficiency
                decision = irrigation_decisions.get((day.isoformat(), crop_name))
                if decision is None:
                    decision = irrigation_decisions.get((day.isoformat(), None))
                if decision is None or decision["action"] == "accept":
                    withdrawal = recommended_withdrawal
                    decision_action = "automatic" if decision is None else "accepted"
                elif decision["action"] == "skip":
                    withdrawal = 0.0
                    decision_action = "skipped"
                else:
                    withdrawal = decision["amount_mm"]
                    decision_action = "replaced"
                if max_irrigation_mm is not None:
                    withdrawal = min(withdrawal, max(0.0, max_irrigation_mm - scenario_irrigation_withdrawal))
                if withdrawal or recommended_withdrawal or decision is not None:
                    effective_amount = withdrawal * irrigation_efficiency
                    water_mm = min(effective_capacity, water_mm + effective_amount)
                    if surface_depletion is not None:
                        surface_depletion = max(0.0, surface_depletion - effective_amount)
                    crop_irrigation += withdrawal
                    crop_effective_irrigation += effective_amount
                    scenario_irrigation_withdrawal += withdrawal
                    scenario_effective_irrigation += effective_amount
                    irrigation_events.append({
                        "date": day.isoformat(),
                        "recommended_withdrawal_mm": round(recommended_withdrawal, 2),
                        "decision": decision_action,
                        "decision_source": None if decision is None else decision["source"],
                        "decision_note": None if decision is None else decision["note"],
                        "amount_mm": round(withdrawal, 2),
                        "withdrawal_mm": round(withdrawal, 2),
                        "effective_amount_mm": round(effective_amount, 2),
                        "application_efficiency": irrigation_efficiency,
                        "amount_m3_for_field": round(withdrawal * area_ha * 10, 2),
                        "crop": crop_name,
                    })

                if dual_config is not None:
                    if et0 is None:
                        raise ValueError(f"ET0 is missing on {day} for crop '{crop_name}'.")
                    dual_day = dual_coefficient_day(
                        et0_mm=et0, water_mm=water_mm, capacity_mm=effective_capacity,
                        surface_depletion_mm=surface_depletion, day_index=day_index,
                        stage_days=stage_days, config=dual_config,
                    )
                    daily_need = dual_day["crop_water_need_mm"]
                    surface_depletion = min(
                        float(dual_config["total_evaporable_water_mm"]),
                        surface_depletion + dual_day["soil_evaporation_mm"],
                    )
                    for key in ("kcb", "ks", "ke"):
                        dual_totals[key] += dual_day[key]
                    if dual_day["ks"] < 0.999:
                        dual_totals["stress_days"] += 1
                elif total_need is not None:
                    daily_need = total_need / duration
                else:
                    if et0 is None:
                        raise ValueError(
                            f"ET0 is missing on {day} for crop '{crop_name}'."
                        )
                    day_in_crop = day_index
                    stage_start = 0
                    stage_index = 0
                    for index, stage_length in enumerate(stage_days):
                        if day_in_crop < stage_start + stage_length:
                            stage_index = index
                            break
                        stage_start += stage_length
                    daily_kc = stage_kc[stage_index]
                    daily_need = et0 * daily_kc
                crop_need_total += daily_need
                supplied = min(water_mm, daily_need)
                water_mm -= supplied
                crop_unmet += daily_need - supplied
                unmet_water_mm += daily_need - supplied

            crop_water_end = water_mm
            water_mm = min(capacity, inaccessible_water + crop_water_end)

            n_before = mineral_n
            projected_n = mineral_n + n_change
            n_shortfall = max(0.0, -projected_n)
            mineral_n = max(0.0, projected_n)
            p_before = available_p
            p_shortfall = None
            if available_p is not None:
                projected_p = available_p + p_change
                p_shortfall = max(0.0, -projected_p)
                available_p = max(0.0, projected_p)
            k_before = exchangeable_k
            k_shortfall = None
            if exchangeable_k is not None:
                projected_k = exchangeable_k + k_change
                k_shortfall = max(0.0, -projected_k)
                exchangeable_k = max(0.0, projected_k)
            total_nutrient_shortfall += n_shortfall + (p_shortfall or 0) + (k_shortfall or 0)

            soil_effects = crop.get("soil_effects")
            soil_effect_result = None
            if soil_effects is not None:
                if not isinstance(soil_effects, dict):
                    raise ValueError(f"{crop_name}.soil_effects must be an object.")
                source = soil_effects.get("source")
                if not isinstance(source, str) or not source.strip():
                    raise ValueError(f"{crop_name}.soil_effects.source is required.")
                om_change = _number(soil_effects.get("organic_matter_change_percentage_points", 0),
                                    f"{crop_name}.organic_matter_change_percentage_points")
                ph_change = _number(soil_effects.get("ph_change", 0), f"{crop_name}.ph_change")
                if om_change and organic_matter is None:
                    raise ValueError("field.initial_organic_matter_percent is required for organic-matter effects.")
                if ph_change and soil_ph is None:
                    raise ValueError("field.initial_soil_ph is required for pH effects.")
                om_before = organic_matter
                ph_before = soil_ph
                if organic_matter is not None:
                    organic_matter += om_change
                    if not 0 <= organic_matter <= 100:
                        raise ValueError("Modeled organic matter must remain between 0 and 100 percent.")
                if soil_ph is not None:
                    soil_ph += ph_change
                    if not 0 <= soil_ph <= 14:
                        raise ValueError("Modeled soil pH must remain between 0 and 14.")
                soil_effect_result = {
                    "organic_matter_start_percent": om_before,
                    "organic_matter_change_percentage_points": om_change,
                    "organic_matter_end_percent": organic_matter,
                    "soil_ph_start": ph_before,
                    "ph_change": ph_change,
                    "soil_ph_end": soil_ph,
                    "source": source.strip(),
                    "note": soil_effects.get("note"),
                }

            economics = _economics(crop, crop_name, area_ha)
            if economics is None:
                economics_complete = False
            else:
                if scenario_currency is not None and scenario_currency != economics["currency"]:
                    raise ValueError("All crop economics in one scenario must use the same currency.")
                scenario_currency = economics["currency"]
                scenario_margin += economics["estimated_margin_for_field"]
                scenario_gross_revenue += economics["gross_revenue_for_field"]
                scenario_additional_income += economics["additional_income_for_field"]
                scenario_crop_cost += economics["total_crop_cost_for_field"]

            sequence.append({
                "crop": crop_name,
                "earliest_planting_date": earliest_start.isoformat(),
                "planting_date": crop_start.isoformat(),
                "planned_harvest_date": crop_end.isoformat(),
                "gap_before_days": gap_before,
                "calendar_wait_before_days": planting["calendar_wait_days"],
                "planting_window_status": planting["status"],
                "matched_planting_window": planting["matched_window"],
                "duration_days": duration,
                "rain_mm": round(crop_rain, 2),
                "irrigation_mm": round(crop_irrigation, 2),
                "effective_irrigation_mm": round(crop_effective_irrigation, 2),
                "crop_water_need_mm": round(crop_need_total, 2),
                "root_depth_m": root_depth,
                "effective_root_zone_capacity_mm": round(effective_capacity, 2),
                "irrigation_m3_for_field": round(crop_irrigation * area_ha * 10, 2),
                "unmet_water_mm": round(crop_unmet, 2),
                "soil_water_start_mm": round(crop_water_start, 2),
                "soil_water_end_mm": round(crop_water_end, 2),
                "profile_equivalent_soil_water_end_mm": round(water_mm, 2),
                "mineral_n_start_kg_ha": round(n_before, 2),
                "net_soil_n_change_kg_ha": round(n_change, 2),
                "estimated_mineral_n_end_kg_ha": round(mineral_n, 2),
                "estimated_n_shortfall_kg_ha": round(n_shortfall, 2),
                "mineral_n_start_kg_for_field": round(n_before * area_ha, 2),
                "net_soil_n_change_kg_for_field": round(n_change * area_ha, 2),
                "estimated_mineral_n_end_kg_for_field": round(mineral_n * area_ha, 2),
                "estimated_n_shortfall_kg_for_field": round(n_shortfall * area_ha, 2),
                "available_p_start_kg_ha": None if p_before is None else round(p_before, 2),
                "net_available_p_change_kg_ha": None if p_before is None else round(p_change, 2),
                "estimated_available_p_end_kg_ha": None if available_p is None else round(available_p, 2),
                "estimated_p_shortfall_kg_ha": None if p_shortfall is None else round(p_shortfall, 2),
                "exchangeable_k_start_kg_ha": None if k_before is None else round(k_before, 2),
                "net_exchangeable_k_change_kg_ha": None if k_before is None else round(k_change, 2),
                "estimated_exchangeable_k_end_kg_ha": None if exchangeable_k is None else round(exchangeable_k, 2),
                "estimated_k_shortfall_kg_ha": None if k_shortfall is None else round(k_shortfall, 2),
                "nutrient_budget": {"n": n_budget, "p": p_budget, "k": k_budget},
                "soil_effects": soil_effect_result,
                "water_model": (
                    None if dual_config is None else {
                        "method": "fao56_dual",
                        "average_kcb": round(dual_totals["kcb"] / duration, 4),
                        "average_stress_coefficient_ks": round(dual_totals["ks"] / duration, 4),
                        "average_soil_evaporation_coefficient_ke": round(dual_totals["ke"] / duration, 4),
                        "water_stress_days": dual_totals["stress_days"],
                        "final_surface_depletion_mm": round(surface_depletion, 3),
                        "source": dual_config["source"],
                        "source_url": dual_config["source_url"],
                    }
                ),
                "water_model_warning": water_model_warning,
                "economics": economics,
                "input_provenance": {
                    key: crop.get(key)
                    for key in (
                        "profile_id", "profile_version", "calendar_id",
                        "water_profile_source_id", "nitrogen_assumption_source",
                        "nitrogen_assumption_note",
                    )
                    if crop.get(key) is not None
                },
                "variety": variety,
                "_harvest_date": crop_end,
            })

        if missing_dates:
            missing_list = ", ".join(sorted(set(missing_dates)))
            raise ValueError(
                f"Scenario '{scenario.get('name', 'Unnamed scenario')}' has no rainfall data for: {missing_list}. "
                "Supply complete daily coverage; missing rainfall is never treated as zero."
            )

        total_irrigation_mm = sum(item["irrigation_mm"] for item in sequence)
        total_irrigation_m3 = total_irrigation_mm * area_ha * 10
        irrigation_cost = total_irrigation_m3 * irrigation_cost_per_m3
        first_planting = date.fromisoformat(sequence[0]["planting_date"])
        last_harvest = sequence[-1]["_harvest_date"]
        for item in sequence:
            item.pop("_harvest_date", None)
        if schedule_issues:
            calendar_status = "infeasible"
            calendar_feasible = False
        elif not every_crop_has_windows or planning_end is None:
            calendar_status = "not_fully_evaluated"
            calendar_feasible = None
        else:
            calendar_status = "feasible"
            calendar_feasible = True
        if economics_complete and irrigation_cost:
            if scenario_currency != irrigation_currency:
                raise ValueError("Irrigation cost currency must match crop economics currency.")
            scenario_margin -= irrigation_cost
        estimated_margin = round(scenario_margin, 2) if economics_complete else None
        total_scenario_cost = scenario_crop_cost + irrigation_cost
        scenario_roi = (None if not economics_complete or total_scenario_cost == 0
                        else scenario_margin / total_scenario_cost * 100)
        evaluated_pest_score = round(pest_score, 2) if pest_effects_complete else None
        results.append({
            "name": scenario.get("name", "Unnamed scenario"),
            "sequence": sequence,
            "schedule_mode": schedule_mode,
            "planning_end_date": planning_end.isoformat() if planning_end else None,
            "calendar_status": calendar_status,
            "calendar_feasible": calendar_feasible,
            "schedule_issues": schedule_issues,
            "schedule_warnings": schedule_warnings,
            "rotation_span_days": (last_harvest - first_planting).days + 1,
            "total_configured_gap_days": sum(gap_values),
            "total_calendar_wait_days": sum(item["calendar_wait_before_days"] for item in sequence),
            "fallow_periods": fallow_periods,
            "rotation_effects": rotation_effects,
            "pest_disease_rotation_score": evaluated_pest_score,
            "total_rain_mm": round(total_rain_mm, 2),
            "total_irrigation_mm": round(total_irrigation_mm, 2),
            "total_effective_irrigation_mm": round(scenario_effective_irrigation, 2),
            "total_irrigation_m3_for_field": round(total_irrigation_m3, 2),
            "irrigation_limit_mm": max_irrigation_mm,
            "irrigation_cost_for_field": round(irrigation_cost, 2),
            "total_unmet_water_mm": round(unmet_water_mm, 2),
            "estimated_final_mineral_n_kg_ha": round(mineral_n, 2),
            "estimated_final_mineral_n_kg_for_field": round(mineral_n * area_ha, 2),
            "estimated_final_available_p_kg_ha": None if available_p is None else round(available_p, 2),
            "estimated_final_exchangeable_k_kg_ha": None if exchangeable_k is None else round(exchangeable_k, 2),
            "estimated_final_organic_matter_percent": None if organic_matter is None else round(organic_matter, 4),
            "estimated_final_soil_ph": None if soil_ph is None else round(soil_ph, 4),
            "total_nutrient_shortfall_kg_ha": round(total_nutrient_shortfall, 2),
            "estimated_total_margin_for_field": estimated_margin,
            "economics_currency": scenario_currency if economics_complete else None,
            "economics_status": "complete" if economics_complete else "not_fully_evaluated",
            "economics_summary": {
                "status": "complete" if economics_complete else "not_fully_evaluated",
                "field_area_ha": area_ha,
                "gross_crop_revenue_for_field": round(scenario_gross_revenue, 2),
                "additional_income_for_field": round(scenario_additional_income, 2),
                "crop_costs_for_field": round(scenario_crop_cost, 2),
                "irrigation_cost_for_field": round(irrigation_cost, 2),
                "total_cost_for_field": round(total_scenario_cost, 2),
                "net_margin_for_field": estimated_margin,
                "net_margin_per_ha": None if estimated_margin is None else round(estimated_margin / area_ha, 2),
                "return_on_cost_percent": None if scenario_roi is None else round(scenario_roi, 2),
                "currency": scenario_currency if economics_complete else None,
            },
            "irrigation_events": irrigation_events,
        })

    ranking = _rank_scenarios(results, config.get("ranking"))
    return {
        "title": config.get("title", "Crop sequence comparison"),
        "field": {
            "name": field.get("name", "Unnamed field"),
            "area_ha": area_ha,
            "initial_soil_water_mm": initial_water,
            "soil_water_capacity_mm": capacity,
            "soil_water_capacity_depth_m": capacity_depth,
            "initial_mineral_n_kg_ha": initial_n,
            "initial_available_p_kg_ha": initial_p,
            "initial_exchangeable_k_kg_ha": initial_k,
            "initial_organic_matter_percent": initial_om,
            "initial_soil_ph": initial_ph,
            "fallow_kc": fallow_kc,
            "irrigation": {
                "enabled": irrigation_enabled,
                "trigger_fraction": trigger,
                "application_efficiency": irrigation_efficiency,
                "max_withdrawal_mm": max_irrigation_mm,
                "variable_cost_per_m3": irrigation_cost_per_m3,
                "currency": irrigation_currency,
                "source": irrigation_source,
                "farmer_decisions_supplied": len(raw_decisions),
            },
            "soil_test": soil_test or None,
            "management": management,
        },
        "scenarios": results,
        "comparison": {"ranking": ranking},
        "input_assessment": _input_assessment(config),
        "assumptions_and_limits": [
            "This is a transparent planning calculator, not a validated crop-growth or yield model.",
            "Rainfall is treated as effective infiltration up to the active root-zone capacity; runoff and drainage are not modeled.",
            "Root-depth scaling assumes uniform soil-water fraction through the supplied profile depth; it is not a layered soil simulation.",
            "Crop water, nutrient, soil-effect and economic values are explicit sourced/user assumptions; they are not inferred from crop names.",
            "When stage_kc and stage_days are supplied, daily crop water demand is estimated as supplied ET0 multiplied by the user-supplied coefficient for that growth stage.",
            "Detailed N/P/K budgets separately represent fertilizer, residue release, crop uptake from soil and other losses; biological N fixation is reported separately and is not automatically credited to the soil mineral-N pool.",
            "When supplied, irrigation application efficiency, seasonal withdrawal limit and variable water cost are included; equipment flow-rate and local regulations remain caller responsibilities.",
            "Rotation gaps and planting windows are scenario inputs. next_planting_window moves planting to the earliest supplied recurring window; fixed_gap reports an out-of-window issue without moving the date.",
            "When fallow_kc is supplied, rainfall and ET0-based evaporation are simulated during uncropped gaps; otherwise gap water balance is explicitly not evaluated.",
            "Yield, price and cost are caller-supplied baselines and are not adjusted for modeled stress.",
            "Pest/disease transition scores and soil pH/organic-matter changes require a named source and are not universal crop constants.",
            "Ranking uses caller-selected weights, excludes calendar-infeasible or incomplete scenarios, and is decision support—not an agronomic recommendation.",
            "A scenario is only marked calendar-feasible when every crop has a planting window, a planning_end_date is supplied, and no window or horizon issue is found.",
            "Complete daily rainfall coverage is required; missing rainfall dates cause the scenario to stop rather than being treated as zero rainfall.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare crop sequences with an explicit soil-water and mineral-nitrogen budget."
    )
    parser.add_argument("scenario", type=Path, help="Path to a scenario JSON file.")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON report.")
    parser.add_argument(
        "--weather-csv",
        type=Path,
        help="Optional CSV with date, rain_mm, et0_mm; overrides weather in the scenario file.",
    )
    args = parser.parse_args()

    try:
        config = _read_scenario(args.scenario)
        if args.weather_csv:
            with args.weather_csv.open(newline="", encoding="utf-8") as stream:
                config["weather"] = list(csv.DictReader(stream))
        report = simulate_scenarios(config)
        if args.weather_csv:
            sidecar = args.weather_csv.with_suffix(".metadata.json")
            if sidecar.exists():
                report["weather_metadata"] = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.error(str(exc))

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Report saved to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
