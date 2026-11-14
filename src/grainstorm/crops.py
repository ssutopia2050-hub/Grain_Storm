"""Versioned, source-backed crop reference profiles for frontend forms."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


PROFILE_VERSION = "fao-reference-v1"

SOURCES = {
    "fao_crop_water_needs": {
        "title": "FAO Chapter 3: Crop water needs",
        "url": "https://www.fao.org/4/S2022E/s2022e07.htm",
        "supports": [
            "indicative total growing-period ranges",
            "reference stage lengths",
            "four stage-average crop coefficients",
            "indicative seasonal crop-water ranges",
        ],
    },
    "fao56_crop_evapotranspiration": {
        "title": "FAO Irrigation and Drainage Paper 56: Crop evapotranspiration",
        "url": "https://www.fao.org/4/X0490E/x0490e00.htm",
        "supports": [
            "ETc = ET0 x Kc method",
            "local adjustment of coefficients and stage lengths",
        ],
    },
    "gaez_v4_model": {
        "title": "FAO/IIASA Global Agro-Ecological Zones v4 model documentation",
        "url": "https://gaez-v4-data.fao.org/data/documentation/GAEZ%20v4%20Model%20Documentation.pdf",
        "supports": [
            "crop identifiers and location-specific crop-cycle/suitability context",
        ],
    },
    "fao_rooting_depth": {
        "title": "FAO Scaling soil nutrient balances: Annex 3 rooting depth",
        "url": "https://www.fao.org/4/y5749e/y5749e0j.htm",
        "supports": ["conservative reference rooting depth for water and nutrient balances"],
    },
    "fao_ecocrop_chickpea": {
        "title": "FAO EcoCrop: chickpea",
        "url": "https://ecocrop.apps.fao.org/ecocrop/srv/en/cropView?id=2479",
        "supports": ["broad reference range for chickpea days from sowing to harvest"],
    },
}


def _profile(*, crop_id: str, name: str, scientific_name: str, form: str,
             aliases: list[str], gaez_code: str, duration: tuple[int, int],
             calendars: list[tuple[str, int, list[int]]], kc: list[float],
             water_range: tuple[int, int], drought_sensitivity: str,
             root_depth_m: float, extra_source_ids: tuple[str, ...] = (),
             extra_water_limitations: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "id": crop_id,
        "profile_version": PROFILE_VERSION,
        "display_name": name,
        "scientific_name": scientific_name,
        "production_form": form,
        "aliases": aliases,
        "scope": "General FAO reference baseline; local variety and calendar data override it.",
        "gaez": {
            "crop_code": gaez_code,
            "location_suitability_status": "not_evaluated",
            "note": "GAEZ suitability and crop-cycle layers are not yet queried by this endpoint.",
        },
        "growing_period": {
            "indicative_days": {"minimum": duration[0], "maximum": duration[1]},
            "stage_order": ["initial", "development", "mid_season", "late_season"],
            "reference_calendars": [
                {
                    "id": ident,
                    "duration_days": total,
                    "stage_days": stages,
                    "label": f"FAO {total}-day reference",
                    "source_id": "fao_crop_water_needs",
                    "local_override_required": True,
                }
                for ident, total, stages in calendars
            ],
            "local_inputs_needed": ["variety or maturity group", "planting date", "locally expected days to maturity"],
        },
        "water": {
            "method": "ETc = ET0 x stage-average Kc",
            "stage_kc": kc,
            "stage_kc_units": "dimensionless",
            "et0_units": "mm/day",
            "output_units": "mm/day",
            "indicative_seasonal_need_mm": {"minimum": water_range[0], "maximum": water_range[1]},
            "drought_sensitivity": drought_sensitivity,
            "source_ids": ["fao_crop_water_needs", "fao56_crop_evapotranspiration"],
            "limitations": [
                "Reference Kc values depend on climate, wind, humidity and wetting frequency.",
                "The current planner applies one average coefficient per stage; it does not yet interpolate a FAO-56 Kc curve.",
                "Indicative seasonal water need is context only and is not used when daily ET0 and stage Kc are available.",
                *extra_water_limitations,
            ],
        },
        "rooting": {
            "reference_depth_m": root_depth_m,
            "source_id": "fao_rooting_depth",
            "local_override_required": True,
            "note": "Conservative balance parameter; restrictive soil layers and local variety can reduce effective depth.",
        },
        "nitrogen": {
            "default_net_soil_n_change_kg_ha": None,
            "required_planner_field": "net_soil_n_change_kg_ha",
            "status": "local_input_required",
            "reason": (
                "Net mineral-N change depends on soil tests, yield, fertilizer/manure, fixation, "
                "residue handling, harvest removal and losses; it is not a universal crop constant."
            ),
            "legume_warning": (
                "Biological fixation is not automatically a positive soil-N credit after harvest."
                if crop_id in {"grain_soybean", "chickpea"} else None
            ),
            "soybean_warning": (
                "Biological fixation is not automatically a positive soil-N credit after harvest."
                if crop_id == "grain_soybean" else None
            ),
        },
        "source_ids": [
            "fao_crop_water_needs", "fao56_crop_evapotranspiration",
            "gaez_v4_model", "fao_rooting_depth", *extra_source_ids,
        ],
    }


PROFILES = {
    "grain_maize": _profile(
        crop_id="grain_maize", name="Grain maize", scientific_name="Zea mays L.",
        form="Dry grain", aliases=["maize", "field corn", "grain corn"], gaez_code="mze",
        duration=(125, 180),
        calendars=[
            ("fao_reference_125", 125, [20, 35, 40, 30]),
            ("fao_reference_180", 180, [30, 50, 60, 40]),
        ],
        kc=[0.40, 0.80, 1.15, 0.70], water_range=(500, 800),
        drought_sensitivity="medium-high", root_depth_m=0.9,
    ),
    "grain_soybean": _profile(
        crop_id="grain_soybean", name="Grain soybean", scientific_name="Glycine max (L.) Merr.",
        form="Dry seed", aliases=["soybean", "soya bean"], gaez_code="soy",
        duration=(135, 150),
        calendars=[
            ("fao_reference_135", 135, [20, 30, 60, 25]),
            ("fao_reference_150", 150, [20, 30, 70, 30]),
        ],
        kc=[0.35, 0.75, 1.10, 0.60], water_range=(450, 700),
        drought_sensitivity="low-medium", root_depth_m=0.6,
    ),
    "wheat": _profile(
        crop_id="wheat", name="Wheat", scientific_name="Triticum aestivum L.",
        form="Dry grain", aliases=["bread wheat", "common wheat"], gaez_code="whe",
        duration=(120, 150),
        calendars=[
            ("fao_reference_120", 120, [15, 25, 50, 30]),
            ("fao_reference_150", 150, [15, 30, 65, 40]),
        ],
        kc=[0.35, 0.75, 1.15, 0.45], water_range=(450, 650),
        drought_sensitivity="low-medium", root_depth_m=1.0,
    ),
    "sorghum": _profile(
        crop_id="sorghum", name="Grain sorghum", scientific_name="Sorghum bicolor (L.) Moench",
        form="Dry grain", aliases=["grain sorghum", "milo"], gaez_code="srg",
        duration=(120, 130),
        calendars=[
            ("fao_reference_120", 120, [20, 30, 40, 30]),
            ("fao_reference_130", 130, [20, 35, 45, 30]),
        ],
        kc=[0.35, 0.75, 1.10, 0.65], water_range=(450, 650),
        drought_sensitivity="low", root_depth_m=1.0,
    ),
    "chickpea": _profile(
        crop_id="chickpea", name="Chickpea", scientific_name="Cicer arietinum L.",
        form="Dry seed", aliases=["garbanzo bean", "gram", "chana"], gaez_code="chk",
        duration=(90, 180),
        calendars=[
            ("fao_reference_100", 100, [15, 25, 45, 15]),
            ("fao_reference_150", 150, [20, 30, 60, 40]),
        ],
        kc=[0.45, 0.75, 1.10, 0.50], water_range=(350, 500),
        drought_sensitivity="medium-high", root_depth_m=0.6,
        extra_source_ids=("fao_ecocrop_chickpea",),
    ),
    "sunflower": _profile(
        crop_id="sunflower", name="Sunflower", scientific_name="Helianthus annuus L.",
        form="Oilseed", aliases=["oilseed sunflower"], gaez_code="sfl",
        duration=(125, 130),
        calendars=[
            ("fao_reference_125", 125, [20, 35, 45, 25]),
            ("fao_reference_130", 130, [25, 35, 45, 25]),
        ],
        kc=[0.35, 0.75, 1.15, 0.55], water_range=(600, 1000),
        drought_sensitivity="low-medium", root_depth_m=0.8,
    ),
    "rice": _profile(
        crop_id="rice", name="Paddy rice", scientific_name="Oryza sativa L.",
        form="Paddy grain (wetland rice)", aliases=["rice", "paddy", "wetland rice"],
        gaez_code="rcw", duration=(90, 150),
        calendars=[("fao_reference_150", 150, [30, 30, 60, 30])],
        kc=[1.10, 1.10, 1.20, 1.00], water_range=(450, 700),
        drought_sensitivity="high", root_depth_m=0.5,
        extra_water_limitations=(
            "The Kc water range represents crop evapotranspiration, not total paddy irrigation demand.",
            "The current planner does not model puddling/soil saturation, a standing water layer, seepage, percolation, or intentional drainage; its rice irrigation volume is therefore incomplete.",
        ),
    ),
}


def list_profiles() -> list[dict[str, Any]]:
    return [{
        "id": item["id"],
        "profile_version": item["profile_version"],
        "display_name": item["display_name"],
        "scientific_name": item["scientific_name"],
        "production_form": item["production_form"],
        "aliases": item["aliases"],
        "indicative_duration_days": item["growing_period"]["indicative_days"],
        "calendar_ids": [calendar["id"] for calendar in item["growing_period"]["reference_calendars"]],
        "nitrogen_status": item["nitrogen"]["status"],
    } for item in PROFILES.values()]


def get_profile(crop_id: str) -> dict[str, Any]:
    if crop_id not in PROFILES:
        raise KeyError(crop_id)
    profile = deepcopy(PROFILES[crop_id])
    profile["sources"] = {source_id: deepcopy(SOURCES[source_id]) for source_id in profile["source_ids"]}
    return profile


def planner_template(crop_id: str, calendar_id: str, *, nitrogen_value=None,
                     nitrogen_source=None, nitrogen_note=None) -> dict[str, Any]:
    profile = get_profile(crop_id)
    calendar = next((item for item in profile["growing_period"]["reference_calendars"]
                     if item["id"] == calendar_id), None)
    if calendar is None:
        raise ValueError(f"Unknown calendar '{calendar_id}' for crop '{crop_id}'.")
    if nitrogen_value is not None and not nitrogen_source:
        raise ValueError("A nitrogen_source is required when a net nitrogen assumption is supplied.")
    planner_crop = {
        "duration_days": calendar["duration_days"],
        "stage_days": calendar["stage_days"],
        "stage_kc": profile["water"]["stage_kc"],
        "net_soil_n_change_kg_ha": nitrogen_value,
        "profile_id": crop_id,
        "profile_version": PROFILE_VERSION,
        "calendar_id": calendar_id,
        "water_profile_source_id": "fao_crop_water_needs",
        "nitrogen_assumption_source": nitrogen_source,
        "nitrogen_assumption_note": nitrogen_note,
    }
    return {
        "crop_id": crop_id,
        "calendar_id": calendar_id,
        "ready_for_planner": nitrogen_value is not None,
        "missing_inputs": [] if nitrogen_value is not None else ["net_soil_n_change_kg_ha", "nitrogen_source"],
        "planner_crop": planner_crop,
        "warnings": [
            "Confirm the reference calendar against the local variety and planting season.",
            profile["nitrogen"]["reason"],
        ],
        "sources": profile["sources"],
    }
