
import requests
import json

url = "https://power.larc.nasa.gov/api/temporal/hourly/point"

params = {
    "parameters": "T2M,RH2M",
    "community": "AG",
    "longitude": 76.39,
    "latitude": 30.34,
    "start": "20240101",
    "end": "20240131",
    "format": "JSON",
    "time-standard": "UTC",
}

response = requests.get(url, params=params, timeout=60)
response.raise_for_status()

payload = response.json()

with open("nasa_hourly.json", "w") as file:
    json.dump(payload, file, indent=2)

print("Download successful!")

print("Parameters:", payload["properties"]["parameter"].keys())

for parameter, values in payload["properties"]["parameter"].items():
    print(parameter, "records:", len(values))
