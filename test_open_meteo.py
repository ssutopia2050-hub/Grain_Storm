
import json
from pathlib import Path

from grainstorm.sources.open_meteo import (
    parse_hourly_data,
    aggregate_daily_data,
)

from grainstorm.processing.quality import (
    inspect_open_meteo_daily,
    print_open_meteo_quality_report,
)

output_path = Path("data/processed/open_meteo_daily_ist.csv")
output_path.parent.mkdir(parents=True, exist_ok=True)




with open("archive.json", "r") as file:
    payload = json.load(file)

hourly_df = parse_hourly_data(payload)

daily_df = aggregate_daily_data(hourly_df)

daily_df.to_csv(output_path, index=False)

print("\nOPEN-METEO QUALITY REPORT")

report = inspect_open_meteo_daily(daily_df)

print_open_meteo_quality_report(report)

print(f"\nDaily dataset saved to: {output_path}")
print("HOURLY DATA")
print(hourly_df.head())
print("Shape:", hourly_df.shape)

print("\nDAILY DATA")
print(daily_df.head())
print("Shape:", daily_df.shape)

print("\nHourly observations per day:")
print(daily_df["HOURS_RECORDED"].value_counts())
