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

(placeholder)

### Task B — D-3 sidecar manager and quit flow

(placeholder)

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
