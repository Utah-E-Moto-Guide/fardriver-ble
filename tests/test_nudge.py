import unittest

from fardriver_ble import nudge
from fardriver_ble.crc import crc16_bytes


class NudgeGuardTest(unittest.TestCase):
    def test_bit_field_keeps_other_bits(self):
        # a fake 4-bit field at bits 4-7 via the real helper's masking logic
        from fardriver_ble.address_map import Field

        f = Field(0x99, "t", "setting", 4, 4)
        mask = ((1 << f.bits) - 1) << f.lo
        self.assertEqual((0xABCD & ~mask & 0xFFFF) | (3 << f.lo), 0xAB3D)

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


class SaveGuardTest(unittest.TestCase):
    def test_save_frame_is_command_04_only(self):
        self.assertEqual(nudge.SAVE_COMMAND.hex(), "aac6a0a08804c50c")
        # Our builder reproduces the community-documented factory-reset frame (never sent).
        self.assertEqual(nudge._addr_frame(0xA0, bytes([0x88, 0x08])).hex(), "aac6a0a08808c509")

    def test_stamp_frame_format(self):
        from datetime import datetime

        f = nudge.save_stamp_frame(datetime(2026, 9, 27, 7, 15, 32))
        self.assertEqual(f[:10].hex(), "aaca22221a091b070f20")  # yy mm dd hh mi ss

    def test_presave_check_blocks_extra_changes(self):
        from fardriver_ble import snapshot as snap

        ref = snap.load("2026-11-21T215001Z_accel-65-before")
        ok = snap.load("2026-11-21T215134Z_accel-65-after")
        self.assertEqual(nudge.presave_check(ref, ok, "Throttle acceleration step", 65), [])
        bad = snap.Snapshot(ok.taken_at, "test", dict(ok.words), serial=ok.serial, second=list(ok.second))
        bad.words[0x1C] += 1  # battery capacity also differs: must refuse
        self.assertTrue(nudge.presave_check(ref, bad, "Throttle acceleration step", 65))
        self.assertTrue(nudge.presave_check(ref, ref, "Throttle acceleration step", 65))  # nudge missing


if __name__ == "__main__":
    unittest.main()
