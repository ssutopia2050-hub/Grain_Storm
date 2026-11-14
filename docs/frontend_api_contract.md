# Grain Storm frontend API contract

This document describes the current `v1` backend contract for the frontend.
It reflects the running FastAPI application, not the intended final agronomic
model. The live schema is always available at `/openapi.json`, with interactive
documentation at `/docs`.

Companion TypeScript definitions: [frontend-api-types.ts](frontend-api-types.ts).
For the product UI, use the simplified [single rotation-advice endpoint](frontend_rotation_advice.md).
Working request examples: [context_request.json](../examples/context_request.json)
and [planner_cached_demo.json](../examples/planner_cached_demo.json). The
synthetic [rotation_calendar_demo.json](../examples/rotation_calendar_demo.json)
shows gaps, recurring windows and horizon feasibility without claiming local
agronomic dates. [decision_support_demo.json](../examples/decision_support_demo.json)
exercises the complete advanced input/output shape with deliberately synthetic
agronomic and financial numbers.

## Connection

- Local base URL: `http://127.0.0.1:8000`
- Content type for POST requests: `application/json`
- Dates: ISO calendar dates, `YYYY-MM-DD`
- Environmental day boundary: UTC
- Authentication: none in the current local prototype
- Allowed development origins: `localhost` or `127.0.0.1` on ports `5173` and
  `3000`. A deployed frontend origin must be added to backend CORS settings.
- Recommended frontend environment variable: `VITE_API_BASE_URL`

Never turn a missing or `null` measurement into zero. Zero rainfall is a valid
measurement; missing rainfall means the plan cannot be calculated.

## Frontend flow

```text
POST /v1/context
       |
       +-- all requested sources complete -> render environmental context
       |
       +-- active jobs returned -> show data-processing state
                                  poll GET /v1/context/jobs/{id}
                                  repeat POST /v1/context after completion

GET /v1/crops -> choose crop and reference calendar
POST /v1/crop-suitability -> screen chosen crops for the location
POST /v1/crop-calendar -> load location-aware cycle anchors and root depths
POST /v1/soil-context -> load mapped soil context when the point has SSURGO coverage
POST /v1/us-crop-statistics -> load state/year yield and price records for U.S. pilots
POST /v1/crops/{crop_id}/planner-template
              -> add a sourced local nitrogen assumption
              -> copy planner_crop into crop_catalog

POST /v1/plans
       |
       +-- 200 -> render scenario comparison
       |
       +-- 202 -> show processing state, poll returned jobs, retry same plan
       |
       +-- 422 -> show input/coverage error
```

The frontend should retain the original request while jobs are running. Job
completion does not push a result to the browser; retry the original request.

## Endpoint summary

| Method | Path | Purpose | Normal success |
|---|---|---|---|
| `GET` | `/health` | Backend availability | `200` |
| `GET` | `/v1/crops` | List supported crop profiles and calendar IDs | `200` |
| `GET` | `/v1/crops/{crop_id}` | Complete sourced crop reference profile | `200` |
| `POST` | `/v1/crops/{crop_id}/planner-template` | Build one planner crop entry | `200` |
| `POST` | `/v1/crop-suitability` | GAEZ location screening for supported crops | `200` |
| `POST` | `/v1/crop-calendar` | GAEZ cycle start/length plus FAO root reference | `200` |
| `POST` | `/v1/crop-yield-baseline` | Historical rainfed yield baseline for economics | `200` |
| `POST` | `/v1/soil-context` | USDA SSURGO mapped soil context for covered U.S. points | `200` |
| `POST` | `/v1/us-crop-statistics` | USDA NASS state yield/price records | `200` |
| `POST` | `/v1/rotation-advice` | Single polygon-to-rotation product workflow | `200` or `202` |
| `POST` | `/v1/context` | Historical environmental data and acquisition jobs | `200` |
| `GET` | `/v1/context/jobs/{job_id}` | Poll one IMERG/SMAP job | `200` |
| `POST` | `/v1/plans` | Compare crop sequences | `200` or `202` |
| `POST` | `/v1/weather/era5` | Low-level ERA5 fetch; diagnostic/advanced use | `200` |

The recommended product flow uses `/v1/context` and `/v1/plans`. The frontend
normally should not call `/v1/weather/era5` directly.

## 1. Health

`GET /health`

```json
{
  "status": "ok",
  "service": "grain-storm"
}
```

Use this for a simple connection indicator. It does not prove that NASA
providers or the background worker are available.

## 2. Crop profiles and planner templates

`GET /v1/crops` lists the current `grain_maize` and `grain_soybean` profiles.
Use `GET /v1/crops/{crop_id}` to populate the crop details and calendar picker.
The response includes FAO reference stage lengths and Kc values, limitations,
GAEZ identifiers for future suitability work, and clickable source URLs.

These are general baselines. The UI must label each calendar as a reference
and ask the farmer/team to confirm the local variety, planting season and days
to maturity.

Convert the selected calendar into a planner entry with:

`POST /v1/crops/grain_maize/planner-template`

```json
{
  "calendar_id": "fao_reference_125",
  "net_soil_n_change_kg_ha": -50,
  "nitrogen_source": "Reviewed local nutrient budget",
  "nitrogen_note": "Expected yield and fertilizer plan recorded separately"
}
```

The nitrogen number above only demonstrates the payload; it is not a crop
recommendation. The API has no universal nitrogen default. If nitrogen and its
source are omitted, the endpoint still returns the water/calendar template but
sets `ready_for_planner: false` and lists both as missing inputs. Do not submit
that incomplete `planner_crop` to `/v1/plans`.

When `ready_for_planner` is true, copy `planner_crop` under any display key in
`crop_catalog`. Keep its provenance fields unchanged; they are returned with
the crop result so the results screen can show which profile, calendar and
nitrogen assumption produced the calculation.

### Location suitability screening

Call `POST /v1/crop-suitability` after the user chooses a point:

```json
{
  "latitude": 30.34,
  "longitude": 76.39,
  "crop_ids": ["grain_maize", "grain_soybean"]
}
```

If `crop_ids` is omitted, both supported crops are queried. The current v1
endpoint intentionally fixes the comparison assumptions so two results remain
comparable: GAEZ v4, historical CRUTS32 climate for 1981–2010, rainfed, high
input, and the all-land suitability index. It samples the official FAO/IIASA
5-arc-minute raster (roughly 9 km at the equator); it does not download a
global raster.

Each crop returns `suitability_index_percent` and a documented class:

| Code | Meaning | GAEZ attainable-yield band |
|---|---|---|
| `VS` | Very suitable | 80–100% |
| `S` | Suitable | 60–80% |
| `MS` | Moderately suitable | 40–60% |
| `mS` | Marginally suitable | 20–40% |
| `vmS` | Very marginally suitable | greater than 0–20% |
| `NS` | Not suitable | 0% |

The percentage is a normalized agro-ecological suitability index relative to
the GAEZ scenario—not a predicted farm yield or probability of crop success.
Show the baseline assumptions and resolution beside the result. Do not use it
as a hidden pass/fail gate, and do not label it a current field condition.

### Location-aware crop calendar

`POST /v1/crop-calendar` accepts the same point/crop IDs plus `target_year`.
It samples GAEZ Module II `cbd` (cycle start day) and `cyl` (cycle length) and
returns concrete planting/harvest dates, planner duration overrides, and FAO
reference rooting depths. Its fixed v1 baseline is historical 1981–2010,
rain-fed, high-input, and 200 mm/m assumed available water capacity.

Treat the returned planting date as a coarse grid-cell anchor—not a validated
local window. Confirm it with local variety guidance before converting it into
`planting_windows`. Duration and root-depth overrides retain full raster/source
provenance.

`POST /v1/crop-yield-baseline` uses the same point/crop request and returns
FAO/IIASA GAEZ Module VI downscaled 2010 rainfed yield in t/ha. It can replace
the synthetic `expected_yield_t_ha`, but remains an old regional baseline—not a
current farm forecast. Prices and costs must come from a current market/local
source.

### Soil context

`POST /v1/soil-context` accepts `latitude` and `longitude`. For covered U.S.
points it returns the dominant SSURGO map component, horizon texture, organic
matter, pH, drainage, hydrologic group, and thickness-weighted 0–30 cm
available water capacity. For points outside SSURGO coverage, the normal `200`
response has `status: "unavailable"` and `soil: null`, so the frontend can ask
for another country-specific source or manual soil inputs.

These values describe mapped soil components rather than a field sample.
Current nitrogen, phosphorus, and potassium remain explicitly unavailable and
must come from a recent soil test; never infer them from SMAP or SSURGO.

### U.S. crop statistics

`POST /v1/us-crop-statistics` accepts a two-letter `state_alpha`, `year`, and
optional maize/soybean `crop_ids`. It returns the matching USDA NASS Quick Stats
`YIELD` and `PRICE RECEIVED` records without discarding their units, production
practice, utilization, reference period, or suppression codes. A suppressed
value such as `(D)` remains in `raw_value` while numeric `value` is `null`.

The backend must have `NASS_QUICKSTATS_API_KEY` configured. Without it the
endpoint returns `status: "auth_required"`; the secret must never be placed in
frontend code. These state aggregates are U.S.-only baselines and should not be
presented as a farm-specific price or yield.

## 3. Environmental context

`POST /v1/context`

### Request

```json
{
  "latitude": 30.34,
  "longitude": 76.39,
  "start_date": "2024-04-01",
  "end_date": "2024-09-30",
  "sources": ["imerg", "smap", "era5"],
  "refresh": false,
  "acquire_satellites": true,
  "retry_failed": false
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `latitude` | number | yes | `-90..90` |
| `longitude` | number | yes | `-180..180` |
| `end_date` | date string | yes | Historical date |
| `start_date` | date string | no | Use this or `lookback_days` |
| `lookback_days` | integer | no | `1..3660`, default `90`; inclusive of `end_date` |
| `sources` | array | no | Distinct values from `imerg`, `smap`, `era5`, `power`; default `imerg,era5,smap` |
| `refresh` | boolean | no | Default `false`; bypasses reusable cached rows |
| `acquire_satellites` | boolean | no | Default `true`; queue missing IMERG/SMAP data |
| `retry_failed` | boolean | no | Default `false`; use only after correcting a failed job |

When sending `start_date`, omit `lookback_days` entirely. The two fields cannot
be explicitly supplied together.

### Response envelope

```json
{
  "requested_point": {"latitude": 30.34, "longitude": 76.39},
  "start_date": "2024-02-01",
  "end_date": "2024-02-01",
  "time_support": "UTC calendar days",
  "sources": {
    "imerg": {},
    "smap": {},
    "era5": {}
  }
}
```

Each requested source contains:

| Field | Type | Frontend meaning |
|---|---|---|
| `status` | string | Source coverage state; see below |
| `product` | string | Exact backend product/version |
| `location_key` | string | Internal cache/grid identifier; diagnostic only |
| `location_matching` | `native_grid_cell` or `requested_point` | How the location was matched |
| `units` | object | Map of primary variable name to unit |
| `records` | array | Daily source-specific records |
| `missing_dates` | date string array | Requested dates without a reusable record |
| `invalid_dates` | date string array | Records present but missing a required primary value |
| `cache_hits` | integer | Dates reused from cache for this request |
| `fetched_days` | integer | ERA5/POWER dates fetched synchronously during this request |
| `jobs` | job summary array | Satellite acquisition work associated with remaining gaps |
| `errors` | string array | Sanitized provider error categories |
| `acquisition_required` | boolean | Satellite gaps exist; inspect `jobs` to know whether work is active |
| `provenance` | array | Full diagnostic source metadata; do not render by default |
| `note` | string | Backend operational/source note |

Source status values:

| Status | UI treatment |
|---|---|
| `complete` | All requested dates have valid primary values |
| `partial` | Some records exist, but dates are missing or invalid; active jobs may also exist |
| `acquisition_pending` | No records yet and at least one satellite job is active |
| `acquisition_required` | Data is absent and no active acquisition can currently complete it |
| `upstream_error` | ERA5/POWER request failed and no usable rows were returned |

Do not rely only on `status` for loading state. A partially cached range can
have `status: "partial"` while jobs are active. Compute:

```ts
const ACTIVE_JOB_STATES = new Set(["queued", "running", "waiting"]);
const isProcessing = source.jobs.some(job => ACTIVE_JOB_STATES.has(job.status));
```

### Daily records by source

IMERG rainfall:

```json
{
  "date": "2024-02-01",
  "gpm_precipitation_mm_day": 0.0,
  "gpm_random_error_mm_day": 2.7648,
  "gpm_valid_half_hourly_count": 48,
  "gpm_wet_half_hourly_count": 0
}
```

- Display rainfall from `gpm_precipitation_mm_day` in `mm/day`.
- `gpm_random_error_mm_day` is diagnostic uncertainty, not rainfall.
- A valid count below 48 means partial temporal sampling.

SMAP soil moisture:

```json
{
  "date": "2024-02-01",
  "soil_moisture_rootzone_m3_m3": 0.1827739,
  "soil_moisture_surface_m3_m3": 0.1490379,
  "rootzone_observations": 8,
  "surface_observations": 8
}
```

- Values are volumetric water content in `m³/m³`.
- Root-zone depth is approximately `0–100 cm`; surface depth is approximately
  `0–5 cm` for this product.
- These values are modeled gridded context, not soil nutrients or a field sensor.
- Older imported cache rows may encode observation counts as numeric strings;
  use `Number(value)` at the API boundary until response schemas are tightened.

ERA5 weather/water balance:

```json
{
  "date": "2024-02-01",
  "rain_mm": 0.0,
  "et0_mm": 2.37,
  "hours_recorded": 24
}
```

- `rain_mm`: ERA5 rainfall estimate in mm/day. It is context only when the
  planner uses IMERG rainfall.
- `et0_mm`: FAO reference evapotranspiration in mm/day; used by the planner.

NASA POWER:

```json
{
  "date": "2024-02-01",
  "T2M": 14.2,
  "PRECTOTCORR": 0.0,
  "RH2M": 66.5
}
```

- `T2M`: air temperature at 2 m, °C.
- `PRECTOTCORR`: corrected precipitation, mm/day.
- `RH2M`: relative humidity at 2 m, percent.

The context endpoint returns distinct products. The frontend should never add
or average their rainfall fields together.

## 4. Satellite job polling

`GET /v1/context/jobs/{job_id}`

```json
{
  "id": "085cb05060534a2ea6fe6fb0697d0aa7",
  "source": "smap",
  "status": "waiting",
  "start_date": "2024-02-01",
  "end_date": "2024-02-01",
  "error": null,
  "updated_at": 1794623168.4
}
```

Job states:

| State | Meaning | Terminal? |
|---|---|---|
| `queued` | Waiting for local worker | no |
| `running` | Worker is downloading/processing | no |
| `waiting` | NASA AppEEARS is processing SMAP | no |
| `complete` | All job days were cached | yes |
| `partial` | NASA returned missing/invalid values | yes |
| `auth_required` | Worker credentials need attention | yes |
| `failed` | Retrieval/validation failed | yes |

Poll active jobs approximately every 3–5 seconds. Stop polling terminal jobs.
When all jobs are `complete`, repeat the original context or plan request.
`updated_at` is currently Unix epoch seconds; it is operational metadata, not a
user-facing observation time.

## 5. Crop sequence planning

`POST /v1/plans`

For the product UI, use `weather_source.provider: "imerg_era5"`. IMERG becomes
the only rainfall source and ERA5 supplies ET0.

`/v1/plans` currently reads IMERG and ERA5 only. Fetch SMAP through
`/v1/context` for the environmental-context screen; the planner does not convert
SMAP moisture into its simplified soil-water capacity or initial soil water.

### Recommended request shape

```json
{
  "title": "Maize and soybean comparison",
  "field": {
    "name": "Demo field",
    "area_ha": 2.0,
    "soil_water_capacity_mm": 80,
    "initial_soil_water_mm": 45,
    "initial_mineral_n_kg_ha": 75,
    "irrigation_enabled": true,
    "irrigation_trigger_fraction": 0.5
  },
  "crop_catalog": {
    "maize": {
      "duration_days": 120,
      "stage_days": [25, 35, 40, 20],
      "stage_kc": [0.3, 0.8, 1.2, 0.6],
      "net_soil_n_change_kg_ha": -80
    },
    "soybean": {
      "duration_days": 110,
      "stage_days": [20, 30, 40, 20],
      "stage_kc": [0.4, 0.8, 1.15, 0.5],
      "net_soil_n_change_kg_ha": -20
    }
  },
  "scenarios": [
    {
      "name": "Maize then soybean",
      "start_date": "2024-04-01",
      "crops": ["maize", "soybean"]
    },
    {
      "name": "Soybean then maize",
      "start_date": "2024-04-01",
      "crops": ["soybean", "maize"]
    }
  ],
  "weather_source": {
    "provider": "imerg_era5",
    "latitude": 30.34,
    "longitude": 76.39,
    "start_date": "2024-04-01",
    "end_date": "2024-11-16"
  }
}
```

The numbers above demonstrate the JSON shape only. They are not reviewed farm
recommendations. The weather range must cover every simulated crop day.

### Field inputs

| Field | Type/unit | Rules |
|---|---|---|
| `name` | string | Optional label; defaults to `Unnamed field` |
| `area_ha` | number, ha | Required, greater than zero |
| `soil_water_capacity_mm` | number, mm | Required, nonnegative |
| `initial_soil_water_mm` | number, mm | Required, `0..soil_water_capacity_mm` |
| `initial_mineral_n_kg_ha` | number, kg/ha | Required, nonnegative; user/reviewed input |
| `irrigation_enabled` | boolean | Optional, default `false` |
| `irrigation_trigger_fraction` | number | Optional `0..1`, default `0.5` |

### Crop inputs

Each `crop_catalog` key is the ID used in scenario `crops` arrays.

- `duration_days`: positive whole number.
- `net_soil_n_change_kg_ha`: signed number; negative removes from the simple
  mineral-N pool, positive adds to it.
- Preferred water model: `stage_days` and `stage_kc`, each exactly four values.
  Stage days must be positive whole numbers and sum to `duration_days`.
- Basic alternative: omit both stage arrays and provide `water_need_mm` as a
  nonnegative total for the crop.
- Optional `planting_windows`: recurring local calendar windows. Every item
  contains `label`, `start_month_day` and `end_month_day` in `MM-DD` format.
  A window such as `11-01` to `02-15` may wrap across New Year. These dates
  must come from locally reviewed crop/variety guidance; the crop-profile API
  does not invent them.

### Scenario inputs

- `name`: display label.
- `start_date`: ISO planting date for the first crop.
- `crops`: nonempty array of IDs from `crop_catalog`.
- `gaps_after_crops_days`: one nonnegative whole-day gap between every pair of
  crops. For three crops, provide exactly two values.
- `planning_end_date`: the last acceptable harvest date for the comparison.
- `schedule_mode: "fixed_gap"` keeps the earliest date produced by the supplied
  gap and reports an issue when it is outside the crop's planting windows.
- `schedule_mode: "next_planting_window"` moves planting to the earliest
  supplied recurring window and reports the additional calendar wait.

Example schedule fields:

```json
{
  "name": "Maize then soybean",
  "start_date": "2024-04-01",
  "planning_end_date": "2025-03-31",
  "schedule_mode": "next_planting_window",
  "crops": ["maize", "soybean"],
  "gaps_after_crops_days": [14]
}
```

The backend only returns `calendar_status: "feasible"` when every crop has at
least one planting window, a planning end date is supplied, and no window or
horizon issue is found. Missing calendar inputs produce
`not_fully_evaluated`, never a false claim of feasibility.

### Advanced decision-support inputs

The planner also accepts these optional, source-explicit inputs:

- Field: `soil_test` with sample date/depth/source and measured N/P/K, organic
  matter and pH; `management` with its source; `soil_water_capacity_depth_m`;
  and `fallow_kc`. Legacy top-level initial soil values remain supported, but
  must not be duplicated with `soil_test`.
- Field irrigation: `irrigation.enabled`, trigger fraction, application
  efficiency, optional seasonal `max_withdrawal_mm`, water cost/currency and a
  source. The report separates water withdrawn from water effectively reaching
  the root zone and subtracts supplied irrigation cost from complete economics.
- Crop: `root_depth_m`; detailed `nutrient_budget` for N/P/K; sourced
  `soil_effects`; and sourced `economics` containing expected yield, price and
  variable cost plus a three-letter currency code. All crops in one scenario
  must use the same currency.
- Economics may instead use sourced `cost_items` with per-hectare or fixed
  whole-field amounts. The API reports line items, polygon-scaled totals,
  marketable production, revenue, irrigation cost, net margin, ROI and
  break-even price/yield.
- Crop alternative: supply sourced `agronomy` coefficients instead of a
  precomputed `nutrient_budget`. The API derives crop removal as expected yield
  multiplied by N/P/K removal per tonne, applies fertilizer recovery, residue
  release, other losses and soybean biological fixation. Never send both blocks.
- Crop variety: `variety.name`, `maturity_days` and `source`. Maturity days can
  supply duration when `duration_days` is absent.
- Plan: `rotation_effect_catalog`, keyed like `maize->soybean`, with a sourced
  pest/disease break score from `-2` to `2`.
- Plan: optional `ranking.weights` for net margin, irrigation, unmet water,
  nutrient shortfall and pest/disease score.

Detailed nutrient budgets use `fertilizer + residue_release -
crop_uptake_from_soil - other_losses`. Biological N fixation is returned as a
separate flow and is **not** automatically added to the soil mineral-N pool.
All nutrient and soil-effect blocks require a `source` string.

Every plan response includes `input_assessment`. It lists missing optional
inputs by domain. Supplied features are calculated; missing values are never
replaced by hidden crop defaults. Therefore a partial request can still produce
water/calendar output while nutrient, economics or rotation-effect output stays
incomplete or not evaluated.

Root depth scales the accessible water capacity relative to
`soil_water_capacity_depth_m`. This assumes a uniform water fraction through
the profile; it is not a layered soil model. When `fallow_kc` is present, the
planner applies rainfall and `ET0 × fallow_kc` through every uncropped day.

Economics uses the supplied baseline yield directly; the current engine does
not claim a stress-adjusted yield prediction. Ranking excludes scenarios that
are not calendar-feasible or lack a metric required by a positive weight. Its
score is a transparent comparison using frontend/user-selected weights—not a
NASA or agronomic recommendation.

### Mutually exclusive weather inputs

The API also supports raw `weather` and `imerg_rainfall` arrays for testing and
advanced clients. The product frontend should omit them and send
`weather_source`. Never send both `weather` and `weather_source`, or both
`imerg_rainfall` and `weather_source.provider: "imerg_era5"`.

## 6. Successful plan response (`200`)

```json
{
  "report": {
    "title": "Maize and soybean comparison",
    "field": {
      "name": "Demo field",
      "area_ha": 2.0,
      "initial_soil_water_mm": 45.0,
      "soil_water_capacity_mm": 80.0,
      "initial_mineral_n_kg_ha": 75.0
    },
    "scenarios": [],
    "assumptions_and_limits": []
  },
  "weather_metadata": {}
}
```

Each scenario contains:

| Field | Unit/meaning |
|---|---|
| `name` | Scenario label |
| `sequence` | One result object per crop |
| `calendar_status` | `feasible`, `infeasible`, or `not_fully_evaluated` |
| `calendar_feasible` | `true`, `false`, or `null` when required calendar inputs are missing |
| `schedule_issues`, `schedule_warnings` | Frontend-readable reason objects |
| `rotation_span_days` | Days from first planting through final harvest |
| `total_configured_gap_days` | Explicit harvest-to-next-crop gaps |
| `total_calendar_wait_days` | Extra wait added to reach valid planting windows |
| `fallow_periods` | Gap dates, rainfall/evaporation and whether fallow water was modeled |
| `rotation_effects`, `pest_disease_rotation_score` | Sourced transition evidence and aggregate score, or not evaluated |
| `total_rain_mm` | Rainfall during all crop days, mm |
| `total_irrigation_mm` | Modeled irrigation depth, mm |
| `total_irrigation_m3_for_field` | Irrigation volume for field area, m³ |
| `total_unmet_water_mm` | Crop water demand not supplied, mm |
| `estimated_final_mineral_n_kg_ha` | Simple ending mineral-N pool, kg/ha |
| `estimated_final_mineral_n_kg_for_field` | Ending field total, kg |
| `estimated_final_available_p_kg_ha`, `estimated_final_exchangeable_k_kg_ha` | Optional simple ending P/K pools |
| `estimated_final_organic_matter_percent`, `estimated_final_soil_ph` | Optional sourced scenario effects |
| `estimated_total_margin_for_field` | Supplied-yield enterprise estimate, or `null` |
| `irrigation_events` | Modeled dated irrigation events |

Each crop in `sequence` contains:

| Field | Unit/meaning |
|---|---|
| `crop` | Crop ID from the request |
| `earliest_planting_date` | Date produced by prior harvest plus configured gap |
| `planting_date` | ISO date |
| `planned_harvest_date` | ISO date |
| `gap_before_days` | Explicit configured gap before this crop |
| `calendar_wait_before_days` | Additional wait for the selected planting window |
| `planting_window_status` | Missing, within, outside, or shifted-to-window state |
| `matched_planting_window` | Concrete dated occurrence of the recurring window, or `null` |
| `duration_days` | Whole days |
| `rain_mm` | Rain during crop period, mm |
| `irrigation_mm` | Modeled irrigation depth, mm |
| `crop_water_need_mm` | ET0 × crop coefficient, or supplied total, mm |
| `irrigation_m3_for_field` | Modeled field irrigation volume, m³ |
| `unmet_water_mm` | Unsupplied modeled water demand, mm |
| `soil_water_start_mm`, `soil_water_end_mm` | Simplified soil-water pool, mm |
| `mineral_n_start_kg_ha` | Starting simple N pool, kg/ha |
| `net_soil_n_change_kg_ha` | Supplied signed crop assumption, kg/ha |
| `estimated_mineral_n_end_kg_ha` | Ending simple N pool, kg/ha |
| `estimated_n_shortfall_kg_ha` | Amount by which the assumption would fall below zero, kg/ha |
| `*_kg_for_field` | Corresponding field total, kg |
| `input_provenance` | Profile, calendar, water-source and local nitrogen-assumption identifiers copied from the crop input |

Irrigation event:

```json
{
  "date": "2024-07-22",
  "amount_mm": 2.94,
  "amount_m3_for_field": 58.8,
  "crop": "maize"
}
```

`weather_metadata` identifies rainfall/ET0 sources, coverage, partial IMERG
sampling and context provenance. Suggested UI use:

- Display source names, date coverage and partial-sampling warning.
- Put full `context.sources.*.provenance` in a collapsible diagnostics/download
  panel; it can be large.
- Display `assumptions_and_limits` near results, not hidden in logs.

The backend currently returns scenario comparisons and an optional weighted
decision score. It does **not** return:

- a scientifically validated “best crop” recommendation;
- stress-adjusted yield or future market-price predictions;
- a validated confidence score;
- measured soil N/P/K;
- future weather forecasts.

The frontend must not label the highest weighted score “NASA recommended.” Show
the selected weights, exclusions, input sources and warning beside the rank.

## 7. Plan pending response (`202`)

If IMERG coverage is being acquired, the same plan request returns:

```json
{
  "detail": {
    "message": "Satellite retrieval is queued or processing; retry this plan after jobs complete.",
    "sources": {
      "imerg": {
        "status": "acquisition_pending",
        "missing_dates": ["2024-04-01"],
        "invalid_dates": [],
        "errors": [],
        "acquisition_required": true,
        "jobs": [
          {
            "id": "JOB_ID",
            "source": "imerg",
            "status": "queued",
            "start_date": "2024-04-01",
            "end_date": "2024-04-01",
            "error": null
          }
        ]
      }
    }
  }
}
```

Treat `202` as a valid processing state, not a user error. Poll the returned
job IDs, then resend the exact original plan request.

## 8. Errors

| HTTP status | Meaning | Frontend action |
|---|---|---|
| `200` | Request handled; context sources can still be partial | Inspect per-source status |
| `202` | Plan awaits active satellite jobs | Poll and retry |
| `404` | Unknown job ID/route | Stop polling; show expired/unknown job |
| `422` | Invalid input, missing coverage or terminal data issue | Display actionable `detail` |
| `502` | ERA5 or GAEZ upstream failure | Offer retry later |

FastAPI model validation uses:

```json
{
  "detail": [
    {
      "loc": ["body", "latitude"],
      "msg": "Input should be less than or equal to 90",
      "type": "less_than_equal"
    }
  ]
}
```

Application errors can instead use `{"detail":"message"}` or a structured
`detail` object. The frontend error parser must accept all three forms.

## 9. Recommended frontend screens

1. **Field setup:** coordinate/map, area, soil-water and optional mineral-N
   assumptions, irrigation availability.
2. **Data readiness:** source cards for IMERG, SMAP and ERA5; cached/processing/
   complete/error state; requested date coverage.
3. **Crop screening:** GAEZ suitability cards with baseline, resolution and a
   prominent “regional screening, not field recommendation” explanation.
4. **Rotation setup:** crop choices, order, start date and reviewed crop profile.
5. **Comparison:** scenario summary cards plus crop timeline, water chart,
   irrigation events and simple N balance.
6. **Data and limitations:** source/version, dates, units, missing/partial flags,
   model assumptions and provenance download.

## 10. Current contract limitations

- Several nested plan request/response objects are currently represented as
  generic dictionaries in OpenAPI. Use the companion TypeScript definitions and
  this document until typed Pydantic response models are added.
- Context provenance is intentionally complete and can make responses large.
  A future frontend-specific summary endpoint should keep diagnostics optional.
- There is no websocket or callback. Poll jobs and retry the original request.
- API authentication, rate limiting and production CORS are not implemented.
- This is `v1`; coordinate/date/source fields should be treated as stable, while
  agronomic inputs and scoring will evolve as reviewed crop/soil data is added.

## 11. Minimal frontend request handling

```ts
import type {
  ContextRequest,
  ContextResponse,
  JobDetail,
  PlanPendingResponse,
  PlanRequest,
  PlanResponse,
} from "./frontend-api-types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function postJson<T>(path: string, body: unknown): Promise<{status: number; data: T}> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok && response.status !== 202) {
    throw Object.assign(new Error("Backend request failed"), {status: response.status, data});
  }
  return {status: response.status, data};
}

export const loadContext = (request: ContextRequest) =>
  postJson<ContextResponse>("/v1/context", request);

export async function createPlan(request: PlanRequest) {
  const result = await postJson<PlanResponse | PlanPendingResponse>("/v1/plans", request);
  return result.status === 202
    ? {kind: "processing" as const, value: result.data as PlanPendingResponse}
    : {kind: "ready" as const, value: result.data as PlanResponse};
}

export async function getJob(id: string): Promise<JobDetail> {
  const response = await fetch(`${API_BASE}/v1/context/jobs/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error(`Job lookup failed: ${response.status}`);
  return response.json();
}
```

This example deliberately leaves UI state management and polling cancellation to
the frontend framework. Cancel timers when the component unmounts or when every
job reaches a terminal state.
