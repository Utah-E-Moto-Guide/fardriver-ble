import unittest

from trailtune import nudge, policy
from trailtune.crc import crc16_bytes

from . import SNAPSHOTS


class NudgeGuardTest(unittest.TestCase):
    def test_bit_field_keeps_other_bits(self):
        # a fake 4-bit field at bits 4-7 via the real helper's masking logic
        from trailtune.address_map import Field

        f = Field(0x99, "t", "setting", 4, 4)
        mask = ((1 << f.bits) - 1) << f.lo
        self.assertEqual((0xABCD & ~mask & 0xFFFF) | (3 << f.lo), 0xAB3D)

    def test_frame_matches_app_format(self):
        body = bytes.fromhex("aac62f2f4100")  # throttle accel = 65
        self.assertEqual(nudge.setting_frame("Throttle acceleration step", 65), body + crc16_bytes(body))

    def test_never_fields_refused(self):
        for name in ("Low-voltage cutoff", "Motor pole pairs", "Brake input mode (4 = brake disabled)",
                     "Motor matching LM (smoothness; manual default 22)", "Over-voltage cutoff", "Side-stand input pin"):
            with self.assertRaises(PermissionError):
                nudge.setting_frame(name, 1)

    def test_app_range_enforced(self):
        for v in (0, 1, 225, 1000):
            with self.assertRaises(ValueError):
                nudge.setting_frame("Throttle acceleration step", v)

    def test_energy_feedback_only_off_or_brake_regen(self):
        name = "Energy feedback (0 follow, 1 off, 2 brake regen, 3 throttle-off regen)"
        self.assertEqual(nudge.raw_range(name, policy.specs(None)), (1, 2))
        word = 0x2B09  # baseline 0x1A: feedback 1 (off), ECO 2, speed pulses 11, gear mode 1
        self.assertEqual(nudge.new_word(name, 2, word), 0x2B0A)  # other bits untouched
        for v in (0, 3):  # follow and throttle-off regen stay out of reach
            with self.assertRaises(ValueError):
                nudge.new_word(name, v, word)

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
        from trailtune import snapshot as snap

        ref = snap.load(SNAPSHOTS / "2026-11-21T215001Z_accel-65-before")
        ok = snap.load(SNAPSHOTS / "2026-11-21T215134Z_accel-65-after")
        self.assertEqual(nudge.presave_check(ref, ok, "Throttle acceleration step", 65), [])
        bad = snap.Snapshot(ok.taken_at, "test", dict(ok.words), serial=ok.serial, second=list(ok.second))
        bad.words[0x1C] += 1  # battery capacity also differs: must refuse
        self.assertTrue(nudge.presave_check(ref, bad, "Throttle acceleration step", 65))
        self.assertTrue(nudge.presave_check(ref, ref, "Throttle acceleration step", 65))  # nudge missing


class AllowListTest(unittest.TestCase):
    def test_no_allowed_field_is_never_write(self):
        from trailtune.address_map import risk

        for name in nudge.NUDGEABLE:
            self.assertNotEqual(risk(nudge._field(name)), "never", name)

    def test_profile_bits_only(self):
        name = "Throttle response profile (0 Line, 1 Sport, 2 ECO)"
        word = 0x2B09  # baseline 0x1A: follow=1, profile=2 (ECO), speed pulses 11, gear mode 1
        self.assertEqual(nudge.new_word(name, 1, word), 0x2B05)  # Sport: only bits 2-3 change
        with self.assertRaises(ValueError):
            nudge.new_word(name, 3, word)

    def test_release_response_keeps_high_byte(self):
        self.assertEqual(nudge.new_word("Throttle release response", 5, 0x0000), 0x0005)

    def test_eco_acc_refused_when_zero(self):
        with self.assertRaises(PermissionError):
            nudge.new_word("ECO acceleration coefficient", 2, 0x0100)  # bits 12-15 are 0
        self.assertEqual(nudge.new_word("ECO acceleration coefficient", 3, 0x2100), 0x3100)

    def test_brake_bit_is_not_a_fault(self):
        from trailtune.address_map import FAULT_MASK, brake_on, faults

        self.assertTrue(brake_on(0x8000))  # seen on every lever pull, brake test 2026-11-22
        self.assertFalse(brake_on(0x0100))
        self.assertEqual(0x8000 & FAULT_MASK, 0)  # not reverted on
        for bit in range(15):  # every other bit still counts, named or not
            self.assertTrue((1 << bit) & FAULT_MASK, bit)
        self.assertEqual(faults(0x8100), ["9 Phase current overflow"])

    def test_watch_problems_block_save(self):
        clean = {"auto_reverted": None, "read_back_twice": True,
                 "brake_signal": {"before_write": False, "on_at_end": False}}
        self.assertEqual(nudge.watch_problems(clean), [])
        self.assertTrue(nudge.watch_problems({**clean, "brake_signal": {"on_at_end": True}}))
        self.assertTrue(nudge.watch_problems({**clean, "auto_reverted": []}))  # empty list still counts
        self.assertTrue(nudge.watch_problems({**clean, "read_back_twice": False}))


if __name__ == "__main__":
    unittest.main()
