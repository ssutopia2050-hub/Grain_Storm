
# Grain Storm 

A generalized agricultural monitoring and environmental data analysis framework using NASA datasets.

See the [project TODO](docs/TODO.md) for current priorities and follow-up work.
Frontend developers should start with the [v1 API contract](docs/frontend_api_contract.md)
and its [copyable TypeScript definitions](docs/frontend-api-types.ts).
The normal product flow is now consolidated in the [single rotation-advice endpoint](docs/frontend_rotation_advice.md).
The current challenge alignment and resource shortlist are in
[challenge resource triage](docs/challenge_resources_triage.md).
The v1 crop pair and reference assumptions are documented in
[starter crop profiles](docs/crop_profiles_v1.md).

## Current Status

**Milestone 1: NASA POWER weather data acquisition — complete.**

**Milestone 2: Historical soil-moisture acquisition — initial connector added.**
The project can retrieve hourly ERA5-Land soil moisture at four modeled depths.
This is reanalysis data in volumetric units, not a field sensor reading or a
crop-specific root-zone estimate. See [the soil-moisture source notes](docs/soil_moisture.md).

Grain Storm currently supports downloading daily environmental observations from NASA POWER for a specified geographical coordinate and date range.

### Retrieved variables

| Parameter | Description |
|---|---|
| T2M | Temperature at 2 metres |
| PRECTOTCORR | Corrected precipitation |
| RH2M | Relative humidity at 2 metres |

## Architecture

```text
Grain_Storm/
├── data/
│   ├── raw/
│   └── processed/
├── docs/
├── notebooks/
├── tests/
└── src/
    └── grainstorm/
        ├── sources/
        │   └── power.py
        ├── cli.py
        └── __main__.py
```

- `sources/`: External data source integrations.
- `data/raw/`: Original API responses.
- `data/processed/`: Parsed datasets and metadata.
- `tests/`: Automated tests.

## Setup

Activate your Python environment and install dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Usage

Example NASA POWER request:

```bash
python -m grainstorm \
    --latitude 30.34 \
    --longitude 76.39 \
    --start 20240101 \
    --end 20240131
```

### Output

- Original API response: `data/raw/`
- Processed CSV: `data/processed/`
- Metadata JSON: `data/processed/`

### Crop sequence what-if planner (first prototype)

The planner compares user-defined crop sequences with a simple daily soil-water
budget and an explicit net mineral-nitrogen change per crop. It does not predict
yield, crop stress, or exact nutrient availability. Crop values in the demo are
synthetic and must not be used as farm recommendations.

Run the illustrative example:

```bash
python -m grainstorm.planner examples/planner_demo.json
```

Save the report as JSON:

```bash
python -m grainstorm.planner examples/planner_demo.json --output data/processed/planner_report.json
```

To exercise the optional soil-test, management, variety, derived nutrient,
irrigation-efficiency/limit/cost and missing-input features, run:

```bash
python -m grainstorm.planner examples/optional_frontend_inputs_demo.json
```

Replace the example rainfall, field properties, crop durations, water needs,
and net nitrogen changes with reviewed data before interpreting results. The
planner requires complete rainfall coverage for each modeled date and states
the model's assumptions. It reports both per-hectare nutrient quantities and
field-total quantities, plus estimated irrigation volume.

#### Fetch global ERA5 water-balance weather

The challenge-listed ERA5 resource is available through Open-Meteo without an
Earthdata account. Grain Storm can fetch daily rainfall and FAO reference
evapotranspiration (ET0), and the planner accepts that CSV as its weather
input:

```bash
grainstorm-fetch-era5 \
  --latitude 40.0 \
  --longitude -95.0 \
  --start 2024-04-01 \
  --end 2024-10-31
```

This writes `data/processed/era5_daily_water_balance.csv`, a metadata sidecar,
and the raw API response. To use it, create a scenario file with daily crop
`stage_kc` values and `stage_days` lengths, then run:

```bash
grainstorm-plan path/to/your_scenario.json \
  --weather-csv data/processed/era5_daily_water_balance.csv
```

If the `grainstorm-fetch-era5` or `grainstorm-plan` commands are not found
after updating the project, run `python -m pip install -e .` again inside the
active virtual environment.

Stage coefficients are applied to ERA5 ET0; use the crop profile reference
values only as broad baselines and enter local stage lengths. Rainfall and ET0
are reanalysis estimates, not field measurements.

### Python HTTP API for a future frontend

The calculation engine and weather retrieval are exposed through HTTP endpoints
so a frontend can send JSON requests later. Install the updated dependencies,
then start the development server:

```bash
python -m pip install -e .
uvicorn grainstorm.api:app --reload
```

Open `http://127.0.0.1:8000/docs` to inspect and try the API. Current endpoints:

- `GET /health` — service status.
- `GET /v1/crops` and `GET /v1/crops/{crop_id}` — list and inspect the six versioned, source-backed crop profiles.
- `POST /v1/crops/{crop_id}/planner-template` — turn a selected reference calendar and sourced nitrogen assumption into a planner crop entry.
- `POST /v1/crop-suitability` — sample the official FAO/IIASA GAEZ v4 historical suitability index for supported crops at a location.
- `POST /v1/crop-calendar` — sample GAEZ crop-cycle start/length and return FAO reference rooting depths for a target year.
- `POST /v1/crop-yield-baseline` — obtain a historical GAEZ 2010 rainfed yield baseline for the economics input.
- `POST /v1/context` — retrieve a historical location/date window with shared caching, coverage, units, and provenance.
- `POST /v1/weather/era5` — fetch daily ERA5 rainfall and ET0 for coordinates and dates.
- `POST /v1/plans` — calculate a plan from supplied weather rows, or fetch ERA5 by passing a `weather_source` object.

The API accepts crop coefficients, stage lengths, and soil/field assumptions as
request data. It does not silently choose a crop calendar or nutrient budget.
The crop-profile endpoint supplies FAO reference baselines, but deliberately
requires the caller to provide and name the source of the local net nitrogen
assumption before its template is ready for planning.

Rotation scenarios can now provide explicit gaps between crops, recurring
local planting windows, a planning horizon, and either fixed-gap or
next-valid-window scheduling. The response distinguishes feasible, infeasible,
and not-fully-evaluated calendars and returns the reason objects needed by the
frontend. When `fallow_kc` is supplied, gap rainfall and ET0 evaporation are
modeled; otherwise the fallow water balance is explicitly marked unconfigured.
Advanced scenarios may also include crop rooting depth, sourced N/P/K flows,
soil pH/organic-matter effects, pest/disease transition evidence, enterprise
budgets and user-weighted ranking. These remain transparent accounting and
screening tools, not validated yield or agronomic recommendation models.

The suitability endpoint uses a fixed comparable baseline: 1981–2010 CRUTS32
historical climate, rainfed conditions, high inputs, and all land in a
5-arc-minute grid cell. It is a broad agro-ecological screening layer, not a
field soil test, current condition, yield prediction, or planting instruction.

### Shared environmental context cache

Requests share a local SQLite database keyed by source, product/version,
location, and UTC date. Repeated or overlapping requests reuse stored days.
ERA5 and NASA POWER fetch only missing or expired intervals through their point
APIs. IMERG and SMAP reuse imported or fetched rows; missing or invalid dates
enqueue satellite subset jobs. Run the separate worker to process these jobs
using server-side Earthdata credentials. See [satellite setup and job flow](docs/satellite_context.md).
IMERG requests one native grid cell per day; SMAP requests point tables in
windows of at most 31 days. Neither route falls back to global-granule downloads.

Preload a selected pilot or crop-season window without downloading global
archives. This command reuses existing cache rows, fetches ERA5 as needed,
queues only missing IMERG/SMAP dates, processes up to four satellite jobs at
once, waits for AppEEARS, and prints a compact coverage summary:

```bash
python -m grainstorm.preload \
  --latitude 30.34 --longitude 76.39 \
  --start 2024-04-01 --end 2024-09-30 \
  --sources imerg smap era5 \
  --wait --concurrency 4
```

One preload is limited to 366 days and concurrency is capped at 8. Four is the
recommended default. Without `--wait`, it only fills synchronous sources and
queues satellite work for the already-running worker. Restart an older worker
after updating the project so it uses the parallel batch code. Preload only
locations and seasons selected for demos/pilots; ordinary API requests still
fetch new gaps on demand.

Start from the project root. The default database is
`data/cache/environment.sqlite3` (ignored by Git); set `GRAINSTORM_CACHE_DB` to
an absolute path to share it across server launches from other directories.
Only public environmental rows and source provenance are cached, not user or
farm-management inputs. This is a single-host prototype. Satellite jobs reserve
source/location/days transactionally to deduplicate overlapping requests; durable
task IDs support restart recovery. Run one satellite worker process for now;
that process handles up to four jobs concurrently by default. Multi-host
coordination and deduplication of concurrent ERA5/POWER fetches remain pending.

The existing local datasets have been registered: ERA5 for 2024, IMERG for
January 1–3 and July 19–August 1, and SMAP for January 2024 at the test point.
To register newly processed files (each must have a `.metadata.json` sidecar):

```bash
python -m grainstorm.context import --source imerg --csv data/processed/gpm_imerg_july_comparison.csv
python -m grainstorm.context import --source era5 --csv data/processed/era5_daily_water_balance.csv
python -m grainstorm.context import --source smap --csv data/processed/smap_daily_soil_moisture.csv
```

Try the API using the supplied three-day historical example:

```bash
curl -s http://127.0.0.1:8000/v1/context \
  -H 'Content-Type: application/json' \
  --data-binary @examples/context_request.json
```

The JSON accepts coordinates, `end_date`, and either `lookback_days` (default
90, inclusive of the end date) or `start_date`. Select any combination of
`imerg`, `era5`, `smap`, and `power` in `sources`. It reports records, missing
and invalid dates, source status, cache hits, fetched days, units, and provenance.
The `jobs` array identifies queued/running/waiting or failed subset requests;
`GET /v1/context/jobs/{job_id}` reports progress. Set `acquire_satellites: false`
(CLI `--no-acquire`) for a read-only satellite coverage check, or explicitly
set `retry_failed: true` (CLI `--retry-failed`) after resolving a failed acquisition.
HTTP 200 means the context response was assembled, not that every source is
complete: inspect each source's `status`. Future dates are rejected because
this endpoint serves historical context, not forecasts.

The equivalent command-line query is:

```bash
python -m grainstorm.context query \
  --latitude 30.34 --longitude 76.39 \
  --start 2024-01-01 --end 2024-01-03
```

IMERG data can be reused within its verified native 0.1-degree cell. SMAP,
ERA5, and POWER are matched to the requested point; neighboring coordinates
are not assumed equivalent. ERA5 and POWER records expire after seven days.
Imported satellite data are versioned historical snapshots without automatic
revision checks; reimport or refresh to replace them. `refresh: true`
(CLI `--refresh`) bypasses cached rows for that request: remote sources refetch,
while satellites queue subset jobs. Missing and invalid values remain
explicit; they never become zero rainfall.

The planner can now use this shared layer by passing
`weather_source.provider: "imerg_era5"` with coordinates and start/end dates.
IMERG supplies all rainfall and ERA5 supplies ET0. Missing or invalid coverage
returns HTTP 202 with job details while acquisition is active, or HTTP 422 if
it cannot proceed. Retry the same plan after acquisition completes. SMAP is available as
context, but is not silently converted into plant-available water or nutrients.
The original ERA5-only routes remain compatible and bypass this shared cache.

An eight-day **software demonstration with synthetic crop/soil assumptions**
uses the existing July weather, with no new satellite download:

```bash
curl -s http://127.0.0.1:8000/v1/plans \
  -H 'Content-Type: application/json' \
  --data-binary @examples/planner_cached_demo.json
```

### NASA AppEEARS point-data pipeline

AppEEARS can subset supported NASA/USGS land products to a coordinate and
return time-series tables with product quality layers. Its catalog can be
used to discover supported vegetation-index, soil-moisture, elevation, and
ECOSTRESS products. It does not make those measurements equivalent; keep each
product, layer, unit, and quality field distinct.

List products/layers, then request a point sample. If the two Earthdata
environment variables are unset, the command prompts for your NASA Earthdata
Login username and password (the password is hidden while typing):

```bash
grainstorm-appeears products --contains SMAP
grainstorm-appeears layers --product PRODUCT.VERSION
grainstorm-appeears point \
  --product PRODUCT.VERSION \
  --layers LAYER_NAME \
  --latitude 30.34 \
  --longitude 76.39 \
  --start 2024-01-01 \
  --end 2024-12-31
```

The product and layer names must come from the live AppEEARS catalog. Raw
downloads and a request/provenance sidecar are written under
`data/raw/appeears/`. Point samples are for coordinate-level context; field
boundaries and area-level raster analysis need a separate polygon workflow.

For the SMAP L4 root-zone and surface point sample, make a daily context CSV
without converting volumetric moisture to an unsupported soil-water estimate:

```bash
grainstorm-process-smap \
  data/raw/appeears/grain-storm-SPL4SMGP-008-SPL4SMGP-008-results.csv \
  --metadata data/raw/appeears/appeears_TASK_ID_metadata.json
```

The output is `data/processed/smap_daily_soil_moisture.csv` with daily means,
valid-sample counts, and a metadata sidecar. SMAP L4 here returns sub-daily
timestamps, so daily aggregation is explicit. These values remain regional
soil-moisture context; they are not field measurements, nutrient values, or
plant-available water.

### NASA GPM IMERG daily granules

GPM IMERG is acquired separately from GES DISC through NASA's `earthaccess`
client. The downloader fetches bounded sets of native daily Final V07
granules; the separate processor below extracts daily point rows. A granule cap avoids unintentionally fetching a
large archive range:

```bash
grainstorm-fetch-gpm-imerg \
  --start 2024-01-01 \
  --end 2024-01-10 \
  --bbox 76.3,30.2,76.5,30.5 \
  --max-granules 10
```

NASA Earthdata Login is required for download. On first GES DISC access, sign
in to Earthdata Login, open **Applications → Authorized Apps → Approve More
Applications**, search for **NASA GESDISC DATA ARCHIVE**, and authorize it while
accepting any agreement shown. NASA documents this application authorization
flow in its [Earthdata Login guide](https://urs.earthdata.nasa.gov/documentation/for_users/how_to_preauth_app).
NASA's daily Final IMERG V07 product reports precipitation in mm/day at
0.1-degree resolution. To extract the nearest grid cell and compare matched
days with ERA5, run:

```bash
python -m pip install -e .
grainstorm-process-gpm-imerg \
  --manifest data/raw/gpm_imerg/GPM_3IMERGDF_07_2024-01-01_2024-01-03_manifest.json \
  --latitude 30.34 \
  --longitude 76.39 \
  --era5-csv data/processed/era5_daily_water_balance.csv
```

This creates a point-level daily CSV, a provenance sidecar, and a comparison
CSV containing dates present in both sources. It records the nearest IMERG
grid-cell center; this can differ from the ERA5 grid cell. Keep the two
gridded estimates separate from local gauge observations. See the [GES DISC product
record](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDF_07/summary) and the
[earthaccess guide](https://earthaccess.readthedocs.io/en/stable/user/quick-start/).

The lower-level `grainstorm-fetch-earthdata` command uses the same bounded
NASA granule-search pipeline for other CMR-indexed products such as GLDAS or
GEDI. It expects a product short name and version from NASA Earthdata Search;
downloaded granules are retained in their native format for later processing.

### Use IMERG rainfall in the planner

Use the shared context cache above for the current workflow. The earlier
`scripts/prepare_imerg_2024.sh` is a legacy, opt-in bulk example, not a prerequisite
and never invoked by the API. Its bounding box filters granules without cropping
the downloaded global files. The current design instead prioritizes requested
date windows and reusable data through the satellite subset worker.
Real crop durations, seasonal gaps, and planting dates still need to be supplied.

Prepare a weather CSV with IMERG as the only rainfall source and ERA5 providing
reference evapotranspiration (ET0). Both inputs must represent the same requested
location and UTC dates. Native grid centers can differ. Available metadata
sidecars are retained; mismatched requested coordinates or a nonzero ET0 UTC
offset cause an error. Without coordinate metadata, spatial alignment remains
the caller's responsibility.

```bash
python -m grainstorm.prepare_weather \
  --imerg-csv data/processed/gpm_imerg_july_comparison.csv \
  --et0-csv data/processed/era5_daily_water_balance.csv \
  --output data/processed/planner_weather_imerg.csv
```

After reinstalling with `python -m pip install -e .`, the same command is
available as `grainstorm-prepare-weather`. Pass its output to `grainstorm-plan`
with `--weather-csv`. The planner copies the preparation metadata into its report.
The current July sample contains only **2024-07-19 through 2024-08-01**: it is
suitable for checking the input pipeline, but full crop rotations require IMERG
and ET0 coverage for every simulated day. Historical observations support
historical simulations; they are not future rainfall forecasts.

The merge retains IMERG dates only and never substitutes ERA5 rainfall or zero
for absent IMERG rainfall. Duplicate dates, missing ET0, and invalid amounts are
rejected. Partial IMERG observation counts are recorded in metadata; randomError
does not enter the water budget.

For the frontend, `POST /v1/plans` accepts an optional `imerg_rainfall` array
alongside existing `weather` rows (used for ET0) or `weather_source` (ERA5).
Each IMERG row uses the processed CSV column names, for example:

```json
{"date":"2024-07-19","gpm_precipitation_mm_day":1.775,"gpm_valid_half_hourly_count":48}
```

When `imerg_rainfall` is supplied, only those rainfall values enter the planner.
The response's `weather_metadata` identifies rainfall and ET0 separately. Raw
API inputs must already use the same requested location and UTC dates; the API
cannot infer a location from rainfall values. The existing ERA5-only API remains
available for clients that do not supply the optional IMERG array.

## Testing

```bash
python -m unittest discover -s tests -v
```

## Data-source coverage

- NASA POWER daily connector: implemented.
- ERA5 archive daily rain / ET0 connector: implemented.
- ERA5-Land soil-moisture connector: implemented.
- AppEEARS point-sampling adapter: implemented; select supported products and layers from its live catalog.
- GPM IMERG daily acquisition, point extraction, normalization, and planner rainfall integration: implemented.
- SMAP daily normalization and cached environmental context: implemented; conversion to planner soil-water inputs is not assumed.
- Shared historical context API and SQLite cache: implemented for ERA5, POWER, and imported IMERG/SMAP.
- Satellite subset queue, IMERG cloud OPeNDAP adapter, and resumable SMAP AppEEARS adapter: implemented and offline-tested; authenticated live verification requires locally configured Earthdata credentials.
- USDA SSURGO location-based mapped soil context: implemented for covered U.S. points; current N/P/K still require soil tests and non-U.S. adapters remain pending.
- USDA NASS state/year records for the supported crop catalog: implemented; set `NASS_QUICKSTATS_API_KEY` on the backend for U.S. pilots. Automatic metric economics selection currently applies where matching bushel-based yield and price records exist.

## Long-term direction

Build a reusable pipeline for acquiring, processing and analysing environmental datasets that can support agricultural monitoring across different geographical regions and crops.

## Farming practices as context

Future analyses should record field management alongside weather and soil
conditions. Farming practices can change how precipitation becomes soil water
available to crops: tillage and residue cover affect infiltration, runoff and
evaporation; cover crops can affect infiltration, soil cover and nutrient
cycling; irrigation adds water independently of rainfall; and fertilizer and
manure applications affect nutrient inputs and can influence soil acidity.
These effects depend on crop, soil, timing and local conditions, so a practice
should be treated as contextual data rather than a universal good/bad score.
[USDA NRCS soil-health guidance](https://www.nrcs.usda.gov/conservation-basics/soil/soil-health/soil-health-on-cropland)
and its [national agronomy manual](https://nrcs.stg.platform.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf)
describe these management pathways and their site-specific tradeoffs.

For each field and season, a future management dataset should prioritize:

- Crop and variety, planting date, and observed or estimated growth stage.
- Irrigation dates, amounts, and method, kept separate from rainfall.
- Tillage type/intensity and dates; surface residue or mulch cover.
- Cover-crop species and planting/termination dates; crop rotation history.
- Fertilizer/manure product, amount, application date, and method.

Record units, time, field/location, source, and unknown values explicitly.
These records can help explain differences between fields or seasons, but they
do not by themselves establish that a management practice caused a crop
response. See the proposed [three-person work schedule](docs/farming_practices_task_schedule.md).
