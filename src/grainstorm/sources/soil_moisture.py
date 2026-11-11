"""Historical soil-moisture data from Open-Meteo's ERA5-Land archive."""

from datetime import date

import pandas as pd
import requests


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOIL_MOISTURE_VARIABLES = {
    "soil_moisture_0_to_7cm": "SOIL_MOISTURE_0_7CM",
    "soil_moisture_7_to_28cm": "SOIL_MOISTURE_7_28CM",
    "soil_moisture_28_to_100cm": "SOIL_MOISTURE_28_100CM",
    "soil_moisture_100_to_255cm": "SOIL_MOISTURE_100_255CM",
}
SOIL_MOISTURE_COLUMNS = tuple(SOIL_MOISTURE_VARIABLES.values())


class SoilMoistureError(Exception):
    """Raised when soil-moisture data cannot be retrieved or parsed."""


def _validate_inputs(latitude: float, longitude: float, start_date: str, end_date: str) -> None:
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc

    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("Dates must use YYYY-MM-DD format.")

    if start > end:
        raise ValueError("Start date cannot be after end date.")


def fetch_hourly_soil_moisture(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    timezone: str = "UTC",
) -> tuple[pd.DataFrame, dict, dict]:
    """Fetch hourly ERA5-Land soil moisture at four modeled soil layers.

    Values are volumetric water content (m³/m³), not percent saturation.
    Returns the observations, request/response metadata, and original JSON.
    """
    _validate_inputs(latitude, longitude, start_date, end_date)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(SOIL_MOISTURE_VARIABLES),
        "models": "era5_land",
        "timezone": timezone,
    }

    try:
        response = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SoilMoistureError(f"Open-Meteo request failed: {exc}") from exc
    except ValueError as exc:
        raise SoilMoistureError("Open-Meteo returned invalid JSON.") from exc

    try:
        hourly = payload["hourly"]
        timestamps = pd.DatetimeIndex(pd.to_datetime(hourly["time"]))
        tz = payload.get("timezone", timezone)
        if timestamps.tz is None:
            timestamps = timestamps.tz_localize(tz)

        dataframe = pd.DataFrame({"time": timestamps})
        for api_name, column_name in SOIL_MOISTURE_VARIABLES.items():
            dataframe[column_name] = hourly[api_name]
        if dataframe.empty:
            raise ValueError("No hourly observations were returned.")
        dataframe = dataframe.sort_values("time").reset_index(drop=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise SoilMoistureError(f"Could not interpret Open-Meteo response: {exc}") from exc

    metadata = {
        "source": "Open-Meteo Historical Weather API",
        "model": "ERA5-Land",
        "units": "m³/m³ (volumetric water content)",
        "api_units": payload.get("hourly_units", {}),
        "layer_depths_cm": {
            "SOIL_MOISTURE_0_7CM": "0-7",
            "SOIL_MOISTURE_7_28CM": "7-28",
            "SOIL_MOISTURE_28_100CM": "28-100",
            "SOIL_MOISTURE_100_255CM": "100-255",
        },
        "request": params,
        "response_metadata": {
            key: payload.get(key)
            for key in ("latitude", "longitude", "elevation", "timezone", "utc_offset_seconds")
        },
    }
    return dataframe, metadata, payload


def inspect_hourly_soil_moisture(dataframe: pd.DataFrame) -> dict:
    """Report basic integrity and range issues without filling missing data."""
    if dataframe.empty:
        raise ValueError("Dataset is empty.")
    if "time" not in dataframe.columns:
        raise ValueError("Dataset must contain a 'time' column.")

    times = pd.to_datetime(dataframe["time"], errors="coerce", utc=True)
    report = {
        "total_observations": len(dataframe),
        "missing_columns": [
            column for column in SOIL_MOISTURE_COLUMNS
            if column not in dataframe.columns
        ],
        "invalid_timestamps": int(times.isna().sum()),
        "duplicate_timestamps": int(times.duplicated().sum()),
        "missing_timestamps": [],
        "missing_values": dataframe.isna().sum().to_dict(),
        "non_numeric_values": {},
        "out_of_range_values": {},
    }

    valid_times = pd.DatetimeIndex(times.dropna().unique()).sort_values()
    if len(valid_times) > 1:
        expected_times = pd.date_range(
            start=valid_times[0], end=valid_times[-1], freq="h", tz="UTC"
        )
        missing_times = expected_times.difference(valid_times)
        report["missing_timestamps"] = [
            timestamp.isoformat() for timestamp in missing_times
        ]

    for column in SOIL_MOISTURE_COLUMNS:
        if column not in dataframe.columns:
            continue
        values = pd.to_numeric(dataframe[column], errors="coerce")
        report["non_numeric_values"][column] = int(
            (dataframe[column].notna() & values.isna()).sum()
        )
        report["out_of_range_values"][column] = int(
            ((values < 0) | (values > 1)).sum()
        )

    has_issues = (
        bool(report["missing_columns"])
        or report["invalid_timestamps"] > 0
        or report["duplicate_timestamps"] > 0
        or bool(report["missing_timestamps"])
        or sum(report["missing_values"].values()) > 0
        or sum(report["non_numeric_values"].values()) > 0
        or sum(report["out_of_range_values"].values()) > 0
    )
    report["status"] = "REVIEW" if has_issues else "PASS"
    return report
