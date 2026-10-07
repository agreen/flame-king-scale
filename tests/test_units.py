"""Tests for weight unit conversion helpers."""

import pytest

from custom_components.flame_king_scale.units import (
    format_tank_size,
    format_weight,
    lb_to_unit,
    resolve_weight_unit,
    unit_to_lb,
)


@pytest.mark.parametrize(
    ("preference", "is_metric", "expected"),
    [
        ("auto", True, "kg"),
        ("auto", False, "lb"),
        ("lb", True, "lb"),
        ("kg", False, "kg"),
        ("unexpected", False, "lb"),
    ],
)
def test_resolve_weight_unit(preference: str, is_metric: bool, expected: str) -> None:
    assert resolve_weight_unit(preference, is_metric=is_metric) == expected


def test_round_trip_is_stable() -> None:
    for value in (0.01, 17.0, 25.0, 123.456):
        assert unit_to_lb(lb_to_unit(value, "kg"), "kg") == pytest.approx(value)
        assert lb_to_unit(value, "lb") == value


def test_known_conversions() -> None:
    assert lb_to_unit(20, "kg") == pytest.approx(9.0718, abs=1e-3)
    assert unit_to_lb(6, "kg") == pytest.approx(13.2277, abs=1e-3)


def test_formatting() -> None:
    assert format_weight(17, "lb") == "17 lb"
    assert format_weight(17, "kg") == "7.7 kg"
    assert format_tank_size(20) == "20 lb (9 kg)"
    assert format_tank_size(40) == "40 lb (18 kg)"
