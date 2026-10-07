"""Tests for Bluetooth advertisement matching."""

import unittest

from custom_components.flame_king_scale.const import DEVICE_NAME, SERVICE_UUID
from custom_components.flame_king_scale.discovery import is_flame_king_candidate


class DiscoveryTests(unittest.TestCase):
    """Validate name and service fingerprint filtering."""

    def test_accepts_name_and_flame_king_service(self) -> None:
        self.assertTrue(
            is_flame_king_candidate(
                "Gas Monitor",
                [SERVICE_UUID],
                device_name=DEVICE_NAME,
                service_uuid=SERVICE_UUID,
            )
        )

    def test_accepts_exact_name_when_firmware_omits_services(self) -> None:
        self.assertTrue(
            is_flame_king_candidate(
                "Gas Monitor",
                [],
                device_name=DEVICE_NAME,
                service_uuid=SERVICE_UUID,
            )
        )

    def test_rejects_name_with_conflicting_service_fingerprint(self) -> None:
        self.assertFalse(
            is_flame_king_candidate(
                "Gas Monitor",
                ["0000180f-0000-1000-8000-00805f9b34fb"],
                device_name=DEVICE_NAME,
                service_uuid=SERVICE_UUID,
            )
        )

    def test_rejects_unrelated_device(self) -> None:
        self.assertFalse(
            is_flame_king_candidate(
                "Other Monitor",
                [SERVICE_UUID],
                device_name=DEVICE_NAME,
                service_uuid=SERVICE_UUID,
            )
        )


if __name__ == "__main__":
    unittest.main()
