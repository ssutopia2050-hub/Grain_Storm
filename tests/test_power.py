
import unittest

from grainstorm.sources.power import validate_inputs


class TestPowerValidation(unittest.TestCase):

    def test_valid_inputs(self):
        validate_inputs(
            latitude=30.34,
            longitude=76.39,
            start_date="20240101",
            end_date="20240131",
        )

    def test_invalid_latitude(self):
        with self.assertRaises(ValueError):
            validate_inputs(
                latitude=100,
                longitude=76.39,
                start_date="20240101",
                end_date="20240131",
            )

    def test_invalid_longitude(self):
        with self.assertRaises(ValueError):
            validate_inputs(
                latitude=30.34,
                longitude=200,
                start_date="20240101",
                end_date="20240131",
            )

    def test_invalid_date_order(self):
        with self.assertRaises(ValueError):
            validate_inputs(
                latitude=30.34,
                longitude=76.39,
                start_date="20240131",
                end_date="20240101",
            )

    def test_invalid_date_format(self):
        with self.assertRaises(ValueError):
            validate_inputs(
                latitude=30.34,
                longitude=76.39,
                start_date="01-01-2024",
                end_date="20240131",
            )


if __name__ == "__main__":
    unittest.main()
