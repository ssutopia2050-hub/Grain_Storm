"""Temporal screening and frontend planning sections with explicit evidence limits."""
from datetime import date, timedelta
from grainstorm.crops import get_profile


def temporal_summary(rows, metadata):
    rows = sorted(rows, key=lambda r: r["date"])
    spells, current = [], []
    def save():
        if len(current) >= 3:
            last = date.fromisoformat(current[-1]["date"])
            later = [r for r in rows if last < date.fromisoformat(r["date"]) <= last + timedelta(days=3)]
            spells.append({"start": current[0]["date"], "end": current[-1]["date"], "days": len(current),
                "rain_in_next_3_days_mm": round(sum(r["rain_mm"] for r in later), 2) if len(later) == 3 else None,
                "subsequent_rain_basis": "same historical/forecast/scenario dataset; never assumed known in advance"})
    previous = None
    for row in rows:
        day = date.fromisoformat(row["date"])
        if previous is not None and (day - previous).days != 1:
            save()
            current = []
        if row["rain_mm"] < 1:
            current.append(row)
        else:
            save()
            current = []
        previous = day
    save()
    windows = []
    for index in range(max(0, len(rows) - 13)):
        block = rows[index:index + 14]
        if (date.fromisoformat(block[-1]["date"]) - date.fromisoformat(block[0]["date"])).days != 13:
            continue
        rain, et0 = sum(r["rain_mm"] for r in block), sum(r["et0_mm"] for r in block)
        windows.append({"start": block[0]["date"], "end": block[-1]["date"],
                        "rain_mm": round(rain, 2), "et0_mm": round(et0, 2),
                        "rain_minus_et0_mm": round(rain - et0, 2)})
    windows.sort(key=lambda w: -w["rain_minus_et0_mm"])
    return {"data_kind": (metadata or {}).get("data_kind", "historical_replay"),
            "context_start": rows[0]["date"] if rows else None,
            "context_end": rows[-1]["date"] if rows else None,
            "dry_spell_definition": "at least 3 consecutive days below 1 mm/day; screening threshold, not crop damage threshold",
            "dry_spells": spells,
            "moisture_favorable_14day_windows": windows[:3],
            "period_limit": "Rain-minus-ET0 screening within acquired context only; not a crop optimum. Inspect context_start/context_end for actual coverage."}


def build_farm_plan(context):
    result = {"favorable_periods": {"status": "screening_only", "temporal_context": context.get("temporal_context"),
        "calendar_options": context["planning_estimates"]["calendar_alternatives"],
        "missing_for_optimum": ["Crop-specific temperature/frost limits and variety", "Deterministic date-search simulation", "Weather coverage outside requested dates"]},
        "rotation_scenarios": [], "growth_and_harvest_stages": [],
        "harvest_yield_assessment": {"probability_status": "not_calibrated", "harvest_success_probability": None,
            "yield_probability_distribution": None,
            "reason": "No calibrated crop-yield/harvest model or observed yield-outcome sample was supplied.",
            "scenario_estimates": context["planning_estimates"]["scenario_estimates"]},
        "irrigation_by_stage_and_gap": [],
        "dry_spell_plan": {"episodes": (context.get("temporal_context") or {}).get("dry_spells", []),
            "actions": ["Check root-zone water and stage-specific unmet demand before changing irrigation.",
                        "Refresh a near-term forecast before each irrigation decision; forecast rain may change.",
                        "Do not delay essential water solely because rain appears later in historical observations.",
                        "If root-zone water cannot bridge the forecast waiting period, verify supplemental water capacity.",
                        "Recalculate after actual rainfall; do not assume all rainfall infiltrates or offsets paddy losses."],
            "historical_warning": "Historical rain after a dry spell is hindsight, not an operational forecast."}}
    for index, scenario in enumerate(context["scenarios"]):
        result["rotation_scenarios"].append({"id": f"scenario.{index}", "name": scenario["name"],
            "calendar_status": scenario["calendar_status"], "sequence": scenario["schedule"],
            "gaps": scenario.get("fallow_periods", []), "water": scenario["water"],
            "nutrients": scenario["nutrients"], "economics": scenario["economics"]})
        for crop in scenario["schedule"]:
            duration = crop.get("duration_days")
            stages = crop.get("stage_water_assessment") or []
            if not stages and duration:
                profile = get_profile(crop["crop_id"])
                lengths = profile["growing_period"]["reference_calendars"][0]["stage_days"]
                scaled = [int(duration * n / sum(lengths)) for n in lengths]
                for n in range(duration - sum(scaled)):
                    scaled[n % 4] += 1
                cursor = date.fromisoformat(crop["planting_date"])
                for name, days in zip(["initial", "development", "mid_season", "late_season"], scaled):
                    if not days:
                        continue
                    stages.append({"stage": name, "start_date": cursor.isoformat(),
                        "end_date": (cursor + timedelta(days=days - 1)).isoformat(),
                        "crop_demand_mm": None, "irrigation_withdrawal_mm": None,
                        "basis": "FAO stage proportions scaled to supplied duration; estimated phenology only"})
                    cursor += timedelta(days=days)
            result["growth_and_harvest_stages"].append({"scenario_id": f"scenario.{index}", "crop_id": crop["crop_id"],
                "stages": stages, "planned_maturity_date": crop["harvest_date"],
                "harvest_options": [{"timing": timing, "date": (date.fromisoformat(crop["harvest_date"]) + timedelta(days=offset)).isoformat(),
                    "yield_t_ha": None, "harvest_success_probability": None,
                    "status": "requires_variety_maturity_grain_moisture_and_weather_validation"}
                    for timing, offset in (("7_days_before_planned_maturity", -7), ("planned_maturity", 0), ("7_days_after_planned_maturity", 7))],
                "harvest_limit": "Date sensitivity only; early harvest is not endorsed and no yield penalty or benefit is inferred."})
            result["irrigation_by_stage_and_gap"].append({"scenario_id": f"scenario.{index}", "crop_id": crop["crop_id"],
                "stages": [{**stage,
                    "irrigation_withdrawal_m3_for_field": None if stage.get("irrigation_withdrawal_mm") is None else round(stage["irrigation_withdrawal_mm"] * context["field"]["area_ha"] * 10, 2),
                    "unmet_crop_water_m3_for_field": None if stage.get("unmet_water_mm") is None else round(stage["unmet_water_mm"] * context["field"]["area_ha"] * 10, 2)} for stage in stages],
                "status": "modeled" if crop.get("stage_water_assessment") else "stage_water_unavailable_in_saved_analysis",
                "paddy_limit": crop.get("water_model_warning"), "gaps": scenario.get("fallow_periods", [])})
    return result
