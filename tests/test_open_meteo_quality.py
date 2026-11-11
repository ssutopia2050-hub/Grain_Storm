
import unittest
import pandas as pd

from grainstorm.processing.quality import inspect_open_meteo_daily


class TestOpenMeteoQuality(unittest.TestCase):

    def test_valid_dataset(self):
        dataframe = pd.DataFrame({
            "time": pd.to_datetime([
                "2024-01-01",
                "2024-01-02",
            ]),
            "T2M_MEAN": [10.0, 11.0],
            "T2M_MIN": [5.0, 6.0],
            "T2M_MAX": [15.0, 16.0],
            "RH2M_MEAN": [70.0, 75.0],
            "PRECTOT_SUM": [0.0, 2.0],
            "HOURS_RECORDED": [24, 24],
        })

        report = inspect_open_meteo_daily(dataframe)

        self.assertEqual(report["total_observations"], 2)
        self.assertEqual(report["missing_columns"], [])
        self.assertEqual(report["invalid_dates"], 0)
        self.assertEqual(report["duplicate_dates"], 0)
        self.assertEqual(report["missing_dates"], [])
        self.assertEqual(
            report["temperature_consistency_violations"], 0
        )
        self.assertEqual(report["status"], "PASS")


    def test_invalid_temperature_relationship(self):
        dataframe = pd.DataFrame({
            "time": pd.to_datetime([
                "2024-01-01",
                "2024-01-02",
            ]),
            "T2M_MEAN": [10.0, 11.0],
            "T2M_MIN": [5.0, 12.0],
            "T2M_MAX": [15.0, 16.0],
            "RH2M_MEAN": [70.0, 75.0],
            "PRECTOT_SUM": [0.0, 2.0],
            "HOURS_RECORDED": [24, 24],
        })

        report = inspect_open_meteo_daily(dataframe)

        self.assertEqual(
            report["temperature_consistency_violations"], 1
        )
        self.assertEqual(report["status"], "REVIEW")


    def test_incomplete_day(self):
        dataframe = pd.DataFrame({
            "time": pd.to_datetime([
                "2024-01-01",
                "2024-01-02",
            ]),
            "T2M_MEAN": [10.0, 11.0],
            "T2M_MIN": [5.0, 6.0],
            "T2M_MAX": [15.0, 16.0],
            "RH2M_MEAN": [70.0, 75.0],
            "PRECTOT_SUM": [0.0, 2.0],
            "HOURS_RECORDED": [24, 20],
        })

        report = inspect_open_meteo_daily(dataframe)

        self.assertEqual(report["incomplete_days"], 1)
        self.assertEqual(report["status"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
