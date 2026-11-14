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
returns one of three product states.

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
- explicit warnings, assumptions and missing domains.

The product response contains compact IMERG/ERA5 status and record counts, not
hundreds of raw daily rows. Those rows remain in the backend cache and are fed
directly into the calculation. SMAP is available through the diagnostic context
API but is not downloaded or treated as a blocker for rotation advice.

## Important behavior

- Historical IMERG/ERA5 observations cannot predict future daily rainfall. A
  future planning period therefore returns `needs_input` for an approved future
  weather/climate scenario rather than fabricating weather.
- Current N/P/K are never inferred from satellite soil moisture.
- GAEZ planting dates are coarse anchors; local planting windows remain a
  farmer/agronomist input.
- The first and last polygon coordinates must be identical.
- Only `grain_maize` and `grain_soybean` are supported in v1.

The lower-level endpoints remain useful for diagnostics and research, but they
are not part of the normal frontend orchestration.
