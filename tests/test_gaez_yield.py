"""Offline tests for GAEZ historical yield baselines."""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.sources.gaez_yield import _raster, fetch_location_yield_baselines


def response(payload):
    value = Mock()
    value.raise_for_status.return_value = None
    value.json.return_value = payload
    return value


class GaezYieldTests(unittest.TestCase):
    def setUp(self):
        _raster.cache_clear()
        self.addCleanup(_raster.cache_clear)

    @patch("grainstorm.sources.gaez_yield.requests.get")
    def test_historical_yield_is_normalized_with_provenance(self, get):
        get.side_effect = [
            response({"features": [{"attributes": {"OBJECTID": 768, "Name": "mze_2010_yld",
                "variable": "Yield", "year": "2010", "crop": "Maize",
                "water_supply": "Rainfed", "units": "t/ha", "download_url": " https://example.invalid"}}]}),
            response({"value": "1.74317"}),
        ]
        result = fetch_location_yield_baselines(30.34, 76.39, ["grain_maize"])
        self.assertEqual(result["crops"][0]["historical_yield_t_ha"], 1.74317)
        self.assertEqual(result["crops"][0]["economics_yield_input"]["expected_yield_t_ha"], 1.74317)
        self.assertEqual(result["crops"][0]["raster"]["download_url"], "https://example.invalid")

    def test_api_exposes_yield_baseline(self):
        payload = {"requested_point": {}, "dataset": {}, "crops": [], "limitations": []}
        with patch("grainstorm.api.fetch_location_yield_baselines", return_value=payload), TestClient(app) as client:
            response_value = client.post("/v1/crop-yield-baseline", json={
                "latitude": 30.34, "longitude": 76.39, "crop_ids": ["grain_maize"]})
        self.assertEqual(response_value.status_code, 200)
        self.assertEqual(response_value.json(), payload)

    def test_chickpea_missing_raster_is_explicit(self):
        result = fetch_location_yield_baselines(30.34, 76.39, ["chickpea"])
        self.assertEqual(result["crops"][0]["status"], "unavailable")
        self.assertIsNone(result["crops"][0]["historical_yield_t_ha"])

    @patch("grainstorm.sources.gaez_yield.requests.get")
    def test_wetland_rice_uses_verified_gaez_raster(self, get):
        get.side_effect = [
            response({"features": [{"attributes": {"OBJECTID": 786, "Name": "rcw_2010_yld",
                "variable": "Yield", "year": "2010", "crop": "Wetland rice",
                "water_supply": "Irrigated", "units": "t/ha", "download_url": "rice-url"}}]}),
            response({"value": "4.25"}),
        ]
        result = fetch_location_yield_baselines(30.34, 76.39, ["rice"])
        self.assertEqual(result["crops"][0]["historical_yield_t_ha"], 4.25)
        self.assertIn("Wetland rice", get.call_args_list[0].kwargs["params"]["where"])
        self.assertIn("Irrigated", get.call_args_list[0].kwargs["params"]["where"])


if __name__ == "__main__":
    unittest.main()
