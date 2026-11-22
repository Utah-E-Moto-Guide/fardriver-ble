# Contributing

Thanks for helping. The most useful contributions don't need any code.

## Report your controller

Run `trailtune report <MAC>` and open a **Controller report** issue with the output. It lists
the firmware and model codes and whether the settings read sensibly, without the serial number or
Bluetooth address. A firmware is added to the verified list
(`trailtune/knowledge/controllers.yml`) once someone has confirmed on it that:

1. a snapshot completes and the `.heb` backup imports into the phone app;
2. `fardriver_show` values match what the phone app shows (a few settings, including currents);
3. a RAM-only comfort change reads back and restores (with `allow_untested_firmware: true`);
4. a saved change survives a power cycle.

Do the write steps with the bike on a stand, the driven wheel off the ground, and the bike strapped
down.

## Add a bike profile

Copy `trailtune/knowledge/profiles/xpro-drax-apex.yml` to `profiles/<make-model>.yml`. Every
note needs a `source` (`manual`, `app`, `owner`, `session`, `community`, `reasoning`) and a
`confidence` (`high`, `medium`, `low`). Credit community guides in `THIRD_PARTY_NOTICES.md`, write
in your own words, and don't name individual owners. The tests check that every profile loads and
that every note is sourced.

## Code

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e .
.venv/bin/python -m unittest
```

Read [docs/development.md](docs/development.md) first. The ground rules:

- **No Fardriver code** (APK, DLLs, decompiled source) in the repo.
- **No new kinds of write** without a note in `docs/protocol.md` on how it was verified.
- **The safety rules in `policy.py` only get stricter.** Never relax them, and never add a way to
  change voltage cutoffs, temperature limits, motor matching, PID, calibration, brake or interlock
  wiring, throttle voltages, the PIN, or the command register.
- **No rider data in the repo**, and tests must not touch the real data folder.
