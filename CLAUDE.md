# Reframe

A HandBrake-style video transcoder: a Python core (`reframe`), a FastAPI + Vue 3 web app, and a
Tauri 2 desktop app. FFmpeg/FFprobe run as subprocesses.

## The plan is the spec

- The plan lives in `docs/plan/`. Start with `docs/plan/README.md`. Milestones are in
  `08-roadmap.md`, core steps in `05-core.md`, the feature spec in `03-features.md`.
- Build what the plan says. A step is done only when its **"Done when"** criteria pass.
- If the plan is wrong or cannot be done, do not quietly change course: write a decision
  record (below) and update the affected plan file **in the same commit**.
- Do not rely on memory for FFmpeg, ffprobe, mkvpropedit, guessit or library behaviour. Check
  it against the real tools and record the result in a test or a decision record.

## Step IDs

| Prefix | Area | Plan file |
|--------|------|-----------|
| `C-x.y` | core package `reframe` | `05-core.md` |
| `S-x.y` | FastAPI server `reframe-server` | `06-web-app.md` (Part A) |
| `F-x.y` | Vue frontend | `06-web-app.md` (Part B) |
| `D-x.y` | Tauri desktop shell | `07-desktop-app.md` |
| `Q-x.y` | quality, CI, release | `09-quality-and-release.md` |

Commit after each step, with the step ID first: `C-5: dimension maths with property tests`.
One branch per milestone (`m0-foundations`, `m1-read-media`, …), merged into `main` when the
milestone demo passes. Never push.

## Commands

Python (from the repository root; uv workspace, Python ≥ 3.13):

```sh
uv sync                                   # install everything (dev group is the default)
uv run ruff check                         # lint
uv run ruff format --check                # format check (uv run ruff format to fix)
uv run mypy                               # strict type check (files listed in pyproject.toml)
uv run mypy --platform win32              # the same, as the Windows CI runner sees it
uv run pytest                             # all tests
uv run pytest -m "not needs_gpu"          # what CI runs
uv run pytest --cov=reframe --cov-report=term-missing  # coverage
uv run python scripts/make-testdata.py    # generate test media into testdata/media/ (git-ignored)
uv run --no-project python scripts/fetch-tools.py   # pinned FFmpeg (tools/ffmpeg.toml) into .tools/, prints its bin dir
uv run python -m reframe.tools            # which ffmpeg/ffprobe/mkvpropedit/mediainfo discovery picks, and why
```

Tests that need real media use the `fixture_media("multitrack")` pytest fixture (generated on
demand) and the `needs_ffmpeg` marker. Fault-injection tests use the `fake_tools` fixture or
`reframe_testing.fake_tools` (a fake ffmpeg/ffprobe driven by a scenario). Shared test
infrastructure lives in `testing/reframe_testing/`; real tool behaviour that tests rely on is
recorded in `testdata/README.md` ("Verified tool behaviour").

Frontend (from `frontend/`):

```sh
npm ci
npm run lint          # oxlint
npm run fmt:check     # oxfmt --check (npm run fmt to fix)
npm run typecheck     # vue-tsc --noEmit (strict templates)
npm test              # vitest run
npm run build:web     # production build (web); build:desktop for the Tauri build
```

All of these must be green before a step is done. CI (`.github/workflows/`) runs the same
commands on Ubuntu and Windows.

## Rules for the code

- Core (`packages/reframe`) never imports FastAPI, Tauri, Vue or any UI code.
- Every subprocess goes through `reframe.tools.run*` (timeout, cancel, output limit, tree kill).
- Expected failures are data (`ValidationIssue`, status enums), not exceptions.
- The command builder is pure (no I/O). Pydantic models in `reframe.models` are the only schema.
- Windows code paths (Job Objects, `CREATE_NO_WINDOW`, `SetThreadExecutionState`) are written
  to the plan and unit-tested with mocks on Linux.
- Never commit generated media. `scripts/make-testdata.py` creates the fixtures. The name
  corpus `testdata/names.toml` and recorded probe JSON in `testdata/probes/` are committed.
- Use current stable dependency versions, pinned in `uv.lock` / `frontend/package-lock.json`.

## Persistence rules

- Persisted documents (settings, presets, job settings in the queue, probe cache) keep unknown
  fields and write them back unchanged (`DocumentModel`, `extra="allow"`).
- A new value in a persisted `Literal`/enum (or a new union `kind`/`mode`) makes older versions
  reject the file: bump `schema_version`, register a migration and add a down-level note
  (`reframe/models/migrations.py`). So do removals and renames.

## Decision records

`docs/decisions/NNNN-short-title.md`, numbered in order. `0001` (desktop shell, `D-0`) and
`0002` (bundled FFmpeg, `D-7`) are reserved by the plan, so new records start at `0003`. See
`docs/decisions/README.md` for the template.
