# M5 task breakdown

Working notes of the lead for the branch `m5-desktop-shell`: milestone M5, the desktop shell. The
plan ([plan/07-desktop-app.md](plan/07-desktop-app.md) §Sidecar lifecycle, §Native integrations,
§D-1 to §D-6; [plan/08-roadmap.md](plan/08-roadmap.md) §M5; the desktop parts of
[plan/02-architecture.md](plan/02-architecture.md) and
[plan/09-quality-and-release.md](plan/09-quality-and-release.md)) is the spec; this file says who
builds which part, in which order, and what each part must offer to the others. Decision:
[0069](decisions/0069-m5-desktop-shell.md) (the lead's choices, what the plan got wrong, and one
section per task). Status: [status.md](status.md). The template is
[m9-breakdown.md](m9-breakdown.md). If the lead's context is summarised, this file and
`status.md` are the source of truth.

M5 builds on D-0 ([0001](decisions/0001-desktop-shell.md): the spike's shell, its sidecar
start, cleanup and PyInstaller options), the shared queue
([0042](decisions/0042-one-scheduler-process-and-cli-clients.md) items 3 and 11, `server.json`
of [0056](decisions/0056-s7-owner-endpoint-file-and-idle-exit.md)), and the frontend's
`Platform` adapter (F-5 pickers and drop, F-14 reveal in folder already call it).

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| lead | D-1 | the scaffold: `desktop/src-tauri` (Tauri 2.12.5), `tauri.conf.json` (`devUrl`, `beforeDevCommand`, `beforeBuildCommand`, `frontendDist`), capability files, the CSP, the module stubs and contracts below, the CI job | 07 §D-1; 0069 items 1–5, 11 |
| A | D-2 | `desktop/sidecar/build.py`: the PyInstaller onedir of `reframe_server.__main__` and the frozen `reframe` CLI in one folder (one set of libraries), the data files, the version stamp, the output in `desktop/src-tauri/resources/sidecar/` under `bundle.resources`, the `.deb` / `.rpm` link `/usr/bin/reframe`, the Windows installer's PATH offer, the smoke test | 07 §D-2; 0001 §PyInstaller; 0042 item 11 |
| B | D-3 | the sidecar manager in Rust (`backend/`): the owner first (`server.json`, `GET /api/health`), else the sidecar (spawn, ready line, managed state, restart policy, `<data>/logs/sidecar.log`, death signal, Job Object on Windows), `backend_info`; the quit flow's shell side (`quit.rs`) | 07 §Sidecar lifecycle, §D-3; 0001 Decision 1–2, Consequences D-3; 0042 item 3; 0069 items 7–8 |
| C | D-4 | `frontend/src/platform/desktop/` with the Tauri plugins (dialogs, drop, reveal, open, notifications, taskbar progress), the backend's state in the app (error screen with the log and **Retry**, *Reconnecting…*, a new address after a restart), the running-jobs quit dialog, when-done `quit`, the web-only UI hidden; `progress.rs` (the Linux `LauncherEntry` signal) | 07 §D-4, §Sidecar lifecycle 2, 5, 6; 06 §Platform adapter; 0069 item 6 |
| D | D-5 | single instance, `reframe-desktop file1.mkv folder/` (open or focus, then probe), the optional file associations | 07 §D-5; 0001 Consequences D-5 |
| E | D-6 | window state, the 1100×700 minimum, the detached preview window, theme follow, the optional tray (off by default), the shell's own settings | 07 §D-6, §Native integrations; 03 §Preview panel |

**Out of scope** (do not start): D-7 (tool bundling; `0002-bundled-ffmpeg.md` stays unwritten),
D-8 (installers, signing, updater), D-9 (tauri-driver smoke tests), F-16, Q-x, the Windows
testing phase. Do not block them: the resources layout leaves `resources/tools/` free for D-7,
and nothing here assumes a bundle format D-8 has not chosen.

**Windows** ([0053](decisions/0053-linux-first-windows-testing-phase.md)): the Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `CREATE_NO_WINDOW`, the installer's PATH offer and the
`Reframe.exe` arguments are written to the plan and unit-tested with mocks on Linux (the logic
behind a small trait or a pure function; the `windows` crate calls under `cfg(windows)`), and
listed in `status.md` "Not verified". This machine has no Windows target, so `cfg(windows)` code
is not even compiled here; the CI job's Windows runner is where it would.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0069, D-1 (the scaffold, the CSP checked in the real webview), the stubs and contracts, the frontend mounts (`useOpenPaths`, the bare `/preview/:sourceId` route; tests that fail without them), the Tauri npm packages, the CI job, the headless tools | `main` (72eb54a) |
| 1 | A, B, C (C two-phase: phase 1 against the stubs, phase 2 resumed through SendMessage after B merges) | wave 0 |
| 2 | D, E | B and C merged |
| 3 | two fresh reviews (R1: Rust and the sidecar: process lifetime, `kill -9` cleanup, owner discovery races, the CLI handoff; R2: the frontend and the integration), the lead's reproduction of every blocker and major, the fix round, the final checks, the M5 demo (headless, then once headed by the lead), the docs | wave 2 merged |

The lead merges each task with `--no-ff`, runs the checks, mutates once per task, and removes the
worktree and its branch. Every agent: `model: "opus"`, `effort: "high"` (the owner's rule for this
run), a fresh agent (not a fork), `isolation: "worktree"` for code.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Frontend
paths are relative to `frontend/src/`; Rust paths to `desktop/src-tauri/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **A** | `desktop/sidecar/**` (new), `packages/reframe-server/tests/test_frozen_sidecar.py` (move or rename it if a better place exists), the `bundle` object of `tauri.conf.json` except `bundle.fileAssociations` (resources, Linux and Windows packaging keys), `desktop/src-tauri/windows/**` and `desktop/src-tauri/linux/**` (new: installer hooks, package scripts), in `pyproject.toml` only the ruff / mypy entries for `desktop/sidecar` and the `dev` group if a tool is missing, `testdata/README.md` (its own heading) | `src/**` (Rust), the frontend, `desktop/spike/**` (read it, reuse by copying) |
| **B** | `src/backend/**` (the stub `mod.rs` is B's), `src/quit.rs`; `Cargo.toml` / `Cargo.lock` only to add a dependency it can name a reason for (no other wave-1 task touches them) | the other `src/*.rs`, `main.rs`, `tauri.conf.json`, capabilities, the frontend |
| **C** | `platform/desktop/index.ts` (+ new tests there), `platform/index.test.ts`, `api/boot.ts` (+ `boot.test.ts`), `App.vue` (+ `App.test.ts`; keep the lead's mounts and their tests), new files in `components/shell/` and `composables/` for the quit dialog, the backend error screen and the reconnect overlay, `components/shell/BootScreen.vue`, `i18n/messages/en/desktop.json` (new), components that show web-only UI in the desktop build (list them in the report), `src/progress.rs`, `capabilities/main.json` | `platform/types.ts`, `platform/web.ts`, `platform/desktop/{openPaths,comfort}.ts`, `components/shell/PreviewPanel.vue`, `views/**`, `stores/**` (use them), the other Rust files |
| **D** | `src/open_paths.rs`, `platform/desktop/openPaths.ts` (+ test), `composables/useOpenPaths.ts` (+ test), `bundle.fileAssociations` of `tauri.conf.json` (and the desktop entry's `MimeType=`), `i18n/messages/en/openPaths.json` (new) | the other Rust files, `App.vue`, `stores/**` (use them) |
| **E** | `src/comfort.rs`, `src/tray.rs`, `src/desktop_settings.rs`, `capabilities/preview.json`, `platform/desktop/comfort.ts` (+ test), `views/PreviewWindowView.vue` (+ test), `components/shell/PreviewPanel.vue` (+ test; the detach button), `views/SettingsView.vue` (+ test) and a new `components/settings/DesktopSection.vue` (the tray switch), `composables/useTheme.ts` only if theme follow needs it, `i18n/messages/en/window.json` (new) | the other Rust files, `App.vue`, `router/**` |

**Lead-owned**: `src/main.rs`, `tauri.conf.json` (except the keys above), `tauri.windows.conf.json`,
`Cargo.toml` / `Cargo.lock` (B's exception above), `desktop/package.json`, `frontend/package.json`,
`frontend/package-lock.json`, `platform/types.ts`, `platform/web.ts`, `router/**`, `main.ts`,
`setup.ts`, `stores/**`, `api/**` except `boot.ts`, `frontend/vite.config.ts`, `.github/**`,
`scripts/**`, `packages/**` except A's test. An agent that needs a dependency, a command, an event,
a store member or a change of these files asks the lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own `D-x` row.
- `docs/decisions/0069-m5-desktop-shell.md`: each task writes only its own section ("Task X").
- `docs/plan/07-desktop-app.md`: a task ticks its own step's boxes when they pass, and edits its
  step's text only together with a decision (its 0069 section).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. Only additions that keep every caller working are allowed (a new optional field, a new
function); anything else goes back to the lead first.

### Tauri commands (registered in `main.rs`)

| Command | Owner | Arguments → result |
|---------|-------|--------------------|
| `backend_info` | B | → `BackendInfo` or the error `BackendError`; waits while the backend starts |
| `backend_retry` | B | → nothing; runs the start order again after a failure |
| `quit_ready` | B | → nothing; the page answers `quit-requested` from now on |
| `quit_app` | B | → nothing; stops the backend if the app started it (shutdown request, a kill after 5 s), then exits 0 |
| `hide_main_window` | B | → nothing or an error string; *Keep running in tray* |
| `take_open_paths` | D | → the waiting paths, once each (D may give it a richer result type, e.g. to report a name that cannot be read) |
| `set_taskbar_progress` | C | `value: number \| null` (0…1) → nothing; also calls `tray::show_progress` |
| `open_preview_window` | E | `sourceId: string` → nothing or an error string |
| `desktop_settings` | E | → `DesktopSettings` |
| `set_desktop_settings` | E | `settings: DesktopSettings` → the saved `DesktopSettings` or an error string |

Payloads (serde `camelCase`): `BackendInfo { baseUrl, token, instance, owned }`,
`BackendError { message, log: string | null }`, `DesktopSettings { tray }`.

### Events (Rust → pages)

| Event | Sender | To | Payload |
|-------|--------|----|---------|
| `backend-state` | B | every window, on each change | `{state:"starting"}` \| `{state:"ready", info: BackendInfo}` \| `{state:"failed", error: BackendError}` |
| `quit-requested` | B | `main` | none; sent on a close of the main window (and the tray's Quit) once the page called `quit_ready`; before that a close quits at once |
| `open-paths` | D | `main` | none: paths are waiting in `take_open_paths` (the page also calls it once at start) |
| Tauri's drag-drop events | Tauri | the webview | `getCurrentWebview().onDragDropEvent`; the main window keeps drag-and-drop on |

### Rust module surfaces (`desktop/src-tauri/src/`)

- `backend::Backend` (B), managed state: `Backend::start() -> Backend` (on the main thread,
  before the builder), `attach(&self, AppHandle)` (in `setup`; events from then on),
  `state(&self) -> BackendState`, `async info(&self) -> Result<BackendInfo, BackendError>`,
  `retry(&self)`, `async request(&self, method: &str, path: &str) -> Result<u16, String>` (a
  request without a body to the current backend, for the tray's *Pause all*), `async stop(&self)`
  (idempotent; an owner the app did not start is left running). `backend::STATE_EVENT`.
- `quit` (B): `request_quit(&AppHandle)` (what a close does; the tray's Quit calls it; it shows
  the main window first when the page will ask), `on_window_event`, `on_run_event` (`Exit` stops
  the backend), `QUIT_EVENT`, the three commands.
- `progress` (C): `DESKTOP_ENTRY` = `Reframe.desktop`: Tauri's deb and rpm install the entry under the product name, with `StartupWMClass=reframe-desktop`, the Wayland app id (0069 Context item 3; task A), the command.
- `open_paths` (D): `single_instance()` (the first plugin), `Pending::from_args(args_os)`,
  `OPEN_PATHS_EVENT`, the command.
- `comfort` (E): `window_state()` (a plugin), `create_main_window(&AppHandle)` (label `main`,
  `index.html`, title `Reframe`, minimum 1100×700, drag-and-drop on), the command.
- `tray` (E): `setup(&AppHandle)` (creates the tray when the setting is on),
  `show_progress(&AppHandle, Option<f64>)`.
- `desktop_settings` (E): `DesktopSettings`, the two commands.

**Process rules for B** (0001 Decision 1–2 and Consequences, binding): the sidecar is the shell's
direct child; it is forked on a thread that lives as long as the app (never a `spawn_blocking`
thread: the death signal follows the forking thread), with `PR_SET_PDEATHSIG = SIGTERM` in
`pre_exec` and the re-check of the parent; arguments
`--mode desktop --port 0 --auth token --owner-only --parent-pid <pid>`, the token made in Rust in
`REFRAME_TOKEN`; no `println!` (a closed stdout panics the thread); the ready line within 20 s;
quit = `POST /api/system/shutdown`, then a kill after 5 s; restart at most 3 times in 60 s; exit
75 runs the start order again and is not a crash; the sidecar's stderr goes to
`<data>/logs/sidecar.log`, rotated. In debug builds `REFRAME_DESKTOP_SIDECAR` (a command line
split at spaces, as the spike's) may replace the frozen sidecar, so the app runs from source
before D-2's build exists; in a dev build (`tauri dev`, origin `http://127.0.0.1:5173`) the
sidecar also gets that origin in `REFRAME_CORS_ORIGINS`.

### The frontend (`platform/types.ts`, lead)

`Platform.desktop: DesktopShell | null` (web: `null`). `DesktopShell`: `backendInfo()`,
`onBackendState(cb)`, `retryBackend()`, `onQuitRequested(cb)`, `quitReady()`, `quit()`,
`hideMainWindow()` (C, in `platform/desktop/index.ts`); `onOpenPaths(cb)` (D, in
`platform/desktop/openPaths.ts`; it listens only in the `main` window); `settings()`,
`setSettings(s)`, `openPreviewWindow(sourceId)` (E, in `platform/desktop/comfort.ts`). The types
`DesktopBackend`, `DesktopBackendError`, `DesktopBackendState`, `DesktopSettings` mirror the Rust
payloads. Only `platform/desktop/**` imports `@tauri-apps/*` (the web bundle must not contain
it: `npm run build:web` and a grep of `dist/` for `@tauri-apps` / `__TAURI` show it).

### The quit flow (B and C)

1. A close of the main window, or the tray's Quit: Rust prevents the close and, once the page
   called `quit_ready` and the backend is ready, sends `quit-requested`; otherwise it quits at
   once (`backend.stop()`, exit 0).
2. The page counts the queue's running and paused jobs (every front end's, so a CLI's too). None:
   `quit()`. Some: the dialog **Stop jobs and quit** · **Keep running in tray** (only when the tray
   is on) · **Cancel**.
3. **Stop jobs and quit**: with the app's own sidecar (`owned`), `quit()` (the shutdown request
   ends the running jobs `interrupted` and removes their `.part` files; waiting jobs stay
   waiting). With an owner the app did not start: `POST /api/queue/stop`, then
   `POST /api/queue/{id}/cancel` for each running or paused job, then `quit()`; the owner runs on
   (0042 Consequences).
4. When-done `quit` (`power.state` `executing` with action `quit`): `quit()` without the dialog.

### The backend's state in the page (B and C)

`backend-state` `starting` after `ready` (the sidecar ended and is restarting, or the owner went
away) shows *Reconnecting…* over the app; `ready` with another `baseUrl` or `token` configures
the API client and the event connection again (the queue restores from SQLite; a new `instance`
is handled as today); `failed` shows the error screen with `error.message`, the log path and
**Retry** (`retryBackend()`).

## Done when (word for word in each agent's brief)

07 gives D-1 to D-6 no "Done when" line; the boxes of each step are its criteria, and each must
pass on Linux (Windows: mock-tested, "Not verified").

**D-1** (lead):
- `desktop/src-tauri` (Tauri 2). `tauri.conf.json`: `devUrl` = Vite dev server,
  `beforeBuildCommand` = `npm --prefix ../frontend run build:desktop` (Tauri runs it in
  `desktop/`), `frontendDist` = the desktop frontend output, `frontend/dist-desktop`.
- Tauri v2 capability files: grant only the plugin permissions that the app uses.
- CSP that allows `connect-src http://127.0.0.1:* ws://127.0.0.1:*` and nothing else remote.

**D-2** (A):
- `desktop/sidecar/build.py`: PyInstaller onedir build of `reframe_server.__main__`. It
  includes the `reframe/definitions/data` and built-in preset files and stamps the version.
- Output to `desktop/src-tauri/resources/sidecar/`. It is listed under `bundle.resources`.
- The same build makes the frozen `reframe` CLI in the same folder (one set of libraries). The
  `.deb` and `.rpm` link it as `/usr/bin/reframe`; the Windows installer offers to add the folder
  to the user's `PATH`; the AppImage does not put it on `PATH` (decision 0042 item 11).
- A smoke test runs the frozen binary with `--mode desktop --port 0` and waits for the ready line.

**D-3** (B):
- Spawn with `tokio::process`. Read the ready line. Keep the managed state.
- `backend_info` command. Restart policy. Log sidecar stderr to `<data>/logs/sidecar.log`.
- Windows: create a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and assign the sidecar
  to it (`windows` crate). Checked on Windows: *(Windows testing phase)*.
- The quit flow with the running-jobs dialog.
- **Find the owner first** (decision 0042 item 3), in Rust: read `<data>/server.json`; when
  `GET /api/health` answers with the same `instance` and `api_version`, use that server: no
  sidecar, no restart policy, and **Stop jobs and quit** cancels the jobs through the API. The
  app's event connection keeps that owner from exiting when idle. When it ends, run the order
  again (a new sidecar restores the queue). Otherwise start the sidecar; it publishes
  `server.json` (S-7), so a CLI hands its jobs to the app. The running-jobs dialog counts the
  CLI's jobs too.

**D-4** (C):
- `frontend/src/platform/desktop.ts` implements `Platform` with the Tauri plugins (built as the
  folder `platform/desktop/`).
- The desktop build hides web-only UI (server file browser) and shows desktop-only UI (reveal,
  tray settings, when-done power actions).

**D-5** (D):
- `reframe-desktop file1.mkv folder/` (`Reframe.exe …` on Windows) opens the app (or focuses the
  running one) and probes the paths. `reframe` is always the CLI (decision 0042 item 11).
- Optional file associations for `.mkv`, `.mp4`, `.m2ts`, `.ts`, `.avi`, `.mov`, `.webm`.

**D-6** (E):
- Window state, minimum size (1100×700), detached preview window, theme follow, tray (optional,
  off by default).

Also from 07 §Sidecar lifecycle and §Native integrations (the task named): the ready-line timeout
error screen with the sidecar log path and **Retry** (B: the state, C: the screen); *Reconnecting…*
and restart, at most 3 attempts in 60 s, queue restored, running jobs `interrupted` (B, C);
cleanup on every exit path (B); notifications for job done, queue done and error (C: the
frontend's existing `notify` calls go through the plugin); taskbar progress (C); drag-and-drop with
real paths through `Platform.onFilesDropped`, and a name that cannot be read (U+FFFD) reported with
the file dialog offered (C; 0001 Consequences D-5); reveal in folder and open externally (C).

## The M5 demo (the acceptance test; the lead runs it at the end)

08 §M5 on Linux: the M4 flow as a desktop app (open a file → choose a preset → change the
encoder and quality → add and remove audio tracks → add to queue → watch progress → open the
log; validation issues inline and on Summary), with native dialogs, drag-and-drop from the file
manager, notifications, taskbar progress, and a clean quit while a job runs. Also (the owner's
M5 brief): `kill -9` of the app leaves no sidecar or FFmpeg process; a `reframe encode` in a
terminal hands its jobs to the running app; cold start is under 2 s (09 §Q-3: "Desktop cold start
to interactive UI < 2 s on SSD"). First headless in the virtual session (below), then once headed
by the lead on `HDMI-A-1` through the guard.

## Commands

From the root (Python, CLAUDE.md): `uv run ruff check`, `uv run ruff format --check`,
`uv run mypy`, `uv run mypy --platform win32`, `uv run pytest -m "not needs_gpu"` (agents: only
the tests of what they changed; the lead runs the whole suite alone). From `frontend/`:
`npm run lint`, `npm run fmt:check`, `npm run typecheck`, `npm test`, `npm run build:web`,
`npm run build:desktop`. From `desktop/src-tauri/` (Rust): `cargo fmt --check`,
`cargo clippy --all-targets -- -D warnings`, `cargo test`. `tauri::generate_context!` embeds
`frontend/dist-desktop`, so run `npm run build:desktop` once in a fresh worktree before cargo.
The app: `cd desktop && npm ci && npx tauri build --debug --no-bundle` (it runs
`build:desktop` first), binary `$CARGO_TARGET_DIR/debug/reframe-desktop`.

**Cargo**: every agent uses `CARGO_TARGET_DIR=/home/peti/.cache/reframe-m5-target` (shared; cargo
serialises builds with its lock; disk space is low). The built binary's path is shared too: copy
it into your own `scratchpad/task-<x>/bin/` in the same command as the build
(`… && cp "$CARGO_TARGET_DIR/debug/reframe-desktop" <yours>`) and run only your copy.
Tauri takes the executable's folder as its resource folder only inside a cargo
`target/<profile>/` folder with a `.cargo-lock` file (tauri-utils `resource_dir_from`), so copy it
to `<scratch>/target/debug/reframe-desktop`, `touch <scratch>/target/debug/.cargo-lock`, and, to
use A's frozen sidecar (`uv run python desktop/sidecar/build.py`, about 50 s), copy
`$CARGO_TARGET_DIR/debug/sidecar/` next to it (then remove `$CARGO_TARGET_DIR/debug/sidecar`).
Without it, run the sidecar from source: `REFRAME_DESKTOP_SIDECAR=<worktree>/.venv/bin/reframe-server`. Never copy
or build in `desktop/spike/src-tauri/target`.

**Ports** (rule 7): agent N uses 87N0 to 87N9; 8750 and 8751 belong to `npm run e2e`. A 871x,
B 872x, C 873x, D 874x, E 877x, R1 878x, R2 879x, the lead 876x, fix agents 870x and 8752–8759.
The webview inspector port of an agent is its 87N9.

### Headless checks of the real app (0069 Context item 4; the lead's tools)

The tools are in `/tmp/claude-1000/-home-peti-Programming-reframe/29c176cb-e17e-4273-bbda-4719bf302a99/scratchpad/lead/tools/`
(read them; copy them into your own `scratchpad/task-<x>/` if you change them):

- `vk-run.sh OUT SOCKET SESSION [W H]` runs the shell script `SESSION` inside a private, virtual
  KWin (`kwin_wayland --virtual` under `dbus-run-session`, `DISPLAY` and `WAYLAND_DISPLAY` unset,
  `GDK_BACKEND=wayland`). Every folder the app, its sidecar and a CLI use is below `OUT`
  (`XDG_{CONFIG,DATA,CACHE}_HOME`, `REFRAME_{DATA,CONFIG,CACHE}_DIR`), and
  `REFRAME_POWER_DRY_RUN=1`. Use a socket name `reframe-<task>`. Nothing appears on the owner's
  displays, and the session's D-Bus is private (no notification server, no portal, no
  `com.canonical.Unity`; watch a signal with `dbus-monitor --session` inside the session).
- Inside a session: `spectacle -b -n -f -o "$OUT/name.png"` captures the virtual output (read the
  PNG with the Read tool); `sh "$TOOLS/vk-close.sh"` closes the main window as a click on its close
  button would.
- `uv run python "$TOOLS/webview_eval.py" PORT 'expression'` (or `--file f.js`) runs JavaScript in
  the real webview of an app started with `WEBKIT_INSPECTOR_HTTP_SERVER=127.0.0.1:PORT` (debug
  builds) and prints its value as JSON; a Promise is awaited. Click with `element.click()`, read
  the DOM, call `window.__TAURI_INTERNALS__.invoke` only to check what a page could do.
- Native dialogs (GTK file chooser) open inside the virtual session too: check that they open (a
  screenshot); picking a file in them is the lead's headed check.

## Fix round

(The lead fills it after the reviews.)

## Rules for every agent (word for word in each brief)

### Rule 5: the code

- Use CLAUDE.md. Comments follow the `code-comments` skill: they say why, and never contain step
  IDs, plan sections or history. Strict TypeScript; PrimeVue 4 and TypeScript 6 stay (0003);
  every visible string goes through vue-i18n. Rust: edition 2024, no `unwrap()` on a path a user
  can reach, no `println!` (0001), `unsafe` only with a `SAFETY:` comment.
- All of this is green before a step is done: the commands of the section "Commands" that touch
  what you changed (Python, frontend, Rust), and `scripts/gen-api.sh --check` from the root.
- Desktop work is checked in the real app, not only with unit tests: the headless session above,
  with screenshots that you read and describe, for light and dark where the UI changed.
- Real behaviour of Tauri, WebKitGTK, PyInstaller, FFmpeg or the server is checked against the
  real thing and recorded in a test or in your 0069 section, not taken from memory.

### Rule 6: displays, windows and the pointer (binding for the lead and every agent)

The owner has two displays: `HDMI-A-1` (secondary, at 0,0, 1920x1080) and `DP-1` (primary, at
1920,0), where a movie may be playing. Nothing may open a window on `DP-1`, take its keyboard
focus, move the pointer onto it or click on it. Do not ask the owner which display is which.

- **Default: headless.** A subagent never opens a window on the owner's displays and never uses
  the real pointer or keyboard. The desktop app, a native dialog and Dolphin run only inside the
  virtual session of `vk-run.sh`; a browser only headless (Playwright). That means no `tauri dev`
  or app start outside `vk-run.sh`, no headed browser, no `xdg-open`, no `notify-send` on the
  real bus, no `xdotool`, `ydotool`, `kdotool` or `/dev/uinput`, no `kscreen-doctor` changes, and
  no browser-use plugin. A process inside `vk-run.sh` must never get the real `WAYLAND_DISPLAY`,
  `DISPLAY` or session bus. If a subagent thinks it needs a headed check, it says so in its
  report and does the check headless.
- **Headed checks are done only by the lead, one at a time**, through the spike's guard in
  `desktop/spike/scripts` (`windows.Session.wrapper`, `pointer.for_session`; its README's "Window
  session" section), after asking the owner once to put the mouse and the active window on
  `HDMI-A-1`.
- If the guard refuses or raises (`Refused`, `WrongOutput`), or does not work, stop that headed
  step; do not retry in a loop and do not open the window another way.

### Rule 7: safety

- Every server or app an agent starts uses isolated data, config and cache folders in a temp
  directory (`vk-run.sh` does it for the app; a test uses `reframe_testing.folders_guard` and the
  `reframe_testing` server harness), `REFRAME_POWER_DRY_RUN=1`, and media and output folders
  inside the temp directory. Never use the owner's real data directory (it may hold a real
  `server.json`), and never a `when_done` of `sleep` or `shutdown` without the dry-run flag. A
  Rust test that writes files writes them in a temp folder it removes.
- Your own port range (above). `kill` only processes you started, by pid (never `pkill -f` or a
  pattern that matches your own shell).
- Disk space is limited: one shared `CARGO_TARGET_DIR`, at most 4 worktrees at once, no copy of
  `target/`. Run the full Python suite only when the lead says so; while agents run, run only
  static checks and targeted tests.
- Merge conflicts are almost always adjacent rows of `docs/status.md`: resolve per row against the
  merge base.

### Test rules

A test is meaningful only if it fails when the code has a defect that a user would see. Before you
write a test, name that defect in one sentence. If you cannot name one, do not write the test.

- Write tests for: what your "Done when" requires; each command's and store action's contract (the
  request it sends, the state after the answer, every expected failure); process lifetime (the
  ready line, a crash, a timeout, the restart limit, the kill after 5 s); event handling,
  ordering, reconnect; every branch you wrote, one case per branch.
- Do not write tests of Tauri, Vue, Pinia, PrimeVue, vue-i18n, tokio or the browser themselves;
  snapshot tests of whole components; tests that a mock returned what the test told it to; tests
  of the skeleton's stubs or of test helpers.
- Mutation check before you report: for each test file, break the code it tests on purpose at
  least once per test function (drop the timeout, invert a condition, skip the restart count, kill
  at once). The test must fail, then pass again when you restore the code (`touch` a restored
  Python file). A test that still passes is wrong: fix it or delete it.
- In the report: the tests per file, the mutations and their results.

## Every agent prompt includes

- The task, its step, the plan sections to read, the owned and forbidden files, the contracts it
  builds and the ones it uses, its "Done when" word for word, its section of 0069, rules 5, 6 and
  7 and the test rules word for word, its port range, its virtual-session socket name.
- Setup: the worktree starts at `main`: first `git merge --ff-only m5-desktop-shell`. Then
  `uv sync`, `npm ci` in `frontend/` and in `desktop/`, `npm run build:desktop` in `frontend/`,
  and `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`;
  `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not installed. `CARGO_TARGET_DIR` as above.
- Commits per step, step ID first (`D-3: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Stage files by name.
  Update only its own `docs/status.md` row and its own 0069 section.
- Scratch files: each agent keeps its scratch files (logs, ready lines, scripts, screenshots, the
  binary copy) in its own `scratchpad/task-<x>/` and reads a server's URL and token only from a
  server it started itself.
- The report starts with the agent's model ID; then the real output of every command it ran for
  rule 5 (the last lines), what it saw in its screenshots, the test rules' checks, every deviation
  from the plan and from this file, every file touched outside its list, what it chose not to
  build, and what later tasks need.

### Simple code (the owner's rule, word for word in each brief)

- Build what the plan says and nothing more: no extra options, settings, modes or "might need
  later" hooks. Smallest change that makes the "Done when" lines pass.
- Look before you write: reuse the existing components, stores, API layer and helpers, and the
  spike's Rust (`desktop/spike/src-tauri/src/sidecar.rs`: the death signal, the ready line, the
  shutdown request, the private folder) and Python (`desktop/spike/scripts/`). Match the code
  around yours: naming, structure, comment density.
- Plain functions and plain modules. No new abstraction layer, trait hierarchy, plugin point or
  generic utility for one caller (a trait for the Windows Job Object's mock is the exception the
  plan asks for). Extract on the third copy, not the second.
- No defensive code for states the types or the server already rule out. Expected failures stay
  data (the project rule).
- No new dependency unless you can say why the platform or an existing dependency cannot do it.
- Tests: one for each "Done when" line and each bug you fix, testing behaviour, not a copy of the
  implementation.
- Simple does not mean less correct. Process cleanup, the quit flow, file safety, i18n and
  keyboard rules stay. If a simpler design than the plan's exists, do not switch quietly: write it
  in your 0069 section and edit the plan in the same commit.
- Load the `code-comments` skill before writing code. A comment says why. No step IDs, plan
  sections or history in code. Remove the stub's `#![allow(dead_code)]` and its "Stub until"
  line when you replace a stub.
- The report says what you chose not to build.

## Progress

| Date | What |
|------|------|
| 2026-11-03 | **Wave 0.** Branch `m5-desktop-shell` from `main` 72eb54a. The lead checked the machine (0069 Context): no Xvfb, weston, cage, WebKitWebDriver or tauri-driver; `kwin_wayland --virtual` in a private D-Bus session works, with `spectacle`, KWin scripts and WebKitGTK's inspector socket as the headless driver. D-1 built: `desktop/src-tauri` (stubs per task, contracts above), the CSP checked in the real webview, `beforeBuildCommand` fixed (it runs in `desktop/`), taskbar progress planned as the app's own `LauncherEntry` signal (libunity is not installed), the CI job `desktop`. Frontend: `Platform.desktop`, the `platform/desktop/` folder, the `/preview/:sourceId` bare route and the `useOpenPaths` mount (each with a test that fails without it). |
| 2026-11-03 | **Merged A** (259ea0d, merge 2a5d936): `desktop/sidecar/build.py` + `sidecar.spec` (one onedir, `reframe-server` and `reframe` share `_internal/`, 98 MB, MediaInfo shipped), the committed placeholder `resources/sidecar/README.md` (a fresh worktree builds), deb/rpm link scripts, the NSIS PATH hook (not run), 14 frozen tests. The lead rebuilt it (47–70 s) and ran the tests: 14 passed; the lead's mutation (no `reframe.presets` data) fails them; restored and rebuilt, 14 pass. Worktree removed. A found that the packages install `Reframe.desktop`, so `DESKTOP_ENTRY` is `Reframe.desktop` (C told) |
| 2026-11-03 | **Merged B** (17b6e07, merge 2275851; `status.md` D-2/D-3 rows resolved): `backend/` (`mod.rs`, `owner.rs`, `sidecar.rs`, `job.rs`, `tests.rs`), `quit.rs`, `main.rs` passes the context to `Backend::start`; deps `getrandom`, `dirs` (Windows). 25 cargo tests, 36 mutations; 8 real checks in the virtual session. Lead: fmt, clippy, 25 tests green; the lead's mutation (no `--owner-only`) fails 4 tests; restored. The lead ran the app with A's frozen sidecar in the virtual session: the sidecar is the app's direct child with `--owner-only`, `backend_info` `owned: true`, a window close sends the shutdown request (204), nothing left. **Finding for every run of a copied binary**: Tauri takes the executable's folder as the resource folder only in a cargo `target/<profile>/` with a `.cargo-lock` (tauri-utils `resource_dir_from`), and the shared `CARGO_TARGET_DIR` is named `reframe-m5-target`: copy the binary and `debug/sidecar/` into `<scratch>/target/debug/` and `touch .cargo-lock` there. Lead fixes: `font: inherit` on buttons (`styles/main.css`, 0001 Consequences, C found it missing), 0069 items 3, 6 and Consequences name `Reframe.desktop`. Worktree removed. **C phase 1 reported** (dbac4c8, 9897d5a, ae68d9e); C resumed for phase 2 |
| 2026-11-03 | **Merged C phase 1** (ae68d9e, merge 7b0a62e) so that wave 2 boots a real page: `platform/desktop/index.ts`, `boot.ts` (backend state, reconfigure), `BackendErrorScreen`, `ReconnectOverlay`, `QuitDialog` + `useQuitFlow`, `progress.rs` (`LauncherEntry.Update` for `application://Reframe.desktop`), `capabilities/main.json` (+ `dialog:allow-message`, `opener:allow-open-url` scoped to the clip links). Lead: lint, format, typecheck, 1889 unit tests, both builds (no Tauri code in `dist/`), fmt, clippy, 29 cargo tests; the lead's mutation (paused jobs not counted at quit) fails 2 tests; restored. C's phase 2 runs in its worktree. **Wave 2 launched**: D (874x), E (877x) |
| 2026-11-03 | **Merged C phase 2** (38710b7, 2899b60, merge 7a0eb93): every phase-2 check passed against B's real sidecar (when-done power actions shown; the quit dialog's Cancel / Escape / Stop jobs and quit; *Reconnecting…* after `kill -9` of the sidecar; the error screen after the restart limit and Retry; a failed start; when-done Quit Reframe; the external owner cancelled through the API and left running); two texts fixed. Not checked: *Keep running in tray* (E's setting). C found that an event sent to `main` also reaches `Any` listeners of other windows (told E). 1889 unit tests on the merged branch. Worktree removed |
| 2026-11-03 | **Merged D** (8465a77, merge 132d73c): `open_paths.rs` (single instance; a second launch's paths made absolute against its folder; flags dropped), `openPaths.ts` (main window only; a name with U+FFFD gets the native question), `useOpenPaths` (after ready, switches to the workspace), `bundle.fileAssociations` (the deb's `MimeType=` read back; GIO/KIO checked in a virtual session; NSIS from the CLI's template). Lead: lint, typecheck, 1899 unit tests, fmt, clippy, 37 cargo tests; the lead's mutation (a second launch's relative paths against `/`) fails 1 test; restored. Worktree removed. D's notes for R1 and the end: two launches at the same moment both start a sidecar before the single-instance check (it works after ~5 s); Tauri's desktop entry has `Exec=reframe-desktop` without `%F` (one process per file from GIO; D-8 `desktopTemplate`); focus of a second launch on real Plasma is a headed check |

## Where M5 ended

(The lead fills it at the end.)
