#!/usr/bin/env bash
# Historical pipeline example for the existing test point, not a crop calendar.
# Run in an interactive terminal so Earthdata can ask for credentials.
set -euo pipefail

grainstorm_task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$grainstorm_task_root"
grainstorm_task_python="$grainstorm_task_root/.venv/bin/python"
if [[ ! -x "$grainstorm_task_python" ]]; then
  echo "The project's .venv/bin/python is required. Install project dependencies first."
  exit 1
fi

# Check that the existing ET0 input is for this test point and the whole year
# before starting a large download. Never replace the original input files.
"$grainstorm_task_python" - <<'PY'
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

p = Path('data/processed/era5_daily_water_balance.csv')
rows = list(csv.DictReader(p.open()))
expected = {(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)}
if len(rows) != 366 or {r['date'] for r in rows} != expected:
    raise SystemExit('ERA5 input must contain all 366 unique dates of 2024.')
for r in rows:
    try:
        value = float(r['et0_mm'])
    except (KeyError, ValueError, TypeError):
        raise SystemExit(f"ET0 missing or invalid on {r['date']}.")
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f"ET0 missing or invalid on {r['date']}.")
metadata = json.loads(p.with_suffix('.metadata.json').read_text())
request = metadata['request']
if abs(float(request['latitude']) - 30.34) > 0.00001 or abs(float(request['longitude']) - 76.39) > 0.00001:
    raise SystemExit('ERA5 requested coordinates differ from this example (30.34, 76.39).')
if metadata['response_metadata']['utc_offset_seconds'] != 0:
    raise SystemExit('ERA5 must use UTC dates.')
print('ERA5 input ready: 366 UTC days with ET0 for the current test point.')
PY

"$grainstorm_task_python" -m grainstorm.fetch_gpm_imerg \
  --start 2024-01-01 --end 2024-12-31 \
  --bbox 76.3,30.2,76.5,30.5 --max-granules 366

# A successful search is not sufficient: require a file for every UTC day.
"$grainstorm_task_python" - <<'PY'
import json
import re
from pathlib import Path
from datetime import date, timedelta

manifest = json.loads(Path('data/raw/gpm_imerg/GPM_3IMERGDF_07_2024-01-01_2024-12-31_manifest.json').read_text())
files = [Path(p) for p in manifest['files_downloaded']]
dates = []
for p in files:
    match = re.search(r'IMERG\.(\d{8})-', p.name)
    if not match or not p.is_file() or p.stat().st_size == 0:
        raise SystemExit(f'Invalid or missing downloaded file: {p}')
    dates.append(match.group(1))
expected = {(date(2024, 1, 1) + timedelta(days=i)).strftime('%Y%m%d') for i in range(366)}
if len(dates) != 366 or set(dates) != expected:
    missing = sorted(expected - set(dates))
    raise SystemExit(f'Incomplete or duplicate IMERG coverage. Missing dates: {missing}. Rerun this script to retry.')
print('Download coverage ready: all 366 days.')
PY

"$grainstorm_task_python" -m grainstorm.process_gpm_imerg \
  --manifest data/raw/gpm_imerg/GPM_3IMERGDF_07_2024-01-01_2024-12-31_manifest.json \
  --latitude 30.34 --longitude 76.39 \
  --output data/processed/gpm_imerg_2024_daily_point.csv

"$grainstorm_task_python" -m grainstorm.prepare_weather \
  --imerg-csv data/processed/gpm_imerg_2024_daily_point.csv \
  --et0-csv data/processed/era5_daily_water_balance.csv \
  --output data/processed/planner_weather_imerg_2024.csv

"$grainstorm_task_python" - <<'PY'
import csv
from datetime import date, timedelta
from pathlib import Path

p = Path('data/processed/planner_weather_imerg_2024.csv')
rows = list(csv.DictReader(p.open()))
expected = {(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)}
if len(rows) != 366 or {r['date'] for r in rows} != expected:
    raise SystemExit('Prepared weather is incomplete. Do not use it for a full-year scenario.')
print(f'Ready: {p.resolve()} (366 days of IMERG rain and ERA5 ET0).')
PY
