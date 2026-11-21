# fardriver-ble

Back up a Fardriver motor controller's settings over Bluetooth from a laptop, so an AI
assistant can do it instead of the phone app's small touch screen. Built against the
controller on an X-Pro Drax Apex.

## Rules

- **Read-only.** Nothing here writes settings or flash. The allowlist in `probe.py` holds exactly
  three frames: the hello/keep-alive, entering the default PIN, and the request for the second
  settings section. Each was added deliberately and is logged in `docs/protocol.md`.
- **No Fardriver code in this repo.** The APK, unpacked DLLs and decompiled source stay
  local and are ignored by git. Notes are in our own words.
- **Never change the controller PIN** (factory default 3414). The tool has no PIN-change or
  password/binding command, and tests make sure none can be sent. Entering the default PIN, as the
  phone app does on every connect, is a separate question and not added yet.
- Bike on and not being ridden when testing. Close the phone app first (one connection at a time).

## Setup

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e .
claude mcp add -s user fardriver -- "$PWD/.venv/bin/python" -m fardriver_ble.mcp_server
```

## Use

Ask Claude: "back up the Apex controller", "what changed since the baseline?",
"compare against the September GDriver file". The MCP tools are `fardriver_scan`,
`fardriver_snapshot`, `fardriver_list_snapshots`, `fardriver_diff`, `fardriver_show`.

Or by hand:

```sh
.venv/bin/python -m fardriver_ble scan
.venv/bin/python -m fardriver_ble snapshot <MAC> --label before-tune
.venv/bin/python -m fardriver_ble list
.venv/bin/python -m fardriver_ble diff <old snapshot or .heb> [new]   # default new: latest
.venv/bin/python -m unittest
```

Each snapshot is a folder in `snapshots/` with `snapshot.json` (every word, with labels) and
`controller.heb`, the same 696-byte format the phone apps export: the 156-word main section plus the
192-word second section. If the second section can't be read, the folder gets
`heb_main_section.bin.NOT_IMPORTABLE` instead, never a padded `.heb` that would wipe that section.

Diffs list setting changes first. Words the controller changes on its own, and anything the
app's own backup leaves out, are listed separately.

## Guided tuning

The `fardriver-tune` skill (`skills/fardriver-tune/SKILL.md`, linked into `~/.claude/skills/`) runs a
garage-to-trail loop with the `tune_*` MCP tools: state a goal, try one small change (RAM-only by
default: turning the key off undoes it), ride, report how it felt, then keep (save) or revert.
Advice comes from `knowledge/settings.yml`, where every note is tagged with its source (manual, app,
GDriver, owner, session, community, reasoning) and a confidence. Sessions are logged in `sessions/`.
`tune_audit` compares the settings with the Fardriver manual's guidance.

Only six comfort settings are tunable (throttle acceleration, deceleration and release response,
curve interval, throttle response profile, ECO acceleration). Everything else is refused.

## Layout

- `fardriver_ble/crc.py`: frame checksums
- `fardriver_ble/listen.py`: passive listener and frame decoder
- `fardriver_ble/probe.py`: the hello/keep-alive, the only allowed write
- `fardriver_ble/snapshot.py`: capture, save, load, diff
- `fardriver_ble/names.py`: what we know about each address
- `fardriver_ble/mcp_server.py`: the MCP tools
- `fardriver_ble/nudge.py`: the only setting-write path (allow list, limits, guarded Save)
- `fardriver_ble/tune.py`: tuning sessions and the manual-based audit
- `knowledge/settings.yml`: sourced tuning knowledge
- `skills/fardriver-tune/`: the Claude Code skill
- `sessions/`: tuning session logs
- `snapshots/`: saved snapshots
- `tools/unpack_xamarin_blob.py`: pull .NET assemblies out of the app's APK (local use only)
- `docs/protocol.md`: what we know, and the live test log
- `captures/`: raw notification logs from the bike

## Credits

- **MAXAPACITY**, for their DRAX Apex FarDriver tuning guide: the Apex-specific stock settings, owner tune
  results, safety practice and failure points that the tune tool's community notes are built on.
- jackhumbert/fardriver-controllers (MIT), for the frame-to-address map and field notes.
  See `THIRD_PARTY_NOTICES.md`.
