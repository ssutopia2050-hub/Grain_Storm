# Grain Storm — Project TODO

This is the running project task list. Update the checkboxes as work is
completed, and add new tasks here before treating them as project commitments.

## Completed / documented

- [x] Add NASA POWER acquisition for temperature, precipitation, and relative humidity.
- [x] Add the initial Open-Meteo ERA5-Land hourly soil-moisture connector for four layers.
- [x] Document and explore the January 2024 soil-moisture dataset.
- [x] Investigate rainfall compatibility, grid coordinates, and ERA5-Land precipitation availability; run the small IFS comparison retrieval.
- [x] Research farming practices as context for environmental and soil observations; add a three-person work schedule.
- [x] Research air-quality effects relevant to crops and soil chemistry.
- [x] Add a first transparent crop-sequence planner prototype with user-supplied rainfall, soil-water, and net mineral-nitrogen inputs; report field-scale totals and clearly label the synthetic demo and limitations.
- [x] Select grain maize and grain soybean as the v1 crop pair and document broad reference water profiles plus the need for local calendars and nutrient inputs. See [v1 crop profiles](crop_profiles_v1.md).
- [x] Expose versioned maize and soybean reference profiles through the API, including FAO reference calendars/Kc values, GAEZ crop identifiers, source links, nitrogen-input guardrails, planner-ready template generation, and result provenance.
- [x] Add on-demand GAEZ v4 location screening for maize and soybean using the official Module V ImageServer. Lock exact 1981–2010 historical, rainfed, high-input all-land rasters; return normalized index, documented class, raster provenance, resolution and limitations without global downloads.
- [x] Add rotation calendar feasibility: explicit between-crop gaps, recurring local planting windows (including New Year wrap), fixed-date versus next-window scheduling, planning-horizon checks, total rotation span, and frontend-readable issues/warnings. Legacy scenarios remain valid but are marked not fully evaluated when calendar inputs are absent.
- [x] Add an explicit decision-support MVP for the remaining rotation factors: root-depth-scaled water capacity, fallow rainfall/ET, sourced N/P/K flow budgets, separate biological fixation reporting, sourced pH/organic-matter effects, sourced pest/disease transition scores, baseline yield/revenue/cost accounting, and feasibility-gated user-weighted ranking.
- [x] Add optional frontend-driven farm inputs: dated/depth-specific soil tests, management provenance, variety maturity, yield-scaled nutrient-removal coefficients, fertilizer recovery, residue/loss/fixation flows, irrigation efficiency/seasonal limits/costs, and an explicit missing-input assessment. Calculations activate only when their inputs are provided.
- [x] Derive field area and perimeter from the selected GeoJSON farm polygon; scale water, nutrient, production and financial totals to that area. Add sourced itemized crop costs, marketable yield, additional income, gross revenue, total cost, margin, ROI and break-even economics.
- [x] Replace synthetic duration/root placeholders with on-demand authoritative baselines: GAEZ Module II location-specific cycle start and length plus conservative FAO maize/soybean rooting depths, returned with target-year dates and provenance.
- [x] Replace synthetic yield placeholders with on-demand GAEZ Module VI downscaled 2010 rainfed actual-yield baselines; retain year, units, raster provenance and the warning that these are historical regional baselines rather than forecasts.
- [x] Add a no-login ERA5 archive connector for daily precipitation and FAO reference ET0, with raw response, metadata, and CSV output; allow the planner to consume the ERA5 weather CSV.
- [x] Add a reusable NASA AppEEARS point-sampling pipeline for discovering and requesting supported land products, retaining raw downloads and request provenance. Product-specific normalization and planner integration remain pending.
- [x] Add a bounded NASA Earthdata granule downloader and a daily GPM IMERG Final V07 acquisition command.
- [x] Add a daily normalizer for AppEEARS SMAP L4 root-zone and surface point samples, retaining sample counts and source metadata. Planner integration remains pending.

## Next priorities

- [x] Connect processed IMERG rainfall to planner weather and `POST /v1/plans`, retaining ERA5 ET0, source metadata, and strict missing-date handling. Prepared the July 19–August 1 sample and checked merge/API behavior.
- [x] Add a shared location/date context API and SQLite cache: source/product/day keys, coverage and provenance, ERA5/POWER point fetches for missing intervals, and metadata-checked IMERG/SMAP imports. Connect the planner through `weather_source.provider: imerg_era5`.
- [x] Implement satellite subset jobs on cache misses: single-cell/day IMERG OPeNDAP, SMAP AppEEARS point windows, durable task IDs, progress API, noninteractive worker authentication, shared-cache ingestion, and strict download limits. Offline subset/queue/API tests pass. See [worker setup](satellite_context.md).
- [x] Verify an authenticated live IMERG cloud OPeNDAP subset end-to-end: one 42 KB cell/day response for 2024-01-04 was validated, normalized, cached, and served on the next request without another download.
- [x] Verify a new SMAP task end-to-end through the automated worker for 2024-02-01, including saved task ID, polling, eight-observation daily normalization, ingestion, and subsequent cache hit.
- [x] Add a bounded preload command and controlled IMERG concurrency (default 4, maximum 8), preserving per-day deduplication, single-cell size limits, compact status output, and at most one SMAP job per worker batch.
- [x] Add the first source-specific soil-property adapter: USDA SSURGO/WSS point context for covered U.S. locations, including mapped horizons, texture, pH, organic matter, drainage and water capacity; expose no-coverage and unavailable current N/P/K explicitly.
- [ ] Add country-appropriate soil adapters outside SSURGO coverage and a persistent cache for GAEZ/SSURGO point results.
- [x] Add an authenticated USDA NASS Quick Stats adapter for U.S. state/year maize and soybean yield plus price-received records; preserve units, record semantics and suppressed values, and keep the API key server-side.
- [x] Select final NASS grain `YEAR` and `MARKETING YEAR` records automatically, reject forecast/silage rows, convert bushels/acre to t/ha and $/bushel to $/tonne, and return planner-ready partial economics awaiting local variable cost.
- [ ] Add market/yield adapters for non-U.S. pilots and a reviewed rule for selecting one semantically matching record for planner economics.
- [x] Deduplicate overlapping satellite requests by source/product/location/day; claim jobs transactionally and preserve NASA task IDs for restart recovery.
- [ ] Add multi-host coordination, operational monitoring, access controls, and concurrent ERA5/POWER fetch deduplication before public deployment. The current API is a local development service.
- [ ] Acquire IMERG and ET0 only for the requested crop-sequence period before a full historical rotation simulation. Reuse the cache; the current July sample provides 14 days only. The previous annual bulk script is not the default path.
- Current rainfall decision: use IMERG for the planning workflow. CoCoRaHS/IMD validation exploration is deferred; it is not a prerequisite for this prototype. Existing source comparisons do not establish ground validation.

- [ ] **Finish replacing synthetic planner values with reviewed agronomic inputs:** the water-profile API now supplies sourced FAO baselines; next add a location/variety calendar override, reviewed soil-water properties, and a sourced local nitrogen budget with region, units, and uncertainty recorded.
- [x] **Review the first GPM processing runs:** January dry-day and July wet-event samples were processed and compared with ERA5. Large differences and unusual randomError values were observed; randomError is excluded from planner inputs.
- [x] Extract GPM IMERG precipitation and available count/error layers at a point, normalize to a daily CSV, retain source metadata, compare matched dates with ERA5, and connect rainfall to the planner.
- [ ] **Demonstrate product-specific AppEEARS pipelines:** select and retrieve a supported SMAP soil-moisture product, one vegetation-index product, SRTM elevation, and ECOSTRESS when coverage is available; preserve product/version/quality metadata and document their distinct spatial/time support.
- [ ] **Finish sequence timing:** local recurring planting windows, exact durations, harvest dates, between-season gaps and horizon feasibility are implemented. Add duration ranges, maturity alternatives and fallow-period water balance.
- [ ] **Connect planner to real weather and farm inputs:** add adapters for daily weather, field soil tests, fertilizer/irrigation records, and crop/variety calendars while preserving missing values.
- [ ] **Improve the water balance:** account for reference evapotranspiration, crop-stage coefficients, effective rainfall, rooting depth, runoff/drainage assumptions, and irrigation application efficiency before presenting irrigation amounts as actionable.
- [ ] **Add management and timing constraints:** represent planting windows, crop maturity ranges, harvest limits, equipment capacity, water availability, and farmer objectives; compare feasible schedules instead of shifting harvest dates freely.
- [ ] **Validate with agronomists and field records before recommendations:** compare modeled water/nutrient states and proposed schedules with measured observations across more than one crop, region, and season.
- [ ] **Define the generalized model scope:** specify which regions, crops, and rotation questions the model should support; make geographic coverage and input availability explicit, and avoid treating one pilot location as representative of all farms. See [challenge resource triage](challenge_resources_triage.md).
- [ ] **Choose a coverage-aware environmental stack:** compare NASA POWER and ERA5/ERA5-Land for climate context, GPM IMERG for precipitation, and SMAP as an independent surface-soil-moisture product; assess spatial/temporal fit and keep products distinct. Use Landsat/Sentinel-2 or MODIS/VIIRS for vegetation context only when resolution and cloud coverage fit the use case. See [challenge resource triage](challenge_resources_triage.md).
- [ ] **Preserve source provenance:** for new acquisitions, record requested and returned coordinates, model/product, variables, units, timezone, request dates, and missing-value counts alongside the raw response.
- [ ] **Choose a small field-management data schema:** include crop/variety, planting and growth-stage dates, irrigation events and amounts, tillage, residue/mulch, cover crops/rotation, and fertilizer/manure events. Keep unknown values explicit.
- [ ] **Check management data availability:** identify representative field/season records for an initial evaluation, document their geographic and crop limits, and do not infer irrigation or inputs from environmental observations.
- [ ] **Plan an air-quality data pilot:** prioritize pollutant-specific ozone and PM measurements over a composite AQI; identify source, spatial/temporal resolution, units, and coverage before acquisition.
- [ ] **Define soil-chemistry observations:** if field data are available, identify measurements such as soil pH, texture, organic matter, exchangeable nutrients/acidity, and deposition or rainfall chemistry. Keep these distinct from atmospheric AQI/PM concentrations.
- [ ] **Validate modeled environmental data:** identify relevant local observations (weather station, soil sensors, or field/lab samples) for comparison, with location and measurement depth recorded; document which regions and conditions are not validated.
- [ ] **Run a paired pilot only after inputs and evaluation sites are selected:** align timestamps and coordinates, retain missing values, document model/product differences, and treat results as site-specific evidence rather than proof of general performance.

## Later, after data and validation are available

- [ ] Compare multiple fields or seasons to understand how crop, soil, weather, and management context relate to observed environmental patterns.
- [ ] Define scientifically reviewed, crop-specific indicators only when crop identity, growth stage, soil properties, and suitable validation data are available.
- [ ] Revisit whether any predictive modeling is justified after building a sufficiently documented and validated data foundation.

## Current guardrails

- Do not treat modeled soil moisture as a field measurement or direct crop-stress measure.
- Do not treat hourly timestamps as proof that two products are spatially or scientifically equivalent.
- Do not turn missing observations into zero or interpolate without documenting and justifying the method.
- Keep rainfall, irrigation, air pollutants, deposition, and soil chemistry as distinct variables with source and units.
- Do not make causal claims from simple correlations or one field/month of data.

Related planning document: [Farming Practices Research and Data Plan](farming_practices_task_schedule.md).
