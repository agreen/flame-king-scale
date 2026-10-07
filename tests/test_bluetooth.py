"""Tests for the Bluetooth session manager using a fake BLE client."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale import bluetooth as bt
from custom_components.flame_king_scale.const import (
    CHARACTERISTIC_UUID,
    DOMAIN,
    SERVICE_UUID,
)


def packet(raw: int, battery: int = 100) -> bytes:
    body = bytes([0xAA, 0x01, raw & 0xFF, raw >> 8, battery])
    checksum = 0
    for value in body:
        checksum ^= value
    return body + bytes([checksum])


class FakeServices:
    def __init__(self, present: bool) -> None:
        self.present = present

    def get_service(self, uuid: str):
        return object() if self.present and uuid == SERVICE_UUID else None

    def get_characteristic(self, uuid: str):
        return object() if self.present and uuid == CHARACTERISTIC_UUID else None


class FakeClient:
    """Delivers scripted packets as soon as notifications start."""

    def __init__(self, packets: list[bytes], *, services: bool = True) -> None:
        self.packets = packets
        self.services = FakeServices(services)
        self.is_connected = True
        self.disconnected = False
        self.handler = None

    async def start_notify(self, _characteristic, handler) -> None:
        self.handler = handler
        for data in self.packets:
            handler(None, bytearray(data))

    async def disconnect(self) -> None:
        self.is_connected = False
        self.disconnected = True


@pytest.fixture
def manager(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bt, "_FIRST_PACKET_TIMEOUT", 0.2)
    monkeypatch.setattr(bt, "_QUIET_SAMPLE_SECONDS", 0.1)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        data={"address": "AA:BB:CC:DD:EE:FF"},
        options={"stability_time_minutes": 0.002},
    )
    entry.add_to_hass(hass)
    return bt.FlameKingBluetoothManager(hass, entry)


def patch_connection(client: FakeClient | None):
    """Patch the BLE device lookup and connection helper."""

    async def establish(*_args, **_kwargs):
        return client

    return (
        patch.object(
            bt,
            "async_ble_device_from_address",
            return_value=None if client is None else SimpleNamespace(),
        ),
        patch.object(bt, "establish_connection", side_effect=establish),
    )


async def test_one_shot_reads_and_disconnects(manager) -> None:
    client = FakeClient([packet(2106, 87)])
    lookup, connect = patch_connection(client)
    manager._one_shot_requested = True
    with lookup, connect:
        await manager._async_poll_session()

    assert manager.packet is not None
    assert (manager.packet.raw, manager.packet.battery) == (2106, 87)
    assert client.disconnected
    assert manager.consecutive_failures == 0


async def test_unchanged_weight_disconnects_after_quiet_sample(manager) -> None:
    client = FakeClient([packet(1000)])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_session()
    assert client.disconnected
    assert manager._last_session_raw == 1000


async def test_change_during_quiet_sample_keeps_streaming(manager) -> None:
    client = FakeClient([packet(1000)])
    lookup, connect = patch_connection(client)

    async def jolt() -> None:
        await asyncio.sleep(0.03)
        client.handler(None, bytearray(packet(5000)))

    with lookup, connect:
        task = asyncio.create_task(jolt())
        await manager._async_poll_session()
        await task

    assert manager.packet.raw == 5000
    assert client.disconnected
    assert manager._last_session_raw == 5000


async def test_invalid_packets_are_ignored(manager) -> None:
    client = FakeClient([b"\x00\x01", packet(500)])
    lookup, connect = patch_connection(client)
    manager._one_shot_requested = True
    with lookup, connect:
        await manager._async_poll_session()
    assert manager.packet.raw == 500


async def test_unreachable_scale_logs_once_then_recovers(
    manager, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=bt.__name__)
    lookup, connect = patch_connection(None)
    with lookup, connect:
        await manager._async_poll_session()
        await manager._async_poll_session()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "not currently visible" in warnings[0].getMessage()
    assert manager.consecutive_failures == 2
    assert manager.last_error

    caplog.clear()
    client = FakeClient([packet(700)])
    lookup, connect = patch_connection(client)
    manager._one_shot_requested = True
    with lookup, connect:
        await manager._async_poll_session()
    assert manager.consecutive_failures == 0
    assert manager.last_error is None
    assert any("restored" in r.getMessage() for r in caplog.records)


async def test_missing_gatt_fingerprint_is_reported(
    manager, caplog: pytest.LogCaptureFixture
) -> None:
    client = FakeClient([packet(1)], services=False)
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_session()
    assert manager.packet is None
    assert "FFE0/FFE4" in (manager.last_error or "")
    assert client.disconnected


async def test_silent_scale_times_out(manager) -> None:
    client = FakeClient([])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_session()
    assert "no valid packet" in (manager.last_error or "")
    assert client.disconnected
