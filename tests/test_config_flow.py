"""Tests for the setup and options flows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale.config_flow import (
    FlameKingConfigFlow,
    FlameKingOptionsFlow,
)
from custom_components.flame_king_scale.const import (
    CONF_ADDRESS,
    CONF_CAPACITY,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_TARE_WEIGHT,
    CONF_WEIGHT_UNIT,
    DEFAULT_OPTIONS,
    DOMAIN,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


def discovery(name: str | None = "Gas Monitor", services: list[str] | None = None):
    return SimpleNamespace(address=ADDRESS, name=name, service_uuids=services or [])


def new_flow(hass: HomeAssistant) -> FlameKingConfigFlow:
    flow = FlameKingConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "test"
    flow.context = {"source": "bluetooth"}
    return flow


async def test_rejects_unrelated_bluetooth_device(hass: HomeAssistant) -> None:
    result = await new_flow(hass).async_step_bluetooth(discovery(name="Other"))
    assert result["type"] == "abort"
    assert result["reason"] == "not_supported"


@pytest.mark.parametrize(
    ("system", "typed", "expected_tare_lb"),
    [
        (US_CUSTOMARY_SYSTEM, 18.5, 18.5),
        (METRIC_SYSTEM, 8.0, 17.637),
    ],
)
async def test_setup_with_tare_override_in_user_unit(
    hass: HomeAssistant, system, typed: float, expected_tare_lb: float
) -> None:
    hass.config.units = system
    flow = new_flow(hass)
    result = await flow.async_step_bluetooth(discovery())
    assert result["step_id"] == "bluetooth_confirm"

    result = await flow.async_step_bluetooth_confirm(
        {"name": "Grill", CONF_CAPACITY: "20"}
    )
    assert result["step_id"] == "tare_override"
    assert "20 lb (9 kg)" in result["description_placeholders"]["size"]

    result = await flow.async_step_tare_override({CONF_TARE_WEIGHT: typed})
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["options"][CONF_TARE_WEIGHT] == pytest.approx(
        expected_tare_lb, abs=1e-3
    )
    assert result["options"][CONF_CAPACITY] == 20.0
    assert result["options"][CONF_WEIGHT_UNIT] == "auto"


async def test_setup_blank_override_uses_preset(hass: HomeAssistant) -> None:
    flow = new_flow(hass)
    await flow.async_step_bluetooth(discovery())
    await flow.async_step_bluetooth_confirm({"name": "Grill", CONF_CAPACITY: "30"})
    result = await flow.async_step_tare_override({})
    assert result["options"][CONF_TARE_WEIGHT] == 25.0
    assert result["options"][CONF_CAPACITY] == 30.0


async def test_setup_rejects_blank_name(hass: HomeAssistant) -> None:
    flow = new_flow(hass)
    await flow.async_step_bluetooth(discovery())
    result = await flow.async_step_bluetooth_confirm(
        {"name": "  ", CONF_CAPACITY: "20"}
    )
    assert result["errors"] == {"name": "invalid_name"}


# --- options flow -----------------------------------------------------------


class FakeManager:
    """Stands in for the Bluetooth manager during guided calibration."""

    def __init__(self, raws: list[int]) -> None:
        self.raws = list(raws)
        self.available = True
        self.packet = SimpleNamespace(raw=raws[0])

    def async_trigger_poll(self) -> None:
        pass

    async def async_request_refresh(self):
        if not self.raws:
            return None
        self.packet = SimpleNamespace(raw=self.raws.pop(0))
        return self.packet


def options_flow(
    hass: HomeAssistant, manager: FakeManager, **options: Any
) -> FlameKingOptionsFlow:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS},
        options={**DEFAULT_OPTIONS, **options},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = manager
    flow = FlameKingOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    return flow


async def test_guided_calibration_in_kilograms(hass: HomeAssistant) -> None:
    hass.config.units = METRIC_SYSTEM
    # unloaded, first load (empty cylinder), second load.
    manager = FakeManager([0, 1000, 3000])
    flow = options_flow(hass, manager)

    await flow.async_step_calibrate({})
    result = await flow.async_step_calibrate_empty_tank(None)
    # The 17 lb preset tare is shown in the user's unit.
    assert result["type"] == "form"
    assert result["description_placeholders"]["tare"] == "7.7 kg"
    result = await flow.async_step_calibrate_empty_tank({})
    assert result["step_id"] == "calibrate_second_load"
    assert result["description_placeholders"]["first_weight"] == "7.7 kg"

    result = await flow.async_step_calibrate_second_load(
        {CONF_REFERENCE_WEIGHT: 18.0}  # kilograms
    )
    assert result["type"] == "create_entry"
    options = result["data"]
    # The 18 kg second load is stored in pounds.
    assert options[CONF_REFERENCE_WEIGHT] == pytest.approx(39.683, abs=1e-3)
    assert options[CONF_RAW_REFERENCE] == 3000
    assert options[CONF_RAW_ZERO] < 1000


async def test_calibration_rejects_missing_load(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([500, 400]))
    await flow.async_step_calibrate({})
    result = await flow.async_step_calibrate_empty_tank({"go": True})
    assert result["errors"] == {"base": "load_not_detected"}


async def test_calibration_without_live_reading(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    flow._captured_unloaded_raw = 0
    flow.config_entry.runtime_data.raws.clear()
    result = await flow.async_step_calibrate({})
    assert result["errors"] == {"base": "no_live_reading"}


async def test_tank_step_changes_unit_and_preserves_override(
    hass: HomeAssistant,
) -> None:
    flow = options_flow(hass, FakeManager([0]), **{CONF_TARE_WEIGHT: 18.4})
    result = await flow.async_step_tank({CONF_CAPACITY: "30", CONF_WEIGHT_UNIT: "kg"})
    assert result["step_id"] == "tank_tare_override"
    # The stamped override survives, shown in kilograms.
    schema_default = next(
        key.default() for key in result["data_schema"].schema if key == CONF_TARE_WEIGHT
    )
    assert schema_default == pytest.approx(8.35, abs=0.01)

    result = await flow.async_step_tank_tare_override({CONF_TARE_WEIGHT: 8.35})
    assert result["data"][CONF_WEIGHT_UNIT] == "kg"
    assert result["data"][CONF_CAPACITY] == 30.0
    assert result["data"][CONF_TARE_WEIGHT] == pytest.approx(18.409, abs=1e-3)


async def test_tank_step_switches_to_preset_when_no_override(
    hass: HomeAssistant,
) -> None:
    flow = options_flow(hass, FakeManager([0]))
    await flow.async_step_tank({CONF_CAPACITY: "40", CONF_WEIGHT_UNIT: "lb"})
    result = await flow.async_step_tank_tare_override({})
    assert result["data"][CONF_TARE_WEIGHT] == 32.0


async def test_reset_calibration_keeps_other_settings(hass: HomeAssistant) -> None:
    flow = options_flow(
        hass,
        FakeManager([0]),
        **{CONF_RAW_ZERO: 7, CONF_RAW_REFERENCE: 99, CONF_CAPACITY: 30.0},
    )
    result = await flow.async_step_reset_calibration({})
    assert result["data"][CONF_RAW_ZERO] == DEFAULT_OPTIONS[CONF_RAW_ZERO]
    assert result["data"][CONF_RAW_REFERENCE] == DEFAULT_OPTIONS[CONF_RAW_REFERENCE]
    assert result["data"][CONF_CAPACITY] == 30.0


async def test_advanced_rejects_identical_points(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    result = await flow.async_step_advanced(
        {CONF_RAW_ZERO: 5, CONF_RAW_REFERENCE: 5, CONF_REFERENCE_WEIGHT: 10}
    )
    assert result["errors"] == {"base": "same_calibration_points"}
