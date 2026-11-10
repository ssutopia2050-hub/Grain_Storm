
# Grain Storm 

A generalized agricultural monitoring and environmental data analysis framework using NASA datasets.

## Current Status

**Milestone 1: NASA POWER data acquisition — complete.**

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
- NASA SMAP

## Long-term direction

Build a reusable pipeline for acquiring, processing and analysing environmental datasets that can support agricultural monitoring across different geographical regions and crops.
