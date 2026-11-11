
# Grain Storm 

A generalized agricultural monitoring and environmental data analysis framework using NASA datasets.

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

## Testing

```bash
python -m unittest discover -s tests -v
```

## Planned data sources

- NASA POWER
- NASA ECOSTRESS
- NASA GPM IMERG
- NASA SMAP L4 (candidate for comparison with ERA5-Land)

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
