"""Tests for propane-use estimation."""

import unittest

from custom_components.flame_king_scale.usage import PropaneUsageTracker


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


# --- sampling at poll rates ---------------------------------------------------

LB_PER_COUNT = 13.2277357308 / 1536  # factory calibration: 1536 counts = 6 kg


def first_flow_poll(lb_per_hour: float, gap: float, window: float) -> int | None:
    """Return the index of the first poll that reports gas flow, or None."""
    tracker = PropaneUsageTracker()
    for poll in range(14):
        now = poll * (gap + 5)  # each poll also takes a few seconds
        counts = round(3000 - lb_per_hour / 3600 * now / LB_PER_COUNT)  # quantized
        state = tracker.add_sample(
            now,
            counts * LB_PER_COUNT,
            detection_seconds=window,
            minimum_rate_lb_per_hour=0.5,
        )
        if state.flowing:
            return poll
    return None


def test_burners_are_detected_at_one_poll_per_minute() -> None:
    for lb_per_hour in (0.9, 1.7):  # roughly 20,000 and 36,000 BTU/h
        found = first_flow_poll(lb_per_hour, gap=60, window=300)
        assert found is not None
        assert found <= 6  # about one detection window plus a poll


def test_polling_faster_does_not_detect_flow_sooner() -> None:
    # Latency is set by the detection window, not by how often we poll.
    slow = first_flow_poll(1.7, gap=60, window=300)
    fast = first_flow_poll(1.7, gap=30, window=300)
    assert slow is not None and fast is not None
    assert fast * 35 >= slow * 65 - 65  # within one slow poll of the same time


def test_a_shorter_window_detects_sooner() -> None:
    assert first_flow_poll(1.7, gap=60, window=180) < first_flow_poll(
        1.7, gap=60, window=300
    )
