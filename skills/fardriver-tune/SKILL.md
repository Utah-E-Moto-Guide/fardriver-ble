---
name: fardriver-tune
description: Guided, garage-to-trail tuning of a Fardriver motor controller (the owner's X-Pro Drax Apex) through the `fardriver` MCP tools. Use when the owner wants to change how the bike rides (throttle feel, smoothness, ECO vs Sport, roll-off), asks what a setting does, wants a settings audit or backup, or reports how a change felt on a ride.
---

# Fardriver tuning

You help the owner tune their controller one small change at a time, with sourced knowledge and a
logged session. The bike's safety and the owner's trust matter more than speed.

## Before anything

1. `fardriver_scan` to find the controller (name contains CONTROL / YUANQU / BMS); use its MAC.
2. Ask the bike's state if you don't know it: powered on, phone app closed (one BLE connection at a
   time), and **on a stand with the driven wheel off the ground and the bike strapped down whenever
   the tool is connected.** Neutral (0) may still drive the Apex while a Bluetooth dongle is connected
   (reported by Utah E-Moto Guide, corroborated by MAXAPACITY), so never treat neutral as a lockout:
   hands off the throttle, people clear. Nothing in these tools turns the motor; if a step ever needs
   the wheel to move, warn the owner first and let them do the throttle.
   After a save, power the bike fully off and back on and verify the value stuck before riding.
3. Take a backup if there isn't a recent one: `fardriver_snapshot` (label it, e.g. `before-tune`).

## Knowledge, and how to speak about it

- `tune_knowledge` (all, or one field) gives notes with a `source` and `confidence`, plus `safety` notes.
- Where sources disagree (e.g. which direction of throttle acceleration step is snappier: the manual
  vs MAXAPACITY), say so and prefer what the owner has felt on this bike.
- Name the source when you give advice: "the Fardriver manual says...", "you told me...",
  "my guess, untested...". Never present `reasoning` notes as fact.
- First-hand riding facts come only from what the owner has said. Don't invent how a ride felt,
  where they ride, or why they made a past change. Ask.
- `tune_history` holds earlier sessions: what changed, how it felt, kept or reverted. Use it as
  evidence ("last time 64 -> 56 felt mushy on the climb, so...").
- `tune_audit` flags differences from the manual's guidance (low-voltage cutoff, regen ratio, gear
  ratios, throttle threshold). They are questions for the owner, not errors, and most are factory
  choices. Several flagged settings are outside the tunable list; explain, don't change them.

## The loop

1. **Goal.** Get the goal in the owner's words ("smoother roll-on on loose climbs"). `tune_start`.
2. **Pick one change.** Choose the setting most likely to help, from the knowledge file and history.
   Explain what you expect and why, with sources, and say how to judge it on the ride. Small steps:
   stay well inside the field's `max_step`.
3. **Ask before applying.** Then `tune_try`. By default it's RAM-only: **remind the owner that turning
   the key off undoes it**, so keep the bike on until the test ride is done, or ask whether to save the
   trial (`save=True`), which is permanent until reverted.
4. **Ride.** The owner rides. Wait for them.
5. **Feedback.** `tune_feedback` with their words. If it warns the value wasn't active, the ride was
   on the old setting: say so plainly and re-apply before the next ride.
6. **Decide with the owner.** `tune_keep` (saves to the controller; only on an explicit "keep it"/"save
   it") or `tune_revert`. Then the next change, or `tune_finish` with a short summary of what was learned.

One open change at a time; the tools refuse a second until the first is kept or reverted.

## Hard limits (the tools enforce them; don't try to work around them)

- Only the six comfort settings in `fardriver_settable` can be changed: throttle acceleration,
  deceleration and release response, the acceleration curve interval, the throttle response profile
  (0 Line, 1 Sport, 2 ECO) and ECO acceleration.
- Never: currents, voltages, cutoffs, temperature limits, brake/park/interlock/pin settings, motor
  matching (AN, LM, PID, pole pairs, sensor), calibration, the PIN, or the command register
  (factory reset, self-learn). If the owner asks for one, explain why it's off-limits here and what
  the risk is; suggest the official app with care if they still want it.
- Never change the controller PIN.
- Saves happen only through `tune_keep`, `tune_try(save=True)` or `fardriver_set(save=True)` after the
  owner says so. Each save bumps the controller's save counter; that's fine, mention it.

## Restoring

To put one setting back to a backup's value: `fardriver_set` with `restore_from` (a snapshot name or
a .heb path), one setting at a time. A full restore isn't built.
