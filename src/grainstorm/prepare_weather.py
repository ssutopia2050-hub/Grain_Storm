"""Join processed IMERG rainfall with ET0 for the crop planner."""

import argparse
import csv
import json
from pathlib import Path

from grainstorm.processing.planner_weather import merge_imerg_weather


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imerg-csv", required=True, type=Path)
    parser.add_argument("--et0-csv", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed/planner_weather_imerg.csv"))
    args = parser.parse_args()
    try:
        if args.output.resolve() in {args.imerg_csv.resolve(), args.et0_csv.resolve()}:
            raise ValueError("Output must be different from either input file.")
        with args.imerg_csv.open(newline="", encoding="utf-8-sig") as stream:
            imerg = list(csv.DictReader(stream))
        with args.et0_csv.open(newline="", encoding="utf-8-sig") as stream:
            et0 = list(csv.DictReader(stream))
        rows, metadata = merge_imerg_weather(imerg, et0)
        sources = {}
        for name, path in (("imerg", args.imerg_csv), ("et0", args.et0_csv)):
            sidecar = path.with_suffix(".metadata.json")
            sources[name] = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        rain_point = sources["imerg"].get("requested_point")
        et0_point = sources["et0"].get("request")
        offset = sources["et0"].get("response_metadata", {}).get("utc_offset_seconds")
        if offset is not None and offset != 0:
            raise ValueError("ET0 input must be aggregated using UTC days to match IMERG.")
        metadata["requested_coordinates_checked"] = False
        if rain_point and et0_point and all(k in rain_point and k in et0_point for k in ("latitude", "longitude")):
            if any(abs(float(rain_point[k]) - float(et0_point[k])) > 0.00001 for k in ("latitude", "longitude")):
                raise ValueError("IMERG and ET0 metadata have different requested coordinates.")
            metadata["requested_coordinates_checked"] = True
        metadata["source_metadata"] = sources
        metadata["input_files"] = {"imerg": str(args.imerg_csv), "et0": str(args.et0_csv)}
        metadata["et0_source"] = sources["et0"].get("product", "Supplied ET0 series")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["date", "rain_mm", "et0_mm"])
            writer.writeheader()
            writer.writerows(rows)
        sidecar = args.output.with_suffix(".metadata.json")
        sidecar.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Planner weather: {args.output}")
    print(f"Metadata: {sidecar}")
    print(f"Coverage: {rows[0]['date']} to {rows[-1]['date']} ({len(rows)} days)")


if __name__ == "__main__":
    main()
