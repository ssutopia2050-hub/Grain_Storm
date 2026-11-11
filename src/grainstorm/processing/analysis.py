
import pandas as pd


def summarize_environmental_data(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:

    parameters = [
        "T2M",
        "PRECTOTCORR",
        "RH2M",
    ]
    summary = dataframe[parameters].describe()

    return summary

def calculate_correlations(
            dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Calculate pairwise correlations between environmental parameters."""

        parameters = [
            "T2M",
            "PRECTOTCORR",
            "RH2M",
        ]

        return dataframe[parameters].corr()


def analyze_rainfall(
    dataframe: pd.DataFrame,
) -> dict:
    """Calculate basic rainfall statistics."""

    if "PRECTOTCORR" not in dataframe.columns:
        raise ValueError(
            "Dataset must contain PRECTOTCORR."
        )

    rainfall = pd.to_numeric(
        dataframe["PRECTOTCORR"],
        errors="coerce"
    ).dropna()

    if rainfall.empty:
        raise ValueError("No valid precipitation observations.")

    # Separate rainy days from dry days.
    rainy_days = rainfall[rainfall > 0]
    dry_days = rainfall[rainfall == 0]

    # Calculate the maximum rainfall observation.
    max_index = rainfall.idxmax()

    max_rainfall = rainfall.loc[max_index]

    # Find the corresponding date, if available.
    max_rainfall_date = None

    if "date" in dataframe.columns:
        max_rainfall_date = str(
            dataframe.loc[max_index, "date"]
        )

    # Calculate rainfall statistics.
    report = {
        "total_observations": len(rainfall),
        "rainy_days": len(rainy_days),
        "dry_days": len(dry_days),
        "total_precipitation": float(rainfall.sum()),
        "average_rainfall_on_rainy_days": float(
            rainy_days.mean() if not rainy_days.empty else 0
        ),
        "maximum_rainfall": float(max_rainfall),
        "maximum_rainfall_date": max_rainfall_date,
        "dry_day_percentage": float(
            len(dry_days) / len(rainfall) * 100
        ),
    }

    return report



def analyze_dry_spells(dataframe: pd.DataFrame) -> dict:
    """Identify consecutive days with zero precipitation."""

    if "date" not in dataframe.columns:
        raise ValueError("Dataset must contain date.")

    if "PRECTOTCORR" not in dataframe.columns:
        raise ValueError("Dataset must contain PRECTOTCORR.")

    df = dataframe[["date", "PRECTOTCORR"]].copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["PRECTOTCORR"] = pd.to_numeric(
        df["PRECTOTCORR"], errors="coerce"
    )

    if df["date"].isna().any() or df["PRECTOTCORR"].isna().any():
        raise ValueError("Invalid dates or precipitation values.")

    df = df.sort_values("date")

    if df["date"].duplicated().any():
        raise ValueError("Duplicate dates found.")

    if (df["PRECTOTCORR"] < 0).any():
        raise ValueError("Negative precipitation found.")

    # Ensure observations are from consecutive calendar days.
    date_gaps = df["date"].diff().dropna()
    if not date_gaps.eq(pd.Timedelta(days=1)).all():
        raise ValueError("Dataset contains missing or non-consecutive dates.")

    dry = df["PRECTOTCORR"] == 0
    groups = (~dry).cumsum()

    spells = (
        df[dry]
        .groupby(groups[dry])
        .agg(
            duration=("date", "size"),
            start_date=("date", "min"),
            end_date=("date", "max"),
        )
    )

    return {
        "number_of_dry_spells": len(spells),
        "longest_dry_spell": (
            int(spells["duration"].max()) if not spells.empty else 0
        ),
        "dry_spells": [
            {
                "duration": int(row.duration),
                "start_date": str(row.start_date.date()),
                "end_date": str(row.end_date.date()),
            }
            for row in spells.itertuples()
        ],
    }
