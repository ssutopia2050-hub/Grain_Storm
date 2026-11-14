"""Short-range daily weather forecasts for near-term irrigation decisions."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import requests


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16


class ForecastError(RuntimeError):
    """Raised when operational forecast data cannot be used safely."""


def fetch_daily_forecast(latitude: float, longitude: float, start_date: str,
                         end_date: str, *, today: date | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    current = today or date.today()
    if start < current or end < start:
        raise ValueError("Forecast dates must be ordered and cannot begin in the past.")
    if end > current + timedelta(days=MAX_FORECAST_DAYS - 1):
        raise ValueError(f"Operational forecasts are limited to {MAX_FORECAST_DAYS} days.")
    try:
        response = requests.get(FORECAST_URL, params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "precipitation_sum,et0_fao_evapotranspiration,precipitation_probability_max",
            "timezone": "UTC",
            "precipitation_unit": "mm",
        }, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise ForecastError("Open-Meteo forecast request failed.") from exc
    except ValueError as exc:
        raise ForecastError("Open-Meteo forecast returned invalid JSON.") from exc
    try:
        daily = payload["daily"]
        times = daily["time"]
        rain = daily["precipitation_sum"]
        et0 = daily["et0_fao_evapotranspiration"]
        probability = daily["precipitation_probability_max"]
        if not (len(times) == len(rain) == len(et0) == len(probability)):
            raise ValueError()
        rows = []
        for index, raw_day in enumerate(times):
            day = date.fromisoformat(raw_day).isoformat()
            rain_value, et0_value = float(rain[index]), float(et0[index])
            probability_value = None if probability[index] is None else float(probability[index])
            if rain_value < 0 or et0_value < 0 or (
                probability_value is not None and not 0 <= probability_value <= 100
            ):
                raise ValueError()
            rows.append({
                "date": day,
                "rain_mm": rain_value,
                "et0_mm": et0_value,
                "precipitation_probability_percent": probability_value,
            })
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastError("Open-Meteo forecast payload is incomplete or invalid.") from exc
    expected = {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }
    if {row["date"] for row in rows} != expected:
        raise ForecastError("Operational forecast does not fully cover the requested dates.")
    metadata = {
        "provider": "Open-Meteo",
        "product": "Operational Weather Forecast API",
        "service": FORECAST_URL,
        "documentation": "https://open-meteo.com/en/docs",
        "issued_at_generation_time_ms": payload.get("generationtime_ms"),
        "model_timezone": payload.get("timezone"),
        "time_support": "UTC calendar days",
        "forecast_horizon_limit_days": MAX_FORECAST_DAYS,
        "limitations": [
            "Forecast skill decreases with lead time.",
            "This is gridded model guidance, not an on-farm weather observation.",
            "Re-fetch before acting because operational forecasts change with each model cycle.",
        ],
    }
    return rows, metadata
