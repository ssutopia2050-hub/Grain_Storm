import unittest
from datetime import date
from unittest.mock import Mock, patch

from grainstorm.sources.forecast import ForecastError, fetch_daily_forecast


class ForecastTests(unittest.TestCase):
    @patch("grainstorm.sources.forecast.requests.get")
    def test_normalizes_complete_utc_daily_forecast(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "timezone": "GMT", "generationtime_ms": 1.2,
            "daily": {
                "time": ["2026-11-14", "2026-11-15"],
                "precipitation_sum": [2, 0],
                "et0_fao_evapotranspiration": [3.1, 3.2],
                "precipitation_probability_max": [70, 10],
            },
        }
        get.return_value = response
        rows, metadata = fetch_daily_forecast(
            30.34, 76.39, "2026-11-14", "2026-11-15", today=date(2026, 11, 14)
        )
        self.assertEqual(rows[0]["rain_mm"], 2)
        self.assertEqual(rows[1]["et0_mm"], 3.2)
        self.assertEqual(metadata["forecast_horizon_limit_days"], 16)
        self.assertEqual(get.call_args.kwargs["params"]["timezone"], "UTC")

    def test_rejects_long_range_as_fake_precision(self):
        with self.assertRaisesRegex(ValueError, "limited to 16 days"):
            fetch_daily_forecast(
                30.34, 76.39, "2026-11-14", "2026-12-01", today=date(2026, 11, 14)
            )

    @patch("grainstorm.sources.forecast.requests.get")
    def test_rejects_partial_coverage(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"daily": {
            "time": ["2026-11-14"], "precipitation_sum": [0],
            "et0_fao_evapotranspiration": [2], "precipitation_probability_max": [0],
        }}
        get.return_value = response
        with self.assertRaises(ForecastError):
            fetch_daily_forecast(
                30.34, 76.39, "2026-11-14", "2026-11-15", today=date(2026, 11, 14)
            )


if __name__ == "__main__":
    unittest.main()
