"""Which controller firmwares are verified, and the write gate for the rest.

The address map, scales and Save behaviour were worked out on one firmware. Another firmware may
lay out its memory differently, and then a careful one-step write could land on the wrong setting:
the factory-reference limits would not catch that. So:

- verified firmware (knowledge/controllers.yml): writes allowed, under the usual policy;
- any other firmware: read-only (backups, diffs, audits) unless the rider opts in with
  `allow_untested_firmware: true` in <data>/config.yml or FARDRIVER_ALLOW_UNTESTED=1;
- even then, a write is refused if the changeable settings read outside the app's own ranges,
  the clearest sign that the memory layout differs.
"""

import os

import yaml

from . import paths
from .address_map import FIELDS

_BY_NAME = {f.name: f for f in FIELDS}
VERIFIED_FILE = paths.PACKAGE / "knowledge" / "controllers.yml"


def _v(words: dict[int, int], name: str):
    f = _BY_NAME[name]
    return f.value(words[f.addr]) if f.addr in words else None


def _ch(v) -> str:
    return chr(int(v)) if v is not None and 32 <= int(v) < 127 else "?"


def identity(words: dict[int, int]) -> dict:
    """What the controller reports about its model and firmware (no serial)."""
    return {
        "firmware": _ch(_v(words, "Firmware version character 0")) + _ch(_v(words, "Firmware version character 1")),
        "software": _v(words, "Software version"),
        "custom_code": _ch(_v(words, "Custom code character 0")) + _ch(_v(words, "Custom code character 1")),
        "special_code": _ch(_v(words, "Special code character")),
        "max_voltage": _v(words, "Production maximum voltage"),
        "max_current_code": _v(words, "Production maximum current (ISMax)"),
        "parameter_set": _v(words, "Parameter set index"),
    }


def key(ident: dict) -> str:
    return f"{ident['firmware']}{ident['software']}"


def verified_list() -> list[dict]:
    return yaml.safe_load(VERIFIED_FILE.read_text(encoding="utf-8")).get("verified") or []


def verified(ident: dict) -> dict | None:
    return next((v for v in verified_list() if f"{v['firmware']}{v['software']}" == key(ident)), None)


def allow_untested() -> bool:
    env = os.environ.get("FARDRIVER_ALLOW_UNTESTED", "")
    if env:
        return env.lower() in ("1", "true", "yes")
    return bool(paths.config().get("allow_untested_firmware"))


def implausible(words: dict[int, int], specs: dict) -> list[str]:
    """Changeable settings whose current value is outside its allowed range."""
    out = []
    for name, s in specs.items():
        v = _v(words, name)
        if v is not None and not s.lo <= v <= s.hi:
            out.append(f"{name} = {v} (expected {s.lo}..{s.hi})")
    return out


def write_gate(words: dict[int, int], specs: dict) -> None:
    """Raise PermissionError unless writes are safe to attempt on this controller."""
    ident = identity(words)
    if verified(ident):
        return
    what = f"firmware {key(ident)} ({ident['custom_code']}, {ident['max_voltage']} V)"
    if not allow_untested():
        raise PermissionError(
            f"{what} is not on the verified list, so writes are off; backups, diffs and audits still work. "
            "Its memory layout may differ from the verified firmware, and a write could land on the wrong "
            "setting. To try anyway, at your own risk, set `allow_untested_firmware: true` in "
            f"{paths.CONFIG}. Please share `fardriver-ble report <MAC>` in an issue so it can be verified.")
    bad = implausible(words, specs)
    if bad:
        raise PermissionError(
            f"{what} is untested and {len(bad)} changeable settings read outside their normal ranges "
            f"({'; '.join(bad[:4])}{'; ...' if len(bad) > 4 else ''}). The memory layout probably differs: "
            "writes refused even with allow_untested_firmware.")
