"""Tests for the YSNPS1 protocol decoder and tank calculations."""

import math
import unittest

from custom_components.flame_king_scale.const import (
    DEFAULT_RAW_REFERENCE,
    DEFAULT_RAW_ZERO,
    DEFAULT_REFERENCE_WEIGHT,
    default_tare_for_capacity,
)
from custom_components.flame_king_scale.protocol import (
    InvalidPacketError,
    calculate_tank_state,
    calibration_from_loaded_points,
    decode_packet,
)

OFFICIAL_LB_PER_KG = 2.2046226218


class ProtocolTests(unittest.TestCase):
    """Validate protocol behavior against captured packets."""

    def test_decode_zero_packet_from_device(self) -> None:
        packet = decode_packet(bytes.fromhex("AA 01 00 00 64 CF"))
        self.assertEqual(packet.raw, 0)
        self.assertEqual(packet.battery, 100)

    def test_tank_size_empty_weight_presets(self) -> None:
        self.assertEqual(default_tare_for_capacity(20), 17)
        self.assertEqual(default_tare_for_capacity(30), 25)
        self.assertEqual(default_tare_for_capacity(40), 32)

    def test_decode_little_endian_weight_and_checksum(self) -> None:
        # AA XOR 01 XOR 3A XOR 08 XOR 64 = FD
        packet = decode_packet(bytes.fromhex("AA 01 3A 08 64 FD"))
        self.assertEqual(packet.raw, 0x083A)
        self.assertEqual(packet.battery, 100)

    def test_reject_invalid_packets(self) -> None:
        invalid_packets = (
            b"",
            bytes.fromhex("AA 01 00 00 64"),
            bytes.fromhex("AB 01 00 00 64 CE"),
            bytes.fromhex("AA 01 00 00 64 00"),
        )
        for packet in invalid_packets:
            with self.subTest(packet=packet), self.assertRaises(InvalidPacketError):
                decode_packet(packet)

    def test_calculate_tank_state(self) -> None:
        state = calculate_tank_state(
            3700,
            raw_zero=100,
            raw_reference=1300,
            reference_weight_lb=10,
            tare_weight_lb=17,
            capacity_lb=20,
        )
        self.assertTrue(math.isclose(state.gross_weight_lb, 30))
        self.assertTrue(math.isclose(state.propane_weight_lb, 13))
        self.assertTrue(math.isclose(state.propane_percent, 65))

    def test_default_calibration_matches_official_app_weight_formula(self) -> None:
        """The two-point model should reproduce Flame King's fixed conversion."""
        for raw in (64, 320, 1600, 4096, 8192):
            with self.subTest(raw=raw):
                state = calculate_tank_state(
                    raw,
                    raw_zero=DEFAULT_RAW_ZERO,
                    raw_reference=DEFAULT_RAW_REFERENCE,
                    reference_weight_lb=DEFAULT_REFERENCE_WEIGHT,
                    tare_weight_lb=17,
                    capacity_lb=20,
                )
                official_gross_lb = (raw / 256 - 0.25) * OFFICIAL_LB_PER_KG
                self.assertTrue(
                    math.isclose(
                        state.gross_weight_lb,
                        official_gross_lb,
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    )
                )

    def test_factory_conversion_clips_unloaded_negative_weight(self) -> None:
        state = calculate_tank_state(
            0,
            raw_zero=DEFAULT_RAW_ZERO,
            raw_reference=DEFAULT_RAW_REFERENCE,
            reference_weight_lb=DEFAULT_REFERENCE_WEIGHT,
            tare_weight_lb=17,
            capacity_lb=20,
        )
        self.assertEqual(state.gross_weight_lb, 0)

    def test_calibration_uses_two_loaded_points(self) -> None:
        raw_zero, raw_reference, reference_weight = calibration_from_loaded_points(
            2154, 18.0, 4476, 38.0
        )
        self.assertEqual(raw_zero, 64)
        self.assertEqual(raw_reference, 4476)
        self.assertEqual(reference_weight, 38.0)

        for raw, expected_weight in ((2154, 18.0), (4476, 38.0)):
            state = calculate_tank_state(
                raw,
                raw_zero=raw_zero,
                raw_reference=raw_reference,
                reference_weight_lb=reference_weight,
                tare_weight_lb=18,
                capacity_lb=20,
            )
            self.assertTrue(
                math.isclose(state.gross_weight_lb, expected_weight, abs_tol=0.01)
            )

    def test_loaded_calibration_rejects_reversed_or_duplicate_points(self) -> None:
        invalid = (
            (1000, 10.0, 1000, 20.0),
            (1000, 10.0, 2000, 10.0),
            (2000, 10.0, 1000, 20.0),
        )
        for points in invalid:
            with self.subTest(points=points), self.assertRaises(ValueError):
                calibration_from_loaded_points(*points)

    def test_calculation_clamps_propane_and_percentage(self) -> None:
        empty = calculate_tank_state(
            0,
            raw_zero=0,
            raw_reference=100,
            reference_weight_lb=10,
            tare_weight_lb=17,
            capacity_lb=20,
        )
        overfull = calculate_tank_state(
            1000,
            raw_zero=0,
            raw_reference=100,
            reference_weight_lb=10,
            tare_weight_lb=17,
            capacity_lb=20,
        )
        self.assertEqual(empty.propane_weight_lb, 0)
        self.assertEqual(empty.propane_percent, 0)
        self.assertEqual(overfull.propane_percent, 100)

    def test_reject_degenerate_calibration(self) -> None:
        with self.assertRaisesRegex(ValueError, "Raw reference"):
            calculate_tank_state(
                100,
                raw_zero=100,
                raw_reference=100,
                reference_weight_lb=10,
                tare_weight_lb=17,
                capacity_lb=20,
            )


if __name__ == "__main__":
    unittest.main()
