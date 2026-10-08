"""Adaptive polling calculations for the Flame King scale."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


def raw_tolerance_for_percent(
    *,
    raw_zero: int,
    raw_reference: int,
    reference_weight_lb: float,
    capacity_lb: float,
    variance_percent: float,
) -> int:
    """Convert a propane-capacity percentage tolerance into raw scale units."""
    raw_span = abs(raw_reference - raw_zero)
    if raw_span == 0 or reference_weight_lb <= 0 or capacity_lb <= 0:
        return 1
    tolerance_lb = capacity_lb * max(variance_percent, 0) / 100
    return max(1, math.ceil(tolerance_lb * raw_span / reference_weight_lb))


def has_significant_change(previous_raw: int, current_raw: int, tolerance: int) -> bool:
    """Return whether two raw readings differ by more than the tolerance."""
    return abs(current_raw - previous_raw) > max(0, tolerance)


# --- Idle / fast polling plan -------------------------------------------------

MIN_FAST_POLL_SECONDS = 15.0
"""Shortest allowed gap between fast polls (a gap after a poll ends, not a rate)."""
MIN_QUIET_POLLS = 4
"""Quiet polls required before fast polling ends, so one unchanged reading on a
quantized scale cannot end it early."""
MAX_CONSECUTIVE_FAILURES = 3
"""Failed polls in a row after which fast polling gives up."""
TYPICAL_POLL_SECONDS = 5.0
"""Rough time a successful poll takes, used only to turn a window into a count."""
MAX_FAST_SECONDS = 24 * 60 * 60.0
"""Safety cap on one continuous stretch of fast polling."""


def quiet_polls_needed(window_seconds: float, fast_gap_seconds: float) -> int:
    """Return how many quiet polls make up the user's fast-polling window.

    Each poll takes a few seconds on top of the configured gap, so the gap alone
    would understate how long a poll count really lasts.
    """
    period = max(fast_gap_seconds, MIN_FAST_POLL_SECONDS) + TYPICAL_POLL_SECONDS
    return max(MIN_QUIET_POLLS, math.ceil(max(window_seconds, 0.0) / period))


class PollMode(StrEnum):
    """How often the scale is being read."""

    IDLE = "idle"
    FAST = "fast"


@dataclass
class PollPlanner:
    """Decide between slow and fast polling from the results of each poll.

    Only successful polls can count as quiet. A failed poll changes neither the
    quiet count nor the baseline reading; a short run of failures ends fast
    polling so an absent scale is not retried at the fast rate forever.
    """

    mode: PollMode = PollMode.IDLE
    quiet_polls: int = 0
    consecutive_failures: int = 0
    anchor_raw: int | None = None
    fast_since: float | None = None

    def seed_fast(self, now: float) -> None:
        """Start (or restart the quiet count of) fast polling."""
        if self.mode is not PollMode.FAST:
            self.mode = PollMode.FAST
            self.fast_since = now
        self.quiet_polls = 0

    def to_idle(self) -> None:
        """Return to slow polling."""
        self.mode = PollMode.IDLE
        self.quiet_polls = 0
        self.fast_since = None

    def record_success(
        self,
        raw: int,
        *,
        tolerance: int,
        flowing: bool,
        quiet_needed: int,
        now: float,
    ) -> None:
        """Account for one successful poll."""
        self.consecutive_failures = 0
        if (
            self.mode is PollMode.FAST
            and self.fast_since is not None
            and now - self.fast_since >= MAX_FAST_SECONDS
        ):
            self.to_idle()
            self.anchor_raw = raw
            return

        changed = self.anchor_raw is not None and has_significant_change(
            self.anchor_raw, raw, tolerance
        )
        if self.anchor_raw is None or changed:
            self.anchor_raw = raw

        if changed or flowing:
            self.seed_fast(now)
        elif self.mode is PollMode.FAST:
            self.quiet_polls += 1
            if self.quiet_polls >= quiet_needed:
                self.to_idle()
                self.anchor_raw = raw
        else:
            # Idle: compare each reading with the previous one, so slow drift
            # over the idle interval can still add up to a change.
            self.anchor_raw = raw

    def record_failure(self) -> bool:
        """Account for one failed poll; return True if fast polling gave up."""
        self.consecutive_failures += 1
        if (
            self.mode is PollMode.FAST
            and self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
        ):
            self.to_idle()
            return True
        return False

    def next_interval(self, idle_seconds: float, fast_seconds: float) -> float:
        """Return the gap before the next poll."""
        if self.mode is PollMode.FAST:
            return max(fast_seconds, MIN_FAST_POLL_SECONDS)
        return idle_seconds
