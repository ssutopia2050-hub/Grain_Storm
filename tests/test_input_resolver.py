"""Tests for transparent automatic planning baselines."""
import unittest
from datetime import date

from grainstorm.input_resolver import resolve_rotation_inputs


class InputResolverTests(unittest.TestCase):
    def test_ssurgo_gaez_and_faostat_values_fill_without_overwriting(self):
        data = {
            "crop_sequence": ["grain_maize", "wheat"],
            "field_inputs": {"initial_soil_water_mm": 25},
            "crop_inputs": {"wheat": {"planting_windows": [{
                "label": "Local", "start_month_day": "10-01", "end_month_day": "11-01",
            }]}},
        }
        bundle = {
            "soil": {"status": "complete", "dataset": {"source_page": "soil-url"}, "soil": {
                "topsoil_0_30cm": {"available_water_capacity_mm": 45, "covered_depth_cm": 30,
                                     "organic_matter_percent": 2.1, "ph_h2o": 6.7},
            }},
            "calendar": {"dataset": {"service": "calendar-url"}, "crops": [
                {"crop_id": "grain_maize", "planting_date_for_target_year": "2027-04-10"},
                {"crop_id": "wheat", "planting_date_for_target_year": "2027-10-15"},
            ]},
            "yield_baseline": {"crops": [
                {"crop_id": "grain_maize", "historical_yield_t_ha": 4.2},
                {"crop_id": "wheat", "historical_yield_t_ha": 3.1},
            ]},
        }
        resolved, metadata = resolve_rotation_inputs(
            data, bundle, ["grain_maize", "wheat"], date(2027, 4, 1)
        )
        self.assertEqual(resolved["field_inputs"]["initial_soil_water_mm"], 25)
        self.assertEqual(resolved["field_inputs"]["soil_water_capacity_mm"], 150)
        self.assertEqual(resolved["gaps_after_crops_days"], [14])
        self.assertEqual(resolved["crop_inputs"]["grain_maize"]["agronomy"]["expected_yield_t_ha"], 4.2)
        self.assertEqual(resolved["crop_inputs"]["wheat"]["planting_windows"][0]["label"], "Local")
        self.assertEqual(
            resolved["rotation_effect_catalog"]["grain_maize->wheat"]["pest_disease_break_score"], -1
        )
        self.assertGreater(metadata["generated_count"], 0)


if __name__ == "__main__":
    unittest.main()
