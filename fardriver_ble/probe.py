"""Send the app's hello/keep-alive and listen. The ONLY write this module can make.

Allowed writes, and nothing else:
- the hello: 8-byte command frame (19, 7, 1, 95) the app sends on connect and as a keep-alive
- entering the factory-default PIN 3414 (a check, never a change), as the app does on connect
No settings, flash, PIN-change, binding or motor command can be sent.

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


def _addr_write(addr: int, payload: bytes) -> bytes:
    from .crc import crc16_bytes

    body = bytes([0xAA, 0xC0 + len(payload) + 4, addr, addr]) + payload
    return body + crc16_bytes(body)


# Enter (not set) the factory-default PIN 3414, exactly as the app does on connect:
# digits packed two per byte, written to the PIN-check address 0xAB. A PIN check
# stores nothing; the PIN-change command is a different frame and is not allowed.
DEFAULT_PIN_ENTRY = _addr_write(0xAB, bytes([0x34, 0x14]))
assert DEFAULT_PIN_ENTRY.hex() == "aac6abab3414c7e6"

ALLOWED_WRITES = {HELLO, DEFAULT_PIN_ENTRY}


async def safe_write(client: BleakClient, data: bytes, log):
    if data not in ALLOWED_WRITES:
        raise PermissionError(f"refusing to write {data.hex()}: not on the allowlist")
    log(f"TX {data.hex()}")
    await client.write_gatt_char(CHAR, data, response=False)


async def probe(mac: str, seconds: float, outdir: Path, repeat: float | None, pin: bool = False) -> dict:
    framer = Framer()
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(outdir / "raw_notifications.txt", "w") as raw:

        def log(line: str):
            raw.write(f"{time.monotonic() - t0:8.3f} {line}\n")

        def on_notify(_, data: bytearray):
            log(f"RX {bytes(data).hex()}")
            framer.feed(bytes(data))

        client = BleakClient(mac, timeout=30)
        for attempt in range(3):  # weak signal at the bike: connects often need a retry
            try:
                await client.connect()
                break
            except (TimeoutError, asyncio.TimeoutError, OSError) as e:
                log(f"connect attempt {attempt + 1} failed: {type(e).__name__}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
        try:
            await client.start_notify(CHAR, on_notify)
            await asyncio.sleep(1.0)
            await safe_write(client, HELLO, log)
            end = time.monotonic() + seconds
            n = 0
            while time.monotonic() < end:
                await asyncio.sleep(repeat or 0.25)
                if repeat:
                    n += 1
                    if pin and n % 2 == 0:  # like the app: PIN entry every other keep-alive
                        await safe_write(client, DEFAULT_PIN_ENTRY, log)
                        await asyncio.sleep(0.01)
                    await safe_write(client, HELLO, log)
            await client.stop_notify(CHAR)
        finally:
            await client.disconnect()

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
    ap.add_argument("--pin", action="store_true", help="also enter the default PIN every other keep-alive")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(probe(a.mac, a.seconds, a.outdir, a.repeat, a.pin)), indent=2))
