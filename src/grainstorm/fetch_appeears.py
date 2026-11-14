"""Command-line point sampling for products available in NASA AppEEARS."""

import argparse
import json
import sys

from grainstorm.sources.appeears import AppEEARSClient, AppEEARSException


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover or fetch NASA/USGS land datasets through AppEEARS."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    products_parser = subparsers.add_parser("products", help="List available products.")
    products_parser.add_argument("--contains", help="Filter by product ID, platform, or description.")

    layers_parser = subparsers.add_parser("layers", help="List layers for a product/version.")
    layers_parser.add_argument("--product", required=True)

    fetch_parser = subparsers.add_parser("point", help="Fetch one point time series.")
    fetch_parser.add_argument("--product", required=True, help="AppEEARS product/version, e.g. MOD13Q1.061")
    fetch_parser.add_argument("--layers", required=True, help="Comma-separated product layer names.")
    fetch_parser.add_argument("--latitude", required=True, type=float)
    fetch_parser.add_argument("--longitude", required=True, type=float)
    fetch_parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    fetch_parser.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    fetch_parser.add_argument("--output-dir", default="data/raw/appeears")
    fetch_parser.add_argument("--timeout", type=int, default=3600, help="Maximum task wait in seconds.")

    args = parser.parse_args()
    try:
        client = AppEEARSClient()
        if args.command == "products":
            products = client.list_products()
            if args.contains:
                term = args.contains.casefold()
                products = [p for p in products if term in json.dumps(p).casefold()]
            print(json.dumps(products, indent=2))
            return
        if args.command == "layers":
            print(json.dumps(client.list_layers(args.product), indent=2))
            return

        metadata = client.fetch_point_sample(
            product=args.product,
            layers=[layer.strip() for layer in args.layers.split(",") if layer.strip()],
            latitude=args.latitude,
            longitude=args.longitude,
            start_date=args.start,
            end_date=args.end,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout,
        )
        print(json.dumps(metadata, indent=2))
    except (AppEEARSException, ValueError) as exc:
        print(f"AppEEARS error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
