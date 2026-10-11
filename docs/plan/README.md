# Reframe — Implementation Plan

Reframe is a video transcoder in the spirit of HandBrake. It keeps HandBrake's workflow and
presets. It adds better track information, mkvtoolnix-style track metadata editing, season-wide
batch editing, a crop preview with zoom, and StaxRip-level encoder options.

This folder holds the plan. Each file covers one part. What is already built is tracked in
[../status.md](../status.md). Read the plan files in this order:

| # | File | What it covers |
|---|------|----------------|
| 1 | [01-scope.md](01-scope.md) | Goals, non-goals, target platforms, v1 boundary, open questions |
| 2 | [02-architecture.md](02-architecture.md) | Repository layout, tech stack, how the parts talk to each other, key decisions |
| 3 | [03-features.md](03-features.md) | Feature spec for every tab (Summary → Tags), presets, queue, preview |
| 4 | [04-batch-mode.md](04-batch-mode.md) | Season / batch editing: grouping, track rules, apply-to-all |
| 5 | [05-core.md](05-core.md) | The `reframe` Python core package, step by step |
| 6 | [06-web-app.md](06-web-app.md) | FastAPI server and the Vue 3 frontend, step by step |
| 7 | [07-desktop-app.md](07-desktop-app.md) | Desktop shell (Tauri 2) for Linux and Windows, step by step |
| 8 | [08-roadmap.md](08-roadmap.md) | Milestones that put the steps from 5–7 in order, with "done when" criteria |
| 9 | [09-quality-and-release.md](09-quality-and-release.md) | Testing, CI, packaging, licensing |

## Decisions at a glance

| Topic | Decision | Where |
|-------|----------|-------|
| Encoding backend | FFmpeg/FFprobe as subprocesses. MKVToolNix (`mkvpropedit`) is optional, for metadata-only edits | [02](02-architecture.md#encoding-backend) |
| FFmpeg distribution | The same pinned build is bundled in every artefact (Docker, Linux, Windows). The path to each tool can be overridden (env var or Settings) | [02](02-architecture.md#bundled-ffmpeg) |
| Core | One Python package, `reframe`. It has no UI or web imports, is async, and uses Pydantic v2 models | [05](05-core.md) |
| Web | FastAPI + WebSocket events, Vue 3 + TypeScript + Vite + Pinia + PrimeVue | [06](06-web-app.md) |
| Desktop | Tauri 2 shell. It reuses the same Vue frontend and runs the Python server as a sidecar process | [07](07-desktop-app.md#decision-tauri-2) |
| Shared contract | Pydantic models → OpenAPI → generated TypeScript types | [02](02-architecture.md#one-contract) |
| Editing state | Lives in the client. The server only validates, resolves and builds commands. The queue lives on the server | [02](02-architecture.md#state-model) |

## Step IDs

Every implementation step has an ID, so the roadmap and issues can refer to it:

- `C-x.y`: core package ([05-core.md](05-core.md))
- `S-x.y`: FastAPI server ([06-web-app.md](06-web-app.md))
- `F-x.y`: Vue frontend ([06-web-app.md](06-web-app.md))
- `D-x.y`: desktop shell ([07-desktop-app.md](07-desktop-app.md))
- `Q-x.y`: quality, CI, release ([09-quality-and-release.md](09-quality-and-release.md))

Each step has a "Done when" line. A step is done only when its tests pass.
