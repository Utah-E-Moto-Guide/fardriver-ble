import asyncio
import unittest

from trailtune import nudge, policy
from trailtune import snapshot as snap
from trailtune.address_map import faults

from . import SNAPSHOTS

BASE = "2026-11-21T211233Z_full-baseline"


FACTORY = policy.factory_values(snap.load(SNAPSHOTS / BASE))
SPECS = policy.specs(FACTORY)


def with_value(words, name, display):
    f = policy.NAMES[name]
    w = dict(words)
    w[f.addr] = nudge.new_word(name, policy.to_raw(name, display), w[f.addr], SPECS)
    return w


class PolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = snap.load(SNAPSHOTS / BASE).words

    def test_factory_state_passes(self):
        self.assertEqual(policy.violations(self.words, FACTORY), [])

    def test_currents_cannot_exceed_factory(self):
        with self.assertRaises(ValueError):  # range check
            nudge.new_word("High gear phase current", policy.to_raw("High gear phase current", 360), 0, SPECS)
        w = dict(self.words)
        w[0x2D] = 380 * 4  # crafted directly: the sanity rule still catches it
        self.assertTrue(any("above this controller's factory" in v for v in policy.violations(w, FACTORY)))

    def test_boost_not_below_max(self):
        w = with_value(self.words, "Boost phase current", 340)  # max phase stays 350
        self.assertTrue(any("boost phase" in v for v in policy.violations(w, FACTORY)))

    def test_gear_order(self):
        w = with_value(self.words, "Low gear speed", 3000)  # above mid 2800
        self.assertTrue(any("gear speeds" in v for v in policy.violations(w, FACTORY)))

    def test_power_curve_never_rises(self):
        w = with_value(self.words, "Power curve at 3000 RPM", 95)  # 2500 RPM is 90
        self.assertTrue(any("power curve" in v for v in policy.violations(w, FACTORY)))
        w = with_value(self.words, "Power curve at 3000 RPM", 85)  # lowering is fine
        self.assertEqual(policy.violations(w, FACTORY), [])

    def test_regen_order(self):
        w = with_value(self.words, "Regen current (maximum)", 1)  # below normal 2
        self.assertTrue(any("regen" in v for v in policy.violations(w, FACTORY)))

    def test_no_curve_points_at_or_above_6000(self):
        for r in range(6000, 9500, 500):
            self.assertNotIn(f"Power curve at {r} RPM", SPECS)

    def test_limits_follow_the_controller(self):
        small = {"High gear line current": 40, "High gear phase current": 120, "Boost line current": 40,
                 "Boost phase current": 120, "Speed limiter target": 4500, "Boost duration": 0}
        sp = policy.specs(small)
        self.assertEqual((sp["High gear phase current"].lo, sp["High gear phase current"].hi), (60, 120))
        self.assertLessEqual(sp["High gear line current"].max_step, 2)  # ~5% of a small controller
        self.assertEqual(sp["Speed limiter target"].hi, 4500)
        self.assertNotIn("Power curve at 4500 RPM", sp)
        with self.assertRaises(ValueError):  # the Apex's 130 A is far above this controller's 40 A
            nudge.new_word("High gear line current", policy.to_raw("High gear line current", 130), 0, sp)
        w = dict(self.words)  # the Apex fixture's 130 A breaks this controller's ceiling
        self.assertTrue(any("above this controller's factory" in v for v in policy.violations(w, small)))

    def test_no_factory_reference_locks_controller_dependent_fields(self):
        sp = policy.specs(None)
        for name in (*policy.CURRENTS, "Speed limiter target", "High gear speed", "Boost duration",
                     "Power curve at 3000 RPM"):
            self.assertNotIn(name, sp)
            with self.assertRaises(PermissionError):
                nudge.new_word(name, 1, 0)
        self.assertIn("Throttle acceleration step", sp)

    def test_high_tier_needs_acknowledgement(self):
        with self.assertRaises(PermissionError):
            asyncio.run(nudge.nudge("00:00:00:00:00:00", "High gear line current", 125))

    def test_display_units_round_trip(self):
        self.assertEqual(policy.to_raw("High gear line current", 125), 500)
        self.assertEqual(policy.to_raw("Boost duration", 10), 5000)
        self.assertEqual(policy.to_raw("Acceleration curve update interval", 100), 49)

    def test_fault_names(self):
        self.assertEqual(faults(0), [])
        self.assertEqual(faults(1 << 8), ["9 Phase current overflow"])


if __name__ == "__main__":
    unittest.main()
