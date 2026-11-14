"""Offline tests for USDA NRCS SSURGO point context."""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.sources.ssurgo import fetch_us_soil_context


def response(table):
    value = Mock()
    value.raise_for_status.return_value = None
    value.json.return_value = {"Table": table}
    return value


class SsurgoTests(unittest.TestCase):
    @patch("grainstorm.sources.ssurgo.requests.post")
    def test_returns_weighted_topsoil_and_preserves_missing_nutrients(self, post):
        columns = ["mukey", "musym", "muname", "cokey", "compname", "comppct_r",
                   "drainagecl", "hydgrp", "chkey", "hzdept_r", "hzdepb_r",
                   "sandtotal_r", "silttotal_r", "claytotal_r", "om_r",
                   "ph1to1h2o_r", "awc_r", "texture_class"]
        post.return_value = response([columns,
            ["1", "A", "Example", "2", "Main", "80", "Well drained", "B", "3", "0", "20", "30", "40", "30", "4", "6", ".2", "Loam"],
            ["1", "A", "Example", "2", "Main", "80", "Well drained", "B", "4", "20", "40", "40", "30", "30", "2", "7", ".1", "Clay loam"]])
        result = fetch_us_soil_context(42.03, -93.65)
        topsoil = result["soil"]["topsoil_0_30cm"]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(topsoil["organic_matter_percent"], 3.333)
        self.assertEqual(topsoil["available_water_capacity_mm"], 50.0)
        self.assertIn("current_nitrogen", result["unavailable_properties"])

    @patch("grainstorm.sources.ssurgo.requests.post")
    def test_outside_coverage_is_explicit(self, post):
        post.return_value = response([["mukey"]])
        result = fetch_us_soil_context(30.34, 76.39)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["soil"])

    @patch("grainstorm.sources.ssurgo.requests.post")
    def test_null_or_empty_outside_coverage_tables_are_normal(self, post):
        for table in (None, []):
            post.return_value = response(table)
            result = fetch_us_soil_context(30.34, 76.39)
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["soil"])

    @patch("grainstorm.sources.ssurgo.requests.post")
    def test_empty_object_outside_coverage_is_normal(self, post):
        value = Mock()
        value.raise_for_status.return_value = None
        value.json.return_value = {}
        post.return_value = value
        result = fetch_us_soil_context(30.34, 76.39)
        self.assertEqual(result["status"], "unavailable")

    def test_api_exposes_soil_context(self):
        payload = {"status": "unavailable", "soil": None}
        with patch("grainstorm.api.fetch_us_soil_context", return_value=payload), TestClient(app) as client:
            result = client.post("/v1/soil-context", json={
                "latitude": 30.34, "longitude": 76.39})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), payload)


if __name__ == "__main__":
    unittest.main()
