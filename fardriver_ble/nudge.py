"""Nudge one safe setting by one step, the way the app does, and verify it.

Guardrails:
- Only fields listed in NUDGEABLE (whole-word, risk "safe", with the app's own limits).
- One step from the current value, or back to a value from an earlier snapshot.
- Save is opt-in (--save) and only after a pre-save check: working memory must differ from
  the snapshot taken just before the nudge in exactly the one intended setting. Save sends what
  the app's Save button sends: the local date/time to 0x22, then `88 04` (system command 04,
  save to flash) to 0xA0. No other command can be sent to 0xA0.
- The setting frame is built and checked here (setting_frame), not via probe's fixed allowlist;
  it is the only code path that can write a setting.
- Snapshot before and after, and read the new value back from the live stream.

Verified 2026-11-21: an unsaved write is RAM-only; a power cycle restores the saved value.

Usage: python -m fardriver_ble.nudge <mac> "<field name>" <new value> [--restore-from SNAPSHOT]
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient

from . import snapshot as snap
from .address_map import FIELDS, risk
from .decode import frame_block
from .listen import CHAR, Framer
from .probe import HELLO, safe_write

# field name -> (min, max) from the app's own input checks
NUDGEABLE = {
    "Throttle acceleration step": (2, 224),
}
FORBIDDEN_ADDRS = {0xA0, 0x22, 0x23, 0x24}  # command register and save stamp


def _field(name: str):
    f = next(f for f in FIELDS if f.name == name)
    assert f.bits == 16 and f.lo == 0, "only whole-word fields can be nudged"
    return f


def setting_frame(name: str, value: int) -> bytes:
    """The app's single-setting address write: AA C6 addr addr lo hi crc16."""
    if name not in NUDGEABLE:
        raise PermissionError(f"{name!r} is not nudgeable")
    f = _field(name)
    if risk(f) != "safe" or f.addr in FORBIDDEN_ADDRS:
        raise PermissionError(f"{name!r} is not a safe field")
    lo, hi = NUDGEABLE[name]
    if not lo <= value <= hi:
        raise ValueError(f"{value} outside the app's range {lo}..{hi}")
    from .crc import crc16_bytes

    body = bytes([0xAA, 0xC6, f.addr, f.addr, value & 0xFF, value >> 8])
    return body + crc16_bytes(body)


def check_step(name: str, current: int, new: int, restore_value: int | None) -> None:
    if new == restore_value:
        return
    if abs(new - current) != 1:
        raise ValueError(f"{name}: {current} -> {new} is more than one step (use --restore-from to go back)")


async def _write_and_verify(mac: str, name: str, value: int, log_dir: Path, timeout: float = 25.0) -> dict:
    f = _field(name)
    frame = setting_frame(name, value)
    block = max(b for b in snap.PARAM_BLOCKS if b <= f.addr)  # the stream block holding this word
    seen_new = 0
    started = False
    log_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(log_dir / "raw_notifications.txt", "w") as raw:

        def log(line):
            raw.write(f"{time.monotonic() - t0:8.3f} {line}\n")

        def on_frame(fr: bytes):
            nonlocal seen_new, started
            b = frame_block(fr)
            if b and b[0] == block:
                started = True
                if b[1][f.addr - block] == value and wrote:
                    seen_new += 1

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
            while time.monotonic() - t_read < timeout and seen_new < 2:
                if time.monotonic() >= next_hello:
                    await safe_write(client, HELLO, log)
                    next_hello = time.monotonic() + 1.0
                if started and not wrote:
                    log(f"TX {frame.hex()}  ({name} -> {value})")
                    await client.write_gatt_char(CHAR, frame, response=False)
                    wrote = True
                await asyncio.sleep(0.05)
            await client.stop_notify(CHAR)
        finally:
            await client.disconnect()
    return {"wrote": wrote, "frame": frame.hex(), "read_back_twice": seen_new >= 2}


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
    mac: str, name: str, value: int, label: str, restore_from: str | None = None, save: bool = False
) -> dict:
    restore_value = None
    if restore_from:
        restore_value = _field(name).value(snap.load(restore_from).words[_field(name).addr])
    before = await snap.capture(mac)
    current = _field(name).value(before.words[_field(name).addr])
    check_step(name, current, value, restore_value)
    bdir = snap.save(before, label=f"{label}-before")
    result = await _write_and_verify(mac, name, value, snap.REPO / "captures" / f"{bdir.name}-write")
    after = await snap.capture(mac)
    adir = snap.save(after, label=f"{label}-after")
    out = {"field": name, "from": current, "to": value, **result, "before": bdir.name, "after": adir.name}
    if save:
        problems = presave_check(before, after, name, value)
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
    ap.add_argument("value", type=int)
    ap.add_argument("--label", default="nudge")
    ap.add_argument("--restore-from", default=None)
    ap.add_argument("--save", action="store_true", help="save to flash after a clean pre-save check")
    a = ap.parse_args()
    r = asyncio.run(nudge(a.mac, a.field, a.value, a.label, a.restore_from, a.save))
    print(r.pop("diff"))
    print(json.dumps(r, indent=2))
