"""Live, RAM-only check of the caution and high tiers (each change lowers stress), then restore.

Usage: .venv/bin/python tools/test_tiers_live.py <mac>
"""

import asyncio
import json
import sys

from trailtune import snapshot as snap
from trailtune.nudge import nudge

PLAN = [  # (field, step from the current display value, acknowledge_risk); every step lowers stress
    ("Battery capacity", +1, False),
    ("High gear line current", -5, True),
    ("Power curve at 5000 RPM", -5, True),
]


async def main(mac):
    start = await snap.capture(mac)
    sdir = snap.save(start, label="tiers-test-start")
    from trailtune.policy import NAMES

    for name, step, ack in PLAN:
        f = NAMES[name]
        value = f.value(start.words[f.addr]) + step
        r1 = await nudge(mac, name, value, label="tiers-step", acknowledge_risk=ack)
        r2 = await nudge(mac, name, None, label="tiers-restore", restore_from=sdir.name, acknowledge_risk=ack)
        print(json.dumps({
            "field": name, "tier": r1.get("tier"), "from": r1.get("from"), "to": r1.get("to"),
            "read_back": r1.get("read_back_twice"), "faults_before": r1.get("faults_before"),
            "new_faults": r1.get("new_faults"), "auto_reverted": r1.get("auto_reverted"),
            "restored_to": r2.get("to"), "restore_read_back": r2.get("read_back_twice"),
        }), flush=True)
    end = await snap.capture(mac)
    snap.save(end, label="tiers-test-end")
    print(snap.format_diff(snap.diff(start, end)), flush=True)


asyncio.run(main(sys.argv[1]))
