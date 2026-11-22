"""A controller report to paste into a GitHub issue: model and firmware, whether this tool has
verified it, and whether the settings read sensibly. No serial number, MAC or personal data."""

import platform
import re
import sys
from importlib.metadata import PackageNotFoundError, version

from . import controllers, policy
from . import snapshot as snap


_ADDRESS = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"  # MAC (Linux, Windows)
                      r"|^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")  # CoreBluetooth UUID (macOS)


def is_address(s: str) -> bool:
    """True for a Bluetooth address as bleak takes it, False for a snapshot name or path."""
    return bool(_ADDRESS.match(s))


def _version() -> str:
    try:
        return version("trailtune")
    except PackageNotFoundError:
        return "unknown"


def build(s: "snap.Snapshot") -> dict:
    ident = controllers.identity(s.words)
    ref = snap.factory_reference(s.serial) if s.serial else None
    specs = policy.specs(policy.factory_values(ref or s))
    return {
        "controller": ident,
        "firmware_key": controllers.key(ident),
        "verified": bool(controllers.verified(ident)),
        "settings_outside_normal_ranges": controllers.implausible(s.words, specs),
        "words_read": len(s.words),
        "second_section": "complete" if len(s.second) == 192 else "missing",
        "factory_values": policy.factory_values(ref or s),
        "tool": _version(), "python": sys.version.split()[0], "os": f"{platform.system()} {platform.release()}",
    }


def markdown(r: dict) -> str:
    c = r["controller"]
    lines = [
        "### trailtune controller report",
        "",
        f"- Firmware: **{r['firmware_key']}** ({'verified' if r['verified'] else 'not verified yet'})",
        f"- Model codes: custom `{c['custom_code']}`, special `{c['special_code']}`, rated {c['max_voltage']} V, "
        f"current code {c['max_current_code']}, parameter set {c['parameter_set']}",
        f"- Read: {r['words_read']} words, second section {r['second_section']}",
        "- Settings outside normal ranges: "
        + (", ".join(r["settings_outside_normal_ranges"]) if r["settings_outside_normal_ranges"] else "none"),
        "- Factory values used for limits: " + ", ".join(f"{k} {v}" for k, v in r["factory_values"].items()),
        f"- trailtune {r['tool']}, Python {r['python']}, {r['os']}",
        "",
        "(No serial number or Bluetooth address included.)",
    ]
    return "\n".join(lines)
