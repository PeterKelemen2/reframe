# Implementation status

Last updated: 2026-10-13. Milestone M2 is in progress on branch `m2-encode-cli`
([task breakdown](m2-breakdown.md)).

This file says which parts of the plan (`docs/plan/`) are built. Update it in the same commit
as each step that lands.

Status values:

- **Done**: every bullet of the step is built, and its "Done when" criteria pass on Linux.
- **Partial**: some bullets are built. The notes say what is missing.
- **Not started**: no code yet. Many of these steps already have their Pydantic models in
  `reframe.models` (C-2), but no behaviour.

Nothing has run on Windows or on GitHub Actions yet: the branches were never pushed. See
[Not verified](#not-verified).

## Milestones

| Milestone | Status | Notes |
|-----------|--------|-------|
| M0 Foundations | **Done** | Merged into `main`. Every CI step passes when run locally on Linux |
| M1 Read media | **Done** | Merged into `main`. Demo: `reframe probe FILE [--json]` |
| M2 Encode from the CLI | **In progress** | Branch `m2-encode-cli` ([m2-breakdown.md](m2-breakdown.md)). Wave 1 (C-4, C-5, C-6, C-14, C-16) is merged; wave 2 (C-7, C-8, C-9, C-12 codec rules) is next |
| M3 – M10 | Not started | |

## Steps

### Core (`reframe`, 05-core.md)

| Step | Status | Notes |
|------|--------|-------|
| C-0 Project skeleton | **Done** | uv workspace, strict mypy, ruff, pytest markers (`slow`, `needs_ffmpeg`, `needs_gpu`, `benchmark`) |
| C-1 Tool runner and discovery | **Done** | `reframe.tools`: `run` / `run_streaming` (timeout, cancel, output limit, process-tree kill), discovery env → Settings → bundled → `PATH`, version parsing (minimum FFmpeg 7.0), child safety (Linux `PR_SET_PDEATHSIG`; Windows Job Object, [0005](decisions/0005-tool-discovery-details.md)). Windows code is tested with mocks only. `LIBVA_DRIVERS_PATH` handling stays until D-7 decides |
| C-2 Data models | **Done** | All public models with JSON Schema snapshots and round-trip property tests. Known gaps: no `FieldChange` model (C-9 adds it), no language-list model for `GET /api/languages` (S-2), `-show_programs` output is not modelled |
| C-3 Probe and track analysis | **Done** | `reframe.probe`: commercial codec names, bitrate chain with its source, role heuristics with evidence, HDR10 / HDR10+ / HLG / Dolby Vision, VFR, interlacing, `delay`, probe cache, folder probe as a task. Decisions [0006](decisions/0006-probe-recordings-and-roles.md) and [0007](decisions/0007-probe-mediainfo-library-and-delay.md). `language_ietf` is filled only when MediaInfo is available |
| C-4 Encoder capabilities | **Done** (branch `m2-encode-cli`) | `reframe.capabilities`: `CapabilityService` (`Reframe.capabilities`: cached result at once, full detection in the background, `capabilities.changed`, re-scan, a new ffmpeg starts a new detection), `-encoders` / `-filters` / `-h encoder=` parsing, hardware test encodes (3 at a time, 10 s, 10-bit test), VAAPI on every render node with the node in `EncoderStatus.device` or the node forced by `encoders.vaapi_device` ([0020](decisions/0020-m2-wave-1-product-decisions.md)), the `libplacebo` run test (`CapabilitySnapshot.usable_filter`), reason mapping of the real FFmpeg texts, cache keyed by binary + GPU fingerprint + settings + render nodes, `closest_available` (video and audio chains: `libfdk_aac → aac`, 0020), `encoder_issues` (`encoder.unknown` / `checking` / `untested` / `unavailable`) for C-8. Decision [0008](decisions/0008-encoder-detection-reasons-and-filters.md). Checked on one Linux machine (AMD: VAAPI on its one render node, AMF and libplacebo work; NVENC and QSV only as failures; several render nodes only with the fake ffmpeg); the Windows registry fingerprint is tested with mocks only |
| C-5 Dimensions maths | **Done** (branch `m2-encode-cli`) | `reframe.dimensions`: `compute_geometry` (crop snapped to the chroma grid, rotation, the four size modes, square / keep / custom pixel aspect, a fit box that turns for portrait output, modulus rounding within 0.5 % or 1 px, notes), `detect_crop_consensus` (auto, conservative), `source_geometry`, `rotate_crop`. Hypothesis properties of "Done when", table tests of the classic cases, and real-FFmpeg tests (crop grid of all 200 pixel formats, the filter chain for C-7 on the anamorphic, letterbox and rotated files). Conventions and corner cases: [0009](decisions/0009-dimension-maths-conventions.md); portrait fit: [0020](decisions/0020-m2-wave-1-product-decisions.md) |
| C-6 Definitions | **Partial** (M2 part done) | **Done:** `reframe.languages` (search, normalisation, ISO 639-2/B for Matroska, ISO 639-2/T for MP4, display names). **Branch `m2-encode-cli`:** `reframe.definitions` with every video encoder (rate control with ranges, args and the quality conversion table, presets, tunes, profiles, levels, 2-pass, the `EncoderOption` schema with the basic option sets for x264, x265, SVT-AV1, NVENC, QSV, AMF, VAAPI and the x264 / x265 per-preset default tables), audio encoders (bitrates per mixdown, fixed steps, sample rates, VBR quality, passthru codecs, mixdowns, the fallback chain `libfdk_aac → aac` of [0020](decisions/0020-m2-wave-1-product-decisions.md)), containers (copy / encode codecs, flags, chapters, attachments, tags, `+faststart`), filters (implementations with their own HandBrake-mapped presets and tunes, chosen by the new `FilterConfig.implementation`; help, fixed order), `convert_quality`, `supported_options`, `lint_definitions`. Checked against FFmpeg n9.0.2 (both builds) and AMF / VAAPI hardware ([0010](decisions/0010-definitions-filters-and-containers.md)). **Not started (M9):** the complete option sets of 03 §Advanced (analysis, colour, performance options, VP9 options). **Not verified:** NVENC and QSV on hardware; QSV levels are not offered |
| C-7 Command builder | **Done** (branch `m2-encode-cli`) | `reframe.command`: `build_plan` (pure; `PlanError` for jobs that skipped validation), `job_type` (`encode` / `remux` with the reason). Argument order of 05 with an output `-t`, decoder options, `-map_metadata:s -1` and `-f`; the fixed filter order with colour tagging, HDR metadata removed after tone mapping (`libplacebo` only when its run test passed, else `zscale,tonemap`), hardware init and upload tail (VAAPI render node from the status), text burn-in on the final picture (time-shifted for ranges) and bitmap `overlay` after the crop; every encoder's rate control, choices, advanced options, custom params, HDR10 params (x265, SVT-AV1), 2-pass (`EncodePlan.temp_files`), frame rate; audio passthru with fallback, output layout (`5.1(side)` → `5.1` for Opus), sample rate, default bitrates, DRC, gain, two-pass loudnorm (one analyse step per track); subtitles copy / convert / burn, external files; languages in the container's form plus an `mkvpropedit` step for BCP 47, all six flags; chapters (copy, FFMETADATA for renamed or generated), tags with naming variables; display for POSIX and Windows. 68 plan snapshots, 31 integration tests on real FFmpeg (both n9.0.2 builds; VAAPI and AMF as `needs_gpu`). Decision [0013](decisions/0013-command-builder-details.md). Not verified: NVENC, QSV (no hardware), Windows |
| C-8 Validation | Not started | Models only (`ValidationIssue`, `Fix`). `reframe.jsonpatch` (RFC 6902, for fixes) is done |
| C-9 Presets and settings stores | Not started | Models only (`Preset`, `AppSettings`, migrations registry). The facade uses `AppSettings()` defaults |
| C-10 Preview and analysis tasks | **Partial** | **Done:** the background task manager `reframe.tasks` (id, progress, cancel, limit per kind). **Not started:** frames, crop detection, preview clips, bitrate and subtitle scans, loudness measurement |
| C-11 Queue and job runner | Not started | Models only (`QueueJob`, `JobState`, `JobProgress`). The event bus `reframe.events` is done |
| C-12 Batch engine | Not started | Models only (`TrackSelector`, `OutputTrackRule`, `AudioDefaults`, …) |
| C-13 Metadata edit and remux | Not started | The language-tag behaviour of FFmpeg and mkvpropedit is verified and recorded (`testdata/README.md`) |
| C-14 Platform services | **Partial** | **Branch `m2-encode-cli` only:** sleep inhibit for automatic sleep only, `reframe.platform.sleep` (counted `SleepInhibitor`; Linux: the desktop session's inhibit, `org.freedesktop.PowerManagement.Inhibit` or the XDG portal, plus a logind `idle` lock where needed, through a stdlib D-Bus client, checked on KDE; GNOME not tested; Windows `SetThreadExecutionState` on one dedicated thread, mock-tested only; `sleep_inhibit.unavailable` warning), [0011](decisions/0011-sleep-inhibit.md), [0020](decisions/0020-m2-wave-1-product-decisions.md). **Not started:** power actions, the notification hook. (`reframe.platform` also has child-process safety from C-1 and `launch_detached` for user-facing programs) |
| C-15 Service facade and CLI | **Partial** | **Done:** `Reframe.create()` / `close()` with `tools`, `sources`, `tasks` and `events`; CLI `reframe probe FILE [--json]` and `reframe version`; `python -m reframe.tools` (tool status). **Not started:** the capabilities, presets, jobs, batch, queue and settings services; CLI `encoders`, `tools status\|fetch`, `name`, `presets`, `plan`, `encode`, `batch` |
| C-16 Output naming | **Done** (branch `m2-encode-cli`) | `reframe.naming`: `resolve_output_name` (name source Auto / File / Folder with generic-folder skipping, season packs and scores; guessit parsing that keeps the original text and positions; templates with format specs, `<…>` groups, `/` subfolders, `{{ }}`; the 17 HandBrake variables and the Reframe ones; word separator and HandBrake clean-up; Windows-safe names on every OS; MP4/M4V rule; the job's manual name, template, name source and per-file `field_overrides`) and `check_template` (syntax, unknown variables with "did you mean" fixes, format specs). Models `NameResult`, `NameCandidate`, `ParsedName`, `NameSpan`, `NamingVariable`. Name corpus `testdata/names.toml`: 146 real-world cases. Decision [0012](decisions/0012-output-naming-rules.md). Collisions are C-8 / C-11; the `reframe name` command is C-15 |

### Server (`reframe-server`, 06-web-app.md Part A)

| Step | Status | Notes |
|------|--------|-------|
| S-0 … S-6 | Not started | Only the empty package from C-0 exists |

### Frontend (`frontend/`, 06-web-app.md Part B)

| Step | Status | Notes |
|------|--------|-------|
| F-0 Scaffold | **Done** | Vue 3.5, Vite, Pinia, Router, PrimeVue 4, vue-i18n, oxlint, oxfmt, vue-tsc (strict templates), Vitest, the `Platform` interface. PrimeVue 4 and TypeScript 6 are held back on purpose ([0003](decisions/0003-frontend-held-back-majors.md)) |
| F-1 … F-18 | Not started | |

### Desktop (`desktop/`, 07-desktop-app.md)

| Step | Status | Notes |
|------|--------|-------|
| D-0 … D-9 | Not started | `docs/decisions/0001-desktop-shell.md` and `0002-bundled-ffmpeg.md` are still to be written (D-0, D-7) |

### Quality and release (09-quality-and-release.md)

| Step | Status | Notes |
|------|--------|-------|
| Q-1.1 CI matrix | **Done, never run** | `.github/workflows/ci.yml`: Python (Ubuntu + Windows, plus Python 3.13 on Ubuntu), frontend, override job, non-blocking benchmark job. Checked with actionlint and by running every Linux step locally |
| Q-1.2 Pinned FFmpeg in CI | **Done, never run** | `tools/ffmpeg.toml` pins BtbN `autobuild-2026-09-30` (n9.0.2; override test n8.1.3). `scripts/fetch-tools.py` checks the SHA-256. BtbN keeps month-end builds for 2 years, so re-pin or mirror before about 2028-09 |
| Q-1.3 Dependency updates and audits | **Done, never run** | Dependabot (uv, npm, GitHub Actions), `pip-audit`, `npm audit --audit-level=high` |
| Q-2.1 Fixtures and fake FFmpeg | **Done** | `scripts/make-testdata.py` (all rows of the test media table) and the fake ffmpeg / ffprobe in `testing/reframe_testing/` ([0004](decisions/0004-shared-testing-package.md)) |
| Q-2.2 Recorded probes | **Done** | `testdata/probes/`. The TrueHD Atmos, DTS-HD MA, DTS:X, PGS and DV probes are **synthesised from real output**, not recorded from real files ([0006](decisions/0006-probe-recordings-and-roles.md)). Replace them with real recordings when you can |
| Q-2.3 API contract check | Not started | Needs S-5 |
| Q-2.4 Local samples suite | Not started | |
| Q-3 Performance budgets | **Partial** | The `benchmark` marker and job exist. Only the probe budgets are checked (one file: 58 ms of 500 ms; 24 files: 0.39 s of 5 s) |
| Q-4 Logging and diagnostics | Not started | |
| Q-5 Release process | Not started | Licence: GPL-3.0-or-later is set in the package metadata (open question 2, default) |

## Features

This table maps the product features ([01 §Must-have](plan/01-scope.md#must-have-for-v1) and
the parity table) to what exists. No feature has a user interface yet.

| Feature | Status | What exists |
|---------|--------|-------------|
| Rich audio and subtitle information, role detection | **Partial** | Core and CLI: commercial codec names, bitrate with its source, roles with evidence, flags, subtitle event counts from statistics tags. Missing: the **Measure** bitrate scan (C-10), the UI |
| Source open (file, folder of files) | **Partial** | Core: probe one file, probe a folder as a task. CLI: one file. Missing: the UI, the server file browser |
| HDR information | **Partial** | Detection of HDR10, HDR10+, HLG and Dolby Vision profile, with mastering display and MaxCLL. Core (C-7, branch `m2-encode-cli`): HDR → SDR tone mapping (libplacebo or zscale + tonemap) with the HDR metadata removed, and HDR10 metadata kept in x265 / SVT-AV1 / hardware encodes. Missing: the Source colour box and the UI |
| Tool paths and bundled FFmpeg | **Partial** | Core discovery with overrides and fixes, the manifest and the fetch script. Missing: `reframe tools fetch`, Settings → Tools UI, packaging |
| Languages (search, codes, display) | **Partial** | Core module done. Missing: the language picker UI |
| Non-blocking encoder detection with fallbacks | **Partial** | Core: detection in the background with strict timeouts, plain-language reasons, cache, fallback chain and the `encoder.unavailable` fix. Missing: the C-8 rule registration, CLI `reframe encoders` (C-15), the encoder picker and Settings → Encoders UI |
| Presets (built-in, user, import/export) | Not started | |
| Range, Dimensions, Filters, Video, advanced encoder options | **Partial** | Core: the dimension maths (C-5) and the definitions (C-6: encoders with rate control, presets and the basic advanced options; filters with HandBrake presets and help) and the command builder (C-7: every encoder, the filter chain, ranges by time, chapters and frames, frame rate modes), branch `m2-encode-cli`. Missing: validation (C-8), crop detection (C-10), the UI |
| Audio and subtitle output tracks, audio defaults, track rules | **Partial** | Core (C-7, branch `m2-encode-cli`): output tracks in the command builder (passthru with fallback, mixdowns, sample rate, bitrate, gain, DRC, two-pass loudness normalisation; subtitle copy / convert / burn-in, external files). Missing: audio defaults and track rules (C-12), the UI |
| Track metadata editing, remux-only and metadata-edit jobs | **Partial** | Core (C-7, branch `m2-encode-cli`): languages, names and all six flags written for every track, BCP 47 through an `mkvpropedit` step, remux job type. Missing: metadata-edit jobs (C-13), the UI |
| Chapters, tags | **Partial** | Chapters are probed. Core (C-7, branch `m2-encode-cli`): chapters copied, renamed or generated (FFMETADATA), the eight tags with naming variables. Missing: chapter import / export, the UI |
| Output naming (variables, release-name parsing, templates) | **Partial** | Core done (C-16). Missing: `reframe name` and the default name of `reframe encode` (C-15), name collisions (C-8, C-11), `POST /api/naming/preview` and the variable list in `GET /api/definitions` (S-2), the naming editor (F-18) |
| Queue, logs, when done, sleep inhibit | Not started | The event bus and the task manager exist. Sleep inhibit is built in the core (C-14, branch `m2-encode-cli`); the queue (C-11) does not use it yet |
| Batch / season mode | Not started | |
| Crop preview, filter preview, live preview clip | Not started | |
| Web app | Not started | Frontend scaffold only |
| Desktop app | Not started | |

## What you can run today

```sh
uv run reframe probe FILE            # every track: codec, channels, bitrate + source, language, title, roles, flags
uv run reframe probe --json FILE     # the MediaSource model as JSON
uv run python -m reframe.tools       # which ffmpeg / ffprobe / mkvpropedit / mediainfo is used, and why
uv run python scripts/make-testdata.py
uv run --no-project python scripts/fetch-tools.py
uv run pytest                        # about 1 770 tests
cd frontend && npm run dev:web       # placeholder page only
```

## Not verified

- **Windows**: nothing has run on Windows. That includes the Job Object, `CREATE_NO_WINDOW`,
  the `.exe`-only tool lookup, the `.cmd` test launchers, console encoding, and the Windows CI
  jobs.
- **GitHub Actions**: no workflow has run, because nothing was pushed.
- **GPU encoders**: detection is checked on one Linux machine (AMD RX 7600: VAAPI and AMF
  work); NVENC and QSV only as failures (no NVIDIA driver, no Intel GPU); Windows not at all.

## Open items for the next steps

- **C-13**: ffprobe cannot read Matroska `LanguageIETF`. Reframe reads it through MediaInfo
  (`language_ietf`). Decide in C-13 how a metadata edit is checked after the re-probe.
- **C-7** (done): languages are written in the container's form and every disposition is set
  ([0013](decisions/0013-command-builder-details.md)). Left for others: C-3 reads an MP4
  track title only from `title`, but FFmpeg's MP4 demuxer reports it as `name`; C-11 removes
  `EncodePlan.temp_files` and must clamp `-inf` loudnorm measurements; C-8 must report what
  the builder refuses (list in 0013, Consequences).
- **D-7**: follow the bundled layout of [0005](decisions/0005-tool-discovery-details.md)
  (`tools/ffmpeg/`, `tools/mkvtoolnix/`, `tools/mediainfo/`), and decide on
  `LIBVA_DRIVERS_PATH`.
- **M2**: wave 1 = C-4, C-5, C-6, C-16, C-14 (merged); wave 2 = C-7, C-8, C-9, C-12 (codec
  rules, [0018](decisions/0018-m2-draft-tracks-and-multi-file-encode.md)); wave 3 = C-11, C-15
  ([m2-breakdown.md](m2-breakdown.md)).
