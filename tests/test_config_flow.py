"""Tests for the setup and options flows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
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


# --- discovery, abort, and form paths ---------------------------------------

from unittest.mock import patch  # noqa: E402

from homeassistant.helpers import area_registry as ar  # noqa: E402

from custom_components.flame_king_scale import config_flow  # noqa: E402


def scan(*infos):
    """Patch the list of recently seen Bluetooth devices."""
    return patch.object(
        config_flow.bluetooth,
        "async_discovered_service_info",
        return_value=list(infos),
    )


async def test_user_step_without_devices_reports_error(hass: HomeAssistant) -> None:
    with scan():
        result = await new_flow(hass).async_step_user()
    assert result["errors"] == {"base": "no_devices_found"}


async def test_user_step_with_one_device_goes_to_confirmation(
    hass: HomeAssistant,
) -> None:
    with scan(discovery()):
        result = await new_flow(hass).async_step_user()
    assert result["step_id"] == "bluetooth_confirm"


async def test_user_step_with_several_devices_lets_you_choose(
    hass: HomeAssistant,
) -> None:
    other = SimpleNamespace(
        address="11:22:33:44:55:66", name="Gas Monitor", service_uuids=[]
    )
    flow = new_flow(hass)
    unrelated = SimpleNamespace(address="99:99", name="Unrelated", service_uuids=[])
    with scan(discovery(), other, unrelated):
        result = await flow.async_step_user()
        assert result["step_id"] == "user"
        result = await flow.async_step_user({"device": "11:22:33:44:55:66"})
    assert result["step_id"] == "bluetooth_confirm"


async def test_user_step_skips_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={}).add_to_hass(hass)
    with scan(discovery()):
        result = await new_flow(hass).async_step_user()
    assert result["errors"] == {"base": "no_devices_found"}


async def test_discovery_of_configured_device_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={}).add_to_hass(hass)
    with pytest.raises(AbortFlow) as aborted:
        await new_flow(hass).async_step_bluetooth(discovery())
    assert aborted.value.reason == "already_configured"


async def test_setup_validates_and_stores_the_room(hass: HomeAssistant) -> None:
    flow = new_flow(hass)
    await flow.async_step_bluetooth(discovery())

    result = await flow.async_step_bluetooth_confirm(
        {"name": "Grill", "area_id": "missing", CONF_CAPACITY: "20"}
    )
    assert result["errors"] == {"area_id": "invalid_area"}

    area = ar.async_get(hass).async_create("Patio")
    result = await flow.async_step_bluetooth_confirm(
        {"name": "Grill", "area_id": area.id, CONF_CAPACITY: "20"}
    )
    result = await flow.async_step_tare_override({})
    assert result["data"]["suggested_area"] == "Patio"


async def test_tare_step_without_context_restarts_discovery(
    hass: HomeAssistant,
) -> None:
    with scan():
        result = await new_flow(hass).async_step_tare_override()
    assert result["step_id"] == "user"


async def test_options_flow_entry_points(hass: HomeAssistant) -> None:
    assert isinstance(
        FlameKingConfigFlow.async_get_options_flow(None), FlameKingOptionsFlow
    )
    flow = options_flow(hass, FakeManager([0]))
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert "calibrate" in menu["menu_options"]


async def test_power_step_converts_flow_rate(hass: HomeAssistant) -> None:
    hass.config.units = METRIC_SYSTEM
    flow = options_flow(hass, FakeManager([0]))
    form = await flow.async_step_power()
    assert form["step_id"] == "power"

    values = {
        key: DEFAULT_OPTIONS[key]
        for key in (
            "poll_interval_minutes",
            "stability_time_minutes",
            "stability_variance_percent",
            "flow_detection_seconds",
            "long_use_minutes",
        )
    }
    result = await flow.async_step_power(
        {**values, "flow_minimum_rate_lb_per_hour": 0.5}
    )
    # 0.5 kg/h is stored as pounds per hour.
    assert result["data"]["flow_minimum_rate_lb_per_hour"] == pytest.approx(
        1.1023, abs=1e-3
    )


async def test_advanced_step_saves_valid_points(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    form = await flow.async_step_advanced()
    assert form["step_id"] == "advanced"
    result = await flow.async_step_advanced(
        {CONF_RAW_ZERO: 10, CONF_RAW_REFERENCE: 2000, CONF_REFERENCE_WEIGHT: 20}
    )
    assert result["data"][CONF_RAW_REFERENCE] == 2000


async def test_known_weight_calibration_path(hass: HomeAssistant) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    flow = options_flow(hass, FakeManager([0, 1000, 3000]))
    await flow.async_step_calibrate({})
    form = await flow.async_step_calibrate_known_weight()
    assert form["step_id"] == "calibrate_known_weight"
    result = await flow.async_step_calibrate_known_weight({CONF_REFERENCE_WEIGHT: 10})
    assert result["step_id"] == "calibrate_second_load"
    result = await flow.async_step_calibrate_second_load({CONF_REFERENCE_WEIGHT: 30})
    assert result["type"] == "create_entry"


async def test_second_load_must_form_a_valid_line(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0, 1000, 900]))
    await flow.async_step_calibrate({})
    await flow.async_step_calibrate_empty_tank({})
    # A heavier load that reads lower than the first is rejected.
    result = await flow.async_step_calibrate_second_load({CONF_REFERENCE_WEIGHT: 40})
    assert result["errors"] == {"base": "invalid_loaded_points"}


async def test_second_load_without_live_reading(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0, 1000]))
    await flow.async_step_calibrate({})
    await flow.async_step_calibrate_empty_tank({})
    result = await flow.async_step_calibrate_second_load({CONF_REFERENCE_WEIGHT: 40})
    assert result["errors"] == {"base": "no_live_reading"}


async def test_out_of_order_steps_restart_safely(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    # No unloaded capture yet: loaded-point steps fall back to the first step.
    result = await flow.async_step_calibrate_empty_tank({})
    assert result["step_id"] == "calibrate"
    result = await flow.async_step_calibrate_second_load({CONF_REFERENCE_WEIGHT: 5})
    assert result["step_id"] == "calibrate"
    # No pending tank options: the tare step returns to the tank form.
    result = await flow.async_step_tank_tare_override({})
    assert result["step_id"] == "tank"


async def test_flows_show_unavailable_when_scale_is_asleep(
    hass: HomeAssistant,
) -> None:
    manager = FakeManager([0])
    manager.available = False
    flow = options_flow(hass, manager)
    form = await flow.async_step_calibrate()
    assert form["description_placeholders"]["raw"] == "unavailable"


async def test_reset_calibration_shows_confirmation_form(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    result = await flow.async_step_reset_calibration()
    assert result["type"] == "form"
    assert result["step_id"] == "reset_calibration"


async def test_first_load_without_live_reading(hass: HomeAssistant) -> None:
    flow = options_flow(hass, FakeManager([0]))
    await flow.async_step_calibrate({})
    result = await flow.async_step_calibrate_empty_tank({})
    assert result["errors"] == {"base": "no_live_reading"}
