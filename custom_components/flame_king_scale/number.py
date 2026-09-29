"""Configuration number entities for the Flame King Propane Scale."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bluetooth import FlameKingBluetoothManager
from .const import (
    CONF_FLOW_DETECTION_TIME,
    CONF_FLOW_MIN_RATE,
    CONF_LONG_USE_TIME,
    CONF_POLL_INTERVAL,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_STABILITY_TIME,
    CONF_STABILITY_VARIANCE,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
)
from .entity import scale_device_info


@dataclass(frozen=True, kw_only=True)
class FlameKingNumberDescription(NumberEntityDescription):
    """Describe a Flame King configuration number."""

    option_key: str


NUMBER_DESCRIPTIONS = (
    FlameKingNumberDescription(
        key="tare_weight",
        translation_key="tare_weight",
        option_key=CONF_TARE_WEIGHT,
        native_min_value=0.01,
        native_max_value=500,
        native_step=0.01,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        icon="mdi:weight",
    ),
    FlameKingNumberDescription(
        key="poll_interval",
        translation_key="poll_interval",
        option_key=CONF_POLL_INTERVAL,
        native_min_value=5,
        native_max_value=1440,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-sync-outline",
    ),
    FlameKingNumberDescription(
        key="stability_time",
        translation_key="stability_time",
        option_key=CONF_STABILITY_TIME,
        native_min_value=1,
        native_max_value=30,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-sand-complete",
    ),
    FlameKingNumberDescription(
        key="stability_variance",
        translation_key="stability_variance",
        option_key=CONF_STABILITY_VARIANCE,
        native_min_value=0.1,
        native_max_value=10,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:approximately-equal",
    ),
    FlameKingNumberDescription(
        key="flow_detection_time",
        translation_key="flow_detection_time",
        option_key=CONF_FLOW_DETECTION_TIME,
        native_min_value=15,
        native_max_value=600,
        native_step=15,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:chart-timeline-variant",
    ),
    FlameKingNumberDescription(
        key="minimum_flow_rate",
        translation_key="minimum_flow_rate",
        option_key=CONF_FLOW_MIN_RATE,
        native_min_value=0.1,
        native_max_value=20,
        native_step=0.1,
        native_unit_of_measurement="lb/h",
        icon="mdi:fire-alert",
    ),
    FlameKingNumberDescription(
        key="long_use_time",
        translation_key="long_use_time",
        option_key=CONF_LONG_USE_TIME,
        native_min_value=5,
        native_max_value=1440,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-alert-outline",
    ),
    FlameKingNumberDescription(
        key="reference_weight",
        translation_key="reference_weight",
        option_key=CONF_REFERENCE_WEIGHT,
        native_min_value=0.01,
        native_max_value=500,
        native_step=0.01,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        icon="mdi:weight-kilogram",
        entity_registry_enabled_default=False,
    ),
    FlameKingNumberDescription(
        key="raw_zero",
        translation_key="raw_zero",
        option_key=CONF_RAW_ZERO,
        native_min_value=0,
        native_max_value=65535,
        native_step=1,
        icon="mdi:ray-start-arrow",
        entity_registry_enabled_default=False,
    ),
    FlameKingNumberDescription(
        key="raw_reference",
        translation_key="raw_reference",
        option_key=CONF_RAW_REFERENCE,
        native_min_value=0,
        native_max_value=65535,
        native_step=1,
        icon="mdi:ray-end-arrow",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[FlameKingBluetoothManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up configuration number entities."""
    async_add_entities(
        FlameKingNumber(entry, description) for description in NUMBER_DESCRIPTIONS
    )


class FlameKingNumber(NumberEntity):
    """A writable scale or tank configuration value."""

    entity_description: FlameKingNumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry[FlameKingBluetoothManager],
        description: FlameKingNumberDescription,
    ) -> None:
        """Initialize a configuration number."""
        self.entry = entry
        self.manager = entry.runtime_data
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = scale_device_info(entry)

    @property
    def native_value(self) -> float:
        """Return the configured value."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        return float(options[self.entity_description.option_key])

    async def async_set_native_value(self, value: float) -> None:
        """Persist a new configuration value."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        option_key = self.entity_description.option_key
        new_value: float | int = value
        if option_key in (CONF_RAW_ZERO, CONF_RAW_REFERENCE):
            new_value = round(value)
            other_key = (
                CONF_RAW_REFERENCE if option_key == CONF_RAW_ZERO else CONF_RAW_ZERO
            )
            if new_value == options[other_key]:
                raise HomeAssistantError(
                    "Raw zero and raw reference must be different"
                )
        options[option_key] = new_value
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def async_added_to_hass(self) -> None:
        """Subscribe to configuration updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
