"""Tests for the single farmer-facing rotation endpoint orchestration."""
import unittest
from datetime import date
from unittest.mock import patch

from grainstorm.geometry import polygon_summary
from grainstorm.rotation_advice import build_rotation_advice


POLYGON = {"type": "Polygon", "coordinates": [[
    [-93.6500, 42.0300], [-93.6490, 42.0300], [-93.6490, 42.0310],
    [-93.6500, 42.0310], [-93.6500, 42.0300],
]]}


def bundle():
    return {
        "suitability": {"crops": [{"crop_id": "grain_maize"}]},
        "calendar": {"crops": [{"crop_id": "grain_maize", "cycle_length_days": 4,
                                  "reference_root_depth_m": 0.9}]},
        "yield_baseline": {"crops": [{"crop_id": "grain_maize", "historical_yield_t_ha": 2}]},
        "soil": {"status": "complete"},
    }


class FakeContext:
    requested_sources = None

    def query(self, *_args, **_kwargs):
        self.requested_sources = _args[-1] if _args else _kwargs.get("sources")
        days = [f"2024-01-0{day}" for day in range(1, 5)]
        return {"sources": {
            "imerg": {"status": "complete", "records": [
                {"date": day, "gpm_precipitation_mm_day": 0,
                 "gpm_valid_half_hourly_count": 48} for day in days], "jobs": []},
            "era5": {"status": "complete", "records": [
                {"date": day, "et0_mm": 2} for day in days], "jobs": []},
            "smap": {"status": "complete", "records": [], "jobs": []},
        }}


class RotationAdviceTests(unittest.TestCase):
    def test_polygon_summary_returns_centroid_and_area(self):
        result = polygon_summary(POLYGON["coordinates"])
        self.assertAlmostEqual(result["centroid"]["latitude"], 42.0305, places=4)
        self.assertGreater(result["area_ha"], 0.5)

    @patch("grainstorm.rotation_advice._source_bundle", return_value=bundle())
    def test_one_call_returns_complete_calculation_when_inputs_exist(self, _source):
        request = {
            "field_polygon": POLYGON, "field_name": "North field",
            "crop_sequence": ["grain_maize"], "preferred_start_date": date(2024, 1, 1),
            "planning_end_date": date(2024, 1, 4), "schedule_mode": "next_planting_window",
            "compare_all_orders": True, "gaps_after_crops_days": None,
            "field_inputs": {"soil_water_capacity_mm": 100, "soil_water_capacity_depth_m": 1,
                             "initial_soil_water_mm": 50},
            "soil_test": {"sample_date": "2023-12-01", "depth_cm": 30, "source": "Lab",
                          "mineral_n_kg_ha": 100, "available_p_kg_ha": 50,
                          "exchangeable_k_kg_ha": 50, "organic_matter_percent": 2, "ph": 7},
            "management": None, "irrigation": None,
            "crop_inputs": {"grain_maize": {
                "planting_windows": [{"label": "Local", "start_month_day": "01-01", "end_month_day": "01-10"}],
                "agronomy": {"nutrient_removal_kg_per_tonne": {"n": 10, "p": 2, "k": 3},
                              "source": "Reviewed"},
                "economics": {"expected_yield_t_ha": 2, "price_per_tonne": 100,
                              "variable_cost_per_ha": 50, "currency": "USD", "source": "Market"},
            }},
            "rotation_effect_catalog": {}, "ranking": None,
        }
        status, response = build_rotation_advice(request, FakeContext())
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "complete")
        self.assertIsNotNone(response["calculation"])
        self.assertEqual(response["advice"]["scenarios"][0]["steps"][0]["crop_id"], "grain_maize")
        self.assertNotIn("records", response["environmental_context"]["sources"]["imerg"])
        self.assertEqual(response["environmental_context"]["sources"]["imerg"]["record_count"], 4)


if __name__ == "__main__":
    unittest.main()
