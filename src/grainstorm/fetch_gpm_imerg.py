"""Bounded downloader for NASA's daily Final IMERG V07 product."""

import argparse
import json
import sys

from grainstorm.sources.earthdata import EarthdataError, fetch_gpm_imerg_daily


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search and download daily NASA GPM IMERG Final V07 granules."
    )
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    parser.add_argument(
        "--bbox", required=True, metavar="WEST,SOUTH,EAST,NORTH",
        help="Geographic bounding box; limits the granules searched.",
    )
    parser.add_argument("--max-granules", type=int, default=10)
    parser.add_argument("--output-dir", default="data/raw/gpm_imerg")
    args = parser.parse_args()

    try:
        bbox_values = tuple(float(value) for value in args.bbox.split(","))
        if len(bbox_values) != 4:
            raise ValueError("bbox needs west,south,east,north.")
        result = fetch_gpm_imerg_daily(
            start_date=args.start,
            end_date=args.end,
            output_dir=args.output_dir,
            bounding_box=bbox_values,
            count=args.max_granules,
        )
        print(json.dumps(result, indent=2))
    except (EarthdataError, ValueError) as exc:
        print(f"GPM IMERG error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
