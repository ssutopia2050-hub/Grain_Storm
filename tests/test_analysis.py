
import unittest
import pandas as pd

from grainstorm.processing.analysis import analyze_rainfall
from grainstorm.processing.analysis import analyze_dry_spells

class TestRainfallAnalysis(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
            ],
            "PRECTOTCORR": [0, 2, 0, 6],
        })

    def test_rainy_days(self):
        report = analyze_rainfall(self.df)
        self.assertEqual(report["rainy_days"], 2)

    def test_dry_days(self):
        report = analyze_rainfall(self.df)
        self.assertEqual(report["dry_days"], 2)

    def test_total_precipitation(self):
        report = analyze_rainfall(self.df)
        self.assertEqual(report["total_precipitation"], 8)

    def test_maximum_rainfall(self):
        report = analyze_rainfall(self.df)
        self.assertEqual(report["maximum_rainfall"], 6)

    def test_maximum_rainfall_date(self):
        report = analyze_rainfall(self.df)
        self.assertEqual(
            report["maximum_rainfall_date"],
            "2024-01-04"
        )

    def test_missing_precipitation_column(self):
        df = self.df.drop(columns=["PRECTOTCORR"])

        with self.assertRaises(ValueError):
            analyze_rainfall(df)

class TestDrySpellAnalysis(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "date": pd.date_range(
                start="2024-01-01",
                periods=8,
                freq="D"
            ),
            "PRECTOTCORR": [0, 0, 0, 5, 0, 0, 2, 0]
        })

    def test_number_of_dry_spells(self):
        result = analyze_dry_spells(self.df)
        self.assertEqual(result["number_of_dry_spells"], 3)

    def test_longest_dry_spell(self):
        result = analyze_dry_spells(self.df)
        self.assertEqual(result["longest_dry_spell"], 3)

    def test_dry_spell_durations(self):
        result = analyze_dry_spells(self.df)

        durations = [
            spell["duration"]
            for spell in result["dry_spells"]
        ]

        self.assertEqual(durations, [3, 2, 1])

    def test_dry_spell_dates(self):
        result = analyze_dry_spells(self.df)

        first_spell = result["dry_spells"][0]

        self.assertEqual(first_spell["start_date"], "2024-01-01")
        self.assertEqual(first_spell["end_date"], "2024-01-03")

    def test_no_dry_spells(self):
        df = self.df.copy()
        df["PRECTOTCORR"] = [1, 2, 3, 4, 5, 6, 7, 8]

        result = analyze_dry_spells(df)

        self.assertEqual(result["number_of_dry_spells"], 0)
        self.assertEqual(result["longest_dry_spell"], 0)

    def test_missing_dates_are_rejected(self):
        df = self.df.drop(index=3)

        with self.assertRaises(ValueError):
            analyze_dry_spells(df)

    def test_negative_rainfall_is_rejected(self):
        df = self.df.copy()
        df.loc[0, "PRECTOTCORR"] = -5

        with self.assertRaises(ValueError):
            analyze_dry_spells(df)


if __name__ == "__main__":
    unittest.main()
