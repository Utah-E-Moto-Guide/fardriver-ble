"""Pull the address -> field map out of a local decompile of the official app.

Walks ProControlPage's receive switch (`switch (num2)`, one `case` per block start
address) and records every `rcv_* = ...arg[n]...` assignment: which word(s) of the
block it reads, plus the expression (for bit masks and scaling).

Input and output both stay in local/ (derived from Fardriver's code, not committed).
We write our own descriptions from this into fardriver_ble/address_map.py.

Usage: python3 -I tools/extract_field_map.py local/decomp/MotorNet6/MotorNet6/ProControlPage.cs local/field_map.json
"""

import json
import re
import sys
from pathlib import Path

ASSIGN = re.compile(r"([A-Za-z_][\w\.]*(?:\[[^\]]+\])?)\s*(?:\+|\|)?=\s*(.+?);\s*$")
ARG = re.compile(r"arg\[(\d+)\]")


def main(src, out):
    lines = Path(src).read_text(encoding="utf-8").splitlines()
    rows = []
    for start, ln in enumerate(lines):
        sw = re.match(r"^(\t*)switch \((?:num\d*|b\d*|\w*FlashReadAddr\[\w+\])\)", ln)
        if not sw:
            continue
        tabs = len(sw[1])
        case = re.compile(rf"^\t{{{tabs}}}case (\d+):")
        close = re.compile(rf"^\t{{0,{tabs - 1}}}\}}")
        addr = None
        for body in lines[start + 1 :]:
            if close.match(body):  # indentation back above the switch: it ended
                break
            m = case.match(body)
            if m:
                addr = int(m[1])
                continue
            a = ASSIGN.search(body)
            if a and addr is not None and "arg[" in a[2]:
                byts = sorted({int(b) for b in ARG.findall(a[2])})
                words = sorted({addr + (b - 2) // 2 for b in byts if 2 <= b <= 13})
                rows.append({
                    "block": addr,
                    "words": words,
                    "bytes": byts,
                    "field": re.sub(r"^\w+Page\.", "", a[1]),
                    "expr": re.sub(r"\b\w+Page\.", "", a[2]),
                })
    Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{len(rows)} fields from {len({r['block'] for r in rows})} blocks -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
