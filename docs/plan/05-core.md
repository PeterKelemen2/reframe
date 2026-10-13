# 05 — Core Package (`reframe`)

The core holds all logic. The web server and the desktop app are thin layers over it. It must
work headless, from a script or from the bundled CLI.

## Rules for the core

- No imports from FastAPI, Tauri, Vue or any UI toolkit. Dependencies: `pydantic`, `psutil`,
  `platformdirs`, `langcodes`, `guessit`. Optional extras: `pymediainfo`
  (`[mediainfo]`), `typer` (`[cli]`).
- The public API is the `Reframe` facade (`C-15`) and `reframe.models`. Everything else is
  internal and can change.
- Async throughout. All subprocess calls go through `reframe.tools.run*` (`C-1`).
- Expected failures return as data (`ValidationIssue`, status enums), not as exceptions.
- mypy strict, ruff, and ≥ 90 % line coverage on pure modules (dimensions, command, batch,
  validation).

## Module layout

```
packages/reframe/src/reframe/
├── __init__.py            # Reframe facade, __version__
├── models/                # media, job, template, preset, settings, issues, events, capabilities
├── tools/                 # runner, discovery, versions
├── probe/                 # ffprobe parsing, enrichment, commercial names, role heuristics
├── capabilities/          # encoder detection, hardware tests, cache
├── dimensions.py          # crop/scale/aspect maths (pure)
├── definitions/           # encoder, option, filter, container definitions
│   └── data/*.toml        # declarative definitions + help texts (read with stdlib tomllib)
├── languages.py
├── command/               # plan builder, filtergraph, video, audio, subtitles, metadata
├── validation/            # rule registry and rules per area
├── presets/               # store, built-ins, migrations
├── settings.py
├── preview/               # frames, cropdetect, preview clips, cache
├── analysis/              # bitrate scan, event count scan, loudness, forced-subtitle scan
├── tasks.py               # background task manager
├── events.py              # async event bus
├── queue/                 # store (SQLite), runner, progress parser, when-done
├── batch/                 # descriptors, fingerprint, rules, resolve
├── naming/                # name source, release-name parsing, templates, safe file names
├── metadata/              # remux + mkvpropedit
├── platform/              # sleep inhibit, power actions, child-process safety
├── service.py             # facade wiring
└── cli.py
```

---

## C-0 Project skeleton

- [ ] Create the uv workspace root `pyproject.toml` with `packages/reframe` and
      `packages/reframe-server` as members. Shared config for ruff and mypy.
- [ ] `packages/reframe/pyproject.toml` with hatchling, `src/` layout, extras as listed above.
- [ ] `pytest` with `anyio`, `hypothesis`, `syrupy`. Markers: `slow`, `needs_ffmpeg`, `needs_gpu`.
- [ ] `scripts/make-testdata.py`: generates small media fixtures with FFmpeg `lavfi` sources
      (see [09 §Test media](09-quality-and-release.md#test-media)).

Done when: `uv run pytest` and `uv run mypy packages/reframe` pass on an empty package in CI on
Linux and Windows.

## C-1 Tool runner and discovery

```python
async def run(argv: Sequence[str], *, timeout: float, cancel: CancelToken | None = None,
              max_output: int = 16 * 2**20, cwd: Path | None = None) -> RunResult
async def run_streaming(argv, *, on_stdout_line, on_stderr_line, cancel, timeout=None) -> RunResult
```

- [ ] `run` returns `RunResult(returncode, stdout, stderr, duration, timed_out, cancelled)`. It
      never raises for a non-zero exit code. It raises only for programming errors.
- [ ] Timeout and cancel kill the **whole process tree** (psutil).
- [ ] Child safety: on Linux, set `PR_SET_PDEATHSIG` (ctypes `prctl` in `preexec_fn`). On
      Windows, children run inside a Job Object with `KILL_ON_JOB_CLOSE`: Reframe puts its own
      process into the job before it starts the first tool, so every child is born in the job
      (no assignment race). If that fails, each child is assigned after start
      ([decision 0005](../decisions/0005-tool-discovery-details.md)). FFmpeg then dies if
      Reframe dies.
- [ ] Windows: `CREATE_NO_WINDOW`, so no console window flashes.
- [ ] Discovery for each tool (`ffmpeg`, `ffprobe`, `mkvpropedit`, `mediainfo`) in the order
      from [02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg): environment variable →
      Settings path → bundled directory → `PATH` (only without a bundled build). Record which
      source won (`ToolInfo.origin = env | settings | bundled | path`) so the UI can show it.
- [ ] `ffprobe` next to an overridden `ffmpeg` is preferred over the bundled `ffprobe`.
- [ ] A broken override gives a `broken`/`missing` status with a reason and a "Use bundled"
      fix. It never falls back to the bundled build without telling the user.
- [ ] Linux, bundled build only: if `LIBVA_DRIVERS_PATH` is not set, set it for the child
      process to the first existing distro driver folder (`/usr/lib/x86_64-linux-gnu/dri`,
      `/usr/lib64/dri`, `/usr/lib/dri`). Keep this only if `D-7` shows that it is needed.
- [ ] Parse versions (`ffmpeg -version`, `mkvpropedit --version`). Set a minimum FFmpeg version
      (7.0). Record build flags (`--enable-libx265`, …) for diagnostics.
- [ ] `ToolStatus` per tool: `found | missing | too_old | broken`, plus a reason.

Done when: tests cover timeout, cancel, a large output limit and a missing binary, on both OSes.

## C-2 Data models

Pydantic v2 models in `reframe.models`. All of them are JSON-serialisable and have JSON Schema.

- [ ] **Media** (`MediaSource`, `VideoStream`, `AudioStream`, `SubtitleStream`, `Chapter`,
      `Attachment`, `ColorInfo`, `HdrInfo`, `Disposition`, `TrackRole`, `BitrateInfo` with a
      `source` field: `stream | stats_tag | mediainfo | measured | unknown`).
- [ ] **Job** (sketch):

```python
class JobSettings(BaseModel):
    schema_version: int = 1
    source: SourceRef                       # path + fingerprint (size, mtime, probe hash)
    range: Range = FullRange()              # | ChapterRange | TimeRange | FrameRange
    output: OutputSettings                  # container, path, web_optimized, align_av_start, passthru_metadata
    dimensions: DimensionSettings           # rotate, flip, crop, size, pixel_aspect, modulus, scaler
    filters: FilterSettings                 # ordered map: filter_id -> FilterConfig(preset, tune, custom)
    video: VideoSettings                    # encoder | passthrough, framerate, rate_control, preset, tune,
                                            # profile, level, bit_depth, advanced: dict[str, OptionValue],
                                            # custom_params: str
    audio: list[AudioOutputTrack]           # source_stream | None, action, encoder, mixdown, samplerate,
                                            # bitrate/quality, gain, drc, loudness, metadata: TrackMetadata
    subtitles: list[SubtitleOutputTrack]    # source_stream | ExternalSubtitle, action (copy|burn|convert),
                                            # forced_only, metadata: TrackMetadata
    chapters: ChapterSettings               # enabled, names, generate_every
    tags: TagSettings
```

- [ ] **Template / preset**: `JobTemplate` = `JobSettings` without source-specific fields +
      `OutputTrackRule` lists + naming template + crop policy ([04](04-batch-mode.md#track-rules)).
      `Preset` = `JobTemplate` + name, category, description, built-in flag.
- [ ] **Audio and subtitle defaults** ([03 §Audio defaults](03-features.md#audio-defaults-stored-in-the-preset)):
      `AudioDefaults(selection: TrackSelection, codec_rules: list[AudioCodecRule], passthru: PassthruPolicy)`.
      `AudioCodecRule(languages | any, source_channels, codec, mixdown, max_bitrate, if_fits:
      passthru | reencode, extras)`. The last rule is a catch-all, and the model enforces it.
      `SubtitleDefaults` reuses `TrackSelection`.
- [ ] **Issues**: `ValidationIssue(severity, code, path, message, fixes: list[Fix])`. `Fix` holds
      an RFC 6902 JSON patch.
- [ ] **Events**: one discriminated union `Event` (see [02 §Events](02-architecture.md#events)).
- [ ] **Capabilities**: `EncoderStatus(id, state, reason, checked_at, supports_10bit, …)`.
- [ ] Every persisted model has `schema_version`. `migrate(data) -> data` functions are
      registered per version.

Done when: a JSON Schema snapshot test exists for all public models. Round trip
(model → JSON → model) is a property test.

## C-3 Probe and track analysis

- [ ] Run `ffprobe -v error -of json -show_format -show_streams -show_chapters -show_programs`
      with a 60 s timeout (network shares can be slow).
- [ ] Parse it into `MediaSource`. Handle: attached pictures (cover art is not a video track),
      attachments (fonts), data streams, VFR (`r_frame_rate` ≠ `avg_frame_rate`; in Matroska
      also `NUMBER_OF_FRAMES` / `DURATION` vs `avg_frame_rate`, then MediaInfo, then a packet
      timestamp sample), interlacing (`field_order`), stream start offsets (`delay`, relative
      to the main video stream, shown as audio delay), and missing durations (decision 0007).
- [ ] **HDR**: read stream side data (mastering display, content light level, DOVI
      configuration). If it is missing, read the first frame's side data
      (`-show_frames -read_intervals %+#5 -select_streams v:0`). Detect HDR10, HDR10+, HLG, and
      Dolby Vision profile. HDR10+ is only in frame side data, so the first frame is read for
      every PQ stream (decision 0006).
- [ ] **Commercial codec names**: map `(codec_name, profile)` to a display name. Examples:
      `dts/DTS-HD MA → DTS-HD MA`, `dts/DTS-HD MA + DTS:X → DTS:X`,
      `truehd/… + Dolby Atmos → TrueHD Atmos`, `eac3/… + Dolby Atmos → E-AC-3 Atmos`,
      `aac/LC → AAC-LC`, `hdmv_pgs_subtitle → PGS`. A table-driven test covers the map.
- [ ] **Bitrate chain**: `bit_rate` → Matroska statistics tags (`BPS`, `BPS-eng`,
      `NUMBER_OF_BYTES` / `DURATION`) → MediaInfo (the pymediainfo library, if it loads) →
      `unknown`. The value records its source. Statistics tags are used only when they are
      plausible for the file (size, bit rate, duration); FFmpeg copies stale ones on re-encode.
      MediaInfo also gives `language_ietf` (Matroska `LanguageIETF`, which ffprobe does not
      show) (decision 0007).
- [ ] **Subtitle event counts** from `NUMBER_OF_FRAMES` tags, when present and plausible.
- [ ] **Role heuristics** (`probe/roles.py`): dispositions first, then title keywords
      (commentary, kommentar, commentaire, comentario, commento, kommentár, コメンタリー; SDH, CC,
      hearing impaired; forced, foreign, signs, songs; audio description, descriptive, AD),
      then structure (a 2.0 track with low bitrate in the same language as a multichannel
      main track → possible commentary). Each role records `evidence: flag | title | heuristic`.
      Keywords match whole words, case-insensitive; the acronyms `AD` and `CC` only in upper
      case. A track with no other role gets `main` (decision 0006).
- [ ] Probe cache: key = absolute path + size + mtime. Stored as JSON in the cache dir.
- [ ] Folder probe: a task with a concurrency limit (default 4) that reports progress.

Done when: snapshot tests of `MediaSource` exist for every fixture file, plus recorded JSON
from real-world ffprobe output (TrueHD Atmos, DTS-HD MA, DTS:X, PGS, ASS with fonts, VFR,
interlaced DVD, HDR10, DV profile 8).

## C-4 Encoder capabilities

This step fixes the HandBrake freeze. Detection runs in the background, has strict timeouts,
and returns statuses, never exceptions.

- [ ] Parse `ffmpeg -hide_banner -encoders` to list the encoders in this build.
- [ ] Parse `ffmpeg -h encoder=<name>` for each known encoder to find its private options and
      presets. Options in the definitions that this build does not support are hidden.
- [ ] **Hardware test encode** for each hardware encoder in the build: encode 3 frames of
      `lavfi color=size=640x360` to `-f null -`, with the encoder's hardware init arguments and
      a 10 s timeout. Run up to 3 tests in parallel. Run an extra 10-bit test where relevant.
- [ ] **Reason mapping**: map known stderr patterns to plain-language reasons. Examples:
      `Cannot load libcuda` → "NVIDIA driver not found";
      `Driver does not support the required nvenc API version` → "NVIDIA driver too old";
      `No VA display found` / `Failed to initialise VAAPI` → "No VAAPI device (/dev/dri)";
      `MFX_ERR_UNSUPPORTED` → "Intel QSV not supported on this GPU". Unknown patterns keep the
      last stderr line.
- [ ] **Cache**: key = ffmpeg path + size + mtime + version, plus a GPU fingerprint (Linux:
      `/sys/class/drm/*/device/{vendor,device}`, `/proc/driver/nvidia/version`. Windows:
      display adapter name + driver version, read once in the background). On start, the cached
      result is used at once and checked again in the background. A change emits
      `capabilities.changed`.
- [ ] States: `unknown → checking → available | unavailable(reason) | error(reason)`.
- [ ] `closest_available(encoder_id) -> encoder_id | None` uses the fallback chain from the
      definitions (`hevc_nvenc → hevc_qsv → hevc_amf → hevc_vaapi → libx265`, etc.).

Done when: the app starts and serves the UI in < 1 s while detection runs. A fake-ffmpeg test
double (a script that sleeps or prints driver errors) proves timeouts and reason mapping. A
preset that references a removed encoder gives `encoder.unavailable` with a fix to the
closest available encoder.

## C-5 Dimensions maths

A pure module with no I/O.

```python
def compute_geometry(src: SourceGeometry, settings: DimensionSettings) -> Geometry
# Geometry: crop rect, scaled size, output SAR, display aspect, upscaled: bool, notes: list[str]
def detect_crop_consensus(samples: list[CropRect], mode: Literal["auto", "conservative"]) -> CropRect
```

- [ ] Size modes: same as cropped source, fit within W×H, exact width, exact height.
- [ ] Pixel aspect: square (scale the anamorphic source to square pixels), keep source PAR,
      custom PAR.
- [ ] Rotation of 90/270 swaps width and height before the size is computed.
- [ ] Modulus rounding keeps the aspect error as small as possible. Crop snaps to the chroma
      grid.
- [ ] `notes` explain every snap or limit ("Crop left 141 → 140 for 4:2:0").

Done when: hypothesis tests prove these properties: the output is inside the fit box; no
upscale unless allowed; the result is a multiple of the modulus; display aspect error
< 0.5 % (or < 1 px); the crop is never negative and never removes the full frame. Table tests
cover the classic cases (DVD NTSC 720×480 anamorphic 16:9, 1080p 2.40:1 letterbox, 4K → 1080p).

## C-6 Definitions: encoders, options, filters, containers, languages

Declarative data in `definitions/data/*.toml`, validated by Pydantic at import.

- [ ] **Video encoders**: id, codec, family, software/hardware, vendor, hardware init args and
      filter tail (for example VAAPI: `-vaapi_device …` and `format=nv12,hwupload`; QSV:
      `-init_hw_device qsv=hw -filter_hw_device hw` and `hwupload=extra_hw_frames=64,format=qsv`),
      rate-control modes with value ranges, presets, tunes, profiles, levels, pixel formats per
      bit depth, fallback chain, quality conversion table.
- [ ] **Encoder option schema** (StaxRip-style):

```python
class EncoderOption(BaseModel):
    key: str                         # "bframes"
    label: str                       # "B-frames"
    category: str                    # "Frame types / GOP"
    type: Literal["int", "float", "bool", "enum", "string"]
    min: float | None = None; max: float | None = None; step: float | None = None
    choices: list[Choice] | None = None
    default: OptionDefault           # fixed value, or per-speed-preset table, or "encoder decides"
    help: str                        # what it does, typical range, quality/speed effect
    mapping: OptionMapping           # x26x_param("bframes") | ffmpeg_arg("-bf") | private_opt("b_ref_mode")
    requires: list[Condition] = []   # e.g. rate_control == "crf"
```

- [ ] Option sets for x264, x265, SVT-AV1, NVENC, QSV, AMF, VAAPI (coverage list in
      [03 §Advanced](03-features.md#advanced-encoder-options)). Include x264/x265 per-preset
      default tables.
- [ ] **Audio encoders**: bitrate ranges per mixdown, **allowed bitrate values** (fixed steps
      for AC-3 / E-AC-3, free ranges for AAC / Opus), sample rates, passthru codecs.
- [ ] **Containers**: allowed video/audio/subtitle codecs, chapter and attachment support, the
      metadata flags each muxer can write.
- [ ] **Filters**: id, FFmpeg implementation, presets/tunes with parameter values (HandBrake
      values mapped to FFmpeg parameters, with the mapping documented), help text sections
      (what / use when / avoid when / speed cost).
- [ ] `languages.py`: search (by name, native name, ISO 639-1/2/3, BCP 47), normalisation,
      `to_matroska_legacy()` (ISO 639-2/B, for example `ger`, `fre`, `chi`), `to_mp4()`
      (ISO 639-2/T), display names. Built on `langcodes`.

Done when: a definitions linter test runs. It checks that every option has help text and a
mapping, that ranges are consistent, and that every fallback chain ends in a software encoder.

## C-7 Command builder

A pure function: `build_plan(job, source, caps, tools) -> EncodePlan`.

```python
class EncodePlan(BaseModel):
    job_type: Literal["encode", "remux", "metadata_edit"]
    steps: list[PlanStep]        # analyse (loudnorm measure) | pass1 | pass2 | encode | mkvpropedit | finalize
    output_tmp: Path             # <name>.part.<ext>
    output_final: Path
    expected_duration: float     # range-adjusted, for progress
    display: str                 # shell-quoted for the command preview (POSIX or Windows style)
```

- [ ] Argument order: global (`-hide_banner -nostdin -y -progress pipe:1 -nostats`) →
      hardware init → input options (range seek) → `-i source` → external subtitle inputs
      (`-itsoffset`, `-sub_charenc`) → chapter metadata input → `-map` with **absolute stream
      indexes** (`0:3`) → filter graph → per-stream codec args → per-stream metadata and
      dispositions → chapters → global tags → container flags (`-movflags +faststart`) → output.
- [ ] **Filter graph builder** (`command/filtergraph.py`): fixed filter order (see
      [03 §Filters](03-features.md#filters)), colour tagging, hardware upload tail, burn-in
      overlay. Correct escaping of filter arguments, including Windows paths in `subtitles=`
      (`C\:/…`). This is a known source of bugs, so it needs dedicated tests.
- [ ] **Video**: rate control, preset/tune/profile/level, `-x264-params` / `-x265-params` /
      `-svtav1-params` assembled from advanced options + colour + HDR metadata. 2-pass for x264
      (`-pass`/`-passlogfile`) and x265 (`pass=`/`stats=` in params).
- [ ] **Audio**: `-c:a:N`, `-b:a:N`, `-ac:a:N`, `-ar:a:N`, `-filter:a:N` (gain, DRC, downmix
      with `aresample=matrix_encoding=dplii`, loudnorm with the measured values from the
      analyse step).
- [ ] **Subtitles**: copy, convert, burn. For MKV, copy attachments (`-map 0:t?`) when ASS
      tracks are copied, so the fonts are kept.
- [ ] **Metadata**: `-metadata:s:<type>:N language=… title=…`, `-disposition:<type>:N
      default+forced+comment+hearing_impaired+visual_impaired+original`. Flags the muxer cannot
      write go to an `mkvpropedit` step.
- [ ] **Chapters**: `-map_chapters 0|-1`, or a generated FFMETADATA file for renamed or
      generated chapters.
- [ ] Tags with `-metadata`. Passthru common metadata = `-map_metadata 0` before the overrides.

Done when: syrupy snapshots of `EncodePlan` exist for ≥ 40 fixture jobs (every encoder family,
every container, burn-in, 2-pass, loudnorm, external subs, range, HDR → SDR). An
integration test runs a subset of plans on fixture media and re-probes the outputs to check
the stream layout, languages, titles and flags.

## C-8 Validation

`validate(job, source, caps, tools, fs) -> list[ValidationIssue]`. The rules are small
functions in a registry, grouped by area.

- [ ] Tools: ffmpeg missing or too old. mkvpropedit is needed but missing.
- [ ] Encoder: unknown, checking, unavailable (with a fix to the closest one), 10-bit not
      supported, option not supported by this build.
- [ ] Container: codec not allowed (with fixes: convert, switch container, drop the track),
      flags not writable.
- [ ] Dimensions: invalid crop, upscaling (warning), odd sizes for 4:2:0.
- [ ] Filters: HDR → SDR conversion without tone mapping (warning, with a fix).
- [ ] Subtitles: more than one burn-in, bitmap subtitle into MP4, forced-only on a format that
      does not support it.
- [ ] Output: path not writable, output = source, name collision, not enough free disk space
      (estimate in bitrate mode).
- [ ] Range is outside the duration.

Done when: every rule has a positive and a negative test, and every fix patch, when applied,
removes its issue.

## C-9 Presets and settings stores

- [ ] Built-in presets ship as JSON inside the package (read-only). User presets are stored in
      `<config>/presets.json`.
- [ ] CRUD, set default, import/export (single preset or all), name-conflict handling.
- [ ] `diff(job_template, preset) -> list[FieldChange]` for the "modified" marker.
- [ ] Settings in `<config>/settings.json`. Atomic writes (temp file + `os.replace`).
- [ ] Migrations for both files. Unknown fields are kept.

Done when: an old-schema fixture loads after migration, export → import gives the same
result, and a corrupt file is backed up and replaced with defaults plus a warning event.

## C-10 Preview and analysis tasks

All of these run as background **tasks** (`tasks.py`): each has an id, progress, cancel, and a
concurrency limit per kind.

- [ ] **Frames**: N evenly spaced timestamps (skip the first and last 5 %). Fast seek (`-ss`
      before `-i`). Output a PNG of the source frame, and of the output frame with the job's
      filter graph applied. Cache key: source fingerprint + timestamp + settings hash. LRU with
      a size limit.
- [ ] **Crop detection**: `cropdetect` on each sample (round=2, a limit that suits HDR/PQ
      black levels). Results per frame → `detect_crop_consensus` (`C-5`).
- [ ] **Preview clip**: encode N seconds from timestamp T with the full plan (as an mkv/mp4 in
      the cache).
- [ ] **Bitrate scan**: packet sizes for one stream (`-show_entries packet=size`) → average
      bitrate. It streams progress and can be cancelled.
- [ ] **Subtitle scans**: event counts. PGS forced-flag count (decode with `forced_subs_only`).
- [ ] **Loudness measure** (`loudnorm` print_format=json) for the analyse step and for preview.

Done when: frames for a 4K HDR fixture come back in < 2 s each on a normal desktop, and
cancelling a scan stops its FFmpeg process within 1 s.

## C-11 Queue and job runner

- [ ] SQLite store: `jobs(id, position, state, settings_json, plan_json, issues_json,
      created_at, started_at, finished_at, output_path, log_path, error)`.
- [ ] Runner loop: when a slot is free (parallel limit), take the next `Waiting` job →
      **validate again** (capabilities can change) → build the plan → run the steps.
- [ ] **Progress parser** for `-progress` blocks (`out_time_us`, `fps`, `speed`, `total_size`,
      `progress=end`). Weighted across steps (pass 1 = 40 %, …). ETA from a smoothed speed.
- [ ] Logs: the full command line + stderr, to `<data>/logs/<job>.log`. Rate-limited
      `job.log` events.
- [ ] Pause and resume: psutil `suspend()` / `resume()` on the process tree.
- [ ] Cancel: kill the tree and remove the `.part` file.
- [ ] Success: rename `.part` → final name (collision policy), run the post steps, re-probe the
      output and check its layout (number of streams, languages).
- [ ] Restart recovery: `Running` → `Interrupted`.
- [ ] When-done actions through `platform/`. Sleep inhibit while any job runs.

Done when: an integration test queues 3 fixture jobs (parallel = 2) and covers pause, resume,
cancel, a failure from a fake encoder error, and a restart with an interrupted job. All
expected events arrive in order.

## C-12 Batch engine

Implements [04-batch-mode.md](04-batch-mode.md): descriptors, fingerprints, grouping, rule
derivation, rule resolution with relaxation, overrides as JSON patches (including parsed-name
overrides for `C-16`), and per-group resolution with a match report.

- [ ] **Audio and subtitle defaults** (needed by M6, before grouping):
  - Selection stage: languages, first/all matching, tie-break, `und`, other languages, no-match
    behaviour, roles, order, default track.
  - Codec-rule stage: first match wins. Bitrate cap: never bigger than the source; passthru
    when the source fits; snap to the allowed encoder values; unknown bitrate counts as above
    the max.
  - `explain(defaults, source) -> list[TrackDecision]`, with a reason string for every
    selected or dropped track and every chosen rule. It feeds the live preview.
  - Lint: shadowed rules, unreachable rules, max bitrate out of range.

Done when: the "Done when" list in [04](04-batch-mode.md#core-api-implemented-in-c-12) passes,
and a table test reproduces the example in
[03 §Audio defaults](03-features.md#audio-defaults-stored-in-the-preset) row by row (Hungarian
5.1 → 320, English 5.1 → 384, AC-3 224 passthru, stereo fallback).

## C-13 Metadata edit and remux

- [ ] Job type detection (`encode`, `remux`, `metadata_edit`) with a reason string.
- [ ] `mkvpropedit` builder:
      `--edit track:a1 --set language=ger --set language-ietf=de --set name="…" --set flag-default=1 --set flag-commentary=1`.
- [ ] Post-mux fix-up step for flags and IETF tags that FFmpeg did not write.
- [ ] After every metadata change, re-probe the file to check the result.

Done when: changing only languages and flags on an MKV fixture runs as `metadata_edit`, takes
< 1 s, and the re-probe shows the new values.

## C-14 Platform services

- [ ] Sleep inhibit: Windows `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`.
      Linux: the logind `Inhibit` D-Bus call, or `systemd-inhibit` as a fallback. If neither
      is available, emit a warning and continue. The Linux lock is `what=sleep:idle`,
      `mode=block`; the D-Bus call uses a small stdlib client (no D-Bus dependency); on
      Windows one dedicated thread sets and clears the state
      ([0011](../decisions/0011-sleep-inhibit.md)).
- [ ] Power actions: shut down, sleep (Windows: `shutdown /s /t 60` and `SetSuspendState`.
      Linux: `systemctl poweroff|suspend`). Always after a cancellable 60 s countdown event.
- [ ] Notification hook: emits an event only. The UI layer shows the notification.

## C-15 Service facade and CLI

```python
class Reframe:
    @classmethod
    async def create(cls, config_dir: Path | None = None, data_dir: Path | None = None) -> Reframe: ...
    events: EventBus
    tools: ToolsService            # status, versions, re-scan
    capabilities: CapabilityService
    sources: SourceService         # probe, probe_folder, get, frames, cropdetect, scans
    presets: PresetService
    jobs: JobService               # draft_from_preset, validate, plan, preview_clip
    batch: BatchService            # group, derive, resolve
    queue: QueueService            # add, list, reorder, start/pause/resume/cancel, logs
    settings: SettingsService
    async def close(self) -> None  # stop the runner, kill children, flush stores
```

- [ ] Wire every service. `create()` returns quickly. Detection and queue restore continue in
      the background.
- [ ] CLI (`reframe` entry point, `[cli]` extra):
      `reframe probe FILE [--json]` · `reframe encoders` · `reframe tools status|fetch` ·
      `reframe name PATH… [--template T]` (prints the name source, parsed fields and the output name) · `reframe presets list|export|import` ·
      `reframe plan FILE --preset NAME` (prints the command) · `reframe encode FILE --preset NAME -o OUT` ·
      `reframe batch DIR --preset NAME [--dry-run]` (prints the resolution matrix).

Done when: the CLI can encode a season folder end to end with no UI. This is the first point
where you can use Reframe for real.

## C-16 Output naming

Implements [03 §Output naming](03-features.md#output-naming).

- [ ] `naming/source.py`: pick the name source (Auto / File / Folder). Skip generic folders,
      detect season packs, score candidates, and return a reason string.
- [ ] `naming/parse.py`: run `guessit` in advanced mode to get each match **with its position**,
      so text fields are cut from the original string and keep their spelling and separators.
      `{main_title}` = the text before the first release tag. For episodes, the show name,
      a year before the episode code, the episode code and the episode title stay. Merge
      folder fields into file fields for season packs.
- [ ] `naming/template.py`: a parser for variables, format specs, `<…>` optional groups, `/`
      subfolders and `{{ }}` escapes. All 17 HandBrake variables, plus the Reframe ones. A
      context is built from the source, the job and the preset. Unknown variables give a
      validation issue with a "did you mean" fix.
- [ ] `naming/sanitize.py`: Windows rules on all OSes, reserved names, a 255-byte limit per
      path part (shorten `{sub_title}`, then `{main_title}`), fallback to `{file_name}`.
- [ ] Clean-up options (HandBrake parity): title case, replace underscores, remove common
      punctuation. Word separator. MP4/M4V rule.
- [ ] Name corpus `testdata/names.toml`: names only, no media, each with the expected fields
      and `{main_title}`. Add your own library's names here to tune the parser.

Done when: the corpus has ≥ 100 real-world cases (movies, episodes, multi-episode codes,
anime with absolute numbers, a year in the show name such as `Doctor.Who.2005`, titles without
separators such as `hacksawridge`, season-pack and movie-folder layouts) and passes, including
the Hacksaw Ridge and Sopranos examples from 03. Every HandBrake variable has a test, and the
Windows sanitising rules have tests on Linux too.
