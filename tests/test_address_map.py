import unittest

from fardriver_ble import snapshot as snap
from fardriver_ble.address_map import BY_ADDR, FIELDS, check_coverage, field_changes
from fardriver_ble.decode import FLASH_READ_ADDR, TELEMETRY_ADDRS

BASELINE = "2026-11-21T202712Z_baseline"

# Values from the owner's GDriver XLSX (2026-09-26) for settings they did not change.
SHEET = {
    "High gear line current": 130, "High gear phase current": 350,
    "Boost line current": 130, "Boost phase current": 360,
    "Throttle closed voltage": 1.1, "Rated battery voltage": 72,
    "Low-voltage cutoff": 60, "Over-voltage cutoff": 90.7,
    "Motor temperature limit": 160, "Motor temperature restore": 140,
    "Motor pole pairs": 4, "Learned phase offset": 30.4,
    "High gear speed": 4200, "Mid gear speed": 2800, "Low gear speed": 1800,
    "Reverse speed": 360, "Speed limiter target": 6000,
    "Regen current (normal)": 2, "Regen current (maximum)": 4,
    "Forward/reverse speed ratio": 64, "Speed pulses per revolution": 11,
    "Tire width": 120, "Tire aspect ratio": 70, "Rim diameter": 12,
    "Drivetrain reduction ratio": 4,
    "Power curve at 500 RPM": 100, "Power curve at 1000 RPM": 98,
    "Power curve at 5000 RPM": 75, "Power curve at 5500 RPM": 1, "Power curve at 6000 RPM": 0,
    "Regen curve at 500 RPM": -10, "Regen curve at 2000 RPM": -15,
    "Regen curve at 4500 RPM": -20, "Regen curve at 5000 RPM": 0,
    "Motor rated power": 2500, "Motor rated speed": 3166, "Battery internal resistance": 32,
    "Empty-battery point": 896, "Full-battery point": 1250,
}


class AddressMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = snap.load(BASELINE).words

    def value(self, name):
        f = next(f for f in FIELDS if f.name == name)
        return f.value(self.words[f.addr])

    def test_matches_gdriver_sheet(self):
        for name, want in SHEET.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(self.value(name), want, places=6)

    def test_owner_changes(self):
        self.assertEqual(self.value("Battery capacity"), 35)
        self.assertEqual(self.value("Throttle acceleration step"), 64)
        self.assertEqual(self.value("Throttle deceleration step"), 64)

    def test_every_parameter_word_has_a_field(self):
        param = {a + k for a in set(FLASH_READ_ADDR) - TELEMETRY_ADDRS for k in range(6)}
        self.assertEqual(sorted(hex(a) for a in param - set(BY_ADDR)), [])
        self.assertEqual(check_coverage(param)["overlaps"], {})

    def test_field_changes_split_mixed_words(self):
        old = dict(self.words)
        new = dict(self.words)
        new[0xD3] = (new[0xD3] & 0xFF00) | ((new[0xD3] + 1) & 0xFF)  # only the live average-speed byte
        rows = field_changes(old, new)
        self.assertEqual([(r["field"], r["kind"]) for r in rows], [("Average speed (live)", "live")])


if __name__ == "__main__":
    unittest.main()
