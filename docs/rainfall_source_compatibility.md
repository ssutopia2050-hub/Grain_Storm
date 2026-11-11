# Rainfall Source Compatibility Investigation

## Summary

The existing ERA5-Land soil-moisture data and the available Open-Meteo
precipitation files are not a fully matched pair. The Historical Weather API
does not provide precipitation for ERA5-Land. Its ERA5-Land precipitation
arrays are null; they are missing data, not zero rainfall. A previously saved
daily CSV converts those nulls to zero, so its precipitation column is not
valid for analysis.

The best internally consistent Open-Meteo option tested here is to request
precipitation and all soil-moisture layers together from `ecmwf_ifs`. The
controlled three-day request returned all variables at one returned grid
coordinate, with 72 complete hourly UTC records. This makes a matched IFS
dataset; it does not make IFS precipitation compatible with the existing
ERA5-Land soil-moisture time series. For the latter, NASA GPM IMERG is a
reasonable separate precipitation product at a similar nominal spatial scale,
but it is a satellite product and not the same model.

## Existing local data and metadata

Files were located by inventorying the project rather than assuming names.
The raw JSON responses contain coordinates, timezone, and units, but most do
not retain the original request parameters. In particular, Open-Meteo response
JSON does not include a model-selection field. The existing soil-moisture
metadata sidecar does retain its request and model.

| Local file | Contents and metadata | Coverage / missingness |
|---|---|---|
| `data/raw/open_meteo_soil_moisture_era5_land_20240101_20240131.json` | Four soil-moisture variables; units m³/m³; response at 30.300003° N, 76.399994° E; GMT, UTC offset 0 | 744 hourly rows, Jan 1 00:00–Jan 31 23:00 UTC; no missing layer values |
| `data/processed/open_meteo_soil_moisture_era5_land_20240101_20240131.metadata.json` | Explicit model `ERA5-Land`; request 30.34° N, 76.39° E; response coordinate, timezone, units and quality report | Records the request and response details absent from the raw JSON |
| `data/processed/open_meteo_soil_moisture_era5_land_20240101_20240131.csv` | `time` plus 0–7, 7–28, 28–100, 100–255 cm columns; values parse as floats and times parse as UTC | 744 rows; no missing values or duplicate timestamps |
| `archive_utc.json` | Hourly temperature (°C), relative humidity (%) and precipitation (mm); response at 30.333918° N, 76.389210° E; GMT, UTC offset 0. Model/request parameters are absent | 744 hourly rows, Jan 1 00:00–Jan 31 23:00 UTC; no missing values; precipitation totals 12.5 mm |
| `archive.json` | Same weather variables and returned coordinate as `archive_utc.json`; timezone Asia/Kolkata, UTC offset +19,800 seconds. Model/request parameters are absent | 744 hourly rows in local time Jan 1–31; no missing weather values; precipitation total 12.5 mm |
| `archive_era5_land.json` | Explicitly named ERA5-Land experiment; temperature, humidity and precipitation variables are present in the response structure; timezone GMT; no model-selection field in JSON | 744 hourly rows, Jan 1 00:00–Jan 31 23:00 UTC; temperature/humidity present, precipitation null in all 744 rows |
| `archive_humidity.json` | Temperature, relative humidity and dew point; response at 30.300003° N, 76.399994° E; GMT | 744 hourly rows; no precipitation variable |
| `data/processed/open_meteo_daily_utc.csv` | UTC daily aggregation of the weather data; precipitation in mm/day | 31 rows; Jan 31 total is 12.5 mm |
| `data/processed/open_meteo_daily_ist.csv` | Daily weather aggregation in the Asia/Kolkata timezone | 31 rows; values present; timestamps are local-day boundaries |
| `data/processed/era5_land_daily_utc.csv` | Daily aggregation associated with the ERA5-Land experiment | 31 rows, but `PRECTOT_SUM` is 0 each day despite all 744 source precipitation values being null |

The old weather response `archive_utc.json` has no request sidecar, so its
requested coordinates and model cannot be recovered with certainty from the
saved file. The response coordinate and variables are known. The same applies
to `archive_era5_land.json`: its filename and experiment identify the intended
model, but the response JSON itself does not prove the request model.

### Why the ERA5-Land precipitation is null

This is expected model-variable availability, not a zero-rain result or a
temporary parse issue. The current Open-Meteo Historical Weather API
availability table lists soil moisture for ERA5-Land but marks precipitation,
rain and snowfall unavailable. It lists both soil moisture and precipitation
for ERA5 and ECMWF IFS. The all-null `precipitation` array in
`archive_era5_land.json` agrees with that documentation.

The `PRECTOT_SUM=0` values in `era5_land_daily_utc.csv` are an aggregation
artifact: a sum operation on an all-missing group produced zero. That CSV must
not be interpreted as evidence of zero rainfall. Preserve nulls or mark the
field unavailable when aggregating all-missing input.

## Requested coordinates versus returned grid coordinates

The soil metadata records a request at **30.34° N, 76.39° E**, while the
response reports the center of the selected ERA5-Land cell as **30.300003° N,
76.399994° E**. The weather response coordinate is **30.333918° N,
76.389210° E**. Relative to the ERA5-Land cell, that weather coordinate is
0.033915° farther north and 0.010784° farther west, about 3.8 km north and
1.0 km west at this latitude.

The API's `latitude` and `longitude` request values identify a location to
look up; the returned coordinates describe the grid-cell center actually used.
The API documentation says these may be a few kilometres apart. Its default
`cell_selection=land` chooses an appropriate land cell using elevation; the
`nearest` option chooses the nearest available cell. Even when requesting the
returned soil-cell coordinates, another model may select a different center
because its grid differs.

## Controlled three-day test

I made one request to the Open-Meteo Historical Weather API for **Jan 30–Feb 1,
2024**, requesting `precipitation` and all four soil-moisture layers with
`models=ecmwf_ifs`, `timezone=UTC`, and the ERA5-Land returned coordinates
30.300003° N, 76.399994° E. The raw controlled response was saved outside the
repository at `/private/tmp/grainstorm_ifs_compatibility_20240130_20240201.json`;
no existing dataset was changed.

| Check | Result |
|---|---|
| Variables returned | Precipitation and all four requested soil-moisture layers |
| Units | Precipitation mm; soil moisture m³/m³; timestamps ISO 8601 |
| Observations | 72 hourly rows, Jan 30 00:00–Feb 1 23:00 UTC |
| Time alignment | Complete and continuous; no duplicates |
| Missing values | 0 of 72 in precipitation and each soil layer |
| Precipitation over test period | 14.9 mm total; 0.0–3.4 mm per hourly value |
| Returned timezone | GMT, UTC offset 0 |
| Returned coordinate | 30.333918° N, 76.389210° E |
| Coordinate match to requested ERA5-Land cell | No; response cell differs by about 3.8 km north and 1.0 km west |

The tested IFS response provided precipitation and all soil layers together
under one explicit model selection and one returned coordinate. This is a
coherent IFS pairing. It cannot be treated as the same series as the existing
ERA5-Land dataset; the model and returned grid cell differ. Open-Meteo's
response object does not include the selected model name, so applications
should preserve the request parameters alongside each response.

## Candidate sources

| Candidate | What it offers | Compatibility and limitations |
|---|---|---|
| Open-Meteo ERA5-Land | Existing four soil layers, ~0.1° / ~11 km, hourly, historical from 1950 | Precipitation is unavailable in this API model. There is no supported same-model ERA5-Land precipitation field to join. |
| Open-Meteo ECMWF IFS (`ecmwf_ifs`) | Hourly precipitation and the four soil-moisture layers; ~9 km, historical from 2017. Controlled test returned all fields complete | Strong option for a new same-model pair if both soil and rain are acquired as IFS. It does not match existing ERA5-Land values or grid centers; model history is shorter than ERA5/ERA5-Land. |
| Open-Meteo ERA5 (`era5`) | Hourly precipitation and soil moisture at 0.25° / ~25 km, historical from 1940 | A consistent same-model pair is possible if both variables are acquired from ERA5. It is substantially coarser than ERA5-Land. Open-Meteo recommends ERA5/ERA5-Land for long climate series to avoid model-upgrade discontinuities. |
| NASA GPM IMERG Final | Satellite-derived precipitation on a 0.1° grid at 30-minute intervals; 2024 is within its historical record | Spatial spacing is close to ERA5-Land but grid alignment is not guaranteed. It is a different satellite/retrieval product, not ERA5-Land precipitation. Convert half-hourly rates to hourly amounts carefully and retain its independent provenance. Historical research downloads require a NASA data-access workflow. |

NASA describes IMERG as a multisatellite precipitation estimate at about
0.1° (~10 km) and 30-minute resolution. Its half-hourly rates are in mm/hour;
the IMERG guidance treats each rate as representative of that half-hour. To
form hourly accumulation, sum each half-hour rate multiplied by 0.5 hour, while
preserving missing intervals and recording the aggregation rule.

## Recommendation

For future analysis where **same model and a shared returned grid cell** are
the top priorities, acquire precipitation and soil moisture together from
Open-Meteo ECMWF IFS in one explicit-model request. The controlled request
shows those variables are available and time-aligned for the target dates.
Do not use IFS precipitation as though it belonged to the existing
ERA5-Land soil-moisture values. If Grain Storm keeps the ERA5-Land soil series,
use GPM IMERG as a clearly labeled, independent rainfall product after checking
its cell and aggregating its 30-minute data; document that model and spatial
support differ.

The next implementation should make the model choice explicit and store the
request parameters, returned cell coordinates, units, and missingness with
each response. Before production analysis, compare a longer interval and
validate precipitation against an independent gauge or appropriate reference
where available.

## References

- [Open-Meteo Historical Weather API: model/variable availability, cell selection, returned coordinates, and units](https://open-meteo.com/en/docs/historical-weather-api)
- [NASA GPM FAQ: IMERG resolution and half-hourly rate interpretation](https://gpm.nasa.gov/resources/faq)
- [NASA GPM precipitation data directory: IMERG products and download options](https://gpm.nasa.gov/data/directory)
