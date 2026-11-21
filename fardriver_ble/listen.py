"""Passive Fardriver BLE listener. Subscribes to notifications only; never writes.

Usage: python -m fardriver_ble.listen <mac> <seconds> <outdir>
"""

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

from bleak import BleakClient

from .crc import frame_ok

CHAR = "0000ffec-0000-1000-8000-00805f9b34fb"
DEVICE_INFO = {
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "model": "00002a24-0000-1000-8000-00805f9b34fb",
    "serial": "00002a25-0000-1000-8000-00805f9b34fb",
    "hardware": "00002a27-0000-1000-8000-00805f9b34fb",
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",
    "system_id": "00002a23-0000-1000-8000-00805f9b34fb",
}
SETTINGS_IDS = range(56, 88)


class Framer:
    """Reassembles 16-byte 0xAA frames from BLE notifications, as the app does."""

    def __init__(self):
        self.buf = bytearray()
        self.ids = Counter()
        self.bad_crc = 0
        self.old_format = 0
        self.settings: dict[int, str] = {}

    def feed(self, data: bytes):
        for byte in data:
            if not self.buf:
                if byte == 0xAA:
                    self.buf.append(byte)
                continue
            self.buf.append(byte)
            if len(self.buf) == 16:
                self._frame(bytes(self.buf))
                self.buf.clear()

    def _frame(self, f: bytes):
        if not f[1] & 0x80:
            self.old_format += 1
            return
        if not frame_ok(f):
            self.bad_crc += 1
            return
        fid = f[1] & 0x7F
        self.ids[fid] += 1
        if fid in SETTINGS_IDS:
            self.settings[fid] = f[2:14].hex()


async def listen(mac: str, seconds: float, outdir: Path) -> dict:
    framer = Framer()
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(outdir / "raw_notifications.txt", "w") as raw:

        def on_notify(_, data: bytearray):
            raw.write(f"{time.monotonic() - t0:8.3f} {bytes(data).hex()}\n")
            framer.feed(bytes(data))

        async with BleakClient(mac, timeout=30) as client:
            info = {}
            for key, uuid in DEVICE_INFO.items():
                try:
                    v = await client.read_gatt_char(uuid)
                    info[key] = v.hex() if key == "system_id" else v.decode(errors="replace").strip("\x00")
                except Exception as e:  # noqa: BLE001
                    info[key] = f"<{type(e).__name__}>"
            await client.start_notify(CHAR, on_notify)
            await asyncio.sleep(seconds)
            await client.stop_notify(CHAR)

    summary = {
        "device_info": info,
        "seconds": seconds,
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
    result = asyncio.run(listen(sys.argv[1], float(sys.argv[2]), Path(sys.argv[3])))
    print(json.dumps(result, indent=2))
