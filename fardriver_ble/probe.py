"""Send the app's hello/keep-alive and listen. The ONLY write this module can make.

The hello is the 8-byte command frame (19, 7, 1, 95) the official app sends on
connect and then repeatedly. It is a status request: no settings, flash,
password or motor command. Any other frame is refused.

Usage: python -m fardriver_ble.probe <mac> <seconds> <outdir> [--repeat SECONDS]
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from bleak import BleakClient

from .crc import command_frame
from .listen import CHAR, SETTINGS_IDS, Framer

HELLO = command_frame(19, 7, 1, 95)
ALLOWED_WRITES = {HELLO}


async def safe_write(client: BleakClient, data: bytes, log):
    if data not in ALLOWED_WRITES:
        raise PermissionError(f"refusing to write {data.hex()}: not on the allowlist")
    log(f"TX {data.hex()}")
    await client.write_gatt_char(CHAR, data, response=False)


async def probe(mac: str, seconds: float, outdir: Path, repeat: float | None) -> dict:
    framer = Framer()
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(outdir / "raw_notifications.txt", "w") as raw:

        def log(line: str):
            raw.write(f"{time.monotonic() - t0:8.3f} {line}\n")

        def on_notify(_, data: bytearray):
            log(f"RX {bytes(data).hex()}")
            framer.feed(bytes(data))

        async with BleakClient(mac, timeout=30) as client:
            await client.start_notify(CHAR, on_notify)
            await asyncio.sleep(1.0)
            await safe_write(client, HELLO, log)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                await asyncio.sleep(repeat or 0.25)
                if repeat:
                    await safe_write(client, HELLO, log)
            await client.stop_notify(CHAR)

    summary = {
        "seconds": seconds,
        "repeat": repeat,
        "valid_frames": sum(framer.ids.values()),
        "bad_crc": framer.bad_crc,
        "old_format_frames": framer.old_format,
        "frame_ids_seen": dict(sorted(framer.ids.items())),
        "settings_frames_seen": sorted(framer.settings),
        "settings_frames_missing": [i for i in SETTINGS_IDS if i not in framer.settings],
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (outdir / "settings_frames.json").write_text(json.dumps(framer.settings, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mac")
    ap.add_argument("seconds", type=float)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--repeat", type=float, default=None, help="resend the hello every N seconds")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(probe(a.mac, a.seconds, a.outdir, a.repeat)), indent=2))
