
import argparse
import json
from pathlib import Path

from grainstorm.sources.power import (
    fetch_daily_point,
    NasaPowerError,
)


def main():
    parser = argparse.ArgumentParser(
        description="Download daily NASA POWER environmental data."
    )

    parser.add_argument(
        "--latitude",
        type=float,
        required=True,
        help="Location latitude.",
    )

    parser.add_argument(
        "--longitude",
        type=float,
        required=True,
        help="Location longitude.",
    )

    parser.add_argument(
        "--start",
        required=True,
        help="Start date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--end",
        required=True,
        help="End date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--output",
        default="data/processed/power_daily.csv",
        help="Path for the output CSV.",
    )

    args = parser.parse_args()

    print("\nGRAIN STORM | NASA POWER")
    print("-" * 40)
    print("Requesting environmental data...")

    try:
        dataframe, metadata, raw_payload = fetch_daily_point(
            latitude=args.latitude,
            longitude=args.longitude,
            start_date=args.start,
            end_date=args.end,
        )

        output_path = Path(args.output)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        dataframe.to_csv(output_path, index=False)

        metadata_path = output_path.with_suffix(".metadata.json")

        with metadata_path.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=4, default=str)

        raw_filename = (
            f"power_daily_{args.start}_{args.end}.json"
        )

        raw_path = Path("data/raw") / raw_filename
        raw_path.parent.mkdir(parents=True, exist_ok=True)

        with raw_path.open("w", encoding="utf-8") as file:
            json.dump(raw_payload, file, indent=4)

        print(f"Raw NASA response saved to: {raw_path}")

        print("\nDownload successful!")
        print(f"Observations: {len(dataframe)}")
        print(f"Variables: {list(dataframe.columns)}")
        print(f"CSV saved to: {output_path}")
        print(f"Metadata saved to: {metadata_path}")

        print("\nFirst five observations:")
        print(dataframe.head().to_string(index=False))

        print("\nMissing values:")
        print(dataframe.isna().sum().to_string())

    except (ValueError, NasaPowerError) as exc:
        print(f"\nERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
