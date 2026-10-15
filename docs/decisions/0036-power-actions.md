# 0036 — Power actions: the countdown, the commands per OS, the test safety

- Status: accepted
- Date: 2026-10-15
- Steps: C-14 (power actions), C-11 (when done), C-15 (the CLI shows the countdown)

## Context

[05 §C-14](../plan/05-core.md#c-14-platform-services): "Power actions: shut down, sleep
(Windows: `shutdown /s /t 60` and `SetSuspendState`. Linux: `systemctl poweroff|suspend`).
Always after a cancellable 60 s countdown event." [03 §Queue](../plan/03-features.md#queue):
"When done: nothing · notify · quit · sleep · shut down (desktop and bare-metal only)." The
contract ([0030](0030-core-complete-contract.md), [core-breakdown.md](../core-breakdown.md)) fixes
`PowerService(events, *, executor=None, countdown=60.0)` with `schedule`, `cancel`, `pending`,
`close`, the `PowerExecutor` protocol and `PowerCountdownEvent`.

The plan does not say how the countdown behaves around a system sleep or `close()`, whether
`systemctl` may ask for a password, how the two Windows countdowns add up, or what
`SetSuspendState` needs. And the code runs on the user's own desktop and on the CI runners:
a test that reaches a real power call would shut down the machine running it. The checks
behind this record (read-only; nothing was ever run) are in
[testdata/README.md](../../testdata/README.md) "Power actions (C-14)".

## Decision

### 1. The countdown

- Events: `started` (once, with `seconds_left` = the countdown rounded up and `deadline`),
  `tick` every second (59 … 1), then `cancelled` or `executing` (0). Every event of one
  countdown carries the same `countdown_id`, `action` and `deadline`.
- **It counts ticks, not wall-clock time**: each tick is one `sleep(1)`. A system sleep or a
  blocked event loop in the middle can only make it longer, never fire the action early (an
  absolute deadline would fire every missed tick at once after a wake, and the action with
  them, before the user could press Cancel). `deadline` is the estimate made at the start;
  `seconds_left` is what counts. A fractional countdown first steps to the next whole second.
- `cancel()` (by id or the running one), a new `schedule()` and `close()` publish
  `cancelled` with the seconds left. `cancel()` wins also when the last second is over but the
  countdown task has not run yet. Once `executing` is published the countdown is over:
  `cancel()` returns `False` and `pending` is `None`.
- `close()` cancels the countdown and also stops an action that is being started (it cancels
  the task that awaits the executor). It never starts one. `schedule()` after `close()` starts
  nothing: its id gets one `cancelled` event, so a late when-done never fires.
- `schedule()` needs a running event loop and the loop's thread (`RuntimeError` otherwise: a
  programming error, not an expected failure).
- `quit` is not an OS action: the countdown ends with `executing` and the UI layer quits
  (the desktop shell, or the CLI).
- A failure is data: one `app.warning` with code `power.failed`, a message ("Reframe could not
  shut down the computer." / "… put the computer to sleep.") and the detail, with the
  `reason` of `schedule()` added. An executor that raises anyway is caught and becomes the
  same warning.

### 2. Linux: `systemctl --no-ask-password poweroff|suspend`

- **systemctl, as the plan says**, through `reframe.tools.run` (30 s time-out; both verbs only
  queue the action and return). systemctl asks logind's `PowerOff` / `Suspend` itself, so the
  direct D-Bus call (the stdlib client of `reframe.platform.dbus`) would give the same
  result with more code and a second, unguarded path to a power call. Lost: systems with
  elogind and no systemctl (Void, Gentoo with OpenRC, …) get `power.failed` ("systemctl could
  not be started"). Revisit when a user asks; the fallback would be logind `PowerOff(false)`.
- **`--no-ask-password`** (interactive = false): polkit allows both actions for the active
  local session without a password (`implicit active: yes`); everywhere else (a service
  outside the active session, another user logged in, someone's `block` lock) it needs an
  administrator password. A password dialog that nobody answers at night would keep the
  machine on and stay on screen; the call fails at once instead and the user sees
  `power.failed` with systemctl's message. Same rule as sleep inhibit: no call ever asks for a
  password.
- `suspend`, not `sleep`: `systemctl sleep` (systemd 256+) lets logind pick
  `suspend-then-hibernate` by default, which is not what "sleep" means in the app.
- Inhibitors: no `--check-inhibitors` / `-i`. Without a TTY systemctl leaves the check to
  logind, which respects other programs' `block` locks (that is right: something like a disc
  burner asked not to be interrupted). Reframe's own sleep inhibit holds only `idle` locks
  ([0020](0020-m2-wave-1-product-decisions.md), [0022](0022-linux-sleep-inhibit-mechanism.md)),
  which never block either action.
- "Desktop and bare-metal only" is the UI's and the server's rule (S-x / F-x hide the
  choices in a container). The core does not guess: in a container `systemctl` fails ("System
  has not been booted with systemd …" or not found) and that is `power.failed`.

### 3. Windows shut down: `shutdown.exe /s /t 60 /c "…"` after Reframe's countdown

- **Kept as the plan says**, so the user gets two warnings: Reframe's 60 s countdown (in the
  app or the browser, which may be on another device), then Windows' own one-minute warning
  on the machine itself, which `shutdown /a` cancels. Two minutes in all (HandBrake's
  Windows GUI does the same, as far as we know; not checked).
  `/t 0` after Reframe's countdown was the alternative: shorter, and it does not imply `/f`.
- The Windows docs: "If the timeout period is greater than 0, the /f parameter is implied"
  (apps are closed without asking; unsaved work is lost). For an unattended "shut down when
  done" this is what makes the shutdown actually happen; the two warnings are the protection.
  The value is one constant (`WINDOWS_SHUTDOWN_DELAY`).
- `/c "Reframe: the queue is done. Run 'shutdown /a' to cancel."` so the Windows warning says
  who asked and how to stop it (at most 512 characters, as documented).
- The program is `%SYSTEMROOT%\System32\shutdown.exe` by absolute path (a bare name could find
  a `shutdown.exe` in the working directory).
- Not done: `cancel()` after `executing` does not run `shutdown /a` (the countdown is over by
  then; the user cancels the Windows warning itself).

### 4. Windows sleep: `SetSuspendState(FALSE, FALSE, FALSE)` with `SeShutdownPrivilege`

- `bHibernate = FALSE` (sleep), `bForce` has no effect, `bWakeupEventsDisabled = FALSE` (wake
  timers still work). The docs require `SE_SHUTDOWN_NAME` in the token, enabled with
  `AdjustTokenPrivileges`: done first (`OpenProcessToken`, `LookupPrivilegeValueW`,
  `AdjustTokenPrivileges`; `ERROR_NOT_ALL_ASSIGNED` means the account lacks it), the token
  handle is always closed.
- On a worker thread: the call may block until the system wakes again.
- Hibernation: with hibernation enabled, Windows may hibernate instead of sleep. The reports
  we know of are about `rundll32 powrprof.dll,SetSuspendState …`, which does not pass real
  BOOLEAN arguments; the direct call passes FALSE, which the docs define as "suspended". Not
  verified on Windows, and neither are hybrid sleep and Modern Standby (S0ix) machines (the
  docs say nothing about them). If it turns out to hibernate, the fix belongs here.
- Mock-tested on Linux only (`mypy --platform win32` checks the `ctypes` bindings).

### 5. Safety: no test can reach a power action

- **Two functions reach the operating system, nothing else**: `_run_command` (every power
  command process) and `_load_win32` (the only way to the DLLs). The executors look them up at
  call time, so a replacement always applies.
- **Layer 1, the shared pytest plugin** (`reframe_testing.pytest_plugin`): a session-wide
  autouse fixture replaces both with functions that record the call and `pytest.fail` the
  test; an autouse per-test fixture (`power_guard`) fails the test at teardown if a call was
  recorded, also when the failure was swallowed inside an asyncio task. This covers every test
  of the repository (core, server, testing). Tests that prove the guard take the record with
  `power_guard.take_calls()`.
- **Layer 2, in the core**: both functions refuse by themselves while `PYTEST_CURRENT_TEST`
  is set (pytest sets it during every test) or `REFRAME_POWER_DRY_RUN` is set: the command
  becomes a `RunResult` with `error`, the DLL load an `OSError`, so the action fails with a
  reason. This holds even if the plugin is not loaded. `REFRAME_POWER_DRY_RUN=1` is also for
  people: it lets a developer try the when-done flow of the desktop app without the computer
  going off (the countdown runs, then `power.failed` says "dry run").
- Every test of the step uses a fake executor, a fake command runner or mocked DLLs; the
  tests of layer 2 also mock `reframe.tools.run` and use a harmless argv.

## Consequences

- The queue (C-11, 1g) calls `power.schedule(action, reason=…)`; the CLI (C-15, 1h) and
  later the UI show `power.countdown` and call `cancel`. The UI quits on `executing` for
  `quit`.
- Open product questions, each with a default that is one constant or one line to change:
  1. Windows: two countdowns (Reframe's 60 s, then `shutdown /t 60` with the implied `/f`)
     or `/t 0` after Reframe's countdown. Default: as the plan says (`/t 60`).
  2. A password prompt for a shutdown that polkit does not allow: never (default), or let
     polkit's agent ask.
  3. Linux sleep: `suspend` (default) or `systemctl sleep` (logind's `SleepOperation`).
  4. Whether to support elogind systems through logind's D-Bus `PowerOff` when systemctl is
     missing. Default: no.
- Not verified: the real power calls on any OS (by design, never run), the Windows code on
  Windows, `SetSuspendState` on Modern Standby machines.

## Plan changes

None: the plan's commands are kept (`systemctl poweroff|suspend` gains `--no-ask-password`,
`shutdown /s /t 60` gains `/c`).
