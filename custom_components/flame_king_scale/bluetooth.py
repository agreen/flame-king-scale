"""Bluetooth connection manager for the Flame King YSNPS1."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CHARACTERISTIC_UUID,
    CONF_ADDRESS,
    CONF_CAPACITY,
    CONF_FLOW_DETECTION_TIME,
    CONF_FLOW_MIN_RATE,
    CONF_LONG_USE_TIME,
    CONF_POLL_INTERVAL,
    CONF_RAW_REFERENCE,
    CONF_RAW_ZERO,
    CONF_REFERENCE_WEIGHT,
    CONF_STABILITY_TIME,
    CONF_STABILITY_VARIANCE,
    CONF_TARE_WEIGHT,
    DEFAULT_OPTIONS,
    DEVICE_NAME,
    SERVICE_UUID,
)
from .polling import has_significant_change, raw_tolerance_for_percent
from .protocol import (
    InvalidPacketError,
    ScalePacket,
    calculate_tank_state,
    decode_packet,
)
from .usage import PropaneUsageTracker, UsageState

_LOGGER = logging.getLogger(__name__)
_FIRST_PACKET_TIMEOUT = 15.0
_QUIET_SAMPLE_SECONDS = 10.0
_MAX_ACTIVE_SESSION_SECONDS = 24 * 60 * 60.0


class FlameKingBluetoothManager:
    """Maintain a BLE notification subscription and publish decoded packets."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self.packet: ScalePacket | None = None
        self.available = False
        self._listeners: set[Callable[[], None]] = set()
        self._stop = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._poll_requested = asyncio.Event()
        self._packet_received = asyncio.Event()
        self._packet_generation = 0
        self._last_session_raw: int | None = None
        self._session_active = False
        self._task: asyncio.Task[None] | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._usage = PropaneUsageTracker()

    @property
    def usage(self) -> UsageState:
        """Return the current propane-use estimate."""
        return self._usage.state

    @property
    def long_use(self) -> bool:
        """Return whether the current use episode crossed the configured limit."""
        return self.usage.flowing and self.usage.duration_minutes >= float(
            self._options()[CONF_LONG_USE_TIME]
        )

    async def async_start(self) -> None:
        """Start the background connection loop."""
        if self._task is None:
            self._task = self._hass.async_create_background_task(
                self._connection_loop(), f"{DEVICE_NAME} {self.address}"
            )

    async def async_stop(self) -> None:
        """Stop reconnecting and disconnect cleanly."""
        self._stop.set()
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    @callback
    def async_trigger_poll(self) -> None:
        """Request an immediate sample when a session is not already active."""
        if not self._session_active:
            self._poll_requested.set()

    async def async_request_refresh(
        self, timeout: float = _FIRST_PACKET_TIMEOUT
    ) -> ScalePacket | None:
        """Request a poll and wait for a new packet."""
        generation = self._packet_generation
        self.async_trigger_poll()
        return await self._async_wait_for_new_packet(generation, timeout)

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update listener."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @callback
    def async_notify_listeners(self) -> None:
        """Notify entities that local configuration changed."""
        self._notify_listeners()
        self.async_trigger_poll()

    @callback
    def _notification_handler(self, _sender: object, data: bytearray) -> None:
        try:
            self.packet = decode_packet(data)
        except InvalidPacketError as err:
            _LOGGER.debug("Ignoring invalid Flame King packet: %s", err)
            return
        self._packet_generation += 1
        self._update_usage()
        self._packet_received.set()
        self.available = True
        self._notify_listeners()

    @callback
    def _update_usage(self) -> None:
        """Feed a decoded reading to the gas-use estimator."""
        if self.packet is None:
            return
        options = self._options()
        tank = calculate_tank_state(
            self.packet.raw,
            raw_zero=int(options[CONF_RAW_ZERO]),
            raw_reference=int(options[CONF_RAW_REFERENCE]),
            reference_weight_lb=float(options[CONF_REFERENCE_WEIGHT]),
            tare_weight_lb=float(options[CONF_TARE_WEIGHT]),
            capacity_lb=float(options[CONF_CAPACITY]),
        )
        self._usage.add_sample(
            asyncio.get_running_loop().time(),
            tank.propane_weight_lb,
            detection_seconds=float(options[CONF_FLOW_DETECTION_TIME]),
            minimum_rate_lb_per_hour=float(options[CONF_FLOW_MIN_RATE]),
        )

    @callback
    def _disconnected_callback(self, _client: object) -> None:
        self.available = False
        self._notify_listeners()
        self._disconnected.set()
        self._packet_received.set()

    async def _connection_loop(self) -> None:
        first_poll = True
        while not self._stop.is_set():
            if not first_poll and not await self._async_wait_for_next_poll():
                return
            first_poll = False
            self._poll_requested.clear()
            await self._async_poll_session()

    def _options(self) -> dict[str, Any]:
        """Return current integration options with defaults."""
        return {**DEFAULT_OPTIONS, **self._entry.options}

    def _raw_tolerance(self) -> int:
        """Return the configured stability tolerance in raw scale units."""
        options = self._options()
        return raw_tolerance_for_percent(
            raw_zero=int(options[CONF_RAW_ZERO]),
            raw_reference=int(options[CONF_RAW_REFERENCE]),
            reference_weight_lb=float(options[CONF_REFERENCE_WEIGHT]),
            capacity_lb=float(options[CONF_CAPACITY]),
            variance_percent=float(options[CONF_STABILITY_VARIANCE]),
        )

    async def _async_poll_session(self) -> None:
        """Connect, collect a reading, and disconnect after it becomes stable."""
        self._session_active = True
        self._disconnected.clear()
        session_start_generation = self._packet_generation
        try:
            ble_device: BLEDevice | None = async_ble_device_from_address(
                self._hass, self.address, connectable=True
            )
            if ble_device is None:
                return

            self._client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                DEVICE_NAME,
                self._disconnected_callback,
            )
            service = self._client.services.get_service(SERVICE_UUID)
            characteristic = self._client.services.get_characteristic(
                CHARACTERISTIC_UUID
            )
            if service is None or characteristic is None:
                raise ValueError(
                    "Bluetooth device does not expose the Flame King "
                    "FFE0/FFE4 GATT fingerprint"
                )
            await self._client.start_notify(characteristic, self._notification_handler)
            packet = await self._async_wait_for_new_packet(
                session_start_generation, _FIRST_PACKET_TIMEOUT
            )
            if packet is None:
                return

            tolerance = self._raw_tolerance()
            changed = self._last_session_raw is not None and has_significant_change(
                self._last_session_raw, packet.raw, tolerance
            )
            if not changed:
                changed = await self._async_quiet_sample(packet.raw, tolerance)
            if changed and self.packet is not None:
                await self._async_monitor_until_stable(self.packet.raw, tolerance)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # BLE backends expose several exception types.
            _LOGGER.debug("Flame King polling session failed: %s", err)
        finally:
            if (
                self.packet is not None
                and self._packet_generation > session_start_generation
            ):
                self._last_session_raw = self.packet.raw
            self.available = False
            self._notify_listeners()
            if self._client and self._client.is_connected:
                await self._client.disconnect()
            self._client = None
            self._session_active = False
            self._disconnected.clear()
            usage_was_active = self.usage.flowing
            self._usage.stop()
            if usage_was_active:
                self._notify_listeners()

    async def _async_quiet_sample(self, anchor_raw: int, tolerance: int) -> bool:
        """Briefly sample an unchanged scale before returning it to sleep."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _QUIET_SAMPLE_SECONDS
        generation = self._packet_generation
        while not self._stop.is_set() and not self._disconnected.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            packet = await self._async_wait_for_new_packet(
                generation, min(1.0, remaining)
            )
            if packet is None:
                continue
            generation = self._packet_generation
            if has_significant_change(anchor_raw, packet.raw, tolerance):
                return True
        return False

    async def _async_monitor_until_stable(
        self, anchor_raw: int, tolerance: int
    ) -> None:
        """Stream changes until the load has remained stable for the set time."""
        loop = asyncio.get_running_loop()
        options = self._options()
        stable_seconds = float(options[CONF_STABILITY_TIME]) * 60
        stable_since = loop.time()
        deadline = loop.time() + max(_MAX_ACTIVE_SESSION_SECONDS, stable_seconds * 2)
        generation = self._packet_generation

        while not self._stop.is_set() and not self._disconnected.is_set():
            now = loop.time()
            if now - stable_since >= stable_seconds or now >= deadline:
                return
            packet = await self._async_wait_for_new_packet(generation, 1.0)
            if packet is None:
                continue
            generation = self._packet_generation
            if has_significant_change(anchor_raw, packet.raw, tolerance):
                anchor_raw = packet.raw
                stable_since = loop.time()
            elif self.usage.flowing:
                # A real, sustained burn can be much smaller than the tank-change
                # tolerance. Keep listening until the burn stops and clear air elapses.
                stable_since = loop.time()

    async def _async_wait_for_new_packet(
        self, after_generation: int, timeout: float
    ) -> ScalePacket | None:
        """Wait for a packet newer than the requested generation."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self._stop.is_set() and not self._disconnected.is_set():
            self._packet_received.clear()
            if self._packet_generation > after_generation:
                return self.packet
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(self._packet_received.wait(), remaining)
            except TimeoutError:
                return None
        return None

    async def _async_wait_for_next_poll(self) -> bool:
        """Sleep until the interval elapses or an immediate poll is requested."""
        interval = float(self._options()[CONF_POLL_INTERVAL]) * 60
        stop_task = asyncio.create_task(self._stop.wait())
        poll_task = asyncio.create_task(self._poll_requested.wait())
        done, pending = await asyncio.wait(
            {stop_task, poll_task},
            timeout=interval,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
        return not self._stop.is_set()
