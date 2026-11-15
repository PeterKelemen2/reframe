# 07 — Desktop App (Linux + Windows)

## Decision: Tauri 2

The desktop app is a **Tauri 2** shell. It shows the shared Vue frontend in the system webview
(WebView2 on Windows, WebKitGTK on Linux). The Python core runs as a **sidecar process**: the
frozen `reframe-server` in desktop mode, bound to `127.0.0.1` with a random port and a
per-launch token.

Reasons:

- **One UI codebase.** Every frontend step in [06](06-web-app.md) also delivers the desktop UI.
  Only the `Platform` adapter differs.
- **Modern look.** It is the same Vue/PrimeVue UI, with native window chrome and OS theme
  detection.
- **The native features Reframe needs**, as official plugins: file and folder dialogs,
  drag-and-drop with **real file paths**, notifications, taskbar progress, single instance with
  open-with forwarding, window state, reveal in file manager, updater, tray.
- **Small shell** (no bundled Chromium). The bundled FFmpeg is the largest part of every
  installer. Per-user install on Windows.
- **The same API as the web app**, so the desktop app gets the server's tests and behaviour for
  free.

### Alternatives considered

| Option | For | Against | Verdict |
|--------|-----|---------|---------|
| **Tauri 2** + shared Vue + Python sidecar | One UI. Strong native integration. Small bundles. Active ecosystem | Two toolchains (Rust + Python). Sidecar lifecycle to manage. WebKitGTK codec support depends on GStreamer | **Chosen** |
| pywebview + shared Vue + in-process server | Python only, one PyInstaller build | No taskbar progress or single-instance plugin. Fewer packaging tools. Linux backend quirks (GTK vs Qt) | Fallback if you do not want Rust in the stack. The frontend `Platform` adapter makes a later switch cheap |
| PySide6 / Qt Quick (QML) | Native. Core runs in-process. Qt Multimedia for playback | A **second UI codebase** that must keep parity with the Vue app. A modern QML look takes extra work | Rejected |
| Electron | Mature. The same Chromium everywhere (consistent codecs) | 100 MB+ installers, high memory use, and it still needs the Python sidecar | Rejected |
| Flet (Flutter) | Python only, modern look | A separate UI codebase. Canvas-heavy views (crop magnifier) and file drag-and-drop are less mature | Rejected |

## Runtime architecture

```
┌──────────────────── Reframe.exe / reframe-desktop (Tauri, Rust) ────────────────────┐
│ main window (webview: Vue, VITE_PLATFORM=desktop)    preview window (optional)       │
│        │ invoke('backend_info') → {baseUrl, token}                                   │
│        │ HTTP + WS → 127.0.0.1:<port>                                                │
│ Rust: sidecar manager · plugins (dialog, notification, single-instance, opener,     │
│       window-state, updater) · Job Object (Windows)                                 │
└──────────────┬──────────────────────────────────────────────────────────────────────┘
               │ spawn (onedir, resources/sidecar/reframe-server[.exe])
       ┌───────┴─────────────────────────┐
       │ reframe-server --mode desktop   │──► ffmpeg / ffprobe (bundled, or override)
       │   --port 0 --auth token         │
       │   --parent-pid <pid>            │
       └─────────────────────────────────┘
```

## Sidecar lifecycle

1. On the main thread before the Tauri builder (so the sidecar starts while the webview loads),
   first look for a running owner of the queue (D-3,
   [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 3). When
   one is found, use its address and token and start no sidecar. Otherwise spawn the sidecar
   from the resources directory. Pass
   `--mode desktop --port 0 --auth token --owner-only --parent-pid <pid>`. The token is
   generated in Rust and passed in `REFRAME_TOKEN`, not on the command line (S-0). A sidecar
   that loses the queue lock to another owner exits 75; then run the order again
   ([decision 0069](../decisions/0069-m5-desktop-shell.md)). An owner whose process runs but
   whose server does not answer (starting, stopped, busy) is waited for, not replaced. An
   owner of another API version, a web-mode owner (`GET /api/system`'s `mode`) and one whose
   token cannot be sent are not used: the sidecar then runs on a private queue, and
   `backend_info`'s `privateQueue` says why, so the page can say that this window's jobs are
   not saved or shared (0069 "Fix round — FB").
2. Read stdout until the ready line `{"event":"ready","port":…}` arrives (20 s timeout). On
   timeout or early exit, show an error screen with the sidecar log path and a **Retry** button.
3. Keep `{baseUrl, token}` in Tauri managed state. The frontend gets it through
   `invoke('backend_info')`.
4. **Cleanup on every exit path**:
   - Normal quit: Tauri asks the server to shut down (`POST /api/system/shutdown`), waits up to
     5 s, then kills the process tree.
   - Tauri crash: on Windows, the sidecar is in a Job Object with `KILL_ON_JOB_CLOSE`. On
     Linux, the server watches `--parent-pid` and exits when the parent is gone. The server's own
     FFmpeg children follow (`C-1` child safety).
5. **Sidecar crash**: the frontend shows a "Reconnecting…" overlay. Rust restarts the sidecar
   (max 3 attempts in 60 s). The queue restores from SQLite, and running jobs become
   `Interrupted`.
6. **Quit while jobs run**: a dialog offers **Stop jobs and quit** · **Keep running in tray**
   (only when the tray is on and, on Linux, a tray host shows it, D-6) · **Cancel**.

## Native integrations

| Feature | Implementation |
|---------|----------------|
| Open files / folder, save path | `tauri-plugin-dialog` |
| Drag and drop with paths | Webview drag-drop event → `Platform.onFilesDropped` |
| Notifications (job done, queue done, error) | `tauri-plugin-notification` |
| Taskbar progress | `Window.setProgressBar` on Windows. Linux: the app's own Unity `LauncherEntry.Update` signal on the session bus, for launchers that support it (Tauri's needs libunity; [decision 0069](../decisions/0069-m5-desktop-shell.md)) |
| Single instance + "Open with Reframe" | `tauri-plugin-single-instance`. Paths from argv are forwarded to the running window and probed |
| File associations (optional) | NSIS registry entries. Linux `.desktop` `MimeType=` |
| Reveal in folder, open externally | Reveal: `tauri-plugin-opener` (D-Bus `FileManager1` on Linux). Open externally: the shell's `open_external` command (the preview clip links only); in an AppImage it starts the opener's launchers itself, with the user's environment and folder ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md) "Fix round — FA") |
| Remember window size/position | `tauri-plugin-window-state` |
| Detached preview window | A second webview window on route `/preview/:sourceId`, same backend |
| Tray (optional) | Queue progress, pause all, show, quit |
| Theme | Follows the OS light/dark setting, unless set in Settings |
| Updates | `tauri-plugin-updater` with signed release manifests |

### In-app video playback

Webview codec support differs: WebView2 plays H.264 out of the box, but HEVC and AV1 need
Windows extensions. WebKitGTK depends on the GStreamer plugins that are installed. Because of
this:

- The preview clip plays in-app when the webview can decode it (checked with
  `HTMLMediaElement.canPlayType`).
- **Frame compare works for every codec.** FFmpeg decodes frames from the encoded preview clip
  to PNG, and the split view shows them next to the source frame. This is the main quality
  check and does not depend on the webview.
- **Open in external player** (mpv, VLC, or the system default) is always available.

## Tool bundling

Every desktop package bundles the pinned FFmpeg from `tools/ffmpeg.toml`
([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)).

| Platform | FFmpeg |
|----------|--------|
| Windows | Bundled in `resources/tools/ffmpeg/` |
| Linux AppImage | Bundled inside the AppImage |
| Linux .deb / .rpm | Bundled in `/usr/lib/Reframe/tools/ffmpeg/`. No dependency on the distro `ffmpeg` package |

No other tool is bundled or recommended: since C-18 and C-19 Reframe runs no MKVToolNix or
MediaInfo ([decision 0080](../decisions/0080-own-matroska-header-writer.md),
[decision 0081](../decisions/0081-probe-without-mediainfo.md)). Until then, the Windows
package bundles the MediaInfo CLI and the .deb / .rpm have `Recommends: mediainfo`.

**Override**: Settings → Tools has a path field for each tool, a **Test** button and a **Use
bundled** reset. Environment variables (`REFRAME_FFMPEG`, …) take precedence and show as
read-only. The first-run screen shows which binary is in use and where it came from.

## Steps

Linux first ([decision 0053](../decisions/0053-linux-first-windows-testing-phase.md)): every
step is built and checked on Linux. The Windows code is written to this plan and mock-tested
on Linux; its parts marked *(Windows testing phase)* are checked in the
[Windows testing phase](08-roadmap.md#windows-testing-phase) of M10.

### D-0 Spike (do this before the frontend is far along)
The spike lives in `desktop/spike/`, committed and not built by CI; D-1 and D-2 may reuse
or delete it ([decision 0054](../decisions/0054-d0-spike-layout-and-parent-watch.md)).

- [x] Minimal Tauri app + PyInstaller **onedir** sidecar running `reframe-server` with a hello
      endpoint, on Linux. On Windows: *(Windows testing phase)*.
- [x] Measure cold start to "ready" (target < 2 s from SSD).
- [x] Prove cleanup: `kill -9` the Tauri process, then check that no sidecar or FFmpeg process
      remains. The same with a kill from Task Manager: *(Windows testing phase)*.
- [x] Check drag-and-drop paths, PrimeVue rendering and canvas magnifier performance on
      WebKitGTK.
- [x] Note any PyInstaller hidden imports (pydantic, uvicorn loops, langcodes data; since C-20
      the generated language table instead, [decision 0082](../decisions/0082-own-language-data-table.md)).

Linux result (2026-10-28): [decision 0001](../decisions/0001-desktop-shell.md). The Windows items
stay open for the Windows testing phase.

Done when: a short written result for Linux goes into `docs/decisions/0001-desktop-shell.md`
and confirms or revisits this choice. It lists the Windows items as not verified.

### D-1 Project scaffold
- [x] `desktop/src-tauri` (Tauri 2). `tauri.conf.json`: `devUrl` = Vite dev server,
      `beforeBuildCommand` = `npm --prefix ../frontend run build:desktop` (Tauri runs it in
      `desktop/`), `frontendDist` = the desktop frontend output, `frontend/dist-desktop`
      ([decision 0069](../decisions/0069-m5-desktop-shell.md)).
- [x] Tauri v2 capability files: grant only the plugin permissions that the app uses.
- [x] CSP that allows `connect-src http://127.0.0.1:* ws://127.0.0.1:*` and nothing else
      remote.

### D-2 Sidecar build
- [x] `desktop/sidecar/build.py`: PyInstaller onedir build of `reframe_server.__main__`. It
      includes the `reframe/definitions/data` and built-in preset files and stamps the version.
- [x] Output to `desktop/src-tauri/resources/sidecar/`. It is listed under `bundle.resources`.
- [x] The same build makes the frozen `reframe` CLI in the same folder (one set of
      libraries). The `.deb` and `.rpm` link it as `/usr/bin/reframe`; the Windows installer
      offers to add the folder to the user's `PATH`; the AppImage does not put it on `PATH`
      ([decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 11).
      The Windows installer's offer is checked on Windows, also that an update keeps the entry
      ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md) task W).
- [x] A smoke test runs the frozen binary with `--mode desktop --port 0` and waits for the ready
      line.

Linux result (2026-11-03): [decision 0069](../decisions/0069-m5-desktop-shell.md) "Task A". The
sidecar ships MediaInfo (pymediainfo with its own library) until C-19
([decision 0081](../decisions/0081-probe-without-mediainfo.md)).

### D-3 Sidecar manager (Rust)
- [x] Spawn with `tokio::process`. Read the ready line. Keep the managed state.
- [x] `backend_info` command. Restart policy. Log sidecar stderr to `<data>/logs/sidecar.log`.
- [x] Windows: create a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and assign the
      sidecar to it (`windows` crate). Checked on Windows: *(Windows testing phase)*.
- [x] The quit flow with the running-jobs dialog.
- [x] **Find the owner first**
      ([decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 3),
      in Rust: read `<data>/server.json`; when `GET /api/health` answers with the same
      `instance` and `api_version`, and `GET /api/system` with `mode` `desktop`, use that
      server: no sidecar, no restart policy, and
      **Stop jobs and quit** cancels the jobs through the API. The app's event connection
      keeps that owner from exiting when idle. When it ends, run the order again (a new
      sidecar restores the queue). Otherwise start the sidecar; it publishes `server.json`
      (S-7), so a CLI hands its jobs to the app. The running-jobs dialog counts the CLI's
      jobs too.

### D-4 Desktop platform adapter
- [x] `frontend/src/platform/desktop.ts` implements `Platform` with the Tauri plugins.
- [x] The desktop build hides web-only UI (server file browser) and shows desktop-only UI
      (reveal, tray settings, when-done power actions).

### D-5 Single instance, open-with, CLI arguments
- [x] `reframe-desktop file1.mkv folder/` (`Reframe.exe …` on Windows) opens the app (or
      focuses the running one) and probes the paths. `reframe` is always the CLI
      ([decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 11).
- [x] Optional file associations for `.mkv`, `.mp4`, `.m2ts`, `.ts`, `.avi`, `.mov`, `.webm`.

### D-6 Windows and comfort
- [x] Window state, minimum size (1100×700), detached preview window, theme follow, tray
      (optional, off by default). On Linux; Windows not verified. On Wayland the compositor
      places windows, so only size and maximised state come back; a tray switched off is
      hidden, not removed ([decision 0069](../decisions/0069-m5-desktop-shell.md) "Task E").
      On Linux the tray is on only while a tray host (`org.kde.StatusNotifierWatcher`) is on
      the session bus (0069 "Fix round — FB").

### D-7 Tool bundling
- [x] Choose the FFmpeg build for `tools/ffmpeg.toml` against the requirements in
      [02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg). Test it on the hosts that are
      available, aiming at Intel (VAAPI + QSV), AMD (VAAPI, AMF on Windows) and NVIDIA
      (NVENC), on at least two Linux distros (Debian/Ubuntu and Fedora or Arch) and on
      Windows *(Windows testing phase)*. Record each host and its result in `docs/decisions/0002-bundled-ffmpeg.md`, and
      list there the hosts that were not tested as not verified
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 7).
- [x] CI downloads the pinned FFmpeg / MediaInfo builds (MediaInfo: until C-19,
      [decision 0081](../decisions/0081-probe-without-mediainfo.md); MKVToolNix: not bundled since
      [decision 0079](../decisions/0079-q5-release-process.md) item 11), verifies the checksums,
      and puts them in `resources/tools/` (`scripts/bundle-tools.py`; one build platform per
      layout, so no sub-folder per OS). The same step feeds the .deb/.rpm layout. The
      `desktop-smoke` CI job and the Linux package build run it; the job has not run on GitHub
      ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md)).
- [x] Settings → Tools: a path override per tool, **Test**, **Use bundled**, env overrides shown
      read-only. The first-run check runs before the main UI. On Linux; the Windows row of the
      bundled MediaInfo is checked with D-8's installer
      ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md) "Task U"). Since
      C-18 there is no mkvpropedit row and no MKVToolNix text
      ([decision 0080](../decisions/0080-own-matroska-header-writer.md)), and since C-19 no
      mediainfo row ([decision 0081](../decisions/0081-probe-without-mediainfo.md)).

### D-8 Packaging, signing, updates
- [x] Windows: NSIS installer (per-user, no admin rights), WebView2 bootstrapper, optional MSI.
      Code signing is strongly recommended (SmartScreen warns about unsigned installers).
      Installed and run on Windows: *(Windows testing phase)*. The per-user install goes to
      `%LOCALAPPDATA%\Programs\Reframe` (Tauri's default is Reframe's data folder); the MSI is
      per machine, for administrators. Signed with a self-signed test certificate; a release
      needs one from a certification authority. Installed, run, updated and removed on the
      Windows VM ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md)
      task W).
- [x] Linux: AppImage (built on the oldest supported distro image, for glibc compatibility),
      `.deb`, `.rpm`. Flatpak comes later (its sandbox complicates file access and GPU access).
      Built in `ubuntu:22.04` by `desktop/packaging/linux/build.sh`; installed and run in Ubuntu
      22.04, Debian 12 and Fedora 45 containers, the AppImage on the host in a virtual session
      ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md) task L).
- [ ] Updater: signed `latest.json` in GitHub Releases. The plugin, the test key, the question,
      the install through the quit flow and a signed `latest.json` are built and checked from a
      test release served to the VM (0072 task W, with the release job's steps); a GitHub
      release has not been made (no workflow runs, and the repository is private).

### D-9 Desktop smoke tests
- [ ] `tauri-driver` (WebDriver) on Linux and Windows CI: the app starts, the backend becomes
      ready, a fixture opens from argv, a job is queued and finishes, and quitting leaves no
      orphan processes. On Windows: *(Windows testing phase)*.

## Risks

| Risk | Mitigation |
|------|-----------|
| Orphaned FFmpeg or sidecar after a crash | Job Object (Windows), PDEATHSIG + parent watch (Linux). Tested in D-0 and D-9 |
| Antivirus false positives on the PyInstaller binary (Windows) | Onedir build (not onefile), code signing, submit to vendors if needed |
| WebKitGTK differences (CSS, performance, codecs) | D-0 spike, Playwright WebKit project in CI, frame compare that does not need webview codecs |
| The bundled FFmpeg cannot use VAAPI/QSV on some Linux hosts (driver path or libva mismatch) | D-7 tests on several distros. `LIBVA_DRIVERS_PATH` handling in `C-1`. Capability reasons in Settings name the cause. Users can point the override to their distro FFmpeg |
| The bundled FFmpeg makes installers larger | Shared-library build (one copy of the libraries for `ffmpeg` and `ffprobe`). Installer compression |
| Startup time of the Python sidecar | Onedir build, lazy imports, the UI shows a skeleton while it connects |
