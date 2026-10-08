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
    DOMAIN,
)
from .entity import scale_device_info, weight_unit_for
from .units import UNIT_KG, lb_to_unit, unit_to_lb

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FlameKingNumberDescription(NumberEntityDescription):
    """Describe a Flame King configuration number."""

    option_key: str
    # "mass" (lb) and "rate" (lb/h) options are stored in pounds and shown in
    # the user's preferred unit.
    measure: str | None = None


NUMBER_DESCRIPTIONS = (
    FlameKingNumberDescription(
        key="tare_weight",
        translation_key="tare_weight",
        option_key=CONF_TARE_WEIGHT,
        measure="mass",
        native_min_value=0.01,
        native_max_value=500,
        native_step=0.01,
        native_unit_of_measurement=UnitOfMass.POUNDS,
    ),
    FlameKingNumberDescription(
        key="poll_interval",
        translation_key="poll_interval",
        option_key=CONF_POLL_INTERVAL,
        native_min_value=5,
        native_max_value=1440,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    FlameKingNumberDescription(
        key="stability_time",
        translation_key="stability_time",
        option_key=CONF_STABILITY_TIME,
        native_min_value=1,
        native_max_value=30,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    FlameKingNumberDescription(
        key="stability_variance",
        translation_key="stability_variance",
        option_key=CONF_STABILITY_VARIANCE,
        native_min_value=0.1,
        native_max_value=10,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
    ),
    FlameKingNumberDescription(
        key="flow_detection_time",
        translation_key="flow_detection_time",
        option_key=CONF_FLOW_DETECTION_TIME,
        native_min_value=15,
        native_max_value=600,
        native_step=15,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    FlameKingNumberDescription(
        key="minimum_flow_rate",
        translation_key="minimum_flow_rate",
        option_key=CONF_FLOW_MIN_RATE,
        measure="rate",
        native_min_value=0.1,
        native_max_value=20,
        native_step=0.1,
        native_unit_of_measurement="lb/h",
    ),
    FlameKingNumberDescription(
        key="long_use_time",
        translation_key="long_use_time",
        option_key=CONF_LONG_USE_TIME,
        native_min_value=5,
        native_max_value=1440,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    FlameKingNumberDescription(
        key="reference_weight",
        translation_key="reference_weight",
        option_key=CONF_REFERENCE_WEIGHT,
        measure="mass",
        native_min_value=0.01,
        native_max_value=500,
        native_step=0.01,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        entity_registry_enabled_default=False,
    ),
    FlameKingNumberDescription(
        key="raw_zero",
        translation_key="raw_zero",
        option_key=CONF_RAW_ZERO,
        native_min_value=-65535,
        native_max_value=65535,
        native_step=1,
        entity_registry_enabled_default=False,
    ),
    FlameKingNumberDescription(
        key="raw_reference",
        translation_key="raw_reference",
        option_key=CONF_RAW_REFERENCE,
        native_min_value=0,
        native_max_value=65535,
        native_step=1,
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
    def _weight_unit(self) -> str:
        return weight_unit_for(self.hass, self.entry)

    def _to_display(self, value_lb: float) -> float:
        if self.entity_description.measure:
            return lb_to_unit(value_lb, self._weight_unit)
        return value_lb

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, following the user's weight-unit preference."""
        match self.entity_description.measure:
            case "mass":
                return (
                    UnitOfMass.KILOGRAMS
                    if self._weight_unit == UNIT_KG
                    else UnitOfMass.POUNDS
                )
            case "rate":
                return "kg/h" if self._weight_unit == UNIT_KG else "lb/h"
        return self.entity_description.native_unit_of_measurement

    @property
    def native_min_value(self) -> float:
        """Return the minimum in the displayed unit."""
        return round(self._to_display(self.entity_description.native_min_value), 3)

    @property
    def native_max_value(self) -> float:
        """Return the maximum in the displayed unit."""
        return round(self._to_display(self.entity_description.native_max_value), 3)

    @property
    def native_value(self) -> float:
        """Return the configured value."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        value = float(options[self.entity_description.option_key])
        return round(self._to_display(value), 3)

    async def async_set_native_value(self, value: float) -> None:
        """Persist a new configuration value."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        option_key = self.entity_description.option_key
        new_value: float | int = value
        if self.entity_description.measure:
            new_value = round(unit_to_lb(value, self._weight_unit), 4)
        if option_key in (CONF_RAW_ZERO, CONF_RAW_REFERENCE):
            new_value = round(value)
            other_key = (
                CONF_RAW_REFERENCE if option_key == CONF_RAW_ZERO else CONF_RAW_ZERO
            )
            if new_value == options[other_key]:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="raw_points_equal",
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
