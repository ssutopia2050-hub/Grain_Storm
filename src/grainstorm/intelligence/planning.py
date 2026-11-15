"""Reproducible planning estimates; never current-season yield predictions."""
from datetime import date, timedelta
from grainstorm.intelligence.season import build_farm_plan


def enrich_context(context):
    area = context["field"]["area_ha"]
    crops = {c["crop_id"]: c for c in context["crops"]}
    windows, gaps = {}, None
    for e in context["evidence_catalog"]:
        if e["id"].startswith("input.generated."):
            item = e["value"]
            if item["path"].endswith(".planting_windows"):
                windows[item["path"].split(".")[1]] = item["value"]
            if item["path"] == "gaps_after_crops_days":
                gaps = item["value"]
    estimates, alternatives = [], []
    end = date.fromisoformat(context["field"]["planning_end"])
    for s in context["scenarios"]:
        production = []
        cursor = date.fromisoformat(context["field"]["planning_start"])
        schedule, complete = [], True
        for i, crop in enumerate(s["schedule"]):
            cid = crop["crop_id"]
            y = crops.get(cid, {}).get("historical_yield")
            production.append({"crop_id": cid, "yield_t_ha": y,
                "production_tonnes_for_field": None if y is None else round(y * area, 3),
                "basis": "historical_baseline_estimate" if y is not None else "unavailable",
                "formula": "historical_yield_t_ha * hectares",
                "limitation": "Historical benchmark; no current-season or stress-adjusted yield forecast."})
            production[-1]["nutrient_shortfalls_for_field_kg"] = {
                n: None if crop.get(f"{n}_shortfall_kg_ha") is None else round(crop[f"{n}_shortfall_kg_ha"] * area, 2)
                for n in ("n", "p", "k")}
            production[-1]["nutrient_interpretation"] = "Modeled elemental shortfalls, not fertilizer product doses; zero-credit assumptions do not establish nutrient deficiency."
            production[-1]["yield_sensitivity"] = ([
                {"scenario": label, "assumed_baseline_multiplier": multiplier,
                 "yield_t_ha": round(y * multiplier, 3), "production_tonnes_for_field": round(y * multiplier * area, 3)}
                for label, multiplier in (("20_percent_below_baseline", 0.8), ("historical_baseline", 1.0), ("20_percent_above_baseline", 1.2))
            ] if y is not None else [])
            production[-1]["sensitivity_limit"] = "Illustrative +/-20% yield assumptions only; not forecast bounds, probabilities or water-stress response."
            if not complete:
                continue
            if i:
                gap = gaps[i - 1] if gaps and i - 1 < len(gaps) else crop.get("gap_before_days")
                if gap is None:
                    complete = False
                    continue
                cursor += timedelta(days=gap)
            choices = windows.get(cid) or ([crop["matched_planting_window"]] if crop.get("matched_planting_window") else [])
            duration = crop.get("duration_days") or crops.get(cid, {}).get("calendar", {}).get("cycle_length_days")
            found = None
            while choices and cursor <= end:
                md = cursor.strftime("%m-%d")
                for w in choices:
                    a, b = w.get("start_month_day"), w.get("end_month_day")
                    if a and b and ((a <= md <= b) if a <= b else (md >= a or md <= b)):
                        found = cursor
                        break
                if found:
                    break
                cursor += timedelta(days=1)
            if not found or not duration:
                complete = False
                continue
            harvest = found + timedelta(days=duration - 1)
            if harvest > end:
                complete = False
                continue
            schedule.append({"crop_id": cid, "plant_on": found.isoformat(), "harvest_on": harvest.isoformat(), "duration_days": duration})
            cursor = harvest + timedelta(days=1)
        deficit = s["water"].get("unmet_water_mm")
        demand = sum(c.get("water_demand_mm") or 0 for c in s["schedule"])
        efficiency = context["field"].get("irrigation", {}).get("application_efficiency")
        estimates.append({"name": s["name"], "production_estimates": production,
            "uncovered_water_m3_for_field": None if deficit is None else round(deficit * area * 10, 2),
            "water_formula": "unmet_mm * hectares * 10",
            "modeled_water_coverage_percent": None if not demand or deficit is None else round(max(0, min(100, 100 * (1 - deficit / demand))), 2),
            "indicative_extra_irrigation_withdrawal_m3": (
                round(deficit * area * 10 / efficiency, 2) if deficit is not None and isinstance(efficiency, (int, float)) and 0 < efficiency <= 1 else None),
            "withdrawal_assumption": "Uncovered modeled crop demand divided by supplied application efficiency; scheduling and water availability still require verification.",
            "water_limit": "Deficit equivalent only; irrigation withdrawal needs efficiency and resimulation. Paddy losses excluded.",
            "economics": s["economics"]})
        alternatives.append({"name": s["name"], "calendar_fit_only": complete, "schedule": schedule,
            "status": "calendar_only_proposal" if complete else "no_complete_sequence_within_supplied_windows",
            "limitations": ["GAEZ windows are provisional unless locally confirmed.", "New dates need water/nutrient/economic resimulation."]})
    result = {"scenario_estimates": estimates, "calendar_alternatives": alternatives}
    for scenario in context["scenarios"]:
        economics = scenario.get("economics")
        if economics and economics.get("status") != "complete":
            for key in ("gross_crop_revenue_for_field", "additional_income_for_field", "crop_costs_for_field", "irrigation_cost_for_field", "total_cost_for_field"):
                economics[key] = None
    context["planning_estimates"] = result
    context["evidence_catalog"].append({"id": "planning.estimates", "source_path": "derived_by_python", "basis": "modeled", "value": result, "units": None, "source": "Grain Storm arithmetic and calendar screening"})
    context["evidence_catalog"].append({"id": "field.irrigation", "source_path": "calculation.report.field.irrigation", "basis": "assumed", "value": context["field"].get("irrigation", {}), "units": None, "source": "Simulation settings; physical availability unconfirmed"})
    context["evidence_catalog"].append({"id": "input.quality", "source_path": "input_resolution", "basis": "assumed", "value": context["input_quality"], "units": None, "source": "Backend generated-input assessment"})
    if context["field"]["irrigation_status"] == "unavailable":
        context["field"]["irrigation_status"] = "unknown"
    paths = []
    def visit(value, path, evidence):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, path + [key], evidence)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, path + [str(i)], evidence)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            paths.append({"evidence_reference": evidence["id"], "value_path": path, "value": value, "units": evidence["units"]})
    for e in context["evidence_catalog"]:
        if e["id"].endswith(".suitability"):
            crop = next((c for c in context["crops"] if e["id"] == f"crop.{c['crop_id']}.suitability"), None)
            override = crop["suitability"].get("baseline_override") if crop else None
            if override:
                e["value"]["baseline"] = {**(e["value"].get("baseline") or {}), **override}
        visit(e["value"], [], e)
    context["allowed_numerical_claims"] = paths
    context["farm_plan"] = build_farm_plan(context)
    return context
