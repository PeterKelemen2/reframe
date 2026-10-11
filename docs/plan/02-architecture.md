# 02 — Architecture

## Overview

```
                ┌───────────────────────────── frontend/ (Vue 3, one codebase) ─────────────────────────────┐
                │  views · tabs · stores (Pinia) · generated API client · platform adapter (web | desktop)  │
                └───────────────▲───────────────────────────────────────────────────────▲───────────────────┘
                                │ HTTP + WebSocket                                      │ HTTP + WebSocket (127.0.0.1)
                    ┌───────────┴───────────┐                               ┌───────────┴──────────────┐
  Web deployment →  │ reframe-server        │      Desktop deployment →     │ Tauri 2 shell (Rust)     │
  (Docker / bare)   │ FastAPI, uvicorn      │                               │  ├─ webview (same Vue UI)│
                    │                       │                               │  └─ sidecar: reframe-    │
                    └───────────┬───────────┘                               │     server (frozen)      │
                                │ in-process calls                          └───────────┬──────────────┘
                    ┌───────────┴─────────────────────────────────────────────────────────┴───────────┐
                    │ reframe (core package): probe · capabilities · dimensions · filters · encoders  │
                    │ command builder · validation · preview · presets · batch · queue · metadata     │
                    └───────────┬─────────────────────────────────────────────────────────────────────┘
                                │ subprocess (asyncio)
                      ffprobe · ffmpeg · mkvpropedit (optional) · mediainfo (optional)
```

The core is the product. The server is a thin transport layer. The frontend is the only UI
codebase, and both deployments ship it.

## Repository layout

```
reframe/
├── pyproject.toml                # uv workspace root (dev tools, shared ruff/mypy config)
├── uv.lock
├── packages/
│   ├── reframe/                  # CORE — import name: reframe
│   │   ├── pyproject.toml
│   │   ├── src/reframe/
│   │   └── tests/
│   └── reframe-server/           # FastAPI app — import name: reframe_server
│       ├── pyproject.toml
│       ├── src/reframe_server/
│       └── tests/
├── frontend/                     # Vue 3 + TS + Vite (shared by web and desktop)
│   ├── package.json
│   └── src/
├── desktop/                      # Tauri 2 project
│   ├── src-tauri/
│   └── sidecar/                  # PyInstaller spec + build script for reframe-server
├── docker/                       # Dockerfile, compose example
├── tools/                        # ffmpeg.toml: pinned FFmpeg version, URLs and SHA-256 per platform
├── scripts/                      # dev helpers (generate API types, make test media, …)
├── testing/                      # shared test infrastructure (`reframe_testing`): fake FFmpeg, fixture helpers
├── testdata/                     # small generated fixtures (git-ignored large ones)
└── docs/
    └── plan/                     # this folder
```

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Python | ≥ 3.13, managed with **uv** (workspace) | One lock file for core and server. Fast CI |
| Models | **Pydantic v2** | Validation, JSON (de)serialisation, JSON Schema for the frontend |
| Async | `asyncio` subprocesses, `anyio` in tests | FastAPI is async. Encodes are long-running child processes |
| Process control | `psutil` | Cross-platform suspend/resume (pause), tree kill, parent-death watch |
| Paths | `platformdirs` | Config/data/cache dirs on Linux and Windows |
| Languages | `langcodes` (+ `language_data`) | BCP 47 parsing, display names, ISO 639-2/B conversion for Matroska |
| Release-name parsing | `guessit` (LGPL-3.0) | Title, year, season/episode, episode title and release tags from file and folder names, with their positions, for [output naming](03-features.md#output-naming) |
| Storage | JSON files (presets, settings) + SQLite (queue, history) | Presets stay portable. The queue needs safe updates |
| Server | **FastAPI** + uvicorn, WebSocket for events | Async, OpenAPI out of the box |
| Frontend | **Vue 3.5+**, TypeScript 6, Vite, Pinia, Vue Router | As requested. TypeScript 6, not 7: vue-tsc does not run on TypeScript 7 yet ([decision 0003](../decisions/0003-frontend-held-back-majors.md)) |
| UI kit | **PrimeVue 4** (styled mode, custom Aura tokens) + Lucide icons | Rich DataTable, TreeTable, Slider, InputNumber, Tabs. Light/dark theming. PrimeVue 4 is MIT. PrimeVue 5 has a proprietary licence with a licence key, so Reframe does not use it ([decision 0003](../decisions/0003-frontend-held-back-majors.md)) |
| API client | `openapi-typescript` + `openapi-fetch` | Types generated from the server's OpenAPI. No hand-written DTOs |
| Desktop | **Tauri 2** | Modern webview UI, small bundles, native dialogs and drag-and-drop with real paths |
| Lint / format / types | ruff, mypy (strict on core), **oxlint**, **oxfmt**, vue-tsc | oxlint and oxfmt are fast Rust tools with one config each. oxlint checks only `<script>` in `.vue` files, so vue-tsc (strict templates) checks the templates |
| Tests | pytest, hypothesis, syrupy (snapshots), Vitest, Playwright | See [09](09-quality-and-release.md) |

## Encoding backend

**FFmpeg and FFprobe**, called as subprocesses.

- `ffprobe -show_format -show_streams -show_chapters -of json` reads the source.
- `ffmpeg` encodes. It also extracts preview frames, runs crop detection and renders preview
  clips.
- `ffmpeg -progress pipe:1 -nostats` reports progress in a machine-readable format.
- `mkvpropedit` (optional) edits Matroska metadata in place, with no remux. Reframe uses it when
  the user changes only track names, languages or flags. It also sets fields that FFmpeg's
  Matroska muxer cannot write (for example BCP 47 `LanguageIETF`).
- `mediainfo` (optional, through `pymediainfo`) adds detail when FFprobe has none (for
  example the bitrate of lossless audio in files without statistics tags).

Why not HandBrakeCLI as the backend? It hides the knobs this project needs to expose:
per-stream metadata flags, arbitrary encoder parameters, FFmpeg filters such as `libplacebo`
tone mapping, and remux-only jobs. FFmpeg covers all of them, and its CLI is stable.

### Bundled FFmpeg

**Every build ships the same pinned FFmpeg**: the Docker image, the Linux packages (AppImage,
.deb, .rpm) and the Windows installer. Users get a known-good FFmpeg on every target, and every
build behaves the same.

- **One manifest**, `tools/ffmpeg.toml`, pins the version, the download URL and the SHA-256
  for each platform (`linux-x64`, `windows-x64`). CI uses it for the tests and for every
  package, so the tests run against the exact binaries that ship (`Q-1.2`).
- **Build requirements**: GPL build from an upstream release branch. It must include libx264,
  libx265, libsvtav1, libopus, libplacebo + Vulkan, libvpl (QSV), NVENC, AMF (Windows) and
  VAAPI (Linux), and it must run on the oldest supported distro. The first candidate is the
  BtbN release-branch GPL build, shared-library variant, so `ffmpeg` and `ffprobe` share one
  set of libraries. `D-7` confirms the choice.
- **Install location**: `<app>/tools/ffmpeg/` (Windows, AppImage), `/usr/lib/reframe/tools/ffmpeg/`
  (.deb/.rpm, so it does not conflict with the distro's `ffmpeg` package),
  `/opt/reframe/tools/ffmpeg/` (Docker).

**Path override.** Each tool path is resolved in this order:

| # | Source | Typical use |
|---|--------|-------------|
| 1 | Environment variable: `REFRAME_FFMPEG`, `REFRAME_FFPROBE` (also `REFRAME_MKVPROPEDIT`, `REFRAME_MEDIAINFO`) | Docker, scripts, CI. Settings shows the value read-only, with a note that the environment sets it |
| 2 | Path in **Settings → Tools** | Desktop users with their own FFmpeg build |
| 3 | Bundled build | Default |
| 4 | `PATH` | Only when no bundled build exists (for example when running from source) |

- If only `ffmpeg` is overridden, Reframe looks for `ffprobe` next to it first, so pointing
  to a custom build folder is enough.
- An override that is missing, broken or too old is **never** replaced by the bundled build
  without telling the user. The tool status shows the reason, and a **Use bundled FFmpeg**
  fix is offered.
- Changing the path triggers a new encoder detection (the capability cache key includes the
  binary, see `C-4`).

## One contract

The Pydantic models in `reframe.models` are the only schema definition:

```
reframe.models (Pydantic) ──► FastAPI OpenAPI schema ──► openapi-typescript ──► frontend/src/api/schema.d.ts
                         └──► JSON files on disk (presets, settings) with a schema_version field
```

`scripts/gen-api.sh` regenerates the TypeScript types. CI fails if the generated file is
out of date (see `Q-2.3`).

## State model

| State | Owner | Lifetime |
|-------|-------|----------|
| Probed sources (`MediaSource`) | Core cache, keyed by path + size + mtime | Process lifetime + disk cache |
| Encoder capabilities | Core, detected in the background at start | Cached on disk, keyed by FFmpeg binary hash and GPU/driver fingerprint |
| **Job being edited** (`JobSettings`) | **Client** (Pinia store) | Until the user queues it or discards it |
| Batch group template + overrides | **Client** | Same |
| Presets | Core, JSON files in the config dir | Persistent |
| Queue + job history + logs | Core, SQLite + log files | Persistent, restored at start |
| App settings | Core, JSON file | Persistent |

Editing is **stateless on the server**. The client sends the full `JobSettings` (or batch
template) to helper endpoints: `validate`, `resolve`, `command`, `preview`. This keeps the
server simple, makes undo/redo a pure client feature, and works the same in web and desktop.

## Events

The core has an async **event bus**. The server forwards it over one WebSocket
(`/api/events`). Event types:

| Event | Payload | Emitted by |
|-------|---------|------------|
| `capabilities.changed` | encoder statuses | Encoder detection |
| `task.progress` / `task.done` | generic background task (probe folder, crop scan, bitrate scan) | Core task runner |
| `job.state` | job id, new state, error | Queue |
| `job.progress` | percent, fps, speed, eta, output size | Queue |
| `job.log` | log lines (batched, rate-limited) | Queue |
| `queue.changed` | order / membership | Queue |

Every long operation is a **task** with an id. The task can be cancelled and reports
progress. The API returns the task id at once and never waits for the result.

## Cross-cutting rules

1. **Never block.** Every subprocess call goes through one helper (`reframe.tools.run`).
   That helper has a timeout, cancellation and output limits. Hardware encoder tests have a
   short timeout (10 s default).
2. **Expected failures are data, not exceptions.** A missing encoder, an unsupported codec
   in a container, or a subtitle that cannot be burned in each become a `ValidationIssue`
   with a severity, a field path, a message and optional fix actions.
3. **The command builder is pure.** `build_command(job, source, capabilities) -> Command`
   has no I/O. Snapshot tests cover it.
4. **Versioned persistence.** Every JSON file has `schema_version`. Loaders run migrations.
   Unknown fields are kept, not dropped, to protect newer files.
5. **Core API is a facade.** UIs talk to the `Reframe` service object (see
   [05-core.md §C-15](05-core.md#c-15-service-facade-and-cli)), not to the internal modules.
6. **The server runs one worker process.** Queue state lives in that process. Uvicorn must not
   run with multiple workers.
