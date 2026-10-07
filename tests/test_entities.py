"""Tests for entity values, units, and conversions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale import number, select, sensor
from custom_components.flame_king_scale.const import (
    CONF_CAPACITY,
    CONF_FLOW_MIN_RATE,
    CONF_TARE_WEIGHT,
    CONF_WEIGHT_UNIT,
    DEFAULT_OPTIONS,
    DOMAIN,
)

# Factory calibration: raw 1600 is 6 kg, so raw 3136 is 12 kg = 26.455 lb gross.
RAW = 3136
GROSS_LB = 12 * 2.2046226218


def make_entry(hass: HomeAssistant, system, **options: Any) -> MockConfigEntry:
    hass.config.units = system
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        title="Grill",
        data={"address": "AA:BB:CC:DD:EE:FF"},
        options={**DEFAULT_OPTIONS, **options},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        packet=SimpleNamespace(raw=RAW, battery=77),
        usage=SimpleNamespace(
            flowing=True,
            rate_lb_per_hour=2.2046226218,
            estimated_hours_remaining=3.0,
            duration_minutes=12.0,
        ),
        long_use=False,
        available=True,
        async_add_listener=lambda _listener: lambda: None,
    )
    return entry


async def entities(hass: HomeAssistant, entry, module) -> dict[str, Any]:
    found: list[Any] = []
    await module.async_setup_entry(hass, entry, found.extend)
    for entity in found:
        entity.hass = hass
    key = (
        (lambda e: e.entity_description.key)
        if hasattr(found[0], "entity_description")
        else (lambda e: type(e).__name__)
    )
    return {key(entity): entity for entity in found}


async def test_sensors_follow_metric_system(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    by_key = await entities(hass, entry, sensor)

    gross = by_key["gross_weight"]
    assert gross.native_unit_of_measurement == "kg"
    assert gross.native_value == pytest.approx(12.0, abs=0.01)
    # 12 kg gross - 17 lb tare = 26.455 - 17 lb, shown in kg.
    assert by_key["propane_weight"].native_value == pytest.approx(
        (GROSS_LB - 17) / 2.2046226218, abs=0.01
    )
    rate = by_key["consumption_rate"]
    assert rate.native_unit_of_measurement == "kg/h"
    assert rate.native_value == pytest.approx(1.0, abs=0.01)
    # Percentages, battery, and raw are not unit-converted.
    assert by_key["battery"].native_value == 77
    assert by_key["raw"].native_value == RAW


async def test_sensors_follow_us_system(hass: HomeAssistant) -> None:
    entry = make_entry(hass, US_CUSTOMARY_SYSTEM)
    by_key = await entities(hass, entry, sensor)
    assert by_key["gross_weight"].native_unit_of_measurement == "lb"
    assert by_key["gross_weight"].native_value == pytest.approx(GROSS_LB, abs=0.01)
    assert by_key["consumption_rate"].native_unit_of_measurement == "lb/h"
    assert by_key["consumption_rate"].native_value == pytest.approx(2.2, abs=0.01)


async def test_explicit_unit_overrides_system(hass: HomeAssistant) -> None:
    entry = make_entry(hass, US_CUSTOMARY_SYSTEM, **{CONF_WEIGHT_UNIT: "kg"})
    by_key = await entities(hass, entry, sensor)
    assert by_key["gross_weight"].native_unit_of_measurement == "kg"
    assert by_key["gross_weight"].native_value == pytest.approx(12.0, abs=0.01)

    entry = make_entry(hass, METRIC_SYSTEM, **{CONF_WEIGHT_UNIT: "lb"})
    by_key = await entities(hass, entry, sensor)
    assert by_key["gross_weight"].native_unit_of_measurement == "lb"


async def test_sensor_unavailable_until_first_packet(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    entry.runtime_data.packet = None
    by_key = await entities(hass, entry, sensor)
    assert not by_key["gross_weight"].available
    assert by_key["gross_weight"].native_value is None


async def test_number_entities_convert_both_ways(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM, **{CONF_TARE_WEIGHT: 17.0})
    by_key = await entities(hass, entry, number)

    tare = by_key["tare_weight"]
    assert tare.native_unit_of_measurement == "kg"
    assert tare.native_value == pytest.approx(7.711, abs=1e-3)
    assert tare.native_max_value == pytest.approx(226.796, abs=1e-2)

    await tare.async_set_native_value(8.0)  # kilograms
    assert entry.options[CONF_TARE_WEIGHT] == pytest.approx(17.637, abs=1e-3)

    rate = by_key["minimum_flow_rate"]
    assert rate.native_unit_of_measurement == "kg/h"
    await rate.async_set_native_value(0.5)
    assert entry.options[CONF_FLOW_MIN_RATE] == pytest.approx(1.1023, abs=1e-3)


async def test_non_weight_numbers_are_unchanged(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    by_key = await entities(hass, entry, number)
    poll = by_key["poll_interval"]
    assert poll.native_unit_of_measurement == "min"
    assert poll.native_value == 60
    assert poll.native_max_value == 1440


async def test_number_in_pounds_is_untouched(hass: HomeAssistant) -> None:
    entry = make_entry(hass, US_CUSTOMARY_SYSTEM, **{CONF_TARE_WEIGHT: 17.0})
    tare = (await entities(hass, entry, number))["tare_weight"]
    assert tare.native_value == 17.0
    await tare.async_set_native_value(18.25)
    assert entry.options[CONF_TARE_WEIGHT] == 18.25


async def test_raw_calibration_numbers_reject_equal_points(
    hass: HomeAssistant,
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    entry = make_entry(hass, US_CUSTOMARY_SYSTEM)
    by_key = await entities(hass, entry, number)
    with pytest.raises(HomeAssistantError):
        await by_key["raw_zero"].async_set_native_value(1600)


async def test_tank_size_select_labels_and_tare_preset(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    entry.runtime_data.async_add_listener = lambda _l: lambda: None
    (entity,) = (await entities(hass, entry, select)).values()

    assert entity.options == ["20 lb (9 kg)", "30 lb (14 kg)", "40 lb (18 kg)"]
    assert entity.current_option == "20 lb (9 kg)"

    await entity.async_select_option("30 lb (14 kg)")
    assert entry.options[CONF_CAPACITY] == 30.0
    # Typical-empty preset follows the size when no stamped override is set.
    assert entry.options[CONF_TARE_WEIGHT] == 25.0


async def test_tank_size_select_keeps_stamped_override(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM, **{CONF_TARE_WEIGHT: 18.4})
    (entity,) = (await entities(hass, entry, select)).values()
    await entity.async_select_option("40 lb (18 kg)")
    assert entry.options[CONF_TARE_WEIGHT] == 18.4


async def test_tank_size_select_includes_custom_size(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM, **{CONF_CAPACITY: 33.0})
    (entity,) = (await entities(hass, entry, select)).values()
    assert "33 lb (15 kg)" in entity.options
    assert entity.current_option == "33 lb (15 kg)"
