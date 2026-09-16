"""Shared entity helpers for the Flame King scale."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .bluetooth import FlameKingBluetoothManager
from .const import CONF_SUGGESTED_AREA, DOMAIN, MANUFACTURER, MODEL


def scale_device_info(
    entry: ConfigEntry[FlameKingBluetoothManager],
) -> DeviceInfo:
    """Return the common device registry description."""
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.runtime_data.address)},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model=MODEL,
    )
    if suggested_area := entry.data.get(CONF_SUGGESTED_AREA):
        info["suggested_area"] = suggested_area
    return info
