"""One-call orchestration for the farmer-facing crop-rotation workflow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import permutations
from typing import Any

from grainstorm.context import ContextService
from grainstorm.crops import get_profile
from grainstorm.geometry import polygon_summary
from grainstorm.planner import simulate_scenarios
from grainstorm.processing.planner_weather import merge_imerg_weather
from grainstorm.sources.gaez import fetch_location_suitability
from grainstorm.sources.gaez_calendar import fetch_location_crop_calendars
from grainstorm.sources.gaez_yield import fetch_location_yield_baselines
from grainstorm.sources.ssurgo import fetch_us_soil_context


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
                        "reason": "Complete IMERG rainfall and ERA5 ET0 are required for the requested dates."})
    return missing


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


def build_rotation_advice(data: dict[str, Any], context_service: ContextService) -> tuple[int, dict[str, Any]]:
    geometry = polygon_summary(data["field_polygon"]["coordinates"])
    latitude = geometry["centroid"]["latitude"]
    longitude = geometry["centroid"]["longitude"]
    crop_sequence = data["crop_sequence"]
    unique_crops = list(dict.fromkeys(crop_sequence))
    start = data["preferred_start_date"]
    end = data["planning_end_date"]
    bundle = _source_bundle(latitude, longitude, unique_crops, start.year)

    response: dict[str, Any] = {
        "status": "preliminary",
        "field": {"polygon": data["field_polygon"], **geometry},
        "request": {"crop_sequence": crop_sequence, "preferred_start_date": start.isoformat(),
                    "planning_end_date": end.isoformat(), "schedule_mode": data["schedule_mode"]},
        "crop_analysis": {name: bundle[name] for name in ("suitability", "calendar", "yield_baseline")},
        "soil_context": bundle["soil"],
        "environmental_context": None,
        "missing_inputs": [],
        "calculation": None,
        "advice": None,
        "limitations": [
            "The polygon centroid selects gridded datasets; gridded values do not become field measurements.",
            "Future crop-season rainfall is not predicted by historical IMERG/ERA5 observations.",
            "Recommendations remain decision support until locally validated by an agronomist and field records.",
        ],
    }

    environment_ready = False
    weather_rows = None
    weather_metadata = None
    if end <= date.today():
        context = context_service.query(latitude, longitude, start.isoformat(), end.isoformat(),
                                        ["imerg", "era5"])
        response["environmental_context"] = {
            **{key: value for key, value in context.items() if key != "sources"},
            "sources": {
                name: {**{key: value for key, value in source.items() if key != "records"},
                       "record_count": len(source.get("records", []))}
                for name, source in context["sources"].items()
            },
            "note": "Raw daily records stay in the backend cache and feed the calculation; this product response is intentionally compact.",
        }
        environment_ready = all(context["sources"][name]["status"] == "complete"
                                for name in ("imerg", "era5"))
        if environment_ready:
            weather_rows, weather_metadata = merge_imerg_weather(
                context["sources"]["imerg"]["records"], context["sources"]["era5"]["records"])
    else:
        response["environmental_context"] = {
            "status": "future_weather_unavailable",
            "note": "Historical satellite observations cannot predict daily weather for a future rotation.",
        }

    missing = _requirements(data, unique_crops, environment_ready)
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
    field_inputs.update({"name": data.get("field_name", "Selected field"), "area_ha": geometry["area_ha"],
                         "soil_test": data["soil_test"]})
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
    }
    report = simulate_scenarios(config)
    response.update({"status": "complete", "missing_inputs": [],
                     "calculation": {"report": report, "weather_metadata": weather_metadata},
                     "advice": _advice(report)})
    return 200, response
