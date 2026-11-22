# trailtune

[![tests](https://github.com/Utah-E-Moto-Guide/trailtune/actions/workflows/tests.yml/badge.svg)](https://github.com/Utah-E-Moto-Guide/trailtune/actions/workflows/tests.yml)

Back up, compare and carefully tune a **Fardriver motor controller** over Bluetooth from a laptop,
by talking to Claude (or from the command line) instead of poking at the phone app.
(Formerly `fardriver-ble`.)

- **Back up** every setting to a dated snapshot plus a `.heb` file, the same format the phone apps
  export and import.
- **Compare** any two backups and see exactly which settings changed.
- **Tune** with a guided garage-to-trail loop: state a goal, try one small change, ride, say how it
  felt, then keep it or put it back. Every change is logged.

It works with Fardriver controllers that advertise over BLE as `YUANQU…`, `CONTROL…` or `BMS…`
(the names the official app looks for). Developed and tested on an X-Pro Drax Apex (WC72V150).

**Verified firmware:** HA80 (WC72V150AB_17_1ZHA80). Backups, diffs and audits work on any Fardriver
controller; **writes are off on other firmware** until you opt in, because another firmware may store
settings at different addresses. See [Other controllers](#other-controllers).

## Safety first

This tool **can write settings and save them to the controller**. It is careful by design, but you
are working on a vehicle:

- **Bike on a stand, driven wheel off the ground, bike strapped down, whenever the tool is
  connected.** On some bikes neutral does not stop the motor while a Bluetooth device is connected.
  Hands off the throttle, people clear.
- Close the phone app first. The controller only takes one Bluetooth connection at a time.
- Changes are RAM-only unless you choose to save them: turning the key off undoes them.
- After a save, power fully off and on, and check the value stuck before you ride.
- Stop and revert on any fault code, stutter, overheating or BMS cut-out.

What it will and won't do:

- Writes only on verified firmware unless you opt in (see [Other controllers](#other-controllers)).
- Changes one setting at a time, in small steps, within the app's own ranges.
- Currents can only go **down** from your controller's factory values, never up. The limits come
  from the first backup of *your* controller (see [Factory reference](#factory-reference)).
- Watches the controller's fault bits after every write and puts the old value back if a fault
  appears.
- Never touches voltage cutoffs, temperature limits, motor matching, PID, calibration, brake and
  interlock wiring, throttle voltages, the PIN, factory reset or self-learn.

You use it at your own risk; see [LICENSE](LICENSE).

## Install

You need a Bluetooth adapter and [uv](https://docs.astral.sh/uv/getting-started/installation/), which
fetches Python 3.11+ and the dependencies by itself.

### As a Claude Code plugin (recommended)

At a Claude Code prompt:

```
/plugin install trailtune --marketplace Utah-E-Moto-Guide/trailtune
```

Answer `y` to add the marketplace, then pick a scope (user is usual). This installs the `trailtune`
MCP tools and the `trailtune` skill together. The first start takes a few seconds while uv sets
up the environment. From a shell, the same is `claude plugin install trailtune --marketplace
Utah-E-Moto-Guide/trailtune`. In the desktop app: + next to the prompt box, Plugins, Add
marketplace `Utah-E-Moto-Guide/trailtune`, then Add plugin.

### From a clone (for the command line, or to hack on it)

```sh
git clone https://github.com/Utah-E-Moto-Guide/trailtune
cd trailtune
uv venv .venv && uv pip install --python .venv/bin/python -e .
```

To use a clone from Claude Code instead of the plugin, use one or the other, not both:

```sh
claude mcp add -s user trailtune -- "$PWD/.venv/bin/python" -m trailtune.mcp_server
ln -s "$PWD/skills/trailtune" ~/.claude/skills/trailtune   # the guided tuning method
```

### Use it

Then ask things like:

- "Scan for my Fardriver controller and back it up."
- "What changed since my first backup?"
- "My throttle is too jumpy on loose climbs. Help me tune it."
- "Turn on brake regen, carefully."

### Or from the command line (a clone)

```sh
.venv/bin/trailtune scan
.venv/bin/trailtune snapshot <MAC> --label before-tune
.venv/bin/trailtune list
.venv/bin/trailtune diff <old snapshot or .heb> [new]   # default new: the latest
.venv/bin/trailtune factory                             # show factory references
.venv/bin/trailtune report                              # controller report for an issue
```

## Your data

Nothing personal is stored in the repo. Snapshots, write logs, tuning sessions and your notes go to
a data folder: `~/.local/share/trailtune` on Linux, `~/Library/Application Support/trailtune`
on macOS, `%LOCALAPPDATA%\trailtune` on Windows. Set `TRAILTUNE_DATA` to keep them somewhere
else, for example a private git repo of your own:

```
snapshots/      one folder per backup: snapshot.json + controller.heb
captures/       raw Bluetooth logs of every write and save
sessions/       tuning sessions: goal, each change, how it felt, kept or reverted
factory/        your controller's factory reference, by serial number
knowledge.yml   your own notes, merged into the tuning knowledge (optional)
config.yml      optional settings, see below
```

### Factory reference

The first backup taken of a controller becomes its factory reference. Current ceilings, the top RPM
and boost time are taken from it, so the limits fit your controller, not someone else's. Until a
controller has a reference, those settings can't be changed at all.

If your controller was already tuned before its first backup (by a dealer or a previous owner),
point the reference at a stock backup, such as a `.heb` from the seller or another owner of the same
model:

```sh
.venv/bin/trailtune factory path/to/stock.heb --serial <your controller's serial>
```

### Other controllers

Writes are verified only on the firmware listed in
[`trailtune/knowledge/controllers.yml`](trailtune/knowledge/controllers.yml). On anything
else the tool still backs up, compares and audits, but refuses to change settings, because a
different firmware may keep a setting at a different address and a write could land on the wrong
one. To try writes anyway, at your own risk, add this to your data folder's `config.yml`:

```yaml
allow_untested_firmware: true
```

Even then, a write is refused if the controller's settings read outside their normal ranges, which
is a strong sign its memory layout differs. If your controller works (or doesn't), please run
`trailtune report <MAC>` and open a [controller report](https://github.com/Utah-E-Moto-Guide/trailtune/issues/new?template=controller-report.yml)
so it can be added to the verified list.

### Bike profiles

The tuning knowledge ships with generic Fardriver notes (the manual, the app). Bike profiles add
model-specific community notes. Turn one on in your data folder's `config.yml`:

```yaml
profiles: [xpro-drax-apex]
```

Available: `xpro-drax-apex`. Profiles for other bikes are welcome: copy the format of
`trailtune/knowledge/profiles/xpro-drax-apex.yml` and tag every note with its source.

## How tuning works

1. **Goal.** You say what you want in your own words; a session opens with a baseline backup.
2. **One change.** Claude picks one setting, explains why and what could go wrong, and asks first.
   It's applied to RAM only unless you choose to save.
3. **Ride.** Ride it.
4. **Feedback.** Say how it felt. The tool checks the change was still active during the ride.
5. **Keep or revert.** Keep saves it to the controller; revert puts the old value back.

Settings come in three tiers. **Comfort** (throttle feel) gets normal care. **Caution** (gear speeds
and ratios, boost, regen, battery gauge) gets an explanation first. **High** (currents, power curve)
needs your explicit yes every time, starts RAM-only, and can only go down from factory.

## Known limits

- **One Bluetooth connection at a time.** Close the phone app, and any dongle's app, first.
- **Custom PINs.** The tool only enters the factory-default PIN (3414), as the app does. A controller
  with a custom PIN may refuse to answer; changing or removing the PIN is out of scope.
- **macOS** identifies Bluetooth devices by a UUID instead of a MAC address. Use whatever
  `trailtune scan` prints.
- **Weak signal is normal** at the bike: connecting can take 20-35 s.
- **Verified on one firmware so far.** See [Other controllers](#other-controllers) and
  [CONTRIBUTING.md](CONTRIBUTING.md) to help add yours.

## Credits

- **MAXAPACITY**, for the DRAX Apex FarDriver tuning guide behind the Apex profile and several
  safety notes.
- [jackhumbert/fardriver-controllers](https://github.com/jackhumbert/fardriver-controllers) (MIT),
  for the frame-to-address map and field notes. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Not affiliated with Fardriver. No Fardriver code is included.

Protocol notes and developer information: [docs/development.md](docs/development.md) and
[docs/protocol.md](docs/protocol.md).
