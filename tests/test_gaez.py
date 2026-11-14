"""Offline tests for the FAO GAEZ point-suitability adapter."""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.sources.gaez import (
    GaezError,
    _resolve_raster,
    fetch_location_suitability,
    suitability_class,
)


def response(payload):
    result = Mock()
    result.raise_for_status.return_value = None
    result.json.return_value = payload
    return result


class GaezTests(unittest.TestCase):
    def setUp(self):
        _resolve_raster.cache_clear()
        self.addCleanup(_resolve_raster.cache_clear)

    def test_documented_class_boundaries(self):
        expected = {
            10000: "VS", 8000: "VS", 7999: "S", 6000: "S",
            5999: "MS", 4000: "MS", 3999: "mS", 2000: "mS",
            1999: "vmS", 1: "vmS", 0: "NS",
        }
        for value, code in expected.items():
            with self.subTest(value=value):
                self.assertEqual(suitability_class(value)["code"], code)
        for invalid in (-1, 10001, True):
            with self.assertRaises(ValueError):
                suitability_class(invalid)

    @patch("grainstorm.sources.gaez.requests.get")
    def test_point_lookup_locks_exact_raster_and_normalizes_index(self, get):
        catalog = response({"features": [{"attributes": {
            "objectid": 257854,
            "name": "sxHr_mze",
            "variable": "Suitability index range (0-10000); all land in grid cell",
            "year": "1981-2010",
            "model": "CRUTS32",
            "rcp": "Historical",
            "crop": "Maize",
            "water_supply": "Rainfed",
            "input_level": "High",
            "c02_fertilization": "With CO2 Fertilization",
            "units": "Index",
            "download_url": "https://example.invalid/sxHr_mze.tif",
            "file_id": "000582405",
        }}]})
        identify = response({
            "value": "6285",
            "location": {"x": 76.39, "y": 30.34, "spatialReference": {"wkid": 4326}},
        })
        get.side_effect = [catalog, identify]

        result = fetch_location_suitability(30.34, 76.39, ["grain_maize"])
        crop = result["crops"][0]
        self.assertEqual(crop["suitability_index_percent"], 62.85)
        self.assertEqual(crop["suitability_class"]["code"], "S")
        self.assertEqual(crop["raster"]["file_id"], "000582405")
        self.assertEqual(result["dataset"]["baseline"]["time_period"], "1981-2010")
        self.assertIn("esriMosaicLockRaster", get.call_args_list[1].kwargs["params"]["mosaicRule"])
        self.assertIn("257854", get.call_args_list[1].kwargs["params"]["mosaicRule"])

    def test_validation_rejects_unknown_or_duplicate_crops(self):
        for crop_ids in ([], ["grain_maize", "grain_maize"], ["wheat"]):
            with self.assertRaises(ValueError):
                fetch_location_suitability(30.34, 76.39, crop_ids)
        with self.assertRaises(ValueError):
            fetch_location_suitability(91, 76.39, ["grain_maize"])

    @patch("grainstorm.sources.gaez.requests.get")
    def test_missing_numeric_value_is_not_turned_into_zero(self, get):
        get.side_effect = [
            response({"features": [{"attributes": {
                "objectid": 1, "crop": "Maize", "name": "sxHr_mze",
            }}]}),
            response({"value": "NoData", "location": {"x": 0, "y": 0}}),
        ]
        with self.assertRaisesRegex(GaezError, "no numeric suitability"):
            fetch_location_suitability(0, 0, ["grain_maize"])

    def test_api_contract_and_upstream_error(self):
        payload = {
            "requested_point": {"latitude": 30.34, "longitude": 76.39},
            "dataset": {"product": "GAEZ v4 Module V suitability index"},
            "crops": [],
            "interpretation": "screening only",
        }
        with patch("grainstorm.api.fetch_location_suitability", return_value=payload), TestClient(app) as client:
            result = client.post("/v1/crop-suitability", json={
                "latitude": 30.34, "longitude": 76.39,
                "crop_ids": ["grain_maize", "grain_soybean"],
            })
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), payload)
            duplicate = client.post("/v1/crop-suitability", json={
                "latitude": 30.34, "longitude": 76.39,
                "crop_ids": ["grain_maize", "grain_maize"],
            })
            self.assertEqual(duplicate.status_code, 422)

        with patch("grainstorm.api.fetch_location_suitability", side_effect=GaezError("GAEZ unavailable")), \
                TestClient(app) as client:
            result = client.post("/v1/crop-suitability", json={
                "latitude": 30.34, "longitude": 76.39,
            })
            self.assertEqual(result.status_code, 502)
            self.assertEqual(result.json()["detail"], "GAEZ unavailable")


if __name__ == "__main__":
    unittest.main()
