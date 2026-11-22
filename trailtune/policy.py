"""What the tune tool may change, how far, and the sanity rules it will not break.

Values are in display units (A, RPM, %, s), as the app shows them. The write path converts to raw.
Tiers:
  comfort  feel settings; normal care
  caution  changes how the bike pulls, brakes or reports charge; explain before trying
  high     currents and the power curve; needs acknowledge_risk=True on every call, RAM-only
           first, a fault watch with automatic revert, and a ride test before any save

Limits that depend on the controller (current ceilings, the top RPM, boost time) come from that
controller's factory reference (snapshot.factory_reference: its first snapshot, by serial). Without
one, those fields cannot be changed at all.

Hard rules (never relaxed by the LLM or the rider through this tool):
  - never-write fields stay blocked (address_map.risk == "never")
  - currents never above this controller's factory value, never below half of it
  - boost current never below its max current
  - low gear <= mid gear <= high gear <= speed limiter <= the factory speed limiter
  - max regen >= normal regen
  - power curve only below the factory speed limiter, never rising with RPM
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


CURRENTS = {  # field -> largest step in A
    "High gear line current": 5, "High gear phase current": 10,
    "Boost line current": 5, "Boost phase current": 10,
}
FACTORY_FIELDS = (*CURRENTS, "Speed limiter target", "Boost duration")
CURVE_RPMS = range(500, 9500, 500)

BASE_SPECS: dict[str, Spec] = {  # limits that are the same on every controller (the app's own ranges)
    # comfort
    "Throttle acceleration step": Spec("comfort", 2, 224, 16),
    "Throttle deceleration step": Spec("comfort", 4, 224, 16),
    "Throttle release response": Spec("comfort", 0, 192, 16),
    "Acceleration curve update interval": Spec("comfort", 10, 2002, 20),  # ms, (raw+1)*2
    "Throttle response profile (0 Line, 1 Sport, 2 ECO)": Spec("comfort", 0, 2, 2),
    "ECO acceleration coefficient": Spec("comfort", 1, 8, 2, requires_nonzero=True),
    # caution: gear ratios and boost
    "Low gear line current ratio": Spec("caution", 10, 100, 10),
    "Mid gear line current ratio": Spec("caution", 10, 100, 10),
    "Low gear phase current ratio": Spec("caution", 10, 100, 10),
    "Mid gear phase current ratio": Spec("caution", 10, 100, 10),
    "Boost release delay": Spec("caution", 10, 120, 5),  # s
    # caution: regen
    # Energy feedback switch (app "Energy feedback", FollowConfig): only 1 off <-> 2 brake regen (EABS).
    # 0 "follow" (undocumented) and 3 throttle-off regen are left out on purpose: throttle-off regen acts
    # like engine braking and can slide the rear on loose descents.
    # The tool writes only this bit field, not the app preset's currents and curve.
    "Energy feedback (0 follow, 1 off, 2 brake regen, 3 throttle-off regen)": Spec("caution", 1, 2, 1),
    "Regen current (normal)": Spec("caution", 0, 10, 1),  # app limit 10
    "Regen current (maximum)": Spec("caution", 0, 20, 2),  # app limit 20
    **{f"Regen curve at {r} RPM": Spec("caution", -30, 0, 5) for r in CURVE_RPMS},
    # caution: battery gauge
    "Battery capacity": Spec("caution", 20, 250, 5),  # app limit 20..250 Ah
    "Empty-battery point": Spec("caution", 768, 1024, 16),  # app limit
    "Full-battery point": Spec("caution", 1024, 1536, 16),  # app limit
}

TIER = {  # every field that can ever be changed, with its tier
    **{n: s.tier for n, s in BASE_SPECS.items()},
    "High gear speed": "caution", "Mid gear speed": "caution", "Low gear speed": "caution",
    "Speed limiter target": "caution", "Boost duration": "caution",
    **{n: "high" for n in CURRENTS},
    **{f"Power curve at {r} RPM": "high" for r in CURVE_RPMS},
}


def factory_values(ref) -> dict | None:
    """The factory values the limits are built from, from a factory reference snapshot (or None)."""
    if ref is None:
        return None
    words = ref.words if hasattr(ref, "words") else ref
    return {n: _get(words, n) for n in FACTORY_FIELDS}


def specs(factory: dict | None) -> dict[str, Spec]:
    """Every changeable field with its limits for a controller with these factory values.
    Without factory values, the controller-dependent fields (currents, RPM, boost time, power
    curve) are left out, so they cannot be changed."""
    out = dict(BASE_SPECS)
    if not factory:
        return out
    lim = factory["Speed limiter target"]
    if lim > 0:
        out["High gear speed"] = Spec("caution", min(500, lim), lim, 300)
        out["Mid gear speed"] = Spec("caution", min(300, lim), lim, 300)
        out["Low gear speed"] = Spec("caution", min(300, lim), lim, 300)
        out["Speed limiter target"] = Spec("caution", min(1000, lim), lim, 500)
        for r in CURVE_RPMS:
            if r < lim:
                out[f"Power curve at {r} RPM"] = Spec("high", 0, 100, 5)
    out["Boost duration"] = Spec("caution", 0, 2 * factory["Boost duration"], 2)
    for name, step in CURRENTS.items():
        f = factory[name]
        if f > 0:  # steps shrink on small controllers: at most ~5% of factory
            half = f / 2
            out[name] = Spec("high", int(half) if float(half).is_integer() else half, f,
                             max(1, min(step, round(f * 0.05))))
    return out


NAMES = {f.name: f for f in FIELDS}
assert all(n in NAMES for n in TIER), [n for n in TIER if n not in NAMES]


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


def violations(words: dict[int, int], factory: dict | None) -> list[str]:
    """Sanity rules over a full set of words (the proposed state). Empty list = OK."""
    v = []
    g = lambda n: _get(words, n)  # noqa: E731
    for name in CURRENTS:
        if factory and g(name) > factory[name]:
            v.append(f"{name} {g(name)} A is above this controller's factory {factory[name]} A "
                     "(currents only at or below factory)")
    if g("Boost line current") < g("High gear line current"):
        v.append("boost line current must not be below max line current")
    if g("Boost phase current") < g("High gear phase current"):
        v.append("boost phase current must not be below max phase current")
    lo, mid, hi, lim = g("Low gear speed"), g("Mid gear speed"), g("High gear speed"), g("Speed limiter target")
    top = factory["Speed limiter target"] if factory else lim
    if not lo <= mid <= hi <= lim <= top:
        v.append(f"gear speeds must satisfy low {lo} <= mid {mid} <= high {hi} <= limiter {lim} <= factory {top} RPM")
    if g("Regen current (maximum)") < g("Regen current (normal)"):
        v.append("max regen current must not be below normal regen current")
    rpms = [r for r in CURVE_RPMS if r <= top]
    curve = [g(f"Power curve at {r} RPM") for r in rpms]
    for i in range(1, len(curve)):
        if curve[i] > curve[i - 1]:
            v.append(f"power curve must not rise with RPM ({rpms[i - 1]} RPM {curve[i - 1]}% -> "
                     f"{rpms[i]} RPM {curve[i]}%)")
            break
    return v


def describe(factory: dict | None) -> list[dict]:
    out = []
    for name, s in specs(factory).items():
        f = NAMES[name]
        out.append({"field": name, "tier": s.tier, "min": s.lo, "max": s.hi, "max_step": s.max_step, "unit": f.unit})
    return out
