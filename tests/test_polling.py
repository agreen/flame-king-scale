"""Tests for adaptive polling calculations."""

import unittest

from custom_components.flame_king_scale.polling import (
    has_significant_change,
    raw_tolerance_for_percent,
)


class PollingTests(unittest.TestCase):
    """Validate percentage-to-raw polling thresholds."""

    def test_converts_one_percent_of_capacity_to_raw_units(self) -> None:
        self.assertEqual(
            raw_tolerance_for_percent(
                raw_zero=100,
                raw_reference=1900,
                reference_weight_lb=18,
                capacity_lb=20,
                variance_percent=1,
            ),
            20,
        )

    def test_invalid_calibration_uses_minimum_tolerance(self) -> None:
        self.assertEqual(
            raw_tolerance_for_percent(
                raw_zero=100,
                raw_reference=100,
                reference_weight_lb=18,
                capacity_lb=20,
                variance_percent=1,
            ),
            1,
        )

    def test_change_must_exceed_tolerance(self) -> None:
        self.assertFalse(has_significant_change(100, 120, 20))
        self.assertTrue(has_significant_change(100, 121, 20))


if __name__ == "__main__":
    unittest.main()
