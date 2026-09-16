"""Config flow for the Flame King Propane Scale integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig

from .const import (
    CONF_ADDRESS,
    CONF_CAPACITY,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
    DEVICE_NAME,
    DOMAIN,
)


class FlameKingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Flame King config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._address: str | None = None
        self._name = DEVICE_NAME

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or DEVICE_NAME
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovered device setup."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address},
                options=DEFAULT_OPTIONS,
            )
        return self.async_show_form(step_id="confirm")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow setup by Bluetooth address when discovery is unavailable."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEVICE_NAME),
                data={CONF_ADDRESS: address},
                options=DEFAULT_OPTIONS,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default=DEVICE_NAME): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

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
