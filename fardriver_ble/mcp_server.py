"""MCP server: back up and compare Fardriver controller settings by asking an AI.

Read-only. Writes are limited to the allowlist in probe.py (hello/keep-alive, default
PIN entry, second-section request). There is deliberately no restore, set or PIN-change tool.

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


if __name__ == "__main__":
    mcp.run()
