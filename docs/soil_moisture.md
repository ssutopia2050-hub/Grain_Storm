# Soil moisture source notes

## First acquisition path

Grain Storm's initial soil-moisture connector uses the Open-Meteo Historical
Weather API with the model fixed to ERA5-Land. It requests hourly volumetric
soil water content at four modeled layers: 0–7 cm, 7–28 cm, 28–100 cm, and
100–255 cm. Values are in m³/m³. The implementation is
`grainstorm.sources.soil_moisture.fetch_hourly_soil_moisture`.

```python
from grainstorm.sources.soil_moisture import fetch_hourly_soil_moisture

hourly, metadata, raw_payload = fetch_hourly_soil_moisture(
    latitude=30.34,
    longitude=76.39,
    start_date="2024-01-01",
    end_date="2024-01-31",
)
```

The returned timestamps use the requested timezone (UTC by default). The
connector returns hourly values and does not aggregate depths into a single
root-zone estimate. Missing values remain missing. Call
`inspect_hourly_soil_moisture(hourly)` for a basic integrity report; it flags
missing fields, timestamps and measurements, duplicates, and values outside
the broad physical interval 0–1 m³/m³. This is a screening check, not product
validation.

## How to read the measurements

Soil moisture here is modeled volumetric water content: the volume of water per
volume of soil. It is not rainfall, a percentage of plant-available water, or a
direct measurement at a farm sensor. The shallow 0–7 cm layer responds quickly
to rain and evaporation. Deeper layers generally change more slowly and may be
more relevant to water available below the immediate surface, but modeled
layers do not map exactly to crop rooting depth. In particular, the 28–100 cm
layer is not a crop-specific root-zone value.

ERA5-Land is a reanalysis model product at roughly 0.1° (~11 km) resolution,
with historical data available from 1950 through the archive's current
availability. The API returns the grid-cell coordinates used for the request;
they can differ slightly from the requested point. A grid cell is not a field
measurement. Retain the returned coordinates, model, units, and layer metadata
with each download.

The 0–1 m³/m³ check is only a broad physical screening bound for volumetric
water content. It is not a soil-specific wet/dry classification or a crop
stress threshold. The quality report also identifies missing and nonnumeric
measurements, duplicate or invalid times, and gaps between observed hourly
timestamps. It cannot infer omitted hours before the first or after the last
timestamp unless those expected boundaries are checked against the request.

These values can help describe modeled water content in the soil layers at a
grid cell. By themselves, they do not establish how much water a crop can use
or whether it is stressed. That interpretation also depends on soil texture
and structure, rooting depth, crop type, growth stage, irrigation, and other
conditions. Do not merge these data with NASA POWER weather values as if the
spatial support and modeling were identical.

## Candidate for a later source comparison: NASA SMAP L4

NASA POWER documents daily SMAP L4 surface moisture (0–5 cm) and root-zone
moisture (0–100 cm) at approximately 9 km, with coverage beginning in 2015.
SMAP L4 assimilates satellite brightness temperatures into a land-surface
model; it is not a direct measurement of the entire root zone. NASA POWER says
it has not independently validated these parameters and warns that effective
resolution differs from the meteorological fields. It is a useful secondary
comparison candidate, especially for a surface/root-zone pairing, subject to
checking the current API parameter aliases and request behavior before adding
another connector.

## References

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [NASA POWER hydrology and SMAP methodology](https://power.larc.nasa.gov/docs/methodology/data/sources_hydrology/)
- [NSIDC SMAP Enhanced L3 soil moisture user guide](https://nsidc.org/sites/default/files/spl3smp_e-v004-userguide.pdf)
