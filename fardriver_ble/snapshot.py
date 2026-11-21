"""Capture, save, load and diff controller settings snapshots. Read-only.

The only thing ever written to the controller is the app's hello/keep-alive,
through probe.safe_write and its allowlist.

A capture is complete when every parameter block has been read twice in a row
with identical values (volatile words excepted). That guards against a frame
that passed CRC but caught a value mid-update.
"""

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient

from . import names
from .decode import FLASH_READ_ADDR, HEB_ADDRS, TELEMETRY_ADDRS, frame_block, heb_main_words
from .listen import CHAR, DEVICE_INFO, Framer
from .probe import HELLO, safe_write

PARAM_BLOCKS = tuple(sorted(set(FLASH_READ_ADDR) - TELEMETRY_ADDRS))
REPO = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO / "snapshots"


@dataclass
class Snapshot:
    taken_at: str
    source: str  # "ble:<mac>" or "heb:<path>"
    words: dict[int, int]
    serial: str = ""
    device_info: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["words"] = {f"0x{a:02X}": v for a, v in sorted(self.words.items())}
        d["labels"] = {f"0x{a:02X}": names.label(a) for a in sorted(self.words) if names.label(a)}
        return json.dumps(d, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Snapshot":
        d = json.loads(text)
        d.pop("labels", None)
        d["words"] = {int(k, 16): v for k, v in d["words"].items()}
        return cls(**d)

    @classmethod
    def from_heb(cls, path: Path) -> "Snapshot":
        words = heb_main_words(Path(path).read_bytes())
        m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})", Path(path).name)  # GDriver naming
        if m:
            taken = f"{m[1]}T{m[2]}:{m[3]}:{m[4]}+00:00"
        else:
            taken = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        return cls(taken_at=taken, source=f"heb:{path}", words=words, serial=names.decode_serial(words))

    def heb_main_section(self) -> bytes:
        """The 312-byte first section of a .heb, for comparison only. NOT importable on its own."""
        return b"".join(self.words[a].to_bytes(2, "little") for a in HEB_ADDRS)


class _Collector:
    def __init__(self):
        self.framer = Framer(on_frame=self._on_frame)
        self.last: dict[int, list[int]] = {}
        self.confirmed: dict[int, list[int]] = {}
        self.reads = 0
        self.mismatches = 0

    def feed(self, data: bytes):
        self.framer.feed(data)

    def _on_frame(self, f: bytes):
        b = frame_block(f)
        if not b or b[0] in TELEMETRY_ADDRS:
            return
        addr, w = b
        self.reads += 1
        prev = self.last.get(addr)
        self.last[addr] = w
        if prev is None:
            return
        stable = all(p == x or (addr + i) in names.VOLATILE for i, (p, x) in enumerate(zip(prev, w)))
        if stable:
            self.confirmed[addr] = w
        else:
            self.mismatches += 1
            self.confirmed.pop(addr, None)

    def done(self) -> bool:
        return all(a in self.confirmed for a in PARAM_BLOCKS)


async def capture(mac: str, timeout: float = 30.0, keepalive: float = 1.0, attempts: int = 3) -> Snapshot:
    """Connect (retrying, weak signal is normal at the bike), then capture."""
    for attempt in range(1, attempts + 1):
        try:
            return await _capture_once(mac, timeout, keepalive)
        except (TimeoutError, asyncio.TimeoutError, OSError) as e:
            if attempt == attempts or "incomplete" in str(e):
                raise
            await asyncio.sleep(2)
    raise AssertionError("unreachable")


async def _capture_once(mac: str, timeout: float, keepalive: float) -> Snapshot:
    col = _Collector()
    t0 = time.monotonic()
    async with BleakClient(mac, timeout=30) as client:
        info = {}
        for key, uuid in DEVICE_INFO.items():
            try:
                v = await client.read_gatt_char(uuid)
                info[key] = v.hex() if key == "system_id" else v.decode(errors="replace").strip("\x00")
            except Exception as e:  # noqa: BLE001
                info[key] = f"<{type(e).__name__}>"
        await client.start_notify(CHAR, lambda _, d: col.feed(bytes(d)))
        writes = 0
        next_hello = 0.0
        while not col.done() and time.monotonic() - t0 < timeout:
            if time.monotonic() >= next_hello:
                await safe_write(client, HELLO, lambda _: None)
                writes += 1
                next_hello = time.monotonic() + keepalive
            await asyncio.sleep(0.05)
        await client.stop_notify(CHAR)

    if not col.done():
        missing = [f"0x{a:02X}" for a in PARAM_BLOCKS if a not in col.confirmed]
        raise TimeoutError(f"incomplete after {timeout:.0f}s; blocks not confirmed: {missing}")

    words = {a + i: v for a, w in col.confirmed.items() for i, v in enumerate(w)}
    return Snapshot(
        taken_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=f"ble:{mac}",
        words=words,
        serial=names.decode_serial(words),
        device_info=info,
        stats={
            "seconds": round(time.monotonic() - t0, 1),
            "hello_writes": writes,
            "block_reads": col.reads,
            "unstable_reads": col.mismatches,
            "bad_crc": col.framer.bad_crc,
        },
    )


def save(snap: Snapshot, root: Path = DEFAULT_DIR, label: str = "") -> Path:
    stamp = snap.taken_at.replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    name = stamp + (f"_{label}" if label else "")
    d = Path(root) / name
    d.mkdir(parents=True, exist_ok=False)
    (d / "snapshot.json").write_text(snap.to_json())
    (d / "heb_main_section.bin.NOT_IMPORTABLE").write_bytes(snap.heb_main_section())
    return d


def load(ref: str | Path, root: Path = DEFAULT_DIR) -> Snapshot:
    """Load by snapshot dir, snapshot.json, .heb path, or a dir name under root."""
    p = Path(ref)
    if not p.exists():
        p = Path(root) / str(ref)
    if p.suffix.lower() == ".heb":
        return Snapshot.from_heb(p)
    if p.is_dir():
        p = p / "snapshot.json"
    return Snapshot.from_json(p.read_text())


def list_snapshots(root: Path = DEFAULT_DIR) -> list[dict]:
    out = []
    for d in sorted(Path(root).glob("*/snapshot.json")):
        s = Snapshot.from_json(d.read_text())
        out.append({"name": d.parent.name, "taken_at": s.taken_at, "serial": s.serial, "source": s.source})
    return out


def diff(old: Snapshot, new: Snapshot) -> dict:
    """Changes grouped: settings first, then controller-maintained words."""
    common = sorted(set(old.words) & set(new.words))
    changes = [(a, old.words[a], new.words[a]) for a in common if old.words[a] != new.words[a]]

    def row(a, o, n):
        return {"addr": f"0x{a:02X}", "label": names.label(a), "old": o, "new": n}

    # Words the app's own backup leaves out are runtime data, not settings.
    maintained = names.VOLATILE | names.LIKELY_CONTROLLER_MAINTAINED | (set(common) - set(HEB_ADDRS))
    return {
        "old": {"taken_at": old.taken_at, "source": old.source, "serial": old.serial},
        "new": {"taken_at": new.taken_at, "source": new.source, "serial": new.serial},
        "compared_words": len(common),
        "same_controller": bool(old.serial) and old.serial == new.serial,
        "setting_changes": [row(*c) for c in changes if c[0] not in maintained],
        "controller_maintained_changes": [row(*c) for c in changes if c[0] in maintained],
    }


def format_diff(d: dict) -> str:
    lines = [
        f"{d['old']['taken_at']} ({d['old']['source']})  ->  {d['new']['taken_at']} ({d['new']['source']})",
        f"serial {d['old']['serial'] or '?'} -> {d['new']['serial'] or '?'}; {d['compared_words']} words compared",
    ]
    for title, key in (("Setting changes", "setting_changes"), ("Controller-maintained", "controller_maintained_changes")):
        rows = d[key]
        lines.append(f"\n{title}: {len(rows) or 'none'}")
        for r in rows:
            lines.append(f"  {r['addr']}  {r['old']:>6} -> {r['new']:<6}  {r['label']}")
    return "\n".join(lines)
