# Grain Storm v1 — Starter Crop Profiles

## Supported starter catalog

The starter catalog contains **grain maize, grain soybean, wheat, grain sorghum,
chickpea, and sunflower**. Maize, soybean and sorghum refer to dry grain/seed
rather than sweet corn, vegetable soybean, or forage sorghum.

The first model scope is software support for comparing these crops in a sequence on the same field across growing seasons. It is not a claim that both crops suit every location. A location should only be evaluated when both crops are locally viable and the required crop calendar and field inputs are available. Local crop variety and planting/harvest calendars must override generic baselines.

## Broad reference baseline

FAO crop-water guidance divides annual crops into initial, crop-development, mid-season, and late-season stages. It gives the following indicative growing-period ranges and crop coefficients for baseline calculations:

| Crop | Indicative full growing period | Kc initial | Kc development | Kc mid-season | Kc late-season |
|---|---:|---:|---:|---:|---:|
| Grain maize | 125–180 days | 0.40 | 0.80 | 1.15 | 0.70 |
| Soybean | 135–150 days | 0.35 | 0.75 | 1.10 | 0.60 |
| Wheat | 120–150 days | 0.35 | 0.75 | 1.15 | 0.45 |
| Sorghum | 120–130 days | 0.35 | 0.75 | 1.10 | 0.65 |
| Chickpea | 90–180 days | 0.45 | 0.75 | 1.10 | 0.50 |
| Sunflower | 125–130 days | 0.35 | 0.75 | 1.15 | 0.55 |

These are **reference values, not universal crop constants**. The FAO guide says growing period depends on variety, climate, and planting date, and advises using local data when available. Crop coefficients also need adjustment for climate and wetting practices. The reference method estimates crop evapotranspiration from reference evapotranspiration and a crop-stage coefficient (`ETc = ETo × Kc`).

For v1, the planner should eventually calculate daily crop-water demand from local weather/ETo and stage-specific coefficients, rather than use one fixed seasonal water number. Soil-water capacity, effective rainfall, root depth, and irrigation efficiency also need field-specific inputs.

The planner now supports this water calculation when each crop entry includes four `stage_kc` values in the table order and four `stage_days` lengths that sum to `duration_days`. Each daily crop-water need is calculated as `ET0 × stage Kc`. The coefficients are baseline values from the FAO guide; stage lengths should come from the local crop variety and calendar. Example crop entry:

```json
{
  "duration_days": 125,
  "stage_kc": [0.40, 0.80, 1.15, 0.70],
  "stage_days": [20, 35, 40, 30],
  "net_soil_n_change_kg_ha": 0
}
```

The duration and stage lengths above illustrate the FAO grain-maize reference example; they are not suitable for every variety or location. The zero nitrogen change is only a software placeholder, not an agronomic estimate. For soybean, use locally documented stage lengths rather than copying maize's calendar.

## Crop-profile API now available

The backend exposes these references as versioned data instead of forcing the
frontend to copy crop numbers:

- `GET /v1/crops` lists supported crops and calendar IDs.
- `GET /v1/crops/{crop_id}` returns the complete reference profile, source
  links, limitations and local inputs still needed.
- `POST /v1/crops/{crop_id}/planner-template` converts one chosen calendar to
  the exact `crop_catalog` shape used by `POST /v1/plans`.

The supported IDs are `grain_maize`, `grain_soybean`, `wheat`, `sorghum`,
`chickpea`, and `sunflower`. The profile version remains `fao-reference-v1`.
Each crop exposes two reference calendars, while location-specific GAEZ cycle
data and locally confirmed varieties can override them.

The template endpoint intentionally returns `ready_for_planner: false` until a
signed `net_soil_n_change_kg_ha` and its `nitrogen_source` are supplied. This
prevents the UI from silently turning biological fixation or generic crop
uptake into a soil-nitrogen credit. Profile, calendar, water source and
nitrogen-assumption provenance are copied into each crop result.

The profiles now connect to GAEZ through `POST /v1/crop-suitability`. The
adapter samples the official Module V suitability index for a requested point
without downloading the global rasters. Its v1 comparison is deliberately
fixed to the 1981–2010 CRUTS32 historical baseline, rainfed water supply, high
input level, and all land in the grid cell. Results are coarse 5-arc-minute
screening context—not a field soil test, yield forecast, or crop recommendation.

## Nutrient values: keep local and measured

Do **not** assign one fixed nitrogen requirement or automatic legume nitrogen credit to any crop. Nutrient balance depends on soil tests, expected yield, variety, inoculation and fixation, fertilizer/manure, residue handling, harvest removal, and weather-related losses. The first real nutrient-budget implementation should either:

- use a reviewed, location-specific recommendation and record its source and assumptions; or
- show nutrient balance as unknown until the required soil and management inputs are available.

Any nitrogen credit attributed to soybean must be represented as an evidence-based range and must distinguish nitrogen fixed into the plant from nitrogen left in the soil after harvest. It must not be treated as an automatic positive soil-N change.

## Rotation scenarios to compare

Once the planner supports real growing-season dates and management inputs, compare at least:

1. maize → soybean;
2. maize → maize as a continuous-crop baseline;
3. soybean → maize, where locally relevant.

These are scenario comparisons, not recommendations. The model should report water demand, irrigation estimate, nutrient assumptions, missing inputs, and uncertainty for each season. It should not move harvest dates freely to fit the next crop; planting windows, maturity, local weather, and equipment constraints must be represented.

## References

- [FAO, Chapter 3: Crop water needs](https://www.fao.org/4/S2022E/s2022e07.htm) — indicative crop durations, growth stages, and crop coefficients for grain maize and soybean.
- [FAO, Chapter 5: Introduction to crop evapotranspiration](https://www.fao.org/4/x0490e/x0490e0a.htm) — crop-stage water use and limits of reference coefficients.
- [FAO, Chapter 8: Optimizing nitrogen use on the farm](https://www.fao.org/4/y5146e/y5146e09.htm) — nitrogen budgets use soil tests and crop/yield context; crop requirement is not the same as fertilizer requirement.
