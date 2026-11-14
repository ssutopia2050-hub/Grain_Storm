# Frontend handoff: one rotation-advice endpoint

The farmer-facing frontend only needs to orchestrate one endpoint:

`POST /v1/rotation-advice`

The backend calls the crop, GAEZ, soil, rainfall, soil-moisture, ET0 and planner
components. The frontend should not call those individual endpoints for the
normal product flow.

## First request

Send a closed GeoJSON polygon in `[longitude, latitude]` order, the crops, and
the preferred planning period:

```json
{
  "field_polygon": {
    "type": "Polygon",
    "coordinates": [[
      [76.3890, 30.3390],
      [76.3910, 30.3390],
      [76.3910, 30.3410],
      [76.3890, 30.3410],
      [76.3890, 30.3390]
    ]]
  },
  "field_name": "North field",
  "crop_sequence": ["grain_soybean", "grain_maize"],
  "preferred_start_date": "2024-04-01",
  "planning_end_date": "2024-09-30",
  "schedule_mode": "next_planting_window",
  "compare_all_orders": true
}
```

The backend calculates the polygon centroid and approximate hectares. It then
returns one of four product states.

`autofill_missing` defaults to `true`. The backend therefore produces a usable
`preliminary` calculation when local values are absent. Caller values always
win. Generated values and their source, confidence and replacement guidance are
listed under `input_resolution`. Send `"autofill_missing": false` to restore
strict `needs_input` behavior.

Automatic baseline mode can supply:

- soil available-water capacity from SSURGO where available, otherwise an FAO
  medium-texture reference baseline;
- a clearly labelled 50% initial-water planning state;
- zero-credit N/P/K starting scenarios, which show maximum modeled nutrient
  shortfall and never pretend to be soil tests;
- GAEZ planting anchors expanded into provisional ±14-day windows;
- a 14-day harvest-to-planting turnaround assumption;
- FAOSTAT crop nutrient-removal coefficients combined with the GAEZ historical
  rainfed yield baseline;
- provisional pest/disease break scores from botanical-family changes.

The backend deliberately does not invent local crop prices or production
costs. Water, calendar and nutrient screening still run; margin remains
unavailable until economics are supplied.

The `field` result includes `area_m2`, `area_ha`, `area_acres` and
`perimeter_m`. All whole-field water, nutrient, production, cost and revenue
totals use this polygon-derived hectare value; the frontend does not calculate
area independently.

## Response states

### `202` — `status: "processing"`

Satellite subsets are being acquired. Show a single “Preparing field analysis”
screen. The response includes `jobs`; the frontend may poll the existing job
endpoint or simply repeat the same rotation-advice request after a delay.

### `200` — `status: "needs_input"`

The response already contains available crop suitability, calendar, historical
yield, soil and environmental context. Render a short form from
`missing_inputs`; each item contains an exact request `path` and farmer-readable
`reason`. Submit the same request again with those values added.

Typical additions are:

```json
{
  "gaps_after_crops_days": [14],
  "field_inputs": {
    "soil_water_capacity_mm": 120,
    "soil_water_capacity_depth_m": 1,
    "initial_soil_water_mm": 60
  },
  "soil_test": {
    "sample_date": "2024-03-15",
    "depth_cm": 30,
    "source": "Farmer laboratory report",
    "mineral_n_kg_ha": 40,
    "available_p_kg_ha": 20,
    "exchangeable_k_kg_ha": 80,
    "organic_matter_percent": 1.8,
    "ph": 6.8
  },
  "management": {
    "source": "Farmer record",
    "previous_crop": "wheat"
  },
  "irrigation": {
    "enabled": true,
    "trigger_fraction": 0.5,
    "application_efficiency": 0.75,
    "max_withdrawal_mm": 300,
    "variable_cost_per_m3": 0.05,
    "currency": "USD",
    "source": "Farmer irrigation record"
  }
}
```

Each crop can add `planting_windows`, `variety`, `agronomy` and `economics`
under `crop_inputs.<crop_id>`. The live Swagger schema and
`frontend-api-types.ts` contain their field shapes.

## Optional precision controls

These inputs improve the calculation without changing the endpoint:

- `weather_scenario`: one `{date, rain_mm, et0_mm}` row for every planning
  day. Use this for seasonal dry/expected/wet comparisons. Caller-supplied
  values are clearly labelled as a scenario, not a forecast.
- `management_zones`: one to twenty area-fraction zones. Each zone inherits
  the main field inputs and can override soil test, management or irrigation
  values. Fractions must total `1.0`; the backend calculates each zone and then
  produces area-weighted field results.
- `irrigation.decisions`: dated farmer choices with `accept`, `skip` or
  `replace`. A replacement also supplies `amount_mm`. The result preserves the
  automatic recommendation and the farmer's actual choice.
- `crop_inputs.<crop_id>.water_model`: an optional `fao56_dual` coefficient
  model that separates basal crop transpiration, exposed-soil evaporation and
  water-stress reduction. The existing four-stage `stage_kc` model remains the
  default, so older requests continue to work.

Example farmer override:

```json
{
  "irrigation": {
    "enabled": true,
    "application_efficiency": 0.75,
    "source": "Farmer irrigation plan",
    "decisions": [
      {
        "date": "2026-11-16",
        "action": "replace",
        "amount_mm": 18,
        "source": "Farmer confirmed pump availability"
      }
    ]
  }
}
```

Economics accepts either the older `variable_cost_per_ha` lump sum or detailed
`cost_items`. Each item has a name/category/source and exactly one of
`amount_per_ha` or `amount_for_field`. Categories can cover seed, fertilizer,
labour, machinery, crop protection, land preparation, harvesting, transport,
insurance and any custom cost. The response calculates per-crop and whole-field
production, marketable yield, revenue, additional income, every cost line,
irrigation cost, net margin, return on cost, break-even price and break-even
yield. The frontend must set `cost_completeness_confirmed: true` for itemized
costs, preventing a partial list from being presented as a complete farm budget.

### `200` — `status: "complete"`

Render `advice` as the simple farmer result and retain `calculation.report` for
detail screens. It contains:

- polygon centroid and calculated field area;
- crop suitability, calendar and historical yield context;
- planting/harvest dates and calendar feasibility;
- gaps and waiting days;
- daily weather provenance and data quality;
- rainfall, crop demand, irrigation withdrawal/effective water and shortages;
- N/P/K flows, shortages and estimated ending amounts;
- pH/organic-matter effects when supplied;
- pest/disease transition effects when supplied;
- revenue, costs and estimated margin;
- scenario comparison/ranking when enough inputs exist;
- optional per-zone calculations and area-weighted field totals;
- the automatic and farmer-adjusted amount for every irrigation decision;
- dual-coefficient water diagnostics when that model was requested;
- explicit warnings, assumptions and missing domains.

The product response contains compact IMERG/ERA5 status and record counts, not
hundreds of raw daily rows. Those rows remain in the backend cache and are fed
directly into the calculation. SMAP is available through the diagnostic context
API but is not downloaded or treated as a blocker for rotation advice.

### `200` — `status: "preliminary"`

The calculation ran using one or more generated planning baselines. Render the
results, show `input_resolution.generated_inputs`, and invite the farmer to
replace the low-confidence values listed in `recommended_replacements`.

## Important behavior

- Historical periods use IMERG/ERA5. A future period within the operational
  horizon can use the Open-Meteo daily forecast (up to 16 days). Longer future
  periods return `needs_input` for a complete `weather_scenario` rather than
  pretending a seasonal scenario is a precise daily forecast.
- Current N/P/K are never inferred from satellite soil moisture.
- GAEZ planting dates are coarse anchors. Automatic mode makes a provisional
  ±14-day window; a local farmer/agronomist window should replace it.
- The first and last polygon coordinates must be identical.
- Supported crop IDs are `grain_maize`, `grain_soybean`, `wheat`, `sorghum`,
  `chickpea`, `sunflower`, and `rice`. A rotation request can contain up to four crops.
- `rice` means wetland/paddy rice. Its ET is calculated, but the returned
  irrigation amount excludes puddling, standing-water, seepage, percolation
  and drainage requirements; display the `water_model_limitation` warning.
- GAEZ has no standalone 2010 chickpea actual-yield raster, so that specific
  baseline is returned as unavailable; the frontend must request a local yield.

The lower-level endpoints remain useful for diagnostics and research, but they
are not part of the normal frontend orchestration.
