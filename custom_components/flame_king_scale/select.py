"""Tank-size selector for the Flame King Propane Scale."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bluetooth import FlameKingBluetoothManager
from .const import (
    CONF_CAPACITY,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
    TANK_CAPACITY_OPTIONS,
    default_tare_for_capacity,
)
from .entity import scale_device_info
from .units import format_tank_size

PARALLEL_UPDATES = 0


def _capacity_label(capacity: float) -> str:
    """Format a propane capacity for the dropdown, for example ``20 lb (9 kg)``."""
    return format_tank_size(capacity)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FlameKingBluetoothManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the tank-size selector."""
    async_add_entities([FlameKingTankSizeSelect(entry)])


class FlameKingTankSizeSelect(SelectEntity):
    """Select the cylinder's rated propane capacity."""

    _attr_has_entity_name = True
    _attr_translation_key = "tank_size"

    def __init__(self, entry: ConfigEntry[FlameKingBluetoothManager]) -> None:
        """Initialize the selector."""
        self.entry = entry
        self.manager = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id}_tank_size"
        self._attr_device_info = scale_device_info(entry)

    @property
    def options(self) -> list[str]:
        """Return standard sizes plus an existing custom size, if needed."""
        current = self._capacity
        capacities = list(TANK_CAPACITY_OPTIONS)
        if current not in capacities:
            capacities.append(current)
        return [_capacity_label(value) for value in sorted(capacities)]

    @property
    def current_option(self) -> str:
        """Return the configured tank size."""
        return _capacity_label(self._capacity)

    @property
    def _capacity(self) -> float:
        """Return the configured propane capacity."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        return float(options[CONF_CAPACITY])

    async def async_select_option(self, option: str) -> None:
        """Persist the selected propane capacity."""
        capacity = float(option.split(" ", 1)[0])
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        old_capacity = float(options[CONF_CAPACITY])
        old_tare = float(options[CONF_TARE_WEIGHT])
        if abs(old_tare - default_tare_for_capacity(old_capacity)) <= 0.001:
            options[CONF_TARE_WEIGHT] = default_tare_for_capacity(capacity)
        options[CONF_CAPACITY] = capacity
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def async_added_to_hass(self) -> None:
        """Subscribe to configuration updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
