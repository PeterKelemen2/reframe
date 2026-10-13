# 0015 — Built-in presets from HandBrake 1.11.2, and how the stores handle files

- Status: accepted; the default preset is superseded by [0024](0024-m2-wave-2-product-decisions.md)
- Date: 2026-10-13
- Steps: C-9

## Context

05 §C-9 asks for built-in presets as package JSON, user presets in `<config>/presets.json`,
CRUD with name-conflict handling, import / export, `diff`, settings in
`<config>/settings.json` with atomic writes, migrations, and "a corrupt file is backed up and
replaced with defaults plus a warning event". 03 §Presets says the built-ins are "modelled on
HandBrake's defaults and adapted to FFmpeg encoders". The plan does not give the values, the
names, the default preset, the conflict rules, or what to do with a file that is only partly
damaged, newer than this Reframe, or unreadable.

**Source of the values.** HandBrake 1.11.2 (the latest release, 2026-06-07),
`preset/preset_builtin.json` at tag `1.11.2`, read from github.com/HandBrake/HandBrake. Speed
preset names: `libhb/nvenc_common.c` `hb_map_nvenc_preset_name` (`medium` → `p4`) and
`libhb/qsv_common.c` `hb_map_qsv_preset_name` (`speed` → `veryfast`). Audio:
`libhb/preset.c` `add_audio_for_lang` / `sanitize_audio_codec` and `libhb/common.c`
`hb_audio_encoder_get_fallback_for_passthru` (a `copy:ac3` entry on a source that is not AC-3
encodes with the AC-3 encoder). HandBrake's default preset is `Fast 1080p30`
(`"Default": true`).

**Checked with FFmpeg n9.0.2** (the pinned BtbN build and the system build): every
`VideoOptionExtra` string that the built-ins keep runs without a warning (x264, x265, SVT-AV1
v4.2, including `keyint=10s`, `ac-bias`, `qp-scale-compress-strength`). A bad key in
`-x264-params`, `-x265-params` or `-svtav1-params` is only a warning ("Error parsing option",
"Unknown option") with exit code 0. Test: `tests/presets/test_builtin.py`
(`test_handbrake_parameter_strings_work_in_ffmpeg`, `test_a_bad_parameter_key_is_only_a_warning`).

## Decision

### 1. The built-in presets (26)

| Category | Reframe presets (id) | From HandBrake 1.11.2 |
|----------|----------------------|-----------------------|
| General | `very-fast-1080p30`, `fast-1080p30` (default), `fast-720p30`, `hq-1080p30-surround`, `super-hq-1080p30-surround`, `fast-2160p60-4k-hevc` | the presets of the same name |
| Web | `creator-1080p60`, `social-25-mb-1-minute-720p60` | same name |
| Devices | `android-1080p30`, `apple-1080p30-surround`, `chromecast-1080p30-surround` | same name |
| Matroska | `h265-mkv-1080p`, `h265-mkv-720p`, `h265-mkv-2160p-4k`, `h264-mkv-1080p`, `av1-mkv-2160p-4k`, `vp9-mkv-1080p` | `H.265 MKV 1080p30`, `… 720p30`, `… 2160p60 4K`, `H.264 MKV 1080p30`, `AV1 MKV 2160p60 4K`, `VP9 MKV 1080p30` |
| Hardware | `h265-nvenc-1080p`, `h265-nvenc-2160p-4k`, `h265-qsv-1080p`, `av1-qsv-2160p-4k`, `h265-vcn-1080p`, `av1-vcn-2160p-4k`, `h265-vaapi-1080p` | same name; VAAPI: none (made from `H.265 VCN 1080p`) |
| Production | `production-standard`, `production-proxy-1080p` | same name (HandBrake's category is "Professional") |

Field mapping (HandBrake key → Reframe field):

- `VideoEncoder` → `video.encoder`: `x264` → `libx264`, `x265_10bit` → `libx265` with
  `bit_depth` 10, `svt_av1_10bit` → `libsvtav1` 10-bit, `vp9` → `libvpx-vp9`, `nvenc_h265` →
  `hevc_nvenc`, `qsv_h265` / `qsv_av1_10bit` → `hevc_qsv` / `av1_qsv`, `vce_h265` /
  `vce_av1_10bit` → `hevc_amf` / `av1_amf`. `VideoQualityType` 2 → constant quality with
  `VideoQualitySlider` on the encoder's own scale; 1 → average bitrate (`VideoAvgBitrate`,
  `VideoMultiPass`, `VideoTurboMultiPass`). `VideoPreset`, `VideoProfile`, `VideoLevel` as they
  are (`auto` → not set; NVENC and QSV names mapped as above; SVT-AV1 tune `psnr` → `1`).
  `VideoOptionExtra` → `custom_params` for x264 / x265 / SVT-AV1; for NVENC `rc-lookahead=10`
  → `advanced["rc-lookahead"]`. `VideoFramerate` + `VideoFramerateMode` (`pfr`, `cfr`, `vfr`)
  → `framerate` + `framerate_mode` (`peak`, `constant`, `variable`).
- `PictureWidth` × `PictureHeight` → `dimensions.size` fit within (0 × 0 → same as source);
  `PictureCropMode` 0 → crop `auto`, 2 → `none`; upscaling off; modulus 2.
  `PicturePAR: auto` (anamorphic) is **not** mapped: Reframe keeps its own default, square
  pixels (03 §Dimensions).
- `PictureDeinterlaceFilter: decomb` + `PictureCombDetectPreset` → `interlace_detection`
  (`default` / `fast`) + `deinterlace` `default` (Bwdif on combed frames, the closest
  FFmpeg form of HandBrake's decomb, decision 0010). Denoise, deblock, sharpen and colourspace
  are off in every source preset.
- `FileFormat` → `output.container`; `Optimize` → `web_optimized`; `AlignAVStart` →
  `align_av_start`; `ChapterMarkers` (always on) → the default.
- **Audio** (decision 0018: the codec rules decide an M2 draft; decision 0023: what "fits"
  means). HandBrake's `AudioList` is a list of encoders for each selected track. An encoder
  entry (`aac`, `opus`) always re-encodes; a `copy:*` entry passes that codec through and
  encodes anything else with the codec's own encoder. So:
  - one `aac` (or `opus`) stereo entry → one catch-all rule: that encoder, mixdown stereo,
    max = `AudioBitrate`, `if_fits = "reencode"`; `passthru.allowed = []`.
  - Surround presets (`aac` stereo 160 + `copy:ac3`) → rule 1: 5.1 or more → AC-3 5.1, max
    640, `if_fits = "passthru"`, extra output AAC stereo 160; rule 2 (catch-all): AAC stereo
    160, `reencode`; `passthru.allowed = ["ac3"]`. HandBrake also adds an AC-3 track for a
    stereo source; Reframe does not (it would copy or re-encode the same stereo audio twice).
  - `AudioEncoderFallback` → `passthru.fallback_encoder` (`opus` → `libopus`; `none` → `aac`,
    because the model needs one). `AudioCopyMask` is not mapped: HandBrake uses it only for
    the auto-passthru encoder, which none of these presets has.
  - `AudioSamplerate` 48 (Creator) → `extras.samplerate` 48000.
  - `AudioTrackSelectionBehavior` `first` / `all` → `selection.tracks_per_language` (`all` also
    keeps other languages); `AudioLanguageList` empty → `languages` from Settings.
- Subtitles: `SubtitleTrackSelectionBehavior: none` → no tracks per language;
  `SubtitleAddForeignAudioSearch` → `foreign_audio_search`; `SubtitleBurnBehavior: foreign` →
  `burn_in: foreign_audio`.

Differences from HandBrake, on purpose:

- **Matroska presets keep the source frame rate**, and their names drop the frame rate
  ("H.265 MKV 1080p", the name of the M2 demo, 08 §M2). HandBrake caps them at 30 or 60 fps
  (peak). The other categories keep HandBrake's caps and names.
- `H.265 VAAPI 1080p` has no HandBrake original (HandBrake has no VAAPI). It copies
  `H.265 VCN 1080p` (QP 25, no crop, source frame rate) for Linux machines without AMF.
- Not built in, because the definitions have no such encoder: HandBrake's Media Foundation,
  VideoToolbox, ProRes, DNxHR and FFV1 presets, and the other sizes of each family (480p,
  576p, 540p, the other Social and Creator sizes, Amazon Fire, Playstation, Roku, Xbox).
  They can be added later as JSON only.

### 2. Preset store rules

- Ids: built-ins have stable slugs; user presets get a UUID. Names are unique among all
  presets (built-in and user), compared without case and repeated spaces. A clash is a
  `ValidationIssue` `preset.name_conflict` with a fix that sets the next free name
  (`Name (2)`). Built-ins cannot be changed, renamed or deleted (`preset.built_in`);
  duplicating one makes a user preset in the `Custom` category.
- If a newer Reframe adds a built-in with the name of an existing user preset, both stay and
  `find(name)` returns the user's preset.
- The default is the user's choice, else HandBrake's default `Fast 1080p30`. Deleting the
  default preset falls back to it.
- Import, `on_conflict`: `rename` (the default: a new id when the id is taken, the next free
  name when the name is), `replace` (overwrite the user preset with the same id or name and
  keep its id; never a built-in: the imported one is renamed) or `skip`. Export of chosen ids
  includes `default_preset_id` when the default is among them; import uses it only when the
  target has no default. Export → import into an empty store gives the same presets, ids and
  default.

### 3. Files (both stores)

- Atomic write: temporary file in the same folder, `fsync`, `os.replace`, folder `fsync` on
  POSIX. On Windows a `PermissionError` from `os.replace` (the target is open in another
  process) is retried 6 times with a doubling pause from 50 ms; on Linux it is not retried.
- **Corrupt** (bad JSON, not an object, a failed migration, a value the model rejects): the
  file is renamed to `<name>.corrupt-<time>.json`, the defaults are written, and an
  `app.warning` (`settings.corrupt` / `presets.corrupt`) names the backup. When only some
  presets in `presets.json` are damaged (or two share an id), the file is backed up, the
  damaged presets are left out and the others are kept. If the backup fails, nothing is
  written.
- **Newer** (`UnsupportedSchemaVersion` with a version above ours) or **unreadable**: the file
  is not touched; defaults (or only the built-ins) are used for this session; saving is
  refused with `settings.not_saved` / `presets.read_only`. A `schema_version` that is not a
  positive integer counts as corrupt. A single preset written by a newer Reframe is kept
  verbatim in `presets.json` and written back unchanged.
- The warnings of the start-up load are published before any UI can subscribe, so each
  store also keeps them (`Reframe.settings.problems`, `Reframe.presets.problems`).
- `settings.json` is read in `Reframe.create()` (one small file); `presets.json` at the first
  use of the presets.

## Consequences

- An M2 draft with an H.265 MKV 1080p job re-encodes every audio track to AAC stereo
  160 kb/s, as HandBrake does; the Surround presets pass AC-3 5.1 through.
- Product questions for the user (each is one JSON value or one constant to change):
  1. Should the Matroska presets keep HandBrake's 30 / 60 fps cap (and its names), or the
     source frame rate as built?
  2. Is `Fast 1080p30` (HandBrake's) the right default, or should it be `H.265 MKV 1080p`?
  3. Should HandBrake's `AudioCopyMask` (`copy:aac` in most presets) become the passthru list
     with `if_fits = "passthru"`? That would pass AAC sources through at any bitrate
     (decision 0023) instead of re-encoding them as HandBrake does.
  4. Should `H.265 VAAPI 1080p` stay, and should the other HandBrake sizes be added?
- No settings change event exists; a UI that shows settings must read them again after an
  update (C-15 / S-3 may add `settings.changed`, a new event model).

## Plan changes

- [03 §Presets](../plan/03-features.md#presets): the built-in list, unique names and the
  conflict choices point here.
- [05 §C-9](../plan/05-core.md#c-9-presets-and-settings-stores): corrupt, newer and
  unreadable files, and the conflict choices, point here.
