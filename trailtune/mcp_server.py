"""MCP server: back up, compare and carefully tune Fardriver controller settings by asking an AI.

Reads use only the allowlist in probe.py (hello/keep-alive, default PIN entry,
second-section request). Every write (fardriver_set and the tune_* tools) goes through nudge.py:
listed settings only, one step or back to a snapshot value, within limits taken from this
controller's factory reference, optional Save after a pre-save check. No PIN-change, factory reset
or other command exists. Data (snapshots, sessions, captures) lives in paths.DATA.

Run: .venv/bin/python -m trailtune.mcp_server
"""

import json

from mcp.server.mcpserver import MCPServer

from . import snapshot as snap
from .__main__ import scan

import functools
import inspect


def refusals_as_text(fn):
    """Return a plain message for guard refusals instead of a traceback."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **k):
            try:
                return await fn(*a, **k)
            except (PermissionError, RuntimeError, ValueError) as e:
                return f"REFUSED: {e}"
    else:
        @functools.wraps(fn)
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except (PermissionError, RuntimeError, ValueError) as e:
                return f"REFUSED: {e}"
    return wrapper


mcp = MCPServer(
    "trailtune",
    instructions=(
        "Back up, compare and tune a Fardriver motor controller over Bluetooth. Snapshot tools only read. "
        "fardriver_set and tune_try/keep/revert WRITE settings: one small step at a time, RAM-only unless "
        "saved, never above the controller's factory currents. Before any write, confirm the bike is on a "
        "stand with the driven wheel off the ground, strapped down, phone app closed, hands off the throttle. "
        "Follow the trailtune skill for tuning."
    ),
)


@mcp.tool()
@refusals_as_text
async def fardriver_scan(seconds: float = 8.0) -> str:
    """Scan for nearby Fardriver controllers (names containing YUANQU, CONTROL or BMS)."""
    return json.dumps(await scan(seconds), indent=2)


@mcp.tool()
@refusals_as_text
async def fardriver_snapshot(mac: str, label: str = "") -> str:
    """Read the controller's full settings over BLE and save a dated snapshot with a .heb backup.

    Read-only: sends only the app's hello/keep-alive and its second-section request.
    Takes about 5-10 seconds after the (slow) connect. The first snapshot of a controller also
    becomes its factory reference (the source of its current and RPM limits).
    """
    s = await snap.capture(mac)
    d = snap.save(s, label=label)
    ref = snap.factory_reference(s.serial) if s.serial else None
    return json.dumps({"saved": d.name, "serial": s.serial, "words": len(s.words), **s.stats,
                       "factory_reference": ref.taken_at if ref else None}, indent=2)


@mcp.tool()
@refusals_as_text
def fardriver_list_snapshots() -> str:
    """List saved snapshots, oldest first."""
    return json.dumps(snap.list_snapshots(), indent=2)


@mcp.tool()
@refusals_as_text
def fardriver_diff(old: str, new: str = "") -> str:
    """Compare two snapshots (names from fardriver_list_snapshots, or a .heb file path).

    `new` defaults to the latest snapshot. Setting changes are listed apart from
    words the controller changes on its own.
    """
    new = new or snap.latest()
    return snap.format_diff(snap.diff(snap.load(old), snap.load(new)))


@mcp.tool()
@refusals_as_text
def fardriver_show(name: str = "", kind: str = "setting") -> str:
    """Decode a snapshot's fields (default: latest snapshot, settings only).

    kind: setting, calibration, counter, stamp, identity, live, unknown, or all.
    """
    from .address_map import decode

    name = name or snap.latest()
    s = snap.load(name)
    rows = [r for r in decode(s.words) if kind == "all" or r["kind"] == kind]
    head = {"snapshot": name, "taken_at": s.taken_at, "serial": s.serial}
    return json.dumps({**head, "fields": rows}, indent=1)


@mcp.tool()
@refusals_as_text
def fardriver_report(snapshot: str = "") -> str:
    """A controller report (Markdown) for a GitHub issue: firmware, whether it is verified, and
    whether the settings read sensibly. Has no serial number or Bluetooth address. Default: latest snapshot."""
    from . import report

    return report.markdown(report.build(snap.load(snapshot or snap.latest())))


@mcp.tool()
@refusals_as_text
def fardriver_settable(serial: str = "") -> str:
    """Settings that can be changed: tier (comfort/caution/high), limits and max step in display units.

    Limits for currents, RPM, boost time and the power curve come from the controller's factory
    reference; `serial` picks the controller (default: the only one known). Everything else is
    refused. High-tier fields need acknowledge_risk=True. Sanity rules always apply."""
    from . import policy

    refs = snap.factory_references()
    if not serial and len(refs) == 1:
        serial = refs[0]["serial"]
    ref = snap.factory_reference(serial) if serial else None
    out = {"serial": serial or None, "factory_reference": next((r for r in refs if r["serial"] == serial), None)}
    if ref is None:
        out["note"] = ("No factory reference chosen, so currents, RPM, boost time and the power curve are not listed "
                       "and cannot be changed. Take a snapshot first" + (f"; known controllers: {[r['serial'] for r in refs]}"
                                                                         if refs else "") + ".")
    if ref is not None:
        from . import controllers

        ident = controllers.identity(ref.words)
        out["controller"] = {**ident, "verified": controllers.verified(ident),
                             "writes": "on" if controllers.verified(ident) else
                             ("on, untested firmware (rider opted in)" if controllers.allow_untested() else
                              "off: firmware not verified (see allow_untested_firmware)")}
    out["fields"] = policy.describe(policy.factory_values(ref))
    out["rules"] = policy.__doc__.split("Hard rules")[1].strip()
    return json.dumps(out, indent=1)


@mcp.tool()
@refusals_as_text
async def fardriver_set(
    mac: str, field: str, value: float | None = None, restore_from: str = "", save: bool = False,
    acknowledge_risk: bool = False,
) -> str:
    """Change ONE allowed setting on the controller (see fardriver_settable), the way the app does.

    - value: new value in DISPLAY units (A, RPM, %, s, ms), within the field's max step. Or omit it and pass restore_from
      (a snapshot name or .heb path) to put back that backup's value for this one field.
    - save=False (default): the change lives in RAM only and a power cycle undoes it.
    - save=True: after a pre-save check (only this field differs from what's stored), sends the app's
      Save (timestamp + command 04). Permanent; bumps the save count.
    Snapshots are taken before and after automatically. Ask the rider before save=True.
    """
    from .nudge import nudge

    r = await nudge(mac, field, value, label="mcp-set", restore_from=restore_from or None, save=save,
                    acknowledge_risk=acknowledge_risk)
    diff = r.pop("diff", "")
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


# --- guided tuning (garage-to-trail loop) ------------------------------------
# Method lives in skills/trailtune/SKILL.md. Knowledge: see tune.py (shipped, bike profile, yours).


@mcp.tool()
@refusals_as_text
def tune_knowledge(field: str = "") -> str:
    """Sourced tuning knowledge. No field: the tunable settings and the context notes.

    Each note has a source (manual, app, owner, session, community, reasoning) and a
    confidence. Say which source an idea comes from; never present reasoning as fact.
    """
    from . import tune

    if field:
        return json.dumps(tune.knowledge_for(field) or {"error": f"no notes for {field!r}"}, indent=1)
    return json.dumps(tune.knowledge(), indent=1)


@mcp.tool()
@refusals_as_text
def tune_audit(snapshot: str = "") -> str:
    """Compare a snapshot (default: latest) with the manual's guidance. Flags are questions, not errors."""
    from . import tune

    name = snapshot or snap.latest()
    return json.dumps({"snapshot": name, "flags": tune.audit(snap.load(name))}, indent=1)


@mcp.tool()
@refusals_as_text
async def tune_start(mac: str, goal: str) -> str:
    """Open a tuning session: records the rider's goal (their words) and takes a baseline snapshot."""
    from . import tune

    return json.dumps(await tune.start(mac, goal), indent=1)


@mcp.tool()
@refusals_as_text
async def tune_try(mac: str, field: str, value: float, save: bool = False, acknowledge_risk: bool = False) -> str:
    """Try ONE change (display units, within the field's max step). RAM-only unless save=True.

    High-tier fields (currents, power curve) need acknowledge_risk=True, which you may only pass
    after explaining the specific risk to the rider and hearing them accept it. The controller's
    fault bits are watched after the write; a new fault puts the old value back automatically.

    RAM-only changes vanish when the key goes off, so tell the rider to keep the bike on until the ride
    is done, or ask whether to save the trial (reversible by tune_revert, which saves the old value back).
    """
    from . import tune

    r = await tune.try_change(mac, field, value, save=save, acknowledge_risk=acknowledge_risk)
    diff = r.pop("diff", "") if isinstance(r, dict) else ""
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


@mcp.tool()
@refusals_as_text
async def tune_feedback(mac: str, notes: str) -> str:
    """Record how the open change felt, in the rider's words, and check it was still active."""
    from . import tune

    return json.dumps(await tune.feedback(mac, notes), indent=1)


@mcp.tool()
@refusals_as_text
async def tune_keep(mac: str) -> str:
    """Make the open change permanent (Save). Only after the rider explicitly says to keep it."""
    from . import tune

    r = await tune.keep(mac)
    diff = r.pop("diff", "")
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


@mcp.tool()
@refusals_as_text
async def tune_revert(mac: str) -> str:
    """Put the open change back to its previous value (saves only if the trial had been saved)."""
    from . import tune

    return json.dumps(await tune.revert(mac), indent=1)


@mcp.tool()
@refusals_as_text
def tune_finish(summary: str = "") -> str:
    """Close the open session with a short summary of what was learned."""
    from . import tune

    return json.dumps(tune.finish(summary), indent=1)


@mcp.tool()
@refusals_as_text
def tune_status() -> str:
    """The open session (goal, trials, notes), or null."""
    from . import tune

    return json.dumps(tune.current_session(), indent=1)


@mcp.tool()
@refusals_as_text
def tune_history() -> str:
    """All tuning sessions: goals, changes, how they felt and whether they were kept. Evidence for advice."""
    from . import tune

    return json.dumps(tune.history(), indent=1)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
