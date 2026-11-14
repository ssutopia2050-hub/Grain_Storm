"""Create a daily summary from an AppEEARS SMAP L4 point CSV."""

import argparse
import sys

from grainstorm.processing.smap import normalize_smap_point_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily-average AppEEARS SMAP L4 point-sample soil moisture."
    )
    parser.add_argument("input_csv", help="AppEEARS *-results.csv path.")
    parser.add_argument("--metadata", help="AppEEARS provenance JSON sidecar.")
    parser.add_argument(
        "--output",
        default="data/processed/smap_daily_soil_moisture.csv",
        help="Destination CSV path.",
    )
    args = parser.parse_args()
    try:
        daily, metadata = normalize_smap_point_csv(
            args.input_csv, output_csv=args.output, input_metadata=args.metadata
        )
    except (OSError, ValueError) as exc:
        print(f"SMAP processing error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Daily data: {metadata['output_csv']}")
    print(f"Metadata:   {metadata['metadata_file']}")
    print(daily.head().to_string(index=False))


if __name__ == "__main__":
    main()
