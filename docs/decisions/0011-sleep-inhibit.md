# 0011 — Sleep inhibit: stdlib D-Bus client, `sleep:idle` block lock, one state thread on Windows

- Status: accepted; item 2 (the `sleep:idle` block lock) superseded by [0020](0020-m2-wave-1-product-decisions.md)
- Date: 2026-10-13
- Steps: C-14 (sleep inhibit only, M2), C-11

## Context

05 §C-14: "Sleep inhibit: Windows `SetThreadExecutionState(ES_CONTINUOUS |
ES_SYSTEM_REQUIRED)`. Linux: the logind `Inhibit` D-Bus call, or `systemd-inhibit` as a
fallback. If neither is available, emit a warning and continue." 05 §C-11: "Sleep inhibit
while any job runs." The plan does not say:

- how the core talks to D-Bus (05 §Rules for the core lists no D-Bus library),
- which `what` and `mode` the logind lock uses,
- on which thread the Windows call runs (the execution state belongs to the calling thread),
- when the warning is sent and what "done" means for C-14 (there is no "Done when" line).

What we found on this machine (Arch, systemd 262, KDE Plasma; commands and output in
`testdata/README.md` "Sleep inhibit (C-14)"):

- `org.freedesktop.login1.Manager.Inhibit` has the signature `ssss` → `h`. The lock lasts
  while the returned fd and all its duplicates are open (`man org.freedesktop.login1`).
- With a `sleep` block lock, `CanSuspend` changes from `yes` to `inhibited`. With an `idle`
  lock alone it stays `yes`. Neither lock changes KDE's own PolicyAgent (`HasInhibition` stays
  `false` for "suspend" and "screen"), so the screen still dims and locks.
- polkit defaults: `inhibit-block-sleep` is `yes` for active and inactive local sessions and
  `auth_admin_keep` for any other caller; `inhibit-block-idle` is `yes` for all.
- `mode=delay` lasts only `InhibitDelayMaxSec` (5 s). `block-weak` (systemd ≥ 257) is not
  enforced for the lock owner's own user, so the desktop's automatic suspend (same user)
  is not stopped.
- `LidSwitchIgnoreInhibited=yes` is the logind default: closing the lid still suspends.
  Windows documents the same: `SetThreadExecutionState` "cannot be used to prevent the user
  from putting the computer to sleep".
- Failures are fast and clear: no bus → `FileNotFoundError` on the socket;
  `systemd-inhibit` prints `Failed to inhibit: …` or `Failed to connect to system scope bus
  …` and exits 1.

## Decision

1. **D-Bus: a minimal stdlib client** (`reframe/platform/dbus.py`, option (b) of the M2
   breakdown), not a new dependency. It does exactly what the one call needs: connect to a
   `unix:path=`/`unix:abstract=` address, SASL `EXTERNAL`, `NEGOTIATE_UNIX_FD`, `Hello`, one
   method call with string arguments, and read until the reply; fds arrive as `SCM_RIGHTS`
   with `MSG_CMSG_CLOEXEC`. It never sets `ALLOW_INTERACTIVE_AUTHORIZATION` (no password
   prompt from a background queue). Its bytes for the Inhibit call are identical to
   jeepney 0.9.0's (checked, and kept as a golden test), and it is tested for real against
   the system bus. Reasons against `jeepney` (the best small option): it has no type
   information (`py.typed`), so strict mypy needs an override; it passes fds only in its
   blocking and threading I/O; and the subset we need is small and fixed by a stable spec.
   If Reframe ever needs more of D-Bus (signals, other services), switch to jeepney: the
   client is one module with one function (`dbus.call`) and the logind backend takes the
   call function as a parameter.
2. **What and mode: `what="sleep:idle"`, `mode="block"`, `who="Reframe"`,
   `why=<reason of the first holder>`.** `sleep` is what stops the encode from being cut by a
   suspend (logind refuses `Suspend()`, also the one that the desktop's idle timer asks for).
   `idle` stops logind's own `IdleAction=` (which can also be `poweroff`), and is the closest
   match of `ES_SYSTEM_REQUIRED` ("resets the system idle timer"). `shutdown` is not
   inhibited. The screen may still turn off and lock, as on Windows (no
   `ES_DISPLAY_REQUIRED`).
3. **Backends in order:** logind (the D-Bus call in a worker thread; the fd is not tied to a
   thread) → `systemd-inhibit --what=sleep:idle --who=Reframe --why=… --mode=block
   --no-ask-password sh -c 'echo ready && exec sleep infinity'` through
   `reframe.tools.run_streaming` (held once `ready` arrives, stopped with its `CancelToken`,
   which kills the tree and so closes the lock fd; it dies with Reframe through the C-1
   child safety) → unavailable. `systemd-inhibit` reaches the same logind, so it helps only
   when our client fails for a reason of its own; it costs one process start.
4. **Windows:** a dedicated thread per hold (`reframe-sleep-inhibit`) makes both calls:
   `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` on acquire and
   `SetThreadExecutionState(ES_CONTINUOUS)` on release, then ends. Never an asyncio worker
   thread (it can end or run other work). A return value of 0 (`NULL`) is a failure
   (`GetLastError` in the warning detail). Tested with a mocked `kernel32` on Linux; not run
   on Windows yet.
5. **Counting and lifetime.** `acquire`/`release` nest; the first acquire takes the lock, the
   last release frees it, extra releases do nothing. `close()` frees the lock whatever the
   count, can be called twice, and is **final**: a later `acquire` does nothing and returns
   the state (a job that starts during shutdown must not take a new lock). An `acquire` that
   is cancelled while the lock is being taken undoes its count and frees the lock once it was
   taken. Two takes never overlap (no second fd).
6. **Unavailable.** When no backend works: `state = unavailable`, one `app.warning` event
   (`sleep_inhibit.unavailable`, the detail lists every backend's reason), and the queue goes
   on. The next hold (count 0 → 1) tries again; it warns again only after a success in
   between. A lock that goes away on its own (the `systemd-inhibit` helper was killed) also
   turns the state to `unavailable` with the warning. `acquire` never raises for expected
   failures.
7. **What "done" means for C-14 in M2** (the plan has no "Done when"): the four acceptance
   criteria of the M2 lead — (1) the Windows calls, on one live thread, mock-tested, and
   `mypy --platform win32` passes; (2) the Linux lock appears and disappears for real on a
   machine with logind, through both backends (a test that is skipped without a system bus
   or logind, so CI containers pass); (3) without a backend, exactly one warning and the state
   `unavailable`, never an exception; (4) nested acquire/release, `close()`, no leaked
   process or fd, `close()` twice. Power actions and the notification hook stay open, so
   C-14 stays **Partial**.

## Consequences

- No new dependency; 05 §Rules for the core is unchanged. Reframe owns about 340 statements of
  D-Bus wire protocol, limited to one call and covered by a golden test, a fake-bus test and
  the real-bus test.
- While a job runs, a user-chosen suspend on Linux is refused by logind (or asks for an
  administrator password, polkit `suspend-ignore-inhibit`); on Windows it is allowed. The
  lid switch suspends on both (logind default). This is a product question for the user
  (see below); the choice is two constants (`WHAT`, `MODE` in `reframe/platform/sleep.py`).
- A process without a local session (a system service, SSH) gets `auth_admin_keep` for the
  `sleep` block lock, so the lock is refused and the warning appears. Falling back to an
  `idle`-only lock in that case was not done (it does not stop the desktop's suspend).
- C-11 calls `acquire(reason)` when the first job starts and `release()` when the last one
  ends (when `QueueSettings.sleep_inhibit` is on), and `close()` on shutdown.

Open question for the user: should a running encode on Linux also block the user's own
"Sleep" from the menu (`block`, current), or only automatic suspend, like Windows? Only
automatic would need a desktop-specific API (logind has no "idle suspend only" lock).

## Plan changes

- 05 §C-14: the sleep-inhibit bullet names the lock (`sleep:idle`, `block`), the stdlib
  D-Bus client and this record.
