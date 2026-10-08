"""Estimate propane consumption from a stream of scale readings."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True, slots=True)
class UsageState:
    """Current gas-use estimate."""

    flowing: bool
    rate_lb_per_hour: float | None
    estimated_hours_remaining: float | None
    duration_minutes: float


class PropaneUsageTracker:
    """Recognize a sustained downward weight trend without treating bumps as use."""

    def __init__(self) -> None:
        """Initialize an empty tracker."""
        self._samples: deque[tuple[float, float]] = deque()
        self._flow_started: float | None = None
        self._smoothed_rate: float | None = None
        self._state = UsageState(False, None, None, 0.0)

    @property
    def state(self) -> UsageState:
        """Return the most recently calculated state."""
        return self._state

    def add_sample(
        self,
        timestamp: float,
        propane_weight_lb: float,
        *,
        detection_seconds: float,
        minimum_rate_lb_per_hour: float,
    ) -> UsageState:
        """Add a reading and update the sustained-consumption estimate."""
        self._samples.append((timestamp, propane_weight_lb))
        cutoff = timestamp - detection_seconds * 1.25
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        rate = self._trend_rate(detection_seconds)
        flowing = rate is not None and rate >= minimum_rate_lb_per_hour
        if flowing and rate is not None:
            if self._flow_started is None:
                self._flow_started = timestamp - detection_seconds
            self._smoothed_rate = (
                rate
                if self._smoothed_rate is None
                else self._smoothed_rate * 0.75 + rate * 0.25
            )
        else:
            self._flow_started = None
            self._smoothed_rate = None

        duration = (
            max(0.0, timestamp - self._flow_started) / 60
            if self._flow_started is not None
            else 0.0
        )
        eta = (
            propane_weight_lb / self._smoothed_rate
            if flowing and self._smoothed_rate and propane_weight_lb > 0
            else None
        )
        self._state = UsageState(flowing, self._smoothed_rate, eta, duration)
        return self._state

    def stop(self) -> UsageState:
        """End a flow episode when active monitoring has gone quiet."""
        self._samples.clear()
        self._flow_started = None
        self._smoothed_rate = None
        self._state = UsageState(False, None, None, 0.0)
        return self._state

    def _trend_rate(self, detection_seconds: float) -> float | None:
        """Return lb/hour for a sustained three-part downward trend."""
        if len(self._samples) < 3:
            return None
        start_time = self._samples[0][0]
        end_time = self._samples[-1][0]
        span = end_time - start_time
        if span < detection_seconds:
            return None

        third = span / 3
        groups: list[list[tuple[float, float]]] = [[], [], []]
        for sample_time, weight in self._samples:
            index = min(2, int((sample_time - start_time) / third))
            groups[index].append((sample_time, weight))
        if any(not group for group in groups):
            return None

        group_times = [median(item[0] for item in group) for group in groups]
        first, middle, last = (median(item[1] for item in group) for group in groups)
        # Requiring both thirds to fall rejects a tank being lifted or bumped once.
        if middle >= first or last >= middle:
            return None
        trend_span = group_times[2] - group_times[0]
        return (first - last) / trend_span * 3600
