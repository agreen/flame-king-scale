"""Config flow for the Flame King Propane Scale integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import (
    CONF_ADDRESS,
    CONF_AREA_ID,
    CONF_CAPACITY,
    CONF_DEVICE,
    CONF_FAST_POLL,
    CONF_FLOW_DETECTION_TIME,
    CONF_FLOW_MIN_RATE,
    CONF_LONG_USE_TIME,
    CONF_POLL_INTERVAL,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_STABILITY_TIME,
    CONF_STABILITY_VARIANCE,
    CONF_SUGGESTED_AREA,
    CONF_TARE_WEIGHT,
    CONF_WEIGHT_UNIT,
    DEFAULT_OPTIONS,
    DEVICE_NAME,
    DOMAIN,
    SERVICE_UUID,
    TANK_CAPACITY_OPTIONS,
    default_tare_for_capacity,
)
from .discovery import is_flame_king_candidate
from .protocol import calibration_from_loaded_points
from .units import (
    UNIT_KG,
    WEIGHT_UNIT_CHOICES,
    format_tank_size,
    format_weight,
    lb_to_unit,
    resolve_weight_unit,
    unit_to_lb,
)


def _tank_size_selector() -> SelectSelector:
    """Return the tank-size dropdown; custom sizes are entered in pounds."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=f"{value:g}", label=format_tank_size(value))
                for value in TANK_CAPACITY_OPTIONS
            ],
            custom_value=True,
        )
    )


def _weight_selector(unit: str, *, step: float = 0.01) -> NumberSelector:
    """Return a weight input in the user's unit (stored in pounds)."""
    return NumberSelector(
        NumberSelectorConfig(
            min=round(lb_to_unit(0.01, unit), 3),
            max=round(lb_to_unit(500, unit), 1),
            step=step,
            unit_of_measurement=unit,
        )
    )


class FlameKingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Flame King config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._address: str | None = None
        self._name = DEVICE_NAME
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}
        self._pending_data: dict[str, Any] | None = None
        self._pending_capacity: float | None = None

    @property
    def _unit(self) -> str:
        """Return the weight unit implied by the system unit setting."""
        return resolve_weight_unit(
            str(DEFAULT_OPTIONS[CONF_WEIGHT_UNIT]),
            is_metric=self.hass.config.units is METRIC_SYSTEM,
        )

    async def _async_set_discovered_device(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Store a discovered candidate and continue to confirmation."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or DEVICE_NAME
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        if not is_flame_king_candidate(
            discovery_info.name,
            discovery_info.service_uuids,
            device_name=DEVICE_NAME,
            service_uuid=SERVICE_UUID,
        ):
            return self.async_abort(reason="not_supported")
        return await self._async_set_discovered_device(discovery_info)

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the discovered device and its tank."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            if not name:
                errors[CONF_NAME] = "invalid_name"
            else:
                data = {CONF_ADDRESS: self._address}
                if area_id := user_input.get(CONF_AREA_ID):
                    area = ar.async_get(self.hass).async_get_area(area_id)
                    if area is None:
                        errors[CONF_AREA_ID] = "invalid_area"
                    else:
                        data[CONF_SUGGESTED_AREA] = area.name
                if not errors:
                    self._name = name
                    self._pending_data = data
                    self._pending_capacity = float(user_input[CONF_CAPACITY])
                    return await self.async_step_tare_override()
        tank_size = _tank_size_selector()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self._name): TextSelector(),
                    vol.Optional(CONF_AREA_ID): AreaSelector(),
                    vol.Required(
                        CONF_CAPACITY,
                        default=f"{DEFAULT_OPTIONS[CONF_CAPACITY]:g}",
                    ): tank_size,
                }
            ),
            errors=errors,
            description_placeholders={"name": self._name},
        )

    async def async_step_tare_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer an optional stamped tare override after tank-size selection."""
        if self._pending_data is None or self._pending_capacity is None:
            return await self.async_step_user()

        preset = default_tare_for_capacity(self._pending_capacity)
        if user_input is not None:
            tare = (
                unit_to_lb(float(user_input[CONF_TARE_WEIGHT]), self._unit)
                if CONF_TARE_WEIGHT in user_input
                else preset
            )
            options = {
                **DEFAULT_OPTIONS,
                CONF_TARE_WEIGHT: round(tare, 4),
                CONF_CAPACITY: self._pending_capacity,
            }
            return self.async_create_entry(
                title=self._name,
                data=self._pending_data,
                options=options,
            )

        return self.async_show_form(
            step_id="tare_override",
            data_schema=vol.Schema(
                {vol.Optional(CONF_TARE_WEIGHT): _weight_selector(self._unit)}
            ),
            description_placeholders={
                "size": format_tank_size(self._pending_capacity),
                "tare": format_weight(preset, self._unit),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer recently seen scales without asking for an address."""
        if user_input is not None and CONF_DEVICE in user_input:
            return await self._async_set_discovered_device(
                self._discovered[user_input[CONF_DEVICE]]
            )

        configured = {
            entry.unique_id
            for entry in self._async_current_entries()
            if entry.unique_id
        }
        candidates = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(
                self.hass, connectable=True
            )
            if info.address not in configured
            and is_flame_king_candidate(
                info.name,
                info.service_uuids,
                device_name=DEVICE_NAME,
                service_uuid=SERVICE_UUID,
            )
        }
        self._discovered = candidates

        if not candidates:
            return self.async_show_form(
                step_id="user", errors={"base": "no_devices_found"}
            )

        if len(candidates) == 1:
            return await self._async_set_discovered_device(
                next(iter(candidates.values()))
            )

        options = [
            SelectOptionDict(
                value=address,
                label=f"{info.name or DEVICE_NAME} ({address})",
            )
            for address, info in sorted(candidates.items())
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Return the options flow."""
        return FlameKingOptionsFlow()


class FlameKingOptionsFlow(OptionsFlow):
    """Configure scale calibration and tank properties."""

    def __init__(self) -> None:
        """Initialize the guided calibration state."""
        self._captured_unloaded_raw: int | None = None
        self._first_calibration_raw: int | None = None
        self._first_calibration_weight: float | None = None
        self._pending_tank_options: dict[str, Any] | None = None
        self._pending_tare_override: float | None = None

    @property
    def _unit(self) -> str:
        """Return the weight unit for the saved preference."""
        return resolve_weight_unit(
            str(self._current_options()[CONF_WEIGHT_UNIT]),
            is_metric=self.hass.config.units is METRIC_SYSTEM,
        )

    def _current_options(self) -> dict[str, Any]:
        """Return a complete mutable copy of the current options."""
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    def _live_raw(self) -> int | None:
        """Return the current live raw reading when the scale is connected."""
        manager = self.config_entry.runtime_data
        if not manager.available or manager.packet is None:
            return None
        return int(manager.packet.raw)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the scale configuration menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "tank",
                "calibrate",
                "reset_calibration",
                "power",
                "advanced",
            ],
        )

    async def async_step_reset_calibration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reset only the load-cell conversion to Flame King factory values."""
        if user_input is not None:
            current = self._current_options()
            for key in (CONF_RAW_ZERO, CONF_RAW_REFERENCE, CONF_REFERENCE_WEIGHT):
                current[key] = DEFAULT_OPTIONS[key]
            return self.async_create_entry(title="", data=current)

        return self.async_show_form(
            step_id="reset_calibration",
            data_schema=vol.Schema({}),
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure adaptive polling and stability behavior."""
        current = self._current_options()
        unit = self._unit
        if user_input is not None:
            user_input[CONF_FLOW_MIN_RATE] = round(
                unit_to_lb(float(user_input[CONF_FLOW_MIN_RATE]), unit), 4
            )
            current.update(user_input)
            return self.async_create_entry(title="", data=current)

        return self.async_show_form(
            step_id="power",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL, default=current[CONF_POLL_INTERVAL]
                    ): NumberSelector(NumberSelectorConfig(min=5, max=1440, step=5)),
                    vol.Required(
                        CONF_FAST_POLL, default=current[CONF_FAST_POLL]
                    ): NumberSelector(NumberSelectorConfig(min=15, max=600, step=5)),
                    vol.Required(
                        CONF_STABILITY_TIME, default=current[CONF_STABILITY_TIME]
                    ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1)),
                    vol.Required(
                        CONF_STABILITY_VARIANCE,
                        default=current[CONF_STABILITY_VARIANCE],
                    ): NumberSelector(NumberSelectorConfig(min=0.1, max=10, step=0.1)),
                    vol.Required(
                        CONF_FLOW_DETECTION_TIME,
                        default=current[CONF_FLOW_DETECTION_TIME],
                    ): NumberSelector(NumberSelectorConfig(min=15, max=600, step=15)),
                    vol.Required(
                        CONF_FLOW_MIN_RATE,
                        default=round(
                            lb_to_unit(float(current[CONF_FLOW_MIN_RATE]), unit), 2
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=round(lb_to_unit(0.1, unit), 2),
                            max=round(lb_to_unit(20, unit), 1),
                            step=0.05 if unit == UNIT_KG else 0.1,
                            unit_of_measurement=f"{unit}/h",
                        )
                    ),
                    vol.Required(
                        CONF_LONG_USE_TIME, default=current[CONF_LONG_USE_TIME]
                    ): NumberSelector(NumberSelectorConfig(min=5, max=1440, step=5)),
                }
            ),
        )

    async def async_step_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the cylinder's rated propane capacity."""
        current = self._current_options()
        if user_input is not None:
            old_capacity = float(current[CONF_CAPACITY])
            old_preset = default_tare_for_capacity(old_capacity)
            current_tare = float(current[CONF_TARE_WEIGHT])
            self._pending_tare_override = (
                current_tare if abs(current_tare - old_preset) > 0.001 else None
            )
            current[CONF_CAPACITY] = float(user_input[CONF_CAPACITY])
            current[CONF_WEIGHT_UNIT] = user_input[CONF_WEIGHT_UNIT]
            self._pending_tank_options = current
            return await self.async_step_tank_tare_override()

        tank_size = _tank_size_selector()
        return self.async_show_form(
            step_id="tank",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CAPACITY, default=f"{float(current[CONF_CAPACITY]):g}"
                    ): tank_size,
                    vol.Required(
                        CONF_WEIGHT_UNIT, default=str(current[CONF_WEIGHT_UNIT])
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(WEIGHT_UNIT_CHOICES),
                            translation_key="weight_unit",
                        )
                    ),
                }
            ),
        )

    async def async_step_tank_tare_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer an optional stamped tare override for the selected tank size."""
        if self._pending_tank_options is None:
            return await self.async_step_tank()

        capacity = float(self._pending_tank_options[CONF_CAPACITY])
        preset = default_tare_for_capacity(capacity)
        if user_input is not None:
            tare = (
                unit_to_lb(float(user_input[CONF_TARE_WEIGHT]), self._unit)
                if CONF_TARE_WEIGHT in user_input
                else preset
            )
            self._pending_tank_options[CONF_TARE_WEIGHT] = round(tare, 4)
            return self.async_create_entry(title="", data=self._pending_tank_options)

        field = vol.Optional(CONF_TARE_WEIGHT)
        if self._pending_tare_override is not None:
            field = vol.Optional(
                CONF_TARE_WEIGHT,
                default=round(lb_to_unit(self._pending_tare_override, self._unit), 2),
            )
        return self.async_show_form(
            step_id="tank_tare_override",
            data_schema=vol.Schema({field: _weight_selector(self._unit)}),
            description_placeholders={
                "size": format_tank_size(capacity),
                "tare": format_weight(preset, self._unit),
            },
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture the unloaded sentinel without using it as a loaded point."""
        manager = self.config_entry.runtime_data
        manager.async_trigger_poll()
        errors: dict[str, str] = {}
        if user_input is not None:
            packet = await manager.async_request_refresh()
            if packet is None:
                errors["base"] = "no_live_reading"
            else:
                self._captured_unloaded_raw = packet.raw
                return self.async_show_menu(
                    step_id="calibration_reference",
                    menu_options=["calibrate_empty_tank", "calibrate_known_weight"],
                )

        live_raw = self._live_raw()
        return self.async_show_form(
            step_id="calibrate",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "raw": str(live_raw) if live_raw is not None else "unavailable"
            },
        )

    async def async_step_calibrate_empty_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture the first loaded point using the configured empty cylinder."""
        return await self._async_capture_first_loaded_point(user_input)

    async def async_step_calibrate_known_weight(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture the first loaded point using a user-supplied known weight."""
        return await self._async_capture_first_loaded_point(
            user_input, request_weight=True
        )

    async def _async_capture_first_loaded_point(
        self,
        user_input: dict[str, Any] | None,
        *,
        request_weight: bool = False,
    ) -> ConfigFlowResult:
        """Capture the first of two non-zero calibration loads."""
        if self._captured_unloaded_raw is None:
            return await self.async_step_calibrate()

        current = self._current_options()
        manager = self.config_entry.runtime_data
        manager.async_trigger_poll()
        errors: dict[str, str] = {}
        reference_weight = float(current[CONF_TARE_WEIGHT])
        if request_weight and user_input is not None:
            reference_weight = unit_to_lb(
                float(user_input[CONF_REFERENCE_WEIGHT]), self._unit
            )

        if user_input is not None:
            packet = await manager.async_request_refresh()
            if packet is None:
                errors["base"] = "no_live_reading"
            elif packet.raw <= self._captured_unloaded_raw:
                errors["base"] = "load_not_detected"
            else:
                self._first_calibration_raw = packet.raw
                self._first_calibration_weight = reference_weight
                return await self.async_step_calibrate_second_load()

        schema: dict[Any, Any] = {}
        if request_weight:
            schema[vol.Required(CONF_REFERENCE_WEIGHT)] = _weight_selector(
                self._unit, step=0.1
            )

        live_raw = self._live_raw()
        step_id = "calibrate_known_weight" if request_weight else "calibrate_empty_tank"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "raw": str(live_raw) if live_raw is not None else "unavailable",
                "tare": format_weight(reference_weight, self._unit),
            },
        )

    async def async_step_calibrate_second_load(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture a second known load and fit the loaded measurement line."""
        if (
            self._first_calibration_raw is None
            or self._first_calibration_weight is None
        ):
            return await self.async_step_calibrate()

        manager = self.config_entry.runtime_data
        manager.async_trigger_poll()
        errors: dict[str, str] = {}
        if user_input is not None:
            packet = await manager.async_request_refresh()
            if packet is None:
                errors["base"] = "no_live_reading"
            else:
                try:
                    raw_zero, raw_reference, reference_weight = (
                        calibration_from_loaded_points(
                            self._first_calibration_raw,
                            self._first_calibration_weight,
                            packet.raw,
                            unit_to_lb(
                                float(user_input[CONF_REFERENCE_WEIGHT]), self._unit
                            ),
                        )
                    )
                except ValueError:
                    errors["base"] = "invalid_loaded_points"
                else:
                    current = self._current_options()
                    current.update(
                        {
                            CONF_RAW_ZERO: raw_zero,
                            CONF_RAW_REFERENCE: raw_reference,
                            CONF_REFERENCE_WEIGHT: reference_weight,
                        }
                    )
                    return self.async_create_entry(title="", data=current)

        live_raw = self._live_raw()
        return self.async_show_form(
            step_id="calibrate_second_load",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REFERENCE_WEIGHT): _weight_selector(
                        self._unit, step=0.1
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "first_weight": format_weight(
                    self._first_calibration_weight, self._unit
                ),
                "first_raw": str(self._first_calibration_raw),
                "raw": str(live_raw) if live_raw is not None else "unavailable",
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manually configure calibration values for diagnostics."""
        errors: dict[str, str] = {}
        current = self._current_options()
        if user_input is not None:
            if user_input[CONF_RAW_ZERO] == user_input[CONF_RAW_REFERENCE]:
                errors["base"] = "same_calibration_points"
            else:
                current.update(user_input)
                return self.async_create_entry(title="", data=current)

        positive = NumberSelector(NumberSelectorConfig(min=0.01, max=500, step=0.01))
        raw = NumberSelector(NumberSelectorConfig(min=-65535, max=65535, step=1))
        schema = vol.Schema(
            {
                vol.Required(CONF_RAW_ZERO, default=current[CONF_RAW_ZERO]): raw,
                vol.Required(
                    CONF_RAW_REFERENCE, default=current[CONF_RAW_REFERENCE]
                ): raw,
                vol.Required(
                    CONF_REFERENCE_WEIGHT, default=current[CONF_REFERENCE_WEIGHT]
                ): positive,
            }
        )
        return self.async_show_form(
            step_id="advanced", data_schema=schema, errors=errors
        )
