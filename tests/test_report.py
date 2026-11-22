import unittest

from trailtune import report
from trailtune import snapshot as snap

from . import SNAPSHOTS


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.s = snap.load(SNAPSHOTS / "2026-11-21T211233Z_full-baseline")
        self.r = report.build(self.s)
        self.md = report.markdown(self.r)

    def test_no_serial_or_address(self):
        for text in (self.md, str(self.r)):
            self.assertNotIn(self.s.serial, text)
            self.assertNotIn(self.s.source.removeprefix("ble:"), text)

    def test_content(self):
        self.assertTrue(self.r["verified"])
        self.assertEqual(self.r["firmware_key"], "HA80")
        self.assertEqual(self.r["settings_outside_normal_ranges"], [])
        self.assertIn("HA80", self.md)

    def test_address_detection(self):
        self.assertTrue(report.is_address("EA:01:01:16:31:37"))
        self.assertTrue(report.is_address("0A1B2C3D-1234-5678-9ABC-DEF012345678"))
        for name in ("2026-11-21T211233Z_full-baseline", "tune-2026-11-21-1647-baseline", "backup.heb"):
            self.assertFalse(report.is_address(name), name)


if __name__ == "__main__":
    unittest.main()
