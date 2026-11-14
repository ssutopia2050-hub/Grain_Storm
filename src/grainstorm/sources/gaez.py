"""On-demand FAO GAEZ v4 crop-suitability point sampling."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from typing import Any

import requests


GAEZ_IMAGE_SERVER = "https://gaez-services.fao.org/server/rest/services/res05/ImageServer"
BASELINE = {
    "time_period": "1981-2010",
    "climate_model": "CRUTS32",
    "scenario": "Historical",
    "water_supply": "Rainfed",
    "input_level": "High",
    "land_basis": "all land in grid cell",
}
CROPS = {
    "grain_maize": {"gaez_name": "Maize", "gaez_code": "mze", "raster_name": "sxHr_mze"},
    "grain_soybean": {"gaez_name": "Soybean", "gaez_code": "soy", "raster_name": "sxHr_soy"},
    "wheat": {"gaez_name": "Wheat", "gaez_code": "whe", "raster_name": "sxHr_whe"},
    "sorghum": {"gaez_name": "Sorghum", "gaez_code": "srg", "raster_name": "sxHr_srg"},
    "chickpea": {"gaez_name": "Chickpea", "gaez_code": "chk", "raster_name": "sxHr_chk"},
    "sunflower": {"gaez_name": "Sunflower", "gaez_code": "sfl", "raster_name": "sxHr_sfl"},
}


class GaezError(Exception):
    """Raised when GAEZ metadata or a point value cannot be retrieved safely."""


def suitability_class(index: float) -> dict[str, str]:
    """Translate the GAEZ 0-10000 suitability index to documented classes."""
    if isinstance(index, bool) or not 0 <= index <= 10000:
        raise ValueError("GAEZ suitability index must be between 0 and 10000.")
    if index >= 8000:
        return {"code": "VS", "label": "very_suitable", "attainable_yield_band": "80-100%"}
    if index >= 6000:
        return {"code": "S", "label": "suitable", "attainable_yield_band": "60-80%"}
    if index >= 4000:
        return {"code": "MS", "label": "moderately_suitable", "attainable_yield_band": "40-60%"}
    if index >= 2000:
        return {"code": "mS", "label": "marginally_suitable", "attainable_yield_band": "20-40%"}
    if index > 0:
        return {"code": "vmS", "label": "very_marginally_suitable", "attainable_yield_band": ">0-20%"}
    return {"code": "NS", "label": "not_suitable", "attainable_yield_band": "0%"}


def _payload(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise GaezError(f"GAEZ {operation} request failed.") from exc
    except ValueError as exc:
        raise GaezError(f"GAEZ {operation} returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise GaezError(f"GAEZ {operation} returned a service error.")
    return payload


@lru_cache(maxsize=len(CROPS))
def _resolve_raster(crop_id: str) -> dict[str, Any]:
    """Resolve and cache the exact official raster instead of trusting mosaic order."""
    spec = CROPS[crop_id]
    where = (
        f"name='{spec['raster_name']}' AND crop='{spec['gaez_name']}' "
        "AND year='1981-2010' AND model='CRUTS32' AND rcp='Historical' "
        "AND water_supply='Rainfed' AND input_level='High'"
    )
    try:
        response = requests.get(
            f"{GAEZ_IMAGE_SERVER}/query",
            params={
                "where": where,
                "outFields": (
                    "objectid,name,variable,file_description,year,model,rcp,crop,"
                    "water_supply,input_level,c02_fertilization,units,download_url,file_id"
                ),
                "returnGeometry": "false",
                "resultRecordCount": 2,
                "f": "json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GaezError("GAEZ catalog request failed.") from exc
    payload = _payload(response, "catalog")
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise GaezError(f"GAEZ catalog did not return one exact raster for {crop_id}.")
    attributes = features[0].get("attributes")
    if not isinstance(attributes, dict) or not isinstance(attributes.get("objectid"), int):
        raise GaezError(f"GAEZ catalog metadata is incomplete for {crop_id}.")
    return attributes


def _sample_crop(crop_id: str, latitude: float, longitude: float) -> dict[str, Any]:
    raster = _resolve_raster(crop_id)
    geometry = {
        "x": longitude,
        "y": latitude,
        "spatialReference": {"wkid": 4326},
    }
    mosaic_rule = {
        "mosaicMethod": "esriMosaicLockRaster",
        "lockRasterIds": [raster["objectid"]],
    }
    try:
        response = requests.get(
            f"{GAEZ_IMAGE_SERVER}/identify",
            params={
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPoint",
                "mosaicRule": json.dumps(mosaic_rule, separators=(",", ":")),
                "returnGeometry": "false",
                "returnCatalogItems": "false",
                "f": "json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GaezError(f"GAEZ point request failed for {crop_id}.") from exc
    payload = _payload(response, "point")
    raw_value = payload.get("value")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise GaezError(f"GAEZ returned no numeric suitability value for {crop_id}.") from exc
    try:
        classification = suitability_class(value)
    except ValueError as exc:
        raise GaezError(f"GAEZ returned an out-of-range suitability value for {crop_id}.") from exc
    location = payload.get("location") or geometry
    return {
        "crop_id": crop_id,
        "gaez_crop": raster["crop"],
        "gaez_crop_code": CROPS[crop_id]["gaez_code"],
        "status": "complete",
        "suitability_index_raw": value,
        "suitability_index_percent": round(value / 100, 2),
        "suitability_class": classification,
        "sampled_location": {"latitude": location.get("y"), "longitude": location.get("x")},
        "raster": {
            key: raster.get(key)
            for key in (
                "objectid", "file_id", "name", "variable", "year", "model", "rcp",
                "water_supply", "input_level", "c02_fertilization", "units", "download_url",
            )
        },
    }


def fetch_location_suitability(latitude: float, longitude: float,
                               crop_ids: list[str]) -> dict[str, Any]:
    """Sample the fixed historical rainfed/high-input baseline for selected crops."""
    if isinstance(latitude, bool) or not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if isinstance(longitude, bool) or not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if not crop_ids:
        raise ValueError("Select at least one crop.")
    if len(crop_ids) != len(set(crop_ids)):
        raise ValueError("crop_ids must not contain duplicates.")
    unknown = [crop_id for crop_id in crop_ids if crop_id not in CROPS]
    if unknown:
        raise ValueError(f"Unsupported crop profile: {unknown[0]}.")

    with ThreadPoolExecutor(max_workers=min(4, len(crop_ids))) as executor:
        crops = list(executor.map(lambda crop_id: _sample_crop(crop_id, latitude, longitude), crop_ids))
    return {
        "requested_point": {"latitude": latitude, "longitude": longitude},
        "dataset": {
            "provider": "FAO/IIASA",
            "product": "GAEZ v4 Module V suitability index",
            "service": GAEZ_IMAGE_SERVER,
            "documentation": "https://www.fao.org/gaez/gaezv4/en",
            "attribution": "FAO and IIASA Global Agro-Ecological Zones v4",
            "spatial_resolution": "5 arc-minutes (approximately 9 km at the equator)",
            "index_scale": "0-10000; divide by 100 for percentage",
            "baseline": BASELINE,
        },
        "crops": crops,
        "interpretation": (
            "This is a coarse historical agro-ecological suitability screening layer, not a field soil test, "
            "yield prediction, planting recommendation, or current-season condition."
        ),
    }
