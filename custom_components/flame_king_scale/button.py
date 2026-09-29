"""Button entities for the Flame King Propane Scale integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bluetooth import FlameKingBluetoothManager
from .entity import scale_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FlameKingBluetoothManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the on-demand reading and live-monitoring buttons."""
    async_add_entities(
        [FlameKingRefreshButton(entry), FlameKingLiveMonitorButton(entry)]
    )


class FlameKingRefreshButton(ButtonEntity):
    """Request an immediate scale reading."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:scale-bathroom"

    def __init__(self, entry: ConfigEntry[FlameKingBluetoothManager]) -> None:
        """Initialize the button."""
        self.manager = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id}_refresh"
        self._attr_device_info = scale_device_info(entry)

    async def async_press(self) -> None:
        """Fetch one fresh packet without forcing a live session."""
        await self.manager.async_request_once()


class FlameKingLiveMonitorButton(ButtonEntity):
    """Start or extend a deliberate live-monitoring session."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_monitor"
    _attr_icon = "mdi:access-point"

    def __init__(self, entry: ConfigEntry[FlameKingBluetoothManager]) -> None:
        """Initialize the button."""
        self.manager = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id}_live_monitor"
        self._attr_device_info = scale_device_info(entry)

    async def async_press(self) -> None:
        """Connect now and remain live until the configured quiet time passes."""
        await self.manager.async_start_live_monitoring()
