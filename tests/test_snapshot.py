import tempfile
import unittest
from pathlib import Path

from trailtune import snapshot as snap

from . import CAPTURES, SNAPSHOTS

RUN3 = CAPTURES / "2026-11-21-run3/raw_notifications.txt"


def replay(path: Path) -> snap._Collector:
    col = snap._Collector()
    for line in open(path, encoding="utf-8"):
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


class SecondSectionTest(unittest.TestCase):
    def test_run5_replay_reads_second_section(self):
        col = replay(CAPTURES / "2026-11-21-run5-request56/raw_notifications.txt")
        self.assertTrue(col.done())
        self.assertTrue(col.second_done())
        second = col.second_words()
        self.assertEqual(len(second), 192)
        # Same as the September export: only words 17 and 19 non-zero.
        self.assertEqual({i: v for i, v in enumerate(second) if v}, {17: 61440, 19: 64})
        words = {a + i: v for a, w in col.confirmed.items() for i, v in enumerate(w)}
        s = snap.Snapshot("2026-11-21T21:10:00+00:00", "replay", words, second=second)
        heb = s.heb()
        self.assertEqual(len(heb), 696)
        self.assertEqual(snap.Snapshot.from_json(s.to_json()).heb(), heb)


class FactoryReferenceTest(unittest.TestCase):
    def test_set_and_load_by_serial(self):
        s = snap.load(SNAPSHOTS / "2026-11-21T211233Z_full-baseline")
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(snap.factory_reference(s.serial, Path(d)))
            snap.set_factory_reference(s, "test", Path(d))
            back = snap.factory_reference(s.serial, Path(d))
            self.assertEqual(back.words, s.words)
            self.assertEqual(snap.factory_references(Path(d))[0]["serial"], s.serial)

    def test_no_serial_refused(self):
        s = snap.load(SNAPSHOTS / "2026-11-21T211233Z_full-baseline")
        s.serial = ""
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            snap.set_factory_reference(s, "test", Path(d))

    def test_tests_use_a_throwaway_data_dir(self):
        from trailtune import paths

        self.assertIn("trailtune-test-", str(paths.DATA))

    def test_old_data_folder_still_used(self):
        import os
        import tempfile as tf
        from unittest import mock

        from trailtune import paths

        with tf.TemporaryDirectory() as base, mock.patch.dict(os.environ, {"TRAILTUNE_DATA": "", "XDG_DATA_HOME": base}), \
                mock.patch("sys.platform", "linux"):
            self.assertEqual(paths.data_dir().name, "trailtune")  # neither exists: the new name
            (Path(base) / "fardriver-ble").mkdir()
            self.assertEqual(paths.data_dir().name, "fardriver-ble")  # only the old one: keep using it
            (Path(base) / "trailtune").mkdir()
            self.assertEqual(paths.data_dir().name, "trailtune")  # both: the new one wins

    def test_latest_explains_when_empty(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            snap.latest(Path(d))


if __name__ == "__main__":
    unittest.main()
