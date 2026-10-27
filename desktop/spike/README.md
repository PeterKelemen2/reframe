# D-0 desktop spike (Linux)

A minimal Tauri 2 app whose sidecar is the PyInstaller **onedir** build of `reframe-server`.
It answers the D-0 questions on Linux: cold start, cleanup, hidden imports, and (task 4b) the
WebKitGTK checks. Layout and checks: [decision 0054](../../docs/decisions/0054-d0-spike-layout-and-parent-watch.md).
CI does not build it. D-1 and D-2 may reuse or delete it. Nothing here runs on Windows.

| Path | What |
|------|------|
| `src-tauri/` | The shell (Rust): `src/sidecar.rs` starts, watches and stops the sidecar |
| `ui/` | The page (Vite + Vue): the ready state, `GET /api/health`, page times |
| `scripts/` | Python: the onedir build, the smoke run, the measurements. Run them from the repository root as modules (`uv run python -m desktop.spike.scripts.<name>`) |
| `dist/reframe-server/` | The onedir build (git-ignored) |

## Build

From the repository root (`uv sync` done, the Tauri 2 prerequisites installed):

```sh
uv run python -m desktop.spike.scripts.build_sidecar   # dist/reframe-server/, about 40 s
cd desktop/spike
npm ci
npx tauri build --no-bundle                            # src-tauri/target/release/reframe-spike
```

`tauri build` runs `npm run build:ui` first, then
`cargo build --bins --features tauri/custom-protocol --release`. A plain `cargo build` has no
`custom-protocol` feature: the app then loads the Vite dev server (`npm run dev:ui`).

Checks (by hand; CI does not run them):

```sh
cargo fmt --manifest-path desktop/spike/src-tauri/Cargo.toml --check
cargo clippy --manifest-path desktop/spike/src-tauri/Cargo.toml --all-targets -- -D warnings
npm --prefix desktop/spike run build:ui
uv run ruff check && uv run ruff format --check && uv run mypy     # the scripts too
uv run pytest packages/reframe-server/tests/test_frozen_sidecar.py # skipped without dist/
```

## Run

```sh
desktop/spike/src-tauri/target/release/reframe-spike
```

The window shows `GET /api/health` of the sidecar, or why the sidecar is not running. The
shell:

- starts the sidecar on its **main thread, before it creates the window**:
  `reframe-server --mode desktop --port 0 --auth token --parent-pid <its pid>`, with a token made
  in Rust (32 random bytes, hex) in `REFRAME_TOKEN`, and the sidecar's config, data and cache
  folders in a temporary folder (`$TMPDIR/reframe-spike-<pid>/`, kept after the exit for its
  log). The sidecar's stderr goes to `<that folder>/data/sidecar.log`;
- sets `PR_SET_PDEATHSIG = SIGTERM` in the child (`pre_exec`): SIGTERM makes uvicorn stop the
  way `POST /api/system/shutdown` does. The death signal follows the thread that forks, so the
  fork is on the main thread (the `sidecar_spawned` line shows `thread == main_thread`);
- reads stdout until the ready line (20 s); an early exit or a timeout shows the error and the
  log path on the page, with no restart (D-3);
- answers `backend_info` (`{baseUrl, token}`) when the sidecar is ready;
- on quit (a closed window, or `quit` on stdin) sends `POST /api/system/shutdown`, waits up to
  5 s, then kills the sidecar.

Variables for the measurements:

| Variable | Effect |
|----------|--------|
| `REFRAME_SPIKE_HOME` | the sidecar's folder instead of a new temporary one |
| `REFRAME_SPIKE_SIDECAR` | the sidecar command, split at spaces (for example `uv run --project /path/to/repo reframe-server`) |
| `REFRAME_SPIKE_EXIT_AFTER_HEALTH` | quit once the page shows the health answer |
| `REFRAME_SPIKE_SPAWN_IN_SETUP` | start the sidecar in Tauri's setup hook, after the window |
| `REFRAME_SPIKE_NO_DEATH_SIGNAL` | no `PR_SET_PDEATHSIG` |
| `REFRAME_SPIKE_NO_PARENT_PID` | no `--parent-pid` |
| `REFRAME_SPIKE_REPORT_TOKEN` | the `sidecar_ready` line carries the token (the cleanup script drives an encode) |

The shell prints one JSON line per event on stdout (`sidecar_spawned`, `sidecar_ready`,
`page_health`, `page_failed`, `sidecar_failed`, `sidecar_stopped`), with `ms` since `main()`.

## The onedir build: what it needs

`scripts/build_sidecar.py` lists each PyInstaller option with what goes wrong without it.
`--without NAME` leaves one out, `--bare` all of them, `--dist PATH` builds elsewhere.
`uv run python -m desktop.spike.scripts.smoke_sidecar [--unfrozen]` calls the routes that read
bundled data, probes a copy of `multitrack.mkv` named `Show.Name.S01E02.1080p.BluRay.x264-GRP.mkv`
and prints the answers; the frozen and the unfrozen server give the same answers.

| Option | Without it (PyInstaller 6.22.3, hooks-contrib 2026.9) |
|--------|--------------------------------------------------------|
| `--collect-data babelfish` | start-up crash: `FileNotFoundError: [Errno 2] No such file or directory: '…/_internal/babelfish/data/iso-3166-1.txt'` |
| `--collect-submodules babelfish` | start-up crash: `ModuleNotFoundError: No module named 'babelfish.converters.alpha2'` (babelfish loads its converters from entry-point strings) |
| `--collect-data reframe.presets` | `FileNotFoundError: … '…/_internal/reframe/presets/data/builtin.json'`, `Application startup failed. Exiting.`, exit 3 |
| `--collect-data language_data` | `GET /api/languages`: 500, `FileNotFoundError: … '…/_internal/language_data/data/language-subtag-registry.txt'` |
| `--collect-data reframe.definitions` | **no error at start-up**: the loader reads a missing file as empty, so `GET /api/definitions` has 0 video encoders and `POST /api/jobs/draft` is a 500 (`KeyError: 'mkv'` in `reframe/batch/audio_rules.py`) |
| `--collect-data reframe.tools` | `POST /api/system/tools/fetch`: the task fails with `cannot read the manifest …/_internal/reframe/tools/ffmpeg.toml: No such file or directory` |
| `--collect-data guessit` | **no error**: guessit raises `FileNotFoundError: … '…/_internal/guessit/config/options.json'` (seen in a frozen guessit-only probe), the core reads a guessit failure as "no match", so every name parses to its whole stem (no season, episode, resolution, source or group) |
| `--hidden-import pymediainfo` | **no error**: the core imports it with `importlib.import_module`, so it is not collected; the probe runs without MediaInfo (`vfr.mkv`: video bitrate `unknown` instead of 483043 from MediaInfo) |
| `--add-binary …/pymediainfo/libmediainfo.so.0:pymediainfo` | the build warns `MediaInfo shared library not found - pymediainfo will likely fail to work!`: the hook's default patterns (`lib*.so`) miss the wheel's `libmediainfo.so.0`; the probe runs without MediaInfo as above |
| `--exclude-module mypy`, `--exclude-module hypothesis` | no error; 7 MB more: pydantic's hook collects `pydantic.mypy` (imports mypy, which pulls `ast_serialize` and `librt`) and `pydantic.v1._hypothesis_plugin` (imports hypothesis) |

Needed no option, because a hook of `pyinstaller-hooks-contrib` covers it: **pydantic**
(`hook-pydantic.py`: every submodule, 104 modules), **uvicorn's loops and protocols**
(`hook-uvicorn.py`: every submodule, `uvicorn.loops.auto`, `uvicorn.protocols.http.*`,
`uvicorn.protocols.websockets.*` are in the build; the event WebSocket works frozen),
**langcodes** data (`hook-langcodes.py`), websockets, platformdirs, psutil.

The build: 82.5 MB in 1014 files (`du -sb`); the executable is 15.9 MB, `libmediainfo.so.0`
14 MB, `language_data` 12 MB. The bootloader runs Python in its own process (no child):
`/proc/<pid>/exe` is the frozen binary and its only children are the tools it starts.

**FFmpeg**: the frozen server looks for a bundled build in `<onedir>/tools/ffmpeg/bin/` and
`<onedir>/../tools/ffmpeg/bin/` (`reframe.paths.bundled_tool_roots`, frozen), before `PATH`;
`REFRAME_FFMPEG` / `REFRAME_FFPROBE` come first. Checked: with the pinned build linked at
`dist/reframe-server/tools/ffmpeg`, `GET /api/system` says `origin: bundled`,
`n9.0.2-17-g2a571b6068-20260930`; without it `origin: path`, `/usr/bin/ffmpeg`.

## Cold start

```sh
uv run python -m desktop.spike.scripts.cold_start --all --runs 10 --json /tmp/cold.json
```

Each run gets new temporary folders. *Sidecar*: from just before the spawn to the ready line.
*App*: from just before the spawn of the app to the `page_health` line (printed when the page
has drawn the health answer). *Warm* runs one start first that is not counted. *Evicted*
drops the page cache of the measured files before each run with
`posix_fadvise(POSIX_FADV_DONTNEED)` and checks with `fincore` that nothing of them is cached.

Results on 2026-10-23 (Intel UHD 620 laptop, 8 threads, NVMe SSD, KDE Plasma on Wayland;
10 runs each; seconds; target < 2 s):

| Case | Cache | Median | Worst | Best |
|------|-------|-------:|------:|-----:|
| sidecar alone, frozen onedir | warm | 1.176 | 1.212 | 1.165 |
| sidecar alone, frozen onedir | evicted | 1.393 | 1.445 | 1.368 |
| sidecar alone, `uv run reframe-server` | warm | 1.167 | 1.261 | 1.144 |
| sidecar alone, `uv run reframe-server` | evicted (user files) | 1.492 | 1.563 | 1.415 |
| app, frozen onedir | warm | 1.338 | 1.372 | 1.307 |
| app, frozen onedir | evicted (+ the app binary) | 1.469 | 1.526 | 1.461 |
| app, frozen onedir, sidecar started in the setup hook | warm | 1.441 | 1.491 | 1.430 |
| app, frozen onedir, sidecar started in the setup hook | evicted | 1.597 | 1.662 | 1.563 |
| app, `uv run reframe-server` | warm | 1.302 | 1.342 | 1.276 |

Inside the app (medians, from `main()`): the sidecar is spawned at 3 ms (137 ms in the setup
hook), its ready line comes at 1.254 s warm / 1.365 s evicted, and the page shows the health
answer 30 ms later; the page itself is mounted 20 ms after its navigation starts. The page
cache of the measured files before and after each eviction (`fincore`): the onedir 38 to
85 MB → **0 bytes** of 82.5 MB; onedir and app binary 44.5 to 49.7 MB → **0 bytes** of
94.0 MB; for `uv run`, 47 to 163 MB → 28.2 MB of 236 MB (left: files that a running process
maps, see below).

What the eviction does not drop: the system libraries (glibc, GTK, WebKitGTK and its helper
processes, the system Python of the unfrozen server and its standard library), the kernel's
dentry and inode caches, and pages that a running process maps (for the unfrozen server: the
`uv` binary of the `uv run` that runs the measurement). `fincore` cannot count files the user
cannot write (`fincore: failed to do cachestat: /usr/lib/python3.14/os.py: Operation not
permitted`), so the system files were left alone. A first start after a reboot also reads
WebKitGTK from disk: these numbers do not cover that.

Where the time goes (unfrozen, `python -X importtime -c "import reframe_server.__main__"`,
warm): 1.04 s of imports, of which `reframe` 372 ms (most in building the pydantic models of
`reframe.models` and `reframe.definitions.models`), `reframe_server` 181 ms (the routers'
models), `fastapi` 104 ms (`fastapi.openapi.models` 68 ms), `pydantic` 52 ms, `guessit` 30 ms,
`langcodes` 26 ms. Uvicorn and the lifespan add about 0.1 s. Starting the sidecar before the
window saves about 0.1 s (warm) to 0.13 s (evicted) against starting it in the setup hook.
If the target is ever missed: import `guessit`, the analysis and the batch modules on first
use, and build rarely used pydantic models on first use (`defer_build`).

## Cleanup proofs

```sh
uv run python -m desktop.spike.scripts.cleanup app-kill       # kill -9 of the app
uv run python -m desktop.spike.scripts.cleanup sidecar-kill   # kill -9 of the sidecar alone
uv run python -m desktop.spike.scripts.cleanup quit           # quit as a closed window does
uv run python -m desktop.spike.scripts.cleanup app-kill --no-death-signal   # the watch alone
uv run python -m desktop.spike.scripts.cleanup app-kill --no-parent-pid     # the death signal alone
```

Each run starts the app with the frozen sidecar, queues an x265 (`slow`) encode of
`hdr10-4k.mkv` through the API and waits until it writes, prints `ps` and `pgrep` before and
after, then starts a new sidecar in the same folders to read the job's state.

Results (2026-10-23; the times are from the kill or the quit until no process of the app,
the sidecar or the encode is left; a zombie counts as gone):

| Case | Gone after | Job | `.part` file |
|------|-----------:|-----|--------------|
| `kill -9` of the app (death signal and watch) | 0.256 s | `interrupted` | removed by the server before it ended |
| `kill -9` of the app, the watch alone | 0.574 s | `interrupted` | removed before it ended |
| `kill -9` of the app, the death signal alone | 0.181 s | `interrupted` | removed before it ended |
| `kill -9` of the app, neither | not in 20 s: the sidecar ran on as an orphan (its new parent: pid 1261, `systemd --user`) and finished the encode | `done` | gone: the job finished |
| `kill -9` of the sidecar alone | 0.0 s (FFmpeg dies with it: the core's death signal, SIGKILL) | `running` in the store; `interrupted` at the next start | left; removed within 2 s of the next start |
| quit (stdin `quit`, as a closed window) | 0.568 s (`POST /api/system/shutdown` → 204; stopped in 0.56 s, not killed) | `interrupted` | removed before it ended |

After `kill -9` of the sidecar the app stays open and its page shows `The server ended
(signal: 9 (SIGKILL)). Log: …/data/sidecar.log` 10 ms later; the shell does not restart it.
With both mechanisms on, the sidecar log shows `The parent process <pid> ended: the server
stops`: the watch and the death signal both fire at once. `ps` before and after the
`kill -9` of the app:

```
--- before
$ ps -o pid,ppid,stat,etime,args -p 50803,50812,51244
    PID    PPID STAT     ELAPSED COMMAND
  50803   50802 S<l        00:04 …/src-tauri/target/release/reframe-spike
  50812   50803 S<l        00:04 …/src-tauri/../dist/reframe-server/reframe-server --mode desktop --port 0 --auth token --parent-pid 50803
  51244   50812 SNsl       00:02 /usr/bin/ffmpeg -hide_banner -nostdin -y -progress pipe:1 -nostats -i /tmp/reframe-spike-3ubnk7e7/media/hdr10-4k.mkv … -c:v:0 libx265 … -preset:v:0 slow … /tmp/reframe-spike-3ubnk7e7/out/encoded.part.mkv
--- after (app-kill)
$ ps -o pid,ppid,stat,etime,args -p 50803,50812,51244
    PID    PPID STAT     ELAPSED COMMAND
  50803   50802 Z<         00:04 [reframe-spike] <defunct>
$ pgrep -af 'reframe-server/reframe-server'
(nothing)
$ pgrep -af 'ffmpeg.*/tmp/reframe-spike-3ubnk7e7'
(nothing)
```

(The app is a zombie until the script that started it reaps it.)

The real window close takes the same path as `quit` on stdin: under XWayland
(`GDK_BACKEND=x11`), `xdotool windowquit` on the window gave `POST /api/system/shutdown` → 204,
the sidecar stopped in 0.63 s and the app exited with 0.

The error page, checked with `REFRAME_SPIKE_SIDECAR`: a missing binary (`The server could not
be started: No such file or directory (os error 2)`, 0.44 s), a sidecar that exits at once
(`The server ended before it was ready (exit status: 1). Log: …`, 0.41 s) and one that never
prints the ready line (`The server was not ready within 20 s. Log: …`, 20.07 s; it is killed).
The app stays open and does not restart the sidecar.

## WebKitGTK checks

Drag-and-drop paths and PrimeVue rendering (task 4b-i, 2026-10-27, the AMD desktop: KDE Plasma
6.8.1 on Wayland, WebKitGTK 2.54.2). The canvas magnifier: [MAGNIFIER.md](MAGNIFIER.md).
Tool behaviour these checks rely on: `testdata/README.md`, "D-0 (4b-i)".

Every window of these checks goes to the output `HDMI-A-1` only, the pointer moves inside it
only, and nothing sends a key. The tools below enforce that; a check that cannot (no
`HDMI-A-1`) opens no window and stops.

### Variables of the app

| Variable | Effect |
|----------|--------|
| `REFRAME_SPIKE_PAGE` | the page `ui/src/pages/<Name>Page.vue` instead of 4a's page (`drop`, `prime`, …) |
| `REFRAME_SPIKE_SNAPSHOT_DIR` | where a relative `snapshot(path)` writes |
| `REFRAME_SPIKE_NO_DRAG_DROP` | Tauri's drag-drop handler off: the page gets WebKitGTK's DOM `drop` |
| `REFRAME_SPIKE_WINDOW_SIZE` | the window's inner size, `WxH` |
| `REFRAME_SPIKE_WINDOW_POSITION` | `X,Y`; only XWayland (`GDK_BACKEND=x11`) honours it |

The app also prints `spike_log` lines (a page's records) and `drop_native` lines (each drag
enter and drop as Tauri's runtime hands it to the window: every path as bytes in hex, whether
it exists, whether it is a folder).

### Hooks (for 4b-ii and later checks)

- **A page**: add `ui/src/pages/<Name>Page.vue`; `REFRAME_SPIKE_PAGE=<name>` shows it (found
  with `import.meta.glob`). A page that needs a plugin exports `install(app)` from a plain
  `<script>` block (see `PrimePage.vue`). Without the variable the app shows 4a's page.
- **The same page in a browser**: `scripts/browser.py` serves `ui/dist` on a loopback port
  with the CSP of `tauri.conf.json` (`serve_ui()`), starts a frozen sidecar in temporary
  folders that allows that origin (`backend(origin)`), and builds the address
  `?page=<name>&base=<url>&token=<token>` (`page_url`). `node(script, arguments, stop=…)`
  runs a Playwright script of `scripts/` and returns its JSON lines; `executables()` gives
  Playwright's own browser binaries. `scripts/prime_browsers.mjs` is an example.
- **`ui/src/spike.js`**: `backend()` → `{baseUrl, token}`; `api(path, init)` → `fetch` with
  the token; `log(record)` → in the app one line `{"event": "spike_log", "ms": <since the
  shell's main()>, …}` on stdout (`drop_check.Lines` reads them), in a browser the record goes
  to `window.spikeLogSink` (expose it with Playwright's `page.exposeFunction`), to
  `window.__spikeLog` and to the console, with `ms` from `performance.now()`;
  `snapshot(path)` → in the app `{ok: true, path, width, height}`, a PNG of the web view's
  visible area made by WebKitGTK (`webkit_web_view_get_snapshot`), or `{ok: false, reason}`
  (always in a browser); `frames(n)` waits n animation frames; `option(name)` reads a setting
  of the app (`snapshotDir`) or a query parameter; `cspViolations` collects every
  `securitypolicyviolation` (each one is also logged).
- **`scripts/windows.py`**: `with windows.Session() as session:` loads a KWin script for the
  block. `session.spawn(argv, spot, **popen)` starts a program behind a gate (it runs once the
  script knows its pid), and the script moves its windows to `spot` = `(x, y, width, height)`
  inside `HDMI-A-1` (`None` for width and height: the window's own; `spot=None`: no move, only
  shown if it is already on `HDMI-A-1`). A new window is transparent until KWin has it on
  `HDMI-A-1`, and kept above the other windows there. `session.window(pid)` waits for it and
  reads it back (`getWindowInfo`); a window anywhere else raises `WrongOutput`, and so does the
  next call after any window of the session moved off. `session.wrapper(binary, spot)` gives
  an executable for a launcher that starts the program itself (Playwright's
  `executablePath`), for a headed browser. The window that had the keyboard keeps it
  (`guard=True`, the default) or gets it back at `session.give_back()`. Close what you start:
  `windows.terminate(process)`, or `quit` on the app's stdin. From the shell:
  `uv run python -m desktop.spike.scripts.windows run -- <command>` (every window of the app's
  class, for 4a's scripts; `--class Reframe-spike` under XWayland),
  `… windows open --spot 40,40,1280,800 -- <program>` (open, read back, close),
  `… windows outputs`.
- **`scripts/pointer.py`**: inside a session with `cursor=True`,
  `pointer.for_session(session.journal, session.screen)` is the real pointer (an absolute
  pointer device made with `/dev/uinput`). `with device:` creates it and removes it on exit;
  call `pointer.check_device(device.device)` first. `move(x, y)` refuses a point outside
  `HDMI-A-1` before it sends anything and stops the run when KWin's read-back is not exactly
  the target; `glide(points)`, `line(start, end, steps)`, `press()`, `release()`,
  `right_click()`. A button still down at the end is released where it went down. Before you
  start a program, move the pointer onto `HDMI-A-1`: KWin opens a window on the output under
  the cursor. `uv run python -m desktop.spike.scripts.pointer demo` moves it round a square.

### Drag-and-drop paths

```sh
uv run python -m desktop.spike.scripts.drop_check --session wayland --json results/drop-wayland.json
uv run python -m desktop.spike.scripts.drop_check --session xwayland --json results/drop-xwayland.json
uv run python -m desktop.spike.scripts.drop_check --session wayland --gtk --json results/drop-gtk-wayland.json
uv run python -m desktop.spike.scripts.drop_check --session xwayland --gtk --json results/drop-gtk-xwayland.json
```

Each run makes the files in a temporary folder (one folder per case, so Dolphin's view holds
the case's items only), starts the app (`REFRAME_SPIKE_PAGE=drop`; `GDK_BACKEND=x11` for
`xwayland`) at 590,120 and, per case, a Dolphin of its own (new XDG folders,
`--new-window --select <items>`) at 20,120, so that the app's left edge is under Dolphin's
right edge. AT-SPI (the system Python's PyGObject, read only) says where the first item is.
The pointer presses there, moves 13 px (past Qt's drag distance), then to the middle of the
app in 30 steps, and releases only after the page saw the drag enter; otherwise it goes back
and releases on the item it pressed (a drop on itself opens nothing). `--handler both` (the
default) runs the cases with Tauri's handler, then without it; `--gtk` drops on a plain GTK 3
window instead (the system Python), which logs the bytes of Dolphin's `text/uri-list`.
`--trace DIR` keeps `WAYLAND_DEBUG` logs of the app and of each Dolphin; `--calibrate` prints
what AT-SPI says of the items. Each drag takes 1.4 s.

Results (2026-10-27; Dolphin 26.08.2; the same on native Wayland and XWayland):

| Case | Sent (file name) | Tauri's event (Rust bytes = page string) | exists | DOM `drop`, Tauri's handler off | Dolphin's `text/uri-list` |
|------|------------------|-------------------------------------------|--------|---------------------------------|---------------------------|
| spaces | `film with spaces.mkv` | the same bytes | yes | `files` empty, `text/uri-list` empty, one `<a>` | `film%20with%20spaces.mkv` |
| non-ASCII | `Ünnepi film – 2.mkv` (`c39c…e28093…`) | the same bytes | yes | as above | `%C3%9Cnnepi%20film%20%E2%80%93%202.mkv` |
| CJK | `日本語.mkv` (`e697a5e69cace8aa9e`) | the same bytes | yes | as above | `%E6%97%A5%E6%9C%AC%E8%AA%9E.mkv` |
| not UTF-8 | `bad\xffname.mkv` (`626164ff6e616d65`) | `bad\u{FFFD}name.mkv` (`626164efbfbd6e616d65`) | **no** | as above (`bad%EF%BF%BDname.mkv`) | `bad%EF%BF%BDname.mkv` |
| three files | `one.mkv`, `két film.mkv`, `日本語 3.mkv` | all three, the same bytes, in Dolphin's view order | yes | one `<a>`, the first item only | three lines |
| folder | `A folder/` | the same bytes | yes (a folder) | as above | `A%20folder` |

- Tauri's drag-drop event is usable: every UTF-8 path arrives byte for byte, as several paths
  and for a folder. The page gets the same strings (`onDragDropEvent`), and Rust gets
  `WindowEvent::DragDrop` before them.
- A name that is not UTF-8 cannot be dropped from Dolphin: Dolphin itself sends U+FFFD
  (`%EF%BF%BD`), so the path that arrives does not exist. (wry would lose such a byte too: it
  decodes with `decode_utf8_lossy`.) D-5 can only report "this file name cannot be read" for
  it, and suggest the file dialog.
- WebKitGTK's own DOM drop gives no files and no URI list: only `text/html` with one link to
  the first item. With Tauri's handler on, the page sees `dragenter` and `dragleave` but no
  `drop`. So the app needs Tauri's drag-drop event (or a native handler); HTML5 drop is not
  enough on Linux.
- Every drag: pointer read back at each of 235 moves per run, always the target, slowest 7 ms;
  no menu, no window outside `HDMI-A-1`; Dolphin's settings of the owner untouched (mtimes of
  `~/.config/dolphinrc` and `~/.local/state/dolphinstaterc` before and after each run);
  the keyboard back to the window that had it after each case.

### PrimeVue 4 rendering

```sh
uv run python -m desktop.spike.scripts.prime_check --headed   # --skip-app: browsers only
```

The page `prime` (`ui/src/pages/PrimePage.vue`) has a DataTable of 200 rows (scrollable,
380 px), a Dialog, a Select (the first 40 languages of the sidecar's `/api/languages`), a
Slider, Tabs and a Toast, with the frontend's preset (`ui/src/prime/theme.js`, a copy of
`frontend/src/styles/theme.ts`, dark mode by the class `reframe-dark`). For each theme
(light, dark) and state (base; the Select open; the Dialog open) it measures its boxes. The
app (1280×800, scale 1) takes a WebKitGTK snapshot of each; Playwright's headless Chromium and
Firefox take a screenshot at the same viewport and a device pixel ratio of 1; headed Chromium
and Firefox (windows on `HDMI-A-1`) the base state. Screenshots: `results/prime/`
(`<engine>-<theme>-<state>.png`, reduced to 256 colours after the measurements);
measurements and differences: `results/prime-metrics.json`.

Results (2026-10-27; Playwright 1.64.1: Chromium 156.0.8078.4, Firefox 157.0):

- **WebKitGTK and Firefox lay the page out the same to about 1 px** (the widest difference: a
  tab 1.06 px wider in Firefox); 1.3 to 7 % of their pixels differ (text antialiasing).
- **Chromium differs by 3 px in the tab bar**: each tab, and so the tab bar (`.p-tablist`),
  is 48 px high in Chromium and 51 px in WebKitGTK and Firefox (`prime-metrics.json`
  `box_differences`; compare `chromium-light-base.png` and `webkitgtk-light-base.png`), so in
  Chromium everything below the tab bar starts 3 px higher. The cause: PrimeVue's
  `Tab` is a `<button>` and takes the browser's button font (WebKitGTK `600 13px Noto Sans`,
  Chromium `600 13.3333px Arial`, Firefox `600 13.3281px sans-serif`). A `font: inherit` on
  buttons in the frontend would remove the difference.
- **Scrollbars**: headed Chromium draws classic 15 px scrollbars (the table's columns are
  15 px narrower: `chromium-headed-light-base.png`); WebKitGTK and Firefox use overlay
  scrollbars (0 px). Headless Chromium hides its scrollbars, so only the headed run shows it.
- **Focus rings**: in Chromium and Firefox the Toast's or the Dialog's close button shows a
  focus ring (`chromium-dark-base.png`, `firefox-dark-dialog.png`); in WebKitGTK it does not,
  because the app's window does not have the keyboard (the check gives it back). Not a
  rendering difference.
- **CSP**: no violation from PrimeVue or the page in any engine. The app runs the policy of
  `tauri.conf.json` with four `sha256-…` sources that Tauri adds to `script-src`;
  `style-src 'self' 'unsafe-inline'` lets PrimeVue's styled mode inject its styles. The
  page's own `eval` test is refused in every engine (`securitypolicyviolation`, `script-src`):
  the policy is in force.

### The placement wrapper with 4a's cold start

```sh
uv run python -m desktop.spike.scripts.windows run -- uv run python -m desktop.spike.scripts.cold_start --target app --runs 2
```

2026-10-27, taken while a movie plays on `DP-1` (165 Hz); the windows on `HDMI-A-1`, 60 Hz:
app (frozen onedir), warm, 2 runs: median 0.808 s, worst 0.815 s (the sidecar's ready line at
0.784 s in the app); with `--in-setup`: median 0.878 s, worst 0.879 s. Each of the three
windows (one warm-up) was read back at 40,40, 900×708 on `HDMI-A-1`. Two runs only: the
numbers show that the wrapper works, they are not the measurement (`cold_start --all`).

### Not run

- Anything on Windows (WebView2's drop paths and rendering: the Windows testing phase).
- Other drag sources than Dolphin (a GTK file manager, a browser's download bar).
- A drop from an XWayland source (Dolphin ran on native Wayland in every case).
