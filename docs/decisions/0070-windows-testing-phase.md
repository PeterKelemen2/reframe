# 0070 — Windows testing phase: the first run of the CI commands on Windows

- Status: accepted
- Date: 2026-11-04
- Steps: Q-1.4, D-0, D-3, D-6 (Windows), S-2

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

## The Rust job

`ci.yml`'s desktop job (`npm run build:desktop`, then in `desktop/src-tauri` `cargo fmt
--check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`) compiled the shell's
`cfg(windows)` code for the first time, on the same VM (rustc 1.99.1, MSVC, Build Tools 2022
17.14), 2026-11-04:

- **No Windows icon** (a defect of the D-1 scaffold): tauri-build needs `icons/icon.ico` for
  the Windows resource file, and only the 32 px `icon.png` placeholder existed, so the app did
  not build on Windows at all. `icons/icon.ico` is generated from the same placeholder with
  `tauri icon` (16 to 256 px) and listed in `bundle.icon`; the real icons are a release item.
- **Dead code on Windows** (clippy `-D warnings`): `progress::DESKTOP_ENTRY` is used by the
  Linux launcher entry only, and a test helper of `backend/owner.rs` by the Linux data-folder
  tests only; both are compiled where they are used.
- **`open_paths` tests with POSIX paths**: `/home/u` is not absolute on Windows, so every path
  was dropped. The product is right (`Path::is_absolute`; a root-relative path takes the launch
  folder's drive); the tests write their paths in the platform's form.

Result: `cargo fmt --check` and clippy pass, `cargo test` 20 passed on Windows (the other tests
of the crate are Linux-only); on Linux 60 passed.

## The full run

The whole suite on Windows, 2026-11-04, `m10-hardening` 926c834 (FFmpeg not on `PATH`):
7428 passed, 2 failed, 203 skipped, 28 deselected in 35 minutes.

- **A regression of task B's crash rule.** "Any code from `0xC0000000` up is a crash" (copied
  from encoder detection, 0008) also takes FFmpeg's own error exit: on Windows FFmpeg exits with
  its negative `AVERROR` as an unsigned 32-bit code (`-22` is `0xFFFFFFEA`), and several of its
  tag codes are above `0xC0000000` (`AVERROR_EOF` `0xDFB9B0BB`, `AVERROR_BUG` `0xDEB8AABE`, the
  HTTP codes `0xCxxxxxxx`). So the silent-track encode failure read "ffmpeg crashed", and
  encoder detection would call an unexplained test-encode failure a crash. One rule now serves
  both (`reframe.tools.crashed`): a negative code (POSIX signal) or a system exception of the
  form `0xC000xxxx`, which no FFmpeg code has.
- **The fake tools' call log** was read while a file was being deleted or scanned, and Windows
  answered `PermissionError` (once in two full runs). The reader retries briefly on Windows.

Both fixed tests and their files pass on the VM (the capability service tests five times in a
row) and on Linux. With that, every failure of the Windows run is fixed: Q-1.4 is done.

## The desktop part and the open items (2026-11-09)

The owner set up a new VM and asked for the rest of the phase that does not wait for D-7 to D-9.

**The machine**: a libvirt VM on the owner's laptop (i5-8250U), Windows 10 Pro 2004 (19041.1, no
updates), 4 cores (1 socket: Windows 10 Pro uses at most 2 sockets, so 4 one-core sockets gave
it 2 processors), 6 GB, no GPU, 1600×900. `scripts/windows-setup.ps1` (new, rerunnable on any
Windows 10/11 machine) installed Git for Windows 2.56, uv with Python 3.14.10, Node 24.22.2,
VS Build Tools 2022, Rust 1.99.1, MKVToolNix 103.0, MediaInfo CLI 26.10, and an OpenSSH server
(the Win32-OpenSSH MSI: the Windows capability failed with 0x800f0950 without updates) with Git
Bash as its shell. The code came from the laptop by `git push` over SSH (the repository is
private). The app was the release build (`npx tauri build --no-bundle`) with the frozen sidecar,
started in the logged-in console session by a scheduled task, and driven through WebView2's
DevTools port (Playwright over CDP, and raw CDP where Playwright's focus emulation would
matter), Win32 and UI Automation for the native windows, and screenshots.

**D-0's Windows items** (all pass):

- The sidecar starts as the app's child, with no console window.
- **A kill from Task Manager** (`taskkill /F`, the same `TerminateProcess`) during a job that a
  CLI handed to the app: FFmpeg and the sidecar were gone about 0.3 s after the app, through the
  Job Object chain (the app's kill-on-close job holds the sidecar; the sidecar's own nested job
  holds FFmpeg). The CLI said "the connection to the Reframe server was lost" and `interrupted`.
  Unlike Linux (a death signal), the sidecar has no chance to clean up: the empty `.part` stayed
  until the next start, which removed it and marked the job interrupted.
- **WebView2 renders the UI** (Edge 157): the workspace, the preview frames, the log dialog, the
  magnifier's edge strips. **`cICP`**: a tone-mapped frame of `hdr10-4k.mkv` decoded in the page
  with `colorSpaceConversion: "none"` equals FFmpeg's rgb24 decode at 1640 sampled pixels;
  without the option 656 differ.
- **Drag-and-drop**: a real mouse drag (`SendInput`) of `Ünnepi film – 2.mkv` from an Explorer
  window onto the Sources panel gave the exact path; the file was probed and grouped.

**The M5 demo on Windows**: the app on its own sidecar; **Open files…** opened the Windows Open
dialog, and the chosen file was opened; the drop above; the M4 flow through the page's controls
(the NVENC preset's banner "NVIDIA driver not found", two Summary errors and **Add to queue**
disabled; the closest-match fix gives libx265; quality 30; audio tracks 3 → 2 → 3; Summary 0
errors; queued, `done`; the log, 121 lines, "Job done after 4.5 s"); taskbar progress (the
button's green fill); a Windows toast "Job done" when the window had no focus; a frozen
`reframe.exe encode` handed its job to the app ("Queue: Reframe 0.1.0.dev0 (pid 8036), shared
…"); closing the window while it ran asked "Quit Reframe? 1 job is running or paused", and
**Stop jobs and quit** ended the app, the sidecar and FFmpeg (about 7 s by one-second polls over
SSH; not measured finer), the CLI reported `interrupted`, no `.part` was left, and the next start
showed the job interrupted; open-with (`Reframe.exe vfr.mkv` while the app ran) handed the path
over and exited, and the file was selected; the kill above.

**D-3 on Windows**: the Job Object as above. Owner discovery: the app started while a
CLI-started owner ran used that owner (no sidecar of its own; the CLI's job was shown), so the
Rust `dirs` and the core's `platformdirs` agree on the data folder; killing that owner, the app
noticed within about 4 s (`process_alive`) and started its own sidecar, and the job became
interrupted. The frozen sidecar loads the bundled `MediaInfo.dll` (probes record "pymediainfo
7.0.1, libmediainfo 24.12").

**Not verified items checked**: a real console Ctrl+C reaches the CLI and cancels only its own
jobs (`remote/test_shared_queue_real.py` runs on Windows now: 9 passed, Ctrl+Z skipped);
Windows keeps a set `SO_RCVBUF`, and the stalled-client tests pass; the folder masks with the
default folders (the cache inside the data folder) work; file identity on a real SMB share:
an existing file has one key as `C:\…`, a mapped drive, `\\localhost\…`, `\\127.0.0.1\…` and in
upper case, and a new file has one key as a mapped drive and its UNC path (`realpath` resolves
the drive), but not as a local path and a UNC path; 14 symbolic-link tests that skipped on
every Windows machine run where links can be made, and pass; sleep inhibit holds
(`powercfg /requests` lists `reframe-server.exe` under SYSTEM while a job runs, and nothing
about 1 s after a cancel).

**Defects found and fixed**:

1. **The main window reached under the taskbar** (D-6): Windows placed it at 208,61 with
   1296×839 on a 1600×900 screen, so the status bar was hidden; on 1366×768 the minimum size
   (1100×700 plus the title bar) did not fit the 728-pixel work area at all. The window, a
   restored one too, is now shrunk and moved into its monitor's work area before it is shown
   (Windows only; on Linux the compositor places it), and the minimum is lowered where the
   screen is smaller. Checked: 1600×900 opens at 26,21 with 1296×839; 1366×768 at 52,0 with
   1296×728, the status bar visible; a state saved at 1600×900 restored at 1366×768 fits.
2. **Server folders not hidden on Windows** (S-2): a folder written with `/` (FFmpeg filter
   text, also with its escaped `C\:`) or in another case was not replaced by `<cache>` etc.
3. Test-only: the event hub's memory tests counted encoder detection's FFmpeg pipes (the
   proactor's 32 KiB read buffers); the owner tests read `server.json` while it was replaced
   (`PermissionError`); the real shared-queue tests' clients inherited "ignore Ctrl+C" from the
   SSH session; the symbolic-link tests above.

**The full run on this VM**, 2026-11-09 (`m10-hardening` 465d8c2, `REFRAME_REQUIRE_FFMPEG=1`,
FFmpeg not on `PATH`): `uv lock --check`, ruff, ruff format, mypy, the Rust job (`cargo fmt
--check`, clippy `-D warnings`, `cargo test`) and every frontend command pass; pytest 7447
passed, 2 failed, 194 skipped (42 min). The two failures: the `server.json` race (fixed, item
3), and FFmpeg itself: the Windows build crashes now and then (`0xC0000005`) when `fieldmatch`
runs before other filters (2 of 40 runs of the test's own command, 0 of 80 without
`fieldmatch`, the Linux build 0 of 80; `testdata/README.md`). Reframe reports such a job as
"ffmpeg crashed"; the test leaves Detelecine out on Windows, and the crash is a known limit.

**Not done, with the reason**: the installers (NSIS, MSI), file associations, the PATH offer and
whether an update drops it, and the notification's app identity (an app that is not installed
shows PowerShell's name and icon) wait for D-8; the bundled tools on Windows for D-7; the smoke
tests for D-9. Open-with bringing the window to the front needs a real double-click (a
background launcher may not give the foreground away). The magnifier's update rate and GPU
encoders need a GPU. The GitHub Windows jobs need a push.

## Consequences

Result, 2026-11-04: on `m10-hardening` 13e8cd0 the 233 failed tests and the 3 spike modules
ran again on the VM, with FFmpeg not on `PATH`: 229 passed, 8 skipped (the 3 spike modules, 4
file names Windows cannot hold, a POSIX path with the byte 0xFF), 0 failed. Each task also ran
its changed test files in full on the VM, and every changed test file passes on Linux. The
whole suite has not run on Windows again since the fixes.

The CI matrix's Windows job (Q-1.1) has never run on GitHub; this phase stands in for it. The
desktop items of the phase (D-0's Windows items, the M5 demo, D-3's Job Object in the running
app) were deferred on 2026-11-04 and done on 2026-11-09 (above). What is left of the phase waits
for D-7, D-8 and D-9: their Windows parts are checked when they are built.

## Plan changes

None.
