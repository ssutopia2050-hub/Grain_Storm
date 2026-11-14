"""One-call orchestration for the farmer-facing crop-rotation workflow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from itertools import permutations
from typing import Any

from grainstorm.context import ContextService
from grainstorm.crops import get_profile
from grainstorm.geometry import polygon_summary
from grainstorm.planner import simulate_scenarios, _rank_scenarios
from grainstorm.processing.planner_weather import merge_imerg_weather
from grainstorm.sources.gaez import fetch_location_suitability
from grainstorm.sources.gaez_calendar import fetch_location_crop_calendars
from grainstorm.sources.gaez_yield import fetch_location_yield_baselines
from grainstorm.sources.ssurgo import fetch_us_soil_context
from grainstorm.sources.forecast import fetch_daily_forecast, MAX_FORECAST_DAYS
from grainstorm.input_resolver import resolve_rotation_inputs


def _scaled_stages(stage_days: list[int], duration: int) -> list[int]:
    raw = [duration * value / sum(stage_days) for value in stage_days]
    result = [max(1, int(value)) for value in raw]
    while sum(result) < duration:
        index = max(range(4), key=lambda i: raw[i] - result[i])
        result[index] += 1
    while sum(result) > duration:
        index = max((i for i in range(4) if result[i] > 1), key=lambda i: result[i] - raw[i])
        result[index] -= 1
    return result


def _source_bundle(latitude: float, longitude: float, crop_ids: list[str], year: int) -> dict[str, Any]:
    calls = {
        "suitability": lambda: fetch_location_suitability(latitude, longitude, crop_ids),
        "calendar": lambda: fetch_location_crop_calendars(latitude, longitude, crop_ids, year),
        "yield_baseline": lambda: fetch_location_yield_baselines(latitude, longitude, crop_ids),
        "soil": lambda: fetch_us_soil_context(latitude, longitude),
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {name: executor.submit(call) for name, call in calls.items()}
        return {name: future.result() for name, future in futures.items()}


def _crop_catalog(crop_ids: list[str], bundle: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    calendars = {row["crop_id"]: row for row in bundle["calendar"]["crops"]}
    catalog = {}
    for crop_id in crop_ids:
        profile = get_profile(crop_id)
        calendar = calendars[crop_id]
        duration = int(calendar["cycle_length_days"])
        reference = profile["growing_period"]["reference_calendars"][0]
        crop = {
            "duration_days": duration,
            "stage_kc": profile["water"]["stage_kc"],
            "stage_days": _scaled_stages(reference["stage_days"], duration),
            "root_depth_m": calendar["reference_root_depth_m"],
            "profile_id": crop_id,
            "profile_version": profile["profile_version"],
            "calendar_id": "gaez_location_cycle",
            "water_profile_source_id": "fao_crop_water_needs",
        }
        if crop_id == "rice":
            crop["water_model_warning"] = (
                "Paddy irrigation is incomplete: the calculator estimates ET demand but does not model "
                "puddling, standing water, seepage, percolation, or intentional drainage."
            )
        supplied = overrides.get(crop_id, {})
        if not isinstance(supplied, dict):
            raise ValueError(f"crop_inputs.{crop_id} must be an object.")
        crop.update(supplied)
        if isinstance(supplied.get("variety"), dict) and supplied["variety"].get("maturity_days") is not None:
            crop["duration_days"] = supplied["variety"]["maturity_days"]
            crop["stage_days"] = _scaled_stages(reference["stage_days"], int(crop["duration_days"]))
        catalog[crop_id] = crop
    return catalog


def _requirements(data: dict[str, Any], unique_crops: list[str], environment_ready: bool) -> list[dict[str, str]]:
    field_inputs = data.get("field_inputs") or {}
    missing: list[dict[str, str]] = []
    for key, reason in (
        ("soil_water_capacity_mm", "Needed for the field water balance."),
        ("soil_water_capacity_depth_m", "Needed to scale water by crop rooting depth."),
        ("initial_soil_water_mm", "A sensor, field estimate or explicitly accepted model value is required."),
    ):
        if field_inputs.get(key) is None:
            missing.append({"path": f"field_inputs.{key}", "reason": reason})
    soil_test = data.get("soil_test")
    if not isinstance(soil_test, dict) or soil_test.get("mineral_n_kg_ha") is None:
        missing.append({"path": "soil_test.mineral_n_kg_ha",
                        "reason": "Current mineral nitrogen cannot be inferred from satellite data."})
    if len(data["crop_sequence"]) > 1 and data.get("gaps_after_crops_days") is None:
        missing.append({"path": "gaps_after_crops_days",
                        "reason": "The backend will not invent harvest-to-planting turnaround time."})
    for crop_id in unique_crops:
        crop = (data.get("crop_inputs") or {}).get(crop_id, {})
        if not crop.get("planting_windows"):
            missing.append({"path": f"crop_inputs.{crop_id}.planting_windows",
                            "reason": "GAEZ supplies a coarse anchor, not a validated local planting window."})
        if not crop.get("agronomy") and not crop.get("nutrient_budget"):
            missing.append({"path": f"crop_inputs.{crop_id}.agronomy",
                            "reason": "Required for N/P/K removal, fertilizer, residue and loss calculations."})
        if not crop.get("economics"):
            missing.append({"path": f"crop_inputs.{crop_id}.economics",
                            "reason": "Yield, price and local production cost are required for margin."})
    if not environment_ready:
        missing.append({"path": "environmental_context",
                        "reason": "Complete historical weather, a bounded operational forecast, or an exact daily weather_scenario is required."})
    return missing


def _weather_scenario(rows: Any, start: date, end: date) -> tuple[list[dict[str, float | str]], dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("weather_scenario must be a non-empty daily array.")
    indexed: dict[str, dict[str, float | str]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"weather_scenario[{index}] must be an object.")
        try:
            raw_day = row["date"]
            day = date.fromisoformat(raw_day).isoformat()
            rain = float(row["rain_mm"])
            et0 = float(row["et0_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"weather_scenario[{index}] requires date, rain_mm and et0_mm.") from exc
        if raw_day != day or rain < 0 or et0 < 0 or day in indexed:
            raise ValueError("weather_scenario dates must be unique ISO dates with nonnegative values.")
        indexed[day] = {"date": day, "rain_mm": rain, "et0_mm": et0}
    expected = [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]
    missing = [day for day in expected if day not in indexed]
    extra = sorted(set(indexed) - set(expected))
    if missing or extra:
        raise ValueError(
            f"weather_scenario must exactly cover the planning period; missing={missing[:3]}, extra={extra[:3]}."
        )
    return [indexed[day] for day in expected], {
        "provider": "caller",
        "product": "explicit planning weather scenario",
        "data_kind": "caller_supplied_scenario",
        "time_support": "UTC calendar days",
        "rainfall_fallback": None,
        "limitations": [
            "This scenario is a caller-supplied assumption, not a weather forecast.",
            "Run alternative dry, expected and wet scenarios for seasonal decisions.",
        ],
    }


def _environment(data: dict[str, Any], service: ContextService, latitude: float, longitude: float,
                 start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]] | None,
                                                   dict[str, Any] | None, bool]:
    if data.get("weather_scenario") is not None:
        rows, metadata = _weather_scenario(data["weather_scenario"], start, end)
        return ({"status": "scenario_ready", "record_count": len(rows),
                 "source": metadata, "note": "Explicit planning scenario supplied by the caller."},
                rows, metadata, True)

    today = date.today()
    if start >= today:
        if end <= today + timedelta(days=MAX_FORECAST_DAYS - 1):
            rows, metadata = fetch_daily_forecast(
                latitude, longitude, start.isoformat(), end.isoformat(), today=today
            )
            return ({"status": "forecast_ready", "record_count": len(rows),
                     "source": metadata, "note": "Operational forecast; refresh before acting."},
                    rows, metadata, True)
        return ({
            "status": "seasonal_scenario_required",
            "maximum_operational_forecast_end": (
                today + timedelta(days=MAX_FORECAST_DAYS - 1)
            ).isoformat(),
            "note": "The planning period exceeds a defensible daily forecast horizon. Supply weather_scenario.",
        }, None, None, False)

    if end >= today:
        return ({
            "status": "mixed_period_scenario_required",
            "note": "A period spanning observed and future dates requires one explicit weather_scenario.",
        }, None, None, False)

    context = service.query(latitude, longitude, start.isoformat(), end.isoformat(), ["imerg", "era5"])
    compact = {
        **{key: value for key, value in context.items() if key != "sources"},
        "sources": {
            name: {**{key: value for key, value in source.items() if key != "records"},
                   "record_count": len(source.get("records", []))}
            for name, source in context["sources"].items()
        },
        "note": "Raw daily records stay in the backend cache and feed the calculation; this response is compact.",
    }
    ready = all(context["sources"][name]["status"] == "complete" for name in ("imerg", "era5"))
    if not ready:
        return compact, None, None, False
    rows, metadata = merge_imerg_weather(
        context["sources"]["imerg"]["records"], context["sources"]["era5"]["records"]
    )
    return compact, rows, metadata, True


def _advice(report: dict[str, Any]) -> dict[str, Any]:
    scenarios = []
    for scenario in report["scenarios"]:
        steps = []
        for crop in scenario["sequence"]:
            steps.append({
                "crop_id": crop["crop"],
                "plant_on": crop["planting_date"],
                "harvest_on": crop["planned_harvest_date"],
                "prepare_irrigation_m3": crop["irrigation_m3_for_field"],
                "unmet_water_mm": crop["unmet_water_mm"],
                "estimated_n_shortfall_kg_ha": crop["estimated_n_shortfall_kg_ha"],
                "estimated_p_shortfall_kg_ha": crop["estimated_p_shortfall_kg_ha"],
                "estimated_k_shortfall_kg_ha": crop["estimated_k_shortfall_kg_ha"],
            })
        scenarios.append({
            "name": scenario["name"], "calendar_status": scenario["calendar_status"],
            "steps": steps, "total_irrigation_m3": scenario["total_irrigation_m3_for_field"],
            "estimated_margin": scenario["estimated_total_margin_for_field"],
            "currency": scenario["economics_currency"],
            "economics": scenario["economics_summary"],
            "preparation_flags": [item["message"] for item in scenario["schedule_issues"] + scenario["schedule_warnings"]],
        })
    return {"scenarios": scenarios, "ranking": report["comparison"]["ranking"]}


def _aggregate_zone_reports(zone_reports: list[dict[str, Any]], ranking: Any,
                            field_area_ha: float) -> dict[str, Any]:
    if not zone_reports:
        raise ValueError("At least one management zone is required.")
    areas = [entry["area_ha"] for entry in zone_reports]

    def weighted(values: list[float | None]) -> float | None:
        if any(value is None for value in values):
            return None
        return round(sum(float(value) * area for value, area in zip(values, areas)) / field_area_ha, 4)

    scenarios = []
    scenario_count = len(zone_reports[0]["report"]["scenarios"])
    for scenario_index in range(scenario_count):
        parts = [entry["report"]["scenarios"][scenario_index] for entry in zone_reports]
        base = deepcopy(parts[0])
        base["sequence"] = []
        for crop_index in range(len(parts[0]["sequence"])):
            crops = [part["sequence"][crop_index] for part in parts]
            crop = deepcopy(crops[0])
            for key in (
                "rain_mm", "irrigation_mm", "effective_irrigation_mm", "crop_water_need_mm",
                "effective_root_zone_capacity_mm", "unmet_water_mm", "soil_water_start_mm",
                "soil_water_end_mm", "profile_equivalent_soil_water_end_mm",
                "mineral_n_start_kg_ha", "net_soil_n_change_kg_ha",
                "estimated_mineral_n_end_kg_ha", "estimated_n_shortfall_kg_ha",
                "available_p_start_kg_ha", "net_available_p_change_kg_ha",
                "estimated_available_p_end_kg_ha", "estimated_p_shortfall_kg_ha",
                "exchangeable_k_start_kg_ha", "net_exchangeable_k_change_kg_ha",
                "estimated_exchangeable_k_end_kg_ha", "estimated_k_shortfall_kg_ha",
            ):
                crop[key] = weighted([value.get(key) for value in crops])
            for key in (
                "irrigation_m3_for_field", "mineral_n_start_kg_for_field",
                "net_soil_n_change_kg_for_field", "estimated_mineral_n_end_kg_for_field",
                "estimated_n_shortfall_kg_for_field",
            ):
                values = [value.get(key) for value in crops]
                crop[key] = None if any(value is None for value in values) else round(sum(values), 2)
            water_models = [value.get("water_model") for value in crops]
            if all(model is not None for model in water_models):
                crop["water_model"] = deepcopy(water_models[0])
                for key in ("average_kcb", "average_stress_coefficient_ks",
                            "average_soil_evaporation_coefficient_ke", "water_stress_days",
                            "final_surface_depletion_mm"):
                    crop["water_model"][key] = weighted([model.get(key) for model in water_models])
            economics_parts = [value.get("economics") for value in crops]
            if all(item is not None for item in economics_parts):
                economics = deepcopy(economics_parts[0])
                for key in (
                    "expected_yield_t_ha", "marketable_yield_fraction", "marketable_yield_t_ha",
                    "price_per_tonne", "variable_cost_per_ha", "total_crop_cost_per_ha",
                    "gross_revenue_per_ha", "additional_income_per_ha", "estimated_margin_per_ha",
                ):
                    economics[key] = weighted([item.get(key) for item in economics_parts])
                for key in (
                    "total_crop_cost_for_field", "gross_revenue_for_field",
                    "additional_income_for_field", "expected_production_t_for_field",
                    "marketable_production_t_for_field", "estimated_margin_for_field",
                ):
                    economics[key] = round(sum(item[key] for item in economics_parts), 2)
                economics["cost_items"] = [
                    {
                        **deepcopy(economics_parts[0]["cost_items"][item_index]),
                        "amount_per_ha": weighted([
                            item["cost_items"][item_index]["amount_per_ha"]
                            for item in economics_parts
                        ]),
                        "amount_for_field": round(sum(
                            item["cost_items"][item_index]["amount_for_field"]
                            for item in economics_parts
                        ), 2),
                    }
                    for item_index in range(len(economics_parts[0]["cost_items"]))
                ]
                total_cost = economics["total_crop_cost_for_field"]
                margin = economics["estimated_margin_for_field"]
                economics["return_on_cost_percent"] = (
                    None if not total_cost else round(margin / total_cost * 100, 2)
                )
                marketable_yield = economics["marketable_yield_t_ha"]
                price = economics["price_per_tonne"]
                fraction = economics["marketable_yield_fraction"]
                economics["break_even_price_per_tonne"] = (
                    None if not marketable_yield else round(
                        economics["total_crop_cost_per_ha"] / marketable_yield, 2
                    )
                )
                economics["break_even_yield_t_ha"] = (
                    None if not price or not fraction else round(
                        economics["total_crop_cost_per_ha"] / price / fraction, 4
                    )
                )
                crop["economics"] = economics
            crop["zone_results"] = [
                {"zone_id": entry["zone_id"], "area_ha": entry["area_ha"],
                 "result": crops[index]}
                for index, entry in enumerate(zone_reports)
            ]
            base["sequence"].append(crop)
        sum_keys = (
            "total_irrigation_m3_for_field", "irrigation_cost_for_field",
            "estimated_total_margin_for_field", "estimated_final_mineral_n_kg_for_field",
        )
        for key in sum_keys:
            values = [part.get(key) for part in parts]
            base[key] = None if any(value is None for value in values) else round(sum(values), 2)
        for key in ("total_rain_mm", "total_irrigation_mm", "total_effective_irrigation_mm",
                    "total_unmet_water_mm", "estimated_final_mineral_n_kg_ha",
                    "estimated_final_available_p_kg_ha", "estimated_final_exchangeable_k_kg_ha",
                    "estimated_final_organic_matter_percent", "estimated_final_soil_ph",
                    "total_nutrient_shortfall_kg_ha", "pest_disease_rotation_score",
                    "irrigation_limit_mm"):
            base[key] = weighted([part.get(key) for part in parts])
        feasibility = [part["calendar_feasible"] for part in parts]
        if any(value is False for value in feasibility):
            base["calendar_feasible"], base["calendar_status"] = False, "infeasible"
        elif all(value is True for value in feasibility):
            base["calendar_feasible"], base["calendar_status"] = True, "feasible"
        else:
            base["calendar_feasible"], base["calendar_status"] = None, "not_fully_evaluated"
        base["schedule_issues"] = [
            {**issue, "zone_id": entry["zone_id"]}
            for entry, part in zip(zone_reports, parts) for issue in part["schedule_issues"]
        ]
        base["schedule_warnings"] = [
            {**warning, "zone_id": entry["zone_id"]}
            for entry, part in zip(zone_reports, parts) for warning in part["schedule_warnings"]
        ]
        base["irrigation_events"] = [
            {**event, "zone_id": entry["zone_id"]}
            for entry, part in zip(zone_reports, parts) for event in part["irrigation_events"]
        ]
        summaries = [part["economics_summary"] for part in parts]
        currency = summaries[0].get("currency")
        economics_complete = all(summary["status"] == "complete" for summary in summaries)
        economics = {
            "status": "complete" if economics_complete else "not_fully_evaluated",
            "field_area_ha": field_area_ha,
            "currency": currency if economics_complete else None,
        }
        for key in ("gross_crop_revenue_for_field", "additional_income_for_field",
                    "crop_costs_for_field", "irrigation_cost_for_field", "total_cost_for_field",
                    "net_margin_for_field"):
            values = [summary.get(key) for summary in summaries]
            economics[key] = None if any(value is None for value in values) else round(sum(values), 2)
        economics["net_margin_per_ha"] = (
            None if economics["net_margin_for_field"] is None
            else round(economics["net_margin_for_field"] / field_area_ha, 2)
        )
        total_cost = economics["total_cost_for_field"]
        economics["return_on_cost_percent"] = (
            None if economics["net_margin_for_field"] is None or not total_cost
            else round(economics["net_margin_for_field"] / total_cost * 100, 2)
        )
        base["economics_summary"] = economics
        base["economics_status"] = economics["status"]
        base["economics_currency"] = economics["currency"]
        scenarios.append(base)
    return {
        "title": "Farmer field rotation advice by management zone",
        "field": {"area_ha": field_area_ha, "management_zone_count": len(zone_reports)},
        "scenarios": scenarios,
        "comparison": {"ranking": _rank_scenarios(scenarios, ranking)},
        "zones": zone_reports,
        "input_assessment": {"status": "zonal"},
        "assumptions_and_limits": [
            "Zone results are calculated independently and aggregated by zone area.",
            "Area fractions describe management zones; this endpoint does not validate polygon topology.",
        ],
    }


def build_rotation_advice(data: dict[str, Any], context_service: ContextService) -> tuple[int, dict[str, Any]]:
    geometry = polygon_summary(data["field_polygon"]["coordinates"])
    latitude = geometry["centroid"]["latitude"]
    longitude = geometry["centroid"]["longitude"]
    crop_sequence = data["crop_sequence"]
    unique_crops = list(dict.fromkeys(crop_sequence))
    start = data["preferred_start_date"]
    end = data["planning_end_date"]
    bundle = _source_bundle(latitude, longitude, unique_crops, start.year)
    input_resolution = None
    if data.get("autofill_missing", True):
        data, input_resolution = resolve_rotation_inputs(data, bundle, unique_crops, start)

    response: dict[str, Any] = {
        "status": "preliminary",
        "field": {"polygon": data["field_polygon"], **geometry},
        "request": {"crop_sequence": crop_sequence, "preferred_start_date": start.isoformat(),
                    "planning_end_date": end.isoformat(), "schedule_mode": data["schedule_mode"],
                    "autofill_missing": data.get("autofill_missing", True)},
        "crop_analysis": {name: bundle[name] for name in ("suitability", "calendar", "yield_baseline")},
        "soil_context": bundle["soil"],
        "environmental_context": None,
        "missing_inputs": [],
        "input_resolution": input_resolution,
        "calculation": None,
        "advice": None,
        "limitations": [
            "The polygon centroid selects gridded datasets; gridded values do not become field measurements.",
            "Future crop-season rainfall is not predicted by historical IMERG/ERA5 observations.",
            "Recommendations remain decision support until locally validated by an agronomist and field records.",
            *(["Paddy-rice irrigation totals exclude land preparation, standing-water, seepage, percolation and drainage requirements."]
              if "rice" in unique_crops else []),
        ],
    }

    environmental_context, weather_rows, weather_metadata, environment_ready = _environment(
        data, context_service, latitude, longitude, start, end
    )
    response["environmental_context"] = environmental_context

    missing = _requirements(data, unique_crops, environment_ready)
    if input_resolution is not None:
        missing = [item for item in missing if item["path"] == "environmental_context"]
    response["missing_inputs"] = missing
    active_jobs = []
    context = response.get("environmental_context")
    if isinstance(context, dict) and "sources" in context:
        active_jobs = [job for source in context["sources"].values() for job in source.get("jobs", [])
                       if job["status"] in {"queued", "running", "waiting"}]
    if active_jobs:
        response["status"] = "processing"
        response["jobs"] = active_jobs
        return 202, response
    if missing:
        response["status"] = "needs_input"
        return 200, response

    catalog = _crop_catalog(unique_crops, bundle, data.get("crop_inputs") or {})
    field_inputs = dict(data.get("field_inputs") or {})
    field_inputs.update({"name": data.get("field_name", "Selected field"), "area_ha": geometry["area_ha"]})
    if data.get("soil_test") is not None:
        field_inputs["soil_test"] = data["soil_test"]
    for optional in ("management", "irrigation"):
        if data.get(optional) is not None:
            field_inputs[optional] = data[optional]
    orders = [crop_sequence]
    if data.get("compare_all_orders", True) and len(unique_crops) == len(crop_sequence) and len(crop_sequence) > 1:
        orders = [list(order) for order in permutations(crop_sequence)]
    gaps = data.get("gaps_after_crops_days") or []
    scenarios = [{
        "name": " → ".join(order), "start_date": start.isoformat(), "planning_end_date": end.isoformat(),
        "schedule_mode": data["schedule_mode"], "crops": order, "gaps_after_crops_days": gaps,
    } for order in orders]
    config = {
        "title": "Farmer field rotation advice", "field": field_inputs, "crop_catalog": catalog,
        "weather": weather_rows, "scenarios": scenarios,
        "rotation_effect_catalog": data.get("rotation_effect_catalog") or {},
        "ranking": data.get("ranking"),
        "input_resolution": input_resolution,
    }
    zones = data.get("management_zones")
    if zones is None:
        report = simulate_scenarios(config)
    else:
        if not isinstance(zones, list) or not 1 <= len(zones) <= 20:
            raise ValueError("management_zones must contain between 1 and 20 zones.")
        identifiers: set[str] = set()
        fractions = []
        normalized_zones = []
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict):
                raise ValueError(f"management_zones[{index}] must be an object.")
            zone_id = zone.get("id")
            if not isinstance(zone_id, str) or not zone_id.strip() or zone_id in identifiers:
                raise ValueError("Every management zone needs a unique non-empty id.")
            identifiers.add(zone_id)
            try:
                fraction = float(zone["area_fraction"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"management_zones[{index}].area_fraction must be numeric.") from exc
            if not 0 < fraction <= 1:
                raise ValueError("Management-zone area fractions must be greater than 0 and at most 1.")
            fractions.append(fraction)
            normalized_zones.append((zone_id, fraction, zone))
        if abs(sum(fractions) - 1) > 0.000001:
            raise ValueError("Management-zone area fractions must sum to 1.")
        zone_reports = []
        for zone_id, fraction, zone in normalized_zones:
            zone_field = deepcopy(field_inputs)
            overrides = zone.get("field_inputs", {})
            if not isinstance(overrides, dict):
                raise ValueError(f"management_zones.{zone_id}.field_inputs must be an object.")
            zone_field.update(overrides)
            zone_field["name"] = f"{field_inputs['name']} — {zone_id}"
            zone_field["area_ha"] = geometry["area_ha"] * fraction
            for optional in ("soil_test", "management", "irrigation"):
                if zone.get(optional) is not None:
                    if not isinstance(zone[optional], dict):
                        raise ValueError(f"management_zones.{zone_id}.{optional} must be an object.")
                    inherited = zone_field.get(optional) if isinstance(zone_field.get(optional), dict) else {}
                    zone_field[optional] = {**inherited, **zone[optional]}
            zone_config = deepcopy(config)
            zone_config["field"] = zone_field
            for crop in zone_config["crop_catalog"].values():
                economics = crop.get("economics")
                if not isinstance(economics, dict):
                    continue
                for item in economics.get("cost_items", []):
                    if item.get("amount_for_field") is not None:
                        item["amount_for_field"] = float(item["amount_for_field"]) * fraction
            zone_report = simulate_scenarios(zone_config)
            zone_reports.append({
                "zone_id": zone_id,
                "area_fraction": fraction,
                "area_ha": zone_field["area_ha"],
                "report": zone_report,
            })
        report = _aggregate_zone_reports(
            zone_reports, data.get("ranking"), geometry["area_ha"]
        )
        response["field"]["management_zones"] = [
            {"id": entry["zone_id"], "area_fraction": entry["area_fraction"],
             "area_ha": round(entry["area_ha"], 6)}
            for entry in zone_reports
        ]
    response.update({"status": "preliminary" if input_resolution and input_resolution["critical_generated_count"] else "complete",
                     "missing_inputs": [],
                     "calculation": {"report": report, "weather_metadata": weather_metadata},
                     "advice": _advice(report)})
    return 200, response
