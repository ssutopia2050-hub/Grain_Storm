
import pandas as pd

# Load datasets
nasa = pd.read_csv("data/processed/power_daily.csv")
era5 = pd.read_csv("data/processed/era5_land_daily_utc.csv")

# Normalize dates
nasa["date"] = pd.to_datetime(nasa["date"]).dt.date
era5["date"] = pd.to_datetime(
    era5["time"], utc=True
).dt.date

# Select comparable variables
nasa = nasa[["date", "T2M", "RH2M"]]

era5 = era5[
    ["date", "T2M_MEAN", "RH2M_MEAN"]
].rename(columns={
    "T2M_MEAN": "ERA5_T2M",
    "RH2M_MEAN": "ERA5_RH2M",
})

# Match dates
comparison = pd.merge(
    nasa,
    era5,
    on="date",
    how="inner"
)

# Calculate differences
comparison["TEMP_DIFF"] = (
    comparison["ERA5_T2M"] - comparison["T2M"]
)

comparison["HUMIDITY_DIFF"] = (
    comparison["ERA5_RH2M"] - comparison["RH2M"]
)

print("\nMATCHED OBSERVATIONS:", len(comparison))

print("\nDAILY COMPARISON")
print(comparison.head(10).to_string(index=False))

print("\nAVERAGE DIFFERENCES (ERA5-LAND - NASA)")
print(comparison[
    ["TEMP_DIFF", "HUMIDITY_DIFF"]
].mean())

print("\nMEAN ABSOLUTE DIFFERENCES")
print(comparison[
    ["TEMP_DIFF", "HUMIDITY_DIFF"]
].abs().mean())

print("\nCORRELATIONS")
print("Temperature:",
      comparison["T2M"].corr(comparison["ERA5_T2M"]))

print("Humidity:",
      comparison["RH2M"].corr(comparison["ERA5_RH2M"]))

# Save
comparison.to_csv(
    "data/processed/era5_land_comparison.csv",
    index=False
)

print("\nSaved: data/processed/era5_land_comparison.csv")
