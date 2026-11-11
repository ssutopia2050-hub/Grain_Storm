# Farming Practices Research and Data Plan

## Goal

Add field-management history as documented context for Grain Storm's
environmental observations. The first milestone is to define and assess the
data, not to build a crop-stress score or machine-learning model.

## Three-person schedule

Suggested duration: two weeks. Team members can work in parallel during week
one and combine their results during week two.

| Time | Teammate 1 — Practices and agronomy | Teammate 2 — Data design | Teammate 3 — Field records and integration |
|---|---|---|---|
| Days 1–2 | Review evidence on management effects on water and nutrients; prioritize practices | Inspect current project data formats and propose a small, documented schema | Identify what field records are available and document gaps/unknowns |
| Days 3–5 | Write concise definitions and note where effects vary by crop/soil | Draft a sample management CSV and metadata conventions; define units and missing-value representation | Map available field/season records into the proposed fields; do not guess missing values |
| Days 6–8 | Review schema fields for agronomic meaning and timing | Build a small parser/validator only if it fits existing project conventions | Prepare a worked example showing management timeline beside weather/soil observations |
| Days 9–10 | Review findings and limitations | Review data quality, dates, units, and field identifiers | Assemble documentation, team demo, and next-step proposal |

## First data fields to collect

Use one record per field, season, and management event where possible:

- Stable field identifier and season/year.
- Crop, variety if known, planting date, and growth-stage dates if observed.
- Irrigation event date, water amount (mm), and irrigation method.
- Tillage type, operation date, and a simple intensity/category field.
- Residue or mulch presence/cover estimate and cover-crop species/dates.
- Crop rotation history.
- Fertilizer or manure type, amount with units, date, and application method.
- Record source, collection date, and confidence/unknown status.

Do not infer irrigation from soil-moisture changes or infer fertilizer from
vegetation response. Keep rainfall separate from irrigation and distinguish
reported measurements from estimates.

## Deliverables

1. A short evidence summary with citations and crop/soil caveats.
2. A documented management-event schema and one example record set.
3. A data availability and quality note identifying missing fields.
4. A recommendation for a later pilot comparison, after suitable field data
   and crop identity are available.

## Interpretation cautions

Management effects depend on soil texture and drainage, climate, crop and
growth stage, timing, and combinations of practices. USDA NRCS guidance notes
that reduced tillage and cover crops can affect infiltration, water retention,
erosion, and nutrient cycling, while also describing situations where the
response depends on soil and management conditions. Irrigation is a separate
water input and needs its own event records. Fertilizer and manure records
matter for nutrient balance and soil chemistry; application rates alone do
not reveal nutrients available to plants.

The planned records are explanatory context for exploratory analysis. They
are not direct measures of crop stress, yield response, or causal effects.

## References

- [USDA NRCS: Soil Health on Cropland](https://www.nrcs.usda.gov/conservation-basics/soil/soil-health/soil-health-on-cropland)
- [USDA NRCS: Cover Crops for Soil Health](https://www.nrcs.usda.gov/conservation-basics/soil/soil-health/cover-crops-for-soil-health)
- [USDA NRCS: National Agronomy Manual, Water Management](https://nrcs.stg.platform.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf)
- [Synthesis of meta-analyses on agronomic measures and crop, soil, and environmental indicators](https://doi.org/10.1016/j.agee.2021.107551)
