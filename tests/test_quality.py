
import unittest
import pandas as pd

from grainstorm.processing.quality import inspect_dataset


class TestQualityInspection(unittest.TestCase):

    def setUp(self):
        """Create a clean sample dataset before every test."""

        self.df = pd.DataFrame({
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
            ],
            "T2M": [20, 21, 22],
            "PRECTOTCORR": [0, 2, 1],
            "RH2M": [50, 60, 70],
        })

    def test_clean_dataset(self):
        report = inspect_dataset(self.df)

        self.assertEqual(report["total_observations"], 3)
        self.assertEqual(report["duplicate_dates"], 0)
        self.assertEqual(report["missing_dates"], [])
        self.assertEqual(report["invalid_dates"], 0)

    def test_empty_dataset(self):
        with self.assertRaises(ValueError):
            inspect_dataset(pd.DataFrame())

    def test_missing_date_column(self):
        df = self.df.drop(columns=["date"])

        with self.assertRaises(ValueError):
            inspect_dataset(df)

    def test_duplicate_dates(self):
        df = self.df.copy()
        df.loc[2, "date"] = "2024-01-02"

        report = inspect_dataset(df)

        self.assertEqual(report["duplicate_dates"], 1)

    def test_missing_dates(self):
        df = self.df.drop(index=1)

        report = inspect_dataset(df)

        self.assertEqual(
            report["missing_dates"],
            ["2024-01-02"]
        )

    def test_invalid_dates(self):
        df = self.df.copy()
        df.loc[2, "date"] = "not-a-date"

        report = inspect_dataset(df)

        self.assertEqual(report["invalid_dates"], 1)

    def test_missing_parameter_column(self):
        df = self.df.drop(columns=["PRECTOTCORR"])

        report = inspect_dataset(df)

        self.assertIn(
            "PRECTOTCORR",
            report["missing_columns"]
        )

    def test_invalid_humidity(self):
        df = self.df.copy()
        df.loc[0, "RH2M"] = 120

        report = inspect_dataset(df)

        self.assertEqual(
            report["out_of_range_values"]["RH2M"],
            1
        )

    def test_missing_values(self):
            df = self.df.copy()
            df.loc[0, "T2M"] = float("nan")

            report = inspect_dataset(df)

            self.assertEqual(report["missing_values"]["T2M"], 1)

    def test_invalid_precipitation(self):
            df = self.df.copy()
            df.loc[0, "PRECTOTCORR"] = -5

            report = inspect_dataset(df)

            self.assertEqual(
                report["out_of_range_values"]["PRECTOTCORR"],
                1
            )


if __name__ == "__main__":
    unittest.main()
