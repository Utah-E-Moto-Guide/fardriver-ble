"""Live, RAM-only check of each allowed setting: one step, read back, restore from backup.

Never saves. Ends by diffing the controller against the starting snapshot.
Usage: .venv/bin/python tools/test_allowlist_live.py <mac>
"""

import asyncio
import json
import sys

from fardriver_ble import snapshot as snap
from fardriver_ble.nudge import NUDGEABLE, _field, nudge

PLAN = {  # field -> step (+1/-1) chosen to stay inside the app's range
    "Throttle deceleration step": +1,
    "Throttle release response": +1,
    "Acceleration curve update interval": +1,
    "Throttle response profile (0 Line, 1 Sport, 2 ECO)": -1,
    "ECO acceleration coefficient": -1,
}


async def main(mac):
    start = await snap.capture(mac)
    sdir = snap.save(start, label="allowlist-test-start")
    results = []
    for name, step in PLAN.items():
        assert name in NUDGEABLE
        f = _field(name)
        cur = f.raw(start.words[f.addr])
        r1 = await nudge(mac, name, cur + step, label="allowlist-step")
        r1.pop("diff", None)
        r2 = await nudge(mac, name, None, label="allowlist-restore", restore_from=sdir.name)
        r2.pop("diff", None)
        results.append({"field": name, "step": r1, "restore": r2})
        print(json.dumps({"field": name, "to": r1.get("to"), "read_back": r1.get("read_back_twice"),
                          "restored_to": r2.get("to"), "restore_read_back": r2.get("read_back_twice")}), flush=True)
    end = await snap.capture(mac)
    edir = snap.save(end, label="allowlist-test-end")
    print(snap.format_diff(snap.diff(start, end)))
    (snap.REPO / "captures" / f"{sdir.name}-allowlist-results.json").write_text(json.dumps(results, indent=1))


asyncio.run(main(sys.argv[1]))
