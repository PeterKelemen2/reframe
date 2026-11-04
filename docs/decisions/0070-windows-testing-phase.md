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

Placeholder: filled when A merges.

## Task B — processes, queue, server and tools

Placeholder: filled when B merges.

## Task C — CLI, models, settings, batch and media

Product defect:

- **A folder given as a chapter file was reported as "The file cannot be read: Permission
  denied."** `textfile.open_regular` documents `IsADirectoryError` for a folder, but on Windows
  `os.open` of a folder raises `PermissionError` (EACCES, checked on the VM), so
  `read_chapter_file` fell through to its generic message. Fix: on `PermissionError`,
  `open_regular` raises `IsADirectoryError` when the path is a folder; this serves every caller
  of `open_regular` (chapter files, subtitle files, charset reads). The test of a folder as a
  chapter file failed on Windows before the fix.

Platform differences that are not defects:

- **A case-insensitive file system.** The draft of `movie.mkv` in `Movie.2016…-GRP/` names the
  output `Movie.mkv`, which on Windows is the source itself (`samefile` is true, checked on the
  VM), so the draft correctly takes `Movie (1).mkv`. The tests compute the expected name from
  the file system, so Windows runs the "name is the source" path and Linux the plain one.
- **Paths in expected text.** Expected strings are built with `Path`, or the JSON is parsed
  before it is compared, instead of POSIX literals.
- **Lone surrogates.** The JSON writer's escape of a lone surrogate is tested on Windows too,
  with strings that are not paths or with checks that do not depend on the separator. Only the
  probe cache case whose key is a POSIX path with the byte 0xFF is skipped: no Windows name
  holds it (the cache's lone-surrogate case runs there).
- **Control characters in file names.** Windows does not allow them in a name, so the tests
  that also put ESC in a file name keep their title (metadata) checks on Windows and make the
  file-name part POSIX-only.
- **Test ids in the environment.** pytest puts the current test id in `PYTEST_CURRENT_TEST`;
  Windows limits a variable to 32767 characters, and one parameter id (200 000 brackets) was
  longer. That case has a short id now, so its node id changed (`[deep-nesting]`).

## Consequences

The CI matrix's Windows job (Q-1.1) has never run on GitHub; this phase stands in for it. The
Rust checks and the desktop items of the phase (D-0's Windows items, the M5 demo, D-3's Job
Object) are separate runs.

## Plan changes

None.
