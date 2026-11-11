
import json

# NASA POWER metadata
with open(
    "data/raw/power_daily_20240101_20240131.json"
) as file:
    nasa = json.load(file)

# Open-Meteo metadata
with open("archive_utc.json") as file:
    open_meteo = json.load(file)

print("\nNASA POWER")
print("==========")
print("Header:")
print(json.dumps(nasa.get("header"), indent=2))

print("\nParameters:")
print(json.dumps(
    nasa.get("parameters", nasa.get("properties", {}).get("parameter", {})),
    indent=2
))

print("\nGeometry:")
print(json.dumps(nasa.get("geometry"), indent=2))

print("\nOPEN-METEO")
print("==========")
print("Coordinates:")
print(open_meteo.get("latitude"), open_meteo.get("longitude"))

print("Elevation:")
print(open_meteo.get("elevation"))

print("Timezone:")
print(open_meteo.get("timezone"))

print("Hourly units:")
print(json.dumps(open_meteo.get("hourly_units"), indent=2))

print("Daily units:")
print(json.dumps(open_meteo.get("daily_units"), indent=2))
