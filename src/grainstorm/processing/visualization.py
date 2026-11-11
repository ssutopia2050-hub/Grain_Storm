
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

def plot_environmental_data(
    dataframe: pd.DataFrame,
    output_path: str = "data/processed/environmental_data.png",
) -> None:
    """Generate plots for NASA POWER environmental observations."""

    required_columns = [
        "date",
        "T2M",
        "PRECTOTCORR",
        "RH2M",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    df = dataframe.copy()

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    if df["date"].isna().any():
        raise ValueError("Dataset contains invalid dates.")

    df = df.sort_values("date")

    # Create three vertically stacked plots.
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(12, 10),
        sharex=True,
    )

    # Temperature
    axes[0].plot(
        df["date"],
        df["T2M"],
        marker="o",
    )
    axes[0].set_title("Daily Temperature")
    axes[0].set_ylabel("Temperature (°C)")
    axes[0].grid(True, alpha=0.3)

    # Precipitation
    axes[1].bar(
        df["date"],
        df["PRECTOTCORR"],
    )
    axes[1].set_title("Daily Precipitation")
    axes[1].set_ylabel("Precipitation (mm/day)")
    axes[1].grid(True, alpha=0.3)

    # Relative humidity
    axes[2].plot(
        df["date"],
        df["RH2M"],
        marker="o",
    )
    axes[2].set_title("Relative Humidity")
    axes[2].set_ylabel("Humidity (%)")
    axes[2].set_xlabel("Date")
    axes[2].grid(True, alpha=0.3)

    fig.suptitle(
        "GRAIN STORM | Environmental Data Analysis",
        fontsize=15,
    )

    fig.tight_layout()

    # Save the generated visualization.
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Visualization saved to: {output}")

def plot_correlations(
    dataframe: pd.DataFrame,
    output_path: str = "data/processed/correlation_plots.png",
) -> None:
    """Generate scatter plots with linear trend lines."""

    relationships = [
        ("T2M", "RH2M", "Temperature vs Humidity"),
        ("T2M", "PRECTOTCORR", "Temperature vs Precipitation"),
        ("PRECTOTCORR", "RH2M", "Precipitation vs Humidity"),
    ]

    fig, axes = plt.subplots(
        1, 3, figsize=(17, 5)
    )

    for ax, (x_column, y_column, title) in zip(
        axes, relationships
    ):
        clean_data = dataframe[
            [x_column, y_column]
        ].dropna()

        x = clean_data[x_column].to_numpy()
        y = clean_data[y_column].to_numpy()

        # Plot individual observations.
        ax.scatter(x, y)

        # Calculate and draw a linear trend line.
        if len(x) >= 2 and len(set(x)) >= 2:
            slope, intercept = np.polyfit(x, y, 1)

            trend_x = np.linspace(x.min(), x.max(), 100)
            trend_y = slope * trend_x + intercept

            ax.plot(trend_x, trend_y)

        correlation = clean_data.corr().iloc[0, 1]

        ax.set_title(
            f"{title}\nr = {correlation:.3f}"
        )
        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)
        ax.grid(True, alpha=0.3)

    fig.suptitle(
        "GRAIN STORM | Environmental Correlations",
        fontsize=15,
    )

    fig.tight_layout()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Correlation plots saved to: {output}")
