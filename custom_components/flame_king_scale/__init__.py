"""Flame King Propane Scale integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .bluetooth import FlameKingBluetoothManager
from .const import DOMAIN, PLATFORMS

type FlameKingConfigEntry = ConfigEntry[FlameKingBluetoothManager]


async def async_setup_entry(hass: HomeAssistant, entry: FlameKingConfigEntry) -> bool:
    """Set up a Flame King scale from a config entry."""
    manager = FlameKingBluetoothManager(hass, entry)
    entry.runtime_data = manager
    registry = er.async_get(hass)
    if old_capacity_entity := registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.unique_id}_capacity"
    ):
        registry.async_remove(old_capacity_entity)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FlameKingConfigEntry) -> bool:
    """Unload a Flame King scale."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: FlameKingConfigEntry
) -> None:
    """Refresh entity values after local configuration changes."""
    entry.runtime_data.async_notify_listeners()
