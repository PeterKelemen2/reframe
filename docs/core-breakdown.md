# Core-complete task breakdown

Working notes of the lead for finishing the core package `reframe`: every `C-x` step that is
still open after M2. The plan ([plan/05-core.md](plan/05-core.md), [plan/04-batch-mode.md](plan/04-batch-mode.md),
[plan/03-features.md](plan/03-features.md)) is the spec; this file says who builds which part,
in which order, and what each part must offer to the others. Status: [status.md](status.md).
If the lead's context is summarised, this file and `status.md` are the source of truth.

## Scope and order

| Step | What is built here | Plan |
|------|--------------------|------|
| C-12 | M6: the selection stage of the audio / subtitle defaults, `explain`, the defaults lint. M7: descriptors, fingerprints, grouping, rule derivation, resolution with relaxation, overrides as JSON patches (including parsed-name overrides for C-16), the match report | 05 §C-12, 04, 03 §Audio defaults, 03 §Subtitles |
| C-10 | M6: bitrate scan, subtitle scans, loudness measure. M8: frames, crop detection, preview clip, frame cache (LRU) | 05 §C-10, 03 §Preview, 03 §Dimensions → Crop |
| C-13 | the `metadata_edit` job type, the mkvpropedit builder, the post-mux fix-up, the re-probe check | 05 §C-13, 03 §Remux-only jobs, 03 §Track metadata |
| C-6 | M9: the complete option sets of 03 §Advanced (analysis, colour, performance, VP9) and the per-preset defaults | 05 §C-6, 03 §Advanced encoder options |
| C-14 | power actions with the cancellable 60 s countdown, the notification hook | 05 §C-14 |
| C-11 | the when-done power actions (quit, sleep, shut down) through C-14 | 05 §C-11, 03 §Queue |
| C-15 | `Reframe.batch` (`BatchService`), `sources.frames / cropdetect / scans`, `jobs.preview_clip`; CLI `tools status\|fetch`, `presets list\|export\|import`, `batch DIR --preset NAME [--dry-run]` | 05 §C-15, decision 0017 |

Small fixes from `status.md`: a public `render_value` in `reframe.naming` (the paused C-7
item); C-3's `str.isdigit()`; a 64-level nesting guard for the queue store and the probe
cache. The C-8 row's "Open: C-12 caps Opus bitrates…" was already fixed by b1dc1a7 (the
agreement test's `DISAGREE` table is empty; the lead corrected the row in the contract
commit). The other known limits stay as recorded.

Out of scope: S-x, F-x, D-x.

**Order** ([decision 0029](decisions/0029-core-before-the-ui-milestones.md)): the core parts of
M6–M9 are built before M3, on one branch **`core-complete`** made from `main`. Each task works
in its own worktree branch; the lead merges it into `core-complete` with `--no-ff` after every
check passes. `core-complete` merges into `main` (`--no-ff`) when every step's "Done when"
passes, the review findings are fixed and the demos below pass. M6–M9 stay open until their UI
parts are built.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: decision 0029, this breakdown, the contract commit | `main` (M2) |
| 1 | 1a C-12 defaults · 1b C-10 scans · 1c C-10 picture · 1d C-13 · 1e C-6 options · 1f C-14 power · 1g C-11 when-done · 1h C-15 CLI tools / presets · 1i small fixes | the contract |
| 2 | 2a C-12 batch engine, `Reframe.batch`, `reframe batch` | wave 1 (1a merged) |
| 3 | review (fresh agent, `xhigh`) of `git diff main...core-complete`; fixes by the task that wrote the step; demos | wave 2 |

The user's task (f) ("C-14 power actions and the notification hook, C-11 when-done power
actions, C-15 CLI `tools` and `presets`") is cut into 1f, 1g and 1h, so each runs at the
effort the user set for its step (C-11: `xhigh`; C-14, C-15: `high`). The notification hook
itself is one function the lead wrote in the contract (`reframe.platform.notify.notify`).
The C-10 scans and picture tasks share the task plumbing, which the lead built as a contract
(`reframe.mediatask`).

### Effort and model

Every agent: `model: "opus"`, `isolation: "worktree"`. `effort: "xhigh"`: 1a, 1b, 1c, 1g, 2a and
every review agent. `effort: "high"`: 1d, 1e, 1f, 1h, 1i and small follow-up fixes.

## Who owns which files

An agent edits only the files it owns. Two agents never own the same file. A change anywhere
else goes back to the lead (say so in the report; do not make it). Paths below are relative to
`packages/reframe/src/reframe/` (code) and `packages/reframe/tests/` (tests) unless they start
with `testing/`, `testdata/`, `scripts/`, `docs/` or `.github/`.

| Task | Owns | Must not touch (common mistakes) |
|------|------|-----------------------------------|
| **1a** C-12 defaults | `batch/` (all files; new modules welcome, e.g. `batch/selection.py`, `batch/explain.py`), `models/defaults.py` (new optional fields only), `tests/batch/` | `jobs.py`, `service.py`, `validation/` (the lint is already wired into `validate_template`), other models |
| **1b** C-10 scans | `analysis/` (all), `tests/analysis/` (new), `testing/reframe_testing/media.py` (new recipes and aliases only), new generator modules in `testing/reframe_testing/` (for example `dts.py`, `pgs.py`), `testing/tests/test_media_fixtures.py` (new tests only), new files in `testdata/probes/fixtures/` and the probe snapshot entries they need, `scripts/make-testdata.py` (only if needed) | `mediatask.py`, `tasks.py`, `service.py`, `jobs.py`, `preview/`, `probe/` (use `ctx.sources.store` to keep a measured value), `queue/` (import `reframe.queue.loudnorm` if useful, do not edit it) |
| **1c** C-10 picture | `preview/` (all), `tests/preview/` (new, including the Q-3 frame benchmark), `command/filtergraph.py` (additions only, if the output frame needs a public helper) | `testing/reframe_testing/media.py` (the 4K fixture `hdr10-4k` and the changing-aspect fixture `letterbox` exist), `mediatask.py`, `service.py`, `jobs.py`, `dimensions.py` (use `detect_crop_consensus`), `command/` other than `filtergraph.py`, `queue/` |
| **1d** C-13 | `metadata/` (all), `command/jobtype.py`, `command/builder.py`, `command/metadata.py`, `queue/runner.py`, `queue/verify.py`, `queue/files.py`, `validation/inplace.py`, `validation/output.py` and `validation/metadata.py` (only what in-place / remux-only jobs need), `probe/prober.py` and a new `probe/<name>.py` (only if the re-probe must read `LanguageIETF` without MediaInfo), the public `render_value` in `naming/` (`naming/__init__.py` and the module that defines it), `tests/metadata/` (new), new test files in `tests/command/`, `tests/queue/`, `tests/validation/`, `tests/validation/cases_inplace.py` | `queue/service.py`, `queue/store.py`, `probe/mediainfo.py`, `probe/cache.py`, `service.py`, `jobs.py`, `command/video.py`, `command/filtergraph.py`, `validation/video.py`, `validation/__init__.py` |
| **1e** C-6 options | `definitions/` (all, with `data/*.toml` and `data/options/*.toml`; a new `data/options/vp9.toml`), `validation/video.py`, `validation/levels.py`, `validation/dryrun.py`, `command/video.py` (only if a new option mapping needs it), `tests/definitions/`, `tests/validation/cases_options.py`, new test files in `tests/validation/` and `tests/command/` | `jobs.py`, `service.py`, `command/builder.py`, `command/metadata.py`, `command/jobtype.py`, `validation/output.py`, `validation/inplace.py`, `validation/__init__.py`, `presets/` (built-in presets keep their values) |
| **1f** C-14 power | `platform/power.py`, `testing/reframe_testing/pytest_plugin.py` (the session-wide safety fixture only), `tests/platform/test_power*.py` (new) | `platform/sleep.py`, `platform/dbus.py` (import them if useful), `platform/notify.py`, `queue/`, `service.py`, `cli.py` |
| **1g** C-11 when-done | `queue/service.py` (the when-done part: `_when_done` and what it needs, the job / queue notifications), new `queue/whendone.py` if useful, new test files `tests/queue/test_when_done*.py` | `queue/runner.py`, `queue/verify.py`, `queue/files.py`, `queue/store.py`, `platform/`, `service.py`, `cli.py` |
| **1h** C-15 CLI | `cli.py`, `tools/fetch.py`, `tools/__main__.py`, a packaged copy of the FFmpeg manifest if needed (new files under `tools/` plus the package-data entry in `packages/reframe/pyproject.toml`), `tests/test_cli.py`, `tests/jobs/test_cli_*.py`, new test files (`tests/tools/test_fetch*.py`, `tests/test_cli_presets.py`, …), `scripts/fetch-tools.py` and `.github/workflows/ci.yml` (only if needed) | `service.py`, `jobs.py`, `presets/`, `tools/discovery.py`, `tools/runner.py`, `queue/`, `platform/` |
| **1i** small fixes | `probe/mediainfo.py`, `probe/cache.py`, `queue/store.py`, new test files for them (`tests/probe/test_*`, `tests/queue/test_store_*`) | `settings.py` and `presets/store.py` (they already have the guard: reuse `reframe.settings.too_deep` / `MAX_DEPTH`), everything else |
| **2a** C-12 batch | `batch/` (all), `models/batch.py` (new optional fields only; the lead writes it before wave 2), `jobs.py` (`job_from_preset` through the batch engine), the `Reframe.batch` stub (`batch/service.py`), `cli.py` (`reframe batch`), `testing/reframe_testing/media.py` (the 04 §Example season), `tests/batch/`, `tests/test_cli*.py` (new tests) | written in the wave-2 contract |

**Existing test files** (new test files are always fine; give them a name of your task, for
example `test_metadata_edit_*.py`, `test_options_*.py`, `test_when_done*.py`):

| Task | May edit these existing test files |
|------|-------------------------------------|
| 1a | `tests/batch/*`, `tests/validation/test_audio_agreement.py`, `tests/validation/test_template.py` |
| 1b | `testing/tests/test_media_fixtures.py`, `testing/tests/test_media_generator.py`, `tests/probe/__snapshots__/test_snapshots.ambr` (new entries) |
| 1c | `tests/command/test_filtergraph.py` |
| 1d | `tests/command/test_builder.py`, `test_snapshots.py` and `__snapshots__/`, `test_tracks.py`, `test_integration.py`; `tests/queue/test_faults.py`, `test_integration.py`, `test_units.py`; `tests/validation/test_command_agreement.py`, `test_paths.py`; `tests/probe/test_prober.py`; `tests/naming/*` (for `render_value`) |
| 1e | `tests/definitions/*`, `tests/command/test_video.py`, `tests/validation/test_x26x_ffmpeg.py`, `test_levels_ffmpeg.py`, `test_hdr_ffmpeg.py` |
| 1f | none (new files only) |
| 1g | `tests/queue/test_queue.py`, `tests/queue/test_facade.py` |
| 1h | `tests/test_cli.py`, `tests/__snapshots__/test_cli.ambr`, `tests/jobs/test_cli_*.py`, `tests/tools/*` |
| 1i | `tests/queue/test_store.py`, `tests/probe/test_cache.py`, `tests/probe/test_cache_file_names.py` |

Nobody edits `tests/validation/test_rules.py`, `tests/validation/scenario.py`, the
`conftest.py` files, `tests/test_service.py`, `tests/jobs/test_service.py` or
`tests/test_mediatask.py` in wave 1: a needed change there goes to the lead.

**Shared files** (more than one task writes them; the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own step row and the feature rows its step
  changes, in the same commit as the step. 1i removes the two "Known limits" lines it fixes.
- `testdata/README.md`: each task writes real tool behaviour under its own heading in
  "Verified tool behaviour" (placeholders exist: one per task); 1b also adds its fixture rows
  to the "Generated media" table.
- `reframe/models/`: a new optional field needs the schema snapshot
  (`uv run pytest packages/reframe/tests/models/test_schema.py --snapshot-update`) and a
  round-trip test. The lead regenerates the snapshot file when two branches touch it.
- `packages/reframe/tests/probe/__snapshots__/test_snapshots.ambr`: a new recorded fixture
  probe adds an entry (`--snapshot-update`); the lead regenerates it on conflicts.
- A new core dependency is a plan change (05 §Rules for the core): a decision record.

## Decision record numbers

One record per task; a task with several topics uses sections in its one record. A review fix
adds a dated section to the record of the task that wrote the step.

| 0029 | 0030 | 0031 | 0032 | 0033 | 0034 | 0035 | 0036 | 0037 | 0038 | 0039 | 0040 | 0041+ |
|------|------|------|------|------|------|------|------|------|------|------|------|-------|
| lead (order, used) | lead (contract, used) | 1a | 1b | 1c | 1d | 1e | 1f | 1g | 1h | 1i (only if needed; unused) | 2a | lead (review, demos: 0041) |

## Contracts

Signatures are binding. A task may add keyword-only parameters with defaults, extra functions,
and new optional fields (with defaults) on its own models, but not change these. Expected
failures are data, never exceptions. Every new persisted value of a `Literal` / enum needs a
`schema_version` bump and a migration (persistence rules of `CLAUDE.md`): **ask the lead
first**.

### Built by the lead (contract commit, before wave 1)

Decision [0030](decisions/0030-core-complete-contract.md) lists the facade methods and why.

**Models** (all runtime models, `ReframeModel`; no persisted document changes, so no
`schema_version` bump and no migration):

- `reframe.models.analysis`: `BitrateScan(path, stream_index, bitrate: BitrateInfo, packets,
  bytes, duration)`, `SubtitleScan(path, tracks: list[SubtitleScanTrack])`,
  `SubtitleScanTrack(stream_index, event_count, forced_event_count)`,
  `LoudnessMeasurement(path, stream_index, integrated, true_peak, lra, threshold, start,
  duration)` (`None` where FFmpeg prints `-inf`).
- `reframe.models.preview`: `PreviewFrame(key, kind: FrameKind, timestamp, path, width,
  height, cached)`, `FrameSet(path, frames, notes)`, `CropSample(timestamp, crop: CropRect |
  None)`, `CropDetection(path, samples, auto, auto_frames, conservative, notes)`,
  `PreviewClip(id, path, source, start, duration, container, video_codec, job_type, size)`.
- `reframe.models.tools.ToolFetchResult(build, platform, version, install_dir, ffmpeg,
  ffprobe, downloaded)`.
- `TrackDecision` gains `kind: "audio" | "subtitle"`, `selected: bool = True`, `selection: str |
  None` (why taken or dropped), `subtitle_outputs: list[SubtitleOutputTrack]`. `TrackDraft`
  gains `subtitle_decisions` and `issues: list[ValidationIssue]`.
- Measured values go into existing `MediaSource` fields: `AudioStream.bitrate` with
  `BitrateSource.MEASURED`; `SubtitleStream.event_count` with `event_count_source="measured"`
  and `forced_event_count`.

**The C-10 task context** (`reframe/mediatask.py`, lead-owned):

```python
@dataclass(frozen=True, slots=True)
class MediaTaskContext:
    tasks: TaskManager; tools: ToolsLookup; sources: SourceAccess; capabilities: CapabilitiesLookup
    settings: Callable[[], AppSettings]; events: EventBus; cache_dir: Path   # <cache dir>
    definitions: Callable[[], Definitions]
class TaskFailed(Exception): ...        # expected failure inside a task → TaskInfo.error
def sample_timestamps(duration: float | None, count: int) -> list[float]   # 5 %…95 %, evenly
async def require_tool(ctx, name: ToolName) -> ToolInfo                    # or TaskFailed
async def require_source(ctx, path, *, cancel=None) -> MediaSource         # or TaskFailed
# SourceAccess: probe(path, *, use_cache=True, cancel=None); store(source) (memory + probe cache);
#   update(source, change) (review fix R3-1: change(latest) applied to the latest known source, per-file lock)
```

Frames go to `<cache dir>/frames`, clips to `<cache dir>/clips`. Every subprocess goes through
`reframe.tools.run*` with the task's `ctx.cancel` (a `reframe.tasks.TaskContext`). Default
limits per kind (`reframe.tasks.DEFAULT_LIMITS`): `bitrate_scan` 2, `subtitle_scan` 2,
`loudness` 2, `frames` 2, `cropdetect` 1, `preview_clip` 1, `tools_fetch` 1.

**Facade** (`reframe/service.py`, `reframe/jobs.py`; lead-owned; each method delegates):

```python
# Reframe.sources (SourceService)
def bitrate_scan(path, stream_index: int) -> TaskInfo                         # → analysis.start_bitrate_scan
def subtitle_scan(path, stream_indexes: Sequence[int] | None = None) -> TaskInfo  # → analysis.start_subtitle_scan
def loudness_scan(path, stream_index: int, *, start=None, duration=None) -> TaskInfo  # → analysis.start_loudness_scan
def frames(path, *, count=None, timestamps=None, job: JobSettings | None = None) -> TaskInfo  # → preview.start_frames
def frame(key: str) -> Path | None                                             # → preview.frame_path
def cropdetect(path, *, count=None) -> TaskInfo                                # → preview.start_cropdetect
async def store(source: MediaSource) -> None                                   # lead: memory + probe cache
# Reframe.jobs (JobService)
def preview_clip(job, *, start: float, seconds: float) -> TaskInfo             # → preview.start_preview_clip
def preview_clip_path(clip_id: str) -> Path | None                             # → preview.clip_path
async def explain(source, template: JobTemplate | str | None = None, *, container=None) -> TrackDraft | ProbeError
async def draft_remux(source, preset=None, *, edit_in_place=True) -> JobDraft | ProbeError  # → metadata.remux_job
def search_options(encoder_id: str, query: str) -> list[EncoderOption]          # → definitions.search_options
def hdr_metadata(job, source) -> list[JsonPatchOp]                             # → definitions.hdr_options
async def dry_run(job, source=None) -> list[ValidationIssue]                   # → validation.dryrun.dry_run
async def plan(job, source=None, *, dry_run: bool = False) -> EncodePlan | list[ValidationIssue]
# Reframe.tools (ToolsService)
def fetch(*, build="default", platform=None, manifest: Path | None = None) -> TaskInfo  # → tools.fetch.start_fetch
# Reframe.power (PowerService, reframe.platform.power) — C-14
```

**Stubs the tasks fill in** (signatures fixed; the bodies raise `NotImplementedError` until
then):

| Module | Functions | Task |
|--------|-----------|------|
| `analysis/__init__.py` | `start_bitrate_scan(ctx, path, stream_index)`, `start_subtitle_scan(ctx, path, stream_indexes)`, `start_loudness_scan(ctx, path, stream_index, *, start, duration)` → `TaskInfo` | 1b |
| `preview/__init__.py` | `start_frames(ctx, path, *, count, timestamps, job)`, `frame_path(ctx, key)`, `start_cropdetect(ctx, path, *, count)`, `start_preview_clip(ctx, job, *, start, seconds)`, `clip_path(ctx, clip_id)` | 1c |
| `metadata/__init__.py` | `remux_job(job, source, *, edit_in_place=True, definitions=None) -> JobSettings` | 1d |
| `definitions/search.py` | `search_options(options: Sequence[EncoderOption], query: str) -> list[EncoderOption]` | 1e |
| `definitions/hdr.py` | `hdr_options(encoder: VideoEncoderDef, stream: VideoStream) -> dict[str, OptionValue]` | 1e |
| `validation/dryrun.py` | `async dry_run(job, source, caps, tools, *, definitions=None, cancel=None) -> list[ValidationIssue]` | 1e |
| `batch/lint.py` | `lint_defaults(defaults: AudioDefaults, *, container="mkv", source=None, definitions=None) -> list[ValidationIssue]` (returns `[]` now; already called by `validate_template`) | 1a |
| `batch/draft.py` | `draft_tracks(source, template, *, definitions=None, languages: LanguageSettings | None = None) -> TrackDraft` (`languages` is new and passed by `JobService` from Settings; ignored until 1a) | 1a |
| `platform/power.py` | `PowerService(events, *, executor=None, countdown=60.0)`: `schedule(action, *, reason="") -> str`, `cancel(countdown_id=None) -> bool`, `pending`, `async close()`; `PowerExecutor.execute(action) -> str | None`; `create_power_service(events)` | 1f |
| `tools/fetch.py` | `start_fetch(tasks, *, data_dir, rescan, build="default", platform=None, manifest=None) -> TaskInfo` | 1h |
| `validation/inplace.py` | (empty; imported by `validation/__init__.py`) register C-13's rules here | 1d |
| `tests/validation/cases_inplace.py`, `cases_options.py` | `cases(h) -> list[Case]`, loaded by `test_rules.py` | 1d, 1e |

The queue gets the power service: `QueueService(…, power: PowerService | None = None)`, stored
as `self._power` (1g uses it). The notification hook is done:
`reframe.platform.notify.notify(events, title, message="", *, level="info", job_id=None)`.
The fixture `hdr10-4k` (3840×2160 HEVC Main 10 PQ, 6 s, keyint 48) is in
`reframe_testing.media`, with its recorded probe and snapshot.

### Wave 1 contracts per task

**1a C-12 defaults** (`reframe.batch`, pure):

```python
def draft_tracks(source, template, *, definitions=None, languages: LanguageSettings | None = None) -> TrackDraft
def explain(defaults: AudioDefaults, source: MediaSource, *, container: Container = "mkv",
            preferred_languages: Sequence[str] = (), definitions: Definitions | None = None) -> list[TrackDecision]
def explain_subtitles(defaults: SubtitleDefaults, source: MediaSource, *, container: Container = "mkv",
                      preferred_languages: Sequence[str] = (),
                      audio: Sequence[AudioOutputTrack] = ()) -> list[TrackDecision]
def lint_defaults(defaults: AudioDefaults, *, container="mkv", source=None, definitions=None) -> list[ValidationIssue]
def apply_codec_rules(...)  # unchanged (keyword-only additions allowed)
```

- `draft_tracks`: the selection stage (03 §Audio defaults part 1: languages, first / all
  matching, tie-break, `und`, other languages, no-match behaviour, commentary and description,
  output order, default track), then the codec rules for each selected audio track (in the
  output order), then the subtitle selection (03 §Subtitles: the same selection, plus foreign
  audio search, burn-in behaviour and the default-track policy). One `TrackDecision` per
  source track (audio in `decisions`, subtitles in `subtitle_decisions`), selected or not,
  with `selection` and `reason`. `issues`: a required language with no track (`no_match:
  "none"` for audio is an error), and `lint_defaults(…, source=source)`.
- **Default to keep (easy to change; record it in 0031):** when no language is configured at
  all (the selection's `languages` is `None` and Settings has no preferred languages of that
  kind), the selection stage takes every track in source order, as M2 did (decision 0018),
  so `reframe encode` with the built-in presets does not start dropping tracks.
- `JobService.draft` and `JobService.explain` already pass `settings.languages`; the CLI's
  `reframe plan` prints `TrackDecision.reason` per track (keep the field meaningful).
- `lint_defaults` paths: `audio_defaults.codec_rules[1]`, `….max_bitrate`; fixes target
  `"template"`. Codes in the `defaults.` namespace (`defaults.rule_shadowed`,
  `defaults.rule_unreachable`, `defaults.bitrate_snapped`, `defaults.codec_not_in_container`,
  `defaults.rule_unused`), severities as 03 says.

**1b C-10 scans** (`reframe.analysis`): the stub signatures above. Results:
`BitrateScan`, `SubtitleScan`, `LoudnessMeasurement`. Each scan streams progress
(`ctx.progress`) and stops its process within 1 s of `TaskManager.cancel`. When a bitrate or
subtitle scan is done, the updated `MediaSource` goes to `ctx.sources.store(source)`.
Fixtures: a DTS-HD MA track with no bit rate in the file (M6 demo 1; see the task prompt) and a
PGS track with forced events (the `forced_subs_only` count).

**1c C-10 picture** (`reframe.preview`): the stub signatures above. Frames: fast seek (`-ss`
before `-i`), PNG of the source frame and (with a job) of the output frame with the job's
crop, scale and filter graph (C-7's filter chain); an HDR source is mapped for display (say
how in `FrameSet.notes`). Cache key: source fingerprint + timestamp + settings hash; LRU with
`settings.preview.cache_size_mb`. Crop detection: `cropdetect` on each sample (`round=2`, a
limit that suits HDR / PQ black levels), then `detect_crop_consensus` (C-5) for `auto` and
`conservative`. Preview clip: `seconds` from `start` with the full plan (C-7 `build_plan` with
a time range), in `<cache dir>/clips`.

**1d C-13** (`reframe.metadata`, `reframe.command`): `remux_job` (above); `job_type` returns
`metadata_edit` for an MKV source with `output.edit_in_place`, the track set and order
unchanged and only metadata changed (03 §Remux-only jobs), with a reason; the plan of a
`metadata_edit` job edits the source in place with mkvpropedit
(`--edit track:a1 --set language=ger --set language-ietf=de --set name="…" --set flag-default=1 …`);
the post-mux fix-up for every other MKV job sets what FFmpeg did not write; after every
metadata change the file is probed again and checked. A metadata edit writes the source
file: decision 0027 says the queue never writes or removes the source, so 0034 must state the
exception exactly (only a `metadata_edit` job, only through mkvpropedit, never a removal).
Public `render_value` in `reframe.naming` (and C-7's tag rendering uses it).

**1e C-6 options** (`reframe.definitions`, `reframe.validation`): the stub signatures above;
the option sets of 03 §Advanced "Option coverage for v1" for every encoder (x264, x265,
SVT-AV1, NVENC, QSV / AMF / VAAPI, and VP9 `libvpx-vp9`), each option with help, mapping,
range and default (per-preset tables for x264 / x265), checked against the real encoders; the
cross-option rules that need them in `validation/video.py`; `search_options`, `hdr_options`,
`dry_run`.

**1f C-14 power** (`reframe.platform.power`): `PowerService` above. Countdown: `started`, a
`tick` every second, then `cancelled` or `executing` (`PowerCountdownEvent`); a new
`schedule` cancels a running countdown; `close()` cancels and never executes. Executors per
OS: Windows `shutdown /s /t 60` and `SetSuspendState` (mocked), Linux `systemctl poweroff` /
`systemctl suspend` through `reframe.tools.run`. A failure is an `app.warning`. `quit` only
publishes `executing` (the UI quits). **The shared pytest plugin gets an autouse fixture that
makes the real executors unusable in every test.**

**1g C-11 when-done** (`reframe.queue`): `_when_done` runs `quit`, `sleep` and `shutdown`
through `self._power.schedule(action, reason=…)` (no power service: today's
`queue.when_done_unavailable` warning); `nothing` and `notify` stay; job-level notifications
through `reframe.platform.notify.notify` when `settings.queue.notifications` (done, failed).
Test with a fake `PowerService` (same contract); never a real power call.

**1h C-15 CLI** (`reframe.cli`, `reframe.tools.fetch`): `reframe tools status` (what
`python -m reframe.tools` prints), `reframe tools fetch [--build] [--platform]` (the task, with
progress), `reframe presets list`, `reframe presets export [NAME…] [-o FILE]`, `reframe presets
import FILE [--on-conflict rename|replace|skip]` through `Reframe.presets`; `reframe plan` runs
`jobs.plan(…, dry_run=True)` when the job has custom parameters; `reframe encode` waits for a
when-done countdown that its own jobs started and shows it (Ctrl+C cancels it). Exit codes and
output style as decision 0017.

**1i small fixes**: `probe/mediainfo.py` accepts only ASCII digits for a stream order;
the queue store and the probe cache refuse JSON nested more than 64 levels (C-9's
`reframe.settings.too_deep` / `MAX_DEPTH`) as a damaged row / entry, never a crash.

### Wave 2 contract (built by the lead after wave 1, commit "wave-2 contract")

What wave 1 delivered for it (read the code; use these names):

- 1a `reframe.batch`: `select_tracks(streams, selection, *, preferred_languages, kind) ->
  Selection` (one `Pick` per track; helpers `effective_languages`, `language_slot`,
  `sort_key`, `extra_role`, `is_forced`, `subtitle_rank`, `is_undetermined`), `audio_stage`,
  `subtitle_stage`, `explain`, `explain_subtitles`, `foreign_audio_search`, `draft_tracks(…,
  languages=…)`, `lint_defaults(…, container_codecs=…)`, `apply_codec_rules`. Decision 0031.
- 1d `reframe.metadata.remux_job`, `job_type` with `metadata_edit` (0034); 1b the
  `dts-hd-ma` fixture generator `reframe_testing.dts` (0032); C-16 `resolve_output_name`.
- Lead: `JobDraft.subtitle_decisions`; the draft's issues include the track stage's errors;
  `reframe.jobs.draft_from_preset(source, preset, *, definitions, languages) -> (job,
  TrackDraft, notes)`.

`reframe/models/batch.py` (runtime models; a group template is a `JobTemplate`, saved as a
preset, so **no new persisted document and no `schema_version` change**): `MatchLevel`,
`TemplateSection`, `MatchStatus`, `TrackDescriptor`, `Fingerprint`, `GroupMember`,
`BatchGroup`, `BatchGrouping` (groups + the issues of files that could not be probed),
`TrackMatch` (one matrix cell), `MatrixColumn`, `Resolution` (path, job, matches, naming,
issues, status ✓/⚠/✗, the override applied), `BatchResolution` (group, columns, rows,
batch-level issues). 2a may add optional fields.

`reframe/batch/service.py` (`Reframe.batch: BatchService`; the one I/O part of the batch
package, never imported by `reframe.batch` itself):

```python
async def group(sources: Sequence[path | MediaSource], *, level: MatchLevel = "standard") -> BatchGrouping
def derive(job: JobSettings, source: MediaSource, sections: Collection[TemplateSection], *,
           base: JobTemplate | None = None) -> JobTemplate
def merge(base: JobTemplate, incoming: JobTemplate, sections: Collection[TemplateSection]) -> JobTemplate
async def resolve(template: JobTemplate | str | None, sources: Sequence[path | MediaSource], *,
                  overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,   # keyed by str(path)
                  group: BatchGroup | None = None) -> BatchResolution
async def save_preset(template: JobTemplate, name: str, *, category="Custom", description="") -> Preset | ValidationIssue
```

The pure engine in `reframe.batch` (04 §Core API; 2a chooses the modules): `describe_tracks(source)
-> list[TrackDescriptor]`, `fingerprint(source, level) -> Fingerprint`,
`group_sources(sources, level) -> list[BatchGroup]`, `derive_template(job, source, sections)
-> JobTemplate`, `merge_template(base, incoming, sections) -> JobTemplate`,
`resolve(template, source, override) -> Resolution`, `resolve_group(group, template, …,
overrides) -> list[Resolution]` (04's `resolve_group` has no sources; the pure function needs
them: an extra parameter, recorded in 0040). Naming, validation and name collisions within
the batch are the service's (they read the file system).

**One rule engine**: the preset's audio / subtitle defaults compile into `OutputTrackRule`s
(04 §Track rules), and `JobService.draft` goes through the same resolution (2a owns
`jobs.py`): the drafts of M2 / M6 stay what they are (the `tests/jobs/` and CLI tests stay
green), or a change is recorded. CLI `reframe batch DIR --preset NAME [--dry-run]`
(05 §C-15): prints the resolution matrix; without `--dry-run` it queues the valid files and
encodes them like `reframe encode` (0017's output and exit codes).

## Seams (where two tasks meet)

- **C-13 ↔ C-11's runner**: 1d owns `queue/runner.py`, `verify.py`, `files.py` (how a
  `metadata_edit` plan runs, the in-place exception to "never write the source", the
  re-probe check). 1g owns `queue/service.py` (when-done) and 1i owns `queue/store.py`. If 1d
  needs a change in `queue/service.py`, it reports it to the lead.
- **C-6 ↔ C-8's rules**: 1e owns `validation/video.py` and `levels.py` (option rules) and the
  dry run; 1d owns `validation/output.py`, `metadata.py`, `inplace.py`. Rule cases go into
  `cases_options.py` / `cases_inplace.py`, never into `test_rules.py`.
- **C-6 ↔ C-7**: 1e may touch `command/video.py` for a new option mapping; 1d owns
  `command/builder.py`, `jobtype.py`, `metadata.py`.
- **C-12 ↔ C-15**: `JobService.draft` / `explain` call `draft_tracks(…, languages=…)` (wired by
  the lead). In wave 2, 2a owns `jobs.py`.
- **C-10 scans ↔ picture**: the shared plumbing is `reframe.mediatask` (lead). 1b owns the
  fixture recipes; 1c uses `hdr10-4k` and `letterbox`.
- **C-14 ↔ C-11 ↔ C-15**: `PowerService` (1f) is used by the queue (1g) and shown by the CLI
  (1h), both against the contract with fakes.
- **C-15 ↔ C-6**: `reframe plan` asks for the dry run (1h) that 1e builds.

## Every agent prompt includes

- The step IDs, plan sections, owned and forbidden files, the contracts, the "Done when"
  lines word for word, the decision number.
- Setup: a fresh worktree starts at `main`: run `git merge --ff-only core-complete` first.
  `.tools/` and `testdata/media/` are not in a worktree: the pinned FFmpeg is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (n8.1.3: `…/override-test-linux-x64/ffmpeg-n8.1.3-9-g29e619e767-linux64-gpl-shared-8.1/bin`);
  `/usr/bin/ffmpeg` (n9.0.2) is on `PATH`; copy the fixtures with
  `cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
- Commands: every Python check of `CLAUDE.md` (`uv run ruff check`, `uv run ruff format
  --check`, `uv run mypy`, `uv run mypy --platform win32`, `uv run pytest -m "not needs_gpu"`),
  plus `uv run pytest -m needs_gpu` when GPU paths are touched. **Run the suite in the
  foreground** (a SIGINT test fails in a background job of a non-interactive shell). Several
  agents run at once: a timing test that fails under load is run again alone before it is
  called a bug.
- Every FFmpeg / ffprobe / mkvpropedit / MediaInfo fact is checked with the real tool and
  recorded in a test or in `testdata/README.md`.
- Commit with the step ID first and the co-author line; update the task's own rows of
  `docs/status.md` in the same commit. Never push.
- Report: real test output (the last lines of each command, not a summary), every deviation
  from the plan, every decision record written, every file touched outside the owned list.
- Safety: power-action tests never shut down, suspend or log out this machine (every
  `systemctl`, `shutdown`, `SetSuspendState` mocked; a test that can reach the real call is a
  bug); sleep-inhibit tests check only their own inhibits; caches in tests use temporary
  folders; `reframe tools fetch` tests use a local file or a local HTTP server, never the
  network; new Windows code is unit-tested with mocks and `mypy --platform win32` stays green.

## Demos (run for real by the lead after wave 3; output in the final report)

CLI where the plan has a command, otherwise a short script against the `Reframe` facade.

1. **M6.1**: a DTS-HD MA fixture with no bitrate in the file → bitrate scan → a bitrate.
2. **M6.2**: a commentary track has its role, with the evidence.
3. **M6.3/4**: set the languages `hu` and `pt-BR`, track names and flags on an MKV → the job
   type is `metadata_edit`, it finishes in under 1 s, and the re-probe shows every value.
4. **M6.5**: defaults "Hungarian 5.1 or more → AC-3 5.1, max 320" and "English 5.1 or more →
   AC-3 5.1, max 384". `explain` shows DTS-HD MA → AC-3 320, an AC-3 224 kb/s source passed
   through, and a stereo track falling to the next rule, with a reason on each row.
5. **M7**: `reframe batch SEASON --preset … --dry-run` on the 04 §Example season gives one
   group and a ✓ for every file, with the right warnings for E05 and E11. The group is saved
   as a preset and applied to a second season.
6. **M8**: frames of the 4K HDR fixture take under 2 s each. Automatic and conservative crop
   give different results on the changing-aspect fixture. A preview clip is written.
   Cancelling a scan stops ffmpeg within 1 s.
7. **M9 (core part)**: an option search for "psy" finds psy-rd and psy-rdoq in the x265 set.
   The HDR10 metadata from the probe fills master-display and MaxCLL. An unsupported custom
   parameter gives a validation error from the dry run.
8. `reframe tools status`, `reframe presets list`, and a presets export → import round trip.

## Progress

| Date | What |
|------|------|
| 2026-10-15 | Baseline on `main` (108b5f1): 5549 passed, 2 skipped (25 `needs_gpu` deselected; they pass: 25). ruff, format, mypy (both platforms) green |
| 2026-10-15 | `core-complete` made from `main`; decision 0029 + roadmap note committed |
| 2026-10-15 | Contract commit: models, `reframe.mediatask`, facade methods, stubs, `hdr10-4k` fixture, decision 0030 |
| 2026-10-15 | Wave 1 started from `core-complete` 56f1abd: nine agents (1a–1i), one worktree each |
| 2026-10-15 | Merged 1i (C-3, C-11 small fixes: ASCII stream orders, the 64-level guard for the queue store and the probe cache; follow-ups in 0007 and 0016, 0039 unused). Checks green: 5646 passed, 2 skipped; `needs_gpu` 25 passed |
| 2026-10-15 | Merged 1f (C-14 power actions, decision 0036; the C-14 row is **Done**). Checks green: 5706 passed, 2 skipped; `needs_gpu` 25 passed. Open questions in 0036: Windows `shutdown /t 60` after Reframe's countdown, no password prompt, `suspend`, no elogind fallback |
| 2026-10-15 | Merged 1g (C-11 when-done power actions and job notifications, decision 0037; the C-11 row is **Done**; its two tests against the real `PowerService` run now). Checks green: 5738 passed, 2 skipped; `needs_gpu` 25 passed. Lead follow-ups done: 0016 points to 0037, the queue package docstring, the open questions of 0036 / 0037 in `status.md`. Told 1h to add `queue.when_done_failed` and `power.failed` to its CLI warning codes. Lead follow-up kept for the review: should a change of the when-done setting cancel a running countdown (0037 says no; S-2's `PUT /api/queue/when-done` may do it) |
| 2026-10-15 | Merged 1d (C-13, 0034; **Done**): 5841 passed. Merged 1a (C-12 selection stage, explain, lint, 0031): 6006 passed. Merged 1h (C-15 CLI tools / presets, 0038): 6148 passed. Merged 1b (C-10 scans, DTS-HD MA and PGS fixtures, 0032): 6232 passed. Merged 1e (C-6 complete option sets, 0035): 6356 passed. Merged 1c (C-10 picture, 0033; C-10 **Done**): 6532 passed, 2 skipped; `needs_gpu` 26 passed; `benchmark` 2 passed. Every merge: ruff, format, mypy (both platforms) green. Three merge commits (1a, 1h, 1b) were committed in the main checkout while the lead's checks ran, by something other than the lead (each right after an agent ended); each holds the lead's staged resolution, and the checks passed on that tree |
| 2026-10-15 | **Wave 1 done.** Status: C-6, C-10, C-11, C-13, C-14 Done; C-12 M2 + M6 parts; C-15 all but `batch` |
| 2026-10-15 | Lead follow-ups of wave 1 (fb895a9): `TaskFailed` is a message without a traceback; `validate_template` reports a codec the container cannot hold once; `JobDraft.subtitle_decisions` and the track stage's errors in a draft; `sources.preview_cache_size` / `clear_preview_cache`; the manifest copy step in `tools/README.md`. Wave-2 contract (a8a16ed): `reframe.models.batch`, `Reframe.batch` skeleton. Checks green: 6707 passed, 2 skipped |
| 2026-10-15 | **Wave 2 started**: 2a (C-12 batch engine, `Reframe.batch`, `reframe batch`; decision 0040). In parallel, follow-ups by the agents that wrote the steps: 1d (in-place jobs in the queue's same-output rule and restore clean-up, the `tool.mkvpropedit_missing` fix, `FileSystemView.writable_file`), 1e (the option rules for templates, the C-8 row, the x265 version note, the n8.1.3 AMF test), 1f (`close()` never cancels an action that is executing: the seam with the CLI's when-done wait) |
| 2026-10-15 | Merged the follow-ups: 1e (C-6: the option rules for templates, the version-aware AMF test, the x265 version; 0035 follow-up): 6714 passed. 1f (C-14: an executing power action runs to its end, `pending` stays `executing` until the executor returns, `close()` waits up to 35 s and never cancels it; 0036 follow-up): 6720 passed. 1d (C-13: in-place jobs in the same-output rule and the restore clean-up, the `tool.mkvpropedit_missing` fix sets a new path, `writable_file` in a separate `WritableFiles` protocol because `tests/validation/scenario.py`'s `FakeFs` lacks it; 0034 follow-up): 6732 passed, 2 skipped; `needs_gpu` 26 passed. Lead decision left open: move `writable_file` into `FileSystemView` (add it to the test `FakeFs` first) |
| 2026-10-15 | The user asked to stop after 2a returns: record the progress in `status.md` and wait for instructions (no review, no demos, no merge into `main` yet) |
| 2026-10-16 | New lead session (the old agents cannot be reached). Checked 2a (`worktree-agent-a3172370b91809950`, 5926ac3, 3 commits): the `BatchService` signatures and the pure functions match the wave-2 contract (only keyword-only additions: `JobService.validate(naming=)`, the new `JobService.name_job`); `draft_from_preset` goes through `reframe.batch.resolve`; `tests/jobs/` and `tests/test_cli.py` unchanged; the M2 draft change (an automatic crop no longer carries a saved rectangle) is recorded in 0040 §6. Files outside 2a's list, all kept: `models/template.py` (`TrackSelector.stream`, the per-file cell pick of 04, an optional field of a `DocumentModel`: no `schema_version` change, 0040 §2), `testing/tests/test_media_fixtures.py` and `test_media_generator.py` (new tests of 2a's fixture recipes only), `tests/jobs/test_cli_batch.py` (a new test file), the plan files 04 / 05 / 09 (edited with 0040), and the shared files (`status.md`, `testdata/README.md`, the schema and probe snapshots, the recorded probes of the anime seasons). Branch checks: ruff, format, mypy (both platforms) green; 6906 passed, 2 skipped |
| 2026-10-16 | Merged 2a (C-12 M7, C-15 `batch`, 0040; C-12 and C-15 **Done**). `status.md` conflict resolved per row against the merge base. Checks: ruff, format, mypy (both platforms) green; 6930 passed, 2 skipped, 1 failed under load (`tests/tools/test_fetch.py::test_fetch_installs_the_build_and_skips_an_intact_install`: its progress went backwards once; 72 / 72 pass alone; given to the review); `needs_gpu` 26 passed. Demo 5 smoke test (`reframe batch … --dry-run` with the demo preset): one group, 12 of 12 files, the E05 and E11 warnings |
| 2026-10-16 | Lead follow-up (05c19b1, C-13, 0034 follow-up): `writable_file` is a member of `FileSystemView` (`FakeFs` has it), `WritableFiles` removed; the runner's check is `LocalFileSystem.writable_file` (on Windows the open for update). Kept as decided in 0037: a change of the when-done setting does not cancel a running countdown (an open user question) |
| 2026-10-16 | **Wave 3, review**: five fresh reviewers (`xhigh`, one area each: R1 C-12 M6, R2 C-12 M7 + C-15 `batch`, R3 C-10, R4 C-13 / C-11 / C-14, R5 C-6 / C-8 / C-15 `tools` / `presets`) on 3cde317. Findings (deduplicated): 3 blockers, 12 majors, 22 minors; the lead ran every blocker and major reproduction again. List and decisions: [0041](decisions/0041-core-complete-review.md). Five fix agents (A C-12 selection, B C-12 batch + C-15, C C-10, D C-13 / C-11 / C-3, E C-6 / C-8 / C-15 tools), all `xhigh` (each group has a blocker or a C-10 / C-11 / C-12 fix); C and D started when R1, R3 and R4 had reported (their files do not meet R2's or R5's areas) |
| 2026-10-16 | Merged fix group A (C-12 selection stage, ff110e7; 0031 and 0006 follow-ups): R1-1 (blocker), R1-2, R1-3, R1-5, R1-6 and the suspected invalid `language_ietf` in `effective_language`, each with a test that failed before. Checks: ruff, format, mypy (both platforms) green; 6954 passed, 2 skipped (core 6751 + server / testing 203; run in two parts, the core part 10:53 under the load of four agents); `needs_gpu` 26 passed. Left by A, recorded in 0031: a source whose every audio track is an extra still gets no audio with `commentary = drop`; the subtitle `first_output` default and the `first` burn-in can pick a commentary that is the only output |
| 2026-10-16 | Merged fix group D (C-11 347ff84, C-13 / C-3 fee150b; 0016, 0034, 0007 follow-ups): R4-1 … R4-6 (job keys compare files; a bounded Matroska reader that skips seek positions past the file, also a `Tracks` bomb; `language_ietf` only from the file; invalid tags dropped with a warning). D's re-measurement found a new blocker, **R4-7** (0041): Reframe's own cancel / `close()` / step limit can kill mkvpropedit late in an in-place edit, 3 of 900 late kills destroyed the source's track headers; given back to D with `queue/runner.py`. Lead: the `language_ietf` docstring (2f43fe9, schema snapshot). Merged fix group C (C-10 f3091f5; 0032, 0033 follow-ups): R3-1 … R3-8 and the scans' tool environment; `SourceAccess.update` added to the contract (this file, 05 §C-15). Both `status.md` conflicts resolved per row. Checks: ruff, format, mypy (both platforms) green; 7009 passed, 2 skipped (three chunks: 1842 + 2709 + 2458); `needs_gpu` 26 passed |
| 2026-10-16 | Merged fix group B (C-12 / C-15, 2d3390f; 0040, 0038, 0035 follow-ups; plan 04 §Grouping, §Per-file overrides, §Output naming and 05 §C-15 with them): R2-1 (blocker: `BatchService.resolve_batch` checks names over every group; `reframe encode` of several files gets the same check, `reframe.jobs.OutputClaims`), R2-2 … R2-8, R1-4, R5-2 (`reframe plan` shows the dry run's issues), the four suspected points, the no-match text. Deviation recorded in 0040: an episode whose planned output is another file of the batch gets `batch.output_is_source` with every collision setting (nothing given to the batch is overwritten). The C-12 row was changed by A and B: merged sentence by sentence. Lead: the `BatchGrouping.issues` docstring (cac17d5). Checks: ruff, format, mypy (both platforms) green; 7033 passed, 2 skipped (1852 + 2723 + 2458); `needs_gpu` 26 passed |
| 2026-10-16 | Merged fix group D's second round (C-13 / C-11, 870717e; 0034 follow-up, `testdata/README.md` "Metadata edit (C-13)"): R4-7 (blocker). A cancel or `close()` never kills a running in-place mkvpropedit: the step has a cancel token of its own, the stop waits for it (a paused step is resumed), and a job stopped after its edit was written ends `cancelled` / `interrupted` with "The edit was already written …"; only the 5-minute step limit still kills a hung mkvpropedit, and its error says the file may be damaged. 300 random cancels through the real queue: 0 damaged files (before: 2), every end matches its file. Then 80ef8a0: the `cancel()` / `close()` docstrings |
| 2026-10-16 | Merged fix group E (C-6 / C-8 a0529f9, C-15 cf894d6 and 71640fe; 0035, 0014, 0038 follow-ups; plan 03 §Advanced encoder options): R5-1 (blocker: custom parameters that make the encoder or FFmpeg read or write a file are `encoder.custom_param_file`, own options outside an allow-list `encoder.custom_param_unknown`; the dry run never starts FFmpeg with them and runs it in a temporary folder), R5-3 … R5-10 (R5-2 was B's), and E's five suspected points (stale `.fetch-*` folders, slow downloads, the tar link check, the `presets import` size cap, dry-run attribution), each real and fixed |
| 2026-10-17 | Merged the test trim (5dbf152): duplicate, low-value and subsumed tests removed and redundant table rows collapsed in ten areas (B, C, M, N, P, Q, R, T, V1, V2), each with a report in `docs/test-trim-reports/` that compares coverage before and after (a test that alone covered a line was put back). The ten reports count 907 tests removed. `status.md`'s count after it: about 6 000 tests (6d6b99a) |
| 2026-10-17 | **Final review**: three fresh reviewers (`xhigh`) on `core-complete` 5dbf152, on `git diff 3cde317..core-complete` (the fix rounds): R-A (C-12 / C-15 batch, `plan`, `encode`), R-B (C-13 / C-11 / C-14 / C-3 queue, Matroska reader, in-place edits, with a stress test on the real mkvpropedit: 1080 stop runs, 0 damaged), R-C (C-6 / C-8 / C-10 / C-15 `tools`). Findings: 1 blocker (RA-1: name checks compared spellings, not files, so a source named through a linked folder was overwritten), 3 majors (RB-1, RB-2, RC-1; the reviewer called RC-1 a blocker, the lead classified it major: no file is written or damaged), 10 minors and a suspected Windows case (`st_ino` 0). The lead ran every blocker and major reproduction again. List and decisions: [0041](decisions/0041-core-complete-review.md) "Final review". Three fix agents (RA, RB, RC) |
| 2026-10-17 | Merged the final-review fixes: RA (C-15 / C-12, ef2fdb6 → 0a78913; 0040, 0038 follow-ups: `reframe.jobs.file_key`, RA-2 … RA-5), RC (C-6 / C-8, 0b93f2d → 47792db; 0035 follow-up: x264 `cqm=<file>` refused, signs in the HDR texts), RB (C-11 / C-13 / C-3, e6a8013 and 9c91444 → 5d82057; 0016, 0034, 0007 follow-ups: the queue's file keys off the event loop, NUL paths, the in-place stop paths, `st_ino` 0, the probe cache fingerprint). Checks after 5d82057: 2660 + 1010 + 2604 + 203 = 6477 passed, 2 skipped; `needs_gpu` 26 passed. Then RN (C-8 / C-15, 11a094f → 4a94c7c; 0016 follow-up "RN": NUL paths in `validation/` and `Reframe.sources`, found by RB outside its files). Checks on 4a94c7c, the full suite run alone in four chunks: 2673 + 1010 + 2611 + 203 = 6497 passed, 2 skipped; `needs_gpu` 26 passed; ruff, format, mypy (both platforms) green. Found by RC and not fixed (a known limit): RC-3, x265 4.3 with deblocking off never finishes a picture narrower than about 256 pixels (0035, 0041) |
| 2026-10-17 | **Demos**: all 8 pass, run for real on 4a94c7c (output in the lead's final report). Demo 1: 2 140 063 b/s measured, stored as `measured`. Demo 3: `metadata_edit` in 0.079 s (limit 1 s; repeat runs 0.071–0.074 s). Demo 5: one group, 12 of 12 files, the E05 / E11 warnings; the second season 3 of 3 ✓. Demo 6: 4K HDR frames at most 0.953 s (limit 2 s); a cancelled scan's ffmpeg gone in 0.020 s (limit 1 s). Demo 8: an export → import → export round trip with an empty diff. Details: 0041 "Demos" |
| 2026-10-17 | Docs: 0041 outcome and final review, this table, `status.md` (the core parts of M6–M9 done, the known limits and open questions of the reviews). **`core-complete` merged into `main`** (`--no-ff`); the lead's final report has the checks on `main` |
