"""Command line: python -m fardriver_ble {scan,snapshot,list,diff}"""

import argparse
import asyncio
import json
from pathlib import Path

from . import snapshot as snap

NAME_HINTS = ("YUANQU", "CONTROL", "BMS")


async def scan(seconds: float) -> list[dict]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        if any(h in name.upper() for h in NAME_HINTS):
            out.append({"address": dev.address, "name": name, "rssi": adv.rssi})
    return sorted(out, key=lambda d: -d["rssi"])


def main():
    ap = argparse.ArgumentParser(prog="fardriver_ble")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--seconds", type=float, default=8)
    s = sub.add_parser("snapshot")
    s.add_argument("mac")
    s.add_argument("--label", default="")
    s.add_argument("--timeout", type=float, default=30)
    s.add_argument("--dir", type=Path, default=snap.DEFAULT_DIR)
    s = sub.add_parser("list")
    s.add_argument("--dir", type=Path, default=snap.DEFAULT_DIR)
    s = sub.add_parser("diff")
    s.add_argument("old", help="snapshot name/dir or .heb file")
    s.add_argument("new", nargs="?", help="default: latest snapshot")
    s.add_argument("--json", action="store_true")
    s.add_argument("--dir", type=Path, default=snap.DEFAULT_DIR)
    a = ap.parse_args()

    if a.cmd == "scan":
        print(json.dumps(asyncio.run(scan(a.seconds)), indent=2))
    elif a.cmd == "snapshot":
        s = asyncio.run(snap.capture(a.mac, timeout=a.timeout))
        d = snap.save(s, a.dir, a.label)
        print(f"saved {d}\nserial {s.serial}  {json.dumps(s.stats)}")
    elif a.cmd == "list":
        print(json.dumps(snap.list_snapshots(a.dir), indent=2))
    elif a.cmd == "diff":
        new = a.new or snap.list_snapshots(a.dir)[-1]["name"]
        d = snap.diff(snap.load(a.old, a.dir), snap.load(new, a.dir))
        print(json.dumps(d, indent=2) if a.json else snap.format_diff(d))


if __name__ == "__main__":
    main()
