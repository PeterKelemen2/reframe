# 0053 — Linux first, Windows in a later testing phase

- Status: accepted
- Date: 2026-10-23
- Steps: Q-1.4, D-0, D-3, D-7, D-8, D-9

## Context

[Decision 0043](0043-plan-review-before-m3.md) item 1 made a Windows run (Q-1.4) part of M3,
because the D-0 spike needs Windows, and made M5 and M10 wait for another Windows run. The
owner develops on Linux only and has no Windows machine in the work loop. With that rule, M3
cannot be done when its server part and the Linux spike are done, and M5 cannot be done
either. Every milestone with a Windows item waits for a machine that is not there.

The owner's decision (2026-10-23): Windows is secondary. It comes later, in a testing phase.
Linux is the platform that the work is done and checked on.

## Decision

1. **Linux is the primary platform.** A milestone is done when its demo works and every CI
   command passes on Linux. No milestone before M10 waits for Windows.
2. **Windows stays a v1 target, but it is secondary.** Windows code paths (Job Objects,
   `CREATE_NO_WINDOW`, `SetThreadExecutionState`, `.exe` lookup, the Windows installer) are
   still written to the plan and unit-tested with mocks on Linux, so that the testing phase
   finds little. `ci.yml` keeps its Windows jobs. `docs/status.md` keeps the list of what has
   not run on Windows.
3. **One Windows testing phase, at the start of M10.** Q-1.4 runs once, there, and not in M3
   or M5. The phase covers:
   - the CI commands of `ci.yml` on Windows 10 or 11 (Q-1.4);
   - the Windows items of D-0: the sidecar on Windows, the cleanup after a kill from Task
     Manager, WebView2 rendering and drag-and-drop paths;
   - the M5 demo on Windows;
   - the Windows parts of D-3 (Job Object), D-7 (the bundled tools on Windows hosts), D-8
     (NSIS installer, MSI) and D-9 (the smoke tests on Windows);
   - each item of the Windows rows of [Not verified](../status.md#not-verified).

   A failure is fixed in the phase, or recorded as a known limit. The release (M10) is done
   only after the phase.
4. **D-0 is a Linux spike in M3.** `0001-desktop-shell.md` records the Linux result and lists
   the Windows items as not verified. If the testing phase finds a problem that changes the
   choice of Tauri, a new decision record supersedes 0001.
5. **M5 is done on Linux.** Its Windows demo moves to the testing phase.
6. macOS does not change: not tested, not blocked, no desktop app in v1.

## Consequences

- M3 is done when D-0 passes on Linux. M5 is done when its demo passes on Linux.
- Windows problems are found late, all at once, in M10. That costs more than finding them
  one milestone at a time. The mock tests of the Windows code paths are the only defence
  until then, so they stay a rule.
- A Windows-only problem with the Tauri shell (WebView2, the Job Object, the PyInstaller
  sidecar and antivirus) is found after D-1 to D-9 are built. If it changes the shell, more
  work is lost than in a Windows D-0.
- 01 open question 5 (how Windows is tested) is now answered for the testing phase only.

## Plan changes

- [01 §Platforms](../plan/01-scope.md#platforms): Linux primary, Windows in the testing phase.
  [01 §Open questions](../plan/01-scope.md#open-questions-owner-to-decide): question 5.
- [07 §Steps](../plan/07-desktop-app.md#steps): D-0 on Linux, its Windows items later; the
  Windows parts of D-3, D-7, D-8 and D-9 verified in the testing phase.
- [08](../plan/08-roadmap.md): the rule for "done", the dependency graph, M3, M5, M10 (the
  Windows testing phase).
- [09 §Q-1](../plan/09-quality-and-release.md#q-1-continuous-integration): Q-1.4 runs once, in
  M10.
- [../status.md](../status.md): M3, Q-1.4, Not verified.
- [../m3-breakdown.md](../m3-breakdown.md): M3 needs D-0 on Linux only.
