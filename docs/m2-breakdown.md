# M2 task breakdown: Encode from the CLI

Working notes of the M2 lead. The plan ([plan/08-roadmap.md §M2](plan/08-roadmap.md#m2--encode-from-the-cli),
[plan/05-core.md](plan/05-core.md)) is the spec; this file says who builds which part, in
which order, and what each step must offer to the steps after it. Status: [status.md](status.md).

## Scope

C-4, C-5, C-6 (encoders, containers, filters; basic options), C-7, C-8, C-9, C-11,
C-12 (codec-rule stage of the audio defaults only), C-14 (sleep inhibit only), C-15 (CLI
`encoders`, `plan`, `encode`, `name`), C-16.

C-12's codec-rule stage and the multi-file `reframe encode` were added by the user's
decision [0018](decisions/0018-m2-draft-tracks-and-multi-file-encode.md): an M2 draft job
takes every audio track through the preset's codec rules (no selection stage) and copies
every subtitle track.

## Waves

Each wave runs in parallel, one agent and one git worktree per step. The next wave starts
when the current one is merged into `m2-encode-cli` and every check is green.

| Wave | Steps | Builds on |
|------|-------|-----------|
| 1 | C-4, C-5, C-6, C-14, C-16 | M1, this contract |
| 2 | C-7, C-8, C-9, C-12 (codec rules) | wave 1 |
| 3 | C-11, C-15 | wave 2 |

## Who owns which files

An agent edits only the files of its step. A change anywhere else goes back to the lead.

| Step | Owns |
|------|------|
| C-4 | `reframe/capabilities/` (new), `reframe/models/capabilities.py` (additions only), the `capabilities` wiring in `reframe/service.py`, `testing/reframe_testing/` (fake data and scenarios it needs), `tests/capabilities/` |
| C-5 | `reframe/dimensions.py` (new), `tests/test_dimensions.py` or `tests/dimensions/` |
| C-6 | `reframe/definitions/` (code and `data/*.toml`), `tests/definitions/` |
| C-14 | `reframe/platform/sleep.py` (new; more modules under `reframe/platform/` if needed), `tests/platform/test_sleep*.py` |
| C-16 | `reframe/naming/` (new), `reframe/models/naming.py`, `JobNaming` in `reframe/models/job.py` (new fields only), `testdata/names.toml`, `tests/naming/` |
| C-7 | `reframe/command/` (new), `tests/command/` |
| C-8 | `reframe/validation/` (new), `tests/validation/` |
| C-9 | `reframe/presets/` (new), `reframe/settings.py` (new), the `settings` / `presets` wiring in `reframe/service.py`, `tests/presets/`, `tests/test_settings.py` |
| C-12 (codec rules) | `reframe/batch/` (new; the audio defaults part), `reframe/models/defaults.py` (additions: the track decision model), `tests/batch/` |
| C-11 | `reframe/queue/` (new), the `queue` wiring in `reframe/service.py`, `tests/queue/` |
| C-15 | `reframe/cli.py`, the `jobs` service in `reframe/service.py`, `tests/test_cli.py` |

Shared files:

- `docs/status.md`: each agent updates only its own step row (and the feature rows its step
  changes). The lead resolves merge conflicts.
- `testdata/README.md`: each agent writes real tool behaviour under its own heading in
  "Verified tool behaviour" (placeholders exist for wave 1).
- `reframe/models/`: new public models need `__all__`, the schema snapshot
  (`uv run pytest packages/reframe/tests/models/test_schema.py --snapshot-update`) and a
  round-trip test. The lead regenerates the snapshot file when two branches touch it.
- A new core dependency is a plan change (05 §Rules for the core lists them): decision record.

## Decision record numbers

Next free was 0008. One record per step; a step with several topics uses sections in its one
record. Numbers that end up unused are noted at the end of the milestone.

| 0008 | 0009 | 0010 | 0011 | 0012 | 0013 | 0014 | 0015 | 0016 | 0017 | 0018 | 0019 | 0020+ |
|------|------|------|------|------|------|------|------|------|------|------|------|-------|
| C-4 | C-5 | C-6 | C-14 | C-16 | C-7 | C-8 | C-9 | C-11 | C-15 | lead (used) | C-12 | lead (0020–0024 used; next 0025) |

## Interfaces between the steps

Signatures are binding. A step may add keyword-only parameters with defaults and extra
functions, but not change these. Expected failures are data, never exceptions.

### Built by the lead before wave 1 (commit "M2 contract")

- `reframe.models.CapabilitySnapshot`: every encoder's `EncoderStatus` by id (video and
  audio encoders of the definitions), `filters` of the build (`None` until read),
  `ffmpeg`, `ffmpeg_version`, `detecting`, `from_cache`, `checked_at`;
  `status(encoder_id)` (unknown when not listed), `has_filter(name)`.
- `reframe.definitions`: every video encoder (x264, x265, SVT-AV1, VP9; NVENC, QSV, AMF
  H.264/H.265/AV1; VAAPI H.264/H.265/AV1) with identity, platforms, pixel formats per bit
  depth, hardware setup and fallback chain, checked on real hardware (see the header of
  `video_encoders.toml`). `AudioEncoderDef` (id, label, codec) for aac, libfdk_aac, ac3,
  eac3, libopus, flac, libmp3lame.

### Wave 1 offers

**C-4 `reframe.capabilities`**

```python
class CapabilityService:
    def __init__(self, events: EventBus, tools: ToolsService, settings: SettingsGetter, *,
                 cache_dir: Path, definitions: Definitions | None = None) -> None: ...
    def start(self) -> None                         # cached result at once, detection in the background
    @property
    def snapshot(self) -> CapabilitySnapshot        # never waits
    async def wait(self) -> CapabilitySnapshot      # waits for a running detection (starts one if none ran)
    async def rescan(self) -> CapabilitySnapshot
    def closest_available(self, encoder_id: str) -> str | None
    async def close(self) -> None                   # kills running test encodes

def closest_available(encoder_id: str, caps: CapabilitySnapshot,
                      definitions: Definitions) -> str | None   # pure
```

`Reframe.capabilities` is wired in `reframe/service.py` (started in `create()`, closed in
`close()`); `create()` stays fast. A changed status publishes `capabilities.changed`. The
snapshot also lists the build's filters (`ffmpeg -hide_banner -filters`): C-7 needs it to
choose `libplacebo` or `zscale,tonemap` (03 §Filters).

**C-5 `reframe.dimensions`** (pure)

```python
def compute_geometry(src: SourceGeometry, settings: DimensionSettings) -> Geometry
def detect_crop_consensus(samples: Sequence[CropRect],
                          mode: Literal["auto", "conservative"]) -> CropRect
def source_geometry(stream: VideoStream) -> SourceGeometry
```

**C-6 `reframe.definitions`** (pure, package data only)

- `load_definitions()` returns `Definitions` with `video_encoders` (plus rate-control modes
  and ranges, presets and the default preset, tunes, profiles, levels, the `-x26x-params`
  style argument, the basic options with the `EncoderOption` schema, quality conversion),
  `audio_encoders` (bitrate ranges per mixdown, allowed bitrate values, sample rates,
  default bitrate), `containers` (`mkv`, `mp4`, `webm`: allowed codecs, chapters,
  attachments, writable flags, the extension) and `filters` (FFmpeg implementation, presets
  and tunes with parameter values, help text, position in the fixed order).
- `convert_quality(value: float, from_encoder: str, to_encoder: str) -> float`.
- `supported_options(encoder: VideoEncoderDef, status: EncoderStatus | None) -> list[EncoderOption]`:
  hides options that this build does not support (05 §C-4, bullet 2).
- The definitions linter: `lint_definitions(defs: Definitions) -> list[str]` and its test.

**C-14 `reframe.platform.sleep`**

```python
class InhibitState(StrEnum): INACTIVE, ACTIVE, UNAVAILABLE
class SleepInhibitor:
    async def acquire(self, reason: str) -> InhibitState   # counted; the first call takes the OS lock
    async def release(self) -> None                         # the last release frees it
    @property
    def state(self) -> InhibitState
    async def close(self) -> None                           # frees it whatever the count
def create_sleep_inhibitor(events: EventBus | None = None) -> SleepInhibitor   # backend per OS
```

When no backend works: one `app.warning` event (`sleep_inhibit.unavailable`), then go on.

**C-16 `reframe.naming`**

```python
def resolve_output_name(file: Path, options: NamingOptions, *,
                        job: JobSettings | None = None, source: MediaSource | None = None,
                        output_size: tuple[int, int] | None = None,
                        container: Container | None = None, root: Path | None = None,
                        now: datetime | None = None, title_index: int = 1) -> NameResult
def check_template(template: str) -> list[ValidationIssue]   # unknown variables, "did you mean"
```

`NameResult` (in `reframe.models.naming`) has at least: the chosen name source (`file` or
`folder`) and the reason, the candidates with scores, the parsed fields, the rendered
relative path (with `/` subfolders and the extension), the full `path` when the output
folder is known, notes (shortening, sanitising) and `issues`. `output_size` is C-5's scaled
size (the caller computes it); `container` is used when `job` is `None` (default `mkv`).
File-system reads (the folder listing for season packs) go through one small function that
tests can replace.

### Wave 2 offers (contract written by the lead after wave 1 was merged)

What wave 1 delivered (read the code; the names below are the ones to use):

- C-4 `reframe.capabilities`: `CapabilitySnapshot` (`status(id)`, `has_filter`,
  `usable_filter` after the C-4 follow-up), `closest_available(id, caps, defs)`,
  `encoder_issues(id, caps, defs, *, path, target, subject)` (codes `encoder.unknown`,
  `encoder.checking` (info), `encoder.untested` (warning), `encoder.unavailable` with the
  closest-match fix), `field_pointer(path)`. Decision 0008. VAAPI encoders carry their render
  node in the status (follow-up, decision 0020).
- C-5 `reframe.dimensions`: `compute_geometry`, `source_geometry`, `detect_crop_consensus`;
  the filter chain and the crop orientation are fixed by decision 0009 (automatic rotation
  on; `crop` only when an edge is non-zero; transpose for `filter_rotation`; `hflip`;
  `scale`; `setsar` always after `scale`). Portrait fit: decision 0020.
- C-6 `reframe.definitions`: `load_definitions()` → video encoders (rate control, presets,
  tunes, profiles, levels, params argument, basic options), audio encoders (bitrates per
  mixdown, `snap`, fallback), `containers` (`CodecSupport.can_copy`, `encode`,
  `text_subtitle_target`, `codec_tags`, `copy_args`, flags, `language_format`), `filters`
  and `filter_order` (`FilterDef.implementation_for`, `chain_for`); `convert_quality`,
  `supported_options`, `supported_presets`. Decision 0010.
- C-14 `reframe.platform.sleep`: `create_sleep_inhibitor`. Decisions 0011, 0020.
- C-16 `reframe.naming`: `resolve_output_name`, `check_template`, `output_extension`.
  Decision 0012.
- Lead: `reframe.models.FieldChange` (for C-9).

**C-7 `reframe.command`** (pure: no I/O, no clock, no subprocess)

```python
def build_plan(job: JobSettings, source: MediaSource, caps: CapabilitySnapshot, tools: ToolSet, *,
               definitions: Definitions | None = None,
               shell: Literal["posix", "windows"] | None = None) -> EncodePlan
def job_type(job: JobSettings, source: MediaSource, *,
             definitions: Definitions | None = None) -> tuple[JobType, str]   # with the reason
class PlanError(ValueError): ...   # the job cannot be planned (it has validation errors)
```

- `job.output.path` is the final path (naming resolved it). `output_tmp` is
  `<stem>.part.<ext>` next to it. `shell=None` = the style of this OS.
- The caller runs `validate()` first; `build_plan` on a job with validation errors is a
  programming error (`PlanError`), never a half-built plan.
- M2 job types: `encode`, `remux` (video passthrough and every track copied).
  `metadata_edit` is C-13 (M6).
- Open item from docs/status.md: FFmpeg writes language codes verbatim: ISO 639-2/B to
  Matroska, ISO 639-2/T to MP4 (`reframe.languages`), and set every disposition explicitly
  (FFmpeg's Matroska muxer leaves single streams without the default flag).

**C-8 `reframe.validation`**

```python
def validate(job: JobSettings, source: MediaSource, caps: CapabilitySnapshot, tools: ToolSet,
             fs: FileSystemView, *, settings: AppSettings | None = None,
             definitions: Definitions | None = None) -> list[ValidationIssue]
def validate_template(template: JobTemplate, caps: CapabilitySnapshot, *,
                      subject: str | None = None,
                      definitions: Definitions | None = None) -> list[ValidationIssue]  # fixes target "template"
class FileSystemView(Protocol): ...   # exists, is_dir, writable_dir, free_bytes, same_file …
class LocalFileSystem: ...            # the real one (no subprocess)
```

- Rules are small functions in a registry, grouped by area (05 §C-8). C-4's
  `encoder_issues` is the encoder rule; C-8 adds the quality conversion (`convert_quality`)
  to the closest-match fix. C-16's issues (`resolve_output_name(...).issues`,
  `check_template`) are the naming rule.
- `validate_template` covers what a preset alone can be checked for (encoder, container
  codecs, naming template): M2 demo item 4.

**C-9 `reframe.settings`, `reframe.presets`**

```python
class SettingsStore:                       # <config>/settings.json, atomic writes, migrations
    def __init__(self, config_dir: Path, events: EventBus | None = None) -> None: ...
    def load(self) -> AppSettings          # corrupt → backed up, defaults, app.warning
    def save(self, settings: AppSettings) -> None
def builtin_presets() -> list[Preset]      # JSON inside the package, read-only
class PresetStore:                         # <config>/presets.json
    def __init__(self, config_dir: Path, events: EventBus | None = None) -> None: ...
    # list, get(id), find(name), save, delete, rename, duplicate, set_default, default,
    # export(ids) -> PresetFile, import_(PresetFile, on_conflict) …
def diff(template: JobTemplate, preset: JobTemplate) -> list[FieldChange]
```

- `Reframe.settings` (get, update, the settings getter of every service) and
  `Reframe.presets` (built-in + user presets) in `reframe/service.py`; `_load_settings`
  is replaced. A change of the tool paths re-runs tool discovery; a change of
  `encoders.hardware_tests` or `encoders.vaapi_device` calls `capabilities.rescan()`.
- Built-in presets modelled on HandBrake's (categories of `BUILT_IN_CATEGORIES`), using
  only encoders, containers and filters of the definitions, including **"H.265 MKV 1080p"**
  (M2 demo item 2) and at least one hardware preset (an NVENC one, for demo item 4).

**C-12 (codec rules) `reframe.batch`**

```python
def apply_codec_rules(stream: AudioStream, defaults: AudioDefaults, container: Container, *,
                      definitions: Definitions | None = None
                      ) -> tuple[list[AudioOutputTrack], TrackDecision]
def draft_tracks(source: MediaSource, template: JobTemplate, *,
                 definitions: Definitions | None = None) -> TrackDraft
# TrackDraft: audio: list[AudioOutputTrack], subtitles: list[SubtitleOutputTrack],
#             decisions: list[TrackDecision]
```

- `TrackDecision` (a model in `reframe/models/defaults.py`): source stream, rule number,
  outputs, the reason string (the "why" column of 03 §Audio defaults → Live preview).
- Decision 0018: every audio track goes through the codec rules in source order; every
  subtitle is copied; language, title and flags come from the source track.

### Wave 3 offers

- **C-11** `reframe.queue`: SQLite store, runner, `-progress` parser, `Reframe.queue`.
  `run_streaming(..., on_start=callback)` gives the pid of the started process for
  pause/resume (built by the lead, commit "C-1: pid hook …").
- **C-15** `Reframe.jobs` (`draft_from_preset`, `validate`, `plan`) and the CLI commands
  `encoders`, `plan`, `encode FILE|DIR… --preset NAME [-o OUT]` (decision 0018), `name`.

## Decided questions

- Product questions of wave 1 (sleep inhibit, portrait fit, VAAPI device, audio fallback):
  decision [0020](decisions/0020-m2-wave-1-product-decisions.md).
- Which audio and subtitle tracks does an M2 draft job get, and how does the CLI encode a
  season? The user's answer is decision
  [0018](decisions/0018-m2-draft-tracks-and-multi-file-encode.md).
