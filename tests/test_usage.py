"""Tests for propane-use estimation."""

import unittest

from usage import PropaneUsageTracker


class UsageTrackerTests(unittest.TestCase):
    """Validate flow recognition and estimates."""

    def test_detects_sustained_flow_and_estimates_time_remaining(self) -> None:
        tracker = PropaneUsageTracker()
        state = None
        for seconds in range(0, 76, 5):
            # A 1.2 lb/hour burn from a tank containing 12 lb.
            state = tracker.add_sample(
                seconds,
                12 - 1.2 * seconds / 3600,
                detection_seconds=60,
                minimum_rate_lb_per_hour=0.5,
            )

        self.assertIsNotNone(state)
        assert state is not None
        self.assertTrue(state.flowing)
        self.assertIsNotNone(state.rate_lb_per_hour)
        assert state.rate_lb_per_hour is not None
        self.assertGreater(state.rate_lb_per_hour, 1.1)
        self.assertLess(state.rate_lb_per_hour, 1.3)
        self.assertIsNotNone(state.estimated_hours_remaining)
        assert state.estimated_hours_remaining is not None
        self.assertGreater(state.estimated_hours_remaining, 9.8)
        self.assertLess(state.estimated_hours_remaining, 10.2)

    def test_rejects_single_weight_change_as_flow(self) -> None:
        tracker = PropaneUsageTracker()
        state = None
        for seconds in range(0, 76, 5):
            weight = 12 if seconds < 20 else 11
            state = tracker.add_sample(
                seconds,
                weight,
                detection_seconds=60,
                minimum_rate_lb_per_hour=0.5,
            )

        self.assertIsNotNone(state)
        assert state is not None
        self.assertFalse(state.flowing)
        self.assertIsNone(state.estimated_hours_remaining)

    def test_stop_clears_active_usage(self) -> None:
        tracker = PropaneUsageTracker()
        for seconds in range(0, 76, 5):
            tracker.add_sample(
                seconds,
                10 - seconds / 1800,
                detection_seconds=60,
                minimum_rate_lb_per_hour=0.5,
            )

        self.assertTrue(tracker.state.flowing)
        self.assertFalse(tracker.stop().flowing)
