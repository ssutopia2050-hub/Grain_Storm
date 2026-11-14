"""Offline tests for USDA NASS yield and price records."""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.sources.nass import fetch_us_crop_statistics


def response(records):
    value = Mock()
    value.raise_for_status.return_value = None
    value.json.return_value = {"data": records}
    return value


class NassTests(unittest.TestCase):
    def test_missing_server_key_is_explicit(self):
        with patch.dict("os.environ", {}, clear=True):
            result = fetch_us_crop_statistics("IA", 2024, ["grain_maize"])
        self.assertEqual(result["status"], "auth_required")
        self.assertEqual(result["records"], [])

    @patch("grainstorm.sources.nass.requests.get")
    def test_values_and_suppression_codes_are_preserved(self, get):
        get.side_effect = [
            response([{"Value": "201.0", "unit_desc": "BU / ACRE", "short_desc": "CORN, GRAIN - YIELD",
                       "util_practice_desc": "GRAIN", "reference_period_desc": "YEAR",
                       "year": "2024", "state_name": "IOWA"}]),
            response([{"Value": "(D)", "unit_desc": "$ / BU", "short_desc": "CORN, GRAIN - PRICE RECEIVED",
                       "util_practice_desc": "GRAIN", "reference_period_desc": "MARKETING YEAR",
                       "year": "2024", "state_name": "IOWA"}]),
        ]
        result = fetch_us_crop_statistics("ia", 2024, ["grain_maize"], api_key="secret")
        self.assertEqual(result["records"][0]["value"], 201.0)
        self.assertIsNone(result["records"][1]["value"])
        self.assertEqual(result["records"][1]["raw_value"], "(D)")
        self.assertNotIn("secret", str(result))

    @patch("grainstorm.sources.nass.requests.get")
    def test_final_grain_records_become_metric_planner_baseline(self, get):
        get.side_effect = [
            response([{"Value": "211", "unit_desc": "BU / ACRE", "short_desc": "CORN, GRAIN - YIELD",
                       "util_practice_desc": "GRAIN", "reference_period_desc": "YEAR",
                       "year": "2024", "state_name": "IOWA"},
                      {"Value": "24", "unit_desc": "TONS / ACRE", "short_desc": "CORN, SILAGE - YIELD",
                       "util_practice_desc": "SILAGE", "reference_period_desc": "YEAR",
                       "year": "2024", "state_name": "IOWA"}]),
            response([{"Value": "4.25", "unit_desc": "$ / BU", "short_desc": "CORN, GRAIN - PRICE RECEIVED",
                       "util_practice_desc": "GRAIN", "reference_period_desc": "MARKETING YEAR",
                       "year": "2024", "state_name": "IOWA"}]),
        ]
        result = fetch_us_crop_statistics("IA", 2024, ["grain_maize"], api_key="secret")
        baseline = result["selected_baselines"][0]
        self.assertAlmostEqual(baseline["yield_t_ha"], 13.244, places=4)
        self.assertAlmostEqual(baseline["price_per_tonne"], 167.32, places=2)
        self.assertEqual(baseline["missing_for_planner"], ["variable_cost_per_ha"])

    def test_api_exposes_auth_state_without_a_secret(self):
        with patch.dict("os.environ", {}, clear=True), TestClient(app) as client:
            result = client.post("/v1/us-crop-statistics", json={
                "state_alpha": "IA", "year": 2024, "crop_ids": ["grain_maize"]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "auth_required")

    @patch("grainstorm.sources.nass.requests.get")
    def test_rice_hundredweight_records_become_metric_baseline(self, get):
        get.side_effect = [
            response([{"Value": "75", "unit_desc": "CWT / ACRE", "short_desc": "RICE - YIELD",
                       "reference_period_desc": "YEAR", "year": "2024", "state_name": "ARKANSAS"}]),
            response([{"Value": "15", "unit_desc": "$ / CWT", "short_desc": "RICE - PRICE RECEIVED",
                       "reference_period_desc": "MARKETING YEAR", "year": "2024", "state_name": "ARKANSAS"}]),
        ]
        result = fetch_us_crop_statistics("AR", 2024, ["rice"], api_key="secret")
        baseline = result["selected_baselines"][0]
        self.assertAlmostEqual(baseline["yield_t_ha"], 8.4064, places=4)
        self.assertAlmostEqual(baseline["price_per_tonne"], 330.69, places=2)
        self.assertEqual(baseline["unit_conversion"]["source_unit"], "hundredweight")


if __name__ == "__main__":
    unittest.main()
