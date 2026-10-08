"""Tests for binary sensors, buttons, diagnostics, and integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale import (
    async_setup_entry,
    async_unload_entry,
    binary_sensor,
    button,
)
from custom_components.flame_king_scale.const import DOMAIN
from custom_components.flame_king_scale.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.helpers import RAW, entities, make_entry


async def test_binary_sensors_reflect_usage(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    by_key = await entities(hass, entry, binary_sensor)
    assert by_key["gas_flowing"].is_on is True
    assert by_key["extended_gas_use"].is_on is False

    entry.runtime_data.usage.flowing = False
    entry.runtime_data.long_use = True
    assert by_key["gas_flowing"].is_on is False
    assert by_key["extended_gas_use"].is_on is True


async def test_buttons_call_the_manager(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    by_name = await entities(hass, entry, button)
    await by_name["FlameKingRefreshButton"].async_press()
    entry.runtime_data.async_request_once.assert_awaited_once()
    await by_name["FlameKingLiveMonitorButton"].async_press()
    entry.runtime_data.async_start_live_monitoring.assert_awaited_once()


async def test_diagnostics_redact_the_address(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    entry.runtime_data.consecutive_failures = 3
    entry.runtime_data.last_error = "boom"
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config"]["address"] == "**REDACTED**"
    assert result["packet"] == {"raw": RAW, "battery": 77}
    assert result["consecutive_failures"] == 3
    assert result["last_error"] == "boom"
    assert result["available"] is True

    entry.runtime_data.packet = None
    assert (await async_get_config_entry_diagnostics(hass, entry))["packet"] is None


async def test_setup_starts_manager_and_removes_old_capacity_entity(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        data={"address": "AA:BB:CC:DD:EE:FF"},
    )
    entry.add_to_hass(hass)

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "number", DOMAIN, f"{entry.unique_id}_capacity", config_entry=entry
    )

    with (
        patch(
            "custom_components.flame_king_scale.FlameKingBluetoothManager.async_start",
            new=AsyncMock(),
        ) as start,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
    ):
        assert await async_setup_entry(hass, entry)

    start.assert_awaited_once()
    forward.assert_awaited_once()
    assert registry.async_get(old.entity_id) is None  # legacy entity removed


async def test_unload_stops_manager(hass: HomeAssistant) -> None:
    entry = make_entry(hass, METRIC_SYSTEM)
    entry.runtime_data.async_stop = AsyncMock()

    with patch.object(
        hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)
    ):
        assert await async_unload_entry(hass, entry)
    entry.runtime_data.async_stop.assert_awaited_once()

    entry.runtime_data.async_stop.reset_mock()
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=False),
    ):
        assert not await async_unload_entry(hass, entry)
    entry.runtime_data.async_stop.assert_not_awaited()


async def test_options_update_refreshes_entities(hass: HomeAssistant) -> None:
    from unittest.mock import MagicMock

    from custom_components.flame_king_scale import _async_options_updated

    entry = make_entry(hass, METRIC_SYSTEM)
    entry.runtime_data.async_notify_listeners = MagicMock()
    await _async_options_updated(hass, entry)
    entry.runtime_data.async_notify_listeners.assert_called_once()
