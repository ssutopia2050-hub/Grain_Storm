
import pandas as pd


# Broad screening limits for NASA POWER parameters.
RANGE_RULES = {
    "T2M": (-90, 65),
    "PRECTOTCORR": (0, None),
    "RH2M": (0, 100),
}
REQUIRED_COLUMNS = [
    "date",
    "T2M",
    "PRECTOTCORR",
    "RH2M",
]

OPEN_METEO_REQUIRED_COLUMNS = [
    "time",
    "T2M_MEAN",
    "T2M_MIN",
    "T2M_MAX",
    "RH2M_MEAN",
    "PRECTOT_SUM",
    "HOURS_RECORDED",
]

OPEN_METEO_RANGE_RULES = {
    "T2M_MEAN": (-90, 65),
    "T2M_MIN": (-90, 65),
    "T2M_MAX": (-90, 65),
    "RH2M_MEAN": (0, 100),
    "PRECTOT_SUM": (0, None),
}


def inspect_dataset(dataframe: pd.DataFrame) -> dict:
    """Inspect a dataset for basic data quality issues."""

    report = {}
    # Check whether the dataset is empty.
    if dataframe.empty:
        raise ValueError("Dataset is empty.")

    # Check whether the date column exists.
    if "date" not in dataframe.columns:
        raise ValueError("Dataset must contain a 'date' column.")
    # 1. Total observations
    report["total_observations"] = len(dataframe)
    report["missing_columns"] = [
        column
        for column in REQUIRED_COLUMNS
        if column not in dataframe.columns
    ]
    # 2. Missing values
    report["missing_values"] = (
        dataframe.isna().sum().to_dict()
    )

    # 3. Date checks
    if "date" in dataframe.columns:
        dates = pd.to_datetime(
            dataframe["date"],
            errors="coerce"
        )
        report["invalid_dates"] = int(dates.isna().sum())

        report["duplicate_dates"] = int(
            dates.duplicated().sum()
        )

        valid_dates = dates.dropna()

        if not valid_dates.empty:
            expected_dates = pd.date_range(
                start=valid_dates.min(),
                end=valid_dates.max(),
                freq="D"
            )

            actual_dates = pd.DatetimeIndex(
                valid_dates.unique()
            )

            missing_dates = expected_dates.difference(
                actual_dates
            )

            report["missing_dates"] = [
                date.strftime("%Y-%m-%d")
                for date in missing_dates
            ]
        else:
            report["missing_dates"] = []

    # 4. Parameter range checks
    report["out_of_range_values"] = {}

    for parameter, (minimum, maximum) in RANGE_RULES.items():

        if parameter not in dataframe.columns:
            continue

        values = pd.to_numeric(
            dataframe[parameter],
            errors="coerce"
        )

        invalid = pd.Series(False, index=dataframe.index)

        if minimum is not None:
            invalid |= values < minimum

        if maximum is not None:
            invalid |= values > maximum

        # Ignore missing values here.
        invalid &= values.notna()

        report["out_of_range_values"][parameter] = int(
            invalid.sum()
        )

    return report


def inspect_open_meteo_daily(dataframe: pd.DataFrame) -> dict:
    """Inspect daily Open-Meteo data for quality issues."""

    if dataframe.empty:
        raise ValueError("Dataset is empty.")

    if "time" not in dataframe.columns:
        raise ValueError("Dataset must contain a 'time' column.")

    report = {
        "total_observations": len(dataframe),
        "missing_columns": [
            column
            for column in OPEN_METEO_REQUIRED_COLUMNS
            if column not in dataframe.columns
        ],
        "missing_values": dataframe.isna().sum().to_dict(),
    }

    dates = pd.to_datetime(dataframe["time"], errors="coerce")

    report["invalid_dates"] = int(dates.isna().sum())
    report["duplicate_dates"] = int(dates.duplicated().sum())

    valid_dates = dates.dropna()

    if not valid_dates.empty:
        expected_dates = pd.date_range(
            start=valid_dates.min(),
            end=valid_dates.max(),
            freq="D",
        )

        actual_dates = pd.DatetimeIndex(valid_dates.unique())

        missing_dates = expected_dates.difference(actual_dates)

        report["missing_dates"] = [
            date.strftime("%Y-%m-%d")
            for date in missing_dates
        ]
    else:
        report["missing_dates"] = []

    report["out_of_range_values"] = {}

    for parameter, (minimum, maximum) in OPEN_METEO_RANGE_RULES.items():

        if parameter not in dataframe.columns:
            continue

        values = pd.to_numeric(
            dataframe[parameter],
            errors="coerce",
        )

        invalid = values.notna() & (
            (values < minimum) |
            (values > maximum if maximum is not None else False)
        )

        report["out_of_range_values"][parameter] = int(
            invalid.sum()
        )

        # Check whether each day has all 24 hourly observations.
        if "HOURS_RECORDED" in dataframe.columns:
            hours = pd.to_numeric(
                dataframe["HOURS_RECORDED"],
                errors="coerce",
            )

            report["incomplete_days"] = int(
                (hours != 24).sum()
            )
        else:
            report["incomplete_days"] = None
    # Check logical consistency between temperature measurements.
    temperature_columns = [
        "T2M_MIN",
        "T2M_MEAN",
        "T2M_MAX",
    ]

    if all(
        column in dataframe.columns
        for column in temperature_columns
    ):
        minimum = pd.to_numeric(
            dataframe["T2M_MIN"], errors="coerce"
        )
        mean = pd.to_numeric(
            dataframe["T2M_MEAN"], errors="coerce"
        )
        maximum = pd.to_numeric(
            dataframe["T2M_MAX"], errors="coerce"
        )

        invalid_temperature = (
            (minimum > mean) |
            (mean > maximum)
        )

        report["temperature_consistency_violations"] = int(
            invalid_temperature.sum()
        )

    # Determine overall dataset quality status.
    has_issues = (
        bool(report["missing_columns"])
        or sum(report["missing_values"].values()) > 0
        or report["invalid_dates"] > 0
        or report["duplicate_dates"] > 0
        or len(report["missing_dates"]) > 0
        or sum(report["out_of_range_values"].values()) > 0
        or report.get("incomplete_days", 0) not in (0, None)
        or report.get("temperature_consistency_violations", 0) > 0
    )

    report["status"] = "REVIEW" if has_issues else "PASS"

    return report


def print_quality_report(report: dict) -> None:
    """Print a human-readable dataset quality report."""

    missing_count = sum(
        report["missing_values"].values()
    )

    duplicate_count = report.get("duplicate_dates", 0)

    missing_date_count = len(
        report.get("missing_dates", [])
    )

    invalid_count = sum(
        report["out_of_range_values"].values()
    )
    invalid_date_count = report.get("invalid_dates", 0)
    missing_column_count = len(report["missing_columns"])
    total_issues = (
            missing_count
            + duplicate_count
            + missing_date_count
            + invalid_date_count
            + invalid_count
            +missing_column_count
    )

    status = "PASS" if total_issues == 0 else "REVIEW"

    print("\nGRAIN STORM | DATA QUALITY REPORT")
    print("=" * 40)

    print(f"Observations: {report['total_observations']}")

    print("\nMissing values:")
    for parameter, count in report["missing_values"].items():
        print(f"  {parameter}: {count}")

    print("\nDate checks:")
    print(f"  Duplicate dates: {duplicate_count}")
    print(f"  Missing dates: {missing_date_count}")
    print(
        f"  Invalid dates: {report.get('invalid_dates', 0)}"
    )
    print("\nMissing columns:")
    for column in report["missing_columns"]:
        print(f"  {column}")
    print("\nInvalid parameter values:")
    for parameter, count in report["out_of_range_values"].items():
        print(f"  {parameter}: {count}")

    print("\n" + "=" * 40)
    print(f"Total detected issues: {total_issues}")
    print(f"Overall status: {status}")

def print_open_meteo_quality_report(report: dict) -> None:
    """Print a human-readable Open-Meteo quality report."""

    print("\nGRAIN STORM | OPEN-METEO QUALITY REPORT")
    print("=" * 45)

    print(f"Observations: {report['total_observations']}")

    print("\nMissing values:")
    for parameter, count in report["missing_values"].items():
        print(f"  {parameter}: {count}")

    print("\nDate checks:")
    print(f"  Invalid dates: {report['invalid_dates']}")
    print(f"  Duplicate dates: {report['duplicate_dates']}")
    print(f"  Missing dates: {len(report['missing_dates'])}")

    print("\nMissing columns:")
    if report["missing_columns"]:
        for column in report["missing_columns"]:
            print(f"  {column}")
    else:
        print("  None")

    print("\nOut-of-range values:")
    for parameter, count in report["out_of_range_values"].items():
        print(f"  {parameter}: {count}")

    print("\nAdditional checks:")
    print(f"  Incomplete days: {report['incomplete_days']}")
    print(
        "  Temperature consistency violations: "
        f"{report['temperature_consistency_violations']}"
    )

    print("\n" + "=" * 45)
    print(f"Overall status: {report['status']}")
