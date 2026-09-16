"""Config flow for the Flame King Propane Scale integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_ADDRESS,
    CONF_CAPACITY,
    CONF_DEVICE,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
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
        """Confirm discovered device setup."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address},
                options=DEFAULT_OPTIONS,
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
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
        return FlameKingOptionsFlow(config_entry)


class FlameKingOptionsFlow(OptionsFlow):
    """Configure scale calibration and tank properties."""

    def __init__(self, config_entry: Any) -> None:
        """Initialize options."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_RAW_ZERO] == user_input[CONF_RAW_REFERENCE]:
                errors["base"] = "same_calibration_points"
            else:
                return self.async_create_entry(title="", data=user_input)

        current = {**DEFAULT_OPTIONS, **self._config_entry.options}
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
                vol.Required(
                    CONF_TARE_WEIGHT, default=current[CONF_TARE_WEIGHT]
                ): positive,
                vol.Required(CONF_CAPACITY, default=current[CONF_CAPACITY]): positive,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
