# Implementation status

Last updated: 2026-10-13. Implementation is **paused** by the user in milestone M2, after
wave 2 (branch `m2-encode-cli`, [task breakdown](m2-breakdown.md)). What is left for M2 is
listed under [Paused: what is left in M2](#paused-what-is-left-in-m2).

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
| M2 Encode from the CLI | **In progress, paused** | Branch `m2-encode-cli` ([m2-breakdown.md](m2-breakdown.md)), not merged into `main`. Waves 1 (C-4, C-5, C-6, C-14, C-16) and 2 (C-7, C-8, C-9, C-12 codec rules) are merged and green. Not started: wave 3 (C-11, C-15; its contract is written), the milestone review and the demo. No M2 CLI command exists yet |
| M3 – M10 | Not started | |

## Steps

### Core (`reframe`, 05-core.md)

| Step | Status | Notes |
|------|--------|-------|
| C-0 Project skeleton | **Done** | uv workspace, strict mypy, ruff, pytest markers (`slow`, `needs_ffmpeg`, `needs_gpu`, `benchmark`) |
| C-1 Tool runner and discovery | **Done** | `reframe.tools`: `run` / `run_streaming` (timeout, cancel, output limit, process-tree kill; M2 added `on_start`, the pid for the queue's pause / resume), discovery env → Settings → bundled → `PATH`, version parsing (minimum FFmpeg 7.0), child safety (Linux `PR_SET_PDEATHSIG`; Windows Job Object, [0005](decisions/0005-tool-discovery-details.md)). Windows code is tested with mocks only. `LIBVA_DRIVERS_PATH` handling stays until D-7 decides |
| C-2 Data models | **Done** | All public models with JSON Schema snapshots and round-trip property tests. `FieldChange` (for C-9) and `CapabilitySnapshot` (for C-4) were added in M2. Known gaps: no language-list model for `GET /api/languages` (S-2), `-show_programs` output is not modelled |
| C-3 Probe and track analysis | **Done** | `reframe.probe`: commercial codec names, bitrate chain with its source, role heuristics with evidence, HDR10 / HDR10+ / HLG / Dolby Vision, VFR, interlacing, `delay`, probe cache, folder probe as a task. Decisions [0006](decisions/0006-probe-recordings-and-roles.md) and [0007](decisions/0007-probe-mediainfo-library-and-delay.md). `language_ietf` is filled only when MediaInfo is available. M2: an MP4 track title is read from the `name` tag too (FFmpeg's MP4 demuxer reports it there) |
| C-4 Encoder capabilities | **Done** (branch `m2-encode-cli`) | `reframe.capabilities`: `CapabilityService` (`Reframe.capabilities`: cached result at once, full detection in the background, `capabilities.changed`, re-scan, a new ffmpeg starts a new detection), `-encoders` / `-filters` / `-h encoder=` parsing, hardware test encodes (3 at a time, 10 s, 10-bit test), VAAPI on every render node with the node in `EncoderStatus.device` or the node forced by `encoders.vaapi_device` ([0020](decisions/0020-m2-wave-1-product-decisions.md)), the `libplacebo` run test (`CapabilitySnapshot.usable_filter`), reason mapping of the real FFmpeg texts, cache keyed by binary + GPU fingerprint + settings + render nodes (written before the final `capabilities.changed` event and before `wait()` / `rescan()` return; `close()` finishes a started write, so a short CLI run leaves the result for the next start), `closest_available` (video and audio chains: `libfdk_aac → aac`, 0020), `encoder_issues` (`encoder.unknown` / `checking` / `untested` / `unavailable`) for C-8. Decision [0008](decisions/0008-encoder-detection-reasons-and-filters.md). Checked on one Linux machine (AMD: VAAPI on its one render node, AMF and libplacebo work; NVENC and QSV only as failures; several render nodes only with the fake ffmpeg); the Windows registry fingerprint is tested with mocks only (a fake `winreg` module). M2 review follow-up ([0008](decisions/0008-encoder-detection-reasons-and-filters.md) "Follow-up"): a cached status that is not available is `encoder.checking` while it is checked again (a stale cache no longer blocks `plan` / `encode`); the 10-bit test fails when FFmpeg replaced the pixel format; a forced VAAPI node is kept with hardware tests off; no filter results of another ffmpeg; a tool-discovery error is a failed detection; `close()` waits for a replaced detection |
| C-5 Dimensions maths | **Done** (branch `m2-encode-cli`) | `reframe.dimensions`: `compute_geometry` (crop snapped to the chroma grid, rotation, the four size modes, square / keep / custom pixel aspect, a fit box that turns for portrait output, modulus rounding within 0.5 % or 1 px, notes), `detect_crop_consensus` (auto, conservative), `source_geometry`, `rotate_crop`. Hypothesis properties of "Done when", table tests of the classic cases, and real-FFmpeg tests (crop grid of all 200 pixel formats, the filter chain for C-7 on the anamorphic, letterbox and rotated files). Conventions and corner cases: [0009](decisions/0009-dimension-maths-conventions.md); portrait fit: [0020](decisions/0020-m2-wave-1-product-decisions.md) |
| C-6 Definitions | **Partial** (M2 part done) | **Done:** `reframe.languages` (search, normalisation, ISO 639-2/B for Matroska, ISO 639-2/T for MP4, display names). **Branch `m2-encode-cli`:** `reframe.definitions` with every video encoder (rate control with ranges, args and the quality conversion table, presets, tunes, profiles, levels, 2-pass, the `EncoderOption` schema with the basic option sets for x264, x265, SVT-AV1, NVENC, QSV, AMF, VAAPI and the x264 / x265 per-preset default tables), audio encoders (bitrates per mixdown, fixed steps, sample rates, VBR quality, passthru codecs, mixdowns, the fallback chain `libfdk_aac → aac` of [0020](decisions/0020-m2-wave-1-product-decisions.md)); the snapping helpers `AudioEncoderDef.snap_mixdown` / `snap_samplerate` and `channels_mixdown` that C-7, C-8 and C-12 share ([0024](decisions/0024-m2-wave-2-product-decisions.md) item 4), containers (copy / encode codecs, flags, chapters, attachments, tags, `+faststart`), filters (implementations with their own HandBrake-mapped presets and tunes, chosen by the new `FilterConfig.implementation`; help, fixed order), `convert_quality`, `supported_options`, `lint_definitions`. Checked against FFmpeg n9.0.2 (both builds) and AMF / VAAPI hardware ([0010](decisions/0010-definitions-filters-and-containers.md)). **Not started (M9):** the complete option sets of 03 §Advanced (analysis, colour, performance options, VP9 options). **Not verified:** NVENC and QSV on hardware; QSV levels are not offered |
| C-7 Command builder | **Done** (branch `m2-encode-cli`) | `reframe.command`: `build_plan` (pure; `PlanError` for jobs that skipped validation), `job_type` (`encode` / `remux` with the reason). Argument order of 05 with an output `-t` (and `-ss 0` when the video is encoded and a range or a negative subtitle offset could put something before 0), decoder options, `-map_metadata:s -1` and `-f`; the fixed filter order with colour tagging, HDR metadata removed after tone mapping (`libplacebo` only when its run test passed, else `zscale,tonemap`), hardware init and upload tail (VAAPI render node from the status), text burn-in on the final picture (time-shifted for ranges) and bitmap `overlay` after the crop (10-bit for a deeper source); every encoder's rate control, choices, advanced options, custom params, HDR10 params (x265, SVT-AV1), 2-pass (`EncodePlan.temp_files`), frame rate (doubled after Bob); audio passthru with fallback, output layout (libopus gets a layout it accepts: side → back, else a downmix; other encoders keep the source layout, only `5.1(side)` → `5.1` is relabelled), DRC, gain, two-pass loudnorm (one analyse step per track); the mixdown, bitrate and sample rate snapped to what the encoder can do with C-6's shared helpers (never an upmix, AC-3 7.1 → 5.1, AC-3 700 → 640 kb/s, Opus 44.1 → 48 kHz; `planned_audio` says what is written; [0024](decisions/0024-m2-wave-2-product-decisions.md) item 4, 0013 follow-up); subtitles copy / convert / burn, external files; languages in the container's form plus an `mkvpropedit` step for BCP 47, all six flags; chapters (copy, FFMETADATA for renamed or generated chapters and for a range edge on a chapter edge; a chapter range's end clamped to the last chapter, [0026](decisions/0026-builder-and-validation-agree.md)), tags with naming variables; display for POSIX shells (bash, zsh, fish, sh; tested) and Windows `cmd.exe` (PowerShell not supported). 70 plan snapshots, 43 integration tests on real FFmpeg (both n9.0.2 builds; VAAPI and AMF as `needs_gpu`). Decision [0013](decisions/0013-command-builder-details.md). Not verified: NVENC, QSV (no hardware), Windows. **Open (paused):** tag values are rendered through C-16 internals (`reframe.command.metadata.render_tag`), a public `render_value` in `reframe.naming` would be cleaner |
| C-8 Validation | **Done** (branch `m2-encode-cli`) | `reframe.validation`: `validate(job, source, caps, tools, fs)` and `validate_template(template, caps)` (fixes target `template`), rules registered by area (tools, source, encoder, container, dimensions, filters, audio, subtitles, metadata, range, output, naming); C-4's `encoder_issues` with the closest-match fix that converts the quality and resets what the new encoder lacks; C-16's naming issues; `FileSystemView` / `LocalFileSystem` (all I/O, Windows paths tested with a fake file system); `next_free_path` and `estimate_output_bytes`. 88 issue codes (plus `validation.rule_failed`), each with a positive and a negative test; every fix is applied and re-validated. Odd 4:2:0 sizes are a property test (C-5 cannot make them); forced-only works only for a burned-in PGS or VobSub track (checked with FFmpeg). Wave-2b follow-up ([0014](decisions/0014-validation-rules-and-severities.md) "Follow-up"): `dimensions.crop_not_detected` and the audio values the encoder cannot do are info notes that name the written value ([0024](decisions/0024-m2-wave-2-product-decisions.md) items 3, 4), computed with C-6's shared snap helpers (no upmix, never Dolby Pro Logic II as a fix); `filter.hdr_8bit` warns about an HDR source encoded to 8-bit without tone mapping (checked with FFmpeg: the output stays tagged HDR10 in 8 bits); every `PlanError` of C-7 is a validation error (a test builds a job for each `raise`; five new error codes) and C-7's snapshot jobs validate without errors; a chapter range that ends after the last chapter is clamped by C-7 and a warning in validation ([0026](decisions/0026-builder-and-validation-agree.md)). M2 review fixes (0014 "Follow-up (M2 review)"): every file the job writes (output, `.part`, chapters, 2-pass statistics) is checked against the source through links ([0027](decisions/0027-one-process-owns-the-queue-store.md) item 5); no fix adds an error; a BCP 47 language without mkvpropedit, gain / DRC / loudness on a copied passthru track and an x265 level too small for the output (checked with x265) are issues; a manual output name follows C-16's file-name rules. Decision [0014](decisions/0014-validation-rules-and-severities.md); its severities beyond the plan are provisional (open questions) |
| C-9 Presets and settings stores | **Done** (branch `m2-encode-cli`) | `reframe.settings` (`SettingsStore`: `<config>/settings.json`, migrations, atomic writes with the Windows sharing-violation retry, corrupt file backed up and replaced with defaults plus `settings.corrupt`; a newer or unreadable file is never overwritten) and `reframe.presets` (26 built-ins from HandBrake 1.11.2 as package JSON, incl. *H.265 MKV 1080p* (the default, [0024](decisions/0024-m2-wave-2-product-decisions.md)) and *H.265 NVENC 1080p*; `PresetStore`: CRUD, duplicate, default, export / import with `rename` / `replace` / `skip` on conflicts, partly damaged files keep their valid presets; `diff` → `FieldChange`). Facade: `Reframe.settings` (`get`, `update` with JSON patches, start-up `problems`; tool-path changes re-run discovery, `encoders.hardware_tests` / `vaapi_device` re-run detection) and `Reframe.presets`. Decision [0015](decisions/0015-presets-and-settings-stores.md). **M2 review fixes** (0015 follow-up): `update` refuses a `schema_version` change; a preset of a newer Reframe is refused by `save` / `create` / `import_` (also a `PresetFile`) and exported unchanged (`export` returns a `PresetExport`: `file`, `newer`, `issues`, `document()`); JSON nested more than 64 levels is a damaged file (one deep preset only damages itself), never a crash at start, and is never written; a symbolic link at `settings.json` / `presets.json` is written through to its target and stays a link. The Windows retry and the Windows link path are tested with mocks only |
| C-10 Preview and analysis tasks | **Partial** | **Done:** the background task manager `reframe.tasks` (id, progress, cancel, limit per kind). **Not started:** frames, crop detection, preview clips, bitrate and subtitle scans, loudness measurement |
| C-11 Queue and job runner | **Partial** (M2 part done, branch `m2-encode-cli`; "Done when" passes) | `reframe.queue`: `Reframe.queue` = `QueueService` (the M2 contract plus `start(*, job_ids=…)` for a CLI that shares the store); SQLite store `<data dir>/queue.sqlite3` (one writer thread, whole-row writes, WAL, unknown `JobSettings` fields kept, rows that do not load kept untouched, newer / corrupt / unwritable files handled, file names that are not UTF-8 kept exactly), opened at the queue's first use by the one process that holds `<data dir>/queue.lock` (another process gets a private queue in memory and `queue.store_busy`; decision [0027](decisions/0027-one-process-owns-the-queue-store.md)); `add` validates at once (errors: added as `failed`); the runner probes again, waits for encoder detection when an encoder is being checked, validates again, plans, writes the plan files, runs the steps through `run_streaming` with the weighted progress parser, loudnorm measurements clamped (`-inf` → -99, an infinite offset → 0), a sleep-aware stall watchdog (10 min without progress, output or CPU) and a 5-min limit for `mkvpropedit`; a job whose `.part`, plan or statistics files or final name are the source fails before anything is written (0027 item 5); the `.part` output is re-probed and checked (streams, languages) before the collision-policy rename (`ask` fails and keeps the finished `.part`); pause / resume by psutil on the tree (a paused job keeps its slot); cancel; clean-up of `.part`, plan files and temporary files; logs `<data dir>/logs/<id>.log` and rate-limited `job.log`; speed and ETA over active time (pauses and system sleep do not count); restart recovery and `close()` → `interrupted`; parallel slots from Settings; same output never in parallel; sleep inhibit per running job; when-done `notify` (power actions report "not done" until C-14). Fault injection with the fake ffmpeg for every failure path (the fake gained an `exec` action that passes calls to a real ffmpeg); "Done when" test on real FFmpeg (both n9.0.2 builds). Decision [0016](decisions/0016-queue-and-job-runner.md). Not verified: Windows (rename / replace retries, psutil suspend: mock-tested only). **Not started:** the when-done power actions (quit, sleep, shut down) need C-14's power actions. Limitation: a silent track shorter than 3 s fails loudness normalisation in FFmpeg |
| C-12 Batch engine | **Partial** (M2 part, branch `m2-encode-cli`) | **Built (M2, [0018](decisions/0018-m2-draft-tracks-and-multi-file-encode.md)):** the codec-rule stage of the audio defaults, `reframe.batch.apply_codec_rules` (first match on language and source channels, passthru when the source fits under the `PassthruPolicy` and the container (a lossy source at any bitrate, a lossless one at or below the max: [0023](decisions/0023-lossy-passthru-above-the-max.md)), bitrate cap never above the source, snapping with notes, unknown bitrate as above the max with Measure, fallback encoder, mixdowns without upmix, sample rate, gain, DRC, loudness, name template, extra outputs, `first_track_of_language_only` as first in source order; the encoder's layout, bitrate and sample rate come from C-6's shared snap helpers `snap_mixdown`, `AudioBitrateDef.snap`, `snap_samplerate` and `channels_mixdown`, the same as C-7 and C-8 ([0024](decisions/0024-m2-wave-2-product-decisions.md) item 4), so a source sample rate the encoder lacks is snapped with a note) with a reason per track (`TrackDecision`), and `draft_tracks` (every audio track through the rules, every subtitle copied, metadata from the source; `TrackDraft`). The example of 03 is reproduced row by row; details in [0019](decisions/0019-audio-codec-rule-details.md). **Not started:** the selection stage, `explain` and the defaults lint (M6); descriptors, fingerprints, grouping, rule derivation and resolution (M7) |
| C-13 Metadata edit and remux | Not started | The language-tag behaviour of FFmpeg and mkvpropedit is verified and recorded (`testdata/README.md`) |
| C-14 Platform services | **Partial** | **Branch `m2-encode-cli` only:** sleep inhibit for automatic sleep only, `reframe.platform.sleep` (counted `SleepInhibitor`; Linux: the desktop session's inhibit, `org.freedesktop.PowerManagement.Inhibit` or the XDG portal, plus a logind `idle` lock where needed, through a stdlib D-Bus client, checked on KDE; GNOME not tested; Windows `SetThreadExecutionState` on one dedicated thread, mock-tested only; `sleep_inhibit.unavailable` warning), [0011](decisions/0011-sleep-inhibit.md), [0020](decisions/0020-m2-wave-1-product-decisions.md). **Not started:** power actions, the notification hook. (`reframe.platform` also has child-process safety from C-1 and `launch_detached` for user-facing programs) |
| C-15 Service facade and CLI | **Partial** (M2 part done) | **Done:** `Reframe.create()` / `close()` with `tools`, `sources`, `tasks` and `events`; the `settings` and `presets` services (C-9); CLI `reframe probe FILE [--json]` and `reframe version`; `python -m reframe.tools` (tool status). `Reframe.capabilities` (C-4). **Branch `m2-encode-cli` (wave 3):** `Reframe.jobs` (`JobService`: `draft` → `JobDraft` with the preset's settings, C-12's tracks, the video default flag, the output name (template, or `-o`; a name that is the source becomes `Name (1).ext`); `validate` with a bounded 60 s wait for encoder detection; `plan`; `name`; `media_files`); CLI `reframe encoders`, `reframe plan FILE [--preset] [-o] [--json]`, `reframe encode FILE\|DIR… [--preset] [-o] [-r]` on the real queue (only its own jobs: `start(job_ids=…)`; Ctrl+C cancels only its own jobs and removes their `.part` files, exit 130), `reframe name PATH… [--template] [--preset] [--json]`. Decision [0017](decisions/0017-jobs-service-and-cli.md). **"Done when" passes on Linux:** a season folder (3 episodes) is encoded end to end with template names; M2 demo item 3 (progress and ETA, a re-probed output, a real SIGINT leaves no `.part`) and item 5 (`reframe name` on the Hacksaw Ridge and Sopranos cases) are tests (`tests/jobs/`), on both n9.0.2 builds. The Windows Ctrl+C path is tested through the cancelled task only. **Not started:** the batch service; CLI `tools status\|fetch`, `presets list\|export\|import`, `batch` |
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
| Non-blocking encoder detection with fallbacks | **Partial** | Core: detection in the background with strict timeouts, plain-language reasons, cache, fallback chain and the `encoder.unavailable` fix, validated for jobs and presets with the quality converted (C-8). CLI (C-15, branch `m2-encode-cli`): `reframe encoders` (the cache at once, then the changes), `reframe plan` names the closest encoder and never waits more than 60 s for detection. Missing: the encoder picker and Settings → Encoders UI |
| Presets (built-in, user, import/export) | **Partial** | Core (C-9, branch `m2-encode-cli`): 26 built-ins modelled on HandBrake 1.11.2, user presets with CRUD, default, import / export and conflict handling, the *modified* diff. CLI (C-15, branch `m2-encode-cli`): `--preset NAME` of `plan`, `encode` and `name` (name or id, the closest names suggested; the default preset without it). Missing: `reframe presets list\|export\|import`, the API and the preset UI, HandBrake preset import (later) |
| Range, Dimensions, Filters, Video, advanced encoder options | **Partial** | Core: the dimension maths (C-5), the definitions (C-6: encoders with rate control, presets and the basic advanced options; filters with HandBrake presets and help), the command builder (C-7: every encoder, the filter chain, ranges by time, chapters and frames, frame rate modes) and validation of all of these (C-8), branch `m2-encode-cli`. Missing: crop detection (C-10), the UI |
| Audio and subtitle output tracks, audio defaults, track rules | **Partial** | Core (branch `m2-encode-cli`): the codec-rule stage of the audio defaults with a reason per track and the M2 track draft (C-12: every audio track through the rules, every subtitle copied); output tracks in the command builder (C-7: passthru with fallback, mixdowns, sample rate, bitrate (each snapped to what the encoder can do), gain, DRC, two-pass loudness normalisation; subtitle copy / convert / burn-in, external files). Missing: the selection stage, `explain`, the defaults lint (M6), track rules and batch resolution (M7), the Audio and Subtitles tabs and the defaults dialog |
| Track metadata editing, remux-only and metadata-edit jobs | **Partial** | Core (C-7, branch `m2-encode-cli`): languages, names and all six flags written for every track, BCP 47 through an `mkvpropedit` step, remux job type. Missing: metadata-edit jobs (C-13), the UI |
| Chapters, tags | **Partial** | Chapters are probed. Core (C-7, branch `m2-encode-cli`): chapters copied, renamed or generated (FFMETADATA), the eight tags with naming variables. Missing: chapter import / export, the UI |
| Output naming (variables, release-name parsing, templates) | **Partial** | Core done (C-16). CLI (C-15, branch `m2-encode-cli`): `reframe name` (demo cases: `Hacksaw.Ridge`, `The.Sopranos.S03E02.Proshai.Livushka`) and the template name of `reframe plan` / `encode`. Queue (C-11): a name collision is renamed (`Name (1).mkv`), overwritten or fails, by the collision setting (validation reports it, C-8). Missing: `POST /api/naming/preview` and the variable list in `GET /api/definitions` (S-2), the naming editor (F-18) |
| Queue, logs, when done, sleep inhibit | **Partial** | Core done (C-11, branch `m2-encode-cli`): persistent queue, logs, pause / resume / cancel, retry, restart recovery, parallel jobs, sleep inhibit while encoding, when-done `nothing` / `notify`. Missing: the when-done power actions (quit, sleep, shut down: C-14), the queue API and WebSocket (S-x), the queue UI with duplicate / edit / open folder (F-x) |
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
uv run pytest                        # about 3 730 tests (M2 branch; 18 more with -m needs_gpu)
cd frontend && npm run dev:web       # placeholder page only
```

## Not verified

- **Windows**: nothing has run on Windows. That includes the Job Object, `CREATE_NO_WINDOW`,
  the `.exe`-only tool lookup, the `.cmd` test launchers, console encoding, and the Windows CI
  jobs.
- **GitHub Actions**: no workflow has run, because nothing was pushed.
- **GPU encoders**: detection and real encodes are checked on one Linux machine (AMD RX 7600:
  VAAPI and AMF work); NVENC and QSV only as detection failures and plan snapshots (no NVIDIA
  driver, no Intel GPU); Windows not at all.
- **Sleep inhibit**: checked on KDE Plasma 6 only (no real suspend was done); GNOME and other
  desktops not tested; Windows mock-tested only.

## Open items for the next steps

- **C-13**: ffprobe cannot read Matroska `LanguageIETF`. Reframe reads it through MediaInfo
  (`language_ietf`). Decide in C-13 how a metadata edit is checked after the re-probe.
- **C-7** (done): languages are written in the container's form and every disposition is set
  ([0013](decisions/0013-command-builder-details.md)). Left for others: C-11 removes
  `EncodePlan.temp_files` and must clamp `-inf` loudnorm measurements; C-8 must report what
  the builder refuses (list in 0013, Consequences).
- **D-7**: follow the bundled layout of [0005](decisions/0005-tool-discovery-details.md)
  (`tools/ffmpeg/`, `tools/mkvtoolnix/`, `tools/mediainfo/`), and decide on
  `LIBVA_DRIVERS_PATH`.
- **M2**: see the next section.

## Paused: what is left in M2

The user paused M2 on 2026-10-13, after wave 2 was merged. The agents' git worktrees under
`.claude/worktrees/` are kept, so the step agents can be resumed for their follow-ups.

1. **Wave-2 follow-ups** (decided, not built):
   - C-7: snap impossible audio values in the builder
     ([0024](decisions/0024-m2-wave-2-product-decisions.md) item 4).
   - C-8: `dimensions.crop_not_detected` and the audio range rules as info (0024 items 3, 4);
     a warning for an HDR source encoded to 8-bit without tone mapping; a test that every
     `PlanError` case of C-7 is a validation error and that C-7's snapshot jobs validate
     without errors.
   - C-7, C-8, C-12: switch to the shared audio snap helpers that C-6 added
     (`AudioEncoderDef.snap_mixdown`, `snap_samplerate`, `AudioBitrateDef.snap`,
     `channels_mixdown`), so the builder, validation and the codec rules agree. C-6 found the
     differences: **C-7 does not snap a chosen mixdown** (AC-3 7.1 is written as 7.1, and a
     5.1 mixdown on a stereo source becomes an upmix, against
     [0019](decisions/0019-audio-codec-rule-details.md) item 3) **and writes the audio bitrate
     unsnapped**; C-8's mixdown fix can pick Dolby Pro Logic II and has no upmix rule.
2. **Wave 3** (not started; contract in [m2-breakdown.md](m2-breakdown.md)): C-11 (queue and
   job runner) and C-15 (`Reframe.jobs`, CLI `encoders`, `plan`, `encode`, `name`). The draft
   job gives the video track the default flag (0024 item 5).
3. **End of milestone**: a fresh review agent over the whole `m2-encode-cli` diff, its fixes,
   the five M2 demo items run for real, this file updated, then the merge into `main`.
4. **Questions for the user that are still open** (each is built with a default that is easy
   to change):
   - C-14: when the desktop inhibit fails but the logind lock works, only a log line is
     written, no `app.warning` ([0022](decisions/0022-linux-sleep-inhibit-mechanism.md)).
   - C-7 ([0013](decisions/0013-command-builder-details.md)): bitmap burn-in with a crop is
     aligned to the bottom; loudnorm uses TP −1 and LRA 20; "Peak" frame rate makes a VFR
     source constant at the peak rate; DRC 0 turns off FFmpeg's default AC-3 DRC; a passthru
     track with no encoder falls back to AAC; a remux may convert text subtitles;
     `align_av_start` is ignored (no FFmpeg mapping chosen).
   - C-8 ([0014](decisions/0014-validation-rules-and-severities.md)): the other provisional
     severities (range end beyond the source, lost flags, disk space, forced-only); a per-job
     overwrite flag for the collision setting `ask`.
   - C-16 ([0012](decisions/0012-output-naming-rules.md)): the `{hdr}` label order, `und`
     tracks left out of `{audio_langs}`, Plex extras folders as generic folders, the folder's
     show name in front of a bare `S01E01`.
   - C-12 ([0019](decisions/0019-audio-codec-rule-details.md)): items 3 to 7 (no upmix,
     "fits" needs no decode, no max = the encoder's default, extra outputs,
     first-of-language) were accepted by the lead without asking.
