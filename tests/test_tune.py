import unittest

from trailtune import snapshot as snap
from trailtune import tune
from trailtune.address_map import FIELDS
from trailtune.nudge import NUDGEABLE

from . import SNAPSHOTS

NAMES = {f.name for f in FIELDS}
SOURCES = {"manual", "app", "owner", "session", "community", "reasoning"}


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.k = tune.knowledge()

    def test_every_field_exists_in_the_map(self):
        for e in self.k["settable"] + self.k["context"]:
            self.assertIn(e["field"], NAMES)

    def test_settable_notes_are_for_changeable_fields(self):
        self.assertLessEqual({e["field"] for e in self.k["settable"]}, set(NUDGEABLE))

    def test_every_note_is_sourced(self):
        notes = [(e["field"], n) for e in self.k["settable"] + self.k["context"] for n in e["notes"]]
        notes += [("safety", n) for n in self.k.get("safety", [])] + [("faults", n) for n in self.k.get("faults", [])]
        for where, n in notes:
            self.assertIn(n["source"], SOURCES, where)
            self.assertIn(n["confidence"], {"high", "medium", "low"}, where)

    def test_neutral_warning_present(self):
        self.assertTrue(any("Neutral (0)" in n["text"] for n in self.k["safety"]))


class ProfileTest(unittest.TestCase):
    def test_every_profile_loads_and_is_sourced(self):
        import os

        for name in tune.available_profiles():
            os.environ["TRAILTUNE_PROFILE"] = name
            try:
                k = tune.knowledge()
            finally:
                os.environ["TRAILTUNE_PROFILE"] = ""
            self.assertEqual(k["layers"], ["shipped", f"profile:{name}"])
            for e in k["settable"] + k["context"]:
                self.assertIn(e["field"], NAMES)
                for n in e["notes"]:
                    self.assertIn(n["source"], SOURCES, (name, e["field"]))

    def test_unknown_profile_is_an_error(self):
        import os

        os.environ["TRAILTUNE_PROFILE"] = "no-such-bike"
        try:
            with self.assertRaises(RuntimeError):
                tune.knowledge()
        finally:
            os.environ["TRAILTUNE_PROFILE"] = ""

    def test_shipped_knowledge_is_generic(self):
        k = tune.knowledge()
        self.assertEqual(k["layers"], ["shipped"])
        notes = [n for e in k["settable"] + k["context"] for n in e["notes"]]
        self.assertFalse([n for n in notes if n["source"] == "owner"])


class AuditTest(unittest.TestCase):
    def test_baseline_flags(self):
        flags = {f["id"] for f in tune.audit(snap.load(SNAPSHOTS / "2026-11-21T211233Z_full-baseline"))}
        self.assertIn("low_voltage_cutoff", flags)  # 60 V vs manual 63 V for 72 V
        self.assertIn("regen_ratio", flags)  # 2 A / 4 A = +100%
        self.assertIn("throttle_full_alarm", flags)


if __name__ == "__main__":
    unittest.main()
