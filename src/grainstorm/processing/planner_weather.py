"""Prepare planner weather with IMERG rainfall and separately supplied ET0."""

from datetime import date
import math
from typing import Any


def _indexed(rows: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
    if not rows:
        raise ValueError(f"{source} contains no daily rows.")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Each {source} row must be an object.")
        try:
            raw = row["date"]
            day = date.fromisoformat(raw).isoformat()
            if raw != day:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{source} rows require dates in YYYY-MM-DD format.") from exc
        if day in indexed:
            raise ValueError(f"Duplicate {source} date: {day}.")
        indexed[day] = row
    return indexed


def _nonnegative(value: Any, label: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError()
        return number
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite, nonnegative number.") from exc


def merge_imerg_weather(
    imerg_rows: list[dict[str, Any]], et0_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use IMERG dates as coverage; never fall back to another rainfall source.

    Inputs represent UTC days at the same requested location. ET0-only dates
    are excluded. The planner subsequently checks full scenario coverage.
    """
    rainfall = _indexed(imerg_rows, "IMERG")
    et0 = _indexed(et0_rows, "ET0")
    weather = []
    partial_dates = []
    for day, row in sorted(rainfall.items()):
        if day not in et0:
            raise ValueError(f"ET0 is missing on IMERG date {day}.")
        rain = _nonnegative(row.get("gpm_precipitation_mm_day"), f"IMERG rainfall on {day}")
        demand = _nonnegative(et0[day].get("et0_mm"), f"ET0 on {day}")
        count = row.get("gpm_valid_half_hourly_count")
        if count is not None and count != "":
            count = _nonnegative(count, f"IMERG sample count on {day}")
            if not count.is_integer() or not 1 <= count <= 48:
                raise ValueError(f"IMERG sample count on {day} must be an integer from 1 to 48.")
            if count < 48:
                partial_dates.append(day)
        weather.append({"date": day, "rain_mm": rain, "et0_mm": demand})
    return weather, {
        "rainfall_source": "NASA GPM IMERG supplied daily estimates",
        "et0_source": "Supplied ET0 series",
        "time_support": "UTC calendar day",
        "start_date": weather[0]["date"],
        "end_date": weather[-1]["date"],
        "days_available": len(weather),
        "et0_dates_excluded": len(set(et0) - set(rainfall)),
        "imerg_dates_with_partial_sampling": partial_dates,
        "rainfall_fallback": None,
        "notes": [
            "Use inputs for the same requested location and UTC day boundaries.",
            "IMERG randomError is retained in the original product, not used as rainfall or a planner input.",
            "These are historical weather inputs, not a future rainfall forecast.",
        ],
    }
