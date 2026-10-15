# 03 — Features

This is the functional spec. Each section says what HandBrake does, what Reframe changes, and
how it should behave. The core implements the logic ([05-core.md](05-core.md)). The frontend
renders it ([06-web-app.md](06-web-app.md)).

Contents: [App layout](#app-layout) · [Summary](#summary) · [Dimensions](#dimensions) ·
[Filters](#filters) · [Video](#video) · [Advanced encoder options](#advanced-encoder-options) ·
[Audio](#audio) · [Subtitles](#subtitles) · [Track metadata & languages](#track-metadata--languages) ·
[Chapters](#chapters) · [Tags](#tags) · [Output naming](#output-naming) · [Preview](#preview) · [Presets](#presets) ·
[Queue](#queue) · [Remux-only jobs](#remux-only-jobs) · [Settings](#settings) ·
[Validation](#validation-and-error-display)

Batch / season editing has its own document: [04-batch-mode.md](04-batch-mode.md).

---

## App layout

```
┌──────┬───────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Nav  │ Source header: title · duration · Range [Chapters 1–12 ▾] · Preset [H.265 MKV 1080p ▾] (modified) │
│      ├────────────────┬────────────────────────────────────────────────┬─────────────────────────────────┤
│ Work │ Sources        │ Summary | Dimensions | Filters | Video | Audio │ Preview                         │
│ Queue│ ▸ Season 1 (12)│ | Subtitles | Chapters | Tags                  │ (frame strip,                   │
│ Pre- │   E01 ✓        │                                                │  before/after,                  │
│ sets │   E02 ✓        │   tab content                                  │  crop overlay)                  │
│ Log  │ ▸ Movie.mkv    │                                                │                                 │
│ Set. ├────────────────┴────────────────────────────────────────────────┴─────────────────────────────────┤
│      │ Output: /media/out/Show - S01E01.mkv   ⚠ 1 warning   [Add to queue] [Add all] [Start]             │
└──────┴───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Sources panel**: open files or folders. Shows probe status, warnings, and batch groups
  ([04](04-batch-mode.md)).
- **Preview panel**: can be collapsed or detached (desktop: separate window). It follows the
  active tab. On Dimensions it shows crop overlays. On Filters it shows before/after.
- **Status bar**: output path, validation summary (click to see the list), queue actions.
- Light, dark and system themes. Compact and comfortable density.
- Keyboard: `Ctrl+O` open, `Ctrl+Enter` add to queue, `Ctrl+1…8` switch tabs, `←/→` move
  through preview frames.

---

## Summary

**HandBrake:** a list of text lines and a few container check boxes. It looks dated.

**Reframe:** a grid of cards.

| Card | Content |
|------|---------|
| Source | Thumbnail, file name, container, duration, size, overall bitrate. Video line, e.g. `HEVC Main 10 · 3840×2160 · 23.976 fps · HDR10 · BT.2020 PQ`. Track counts. Chapter count |
| Output | Container (MKV / MP4 / WebM). Options: **Web optimized** (MP4 faststart), **Align A/V start**, **Passthru common metadata**. Output folder and file name ([template-based](#output-naming)), with the chosen name source |
| Picture pipeline | `3840×2160 → crop 3840×1600 → scale 1920×800 · 2.40:1 · square pixels`, plus filter chips (`Deinterlace: off`, `Colorspace: BT.709`, `Tone map: on`) |
| Video | Encoder, quality mode and value, speed preset, bit depth, number of changed advanced options |
| Tracks | One chip per output audio and subtitle track: language, codec, channels, role badges, flags. Click a chip to open the track in its tab |
| Issues | Validation issues, grouped by severity, each with fix buttons ([Validation](#validation-and-error-display)) |
| Estimate | Estimated output size, shown only in bitrate mode. In quality mode it shows "depends on content" |

Done when: every card updates live while you edit other tabs, and every chip and issue links
to the field it describes.

---

## Dimensions

**HandBrake problems:** manual crop has no visual feedback. Resolution limit, Pixel aspect,
Scaled size and Final dimensions overlap and confuse. Borders are not wanted.

**Reframe layout** (top to bottom):

### 1. Pipeline header (always visible)

`Source 1920×1080 (16:9, square) → Crop 1920×800 → Output 1920×800 · 2.40:1 · square pixels`

This one line replaces HandBrake's "Final dimensions" block. It turns amber when the output
is upscaled. It turns red when a value is invalid.

### 2. Orientation

Rotate (0 / 90 / 180 / 270) and Flip horizontal, in one compact row. The rotation is
clockwise, and the flip mirrors the picture after the rotation.

### 3. Crop

Mode (segmented control): **Automatic** · **Conservative** · **None** · **Manual**.

- **Automatic**: runs FFmpeg `cropdetect` on N sample frames (default 10, same frames as the
  preview strip) and picks the most common result. Shows
  `Detected 0 / 0 / 140 / 140 on 9 of 10 frames`.
- **Conservative**: crops only the area that is black on *all* samples. This is safe for
  films with changing aspect ratios (IMAX scenes).
- **Manual**: Top / Bottom / Left / Right inputs, plus drag handles on the preview.

**Crop magnifier (manual mode):**

```
┌───────────────────────── frame (fit) ─────────────────────────┐   ┌─ Top edge ×4 ───────────────┐
│░░░░░░░░░░░░░░░░ removed (tinted) ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│   │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│─────────────────────── crop line ─────────────────────────────│   │────────── crop line ────────│
│                                                               │   │ picture rows 140–156        │
│                         picture                               │   ├─ Bottom edge ×4 ────────────┤
│                                                               │   ├─ Left edge ×4 ──────────────┤
│─────────────────────── crop line ─────────────────────────────│   ├─ Right edge ×4 ─────────────┤
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│   │ zoom: 2× 4× 8×  · grid on   │
└───────────────────────────────────────────────────────────────┘   └─────────────────────────────┘
  ◀ frame 3 / 10 ▶   [Check crop on all frames]
```

- Four edge strips show the source pixels around each crop line, at full resolution, zoomed
  2×, 4× or 8× with nearest-neighbour sampling. Removed pixels are tinted. The crop line is
  drawn exactly at the pixel boundary.
- Hover over the main frame to show a round loupe that follows the cursor.
- Values snap to the chroma subsampling grid (mod 2 for 4:2:0). A note explains this when
  snapping changes a value.
- **Check crop on all frames** opens a grid of all sample frames with the crop overlay. Each
  frame shows the black bars that were detected on it. A frame gets a warning badge if the
  crop removes picture content there. The client computes this from the luma variance of the
  removed band in the PNG it already has.
- Frame navigation: the sample strip, or seek to any timestamp.

### 4. Output size

One control replaces Resolution limit + Scaled size + Pixel aspect + Final dimensions:

| Field | Values | Default |
|-------|--------|---------|
| Size | **Same as cropped source** · **Fit within** [2160p · 1440p · 1080p · 720p · 576p · 480p · Custom W×H] · **Exact width** · **Exact height** | Fit within 1080p (from preset) |
| Allow upscaling | on / off | off |

"Fit within 1080p" means: the output fits inside 1920×1080, keeps its aspect ratio, and is
never upscaled unless you turn upscaling on. Upscaling is measured against the source's
display size: a 720×480 16:9 DVD made square becomes 854×480, which is not an upscale
([decision 0009](../decisions/0009-dimension-maths-conventions.md)). For portrait output
(taller than wide) the box turns: a 1080×1920 phone video fits inside 1080×1920
([decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)).

### 5. Advanced (collapsed)

| Field | Values | Default | Help text shown |
|-------|--------|---------|-----------------|
| Pixel aspect | **Square pixels** · **Keep source (anamorphic)** · **Custom PAR** | Square | "Square pixels play correctly everywhere. Keep source only for DVD-style anamorphic video that you want to store at its original resolution." |
| Modulus | 2 · 4 · 8 · 16 | 2 | "Rounds the output size to a multiple of this number. Most encoders need 2." |
| Scaler | Lanczos · Bicubic · Spline · Bilinear | Lanczos | Speed and sharpness trade-off, in one sentence |

Done when: the dimension maths has property tests (see `C-5`). Manual crop shows the
magnifier. The pipeline header always matches the command that the builder makes.

---

## Filters

**HandBrake:** a good set of filters. Without explanations, they are hard to use.

**Reframe:** the same filter set. Each filter has a help panel and a before/after preview.

Layout: a filter list on the left (toggle + preset per filter). The selected filter's
**help panel** is on the right. The preview panel shows a split before/after of the current
frame. FFmpeg renders that frame through the job's filter chain, and the result is cached.

Help panel template (the core stores this text with each filter definition):

> **What it does** · **Use it when** · **Avoid when** · **Speed cost** (Low / Medium / High) ·
> **Settings explained** (each preset and tune in one line)

Where a filter has two implementations, the user picks one, as in HandBrake (Denoise: NLMeans
or HQDN3D); each implementation has its own presets and tunes
([0010](../decisions/0010-definitions-filters-and-containers.md)).

| Filter | FFmpeg implementation (the first is the default) | Presets (HandBrake parity) |
|--------|----------------------|----------------------------|
| Detelecine | `fieldmatch,decimate` | Off / Default / Custom |
| Interlace detection | `idet` (analysis) controls deinterlace on combed frames only | Off / Default / Less sensitive / Fast / Custom |
| Deinterlace | Bwdif (`bwdif`) or Yadif (`yadif`) | Bwdif: Off / Default / Bob / Custom. Yadif: Off / Default / Skip spatial check / Bob / Custom |
| Denoise | NLMeans (`nlmeans`) or HQDN3D (`hqdn3d`) | NLMeans: Off / Ultralight / Light / Medium / Strong / Custom, Tune: Film / Grain / High motion / Animation / Tape / Sprite. HQDN3D: Off / Ultralight / Light / Medium / Strong / Custom |
| Chroma smooth | `unsharp` (on chroma only) | Off / Ultralight … Very strong, Tune: Tiny … Very wide |
| Sharpen | Unsharp (`unsharp`) or CAS (`cas`) | Unsharp: Off / Ultralight … Very strong / Custom, Tune: Ultrafine … Very coarse. CAS: Off / Light / Medium / Strong / Custom |
| Deblock | `deblock` | Off / Ultralight … Strong |
| **Colorspace** | `zscale` or `libplacebo` | Keep source / BT.709 / BT.2020 / BT.601 |
| **HDR → SDR tone mapping** (new) | `libplacebo` if available and Vulkan works, else `zscale,tonemap` | Off / On (algorithm: BT.2390 / Hable / Mobius / Reinhard, peak detect) |
| Grayscale | `format=gray` / `hue=s=0` | Off / On |
| Custom | Raw filter string, inserted before scaling | Validated with a dry run |

**Colorspace gets extra care** (it is the most used filter):

- A **Source colour** box next to the control shows primaries, transfer, matrix, range, bit
  depth, HDR format and mastering display / MaxCLL values.
- A sentence describes what happens:
  "Converts BT.2020 PQ (HDR10) to BT.709 SDR. Without tone mapping, the picture will look
  washed out → [Enable tone mapping]".
- The output colour tags are written automatically to the encoder parameters, so players do
  not have to guess.

Filter order is fixed and documented: detelecine → deinterlace → denoise → deblock →
crop (→ burned-in bitmap subtitles) → rotate/flip → custom → scale → tone map / colorspace (→
the source's HDR metadata removed) → sharpen → chroma smooth → grayscale → burned-in text
subtitles → format/upload ([decision 0013](../decisions/0013-command-builder-details.md)).

---

## Video

Same as HandBrake, plus:

- **Encoder picker** groups encoders by family: Software (x264, x265, SVT-AV1, VP9),
  NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI (Linux). Each entry shows a status:
  `available` · `checking…` · `unavailable — <reason>`. You can see unavailable encoders but
  not select them. Hover to read the reason.
- **Video passthrough** (HandBrake does not have this): copy the video stream unchanged. All
  dimension and filter controls are then disabled, with a note.
- Framerate: Same as source / fixed value. Mode: Variable / Constant / Peak. FFmpeg has no
  variable-with-a-maximum mode: Peak keeps a slower source's rate and makes a faster or
  variable source constant at the peak rate ([decision 0013](../decisions/0013-command-builder-details.md)).
- Quality: **Constant quality** (CRF / CQ / QP, depending on the encoder). The slider uses the
  encoder's scale and shades a recommended band for the output resolution. **Average
  bitrate** also has 2-pass and turbo first pass options.
- Speed preset slider (x26x `ultrafast…placebo`, SVT-AV1 `13…0`, NVENC `p1…p7`), Tune,
  Profile, Level, Fast decode, Bit depth (8 / 10).
- **Advanced…** opens the [advanced options](#advanced-encoder-options).
- **Command preview** drawer: the full FFmpeg command for this job. It updates live, has
  syntax highlighting, and has a copy button.

### Missing encoder behaviour (fixes the HandBrake freeze)

Encoders are detected in the background at start ([05 §C-4](05-core.md#c-4-encoder-capabilities)).
The UI never waits for detection.

| Situation | Behaviour |
|-----------|-----------|
| Detection still running | The picker shows `checking…`. A preset or job can be edited. Queueing waits until the encoder's status is known |
| A preset or queued job uses an encoder that is now unavailable | A non-modal **error banner** on the Video tab and a Summary issue: "Preset *H.265 NVENC 1080p* uses `hevc_nvenc`, which is not available: *no NVIDIA device found*". Buttons: **Use `libx265` (closest match)** · **Choose encoder** · **Check again** |
| Queue reaches a job whose encoder became unavailable | The job is marked `Failed — encoder unavailable` with the same fix actions. The queue continues with the next job |
| The bundled FFmpeg is damaged, or an override points to a missing, broken or too old binary | A repair screen shows the reason and where the binary came from (environment, settings, bundled). Buttons: **Use bundled FFmpeg** · **Choose path** · **Check again**. The rest of the UI stays usable for browsing presets and settings |

"Closest match" mapping lives in the encoder definitions (for example `hevc_nvenc → libx265`,
`h264_qsv → libx264`, `av1_amf → libsvtav1`). Quality values are converted with a mapping
table, and a note says that the result is approximate.

---

## Advanced encoder options

Modelled on StaxRip: every parameter that matters is a typed, documented control.

```
┌ Search options… ───────────┐ ┌──────────────────────────────────────────────────────────────┐
│ ☐ Show only changed        │ │ Frame types / GOP                                            │
│ ▸ Basic                    │ │  B-frames            [ 5 ]  default 4 (preset slow)   ↺  ⓘ   │
│ ▸ Rate control             │ │  B-adapt             [ Full ▾ ]  default                   ⓘ │
│ ▸ Frame types / GOP   (3)  │ │  B-pyramid           [✓]                                   ⓘ │
│ ▸ Motion / analysis        │ │  Reference frames    [ 4 ]  default 4                      ⓘ │
│ ▸ Psycho-visual            │ │  Keyframe interval   [ 240 ] (≈10 s at 23.976)             ⓘ │
│ ▸ Loop filters             │ │  Min keyint          [ auto ]                              ⓘ │
│ ▸ HDR / colour             │ │  Scenecut            [ 40 ]                                ⓘ │
│ ▸ Performance              │ │  Open GOP            [✓]                                   ⓘ │
│ ▸ Custom parameters        │ │  Lookahead (rc)      [ 40 ]                                ⓘ │
└────────────────────────────┘ └──────────────────────────────────────────────────────────────┘
```

- **Changed values** are highlighted. Each has a reset button ↺. Each category shows a count
  of changed options.
- The **default** of an option shows as placeholder text. If the default depends on the speed
  preset, the placeholder says so (x264 and x265 preset tables ship with the core).
- **ⓘ** opens help: what the option does, its typical range, and the quality/speed effect.
- **Search** covers labels, CLI names and help text across all categories.
- **Custom parameters**: a free-form `key=value:…` field, appended last and validated by a
  dry run (`-frames:v 1 -f null`). Encoders without a params argument (NVENC, QSV, AMF, VAAPI,
  VP9) get each entry as their own option (`rc-lookahead=20` → `-rc-lookahead 20`). A
  parameter the encoder refuses, or only logs and skips (x264, x265 and SVT-AV1 do that), is a
  validation error from the dry run ([0035](../decisions/0035-advanced-option-sets-and-dry-run.md)).
- **Copy HDR metadata from source** fills master-display and MaxCLL/MaxFALL from the probe
  (x265 `master-display` / `max-cll`, SVT-AV1 `mastering-display` / `content-light`; the
  hardware encoders take it from the frames).
- An option whose condition does not hold (x265 `amp` without `rect`) is not written and shows a
  warning; a combination the encoder silently changes is a warning, one it refuses an error
  ([0035](../decisions/0035-advanced-option-sets-and-dry-run.md)).

Option coverage for v1:

| Encoder | Categories and examples |
|---------|------------------------|
| x264 | rate control (crf, vbv-maxrate/bufsize, qcomp, aq-mode/strength, mbtree), frames (bframes, b-adapt, b-pyramid, ref, keyint, min-keyint, scenecut, rc-lookahead, weightp), analysis (me, subme, merange, trellis, partitions, direct), psy (psy-rd, psy-trellis), deblock, colour (colorprim, transfer, colormatrix; not range: FFmpeg's libx264 wrapper overrides it with the input's range), threads |
| x265 | all x264 equivalents, plus ctu, rd, rdoq-level, psy-rdoq, limit-refs, limit-modes, rect, amp, tu-intra/inter-depth, sao / limit-sao / selective-sao, strong-intra-smoothing, hdr10, hdr10-opt, master-display, max-cll, repeat-headers, pools, frame-threads, wpp |
| SVT-AV1 | preset, crf, tune, film-grain, film-grain-denoise, keyint, scd, lookahead, enable-overlays, enable-qm, qm-min/max, variance-boost, sharpness, enable-tf |
| NVENC | preset p1–p7, tune (hq/uhq/ll), rc (vbr/constqp), cq, multipass, bf, b_ref_mode, refs, spatial/temporal AQ, aq-strength, rc-lookahead |
| QSV / AMF / VAAPI | preset/quality, rc mode, bf, refs, lookahead (when supported), profile/level (QSV: no levels, not verifiable without Intel hardware) |
| VP9 (libvpx) | keyframes (g, keyint_min), lag-in-frames, auto-alt-ref, alt-ref noise reduction, aq-mode, sharpness, qmin/qmax, under/overshoot, enable-tpl, tiles, frame-parallel, threads |

---

## Audio

**HandBrake problems:** too little information. Commentary tracks cannot be recognised. Lossless
tracks (DTS-HD MA) often show no bitrate.

### Source track table (read-only, always visible at the top)

| # | Lang | Name | Codec | Channels | Rate / depth | Bitrate | Role & flags |
|---|------|------|-------|----------|--------------|---------|--------------|
| 1 | jpn | — | **TrueHD Atmos** | 7.1 | 48 kHz / 24-bit | 3 912 kb/s | `Default` |
| 2 | eng | English Dub | **DTS-HD MA** | 5.1 | 48 kHz / 24-bit | 2 104 kb/s | |
| 3 | eng | Director's Commentary | AC-3 | 2.0 | 48 kHz | 192 kb/s | `Commentary` |

- **Codec** uses the commercial name (DTS-HD MA, DTS:X, TrueHD Atmos, E-AC-3 JOC, AAC-LC, HE-AAC,
  FLAC, PCM), from the FFprobe profile with MediaInfo as a fallback.
- **Bitrate** comes from, in order: the stream's `bit_rate` → Matroska statistics tags (`BPS`,
  `NUMBER_OF_BYTES`/`DURATION`) → MediaInfo → `—` with a **Measure** button that runs a
  packet-size scan as a cancellable background task.
- **Role badges**: `Commentary`, `Audio description`, `Music only`, `Main`. A badge is solid
  when the file's disposition flag sets it. It is outlined when a heuristic sets it (title
  keywords in several languages, or a 2.0 low-bitrate track in the same language as a main
  track). The tooltip names the source of the badge.
- Expand a row to see all details: delay, duration, frame count, all tags and dispositions.

### Output tracks (below the source table)

Each output track row has:

- **Source**: a dropdown with rich labels (`2 · eng · DTS-HD MA 5.1 · English Dub`).
- **Action**: Passthru · Encode. Passthru falls back to an encoder when the container cannot
  hold the codec (HandBrake's "auto passthru").
- **Encoder**: AAC (`aac` / `libfdk_aac` if present), AC-3, E-AC-3, Opus, FLAC, MP3.
- **Mixdown** (Mono · Stereo · Dolby Pro Logic II · 5.1 · 7.1), sample rate, bitrate or quality,
  gain, DRC.
- **Normalise loudness** (new): off / EBU R128 (−23 LUFS) / Streaming (−16 LUFS). It uses
  `loudnorm` in two passes. The measurement pass runs as part of the job.
- **Metadata** (new, see [Track metadata](#track-metadata--languages)): language, name, flags.

Rows can be reordered by dragging. Buttons: **Add track**, **Add all**, **Reload from preset
rules**.

### Audio defaults (stored in the preset)

**HandBrake:** "Selection Behavior" filters source tracks by language, but every selected
track gets the same encoder list. You cannot say "Hungarian 5.1 → 320 kb/s, English 5.1 →
384 kb/s".

**Reframe** splits the defaults into three parts: **which tracks**, **how to encode them**,
and **passthru**. Open them with **Defaults…** on the Audio tab, or in the preset editor. The
same dialog shows a live preview of the result.

#### 1. Track selection: which source tracks to take

| Setting | Values | Default |
|---------|--------|---------|
| Languages | Ordered list, chosen with the language picker. Example: `Hungarian, English` | Preferred audio languages from Settings |
| Tracks per language | None · **First matching track** · All matching tracks (HandBrake parity) | First matching |
| If a language has several tracks | Source order · Most channels · Best quality (lossless first, then highest bitrate) | Best quality |
| Undetermined (`und`) tracks | Treat as the first listed language · Treat as other language | Other language |
| Other languages | Drop · Keep first track · Keep all | Drop |
| No listed language found | Take the default-flagged track · Take the first track · Take none (validation error) | Default-flagged track |
| Commentary and audio description | Drop · Keep, after the main tracks | Drop |
| Output order | Language list order · Source order | Language list order |
| Default track | First output track · First track in the first language · None | First output track |

When no language is set at all (the preset has none and Settings has no preferred languages),
every track is kept in source order with its source flags (at most one default track), and
the other settings wait until a language is set. A listed language takes the tracks of that
language: `ger` = `de`; `pt` takes `pt-BR` and `por`, `pt-BR` takes only `pt-BR`. The default
track setting changes only the default flag; the other flags come from the source track.
Details (unknown bit rates in the tie-break, `und` tracks, music-only tracks, the order):
[0031](../decisions/0031-audio-and-subtitle-selection-stage.md).

#### 2. Codec rules: how each selected track is encoded

Reframe checks the rules from top to bottom for each selected track. **The first matching rule
wins.** The last rule (`Any` / `Any`) always exists and cannot be deleted. Drag rows to reorder
them.

```
 #  Language     Source channels  →  Codec   Mixdown     Max bitrate   If the source already fits
 1  Hungarian    5.1 or more      →  AC-3    5.1         320 kb/s      Passthru
 2  English      5.1 or more      →  AC-3    5.1         384 kb/s      Passthru
 3  Any          Stereo or less   →  AAC     Stereo      160 kb/s      Passthru
 4  Any          Any              →  Opus    Up to 5.1   256 kb/s      Re-encode
```

| Column | Values |
|--------|--------|
| Language | One language, several languages, or Any |
| Source channels | Any · Mono · Stereo or less · 5.1 or more · 7.1 or more. This is a condition on the **source** track |
| Codec | Any audio encoder, or Passthru |
| Mixdown | Keep source · Up to 5.1 (only downmixes 7.1) · 5.1 · Stereo · Dolby Pro Logic II · Mono. A mixdown never upmixes: a source with fewer channels keeps its layout, because FFmpeg's upmix only adds silent channels ([0019](../decisions/0019-audio-codec-rule-details.md)) |
| Max bitrate | The target bitrate. It snaps to the encoder's allowed values (AC-3 and E-AC-3 use fixed steps). A note shows any snap |
| If the source already fits | Passthru · Re-encode |

Expand a row for the optional settings: sample rate, gain, DRC, loudness normalisation, name
template (`{lang_native} {channels}` → `Magyar 5.1`), "only for the first track of this
language", and **extra outputs** (for example, also add an AAC stereo track for compatibility.
This is HandBrake's encoder list, per rule).

**Max bitrate rules.** Reframe never makes a track bigger than its source:

| Source | Result |
|--------|--------|
| The source **fits**: its codec is on the passthru list, the container can hold it, its channels are within the mixdown, and the rule changes nothing that needs a decode (gain, DRC, loudness, sample rate). A **lossy** source fits at any bitrate (re-encoding it would only add a generation loss); a **lossless** source only when its bitrate is at or below the max ([0023](../decisions/0023-lossy-passthru-above-the-max.md)) | Passthru (or re-encode, if the rule says so) |
| Lossless (TrueHD, DTS-HD MA, FLAC, PCM) with a bitrate above the max or unknown, or a source that does not fit with a bitrate above the max | Encode at the max bitrate |
| Bitrate at or below the max, but the source does not fit (another codec, or too many channels) | Encode at the smallest allowed bitrate that is at or above the source bitrate |
| Bitrate unknown, and the source is lossless or does not fit | Treated as above the max. The preview says so and offers **Measure** |

A rule with no max bitrate on a lossy encoder (a passthru rule's fallback encoder, for
example) uses the encoder's default bitrate for the layout as its max
([0019](../decisions/0019-audio-codec-rule-details.md)).

With your setup (the codec in this example is AC-3; any encoder works):

| Source track | Rule | Output | Why |
|--------------|------|--------|-----|
| hun · DTS-HD MA 5.1 · 2 104 kb/s | 1 | AC-3 5.1 · 320 kb/s | Lossless source → encode at the max |
| hun · AC-3 5.1 · 224 kb/s | 1 | Passthru | AC-3, 5.1, 224 ≤ 320: passthru |
| eng · TrueHD Atmos 7.1 | 2 | AC-3 5.1 · 384 kb/s | Downmix 7.1 → 5.1. Lossless source → encode at the max |
| eng · AC-3 2.0 · 192 kb/s | 3 | Passthru | Rule 2 needs 5.1 or more. Rule 3 matches, and the source fits (a lossy source is kept above the max) |

#### 3. Passthru and fallback (HandBrake parity)

- **Allowed passthru codecs**: AC-3, E-AC-3, DTS, DTS-HD, TrueHD, AAC, MP3, FLAC, Opus
  (check boxes).
- **Fallback encoder**: used when a rule says Passthru, but the source codec is not allowed or
  the container cannot hold it.

#### Live preview

The dialog shows what the defaults do with the current source. In a batch group, it shows every
file in the group. There is one row per source track:
`source track → selected? (why) → rule # → output → reason`.
Each edit updates the preview at once, so you do not have to queue a job to find out what a
rule does.

#### How the defaults are applied

- When a source opens, Reframe applies the preset's audio defaults.
- Manual changes on the Audio tab override them for that file. **Reload from preset rules**
  applies the defaults again.
- In a batch group, the defaults apply to every file. Manual changes become explicit track rules
  ([04 §Track rules](04-batch-mode.md#track-rules)).
- Validation: a rule that is shadowed by an earlier rule (warning), a rule that matches no track
  in this source (info), a max bitrate outside the encoder's range (snapped, with a note), a
  codec that the container cannot hold (error, with fixes).

---

## Subtitles

### Source track table

| # | Lang | Name | Format | Type | Events | Role & flags |
|---|------|------|--------|------|--------|--------------|
| 1 | eng | Signs & Songs | ASS | text | 212 | `Forced`, `Signs` |
| 2 | eng | Full | ASS | text | 3 410 | `Default` |
| 3 | eng | SDH | PGS | bitmap | 3 655 | `SDH` |
| 4 | hun | — | SRT | text | 3 102 | |

- **Events** come from Matroska `NUMBER_OF_FRAMES` tags, or from a packet count scan on request.
  A low count relative to other tracks in the same language suggests a forced track.
- Roles: `Forced`, `SDH`, `Signs & Songs`, `Commentary`. Badges are solid or outlined, as in Audio.

### Output tracks

| Action | Allowed for | Notes |
|--------|-------------|-------|
| Copy | all formats the container supports | MP4: only `mov_text` (text is converted automatically) and VobSub (as HandBrake does). PGS cannot go into MP4: a validation error offers burn-in or MKV ([0010](../decisions/0010-definitions-filters-and-containers.md)) |
| Burn in | one track per job | Text uses the `subtitles` filter, on the final picture. Bitmap uses `overlay` after the crop; when the crop removes lines, the subtitle canvas is aligned with the bottom of the picture ([0013](../decisions/0013-command-builder-details.md)). **Forced only** uses the decoder option `forced_subs_only`, which only PGS and VobSub have; a copied track keeps every event ([0014](../decisions/0014-validation-rules-and-severities.md)) |
| Convert | text → SRT / ASS / WebVTT / mov_text | |

- **Foreign audio search** (HandBrake parity): when the audio is in the first subtitle language
  (the viewer's language), Reframe takes the forced-subtitle track of that language: from the
  forced flag or title, from event counts and, for PGS and VobSub, from forced flags found in a
  scan of the track (background task; [0032](../decisions/0032-analysis-scans-and-their-fixtures.md)).
  The track goes first and gets the forced flag. Burn-in "foreign audio" burns it, or, when the
  audio is in another language, the first subtitle in the viewer's language
  ([0031](../decisions/0031-audio-and-subtitle-selection-stage.md)).
- **External subtitles**: add `.srt`, `.ass`, `.ssa`, `.vtt` or `.sup` files. Settings:
  language, name, flags, time offset (ms), and character encoding (auto-detected, can be
  changed).
- **Default track policy**: none / first output track / forced track.
- **Subtitle defaults** (HandBrake parity, stored in the preset): the same track selection
  part as [Audio defaults](#audio-defaults-stored-in-the-preset) (languages, first/all
  matching, other languages, `und` handling), plus foreign audio search, burn-in behaviour
  and default track. A live preview works the same way.

---

## Track metadata & languages

Every output audio and subtitle track (and the video track) has an mkvtoolnix-style metadata
block:

| Field | Control | Written as |
|-------|---------|------------|
| Language | Language picker (below) | MKV: `language` (ISO 639-2/B) + `LanguageIETF` (BCP 47). MP4: ISO 639-2/T |
| Name | Text, or a name template such as `{lang_name} {channels} {codec}` → `Japanese 5.1 Opus` | `title` |
| Default | Toggle (only one track per type can be default, unless you override this) | disposition / FlagDefault |
| Forced | Toggle | FlagForced |
| Commentary | Toggle | FlagCommentary |
| Hearing impaired | Toggle | FlagHearingImpaired |
| Visual impaired | Toggle | FlagVisualImpaired |
| Original language | Toggle | FlagOriginal |

Flags that the installed FFmpeg cannot write go through a `mkvpropedit` step after muxing.
If `mkvpropedit` is missing, a warning explains which flags will be lost.

**Language picker** (like mkvtoolnix):

- Search by English name, native name, ISO 639-1/2/3 code, or full BCP 47 tag.
- A **favourites** section at the top (set in Settings), then all languages.
- Region and script subtags: `pt-BR`, `es-419`, `zh-Hans`, `sr-Latn`.
- Shows what will be written: `Hungarian · hun (ISO 639-2) · hu (BCP 47)`.
- **Bulk edit**: select several tracks and set language or flags for all of them at once.

---

## Chapters

HandBrake parity:

- **Create chapter markers** toggle.
- Table: number, start, duration, name (editable).
- Import / export: CSV, OGM text, Matroska XML.
- Reset names to the source names, or to `Chapter N`.
- New: **Generate chapters** every N minutes when the source has none.

## Tags

HandBrake parity: Title, Actors, Director, Release date, Comment, Genre, Description, Plot.
"Passthru common metadata" (on the Summary tab) copies the source values first. Tag fields can
use the same variables as [Output naming](#output-naming). Example Title:
`{name}< – S{season:02}E{episode:02}>< – {sub_title}>`.

---

## Output naming

**HandBrake:** 17 variables, all taken from the source file name or the job settings. Release
names are not parsed, so `{source}` gives you the whole
`Movie.2016.2160p.BluRay.REMUX-Group` string, or a bad file name when the folder has the
better name.

**Reframe:** supports every HandBrake variable with the same meaning. It also parses the
release name (with `guessit`), picks the more complete name from the file or its folder, and
adds variables for the clean title, the episode parts and the output media.

### Where the name comes from

Reframe parses up to two candidates, the **file name** and the **folder name**, and uses the
better one. This is the **name source**.

- **Auto** (default):
  1. Skip generic folders, and look one level higher instead (at most 2 levels, never above
     the opened folder or media root). Generic folders are `Season 03`, `S03`, `Specials`,
     `Extras`, `Featurettes`, `Disc 1`, `CD1`, `BDMV`, `STREAM`, `VIDEO_TS`.
  2. If the folder holds several episode files (a season pack), the **file name** is the name
     source, because only it has the episode number and title. The same holds when only the
     file name has an episode number (a season folder such as `The.Sopranos.S03.1080p…`, or a
     show folder such as `Breaking Bad (2008)`, when the other episodes are not there).
     The folder only fills fields that the file name does not have (for example the year,
     or the show name in front of a bare `S01E01.mkv`). Files in `BDMV`, `STREAM` and
     `VIDEO_TS` are never episodes. ([0012](../decisions/0012-output-naming-rules.md))
  3. Otherwise, the candidate with the higher score wins. Score: +1 for each recognised field
     (title, year, resolution, source, video codec, audio codec, HDR, edition, release group),
     +2 if the title has word separators (`Hacksaw.Ridge`, not `hacksawridge`). On a tie, the
     file name wins.
- **File name** or **Folder name**: forced. Set it in the naming options, or per file in the
  preview.

The naming preview always shows which candidate won and why, for example "Folder name: 11
fields recognised, file name: 3".

### Variables

**HandBrake parity** (same names, same meaning):

| Variable | Value |
|----------|-------|
| `{source}` | The source name. In Reframe, this is the chosen name source (file or folder) |
| `{title}` | Title number (disc input, post-v1), or the file's index, as in HandBrake. Use `{main_title}` for the name |
| `{chapters}` | Selected chapter range, for example `1-12` |
| `{date}` · `{time}` | Current date and time |
| `{creation-date}` · `{creation-time}` | Creation date/time from the source metadata (container `creation_time`, else the file system) |
| `{modification-date}` · `{modification-time}` | The source file's modification date/time |
| `{preset}` | Preset name |
| `{width}` · `{height}` | Output storage width and height |
| `{codec}` | Video format, for example `H.265` |
| `{encoder}` | Short encoder key, HandBrake style: `x265`, `svt_av1`, `nvenc_h265` |
| `{encoder_bit_depth}` | `8` or `10` |
| `{quality_bitrate}` | The quality value (CRF/CQ) or the bitrate from the Video tab |
| `{quality_type}` | `Q` for constant quality, `kbps` for average bitrate |

Dates default to ISO format (`2026-10-11`) and times to `14-30`, because the system's short
date format can contain `/` and `:`, which are not allowed in file names. A format spec changes
this: `{date:%d.%m.%Y}`.

**Name parts**, parsed from the name source. Text keeps its original spelling and separators:

| Variable | Meaning | Hacksaw Ridge | The Sopranos S03E02 |
|----------|---------|---------------|---------------------|
| `{main_title}` | The leading part of the name, cut at the first release tag (year, resolution, source, codec, edition, group). For an episode, the episode code and episode title stay, and a year between the show name and the episode code stays too (`Doctor.Who.2005.S01E01.Rose`) | `Hacksaw.Ridge` | `The.Sopranos.S03E02.Proshai.Livushka` |
| `{name}` | Movie title or show name only | `Hacksaw.Ridge` | `The.Sopranos` |
| `{sub_title}` | Episode title | — | `Proshai.Livushka` |
| `{season}` · `{episode}` | Numbers. `{season:02}` → `03` | — | `3` · `2` |
| `{episode_code}` | As written in the name, including multi-episode codes (`S03E02E03`) | — | `S03E02` |
| `{year}` | Release year | `2016` | — |
| `{edition}` | Director's Cut, Extended, IMAX, … | — | — |
| `{source_type}` | BluRay, UHD.BluRay, WEB-DL, … | `UHD.BluRay` | `BluRay` |
| `{release_group}` | Release group | `HenDerson` | `Kataklysm` |
| `{file_name}` · `{folder_name}` | The raw file name (without extension) and folder name | | |
| `{container_title}` | Title tag stored in the source container | | |

**Output media**, from the job settings:

| Variable | Example |
|----------|---------|
| `{resolution}` | `2160p`, `1080p`, `720p`, `576p`, `480p`, or `WxH` (ASCII `x`: `640x360`) for other sizes |
| `{hdr}` | `HDR10`, `HDR10+`, `DV`, `HLG`. Empty for SDR |
| `{acodec}` · `{audio_channels}` | First output audio track: `AC-3` · `5.1` |
| `{audio_langs}` · `{sub_langs}` | Output track languages: `HUN-ENG` |
| `{container}` | `MKV`, `MP4`, `WebM` |

### Template syntax

| Syntax | Meaning |
|--------|---------|
| `{variable}` | Insert the value |
| `{variable:spec}` | Numbers: `{season:02}`. Dates: `{date:%Y-%m-%d}`. Text: `:upper`, `:lower`, `:title` |
| `<…>` | **Optional group.** It is dropped when any variable inside it is empty, so one template works for movies and episodes. `<` and `>` cannot appear in file names on Windows, so they never clash with literal text |
| `/` | Creates subfolders under the output folder |
| `{{` · `}}` | Literal braces |

An unknown variable is a validation error with a "did you mean …" fix. A width or precision
of more than 255 in a format spec (`{season:999}`) is a validation error: a file name has at
most 255 bytes ([0012](../decisions/0012-output-naming-rules.md)).

### Options

| Option | Values | Default |
|--------|--------|---------|
| Movie template | Template | `{main_title}` |
| Episode template (used when season/episode are recognised) | Template | `{main_title}` |
| Name source | Auto · File name · Folder name | Auto |
| Word separator (applies to text from the name) | Keep source · Space · Dot · Underscore | Keep source |
| Title case (HandBrake) | on / off | off |
| Replace underscores with spaces (HandBrake) | on / off | off |
| Remove common punctuation: dashes, periods, commas (HandBrake) | on / off | off |
| MP4 extension (HandBrake) | `.mp4` · `.m4v` · Auto (`.m4v` with AC-3 passthru, chapters or 3GPP subtitles) | `.mp4` |
| Output folder | Fixed folder · Same as source | From Settings |

The defaults live in **Settings → Output**. A preset can override them. A single job can have
a manual name (**Reset to template** brings the template back).

### Examples

Sources:
- `Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson/hacksawridge.2160p.remux-henderson.mkv`
  → name source: **folder** (more fields recognised; the file's title has no word separators).
- `The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm/The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv`
  → name source: **file** (the folder is a season pack).

Output to MKV at 1080p:

| Template | Hacksaw Ridge | The Sopranos S03E02 |
|----------|---------------|---------------------|
| `{main_title}` (default) | `Hacksaw.Ridge.mkv` | `The.Sopranos.S03E02.Proshai.Livushka.mkv` |
| `{main_title}.{resolution}` | `Hacksaw.Ridge.1080p.mkv` | `The.Sopranos.S03E02.Proshai.Livushka.1080p.mkv` |
| `{name}< ({year})>< - S{season:02}E{episode:02}>< - {sub_title}>`, separator Space | `Hacksaw Ridge (2016).mkv` | `The Sopranos - S03E02 - Proshai Livushka.mkv` |
| `{name}/<Season {season:02}/>{main_title}` | `Hacksaw.Ridge/Hacksaw.Ridge.mkv` | `The.Sopranos/Season 03/The.Sopranos.S03E02.Proshai.Livushka.mkv` |
| `{source}-{title}` (HandBrake default) | `Hacksaw.Ridge.2016.HYBRID.….HUN-HenDerson-1.mkv` | `The.Sopranos.S03E02.….REMUX-Kataklysm-1.mkv` |

### Safe file names

- Windows rules apply on **every** OS, because files move between systems: the characters
  `< > : " / \ | ? *` and control characters are replaced (`": "` → `" - "`; `:` `/` `\` `|`
  → `-`; `"` → `'`; `< > ? *` and control characters are removed), reserved names (`CON`,
  `NUL`, …) get a `_`, and trailing dots and spaces are removed.
- A byte of a source name that is not UTF-8 (a POSIX name such as `bad\xffname.mkv`) becomes
  `�` (U+FFFD) in the output name: such a name cannot be written on Windows or in JSON.
- Each path part has a limit of 255 bytes. The file name (with its extension) keeps room for
  the `.part` of the partial file, so it has 250 bytes. `{sub_title}` is shortened first,
  then `{main_title}`. The limit holds after every rule (the `_` of a reserved name too). An
  empty result falls back to `{file_name}`.
  ([0012](../decisions/0012-output-naming-rules.md))
- Collisions follow the collision setting ([Queue](#queue)). In a batch, duplicate names are
  errors ([04 §Output naming](04-batch-mode.md#output-naming)).

### Naming editor

It is in Settings → Output, in the preset editor, and on the Summary tab's Output card:

- A template field with autocomplete after `{`, and variable chips that show the value for the
  current source (click to insert).
- A **parsed name** panel: the chosen name source and why, the name with coloured spans (title,
  year, episode, resolution, source, group), and editable fields. An edit is a per-file
  override, for when the parser gets a name wrong.
- A live preview of the result. In a batch group, it shows every file.

---

## Preview

- **Frame strip**: N evenly spaced frames (default 10, configurable), or seek to any timestamp.
- **View modes**: Source · Output (crop + scale + filters, rendered by FFmpeg) · Split slider ·
  Side by side. Zoom: fit / 100% / 200%.
- **Live preview clip** (HandBrake parity): encode 10 / 15 / 30 / 60 s from the current
  position with the full job settings. The clip plays in the built-in player if the webview
  can decode it. If not, **Open in external player**.
- **Encoded frame compare**: FFmpeg decodes frames from the preview clip to PNG, and the split
  view shows them next to the matching source frame. This works for every codec, even when
  the webview cannot play the clip.
- Frames are cached on disk by source fingerprint + timestamp + settings hash.

---

## Presets

Same behaviour as HandBrake:

- Categories (built-in, read-only): General, Web, Devices, Matroska, Hardware, Production.
  Contents are modelled on HandBrake's defaults and adapted to FFmpeg encoders (the list,
  the HandBrake 1.11.2 values and the differences: [decision 0015](../decisions/0015-presets-and-settings-stores.md)).
  The default preset is *H.265 MKV 1080p* ([decision 0024](../decisions/0024-m2-wave-2-product-decisions.md)).
- User presets: save new, update, rename, duplicate, delete, set as default. Preset names are
  unique (without case); a clash offers the next free name, *Name (2)*. An import with clashes
  can rename, replace or skip.
- A **modified** marker appears when the current settings differ from the selected preset.
  Hover it to see what changed.
- Import / export JSON (Reframe schema, versioned).
- A preset holds everything except source-specific data: container options, dimensions,
  filters, video including advanced options, audio and subtitle **rules**, chapter and tag
  options, and naming template.
- Later: import HandBrake preset JSON (map the common fields, report fields it skipped).

---

## Queue

- States: `Waiting` · `Running` · `Paused` · `Done` · `Failed` · `Cancelled` · `Interrupted`.
- Columns: source, output, preset, progress, fps, speed, ETA, current size.
- Actions: start / pause / resume / cancel (per job and all), reorder by dragging, retry,
  duplicate, **edit** (loads the job back into the editor), remove, open the output folder.
- **Pause** suspends the FFmpeg process (psutil suspend/resume, works on both OSes).
- **Parallel jobs**: setting, default 1.
- **Persistence**: the queue survives restarts. Running jobs become `Interrupted` and can be
  restarted. One Reframe process owns the saved queue at a time; another process (a second
  CLI command, for example) runs its jobs in a private queue that is not kept
  ([decision 0027](../decisions/0027-one-process-owns-the-queue-store.md)).
- Output safety: Reframe writes to `<name>.part.<ext>`, probes it again and checks its tracks
  and languages, and renames it on success. A failed job removes its partial file
  (configurable). File name collisions follow the setting: ask, auto-rename, or overwrite.
  When the name is taken at the end and the setting is "ask", the job fails and the finished
  `.part` file is kept ([decision 0016](../decisions/0016-queue-and-job-runner.md)).
- **When done**: nothing · notify · quit · sleep · shut down (desktop and bare-metal only).
- **Sleep inhibit** while encoding (Windows `SetThreadExecutionState`, Linux the desktop
  session's inhibit and logind over D-Bus). It stops automatic (idle) sleep only: the user's own Sleep, the
  power button and the lid always work, and the encode then pauses with the system and
  continues after wake ([decision 0020](../decisions/0020-m2-wave-1-product-decisions.md),
  Linux mechanism [0022](../decisions/0022-linux-sleep-inhibit-mechanism.md)).
- Per-job **log**: the full command, FFmpeg output, timing, and a copy button for bug reports.

---

## Remux-only jobs

These cover the "I only want to fix languages and flags" case, without re-encoding:

| Condition | Job type | Speed |
|-----------|----------|-------|
| Video passthrough + all audio and subtitle tracks copied | **Remux** (FFmpeg `-c copy`) | Disk speed |
| Source is MKV, track set and order unchanged, only metadata changed, "Edit in place" chosen | **Metadata edit** (`mkvpropedit`) | Seconds |

The Summary tab shows which job type you will get, and why.

---

## Settings

| Section | Contents |
|---------|----------|
| Tools | ffmpeg, ffprobe, mkvpropedit, mediainfo. Each shows its version and where it comes from (bundled, settings, environment). A path override field, **Test** and **Use bundled** buttons. Overrides from environment variables are read-only |
| Encoders | Table of all known encoders: status, reason, last check time. **Re-scan** button. Hardware test encodes on / off. VAAPI device (automatic, or one `/dev/dri/renderD*` node; [decision 0020](../decisions/0020-m2-wave-1-product-decisions.md)) |
| Output | Default folder, [naming](#output-naming) templates and options, default container, collision behaviour, partial file behaviour |
| Languages | Favourite languages. Preferred audio and subtitle languages (used by preset rules) |
| Preview | Number of sample frames, cache size limit, clear cache |
| Queue | Parallel jobs, when done, sleep inhibit, notifications |
| Appearance | Theme, density, UI language |

---

## Validation and error display

Every job is validated live. The core returns a list of `ValidationIssue` objects:

```
severity: error | warning | info
code:     "encoder.unavailable" | "container.codec_unsupported" | "subtitle.burn_multiple" | …
path:     "video.encoder" | "audio[2].encoder" | …
message:  human-readable text
fixes:    [{label: "Use libx265", patch: {...}}]
```

- Fields show issues inline (red or amber outline + text).
- The Summary "Issues" card and the status bar list all issues.
- `error` blocks **Add to queue**. `warning` does not.
- A **fix** is a JSON patch on `JobSettings`. Clicking it applies the patch on the client, and
  the job is validated again.
