"""Command-line download for historical ERA5 water-balance inputs."""

import argparse
import json
from pathlib import Path

from grainstorm.sources.era5 import Era5Error, fetch_daily_era5_weather


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch daily ERA5 rainfall and reference ET0 for a location."
    )
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/era5_daily_water_balance.csv"),
    )
    args = parser.parse_args()

    try:
        dataframe, metadata, raw_payload = fetch_daily_era5_weather(
            args.latitude, args.longitude, args.start, args.end
        )
    except (Era5Error, ValueError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(args.output, index=False)
    args.output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8"
    )
    raw_path = args.output.with_suffix(".raw.json")
    raw_path.write_text(json.dumps(raw_payload, indent=2) + "\n", encoding="utf-8")
    print(f"Daily data: {args.output}")
    print(f"Metadata:   {args.output.with_suffix('.metadata.json')}")
    print(f"Raw reply:  {raw_path}")
    print(dataframe.head().to_string(index=False))


if __name__ == "__main__":
    main()
