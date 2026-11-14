"""Tests for source-backed crop profiles and planner hand-off."""
from datetime import date, timedelta
import unittest

from fastapi.testclient import TestClient

from grainstorm.api import app
from grainstorm.crops import PROFILES, SOURCES, get_profile, planner_template
from grainstorm.planner import simulate_scenarios


class CropProfileTests(unittest.TestCase):
    def test_profiles_are_consistent_and_have_no_fake_nitrogen_default(self):
        self.assertEqual(set(PROFILES), {
            "grain_maize", "grain_soybean", "wheat", "sorghum", "chickpea", "sunflower",
            "rice",
        })
        for profile in PROFILES.values():
            self.assertIsNone(profile["nitrogen"]["default_net_soil_n_change_kg_ha"])
            self.assertTrue(set(profile["source_ids"]).issubset(SOURCES))
            self.assertEqual(len(profile["water"]["stage_kc"]), 4)
            for calendar in profile["growing_period"]["reference_calendars"]:
                self.assertEqual(sum(calendar["stage_days"]), calendar["duration_days"])
                self.assertEqual(len(calendar["stage_days"]), 4)

    def test_api_lists_and_returns_profiles(self):
        with TestClient(app) as client:
            listing = client.get("/v1/crops")
            self.assertEqual(listing.status_code, 200)
            body = listing.json()
            self.assertEqual(body["profile_version"], "fao-reference-v1")
            self.assertEqual({crop["id"] for crop in body["crops"]}, {
                "grain_maize", "grain_soybean", "wheat", "sorghum", "chickpea", "sunflower",
                "rice",
            })

            maize = client.get("/v1/crops/grain_maize")
            self.assertEqual(maize.status_code, 200)
            profile = maize.json()
            self.assertEqual(profile["gaez"]["crop_code"], "mze")
            self.assertEqual(profile["water"]["stage_kc"], [0.4, 0.8, 1.15, 0.7])
            self.assertEqual(profile["growing_period"]["reference_calendars"][0]["stage_days"],
                             [20, 35, 40, 30])
            self.assertIn("fao_crop_water_needs", profile["sources"])
            self.assertEqual(client.get("/v1/crops/unknown").status_code, 404)

            chickpea = client.get("/v1/crops/chickpea").json()
            self.assertEqual(chickpea["gaez"]["crop_code"], "chk")
            self.assertIsNotNone(chickpea["nitrogen"]["legume_warning"])

            rice = client.get("/v1/crops/rice").json()
            self.assertEqual(rice["gaez"]["crop_code"], "rcw")
            self.assertEqual(rice["water"]["stage_kc"], [1.1, 1.1, 1.2, 1.0])
            self.assertTrue(any("standing water" in item for item in rice["water"]["limitations"]))

    def test_template_requires_a_sourced_nitrogen_assumption(self):
        with TestClient(app) as client:
            incomplete = client.post("/v1/crops/grain_soybean/planner-template", json={
                "calendar_id": "fao_reference_135"
            })
            self.assertEqual(incomplete.status_code, 200)
            body = incomplete.json()
            self.assertFalse(body["ready_for_planner"])
            self.assertIsNone(body["planner_crop"]["net_soil_n_change_kg_ha"])
            self.assertEqual(body["missing_inputs"], ["net_soil_n_change_kg_ha", "nitrogen_source"])

            unsourced = client.post("/v1/crops/grain_soybean/planner-template", json={
                "calendar_id": "fao_reference_135", "net_soil_n_change_kg_ha": -25
            })
            self.assertEqual(unsourced.status_code, 422)

            ready = client.post("/v1/crops/grain_soybean/planner-template", json={
                "calendar_id": "fao_reference_135",
                "net_soil_n_change_kg_ha": -25,
                "nitrogen_source": "Reviewed local nutrient budget",
                "nitrogen_note": "Dry seed harvested; residue retained"
            })
            self.assertEqual(ready.status_code, 200, ready.text)
            crop = ready.json()["planner_crop"]
            self.assertTrue(ready.json()["ready_for_planner"])
            self.assertEqual(crop["profile_id"], "grain_soybean")
            self.assertEqual(crop["calendar_id"], "fao_reference_135")
            self.assertEqual(crop["nitrogen_assumption_source"], "Reviewed local nutrient budget")

            bad_calendar = client.post("/v1/crops/grain_soybean/planner-template", json={
                "calendar_id": "not_a_calendar"
            })
            self.assertEqual(bad_calendar.status_code, 422)

    def test_generated_template_runs_and_preserves_provenance(self):
        crop = planner_template(
            "grain_maize", "fao_reference_125", nitrogen_value=-50,
            nitrogen_source="Reviewed demonstration assumption", nitrogen_note="Test fixture only",
        )["planner_crop"]
        start = date(2024, 1, 1)
        weather = [{
            "date": (start + timedelta(days=index)).isoformat(), "rain_mm": 0, "et0_mm": 1
        } for index in range(125)]
        report = simulate_scenarios({
            "field": {"area_ha": 1, "soil_water_capacity_mm": 200,
                      "initial_soil_water_mm": 200, "initial_mineral_n_kg_ha": 100},
            "crop_catalog": {"maize": crop},
            "weather": weather,
            "scenarios": [{"name": "Reference profile test", "start_date": "2024-01-01",
                           "crops": ["maize"]}],
        })
        result = report["scenarios"][0]["sequence"][0]
        self.assertEqual(result["crop_water_need_mm"], 103.0)
        self.assertEqual(result["input_provenance"]["profile_id"], "grain_maize")
        self.assertEqual(result["input_provenance"]["calendar_id"], "fao_reference_125")
        self.assertEqual(result["input_provenance"]["nitrogen_assumption_source"],
                         "Reviewed demonstration assumption")

    def test_get_profile_returns_a_copy(self):
        profile = get_profile("grain_maize")
        profile["display_name"] = "changed"
        self.assertEqual(get_profile("grain_maize")["display_name"], "Grain maize")


if __name__ == "__main__":
    unittest.main()
