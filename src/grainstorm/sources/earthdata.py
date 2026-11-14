"""Search and download NASA Earthdata granules with the official earthaccess client."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


class EarthdataError(RuntimeError):
    """Raised when Earthdata search or download fails."""


def fetch_granules(
    *,
    short_name: str,
    version: str,
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    bounding_box: tuple[float, float, float, float] | None = None,
    count: int = 20,
) -> dict[str, Any]:
    """Search and download a bounded selection of NASA product granules.

    This preserves the source files. It does not resample rasters or normalize
    product variables, since those operations need product-specific handling.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("Dates must use YYYY-MM-DD format.")
    if start > end:
        raise ValueError("Start date cannot be after end date.")
    if count < 1:
        raise ValueError("count must be at least 1.")
    if bounding_box is not None:
        west, south, east, north = bounding_box
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Bounding box must be west,south,east,north within coordinate limits.")

    try:
        import earthaccess
    except ImportError as exc:
        raise EarthdataError(
            "Install the project dependencies with `python -m pip install -e .` to enable NASA Earthdata downloads."
        ) from exc

    try:
        auth = earthaccess.login()
        if not auth.authenticated:
            raise EarthdataError("NASA Earthdata Login authentication was not completed.")
        search_options: dict[str, Any] = {
            "short_name": short_name,
            "version": version,
            "temporal": (start_date, end_date),
            "count": count,
        }
        if bounding_box is not None:
            search_options["bounding_box"] = bounding_box
        granules = earthaccess.search_data(**search_options)
        if not granules:
            raise EarthdataError("No granules matched the product, date range, and area.")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        downloaded = earthaccess.download(granules, str(destination))
    except EarthdataError:
        raise
    except Exception as exc:
        if "eula acceptance failure" in str(exc).casefold():
            raise EarthdataError(
                "GES DISC access needs one-time Earthdata authorization and EULA acceptance. "
                "In Earthdata Login, open Applications > Authorized Apps > Approve More Applications, "
                "search for 'NASA GESDISC DATA ARCHIVE', then authorize it and accept the agreement. "
                "Rerun this command after accepting."
            ) from exc
        raise EarthdataError(f"NASA Earthdata search/download failed: {exc}") from exc

    files = [str(Path(path)) for path in downloaded]
    manifest = {
        "provider": "NASA Earthdata / CMR",
        "short_name": short_name,
        "version": version,
        "requested_dates": {"start": start_date, "end": end_date},
        "bounding_box_wsen": list(bounding_box) if bounding_box else None,
        "granule_limit": count,
        "granules_found": len(granules),
        "files_downloaded": files,
        "notes": [
            "Downloaded files are native granules; variable scaling, fill values, QA, and spatial subsetting remain product-specific.",
            "A granule limit may return only part of a requested time series.",
        ],
    }
    manifest_path = Path(output_dir) / f"{short_name}_{version}_{start_date}_{end_date}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_file"] = str(manifest_path)
    return manifest


def fetch_gpm_imerg_daily(
    *,
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    bounding_box: tuple[float, float, float, float] | None = None,
    count: int = 20,
) -> dict[str, Any]:
    """Acquire daily Final IMERG V07 granules from NASA GES DISC."""
    return fetch_granules(
        short_name="GPM_3IMERGDF",
        version="07",
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        bounding_box=bounding_box,
        count=count,
    )
