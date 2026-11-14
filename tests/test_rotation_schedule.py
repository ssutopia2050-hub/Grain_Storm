"""Tests for rotation gaps, planting windows and calendar feasibility."""
from datetime import date
import unittest

from grainstorm.planner import _planting_windows, _schedule_planting, simulate_scenarios


def crop(window_start=None, window_end=None):
    result = {
        "duration_days": 2,
        "water_need_mm": 0,
        "net_soil_n_change_kg_ha": 0,
    }
    if window_start:
        result["planting_windows"] = [{
            "label": "Local reviewed window",
            "start_month_day": window_start,
            "end_month_day": window_end,
        }]
    return result


def config(schedule_mode="next_planting_window", planning_end_date="2024-02-28"):
    weather_dates = [
        "2024-01-01", "2024-01-02", "2024-01-06", "2024-01-07",
        "2024-02-01", "2024-02-02",
    ]
    return {
        "field": {
            "area_ha": 1,
            "soil_water_capacity_mm": 100,
            "initial_soil_water_mm": 50,
            "initial_mineral_n_kg_ha": 50,
        },
        "crop_catalog": {
            "first": crop("01-01", "01-10"),
            "second": crop("02-01", "02-10"),
        },
        "weather": [{"date": day, "rain_mm": 0} for day in weather_dates],
        "scenarios": [{
            "name": "Two-crop rotation",
            "start_date": "2024-01-01",
            "planning_end_date": planning_end_date,
            "schedule_mode": schedule_mode,
            "crops": ["first", "second"],
            "gaps_after_crops_days": [3],
        }],
    }


class RotationScheduleTests(unittest.TestCase):
    def test_next_window_waits_and_reports_a_feasible_horizon(self):
        scenario = simulate_scenarios(config())["scenarios"][0]
        second = scenario["sequence"][1]
        self.assertEqual(second["earliest_planting_date"], "2024-01-06")
        self.assertEqual(second["planting_date"], "2024-02-01")
        self.assertEqual(second["planned_harvest_date"], "2024-02-02")
        self.assertEqual(second["gap_before_days"], 3)
        self.assertEqual(second["calendar_wait_before_days"], 26)
        self.assertEqual(second["planting_window_status"], "shifted_to_window")
        self.assertEqual(second["matched_planting_window"]["end_date"], "2024-02-10")
        self.assertEqual(scenario["calendar_status"], "feasible")
        self.assertTrue(scenario["calendar_feasible"])
        self.assertEqual(scenario["rotation_span_days"], 33)
        self.assertEqual(scenario["total_configured_gap_days"], 3)
        self.assertEqual(scenario["total_calendar_wait_days"], 26)

    def test_fixed_gap_flags_out_of_window_without_moving_planting(self):
        scenario = simulate_scenarios(config(schedule_mode="fixed_gap"))["scenarios"][0]
        second = scenario["sequence"][1]
        self.assertEqual(second["planting_date"], "2024-01-06")
        self.assertEqual(second["planting_window_status"], "outside_window")
        self.assertEqual(scenario["calendar_status"], "infeasible")
        self.assertFalse(scenario["calendar_feasible"])
        self.assertEqual(scenario["schedule_issues"][0]["code"], "outside_planting_window")

    def test_horizon_overrun_is_explicit(self):
        scenario = simulate_scenarios(config(planning_end_date="2024-01-31"))["scenarios"][0]
        issue = next(item for item in scenario["schedule_issues"]
                     if item["code"] == "planning_horizon_exceeded")
        self.assertEqual(issue["crop"], "second")
        self.assertEqual(issue["days_over"], 2)
        self.assertFalse(scenario["calendar_feasible"])

    def test_legacy_scenario_is_not_claimed_as_calendar_feasible(self):
        data = config()
        data["crop_catalog"] = {"first": crop()}
        data["scenarios"] = [{"name": "Legacy", "start_date": "2024-01-01", "crops": ["first"]}]
        scenario = simulate_scenarios(data)["scenarios"][0]
        self.assertEqual(scenario["calendar_status"], "not_fully_evaluated")
        self.assertIsNone(scenario["calendar_feasible"])
        self.assertEqual(scenario["schedule_warnings"][0]["code"], "planting_window_not_provided")

    def test_invalid_gap_and_schedule_shapes_are_rejected(self):
        data = config()
        data["scenarios"][0]["gaps_after_crops_days"] = []
        with self.assertRaisesRegex(ValueError, "one value between each pair"):
            simulate_scenarios(data)
        data = config()
        data["scenarios"][0]["schedule_mode"] = "magic"
        with self.assertRaisesRegex(ValueError, "fixed_gap or next_planting_window"):
            simulate_scenarios(data)

    def test_recurring_window_can_wrap_across_new_year(self):
        windows = _planting_windows({"planting_windows": [{
            "label": "Cool season",
            "start_month_day": "11-01",
            "end_month_day": "02-15",
        }]}, "demo")
        inside = _schedule_planting(date(2024, 1, 10), windows, "next_planting_window")
        self.assertEqual(inside["status"], "within_window")
        self.assertEqual(inside["matched_window"]["start_date"], "2023-11-01")
        shifted = _schedule_planting(date(2024, 3, 1), windows, "next_planting_window")
        self.assertEqual(shifted["date"].isoformat(), "2024-11-01")


if __name__ == "__main__":
    unittest.main()
