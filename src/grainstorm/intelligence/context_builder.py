"""Deterministically compact a full analysis into decision-relevant AI context."""
from __future__ import annotations

from datetime import date
import json
import math
from typing import Any

from grainstorm.crops import PROFILES


class ContextBuildError(ValueError):
    """The supplied object is not a completed Grain Storm analysis."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _longest_dry_spell(records: list[dict[str, Any]], rain_key: str) -> dict[str, Any]:
    best: list[str] = []
    current: list[str] = []
    previous = None
    for row in sorted(records, key=lambda item: str(item.get("date", ""))):
        day = date.fromisoformat(row["date"])
        if previous is not None and (day - previous).days != 1:
            current = []
        previous = day
        rain = _number(row.get(rain_key))
        if rain is not None and rain < 1:
            current.append(str(row.get("date")))
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    return {
        "days": len(best),
        "start": best[0] if best else None,
        "end": best[-1] if best else None,
        "threshold_mm_day": 1,
    }


def _series_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep extremes and dry spells instead of reducing a series to one average."""
    if not records:
        return {"record_count": 0}
    candidates = {
        "rain_mm": ("gpm_precipitation_mm_day", "rain_mm", "precipitation_mm"),
        "et0_mm": ("et0_mm",),
        "soil_moisture_rootzone_m3_m3": ("soil_moisture_rootzone_m3_m3",),
        "soil_moisture_surface_m3_m3": ("soil_moisture_surface_m3_m3",),
    }
    result: dict[str, Any] = {
        "record_count": len(records),
        "start_date": min(str(row.get("date")) for row in records if row.get("date") is not None),
        "end_date": max(str(row.get("date")) for row in records if row.get("date") is not None),
    }
    for label, keys in candidates.items():
        key = next((candidate for candidate in keys
                    if any(_number(row.get(candidate)) is not None for row in records)), None)
        if key is None:
            continue
        values = [(str(row.get("date")), float(row[key])) for row in records
                  if _number(row.get(key)) is not None]
        minimum = min(values, key=lambda item: item[1])
        maximum = max(values, key=lambda item: item[1])
        result[label] = {
            "count": len(values),
            "minimum": minimum[1], "minimum_date": minimum[0],
            "maximum": maximum[1], "maximum_date": maximum[0],
            "mean": round(sum(value for _, value in values) / len(values), 4),
            "total": round(sum(value for _, value in values), 4) if label in {"rain_mm", "et0_mm"} else None,
        }
        if label == "rain_mm":
            result["longest_dry_spell"] = _longest_dry_spell(records, key)
            result["heavy_rain_days"] = [
                {"date": day, "rain_mm": value} for day, value in values if value >= 25
            ]
    return result


def _build_ai_context(analysis: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        raise ContextBuildError("analysis must be a JSON object")
    if analysis.get("status") not in {"complete", "preliminary"}:
        raise ContextBuildError("analysis must have status complete or preliminary")
    report = (analysis.get("calculation") or {}).get("report")
    if not isinstance(report, dict) or not report.get("scenarios"):
        raise ContextBuildError("analysis.calculation.report.scenarios is required")
    if not isinstance(analysis.get("advice"), dict):
        raise ContextBuildError("analysis.advice is required")

    evidence: list[dict[str, Any]] = []

    def add(evidence_id: str, source_path: str, basis: str, value: Any,
            units: str | None = None, source: str | None = None) -> str:
        evidence.append({
            "id": evidence_id, "source_path": source_path, "basis": basis,
            "value": value, "units": units, "source": source,
        })
        return evidence_id

    field = analysis["field"]
    request = analysis["request"]
    centroid = field["centroid"]
    add("field.area", "field.area_ha", "modeled", field["area_ha"], "ha",
        field.get("method"))
    add("field.location", "field.centroid", "modeled", centroid, "degrees",
        "GeoJSON polygon centroid")
    backend_summary = analysis["advice"].get("decision_summary") or {}
    add("backend.decision", "advice.decision_summary", "modeled", backend_summary)

    suitability_rows = {
        item["crop_id"]: item for item in analysis.get("crop_analysis", {})
        .get("suitability", {}).get("crops", [])
    }
    calendar_rows = {
        item["crop_id"]: item for item in analysis.get("crop_analysis", {})
        .get("calendar", {}).get("crops", [])
    }
    yield_rows = {
        item["crop_id"]: item for item in analysis.get("crop_analysis", {})
        .get("yield_baseline", {}).get("crops", [])
    }
    crops = []
    for crop_id in dict.fromkeys(request["crop_sequence"]):
        suitability = suitability_rows.get(crop_id, {})
        calendar = calendar_rows.get(crop_id, {})
        yield_data = yield_rows.get(crop_id, {})
        add(f"crop.{crop_id}.suitability", f"crop_analysis.suitability.crops.{crop_id}",
            "historical", {
                "index_percent": suitability.get("suitability_index_percent"),
                "class": suitability.get("suitability_class"),
                "baseline": analysis.get("crop_analysis", {}).get("suitability", {}).get("dataset", {}).get("baseline"),
            }, "percent", "FAO/IIASA GAEZ v4")
        add(f"crop.{crop_id}.calendar", f"crop_analysis.calendar.crops.{crop_id}",
            "historical", {
                "planting_anchor": calendar.get("planting_date_for_target_year"),
                "cycle_length_days": calendar.get("cycle_length_days"),
                "projected_harvest": calendar.get("projected_harvest_date"),
            }, None, "FAO/IIASA GAEZ v4")
        add(f"crop.{crop_id}.yield", f"crop_analysis.yield_baseline.crops.{crop_id}",
            "historical", yield_data.get("historical_yield_t_ha"), "t/ha",
            "FAO/IIASA GAEZ 2010 downscaled actual yield")
        crops.append({
            "crop_id": crop_id,
            "suitability": {key: suitability.get(key) for key in
                            ("suitability_index_percent", "suitability_class", "baseline_override")},
            "calendar": {key: calendar.get(key) for key in
                         ("planting_date_for_target_year", "cycle_length_days", "projected_harvest_date")},
            "historical_yield": yield_data.get("historical_yield_t_ha"),
            "evidence_references": [f"crop.{crop_id}.suitability", f"crop.{crop_id}.calendar",
                                    f"crop.{crop_id}.yield"],
        })

    soil = analysis.get("soil_context") or {"status": "unavailable"}
    add("soil.context", "soil_context", "modeled" if soil.get("status") == "complete" else "unavailable",
        {key: value for key, value in soil.items() if key not in {"dataset"}}, None,
        (soil.get("dataset") or {}).get("provider"))

    generated = (analysis.get("input_resolution") or {}).get("generated_inputs", [])
    for index, item in enumerate(generated):
        add(f"input.generated.{index}", f"input_resolution.generated_inputs.{index}", "assumed",
            {key: item.get(key) for key in ("path", "value", "confidence", "note")}, None,
            item.get("source"))

    scenarios = []
    for index, scenario in enumerate(report["scenarios"]):
        prefix = f"scenario.{index}"
        schedule = [{
            "crop_id": crop.get("crop"),
            "planting_date": crop.get("planting_date"),
            "harvest_date": crop.get("planned_harvest_date"),
            "duration_days": crop.get("duration_days"),
            "planting_window_status": crop.get("planting_window_status"),
            "water_demand_mm": crop.get("crop_water_need_mm"),
            "rain_mm": crop.get("rain_mm"),
            "irrigation_mm": crop.get("irrigation_mm"),
            "unmet_water_mm": crop.get("unmet_water_mm"),
            "n_shortfall_kg_ha": crop.get("estimated_n_shortfall_kg_ha"),
            "p_shortfall_kg_ha": crop.get("estimated_p_shortfall_kg_ha"),
            "k_shortfall_kg_ha": crop.get("estimated_k_shortfall_kg_ha"),
            "water_model_warning": crop.get("water_model_warning"),
            "water_model": crop.get("water_model"),
            "nutrient_budget": crop.get("nutrient_budget"),
            "soil_water_start_mm": crop.get("soil_water_start_mm"),
            "soil_water_end_mm": crop.get("soil_water_end_mm"),
            "matched_planting_window": crop.get("matched_planting_window"),
            "gap_before_days": crop.get("gap_before_days"),
            "root_depth_m": crop.get("root_depth_m"),
            "stage_water_assessment": crop.get("stage_water_assessment", []),
        } for crop in scenario["sequence"]]
        add(f"{prefix}.calendar", f"calculation.report.scenarios.{index}", "modeled", {
            "name": scenario["name"], "status": scenario.get("calendar_status"),
            "feasible": scenario.get("calendar_feasible"),
            "issues": scenario.get("schedule_issues", []), "warnings": scenario.get("schedule_warnings", []),
            "schedule": schedule,
        })
        add(f"{prefix}.water", f"calculation.report.scenarios.{index}", "modeled", {
            "rain_mm": scenario.get("total_rain_mm"),
            "irrigation_mm": scenario.get("total_irrigation_mm"),
            "irrigation_m3_for_field": scenario.get("total_irrigation_m3_for_field"),
            "unmet_water_mm": scenario.get("total_unmet_water_mm"),
        })
        add(f"{prefix}.nutrients", f"calculation.report.scenarios.{index}", "modeled", {
            "combined_shortfall_kg_ha": scenario.get("total_nutrient_shortfall_kg_ha"),
            "final_n_kg_ha": scenario.get("estimated_final_mineral_n_kg_ha"),
            "final_p_kg_ha": scenario.get("estimated_final_available_p_kg_ha"),
            "final_k_kg_ha": scenario.get("estimated_final_exchangeable_k_kg_ha"),
        })
        add(f"{prefix}.economics", f"calculation.report.scenarios.{index}.economics_summary",
            "modeled", scenario.get("economics_summary"))
        scenarios.append({
            "scenario_index": index, "name": scenario["name"],
            "calendar_status": scenario.get("calendar_status"),
            "calendar_feasible": scenario.get("calendar_feasible"),
            "schedule": schedule,
            "water": evidence[-3]["value"], "nutrients": evidence[-2]["value"],
            "economics": evidence[-1]["value"],
            "rotation_health_score": scenario.get("pest_disease_rotation_score"),
            "rotation_effects": scenario.get("rotation_effects", []),
            "fallow_periods": scenario.get("fallow_periods", []),
            "evidence_references": [f"{prefix}.calendar", f"{prefix}.water",
                                    f"{prefix}.nutrients", f"{prefix}.economics"],
        })

    environment = analysis.get("environmental_context") or {}
    environment_summaries = {}
    for name, source in (environment.get("sources") or {}).items():
        summary = _series_summary(source.get("records", [])) if source.get("records") else {
            key: source.get(key) for key in ("status", "record_count", "missing_dates", "invalid_dates", "errors")
            if key in source
        }
        environment_summaries[name] = summary
        add(f"environment.{name}.summary", f"environmental_context.sources.{name}",
            "modeled", summary, None, name)

    irrigation = report.get("field", {}).get("irrigation", {})
    irrigation_status = "unknown"
    if irrigation.get("enabled") is True:
        irrigation_status = "available"
    elif irrigation.get("enabled") is False:
        irrigation_status = "unavailable"

    start = date.fromisoformat(request["preferred_start_date"])
    end = date.fromisoformat(request["planning_end_date"])
    return {
        "context_schema_version": "1.0.0",
        "analysis_status": analysis["status"],
        "field": {
            "name": report.get("field", {}).get("name", "Selected field"),
            "latitude": centroid["latitude"], "longitude": centroid["longitude"],
            "area_ha": field["area_ha"], "planning_start": start.isoformat(),
            "planning_end": end.isoformat(), "planning_horizon_days": (end - start).days + 1,
            "irrigation_status": irrigation_status,
            "irrigation": irrigation,
        },
        "requested_crop_sequence": request["crop_sequence"],
        "supported_crop_ids": sorted(PROFILES),
        "backend_decision": backend_summary,
        "crops": crops,
        "scenarios": scenarios,
        "soil": {"status": soil.get("status"), "evidence_reference": "soil.context"},
        "environment": environment_summaries,
        "temporal_evidence_limit": "Daily rainfall and growth-stage stress timing are unavailable when absent from this analysis; do not infer extremes from season totals.",
        "weather_metadata": (analysis.get("calculation") or {}).get("weather_metadata"),
        "temporal_context": (analysis.get("calculation") or {}).get("temporal_context"),
        "planner_limits": report.get("assumptions_and_limits", []),
        "input_quality": {
            "generated_count": (analysis.get("input_resolution") or {}).get("generated_count", 0),
            "critical_generated_count": (analysis.get("input_resolution") or {}).get("critical_generated_count", 0),
            "recommended_replacements": (analysis.get("input_resolution") or {}).get("recommended_replacements", []),
            "missing_inputs": analysis.get("missing_inputs", []),
        },
        "backend_limitations": analysis.get("limitations", []),
        "evidence_catalog": evidence,
    }


def build_ai_context(analysis: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(analysis, allow_nan=False)
        if len(encoded.encode()) > 2_000_000:
            raise ContextBuildError("Analysis exceeds the 2 MB input limit.")
        context = _build_ai_context(json.loads(encoded))
        if context["field"]["planning_horizon_days"] <= 0 or context["field"]["area_ha"] <= 0:
            raise ContextBuildError("Invalid field area or planning horizon.")
        if len(json.dumps(context).encode()) > 160_000:
            raise ContextBuildError("Decision context exceeds 160 KB; evaluate fewer scenarios.")
        return context
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ContextBuildError):
            raise
        raise ContextBuildError("Malformed analysis: check field, request, dates and calculation structures.") from exc
