"""USDA NASS Quick Stats crop yield and price records."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any

import requests


SERVICE = "https://quickstats.nass.usda.gov/api/api_GET/"
DOCUMENTATION = "https://quickstats.nass.usda.gov/api"
CROPS = {"grain_maize": "CORN", "grain_soybean": "SOYBEANS"}
BUSHEL_KG = {"grain_maize": 25.40117272, "grain_soybean": 27.2155422}
ACRES_PER_HECTARE = 2.4710538147
CONVERSION_SOURCE = "https://www.ams.usda.gov/sites/default/files/media/Book2.pdf"


class NassError(RuntimeError):
    """Raised when Quick Stats cannot answer a configured request."""


def _numeric(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def _fetch(api_key: str, crop_id: str, state_alpha: str, year: int,
           statistic: str) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "format": "JSON",
        "source_desc": "SURVEY",
        "sector_desc": "CROPS",
        "commodity_desc": CROPS[crop_id],
        "statisticcat_desc": statistic,
        "agg_level_desc": "STATE",
        "state_alpha": state_alpha,
        "year": str(year),
        "freq_desc": "ANNUAL",
        "domain_desc": "TOTAL",
    }
    try:
        response = requests.get(SERVICE, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise NassError("USDA NASS Quick Stats request failed.") from exc
    except ValueError as exc:
        raise NassError("USDA NASS Quick Stats returned invalid JSON.") from exc
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        message = payload.get("error") if isinstance(payload, dict) else None
        raise NassError(f"USDA NASS Quick Stats returned no data array{': ' + str(message) if message else '.'}")
    return [{
        "crop_id": crop_id,
        "statistic": statistic.lower().replace(" ", "_"),
        "value": _numeric(row.get("Value")),
        "raw_value": row.get("Value"),
        "unit": row.get("unit_desc"),
        "short_description": row.get("short_desc"),
        "production_practice": row.get("prodn_practice_desc"),
        "utilization": row.get("util_practice_desc"),
        "reference_period": row.get("reference_period_desc"),
        "state": row.get("state_name"),
        "year": int(row["year"]) if str(row.get("year", "")).isdigit() else year,
        "load_time": row.get("load_time"),
    } for row in records if isinstance(row, dict)]


def fetch_us_crop_statistics(state_alpha: str, year: int, crop_ids: list[str],
                             api_key: str | None = None) -> dict[str, Any]:
    state_alpha = state_alpha.strip().upper()
    if len(state_alpha) != 2 or not state_alpha.isalpha():
        raise ValueError("state_alpha must be a two-letter U.S. state code.")
    if not 1900 <= year <= 2200:
        raise ValueError("year is outside the supported range.")
    if not crop_ids or len(crop_ids) != len(set(crop_ids)):
        raise ValueError("crop_ids must be a non-empty array without duplicates.")
    unknown = [crop_id for crop_id in crop_ids if crop_id not in CROPS]
    if unknown:
        raise ValueError(f"Unsupported crop profile: {unknown[0]}.")
    key = api_key or os.getenv("NASS_QUICKSTATS_API_KEY")
    base = {
        "request": {"state_alpha": state_alpha, "year": year, "crop_ids": crop_ids},
        "dataset": {"provider": "USDA NASS", "product": "Quick Stats",
                    "service": SERVICE, "documentation": DOCUMENTATION,
                    "geographic_coverage": "United States"},
    }
    if not key:
        return {
            **base, "status": "auth_required", "records": [],
            "configuration": "Set NASS_QUICKSTATS_API_KEY on the backend; never expose the key in frontend code.",
        }
    jobs = [(crop_id, statistic) for crop_id in crop_ids for statistic in ("YIELD", "PRICE RECEIVED")]
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as executor:
        batches = list(executor.map(
            lambda job: _fetch(key, job[0], state_alpha, year, job[1]), jobs))
    records = [record for batch in batches for record in batch]
    selected_baselines = []
    for crop_id in crop_ids:
        final_yields = [record for record in records
                        if record["crop_id"] == crop_id and record["statistic"] == "yield"
                        and record["reference_period"] == "YEAR"
                        and record["unit"] == "BU / ACRE"
                        and (crop_id != "grain_maize" or record["utilization"] == "GRAIN")
                        and record["value"] is not None]
        final_prices = [record for record in records
                        if record["crop_id"] == crop_id and record["statistic"] == "price_received"
                        and record["reference_period"] == "MARKETING YEAR"
                        and record["unit"] == "$ / BU" and record["value"] is not None]
        if len(final_yields) != 1 or len(final_prices) != 1:
            continue
        yield_record, price_record = final_yields[0], final_prices[0]
        bushel_kg = BUSHEL_KG[crop_id]
        yield_t_ha = yield_record["value"] * bushel_kg / 1000 * ACRES_PER_HECTARE
        price_per_tonne = price_record["value"] / bushel_kg * 1000
        selected_baselines.append({
            "crop_id": crop_id,
            "selection_status": "complete",
            "yield_t_ha": round(yield_t_ha, 4),
            "price_per_tonne": round(price_per_tonne, 2),
            "currency": "USD",
            "gross_revenue_per_ha": round(yield_t_ha * price_per_tonne, 2),
            "source_records": {"yield": yield_record, "price": price_record},
            "unit_conversion": {
                "bushel_kg": bushel_kg,
                "acres_per_hectare": ACRES_PER_HECTARE,
                "source": CONVERSION_SOURCE,
            },
            "planner_economics_partial": {
                "expected_yield_t_ha": round(yield_t_ha, 4),
                "price_per_tonne": round(price_per_tonne, 2),
                "currency": "USD",
                "source": f"USDA NASS Quick Stats, {state_alpha} {year} final state baselines",
            },
            "missing_for_planner": ["variable_cost_per_ha"],
        })
    return {
        **base, "status": "complete", "records": records,
        "selected_baselines": selected_baselines,
        "note": "Records retain their USDA unit, utilization, production practice, and reference period. Select a semantically matching record before using it in economics.",
        "attribution": "This product uses the NASS API but is not endorsed or certified by NASS.",
    }
