"""Observe and optionally probe a Flame King YSNPS1 BLE scale on Windows."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import signal
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

DEFAULT_DEVICE_NAME = "Gas Monitor"
SCALE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
SCALE_NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"


def timestamp() -> str:
    """Return a timezone-aware local timestamp with millisecond precision."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def decode_scale_packet(payload: bytes) -> dict[str, Any] | None:
    """Decode the observed six-byte Flame King notification format."""
    if len(payload) != 6 or payload[:2] != b"\xaa\x01":
        return None
    checksum = 0
    for octet in payload[:5]:
        checksum ^= octet
    return {
        "raw_weight": int.from_bytes(payload[2:4], "little"),
        "battery_percent": payload[4],
        "checksum": payload[5],
        "checksum_valid": checksum == payload[5],
    }


def byte_map(values: dict[int, bytes]) -> dict[str, str]:
    """Convert Bluetooth integer-keyed byte mappings to JSON-safe hex."""
    return {f"0x{key:04x}": bytes(value).hex() for key, value in values.items()}


def safe_platform_data(value: Any) -> list[str]:
    """Keep platform data useful without making JSON serialization fragile."""
    if value is None:
        return []
    if not isinstance(value, tuple):
        value = (value,)
    return [repr(item) for item in value]


def enum_text(value: Any) -> str | None:
    """Return a useful string for a WinRT enum value."""
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def raw_windows_packet(event_args: Any) -> dict[str, Any] | None:
    """Extract all available fields from one native Windows BLE packet."""
    if event_args is None:
        return None
    try:
        advertisement = event_args.advertisement
        return {
            "timestamp": event_args.timestamp.isoformat(timespec="milliseconds"),
            "advertisement_type": enum_text(event_args.advertisement_type),
            "address_type": enum_text(event_args.bluetooth_address_type),
            "rssi": event_args.raw_signal_strength_in_dbm,
            "tx_power": event_args.transmit_power_level_in_dbm,
            "is_anonymous": event_args.is_anonymous,
            "is_connectable": event_args.is_connectable,
            "is_directed": event_args.is_directed,
            "is_scan_response": event_args.is_scan_response,
            "is_scannable": event_args.is_scannable,
            "primary_phy": enum_text(event_args.primary_phy),
            "secondary_phy": enum_text(event_args.secondary_phy),
            "local_name": advertisement.local_name or None,
            "flags": None if advertisement.flags is None else int(advertisement.flags),
            "service_uuids": [str(uuid) for uuid in advertisement.service_uuids],
            "manufacturer_data": [
                {
                    "company_id": item.company_id,
                    "data_hex": bytes(item.data).hex(),
                }
                for item in advertisement.manufacturer_data
            ],
            "data_sections": [
                {
                    "data_type": section.data_type,
                    "data_hex": bytes(section.data).hex(),
                }
                for section in advertisement.data_sections
            ],
        }
    except Exception as error:
        return {
            "extraction_error": f"{type(error).__name__}: {error}",
            "raw_type": type(event_args).__name__,
        }


def raw_windows_advertisements(platform_data: Any) -> dict[str, Any] | None:
    """Extract the Windows advertisement/scan-response pair Bleak retains."""
    if not isinstance(platform_data, tuple) or len(platform_data) < 2:
        return None
    raw_pair = platform_data[1]
    if not hasattr(raw_pair, "adv") or not hasattr(raw_pair, "scan"):
        return None
    return {
        "advertisement": raw_windows_packet(raw_pair.adv),
        "scan_response": raw_windows_packet(raw_pair.scan),
    }


@dataclass
class MonitorSettings:
    name: str
    silence_seconds: float
    status_seconds: float
    notify_seconds: float
    probe_on_first_seen: bool
    probe_every_minutes: float
    max_runtime_minutes: float
    quiet_advertisements: bool
    keep_awake: bool


class EventLog:
    """Write human-readable console output and structured JSONL records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a", encoding="utf-8", buffering=1)

    def close(self) -> None:
        self._stream.close()

    def emit(
        self, event: str, message: str, *, console: bool = True, **details: Any
    ) -> None:
        record = {"timestamp": timestamp(), "event": event, **details}
        self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        if console:
            print(f"{record['timestamp']}  {message}", flush=True)


class AwakeGuard:
    """Temporarily prevent Windows system sleep without changing power settings."""

    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001

    def __init__(self, enabled: bool, event_log: EventLog) -> None:
        self.enabled = enabled
        self.log = event_log
        self.active = False

    def start(self) -> None:
        if not self.enabled:
            return
        if sys.platform != "win32":
            self.log.emit(
                "keep_awake_unavailable",
                "KEEP-AWAKE unavailable: this is not Windows",
            )
            return
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        result = kernel32.SetThreadExecutionState(
            self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED
        )
        self.active = bool(result)
        self.log.emit(
            "keep_awake_started" if self.active else "keep_awake_failed",
            "KEEP-AWAKE active" if self.active else "KEEP-AWAKE failed",
        )

    def stop(self) -> None:
        if not self.active:
            return
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetThreadExecutionState(self._ES_CONTINUOUS)
        self.active = False
        self.log.emit("keep_awake_stopped", "KEEP-AWAKE released")


class FlameKingMonitor:
    """Continuously observe advertisements and perform optional GATT probes."""

    def __init__(self, settings: MonitorSettings, event_log: EventLog) -> None:
        self.settings = settings
        self.log = event_log
        self.stop_event = asyncio.Event()
        self._scanner: BleakScanner | None = None
        self._device: BLEDevice | None = None
        self._target_address: str | None = None
        self._last_advertisement_at: float | None = None
        self._last_scanner_callback_at: float | None = None
        self._advertisement_count = 0
        self._callback_count = 0
        self._all_callback_count = 0
        self._other_device_callback_count = 0
        self._silence_reported = False
        self._gap_includes_scanner_pause = False
        self._probe_lock = asyncio.Lock()
        self._probe_requested = asyncio.Event()
        self._first_probe_requested = False
        self._started_at = monotonic()

    def request_stop(self) -> None:
        """Request a graceful shutdown."""
        self.stop_event.set()

    def _matches(self, device: BLEDevice, advertisement: AdvertisementData) -> bool:
        if self._target_address is not None:
            return device.address.casefold() == self._target_address.casefold()
        name = advertisement.local_name or device.name
        if not name or name.casefold() != self.settings.name.casefold():
            return False
        self._target_address = device.address
        return True

    def _advertisement_callback(
        self, device: BLEDevice, advertisement: AdvertisementData
    ) -> None:
        self._all_callback_count += 1
        self._last_scanner_callback_at = monotonic()
        if not self._matches(device, advertisement):
            self._other_device_callback_count += 1
            return

        now = monotonic()
        previous = self._last_advertisement_at
        gap_ms = None if previous is None else round((now - previous) * 1000, 1)
        paired_scan_response = gap_ms is not None and gap_ms <= 50.0
        gap_includes_scanner_pause = self._gap_includes_scanner_pause
        self._gap_includes_scanner_pause = False
        self._last_advertisement_at = now
        self._device = device
        self._callback_count += 1
        if not paired_scan_response:
            self._advertisement_count += 1
        self._silence_reported = False

        event = "advertisement_update" if paired_scan_response else "advertisement"
        label = "ADV+SCAN" if paired_scan_response else "ADV"
        self.log.emit(
            event,
            f"{label} #{self._advertisement_count}  {self.settings.name}  "
            f"RSSI {advertisement.rssi} dBm"
            + ("" if gap_ms is None else f"  gap {gap_ms:.1f} ms")
            + (" (scanner was paused)" if gap_includes_scanner_pause else ""),
            sequence=self._advertisement_count,
            callback_sequence=self._callback_count,
            paired_scan_response=paired_scan_response,
            gap_includes_scanner_pause=gap_includes_scanner_pause,
            address=device.address,
            device_name=device.name,
            local_name=advertisement.local_name,
            rssi=advertisement.rssi,
            tx_power=advertisement.tx_power,
            gap_ms=gap_ms,
            service_uuids=list(advertisement.service_uuids),
            manufacturer_data=byte_map(advertisement.manufacturer_data),
            service_data={
                key: bytes(value).hex()
                for key, value in advertisement.service_data.items()
            },
            platform_data=safe_platform_data(advertisement.platform_data),
            raw_windows_advertisements=raw_windows_advertisements(
                advertisement.platform_data
            ),
            console=not self.settings.quiet_advertisements,
        )

        if self.settings.probe_on_first_seen and not self._first_probe_requested:
            self._first_probe_requested = True
            self._probe_requested.set()

    async def _start_scanner(self) -> None:
        self._scanner = BleakScanner(detection_callback=self._advertisement_callback)
        await self._scanner.start()
        self.log.emit("scanner_started", f"SCANNING for {self.settings.name!r}")

    async def _stop_scanner(self) -> bool:
        if self._scanner is not None:
            scanner = self._scanner
            self._scanner = None
            self._gap_includes_scanner_pause = True
            try:
                await asyncio.wait_for(scanner.stop(), 5.0)
            except TimeoutError:
                self.log.emit(
                    "scanner_stop_timeout",
                    "SCAN STOP TIMEOUT after 5 seconds; continuing shutdown",
                    timeout_seconds=5.0,
                )
                return False
            self.log.emit("scanner_stopped", "SCAN paused")
        return True

    async def _status_loop(self) -> None:
        next_status = monotonic() + self.settings.status_seconds
        while not self.stop_event.is_set():
            await asyncio.sleep(min(1.0, self.settings.silence_seconds))
            now = monotonic()
            if self._scanner is None:
                if now >= next_status:
                    self.log.emit(
                        "status_scanner_paused",
                        "STATUS: advertisement monitoring is paused for a probe",
                        advertisement_count=self._advertisement_count,
                    )
                    next_status = now + self.settings.status_seconds
                continue
            if self._last_advertisement_at is None:
                if now >= next_status:
                    self.log.emit(
                        "awaiting_advertisement",
                        f"WAITING: no {self.settings.name!r} advertisement seen yet; "
                        f"scanner received {self._all_callback_count} total callbacks",
                        scanner_callback_count=self._all_callback_count,
                        other_device_callback_count=self._other_device_callback_count,
                    )
                    next_status = now + self.settings.status_seconds
                continue

            silence = now - self._last_advertisement_at
            if silence >= self.settings.silence_seconds and not self._silence_reported:
                self._silence_reported = True
                self.log.emit(
                    "advertisement_silence",
                    f"SCALE SILENT: no advertisement for {silence:.1f} seconds; "
                    f"scanner total {self._all_callback_count}, "
                    f"other-device {self._other_device_callback_count}",
                    silence_seconds=round(silence, 3),
                    advertisement_count=self._advertisement_count,
                    scanner_callback_count=self._all_callback_count,
                    other_device_callback_count=self._other_device_callback_count,
                    scanner_last_callback_seconds_ago=(
                        None
                        if self._last_scanner_callback_at is None
                        else round(now - self._last_scanner_callback_at, 3)
                    ),
                )
            if now >= next_status:
                self.log.emit(
                    "status",
                    f"STATUS: {self._advertisement_count} advertisements; "
                    f"scale last seen {silence:.1f}s ago; "
                    f"scanner total {self._all_callback_count}, "
                    f"other-device {self._other_device_callback_count}",
                    advertisement_count=self._advertisement_count,
                    last_seen_seconds_ago=round(silence, 3),
                    scanner_callback_count=self._all_callback_count,
                    other_device_callback_count=self._other_device_callback_count,
                    scanner_last_callback_seconds_ago=(
                        None
                        if self._last_scanner_callback_at is None
                        else round(now - self._last_scanner_callback_at, 3)
                    ),
                )
                next_status = now + self.settings.status_seconds

    async def _probe_scheduler(self) -> None:
        periodic_seconds = self.settings.probe_every_minutes * 60
        while not self.stop_event.is_set():
            waiters = [asyncio.create_task(self.stop_event.wait())]
            waiters.append(asyncio.create_task(self._probe_requested.wait()))
            done, pending = await asyncio.wait(
                waiters,
                timeout=periodic_seconds if periodic_seconds > 0 else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if self.stop_event.is_set():
                return
            self._probe_requested.clear()
            await self._probe()

    async def _probe(self) -> None:
        async with self._probe_lock:
            device = self._device
            if device is None:
                self.log.emit(
                    "probe_skipped",
                    "PROBE skipped: the scale has not been discovered",
                    reason="device_not_discovered",
                )
                return

            if not await self._stop_scanner():
                self.log.emit(
                    "probe_skipped",
                    "PROBE skipped: scanner did not stop cleanly",
                    reason="scanner_stop_timeout",
                )
                return
            self.log.emit(
                "probe_started",
                "PROBE connecting (notification subscription writes only the CCCD)",
                address=device.address,
                notify_seconds=self.settings.notify_seconds,
            )
            notifications = 0

            def notification_callback(_: Any, payload: bytearray) -> None:
                nonlocal notifications
                notifications += 1
                raw = bytes(payload)
                decoded = decode_scale_packet(raw)
                detail = f"NOTIFY {raw.hex()}"
                if decoded is not None:
                    detail += (
                        f"  raw={decoded['raw_weight']}"
                        f"  battery={decoded['battery_percent']}%"
                        f"  checksum={'OK' if decoded['checksum_valid'] else 'BAD'}"
                    )
                self.log.emit(
                    "notification",
                    detail,
                    characteristic_uuid=SCALE_NOTIFY_UUID,
                    payload_hex=raw.hex(),
                    decoded=decoded,
                    sequence=notifications,
                )

            try:
                async with BleakClient(device, timeout=20.0) as client:
                    self.log.emit(
                        "connected",
                        "CONNECTED",
                        address=device.address,
                        is_connected=client.is_connected,
                    )
                    notify_characteristic = None
                    for service in client.services:
                        self.log.emit(
                            "gatt_service",
                            f"SERVICE {service.uuid}  {service.description}",
                            uuid=service.uuid,
                            handle=service.handle,
                            description=service.description,
                            expected_scale_service=(
                                service.uuid.casefold() == SCALE_SERVICE_UUID
                            ),
                        )
                        for characteristic in service.characteristics:
                            properties = list(characteristic.properties)
                            self.log.emit(
                                "gatt_characteristic",
                                f"  CHAR {characteristic.uuid}  "
                                f"[{', '.join(properties) or 'no properties'}]",
                                service_uuid=service.uuid,
                                uuid=characteristic.uuid,
                                handle=characteristic.handle,
                                description=characteristic.description,
                                properties=properties,
                                descriptors=[
                                    {
                                        "handle": descriptor.handle,
                                        "uuid": descriptor.uuid,
                                        "description": descriptor.description,
                                    }
                                    for descriptor in characteristic.descriptors
                                ],
                            )
                            if characteristic.uuid.casefold() == SCALE_NOTIFY_UUID:
                                notify_characteristic = characteristic
                            if "read" in properties:
                                try:
                                    value = bytes(
                                        await asyncio.wait_for(
                                            client.read_gatt_char(characteristic), 8.0
                                        )
                                    )
                                    self.log.emit(
                                        "gatt_read",
                                        f"  READ {characteristic.uuid} = {value.hex()}",
                                        uuid=characteristic.uuid,
                                        handle=characteristic.handle,
                                        success=True,
                                        payload_hex=value.hex(),
                                        decoded=decode_scale_packet(value),
                                    )
                                # BLE error types vary between platform backends.
                                except Exception as error:
                                    self.log.emit(
                                        "gatt_read",
                                        f"  READ FAILED {characteristic.uuid}: "
                                        f"{type(error).__name__}: {error}",
                                        uuid=characteristic.uuid,
                                        handle=characteristic.handle,
                                        success=False,
                                        error_type=type(error).__name__,
                                        error=str(error),
                                    )

                    if notify_characteristic is None:
                        self.log.emit(
                            "notification_unavailable",
                            f"NOTIFY unavailable: {SCALE_NOTIFY_UUID} was not found",
                            characteristic_uuid=SCALE_NOTIFY_UUID,
                        )
                    elif "notify" not in notify_characteristic.properties:
                        self.log.emit(
                            "notification_unavailable",
                            "NOTIFY unavailable: characteristic lacks notify property",
                            characteristic_uuid=SCALE_NOTIFY_UUID,
                            properties=list(notify_characteristic.properties),
                        )
                    else:
                        await client.start_notify(
                            notify_characteristic, notification_callback
                        )
                        self.log.emit(
                            "notification_subscription_started",
                            "SUBSCRIBED for "
                            f"{self.settings.notify_seconds:.1f} seconds",
                            characteristic_uuid=SCALE_NOTIFY_UUID,
                        )
                        with suppress(TimeoutError):
                            await asyncio.wait_for(
                                self.stop_event.wait(), self.settings.notify_seconds
                            )
                        if client.is_connected:
                            await client.stop_notify(notify_characteristic)
                        self.log.emit(
                            "notification_subscription_stopped",
                            f"UNSUBSCRIBED after {notifications} notifications",
                            characteristic_uuid=SCALE_NOTIFY_UUID,
                            notification_count=notifications,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.log.emit(
                    "probe_failed",
                    f"PROBE FAILED: {type(error).__name__}: {error}",
                    address=device.address,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            finally:
                self.log.emit(
                    "probe_finished",
                    f"PROBE complete; {notifications} notifications captured",
                    notification_count=notifications,
                )
                if not self.stop_event.is_set():
                    try:
                        await self._start_scanner()
                    except Exception as error:
                        self.log.emit(
                            "scanner_restart_failed",
                            f"SCAN RESTART FAILED: {type(error).__name__}: {error}",
                            error_type=type(error).__name__,
                            error=str(error),
                        )
                        self.stop_event.set()

    async def run(self) -> None:
        """Run until Ctrl+C, a termination signal, or the configured deadline."""
        self.log.emit(
            "run_started",
            f"Flame King monitor started; log: {self.log.path}",
            settings=asdict(self.settings),
            python=sys.version,
            platform=sys.platform,
            note=(
                "Passive scanning performs no writes. A probe reads all readable "
                "characteristics and enables FFE4 notifications via its CCCD; it "
                "never writes the proprietary FFE9 characteristic."
            ),
        )
        await self._start_scanner()
        tasks = [
            asyncio.create_task(self._status_loop(), name="status"),
            asyncio.create_task(self._probe_scheduler(), name="probe-scheduler"),
        ]
        if self.settings.max_runtime_minutes > 0:
            tasks.append(asyncio.create_task(self._deadline_loop(), name="deadline"))
        try:
            await self.stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._stop_scanner()
            self.log.emit(
                "run_stopped",
                f"Monitor stopped after {monotonic() - self._started_at:.1f} seconds",
                runtime_seconds=round(monotonic() - self._started_at, 3),
                advertisement_count=self._advertisement_count,
                scanner_callback_count=self._all_callback_count,
                other_device_callback_count=self._other_device_callback_count,
            )

    async def _deadline_loop(self) -> None:
        await asyncio.sleep(self.settings.max_runtime_minutes * 60)
        self.log.emit("deadline_reached", "Configured runtime completed")
        self.stop_event.set()


def positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def parse_args() -> argparse.Namespace:
    default_log_dir = Path(__file__).resolve().parent / "logs"
    parser = argparse.ArgumentParser(
        description=(
            "Continuously log Flame King scale BLE advertisements, with optional "
            "brief GATT read/notification probes. Press Ctrl+C to stop."
        )
    )
    parser.add_argument("--name", default=DEFAULT_DEVICE_NAME)
    parser.add_argument("--log-dir", type=Path, default=default_log_dir)
    parser.add_argument("--silence-seconds", type=positive, default=10.0)
    parser.add_argument("--status-seconds", type=positive, default=60.0)
    parser.add_argument("--notify-seconds", type=positive, default=15.0)
    parser.add_argument("--probe-on-first-seen", action="store_true")
    parser.add_argument("--probe-every-minutes", type=nonnegative, default=0.0)
    parser.add_argument("--max-runtime-minutes", type=nonnegative, default=0.0)
    parser.add_argument("--quiet-advertisements", action="store_true")
    parser.add_argument("--keep-awake", action="store_true")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.log_dir / (
        "flame-king-monitor-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl"
    )
    event_log = EventLog(log_path)
    settings = MonitorSettings(
        name=args.name,
        silence_seconds=args.silence_seconds,
        status_seconds=args.status_seconds,
        notify_seconds=args.notify_seconds,
        probe_on_first_seen=args.probe_on_first_seen,
        probe_every_minutes=args.probe_every_minutes,
        max_runtime_minutes=args.max_runtime_minutes,
        quiet_advertisements=args.quiet_advertisements,
        keep_awake=args.keep_awake,
    )
    monitor = FlameKingMonitor(settings, event_log)
    awake_guard = AwakeGuard(settings.keep_awake, event_log)
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            with suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signal_value, monitor.request_stop)
    try:
        awake_guard.start()
        await monitor.run()
    except KeyboardInterrupt:
        monitor.request_stop()
    finally:
        awake_guard.stop()
        event_log.close()
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
