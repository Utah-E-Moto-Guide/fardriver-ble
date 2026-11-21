"""What we know about individual addresses.

SETTINGS: matched by a value that appears exactly once in both the owner's a third-party app
XLSX and the matching .heb (2026-09-26), or confirmed by the owner's own changes.
Treat "value-match" names as strong guesses, not gospel.
"""

SETTINGS = {
    0x0D: ("Battery", "Empty-battery point", "value-match"),
    0x0E: ("Battery", "Full-battery point", "value-match"),
    0x12: ("Motor", "Motor calibration (Ld)", "value-match"),
    0x13: ("Combined", "Alarm-state delay", "value-match"),
    0x15: ("Gears", "High gear speed (RPM)", "value-match"),
    0x16: ("Motor", "Motor rated power (W)", "value-match"),
    0x18: ("Motor", "Motor rated speed (RPM)", "value-match"),
    0x1B: ("Motor", "Motor calibration (Lq)", "value-match"),
    0x1C: ("Battery", "Battery capacity (Ah)", "owner-confirmed change 20 -> 35"),
    0x21: ("Combined", "Combined relay and feature value", "value-match"),
    0x28: ("Gears", "Low gear speed (RPM)", "value-match"),
    0x2A: ("Gears", "Mid gear speed (RPM)", "value-match"),
    0x2B: ("Response", "Throttle deceleration (probable)", "owner-confirmed change 128 -> 64"),
    0x2E: ("Display", "Analog speed-output calibration", "value-match"),
    0x2F: ("Response", "Throttle acceleration", "value-match; owner-confirmed change 175 -> 64"),
    0x35: ("Display", "Speed-pulse calibration", "value-match"),
    0x66: ("Combined", "Temperature calibration value", "value-match"),
    0x6C: ("Gears", "Speed-limiter target (RPM)", "value-match"),
    0x9F: ("Additional", "Voltage-selection calibration", "value-match"),
    0xB5: ("One-wire display", "One-wire sequence byte 2", "value-match"),
    0xC3: ("Motor", "Torque-signal calibration", "value-match"),
    0xC5: ("Calibration", "Self-learn voltage high", "value-match"),
}

# Controller serial number, ASCII, two characters per word (low byte first).
SERIAL_ADDRS = range(0xA1, 0xAB)

# Words the controller changes by itself. Backed up, but reported apart from settings.
# Seen moving within or between live sessions (2026-11-21):
VOLATILE = {0xD8, 0xDA, 0xDC, 0xF5, 0xF6, 0xF8, 0xFB}
# Changed between Sep and Nov with no matching owner edit; likely controller-maintained:
LIKELY_CONTROLLER_MAINTAINED = {0x05, 0x1A, 0x22, 0x23, 0x24, 0x6D, 0x7D, 0x82, 0xB9, 0xD1, 0xD3}


def label(addr: int) -> str:
    if addr in SETTINGS:
        section, name, _ = SETTINGS[addr]
        return f"{section} / {name}"
    if addr in SERIAL_ADDRS:
        return "Serial number"
    if addr in VOLATILE:
        return "(changes on its own)"
    if addr in LIKELY_CONTROLLER_MAINTAINED:
        return "(likely controller-maintained)"
    from .decode import HEB_ADDRS

    if addr not in HEB_ADDRS:
        return "(runtime; not in the app's backup)"
    return ""


def decode_serial(words: dict[int, int]) -> str:
    raw = b"".join(words.get(a, 0).to_bytes(2, "little") for a in SERIAL_ADDRS)
    return raw.split(b"\x00")[0].decode("ascii", errors="replace")
