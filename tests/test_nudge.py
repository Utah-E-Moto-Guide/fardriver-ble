import unittest

from fardriver_ble import nudge
from fardriver_ble.crc import crc16_bytes


class NudgeGuardTest(unittest.TestCase):
    def test_frame_matches_app_format(self):
        body = bytes.fromhex("aac62f2f4100")  # throttle accel = 65
        self.assertEqual(nudge.setting_frame("Throttle acceleration step", 65), body + crc16_bytes(body))

    def test_only_listed_safe_fields(self):
        for name in ("Battery capacity", "Low-voltage cutoff", "High gear line current", "Motor pole pairs"):
            with self.assertRaises(PermissionError):
                nudge.setting_frame(name, 1)

    def test_app_range_enforced(self):
        for v in (0, 1, 225, 1000):
            with self.assertRaises(ValueError):
                nudge.setting_frame("Throttle acceleration step", v)

    def test_one_step_or_restore(self):
        nudge.check_step("x", 64, 65, None)
        nudge.check_step("x", 64, 63, None)
        nudge.check_step("x", 70, 64, 64)  # back to a recorded value
        with self.assertRaises(ValueError):
            nudge.check_step("x", 64, 66, None)

    def test_never_touches_command_register_or_stamp(self):
        for name in nudge.NUDGEABLE:
            f = nudge._field(name)
            self.assertNotIn(f.addr, nudge.FORBIDDEN_ADDRS)


if __name__ == "__main__":
    unittest.main()
