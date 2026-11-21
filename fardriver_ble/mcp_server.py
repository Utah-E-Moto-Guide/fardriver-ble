"""MCP server: back up and compare Fardriver controller settings by asking an AI.

Read-only. The only write any tool can make is the app's hello/keep-alive
(allowlisted in probe.py). There is deliberately no restore or set tool.

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
    """Read the controller's full settings memory over BLE and save a dated snapshot.

    Read-only: sends only the app's hello/keep-alive. Takes a few seconds.
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
def fardriver_show(name: str = "") -> str:
    """Show a snapshot's named settings and serial (default: latest)."""
    name = name or snap.list_snapshots()[-1]["name"]
    s = snap.load(name)
    from .names import SETTINGS

    rows = {f"{sec} / {n}": s.words.get(a) for a, (sec, n, _) in sorted(SETTINGS.items())}
    return json.dumps({"snapshot": name, "taken_at": s.taken_at, "serial": s.serial, "settings": rows}, indent=2)


if __name__ == "__main__":
    mcp.run()
