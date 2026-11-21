"""Field-level map of the controller's memory, in our own words.

Built from reading where the official app displays each value (decompiled locally,
not kept here), cross-checked against the owner's settings export and live captures.

A word can hold several fields (bytes, nibbles, bit flags). Diffs work per field,
so a word that mixes a setting byte with a live byte is reported correctly.

Kinds:
  setting      something a tuner chooses
  calibration  factory or self-learned measurement (changes after a self-learn)
  counter      grows by itself (saves, odometer, work time, fault counts)
  stamp        a date/time the controller or app wrote
  identity     serial, version and model codes
  live         telemetry and runtime state
  command      the system-command register (0xA0): writing it runs actions such as factory reset
  binding      PIN / owner phone-number store
  unknown      read but not yet identified

Sources: the official app's display code, plus field notes in the MIT-licensed
jackhumbert/fardriver-controllers for blocks the app never displays.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    addr: int
    name: str
    kind: str
    lo: int = 0  # first bit
    bits: int = 16
    scale: float = 1.0  # displayed = raw * scale (+ offset)
    unit: str = ""
    signed: bool = False
    offset: float = 0.0

    def raw(self, word: int) -> int:
        v = (word >> self.lo) & ((1 << self.bits) - 1)
        if self.signed and v & (1 << (self.bits - 1)):
            v -= 1 << self.bits
        return v

    def value(self, word: int) -> float | int:
        v = self.raw(word) * self.scale + self.offset
        return round(v, 3) if isinstance(v, float) and not v.is_integer() else int(v)


def _w(addr, name, kind, scale=1.0, unit="", signed=False, offset=0.0):
    return Field(addr, name, kind, 0, 16, scale, unit, signed, offset)


def _lo(addr, name, kind, scale=1.0, unit="", signed=False, offset=0.0):
    return Field(addr, name, kind, 0, 8, scale, unit, signed, offset)


def _hi(addr, name, kind, scale=1.0, unit="", signed=False, offset=0.0):
    return Field(addr, name, kind, 8, 8, scale, unit, signed, offset)


def _bits(addr, lo, bits, name, kind, unit=""):
    return Field(addr, name, kind, lo, bits, 1.0, unit)


PCT128 = 100 / 128  # ratios stored as n/128

FIELDS: list[Field] = [
    # 0x00 block: sensing calibration
    _w(0x00, "Battery voltage sense coefficient", "calibration"),
    _w(0x01, "Second voltage sense coefficient", "calibration", signed=True),
    _w(0x02, "Phase A current sense coefficient", "calibration"),
    _w(0x03, "Line current sense coefficient", "calibration"),
    _w(0x04, "Phase C current sense coefficient", "calibration"),
    _w(0x05, "Settings save count", "counter"),
    # 0x06 block
    _bits(0x06, 1, 2, "Pulse output mode", "setting"),
    _bits(0x06, 4, 4, "RS485 protocol", "setting"),
    _hi(0x06, "Anti-theft code byte", "setting"),
    _lo(0x07, "Speed loop KI", "setting"),
    _hi(0x07, "Speed loop KP", "setting"),
    _lo(0x08, "Throttle closed voltage", "setting", 1 / 20, "V"),
    _hi(0x08, "Throttle full voltage", "setting", 1 / 20, "V"),
    _w(0x09, "Feature flags (throttle insert etc.)", "setting"),
    Field(0x0A, "Acceleration curve update interval", "setting", 0, 16, 2, "ms", offset=2),
    _bits(0x0B, 0, 4, "Brake input mode (4 = brake disabled)", "setting"),
    _bits(0x0B, 4, 3, "Motor temperature sensor type", "setting"),
    _bits(0x0B, 7, 1, "Phase exchange", "setting"),
    _bits(0x0B, 8, 3, "Slow-down strength", "setting"),
    _bits(0x0B, 11, 1, "Race response", "setting"),
    _bits(0x0B, 12, 1, "Current anti-theft (lock motor)", "setting"),
    _bits(0x0B, 13, 2, "Park mode", "setting"),
    _bits(0x0B, 15, 1, "Motor direction reversed", "setting"),
    # 0x0C block
    _w(0x0C, "Learned phase offset", "calibration", 0.1),
    _w(0x0D, "Empty-battery point", "setting"),
    _w(0x0E, "Full-battery point", "setting"),
    _lo(0x0F, "Current loop start KI", "setting"),
    _hi(0x0F, "Current loop mid KI", "setting"),
    _lo(0x10, "Current loop max KI", "setting"),
    _hi(0x10, "Current loop start KP", "setting"),
    _lo(0x11, "Current loop mid KP", "setting"),
    _hi(0x11, "Current loop max KP", "setting"),
    # 0x12 block: motor
    _w(0x12, "Motor inductance Ld", "calibration"),
    _w(0x13, "Alarm delay", "setting"),
    _lo(0x14, "Motor pole pairs", "setting"),
    _hi(0x14, "Word 0x14 high byte", "unknown"),
    _w(0x15, "High gear speed", "setting", unit="RPM"),
    _w(0x16, "Motor rated power", "setting", unit="W"),
    _w(0x17, "Rated battery voltage", "setting", 0.1, "V"),
    # 0x18 block
    _w(0x18, "Motor rated speed", "setting", unit="RPM"),
    _w(0x19, "High gear line current", "setting", 0.25, "A"),
    _bits(0x1A, 0, 2, "Throttle follow mode", "setting"),
    _bits(0x1A, 2, 2, "Throttle response profile (0 Line, 1 Sport, 2 ECO)", "setting"),
    _bits(0x1A, 4, 2, "Field weakening mode", "setting"),
    _bits(0x1A, 6, 2, "Config bits 6-7 (word 0x1A)", "setting"),
    _bits(0x1A, 8, 5, "Speed pulses per revolution", "setting"),
    _bits(0x1A, 13, 3, "Gear switch mode", "setting"),
    _w(0x1B, "Motor inductance Lq", "calibration"),
    _w(0x1C, "Battery capacity", "setting", unit="Ah"),
    _w(0x1D, "Battery internal resistance", "setting"),
    # 0x1E block
    _w(0x1E, "Forward/reverse speed ratio", "setting"),
    _w(0x1F, "Low-voltage cutoff", "setting", 0.1, "V"),
    _lo(0x20, "Custom code character 0", "identity"),
    _hi(0x20, "Custom code character 1", "identity"),
    _w(0x21, "Relay delay and interlock flags", "setting"),
    _lo(0x22, "Last save: year", "stamp", offset=2000),
    _hi(0x22, "Last save: month", "stamp"),
    _lo(0x23, "Last save: day", "stamp"),
    _hi(0x23, "Last save: hour", "stamp"),
    # 0x24 block
    _lo(0x24, "Last save: minute", "stamp"),
    _hi(0x24, "Last save: second", "stamp"),
    _w(0x25, "Over-voltage cutoff", "setting", 0.1, "V"),
    _w(0x26, "Boost line current", "setting", 0.25, "A"),
    _w(0x27, "Boost phase current", "setting", 0.25, "A"),
    _w(0x28, "Low gear speed", "setting", unit="RPM"),
    _w(0x29, "Reverse speed", "setting", unit="RPM"),
    # 0x2A block
    _w(0x2A, "Mid gear speed", "setting", unit="RPM"),
    _w(0x2B, "Throttle deceleration step", "setting"),
    _lo(0x2C, "Throttle release response", "setting"),
    _hi(0x2C, "Word 0x2C high byte", "unknown"),
    _w(0x2D, "High gear phase current", "setting", 0.25, "A"),
    _w(0x2E, "Analog speed output coefficient", "setting"),
    _w(0x2F, "Throttle acceleration step", "setting"),
    # 0x30 block
    _w(0x30, "Regen current (normal)", "setting", unit="A"),
    _w(0x31, "Regen current (maximum)", "setting", unit="A"),
    _lo(0x32, "Low gear line current ratio", "setting", PCT128, "%"),
    _hi(0x32, "Mid gear line current ratio", "setting", PCT128, "%"),
    _lo(0x33, "Low gear phase current ratio", "setting", PCT128, "%"),
    _hi(0x33, "Mid gear phase current ratio", "setting", PCT128, "%"),
    _w(0x34, "Stall protection time", "setting"),
    _w(0x35, "Speed pulse calibration", "setting"),
    # 0x5D block: fault history (not in the app's backup)
    *[_lo(0x5D + i // 2, f"Fault counter {i}", "counter") if i % 2 == 0 else _hi(0x5D + i // 2, f"Fault counter {i}", "counter") for i in range(12)],
    # 0x63 block
    _w(0x63, "Second line current limit", "setting"),
    _w(0x64, "Second phase current limit", "setting"),
    _lo(0x65, "Application / motor type code", "setting"),
    _hi(0x65, "Word 0x65 high byte (maybe a current multiplier)", "unknown"),
    _w(0x66, "Temperature sense coefficient", "calibration"),
    _w(0x67, "Production maximum voltage", "identity", 0.1, "V"),
    _w(0x68, "Production maximum current (ISMax)", "identity"),
    # 0x69 block: input pins (nibbles)
    _bits(0x69, 12, 4, "Boost input pin", "setting"),
    _bits(0x69, 8, 4, "Cruise input pin", "setting"),
    _bits(0x69, 4, 4, "Side-stand input pin", "setting"),
    _bits(0x69, 0, 4, "Park input pin", "setting"),
    _bits(0x6A, 12, 4, "Forward input pin", "setting"),
    _bits(0x6A, 8, 4, "Reverse input pin", "setting"),
    _bits(0x6A, 4, 4, "High speed input pin", "setting"),
    _bits(0x6A, 0, 4, "Low speed input pin", "setting"),
    _bits(0x6B, 12, 4, "Charge input pin", "setting"),
    _bits(0x6B, 8, 4, "Anti-theft input pin", "setting"),
    _bits(0x6B, 4, 4, "Seat input pin", "setting"),
    _bits(0x6B, 0, 4, "Voltage switch input pin", "setting"),
    _w(0x6C, "Speed limiter target", "setting", unit="RPM"),
    _w(0x6D, "Odometer (low word)", "counter"),
    _lo(0x6E, "Parameter set index", "identity"),
    _hi(0x6E, "Special code character", "identity"),
    # 0x7C block
    _lo(0x7C, "Feature config byte 0", "setting"),
    _hi(0x7C, "Feature config byte 1 (fast reverse etc.)", "setting"),
    _w(0x7D, "Work time (low word)", "counter"),
    _w(0x7E, "Work time (high word)", "counter"),
    _w(0x7F, "Info checksum (low word)", "identity"),
    _w(0x80, "Info checksum (high word)", "identity"),
    _w(0x81, "Odometer (high word)", "counter"),
    # 0x82 block
    _w(0x82, "Throttle voltage (live)", "live", 0.01, "V"),
    _w(0x83, "Over-voltage restore", "setting", 0.1, "V"),
    _lo(0x84, "Motor temperature limit", "setting", unit="C"),
    _hi(0x84, "Motor temperature restore", "setting", unit="C"),
    _lo(0x85, "Controller temperature limit", "setting", unit="C"),
    _hi(0x85, "Controller temperature restore", "setting", unit="C"),
    _bits(0x86, 0, 6, "CAN configuration", "setting"),
    _bits(0x86, 6, 2, "Word 0x86 bits 6-7", "unknown"),
    _hi(0x86, "Firmware version character 0", "identity"),
    _lo(0x87, "Firmware version character 1", "identity"),
    _hi(0x87, "Software version", "identity"),
    # 0x88 block: power curve, one byte per point (% of max)
    _lo(0x88, "Power curve at 0 RPM (probable)", "setting", unit="%"),
    *[
        (_hi if (3 + i) % 2 else _lo)(0x88 + (1 + i) // 2, f"Power curve at {500 * (i + 1)} RPM", "setting", unit="%")
        for i in range(18)
    ],
    # regen curve: signed byte per point, point i at i*500 RPM (0x92 low = 0 RPM .. 0x9B high = 9500 RPM).
    # Stored negative (braking); a third-party app shows the magnitude.
    *[
        (_lo if i % 2 == 0 else _hi)(0x92 + i // 2, f"Regen curve at {500 * i} RPM", "setting", unit="%", signed=True)
        for i in range(20)
    ],
    # 0x9C block
    _bits(0x9C, 0, 5, "Auxiliary input mode (AN)", "setting"),
    _bits(0x9C, 5, 1, "Relay output enabled", "setting"),
    _bits(0x9C, 6, 2, "No-load mode", "setting"),
    _bits(0x9C, 8, 6, "Low-battery limiting mode (LM)", "setting"),
    _bits(0x9C, 14, 2, "Word 0x9C bits 14-15", "unknown"),
    _w(0x9D, "Initial voltage", "calibration", signed=True),
    _w(0x9E, "Turtle-speed current coefficient", "setting"),
    _lo(0x9F, "Voltage selection ratio", "setting"),
    _hi(0x9F, "Word 0x9F high byte", "unknown"),
    _lo(0xA0, "Command register marker (0x88)", "command"),
    _hi(0xA0, "Command register: last system command (04 = save to flash)", "command"),
    *[_w(a, f"Serial number characters {2 * (a - 0xA1)}-{2 * (a - 0xA1) + 1}", "identity") for a in range(0xA1, 0xAB)],
    _w(0xAB, "PIN check register (last PIN entered; temporary)", "live"),
    # 0xAC..0xB1: PIN / owner phone-number binding store. Strings are stored as
    # chr(0xB0 + length) + text, so 0xB0 (176) means "empty". Privacy-sensitive.
    *[_w(a, f"PIN / phone binding store word {a - 0xAC}", "binding") for a in range(0xAC, 0xB2)],
    _w(0xB2, "Word 0xB2", "unknown"),
    _w(0xB3, "Word 0xB3", "unknown"),
    # 0xB2 block: one-wire display protocol
    *[(_lo if i % 2 == 0 else _hi)(0xB4 + i // 2, f"One-wire sequence byte {i}", "setting") for i in range(8)],
    _w(0xB8, "One-wire field positions", "setting"),
    _w(0xB9, "Settings checksum (firmware recomputes it on Save; same settings give the same value)", "identity"),
    _lo(0xBA, "One-wire pulse width", "setting"),
    _hi(0xBA, "One-wire pulse period", "setting"),
    _w(0xBB, "One-wire current coefficient", "setting"),
    _w(0xBC, "Park and seat release timing", "setting"),
    _lo(0xBD, "Low-SOC limit stage 1", "setting"),
    _hi(0xBD, "Low-SOC limit stage 2", "setting"),
    # 0xBE block
    _bits(0xBE, 0, 8, "Low-battery current limiting method", "setting"),
    _bits(0xBE, 8, 4, "Config bits 8-11 (word 0xBE)", "setting"),
    _bits(0xBE, 12, 4, "ECO acceleration coefficient", "setting"),
    _w(0xBF, "Boost duration", "setting", 1 / 500, "s"),
    _w(0xC0, "Boost release delay", "setting", 1 / 500, "s"),
    _w(0xC1, "Park time", "setting", 1 / 500, "s"),
    _w(0xC2, "Inverse time", "setting"),
    _w(0xC3, "Torque signal calibration", "calibration"),
    # 0xC4 block
    _w(0xC4, "Self-learn voltage low", "calibration"),
    _w(0xC5, "Self-learn voltage high", "calibration"),
    _w(0xC6, "Slow-down RPM", "setting"),
    _w(0xC7, "Start current", "setting"),
    _w(0xC8, "Throttle insert", "setting"),
    _lo(0xC9, "Exit follow speed", "setting", unit="RPM"),
    _hi(0xC9, "Reverse current ratio", "setting"),
    # 0xCA block
    _lo(0xCA, "Angle learn", "calibration"),
    _bits(0xCA, 8, 4, "Speed limit input pin", "setting"),
    _bits(0xCA, 12, 4, "Repair input pin", "setting"),
    _lo(0xCB, "CAN detect timing", "setting"),
    _hi(0xCB, "Gear and temperature mode bits", "setting"),
    _lo(0xCC, "Learn throttle", "calibration"),
    _hi(0xCC, "Speed limit minimum capacity", "setting"),
    _lo(0xCD, "Speed limit start capacity", "setting"),
    _hi(0xCD, "Speed limit by capacity", "setting"),
    _lo(0xCE, "Speed limit max coefficient", "setting"),
    _bits(0xCE, 8, 4, "Slow-down coefficient", "setting"),
    _bits(0xCE, 12, 4, "Battery type select", "setting"),
    _w(0xCF, "Reverse acceleration", "setting"),
    # 0xD0 block
    _lo(0xD0, "One-wire data byte 0", "setting"),
    _hi(0xD0, "One-wire data byte 1", "setting"),
    _lo(0xD1, "Position sensor type", "setting"),
    _hi(0xD1, "Average power (live)", "live", 4, "W"),
    _lo(0xD2, "Tire aspect ratio", "setting", unit="%"),
    _hi(0xD2, "Rim diameter", "setting", unit="in"),
    _lo(0xD3, "Average speed (live)", "live"),
    _hi(0xD3, "Tire width", "setting", unit="mm"),
    _w(0xD4, "Drivetrain reduction ratio", "setting", 0.001),
    _w(0xD5, "One-wire configuration", "setting"),
    # 0xD6 block: runtime state
    _w(0xD6, "Word 0xD6", "live"),
    _w(0xD7, "Global state 1 (hall error, auto-learn, motor running flags)", "live"),
    _w(0xD8, "Global state 2", "live"),
    _w(0xD9, "Global state 3", "live"),
    _w(0xDA, "Global state 4", "live"),
    _w(0xDB, "Motor temperature", "live", signed=True),
    # 0xDC block: more fault counters (the app also reads bit 7 of 0xE1 as a channel flag)
    # 0xDC..0xE1: the app joins these into three 32-bit values it calls Discover 20/19/18.
    # They move both ways (2540 -> 2538 on 2026-11-21), so they are live values, not counters.
    *[_w(0xDC + i, f"Discover value {20 - i // 2} ({'high' if i % 2 == 0 else 'low'} word)", "live") for i in range(6)],
    # 0xF4 / 0xFA blocks: runtime
    _w(0xF4, "Motor temperature", "live", unit="C", signed=True),
    _lo(0xF5, "Word 0xF5 low byte (scaled time?)", "live"),
    _hi(0xF5, "Battery state of charge", "live", unit="%"),
    _lo(0xF6, "Word 0xF6 low byte", "live"),
    _hi(0xF6, "Last modified: year", "live", offset=2000),
    _lo(0xF7, "Last modified: month", "live"),
    _hi(0xF7, "Last modified: day", "live"),
    _w(0xF8, "Firmware loop time, total", "live", 0.125, "us"),
    _w(0xF9, "Firmware loop time, single", "live", 0.125, "us"),
    _w(0xFA, "Phase A current zero offset", "live"),
    _w(0xFB, "Phase C current zero offset", "live"),
    _w(0xFC, "Motor stop state", "live"),
    _w(0xFD, "Word 0xFD", "live"),
    _w(0xFE, "Motor running state", "live"),
    _w(0xFF, "Word 0xFF", "live"),
]

BY_ADDR: dict[int, list[Field]] = {}
for _f in FIELDS:
    BY_ADDR.setdefault(_f.addr, []).append(_f)


def check_coverage(addrs) -> dict:
    """Bits of each address not covered by any field, and overlaps (for tests)."""
    gaps, overlaps = {}, {}
    for a in addrs:
        mask = 0
        for f in BY_ADDR.get(a, []):
            m = ((1 << f.bits) - 1) << f.lo
            if mask & m:
                overlaps[a] = True
            mask |= m
        if mask != 0xFFFF:
            gaps[a] = 0xFFFF & ~mask
    return {"gaps": gaps, "overlaps": overlaps}


def decode(words: dict[int, int]) -> list[dict]:
    out = []
    for a in sorted(words):
        for f in BY_ADDR.get(a, []):
            out.append({
                "addr": f"0x{a:02X}", "field": f.name, "kind": f.kind,
                "value": f.value(words[a]), "unit": f.unit, "risk": risk(f),
            })
    return out


def field_changes(old: dict[int, int], new: dict[int, int]) -> list[dict]:
    rows = []
    for a in sorted(set(old) & set(new)):
        if old[a] == new[a]:
            continue
        fields = BY_ADDR.get(a) or [Field(a, f"Word 0x{a:02X}", "unknown")]
        for f in fields:
            o, n = f.raw(old[a]), f.raw(new[a])
            if o != n:
                rows.append({
                    "addr": f"0x{a:02X}", "field": f.name, "kind": f.kind,
                    "old": f.value(old[a]), "new": f.value(new[a]), "unit": f.unit,
                })
    return rows


# Words that can legitimately differ between two back-to-back reads.
UNSTABLE_ADDRS = frozenset(a for a, fs in BY_ADDR.items() if any(f.kind in ("live", "counter") for f in fs))

KIND_ORDER = ("setting", "unknown", "command", "binding", "calibration", "identity", "stamp", "counter", "live")
KIND_TITLES = {
    "setting": "Setting changes",
    "unknown": "Unidentified fields that changed",
    "command": "Command register (0xA0)",
    "binding": "PIN / phone binding store",
    "calibration": "Calibration (changes after a self-learn)",
    "identity": "Identity and version",
    "stamp": "Save timestamp",
    "counter": "Counters",
    "live": "Live / runtime",
}


# --- Write risk -------------------------------------------------------------
# What is safe to change while experimenting. Nothing in this tool writes settings;
# this is for choosing what to nudge in the phone app, and for any future restore.
#   never    must not be written: commands, binding, identity, calibration, unknowns,
#            and settings that affect braking, interlocks, wiring, direction or protection
#   caution  changes how the bike rides or performs; fine to tune, not for discovery
#   safe     comfort settings; a small nudge is a harmless discovery test

SAFE_TO_NUDGE = {
    "Throttle acceleration step", "Throttle deceleration step", "Throttle release response",
    "Acceleration curve update interval", "ECO acceleration coefficient", "Throttle response profile (0 Line, 1 Sport, 2 ECO)",
}
NEVER_SETTING_WORDS = (
    "Brake", "pin", "Park", "anti-theft", "Anti-theft", "interlock", "direction", "Phase exchange",
    "cutoff", "restore", "temperature", "Temperature", "Low-voltage", "Over-voltage", "pole pairs",
    "sensor", "CAN", "RS485", "One-wire", "Battery type", "Relay", "Feature", "Config bits",
    "Second line", "Second phase", "Application", "loop K", "Speed loop", "Current loop", "Speed pulse",
    "Rated battery voltage", "Stall", "Start current", "Throttle insert", "Throttle closed", "Throttle full",
    "Auxiliary", "No-load", "Voltage selection", "Pulse output",
)


def risk(f: Field) -> str:
    if f.kind != "setting":
        return "never"
    if f.name in SAFE_TO_NUDGE:
        return "safe"
    if any(w in f.name for w in NEVER_SETTING_WORDS):
        return "never"
    return "caution"
