"""Historical FAO GAEZ v4 downscaled actual-yield point baselines."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from typing import Any

import requests

from grainstorm.sources.gaez import GaezError


SERVER = "https://gaez-services.fao.org/server/rest/services/res06/ImageServer"
CROPS = {
    "grain_maize": "Maize", "grain_soybean": "Soybean", "wheat": "Wheat",
    "sorghum": "Sorghum", "chickpea": None, "sunflower": "Sunflower",
    "rice": "Wetland rice",
}
WATER_SUPPLY = {"rice": "Irrigated"}


def _payload(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise GaezError(f"GAEZ yield {operation} request failed.") from exc
    except ValueError as exc:
        raise GaezError(f"GAEZ yield {operation} returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise GaezError(f"GAEZ yield {operation} returned a service error.")
    return payload


@lru_cache(maxsize=len(CROPS))
def _raster(crop_id: str) -> dict[str, Any]:
    water_supply = WATER_SUPPLY.get(crop_id, "Rainfed")
    try:
        response = requests.get(f"{SERVER}/query", params={
            "where": f"crop='{CROPS[crop_id]}' AND year='2010' AND water_supply='{water_supply}' AND variable='Yield'",
            "outFields": "OBJECTID,Name,variable,year,crop,water_supply,units,download_url",
            "returnGeometry": "false", "resultRecordCount": 2, "f": "json",
        }, timeout=30)
    except requests.RequestException as exc:
        raise GaezError("GAEZ yield catalog request failed.") from exc
    features = _payload(response, "catalog").get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise GaezError(f"GAEZ yield did not return one exact raster for {crop_id}.")
    item = features[0].get("attributes")
    if not isinstance(item, dict) or not isinstance(item.get("OBJECTID"), int):
        raise GaezError(f"GAEZ yield metadata is incomplete for {crop_id}.")
    return item


def _sample(crop_id: str, latitude: float, longitude: float) -> dict[str, Any]:
    if CROPS[crop_id] is None:
        return {
            "crop_id": crop_id,
            "status": "unavailable",
            "historical_yield_t_ha": None,
            "economics_yield_input": None,
            "reason": "GAEZ v4 Module VI has no standalone 2010 rainfed chickpea yield raster.",
        }
    raster = _raster(crop_id)
    geometry = {"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}
    rule = {"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [raster["OBJECTID"]]}
    try:
        response = requests.get(f"{SERVER}/identify", params={
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "geometryType": "esriGeometryPoint",
            "mosaicRule": json.dumps(rule, separators=(",", ":")),
            "returnGeometry": "false", "returnCatalogItems": "false", "f": "json",
        }, timeout=30)
    except requests.RequestException as exc:
        raise GaezError(f"GAEZ yield point request failed for {crop_id}.") from exc
    try:
        value = float(_payload(response, "point").get("value"))
    except (TypeError, ValueError) as exc:
        raise GaezError(f"GAEZ yield returned no numeric value for {crop_id}.") from exc
    if value < 0:
        raise GaezError(f"GAEZ yield returned an invalid value for {crop_id}.")
    return {
        "crop_id": crop_id,
        "historical_yield_t_ha": round(value, 5),
        "economics_yield_input": {"expected_yield_t_ha": round(value, 5)},
        "raster": {key.lower(): (val.strip() if isinstance(val, str) else val)
                   for key, val in raster.items()},
    }


def fetch_location_yield_baselines(latitude: float, longitude: float,
                                   crop_ids: list[str]) -> dict[str, Any]:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    if not crop_ids or len(crop_ids) != len(set(crop_ids)):
        raise ValueError("crop_ids must be a non-empty array without duplicates.")
    unknown = [crop_id for crop_id in crop_ids if crop_id not in CROPS]
    if unknown:
        raise ValueError(f"Unsupported crop profile: {unknown[0]}.")
    with ThreadPoolExecutor(max_workers=min(4, len(crop_ids))) as executor:
        crops = list(executor.map(lambda crop_id: _sample(crop_id, latitude, longitude), crop_ids))
    return {
        "requested_point": {"latitude": latitude, "longitude": longitude},
        "dataset": {"provider": "FAO/IIASA", "product": "GAEZ v4 Module VI downscaled actual yield",
                    "year": 2010, "water_supply": "Rainfed except rice: Irrigated",
                    "units": "t/ha", "service": SERVER},
        "crops": crops,
        "limitations": [
            "This is a downscaled 2010 historical grid-cell baseline, not a current farm yield forecast.",
            "Chickpea has no standalone raster in this product and is returned as unavailable.",
            "Use local recent yield records when available; keep price and cost inputs separate and current.",
        ],
    }
