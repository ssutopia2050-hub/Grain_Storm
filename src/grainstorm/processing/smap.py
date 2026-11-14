"""Normalize AppEEARS SMAP L4 point samples into a daily context series."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOTZONE_SUFFIX = "Geophysical_Data_sm_rootzone"
SURFACE_SUFFIX = "Geophysical_Data_sm_surface"


def normalize_smap_point_csv(
    input_csv: str | Path,
    *,
    output_csv: str | Path,
    input_metadata: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Daily-average valid SMAP L4 point observations, preserving missing data.

    The returned soil-moisture values remain volumetric water content (m³/m³).
    They are contextual observations and are not converted to plant-available
    water or used to infer nutrient amounts.
    """
    source_path = Path(input_csv)
    if not source_path.is_file():
        raise FileNotFoundError(f"Input AppEEARS CSV was not found: {source_path}")
    frame = pd.read_csv(source_path)
    date_column = "Date"
    rootzone_column = next(
        (column for column in frame.columns if column.endswith(ROOTZONE_SUFFIX)), None
    )
    surface_column = next(
        (column for column in frame.columns if column.endswith(SURFACE_SUFFIX)), None
    )
    missing_columns = [
        name for name, column in (
            (date_column, date_column if date_column in frame.columns else None),
            (ROOTZONE_SUFFIX, rootzone_column),
            (SURFACE_SUFFIX, surface_column),
        ) if column is None
    ]
    if missing_columns:
        raise ValueError(
            "CSV does not contain the expected SMAP point-sample columns: "
            + ", ".join(missing_columns)
        )

    timestamps = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    if timestamps.isna().any():
        raise ValueError("The AppEEARS CSV contains invalid timestamps.")

    normalized = pd.DataFrame({
        "date": timestamps.dt.strftime("%Y-%m-%d"),
        "soil_moisture_rootzone_m3_m3": pd.to_numeric(frame[rootzone_column], errors="coerce"),
        "soil_moisture_surface_m3_m3": pd.to_numeric(frame[surface_column], errors="coerce"),
    })
    for column in (
        "soil_moisture_rootzone_m3_m3",
        "soil_moisture_surface_m3_m3",
    ):
        normalized.loc[~normalized[column].between(0, 1), column] = float("nan")

    daily = (
        normalized.groupby("date", sort=True)
        .agg(
            soil_moisture_rootzone_m3_m3=("soil_moisture_rootzone_m3_m3", "mean"),
            soil_moisture_surface_m3_m3=("soil_moisture_surface_m3_m3", "mean"),
            rootzone_observations=("soil_moisture_rootzone_m3_m3", "count"),
            surface_observations=("soil_moisture_surface_m3_m3", "count"),
        )
        .reset_index()
    )
    daily["soil_moisture_rootzone_m3_m3"] = daily["soil_moisture_rootzone_m3_m3"].round(7)
    daily["soil_moisture_surface_m3_m3"] = daily["soil_moisture_surface_m3_m3"].round(7)

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output_path, index=False)

    source_metadata: dict[str, Any] = {}
    if input_metadata is not None and Path(input_metadata).is_file():
        source_metadata = json.loads(Path(input_metadata).read_text(encoding="utf-8"))
    output_metadata = {
        "provider": "NASA AppEEARS",
        "product": source_metadata.get("product", "SPL4SMGP.008"),
        "task_id": source_metadata.get("task_id"),
        "requested_coordinates": source_metadata.get("requested_coordinates"),
        "input_csv": str(source_path),
        "input_metadata": str(input_metadata) if input_metadata else None,
        "source_metadata": source_metadata,
        "output_csv": str(output_path),
        "time_handling": "UTC timestamps grouped by calendar date; daily values are arithmetic means of valid sub-daily samples.",
        "source_variables": {
            "soil_moisture_rootzone_m3_m3": {
                "layer": ROOTZONE_SUFFIX,
                "depth": "0-100 cm",
                "units": "m^3/m^3",
            },
            "soil_moisture_surface_m3_m3": {
                "layer": SURFACE_SUFFIX,
                "depth": "0-5 cm",
                "units": "m^3/m^3",
            },
        },
        "aggregation": "Daily means are kept null when no valid samples are available; observation counts are included.",
        "interpretation": "SMAP L4 gridded soil-moisture context, not a field soil test. Values are not converted to plant-available water or nutrients.",
        "raw_sample_count": int(len(frame)),
        "daily_row_count": int(len(daily)),
        "date_start_utc": daily["date"].min() if not daily.empty else None,
        "date_end_utc": daily["date"].max() if not daily.empty else None,
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(output_metadata, indent=2, allow_nan=False), encoding="utf-8")
    output_metadata["metadata_file"] = str(metadata_path)
    return daily, output_metadata
