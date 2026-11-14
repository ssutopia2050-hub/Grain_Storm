"""Location-aware FAO GAEZ v4 crop-cycle point sampling."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache
import json
from typing import Any

import requests

from grainstorm.sources.gaez import GaezError


GAEZ_CALENDAR_SERVER = "https://gaez-services.fao.org/server/rest/services/res02/ImageServer"
WATER_SUPPLY = "Available water content of 200 mm/m (under rain-fed conditions)"
CROPS = {
    "grain_maize": {"gaez_name": "Maize", "prefix": "maiz200b", "root_depth_m": 0.9},
    "grain_soybean": {"gaez_name": "Soybean", "prefix": "soyb200b", "root_depth_m": 0.6},
}
ROOT_SOURCE = "https://www.fao.org/4/y5749e/y5749e0j.htm"


def _payload(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise GaezError(f"GAEZ calendar {operation} request failed.") from exc
    except ValueError as exc:
        raise GaezError(f"GAEZ calendar {operation} returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise GaezError(f"GAEZ calendar {operation} returned a service error.")
    return payload


@lru_cache(maxsize=len(CROPS))
def _resolve_calendar_rasters(crop_id: str) -> dict[str, dict[str, Any]]:
    spec = CROPS[crop_id]
    where = (
        f"crop='{spec['gaez_name']}' AND year='1981-2010' AND model='CRUTS32' "
        f"AND rcp='Historical' AND water_supply='{WATER_SUPPLY}' AND input_level='High' "
        "AND (variable='Beginning of crop growth cycle (day)' "
        "OR variable='Length of crop growth cycle (days)')"
    )
    try:
        response = requests.get(f"{GAEZ_CALENDAR_SERVER}/query", params={
            "where": where,
            "outFields": "objectid,name,variable,year,model,rcp,crop,water_supply,input_level,units,file_id,download_url",
            "returnGeometry": "false", "resultRecordCount": 4, "f": "json",
        }, timeout=30)
    except requests.RequestException as exc:
        raise GaezError("GAEZ calendar catalog request failed.") from exc
    features = _payload(response, "catalog").get("features")
    if not isinstance(features, list) or len(features) != 2:
        raise GaezError(f"GAEZ calendar did not return two exact rasters for {crop_id}.")
    result = {}
    for feature in features:
        attributes = feature.get("attributes")
        if not isinstance(attributes, dict) or not isinstance(attributes.get("objectid"), int):
            raise GaezError(f"GAEZ calendar metadata is incomplete for {crop_id}.")
        variable = attributes.get("variable")
        key = "start_day" if variable == "Beginning of crop growth cycle (day)" else "cycle_length"
        result[key] = attributes
    if set(result) != {"start_day", "cycle_length"}:
        raise GaezError(f"GAEZ calendar variables are incomplete for {crop_id}.")
    return result


def _identify(raster_id: int, latitude: float, longitude: float) -> int:
    geometry = {"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}
    rule = {"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [raster_id]}
    try:
        response = requests.get(f"{GAEZ_CALENDAR_SERVER}/identify", params={
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "geometryType": "esriGeometryPoint",
            "mosaicRule": json.dumps(rule, separators=(",", ":")),
            "returnGeometry": "false", "returnCatalogItems": "false", "f": "json",
        }, timeout=30)
    except requests.RequestException as exc:
        raise GaezError("GAEZ calendar point request failed.") from exc
    try:
        value = float(_payload(response, "point").get("value"))
    except (TypeError, ValueError) as exc:
        raise GaezError("GAEZ calendar returned a nonnumeric value.") from exc
    if not value.is_integer():
        raise GaezError("GAEZ calendar returned a non-whole-day value.")
    return int(value)


def _crop_calendar(crop_id: str, latitude: float, longitude: float, target_year: int) -> dict[str, Any]:
    rasters = _resolve_calendar_rasters(crop_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        start_future = executor.submit(_identify, rasters["start_day"]["objectid"], latitude, longitude)
        length_future = executor.submit(_identify, rasters["cycle_length"]["objectid"], latitude, longitude)
        start_day, duration = start_future.result(), length_future.result()
    if not 1 <= start_day <= 366 or not 1 <= duration <= 366:
        raise GaezError(f"GAEZ calendar returned an out-of-range value for {crop_id}.")
    planting = date(target_year, 1, 1) + timedelta(days=start_day - 1)
    if planting.year != target_year:
        planting = date(target_year, 12, 31)
    harvest = planting + timedelta(days=duration - 1)
    return {
        "crop_id": crop_id,
        "gaez_crop": CROPS[crop_id]["gaez_name"],
        "cycle_start_day_of_year": start_day,
        "cycle_length_days": duration,
        "planting_date_for_target_year": planting.isoformat(),
        "projected_harvest_date": harvest.isoformat(),
        "reference_root_depth_m": CROPS[crop_id]["root_depth_m"],
        "root_depth_source": ROOT_SOURCE,
        "planner_overrides": {
            "duration_days": duration,
            "root_depth_m": CROPS[crop_id]["root_depth_m"],
        },
        "rasters": {key: {field: (value.get(field).strip() if isinstance(value.get(field), str)
                                  else value.get(field)) for field in (
            "objectid", "file_id", "name", "variable", "year", "model", "rcp",
            "water_supply", "input_level", "units", "download_url",
        )} for key, value in rasters.items()},
    }


def fetch_location_crop_calendars(latitude: float, longitude: float,
                                  crop_ids: list[str], target_year: int) -> dict[str, Any]:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    if not crop_ids or len(crop_ids) != len(set(crop_ids)):
        raise ValueError("crop_ids must be a non-empty array without duplicates.")
    unknown = [crop_id for crop_id in crop_ids if crop_id not in CROPS]
    if unknown:
        raise ValueError(f"Unsupported crop profile: {unknown[0]}.")
    with ThreadPoolExecutor(max_workers=min(2, len(crop_ids))) as executor:
        crops = list(executor.map(
            lambda crop_id: _crop_calendar(crop_id, latitude, longitude, target_year), crop_ids))
    return {
        "requested_point": {"latitude": latitude, "longitude": longitude},
        "target_year": target_year,
        "dataset": {
            "provider": "FAO/IIASA",
            "product": "GAEZ v4 Module II crop growth cycle",
            "baseline": "CRUTS32 Historical 1981-2010, high input, rain-fed, AWC 200 mm/m",
            "spatial_resolution": "5 arc-minutes (approximately 9 km at the equator)",
            "service": GAEZ_CALENDAR_SERVER,
        },
        "crops": crops,
        "limitations": [
            "GAEZ provides a coarse grid-cell cycle anchor, not a locally validated planting window.",
            "The target-year dates project a historical day-of-year pattern; confirm variety and local advice.",
            "Reference rooting depths are conservative FAO balance parameters and may be restricted by local soil.",
        ],
    }
