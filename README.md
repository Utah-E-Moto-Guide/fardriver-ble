# fardriver-ble

Back up a Fardriver motor controller's settings over Bluetooth from a laptop, so an AI
assistant can do it instead of the phone app's small touch screen. Built against the
controller on an X-Pro Drax Apex.

## Rules

- **Read-only first.** Nothing here writes settings or flash. Any write, even the app's
  harmless hello, gets added deliberately, one command at a time, and logged in `docs/protocol.md`.
- **No Fardriver code in this repo.** The APK, unpacked DLLs and decompiled source stay
  local and are ignored by git. Notes are in our own words.
- Bike on and not being ridden when testing. Close the phone app first (one connection at a time).

## Setup

```sh
uv venv .venv && uv pip install --python .venv/bin/python bleak
```

## Use

```sh
# find the controller
bluetoothctl --timeout 10 scan le; bluetoothctl devices | grep -iE 'control|yuanqu|bms'

# passive listen, writes nothing
.venv/bin/python -m fardriver_ble.listen <MAC> 30 captures/<date>-runN

# tests
.venv/bin/python -m unittest
```

## Layout

- `fardriver_ble/crc.py`: frame checksums
- `fardriver_ble/listen.py`: passive listener and frame decoder
- `tools/unpack_xamarin_blob.py`: pull .NET assemblies out of the app's APK (local use only)
- `docs/protocol.md`: what we know, and the live test log
- `captures/`: raw notification logs from the bike
