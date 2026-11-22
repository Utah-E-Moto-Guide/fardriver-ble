# Development

## Rules

- **No Fardriver code in this repo.** The APK, unpacked DLLs and decompiled source stay local (in
  `local/`, ignored by git). Notes are in our own words.
- **Never change the controller PIN** (factory default 3414). There is no PIN-change or
  password/binding command, and tests make sure none can be sent. Entering the default PIN, as the
  phone app does, is the only PIN frame allowed.
- **Fixed write allowlist for reads.** `probe.py` holds exactly the frames a snapshot sends: the
  hello/keep-alive, the default PIN entry, and the second-section request.
- **One write path.** Setting writes and Save go only through `nudge.py`, under the limits in
  `policy.py`. Each new kind of write is added deliberately and logged in `docs/protocol.md`.
- **No rider data in the repo.** Snapshots, captures and sessions go to `FARDRIVER_DATA`
  (`paths.py`). Tests run against a throwaway data folder and the fixtures in `tests/fixtures/`.

## Tests

```sh
.venv/bin/python -m unittest          # or: uv run --with pytest pytest
```

`tools/test_*_live.py` talk to a real controller (RAM-only changes, then restore). Run them by hand,
bike on a stand: `.venv/bin/python tools/test_tiers_live.py <MAC>`. pytest is configured to skip them.

## Layout

- `fardriver_ble/crc.py`: frame checksums
- `fardriver_ble/listen.py`, `decode.py`: frame decoding
- `fardriver_ble/probe.py`: the read-side allowlist (hello/keep-alive, PIN entry, second section)
- `fardriver_ble/snapshot.py`: capture, save, load, diff, factory reference
- `fardriver_ble/address_map.py`, `names.py`: what we know about each address
- `fardriver_ble/policy.py`: tiers, limits and sanity rules
- `fardriver_ble/nudge.py`: the only setting-write path (allow list, limits, fault watch, guarded Save)
- `fardriver_ble/tune.py`: tuning sessions, knowledge layers and the manual-based audit
- `fardriver_ble/mcp_server.py`: the MCP tools
- `fardriver_ble/paths.py`: where rider data lives
- `fardriver_ble/knowledge/`: shipped knowledge and bike profiles
- `skills/fardriver-tune/`: the Claude Code skill
- `tests/fixtures/`: snapshots and captures from one controller, used by the tests
- `tools/unpack_xamarin_blob.py`, `extract_field_map.py`: pull data out of the app's APK (local use only)
- `docs/protocol.md`: what we know about the protocol, and the live test log

## Snapshot format

Each snapshot is a folder with `snapshot.json` (every word, with labels) and `controller.heb`, the
same 696-byte format the phone apps export: the 156-word main section plus the 192-word second
section. If the second section can't be read, the folder gets `heb_main_section.bin.NOT_IMPORTABLE`
instead, never a padded `.heb` that would wipe that section on import.

Diffs list setting changes first. Words the controller changes on its own, and anything the app's
own backup leaves out, are listed separately.
