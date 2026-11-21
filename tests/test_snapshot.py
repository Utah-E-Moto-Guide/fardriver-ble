import tempfile
import unittest
from pathlib import Path

from fardriver_ble import snapshot as snap

REPO = Path(__file__).resolve().parent.parent
RUN3 = REPO / "captures/2026-11-21-run3/raw_notifications.txt"


def replay(path: Path) -> snap._Collector:
    col = snap._Collector()
    for line in open(path):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "RX":
            col.feed(bytes.fromhex(parts[2]))
    return col


class CollectorTest(unittest.TestCase):
    def test_run3_replay_completes(self):
        col = replay(RUN3)
        self.assertTrue(col.done())
        self.assertEqual(col.framer.bad_crc, 0)

    def test_needs_two_matching_reads(self):
        col = snap._Collector()
        self.assertFalse(col.done())
        self.assertEqual(col.confirmed, {})


class SnapshotRoundTripTest(unittest.TestCase):
    def make(self):
        col = replay(RUN3)
        words = {a + i: v for a, w in col.confirmed.items() for i, v in enumerate(w)}
        return snap.Snapshot("2026-11-21T20:00:00+00:00", "test", words, serial="X")

    def test_save_load_and_section(self):
        s = self.make()
        self.assertEqual(len(s.heb_main_section()), 312)
        with tempfile.TemporaryDirectory() as d:
            p = snap.save(s, Path(d), "t")
            self.assertTrue((p / "heb_main_section.bin.NOT_IMPORTABLE").exists())
            self.assertFalse(any(p.glob("*.heb")))
            back = snap.load(p)
            self.assertEqual(back.words, s.words)
            self.assertEqual(snap.list_snapshots(Path(d))[0]["name"], p.name)

    def test_diff_groups_changes(self):
        a = self.make()
        b = snap.Snapshot(a.taken_at, "test", dict(a.words), serial="X")
        b.words[0x1C] = a.words[0x1C] + 1  # a setting
        b.words[0xF5] = a.words[0xF5] + 1  # volatile
        d = snap.diff(a, b)
        self.assertEqual([r["field"] for r in d["changes"]["setting"]], ["Battery capacity"])
        self.assertEqual([r["addr"] for r in d["changes"]["live"]], ["0xF5"])
        self.assertTrue(d["same_controller"])


if __name__ == "__main__":
    unittest.main()
