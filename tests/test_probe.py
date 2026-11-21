import asyncio
import unittest

from fardriver_ble import probe


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, char, data, response):
        self.writes.append(data)


class ProbeAllowlistTest(unittest.TestCase):
    def test_only_hello_is_allowed(self):
        self.assertEqual(probe.ALLOWED_WRITES, {bytes.fromhex("aa13ec07015f10ef")})

    def test_other_frames_are_refused(self):
        client = FakeClient()
        with self.assertRaises(PermissionError):
            asyncio.run(probe.safe_write(client, bytes.fromhex("aac6abab3414"), lambda _: None))
        self.assertEqual(client.writes, [])

    def test_hello_goes_through(self):
        client = FakeClient()
        asyncio.run(probe.safe_write(client, probe.HELLO, lambda _: None))
        self.assertEqual(client.writes, [probe.HELLO])


if __name__ == "__main__":
    unittest.main()
