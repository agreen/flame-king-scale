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
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_ADDRESS,
    CONF_AREA_ID,
    CONF_CAPACITY,
    CONF_DEVICE,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_SUGGESTED_AREA,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
    DEVICE_NAME,
    DOMAIN,
    SERVICE_UUID,
)
from .discovery import is_flame_king_candidate


class FlameKingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Flame King config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._address: str | None = None
        self._name = DEVICE_NAME
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

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
                    options = {
                        **DEFAULT_OPTIONS,
                        CONF_TARE_WEIGHT: user_input[CONF_TARE_WEIGHT],
                        CONF_CAPACITY: user_input[CONF_CAPACITY],
                    }
                    return self.async_create_entry(
                        title=name,
                        data=data,
                        options=options,
                    )
        positive = NumberSelector(
            NumberSelectorConfig(min=0.01, max=500, step=0.01)
        )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self._name): TextSelector(),
                    vol.Optional(CONF_AREA_ID): AreaSelector(),
                    vol.Required(
                        CONF_TARE_WEIGHT,
                        default=DEFAULT_OPTIONS[CONF_TARE_WEIGHT],
                    ): positive,
                    vol.Required(
                        CONF_CAPACITY,
                        default=DEFAULT_OPTIONS[CONF_CAPACITY],
                    ): positive,
                }
            ),
            errors=errors,
            description_placeholders={"name": self._name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Actively scan for supported scales without asking for an address."""
        if user_input is not None and CONF_DEVICE in user_input:
            return await self._async_set_discovered_device(
                self._discovered[user_input[CONF_DEVICE]]
            )

        await bluetooth.async_request_active_scan(self.hass)
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
            {
                "value": address,
                "label": f"{info.name or DEVICE_NAME} ({address})",
            }
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
        self._captured_raw_zero: int | None = None

    def _current_options(self) -> dict[str, Any]:
        """Return a complete mutable copy of the current options."""
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    def _live_raw(self) -> int | None:
        """Return the current live raw reading when the scale is connected."""
        manager = self.config_entry.runtime_data
        if not manager.available or manager.packet is None:
            return None
        return manager.packet.raw

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the scale configuration menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["tank", "calibrate", "advanced"],
        )

    async def async_step_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure cylinder tare weight and propane capacity."""
        current = self._current_options()
        if user_input is not None:
            current.update(user_input)
            return self.async_create_entry(title="", data=current)

        positive = NumberSelector(NumberSelectorConfig(min=0.01, max=500, step=0.01))
        return self.async_show_form(
            step_id="tank",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TARE_WEIGHT, default=current[CONF_TARE_WEIGHT]
                    ): positive,
                    vol.Required(
                        CONF_CAPACITY, default=current[CONF_CAPACITY]
                    ): positive,
                }
            ),
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture the unloaded scale reading."""
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = self._live_raw()
            if raw is None:
                errors["base"] = "no_live_reading"
            else:
                self._captured_raw_zero = raw
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
        """Capture a reference reading using the configured empty cylinder."""
        return await self._async_capture_reference(user_input)

    async def async_step_calibrate_known_weight(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture a reference reading using a user-supplied known weight."""
        return await self._async_capture_reference(user_input, request_weight=True)

    async def _async_capture_reference(
        self,
        user_input: dict[str, Any] | None,
        *,
        request_weight: bool = False,
    ) -> ConfigFlowResult:
        """Capture and save the loaded calibration point."""
        if self._captured_raw_zero is None:
            return await self.async_step_calibrate()

        current = self._current_options()
        errors: dict[str, str] = {}
        reference_weight = float(current[CONF_TARE_WEIGHT])
        if request_weight and user_input is not None:
            reference_weight = float(user_input[CONF_REFERENCE_WEIGHT])

        if user_input is not None:
            raw_reference = self._live_raw()
            if raw_reference is None:
                errors["base"] = "no_live_reading"
            elif raw_reference == self._captured_raw_zero:
                errors["base"] = "same_calibration_points"
            else:
                current.update(
                    {
                        CONF_RAW_ZERO: self._captured_raw_zero,
                        CONF_RAW_REFERENCE: raw_reference,
                        CONF_REFERENCE_WEIGHT: reference_weight,
                    }
                )
                return self.async_create_entry(title="", data=current)

        schema: dict[Any, Any] = {}
        if request_weight:
            schema[vol.Required(CONF_REFERENCE_WEIGHT)] = NumberSelector(
                NumberSelectorConfig(min=0.01, max=500, step=0.01)
            )

        live_raw = self._live_raw()
        step_id = (
            "calibrate_known_weight" if request_weight else "calibrate_empty_tank"
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "raw": str(live_raw) if live_raw is not None else "unavailable",
                "tare": f"{reference_weight:.2f}",
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
        raw = NumberSelector(NumberSelectorConfig(min=0, max=65535, step=1))
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
