"""Binary sensors for Flame King propane usage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bluetooth import FlameKingBluetoothManager
from .entity import scale_device_info

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FlameKingBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Flame King binary sensor."""

    value_fn: Callable[[FlameKingBluetoothManager], bool]


DESCRIPTIONS = (
    FlameKingBinarySensorDescription(
        key="gas_flowing",
        translation_key="gas_flowing",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda manager: manager.usage.flowing,
    ),
    FlameKingBinarySensorDescription(
        key="extended_gas_use",
        translation_key="extended_gas_use",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda manager: manager.long_use,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FlameKingBluetoothManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up usage binary sensors."""
    async_add_entities(FlameKingBinarySensor(entry, item) for item in DESCRIPTIONS)


class FlameKingBinarySensor(BinarySensorEntity):
    """A propane-use state reported by the Bluetooth manager."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[FlameKingBluetoothManager],
        description: FlameKingBinarySensorDescription,
    ) -> None:
        """Initialize the entity."""
        self.manager = entry.runtime_data
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = scale_device_info(entry)

    @property
    def is_on(self) -> bool:
        """Return the detected state."""
        return self.entity_description.value_fn(self.manager)

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
