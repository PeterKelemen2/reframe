# 0054 — D-0 spike layout, its checks, and the server's parent watch

- Status: accepted
- Date: 2026-10-23
- Steps: D-0, S-0

## Context

D-0 ([07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along))
is a spike: a minimal Tauri 2 app, a PyInstaller onedir build of `reframe-server` as its
sidecar, measurements, and WebKitGTK checks. The plan does not say where the spike code
lives, whether it is committed, or how its code is checked. D-1 makes `desktop/src-tauri/`
and D-2 makes `desktop/sidecar/build.py`, so the spike must not take those paths.

[07 §Sidecar lifecycle](../plan/07-desktop-app.md#sidecar-lifecycle) starts the sidecar with
`--parent-pid <pid>`, and on Linux "the server watches `--parent-pid` and exits when the parent
is gone". D-0 must prove that cleanup. But [06 §S-0](../plan/06-web-app.md#s-0-package-skeleton)
has no `--parent-pid`, and `reframe-server` does not have it:

```
$ grep -rn 'parent' packages/reframe-server/src
$
```

The machine for the spike (checked 2026-10-23): CachyOS, KDE Plasma on Wayland, Intel UHD 620,
NVMe SSD; rustc / cargo 1.99.1 stable; WebKitGTK `webkit2gtk-4.1` 2.54.1, libsoup 3.8.0,
GTK 3.24.52, librsvg 2.63.3, OpenSSL 3.6.5, xdotool. The Tauri 2 prerequisites page lists
`libappindicator-gtk3` for Arch. That package name no longer exists in the Arch repositories
(`pacman -Si libappindicator-gtk3`: not found; the package is now `libappindicator`), and
`libayatana-appindicator` 0.6.1 is installed. The spike has no tray, so this does not block
D-0. D-6 (tray) checks it again. No Chromium is installed; `sudo` needs a password.

## Decision

1. **The spike lives in `desktop/spike/` and is committed**, so that the measurements can be
   reproduced. CI does not build it. D-1 and D-2 may reuse its code or delete the folder.
   Layout:
   - `desktop/spike/src-tauri/`: the Tauri 2 app (`Cargo.toml`, `Cargo.lock`,
     `tauri.conf.json`, `capabilities/`, `src/`).
   - `desktop/spike/ui/`: the spike pages (Vite + Vue). They are not F-x components.
   - `desktop/spike/package.json` + `package-lock.json`: `@tauri-apps/cli`,
     `@tauri-apps/api`, and the UI's build tools. Vue, PrimeVue and `@primeuix/themes` use
     the same versions as `frontend/package-lock.json`, so the WebKitGTK checks see the
     versions the UI will use.
   - `desktop/spike/scripts/`: the Python of the spike (the sidecar build, the measurement
     scripts).
   - `desktop/spike/README.md`: how to build and run it, and how to repeat each measurement.
   - Build output stays out of git: `desktop/spike/src-tauri/target/`,
     `desktop/spike/src-tauri/gen/`, and the PyInstaller `build/` and `dist/` folders (the
     existing `build/` and `dist/` patterns of `.gitignore`).
2. **How the spike is checked.** The Python in `desktop/spike/scripts/` follows the same rules
   as `scripts/`: `ruff check`, `ruff format --check` and strict `mypy` run on it (the
   `desktop` exclusion in ruff's configuration is narrowed to `desktop/spike/src-tauri` and
   `desktop/spike/ui`, and mypy's `files` gets `desktop/spike/scripts`). The Rust code is
   checked by the spike's author and by the lead before a merge with `cargo fmt --check` and
   `cargo clippy --all-targets -- -D warnings`; CI does not run them, because CI does not
   build the spike. The spike's UI is checked by its production build (`vite build`); it is
   not linted. D-1 decides the checks for the real app.
3. **Versions** (current stable on 2026-10-23): crates `tauri` 2.12.5 and `tauri-build` 2.7.4,
   with `Cargo.lock` committed; npm `@tauri-apps/cli` 2.12.4 and `@tauri-apps/api` 2.12.4,
   with `package-lock.json` committed; PrimeVue 4.5.5, `@primeuix/themes` 2.0.3, Vue 3.5.43,
   Vite 8.3.4 (the frontend's pins); PyInstaller 6.22.3 as a dev dependency of the workspace
   (`pyinstaller>=6.22.3` in the root `dev` group, pinned in `uv.lock`). The spike does not
   use `tauri-plugin-shell`: it spawns the sidecar with `std::process` / `tokio::process`, as
   D-3 will, so it can set the child's death signal.
4. **`--parent-pid` is part of S-0.** `ServerConfig.parent_pid` (`REFRAME_PARENT_PID`; `None`
   by default) and `reframe-server --parent-pid PID`. When it is set, the server watches that
   process and, when it ends, stops the way `POST /api/system/shutdown` does (the queue
   cancels its jobs, the facade closes), with a hard exit if the stop does not end in time.
   The watch must not take a reused pid for the parent. On Linux the desktop shell also gives
   the sidecar a death signal (`PR_SET_PDEATHSIG` in `pre_exec`): the parent watch is the
   second line, for a parent that is not the direct parent and for the platforms without a
   death signal. The Windows path of the watch is written and mock-tested on Linux
   ([0053](0053-linux-first-windows-testing-phase.md)).

## Consequences

- The spike is reproducible from the repository, and nothing in CI depends on it.
- The spike's Rust and UI code are checked by hand only. That is acceptable for code that D-1
  may delete; it is not acceptable for `desktop/src-tauri/` (D-1 decides).
- PyInstaller is installed by `uv sync` on every machine, also in CI, where it is not used.
- The parent watch is server code with tests in CI; the desktop shell of D-3 relies on it.

## Plan changes

- [06 §S-0](../plan/06-web-app.md#s-0-package-skeleton): `parent_pid` in `ServerConfig`, the
  `--parent-pid` option and the watch.
- [07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along):
  where the spike lives.
- [../m3-breakdown.md](../m3-breakdown.md): waves 4 to 6.

## Follow-up (4a), 2026-10-23

The parent watch is `reframe_server/parent.py`; `serve` starts it before uvicorn when
`parent_pid` is set. Tests: `packages/reframe-server/tests/test_parent.py`.

1. **Linux mechanism: a pidfd and the start time.** The watch opens `pidfd_open(pid)`, then
   reads the start time of `pid` (field 22 of `/proc/<pid>/stat`) and of its own process. A
   parent starts before its child, so a process with that pid that started later has a reused
   pid: the parent is gone. The start time is read after the pidfd is open, so when the check
   passes the pidfd is the parent's; a pidfd stays with its process when the pid is reused
   later. A daemon thread waits until the pidfd is readable (the process has ended). The thread
   does not need the event loop: it also works when the loop is blocked. The start-time check
   also accepts a parent that is not the direct parent (for example the app above
   `uv run reframe-server`).
2. **Windows mechanism** (written to the plan, mock-tested on Linux only, [0053](0053-linux-first-windows-testing-phase.md)):
   `OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION)`; the creation times of both
   processes from `GetProcessTimes` (the parent must not be younger); `WaitForSingleObject(…,
   INFINITE)` on the thread. Windows does not reuse a pid while a handle to the process is
   open. A failed `OpenProcess` counts as "not running"; a failed `GetProcessTimes` closes the
   handle and raises `OSError` (the server does not start).
3. **A parent that is already gone at start-up** (no such pid, or the pid of a younger
   process): `serve` returns **1** before uvicorn starts, prints
   `reframe-server: the parent process <pid> is not running` on stderr and no ready line. The
   shell that started the server is gone, so nobody would use it. (A pid ≤ 0 is an invalid
   option: exit 2.)
4. **When the parent ends**: the thread logs `The parent process <pid> ended: the server stops`
   (WARNING) and calls `request_shutdown()` on the event loop, the same call as
   `POST /api/system/shutdown`. A graceful stop ends with exit code **0**, as after the
   shutdown request: running jobs end `interrupted` and their `.part` files are removed.
5. **The hard exit**: if the process still lives **5 s** (`STOP_LIMIT`) after the stop request,
   the thread calls `os._exit(70)` (`EX_SOFTWARE`). The 5 s are the time the desktop shell
   gives a normal quit before it kills the server (uvicorn's 2 s connection grace, then the
   facade's close); the countdown also covers a process that hangs after uvicorn returned
   (`asyncio.run` waits for the default executor's threads). The FFmpeg children die with the
   server at a hard exit: the core gives them `PR_SET_PDEATHSIG = SIGKILL` (Linux) or puts them
   in its kill-on-close job (Windows). After a normal stop, `serve` closes the watch, so a
   parent that ends later changes nothing; a countdown that has started still runs until the
   process ends.
6. **Measured** (frozen sidecar in the spike app, an x265 encode of `hdr10-4k.mkv` running,
   `desktop/spike/scripts/cleanup.py`): after `kill -9` of the app, the sidecar and its FFmpeg
   were gone in 0.26 s with both the death signal and the watch, 0.57 s with the watch alone,
   0.18 s with the death signal alone; with neither, the sidecar ran on and finished the
   encode as an orphan. In every case with a mechanism the job was `interrupted` and its
   `.part` file was removed before the process ended. In the test (unfrozen server, a
   stand-in parent killed by SIGKILL during a real encode) the server ended 0.52 s after the
   kill, exit code 0, in three runs out of three.
7. **The shell's death signal is SIGTERM**, not SIGKILL: uvicorn handles SIGTERM like the
   shutdown request, so the server stops gracefully (the run with the death signal alone
   above). The watch then is the second line, and its hard exit covers a stop that hangs. The
   shell forks on its main thread: the death signal follows the thread that forked, not the
   process (checked; `testdata/README.md` "D-0 (4a)").

## Follow-up (review), 2026-10-27

The review of D-0 found that the start-time check of item 1 (`<=`) accepts a process that got
the parent's pid in the clock tick in which the server started (10 ms), and, for a parent that
is not the direct parent, one that got it before the server started. This adds to item 1; the
decision stays.

1. **A live ancestor is the parent, exactly.** After the pidfd is open, the watch walks up from
   the server's parent (`os.getppid()`, then field 4 of each `/proc/<pid>/stat`). A pid on that
   chain is accepted: a live ancestor has held its pid since before the server started, so the
   pidfd is its. Each link is read again from the server up, so a process that ended during
   the walk (its child then has another parent) makes the check fail. The direct parent needs
   no `/proc` read.
2. **Any other pid needs a start one tick earlier** (`<`, not `<=`). Measured on 2026-10-27
   (`SC_CLK_TCK` 100, kernel 7.3): a Python started through `timeout 60` shared the start tick
   of `timeout` in 198 of 200 runs; through `timeout 60 timeout 60` it shared the outer
   `timeout`'s tick in 177 of 200; `uv run` and its Python shared it in 4 of 20. So `<` alone
   would refuse a real parent most of the time; the ancestor check accepts these exactly. A
   stand-in that is not an ancestor (a sibling, in the tests) must start a tick before the
   server: the tests wait 30 ms after starting it. The old frozen-sidecar test did not, and a
   build with this check refused its stand-in (exit 1, no ready line).
3. **The window left.** A process that is not a live ancestor of the server and that got the
   parent's pid at least one tick before the server started is taken for the parent. For the
   direct parent that cannot happen: it lived when it forked the server, so a reuse comes after
   the server's start. For a parent above it (the app above `uv run`), it is a parent that ended,
   and whose pid was given to a new process, between its fork of `uv` and `uv`'s fork of the
   server, less one tick. A reuse also needs the kernel's pid counter to come round
   (`pid_max` 4194304 here). D-3 starts the frozen sidecar as the direct child.
4. Tests (`test_parent.py`): a process started in the server's tick is the parent as its parent
   or grandparent and not as a younger process; a younger process whose name holds `)` and a
   space is not the parent; an in-process `serve()` stopped by `POST /api/system/shutdown` exits
   with 0 and the parent's end afterwards brings no hard exit; the hard exit's code is 70.
