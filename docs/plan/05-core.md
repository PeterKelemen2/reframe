# 05 — Core Package (`reframe`)

The core holds all logic. The web server and the desktop app are thin layers over it. It must
work headless, from a script or from the bundled CLI.

## Rules for the core

- No imports from FastAPI, Tauri, Vue or any UI toolkit. Dependencies: `pydantic`, `psutil`,
  `platformdirs`, `guessit`. Optional extra: `typer` (`[cli]`). No `[mediainfo]` extra since
  C-19 ([decision 0081](../decisions/0081-probe-without-mediainfo.md)).
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
├── metadata/              # remux, Matroska header writer (C-18)
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
async def run_streaming(argv, *, on_stdout_line, on_stderr_line, cancel) -> RunResult  # no timeout: cancel stops it
```

- [ ] `run` returns `RunResult(returncode, stdout, stderr, duration, timed_out, cancelled)`. It
      never raises for a non-zero exit code. It raises only for programming errors.
- [ ] Timeout and cancel kill the **whole process tree** (psutil).
- [ ] Child safety: on Linux, set `PR_SET_PDEATHSIG` (ctypes `prctl` in `preexec_fn`; under a
      tracer such as coverage, `prctl` alone bound with `functools.partial`, so no Reframe Python
      code runs in the forked child:
      [decision 0092](../decisions/0092-no-reframe-python-code-in-a-forked-child.md)). On
      Windows, children run inside a Job Object with `KILL_ON_JOB_CLOSE`: Reframe puts its own
      process into the job before it starts the first tool, so every child is born in the job
      (no assignment race). If that fails, each child is assigned after start
      ([decision 0005](../decisions/0005-tool-discovery-details.md)). FFmpeg then dies if
      Reframe dies.
- [ ] Windows: `CREATE_NO_WINDOW`, so no console window flashes.
- [ ] Discovery for each tool (`ffmpeg`, `ffprobe`; `mediainfo` until C-19) in the order
      from [02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg): environment variable →
      Settings path → bundled directory → `PATH` (only without a bundled build). Record which
      source won (`ToolInfo.origin = env | settings | bundled | path`) so the UI can show it.
      mkvpropedit, and with it the `installed` origin (MKVToolNix's install folder on
      Windows), leaves discovery with C-18
      ([decision 0080](../decisions/0080-own-matroska-header-writer.md)).
- [ ] `ffprobe` next to an overridden `ffmpeg` is preferred over the bundled `ffprobe`.
- [ ] A broken override gives a `broken`/`missing` status with a reason and a "Use bundled"
      fix. It never falls back to the bundled build without telling the user.
- [ ] Linux, bundled build only: if `LIBVA_DRIVERS_PATH` is not set, set it for the child
      process to every existing distro driver folder, joined by `:` (`/usr/lib/x86_64-linux-gnu/dri`,
      `/usr/lib64/dri-nonfree`, `/usr/lib64/dri-freeworld`, `/usr/lib64/dri`, `/usr/lib/dri`;
      the bundled libva's built-in path is the same list, [0002](../decisions/0002-bundled-ffmpeg.md)
      "Follow-up: Fedora with RPM Fusion's VA drivers"). Keep this only if `D-7` shows that it
      is needed.
- [ ] Parse versions (`ffmpeg -version`). Set a minimum FFmpeg version
      (7.0). Record build flags (`--enable-libx265`, …) for diagnostics.
- [ ] `ToolStatus` per tool: `found | missing | too_old | broken`, plus a reason.

Done when: tests cover timeout, cancel, a large output limit and a missing binary, on both OSes.

## C-2 Data models

Pydantic v2 models in `reframe.models`. All of them are JSON-serialisable and have JSON Schema.

- [ ] **Media** (`MediaSource`, `VideoStream`, `AudioStream`, `SubtitleStream`, `Chapter`,
      `Attachment`, `ColorInfo`, `HdrInfo`, `Disposition`, `TrackRole`, `BitrateInfo` with a
      `source` field: `stream | stats_tag | estimated | measured | unknown`; `estimated` replaces
      `mediainfo` with C-19).
- [ ] **Job** (sketch):

```python
class JobSettings(BaseModel):
    schema_version: int = 1
    source: SourceRef                       # path + fingerprint (size, mtime)
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
      also `NUMBER_OF_FRAMES` / `DURATION` vs `avg_frame_rate`, then a packet timestamp sample), interlacing (`field_order`), stream start offsets (`delay`, relative
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
      `NUMBER_OF_BYTES` / `DURATION`) → for Matroska, the sampled estimate of C-19 → `unknown`.
      The value records its source. Statistics tags are used only when they are plausible for
      the file (size, bit rate, duration; a compressed track's `NUMBER_OF_BYTES` is left out of
      the size check, C-19); FFmpeg copies stale ones on re-encode.
      `language_ietf` is the file's BCP 47 tag (Matroska `LanguageIETF`, which ffprobe does
      not show): for Matroska, Reframe's own track reader gives it (`None` when the track has
      none); for other containers it is derived from the ISO 639 code (decision 0007 and its follow-ups,
      decision 0034, [decision 0081](../decisions/0081-probe-without-mediainfo.md)).
- [ ] **Subtitle event counts** from `NUMBER_OF_FRAMES` tags, when present and plausible.
- [ ] **Role heuristics** (`probe/roles.py`): dispositions first, then title keywords
      (commentary, kommentar, commentaire, comentario, commento, kommentár, コメンタリー; SDH, CC,
      hearing impaired; forced, foreign, signs, songs; audio description, descriptive, AD),
      then structure (a 2.0 track with low bitrate in the same language as a multichannel
      main track → possible commentary). Each role records `evidence: flag | title | heuristic`.
      Keywords match whole words, case-insensitive; the acronyms `AD` and `CC` only in upper
      case. A track with no other role gets `main` (decision 0006).
- [ ] Probe cache: key = absolute path + size + mtime. Stored as JSON in the cache dir.
- [ ] Many files: `SourceService.probe_many` probes a list of files with a concurrency limit
  (default 4), in the order of the list, with progress; after a cancel no new ffprobe starts
  ([0089](../decisions/0089-folder-probe-and-language-list-removed.md); the server lists a
  folder's files itself).

Done when: snapshot tests of `MediaSource` exist for every fixture file, plus recorded JSON
from real-world ffprobe output (TrueHD Atmos, DTS-HD MA, DTS:X, PGS, ASS with fonts, VFR,
interlaced DVD, HDR10, DV profile 8).

## C-4 Encoder capabilities

This step fixes the HandBrake freeze. Detection runs in the background, has strict timeouts,
and returns statuses, never exceptions.

- [ ] Parse `ffmpeg -hide_banner -encoders` to list the encoders in this build.
- [ ] Parse `ffmpeg -hide_banner -filters` into the snapshot's filter list
      ([decision 0008](../decisions/0008-encoder-detection-reasons-and-filters.md)).
      `libplacebo` also needs a working Vulkan device, which the list cannot show: detection
      runs one frame through it (same timeout, cancel and parallel limit as the test encodes;
      not run when hardware tests are off). `C-7` chooses `libplacebo` only when
      `CapabilitySnapshot.usable_filter("libplacebo")` is true, else `zscale,tonemap`
      ([decision 0021](../decisions/0021-libplacebo-run-test.md)).
- [ ] Parse `ffmpeg -h encoder=<name>` for each known encoder to find its private options and
      presets. Options in the definitions that this build does not support are hidden.
- [ ] **Hardware test encode** for each hardware encoder in the build: encode 3 frames of
      `lavfi color=size=640x360` to `-f null -`, with the encoder's hardware init arguments and
      a 10 s timeout. Run up to 3 tests in parallel. Run an extra 10-bit test when the
      encoder's definition has a 10-bit pixel format (result: `supports_10bit`). VAAPI
      encoders are tested on every render node (`/dev/dri/renderD*`); each uses the first node
      that works, unless Settings → Encoders forces one ([decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)).
- [ ] **Reason mapping** ([decision 0008](../decisions/0008-encoder-detection-reasons-and-filters.md)):
      map the texts that real FFmpeg prints (recorded in `testdata/README.md`) to
      plain-language reasons. Examples: `Cannot load libcuda.so.1` → "NVIDIA driver not
      found"; `Driver does not support the required nvenc API version` → "NVIDIA driver too
      old"; `No VA display found for device X` → "No VAAPI device (X)";
      `Failed to initialise VAAPI connection` → "VAAPI driver failed to start";
      `Error creating a MFX session` → "No Intel QSV device or runtime"; `DLL libamfrt64.so.1 failed
      to open` → "AMD AMF runtime not found". A known text gives `unavailable`. Any other
      failure gives `error` with the most informative line: the first line that the encoder
      logs (`[hevc_nvenc @ …]`), else the first line of a hardware device (`[VAAPI @ …]`),
      else the first line that is not fftools bookkeeping. Never the last line: it is a
      generic `Conversion failed!`.
- [ ] **Busy GPU** ([decision 0101](../decisions/0101-nvenc-session-limit-and-older-build-hint.md)):
      an NVENC session error comes before `No capable devices found` (FFmpeg skips the GPU,
      so that line always follows). Status 21 (`incompatible client key`, the GeForce limit
      of concurrent sessions) means the GPU is busy: the test runs again twice (after 2 s,
      then 4 s, outside the parallel limit), and a test that stays busy gives `error` with
      "Every NVENC session of the GPU is in use by other programs …", never `unavailable`.
      A job that fails on it gets the same cause in plain words.
- [ ] **Cache**: key = ffmpeg path + size + mtime + version, plus a GPU fingerprint (Linux:
      `/sys/class/drm/*/device/{vendor,device}`, `/proc/driver/nvidia/version`. Windows:
      display adapter name + driver version, read once in the background). On start, the cached
      result is used at once and checked again in the background: the full detection runs, and
      the cached statuses stay until their new results are in. While that check runs, a
      cached status that is not *available* is reported to validation as `encoder.checking`,
      so a job waits for the new result instead of failing on a stale one (drivers can change
      without changing the fingerprint; [0008](../decisions/0008-encoder-detection-reasons-and-filters.md),
      follow-up of the M2 review). A change emits `capabilities.changed`. A new ffmpeg
      (`tools.changed`) starts a new detection.
- [ ] States: `unknown → checking → available | unavailable(reason) | error(reason)`.
- [ ] `closest_available(encoder_id) -> encoder_id | None` uses the fallback chain from the
      definitions (`hevc_nvenc → hevc_qsv → hevc_amf → hevc_vaapi → libx265`, etc.), for
      video and audio encoders (`libfdk_aac → aac`, [decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)).

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
def source_geometry(stream: VideoStream) -> SourceGeometry
```

- [ ] Size modes: same as cropped source, fit within W×H, exact width, exact height.
- [ ] Pixel aspect: square (scale the anamorphic source to square pixels), keep source PAR,
      custom PAR.
- [ ] Rotation of 90/270 swaps width and height before the size is computed.
- [ ] Modulus rounding keeps the aspect error as small as possible. Crop snaps to the chroma
      grid.
- [ ] `notes` explain every snap or limit ("Crop left 141 → 140 for 4:2:0").
- [ ] Conventions ([decision 0009](../decisions/0009-dimension-maths-conventions.md)): the crop
      is measured on the picture as FFmpeg decodes it (display matrix applied, job rotation
      not yet); the filter chain for `C-7` (automatic rotation on, then crop → transpose →
      hflip → scale → setsar); upscaling is measured against the display size (DVD 16:9 →
      854×480 is not an upscale); the rounding rule. The fit box turns for portrait output
      ([decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)).

Done when: hypothesis tests prove these properties: the output is inside the fit box; no
upscale unless allowed; the result is a multiple of the modulus; display aspect error
< 0.5 % (or < 1 px); the crop is never negative and never removes the full frame. Corner
cases are defined, not skipped ([0009](../decisions/0009-dimension-maths-conventions.md)): a
fit box or a picture smaller than one modulus step gives one step on that axis, and when no
size inside the limits meets the aspect tolerance, the closest one is used (the test proves
that none exists). Table tests cover the classic cases (DVD NTSC 720×480 anamorphic 16:9,
1080p 2.40:1 letterbox, 4K → 1080p).

## C-6 Definitions: encoders, options, filters, containers, languages

Declarative data in `definitions/data/*.toml`, validated by Pydantic at import.

- [ ] **Video encoders**: id, codec, family, software/hardware, vendor, hardware init args and
      filter tail (for example VAAPI: `-vaapi_device …` and `format=nv12,hwupload`; NVENC, AMF
      and QSV take software frames, [0095](../decisions/0095-qsv-takes-software-frames.md)),
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
      for AC-3 / E-AC-3, free ranges for AAC / Opus), sample rates, passthru codecs, fallback
      chain (`libfdk_aac → aac`, [decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)).
- [ ] **Containers**: allowed video/audio/subtitle codecs, chapter and attachment support, the
      metadata flags each muxer can write.
- [ ] **Filters**: id, FFmpeg implementation, presets/tunes with parameter values (HandBrake
      values mapped to FFmpeg parameters, with the mapping documented), help text sections
      (what / use when / avoid when / speed cost).
- [ ] `languages.py`: search (by name, native name, ISO 639-1/2/3, BCP 47), normalisation,
      `to_matroska_legacy()` (ISO 639-2/B, for example `ger`, `fre`, `chi`), `to_mp4()`
      (ISO 639-2/T), display names. Built on a generated language table (C-20,
      [decision 0082](../decisions/0082-own-language-data-table.md)); `langcodes` and
      `language_data` are dev tools that build it.

Done when: a definitions linter test runs. It checks that every option has help text and a
mapping, that ranges are consistent, and that every fallback chain ends in a software encoder.

## C-7 Command builder

A pure function: `build_plan(job, source, caps, tools) -> EncodePlan`.

```python
class EncodePlan(BaseModel):
    job_type: Literal["encode", "remux", "metadata_edit"]
    steps: list[PlanStep]        # analyse (loudnorm measure) | pass1 | pass2 | encode | header_edit | finalize
    output_tmp: Path             # <name>.part.<ext>
    output_final: Path
    expected_duration: float     # range-adjusted, for progress
    display: str                 # shell-quoted for the command preview (POSIX or Windows style)
    files: list[PlanFile]        # written before the first step (FFMETADATA chapters)
    temp_files: list[Path]       # removed when the job ends (2-pass statistics; 0013)
```

- [ ] Argument order: global (`-hide_banner -nostdin -y -progress pipe:1 -nostats`) →
      hardware init → input options (decoder options `-drc_scale` / `-forced_subs_only`,
      range seek `-ss`) → `-i source` → external subtitle inputs (`-itsoffset`, `-ss`,
      `-sub_charenc`) → chapter metadata input → `-map` with **absolute stream indexes**
      (`0:3`) → `-ss 0` when the video is encoded and a stream could start before 0 (a
      range, a negative subtitle offset: nothing reaches the muxer before 0; 0013 "Follow-up
      (M2 review)") → range end (`-t`, an output option, so FFmpeg cuts the copied chapters) →
      filter graph → per-stream codec args → per-stream metadata and dispositions (no source
      stream tags: `-map_metadata:s -1`) → chapters → global tags → container flags
      (`-movflags +faststart`, `-strict -2`) → `-f <muxer>` → output
      ([decision 0013](../decisions/0013-command-builder-details.md)).
- [ ] **Filter graph builder** (`command/filtergraph.py`): fixed filter order (see
      [03 §Filters](03-features.md#filters)), colour tagging (`setparams` for untagged
      sources), HDR metadata removed after tone mapping, hardware upload tail, burn-in (text
      last, bitmap `overlay` after the crop, in 10 bits for a deeper source; 0013). Correct
      escaping of filter arguments,
      including Windows paths in `subtitles=` (`C\:/…`). This is a known source of bugs, so it
      needs dedicated tests.
- [ ] **Video**: rate control, preset/tune/profile/level, `-x264-params` / `-x265-params` /
      `-svtav1-params` assembled from advanced options + colour + HDR metadata. 2-pass for x264
      (`-pass`/`-passlogfile`) and x265 (`pass=`/`stats=` in params); the statistics files are
      listed in `EncodePlan.temp_files` for the runner to remove. Frame rate: constant
      `-r -fps_mode cfr` ("same as source" = the rate after the filters: twice the
      source's after a Bob deinterlacer, 4/5 of it after detelecine), peak `-fpsmax`
      (0013).
- [ ] **Audio**: `-c:a:N`, `-b:a:N`, `-ar:a:N` (always), `-filter:a:N` (output layout and
      downmix with `aresample=[matrix_encoding=dplii:]out_chlayout=…`, gain, loudnorm with the
      measured values of the track's own analyse step); DRC is the AC-3 decoder's
      `-drc_scale` (0013). A bitrate, mixdown or sample rate the encoder cannot do is snapped
      to an allowed value with C-6's helpers, which C-8 and C-12 share: a mixdown never
      upmixes and otherwise becomes the encoder's largest layout below (AC-3 7.1 → 5.1); a
      bitrate is clamped to the range of the effective mixdown and goes down to the next
      allowed step (as HandBrake does); a sample rate goes to the nearest listed rate.
      Validation shows it as info ([decision 0024](../decisions/0024-m2-wave-2-product-decisions.md),
      0013 "Follow-up (M2 wave 2b)"). libopus gets a channel layout it accepts (side → back,
      else the largest accepted layout of the source's channels); other encoders get the
      source layout, relabelled only where that is lossless (0013 "Follow-up (M2 review)").
- [ ] **Subtitles**: copy, convert, burn. For MKV, copy attachments (`-map 0:t?`) when ASS
      tracks are copied, so the fonts are kept.
- [ ] **Metadata**: `-metadata:s:<type>:N language=… title=…`, `-disposition:<type>:N
      default+forced+comment+hearing_impaired+visual_impaired+original` (every flag, `0` for
      none). Matroska `LanguageIETF`, which FFmpeg never writes, goes to a `header_edit` step
      (C-18; FFmpeg writes all six flags, [0034](../decisions/0034-metadata-edit-in-place.md)).
- [ ] **Chapters**: `-map_chapters 0|-1`, or a generated FFMETADATA file for renamed or
      generated chapters, and for the source's chapters when the range starts or ends on a
      chapter edge (FFmpeg's copy keeps an empty chapter there; 0013 "Follow-up (M2 wave
      2b)"). The end of a chapter range is clamped to the last chapter
      ([decision 0026](../decisions/0026-builder-and-validation-agree.md)).
- [ ] Tags with `-metadata`. Passthru common metadata = `-map_metadata 0` before the overrides.
- [x] NVENC constant quality: with no level and no `maxrate`/`bufsize` in the custom
      parameters, a `-maxrate`/`-bufsize` high enough that the level NVENC picks does not cap
      the quality (values measured, [0103](../decisions/0103-owner-decisions-before-v1.md) item 1).
- [x] Align A/V start: the output's streams start together (0103 item 4).

Done when: syrupy snapshots of `EncodePlan` exist for ≥ 40 fixture jobs (every encoder family,
every container, burn-in, 2-pass, loudnorm, external subs, range, HDR → SDR). An
integration test runs a subset of plans on fixture media and re-probes the outputs to check
the stream layout, languages, titles and flags.

## C-8 Validation

`validate(job, source, caps, tools, fs) -> list[ValidationIssue]`. The rules are small
functions in a registry, grouped by area.

- [ ] Tools: ffmpeg missing or too old. (mkvpropedit is not needed since C-18,
      [0080](../decisions/0080-own-matroska-header-writer.md).)
- [ ] Encoder: unknown, checking, unavailable (with a fix to the closest one), 10-bit not
      supported, option not supported by this build.
- [ ] Container: codec not allowed (with fixes: convert, switch container, drop the track),
      flags not writable.
- [ ] Dimensions: invalid crop, upscaling (warning). Odd sizes for 4:2:0 cannot happen: C-5
      rounds every size to the chroma grid, so a property test replaces the rule; C-5's notes
      give the other issues (crop not detected, crop snapped, outside the fit box)
      ([0014](../decisions/0014-validation-rules-and-severities.md)). "Crop not detected" is
      info: an automatic crop without a rectangle means crop detection did not run for the
      job, as for every CLI job ([decision 0024](../decisions/0024-m2-wave-2-product-decisions.md),
      follow-up of 2026-10-17).
- [ ] Filters: HDR → SDR conversion without tone mapping (warning, with a fix). An HDR source
      encoded to 8-bit without tone mapping stays tagged HDR in 8 bits (warning, with fixes:
      tone mapping, 10-bit; [0014](../decisions/0014-validation-rules-and-severities.md)
      follow-up).
- [ ] Audio: a mixdown, bitrate or sample rate the encoder cannot do, and an upmix, are info
      notes that name the value the command builder writes (C-6's snap helpers,
      [decision 0024](../decisions/0024-m2-wave-2-product-decisions.md)).
- [ ] Subtitles: more than one burn-in, PGS subtitle into MP4 (VobSub is allowed,
      [0010](../decisions/0010-definitions-filters-and-containers.md)), forced-only on a format that
      does not support it (it works only for a burned-in PGS or VobSub track,
      [0014](../decisions/0014-validation-rules-and-severities.md)).
- [ ] Output: path not writable, output = source (also the `.part` file, the plan files and
      the 2-pass statistics files, through links: decision 0027 item 5), name collision, not
      enough free disk space (estimate in bitrate mode and for video passthrough), a manual
      name that breaks C-16's file-name rules.
- [ ] Silent losses: gain / DRC / loudness on a copied
      passthru track, an x265 level too small for the output
      ([0014](../decisions/0014-validation-rules-and-severities.md) "Follow-up (M2 review)").
- [ ] NVENC levels ([0102](../decisions/0102-nvenc-on-linux.md)): an H.264 or H.265 NVENC
      level too small for the output (`encoder.level_too_low`), and in bitrate mode a bitrate
      above what NVENC takes at the level (`encoder.level_bitrate_too_high`, measured table).
- [x] AMF pre-analysis on a picture below 320×200, which the encoder refuses at run time
      ([0103](../decisions/0103-owner-decisions-before-v1.md) item 9).
- [ ] Range is outside the duration.
- [ ] Everything the command builder refuses (`PlanError`) is a validation error (a test
      builds a job for each refusal, decision 0013).

Done when: every rule has a positive and a negative test, and every fix patch, when applied,
removes its issue.

## C-9 Presets and settings stores

- [ ] Built-in presets ship as JSON inside the package (read-only). User presets are stored in
      `<config>/presets.json`.
- [ ] CRUD, set default, import/export (single preset or all), name-conflict handling.
- [ ] `diff(job_template, preset) -> list[FieldChange]` for the "modified" marker.
- [ ] Settings in `<config>/settings.json`. Atomic writes (temp file + `os.replace`).
- [ ] Migrations for both files. Unknown fields are kept. A file newer than this Reframe, or
      one that cannot be read, is never overwritten; a partly damaged presets file keeps its
      valid presets ([decision 0015](../decisions/0015-presets-and-settings-stores.md)).

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
- [ ] **Subtitle scans**: event counts. PGS forced-flag count (the forced flag of the
      composition objects, read from a stream copy: a decode with `forced_subs_only` does
      not drop PGS events); VobSub forced count (decode with `forced_subs_only`)
      ([0032](../decisions/0032-analysis-scans-and-their-fixtures.md)).
- [ ] **Loudness measure** (`loudnorm` print_format=json) for the analyse step and for preview.

Done when: frames for a 4K HDR fixture come back in < 2 s each on a normal desktop, and
cancelling a scan stops its FFmpeg process within 1 s.

## C-11 Queue and job runner

- [ ] SQLite store: `jobs(id, position, state, settings_json, plan_json, issues_json,
      created_at, started_at, finished_at, output_path, log_path, error)`. One writer thread,
      whole-row writes; damaged, newer and unwritable files as in
      [decision 0016](../decisions/0016-queue-and-job-runner.md).
- [ ] Runner loop: when a slot is free (parallel limit), take the next `Waiting` job →
      **validate again** (capabilities can change; wait for encoder detection when an encoder
      is still being checked) → build the plan → run the steps. Two jobs with the same output
      path never run at once (0016). `add` and `retry` fail a job whose output is the output
      or the source of another waiting, running or paused job (`queue.output_claimed`,
      [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 6;
      built in C-17, [0061](../decisions/0061-c17-remote-queue-and-queue-commands.md)).
- [ ] **Progress parser** for `-progress` blocks (`out_time_us`, `fps`, `speed`, `total_size`,
      `progress=end`). Weighted across steps (pass 1 = 40 %, …). ETA from a smoothed rate over
      active time: paused time and a system sleep do not count (FFmpeg's own `speed` and `fps`
      do count them, so Reframe computes its own; 0016).
- [ ] Logs: the full command line + stderr, to `<data>/logs/<job>.log`. Rate-limited
      `job.log` events.
- [ ] Pause and resume: psutil `suspend()` / `resume()` on the process tree. The in-process
      `header_edit` step cannot be suspended: a pause shows at once, the write (milliseconds)
      ends, and nothing after it starts until resume ([decision 0080](../decisions/0080-own-matroska-header-writer.md) "Built: I").
- [ ] Cancel: kill the tree and remove the `.part` file.
- [ ] Time limits: none for an encode; a sleep-aware stall watchdog for FFmpeg steps (no
      progress, no output and no CPU use for 10 minutes) and a 5-minute limit for other short tool steps
      (0016). An FFmpeg step still running 1 minute after its last progress block
      (`progress=end`) is stopped, busy or not
      ([0096](../decisions/0096-qsv-options-on-intel-hardware-and-ffmpeg-that-does-not-exit.md)).
      The in-process `header_edit` step (C-18) has no time limit and is let finish
      once it starts; a cancel or close before it starts writes nothing.
- [ ] Success: re-probe the `.part` output and check its layout (number and type of streams,
      languages) **before** the rename, so a bad output never takes the final name; then rename
      `.part` → final name (collision policy; with `ask` the job fails with the issue and the
      complete `.part` file is kept) (0016).
- [ ] Restart recovery: `Running` → `Interrupted`. `close()` stops running jobs as
      `Interrupted` (0016). The store is opened on first use under an exclusive lock
      (`<data>/queue.lock`): only the owner restores it and runs its jobs; another
      process hands its jobs to the owner's server, or, when it cannot, gets a private queue
      that is not kept ([decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md)).
      No file that a job writes or removes may
      be the source ([decision 0027](../decisions/0027-one-process-owns-the-queue-store.md)),
      except the source of a `metadata_edit` job, which only the `header_edit` step (C-18)
      edits and nothing removes ([decision 0034](../decisions/0034-metadata-edit-in-place.md)).
- [ ] When-done actions through `platform/`. Sleep inhibit while any job runs.

Done when: an integration test queues 3 fixture jobs (parallel = 2) and covers pause, resume,
cancel, a failure from a fake encoder error, and a restart with an interrupted job. All
expected events arrive in order.

What the runner takes (`QueueService.processing` and `only`, running state) changes with
`start`, `stop` and the end of the jobs that a `start(job_ids=…)` named, however they end
(idle); each change is a `queue.processing` event
([decision 0064](../decisions/0064-queue-processing-event.md)).

## C-12 Batch engine

Implements [04-batch-mode.md](04-batch-mode.md): descriptors, fingerprints, grouping, rule
derivation, rule resolution with relaxation, overrides as JSON patches (including parsed-name
overrides for `C-16`), and per-group resolution with a match report.

- [ ] **Audio and subtitle defaults** (needed by M6, before grouping):
  - Selection stage: languages, first/all matching, tie-break, `und`, other languages, no-match
    behaviour, roles, order, default track.
  - Codec-rule stage: first match wins. Bitrate cap: never bigger than the source; passthru
    when the source fits; snap to the allowed encoder values; unknown bitrate counts as above
    the max. Built in M2, before the selection stage: an M2 draft job takes every audio track
    through the codec rules ([decision 0018](../decisions/0018-m2-draft-tracks-and-multi-file-encode.md)).
  - One `TrackDecision` per source track, with a reason string for every selected or dropped
    track and every chosen rule: `audio_stage(defaults, source).decisions` and
    `subtitle_stage(...).decisions`. `JobService.explain` feeds the live preview
    ([decision 0090](../decisions/0090-batch-api-and-draft-path.md)).
  - Lint: shadowed rules, unreachable rules, max bitrate out of range.

The rule engine (explicit track rules with relaxation; the defaults compiled into rules over
the selection stage), grouping, derivation, overrides and the match report:
[decision 0040](../decisions/0040-batch-engine-and-reframe-batch.md).

Done when: the "Done when" list in [04](04-batch-mode.md#core-api-implemented-in-c-12) passes,
and a table test reproduces the example in
[03 §Audio defaults](03-features.md#audio-defaults-stored-in-the-preset) row by row (Hungarian
5.1 → 320, English 5.1 → 384, AC-3 224 passthru, stereo fallback).

## C-13 Metadata edit and remux

- [ ] Job type detection (`encode`, `remux`, `metadata_edit`) with a reason string.
- [ ] The edits of a `metadata_edit` job: per track, the language pair (`ger` + `de`), the
      name and the flags that differ from the probed source, and the segment title. C-18's
      writer applies them; it replaces the `mkvpropedit` builder
      ([decision 0080](../decisions/0080-own-matroska-header-writer.md)).
- [ ] Post-mux fix-up step for the `LanguageIETF` that FFmpeg does not write (C-18's writer).
- [ ] After every metadata change, re-probe the file to check the result.

Done when: changing only languages and flags on an MKV fixture runs as `metadata_edit`, takes
< 1 s, and the re-probe shows the new values.

What can change in place (track languages, names, flags, the container title), the exact
exception to decision 0027, the fix-up (only `LanguageIETF`: FFmpeg writes all six flags), and
how the BCP 47 value is read back without MediaInfo (Reframe's own Matroska track reader):
[decision 0034](../decisions/0034-metadata-edit-in-place.md). Since C-18 the writer is Reframe's
own too ([decision 0080](../decisions/0080-own-matroska-header-writer.md)).

## C-14 Platform services

- [ ] Sleep inhibit: Windows `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`.
      Linux: the desktop session's inhibit for automatic suspend
      (`org.freedesktop.PowerManagement.Inhibit`, else the XDG portal `Inhibit` with the
      suspend flag) and the logind `Inhibit` D-Bus call with `what=idle` where it is needed
      (no session inhibit, or logind's `IdleAction` is not `ignore`: KDE turns a logind idle
      lock into a screen inhibit). No `systemd-inhibit`. If none is available, emit a
      warning and continue. Only automatic (idle) sleep is stopped: the user's own Sleep is
      never blocked, so on Linux there is no logind `sleep` block lock
      ([decision 0020](../decisions/0020-m2-wave-1-product-decisions.md); the Linux mechanism is
      [0022](../decisions/0022-linux-sleep-inhibit-mechanism.md); both supersede the lock of
      [0011](../decisions/0011-sleep-inhibit.md)). The D-Bus calls use a small stdlib client
      (no D-Bus dependency); on Windows one dedicated thread sets and clears the state.
- [ ] Power actions: shut down, sleep (Windows: `shutdown /s /t 60` and `SetSuspendState`.
      Linux: `systemctl poweroff|suspend`). Always after a cancellable 60 s countdown event.
- [ ] Notification hook: emits an event only. The UI layer shows the notification.

## C-15 Service facade and CLI

```python
class Reframe:
    @classmethod
    async def create(cls, config_dir: Path | None = None, data_dir: Path | None = None) -> Reframe: ...
    events: EventBus
    tools: ToolsService            # status, re-scan; fetch (reframe tools fetch)
    capabilities: CapabilityService
    sources: SourceService         # probe, probe_many, get, store, update; C-10 tasks: bitrate_scan,
                                   # subtitle_scan, loudness_scan, frames, frame, cropdetect
    presets: PresetService
    jobs: JobService               # draft, validate, plan (dry_run=), name, media_files; explain
                                   # (C-12), draft_remux (C-13), search_options, hdr_metadata,
                                   # dry_run (C-6); preview_clip, preview_clip_path (C-10)
    batch: BatchService            # group, derive, resolve, resolve_batch (a whole run)
    queue: QueueService            # add, list, reorder, start/pause/resume/cancel, logs
    settings: SettingsService
    power: PowerService            # when-done power actions with the 60 s countdown (C-14)
    async def close(self) -> None  # stop the runner, kill children, flush stores
```

The method list beyond this sketch, and the task context of the C-10 methods:
[decision 0030](../decisions/0030-core-complete-contract.md).

- [ ] Wire every service. `create()` returns quickly. Detection and queue restore continue in
      the background.
- [ ] CLI (`reframe` entry point, `[cli]` extra):
      `reframe probe FILE [--json]` · `reframe encoders` · `reframe tools status` · `reframe tools fetch [--build NAME] [--platform P]` ·
      `reframe name PATH… [--template T] [--preset NAME]` (prints the name source, parsed fields and the output name) · `reframe presets list` · `reframe presets export [NAME…] [-o FILE]` · `reframe presets import FILE [--on-conflict rename|replace|skip]` ·
      `reframe plan FILE [--preset NAME] [-o OUT]` (prints the issues, then the command) · `reframe encode FILE|DIR… [--preset NAME] [-o OUT] [-r]` (one job per media file, [decision 0018](../decisions/0018-m2-draft-tracks-and-multi-file-encode.md)) ·
      `reframe batch DIR… [--preset NAME] [--level strict|standard|loose] [--dry-run] [-r] [--json]`
      (prints the groups and the resolution matrix; without `--dry-run` it encodes the files
      without errors; the name checks cover every group, and an earlier run's outputs are left
      out, [decision 0040](../decisions/0040-batch-engine-and-reframe-batch.md)).
      No `--preset`: the default preset. Output formats, exit codes, the bounded wait for
      encoder detection and the folder search: [decision 0017](../decisions/0017-jobs-service-and-cli.md).
      The fetch, the preset commands, the dry run of `plan` and the when-done countdown of
      `encode`: [decision 0038](../decisions/0038-cli-tools-presets-and-when-done.md).

Done when: the CLI can encode a season folder end to end with no UI. This is the first point
where you can use Reframe for real.

## C-16 Output naming

Implements [03 §Output naming](03-features.md#output-naming).

- [ ] `naming/source.py`: pick the name source (Auto / File / Folder). Skip generic folders,
      detect season packs, score candidates, and return a reason string.
- [ ] `naming/parse.py`: run `guessit` in advanced mode to get each match **with its position**,
      so text fields are cut from the original string and keep their spelling and separators.
      guessit reads no user config files (`no_user_config`,
      [0012](../decisions/0012-output-naming-rules.md)).
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

## C-17 Remote queue and queue commands

Implements [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md): one
scheduler process, and the CLI hands its jobs to it. Needs S-2 (queue routes), S-3 (events)
and S-7. Milestone M3b.

- [x] `reframe.queue.QueueLike` (a `Protocol`): the methods of `QueueService` that the CLI
      calls (`add`, `list`, `get`, `start(job_ids=…)`, `wait`, `cancel`, `pause`, `resume`,
      `retry`, `remove`, `reorder`, `log_path`). `QueueService` implements it unchanged.
      `reframe encode` and `reframe batch` use only `QueueLike`.
- [x] `reframe.remote`: `RemoteQueue(QueueLike)` over the server's REST and WebSocket
      (`httpx`, `websockets` in the `[cli]` extra), and finding the owner (0042 item 3):
      `<data>/server.json` with the same `instance` and `api_version`; else start one with
      `sys.executable -m reframe_server --mode desktop --host 127.0.0.1 --port 0 --owner-only
      --idle-exit 30` through `launch_detached` and wait at most 10 s; else 0027's in-process
      queue with `queue.store_busy` and the reason.
- [x] Client mode: probe and draft locally, validate with `POST /api/jobs/validate`, show the
      owner's encoder statuses, and run no encoder detection of its own (0042 item 4).
- [x] Attached jobs (the default: the event connection first, then `attach` with its
      `client_id`) and `--detach` for `encode` and `batch`; `--in-process`. The CLI adds its
      jobs at the end of the queue (0042 item 5).
- [x] Output claims in `QueueService.add` and `retry`: `queue.output_claimed` when the job's
      output is the output or the source of another waiting, running or paused job, compared
      as files (0042 item 6).
- [x] `reframe queue list [--json]` · `log ID [-f]` · `pause|resume|cancel [ID…|--all]` ·
      `retry ID` · `remove ID`. With no owner, `list` and `log` open the store read-only: no
      restore, no lock.

Done when, with real processes (the real `reframe-server` and `reframe` CLI, fixture media
or the fake FFmpeg):

1. Two `reframe encode` runs at once both finish, each shows its own progress, and
   `queue.parallel_jobs` holds across both.
2. SIGINT in one cancels only its own jobs.
3. `kill -9` of a client cancels its attached jobs and removes their `.part` files. A
   `--detach` job runs on.
4. `kill -9` of the server in the middle of a job: the client reports `interrupted`; the next
   command starts a new owner that restores the queue.
5. Ten clients that add jobs at the same time lose none and duplicate none.
6. A job whose output is the output of another client's waiting job is added `failed` with
   `queue.output_claimed`.
7. A server of another `api_version` is not used: the client falls back and says why.
8. The queue contract test suite passes against `QueueService` and `RemoteQueue`.

Built as [decision 0061](../decisions/0061-c17-remote-queue-and-queue-commands.md) records.
The owner is started in desktop mode (the web mode with no roots refuses every path); clients
that search at the same time start one owner (`<data>/server-start.lock`); a started owner's
exit code 75 means another one won. `RemoteQueue` keeps a copy of the queue that the event
stream changes in order (an add's answer and a whole-queue read add what events do not carry),
and a call returns once the copy shows its change; a `start` that the owner refuses is raised
by the next awaited call; when the connection ends, its running jobs are reported
`interrupted`. A client drafts here and the owner
validates; the facade starts encoder detection only for an in-process run. Ctrl+C cancels the
command's own jobs and no longer stops the queue. `--in-process` is also
`REFRAME_IN_PROCESS=1`; `--detach` needs an owner. `reframe queue retry` also starts the job.
The eight checks pass: 1–7 with real processes and the real FFmpeg
(`tests/remote/test_shared_queue_real.py`), 8 in `tests/remote/test_queue_contract.py`.
Not verified on Windows.

After the review ([0061](../decisions/0061-c17-remote-queue-and-queue-commands.md), "The
CLI"): a command reports a job that another front end removes and ends without it; a job that
another front end retries is that front end's (the command keeps its first end, and the job
leaves the command's connection on the server); Ctrl+Z in client mode pauses and detaches the
command's running jobs while it is stopped and resumes them on SIGCONT; after a lost
connection the command reports its jobs as the owner, or else the saved queue, shows them.

A global Stop from another front end (0042 open question 5,
[decision 0064](../decisions/0064-queue-processing-event.md)): `RemoteQueue` forwards the
`queue.processing` event and keeps `processing` and `only` in its copy; when a stop holds a
waiting job of the command (checked with a whole-queue read, so a stop that came just before
the command's own start does not count), `encode` and `batch` print one line, "The queue was
stopped by another front end: …", and go on waiting. Ctrl+C cancels the jobs; a later Start
runs them.

## C-18 Matroska header writer

Reframe's own code writes the Matroska header changes that mkvpropedit wrote before
([decision 0080](../decisions/0080-own-matroska-header-writer.md)). MKVToolNix is a development
tool only: tests use it as an oracle, and no product code runs it. Milestone M10.

- [x] A writer in `metadata/` that shares the EBML parsing and the `MAX_*` limits of
      `probe/matroska.py` and runs in-process (a worker thread). It edits, in each
      `TrackEntry`, `Language`, `LanguageIETF`, `Name` and the six flags (`FlagDefault`,
      `FlagForced`, `FlagCommentary`, `FlagHearingImpaired`, `FlagVisualImpaired`,
      `FlagOriginal`), and in `Info`, `Title`. Tracks are picked as the n-th track of a type
      in `TrackEntry` order. Both language elements are always written (ISO 639-2/B and
      BCP 47).
- [x] An element that still fits in its place and the `Void` after it is written there. One
      that does not fit moves to the end of the segment: the old place becomes a `Void`, and
      the `SeekHead` entry and the segment size are updated. A `CRC-32` child of a changed
      element is calculated again.
- [x] A file the writer cannot edit safely is refused with a reason (a failed step, not an
      exception), and the file is unchanged. Record each such case, found on real files, in
      `testdata/README.md`.
- [x] Crash safety: every state that a crash or a kill can leave is a file that ffprobe and
      `mkvmerge -J` open with all the old values or all the new ones. Once the writer starts
      to write, a cancel or `close()` lets it finish.
- [x] The plan step kind `header_edit` (was `mkvpropedit`) for the `metadata_edit` job (C-13)
      and the `LanguageIETF` fix-up (C-7). Its line in the command preview lists the edits
      (track, field, value).
- [x] mkvpropedit leaves the product: discovery, `ToolName`, `ToolsStatus`, `reframe tools
      status`, Settings → Tools, the first-run check, `REFRAME_MKVPROPEDIT`, the Windows
      install-folder search, `tool.mkvpropedit_missing`, the BCP 47 silent loss, and the
      settings field `tools.mkvpropedit` (`schema_version` bump, migration, down-level note).
      Packaging and notices follow in D-8, S-6 and Q-5.

Done when:

1. Property tests: an EBML element that the writer encodes reads back the same through
   `probe/matroska.py`.
2. Oracle tests (`needs_mkvtoolnix`): on the fixture corpus (FFmpeg-written files,
   mkvmerge-written files, files with `CRC-32` elements (mkvmerge 103 writes none: the corpus
   adds them to an mkvmerge file), reordered tracks with attachments, 6000-character
   names that move `Tracks`), the same edit done by mkvpropedit and by the writer reads back the
   same in `mkvmerge -J`, and ffprobe still reads every stream.
3. Fault-injection tests stop the writer after each write; every file left opens in ffprobe
   and `mkvmerge -J` with all the old or all the new values.
4. Every refused case leaves the file byte for byte unchanged.
5. C-13's "Done when" passes with the writer, and no product code path starts an MKVToolNix
   program.

## C-19 Probe without MediaInfo

The probe fills the gaps that MediaInfo filled with Reframe's own code, and MediaInfo leaves the
product ([decision 0081](../decisions/0081-probe-without-mediainfo.md)). Milestone M10.

- [x] Stale statistics tags: a track whose `TrackEntry` has `ContentEncodings` with compression
      (mkvmerge zlib-compresses PGS) is left out of the `NUMBER_OF_BYTES` sum;
      Reframe's Matroska reader reads `ContentEncodings`.
- [x] Sampled estimate for Matroska and WebM, when a video or audio stream has no rate after
      ffprobe and the tags: the clusters that start in 32 windows at evenly spaced offsets
      (2 % to 98 %; a segment no larger than the windows is read whole), each with the next
      cluster's timestamp, in the file's `TimestampScale`. Audio: bytes per sampled
      second. A single video stream without a rate: the file's rate, without the bytes of
      attachments, cues and tags, minus every other stream's. More than one such video stream:
      bytes per sampled second each. Bounded reads (256 KB windows, a cluster of at most 64 MB,
      256 MB in all, the reader's `MAX_*` limits), in the probe's worker thread, with a time
      limit and cancel; a file that cannot be sampled keeps `unknown`, and a sample that timed
      out is not cached ([decision 0081](../decisions/0081-probe-without-mediainfo.md) "Built: E").
- [x] `BitrateSource.estimated` replaces `mediainfo` (`schema_version` bump, migration
      `mediainfo` → `estimated`, down-level note); the probe cache key changes. The track
      table shows `≈` and "estimated from 32 samples" next to **Measure**.
- [x] VFR from ffprobe's output and the 120-packet fallback only. BCP 47 for containers other
      than Matroska from the ISO 639 code.
- [x] MediaInfo leaves the product: `probe/mediainfo.py`, the `[mediainfo]` extra and
      `pymediainfo` in the sidecar, discovery, `ToolName`, `ToolsStatus`, Settings → Tools,
      `REFRAME_MEDIAINFO`, the settings field `tools.mediainfo` (`schema_version` bump,
      migration, down-level note), the Windows MediaInfo CLI in `tools/bundled-tools.toml` and
      `scripts/bundle-tools.py`, `Recommends: mediainfo`, the Docker image's `mediainfo`
      package and extra, and the notices.

Done when:

1. On the fixtures and a recorded real-file corpus (mkvmerge with compressed PGS tracks,
   HandBrake 0.10 and 1.x, FFmpeg output), every video and audio stream of an MKV has a rate;
   each `estimated` video rate is within 3 % and each audio rate within 12 % of the exact
   block-scan value, recorded in `testdata/README.md`.
2. The two mkvmerge files of 0081 whose tags were called stale keep their statistics tags
   (`stats_tag`), checked with a recorded probe of each.
3. A file the sampler cannot read (damaged clusters, unknown-size clusters only) keeps
   `unknown` with no exception.
4. Q-3's probe budgets still pass, and `import reframe` and a probe work with no
   `pymediainfo` installed; no package contains MediaInfo.

## C-20 Language data table

A generated data file replaces `langcodes`, `language_data` and `marisa-trie` at run time
([decision 0082](../decisions/0082-own-language-data-table.md)). The two libraries move to the
dev dependency group. Milestone M10.

- [x] `scripts/gen-language-data.py` builds the file from the libraries into
      `reframe/definitions/data/`: the IANA registry subtags (type, `Deprecated`,
      `Preferred-Value`, `Suppress-Script`, `Macrolanguage`), langcodes' alias tables and the
      canonical tag of each language subtag, ISO 639-1/2B/2T/3 codes, English and native
      names of languages, English names of scripts, regions and variants, region and script
      names per locale, and language names per locale with langcodes' name normalisation.
      `--check` fails when the committed file differs from a new build.
- [x] A core part (codes, canonical forms, English and native names) read at the first use,
      and lazy parts (names per locale) read only by a native name of an unlisted variant or
      a name search.
- [x] `reframe.languages` keeps its public API and its results, read from the file (standard
      library only). English names compose as `Language (detail, detail)` from the script and
      region (a variant is not named: `de-1901` is "German"); a script that is the language's
      `Suppress-Script` is left out; `und` with a detail composes as "Unknown language (…)"
      (`mul-US` is "Multiple languages (United States)";
      [decision 0082](../decisions/0082-own-language-data-table.md) "Built: L").
- [x] `langcodes`, `language_data` and `marisa-trie` leave the runtime dependencies, the
      PyInstaller spec and the notices; the notices get the CLDR and IANA terms (Q-5).

Done when:

1. An equivalence test (dev and CI, libraries installed) gives the same `normalize`,
   `english_name`, `native_name`, `to_matroska_legacy`, `to_mp4`, `search` and `matches`
   results as the libraries over a fixed corpus: every registry language subtag, every
   listed base language with every region and script, deprecated, extlang and grandfathered
   tags, and the names of every listed language in every locale. Each tie (an ambiguous
   name) is fixed to today's result.
2. `scripts/gen-language-data.py --check` passes in CI.
3. `import reframe` and a probe, a draft and a search work in a virtual environment without
   the three libraries, and the frozen sidecar contains none of them.

## C-21 FFmpeg builds to choose and the build-mismatch cause

The desktop packages contain no FFmpeg; the core offers the pinned builds, installs one, and
says when a system does not fit a build
([decision 0093](../decisions/0093-ffmpeg-download-and-build-choice.md)). Milestone M10.

- [x] Manifest: `tools/ffmpeg.toml` marks offered builds (`offered = true`) with `label` and
      `summary`; `default` and `compat` (release/8.1, the pin `override-test` uses) are
      offered. `reframe.tools` lists them with their version, licence and source links, and
      `ToolsService` exposes the list (`tools.builds()`).
- [x] The installed downloaded build: which offered build it is, and `outdated` when its
      version is not that build's pinned version in this release's manifest.
- [x] Install from a file: an archive given by path is checked like a download (size and
      SHA-256 against the manifest entry of the build and platform it claims, then
      `ffmpeg -version`) and installed the same way (`tools.install_file()`, `reframe tools
      fetch --file ARCHIVE [--build NAME]`).
- [x] A download that cannot reach the server (no network or name resolution, a refused or
      timed-out connection) fails with `tools.fetch_offline`, whose message names the
      alternatives (install from a file, choose an FFmpeg path). Other failures keep their
      reasons.
- [x] On Linux, when the app ships a packaged libva (its resource folder), a download or a file
      install copies the libva libraries into the installed build's `lib/`.
- [x] `EncoderStatus.build_mismatch` (default `false`): set by the reason mapping for the NVENC
      API / driver version and for a system library too old or missing for the build; never
      for a 10-bit-only limit and never for a filter. The capability cache format changes.
      `EncoderStatus.build_mismatch_cause` says which (`driver`, `system_library`;
      [decision 0098](../decisions/0098-ffmpeg-download-review-r1-fixes.md)).
- [x] CLI: `reframe encoders` and `reframe tools status` print one `hint:` line per mismatch
      cause (driver: update the driver, or another build: `reframe tools fetch --build …`,
      `REFRAME_FFMPEG`, `tools.ffmpeg`; system library: install or update it, or your own
      FFmpeg, no `--build`; 0098); `reframe tools status` names the installed build
      and says when it is outdated; `reframe tools fetch` lists the offered builds in `--help`.
      The driver hint names only an offered build of an older FFmpeg release than the
      downloaded build in use (a newer FFmpeg never needs an older driver); without one it
      says to update the driver or use an own FFmpeg
      ([decision 0101](../decisions/0101-nvenc-session-limit-and-older-build-hint.md)).

Done when:

1. A recorded NVENC driver failure (`Required: 13.1 Found: 13.0`, `minimum required Nvidia
   driver for nvenc is 610.00`) and an `implib-gen` failure give `build_mismatch` true; AMD's
   10-bit driver message, a missing NVIDIA driver and a missing device give false.
2. A fetch with the network unreachable (a fake transport) gives `tools.fetch_offline` and
   installs nothing; an archive file with a wrong SHA-256 is refused before extraction; the
   right file installs and discovery finds it.
3. With a manifest whose `default` pin changed, the installed build is reported `outdated`.
4. On Linux, a fetch with a packaged libva leaves `libva.so.2` and `libva-drm.so.2` in the
   build's `lib/`, and VAAPI detection works with that build on Ubuntu 22.04 (container).
