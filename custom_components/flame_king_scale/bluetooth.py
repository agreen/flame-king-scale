"""Bluetooth polling manager for the Flame King YSNPS1.

The scale is read with short, single-shot connections: connect, wait for one
packet, disconnect. How often that happens is decided by ``PollPlanner``: slowly
while nothing is happening, and at a faster gap after a weight change, detected
gas flow, or a press of "Start live monitoring", until things have been quiet
for long enough.
"""

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
    CONF_FAST_POLL,
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
from .polling import (
    MIN_FAST_POLL_SECONDS,
    PollMode,
    PollPlanner,
    quiet_polls_needed,
    raw_tolerance_for_percent,
)
from .protocol import (
    InvalidPacketError,
    ScalePacket,
    calculate_tank_state,
    decode_packet,
)
from .usage import PropaneUsageTracker, UsageState

_LOGGER = logging.getLogger(__name__)

POLL_TIMEOUT = 30.0
"""Hard limit for one whole poll: connect, first packet, and disconnect."""
_FIRST_PACKET_TIMEOUT = 15.0
_CONNECT_ATTEMPTS = 2
_DISCONNECT_TIMEOUT = 5.0
_REQUEST_TIMEOUT = POLL_TIMEOUT + 5.0


class FlameKingBluetoothManager:
    """Poll the scale over Bluetooth and publish decoded packets."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self.packet: ScalePacket | None = None
        self.available = False
        self.planner = PollPlanner()
        self.consecutive_failures = 0
        self.last_error: str | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._stop = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._poll_requested = asyncio.Event()
        self._wake = asyncio.Event()
        self._packet_received = asyncio.Event()
        self._packet_generation = 0
        self._session_active = False
        self._observe_requested = False
        self._observe_only = False
        self._last_poll_end: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._usage = PropaneUsageTracker()

    # --- state exposed to entities and diagnostics ---------------------------

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

    @property
    def poll_mode(self) -> PollMode:
        """Return whether the scale is being read at the idle or fast gap."""
        return self.planner.mode

    # --- logging ---------------------------------------------------------------

    def _record_failure(self, message: str, *args: object) -> None:
        """Log a failed poll, loudly the first time and quietly while it repeats."""
        self.consecutive_failures += 1
        self.last_error = message % args
        level = logging.WARNING if self.consecutive_failures == 1 else logging.DEBUG
        _LOGGER.log(level, "%s: " + message, self.address, *args)
        # A manual reading says nothing about whether fast polling should end.
        if not self._observe_only and self.planner.record_failure():
            self._usage.stop()
            _LOGGER.info(
                "%s: %d polls failed in a row; returning to the regular interval",
                self.address,
                self.planner.consecutive_failures,
            )

    def _record_success(self) -> None:
        """Note a healthy poll and announce recovery after a failure streak."""
        if self.consecutive_failures:
            _LOGGER.info(
                "%s: communication restored after %d failed poll(s)",
                self.address,
                self.consecutive_failures,
            )
        self.consecutive_failures = 0
        self.last_error = None

    # --- lifecycle ---------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the background polling loop."""
        if self._task is None:
            self._task = self._hass.async_create_background_task(
                self._connection_loop(), f"{DEVICE_NAME} {self.address}"
            )

    async def async_stop(self) -> None:
        """Stop polling and disconnect cleanly."""
        self._stop.set()
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    # --- requests from buttons, forms, and settings ------------------------------

    def _request_poll(self, *, observe_only: bool) -> bool:
        """Ask for an immediate poll unless one is already running."""
        if self._session_active:
            return False
        self._observe_requested = observe_only
        self._poll_requested.set()
        return True

    @callback
    def async_trigger_poll(self) -> None:
        """Request an immediate poll when one is not already running."""
        self._request_poll(observe_only=False)

    async def async_request_refresh(
        self, timeout: float = _REQUEST_TIMEOUT
    ) -> ScalePacket | None:
        """Take one manual reading and wait for it.

        A manual reading is observe-only: it updates what is shown but does not
        start fast polling, move the baseline, or feed the gas-flow estimate, so
        the next scheduled poll still compares against the real previous reading.
        """
        generation = self._packet_generation
        self._request_poll(observe_only=True)
        return await self._async_wait_for_new_packet(generation, timeout)

    async def async_request_once(
        self, timeout: float = _REQUEST_TIMEOUT
    ) -> ScalePacket | None:
        """Take one manual reading (the Request reading button)."""
        return await self.async_request_refresh(timeout)

    async def async_start_live_monitoring(
        self, timeout: float = _REQUEST_TIMEOUT
    ) -> ScalePacket | None:
        """Start, or restart, fast polling now.

        This is the same event as a scheduled poll noticing a change, started on
        demand: it seeds the fast-poll timer and polls immediately.
        """
        generation = self._packet_generation
        self.planner.seed_fast(asyncio.get_running_loop().time())
        self._wake.set()
        self._request_poll(observe_only=False)
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
        """Refresh entities after a settings change and re-time the next poll."""
        self._notify_listeners()
        self._wake.set()

    # --- packets -----------------------------------------------------------------

    @callback
    def _notification_handler(self, _sender: object, data: bytearray) -> None:
        try:
            self.packet = decode_packet(data)
        except InvalidPacketError as err:
            _LOGGER.debug("Ignoring invalid Flame King packet: %s", err)
            return
        self._packet_generation += 1
        self._packet_received.set()
        self.available = True
        self._notify_listeners()

    @callback
    def _disconnected_callback(self, _client: object) -> None:
        self._disconnected.set()
        self._packet_received.set()

    # --- options -------------------------------------------------------------------

    def _options(self) -> dict[str, Any]:
        """Return current integration options with defaults."""
        return {**DEFAULT_OPTIONS, **self._entry.options}

    def _fast_gap(self) -> float:
        return max(MIN_FAST_POLL_SECONDS, float(self._options()[CONF_FAST_POLL]))

    def _next_interval(self) -> float:
        """Return the gap before the next poll for the current mode."""
        return self.planner.next_interval(
            float(self._options()[CONF_POLL_INTERVAL]) * 60, self._fast_gap()
        )

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

    # --- polling loop --------------------------------------------------------------

    async def _connection_loop(self) -> None:
        loop = asyncio.get_running_loop()
        first_poll = True
        while not self._stop.is_set():
            if not first_poll and not await self._async_wait_for_next_poll():
                return
            first_poll = False
            self._observe_only = (
                self._observe_requested and self._poll_requested.is_set()
            )
            self._observe_requested = False
            self._poll_requested.clear()
            await self._async_poll_once()
            self._last_poll_end = loop.time()

    async def _async_wait_for_next_poll(self) -> bool:
        """Wait out the gap since the last poll; return False if stopping.

        The gap is measured from the end of the previous poll and is recomputed
        whenever settings change or fast polling is started.
        """
        loop = asyncio.get_running_loop()
        started = (
            self._last_poll_end if self._last_poll_end is not None else loop.time()
        )
        while True:
            remaining = started + self._next_interval() - loop.time()
            if remaining <= 0:
                return not self._stop.is_set()
            self._wake.clear()
            waiters = {
                asyncio.create_task(self._stop.wait()): "stop",
                asyncio.create_task(self._poll_requested.wait()): "poll",
                asyncio.create_task(self._wake.wait()): "wake",
            }
            done, pending = await asyncio.wait(
                set(waiters), timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            reasons = {waiters[task] for task in done}
            if "stop" in reasons:
                return False
            if "poll" in reasons or not reasons:
                return True
            # Only settings changed: loop and recompute the remaining time.

    async def _async_poll_once(self) -> None:
        """Take one reading with a connection, within a hard deadline."""
        self._session_active = True
        self._disconnected.clear()
        generation = self._packet_generation
        ok = False
        deadline = asyncio.timeout(POLL_TIMEOUT)
        try:
            async with deadline:
                packet = await self._async_read_packet(generation)
            if packet is not None:
                self._on_poll_success(packet)
                ok = True
        except asyncio.CancelledError:
            raise
        except Exception as err:  # BLE backends expose several exception types.
            if deadline.expired():
                self._record_failure(
                    "poll did not finish within %.0f seconds", POLL_TIMEOUT
                )
            else:
                self._record_failure("polling session failed: %s", err)
        finally:
            client, self._client = self._client, None
            if client is not None and client.is_connected:
                with suppress(Exception):
                    async with asyncio.timeout(_DISCONNECT_TIMEOUT):
                        await client.disconnect()
            self.available = ok
            self._session_active = False
            self._disconnected.clear()
            self._observe_only = False
            self._notify_listeners()

    async def _async_read_packet(self, generation: int) -> ScalePacket | None:
        """Connect, wait for one packet, and return it (disconnect is the caller's)."""
        ble_device: BLEDevice | None = async_ble_device_from_address(
            self._hass, self.address, connectable=True
        )
        if ble_device is None:
            self._record_failure(
                "scale is not currently visible to any Bluetooth adapter or "
                "proxy; check it is on, in range, and not held by another app"
            )
            return None

        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            DEVICE_NAME,
            self._disconnected_callback,
            max_attempts=_CONNECT_ATTEMPTS,
        )
        service = self._client.services.get_service(SERVICE_UUID)
        characteristic = self._client.services.get_characteristic(CHARACTERISTIC_UUID)
        if service is None or characteristic is None:
            raise ValueError(
                "Bluetooth device does not expose the Flame King "
                "FFE0/FFE4 GATT fingerprint"
            )
        await self._client.start_notify(characteristic, self._notification_handler)
        packet = await self._async_wait_for_new_packet(
            generation, _FIRST_PACKET_TIMEOUT
        )
        if packet is None:
            self._record_failure(
                "connected but no valid packet arrived within %.0f seconds",
                _FIRST_PACKET_TIMEOUT,
            )
        return packet

    @callback
    def _on_poll_success(self, packet: ScalePacket) -> None:
        """Account for one good reading."""
        self._record_success()
        if self._observe_only:
            return
        loop_time = asyncio.get_running_loop().time()
        self._update_usage(loop_time)
        was_fast = self.planner.mode is PollMode.FAST
        options = self._options()
        self.planner.record_success(
            packet.raw,
            tolerance=self._raw_tolerance(),
            flowing=self.usage.flowing,
            quiet_needed=quiet_polls_needed(
                float(options[CONF_STABILITY_TIME]) * 60, self._fast_gap()
            ),
            now=loop_time,
        )
        if was_fast and self.planner.mode is PollMode.IDLE:
            self._usage.stop()

    @callback
    def _update_usage(self, now: float) -> None:
        """Feed one reading to the gas-flow estimator."""
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
        # The estimator needs a few readings inside its window, so the window
        # must span several fast polls however small the user sets it.
        detection = max(float(options[CONF_FLOW_DETECTION_TIME]), 3 * self._fast_gap())
        self._usage.add_sample(
            now,
            tank.propane_weight_lb,
            detection_seconds=detection,
            minimum_rate_lb_per_hour=float(options[CONF_FLOW_MIN_RATE]),
        )

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
