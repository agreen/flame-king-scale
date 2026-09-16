"""Bluetooth connection manager for the Flame King YSNPS1."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant, callback

from .const import CHARACTERISTIC_UUID, DEVICE_NAME
from .protocol import InvalidPacketError, ScalePacket, decode_packet

_LOGGER = logging.getLogger(__name__)


class FlameKingBluetoothManager:
    """Maintain a BLE notification subscription and publish decoded packets."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialize the manager."""
        self._hass = hass
        self.address = address
        self.packet: ScalePacket | None = None
        self.available = False
        self._listeners: set[Callable[[], None]] = set()
        self._stop = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client: BleakClientWithServiceCache | None = None

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
    def _notification_handler(self, _sender: object, data: bytearray) -> None:
        try:
            self.packet = decode_packet(data)
        except InvalidPacketError as err:
            _LOGGER.debug("Ignoring invalid Flame King packet: %s", err)
            return
        self.available = True
        self._notify_listeners()

    @callback
    def _disconnected_callback(self, _client: object) -> None:
        self.available = False
        self._notify_listeners()
        self._disconnected.set()

    async def _connection_loop(self) -> None:
        retry_delay = 5
        while not self._stop.is_set():
            self._disconnected.clear()
            ble_device: BLEDevice | None = async_ble_device_from_address(
                self._hass, self.address, connectable=True
            )
            if ble_device is None:
                await self._wait_or_stop(retry_delay)
                retry_delay = min(retry_delay * 2, 60)
                continue

            try:
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    DEVICE_NAME,
                    self._disconnected_callback,
                )
                await self._client.start_notify(
                    CHARACTERISTIC_UUID, self._notification_handler
                )
                retry_delay = 5
                await self._wait_for_disconnect_or_stop()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # BLE backends expose several exception types.
                _LOGGER.debug("Flame King connection failed: %s", err)
            finally:
                self.available = False
                self._notify_listeners()
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
                self._client = None

            if not self._stop.is_set():
                await self._wait_or_stop(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _wait_or_stop(self, delay: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def _wait_for_disconnect_or_stop(self) -> None:
        stop_task = asyncio.create_task(self._stop.wait())
        disconnect_task = asyncio.create_task(self._disconnected.wait())
        done, pending = await asyncio.wait(
            {stop_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
