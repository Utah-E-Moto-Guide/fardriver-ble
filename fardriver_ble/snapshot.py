"""Capture, save, load and diff controller settings snapshots. Read-only.

Writes go only through probe.safe_write and its allowlist: the hello/keep-alive and
the app's request for the second settings section. No setting is ever written.

A capture is complete when every parameter block and every second-section frame
(ids 56..87) has been read twice in a row with identical values (live words excepted).
That guards against a frame that passed CRC but caught a value mid-update.

A complete snapshot saves `controller.heb`, the same 696-byte format the phone apps
export (156 main words + 192 second-section words).
"""

import asyncio
import json
import re
import struct
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient

from . import address_map, names
from .decode import FLASH_READ_ADDR, HEB_ADDRS, TELEMETRY_ADDRS, frame_block, heb_main_words
from .listen import CHAR, DEVICE_INFO, Framer
from .probe import HELLO, REQUEST_SECOND_SECTION, safe_write

PARAM_BLOCKS = tuple(sorted(set(FLASH_READ_ADDR) - TELEMETRY_ADDRS))
SECOND_IDS = range(56, 88)  # 32 frames x 6 words = 192 words
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
    second: list[int] = field(default_factory=list)  # .heb second section, 192 words when read

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
        data = Path(path).read_bytes()
        words = heb_main_words(data)
        second = list(struct.unpack("<192H", data[312:696]))
        m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})", Path(path).name)  # GDriver naming
        if m:
            taken = f"{m[1]}T{m[2]}:{m[3]}:{m[4]}+00:00"
        else:
            taken = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        return cls(taken_at=taken, source=f"heb:{path}", words=words, serial=names.decode_serial(words), second=second)

    def heb_main_section(self) -> bytes:
        """The 312-byte first section of a .heb, for comparison only. NOT importable on its own."""
        return b"".join(self.words[a].to_bytes(2, "little") for a in HEB_ADDRS)

    def heb(self) -> bytes | None:
        """The full 696-byte .heb, or None if the second section wasn't read."""
        if len(self.second) != 192:
            return None
        return self.heb_main_section() + struct.pack("<192H", *self.second)


class _Collector:
    def __init__(self):
        self.framer = Framer(on_frame=self._on_frame)
        self.last: dict[int, list[int]] = {}
        self.confirmed: dict[int, list[int]] = {}
        self.reads = 0
        self.mismatches = 0
        self.last2: dict[int, bytes] = {}
        self.confirmed2: dict[int, bytes] = {}

    def feed(self, data: bytes):
        self.framer.feed(data)

    def _on_frame(self, f: bytes):
        fid = f[1] & 0x7F
        if fid in SECOND_IDS:
            prev = self.last2.get(fid)
            self.last2[fid] = f[2:14]
            if prev == f[2:14]:
                self.confirmed2[fid] = f[2:14]
            elif prev is not None:
                self.mismatches += 1
                self.confirmed2.pop(fid, None)
            return
        b = frame_block(f)
        if not b or b[0] in TELEMETRY_ADDRS:
            return
        addr, w = b
        self.reads += 1
        prev = self.last.get(addr)
        self.last[addr] = w
        if prev is None:
            return
        stable = all(p == x or (addr + i) in address_map.UNSTABLE_ADDRS for i, (p, x) in enumerate(zip(prev, w)))
        if stable:
            self.confirmed[addr] = w
        else:
            self.mismatches += 1
            self.confirmed.pop(addr, None)

    def done(self) -> bool:
        return all(a in self.confirmed for a in PARAM_BLOCKS)

    def second_done(self) -> bool:
        return all(i in self.confirmed2 for i in SECOND_IDS)

    def second_words(self) -> list[int]:
        out = []
        for i in SECOND_IDS:
            b = self.confirmed2[i]
            out += [b[k] | (b[k + 1] << 8) for k in range(0, 12, 2)]
        return out


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
        writes = requests = 0
        next_hello = 0.0
        while not (col.done() and col.second_done()) and time.monotonic() - t0 < timeout:
            if time.monotonic() >= next_hello:
                if not col.second_done() and writes % 5 == 0:
                    await safe_write(client, REQUEST_SECOND_SECTION, lambda _: None)
                    requests += 1
                    await asyncio.sleep(0.01)
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
        second=col.second_words() if col.second_done() else [],
        stats={
            "seconds": round(time.monotonic() - t0, 1),
            "second_section": "complete" if col.second_done() else f"missing {sum(i not in col.confirmed2 for i in SECOND_IDS)} frames",
            "hello_writes": writes,
            "second_section_requests": requests,
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
    full = snap.heb()
    if full:
        (d / "controller.heb").write_bytes(full)
    else:
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
    """Field-level changes grouped by kind (settings first)."""
    common = set(old.words) & set(new.words)
    rows = address_map.field_changes({a: old.words[a] for a in common}, {a: new.words[a] for a in common})
    if len(old.second) == 192 and len(new.second) == 192:
        rows += [
            {"addr": f"S{i:03d}", "field": f"Second section word {i}", "kind": "unknown", "old": o, "new": n, "unit": ""}
            for i, (o, n) in enumerate(zip(old.second, new.second)) if o != n
        ]
    groups = {k: [r for r in rows if r["kind"] == k] for k in address_map.KIND_ORDER}
    return {
        "old": {"taken_at": old.taken_at, "source": old.source, "serial": old.serial,
                "saved": names.decode_save_time(old.words), "save_count": old.words.get(0x05)},
        "new": {"taken_at": new.taken_at, "source": new.source, "serial": new.serial,
                "saved": names.decode_save_time(new.words), "save_count": new.words.get(0x05)},
        "compared_words": len(common) + (192 if len(old.second) == len(new.second) == 192 else 0),
        "same_controller": bool(old.serial) and old.serial == new.serial,
        "changes": groups,
    }


def format_diff(d: dict, show_live: bool = False) -> str:
    o, n = d["old"], d["new"]
    lines = [
        f"{o['taken_at']} ({o['source']})  ->  {n['taken_at']} ({n['source']})",
        f"serial {o['serial'] or '?'} -> {n['serial'] or '?'}; {d['compared_words']} words compared",
        f"settings last saved {o['saved']} -> {n['saved']}; save count {o['save_count']} -> {n['save_count']}",
    ]
    for kind in address_map.KIND_ORDER:
        rows = d["changes"][kind]
        if kind == "live" and not show_live:
            lines.append(f"\n{address_map.KIND_TITLES[kind]}: {len(rows)} fields changed (hidden)")
            continue
        if kind == "stamp" and rows:
            continue  # shown in the header
        if not rows and kind not in ("setting", "unknown"):
            continue
        lines.append(f"\n{address_map.KIND_TITLES[kind]}: {len(rows) or 'none'}")
        for r in rows:
            unit = f" {r['unit']}" if r["unit"] else ""
            lines.append(f"  {r['addr']}  {r['field']}: {r['old']} -> {r['new']}{unit}")
    return "\n".join(lines)
