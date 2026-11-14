"""Optional frontend inputs activate advanced planner calculations without defaults."""
import unittest

from grainstorm.planner import _economics, simulate_scenarios


class OptionalDecisionInputTests(unittest.TestCase):
    def test_itemized_economics_reports_field_totals_roi_and_break_even(self):
        result = _economics({"economics": {
            "expected_yield_t_ha": 2, "marketable_yield_fraction": 0.9,
            "price_per_tonne": 100, "additional_income_per_ha": 10,
            "currency": "USD", "source": "Farm budget",
            "cost_completeness_confirmed": True,
            "cost_items": [
                {"name": "Seed", "category": "seed", "amount_per_ha": 50, "source": "Invoice"},
                {"name": "Harvest", "category": "harvest", "amount_for_field": 100, "source": "Quote"},
            ],
        }}, "maize", 2)
        self.assertEqual(result["total_crop_cost_for_field"], 200)
        self.assertEqual(result["gross_revenue_for_field"], 360)
        self.assertEqual(result["estimated_margin_for_field"], 180)
        self.assertEqual(result["return_on_cost_percent"], 90)
        self.assertEqual(result["break_even_price_per_tonne"], 55.56)

    def test_soil_agronomy_variety_irrigation_and_cost_are_integrated(self):
        config = {
            "field": {
                "name": "Test field", "area_ha": 1,
                "soil_water_capacity_mm": 100, "soil_water_capacity_depth_m": 1,
                "initial_soil_water_mm": 0,
                "soil_test": {
                    "sample_date": "2024-01-01", "depth_cm": 30, "source": "Lab report",
                    "mineral_n_kg_ha": 100, "available_p_kg_ha": 100,
                    "exchangeable_k_kg_ha": 100, "organic_matter_percent": 2, "ph": 7,
                },
                "management": {"source": "Farmer record", "previous_crop": "wheat"},
                "irrigation": {
                    "enabled": True, "trigger_fraction": 0.5,
                    "application_efficiency": 0.5, "max_withdrawal_mm": 20,
                    "variable_cost_per_m3": 0.1, "currency": "USD", "source": "Farmer record",
                },
            },
            "crop_catalog": {"maize": {
                "variety": {"name": "Example", "maturity_days": 2, "source": "Seed label"},
                "water_need_mm": 20, "root_depth_m": 1,
                "planting_windows": [{"label": "Local", "start_month_day": "01-01", "end_month_day": "01-10"}],
                "agronomy": {
                    "nutrient_removal_kg_per_tonne": {"n": 10, "p": 2, "k": 3},
                    "fertilizer_applied_kg_ha": {"n": 10},
                    "fertilizer_recovery_fraction": {"n": 0.5},
                    "residue_release_kg_ha": {"n": 2}, "other_losses_kg_ha": {"n": 1},
                    "biological_fixation_n_kg_ha": 5, "source": "Reviewed coefficients",
                },
                "economics": {"expected_yield_t_ha": 2, "price_per_tonne": 1000,
                              "variable_cost_per_ha": 100, "currency": "USD", "source": "Market record"},
            }},
            "weather": [{"date": "2024-01-01", "rain_mm": 0, "et0_mm": 1},
                        {"date": "2024-01-02", "rain_mm": 0, "et0_mm": 1}],
            "scenarios": [{"name": "Maize", "start_date": "2024-01-01",
                           "planning_end_date": "2024-01-10", "crops": ["maize"]}],
        }
        report = simulate_scenarios(config)
        scenario = report["scenarios"][0]
        crop = scenario["sequence"][0]
        self.assertEqual(crop["duration_days"], 2)
        self.assertEqual(scenario["total_irrigation_mm"], 20)
        self.assertEqual(scenario["total_effective_irrigation_mm"], 10)
        self.assertEqual(scenario["irrigation_cost_for_field"], 20)
        self.assertEqual(scenario["estimated_total_margin_for_field"], 1880)
        self.assertEqual(crop["nutrient_budget"]["n"]["crop_total_removal_kg_ha"], 20)
        self.assertEqual(crop["net_soil_n_change_kg_ha"], -9)
        self.assertEqual(report["input_assessment"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
