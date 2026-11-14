"""Resolve optional rotation inputs into transparent planning baselines.

The resolver never labels a modeled value as a measurement. Caller values win;
every generated value is returned with provenance and a confidence class.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from grainstorm.crops import get_profile


FAO_WATER_URL = "https://www.fao.org/4/r4082e/r4082e03.htm"
FAO_NUTRIENT_URL = "https://files-faostat.fao.org/production/ESB/CNB%20methodology_2022.pdf"

# kg of elemental N, P and K removed per tonne of harvested product.
FAOSTAT_REMOVAL_KG_PER_TONNE = {
    "grain_maize": {"n": 12.4, "p": 3.4, "k": 4.3},
    "grain_soybean": {"n": 59.3, "p": 8.1, "k": 18.3},
    "wheat": {"n": 20.9, "p": 4.2, "k": 5.2},
    "sorghum": {"n": 14.6, "p": 4.5, "k": 4.2},
    "chickpea": {"n": 27.6, "p": 5.1, "k": 15.3},
    "sunflower": {"n": 23.6, "p": 3.9, "k": 6.5},
    "rice": {"n": 12.9, "p": 2.8, "k": 3.0},
}

CROP_FAMILIES = {
    "grain_maize": "Poaceae", "wheat": "Poaceae", "sorghum": "Poaceae",
    "grain_soybean": "Fabaceae", "chickpea": "Fabaceae", "sunflower": "Asteraceae",
    "rice": "Poaceae",
}


def _record(records: list[dict[str, Any]], *, path: str, value: Any, source: str,
            source_url: str | None, confidence: str, note: str) -> None:
    records.append({
        "path": path, "value": value, "source": source, "source_url": source_url,
        "confidence": confidence, "replaceable_by_farmer": True, "note": note,
    })


def _window(anchor: date, radius_days: int = 14) -> list[dict[str, str]]:
    beginning, ending = anchor - timedelta(days=radius_days), anchor + timedelta(days=radius_days)
    return [{
        "label": f"GAEZ anchor ±{radius_days} days",
        "start_month_day": beginning.strftime("%m-%d"),
        "end_month_day": ending.strftime("%m-%d"),
    }]


def resolve_rotation_inputs(data: dict[str, Any], bundle: dict[str, Any],
                            crop_ids: list[str], start: date) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = deepcopy(data)
    generated: list[dict[str, Any]] = []
    replacements: list[dict[str, str]] = []
    field = dict(resolved.get("field_inputs") or {})
    soil = bundle.get("soil", {})
    soil_profile = soil.get("soil") if soil.get("status") == "complete" else None
    topsoil = soil_profile.get("topsoil_0_30cm", {}) if isinstance(soil_profile, dict) else {}
    max_root_depth = max(get_profile(crop_id)["rooting"]["reference_depth_m"] for crop_id in crop_ids)

    if field.get("soil_water_capacity_mm") is None or field.get("soil_water_capacity_depth_m") is None:
        awc = topsoil.get("available_water_capacity_mm")
        covered_m = float(topsoil.get("covered_depth_cm") or 0) / 100
        if awc is not None and covered_m > 0:
            capacity_per_m = float(awc) / covered_m
            source = "USDA NRCS SSURGO topsoil AWC extrapolated to reference root depth"
            source_url = soil.get("dataset", {}).get("source_page")
            confidence = "medium"
            note = "Topsoil available-water capacity is extrapolated uniformly through the reference root depth."
        else:
            capacity_per_m = 120.0
            source = "FAO medium-textured soil reference baseline"
            source_url = FAO_WATER_URL
            confidence = "low"
            note = "Uses 120 mm/m as a medium-textured-soil planning baseline because no field soil-water profile was available."
        if field.get("soil_water_capacity_depth_m") is None:
            field["soil_water_capacity_depth_m"] = max_root_depth
            _record(generated, path="field_inputs.soil_water_capacity_depth_m", value=max_root_depth,
                    source=source, source_url=source_url, confidence=confidence, note=note)
        if field.get("soil_water_capacity_mm") is None:
            capacity = round(capacity_per_m * float(field["soil_water_capacity_depth_m"]), 2)
            field["soil_water_capacity_mm"] = capacity
            _record(generated, path="field_inputs.soil_water_capacity_mm", value=capacity,
                    source=source, source_url=source_url, confidence=confidence, note=note)

    if field.get("initial_soil_water_mm") is None:
        initial_water = round(float(field["soil_water_capacity_mm"]) * 0.5, 2)
        field["initial_soil_water_mm"] = initial_water
        _record(generated, path="field_inputs.initial_soil_water_mm", value=initial_water,
                source="Conservative planning initialization", source_url=None, confidence="low",
                note="Starts the plant-available-water bucket at 50%; replace with a sensor or calibrated soil-moisture estimate.")
        replacements.append({"path": "field_inputs.initial_soil_water_mm",
                             "reason": "A field sensor or calibrated soil-moisture estimate will improve irrigation timing."})

    soil_test = resolved.get("soil_test")
    has_measured_n = isinstance(soil_test, dict) and soil_test.get("mineral_n_kg_ha") is not None
    if not has_measured_n and field.get("initial_mineral_n_kg_ha") is None:
        field["initial_mineral_n_kg_ha"] = 0.0
        _record(generated, path="field_inputs.initial_mineral_n_kg_ha", value=0.0,
                source="Zero-credit nutrient planning scenario", source_url=None, confidence="low",
                note="This is not a soil measurement. It prevents unmeasured soil N from being credited and exposes the maximum modeled N shortfall.")
        replacements.append({"path": "soil_test.mineral_n_kg_ha",
                             "reason": "A laboratory mineral-N test replaces the conservative zero-credit scenario."})

    for field_key, test_key, label in (
        ("initial_available_p_kg_ha", "available_p_kg_ha", "plant-available phosphorus"),
        ("initial_exchangeable_k_kg_ha", "exchangeable_k_kg_ha", "exchangeable potassium"),
    ):
        measured = isinstance(soil_test, dict) and soil_test.get(test_key) is not None
        if not measured and field.get(field_key) is None:
            field[field_key] = 0.0
            _record(generated, path=f"field_inputs.{field_key}", value=0.0,
                    source="Zero-credit nutrient planning scenario", source_url=None, confidence="low",
                    note=f"This is not a soil measurement. It exposes maximum modeled {label} shortfall without crediting an unknown reserve.")
            replacements.append({"path": f"soil_test.{test_key}",
                                 "reason": f"A laboratory {label} result replaces the conservative zero-credit scenario."})

    for destination, source_key in (("initial_organic_matter_percent", "organic_matter_percent"),
                                    ("initial_soil_ph", "ph_h2o")):
        if field.get(destination) is None and topsoil.get(source_key) is not None:
            value = float(topsoil[source_key])
            field[destination] = value
            _record(generated, path=f"field_inputs.{destination}", value=value,
                    source="USDA NRCS SSURGO mapped topsoil", source_url=soil.get("dataset", {}).get("source_page"),
                    confidence="medium", note="Mapped soil context, not a current field laboratory measurement.")

    resolved["field_inputs"] = field
    if len(resolved["crop_sequence"]) > 1 and resolved.get("gaps_after_crops_days") is None:
        gaps = [14] * (len(resolved["crop_sequence"]) - 1)
        resolved["gaps_after_crops_days"] = gaps
        _record(generated, path="gaps_after_crops_days", value=gaps,
                source="Operational turnaround planning assumption", source_url=None, confidence="low",
                note="Allows fourteen days between harvest and the next planting; replace for local labour and machinery capacity.")

    calendars = {row["crop_id"]: row for row in bundle["calendar"]["crops"]}
    yields = {row["crop_id"]: row for row in bundle["yield_baseline"]["crops"]}
    crop_inputs = deepcopy(resolved.get("crop_inputs") or {})
    for crop_id in crop_ids:
        crop = dict(crop_inputs.get(crop_id) or {})
        calendar = calendars[crop_id]
        if not crop.get("planting_windows"):
            raw_anchor = calendar.get("planting_date_for_target_year")
            anchor = date.fromisoformat(raw_anchor) if raw_anchor else start
            crop["planting_windows"] = _window(anchor)
            _record(generated, path=f"crop_inputs.{crop_id}.planting_windows",
                    value=crop["planting_windows"], source="FAO/IIASA GAEZ location crop-cycle anchor",
                    source_url=bundle["calendar"].get("dataset", {}).get("service"), confidence="medium",
                    note="A ±14-day planning window around the coarse GAEZ anchor; local extension guidance should replace it.")
        if not crop.get("agronomy") and not crop.get("nutrient_budget"):
            yield_value = yields[crop_id].get("historical_yield_t_ha")
            if yield_value is not None:
                crop["agronomy"] = {
                    "expected_yield_t_ha": float(yield_value),
                    "nutrient_removal_kg_per_tonne": deepcopy(FAOSTAT_REMOVAL_KG_PER_TONNE[crop_id]),
                    "source": "FAOSTAT global crop-removal coefficients with GAEZ 2010 rainfed yield baseline",
                    "note": "Screening baseline only; fertilizer, residue, fixation and losses remain zero unless supplied.",
                }
                _record(generated, path=f"crop_inputs.{crop_id}.agronomy", value=crop["agronomy"],
                        source="FAOSTAT Cropland Nutrient Budget + FAO/IIASA GAEZ",
                        source_url=FAO_NUTRIENT_URL, confidence="low",
                        note="Historical grid yield multiplied by global removal coefficients; not a fertilizer recommendation.")
            else:
                crop["net_soil_n_change_kg_ha"] = 0.0
                crop["nitrogen_assumption_source"] = "Nutrient calculation unavailable without a yield baseline"
                replacements.append({"path": f"crop_inputs.{crop_id}.agronomy.expected_yield_t_ha",
                                     "reason": "A local expected yield is needed to calculate crop nutrient removal."})
        if not crop.get("economics"):
            replacements.append({"path": f"crop_inputs.{crop_id}.economics",
                                 "reason": "Local price and production costs are required for a meaningful margin; zero-value economics are not fabricated."})
        crop_inputs[crop_id] = crop
    resolved["crop_inputs"] = crop_inputs

    rotation_effects = deepcopy(resolved.get("rotation_effect_catalog") or {})
    sequence = resolved["crop_sequence"]
    transitions = {
        (sequence[index], sequence[index + 1]) for index in range(len(sequence) - 1)
    }
    if resolved.get("compare_all_orders", True) and len(crop_ids) == len(sequence) and len(crop_ids) > 1:
        transitions.update((first, second) for first in crop_ids for second in crop_ids if first != second)
    for first, second in sorted(transitions):
        transition = f"{first}->{second}"
        if transition in rotation_effects:
            continue
        if first == second:
            score, explanation = -2, "The same crop provides no rotation break."
        elif CROP_FAMILIES[first] == CROP_FAMILIES[second]:
            score, explanation = -1, "Crops in the same botanical family may share pests or diseases."
        else:
            score, explanation = 1, "Different botanical families provide a provisional rotation break."
        rotation_effects[transition] = {
            "pest_disease_break_score": score,
            "source": "Botanical-family screening heuristic",
            "note": f"{explanation} Replace with local pest and disease guidance.",
        }
        _record(generated, path=f"rotation_effect_catalog.{transition}",
                value=rotation_effects[transition], source="Botanical-family screening heuristic",
                source_url=None, confidence="low",
                note="Structural screening only; it does not model local pathogen, cultivar or pesticide history.")
    resolved["rotation_effect_catalog"] = rotation_effects
    critical_generated = [
        item for item in generated if not item["path"].startswith("rotation_effect_catalog.")
    ]
    return resolved, {
        "mode": "automatic_baseline",
        "generated_inputs": generated,
        "recommended_replacements": replacements,
        "generated_count": len(generated),
        "critical_generated_count": len(critical_generated),
        "warning": "Generated values are planning baselines, not field measurements or guaranteed recommendations.",
    }
