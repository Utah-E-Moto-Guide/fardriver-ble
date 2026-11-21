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

mcp = MCPServer(
    "fardriver",
    instructions="Read-only backups of a Fardriver motor controller over Bluetooth. No tool changes settings.",
)


@mcp.tool()
async def fardriver_scan(seconds: float = 8.0) -> str:
    """Scan for nearby Fardriver controllers (names containing YUANQU, CONTROL or BMS)."""
    return json.dumps(await scan(seconds), indent=2)


@mcp.tool()
async def fardriver_snapshot(mac: str, label: str = "") -> str:
    """Read the controller's full settings over BLE and save a dated snapshot with a .heb backup.

    Read-only: sends only the app's hello/keep-alive and its second-section request.
    Takes about 5-10 seconds after the (slow) connect.
    """
    s = await snap.capture(mac)
    d = snap.save(s, label=label)
    return json.dumps({"saved": d.name, "serial": s.serial, "words": len(s.words), **s.stats}, indent=2)


@mcp.tool()
def fardriver_list_snapshots() -> str:
    """List saved snapshots, oldest first."""
    return json.dumps(snap.list_snapshots(), indent=2)


@mcp.tool()
def fardriver_diff(old: str, new: str = "") -> str:
    """Compare two snapshots (names from fardriver_list_snapshots, or a .heb file path).

    `new` defaults to the latest snapshot. Setting changes are listed apart from
    words the controller changes on its own.
    """
    new = new or snap.list_snapshots()[-1]["name"]
    return snap.format_diff(snap.diff(snap.load(old), snap.load(new)))


@mcp.tool()
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
def fardriver_settable() -> str:
    """Settings fardriver_set may change, with the app's raw limits. Everything else is refused."""
    from .nudge import NUDGEABLE, _field

    rows = [{"field": n, "raw_min": lo, "raw_max": hi, "unit": _field(n).unit} for n, (lo, hi) in NUDGEABLE.items()]
    return json.dumps(rows, indent=1)


@mcp.tool()
async def fardriver_set(
    mac: str, field: str, value: int | None = None, restore_from: str = "", save: bool = False
) -> str:
    """Change ONE allowed setting on the controller (see fardriver_settable), the way the app does.

    - value: new raw value, one step from the current value. Or omit it and pass restore_from
      (a snapshot name or .heb path) to put back that backup's value for this one field.
    - save=False (default): the change lives in RAM only and a power cycle undoes it.
    - save=True: after a pre-save check (only this field differs from what's stored), sends the app's
      Save (timestamp + command 04). Permanent; bumps the save count.
    Snapshots are taken before and after automatically. Ask the owner before save=True.
    """
    from .nudge import nudge

    r = await nudge(mac, field, value, label="mcp-set", restore_from=restore_from or None, save=save)
    diff = r.pop("diff", "")
    return json.dumps(r, indent=1) + ("\n\n" + diff if diff else "")


if __name__ == "__main__":
    mcp.run()
