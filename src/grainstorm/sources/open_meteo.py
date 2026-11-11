
import pandas as pd


def parse_hourly_data(payload):
    hourly = payload["hourly"]

    timezone = payload["timezone"]

    timestamps = pd.to_datetime(hourly["time"])
    timestamps = timestamps.tz_localize(timezone)

    dataframe = pd.DataFrame({
        "time": timestamps,
        "T2M": hourly["temperature_2m"],
        "RH2M": hourly["relative_humidity_2m"],
        "PRECTOT": hourly["precipitation"],
    })

    return dataframe

def aggregate_daily_data(dataframe):
    """
    Convert hourly environmental observations into daily summaries.
    """

    daily = (
        dataframe
        .set_index("time")
        .resample("D")
        .agg(
            T2M_MEAN=("T2M", "mean"),
            T2M_MIN=("T2M", "min"),
            T2M_MAX=("T2M", "max"),
            RH2M_MEAN=("RH2M", "mean"),
            PRECTOT_SUM=(
                "PRECTOT",
                lambda values: values.sum(min_count=1)
            ),
            HOURS_RECORDED=("T2M", "count"),
        )
        .reset_index()
    )

    return daily
