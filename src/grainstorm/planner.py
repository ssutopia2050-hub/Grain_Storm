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


def _nutrient_change(crop: dict[str, Any], crop_name: str, nutrient: str) -> tuple[float | None, dict[str, float] | None]:
    budget = crop.get("nutrient_budget")
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
    cost = _number(raw.get("variable_cost_per_ha"), f"{crop_name}.variable_cost_per_ha", minimum=0)
    gross_ha = yield_t_ha * price
    return {
        "expected_yield_t_ha": yield_t_ha,
        "price_per_tonne": price,
        "variable_cost_per_ha": cost,
        "gross_revenue_per_ha": round(gross_ha, 2),
        "estimated_margin_per_ha": round(gross_ha - cost, 2),
        "expected_production_t_for_field": round(yield_t_ha * area_ha, 2),
        "estimated_margin_for_field": round((gross_ha - cost) * area_ha, 2),
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
        field.get("initial_mineral_n_kg_ha"),
        "field.initial_mineral_n_kg_ha",
        minimum=0,
    )
    initial_p = _optional_number(field.get("initial_available_p_kg_ha"),
                                 "field.initial_available_p_kg_ha", minimum=0)
    initial_k = _optional_number(field.get("initial_exchangeable_k_kg_ha"),
                                 "field.initial_exchangeable_k_kg_ha", minimum=0)
    initial_om = _optional_number(field.get("initial_organic_matter_percent"),
                                  "field.initial_organic_matter_percent", minimum=0)
    initial_ph = _optional_number(field.get("initial_soil_ph"), "field.initial_soil_ph", minimum=0)
    if initial_om is not None and initial_om > 100:
        raise ValueError("field.initial_organic_matter_percent cannot exceed 100.")
    if initial_ph is not None and initial_ph > 14:
        raise ValueError("field.initial_soil_ph cannot exceed 14.")
    capacity_depth = _optional_number(field.get("soil_water_capacity_depth_m"),
                                      "field.soil_water_capacity_depth_m", minimum=0.000001)
    fallow_kc = _optional_number(field.get("fallow_kc"), "field.fallow_kc", minimum=0)
    if initial_water > capacity:
        raise ValueError("Initial soil water cannot exceed soil water capacity.")

    trigger = _number(
        field.get("irrigation_trigger_fraction", 0.5),
        "field.irrigation_trigger_fraction",
        minimum=0,
    )
    if trigger > 1:
        raise ValueError("irrigation_trigger_fraction must be between 0 and 1.")
    irrigation_enabled = field.get("irrigation_enabled", False)
    if not isinstance(irrigation_enabled, bool):
        raise ValueError("field.irrigation_enabled must be true or false.")
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
        scenario_currency = None
        economics_complete = True
        pest_score = 0.0
        pest_effects_complete = True
        total_nutrient_shortfall = 0.0

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
            duration_value = _number(crop.get("duration_days"), f"{crop_name}.duration_days", minimum=1)
            if not duration_value.is_integer():
                raise ValueError(f"{crop_name}.duration_days must be a whole number.")
            duration = int(duration_value)
            stage_kc = crop.get("stage_kc")
            stage_days = crop.get("stage_days")
            if stage_kc is not None or stage_days is not None:
                if not isinstance(stage_kc, list) or len(stage_kc) != 4:
                    raise ValueError(f"{crop_name}.stage_kc must contain four FAO stage values.")
                if not isinstance(stage_days, list) or len(stage_days) != 4:
                    raise ValueError(f"{crop_name}.stage_days must contain four whole-day lengths.")
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
            crop_unmet = 0.0
            crop_need_total = 0.0

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

                threshold = effective_capacity * (1 - trigger)
                if irrigation_enabled and water_mm < threshold:
                    amount = threshold - water_mm
                    water_mm += amount
                    crop_irrigation += amount
                    irrigation_events.append({
                        "date": day.isoformat(),
                        "amount_mm": round(amount, 2),
                        "amount_m3_for_field": round(amount * area_ha * 10, 2),
                        "crop": crop_name,
                    })

                if total_need is not None:
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
                "_harvest_date": crop_end,
            })

        if missing_dates:
            missing_list = ", ".join(sorted(set(missing_dates)))
            raise ValueError(
                f"Scenario '{scenario.get('name', 'Unnamed scenario')}' has no rainfall data for: {missing_list}. "
                "Supply complete daily coverage; missing rainfall is never treated as zero."
            )

        total_irrigation_mm = sum(item["irrigation_mm"] for item in sequence)
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
        estimated_margin = round(scenario_margin, 2) if economics_complete else None
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
            "total_irrigation_m3_for_field": round(total_irrigation_mm * area_ha * 10, 2),
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
        },
        "scenarios": results,
        "comparison": {"ranking": ranking},
        "assumptions_and_limits": [
            "This is a transparent planning calculator, not a validated crop-growth or yield model.",
            "Rainfall is treated as effective infiltration up to the active root-zone capacity; runoff and drainage are not modeled.",
            "Root-depth scaling assumes uniform soil-water fraction through the supplied profile depth; it is not a layered soil simulation.",
            "Crop water, nutrient, soil-effect and economic values are explicit sourced/user assumptions; they are not inferred from crop names.",
            "When stage_kc and stage_days are supplied, daily crop water demand is estimated as supplied ET0 multiplied by the user-supplied coefficient for that growth stage.",
            "Detailed N/P/K budgets separately represent fertilizer, residue release, crop uptake from soil and other losses; biological N fixation is reported separately and is not automatically credited to the soil mineral-N pool.",
            "Irrigation quantities are planning estimates; they do not account for delivery efficiency, equipment limits, or local regulations.",
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
