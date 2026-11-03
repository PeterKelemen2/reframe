# 0069 — M5 desktop shell: layout, contracts and what the plan got wrong

- Status: accepted
- Date: 2026-11-03
- Steps: D-1, D-2, D-3, D-4, D-5, D-6

## Context

M5 builds the desktop shell of [07](../plan/07-desktop-app.md) (D-1 to D-6) on Linux
([0053](0053-linux-first-windows-testing-phase.md)), on the D-0 result
([0001](0001-desktop-shell.md)) and the shared queue of
[0042](0042-one-scheduler-process-and-cli-clients.md) (items 3 and 11),
[0056](0056-s7-owner-endpoint-file-and-idle-exit.md) and
[0057](0057-s7-attachments-client-id-and-detach.md). The breakdown is
[../m5-breakdown.md](../m5-breakdown.md). 07 gives D-1 to D-6 no "Done when" line: the boxes of
each step are its criteria.

What the lead found in wave 0 (2026-11-03, the AMD desktop: Tauri 2.12.5, WebKitGTK 2.54.2,
KWin 6.8.2 on Wayland, rustc 1.99.1):

1. **Tauri runs `beforeBuildCommand` in the app folder (`desktop/`), not in `src-tauri/`.** With
   07's `npm --prefix ../../frontend run build:desktop`, `npx tauri build --debug --no-bundle`
   from `desktop/` fails:

   ```
   Running beforeBuildCommand `npm --prefix ../../frontend run build:desktop`
   npm error path /home/peti/Programming/frontend/package.json
   beforeBuildCommand `npm --prefix ../../frontend run build:desktop` failed with exit code 254
   ```

   With `../frontend` it builds the desktop frontend and the app.
2. **Tauri's taskbar progress does nothing on this Linux desktop.** `Window::set_progress_bar`
   goes to tao's `TaskbarIndicator` (tao 0.37.2, `platform_impl/linux/taskbar.rs`), which
   `dlopen`s `libunity.so.4/6/9` and gives up when it is missing. No libunity is installed here
   (`ls /usr/lib/libunity.so*`: no match), although plasmashell owns `com.canonical.Unity` and
   listens for `com.canonical.Unity.LauncherEntry.Update` (`busctl --user list`).
3. **The Wayland app id is the binary name.** Tauri passes the identifier as the GTK app id only
   with `app.enableGTKAppId` (tauri 2.12.5, `app.rs`); without it the app id is
   `reframe-desktop`. The deb and rpm install the desktop entry as `Reframe.desktop` with
   `StartupWMClass=reframe-desktop` (task A), so the launcher matches the window to that entry.
4. **Headless checks of the real app are possible here** (no Xvfb, weston, cage,
   WebKitWebDriver or tauri-driver is installed; `sudo` needs a password):
   - `dbus-run-session -- kwin_wayland --virtual --no-lockscreen --socket NAME --exit-with-session
     SCRIPT`, with `DISPLAY` and `WAYLAND_DISPLAY` unset, runs a private compositor
     (`KWin::VirtualBackend`, one `Virtual-0` output, OpenGL ES on the RX 7600) on a private
     session bus. Nothing appears on the owner's displays.
   - `spectacle -b -n -f -o FILE` inside it captures the virtual output only.
   - A KWin script loaded through `org.kde.kwin.Scripting` on the private bus closes the app's
     window as a click on its close button does (the stub app exited 0 after 100 ms).
   - `WEBKIT_INSPECTOR_HTTP_SERVER=127.0.0.1:PORT` (debug builds) lists the page with a
     WebSocket `/socket/1/1/WebPage`; `Target.sendMessageToTarget` with `Runtime.evaluate` and
     `Runtime.awaitPromise` runs JavaScript in the real webview
     (`{"title": "Reframe", "w": 1280, "h": 800}`).
5. **The CSP holds in the real webview** (checked that way): `fetch` of `https://example.org/`,
   `http://example.org/` and `http://localhost:8768/` and a `ws://example.org/` socket are
   refused with `connect-src` violations; a request to `http://127.0.0.1:8768/` reaches the
   server (its log shows the `GET`); `eval` is refused (`script-src eval`).

## Decision

The lead's choices (binding for every task; the contracts are in the breakdown):

1. **Layout.** `desktop/package.json` holds only `@tauri-apps/cli` (2.12.4, as the spike).
   `desktop/src-tauri/` is one binary crate `reframe-desktop` (`productName` Reframe, identifier
   `org.reframe.desktop`, `mainBinaryName` `reframe-desktop`; `tauri.windows.conf.json` makes it
   `Reframe` on Windows, 0042 item 11). Its modules are owned by the tasks: `backend/` and
   `quit.rs` (D-3), `progress.rs` (D-4), `open_paths.rs` (D-5), `comfort.rs`, `tray.rs`,
   `desktop_settings.rs` (D-6). `main.rs` (the lead) wires them. `desktop/sidecar/` is D-2's.
   `desktop/spike/` stays in M5: its window guard (`scripts/windows.py`) is how the lead runs
   the app headed, and `results/` is 0001's evidence.
2. **Build paths.** `beforeDevCommand` / `beforeBuildCommand` are
   `npm --prefix ../frontend run dev:desktop|build:desktop` (Context item 1). The desktop
   frontend builds into `frontend/dist-desktop` (`frontendDist`), so a desktop build never
   replaces the `frontend/dist` that the server serves in web mode.
3. **Windows are made in Rust** (`app.windows` is empty): the main window by
   `comfort::create_main_window`, after the sidecar has started, the preview window by
   `open_preview_window`.
4. **CSP** (`app.security.csp`): `default-src 'self'`; `connect-src ipc: http://ipc.localhost
   http://127.0.0.1:* ws://127.0.0.1:*`; `img-src 'self' data: blob: http://127.0.0.1:*`;
   `media-src 'self' blob: http://127.0.0.1:*`; `style-src 'self' 'unsafe-inline'` (PrimeVue
   adds style elements); `font-src 'self' data:`; `object-src 'none'`; `base-uri 'self'`;
   `form-action 'none'`; `frame-ancestors 'none'`. `ipc:` and `http://ipc.localhost` are
   Tauri's own channel, not remote. `localhost` is left out on purpose (0056 item 6).
5. **Capabilities.** `main.json` (window `main`) and `preview.json` (window `preview`) grant
   only the plugin permissions the pages call. The app's own commands are not listed: 07 asks
   for least privilege for plugin permissions, and Tauri allows app commands unless the build
   script defines an app manifest.
6. **Taskbar progress on Linux is the app's own `LauncherEntry.Update` signal** on the session
   bus (`zbus`, already in the tree through the plugins), for
   `application://Reframe.desktop` (Context items 2 and 3). Windows keeps
   `Window::set_progress_bar`.
7. **The sidecar is started with `--owner-only`** besides 07's
   `--mode desktop --port 0 --auth token --parent-pid <pid>`. A sidecar that loses the race for
   `queue.lock` to a CLI-started owner then exits 75 (0056 item 1) instead of running on a
   private queue; the manager runs the start order again and uses the winner (0042 item 3.2).
   Exit 75 does not count against the restart policy.
8. **The sidecar uses the platform folders** (`REFRAME_DATA_DIR`, `REFRAME_CONFIG_DIR`,
   `REFRAME_CACHE_DIR` pass through when set), so a `reframe` CLI and the app find the same
   `server.json`. The manager reads `server.json` by the core's rule
   (`reframe.remote.owner.endpoint_path`: `REFRAME_ENDPOINT_FILE`, else the data folder; an
   empty variable is unset, a relative one is made absolute).
9. **The shell's own settings** (the tray) live in `desktop.json` in the app's config folder,
   not in the server's settings: no `reframe.models` change, no schema version.
10. **Keep WebKitGTK's DMA-BUF renderer** (0001 Consequences, D-1). Why it gives about 54–55
    pointer events per second was not looked into: it needs the real pointer on `HDMI-A-1`,
    which only the lead may use, and nothing in M5 depends on it. Open question for the owner.
11. **Checks of the Rust code**: `cargo fmt --check`, `cargo clippy --all-targets -- -D
    warnings` and `cargo test` in `desktop/src-tauri`, on Linux by every task and by a CI job
    `desktop` (Ubuntu and Windows; never run, nothing is pushed). The Windows runner is the only
    place where the `cfg(windows)` code compiles: this machine has no Windows target.

## Task sections

Each task fills its own section (what it built, its checks with real output, deviations).

### Task A — D-2 sidecar build

Built (2026-11-03, PyInstaller 6.22.3, hooks-contrib 2026.9, Python 3.14.8, Tauri CLI 2.12.4):

1. **`uv run python desktop/sidecar/build.py`** runs `desktop/sidecar/sidecar.spec`: two
   `Analysis` (`server_entry.py` → `reframe-server`, `cli_entry.py` → `reframe`), one `EXE`
   each with `exclude_binaries=True`, and one `COLLECT` named `sidecar`, so both executables
   share one `_internal/`. Each `Analysis` gets 0001's options as spec values:
   `collect_data_files` of `babelfish`, `guessit`, `language_data`, `reframe.definitions`,
   `reframe.presets`, `reframe.tools`; the hidden imports `collect_submodules("babelfish")` and
   `pymediainfo`; the wheel's `libmediainfo.so*` (or `MediaInfo.dll`) as a binary; `mypy` and
   `hypothesis` excluded. PyInstaller works in `desktop/sidecar/build/` (git-ignored); the
   script then moves the onedir into `desktop/src-tauri/resources/sidecar/`. Result here:
   98,430,522 bytes in 1017 files, 48 s; `reframe-server` 15.9 MB, `reframe` 15.6 MB (each
   executable carries its own archive of pure-Python modules; the libraries and data files are
   there once). The build still prints the pymediainfo hook's "MediaInfo shared library not
   found" warning: it comes from the hook, before the spec adds the library, and the bundled
   library loads (the MediaInfo test).
2. **"Stamps the version"**: an ELF executable has no version field, so the stamp is the
   version that both frozen programs report, and it is the core's `reframe.__version__`.
   `build.py` refuses to build (exit 1) when `reframe_server.__version__` differs from it,
   because the frozen CLI starts the frozen server as its owner and both must be one release.
   The tests see it: `GET /api/health` of the frozen server and `reframe version` of the frozen
   CLI give `reframe.__version__` of the source tree (a stale build fails them). A Windows file
   version resource and the Tauri version from the same source are Q-5 / D-8, not built.
3. **`reframe --version` does not exist**: the CLI has `reframe version` (typer command), and
   `reframe --version` exits 2 ("No such option"). The test checks `reframe version`. Adding the
   option is a `packages/` change (the lead's), not made.
4. **A fresh worktree still builds the app.** `bundle.resources` is
   `{"resources/sidecar/": "sidecar/"}`. Without the folder, `cargo build` fails in
   tauri-build: `resource path `resources/sidecar` doesn't exist` (checked); a glob that
   matches nothing fails too (`GlobPathNotFound`, tauri-utils 2.10.2 `resources.rs`). So
   `resources/sidecar/README.md` is committed (`.gitignore`: `resources/sidecar/*` with
   `!…/README.md`), and `build.py` keeps it when it replaces the folder's other entries. With
   only that file, `cargo fmt --check`, `cargo build`, `cargo clippy --all-targets -- -D
   warnings`, `cargo test` and `npx tauri build --debug --no-bundle` pass. The README ships in
   the packages as `sidecar/README.md`.
5. **Tauri copies the resources into the target folder** (`$CARGO_TARGET_DIR/debug/sidecar/`,
   98 MB after a build with the sidecar) and does not remove them when the folder later holds
   only the README. In the shared target, a debug app run *from the target folder* finds that
   copy at `<resource_dir>/sidecar/reframe-server`; a copy of the binary elsewhere does not.
6. **Packages** (`npx tauri build --debug --bundles deb,rpm --config '{"bundle":{"active":true}}'`
   here; `bundle.active` stays `false`): Tauri puts the resources in `/usr/lib/Reframe/`, so
   the CLI is `/usr/lib/Reframe/sidecar/reframe` (the `.deb`'s `data.tar.gz` and the `.rpm`'s
   payload, read with `ar` and `bsdtar`: `usr/bin/reframe-desktop`,
   `usr/lib/Reframe/sidecar/{reframe,reframe-server,README.md,_internal/…}`,
   `usr/share/applications/Reframe.desktop`; 119 MiB each). `/usr/bin/reframe` cannot be a
   file of the package: `bundle.linux.deb.files` copies the file a link points to (a link in
   the source tree fails with "does not exist"). So `linux/link-cli.sh` is the `.deb`'s
   `postinst` and the `.rpm`'s `%post` (`postInstallScript`), and `linux/unlink-cli.sh` the
   `prerm` / `%preun` (`preRemoveScript`); the `.rpm` header holds them as `POSTIN` and `PREUN`.
   The link is made only when `/usr/bin/reframe` is missing or already this package's link (a
   `reframe` from pip or another package stays, with a message), and removed only on removal
   (`remove`, rpm `0`), not on an upgrade. `dpkg-deb`, `rpm`, `rpmbuild` and `makensis` are not
   installed here, so the packages were not installed; the scripts run in tests with their two
   paths moved into a temporary folder.
7. **Windows PATH offer** (`bundle.windows.nsis.installerHooks` = `windows/hooks.nsh`):
   `NSIS_HOOK_POSTINSTALL` asks (not in a silent install) whether to add `$INSTDIR\sidecar` to
   the user's `PATH` (HKCU, the installer is per-user); `NSIS_HOOK_POSTUNINSTALL` removes it.
   PowerShell edits the value, because an NSIS string is `NSIS_MAX_STRLEN` long and a longer
   `PATH` read with `ReadRegStr` would be lost when written back; the value stays
   `REG_EXPAND_SZ`, then `WM_SETTINGCHANGE` is broadcast. Not verified: nothing here can build
   or run NSIS (Windows testing phase).
8. **The AppImage** does not put the CLI on `PATH`: nothing in the bundle config does, and an
   AppImage has no install step. Not built here (D-8).
9. **MediaInfo ships in the sidecar.** pymediainfo's wheel carries its own `libmediainfo`
   (15.3 MB of the 98 MB), so no system package is needed, and without it a probe falls back
   to ffprobe's bit rates: a stream that ffprobe gives none for stays unknown and every rule
   that reads bit rates treats it as too high (the MediaInfo test: `vfr.mkv`'s bit rate comes
   from MediaInfo). MediaInfo is BSD-2-Clause: its notice goes with the licence files of D-8
   (09 §Licensing). The `MediaInfo.dll` pattern for Windows is not verified.
10. **The frozen CLI through a link finds its server.** PyInstaller's bootloader resolves the
    link: `sys.executable` of `/tmp/…/bin/reframe` → `…/sidecar/reframe` is the real file, so
    `owner_command` starts `…/sidecar/reframe-server` (checked by hand and in a test). So the
    `/usr/bin/reframe` link works as an owner starter.
11. **Tests** (`packages/reframe-server/tests/test_frozen_sidecar.py`, kept where it was: it is
    on the pytest paths; it now reads `desktop/src-tauri/resources/sidecar/`, and the
    `REFRAME_FROZEN_SERVER` override of the spike is gone): the frozen server's ready line in
    `--mode desktop --port 0` and its bundled data (health version, definitions, presets,
    languages, tools manifest, guessit), MediaInfo, the parent watch with its encode; the frozen
    CLI's version, its `encode --detach` and `queue list` against a running frozen server found
    through `server.json`, and a run through a link that starts the frozen server next to the
    real file. These skip without a sidecar build (CI). The package scripts' tests run on any
    Linux. Mutations, each rebuilt and run: no definitions data, no guessit data, no
    `pymediainfo` import, no parent watch, `reframe` frozen from the server's entry, the owner
    looked up next to `argv[0]`; and five in the package scripts. Each failed the test it
    belongs to.

Not built: a Windows version resource; `--without` switches of the spike's build script; an
AppImage or NSIS build (D-8); FFmpeg in `resources/tools/` (D-7: `bundled_tool_roots` already
looks there, one folder above the sidecar).

Found for others: the `.deb` / `.rpm` desktop entry is `Reframe.desktop` (from `productName`),
not `reframe-desktop.desktop` (Context item 3, `progress::DESKTOP_ENTRY`); its
`StartupWMClass=reframe-desktop` matches the window, but a `LauncherEntry` for
`application://reframe-desktop.desktop` will not match the installed entry. Both packages are
named `reframe` (the `.deb`'s `Package: reframe`, the `.rpm`'s `NAME`). Both are D-8's to
settle.

### Task B — D-3 sidecar manager and quit flow

**Built** (`desktop/src-tauri/src/backend/`, `quit.rs`; 2026-11-03):

- `backend/mod.rs`: one supervisor task at a time runs the start order and watches what it
  found; every state change goes to the watch channel that `info()` waits on and, once
  `attach` ran, to every window as `backend-state`. `stop()` sets a flag that every wait of the
  supervisor races against, then waits until the task has ended; after it no start runs
  (`retry` does nothing).
- `backend/owner.rs`: `server.json` by the core's rule (`REFRAME_DATA_DIR` blank-is-unset, `~`
  expanded, made absolute, else platformdirs' folder: `XDG_DATA_HOME` or `~/.local/share` +
  `reframe`, on Windows the local app data folder + `Reframe`; `REFRAME_ENDPOINT_FILE` the
  same way), `GET /api/health` on `127.0.0.1:<port>` (a 30-line HTTP/1.1 client on
  `TcpStream`, `Connection: close`, as the spike's shutdown request), the `instance`, the
  `api_version` and the header-safe token checks of `reframe.remote.owner._endpoint`.
- `backend/sidecar.rs`: every sidecar is forked by one thread that lives as long as the app
  (`reframe-sidecar-spawner`, it enters the tokio runtime so the pipes register); the spike's
  `PR_SET_PDEATHSIG = SIGTERM` with the parent re-check in `pre_exec`; `kill_on_drop`, so a
  start that the quit abandons kills the child; the token from `getrandom` in `REFRAME_TOKEN`;
  stdin null, stdout piped (kept open after the ready line), stderr straight into the log
  file.
- `backend/job.rs`: the Job Object behind a three-call trait (`create`, `kill_on_close`,
  `assign`), the real calls under `cfg(windows)` (not compiled here), the order and the
  handle's lifetime tested with a fake.
- `quit.rs`: a close of `main` is prevented and goes to `request_quit`; the page is asked
  (`quit-requested` to `main`, after the window is shown, unminimised and focused) only when
  it called `quit_ready` and the backend is `ready`, else the app stops the backend and exits
  0. `RunEvent::Exit` stops the backend too (a second stop returns at once).
- `main.rs` (the one allowed change): `generate_context!()` is made first and
  `Backend::start(&context)` reads the resource folder (`tauri::utils::platform::resource_dir`)
  and, in a `tauri dev` build (`cfg(dev)`), the `devUrl`'s origin for `REFRAME_CORS_ORIGINS`.
- `Cargo.toml`: `getrandom` 0.4.3 (the spike's `libc::getrandom` is Linux-only; the token is
  made on Windows too) and, for Windows only, `dirs` 7.0.0 (the known folders that platformdirs
  uses). Both were already in `Cargo.lock`.

**The start order and the timings chosen:**

| Step | What happens |
|------|--------------|
| `server.json` names a server that answers with its `instance` and API 1, token header-safe | used, `owned: false`; no sidecar, no restart policy. Watched with `GET /api/health` every 1 s (2 s timeout); a failed or other-instance answer runs the order again |
| file missing, not valid, stale (no answer, other instance) | the sidecar with `--owner-only` |
| another `api_version`, or a token that cannot go in a header (0042 item 3.3) | the sidecar **without** `--owner-only` (the server runs on a private queue and reports `queue.store_busy`); the reason is the first line of that run in `sidecar.log` (`reframe-desktop: Reframe X (pid N) owns the queue, and it speaks API version 2, not 1 as this app does: this server runs on a private queue`). `BackendInfo` has no field for it |
| the sidecar exits 75 | look for the winner's `server.json` every 50 ms for up to 5 s (`HELD_WAIT`), then run the order again; a second 75 in a row means a lock held without a usable endpoint: 3.3 |
| ready line within 20 s | then one `GET /api/health` for the `instance` (it fails: `failed`), `ready`, `owned: true` |
| no ready line in 20 s, an exit before it, a spawn error | `failed` with the log path; no automatic restart (07 lifecycle 2: the error screen and **Retry**) |
| a ready sidecar ends (any status) | `reframe-desktop: the server ended (<status>)` in the log, `starting`, the order again with a new port and token; the fourth end within 60 s is `failed` (`The server ended 4 times within 60 s (…)`); `backend_retry` starts over with an empty count |
| quit | `POST /api/system/shutdown` with the token, and the kill when the process has not ended 5 s after the request was sent (the request's own time counts) |

The Rust side never reads `queue.lock`: the `--owner-only` sidecar's exit 75 is the lock
test, and the second try covers an owner in its exit window (port closed, lock not yet free),
which the CLI handles by reading the lock.

**Log** (`<data>/logs/sidecar.log`): appended to by every sidecar start, so the error screen's
log still holds the run that failed; at a start a log over 1 MiB is first renamed to
`sidecar.log.1` (one old file). The app writes its own lines with a `reframe-desktop:` prefix
(the 3.3 reason, a sidecar's end, a failed Job Object). Within one run the log is not
rotated: the sidecar writes it directly (no pipe through the app, so a `kill -9` of the app
cannot break the server's stderr).

**Deviations from the plan and the breakdown:**

1. 07 §Sidecar lifecycle 1 said the order runs "in the Tauri `setup` hook"; it runs before the
   builder, on the main thread, as the breakdown's contract and 0001 Decision 1 say (the plan's
   text is changed below).
2. The sidecar does not inherit the server's own options from the app's environment
   (`REFRAME_HOST`, `REFRAME_IDLE_EXIT`, `REFRAME_MEDIA_ROOTS`, … the list of
   `reframe.remote.owner.SERVER_OPTIONS`), as an owner that the CLI starts: a stray
   `REFRAME_IDLE_EXIT` would end the app's sidecar, a `REFRAME_HOST` would bind it elsewhere.
   The folders and `REFRAME_ENDPOINT_FILE` pass through (0069 item 8).
3. A start failure is not restarted; only a sidecar that ended after its ready line counts
   against the 3-in-60-s policy.
4. A Job Object that cannot be made leaves the sidecar running (its parent watch still ends
   it after a crash) and writes the error to the log.
5. `quit_ready` is one flag for the process: a reloaded page keeps it (it calls `quit_ready`
   again anyway).
6. `Backend::request` carries `#[cfg_attr(not(test), expect(dead_code, …))]` until the tray
   calls it: task E removes the attribute (the `expect` warns once it is used).

**Checked in the real app** (the debug build, `vk-run.sh` socket `reframe-b`, the inspector
on 8729, `REFRAME_DESKTOP_SIDECAR` = the worktree's `.venv/bin/reframe-server`, the pinned
FFmpeg first on `PATH`, `hardware_tests` off; the page is still task C's stub, so it shows
*Connecting to the Reframe server…* in every screenshot):

- `invoke('backend_info')` →
  `{"baseUrl": "http://127.0.0.1:38249", "token": "16c0…540d", "instance": "6d2240ca5e3e01b0", "owned": true}`
  2.8 s after the start; the sidecar is the app's direct child:
  `…/.venv/bin/python …/.venv/bin/reframe-server --mode desktop --port 0 --auth token --owner-only --parent-pid 57292`.
- `kill -9` of the app during an x265 encode of `hdr10-4k.mkv` (`kill9.part.mkv` in the
  output folder): the sidecar and its FFmpeg were gone within 0.22 s and 0.28 s (two runs; the
  script polls every 50 ms), nothing left; the output folder empty; a server started on the same data folder
  shows the job `interrupted`, "Reframe was closed while the job was running."; the sidecar's
  log: `The parent process 59634 ended: the server stops`.
- A window close (`vk-close.sh`) during an encode, with the stub page (no `quit_ready`): the
  log has `"POST /api/system/shutdown HTTP/1.1" 204 No Content`, the app exited 0 after 0.42 s and 0.37 s,
  the sidecar and FFmpeg gone, `.part` removed, the job `interrupted`.
- With `quit_ready` called and a `quit-requested` listener in the page: a close left the app
  and the sidecar running and the page received the event once; `hide_main_window` hid the
  window (the virtual output went black); `quit_app` stopped the sidecar (204) and the app
  exited 0. The `invoke('quit_app')` promise never settles: the app exits first.
- A CLI-started owner (`reframe-server --mode desktop --owner-only --idle-exit 30 --port 0`,
  same data folder, one waiting job): `backend_info` gave its port, its token and
  `owned: false`; the app had no child but WebKit's two. After `kill -9` of the owner the page
  got `[{"state": "starting"}, {"state": "ready", "info": {…, "owned": true}}]` within 1 s, the
  app had its own sidecar, and its queue held the waiting job.
- `reframe encode multitrack.mkv -o …` in the session: the job showed in the app's sidecar's
  `GET /api/queue` while it ran (`running`, then `done`; the CLI printed
  `Summary: 1 done, 0 failed, 0 cancelled, 0 not queued.`).
- `kill -9` of the sidecar: the page got `starting` then `ready` with a new port (38341 →
  34407) and token; the old token gets 401 from the new sidecar; the log has
  `reframe-desktop: the server ended (signal: 9 (SIGKILL))`. During an encode, the restarted
  sidecar shows the job `interrupted` ("Reframe stopped while the job was running.") and the
  `.part` file removed.
- `REFRAME_DESKTOP_SIDECAR=/bin/false`: `backend_info` rejects with
  `{"message": "The server ended before it was ready (exit status: 1)", "log": "<data>/logs/sidecar.log"}`;
  `backend_retry` runs the order again with the same result.

**Tests** (25, `cargo test`): `backend/tests.rs` drives the supervisor with shell scripts as
fake sidecars and a tokio listener as the fake server; they and the sidecar tests are
`cfg(unix)` (the Windows runner builds without them). A mutation run broke each test function
at least once (36 mutations, all failing the tests); two survivors showed redundant code (a
kill that `kill_on_drop` already does, a second stop check), which was removed.

**Not verified**: everything under `cfg(windows)` (the Job Object, `CREATE_NO_WINDOW`, the
Windows data folder) is not compiled on this machine; the frozen sidecar path
(`<resources>/sidecar/reframe-server`) waits for task A's build; the running-jobs dialog is
task C's.

### Task C — D-4 desktop platform adapter

Phase 1 (2026-11-03): built and checked against B's stub backend (`REFRAME_DESKTOP_STUB_BACKEND`)
and a web-mode `scripts/dev-server.py`; phase 2 (the quit flow, *Reconnecting…*, the restart
limit and the when-done actions against B's real sidecar) follows after B merges.

What was built:

- `platform/desktop/index.ts`: `open` / `save` of `plugin-dialog` (the callers' `filters`
  become one filter `*.srt *.ass` with the extensions, lower case, without the dot; no filters:
  every file), `getCurrentWebview().onDragDropEvent` (only `drop` is used), `revealItemInDir`
  and `openUrl` of `plugin-opener`, `requestPermission` + `sendNotification` of
  `plugin-notification`, `invoke('set_taskbar_progress')`, and the `DesktopShell` members.
  `backendInfo()` rejects with a `DesktopBackendError`; an IPC failure (a string) becomes
  `{message, log: null}`. `onQuitRequested` and `quitReady` act only in the window `main`: the
  preview window loads the same page, and its `quit_ready` must not stand for the main page's.
- **A dropped name that cannot be read** (U+FFFD, 0001 Consequences D-5): the readable paths
  open as before; the others are named in the native question of `plugin-dialog`
  (`message` with two buttons, so `dialog:allow-message`) with **Open files…** · **Cancel**,
  and **Open files…** opens the file dialog. A native question, not an in-app dialog: the
  platform module has no component to show, and the drop's callback contract stays as it is.
- `api/boot.ts`: with a desktop shell it subscribes to `backend-state` before it asks
  `backend_info`; a rejection shows the error screen and the boot waits for a `ready` state (a
  Retry). A later `ready` with another `baseUrl` or token calls `configureClient` and restarts
  the event connection at once (the connection's own retry would wait for its backoff). The
  state is `desktopBackend` (a `shallowRef` exported by `boot.ts`), read by `App.vue` and the
  quit flow.
- `App.vue`: `BackendErrorScreen` (message, log path, **Try again** = `retryBackend()`; the
  next `backend-state` replaces it), `ReconnectOverlay` over the app with the app `inert`
  while the state is `starting` after the boot, `QuitDialog` + `useQuitFlow`. `quit_ready` is
  sent once the queue is read: before that a close would count no jobs. The count is
  `running` + `paused` of the shared queue (every front end's). **Stop jobs and quit**: own
  sidecar `quit()`; another owner `POST /api/queue/stop`, a cancel per running or paused job,
  then `quit()` (a failed cancel keeps the app open, the request's toast says why). When-done
  `quit`: `queue.$onAction` sees `onPowerCountdown` with `phase: executing` and
  `action: quit` (the store keeps no executing event in `power`) and calls `quit()`.
- `progress.rs`: Linux sends `Update` on `com.canonical.Unity.LauncherEntry` (path
  `/org/reframe/desktop/LauncherEntry`, body `sa{sv}`: `application://Reframe.desktop`,
  `progress` double 0…1, `progress-visible`) on one session-bus connection kept for the app's
  lifetime (none when there is no bus: nothing is sent). Windows: `set_progress_bar` of the
  main window (`Normal` with the percentage, `None` to clear); the conversion is tested on
  Linux, the call is not compiled here. **The entry is `Reframe.desktop`**, not Context item
  3's `reframe-desktop.desktop`: Tauri's deb and rpm install `Reframe.desktop` (named after
  `productName`) with `StartupWMClass=reframe-desktop`, and KDE matches the window (app id
  `reframe-desktop`) to that entry through it (task A). Decision item 6 and the Consequences
  read `application://Reframe.desktop` from now on.
- `capabilities/main.json`: the scaffold's permissions plus `dialog:allow-message` and
  `opener:allow-open-url` scoped to `http://127.0.0.1:*/api/preview/clips/*` (the clip link).
  `notification:allow-is-permission-granted` stays: the plugin's own page script calls it at
  start.
- The UI split: the desktop build mounts no `FileBrowserDialog` (the server file browser).
  The rest was already split: reveal in folder (`QueueTable`, `platform.kind`), the when-done
  `quit` and the tool paths (`system.info.mode === 'desktop'`, the sidecar's mode), the login
  screen and **Sign out** (password mode only; the app's token comes from Rust).

Checked in the real app (virtual session, the stub backend, WebKitGTK 2.54.2):

- The workspace boots against the server at the stub's address with its token; frames load.
- **Open files…** opens the GTK file chooser (closed by a KWin script: the page gets `[]`).
- A job queued and started through the UI: `dbus-monitor --session` shows the app's
  `LauncherEntry.Update` for `application://Reframe.desktop`: `progress-visible` false at start,
  then true with 0, 0.567, 1, then false. Spectacle on the same bus sends the same signal
  (with an `int32` progress), so the form is what KDE apps send.
- With `document.hidden` true, the job's end is a `org.freedesktop.Notifications.Notify` call
  (`"Job done"`, `"multitrack (2).mkv"`); the bus has no server, the call fails, and the app goes
  on (the toast shows, the next requests answer).
- Reveal in folder sends `org.freedesktop.FileManager1.ShowItems` with
  `file:///…/multitrack%20(1).mkv`.
- Open externally of an encoded preview clip reaches the system opener with the signed clip
  URL (a stand-in `xdg-open` first on the app's `PATH` recorded it); `open_url` of
  `https://example.org/`, `http://127.0.0.1:8731/api/queue` and `file:///etc/passwd` is refused
  (`Not allowed to open url …`).
- The unreadable-name question (`plugin:dialog|message` with the code's arguments) shows as a
  GTK message dialog; closed, it answers `Cancel`.
- Without `REFRAME_DESKTOP_STUB_BACKEND` the error screen shows the stub's message; **Try
  again** calls `backend_retry` (the stub changes nothing). Light and dark.

Not checked in phase 1: a real drop from a file manager (needs the pointer: the lead's headed
check), the quit dialog on a real close, *Reconnecting…*, the when-done actions (the stub
quits at once on a close, sends no state changes, and the dev server is in web mode).

Phase 2 (2026-11-03, B's sidecar manager merged; the sidecar from source through
`REFRAME_DESKTOP_SIDECAR`, the pinned FFmpeg; virtual session, light and dark):

- `owned: true`, the sidecar a child of the app; the queue's **When done** offers **Quit
  Reframe** (the server is in desktop mode).
- A close while an x265 job runs shows the dialog (*1 job is running or paused. Quitting
  stops it.*, **Cancel** · **Stop jobs and quit**; no tray button: E's setting is still the
  stub's `tray: false`). **Cancel** and Escape keep the app and the job running. **Stop jobs
  and quit** exits 0; the sidecar ends (`Finished server process`), no FFmpeg is left, the
  `.part` file is gone, and the next start shows the job `interrupted`.
- `kill -9` of the sidecar during the encode: *Reconnecting…* over the app (the status bar
  says *Connection lost, reconnecting…* under it), then the app again on the new port and
  token, a new `instance`, the job `interrupted` (*Reframe stopped while the job was running.*).
- Four `kill -9` within 60 s: the error screen with *The server ended 4 times within 60 s
  (signal: 9 (SIGKILL))* and the log path; **Try again**: error, *Reconnecting…*, the app,
  the queue restored.
- `REFRAME_DESKTOP_SIDECAR=/bin/false`: the error screen with *The server ended before it was
  ready (exit status: 1)* and the log path; **Try again** gives `starting` then `failed`
  (heard on `backend-state`) and the same screen. A close there quits at once (exit 0).
- When-done **Quit Reframe** after a job: the countdown (60 s) in the banner, then the app
  exits 0 without a dialog and the sidecar ends.
- An owner started as the CLI does (`reframe-server --mode desktop --owner-only`, the same
  folders): `owned: false`, no sidecar. A close during its job, **Stop jobs and quit**: the
  owner logs `POST /api/queue/stop` then `POST /api/queue/<id>/cancel` (204 each), the app
  exits 0, the owner runs on, and its queue shows the job `cancelled`.

**`quit-requested` and other windows** (tauri 2.12.5 `event/listener.rs`: `emit_to` calls
`emit_js_filter` on every webview, and a listener whose target is `Any` matches every
filter): a plain `listen()` in the preview window would get the main window's
`quit-requested` too. In the real app, on a close, the main page's listeners with target
`Any` and `WebviewWindow main` fired and one with `WebviewWindow preview` did not. So
`onQuitRequested` and `quitReady` stay limited to the window `main` (the preview window
cannot be opened before E, so that page was not tried).

Fixed in phase 2: the error screen's title said *did not start* also after the restart
limit; it is *The Reframe server is not running*. *Reconnecting…* said the queue comes back
*as it was*; a running job ends `interrupted`, and the text says so.

Not checked: **Keep running in tray** in the real app (E's tray setting; the branch is
unit-tested, and B checked `hide_main_window`), a real drop from a file manager (the lead's
headed check).

Found for others (phase 1, since fixed by the lead): PrimeVue's `Tab` buttons did not
inherit the page font in the real webview (`600 14px Adwaita Sans` against the body's
`system-ui …` stack), 0001's F-x line (`font: inherit` on buttons).

### Task D — D-5 single instance, open-with, CLI arguments

(placeholder)

### Task E — D-6 windows and comfort

**Built** (2026-11-03; `comfort.rs`, `tray.rs`, `desktop_settings.rs`, `capabilities/preview.json`,
`platform/desktop/comfort.ts`, `components/shell/PreviewPanel.vue` and `previewWindow.ts`,
`views/PreviewWindowView.vue`, `views/SettingsView.vue`, `components/settings/DesktopSection.vue`,
`i18n/messages/en/window.json`):

1. **Window state.** `tauri-plugin-window-state` 2.5.0 with `SIZE | POSITION | MAXIMIZED`, for
   both windows. Not `VISIBLE` (the default has it): an app quit while hidden in the tray would
   start hidden. The plugin restores a window inside `build()` (its `on_window_ready` hook runs
   there) and writes `.window-state.json` in the app's config folder on `RunEvent::Exit`; so each
   window is built with `visible(false)` and shown after `build()`, and it does not jump. The
   main window's minimum is 1100×700 (`min_inner_size`).
2. **The detached preview window.** `open_preview_window(sourceId)` makes the window `preview` on
   `/preview/<id>` (Tauri serves `index.html` for a path it has no file for, so the router's bare
   route shows), 960×720, minimum 480×360, or focuses the open one; an id that is not
   alphanumeric is refused (it would change the route). **The sync is a `BroadcastChannel`**,
   not Tauri events: both windows are pages of one origin, so the channel needs no command, no
   event and no permission (checked in the real webview: a message from one window reaches the
   other; `pagehide` fires when KWin closes the window, and a Web Lock held by the closed page is
   released). `components/shell/previewWindow.ts` holds both sides:
   - the main window (the preview panel's scope, desktop build only) sends, on a `hello` and on
     each change, the editor's file and job (and the sources store's entry of the file), the
     tab, the view, the zoom and the frame (`index`, `sought`); it asks once at start, so a
     preview window that outlives a reload of the main page is found again;
   - the preview window's stores take them (the job as a `job` target; a new file waits a tick,
     because the preview store resets the frame of a new file), and it sends back what its user
     chooses: the view, the zoom, the frame (from `select`, `step`, `seek`, so a reset never
     travels) and the editor's `set`, `patch` and `endCoalescing` (the crop handles), which the
     main window applies: its undo history gets one step per drag, and the next state brings the
     job back. A value that comes back equal changes nothing, which ends each round trip.
   - **While it is open** the main window's panel shows *The preview is in its own window.* and
     **Show the preview window** (focus), and asks for no output frames (`panelOpen` false; the
     preview window renders them). **When the preview window closes** (its close button, or
     the page going away: `bye`), the panel shows the frames again at the frame the preview
     window last chose. **When the main window closes**, the app quits (B's flow) and the preview
     window goes with it; with **Keep running in tray** only the main window is hidden.
   - The preview window shows `FrameViewer` and `PreviewClip` as the panel does (the clip's
     **Open externally** needs `opener:allow-open-url`, added to `preview.json` with
     `main.json`'s scope). It mounts no Tauri listener (C's note: `emit_to("main")` reaches
     every page's `listen`).
3. **Theme follow: no code was needed.** WebKitGTK 2.54 takes `prefers-color-scheme` from
   GTK: dark when `gtk-application-prefer-dark-theme` is true or the GTK theme name ends in
   `-dark`, and it follows a change of either while it runs. Checked in the virtual session:
   `gsettings set … gtk-theme Adwaita-dark` turned the page dark at once; a `settings.ini` with
   `gtk-application-prefer-dark-theme=true` and `gtk-theme-name=Breeze` (what KDE writes for a
   dark scheme) gave dark at start; `gsettings … color-scheme prefer-dark` alone changed
   nothing. Tauri's tao (0.37.2, its `dbus` feature is on) reads the settings portal's
   `org.freedesktop.appearance color-scheme` when it makes a window and sets
   `gtk-application-prefer-dark-theme` from it, and on each `SettingChanged` sets it again.
   With a stand-in portal on the private bus (`Read`/`ReadOne`, `SettingChanged`): 2 at start →
   light; 1 → both windows dark within 1 s; 2 → light again; a start with 1 → dark. The owner's
   desktop (KDE Plasma 6.8 on Wayland) has the portal and reports 1 (`ReadOne`, read only). The
   app's `system` choice then follows through `matchMedia` as before; `useTheme.ts` is unchanged.
   The private session's own portal has no Settings interface, and KDE's
   `xdg-desktop-portal-kde` started there kept reporting 1 whatever the session's kdeglobals
   said, so the stand-in was used.
4. **The tray** (`tray.rs`): created at start when `desktop.json` says `tray: true`. Menu: the
   progress line (disabled; *Queue: 43 %* or *No job is running*, from `show_progress`, kept while
   the tray is off), **Pause all** (`Backend::request("POST", "/api/queue/pause")`; B's
   `expect(dead_code)` removed), **Show Reframe**, **Quit** (`quit::request_quit`). The icon is the
   app's window icon; the tooltip carries the progress too (Windows; tray-icon ignores tooltips on
   Linux). The menu strings are English in Rust, not vue-i18n (the tray has no page).
   - **A tray switched off is hidden, not removed** (deviation from the brief's "adds or removes
     the tray"): on Linux a removed tray's `StatusNotifierItem` stays exported (tray-icon only
     sets it `Passive` on drop, and libayatana's object stays on the bus), and a tray made again
     under the same id cannot register (`Unable to register object on path
     '/org/ayatana/NotificationItem/tray_icon_tray_app_reframe': An object is already exported`)
     and showed an empty menu. `set_visible(false)` makes the item `Passive` (the SNI
     specification lets a host hide it; Windows removes the icon), `set_visible(true)` brings it
     back with its menu.
   - **Linux without the indicator library**: tray-icon `dlopen`s
     `libayatana-appindicator3.so.1` or `libappindicator3.so.1` and panics without them (on the
     main thread, so the app would abort). `check_available` tries the same names first;
     `set_desktop_settings` then refuses with *The tray needs the library
     libayatana-appindicator3 (or libappindicator3), which is not installed* and saves nothing;
     a saved `tray: true` without the library starts without a tray. 0054's note holds:
     `libayatana-appindicator` 0.6.1 is what this machine has (it warns that it is deprecated).
5. **`desktop.json`** (`desktop_settings.rs`) in `app_config_dir()`
   (`$XDG_CONFIG_HOME/org.reframe.desktop/`): read as a JSON object; a missing file, one that is
   not an object or a `tray` that is not a boolean gives the defaults. A save reads the object
   again, replaces the known fields, keeps the others (their values unchanged; the keys come out
   sorted) and replaces the file through `desktop.json.part` and a rename. A broken file is
   replaced on save. `set_desktop_settings` saves, then shows or hides the tray, and returns the
   file's settings.
6. **Settings → Desktop app** (`DesktopSection.vue`, the last section, only when
   `platform.desktop` is set): the **Tray icon** switch with its help text; a refusal shows the
   shell's reason under the switch and the switch goes back.

**Checked in the real app** (the debug build, `vk-run.sh` socket `reframe-e`, the inspector on
8779, `REFRAME_DESKTOP_SIDECAR` = the worktree's `reframe-server`, the pinned FFmpeg first on
`PATH`; KWin's virtual output 1440×900, Wayland, no Xwayland):

- Window state: resized by a KWin script to 1200×760, closed (B's quit), started again: 1200×760;
  maximised by a KWin script, quit, started again: 1440×900 maximised, with 1200×760 kept as the
  size to return to. `.window-state.json` holds `"x": 0, "y": 0` for both windows: **on Wayland a
  GTK client can neither read nor set its place**, so KWin places the window again (the preview
  window came back at its 560×600 size but centred). The place is restored only on X11 and
  Windows; neither ran here (no Xwayland in the session).
- Minimum size: a KWin script set the main window's frame to 800×500; `innerWidth`/`innerHeight`
  stayed 1100×700.
- Preview window: the detach button opened it (960×720, label `preview`,
  `tauri://localhost/preview/<id>`), at the main window's frame; the main panel showed the note
  and `panelOpen` false. Dimensions in the main window → the preview window's crop overlay with
  four handles; a crop typed in the main window (30/30/8/8) → the same rectangle in the preview
  window; three ArrowDown presses on the preview window's top handle → the main window's top
  40 → 46 and one undo step (undo → 40 in both). Filters → split with the output frame in the
  preview window only. A thumbnail and *Side by side* picked in the preview window → the main
  window's frame 4 and view. Another file picked in the main window → the preview window's file
  and strip. Closing the preview window (KWin) → the main panel's frames back; the detach button
  again → the window at frame 5 of 10; **Show the preview window** focused it without a second
  window.
- Theme: light and dark screenshots of both windows (point 3), the restored maximised window in
  dark, Settings in light and dark.
- Tray: a stand-in `org.kde.StatusNotifierWatcher` (with a host) on the private bus and
  `dbus-monitor`. Switched on in Settings: `desktop.json` `{"tray": true}`, the app's
  `RegisterStatusNotifierItem` call, the item `Active` with the menu *No job is running* ·
  separator · *Pause all* · *Show Reframe* · *Quit* (read with `com.canonical.dbusmenu.GetLayout`).
  During an encode the line read *Queue: 76 %*, then *No job is running*. **Pause all** clicked
  with `com.canonical.dbusmenu.Event` during an encode: the sidecar's log has
  `"POST /api/queue/pause HTTP/1.1" 204` and the job was `paused`. A window close then showed C's
  dialog with **Keep running in tray**; it hid the window (`document.hidden` true, the output
  black); the tray's **Show Reframe** showed it again. In a later run the tray's **Quit** during an
  encode showed the same dialog; **Stop jobs and quit** sent the shutdown request (204), and
  the app, the sidecar and FFmpeg were gone 3 s later. Switched off: the item `Passive` (a `NewStatus` signal); on again:
  `Active` with its menu (after the fix of point 4). A field added to `desktop.json` by hand
  survived two saves. A restart with `tray: true` registered the item at start; a watcher that
  started after the tray still got the registration.
- Not seen: a real tray host drawing the icon (no Plasma in the private session).

**Tests**: `cargo test` (`desktop_settings`: a missing file, broken files, unknown fields kept,
the config folder made and no `.part` left; `tray`: the progress line, a missing library found
before the tray is made; `comfort`: an id that would leave the preview route). Vitest:
`platform/desktop/comfort.test.ts` (the three commands and their arguments with
`@tauri-apps/api/mocks`, a refusal passed on), `components/shell/previewWindow.test.ts` (two
Pinias as the two pages over a real `BroadcastChannel`: the state when it opens, a tab and crop
change, another file at its first frame, a drag's edits as one undo step in the main window, the
user's frame and view sent back, the close, a main page that loads after the preview window,
nothing sent while no preview window is open), `PreviewPanel.test.ts` (the button opens the shown
file, the detached state and its focus button, a refusal as a toast, no button in the web build),
`views/PreviewWindowView.test.ts` (the main window's frame, output frames asked for, the crop
overlay on Dimensions and the split on Filters, the arrow keys), `DesktopSection.test.ts` and
`SettingsView.test.ts` (the saved value, a save, a refusal that leaves the switch where it was,
the section only in the desktop build). The refusal test found a bug: the switch stayed on after
a refused save, because its model value had not changed; the section now shows its own value.
Mutation run: 38 mutations (each test function broken at least once), all killed.

**Deviations**: the sync is a `BroadcastChannel` (no Tauri event, no relay command, no
`main.json` change); a tray switched off is hidden (point 4); the place of a window is not
restored on Wayland (above); the tray's strings are not translated.

**Found for others** (not changed, not my files):

- `useShortcuts` acts in the preview window: **Ctrl+O there navigates the preview window to
  the workspace** (checked: `location.pathname` `/`, the app shell inside the preview window; the
  file dialog itself is refused there, `preview.json` has no `dialog:allow-open`). A
  `route.meta.bare` check in its key handler would stop it.
- The preview window's `App.vue` also calls `set_taskbar_progress` (the same values as the main
  window's) and would call `platform.notify` when hidden (refused: `preview.json` has no
  notification permission, so nothing shows twice).
- The preview window runs its own crop detection of the shown file (the crop store starts one per
  file and page; the server does not cache it). The main window's job already carries the
  detected rectangle, so the result is not used.
- **Keep running in tray** hides only the main window; an open preview window stays.

## Consequences

- The plan's text of D-1 and of the taskbar row was wrong for this platform; both are fixed
  below.
- The desktop frontend has its own output folder; the Docker image and S-4 still use
  `frontend/dist`.
- On Linux, taskbar progress shows only where a launcher listens for `LauncherEntry`
  (KDE Plasma, Ubuntu's dock) and the desktop entry `Reframe.desktop` is installed.
- Not verified on Windows (status "Not verified"): everything under `cfg(windows)`.

## Plan changes

- [07 §D-1](../plan/07-desktop-app.md#d-1-project-scaffold): `beforeBuildCommand` is
  `npm --prefix ../frontend run build:desktop` (it runs in `desktop/`), `frontendDist` is
  `frontend/dist-desktop`.
- [07 §Native integrations](../plan/07-desktop-app.md#native-integrations): the taskbar row.
- [07 §Sidecar lifecycle](../plan/07-desktop-app.md#sidecar-lifecycle): `--owner-only` and exit 75.
  Task B: item 1 runs on the main thread before the builder, not in the `setup` hook (Task B,
  deviation 1).
- [07 §D-3](../plan/07-desktop-app.md#d-3-sidecar-manager-rust): four boxes ticked by task B; the
  Windows box is written and mock-tested on Linux, its "Checked on Windows" waits for the Windows
  testing phase; the quit-flow box waits for task C's dialog.
