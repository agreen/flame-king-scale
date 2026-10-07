"""Weight unit handling.

All calculations and stored options use pounds. These helpers convert at the
edges (entities and configuration forms) to the unit the user prefers.
"""

from __future__ import annotations

from typing import Final

UNIT_LB: Final = "lb"
UNIT_KG: Final = "kg"
UNIT_AUTO: Final = "auto"
WEIGHT_UNIT_CHOICES: Final = (UNIT_AUTO, UNIT_LB, UNIT_KG)

LB_PER_KG: Final = 2.2046226218


def resolve_weight_unit(preference: str, *, is_metric: bool) -> str:
    """Return ``"lb"`` or ``"kg"`` for a stored preference and unit system."""
    if preference == UNIT_LB:
        return UNIT_LB
    if preference == UNIT_KG:
        return UNIT_KG
    return UNIT_KG if is_metric else UNIT_LB


def lb_to_unit(value_lb: float, unit: str) -> float:
    """Convert pounds to the display unit."""
    return value_lb / LB_PER_KG if unit == UNIT_KG else value_lb


def unit_to_lb(value: float, unit: str) -> float:
    """Convert a value in the display unit to pounds."""
    return value * LB_PER_KG if unit == UNIT_KG else value


def format_weight(value_lb: float, unit: str) -> str:
    """Format a pound value for display text, for example ``"17 lb"``."""
    value = lb_to_unit(value_lb, unit)
    return f"{value:.1f} kg" if unit == UNIT_KG else f"{value:g} lb"


def format_tank_size(capacity_lb: float) -> str:
    """Format a cylinder size showing its nominal pounds and kilograms."""
    return f"{capacity_lb:g} lb ({capacity_lb / LB_PER_KG:.0f} kg)"
