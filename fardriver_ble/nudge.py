"""Change one allowed setting, the way the app does, and verify it.

Guardrails (policy in policy.py):
- Only fields in policy.SPECS, never a never-write field; limits and step sizes in display units.
- The proposed state must pass policy.violations (factory current ceiling, gear order, regen order,
  power curve never rising, ...). High-tier fields (currents, power curve) need acknowledge_risk.
- After every write the controller's fault bits (0xE3) are watched; a new fault makes the tool
  write the previous value back immediately and report it.
- Bit fields are written the way the app does: the whole word is rebuilt from a fresh
  reading, changing only the field's bits.
- One step from the current value, or back to the value in an earlier snapshot
  (restore_from), which is how a backup can be put back one setting at a time.
- Save is opt-in (--save) and only after a pre-save check: working memory must differ from
  the snapshot taken just before the nudge in exactly the one intended setting. Save sends what
  the app's Save button sends: the local date/time to 0x22, then `88 04` (system command 04,
  save to flash) to 0xA0. No other command can be sent to 0xA0.
- The setting frame is built and checked here (setting_frame), not via probe's fixed allowlist;
  it is the only code path that can write a setting.
- Snapshot before and after, and read the new value back from the live stream.

Verified 2026-11-21: an unsaved write is RAM-only; a power cycle restores the saved value.

Usage: python -m fardriver_ble.nudge <mac> "<field name>" [<raw value>] [--restore-from SNAPSHOT] [--save]
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient

from . import snapshot as snap
from . import policy
from .address_map import FIELDS, faults, risk
from .decode import frame_block
from .listen import CHAR, Framer
from .probe import HELLO, safe_write

# field name -> (min, max) RAW value, derived from the display-unit policy
NUDGEABLE = {
    n: tuple(sorted((policy.to_raw(n, s.lo), policy.to_raw(n, s.hi)))) for n, s in policy.SPECS.items()
}
REQUIRES_NONZERO = {n for n, s in policy.SPECS.items() if s.requires_nonzero}
FORBIDDEN_ADDRS = {0xA0, 0x22, 0x23, 0x24}  # command register and save stamp


def _field(name: str):
    return next(f for f in FIELDS if f.name == name)


def new_word(name: str, raw: int, current_word: int) -> int:
    """current_word with only this field's bits replaced by raw (checked against the app's range)."""
    if name not in NUDGEABLE:
        raise PermissionError(f"{name!r} is not nudgeable")
    f = _field(name)
    if risk(f) == "never" or f.addr in FORBIDDEN_ADDRS:
        raise PermissionError(f"{name!r} is a never-write field")
    if name in REQUIRES_NONZERO and f.raw(current_word) == 0:
        raise PermissionError(f"{name!r} is 0 on this controller; the app does not write it then")
    lo, hi = NUDGEABLE[name]
    if not lo <= raw <= hi:
        raise ValueError(f"{raw} outside the app's range {lo}..{hi}")
    mask = ((1 << f.bits) - 1) << f.lo
    return (current_word & ~mask & 0xFFFF) | ((raw & ((1 << f.bits) - 1)) << f.lo)


def setting_frame(name: str, raw: int, current_word: int = 0) -> bytes:
    """The app's single-setting address write: AA C6 addr addr lo hi crc16."""
    from .crc import crc16_bytes

    f = _field(name)
    w = new_word(name, raw, current_word)
    body = bytes([0xAA, 0xC6, f.addr, f.addr, w & 0xFF, w >> 8])
    return body + crc16_bytes(body)


def check_step(name: str, current: float, new: float, restore_value: float | None, max_step: float = 1) -> None:
    """Display-unit step check; going back to a recorded value is always allowed."""
    if new == restore_value:
        return
    if abs(new - current) > max_step + 1e-9:
        raise ValueError(f"{name}: {current} -> {new} is a bigger step than {max_step} (go in smaller steps)")


def _word_frame(addr: int, word: int) -> bytes:
    from .crc import crc16_bytes

    body = bytes([0xAA, 0xC6, addr, addr, word & 0xFF, word >> 8])
    return body + crc16_bytes(body)


async def _write_and_verify(
    mac: str, name: str, raw: int, current_word: int, log_dir: Path, timeout: float = 25.0, watch: float = 6.0
) -> dict:
    f = _field(name)
    frame = setting_frame(name, raw, current_word)
    target = new_word(name, raw, current_word)
    fault_before: int | None = None
    fault_after = 0
    t_readback = None
    block = max(b for b in snap.PARAM_BLOCKS if b <= f.addr)  # the stream block holding this word
    seen_new = 0
    started = False
    log_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(log_dir / "raw_notifications.txt", "w") as raw:

        def log(line):
            raw.write(f"{time.monotonic() - t0:8.3f} {line}\n")

        def on_frame(fr: bytes):
            nonlocal seen_new, started, fault_before, fault_after, t_readback
            b = frame_block(fr)
            if b and b[0] == 0xE2:  # live block: word 0xE3 holds the fault bits
                if not wrote:
                    fault_before = b[1][1]
                else:
                    fault_after |= b[1][1]
            if b and b[0] == block:
                started = True
                if b[1][f.addr - block] == target and wrote:
                    seen_new += 1
                    if seen_new >= 2 and t_readback is None:
                        t_readback = time.monotonic()

        framer = Framer(on_frame=on_frame)
        wrote = False
        client = BleakClient(mac, timeout=30)
        for attempt in range(3):
            try:
                await client.connect()
                break
            except (TimeoutError, asyncio.TimeoutError, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
        try:
            await client.start_notify(CHAR, lambda _, d: (log(f"RX {bytes(d).hex()}"), framer.feed(bytes(d))))
            t_read = time.monotonic()
            next_hello = 0.0
            auto_reverted = None
            while time.monotonic() - t_read < timeout:
                if t_readback is not None and time.monotonic() - t_readback > watch:
                    break
                if time.monotonic() >= next_hello:
                    await safe_write(client, HELLO, log)
                    next_hello = time.monotonic() + 1.0
                if started and not wrote and fault_before is not None:
                    log(f"TX {frame.hex()}  ({name} -> raw {raw}, word {target:#06x})")
                    await client.write_gatt_char(CHAR, frame, response=False)
                    wrote = True
                new_faults = fault_after & ~(fault_before or 0)
                if wrote and new_faults and auto_reverted is None:
                    back = _word_frame(f.addr, current_word)
                    log(f"TX {back.hex()}  (AUTO-REVERT after faults {faults(new_faults)})")
                    await client.write_gatt_char(CHAR, back, response=False)
                    auto_reverted = faults(new_faults)
                    break
                await asyncio.sleep(0.05)
            await client.stop_notify(CHAR)
        finally:
            await client.disconnect()
    return {
        "wrote": wrote, "frame": frame.hex(), "read_back_twice": seen_new >= 2,
        "faults_before": faults(fault_before or 0), "new_faults": faults(fault_after & ~(fault_before or 0)),
        "auto_reverted": auto_reverted,
    }


def _addr_frame(addr: int, payload: bytes) -> bytes:
    from .crc import crc16_bytes

    body = bytes([0xAA, 0xC0 + len(payload) + 4, addr, addr]) + payload
    return body + crc16_bytes(body)


SAVE_COMMAND = _addr_frame(0xA0, bytes([0x88, 0x04]))


def save_stamp_frame(now: datetime) -> bytes:
    """The app's save timestamp: yy, month, day, hour, minute, second to 0x22..0x24."""
    return _addr_frame(0x22, bytes([now.year - 2000, now.month, now.day, now.hour, now.minute, now.second]))


def presave_check(reference: "snap.Snapshot", current: "snap.Snapshot", name: str, value: int) -> list[str]:
    """Problems that block a save; empty means working memory = saved state + the one nudge."""
    d = snap.diff(reference, current)
    problems = []
    for kind in ("setting", "unknown", "command", "binding", "calibration", "identity", "stamp"):
        for r in d["changes"][kind]:
            if not (kind == "setting" and r["field"] == name and r["new"] == value):
                problems.append(f"{r['addr']} {r['field']}: {r['old']} -> {r['new']}")
    if not any(r["field"] == name for r in d["changes"]["setting"]):
        problems.append(f"{name} is not at {value} in working memory")
    if current.words.get(0x05) != reference.words.get(0x05):
        problems.append("save count changed since the reference snapshot")
    return problems


async def _send_save(mac: str, log_dir: Path) -> dict:
    now = datetime.now()
    stamp = save_stamp_frame(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(log_dir / "raw_notifications.txt", "w") as raw:

        def log(line):
            raw.write(f"{time.monotonic() - t0:8.3f} {line}\n")

        started = False

        def on_frame(_fr):
            nonlocal started
            started = True

        framer = Framer(on_frame=on_frame)
        client = BleakClient(mac, timeout=30)
        for attempt in range(3):
            try:
                await client.connect()
                break
            except (TimeoutError, asyncio.TimeoutError, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
        try:
            await client.start_notify(CHAR, lambda _, d: (log(f"RX {bytes(d).hex()}"), framer.feed(bytes(d))))
            t_read, sent, next_hello = time.monotonic(), False, 0.0
            while time.monotonic() - t_read < 15:
                if time.monotonic() >= next_hello:
                    await safe_write(client, HELLO, log)
                    next_hello = time.monotonic() + 1.0
                if started and not sent:
                    log(f"TX {stamp.hex()}  (save stamp {now.isoformat(timespec='seconds')})")
                    await client.write_gatt_char(CHAR, stamp, response=False)
                    await asyncio.sleep(0.01)
                    log(f"TX {SAVE_COMMAND.hex()}  (system command 04: save to flash)")
                    await client.write_gatt_char(CHAR, SAVE_COMMAND, response=False)
                    sent, t_sent = True, time.monotonic()
                if sent and time.monotonic() - t_sent > 3:
                    break
                await asyncio.sleep(0.05)
            await client.stop_notify(CHAR)
        finally:
            await client.disconnect()
    return {"saved": sent, "stamp": now.isoformat(timespec="seconds")}


async def nudge(
    mac: str, name: str, value: float | None = None, label: str = "nudge",
    restore_from: str | None = None, save: bool = False, acknowledge_risk: bool = False,
) -> dict:
    """Set one allowed field. value is in DISPLAY units (A, RPM, %, s, ms); value=None with
    restore_from puts back that snapshot's value for this field."""
    if name not in policy.SPECS:
        raise PermissionError(f"{name!r} is not changeable here; see fardriver_settable")
    spec = policy.SPECS[name]
    if spec.tier == "high" and not acknowledge_risk:
        raise PermissionError(f"{name!r} is high risk: explain the risk to the owner, then pass acknowledge_risk=True")
    f = _field(name)
    restore_display = f.value(snap.load(restore_from).words[f.addr]) if restore_from else None
    if value is None:
        if restore_display is None:
            raise ValueError("give a value or restore_from")
        value = restore_display
    raw = policy.to_raw(name, value)
    before = await snap.capture(mac)
    word = before.words[f.addr]
    current = f.value(word)
    if raw == f.raw(word):
        return {"field": name, "unchanged": True, "value": current, "unit": f.unit}
    check_step(name, current, policy.to_display(name, raw), restore_display, spec.max_step)
    target = new_word(name, raw, word)
    proposed = dict(before.words)
    proposed[f.addr] = target
    bad = policy.violations(proposed)
    if bad and value != restore_display:
        raise ValueError("refused by sanity rules: " + "; ".join(bad))
    bdir = snap.save(before, label=f"{label}-before")
    watch = 10.0 if spec.tier == "high" else 6.0
    result = await _write_and_verify(mac, name, raw, word, snap.REPO / "captures" / f"{bdir.name}-write", watch=watch)
    after = await snap.capture(mac)
    adir = snap.save(after, label=f"{label}-after")
    out = {
        "field": name, "tier": spec.tier, "from": current, "to": f.value(target), "unit": f.unit,
        **result, "before": bdir.name, "after": adir.name,
    }
    if save:
        problems = presave_check(before, after, name, f.value(target))
        if result.get("auto_reverted"):
            problems = [f"auto-reverted after faults {result['auto_reverted']}"] + problems
        if problems or not result["read_back_twice"]:
            out["save"] = {"refused": problems or ["new value was not read back"]}
            out["diff"] = snap.format_diff(snap.diff(before, after))
            return out
        out["save"] = await _send_save(mac, snap.REPO / "captures" / f"{adir.name}-save")
        saved = await snap.capture(mac)
        sdir = snap.save(saved, label=f"{label}-saved")
        out["saved_snapshot"] = sdir.name
        out["diff"] = snap.format_diff(snap.diff(before, saved))
        return out
    out["diff"] = snap.format_diff(snap.diff(before, after))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mac")
    ap.add_argument("field")
    ap.add_argument("value", type=float, nargs="?", default=None, help="display units")
    ap.add_argument("--label", default="nudge")
    ap.add_argument("--restore-from", default=None)
    ap.add_argument("--save", action="store_true", help="save to flash after a clean pre-save check")
    ap.add_argument("--acknowledge-risk", action="store_true", help="required for high-tier fields")
    a = ap.parse_args()
    r = asyncio.run(nudge(a.mac, a.field, a.value, a.label, a.restore_from, a.save, a.acknowledge_risk))
    print(r.pop("diff"))
    print(json.dumps(r, indent=2))
