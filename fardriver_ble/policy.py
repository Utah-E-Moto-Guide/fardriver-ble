"""What the tune tool may change, how far, and the sanity rules it will not break.

Owner decisions (2026-11-21): allow comfort, gears/speed, regen, battery gauge, currents and the
power curve; currents may only go DOWN from factory; power curve in small steps below 6000 RPM.
"Allow wide exploration but no stupidity."

Values here are in display units (A, RPM, %, s), as the app shows them. The write path converts
to raw. Tiers:
  comfort  feel settings; normal care
  caution  changes how the bike pulls, brakes or reports charge; explain before trying
  high     currents and the power curve; needs acknowledge_risk=True on every call, RAM-only
           first, a fault watch with automatic revert, and a ride test before any save

Hard rules (never relaxed by the LLM or the owner through this tool):
  - never-write fields stay blocked (address_map.risk == "never")
  - currents never above factory, never below half of factory
  - boost current never below its max current
  - low gear <= mid gear <= high gear <= speed limiter <= 6000 RPM (factory)
  - max regen >= normal regen
  - power curve only below 6000 RPM, never rising with RPM
"""

from dataclasses import dataclass

from .address_map import FIELDS


@dataclass(frozen=True)
class Spec:
    tier: str
    lo: float  # display units
    hi: float
    max_step: float  # display units per change
    requires_nonzero: bool = False


FACTORY = {  # Apex factory values (this controller's Sep 2026 factory image; MAXAPACITY agrees)
    "High gear line current": 130, "High gear phase current": 350,
    "Boost line current": 130, "Boost phase current": 360, "Speed limiter target": 6000,
    "Boost duration": 10,
}

SPECS: dict[str, Spec] = {
    # comfort
    "Throttle acceleration step": Spec("comfort", 2, 224, 16),
    "Throttle deceleration step": Spec("comfort", 4, 224, 16),
    "Throttle release response": Spec("comfort", 0, 192, 16),
    "Acceleration curve update interval": Spec("comfort", 10, 2002, 20),  # ms, (raw+1)*2
    "Throttle response profile (0 Line, 1 Sport, 2 ECO)": Spec("comfort", 0, 2, 2),
    "ECO acceleration coefficient": Spec("comfort", 1, 8, 2, requires_nonzero=True),
    # caution: gears and speed
    "High gear speed": Spec("caution", 500, 6000, 300),
    "Mid gear speed": Spec("caution", 300, 6000, 300),
    "Low gear speed": Spec("caution", 300, 6000, 300),
    "Speed limiter target": Spec("caution", 1000, 6000, 500),
    "Low gear line current ratio": Spec("caution", 10, 100, 10),
    "Mid gear line current ratio": Spec("caution", 10, 100, 10),
    "Low gear phase current ratio": Spec("caution", 10, 100, 10),
    "Mid gear phase current ratio": Spec("caution", 10, 100, 10),
    "Boost duration": Spec("caution", 0, 20, 2),  # s; cap = 2x factory 10 s
    "Boost release delay": Spec("caution", 10, 120, 5),  # s
    # caution: regen
    # Energy feedback switch (app "Energy feedback", FollowConfig): only 1 off <-> 2 brake regen (EABS).
    # 0 "follow" (undocumented) and 3 throttle-off regen are left out on purpose: throttle-off regen acts
    # like engine braking and can slide the rear on loose descents. Owner chose brake regen, 2026-11-21.
    # The tool writes only this bit field, not the app preset's currents and curve.
    "Energy feedback (0 follow, 1 off, 2 brake regen, 3 throttle-off regen)": Spec("caution", 1, 2, 1),
    "Regen current (normal)": Spec("caution", 0, 10, 1),  # app limit 10
    "Regen current (maximum)": Spec("caution", 0, 20, 2),  # app limit 20
    **{f"Regen curve at {r} RPM": Spec("caution", -30, 0, 5) for r in range(500, 9500, 500)},
    # caution: battery gauge
    "Battery capacity": Spec("caution", 20, 250, 5),  # app limit 20..250 Ah
    "Empty-battery point": Spec("caution", 768, 1024, 16),  # app limit
    "Full-battery point": Spec("caution", 1024, 1536, 16),  # app limit
    # high: currents, only at or below factory
    "High gear line current": Spec("high", 65, 130, 5),
    "High gear phase current": Spec("high", 175, 350, 10),
    "Boost line current": Spec("high", 65, 130, 5),
    "Boost phase current": Spec("high", 180, 360, 10),
    # high: power curve below 6000 RPM
    **{f"Power curve at {r} RPM": Spec("high", 0, 100, 5) for r in range(500, 6000, 500)},
}

NAMES = {f.name: f for f in FIELDS}
assert all(n in NAMES for n in SPECS), [n for n in SPECS if n not in NAMES]


def to_raw(name: str, display: float) -> int:
    f = NAMES[name]
    return int(round((display - f.offset) / f.scale))


def to_display(name: str, raw: int):
    f = NAMES[name]
    v = raw * f.scale + f.offset
    return round(v, 3) if isinstance(v, float) and not float(v).is_integer() else int(v)


def _get(words: dict[int, int], name: str):
    f = NAMES[name]
    return f.value(words[f.addr])


def violations(words: dict[int, int]) -> list[str]:
    """Sanity rules over a full set of words (the proposed state). Empty list = OK."""
    v = []
    g = lambda n: _get(words, n)  # noqa: E731
    for name, cap in (("High gear line current", 130), ("High gear phase current", 350),
                      ("Boost line current", 130), ("Boost phase current", 360)):
        if g(name) > cap:
            v.append(f"{name} {g(name)} A is above factory {cap} A (owner rule: currents only at or below factory)")
    if g("Boost line current") < g("High gear line current"):
        v.append("boost line current must not be below max line current")
    if g("Boost phase current") < g("High gear phase current"):
        v.append("boost phase current must not be below max phase current")
    lo, mid, hi, lim = g("Low gear speed"), g("Mid gear speed"), g("High gear speed"), g("Speed limiter target")
    if not lo <= mid <= hi <= lim <= FACTORY["Speed limiter target"]:
        v.append(f"gear speeds must satisfy low {lo} <= mid {mid} <= high {hi} <= limiter {lim} <= 6000 RPM")
    if g("Regen current (maximum)") < g("Regen current (normal)"):
        v.append("max regen current must not be below normal regen current")
    curve = [g(f"Power curve at {r} RPM") for r in range(500, 6500, 500)]  # 500..6000
    for i in range(1, len(curve)):
        if curve[i] > curve[i - 1]:
            v.append(f"power curve must not rise with RPM ({(i) * 500} RPM {curve[i - 1]}% -> "
                     f"{(i + 1) * 500} RPM {curve[i]}%)")
            break
    return v


def describe() -> list[dict]:
    out = []
    for name, s in SPECS.items():
        f = NAMES[name]
        out.append({"field": name, "tier": s.tier, "min": s.lo, "max": s.hi, "max_step": s.max_step, "unit": f.unit})
    return out
