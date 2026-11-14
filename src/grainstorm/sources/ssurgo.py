"""Location-based U.S. soil context from USDA NRCS Soil Data Access."""
from __future__ import annotations

from typing import Any

import requests


SERVICE = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SOURCE_PAGE = "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo"


class SsurgoError(RuntimeError):
    """Raised when the Soil Data Access service cannot answer a request."""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query(latitude: float, longitude: float) -> str:
    point = f"POINT({longitude:.8f} {latitude:.8f})"
    return f"""
SELECT TOP 50
  mu.mukey, mu.musym, mu.muname,
  c.cokey, c.compname, c.comppct_r, c.drainagecl, c.hydgrp,
  ch.chkey, ch.hzdept_r, ch.hzdepb_r,
  ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r,
  ch.om_r, ch.ph1to1h2o_r, ch.awc_r,
  (SELECT TOP 1 cht.texcl
   FROM chtexturegrp ctg
   INNER JOIN chtexture cht ON cht.chtgkey = ctg.chtgkey
   WHERE ctg.chkey = ch.chkey AND ctg.rvindicator = 'Yes') AS texture_class
FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{point}') s
INNER JOIN mapunit mu ON mu.mukey = s.mukey
INNER JOIN component c ON c.mukey = mu.mukey
INNER JOIN chorizon ch ON ch.cokey = c.cokey
WHERE c.majcompflag = 'Yes'
ORDER BY c.comppct_r DESC, ch.hzdept_r
""".strip()


def _weighted_topsoil(horizons: list[dict[str, Any]], depth_cm: float = 30.0) -> dict[str, Any]:
    fields = ("sand_percent", "silt_percent", "clay_percent", "organic_matter_percent", "ph_h2o")
    sums = {field: 0.0 for field in fields}
    weights = {field: 0.0 for field in fields}
    water_mm = 0.0
    water_depth = 0.0
    for horizon in horizons:
        top = max(0.0, float(horizon["top_depth_cm"]))
        bottom = min(depth_cm, float(horizon["bottom_depth_cm"]))
        thickness = max(0.0, bottom - top)
        if not thickness:
            continue
        for field in fields:
            value = horizon[field]
            if value is not None:
                sums[field] += value * thickness
                weights[field] += thickness
        awc = horizon["available_water_capacity_cm_cm"]
        if awc is not None:
            water_mm += awc * thickness * 10.0
            water_depth += thickness
    result = {
        field: (round(sums[field] / weights[field], 3) if weights[field] else None)
        for field in fields
    }
    result.update({
        "depth_cm": depth_cm,
        "available_water_capacity_mm": round(water_mm, 2) if water_depth else None,
        "covered_depth_cm": round(max(weights.values(), default=0.0), 2),
    })
    return result


def fetch_us_soil_context(latitude: float, longitude: float) -> dict[str, Any]:
    """Return the dominant mapped component at a U.S. point, or explicit no coverage."""
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    try:
        response = requests.post(
            SERVICE,
            json={"format": "JSON+COLUMNNAME", "query": _query(latitude, longitude)},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SsurgoError("USDA NRCS Soil Data Access request failed.") from exc
    except ValueError as exc:
        raise SsurgoError("USDA NRCS Soil Data Access returned invalid JSON.") from exc

    base = {
        "requested_point": {"latitude": latitude, "longitude": longitude},
        "dataset": {
            "provider": "USDA NRCS",
            "product": "Soil Survey Geographic Database (SSURGO) via Soil Data Access",
            "service": SERVICE,
            "source_page": SOURCE_PAGE,
            "geographic_coverage": "United States and covered territories",
        },
    }

    def unavailable() -> dict[str, Any]:
        return {
            **base,
            "status": "unavailable",
            "soil": None,
            "unavailable_properties": ["mapped_soil_properties", "current_nitrogen", "current_phosphorus", "current_potassium"],
            "note": "No SSURGO map unit covers this point. Use a country-appropriate soil source or field/lab test.",
        }

    if not isinstance(payload, dict) or payload.get("error"):
        raise SsurgoError("USDA NRCS Soil Data Access returned a service error.")
    if payload == {}:
        return unavailable()
    if "Table" not in payload:
        raise SsurgoError("USDA NRCS Soil Data Access omitted its result table.")
    table = payload.get("Table")
    # SDA represents a valid point outside U.S. coverage inconsistently as
    # {}, null, [], or a header-only table. All mean normal no-coverage.
    if table is None or table == []:
        return unavailable()
    if not isinstance(table, list):
        raise SsurgoError("USDA NRCS Soil Data Access returned an invalid table.")
    columns = table[0]
    if not isinstance(columns, list):
        raise SsurgoError("USDA NRCS Soil Data Access omitted column metadata.")
    rows = [dict(zip(columns, row)) for row in table[1:] if isinstance(row, list)]
    if not rows:
        return unavailable()

    first = rows[0]
    selected = [row for row in rows if row.get("mukey") == first.get("mukey") and row.get("cokey") == first.get("cokey")]
    horizons = []
    for row in selected:
        top, bottom = _number(row.get("hzdept_r")), _number(row.get("hzdepb_r"))
        if top is None or bottom is None or bottom <= top:
            continue
        horizons.append({
            "horizon_key": row.get("chkey"),
            "top_depth_cm": top,
            "bottom_depth_cm": bottom,
            "texture_class": row.get("texture_class"),
            "sand_percent": _number(row.get("sandtotal_r")),
            "silt_percent": _number(row.get("silttotal_r")),
            "clay_percent": _number(row.get("claytotal_r")),
            "organic_matter_percent": _number(row.get("om_r")),
            "ph_h2o": _number(row.get("ph1to1h2o_r")),
            "available_water_capacity_cm_cm": _number(row.get("awc_r")),
        })
    return {
        **base,
        "status": "complete",
        "soil": {
            "map_unit": {"key": first.get("mukey"), "symbol": first.get("musym"), "name": first.get("muname")},
            "dominant_component": {
                "key": first.get("cokey"), "name": first.get("compname"),
                "map_unit_percent": _number(first.get("comppct_r")),
                "drainage_class": first.get("drainagecl"), "hydrologic_group": first.get("hydgrp"),
            },
            "topsoil_0_30cm": _weighted_topsoil(horizons),
            "horizons": horizons,
        },
        "unavailable_properties": ["current_nitrogen", "current_phosphorus", "current_potassium"],
        "limitations": [
            "SSURGO describes mapped soil components; it is not a laboratory measurement of this field.",
            "Current N, P, and K are intentionally not inferred. Supply recent, depth-specific soil-test results.",
            "Topsoil values are thickness-weighted representative estimates for the dominant mapped component.",
        ],
    }
