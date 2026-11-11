
import pandas as pd

# Load both daily datasets
nasa = pd.read_csv("data/processed/power_daily.csv")
open_meteo = pd.read_csv("data/processed/open_meteo_daily_utc.csv")

# Convert both date columns to a common date format
nasa["date"] = pd.to_datetime(nasa["date"]).dt.date
open_meteo["date"] = pd.to_datetime(
    open_meteo["time"], utc=True
).dt.date

# Keep only the variables we want to compare
nasa = nasa[["date", "T2M", "RH2M", "PRECTOTCORR"]]

open_meteo = open_meteo[
    ["date", "T2M_MEAN", "RH2M_MEAN", "PRECTOT_SUM"]
]

# Give corresponding variables common names
open_meteo = open_meteo.rename(columns={
    "T2M_MEAN": "OPEN_METEO_T2M",
    "RH2M_MEAN": "OPEN_METEO_RH2M",
    "PRECTOT_SUM": "OPEN_METEO_PRECTOT",
})

# Match records by date
comparison = pd.merge(
    nasa,
    open_meteo,
    on="date",
    how="inner"
)

# Calculate differences: Open-Meteo minus NASA
comparison["TEMP_DIFF"] = (
    comparison["OPEN_METEO_T2M"] - comparison["T2M"]
)

comparison["HUMIDITY_DIFF"] = (
    comparison["OPEN_METEO_RH2M"] - comparison["RH2M"]
)

comparison["PRECIP_DIFF"] = (
    comparison["OPEN_METEO_PRECTOT"] - comparison["PRECTOTCORR"]
)

print("\nMATCHED OBSERVATIONS:", len(comparison))

print("\nDAILY COMPARISON")
print(comparison.head(10).to_string(index=False))

print("\nAVERAGE DIFFERENCES (OPEN-METEO - NASA)")
print(comparison[
    ["TEMP_DIFF", "HUMIDITY_DIFF", "PRECIP_DIFF"]
].mean())

print("\nMEAN ABSOLUTE DIFFERENCES")
print(comparison[
    ["TEMP_DIFF", "HUMIDITY_DIFF", "PRECIP_DIFF"]
].abs().mean())

print("\nCORRELATIONS BETWEEN SOURCES")
print(pd.DataFrame({
    "Temperature": [
        comparison["T2M"].corr(comparison["OPEN_METEO_T2M"])
    ],
    "Humidity": [
        comparison["RH2M"].corr(comparison["OPEN_METEO_RH2M"])
    ],
    "Precipitation": [
        comparison["PRECTOTCORR"].corr(
            comparison["OPEN_METEO_PRECTOT"]
        )
    ],
}).T.rename(columns={0: "Correlation"}))

# Save the comparison for further analysis
comparison.to_csv(
    "data/processed/source_comparison.csv",
    index=False
)

print("\nSaved: data/processed/source_comparison.csv")
