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
  **Owner confirmed (2026-11-21):** the three named changes cover their intentional edits. Treat the other 11
  as controller-maintained (counters, timestamps, learned calibration, status): back them up, but report them
  separately from setting changes in diffs. Names for them are still unknown.
- bytes 312..695 (the 56..87 image) are almost all zero in that file (words 17 = 61440, 19 = 64).

## Snapshot tool (2026-11-21)

- Capture is complete when all 31 parameter blocks read twice in a row with equal values. First live baseline
  `snapshots/2026-11-21T202712Z_baseline`: 4 hellos, 62 block reads, 0 unstable, 0 bad CRC, about 4 s after a
  ~16 s connect (signal about -78 dBm at the bike). Serial `JSWX2C2605232776AC28` (ASCII at 0xA1..0xAA).
- Against the September settings export it shows exactly the owner's three changes.
- Against this afternoon's run 3, words 0xDD, 0xE0, 0xF4, 0xF9 and 0x82 moved with no edits. All but 0x82 are in
  blocks the app's backup omits, so diffs now treat every word outside the `.heb` as runtime data.
- 0x22..0x24 = last settings-save timestamp, bytes (yy,mon)(day,hour)(min,sec). Factory value 2026-05-23 11:22:37
  matches the serial's `260523`; after the owner's September edits it reads 2026-09-27 07:15:32.

## Third-party app audit (2026-11-21)

Snapshots `before-export-1`, `before-export-2` (1 min apart, control), owner connects with a third-party app, browses,
changes and saves nothing, closes it, power-cycles the bike, then `after-export`.
- Control drift in 1 min: 0xF8 only.
- before-2 -> after: **0 of 156 backed-up words changed; save timestamp unchanged.** Only runtime words moved
  (0xDC, 0xDD, 0xE0, 0xF4, 0xF5, 0xF6, 0xF8), all seen drifting earlier today; the power cycle covers them.
- Conclusion: connecting and browsing with a third-party app writes nothing to the settings we can read. Not covered: the
  unread 56..87 section, what a third-party app does on Save, and anything it sends to its own servers.

## Address map (2026-11-21)

`fardriver_ble/address_map.py` is the field-level map: 280 fields over the 186 parameter words plus the
runtime blocks, each with bits, scale, unit and a kind (setting / calibration / counter / stamp / identity /
live / unknown). Built by reading where the official app displays each value (`tools/extract_field_map.py`
pulls the raw assignments from a local decompile into `local/`), then checked against the settings export:
`tests/test_address_map.py` decodes the live baseline and matches 39 sheet values, including both curves
and the 120/70-12 tire.

Corrections this made to earlier guesses:
- 0x05 is the **settings save count** (96 in Sep, the "96" in the export's file name; 132 now).
- 0x1A packs throttle follow, **ECO mode**, field weakening, speed pulses and gear mode. Its Sep -> Nov change
  is ECO mode 1 -> 2: a fourth setting change, not controller data. **Owner confirmed it was theirs (2026-11-21).**
- 0x6D/0x81 odometer, 0x7D/0x7E work time, 0x82 live throttle voltage.
- 0xD1 and 0xD3 mix a setting byte with a live byte (average power, average speed).
- Regen curve: point i at i*500 RPM from 0, stored negative. Tire: 0xD2 lo aspect, 0xD2 hi rim, 0xD3 hi width;
  0xD4/1000 = reduction ratio.

Still unidentified in the app's backup: high bytes of 0x14, 0x2C, 0x65 (32), 0x9F; 0x67 (720), 0x68 (20257),
0xA0 (1160), 0xAB, 0xAC..0xB3 (0xAD = 176, rest 0), 0xB9, plus a few config bits. The app never reads block
0xAC or 0xB9.

## What "login" means here (from the app, 2026-11-21)

Fardriver controllers have an optional 4-digit PIN; the factory default is 3414. When the app connects to a
controller it isn't bound to, it sends that PIN every other keep-alive: an address write of `34 14` (the digits
packed two per byte) to 0xAB, then the hello. A PIN the user types goes to the same address. It is a PIN check,
not an account. We have never sent it; everything so far used only the hello. It probably gates frames 56..87
(the `.heb` second section), which was nearly empty (2 non-zero words) in the September file.

## Default PIN entry test (2026-11-21)

Owner OK'd entering (never changing) the default PIN. Allowlisted exactly `AA C6 AB AB 34 14 C7 E6`.
- `before-pin` snapshot; run 4 (`captures/2026-11-21-run4-pin/`): 31 hellos + 15 PIN entries over 30 s,
  956 frames, 0 bad CRC, ids 0..54 only. **Frames 56..87 still absent.**
- PIN-status bits (0xE2 block, `(byte3 & 0x18) >> 3`) read 3 in run 3 (no PIN ever sent) and run 4 alike:
  a controller with no custom PIN already counts as logged in.
- `after-pin-2` vs `before-pin`: no setting changes, save count 132 -> 132, save timestamp unchanged.
  Only 0xAB went 0 -> 0x1434: the PIN-check register echoing the entry. Expect it to clear on power cycle
  (unverified). The Sep settings export had 0 there.
- What the app sends when frames 56..87 are missing: command `(19, 7, 10, 56)`, a variant of the hello.
  Not sent yet.

## Second section request (2026-11-21)

Owner OK'd it. Allowlisted the app's `(19, 7, 10, 56)` = `AA 13 EC 07 0A 38 F2 0D`.
- `before-request56` snapshot; run 5 (`captures/2026-11-21-run5-request56/`): 31 hellos + 6 requests over 30 s,
  975 frames, 0 bad CRC, **all 32 frames 56..87 received**, each read consistently.
- `after-request56`: no setting changes, save count 132 -> 132, timestamp unchanged.
- The 192-word second section is identical to the September settings export (words 17 = 61440, 19 = 64, rest 0).
  The app never interprets it; it only carries it in exports.
- Snapshots now request it automatically and save a full `controller.heb`. First one:
  `snapshots/2026-11-21T211233Z_full-baseline` (19 bytes differ from Sep, all explained).

## Power cycle check (2026-11-21)

Owner power-cycled the bike. `after-power-cycle` vs `full-baseline`: **0xAB went 0x1434 -> 0**, confirming the
PIN-check register is temporary (RAM) and today's PIN test left nothing behind. No setting changes, save count
132 -> 132, second section identical; only live words and counters moved.

Also fixed: the capture timeout counted the BLE connect (16-25 s at the bike), so a slow connect could starve
the read. The timeout now starts after connecting; `stats.connect_seconds` records the connect time.

## Community notes and write risk (2026-11-21)

Cross-checked the blocks the app never displays against the MIT-licensed jackhumbert/fardriver-controllers
struct notes (fetched locally, not vendored):
- **0xA0 is the system-command register.** `88 xx` written there runs actions: 08 = factory reset,
  09/0A reset pin assignments, 0B..0D reset curves, 02/03 start self-learning. Ours reads `88 04`.
  It lies inside the `.heb` main section, so any future restore must handle it deliberately.
- 0xAC..0xB1: PIN / owner phone-number store. Strings are `chr(0xB0 + len) + text`; 0xAD = 0xB0 = empty.
- 0x0B: brake mode (4 = disabled), temp sensor, phase exchange, slow-down, race response, current anti-theft,
  park mode, direction. 0x67 production max voltage, 0x68 production max current. 0xF4 motor temp, 0xF5 hi SOC,
  0xF6..0xF7 last-modified date, 0xF8/0xF9 firmware loop times (/8 us). 0xDC..0xE1 are three 32-bit counters.
- Remaining unknown: high bytes of 0x14, 0x2C, 0x65, 0x9F; spare bits of 0x86, 0x9C; 0xB2, 0xB3 (zero) and 0xB9.

Every field now has a write risk (`address_map.risk`): 6 safe-to-nudge comfort settings (throttle
accel/decel/release, curve interval, ECO mode and ECO acceleration), caution for ride/performance settings,
never for commands, binding, identity, calibration, unknowns and anything touching brakes, interlocks,
wiring, direction or protection. Discovery tests should only nudge a "safe" field.

## How the app changes and saves a setting (2026-11-21)

- Editing one value sends one address write, e.g. throttle acceleration (app limit 2..224):
  `AA C6 2F 2F <lo> <hi> <crc16>`. Same frame shape as the PIN entry.
- The Save button sends the phone's date/time as 6 bytes to 0x22 (the "last saved" stamp), then `88 04` to 0xA0:
  **system command 04 = save to flash**. That's why 0xA0 reads `88 04`, and why the save count (0x05) rises
  once per Save press (96 -> 132 = 36 presses).
- Working assumption, untested: a value write without Save lives in RAM and reverts on power cycle.

## First setting write: throttle acceleration 64 -> 65, no Save (2026-11-21)

`fardriver_ble/nudge.py` (only NUDGEABLE safe fields, one step, app range, never 0xA0 / save stamp).
Frame `AA C6 2F 2F 41 00 89 A0`. Snapshots `accel-65-before` / `accel-65-after`:
- Read back as 65 twice from the live stream. Diff: **one setting change** (0x2F 64 -> 65), save count 132 -> 132,
  save stamp unchanged, 0xB9 unchanged, only 2 live fields moved.
- So a single-setting write takes effect immediately without Save, and doesn't touch 0xB9.
- Next: power cycle to see whether the unsaved value reverts to 64.
- **Power cycle (2026-11-21, `accel-after-power-cycle`): throttle acceleration reverted 65 -> 64.** Versus the
  before snapshot: no setting changes, save count 132, stamp unchanged. **Confirmed: a setting write without
  Save is RAM-only and a power cycle undoes it.** Flash only changes on Save (`88 04` to 0xA0), which the
  tool cannot send.

## First Save from our tool (2026-11-21)

`nudge.py --save`: nudge 64 -> 65, pre-save check (working memory = saved state + only that field), then the app's
Save sequence: local time to 0x22 (`AA CA 22 22 yy mm dd hh mi ss crc`) and `AA C6 A0 A0 88 04 C5 0C`.
Our frame builder reproduces the community-documented factory-reset frame `AA C6 A0 A0 88 08 C5 09` exactly
(computed in a test, never sent), which confirms the command frame format.
Result (`accel-65-save-saved`): save count 132 -> 133, stamp 2026-11-21 15:09:54, throttle accel 65,
**0xB9 10699 -> 5083**. 0xB9 changes on Save only (not on the unsaved nudge). ~300 checksum variants over three
known values match nothing. 0xDC..0xE1 move both ways, so they're live, not counters.
Next: power cycle (expect 65 to persist), then nudge back to 64 with Save; if 0xB9 returns to 10699 it
depends only on settings content.
