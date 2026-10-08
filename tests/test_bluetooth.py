"""Tests for the Bluetooth session manager using a fake BLE client."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flame_king_scale import bluetooth as bt
from custom_components.flame_king_scale.const import (
    CHARACTERISTIC_UUID,
    DOMAIN,
    SERVICE_UUID,
)
from custom_components.flame_king_scale.polling import PollMode


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
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        data={"address": "AA:BB:CC:DD:EE:FF"},
        options={},
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


class HangingClient(FakeClient):
    """Connects but never delivers a packet or finishes subscribing."""

    async def start_notify(self, _characteristic, handler) -> None:
        self.handler = handler
        await asyncio.Event().wait()


async def poll(manager, raw: int | None, *, observe: bool = False) -> None:
    """Run one poll against a fake scale reporting ``raw`` (None: not visible)."""
    client = None if raw is None else FakeClient([packet(raw)])
    lookup, connect = patch_connection(client)
    manager._observe_only = observe
    with lookup, connect:
        await manager._async_poll_once()


# --- one poll -----------------------------------------------------------------


async def test_poll_reads_a_packet_and_disconnects(manager) -> None:
    client = FakeClient([packet(2106, 87)])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_once()

    assert (manager.packet.raw, manager.packet.battery) == (2106, 87)
    assert client.disconnected
    assert manager.available
    assert manager.consecutive_failures == 0


async def test_invalid_packets_are_ignored(manager) -> None:
    client = FakeClient([b"\x00\x01", packet(500)])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_once()
    assert manager.packet.raw == 500


async def test_unreachable_scale_logs_once_then_recovers(
    manager, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=bt.__name__)
    await poll(manager, None)
    await poll(manager, None)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "not currently visible" in warnings[0].getMessage()
    assert manager.consecutive_failures == 2
    assert not manager.available

    caplog.clear()
    await poll(manager, 700)
    assert manager.consecutive_failures == 0
    assert manager.last_error is None
    assert manager.available
    assert any("restored" in r.getMessage() for r in caplog.records)


async def test_missing_gatt_fingerprint_is_reported(manager) -> None:
    client = FakeClient([packet(1)], services=False)
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_once()
    assert manager.packet is None
    assert "FFE0/FFE4" in (manager.last_error or "")
    assert client.disconnected


async def test_silent_scale_is_a_failure(manager) -> None:
    client = FakeClient([])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_once()
    assert "no valid packet" in (manager.last_error or "")
    assert client.disconnected


async def test_poll_has_a_hard_deadline(manager, monkeypatch) -> None:
    monkeypatch.setattr(bt, "POLL_TIMEOUT", 0.1)
    client = HangingClient([])
    lookup, connect = patch_connection(client)
    with lookup, connect:
        await manager._async_poll_once()
    assert "did not finish within" in (manager.last_error or "")
    assert client.disconnected
    assert not manager.available
    assert not manager._session_active


# --- idle and fast polling -------------------------------------------------------


async def test_first_reading_is_only_a_baseline(manager) -> None:
    await poll(manager, 1000)
    assert manager.poll_mode is PollMode.IDLE
    assert manager.planner.anchor_raw == 1000


async def test_scheduled_poll_that_sees_a_change_starts_fast_polling(manager) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000)
    assert manager.poll_mode is PollMode.FAST
    assert manager._next_interval() == 60  # the default active gap


async def test_quiet_polls_return_to_the_regular_interval(manager) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000)
    manager._usage.stop = MagicMock()
    # The default 5 minute window at a 60 s gap is 5 quiet polls.
    for _ in range(4):
        await poll(manager, 3000)
        assert manager.poll_mode is PollMode.FAST
    await poll(manager, 3000)  # the fifth quiet poll
    assert manager.poll_mode is PollMode.IDLE
    assert manager._next_interval() == 3600
    manager._usage.stop.assert_called_once()


async def test_failed_polls_do_not_count_as_quiet(manager) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000)
    await poll(manager, 3000)
    assert manager.planner.quiet_polls == 1
    await poll(manager, None)
    await poll(manager, None)
    assert manager.planner.quiet_polls == 1
    assert manager.planner.anchor_raw == 3000
    assert manager.poll_mode is PollMode.FAST


async def test_three_failures_in_a_row_end_fast_polling(manager) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000)
    for _ in range(3):
        assert manager.poll_mode is PollMode.FAST
        await poll(manager, None)
    assert manager.poll_mode is PollMode.IDLE


async def test_manual_reading_does_not_start_fast_polling_or_move_the_baseline(
    manager,
) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000, observe=True)  # Request reading sees a big change
    assert manager.packet.raw == 3000  # ... and shows it
    assert manager.poll_mode is PollMode.IDLE
    assert manager.planner.anchor_raw == 1000
    # The next scheduled poll still notices the change from the real baseline.
    await poll(manager, 3000)
    assert manager.poll_mode is PollMode.FAST


async def test_manual_failures_do_not_end_fast_polling(manager) -> None:
    await poll(manager, 1000)
    await poll(manager, 3000)
    for _ in range(5):
        await poll(manager, None, observe=True)
    assert manager.poll_mode is PollMode.FAST
    assert manager.consecutive_failures == 5  # still logged and diagnosed


async def test_live_monitoring_seeds_fast_polling_on_demand(manager) -> None:
    assert manager.poll_mode is PollMode.IDLE
    assert await manager.async_start_live_monitoring(timeout=0.05) is None
    assert manager.poll_mode is PollMode.FAST
    assert manager._poll_requested.is_set()
    assert not manager._observe_requested

    manager.planner.quiet_polls = 3
    await manager.async_start_live_monitoring(timeout=0.05)  # pressing again
    assert manager.planner.quiet_polls == 0


async def test_flow_window_spans_several_fast_polls(manager, hass) -> None:
    hass.config_entries.async_update_entry(
        manager._entry, options={"fast_poll_seconds": 120, "flow_detection_seconds": 60}
    )
    manager._usage.add_sample = MagicMock()
    await poll(manager, 1000)
    kwargs = manager._usage.add_sample.call_args.kwargs
    assert kwargs["detection_seconds"] == 360  # 3 fast polls, not the 60 s setting


# --- control surface and housekeeping ---------------------------------------


async def test_listeners_are_notified_and_removable(manager) -> None:
    calls: list[int] = []
    remove = manager.async_add_listener(lambda: calls.append(1))
    manager.async_notify_listeners()
    assert calls == [1]
    assert manager._wake.is_set()  # re-time the next poll, but do not connect
    assert not manager._poll_requested.is_set()
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


async def test_manual_refresh_requests_an_observe_only_poll(manager) -> None:
    task = asyncio.create_task(deliver_later(manager, 111))
    result = await manager.async_request_refresh(timeout=1)
    await task
    assert result.raw == 111
    assert manager._poll_requested.is_set()
    assert manager._observe_requested

    manager._observe_requested = False
    task = asyncio.create_task(deliver_later(manager, 222))
    result = await manager.async_request_once(timeout=1)
    await task
    assert result.raw == 222
    assert manager._observe_requested


async def test_manual_request_during_a_poll_does_not_leave_a_stale_flag(
    manager,
) -> None:
    manager._session_active = True
    await manager.async_request_refresh(timeout=0.01)
    assert not manager._observe_requested
    assert not manager._poll_requested.is_set()


async def test_loop_gives_the_observe_flag_only_to_the_requested_poll(
    manager,
) -> None:
    seen: list[bool] = []

    async def fake_poll() -> None:
        seen.append(manager._observe_only)
        manager._stop.set()

    manager._async_poll_once = fake_poll
    manager._request_poll(observe_only=True)
    await manager._connection_loop()
    assert seen == [True]
    assert not manager._observe_requested

    manager._stop.clear()
    seen.clear()
    manager._async_wait_for_next_poll = lambda: asyncio.sleep(0, result=True)
    await manager._connection_loop()  # a scheduled poll, nothing requested
    assert seen == [False]


async def test_request_times_out_without_a_packet(manager) -> None:
    assert await manager.async_request_refresh(timeout=0.05) is None


async def test_disconnect_callback_wakes_waiters(manager) -> None:
    manager._disconnected_callback(None)
    assert manager._disconnected.is_set()
    assert manager._packet_received.is_set()


async def test_usage_update_ignores_missing_packet(manager) -> None:
    manager.packet = None
    manager._update_usage(0.0)  # must not raise
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


async def test_settings_change_retimes_the_wait(hass: HomeAssistant, manager) -> None:
    waiting = asyncio.create_task(manager._async_wait_for_next_poll())
    await asyncio.sleep(0.05)
    assert not waiting.done()  # an hour is a long time

    hass.config_entries.async_update_entry(
        manager._entry, options={"poll_interval_minutes": 0.0005}
    )
    manager.async_notify_listeners()
    assert await asyncio.wait_for(waiting, 1) is True


async def test_connection_loop_polls_until_stopped(manager) -> None:
    sessions = 0

    async def fake_session() -> None:
        nonlocal sessions
        sessions += 1
        if sessions == 2:
            manager._stop.set()

    manager._async_poll_once = fake_session
    manager._async_wait_for_next_poll = lambda: asyncio.sleep(0, result=True)
    await manager._connection_loop()
    assert sessions == 2


async def test_connection_loop_exits_when_wait_says_stop(manager) -> None:
    sessions = 0

    async def fake_session() -> None:
        nonlocal sessions
        sessions += 1

    manager._async_poll_once = fake_session
    manager._async_wait_for_next_poll = lambda: asyncio.sleep(0, result=False)
    await manager._connection_loop()
    assert sessions == 1  # the first poll runs before any waiting


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
