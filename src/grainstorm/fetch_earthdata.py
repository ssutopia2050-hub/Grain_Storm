"""Bounded downloader for any NASA Earthdata collection indexed in CMR."""

import argparse
import json
import sys

from grainstorm.sources.earthdata import EarthdataError, fetch_granules


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search and download a bounded set of NASA Earthdata granules."
    )
    parser.add_argument("--short-name", required=True, help="NASA collection short name.")
    parser.add_argument("--version", required=True, help="Collection version.")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    parser.add_argument(
        "--bbox", required=True, metavar="WEST,SOUTH,EAST,NORTH",
        help="Area filter; downloads native granules intersecting this area.",
    )
    parser.add_argument("--max-granules", type=int, default=10)
    parser.add_argument("--output-dir", default="data/raw/earthdata")
    args = parser.parse_args()

    try:
        bbox = tuple(float(value) for value in args.bbox.split(","))
        if len(bbox) != 4:
            raise ValueError("bbox needs west,south,east,north.")
        result = fetch_granules(
            short_name=args.short_name,
            version=args.version,
            start_date=args.start,
            end_date=args.end,
            output_dir=args.output_dir,
            bounding_box=bbox,
            count=args.max_granules,
        )
        print(json.dumps(result, indent=2))
    except (EarthdataError, ValueError) as exc:
        print(f"NASA Earthdata error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
