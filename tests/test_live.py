import unittest

from trailtune import live

from . import CAPTURES

RUN3 = CAPTURES / "2026-11-21-run3/raw_notifications.txt"


def replay(path) -> live.LiveCollector:
    col = live.LiveCollector()
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "RX":
            col.feed(bytes.fromhex(parts[2]), t=float(parts[0]))
    return col


class LiveTest(unittest.TestCase):
    def test_run3_gives_timestamped_samples(self):
        col = replay(RUN3)
        self.assertGreater(len(col.samples), 50)
        ts = [s["t"] for s in col.samples]
        self.assertEqual(ts, sorted(ts))
        later = col.samples[-1]
        self.assertTrue(70 <= later["volts"] <= 90, later["volts"])  # 72 V pack at rest
        self.assertFalse(later["brake"])
        self.assertEqual(later["faults"], [])
        self.assertEqual(set(later["raw"]), {f"0x{a:02X}" for a in live.TELEMETRY_WORDS})

    def test_brake_bit_is_not_a_fault(self):
        s = live.sample({0xE3: 0x8000, 0xE5: 0, 0xE8: 820})
        self.assertTrue(s["brake"])
        self.assertEqual(s["faults"], [])
        self.assertEqual(s["volts"], 82.0)

    def test_unnamed_fault_bits_are_reported(self):
        s = live.sample({0xE3: 1 << 12})
        self.assertEqual(len(s["faults"]), 1)

    def test_summary_thins_timeline(self):
        col = replay(RUN3)
        summ = live.summarize(col.samples, every=1.0)
        self.assertEqual(summ["samples"], len(col.samples))
        self.assertLessEqual(len(summ["timeline"]), col.samples[-1]["t"] + 2)
        self.assertIsNotNone(summ["volts_range"])


class CurrentTest(unittest.TestCase):
    def test_battery_current_is_signed(self):
        self.assertEqual(live.sample({0xEA: 0xFFF7})["current"], -9)
        self.assertEqual(live.sample({0xEA: 68})["current"], 68)
        self.assertEqual(live.sample({0xEA: 0xFFE4})["amps_est"], -7.0)

    def test_summary_reports_current_while_braking(self):
        samples = [
            {"t": 0.0, **live.sample({0xE3: 0, 0xE5: 900, 0xE8: 813, 0xEA: 7})},
            {"t": 0.2, **live.sample({0xE3: 0x8000, 0xE5: 500, 0xE8: 816, 0xEA: 0xFFF7})},
        ]
        summ = live.summarize(samples)
        self.assertEqual(summ["current_range"], [-9, 7])
        self.assertEqual(summ["current_while_braking"], [-9, -9])
        self.assertEqual(summ["amps_est_while_braking"], [-2.25, -2.25])
