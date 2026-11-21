import unittest

from fardriver_ble.crc import command_frame, crc16_bytes, frame_ok


class CrcTest(unittest.TestCase):
    def test_hello_frame_matches_app(self):
        self.assertEqual(command_frame(19, 7, 1, 95).hex(), "aa13ec07015f10ef")

    def test_empty_input_is_init_value(self):
        self.assertEqual(crc16_bytes(b""), bytes((0x3C, 0x7F)))

    def test_frame_round_trip(self):
        body = bytes([0xAA, 0x80 | 56] + list(range(12)))
        self.assertTrue(frame_ok(body + crc16_bytes(body)))
        self.assertFalse(frame_ok(body + b"\x00\x00"))


if __name__ == "__main__":
    unittest.main()
