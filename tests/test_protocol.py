"""Tests for the YSNPS1 protocol decoder and tank calculations."""

import math
import unittest

from protocol import InvalidPacketError, calculate_tank_state, decode_packet


class ProtocolTests(unittest.TestCase):
    """Validate protocol behavior against captured packets."""

    def test_decode_zero_packet_from_device(self) -> None:
        packet = decode_packet(bytes.fromhex("AA 01 00 00 64 CF"))
        self.assertEqual(packet.raw, 0)
        self.assertEqual(packet.battery, 100)

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
