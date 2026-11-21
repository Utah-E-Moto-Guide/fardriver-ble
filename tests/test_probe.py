import asyncio
import unittest

from fardriver_ble import probe


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, char, data, response):
        self.writes.append(data)


class ProbeAllowlistTest(unittest.TestCase):
    def test_allowlist_is_exactly_three_frames(self):
        self.assertEqual(
            probe.ALLOWED_WRITES,
            {bytes.fromhex("aa13ec07015f10ef"), bytes.fromhex("aac6abab3414c7e6"), probe.command_frame(19, 7, 10, 56)},
        )

    def test_other_pins_are_refused(self):
        client = FakeClient()
        for digits in (b"\x00\x00", b"\x12\x34", b"\x34\x15"):
            with self.assertRaises(PermissionError):
                asyncio.run(probe.safe_write(client, probe._addr_write(0xAB, digits), lambda _: None))
        self.assertEqual(client.writes, [])

    def test_other_frames_are_refused(self):
        client = FakeClient()
        with self.assertRaises(PermissionError):
            asyncio.run(probe.safe_write(client, bytes.fromhex("aac6abab3414"), lambda _: None))
        self.assertEqual(client.writes, [])

    def test_pin_and_binding_commands_are_refused(self):
        # Password confirm/change (19, 10..13) and phone binding (19, 22..35) command frames.
        from fardriver_ble.crc import command_frame

        client = FakeClient()
        for sub in [10, 11, 12, 13, *range(22, 27), *range(32, 36)]:
            with self.assertRaises(PermissionError):
                asyncio.run(probe.safe_write(client, command_frame(19, sub, 0x33, 0x34), lambda _: None))
        self.assertEqual(client.writes, [])

    def test_hello_goes_through(self):
        client = FakeClient()
        asyncio.run(probe.safe_write(client, probe.HELLO, lambda _: None))
        self.assertEqual(client.writes, [probe.HELLO])


if __name__ == "__main__":
    unittest.main()
