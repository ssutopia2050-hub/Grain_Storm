"""Daily ERA5 rainfall and reference evapotranspiration via Open-Meteo."""

from datetime import date

import pandas as pd
import requests


ERA5_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


class Era5Error(Exception):
    """Raised when ERA5 weather data cannot be retrieved or parsed."""


def fetch_daily_era5_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict, dict]:
    """Fetch ERA5 daily rainfall and FAO reference ET0 in UTC.

    ERA5 is global reanalysis, not a field weather-station observation.
    Precipitation and ET0 are returned in millimetres per day.
    """
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

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "precipitation,et0_fao_evapotranspiration",
        "models": "era5",
        "timezone": "UTC",
        "timeformat": "iso8601",
        "precipitation_unit": "mm",
    }
    try:
        response = requests.get(ERA5_ARCHIVE_URL, params=params, timeout=90)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise Era5Error(f"ERA5 request failed: {exc}") from exc
    except ValueError as exc:
        raise Era5Error("Open-Meteo returned invalid JSON.") from exc

    try:
        hourly = payload["hourly"]
        times = pd.to_datetime(hourly["time"], utc=True, errors="raise")
        hourly_df = pd.DataFrame({
            "time": times,
            "rain_mm": pd.to_numeric(hourly["precipitation"], errors="coerce"),
            "et0_mm": pd.to_numeric(
                hourly["et0_fao_evapotranspiration"], errors="coerce"
            ),
        })
        if hourly_df.empty:
            raise ValueError("No hourly observations were returned.")
        daily = (
            hourly_df.set_index("time")
            .resample("D")
            .agg(
                rain_mm=("rain_mm", lambda values: values.sum(min_count=24)),
                et0_mm=("et0_mm", lambda values: values.sum(min_count=24)),
                hours_recorded=("rain_mm", "count"),
            )
            .reset_index()
        )
        daily["date"] = daily.pop("time").dt.strftime("%Y-%m-%d")
        daily = daily[["date", "rain_mm", "et0_mm", "hours_recorded"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise Era5Error(f"Could not interpret ERA5 response: {exc}") from exc

    metadata = {
        "source": "Open-Meteo Historical Weather API",
        "product": "ERA5 reanalysis",
        "variables": {
            "rain_mm": "precipitation (mm/day)",
            "et0_mm": "FAO-56 reference evapotranspiration (mm/day)",
        },
        "request": params,
        "response_metadata": {
            key: payload.get(key)
            for key in ("latitude", "longitude", "elevation", "timezone", "utc_offset_seconds")
        },
        "hourly_units": payload.get("hourly_units", {}),
        "quality_notes": "Days with fewer than 24 valid hourly values are kept as missing, not filled with zero.",
    }
    return daily, metadata, payload
