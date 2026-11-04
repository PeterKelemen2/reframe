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

Product defects, each with a test that failed on Windows before the fix:

- **The path jail let a path with a NUL through, in both modes.** On Windows,
  `Path.resolve(strict=False)` returns a path with an embedded NUL unchanged (`ntpath.realpath`
  catches the `ValueError`); on Linux it raises. The jail now refuses a NUL before it resolves
  (400 `path.invalid`). The test covers the web and desktop modes.
- **A tool that crashed on Windows was reported as a plain failure.** A Windows exception ends a
  process with an NTSTATUS code (`0xC0000005`, a positive number in Python), not a negative
  signal. The job error was "Pass 2 failed (exit code 0xC0000005): <last stderr line>". It is
  now "ffmpeg crashed during pass 2 (exit code 0xC0000005).": a code of `0xC0000000` or more is
  a crash (`queue.errors.crashed`), as encoder detection already reads it
  ([0008](0008-encoder-detection-reasons-and-filters.md)).
- **`scripts/export-openapi.py` failed when it wrote to stdout on Windows.** A pipe gets the
  ANSI code page (cp1252 cannot encode `→`) and CRLF. It now writes UTF-8 bytes.
  `gen-api.sh` passes a file name, so CI's api-contract job did not have the defect.

uv's `python.exe` in a venv on Windows is a launcher: it starts the base interpreter as a
child process, ends with the child's exit code, and its job object kills the child when the
launcher is killed (checked on the VM). This is not a product defect. A CLI that starts the
queue's owner (`.venv\Scripts\python.exe -m reframe_server`) uses only the started process's
exit code, which the launcher passes on (75 stays 75). `server.json` names the interpreter's
pid. The owner outlives the CLI, a kill of the launcher ends the owner, and the idle exit
ends both (checked with `reframe.exe encode --detach` on the VM). A job's process is never a
launcher (on Windows a tool must be an `.exe`), and a pause suspends the whole process tree.
The tests that compare pids or suspend one process use `reframe_testing.processes.interpreter`
or the base interpreter.

Test-only causes:

- **Linux-only, or a Windows expectation:** a file name with C0 control characters cannot exist
  on Windows (skipped there; a C1 case runs everywhere); the lock backend is msvcrt on Windows;
  two output paths that differ only in case have one key on Windows (`normcase`).
- **Portable tests:** expected paths built with `os.sep` or `Path`, and JSON-escaped where they are
  compared with JSON; the `.cmd` fake tools need `REFRAME_ALLOW_SCRIPT_TOOLS`, and a test that
  clears `REFRAME_*` must keep it; Linux-named fake tools for the `platform="linux"` LIBVA tests;
  a directory link cannot be replaced by a rename on Windows, so the test removes it first.
- **Judgement calls:** pydantic-core serializes only 100 levels on Windows (256 on Linux). The
  queue store's limit of 64 is still below that limit, and the nesting test checks this on both
  platforms. FFmpeg's Matroska muxer takes quadratic time in the number of subtitle packets on
  Windows (50, 100 and 200 loops of the 4 s test file: 0.3, 3.6 and 16 s; 200 loops with
  `-live 1`: 0.25 s). The analysis cancel test therefore writes its 2-hour file as a live file
  there. That file has no cues and no duration, so on Windows the test does not check the
  probed duration.

## Task C — CLI, models, settings, batch and media

Placeholder: filled when C merges.

## Consequences

The CI matrix's Windows job (Q-1.1) has never run on GitHub; this phase stands in for it. The
Rust checks and the desktop items of the phase (D-0's Windows items, the M5 demo, D-3's Job
Object) are separate runs.

## Plan changes

None.
