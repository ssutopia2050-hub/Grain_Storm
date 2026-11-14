"""Offline tests for location-aware GAEZ crop calendars."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.sources.gaez_calendar import fetch_location_crop_calendars


def rasters(crop):
    return {
        "start_day": {"objectid": 1, "crop": crop, "name": "start", "variable": "start"},
        "cycle_length": {"objectid": 2, "crop": crop, "name": "length", "variable": "length"},
    }


class GaezCalendarTests(unittest.TestCase):
    @patch("grainstorm.sources.gaez_calendar._identify")
    @patch("grainstorm.sources.gaez_calendar._resolve_calendar_rasters")
    def test_location_calendar_and_root_profile(self, resolve, identify):
        resolve.side_effect = lambda crop_id: rasters(crop_id)
        identify.side_effect = lambda raster_id, _lat, _lon: 177 if raster_id == 1 else 150
        result = fetch_location_crop_calendars(30.34, 76.39, ["grain_maize"], 2024)
        maize = result["crops"][0]
        self.assertEqual(maize["planting_date_for_target_year"], "2024-06-25")
        self.assertEqual(maize["projected_harvest_date"], "2024-11-21")
        self.assertEqual(maize["planner_overrides"], {"duration_days": 150, "root_depth_m": 0.9})
        self.assertIn("not a locally validated planting window", result["limitations"][0])

    def test_api_exposes_calendar_contract(self):
        payload = {"requested_point": {}, "target_year": 2024, "dataset": {}, "crops": [], "limitations": []}
        with patch("grainstorm.api.fetch_location_crop_calendars", return_value=payload), TestClient(app) as client:
            response = client.post("/v1/crop-calendar", json={
                "latitude": 30.34, "longitude": 76.39, "target_year": 2024,
                "crop_ids": ["grain_maize", "grain_soybean"],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)


if __name__ == "__main__":
    unittest.main()
