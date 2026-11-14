import unittest

from grainstorm.fao56 import basal_coefficient, dual_coefficient_day, validate_dual_config


CONFIG = {
    "method": "fao56_dual", "kcb_initial": 0.15, "kcb_mid": 1.15, "kcb_end": 0.5,
    "depletion_fraction": 0.5, "readily_evaporable_water_mm": 8,
    "total_evaporable_water_mm": 20, "wetted_fraction": 1,
    "crop_height_m": 2, "kc_max": 1.2, "initial_surface_depletion_mm": 0,
}


class Fao56Tests(unittest.TestCase):
    def test_piecewise_basal_coefficient(self):
        stages = [20, 30, 40, 30]
        self.assertEqual(basal_coefficient(0, stages, .15, 1.15, .5), .15)
        self.assertEqual(basal_coefficient(49, stages, .15, 1.15, .5), 1.15)
        self.assertAlmostEqual(basal_coefficient(119, stages, .15, 1.15, .5), .5)

    def test_water_stress_reduces_transpiration(self):
        config = validate_dual_config(CONFIG)
        wet = dual_coefficient_day(et0_mm=5, water_mm=100, capacity_mm=100,
            surface_depletion_mm=0, day_index=50, stage_days=[20, 30, 40, 30], config=config)
        dry = dual_coefficient_day(et0_mm=5, water_mm=10, capacity_mm=100,
            surface_depletion_mm=20, day_index=50, stage_days=[20, 30, 40, 30], config=config)
        self.assertEqual(wet["ks"], 1)
        self.assertLess(dry["ks"], 1)
        self.assertLess(dry["transpiration_mm"], wet["transpiration_mm"])

    def test_invalid_surface_parameters_are_rejected(self):
        bad = {**CONFIG, "readily_evaporable_water_mm": 30}
        with self.assertRaises(ValueError):
            validate_dual_config(bad)


if __name__ == "__main__":
    unittest.main()
