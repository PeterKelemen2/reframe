# 0070 — Windows testing phase: the first run of the CI commands on Windows

- Status: accepted
- Date: 2026-11-04
- Steps: Q-1.4

## Context

The Windows testing phase at the start of M10 ([0053](0053-linux-first-windows-testing-phase.md),
[08 §Windows testing phase](../plan/08-roadmap.md#windows-testing-phase)) runs the Python and
frontend commands of `ci.yml` on Windows for the first time (Q-1.4).

The machine: a libvirt VM on the owner's AMD desktop, Windows 10 Pro 22H2 (build 19045), 4 vCPUs,
8 GB RAM, no GPU passed through; Python 3.14.10 (uv), Node 24.22.2, Git for Windows 2.56,
FFmpeg n9.0.2 from `reframe tools fetch` (origin `bundled`, not on `PATH`), MKVToolNix 103.0 and
MediaInfo CLI 26.10 on `PATH`. The commands ran in Git Bash over SSH, as CI's `shell: bash`.

First run, 2026-11-04, on `main` 152a906:

- `uv lock --check`, `ruff check`, `ruff format --check`, `mypy` (533 files): pass.
- `npm ci`, `lint`, `fmt:check`, `typecheck`, `npm test` (1940 tests), `build:web`,
  `build:desktop`: pass.
- `pytest -m "not needs_gpu and not benchmark"`: collection stops with 3 errors (the desktop
  spike's test modules import `fcntl` and `signal.SIGKILL`). Without those 3 modules: 7184
  passed, 228 failed, 6 errors, 199 skipped, in 38 minutes.

Of the 234 failures, 62 pass when the bundled FFmpeg's folder is on `PATH`: a test that makes a
Reframe with private folders does not see the bundled build of the session's data folder, and
on Linux the system FFmpeg on `PATH` hides that. Most of the other 172 are tests that assume
Linux (POSIX paths in expected values, POSIX shell quoting in plan snapshots, file names that
Windows does not allow, uv's `python.exe` launcher being a separate process). A few are product
defects on Windows.

## Decision

Every failure is fixed, or made a platform-specific test with the reason, in this phase; none is
recorded as a known limit unless it cannot be fixed on Windows 10.

- A test that checks Linux-only behaviour is skipped on Windows, or gets the Windows variant of
  its expectation, with the reason in the skip or the parameter id.
- A product defect is fixed with a test that failed on Windows before the fix.
- The re-run on the VM runs exactly the tests that failed (`pytest @ids`), with FFmpeg not on
  `PATH`, as CI has it.

Wave 0 (the lead):

1. The test plugin puts the bundled FFmpeg's folder on `PATH` for the session when no ffmpeg is
   on `PATH` and the bundled build needs no environment of its own (the Linux bundle's `lib/`
   does, so Linux is unchanged).
2. The desktop spike's test modules skip where `fcntl` does not exist
   (`pytest.importorskip`). `collect_ignore` in a `conftest.py` is not enough: a module named on
   the command line is collected anyway.

The other failures are split by area into tasks A, B and C (below).

## Task A — plans, commands and validation

Product defects (tool behaviour: `testdata/README.md`, "Windows: paths in parameters and filter
text, file times"):

1. **A re-saved subtitle file kept its old encoding.** Validation caches a file's encoding by
   path, device, inode, size, mtime and `st_ctime`. On Windows `st_ctime` is the creation time,
   so a rewrite of the same size with the mtime set back hit the cache. The key now uses NTFS's
   change time there (`FILE_BASIC_INFO.ChangeTime`), which every write moves. It moves in clock
   ticks (up to 15.6 ms), so the test saves the file again 50 ms later, as a person would; with
   that pause it still failed on Windows before the fix.
2. **The fix for a refused custom parameter left part of a Windows path behind.** `csv=C:\x\l.csv`
   splits at the drive colon (FFmpeg's parser too), so "Remove csv=C" left `\x\l.csv` as an
   entry, and for VP9 a second error. An entry after a `:` inside single quotes, or after a lone
   drive letter and before `\` or `/`, now belongs to the parameter before it for the fix (also
   the dry run's fix). The refusal never depended on the value; the split that the builder and
   validation share is unchanged, so an entry such as `/x` after an allowed one is still checked
   on its own.
3. **Recorded data**: the Windows build's QSV encoders have `dual_gfx` and `vcm`. The recorded
   private options (the fallback when detection has not run) list every build Reframe ships, so
   they were added.

Tests:

- **Plan snapshots: one `.ambr` for both platforms**, unchanged. The test pins the display style
  of the case (POSIX unless it asks for Windows); on Windows it gives the case's paths back their
  `/` before it compares (a plan string that starts with a case path's folder, and its quoted form
  in `display`). Filter and x265 stats paths already have `/` on Windows. A Windows `.ambr` would
  need a Windows run after every builder change; the Windows-only parts (cmd quoting, Windows
  filter paths, drive colons) have unit tests that run on both platforms. The `*_windows_display`
  cases failed on Windows for the path separators only. The case whose subtitle name holds `\`,
  `"` and `:` is skipped on Windows.
- Expected paths built with `Path` instead of POSIX literals.
- Paths in custom parameters and filter text are written as FFmpeg's parsers need them
  (`escape_value`, `quote_value`), as the builder does. With that, FFmpeg on Windows reads a file
  through `/option` filter text too, so the server's refusal is needed there; the refusal test
  also uses the Windows form.
- Platform expectations: `output.name_not_portable` is an error for a Windows path
  ([0014](0014-validation-rules-and-severities.md)), so the rule cases and the snapshot job whose
  output name has `:` expect an error there. On Windows `realpath` and `resolve` do not raise for
  a NUL path, and `x\..\y` is `y` even when `x` does not exist.
- Skipped on Windows, as names Windows cannot hold: subtitle file names with `\`, `"` or `:`
  (`a:b` is an NTFS stream there). A name with the other special characters was added.

## Task B — processes, queue, server and tools

Placeholder: filled when B merges.

## Task C — CLI, models, settings, batch and media

Placeholder: filled when C merges.

## Consequences

The CI matrix's Windows job (Q-1.1) has never run on GitHub; this phase stands in for it. The
Rust checks and the desktop items of the phase (D-0's Windows items, the M5 demo, D-3's Job
Object) are separate runs.

## Plan changes

None.
