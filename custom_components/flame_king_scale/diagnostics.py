"""Diagnostics for the Flame King Propane Scale integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .bluetooth import FlameKingBluetoothManager
from .const import CONF_ADDRESS

TO_REDACT = {CONF_ADDRESS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[FlameKingBluetoothManager]
) -> dict[str, Any]:
    """Return diagnostics with the Bluetooth address redacted."""
    manager = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "available": manager.available,
        "poll_mode": str(manager.poll_mode),
        "quiet_polls": manager.planner.quiet_polls,
        "consecutive_failures": manager.consecutive_failures,
        "last_error": manager.last_error,
        "packet": {
            "raw": manager.packet.raw,
            "battery": manager.packet.battery,
        }
        if manager.packet
        else None,
    }
