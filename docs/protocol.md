# Fardriver BLE protocol notes

Our own notes from reading the official Android app (decompiled locally, not kept
here), the MIT-licensed [jackhumbert/fardriver-controllers](https://github.com/jackhumbert/fardriver-controllers)
serial docs, and live tests against our controller. "Verified" means seen on the bike.

## Source app

- far-driver.com "The Controller APP For Android NEW 288", file `南京远驱288-Signed.Apk`, 64 MB,
  sha256 `d03fc3a66bfe33bd055b67c42ddb1a782ff0fc229daf46c5c054a276f1392a8c`. Hosted on Google Drive,
  linked from https://www.far-driver.com/the-controller-app-for-android/
- Xamarin/.NET. Assemblies are in `assemblies/assemblies.blob` (unpack with `tools/unpack_xamarin_blob.py`),
  then `ilspycmd -p`. The protocol code is in `MotorNet6.dll`, class `ConnectPage`.

## Transport

| Item | Value | Status |
|---|---|---|
| Advertised name | contains `YUANQU`, `CONTROL` or `BMS` (app filter) | ours is `CONTROLCN368`, verified |
| Service | `0000ffe0-0000-1000-8000-00805f9b34fb` | verified |
| Characteristic | `0000ffec-0000-1000-8000-00805f9b34fb`, flags read / write-without-response / notify | verified |
| Device Information | manufacturer `Nations`, model `MD_123456`, serial `SN_000001`, hw 0.1, fw 1.0 | verified (generic module defaults) |
| Write chunking | big frames sent in 20-byte pieces, 10 ms apart | from app |

The app drops the link if it gets the 10-byte notification `AT+VERSION` (adapter in AT mode).

## Frames from the controller (notify)

16 bytes, start byte `0xAA`, resync by scanning for `0xAA`.

- **New format** (`byte1 & 0x80`): CRC-16/MODBUS (reflected poly 0xA001) over bytes 0..13, initial
  value `0x7F3C`, stored low byte then high byte in bytes 14, 15. See `fardriver_ble/crc.py`.
  - `id = byte1 & 0x7F`
  - **ids 56..87 = settings image.** Frame `id` carries six little-endian u16 words in bytes 2..13,
    written to words `(id-56)*6 .. +5` of a 192-word array. All 32 seen = complete image.
  - other ids: live telemetry.
- **Old format** (`byte1 & 0x80 == 0`): 16-bit additive sum of bytes 0..13, big-endian in 14, 15.
  Used for file/firmware download acks (`byte1 = 0x1F`, `byte2 == byte3`) and VCU frames.

## Settings file (`.heb`, the app's export), 696 bytes

- bytes 0..311: a 156-word image the app calls `gflash` (source in the receive path not yet found)
- bytes 312..695: the 192-word settings image from frames 56..87
- App export needs new-format frames and all 32 settings frames.

## Frames to the controller (write)

- **Command frame**, 8 bytes: `AA cmd ~cmd sub v1 v2 sum ~sum` (sum = byte sum of the first six, low 8 bits).
  - `(19, 7, 1, 95)` = `AA 13 EC 07 01 5F 10 EF`: sent on connect and repeatedly afterwards (hello / keep-alive).
  - `(19, 10/11, pw…)`, `(19, 12/13, pw…)`: password confirm / old password.
  - `(19, 22..26, …)`, `(19, 32..35, …)`: phone-number binding.
  - `(21, h+1, m+1, s+1)`, `(20, y-2000, m, d)`: set clock. `(4, 0xAB, 31, 31)`: data dump request.
- **Address write**: `AA, 0xC0+len+4, addr, addr, payload…, CRC16` (special length bytes `0xFF` for 388,
  `0xFE` for 316).
  - system command: payload `88 cmd` to address `0xA0`.
  - default login for an unprotected controller: payload `34 14` ("3414") to address `0xAB`, then the hello.
  - full settings import: whole 384-byte image to address `0x00` and 312-byte image to `0x01`. **Writes flash.**

## Login

The app tracks login/bind state (`PassOk`, `BindingStat`). It gates its own export/import buttons on that state,
but its receive path has no gate. Controllers can have a 6..13 character password and/or a cloud owner binding.
Ours has no password (owner, 2026-11-17).

Deliberately not pursued: the app's forced owner-unbind flow and a hardcoded-key challenge/response
(`SendRs232DataPass`). Neither is needed for a backup of our own controller.

## Live test log

- **2026-11-21 run 1** (`captures/2026-11-21-run1/`): passive 30 s listen, nothing written. Nothing for 25 s,
  then one 18-byte payload repeated ~4/s: `18 f8 80 06 00 60 00 06 00 f8 98 00 98 98 06 00 60 fe`.
  No `0xAA` frames. Either the controller waits for the hello, or the adapter's UART speed doesn't match
  (the byte values look like baud-mismatch garbage). Next: send the hello only.
- **2026-11-21 run 2** (`captures/2026-11-21-run2/`): bike on a stand, rear wheel up. Subscribed, then ONE hello
  (`AA 13 EC 07 01 5F 10 EF`, the only write). Controller answered within ~0.1 s with `0xAA` frames, two frames per
  32-byte notification. 300 frames, **0 bad CRC** (confirms framing and CRC on real hardware). Ids 0..54 only.
  Stream lasted ~8 s, then fell back to the idle payload: the hello is also a keep-alive.
  So the idle payload above is "no host", not a baud problem.
- **2026-11-21 run 3** (`captures/2026-11-21-run3/`): hello re-sent every 1 s for 30 s (31 writes, nothing else).
  Stream held the whole time: 1030 frames, 0 bad CRC, ids 0..54, no 56..87.
  - Decoded with the id-to-address map (`fardriver_ble/decode.py`): 186 parameter words (31 blocks of 6) plus
    the 0xE2/0xE8/0xEE telemetry blocks. 180 of 186 parameter words never changed; 145 are non-zero.
  - Run 2 vs run 3 (separate connections): 179 of 186 words identical. Differ: 0xD8, 0xDA, 0xDC, 0xF5, 0xF6,
    0xF8, 0xFB (counter/clock-like; 0xF5/0xF6 tick up).
  - **No login was needed** to read this. The 56..87 image is still unseen; probably needs the default login.

## Snapshot format (working)

`{address: u16}` for the 31 non-telemetry blocks of the 0..54 cycle (addresses 0x00..0xFF with gaps
0x36..0x5C, 0x6F..0x7B, 0xE2..0xF3). Volatile addresses listed above are recorded but excluded from diffs.
Still to do: compare against a `.heb` exported by the phone app to prove nothing is missing.

## `.heb` layout (verified 2026-11-21)

Against a settings export from 2026-09-26 (owner's Dropbox, not committed):
- bytes 0..311 = 26 stream blocks (156 words) packed in address order: every non-telemetry block from 0x00
  to 0xD0 except 0x5D. See `HEB_BLOCKS` in `fardriver_ble/decode.py`.
- Today's stream vs that file: 142/156 words identical; 14 differ, same in runs 2 and 3. Owner says 4-5 settings
  changed since September. Likely: 0x1C battery capacity 20 -> 35, 0x2F throttle acceleration 175 -> 64,
  0x2B throttle deceleration 128 -> 64 (from neighbours in the settings export). Others unnamed:
  0x05 (96 -> 132), 0x1A, 0x22..0x24 (look like packed bytes / timestamp), 0x6D, 0x7D, 0x82, 0xB9, 0xD1, 0xD3.
- bytes 312..695 (the 56..87 image) are almost all zero in that file (words 17 = 61440, 19 = 64).
