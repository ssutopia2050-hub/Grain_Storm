import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from grainstorm.sources.soil_moisture import (
    SOIL_MOISTURE_COLUMNS,
    SoilMoistureError,
    fetch_hourly_soil_moisture,
    inspect_hourly_soil_moisture,
)


def make_payload(times=None, timezone="UTC"):
    times = times or [
        "2024-01-01T00:00",
        "2024-01-01T01:00",
        "2024-01-01T02:00",
    ]
    return {
        "latitude": 30.375,
        "longitude": 76.375,
        "elevation": 250,
        "timezone": timezone,
        "utc_offset_seconds": 0,
        "hourly": {
            "time": times,
            "soil_moisture_0_to_7cm": [0.10, 0.11, 0.12][:len(times)],
            "soil_moisture_7_to_28cm": [0.20, 0.21, 0.22][:len(times)],
            "soil_moisture_28_to_100cm": [0.30, 0.31, 0.32][:len(times)],
            "soil_moisture_100_to_255cm": [0.40, 0.41, 0.42][:len(times)],
        },
        "hourly_units": {
            name: "m³/m³"
            for name in (
                "soil_moisture_0_to_7cm",
                "soil_moisture_7_to_28cm",
                "soil_moisture_28_to_100cm",
                "soil_moisture_100_to_255cm",
            )
        },
    }


class TestSoilMoistureFetch(unittest.TestCase):
    def setUp(self):
        self.payload = make_payload()
        self.response = Mock()
        self.response.json.return_value = self.payload

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_valid_response_parses_all_layers_and_request(self, get):
        get.return_value = self.response
        dataframe, metadata, raw = fetch_hourly_soil_moisture(
            30.34, 76.39, "2024-01-01", "2024-01-31"
        )

        self.assertEqual(len(dataframe), 3)
        self.assertEqual(list(dataframe.columns), ["time", *SOIL_MOISTURE_COLUMNS])
        self.assertEqual(dataframe.loc[0, "SOIL_MOISTURE_0_7CM"], 0.10)
        self.assertEqual(dataframe.loc[0, "SOIL_MOISTURE_7_28CM"], 0.20)
        self.assertEqual(dataframe.loc[0, "SOIL_MOISTURE_28_100CM"], 0.30)
        self.assertEqual(dataframe.loc[0, "SOIL_MOISTURE_100_255CM"], 0.40)
        self.assertEqual(str(dataframe["time"].dt.tz), "UTC")
        self.assertEqual(metadata["model"], "ERA5-Land")
        self.assertEqual(metadata["api_units"]["soil_moisture_0_to_7cm"], "m³/m³")
        self.assertEqual(metadata["response_metadata"]["latitude"], 30.375)
        self.assertIs(raw, self.payload)
        request_params = get.call_args.kwargs["params"]
        self.assertEqual(request_params["models"], "era5_land")
        self.assertEqual(request_params["timezone"], "UTC")

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_requested_timezone_is_applied_to_naive_api_times(self, get):
        self.payload = make_payload(timezone="Asia/Kolkata")
        self.response.json.return_value = self.payload
        get.return_value = self.response

        dataframe, _, _ = fetch_hourly_soil_moisture(
            30.34, 76.39, "2024-01-01", "2024-01-01", timezone="Asia/Kolkata"
        )

        self.assertEqual(str(dataframe["time"].dt.tz), "Asia/Kolkata")
        self.assertEqual(dataframe.loc[0, "time"].hour, 0)

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_missing_values_are_preserved(self, get):
        self.payload["hourly"]["soil_moisture_7_to_28cm"][1] = None
        self.response.json.return_value = self.payload
        get.return_value = self.response

        dataframe, _, _ = fetch_hourly_soil_moisture(
            30.34, 76.39, "2024-01-01", "2024-01-01"
        )

        self.assertTrue(pd.isna(dataframe.loc[1, "SOIL_MOISTURE_7_28CM"]))
        self.assertEqual(
            inspect_hourly_soil_moisture(dataframe)["missing_values"]["SOIL_MOISTURE_7_28CM"],
            1,
        )

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_invalid_coordinates_dates_and_order_are_rejected_without_request(self, get):
        invalid_requests = [
            (91, 76.39, "2024-01-01", "2024-01-31"),
            (30.34, 181, "2024-01-01", "2024-01-31"),
            (30.34, 76.39, "01-01-2024", "2024-01-31"),
            (30.34, 76.39, "2024-02-01", "2024-01-31"),
        ]
        for args in invalid_requests:
            with self.subTest(args=args), self.assertRaises(ValueError):
                fetch_hourly_soil_moisture(*args)
        get.assert_not_called()

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_api_request_failure_is_wrapped(self, get):
        get.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(SoilMoistureError):
            fetch_hourly_soil_moisture(
                30.34, 76.39, "2024-01-01", "2024-01-31"
            )

    @patch("grainstorm.sources.soil_moisture.requests.get")
    def test_malformed_api_responses_are_wrapped(self, get):
        cases = [
            {"error": True},
            {"hourly": {"time": ["2024-01-01T00:00"]}},
            {
                "hourly": {
                    "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
                    **{
                        "soil_moisture_0_to_7cm": [0.1],
                        "soil_moisture_7_to_28cm": [0.2],
                        "soil_moisture_28_to_100cm": [0.3],
                        "soil_moisture_100_to_255cm": [0.4],
                    },
                }
            },
        ]
        for payload in cases:
            response = Mock()
            response.json.return_value = payload
            get.return_value = response
            with self.subTest(payload=payload), self.assertRaises(SoilMoistureError):
                fetch_hourly_soil_moisture(
                    30.34, 76.39, "2024-01-01", "2024-01-01"
                )


class TestSoilMoistureQuality(unittest.TestCase):
    def setUp(self):
        self.dataframe = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"),
            "SOIL_MOISTURE_0_7CM": [0.1, 0.2, 0.3],
            "SOIL_MOISTURE_7_28CM": [0.2, 0.3, 0.4],
            "SOIL_MOISTURE_28_100CM": [0.3, 0.4, 0.5],
            "SOIL_MOISTURE_100_255CM": [0.4, 0.5, 0.6],
        })

    def test_clean_dataset_passes(self):
        report = inspect_hourly_soil_moisture(self.dataframe)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["missing_timestamps"], [])
        self.assertEqual(report["duplicate_timestamps"], 0)

    def test_out_of_range_values_are_reported(self):
        self.dataframe.loc[0, "SOIL_MOISTURE_0_7CM"] = 1.01
        self.dataframe.loc[1, "SOIL_MOISTURE_7_28CM"] = -0.01
        report = inspect_hourly_soil_moisture(self.dataframe)
        self.assertEqual(report["out_of_range_values"]["SOIL_MOISTURE_0_7CM"], 1)
        self.assertEqual(report["out_of_range_values"]["SOIL_MOISTURE_7_28CM"], 1)
        self.assertEqual(report["status"], "REVIEW")

    def test_non_numeric_values_are_reported(self):
        self.dataframe["SOIL_MOISTURE_0_7CM"] = self.dataframe[
            "SOIL_MOISTURE_0_7CM"
        ].astype(object)
        self.dataframe.loc[1, "SOIL_MOISTURE_0_7CM"] = "not numeric"
        report = inspect_hourly_soil_moisture(self.dataframe)
        self.assertEqual(report["non_numeric_values"]["SOIL_MOISTURE_0_7CM"], 1)
        self.assertEqual(report["missing_values"]["SOIL_MOISTURE_0_7CM"], 0)
        self.assertEqual(report["status"], "REVIEW")

    def test_missing_hour_is_reported(self):
        dataframe = self.dataframe.drop(index=1).reset_index(drop=True)
        report = inspect_hourly_soil_moisture(dataframe)
        self.assertEqual(report["missing_timestamps"], ["2024-01-01T01:00:00+00:00"])
        self.assertEqual(report["status"], "REVIEW")

    def test_missing_layer_is_reported(self):
        dataframe = self.dataframe.drop(columns=["SOIL_MOISTURE_28_100CM"])
        report = inspect_hourly_soil_moisture(dataframe)
        self.assertEqual(report["missing_columns"], ["SOIL_MOISTURE_28_100CM"])
        self.assertEqual(report["status"], "REVIEW")

    def test_duplicate_and_invalid_timestamps_are_reported(self):
        dataframe = self.dataframe.copy()
        dataframe.loc[2, "time"] = dataframe.loc[1, "time"]
        report = inspect_hourly_soil_moisture(dataframe)
        self.assertEqual(report["duplicate_timestamps"], 1)
        dataframe["time"] = dataframe["time"].astype(object)
        dataframe.loc[0, "time"] = "not a timestamp"
        report = inspect_hourly_soil_moisture(dataframe)
        self.assertEqual(report["invalid_timestamps"], 1)


if __name__ == "__main__":
    unittest.main()
