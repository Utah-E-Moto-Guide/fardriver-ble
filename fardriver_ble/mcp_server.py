"""MCP server: back up and compare Fardriver controller settings by asking an AI.

Reads use only the allowlist in probe.py (hello/keep-alive, default PIN entry,
second-section request). The one write tool, fardriver_set, goes through nudge.py:
listed safe settings only, one step or back to a snapshot value, within the app's limits,
optional Save after a pre-save check. No PIN-change, factory reset or other command exists.

Run: .venv/bin/python -m fardriver_ble.mcp_server
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
    "fardriver",
    instructions="Read-only backups of a Fardriver motor controller over Bluetooth. No tool changes settings.",
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
    Takes about 5-10 seconds after the (slow) connect.
    """
    s = await snap.capture(mac)
    d = snap.save(s, label=label)
    return json.dumps({"saved": d.name, "serial": s.serial, "words": len(s.words), **s.stats}, indent=2)


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
    new = new or snap.list_snapshots()[-1]["name"]
    return snap.format_diff(snap.diff(snap.load(old), snap.load(new)))


@mcp.tool()
@refusals_as_text
def fardriver_show(name: str = "", kind: str = "setting") -> str:
    """Decode a snapshot's fields (default: latest snapshot, settings only).

    kind: setting, calibration, counter, stamp, identity, live, unknown, or all.
    """
    from .address_map import decode

    name = name or snap.list_snapshots()[-1]["name"]
    s = snap.load(name)
    rows = [r for r in decode(s.words) if kind == "all" or r["kind"] == kind]
    head = {"snapshot": name, "taken_at": s.taken_at, "serial": s.serial}
    return json.dumps({**head, "fields": rows}, indent=1)


@mcp.tool()
@refusals_as_text
def fardriver_settable() -> str:
    """Settings that can be changed: tier (comfort/caution/high), limits and max step in display units.
    Everything else is refused. High-tier fields need acknowledge_risk=True. Sanity rules always apply."""
    from . import policy

    return json.dumps({"fields": policy.describe(), "rules": policy.__doc__.split("Hard rules")[1].strip()}, indent=1)


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
    Snapshots are taken before and after automatically. Ask the owner before save=True.
    """
    from .nudge import nudge

    r = await nudge(mac, field, value, label="mcp-set", restore_from=restore_from or None, save=save,
                    acknowledge_risk=acknowledge_risk)
    diff = r.pop("diff", "")
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


# --- guided tuning (garage-to-trail loop) ------------------------------------
# Method lives in skills/fardriver-tune/SKILL.md. Knowledge in knowledge/settings.yml.


@mcp.tool()
@refusals_as_text
def tune_knowledge(field: str = "") -> str:
    """Sourced tuning knowledge. No field: the tunable settings and the context notes.

    Each note has a source (manual, app, gdriver, owner, session, community, reasoning) and a
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

    name = snapshot or snap.list_snapshots()[-1]["name"]
    return json.dumps({"snapshot": name, "flags": tune.audit(snap.load(name))}, indent=1)


@mcp.tool()
@refusals_as_text
async def tune_start(mac: str, goal: str) -> str:
    """Open a tuning session: records the owner's goal (their words) and takes a baseline snapshot."""
    from . import tune

    return json.dumps(await tune.start(mac, goal), indent=1)


@mcp.tool()
@refusals_as_text
async def tune_try(mac: str, field: str, value: float, save: bool = False, acknowledge_risk: bool = False) -> str:
    """Try ONE change (display units, within the field's max step). RAM-only unless save=True.

    High-tier fields (currents, power curve) need acknowledge_risk=True, which you may only pass
    after explaining the specific risk to the owner and hearing them accept it. The controller's
    fault bits are watched after the write; a new fault puts the old value back automatically.

    RAM-only changes vanish when the key goes off, so tell the owner to keep the bike on until the ride
    is done, or ask whether to save the trial (reversible by tune_revert, which saves the old value back).
    """
    from . import tune

    r = await tune.try_change(mac, field, value, save=save, acknowledge_risk=acknowledge_risk)
    diff = r.pop("diff", "") if isinstance(r, dict) else ""
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


@mcp.tool()
@refusals_as_text
async def tune_feedback(mac: str, notes: str) -> str:
    """Record how the open change felt, in the owner's words, and check it was still active."""
    from . import tune

    return json.dumps(await tune.feedback(mac, notes), indent=1)


@mcp.tool()
@refusals_as_text
async def tune_keep(mac: str) -> str:
    """Make the open change permanent (Save). Only after the owner explicitly says to keep it."""
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


if __name__ == "__main__":
    mcp.run()
