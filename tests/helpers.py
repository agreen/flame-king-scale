"""Shared test helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale.const import DEFAULT_OPTIONS, DOMAIN

# Factory calibration: raw 1600 is 6 kg, so raw 3136 is 12 kg = 26.455 lb gross.
RAW = 3136
GROSS_LB = 12 * 2.2046226218


def make_entry(hass: HomeAssistant, system, **options: Any) -> MockConfigEntry:
    hass.config.units = system
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        title="Grill",
        data={"address": "AA:BB:CC:DD:EE:FF"},
        options={**DEFAULT_OPTIONS, **options},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        packet=SimpleNamespace(raw=RAW, battery=77),
        usage=SimpleNamespace(
            flowing=True,
            rate_lb_per_hour=2.2046226218,
            estimated_hours_remaining=3.0,
            duration_minutes=12.0,
        ),
        long_use=False,
        available=True,
        poll_mode="fast",
        planner=SimpleNamespace(quiet_polls=2),
        consecutive_failures=0,
        last_error=None,
        async_request_once=AsyncMock(),
        async_start_live_monitoring=AsyncMock(),
        async_add_listener=lambda _listener: lambda: None,
    )
    return entry


async def entities(hass: HomeAssistant, entry, module) -> dict[str, Any]:
    found: list[Any] = []
    await module.async_setup_entry(hass, entry, found.extend)
    for entity in found:
        entity.hass = hass
    key = (
        (lambda e: e.entity_description.key)
        if hasattr(found[0], "entity_description")
        else (lambda e: type(e).__name__)
    )
    return {key(entity): entity for entity in found}
