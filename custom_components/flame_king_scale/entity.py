"""Shared entity helpers for the Flame King scale."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util.unit_system import METRIC_SYSTEM

from .bluetooth import FlameKingBluetoothManager
from .const import (
    CONF_SUGGESTED_AREA,
    CONF_WEIGHT_UNIT,
    DEFAULT_OPTIONS,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .units import resolve_weight_unit


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


def weight_unit_for(
    hass: HomeAssistant, entry: ConfigEntry[FlameKingBluetoothManager]
) -> str:
    """Return ``"lb"`` or ``"kg"`` for an entry's display preference."""
    options = {**DEFAULT_OPTIONS, **entry.options}
    return resolve_weight_unit(
        str(options[CONF_WEIGHT_UNIT]), is_metric=hass.config.units is METRIC_SYSTEM
    )
