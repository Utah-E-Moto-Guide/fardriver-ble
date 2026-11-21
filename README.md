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
uv venv .venv && uv pip install --python .venv/bin/python -e .
claude mcp add -s user fardriver -- "$PWD/.venv/bin/python" -m fardriver_ble.mcp_server
```

## Use

Ask Claude: "back up the Apex controller", "what changed since the baseline?",
"compare against the September settings export". The MCP tools are `fardriver_scan`,
`fardriver_snapshot`, `fardriver_list_snapshots`, `fardriver_diff`, `fardriver_show`.

Or by hand:

```sh
.venv/bin/python -m fardriver_ble scan
.venv/bin/python -m fardriver_ble snapshot <MAC> --label before-tune
.venv/bin/python -m fardriver_ble list
.venv/bin/python -m fardriver_ble diff <old snapshot or .heb> [new]   # default new: latest
.venv/bin/python -m unittest
```

Each snapshot is a folder in `snapshots/` with `snapshot.json` (every word, with labels where
known) and `heb_main_section.bin.NOT_IMPORTABLE`, the first 312 bytes of a `.heb`, for comparing
with phone-app exports. It is deliberately not a `.heb`: the app's import writes the whole file,
and we can't read the second section yet, so a padded file would wipe it.

Diffs list setting changes first. Words the controller changes on its own, and anything the
app's own backup leaves out, are listed separately.

## Layout

- `fardriver_ble/crc.py`: frame checksums
- `fardriver_ble/listen.py`: passive listener and frame decoder
- `fardriver_ble/probe.py`: the hello/keep-alive, the only allowed write
- `fardriver_ble/snapshot.py`: capture, save, load, diff
- `fardriver_ble/names.py`: what we know about each address
- `fardriver_ble/mcp_server.py`: the MCP tools
- `snapshots/`: saved snapshots
- `tools/unpack_xamarin_blob.py`: pull .NET assemblies out of the app's APK (local use only)
- `docs/protocol.md`: what we know, and the live test log
- `captures/`: raw notification logs from the bike
