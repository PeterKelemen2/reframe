# 0022 — Linux sleep inhibit: the desktop session's inhibit first, a logind idle lock only where needed

- Status: accepted
- Date: 2026-10-13
- Steps: C-14
- Supersedes in part: [0020](0020-m2-wave-1-product-decisions.md) item 1 (the Linux mechanism
  only; the product decision stays: only automatic sleep is stopped)

## Context

[0020](0020-m2-wave-1-product-decisions.md) item 1 (the user's decision): sleep inhibit stops
only automatic sleep; the user's own Sleep, the power button and the lid always work. For
Linux it named the mechanism "a logind `idle` lock and the desktop session's inhibit", and its
context said that the desktop's automatic suspend ignores logind locks (taken from
[0011](0011-sleep-inhibit.md), which measured 1 s after taking the lock).

C-14 measured again on the capture machine (KDE Plasma 6, systemd 262), polling every second
and reading the state 6–7 s after each lock (records under "Sleep inhibit (C-14)" in
`testdata/README.md`). KDE needs about 5 s before it shows an inhibition:

| Lock | `CanSuspend` | KDE stops automatic suspend | KDE stops screen dim/lock |
|---|---|---|---|
| logind `sleep` block | `inhibited` | yes | no |
| logind `idle` block | `yes` | yes | **yes** |
| `org.freedesktop.PowerManagement.Inhibit` | `yes` | yes | no |
| XDG portal `Inhibit`, flag 4 (suspend) | `yes` | yes | no |
| XDG portal `Inhibit`, flag 8 (idle) | `yes` | yes | **yes** |

So KDE does follow logind locks, and it turns a logind `idle` lock into an idle inhibition that
also keeps the screen on. Taking both locks, as 0020 said, would keep the screen on all night.

## Decision

On Linux, one hold is:

1. **The desktop session's inhibit for automatic suspend**, over the session bus, on a
   connection that stays open while the hold lasts: `org.freedesktop.PowerManagement.Inhibit`
   (`UnInhibit(cookie)` on release), else the XDG desktop portal's `Inhibit` with flag 4
   (suspend; `Request.Close()` on release). No session bus (a headless machine, a system
   service) is not a failure.
2. **A logind `idle` lock (mode `block`) only where it is needed**: when the session inhibit
   is not held, or when logind's `IdleAction` is not `ignore`.
3. **No logind `sleep` lock, and no `systemd-inhibit`**: with `--what=idle` it reaches the same
   logind under the same polkit rule as the direct call, and it cannot take the session
   inhibit.

The hold is `active` when at least one part holds. When a part fails, the inhibitor says what
is not stopped (`not_stopped`) in a log warning. The `sleep_inhibit.unavailable` event is sent
once, when nothing holds.

## Consequences

- On KDE the screen still dims and locks during an encode, and the PC does not suspend by
  itself; the user can still sleep it.
- GNOME and other desktops are not tested: Reframe uses the portal there. Whether GNOME's
  automatic suspend honours the flag-4 inhibit and still allows a manual suspend is not known.
- On a desktop whose `IdleAction` is not `ignore`, both locks are taken, so on KDE the screen
  stays on.
- A partly working inhibit (for example the session inhibit fails but logind works) gives only
  a log warning, no user-visible event. Revisit with the UI (M4/M5).
- 0011's context ("neither lock changes KDE's PolicyAgent") was measured too early; this
  record replaces it.

## Plan changes

- [05 §C-14](../plan/05-core.md#c-14-platform-services) and
  [03 §Queue](../plan/03-features.md#queue): the Linux mechanism, without `systemd-inhibit`
  (in the C-14 commit that this record goes with).
