"""Extract daily GPM IMERG values at a requested point from native NetCDF4 granules."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _value_at_point(dataset: Any, variable_name: str, lon_index: int, lat_index: int) -> float | None:
    """Read a scalar at the requested grid indices, respecting variable dimensions and fill values."""
    if variable_name not in dataset.variables:
        return None
    variable = dataset.variables[variable_name]
    indices: list[int | slice] = []
    for dimension in variable.dimensions:
        if dimension.lower() in {"lon", "longitude"}:
            indices.append(lon_index)
        elif dimension.lower() in {"lat", "latitude"}:
            indices.append(lat_index)
        else:
            size = len(dataset.dimensions[dimension])
            if size != 1:
                raise ValueError(
                    f"Cannot select {variable_name}: unexpected non-spatial dimension {dimension}={size}."
                )
            indices.append(0)
    raw_value = variable[tuple(indices)] if indices else variable[...]
    if np.ma.is_masked(raw_value):
        return None
    value = float(np.asarray(raw_value).item())
    fill_values = [getattr(variable, "_FillValue", None), getattr(variable, "missing_value", None)]
    if not np.isfinite(value) or any(fill is not None and value == float(fill) for fill in fill_values):
        return None
    return value


def extract_gpm_daily_point(
    granule_paths: list[str | Path],
    *,
    latitude: float,
    longitude: float,
    output_csv: str | Path,
    manifest_path: str | Path | None = None,
    era5_csv: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract precipitation and available companion fields at the nearest IMERG pixel."""
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are out of range.")
    if not granule_paths:
        raise ValueError("Provide at least one GPM IMERG daily granule.")
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise RuntimeError(
            "GPM NetCDF processing needs netCDF4. Reinstall the project with `python -m pip install -e .`."
        ) from exc

    rows: list[dict[str, Any]] = []
    grid_center: dict[str, float] | None = None
    for granule_path in sorted(map(Path, granule_paths)):
        match = re.search(r"IMERG\.(\d{8})-", granule_path.name)
        if not match:
            raise ValueError(f"Could not read YYYYMMDD from granule name: {granule_path.name}")
        day = datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
        with Dataset(granule_path, mode="r") as dataset:
            if "lat" not in dataset.variables or "lon" not in dataset.variables:
                raise ValueError(f"Granule lacks one-dimensional lat/lon variables: {granule_path}")
            lats = np.asarray(dataset.variables["lat"][:], dtype=float).squeeze()
            lons = np.asarray(dataset.variables["lon"][:], dtype=float).squeeze()
            if lats.ndim != 1 or lons.ndim != 1:
                raise ValueError("Expected one-dimensional latitude and longitude coordinate arrays.")
            normalized_lon = ((lons - longitude + 180.0) % 360.0) - 180.0
            lat_index = int(np.nanargmin(np.abs(lats - latitude)))
            lon_index = int(np.nanargmin(np.abs(normalized_lon)))
            this_center = {"latitude": float(lats[lat_index]), "longitude": float(lons[lon_index])}
            if grid_center is not None and this_center != grid_center:
                raise ValueError("Granules do not share one IMERG grid cell at the requested point.")
            grid_center = this_center

            rows.append({
                "date": day,
                "gpm_precipitation_mm_day": _value_at_point(dataset, "precipitation", lon_index, lat_index),
                "gpm_random_error_mm_day": _value_at_point(dataset, "randomError", lon_index, lat_index),
                "gpm_valid_half_hourly_count": _value_at_point(dataset, "precipitation_cnt", lon_index, lat_index),
                "gpm_wet_half_hourly_count": _value_at_point(dataset, "precipitation_cnt_cond", lon_index, lat_index),
            })

    frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError("Duplicate granule dates found.")
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)

    comparison_path: str | None = None
    if era5_csv is not None:
        era5 = pd.read_csv(era5_csv)
        if not {"date", "rain_mm"}.issubset(era5.columns):
            raise ValueError("ERA5 comparison CSV must contain date and rain_mm columns.")
        era5 = era5[["date", "rain_mm"]].rename(columns={"rain_mm": "era5_rain_mm_day"})
        comparison = frame[["date", "gpm_precipitation_mm_day"]].merge(era5, on="date", how="inner")
        comparison["gpm_minus_era5_mm_day"] = (
            comparison["gpm_precipitation_mm_day"] - comparison["era5_rain_mm_day"]
        )
        comparison_path_obj = output_path.with_name(f"{output_path.stem}_era5_comparison.csv")
        comparison.to_csv(comparison_path_obj, index=False)
        comparison_path = str(comparison_path_obj)

    manifest: dict[str, Any] = {}
    if manifest_path is not None and Path(manifest_path).is_file():
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    metadata = {
        "provider": "NASA GPM IMERG Final Daily V07",
        "doi": "10.5067/GPM/IMERGDF/DAY/07",
        "input_manifest": str(manifest_path) if manifest_path else None,
        "source_manifest": manifest,
        "requested_point": {"latitude": latitude, "longitude": longitude},
        "selected_grid_cell_center": grid_center,
        "spatial_resolution": "0.1 degree",
        "time_support": "One daily estimate per granule, UTC day.",
        "variables": {
            "gpm_precipitation_mm_day": "precipitation; mm/day",
            "gpm_random_error_mm_day": "randomError; daily RMS error estimate in mm/day, not a precipitation amount",
            "gpm_valid_half_hourly_count": "precipitation_cnt; count of valid half-hourly retrievals",
            "gpm_wet_half_hourly_count": "precipitation_cnt_cond; count of half-hourly retrievals with precipitation >= 0.01 mm/hr",
        },
        "output_csv": str(output_path),
        "era5_comparison_csv": comparison_path,
        "interpretation": "IMERG and ERA5 rainfall are distinct gridded estimates. Compare them; do not treat either as a local gauge reading.",
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    metadata["metadata_file"] = str(metadata_path)
    return frame, metadata
