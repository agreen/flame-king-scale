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


# --- control surface and housekeeping ---------------------------------------


async def test_listeners_are_notified_and_removable(manager) -> None:
    calls: list[int] = []
    remove = manager.async_add_listener(lambda: calls.append(1))
    manager.async_notify_listeners()
    assert calls == [1]
    assert manager._poll_requested.is_set()  # config changes request a poll
    remove()
    manager.async_notify_listeners()
    assert calls == [1]


async def test_long_use_requires_flowing_and_duration(manager) -> None:
    from custom_components.flame_king_scale.usage import UsageState

    manager._usage._state = UsageState(True, 1.0, 5.0, 130.0)
    assert manager.long_use
    manager._usage._state = UsageState(True, 1.0, 5.0, 10.0)
    assert not manager.long_use
    manager._usage._state = UsageState(False, None, None, 500.0)
    assert not manager.long_use


async def test_trigger_poll_is_ignored_during_a_session(manager) -> None:
    manager._session_active = True
    manager.async_trigger_poll()
    assert not manager._poll_requested.is_set()
    manager._session_active = False
    manager.async_trigger_poll()
    assert manager._poll_requested.is_set()


async def deliver_later(manager, raw: int, delay: float = 0.02) -> None:
    await asyncio.sleep(delay)
    manager._notification_handler(None, bytearray(packet(raw)))


async def test_refresh_once_and_live_requests(manager) -> None:
    task = asyncio.create_task(deliver_later(manager, 111))
    result = await manager.async_request_refresh(timeout=1)
    await task
    assert result.raw == 111

    task = asyncio.create_task(deliver_later(manager, 222))
    result = await manager.async_request_once(timeout=1)
    await task
    assert result.raw == 222
    assert manager._one_shot_requested

    task = asyncio.create_task(deliver_later(manager, 333))
    result = await manager.async_start_live_monitoring(timeout=1)
    await task
    assert result.raw == 333
    assert manager._live_monitor_requested.is_set()


async def test_request_times_out_without_a_packet(manager) -> None:
    assert await manager.async_request_refresh(timeout=0.05) is None


async def test_one_shot_not_flagged_during_active_session(manager) -> None:
    manager._session_active = True
    await manager.async_request_once(timeout=0.01)
    assert not manager._one_shot_requested


async def test_disconnect_callback_marks_unavailable(manager) -> None:
    manager.available = True
    manager._disconnected_callback(None)
    assert not manager.available
    assert manager._disconnected.is_set()


async def test_usage_update_ignores_missing_packet(manager) -> None:
    manager.packet = None
    manager._update_usage()  # must not raise
    assert not manager.usage.flowing


async def test_wait_for_next_poll_wakes_on_request_or_stop(manager) -> None:
    manager.async_trigger_poll()
    assert await manager._async_wait_for_next_poll() is True

    manager._poll_requested.clear()
    manager._stop.set()
    assert await manager._async_wait_for_next_poll() is False


async def test_wait_for_next_poll_times_out(hass: HomeAssistant, manager) -> None:
    hass.config_entries.async_update_entry(
        manager._entry, options={"poll_interval_minutes": 0.0005}
    )
    assert await manager._async_wait_for_next_poll() is True


async def test_connection_loop_polls_until_stopped(manager) -> None:
    sessions = 0

    async def fake_session() -> None:
        nonlocal sessions
        sessions += 1
        if sessions == 2:
            manager._stop.set()

    manager._async_poll_session = fake_session
    manager._async_wait_for_next_poll = lambda: asyncio.sleep(0, result=True)
    await manager._connection_loop()
    assert sessions == 2


async def test_connection_loop_exits_when_wait_says_stop(manager) -> None:
    sessions = 0

    async def fake_session() -> None:
        nonlocal sessions
        sessions += 1

    manager._async_poll_session = fake_session
    manager._async_wait_for_next_poll = lambda: asyncio.sleep(0, result=False)
    await manager._connection_loop()
    assert sessions == 1  # the first session runs before any waiting


async def test_start_and_stop_manage_the_background_task(manager) -> None:
    started = asyncio.Event()

    async def idle_loop() -> None:
        started.set()
        await asyncio.Event().wait()

    manager._connection_loop = idle_loop
    await manager.async_start()
    await manager.async_start()  # second start is a no-op
    await asyncio.wait_for(started.wait(), 1)
    assert manager._task is not None

    client = FakeClient([])
    manager._client = client
    await manager.async_stop()
    assert manager._task is None
    assert client.disconnected
