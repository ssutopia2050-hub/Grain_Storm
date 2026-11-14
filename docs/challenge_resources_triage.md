# Field Shift Challenge — Resource Triage

## Challenge fit

The 2026 Space Apps challenge, [Field Shift: Adapting Farms with NASA Data](https://www.spaceappschallenge.org/2026/challenges/field-shift-adapting-farms-with-nasa-data/), asks for decision support that combines NASA Earth observations with local soil information, crop characteristics, and farmer priorities to explore crop-rotation strategies. Grain Storm already has an environmental-data foundation, but a credible rotation comparison also needs a selected pilot location, candidate crops/rotation options, local soil context, and management or farmer-priority information.

Grain Storm is intended as a generalized model rather than a Punjab-specific or U.S.-specific system. The current project example coordinates (30.34° N, 76.39° E) should be treated as one development example, not as the model's target geography or as evidence of general performance. The challenge resource list mixes global products with region-specific resources. Design the input strategy around explicit coverage metadata and allow regional datasets to supply context only where their geography, license, resolution, and dates fit.

## Resource shortlist

| Priority | Resource family | Best initial use | Notes for Grain Storm |
|---|---|---|---|
| Core | NASA POWER | Daily weather/climate context, including temperature and precipitation | Existing connector; keep source metadata and units. It is a gridded environmental product, not a field observation. |
| Core candidate | NASA GPM IMERG | Rainfall timing/amount and precipitation context | Global product candidate; independent of ERA5-Land with its own grid and uncertainty. Validate timestamps, accumulation units, coverage, and selected pixel. |
| Core candidate | SMAP | Satellite surface soil-moisture context and comparison | Broad-coverage satellite product with different depth support, resolution, and revisit from ERA5-Land. Do not splice its values into the existing four-layer series. |
| Core candidate | Landsat, Sentinel-2, MODIS/VIIRS | Seasonal vegetation/cover indicators and timing of crop transitions | Select imagery based on target scale, revisit, cloud availability, and coverage. Vegetation indices indicate canopy/greenness patterns, not crop water stress or yield on their own. |
| Later | ECOSTRESS | Land-surface temperature and evapotranspiration context | Useful when coverage exists for the selected field and dates; revisit is not a regular hourly time series. |
| Later | SRTM | Static elevation/slope context | Terrain is relatively stable and can support runoff/erosion context; it does not measure current soil water. |
| Later | GLDAS/NLDAS | Gridded land/hydrology time series and comparison | NLDAS is North American; GLDAS has broader coverage. Check product, region, and variable details before selecting either. Keep model products distinguished. |
| Global crop/soil context candidate | FAO GAEZ | Broad crop suitability and agro-ecological context | Use as regional context, not as field-level soil testing or a farmer-specific rotation prescription. |
| Local validation/context | Local soil laboratory or survey data, farmer/extension records, and nearby observations | Soil properties, crop/variety, rotation history, irrigation and priorities | Highest value for a real recommendation. Include collection date, depth, units, location, and source. |

## Coverage-aware use of organizer resources

The organizer list is a menu of candidate resources, not a requirement to integrate every dataset. The following broadly available products can inform a generalized environmental feature set, subject to product-level coverage and suitability checks: NASA POWER, SMAP, GPM/IMERG, Landsat, MODIS/VIIRS, SRTM, ECOSTRESS, ERA5, Sentinel-2, and FAO GAEZ. Their spatial resolution, revisit, variables, units, licenses, and time periods differ; availability alone does not make their measurements interchangeable.

Several organizer-listed sources are regional and should be optional adapters rather than universal dependencies:

- **USDA WSS / SSURGO / STATSGO2:** U.S. soil-survey products; use only for covered U.S. locations. Other regions need suitable local soil data or field/lab measurements.
- **USDA Cropland Data Layer (CDL), NAIP, USDA NASS QuickStats, and USDA AMS
  Market News:** U.S. crop classification, imagery, statistics, or markets;
  they do not describe farms or markets outside their coverage.
- **PRISM:** U.S. climate grids; not a universal climate source.
- **CoCoRaHS and USGS NWIS:** North American precipitation and water-monitoring networks; not global observation networks.
- **OpenET:** coverage is focused on the western United States; check current area coverage before use.
- **NLCD and LANDFIRE:** U.S. land-cover and vegetation programs; use only within their coverage.
- **USDA Ag Data Commons:** a catalog of agricultural research data. A listed
  dataset is only useful if its geography, variables, license, and time period
  fit the chosen site.

A generalized model should record the coverage and provenance of every input and support region-specific data where appropriate. Prefer a small, spatially and temporally documented stack for each evaluation, and report where inputs are unavailable rather than silently substituting a different product.

## Suggested generalized-model development scope

1. Define the intended range of regions, crop groups, rotation questions, and users; state what the model cannot currently support.
2. Build a common data contract for environmental inputs and optional regional adapters for soil surveys, crop maps, climate grids, market data, and local observations.
3. Evaluate a compact broad-coverage stack: NASA POWER or ERA5 for climate context, GPM IMERG for precipitation, ERA5-Land and/or SMAP as explicitly distinct soil-moisture products, and one suitable vegetation-imagery family.
4. Keep crop/variety, soil properties, crop calendar, irrigation/rotation records, and farmer priorities as explicit contextual inputs; allow unknown values and report their effect on output confidence.
5. Validate across more than one region, crop, and season before describing performance as generalized. Present outputs as transparent comparisons of conditions and tradeoffs, not validated crop-stress forecasts or prescriptive yield guarantees.

This is a candidate plan, not a commitment to acquire every source. Check coverage, license/access, units, spatial support, missingness, and provenance before implementing connectors.

## References

- [2026 NASA Space Apps challenge: Field Shift](https://www.spaceappschallenge.org/2026/challenges/field-shift-adapting-farms-with-nasa-data/)
- [USDA NRCS Web Soil Survey](https://www.nrcs.usda.gov/resources/data-and-reports/web-soil-survey) — official U.S. soil survey access.
- [USDA NASS Cropland Data Layer FAQ](https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php) — CDL coverage and annual crop-specific land-cover data.
- [PRISM Climate Group](https://prism.oregonstate.edu/) — U.S. gridded climate datasets.
- [OpenET](https://openetdata.org/) — satellite-based ET data; confirm current geographic coverage for any proposed site.
