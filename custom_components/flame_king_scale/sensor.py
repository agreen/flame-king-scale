"""Sensor entities for the Flame King Propane Scale integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bluetooth import FlameKingBluetoothManager
from .const import (
    CONF_CAPACITY,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .protocol import TankState, calculate_tank_state


@dataclass(frozen=True, kw_only=True)
class FlameKingSensorDescription(SensorEntityDescription):
    """Describe a Flame King sensor."""

    value_fn: Callable[[FlameKingSensor], int | float | None]


SENSOR_DESCRIPTIONS = (
    FlameKingSensorDescription(
        key="gross_weight",
        translation_key="gross_weight",
        native_unit_of_measurement=UnitOfMass.POUNDS,
        device_class=SensorDeviceClass.WEIGHT,
        icon=None,
        value_fn=lambda entity: entity.tank_state.gross_weight_lb
        if entity.tank_state
        else None,
    ),
    FlameKingSensorDescription(
        key="propane_weight",
        translation_key="propane_weight",
        native_unit_of_measurement=UnitOfMass.POUNDS,
        device_class=SensorDeviceClass.WEIGHT,
        icon="mdi:propane-tank",
        value_fn=lambda entity: entity.tank_state.propane_weight_lb
        if entity.tank_state
        else None,
    ),
    FlameKingSensorDescription(
        key="propane_percent",
        translation_key="propane_percent",
        native_unit_of_measurement=PERCENTAGE,
        device_class=None,
        icon="mdi:propane-tank-outline",
        value_fn=lambda entity: entity.tank_state.propane_percent
        if entity.tank_state
        else None,
    ),
    FlameKingSensorDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        icon=None,
        value_fn=lambda entity: entity.manager.packet.battery
        if entity.manager.packet
        else None,
    ),
    FlameKingSensorDescription(
        key="raw",
        translation_key="raw",
        native_unit_of_measurement=None,
        device_class=None,
        icon="mdi:scale",
        value_fn=lambda entity: entity.manager.packet.raw
        if entity.manager.packet
        else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FlameKingBluetoothManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    async_add_entities(
        FlameKingSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    )


class FlameKingSensor(SensorEntity):
    """A sensor backed by Flame King Bluetooth notifications."""

    entity_description: FlameKingSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[FlameKingBluetoothManager],
        description: FlameKingSensorDescription,
    ) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.manager = entry.runtime_data
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_icon = description.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or self.manager.address)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        """Return whether the scale has an active connection and valid packet."""
        return self.manager.available and self.manager.packet is not None

    @property
    def tank_state(self) -> TankState | None:
        """Calculate tank measurements using current options."""
        if self.manager.packet is None:
            return None
        options: dict[str, Any] = {**DEFAULT_OPTIONS, **self.entry.options}
        return calculate_tank_state(
            self.manager.packet.raw,
            raw_zero=int(options[CONF_RAW_ZERO]),
            raw_reference=int(options[CONF_RAW_REFERENCE]),
            reference_weight_lb=float(options[CONF_REFERENCE_WEIGHT]),
            tare_weight_lb=float(options[CONF_TARE_WEIGHT]),
            capacity_lb=float(options[CONF_CAPACITY]),
        )

    @property
    def native_value(self) -> int | float | None:
        """Return the sensor value."""
        value = self.entity_description.value_fn(self)
        return round(value, 2) if isinstance(value, float) else value

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
