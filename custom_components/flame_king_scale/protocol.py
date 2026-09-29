"""Decode Flame King YSNPS1 Bluetooth packets and calculate tank state."""

from __future__ import annotations

from dataclasses import dataclass


class InvalidPacketError(ValueError):
    """Raised when a Bluetooth notification is not a valid scale packet."""


@dataclass(frozen=True, slots=True)
class ScalePacket:
    """A decoded YSNPS1 notification."""

    raw: int
    battery: int


@dataclass(frozen=True, slots=True)
class TankState:
    """Calculated propane tank measurements."""

    gross_weight_lb: float
    propane_weight_lb: float
    propane_percent: float


def decode_packet(data: bytes | bytearray) -> ScalePacket:
    """Decode and validate an AA 01 LL HH BB CC notification."""
    if len(data) != 6:
        raise InvalidPacketError(f"Expected 6 bytes, received {len(data)}")
    if data[0] != 0xAA or data[1] != 0x01:
        raise InvalidPacketError("Unexpected packet header")
    checksum = 0
    for value in data[:5]:
        checksum ^= value
    if checksum != data[5]:
        raise InvalidPacketError("Invalid XOR checksum")

    return ScalePacket(raw=data[2] | (data[3] << 8), battery=data[4])


def calculate_tank_state(
    raw: int,
    *,
    raw_zero: int,
    raw_reference: int,
    reference_weight_lb: float,
    tare_weight_lb: float,
    capacity_lb: float,
) -> TankState:
    """Convert a raw reading to gross weight, propane weight, and percentage."""
    span = raw_reference - raw_zero
    if span == 0:
        raise ValueError("Raw reference must differ from raw zero")
    if reference_weight_lb <= 0:
        raise ValueError("Reference weight must be greater than zero")
    if capacity_lb <= 0:
        raise ValueError("Tank capacity must be greater than zero")

    # The stock firmware can report a literal raw zero while unloaded even
    # though Flame King's loaded conversion extrapolates to zero at raw 64.
    gross = max(0.0, (raw - raw_zero) * reference_weight_lb / span)
    propane = max(0.0, gross - tare_weight_lb)
    percent = min(100.0, max(0.0, propane / capacity_lb * 100.0))
    return TankState(gross, propane, percent)


def calibration_from_loaded_points(
    first_raw: int,
    first_weight_lb: float,
    second_raw: int,
    second_weight_lb: float,
) -> tuple[int, int, float]:
    """Derive the linear conversion from two distinct, non-zero loads."""
    raw_delta = second_raw - first_raw
    weight_delta = second_weight_lb - first_weight_lb
    if raw_delta == 0 or weight_delta == 0:
        raise ValueError("Calibration loads and raw readings must differ")
    if raw_delta * weight_delta <= 0:
        raise ValueError("The heavier load must produce the larger raw reading")

    raw_zero = round(first_raw - first_weight_lb * raw_delta / weight_delta)
    if raw_zero == second_raw:
        raise ValueError("Calibration produced a degenerate raw span")
    return raw_zero, second_raw, second_weight_lb
