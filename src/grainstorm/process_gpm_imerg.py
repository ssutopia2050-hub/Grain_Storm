"""Extract a point-level daily series from downloaded GPM IMERG granules."""

import argparse
import json
import sys
from pathlib import Path

from grainstorm.processing.gpm_imerg import extract_gpm_daily_point


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the nearest GPM IMERG daily grid cell and optionally compare with ERA5."
    )
    parser.add_argument("--manifest", required=True, help="Manifest from grainstorm-fetch-gpm-imerg.")
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument("--era5-csv", help="Optional ERA5 daily CSV for matched-date comparison.")
    parser.add_argument(
        "--output",
        default="data/processed/gpm_imerg_daily_point.csv",
        help="Destination CSV path.",
    )
    args = parser.parse_args()

    try:
        manifest_path = Path(args.manifest)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        granules = manifest.get("files_downloaded", [])
        if not granules:
            raise ValueError("Manifest contains no downloaded granule paths.")
        frame, metadata = extract_gpm_daily_point(
            granules,
            latitude=args.latitude,
            longitude=args.longitude,
            output_csv=args.output,
            manifest_path=manifest_path,
            era5_csv=args.era5_csv,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"GPM processing error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Daily data: {metadata['output_csv']}")
    print(f"Metadata:   {metadata['metadata_file']}")
    if metadata["era5_comparison_csv"]:
        print(f"Comparison: {metadata['era5_comparison_csv']}")
    print(f"Selected cell: {metadata['selected_grid_cell_center']}")
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
