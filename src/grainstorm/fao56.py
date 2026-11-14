"""Small, auditable FAO-56 dual-coefficient helpers.

The implementation follows the FAO-56 Kcb + Ke structure. It is optional;
legacy stage-average Kc calculations remain available for existing requests.
"""
from __future__ import annotations

import math
from typing import Any


SOURCE = "FAO Irrigation and Drainage Paper 56, Chapters 7 and 8"
SOURCE_URL = "https://www.fao.org/4/X0490E/x0490e00.htm"


def _finite(value: Any, name: str, minimum: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric.") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return number


def validate_dual_config(value: Any) -> dict[str, float | str]:
    if not isinstance(value, dict) or value.get("method") != "fao56_dual":
        raise ValueError("water_model.method must be fao56_dual.")
    required = (
        "kcb_initial", "kcb_mid", "kcb_end", "depletion_fraction",
        "readily_evaporable_water_mm", "total_evaporable_water_mm",
        "wetted_fraction", "crop_height_m", "kc_max",
    )
    result: dict[str, float | str] = {"method": "fao56_dual"}
    for key in required:
        result[key] = _finite(value.get(key), f"water_model.{key}")
    result["initial_surface_depletion_mm"] = _finite(
        value.get("initial_surface_depletion_mm", 0),
        "water_model.initial_surface_depletion_mm",
    )
    for key in ("depletion_fraction", "wetted_fraction"):
        if result[key] > 1:
            raise ValueError(f"water_model.{key} must be between 0 and 1.")
    if result["depletion_fraction"] == 1:
        raise ValueError("water_model.depletion_fraction must be less than 1.")
    if result["wetted_fraction"] == 0:
        raise ValueError("water_model.wetted_fraction must be greater than 0.")
    if result["readily_evaporable_water_mm"] > result["total_evaporable_water_mm"]:
        raise ValueError("Readily evaporable water cannot exceed total evaporable water.")
    if result["initial_surface_depletion_mm"] > result["total_evaporable_water_mm"]:
        raise ValueError("Initial surface depletion cannot exceed total evaporable water.")
    result["source"] = str(value.get("source") or SOURCE)
    result["source_url"] = str(value.get("source_url") or SOURCE_URL)
    return result


def basal_coefficient(day_index: int, stage_days: list[int], initial: float,
                      mid: float, end: float) -> float:
    initial_days, development_days, mid_days, late_days = stage_days
    if day_index < initial_days:
        return initial
    if day_index < initial_days + development_days:
        progress = (day_index - initial_days + 1) / development_days
        return initial + (mid - initial) * progress
    if day_index < initial_days + development_days + mid_days:
        return mid
    progress = (day_index - initial_days - development_days - mid_days + 1) / late_days
    return mid + (end - mid) * min(1, progress)


def dual_coefficient_day(*, et0_mm: float, water_mm: float, capacity_mm: float,
                         surface_depletion_mm: float, day_index: int,
                         stage_days: list[int], config: dict[str, Any]) -> dict[str, float]:
    kcb = basal_coefficient(
        day_index, stage_days, float(config["kcb_initial"]),
        float(config["kcb_mid"]), float(config["kcb_end"]),
    )
    depletion = max(0.0, capacity_mm - water_mm)
    p = float(config["depletion_fraction"])
    raw = p * capacity_mm
    if capacity_mm <= 0 or depletion <= raw:
        ks = 1.0 if capacity_mm > 0 else 0.0
    else:
        ks = max(0.0, min(1.0, (capacity_mm - depletion) / ((1 - p) * capacity_mm)))
    kc_max = float(config["kc_max"])
    height = float(config["crop_height_m"])
    denominator = max(0.000001, kc_max - 0.15)
    fc = max(0.0, min(0.99, ((max(0.0, kcb - 0.15) / denominator) ** (1 + 0.5 * height))))
    few = max(0.01, min(1 - fc, float(config["wetted_fraction"])))
    rew = float(config["readily_evaporable_water_mm"])
    tew = float(config["total_evaporable_water_mm"])
    if surface_depletion_mm <= rew:
        kr = 1.0
    elif tew == rew:
        kr = 0.0
    else:
        kr = max(0.0, min(1.0, (tew - surface_depletion_mm) / (tew - rew)))
    ke = max(0.0, min(kr * max(0.0, kc_max - kcb), few * kc_max))
    transpiration = kcb * ks * et0_mm
    evaporation = ke * et0_mm
    return {
        "kcb": kcb, "ks": ks, "ke": ke, "kc_actual": kcb * ks + ke,
        "transpiration_mm": transpiration, "soil_evaporation_mm": evaporation,
        "crop_water_need_mm": transpiration + evaporation,
        "root_zone_depletion_mm": depletion, "readily_available_water_mm": raw,
        "surface_exposed_wetted_fraction": few,
    }
