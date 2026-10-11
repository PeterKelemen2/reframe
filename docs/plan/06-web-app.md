# 06 — Web App (FastAPI + Vue 3)

The web app has two parts:

- **`reframe-server`**: a FastAPI package that exposes the core facade over HTTP and a
  WebSocket.
- **`frontend/`**: a Vue 3 single-page app. The desktop app ([07](07-desktop-app.md)) uses
  **the same frontend**, so every frontend step here also delivers the desktop UI.

---

# Part A — Server (`reframe-server`)

## Shape

```
packages/reframe-server/src/reframe_server/
├── __init__.py
├── app.py              # create_app(config) -> FastAPI ; lifespan creates/closes the Reframe facade
├── config.py           # ServerConfig (pydantic-settings, env prefix REFRAME_)
├── security.py         # auth modes, token/cookie checks, path jail
├── errors.py           # ValidationIssue / problem+json mapping
├── events.py           # WebSocket hub
├── routers/            # system, fs, sources, definitions, languages, presets, jobs, batch, preview, queue, settings
├── static.py           # serves the built frontend (web mode)
└── __main__.py         # `python -m reframe_server` / `reframe-server` entry point (uvicorn, 1 worker)
```

The server holds no editing state ([02 §State model](02-architecture.md#state-model)). Its
routers are thin. Each handler calls one facade method and maps the result.

## S-0 Package skeleton

- [ ] `create_app(config: ServerConfig) -> FastAPI` with a lifespan that runs
      `await Reframe.create(...)` and `await reframe.close()`.
- [ ] `ServerConfig`: `host` (default `127.0.0.1`), `port` (0 = random free port), `mode`
      (`web` | `desktop`), `auth` (`none` | `token` | `password`), `token`, `media_roots`,
      `output_roots`, `static_dir`, `cors_origins`, `config_dir`, `data_dir`.
- [ ] Entry point: start uvicorn with **one worker**. In desktop mode, print one JSON line to
      stdout when ready: `{"event":"ready","port":53817,"token":"…"}`.

Done when: `uv run reframe-server` starts and `GET /api/health` returns version info.

## S-1 Security

- [ ] **Auth modes**:
  - `token` (always used in desktop mode): `Authorization: Bearer <token>`. For `<img>` and
    `<video>` URLs, a short-lived signed query parameter (`?sig=`) is used, because those
    elements cannot send headers. The WebSocket gets the token in its first message.
  - `password` (web, single user): login form → HTTP-only, SameSite=Strict session cookie.
    The password hash is stored in settings (argon2 or scrypt).
  - `none`: allowed only when bound to `127.0.0.1`. A startup warning says so.
- [ ] **Path jail**: every path from the client is resolved (`Path.resolve(strict=False)`, which
      follows symlinks) and must be inside `media_roots` (for reading) or `output_roots` (for
      writing). Web mode enforces this. Desktop mode allows the whole filesystem of the
      current user.
- [ ] CORS: off in web mode (same origin). In desktop mode, allow only the Tauri origins
      (`tauri://localhost`, `http://tauri.localhost`).
- [ ] Security headers on static responses (CSP, `X-Content-Type-Options`, frame-ancestors none).

Done when: tests prove that `../` traversal, symlink escape, absolute paths outside the roots,
and a missing or wrong token are all rejected.

## S-2 REST API

Errors use `application/problem+json`. Long operations return `202 {task_id}`. Their
progress arrives as events.

| Area | Method & path | Purpose |
|------|---------------|---------|
| System | `GET /api/health` | Version, uptime |
| | `GET /api/system` | Tool statuses, versions, platform, mode |
| | `GET /api/system/encoders` · `POST /api/system/encoders/rescan` | Capability statuses, re-detection |
| | `POST /api/system/shutdown` | Graceful shutdown (desktop mode only) |
| Files (web) | `GET /api/fs/roots` · `GET /api/fs/list?path=` | Server-side file browser (media files and folders only) |
| Sources | `POST /api/sources` `{paths}` → 202 | Probe files/folders (task) |
| | `GET /api/sources` · `GET /api/sources/{id}` · `DELETE /api/sources/{id}` | Probed sources |
| | `POST /api/sources/{id}/streams/{index}/bitrate-scan` → 202 | Measure the bitrate |
| | `POST /api/sources/{id}/subtitle-scan` → 202 | Event counts, forced flags |
| Preview | `POST /api/preview/frames` `{source_id, count \| timestamps}` | Frame list (timestamps + URLs) |
| | `GET /api/preview/frames/{key}.png` | Frame image (cached, ETag) |
| | `POST /api/preview/render` `{job, timestamp}` | Output frame with filters → URL |
| | `POST /api/preview/cropdetect` `{source_id}` → 202 | Crop detection per sample |
| | `POST /api/preview/clip` `{job, start, seconds}` → 202 | Encoded preview clip |
| | `GET /api/preview/clips/{id}` | Clip file (HTTP Range support) |
| Definitions | `GET /api/definitions` | Encoders, option schemas, filters, containers (cached, ETag) |
| | `GET /api/languages` | Language list for the picker (cached) |
| Jobs | `POST /api/jobs/draft` `{source_id, preset_id}` | `JobSettings` built from a preset |
| | `POST /api/jobs/validate` `{job}` | `ValidationIssue[]` |
| | `POST /api/jobs/plan` `{job}` | `EncodePlan` (command preview, job type) |
| | `POST /api/jobs/geometry` `{job}` | Pipeline header values |
| Batch | `POST /api/batch/group` `{source_ids, level}` | Groups |
| | `POST /api/batch/derive` `{job, source_id, sections}` | `JobTemplate` from a single-file job |
| | `POST /api/batch/resolve` `{template, source_ids, overrides}` | Resolution matrix + per-file jobs + issues |
| Presets | `GET/POST /api/presets` · `GET/PUT/DELETE /api/presets/{id}` | CRUD |
| | `POST /api/presets/{id}/default` · `POST /api/presets/import` · `GET /api/presets/export` | |
| | `POST /api/presets/diff` `{template, preset_id}` | Changes for the "modified" marker |
| | `POST /api/presets/defaults/preview` `{audio_defaults, subtitle_defaults, source_ids}` | Track decisions with reasons, for the live preview |
| Naming | `POST /api/naming/preview` `{naming, source_ids, job?}` | Name source + reason, parsed fields with positions, rendered output paths, issues. The variable list comes with `GET /api/definitions` |
| Queue | `GET /api/queue` · `POST /api/queue` `{jobs}` | Snapshot, add (server validates again) |
| | `POST /api/queue/{id}/{pause\|resume\|cancel\|retry\|duplicate}` · `DELETE /api/queue/{id}` | Per-job actions |
| | `POST /api/queue/{start\|pause\|stop}` · `PUT /api/queue/order` | Global actions |
| | `GET /api/queue/{id}/log?from=` | Log (incremental) |
| | `PUT /api/queue/when-done` | When-done action |
| Settings | `GET/PUT /api/settings` | App settings |

- [ ] Stable `operationId`s (`sources_probe`, `jobs_validate`, …). The generated client uses
      them as function names.

Done when: an httpx `AsyncClient` test suite covers every route against a facade that runs on
fixture media and a fake FFmpeg.

## S-3 Event WebSocket

- [ ] `WS /api/events`. The client authenticates in its first message and then receives
      events as JSON.
- [ ] **Coalescing**: `job.progress` and `task.progress` are coalesced per id (only the latest
      is kept, max 4 per second). `job.log` lines are batched every 250 ms.
- [ ] Heartbeat ping every 15 s. Each event has a sequence number. After a reconnect, the
      client calls the `GET` snapshots (`/api/queue`, `/api/system/encoders`) to resync.

Done when: a test with a slow consumer shows bounded memory and latest-value delivery.

## S-4 Static frontend and SPA fallback

- [ ] Web mode: serve `frontend/dist` with immutable cache headers for hashed assets, and
      `index.html` for unknown non-API paths.
- [ ] Desktop mode: no static files (Tauri bundles the frontend).

## S-5 OpenAPI → TypeScript

- [ ] `scripts/gen-api.sh`: export `openapi.json` from `create_app()` without starting a server,
      then run `openapi-typescript` → `frontend/src/api/schema.d.ts`.
- [ ] CI check: regenerate and fail on any diff (`Q-2.3`).

## S-6 Deployment

- [ ] **Docker image** (multi-stage):
  1. `node` stage builds `frontend/dist`.
  2. `tools` stage downloads the pinned FFmpeg from `tools/ffmpeg.toml` and checks its
     SHA-256 ([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)).
  3. Runtime stage: Debian slim + uv-installed `reframe-server`, the bundled FFmpeg in
     `/opt/reframe/tools/ffmpeg/`, `mkvtoolnix`, `mediainfo`, and the GPU user-space drivers
     that FFmpeg loads at runtime (Intel media driver, Mesa VA drivers, oneVPL GPU runtime; the
     Dockerfile pins the exact packages). Runs as a non-root user (`PUID`/`PGID` env).
  4. Volumes: `/config`, `/data` (queue DB, logs, cache), `/media` (read), `/output` (write).
  5. `HEALTHCHECK` on `/api/health`.
- [ ] **Override in Docker**: mount your own build and set `REFRAME_FFMPEG` /
      `REFRAME_FFPROBE`, for example `-v /opt/my-ffmpeg:/opt/custom-ffmpeg:ro -e
      REFRAME_FFMPEG=/opt/custom-ffmpeg/bin/ffmpeg`.
- [ ] `docker/compose.example.yml` with variants for Intel/AMD (`/dev/dri`) and NVIDIA
      (`deploy.resources.reservations.devices`), and a commented-out override example.
- [ ] Bare metal: `uv tool install reframe-server`, plus a systemd user unit example. The wheels
      do not contain FFmpeg. `reframe tools fetch` downloads the pinned build from the manifest
      (checksum verified) into the data dir, where it counts as the bundled build. On Windows:
      run from a terminal. A Windows service wrapper comes later.
- [ ] Reverse-proxy notes (WebSocket upgrade headers, body size, timeouts).

Done when: `docker compose up` on a Linux host with an Intel iGPU shows `h264_vaapi`/`h264_qsv` as
available and encodes a fixture file.

---

# Part B — Frontend (`frontend/`, shared by web and desktop)

## Stack

Vue 3.5+ · TypeScript 6 (strict) · Vite · Pinia · Vue Router · oxlint · oxfmt · PrimeVue 4 (styled mode, custom
Aura preset) · Lucide icons · VueUse · vue-i18n · `openapi-fetch` · Vitest · Playwright.

PrimeVue stays on 4 (MIT) with `@primeuix/themes` 2.x, and TypeScript stays on 6 (vue-tsc
needs it). See [decision XXXX](../decisions/XXXX-frontend-held-back-majors.md).

## Structure

```
frontend/src/
├── api/              # schema.d.ts (generated), client.ts, events.ts (WebSocket + reconnect)
├── platform/         # Platform interface + web.ts + desktop.ts (Tauri plugins)
├── stores/           # system, sources, editor, validation, presets, queue, tasks, settings
├── views/            # WorkspaceView, QueueView, PresetsView, ActivityView, SettingsView
├── components/
│   ├── base/         # Field, Section, Card, RoleBadge, CodecLabel, LanguageChip, StatusDot, KeyValue
│   ├── editor/tabs/  # SummaryTab … TagsTab
│   ├── media/        # FrameViewer, CropMagnifier, CropCheckGrid, SplitCompare, TrackTable
│   ├── metadata/     # TrackMetadataEditor, LanguagePicker, FlagToggles, BulkEditDialog
│   ├── video/        # EncoderPicker, QualitySlider, AdvancedOptions, CommandPreview
│   ├── batch/        # GroupBanner, ApplyToGroupDialog, ResolutionMatrix, OverrideDot
│   └── queue/        # QueueTable, JobLog
├── composables/      # useValidation, useGeometry, useShortcuts, useUndo
├── i18n/
└── styles/           # tokens, theme preset
```

## Platform adapter

This is the only place where web and desktop differ:

```ts
export interface Platform {
  kind: 'web' | 'desktop'
  backend(): Promise<{ baseUrl: string; token?: string }>
  pickFiles(opts: { multiple: boolean; filters?: string[] }): Promise<string[]>   // web: server file browser dialog
  pickFolder(opts?: { title?: string }): Promise<string | null>
  pickSavePath(opts: { defaultPath: string }): Promise<string | null>
  onFilesDropped(cb: (paths: string[]) => void): () => void                     // web: no-op
  revealInFolder(path: string): Promise<void> | null                           // web: null (hidden)
  openExternal(target: string): Promise<void>
  notify(title: string, body: string): Promise<void>                           // web: Notification API
  setTaskbarProgress(value: number | null): void                               // web: document.title
}
```

The build selects the implementation with `import.meta.env.VITE_PLATFORM`. The desktop build
imports Tauri plugins only in `desktop.ts`, so the web bundle never contains them.

## Steps

### F-0 Scaffold
- [ ] Vite + Vue + TS + Pinia + Router + PrimeVue + vue-i18n + oxlint + oxfmt + vue-tsc + Vitest.
- [ ] Lint and format:
  - `.oxlintrc.json` with the `typescript`, `vue`, `import`, `unicorn` and `promise` plugins.
    Correctness rules are errors.
  - `.oxfmtrc.json`. Pin the exact oxfmt version, because it is still in beta and its output
    can change between releases.
  - oxlint does not lint `<template>` blocks. vue-tsc with `vueCompilerOptions.strictTemplates`
    checks the templates instead (unknown props, events and components; wrong types).
  - Scripts: `lint` (oxlint), `fmt` / `fmt:check` (oxfmt), `typecheck` (vue-tsc --noEmit).
- [ ] Dev proxy `/api` → `127.0.0.1:8765`. `npm run dev:web` and `npm run build:web|build:desktop`.

Done when: the build passes strict type checks, `oxlint` and `oxfmt --check` in CI. Check
oxfmt's output on a few `.vue` files with templates once before you commit to its settings.

### F-1 Design system
- [ ] Colour, spacing, radius and typography tokens. Light/dark theme plus a "system" option.
      Compact and comfortable density.
- [ ] Base components. `Field` is the key one: label, control slot, inline help (ⓘ popover),
      the validation issue for its `path`, and an override dot (batch). Every editor control
      uses `Field`.
- [ ] `RoleBadge` (solid = flag, outlined = heuristic, tooltip = evidence), `CodecLabel`
      (commercial name + raw codec in the tooltip), `LanguageChip`.

Done when: a component sandbox page (dev only) shows every base component in both themes.

### F-2 API layer and events
- [ ] Typed client from `schema.d.ts`. Auth header or cookie. Problem+json → toast.
- [ ] WebSocket client: reconnect with backoff, resync snapshots, dispatch events to stores.

### F-3 App shell
- [ ] Navigation rail, workspace layout (sources | tabs | preview), status bar, keyboard
      shortcuts, theme switch, toasts, a first-run screen when FFmpeg is missing.

### F-4 Editor state
- [ ] `editor` store: an **EditorTarget** is either a single `JobSettings` or a group
      (`JobTemplate` + overrides). The tabs use one API for both.
- [ ] Undo/redo as JSON patch history (Ctrl+Z / Ctrl+Shift+Z).
- [ ] `useValidation`: debounced (250 ms) `jobs/validate`. Issues are indexed by path for `Field`.
- [ ] "Modified vs preset" uses `presets/diff`.

### F-5 Sources panel and opening files
- [ ] Web: a server file-browser dialog (roots, breadcrumbs, media filter, multi-select).
- [ ] Desktop: native dialogs and drag-and-drop through `Platform`.
- [ ] Probe progress, warnings, batch groups (collapsible), near-match markers.

### F-6 Summary tab
- [ ] The cards from [03 §Summary](03-features.md#summary). Chips and issues link to fields.

### F-7 Dimensions tab, preview panel, crop magnifier
- [ ] Pipeline header from `jobs/geometry`.
- [ ] `FrameViewer`: fit/100 %/200 %, frame strip, timestamp seek, crop overlay with drag handles.
- [ ] `CropMagnifier`: canvas-based. It loads the full-resolution PNG and draws 4 edge strips at
      2×/4×/8× with `imageSmoothingEnabled = false`, a removed-area tint, the crop lines, and a
      cursor loupe.
- [ ] `CropCheckGrid`: every sample with the overlay. A Web Worker computes the luma variance
      of the removed band and puts a warning badge on frames that lose content.

### F-8 Filters tab
- [ ] Filter list (toggle + preset + tune), help panel from the definitions, `SplitCompare`
      before/after on the current frame (`preview/render`).
- [ ] Colorspace source-colour box and the "what will happen" sentence.

### F-9 Video tab and advanced options
- [ ] `EncoderPicker` grouped by family, with status dots and reasons. The
      missing-encoder banner shows the fix buttons from the validation issue.
- [ ] `QualitySlider` with the recommended band. Rate-control switch.
- [ ] `AdvancedOptions` is generated from the option schema: categories, search, "show only
      changed", reset, placeholders for defaults, help popovers, "copy HDR metadata".
- [ ] `CommandPreview` drawer (`jobs/plan`), a light syntax highlighter, copy button.

### F-10 Audio and subtitles tabs
- [ ] `TrackTable` (source, read-only) with expandable details, role badges, and a "Measure"
      button for unknown bitrates.
- [ ] Output track editors with drag reorder, action, encoder settings, `TrackMetadataEditor`.
- [ ] `LanguagePicker`: search dialog, favourites on top, a preview of how it is written
      (`hun · hu`).
- [ ] Bulk edit for selected tracks. External subtitle import (file picker through `Platform`).
- [ ] **Defaults dialog** (audio and subtitles), opened from the tab and from the preset editor:
      selection settings, a codec-rule table (drag to reorder, the catch-all row is locked,
      expandable rows for optional settings), passthru check boxes, fallback encoder, and the
      **live preview** table (`presets/defaults/preview`, debounced). In a batch group, the preview
      covers every file.

### F-11 Chapters and tags tabs
- [ ] Chapter table with inline name edits, import/export, generate. Tag form with templates.

### F-12 Presets UI
- [ ] Preset drawer: tree by category, built-in lock, CRUD, default star, import/export,
      "modified" marker with a diff popover.

### F-13 Batch UI
- [ ] Group rows in the sources panel. **Edit group** mode with banner and representative-file
      switcher.
- [ ] `ApplyToGroupDialog` (section checkboxes). Copy/paste sections from the context menu.
- [ ] `ResolutionMatrix`: virtualised table with ✓/≈/✗ cells, a candidate picker per cell, a
      "problems only" filter, and an editable naming column.
- [ ] Override dots on `Field` with **Reset to group** and **Apply to whole group**.
- [ ] Queue-group flow with the error dialog.

### F-14 Queue and activity
- [ ] Queue table: drag reorder, live progress, per-job and global controls, edit-back,
      reveal in folder (desktop), when-done selector.
- [ ] Job log viewer (virtual scroll, follow mode, copy all). Global activity log.

### F-15 Settings view
- [ ] The sections from [03 §Settings](03-features.md#settings). The encoder table has a re-scan
      button. Tool paths have a **Test** button.

### F-16 i18n and accessibility
- [ ] All strings go through vue-i18n (English first). Full keyboard paths. Visible focus.
      WCAG AA contrast in both themes. Respect `prefers-reduced-motion`.

### F-17 End-to-end tests
- [ ] Playwright against `reframe-server` with fixture media and fake FFmpeg:
  1. Open a file → set an audio language and commentary flag → queue → done → re-probe shows
     the flags.
  2. Open a season folder → edit group → check the matrix → queue the group.
  3. A preset with an unavailable encoder → banner → use the fallback → queue.
  4. Manual crop → magnifier shows the crop lines → the command contains the matching
     `crop=` filter.

### F-18 Naming editor
- [ ] Template field with `{` autocomplete and variable chips (current values, click to insert).
- [ ] **Parsed name** panel: name source + reason, coloured spans over the original name,
      editable fields (per-file override).
- [ ] Live preview (`naming/preview`, debounced). Used in Settings → Output, the preset editor,
      the Summary Output card, and the batch matrix naming column.
