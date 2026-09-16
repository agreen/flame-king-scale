"""Bluetooth advertisement matching for Flame King scales."""

from __future__ import annotations

from collections.abc import Iterable


def is_flame_king_candidate(
    name: str | None,
    service_uuids: Iterable[str],
    *,
    device_name: str,
    service_uuid: str,
) -> bool:
    """Return whether an advertisement looks like a supported scale.

    The stock electronics advertise the generic ``Gas Monitor`` name. When
    services are included in the advertisement, FFE0 is required as an
    additional fingerprint. Some firmware omits service UUIDs entirely, so an
    exact name match remains a fallback; the GATT service and characteristic
    are verified when Home Assistant connects.
    """
    if not name or name.casefold() != device_name.casefold():
        return False

    advertised_services = {uuid.casefold() for uuid in service_uuids}
    return not advertised_services or service_uuid.casefold() in advertised_services
