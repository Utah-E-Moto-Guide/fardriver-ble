import os
import unittest

from trailtune import controllers, policy
from trailtune import snapshot as snap

from . import SNAPSHOTS

BASE = snap.load(SNAPSHOTS / "2026-11-21T211233Z_full-baseline")
SPECS = policy.specs(policy.factory_values(BASE))


def other_firmware(words, software=81):
    w = dict(words)
    w[0x87] = (software << 8) | (w[0x87] & 0xFF)  # "Software version" is the high byte of 0x87
    return w


class FirmwareGateTest(unittest.TestCase):
    def tearDown(self):
        os.environ["TRAILTUNE_ALLOW_UNTESTED"] = ""

    def test_fixture_identity(self):
        ident = controllers.identity(BASE.words)
        self.assertEqual(controllers.key(ident), "HA80")
        self.assertEqual((ident["custom_code"], ident["special_code"], ident["max_voltage"]), ("WC", "Z", 72))
        self.assertNotIn("serial", ident)

    def test_verified_firmware_can_write(self):
        controllers.write_gate(BASE.words, SPECS)  # no exception

    def test_unverified_firmware_is_read_only_by_default(self):
        with self.assertRaises(PermissionError) as e:
            controllers.write_gate(other_firmware(BASE.words), SPECS)
        self.assertIn("HA81", str(e.exception))
        self.assertIn("allow_untested_firmware", str(e.exception))

    def test_opt_in_allows_plausible_untested_firmware(self):
        os.environ["TRAILTUNE_ALLOW_UNTESTED"] = "1"
        controllers.write_gate(other_firmware(BASE.words), SPECS)

    def test_opt_in_still_refuses_an_implausible_layout(self):
        os.environ["TRAILTUNE_ALLOW_UNTESTED"] = "1"
        w = other_firmware(BASE.words)
        f = policy.NAMES["Battery capacity"]
        w[f.addr] = 4000  # far outside 20..250 Ah: this word means something else on this firmware
        with self.assertRaises(PermissionError) as e:
            controllers.write_gate(w, SPECS)
        self.assertIn("Battery capacity", str(e.exception))

    def test_verified_list_entries_are_complete(self):
        for v in controllers.verified_list():
            for k in ("firmware", "software", "model", "verified", "tested"):
                self.assertIn(k, v)


if __name__ == "__main__":
    unittest.main()
