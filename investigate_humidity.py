
import json
import numpy as np
import pandas as pd

with open("archive_humidity.json") as file:
    payload = json.load(file)

hourly = payload["hourly"]

df = pd.DataFrame({
    "time": pd.to_datetime(hourly["time"]),
    "temperature": hourly["temperature_2m"],
    "dew_point": hourly["dew_point_2m"],
    "reported_rh": hourly["relative_humidity_2m"],
})

df["time"] = df["time"].dt.tz_localize(payload["timezone"])

# Calculate relative humidity independently
# Using the Magnus approximation
T = df["temperature"]
Td = df["dew_point"]

df["calculated_rh"] = (
    100 * np.exp(
        (17.625 * Td / (243.04 + Td))
        - (17.625 * T / (243.04 + T))
    )
).clip(0, 100)

df["RH_DIFFERENCE"] = (
    df["reported_rh"] - df["calculated_rh"]
)

print("\nHOURLY DATA")
print(df.head(10).to_string(index=False))

print("\nSUMMARY")
print(df[[
    "reported_rh",
    "calculated_rh",
    "RH_DIFFERENCE"
]].describe())

print("\nCORRELATION")
print(
    df["reported_rh"].corr(df["calculated_rh"])
)

print("\nAVERAGE ABSOLUTE DIFFERENCE")
print(df["RH_DIFFERENCE"].abs().mean())
