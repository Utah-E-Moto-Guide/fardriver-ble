"""Watch the controller's live telemetry for a while. Read-only.

The controller streams three telemetry blocks (0xE2, 0xE8, 0xEE: 18 words) every 7 frames, several
times a second, for as long as it gets the hello/keep-alive. Snapshots skip them; this keeps them, with
a timestamp, so you can see motor RPM, battery voltage, the brake signal and fault bits change while
the rider does something (twist the throttle on the stand, pull a lever).

Writes go only through probe.safe_write (the hello). Every notification is logged raw to
<data>/captures/<time>_live-<label>/ next to the decoded samples.

Known words: 0xE3 fault bits (bit 15 = brake signal), 0xE5 motor speed (RPM), 0xE8 battery voltage
(x0.1 V), 0xEA battery current (signed: + draw, - regen charging). The rest are recorded raw so they can
be identified.

Battery current comes out twice: `current` is the raw reading and `amps_est` is that times AMPS_PER_UNIT
(about 0.25 A per unit, worked out from stand tests, not yet checked with a meter). Read `amps_est` as
amps; keep `current` for comparing captures.
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import address_map, paths
from .decode import TELEMETRY_ADDRS, frame_block
from .listen import CHAR, Framer
from .probe import HELLO, safe_write

# 0xEA scale, estimated 2026-11-22: the regen reading scaled with the setting (-9 at 2 A, -28 at 6 A,
# ~4.5 units per set amp), and 6 units holding 2100 RPM free on the stand is ~120 W at 0.25 A/unit
# (an implausible ~490 W at 1 A). See docs/protocol.md "Live telemetry and regen".
AMPS_PER_UNIT = 0.25

TELEMETRY_WORDS = tuple(a + i for a in sorted(TELEMETRY_ADDRS) for i in range(6))


def _signed(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class LiveCollector:
    """Turns frames into timestamped samples: one per telemetry block received."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.t0 = clock()
        self.framer = Framer(on_frame=self._on_frame)
        self.words: dict[int, int] = {}
        self.samples: list[dict] = []

    def feed(self, data: bytes, t: float | None = None):
        self._t = self.clock() - self.t0 if t is None else t
        self.framer.feed(data)

    def _on_frame(self, f: bytes):
        b = frame_block(f)
        if not b or b[0] not in TELEMETRY_ADDRS:
            return
        addr, w = b
        for i, v in enumerate(w):
            self.words[addr + i] = v
        self.samples.append({"t": round(self._t, 3), **sample(self.words)})


def sample(words: dict[int, int]) -> dict:
    """Decode the known telemetry words; keep every telemetry word raw as well."""
    e3 = words.get(0xE3, 0)
    out = {
        "rpm": _signed(words[0xE5]) if 0xE5 in words else None,
        "volts": round(words[0xE8] * 0.1, 1) if 0xE8 in words else None,
        "current": _signed(words[0xEA]) if 0xEA in words else None,
        "brake": address_map.brake_on(e3),
        "faults": [address_map.FAULTS.get(b, f"bit {b}") for b in range(16) if e3 & address_map.FAULT_MASK & (1 << b)],
    }
    out["amps_est"] = None if out["current"] is None else round(out["current"] * AMPS_PER_UNIT, 2)
    out["raw"] = {f"0x{a:02X}": words[a] for a in TELEMETRY_WORDS if a in words}
    return out


def summarize(samples: list[dict], every: float = 1.0) -> dict:
    """Ranges of each word, and a timeline thinned to about one sample per `every` seconds."""
    ranges: dict[str, list[int]] = {}
    for s in samples:
        for k, v in s["raw"].items():
            lo, hi = ranges.get(k, [v, v])
            ranges[k] = [min(lo, v), max(hi, v)]
    timeline, next_t = [], None
    for s in samples:
        if next_t is None or s["t"] >= next_t:
            changing = {k: v for k, v in s["raw"].items() if ranges[k][0] != ranges[k][1]}
            timeline.append({k: s[k] for k in ("t", "rpm", "volts", "current", "amps_est", "brake", "faults")} | {"changing_raw": changing})
            next_t = s["t"] + every
    rpms = [s["rpm"] for s in samples if s["rpm"] is not None]
    volts = [s["volts"] for s in samples if s["volts"] is not None]
    current = [s["current"] for s in samples if s["current"] is not None]
    braking = [s["current"] for s in samples if s["brake"] and s["current"] is not None]

    def span(xs, scale=1.0):
        return [round(min(xs) * scale, 2), round(max(xs) * scale, 2)] if xs else None

    return {
        "samples": len(samples),
        "rpm_range": [min(rpms), max(rpms)] if rpms else None,
        "volts_range": [min(volts), max(volts)] if volts else None,
        "current_range": span(current),
        "current_while_braking": span(braking),
        "amps_est_range": span(current, AMPS_PER_UNIT),
        "amps_est_while_braking": span(braking, AMPS_PER_UNIT),
        "amps_per_unit": AMPS_PER_UNIT,
        "brake_seen": any(s["brake"] for s in samples),
        "faults_seen": sorted({f for s in samples for f in s["faults"]}),
        "raw_ranges": {k: v for k, v in ranges.items()},
        "timeline": timeline,
    }


async def watch(mac: str, seconds: float = 30.0, label: str = "", keepalive: float = 1.0,
                root: Path | None = None, attempts: int = 5) -> dict:
    """Connect, keep the stream alive for `seconds` after connecting, save and summarize."""
    from bleak import BleakClient
    from bleak.exc import BleakError

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    outdir = (root or paths.CAPTURES) / f"{stamp}_live{'-' + label if label else ''}"
    outdir.mkdir(parents=True, exist_ok=True)
    col = LiveCollector()
    t_start = time.monotonic()
    with open(outdir / "raw_notifications.txt", "w", encoding="utf-8") as raw:

        def log(line: str):
            raw.write(f"{time.monotonic() - col.t0:8.3f} {line}\n")

        def on_notify(_, data: bytearray):
            log(f"RX {bytes(data).hex()}")
            col.feed(bytes(data))

        client = BleakClient(mac, timeout=30)
        for attempt in range(attempts):  # weak signal at the bike: connects often need a retry
            try:
                await client.connect()
                break
            except (TimeoutError, asyncio.TimeoutError, OSError, BleakError) as e:  # incl. "not found" (no advert yet)
                log(f"connect attempt {attempt + 1} failed: {type(e).__name__}")
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(2)
        connect_s = time.monotonic() - t_start
        try:
            await client.start_notify(CHAR, on_notify)
            col.t0 = time.monotonic()  # sample times count from the moment we are listening
            print(f"listening after {connect_s:.0f}s connect", file=sys.stderr, flush=True)
            end = col.t0 + seconds
            while time.monotonic() < end:
                await safe_write(client, HELLO, log)
                await asyncio.sleep(keepalive)
            await client.stop_notify(CHAR)
        finally:
            await client.disconnect()

    with open(outdir / "samples.jsonl", "w", encoding="utf-8") as f:
        for s in col.samples:
            f.write(json.dumps(s) + "\n")
    result = {
        "saved": outdir.name,
        "connect_seconds": round(connect_s, 1),
        "listen_seconds": seconds,
        "bad_crc": col.framer.bad_crc,
        **summarize(col.samples),
    }
    (outdir / "summary.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result
