"""Shared historical environmental context, cached per source/location/UTC day.

Only public environmental observations belong here; never store farm/user inputs.
Satellite cache misses enqueue bounded subsets for the separate worker.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from grainstorm.sources.era5 import fetch_daily_era5_weather
from grainstorm.sources.power import fetch_daily_point


SPECS = {
    "imerg": {"product": "GPM_3IMERGDF.07", "variables": {"gpm_precipitation_mm_day": "mm/day"}, "remote": False},
    "smap": {"product": "SPL4SMGP.008", "variables": {"soil_moisture_rootzone_m3_m3": "m3/m3", "soil_moisture_surface_m3_m3": "m3/m3"}, "remote": False},
    "era5": {"product": "Open-Meteo ERA5 adapter-v1", "variables": {"rain_mm": "mm/day", "et0_mm": "mm/day"}, "remote": True},
    "power": {"product": "NASA POWER daily AG UTC adapter-v1", "variables": {"T2M": "degC", "PRECTOTCORR": "mm/day", "RH2M": "%"}, "remote": True},
}


def days_between(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a.isoformat() != start or b.isoformat() != end or a > b:
        raise ValueError("Use an ordered YYYY-MM-DD date range.")
    if (b - a).days >= 3660:
        raise ValueError("Context requests are limited to 3660 days.")
    return [(a + timedelta(days=i)).isoformat() for i in range((b-a).days+1)]


def location_key(source: str, lat: float, lon: float) -> str:
    if source not in SPECS:
        raise ValueError(f"Unsupported source: {source}")
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid coordinates.")
    if source == "imerg":
        # Native 0.1-degree cells, lower edge inclusive, upper edge exclusive.
        x = min(3599, math.floor(round((lon + 180) * 10, 8)))
        y = min(1799, math.floor(round((lat + 90) * 10, 8)))
        return f"imerg-cell:{x}:{y}"
    # Do not guess SMAP EASE cells or merge elevation-adjusted weather points.
    return f"point:{float(lat):.12g}:{float(lon):.12g}"


def _records(frame):
    frame = frame.copy()
    frame["date"] = frame["date"].astype(str).str[:10]
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def _spans(days):
    first = last = None
    for day in days:
        current = date.fromisoformat(day)
        if last is None:
            first = last = current
        elif current == last + timedelta(days=1):
            last = current
        else:
            yield first.isoformat(), last.isoformat()
            first = last = current
    if last is not None:
        yield first.isoformat(), last.isoformat()


class ContextService:
    def __init__(self, db_path=None, fetchers=None, auto_acquire=True):
        self.db_path = Path(db_path or os.environ.get("GRAINSTORM_CACHE_DB", "data/cache/environment.sqlite3"))
        self.fetchers = fetchers if fetchers is not None else {"era5": fetch_daily_era5_weather, "power": fetch_daily_point}
        self.auto_acquire = auto_acquire
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS daily_context (
                source TEXT, product TEXT, location TEXT, day TEXT,
                row_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                stored_at REAL NOT NULL, expires_at REAL,
                PRIMARY KEY (source, product, location, day))""")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def put(self, source, lat, lon, rows, metadata, ttl_seconds=None):
        key = location_key(source, lat, lon)
        now = time.time()
        values, seen = [], set()
        for row in rows:
            day = row["date"]
            days_between(day, day)
            if day in seen:
                raise ValueError(f"Duplicate {source} date: {day}")
            seen.add(day)
            clean = dict(row)
            for variable in SPECS[source]["variables"]:
                value = clean.get(variable)
                if value is None or value == "" or str(value).lower() in {"nan", "na"}:
                    clean[variable] = None
                    continue
                if isinstance(value, bool):
                    raise ValueError(f"{variable} must be numeric, not a boolean.")
                number = float(value)
                if not math.isfinite(number) or number == -999 or (variable != "T2M" and number < 0):
                    clean[variable] = None
                elif (source == "smap" and number > 1) or (variable == "RH2M" and number > 100):
                    clean[variable] = None
                else:
                    clean[variable] = number
            values.append((source, SPECS[source]["product"], key, day,
                           json.dumps(clean, allow_nan=False), json.dumps(metadata, allow_nan=False),
                           now, now + ttl_seconds if ttl_seconds is not None else None))
        with self.connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO daily_context VALUES (?,?,?,?,?,?,?,?)", values)

    def _read(self, source, key, start, end):
        with self.connect() as conn:
            rows = conn.execute("SELECT day,row_json,metadata_json,stored_at,expires_at FROM daily_context WHERE source=? AND product=? AND location=? AND day BETWEEN ? AND ? ORDER BY day",
                                (source, SPECS[source]["product"], key, start, end)).fetchall()
        return {r[0]: r for r in rows}

    def query(self, lat, lon, start, end, sources=("imerg", "era5", "smap"), refresh=False,
              acquire_satellites=None, retry_failed=False):
        if acquire_satellites is None:
            acquire_satellites = self.auto_acquire
        days = days_between(start, end)
        if date.fromisoformat(end) > datetime.now(timezone.utc).date():
            raise ValueError("Context contains historical data; future dates require a forecast service.")
        if not sources or len(set(sources)) != len(sources):
            raise ValueError("Select one or more distinct sources.")
        keys = {source: location_key(source, lat, lon) for source in sources}
        result = {"requested_point": {"latitude": lat, "longitude": lon}, "start_date": start,
                  "end_date": end, "time_support": "UTC calendar days", "sources": {}}
        for source in sources:
            key = keys[source]
            cached = self._read(source, key, start, end)
            now = time.time()
            reusable = {d for d,r in cached.items() if not refresh and (r[4] is None or r[4] > now)}
            missing = [d for d in days if d not in reusable]
            errors, fetched = [], 0
            if SPECS[source]["remote"]:
                for a,b in _spans(missing):
                    try:
                        if source == "power":
                            frame, meta, _ = self.fetchers[source](lat, lon, a.replace('-', ''), b.replace('-', ''))
                        else:
                            frame, meta, _ = self.fetchers[source](lat, lon, a, b)
                        records = [r for r in _records(frame) if a <= r['date'] <= b]
                        self.put(source, lat, lon, records, {"retrieval": "point_api", "provider_metadata": meta}, ttl_seconds=7*86400)
                        fetched += len(records)
                        reusable.update(r['date'] for r in records)
                    except Exception as exc:
                        # Keep partial successful spans and report unavailable dates.
                        errors.append(f"{a} to {b}: {type(exc).__name__}")
            stored = self._read(source, key, start, end)
            records = [json.loads(stored[d][1]) for d in days if d in reusable and d in stored]
            unavailable = [d for d in days if d not in reusable or d not in stored]
            invalid = [r['date'] for r in records if any(r.get(v) is None for v in SPECS[source]['variables'])]
            provenance = []
            for d in days:
                if d in reusable and d in stored:
                    entry = {"metadata": json.loads(stored[d][2]), "stored_at_utc": datetime.fromtimestamp(stored[d][3], timezone.utc).isoformat()}
                    if entry not in provenance:
                        provenance.append(entry)
            status = "complete" if not unavailable and not invalid else "partial"
            if not records:
                status = "upstream_error" if errors else "acquisition_required"
            jobs = []
            if not SPECS[source]['remote'] and acquire_satellites and (unavailable or invalid):
                from grainstorm.satellite_jobs import SatelliteJobs
                jobs = SatelliteJobs(self).enqueue(source, lat, lon, unavailable + invalid, retry=retry_failed or refresh)
                if not records and any(j['status'] in {'queued', 'running', 'waiting'} for j in jobs):
                    status = 'acquisition_pending'
            result['sources'][source] = {"status": status, "product": SPECS[source]['product'],
                "location_key": key, "location_matching": "native_grid_cell" if source == "imerg" else "requested_point",
                "units": SPECS[source]['variables'], "records": records, "missing_dates": unavailable,
                "invalid_dates": invalid, "cache_hits": len(days)-len(missing), "fetched_days": fetched,
                "provenance": provenance, "errors": errors,
                "jobs": [{k: j[k] for k in ('id', 'source', 'status', 'start_date', 'end_date', 'error')} for j in jobs],
                "acquisition_required": bool(unavailable) and not SPECS[source]['remote'],
                "note": "Run grainstorm.satellite_jobs beside the API to process satellite subsets; inspect jobs for progress." if not SPECS[source]['remote'] else "Point API records expire after seven days for revision checks."}
        return result

    def import_csv(self, source, path):
        if source not in {"imerg", "smap", "era5"}:
            raise ValueError("Import supports processed IMERG, SMAP, and ERA5 files with metadata sidecars.")
        path = Path(path)
        meta = json.loads(path.with_suffix('.metadata.json').read_text())
        point = meta.get('requested_point') if source == 'imerg' else meta.get('requested_coordinates') if source == 'smap' else meta.get('request')
        if not point or not all(k in point for k in ('latitude', 'longitude')):
            raise ValueError("Metadata must contain the requested coordinates.")
        lat, lon = float(point['latitude']), float(point['longitude'])
        if source == 'imerg':
            manifest = meta.get('source_manifest', {})
            if manifest.get('short_name') != 'GPM_3IMERGDF' or manifest.get('version') != '07':
                raise ValueError("IMERG import requires GPM_3IMERGDF version 07 provenance.")
            center = meta.get('selected_grid_cell_center', {})
            if location_key(source, float(center['latitude']), float(center['longitude'])) != location_key(source, lat, lon):
                raise ValueError("IMERG selected cell does not match requested point.")
        if source == 'smap' and meta.get('product') != 'SPL4SMGP.008':
            raise ValueError("SMAP import requires SPL4SMGP.008.")
        if source == 'era5' and (meta.get('request', {}).get('models') != 'era5' or meta.get('response_metadata', {}).get('utc_offset_seconds') != 0):
            raise ValueError("ERA5 import requires ERA5 model and UTC provenance.")
        with path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if not {'date', *SPECS[source]['variables']}.issubset(reader.fieldnames or []):
                raise ValueError('Processed CSV is missing required variable columns.')
            rows = list(reader)
        if not rows:
            raise ValueError('Processed CSV is empty.')
        self.put(source, lat, lon, rows, {"retrieval": "processed_file_import", "file": str(path.resolve()),
                 "provider_metadata": meta, "freshness": "Ingestion time is not a verification of latest provider revision."},
                 ttl_seconds=7*86400 if source == 'era5' else None)
        return {"source": source, "imported_days": len(rows), "location_key": location_key(source, lat, lon)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='SQLite cache path (or GRAINSTORM_CACHE_DB).')
    commands = parser.add_subparsers(dest='command', required=True)
    imp = commands.add_parser('import')
    imp.add_argument('--source', choices=['imerg', 'smap', 'era5'], required=True)
    imp.add_argument('--csv', type=Path, required=True)
    query = commands.add_parser('query')
    query.add_argument('--latitude', type=float, required=True)
    query.add_argument('--longitude', type=float, required=True)
    query.add_argument('--start', required=True)
    query.add_argument('--end', required=True)
    query.add_argument('--sources', nargs='+', choices=list(SPECS), default=['imerg', 'era5', 'smap'])
    query.add_argument('--refresh', action='store_true')
    query.add_argument('--no-acquire', action='store_true', help='Report satellite gaps without scheduling retrieval.')
    query.add_argument('--retry-failed', action='store_true', help='Retry terminal satellite jobs for missing days.')
    args = parser.parse_args()
    try:
        service = ContextService(args.db)
        result = service.import_csv(args.source, args.csv) if args.command == 'import' else service.query(args.latitude, args.longitude, args.start, args.end, args.sources, args.refresh, acquire_satellites=not args.no_acquire, retry_failed=args.retry_failed)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
