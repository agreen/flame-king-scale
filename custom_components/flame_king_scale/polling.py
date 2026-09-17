"""Adaptive polling calculations for the Flame King scale."""

from __future__ import annotations

import math


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
