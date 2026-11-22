"""Garage-to-trail tuning sessions, guided by the sourced knowledge files.

Loop: start (goal + baseline snapshot) -> try one change -> ride -> feedback -> keep or revert.

Rules enforced here:
- One open change at a time. Keep or revert it before trying the next.
- Changes go through nudge.py (allow list, app limits, a per-field max step from the knowledge file).
- A trial is RAM-only unless save=True; turning the key off undoes it. Feedback checks whether the
  trial value is still active, so a ride on the old setting is caught.
- keep saves only when working memory differs from the last saved state in just that field.

Sessions live in <data>/sessions/<id>/session.json (see paths.py).

Knowledge is merged from three layers, in this order:
  1. fardriver_ble/knowledge/settings.yml       shipped, generic Fardriver notes
  2. fardriver_ble/knowledge/profiles/<name>.yml bike profiles turned on in <data>/config.yml
                                                 (`profiles: [xpro-drax-apex]`) or FARDRIVER_PROFILE
  3. <data>/knowledge.yml                        the rider's own notes (same format)
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import yaml

from . import paths
from . import snapshot as snap
from .address_map import FIELDS
from .nudge import NUDGEABLE, _field, _send_save, nudge, presave_check

SESSIONS = paths.SESSIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def available_profiles() -> list[str]:
    return sorted(p.stem for p in paths.PROFILES.glob("*.yml"))


def active_profiles() -> list[str]:
    env = os.environ.get("FARDRIVER_PROFILE")
    if env is not None:
        return [x.strip() for x in env.split(",") if x.strip()]
    return list(paths.config().get("profiles") or [])


def knowledge_layers() -> list[tuple[str, Path]]:
    layers = [("shipped", paths.KNOWLEDGE)]
    for name in active_profiles():
        p = paths.PROFILES / f"{name}.yml"
        if not p.exists():
            raise RuntimeError(f"unknown bike profile {name!r}; available: {', '.join(available_profiles()) or 'none'}")
        layers.append((f"profile:{name}", p))
    if paths.LOCAL_KNOWLEDGE.exists():
        layers.append(("yours", paths.LOCAL_KNOWLEDGE))
    return layers


def knowledge() -> dict:
    """All layers merged: notes for the same field are appended in layer order."""
    out = {"layers": [], "settable": [], "context": [], "audit": [], "faults": [], "safety": []}
    by_field: dict[str, dict] = {}
    for label, path in knowledge_layers():
        k = _read_yaml(path)
        out["layers"].append(label)
        for section in ("settable", "context"):
            for e in k.get(section) or []:
                entry = by_field.get(e["field"])
                if entry is None:
                    entry = {"field": e["field"], **({"plain": e["plain"]} if "plain" in e else {}), "notes": []}
                    by_field[e["field"]] = entry
                    out[section].append(entry)
                elif "plain" in e and "plain" not in entry:
                    entry["plain"] = e["plain"]
                entry["notes"] += e.get("notes") or []
        for section in ("audit", "faults", "safety"):
            out[section] += k.get(section) or []
    return out


def knowledge_for(field: str) -> dict | None:
    k = knowledge()
    for entry in k["settable"] + k["context"]:
        if entry["field"] == field:
            return entry
    return None


# --- audit -------------------------------------------------------------------

def _val(words, name):
    f = next(f for f in FIELDS if f.name == name)
    return f.value(words[f.addr])


def audit(s: snap.Snapshot) -> list[dict]:
    """Compare a snapshot with the manual's guidance. Flags are informational, not verdicts."""
    w = s.words
    flags = []
    rated, lvc = _val(w, "Rated battery voltage"), _val(w, "Low-voltage cutoff")
    suggested = {48: 42, 60: 52.5, 72: 63, 84: 73.5, 96: 84, 108: 94.5}.get(round(rated))
    if suggested is not None and abs(lvc - suggested) >= 1:
        flags.append({"id": "low_voltage_cutoff", "value": lvc, "manual": suggested,
                      "text": f"Low-voltage cutoff {lvc} V; the manual suggests about {suggested} V for {rated:g} V."})
    normal, maximum = _val(w, "Regen current (normal)"), _val(w, "Regen current (maximum)")
    if normal:
        pct = round((maximum - normal) / normal * 100)
        if not 25 <= pct <= 50:
            flags.append({"id": "regen_ratio", "value": f"{normal} A / {maximum} A (+{pct}%)", "manual": "+25..50%",
                          "text": f"Max regen is {pct}% above normal; the manual's usual range is 25-50%."})
    typical = {"Mid gear phase current ratio": 75, "Mid gear line current ratio": 50,
               "Low gear phase current ratio": 50, "Low gear line current ratio": 25}
    for name, pct in typical.items():
        v = _val(w, name)
        if abs(v - pct) > 5:
            flags.append({"id": "gear_ratios", "field": name, "value": round(v), "manual": pct,
                          "text": f"{name} {round(v)}%; manual typical {pct}%."})
    full = _val(w, "Throttle full voltage")
    flags.append({"id": "throttle_full_alarm", "value": full, "alarm_at": round(full + 0.6, 2),
                  "text": (f"Full-throttle threshold {full} V, so a grip reading above {full + 0.6:.2f} V is treated "
                           "as a broken throttle. Worth checking the grip's real full-twist voltage once (wheel up, "
                           "strapped down).")})
    return flags


# --- sessions ----------------------------------------------------------------

def _path(sid: str) -> Path:
    return SESSIONS / sid / "session.json"


def _load(sid: str) -> dict:
    return json.loads(_path(sid).read_text(encoding="utf-8"))


def _store(s: dict) -> None:
    p = _path(s["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")


def current_session() -> dict | None:
    if not SESSIONS.exists():
        return None
    for p in sorted(SESSIONS.glob("*/session.json"), reverse=True):
        s = json.loads(p.read_text(encoding="utf-8"))
        if s.get("status") == "open":
            return s
    return None


def history() -> list[dict]:
    if not SESSIONS.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SESSIONS.glob("*/session.json"))]


def _open_trial(s: dict) -> dict | None:
    return next((t for t in s["trials"] if t["status"] in ("applied", "rode")), None)


async def start(mac: str, goal: str) -> dict:
    if current_session():
        raise RuntimeError("a session is already open; finish it first (tune_finish)")
    base = await snap.capture(mac)
    sid = datetime.now().strftime("%Y-%m-%d-%H%M")
    bdir = snap.save(base, label=f"tune-{sid}-baseline")
    s = {"id": sid, "goal": goal, "status": "open", "started": _now(), "baseline": bdir.name,
         "saved_ref": bdir.name, "trials": [], "audit": audit(base)}
    _store(s)
    return s


async def try_change(mac: str, field: str, value: float, save: bool = False, acknowledge_risk: bool = False) -> dict:
    s = current_session()
    if not s:
        raise RuntimeError("no open session; start one with a goal")
    if _open_trial(s):
        raise RuntimeError("a change is still open; give feedback and keep or revert it first")
    if field not in NUDGEABLE:
        raise PermissionError(f"{field!r} is not tunable; allowed: {sorted(NUDGEABLE)}")
    r = await nudge(mac, field, value, label=f"tune-{s['id']}-try", save=save, acknowledge_risk=acknowledge_risk)
    if r.get("unchanged"):
        return r
    trial = {"n": len(s["trials"]) + 1, "field": field, "tier": r.get("tier"), "from": r["from"], "to": r["to"],
             "display_from": r["from"], "display_to": r["to"], "unit": r["unit"],
             "faults": r.get("new_faults"), "auto_reverted": r.get("auto_reverted"),
             "brake_signal": r.get("brake_signal"),
             "saved": bool(save and r.get("save", {}).get("saved")), "status": "applied", "at": _now(),
             "snapshots": [r["before"], r["after"]] + ([r["saved_snapshot"]] if r.get("saved_snapshot") else []),
             "notes": []}
    if r.get("auto_reverted") is not None:
        trial["status"] = "failed"
        trial["notes"].append({"at": _now(), "text": f"controller faulted ({r['auto_reverted']}); value written back automatically"})
    elif save and not trial["saved"]:
        trial["status"] = "failed"
        trial["notes"].append({"at": _now(), "text": f"save refused: {r.get('save')}"})
    if (r.get("brake_signal") or {}).get("on_at_end"):
        trial["notes"].append({"at": _now(), "text": "brake signal was on at the end of the watch; "
                               "check nobody held a lever, and that the bike still drives"})
    s["trials"].append(trial)
    if trial["saved"]:
        s["saved_ref"] = trial["snapshots"][-1]
    _store(s)
    return {"trial": trial, "diff": r.get("diff", "")}


async def feedback(mac: str, notes: str) -> dict:
    s = current_session()
    t = s and _open_trial(s)
    if not t:
        raise RuntimeError("no open change to give feedback on")
    now = await snap.capture(mac)
    ndir = snap.save(now, label=f"tune-{s['id']}-feedback")
    f = _field(t["field"])
    active = f.value(now.words[f.addr]) == t["to"]
    t["notes"].append({"at": _now(), "text": notes, "value_active_now": active, "snapshot": ndir.name})
    t["status"] = "rode"
    warning = None
    if not active:
        warning = ("The trial value is NOT active now (the controller reads "
                   f"{f.raw(now.words[f.addr])}). If the key went off before or during the ride, the ride was on the "
                   "saved setting, so this feedback may not reflect the change. Re-apply (and consider save=True) "
                   "before riding again.")
        t["notes"][-1]["warning"] = warning
    _store(s)
    return {"trial": t, "warning": warning}


async def keep(mac: str) -> dict:
    """Make the open change permanent (Save), after the pre-save check."""
    s = current_session()
    t = s and _open_trial(s)
    if not t:
        raise RuntimeError("no open change to keep")
    if t["saved"]:
        t["status"] = "kept"
        _store(s)
        return {"trial": t, "note": "already saved when tried"}
    f = _field(t["field"])
    cur = await snap.capture(mac)
    if f.value(cur.words[f.addr]) != t["to"]:  # key went off: re-apply first
        await nudge(mac, t["field"], t["to"], label=f"tune-{s['id']}-reapply", restore_from=t["snapshots"][1],
                    acknowledge_risk=True)
        cur = await snap.capture(mac)
    problems = presave_check(snap.load(s["saved_ref"]), cur, t["field"], t["display_to"])
    if problems:
        return {"refused": problems}
    res = await _send_save(mac, paths.CAPTURES / f"tune-{s['id']}-keep-{t['n']}")
    saved = await snap.capture(mac)
    sdir = snap.save(saved, label=f"tune-{s['id']}-kept")
    t.update(saved=True, status="kept", kept_at=_now())
    t["snapshots"].append(sdir.name)
    s["saved_ref"] = sdir.name
    _store(s)
    return {"trial": t, "save": res, "diff": snap.format_diff(snap.diff(snap.load(t["snapshots"][0]), saved))}


async def revert(mac: str) -> dict:
    """Put the open change back to the last saved value (saving again only if the trial was saved)."""
    s = current_session()
    t = s and _open_trial(s)
    if not t:
        raise RuntimeError("no open change to revert")
    ref = t["snapshots"][0]  # state just before this trial
    r = await nudge(mac, t["field"], None, label=f"tune-{s['id']}-revert", restore_from=ref, save=t["saved"],
                    acknowledge_risk=True)
    t.update(status="reverted", reverted_at=_now())
    if r.get("saved_snapshot"):
        s["saved_ref"] = r["saved_snapshot"]
    _store(s)
    return {"trial": t, "result": {k: v for k, v in r.items() if k != "diff"}}


def finish(summary: str = "") -> dict:
    s = current_session()
    if not s:
        raise RuntimeError("no open session")
    if _open_trial(s):
        raise RuntimeError("a change is still open; keep or revert it first")
    s.update(status="closed", finished=_now(), summary=summary)
    _store(s)
    return s
