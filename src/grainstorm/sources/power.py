
from datetime import datetime
import pandas as pd
import requests

NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/daily/point"
)
DEFAULT_PARAMETERS = [
    "T2M",
    "PRECTOTCORR",
    "RH2M",
]
class NasaPowerError(Exception):
    """Raised when NASA POWER data cannot be retrieved or parsed."""


def validate_inputs(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> None:
    """Validate coordinates and date inputs."""

    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")

    try:
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(
            "Dates must use YYYYMMDD format."
        ) from exc

    if start > end:
        raise ValueError("Start date cannot be after end date.")

    if start < datetime(1981, 1, 1):
        raise ValueError("Start date must be 19810101 or later.")


def fetch_daily_point(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    parameters: list[str] | None = None,
    community: str = "AG",
) -> tuple[pd.DataFrame, dict, dict]:
    """
    Fetch daily NASA POWER observations for one coordinate.

    Returns:
        A DataFrame containing observations and a metadata dictionary.
    """

    validate_inputs(
        latitude,
        longitude,
        start_date,
        end_date,
    )

    selected_parameters = parameters or DEFAULT_PARAMETERS

    params = {
        "start": start_date,
        "end": end_date,
        "latitude": latitude,
        "longitude": longitude,
        "community": community,
        "parameters": ",".join(selected_parameters),
        "format": "JSON",
        "units": "METRIC",
        "time-standard": "UTC",
    }

    try:
        response = requests.get(
            NASA_POWER_URL,
            params=params,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        raise NasaPowerError(
            f"NASA POWER request failed: {exc}"
        ) from exc

    except ValueError as exc:
        raise NasaPowerError(
            "NASA POWER returned invalid JSON."
        ) from exc

    try:
        parameter_data = payload["properties"]["parameter"]

        if not parameter_data:
            raise ValueError("No parameter data was returned.")

        dataframe = pd.DataFrame(parameter_data)

        if dataframe.empty:
            raise ValueError("The returned dataset is empty.")

        dataframe.index = pd.to_datetime(
            dataframe.index,
            format="%Y%m%d",
        )

        dataframe.index.name = "date"

        dataframe = dataframe.sort_index()

        # NASA POWER uses -999 as a missing-data fill value.
        dataframe = dataframe.replace(-999, float("nan"))

        dataframe = dataframe.reset_index()

        metadata = {
            "header": payload.get("header", {}),
            "parameters": payload.get("parameters", {}),
            "geometry": payload.get("geometry", {}),
            "request": params,
        }

        return dataframe, metadata, payload

    except (KeyError, TypeError, ValueError) as exc:
        raise NasaPowerError(
            f"Could not interpret NASA POWER response: {exc}"
        ) from exc

# -999 is a missing-data marker. We convert it to NaN, rather than accidentally treating it as a real temperature or rainfall measurement.