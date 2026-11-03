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
   `reframe-desktop`, so the launcher matches the window to `reframe-desktop.desktop`.
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
   `application://reframe-desktop.desktop` (Context items 2 and 3). Windows keeps
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

(placeholder)

### Task D — D-5 single instance, open-with, CLI arguments

(placeholder)

### Task E — D-6 windows and comfort

(placeholder)

## Consequences

- The plan's text of D-1 and of the taskbar row was wrong for this platform; both are fixed
  below.
- The desktop frontend has its own output folder; the Docker image and S-4 still use
  `frontend/dist`.
- On Linux, taskbar progress shows only where a launcher listens for `LauncherEntry`
  (KDE Plasma, Ubuntu's dock) and the desktop entry `reframe-desktop.desktop` is installed.
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
