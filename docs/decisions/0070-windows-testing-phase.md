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

Result, 2026-11-04: on `m10-hardening` 13e8cd0 the 233 failed tests and the 3 spike modules
ran again on the VM, with FFmpeg not on `PATH`: 229 passed, 8 skipped (the 3 spike modules, 4
file names Windows cannot hold, a POSIX path with the byte 0xFF), 0 failed. Each task also ran
its changed test files in full on the VM, and every changed test file passes on Linux. The
whole suite has not run on Windows again since the fixes.

The CI matrix's Windows job (Q-1.1) has never run on GitHub; this phase stands in for it. The
Rust checks and the desktop items of the phase (D-0's Windows items, the M5 demo, D-3's Job
Object) are separate runs.

## Plan changes

None.
