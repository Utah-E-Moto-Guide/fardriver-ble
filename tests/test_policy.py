import asyncio
import unittest

from fardriver_ble import nudge, policy
from fardriver_ble import snapshot as snap
from fardriver_ble.address_map import faults

BASE = "2026-11-21T211233Z_full-baseline"


def with_value(words, name, display):
    f = policy.NAMES[name]
    w = dict(words)
    w[f.addr] = nudge.new_word(name, policy.to_raw(name, display), w[f.addr])
    return w


class PolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = snap.load(BASE).words

    def test_factory_state_passes(self):
        self.assertEqual(policy.violations(self.words), [])

    def test_currents_cannot_exceed_factory(self):
        with self.assertRaises(ValueError):  # range check
            nudge.new_word("High gear phase current", policy.to_raw("High gear phase current", 360), 0)
        w = dict(self.words)
        w[0x2D] = 380 * 4  # crafted directly: the sanity rule still catches it
        self.assertTrue(any("above factory" in v for v in policy.violations(w)))

    def test_boost_not_below_max(self):
        w = with_value(self.words, "Boost phase current", 340)  # max phase stays 350
        self.assertTrue(any("boost phase" in v for v in policy.violations(w)))

    def test_gear_order(self):
        w = with_value(self.words, "Low gear speed", 3000)  # above mid 2800
        self.assertTrue(any("gear speeds" in v for v in policy.violations(w)))

    def test_power_curve_never_rises(self):
        w = with_value(self.words, "Power curve at 3000 RPM", 95)  # 2500 RPM is 90
        self.assertTrue(any("power curve" in v for v in policy.violations(w)))
        w = with_value(self.words, "Power curve at 3000 RPM", 85)  # lowering is fine
        self.assertEqual(policy.violations(w), [])

    def test_regen_order(self):
        w = with_value(self.words, "Regen current (maximum)", 1)  # below normal 2
        self.assertTrue(any("regen" in v for v in policy.violations(w)))

    def test_no_curve_points_at_or_above_6000(self):
        for r in range(6000, 9500, 500):
            self.assertNotIn(f"Power curve at {r} RPM", policy.SPECS)

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
