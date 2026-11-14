"""Integrated tests for the expanded rotation decision-support outputs."""
import unittest

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.planner import simulate_scenarios


def advanced_crop(root_depth, yield_t_ha, n_fixation=0):
    return {
        "duration_days": 1,
        "water_need_mm": 10,
        "root_depth_m": root_depth,
        "planting_windows": [{"label": "Reviewed test window",
                              "start_month_day": "01-01", "end_month_day": "01-31"}],
        "nutrient_budget": {
            "n": {"biological_fixation": n_fixation, "fertilizer": 5,
                  "residue_release": 2, "crop_uptake_from_soil": 8, "other_losses": 1,
                  "source": "Reviewed test nutrient budget"},
            "p": {"fertilizer": 3, "crop_uptake_from_soil": 1,
                  "source": "Reviewed test nutrient budget"},
            "k": {"fertilizer": 4, "crop_uptake_from_soil": 2,
                  "source": "Reviewed test nutrient budget"},
        },
        "soil_effects": {
            "organic_matter_change_percentage_points": 0.1,
            "ph_change": -0.1,
            "source": "Reviewed test soil-effect assumption",
        },
        "economics": {
            "expected_yield_t_ha": yield_t_ha,
            "price_per_tonne": 100,
            "variable_cost_per_ha": 50,
            "currency": "USD",
            "source": "Reviewed test enterprise budget",
        },
    }


class DecisionSupportTests(unittest.TestCase):
    def test_api_preserves_ranking_configuration(self):
        with TestClient(app) as client:
            response = client.post("/v1/plans", json={
                "field": {"area_ha": 1, "soil_water_capacity_mm": 10,
                          "initial_soil_water_mm": 10, "initial_mineral_n_kg_ha": 10},
                "crop_catalog": {"demo": {"duration_days": 1, "water_need_mm": 0,
                    "net_soil_n_change_kg_ha": 0, "planting_windows": [{
                        "label": "Test", "start_month_day": "01-01", "end_month_day": "01-31"}]}},
                "weather": [{"date": "2024-01-01", "rain_mm": 0}],
                "scenarios": [{"name": "Complete", "start_date": "2024-01-01",
                               "planning_end_date": "2024-01-31", "crops": ["demo"]}],
                "ranking": {"enabled": True, "weights": {"irrigation": 1}},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["report"]["comparison"]["ranking"]["status"], "complete")

    def test_integrated_budgets_fallow_root_depth_economics_and_ranking(self):
        report = simulate_scenarios({
            "field": {
                "area_ha": 2,
                "soil_water_capacity_mm": 100,
                "soil_water_capacity_depth_m": 1,
                "initial_soil_water_mm": 50,
                "fallow_kc": 0.5,
                "initial_mineral_n_kg_ha": 20,
                "initial_available_p_kg_ha": 5,
                "initial_exchangeable_k_kg_ha": 5,
                "initial_organic_matter_percent": 2,
                "initial_soil_ph": 7,
            },
            "crop_catalog": {
                "soy": advanced_crop(0.5, 2, n_fixation=10),
                "maize": advanced_crop(1.0, 3),
            },
            "weather": [
                {"date": "2024-01-01", "rain_mm": 0, "et0_mm": 2},
                {"date": "2024-01-02", "rain_mm": 10, "et0_mm": 2},
                {"date": "2024-01-03", "rain_mm": 0, "et0_mm": 2},
            ],
            "rotation_effect_catalog": {
                "soy->maize": {"pest_disease_break_score": 2, "source": "Reviewed test rotation study"},
                "maize->soy": {"pest_disease_break_score": -1, "source": "Reviewed test rotation study"},
            },
            "scenarios": [
                {"name": "Soy then maize", "start_date": "2024-01-01",
                 "planning_end_date": "2024-01-31", "crops": ["soy", "maize"],
                 "gaps_after_crops_days": [1]},
                {"name": "Maize then soy", "start_date": "2024-01-01",
                 "planning_end_date": "2024-01-31", "crops": ["maize", "soy"],
                 "gaps_after_crops_days": [1]},
            ],
            "ranking": {"enabled": True, "weights": {"pest_disease": 1}},
        })
        first = report["scenarios"][0]
        self.assertEqual(first["sequence"][0]["effective_root_zone_capacity_mm"], 50)
        self.assertEqual(first["fallow_periods"][0]["water_balance_status"], "modeled")
        self.assertEqual(first["fallow_periods"][0]["rain_mm"], 10)
        self.assertEqual(first["fallow_periods"][0]["evapotranspiration_mm"], 1)
        self.assertEqual(first["sequence"][0]["nutrient_budget"]["n"]["net_change_kg_ha"], -2)
        self.assertEqual(first["sequence"][0]["nutrient_budget"]["n"]["biological_fixation"], 10)
        self.assertEqual(first["estimated_final_mineral_n_kg_ha"], 16)
        self.assertEqual(first["estimated_final_available_p_kg_ha"], 9)
        self.assertEqual(first["estimated_final_exchangeable_k_kg_ha"], 9)
        self.assertEqual(first["estimated_final_organic_matter_percent"], 2.2)
        self.assertEqual(first["estimated_final_soil_ph"], 6.8)
        self.assertEqual(first["estimated_total_margin_for_field"], 800)
        self.assertEqual(first["pest_disease_rotation_score"], 2)
        ranking = report["comparison"]["ranking"]
        self.assertEqual(ranking["status"], "complete")
        self.assertEqual(ranking["ranked_scenarios"][0]["name"], "Soy then maize")
        self.assertIn("not an agronomic recommendation", ranking["warning"])

    def test_ranking_excludes_unvalidated_legacy_scenarios(self):
        report = simulate_scenarios({
            "field": {"area_ha": 1, "soil_water_capacity_mm": 10,
                      "initial_soil_water_mm": 10, "initial_mineral_n_kg_ha": 10},
            "crop_catalog": {"demo": {"duration_days": 1, "water_need_mm": 0,
                                        "net_soil_n_change_kg_ha": 0}},
            "weather": [{"date": "2024-01-01", "rain_mm": 0}],
            "scenarios": [{"name": "Incomplete", "start_date": "2024-01-01", "crops": ["demo"]}],
            "ranking": {"enabled": True, "weights": {"irrigation": 1}},
        })
        ranking = report["comparison"]["ranking"]
        self.assertEqual(ranking["status"], "insufficient_inputs")
        self.assertIn("calendar_feasibility", ranking["excluded"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
