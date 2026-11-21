import unittest

from fardriver_ble import snapshot as snap
from fardriver_ble import tune
from fardriver_ble.address_map import FIELDS
from fardriver_ble.nudge import NUDGEABLE

NAMES = {f.name for f in FIELDS}
SOURCES = {"manual", "app", "export", "owner", "session", "community", "reasoning"}


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.k = tune.knowledge()

    def test_every_field_exists_in_the_map(self):
        for e in self.k["settable"] + self.k["context"]:
            self.assertIn(e["field"], NAMES)

    def test_settable_matches_allow_list(self):
        self.assertEqual({e["field"] for e in self.k["settable"]}, set(NUDGEABLE))
        for e in self.k["settable"]:
            self.assertEqual(tuple(e["raw_range"]), NUDGEABLE[e["field"]], e["field"])

    def test_every_note_is_sourced(self):
        for e in self.k["settable"] + self.k["context"]:
            for n in e["notes"]:
                self.assertIn(n["source"], SOURCES, e["field"])
                self.assertIn(n["confidence"], {"high", "medium", "low"}, e["field"])


class AuditTest(unittest.TestCase):
    def test_baseline_flags(self):
        flags = {f["id"] for f in tune.audit(snap.load("2026-11-21T211233Z_full-baseline"))}
        self.assertIn("low_voltage_cutoff", flags)  # 60 V vs manual 63 V for 72 V
        self.assertIn("regen_ratio", flags)  # 2 A / 4 A = +100%
        self.assertIn("throttle_full_alarm", flags)


if __name__ == "__main__":
    unittest.main()
