# 0010 — Definitions: VobSub in MP4, filter implementations, HandBrake filter mapping

- Status: accepted
- Date: 2026-10-13
- Steps: C-6 (affects C-7, C-8, F-8)

## Context

C-6 writes the encoder, container and filter definitions and checks them against FFmpeg
n9.0.2 (`packages/reframe/tests/definitions/test_tools.py`, `testdata/README.md` "Encoder
definitions (C-6)"). Three things in the plan did not match what the tools do or what the
data model can hold.

### 1. VobSub in MP4

03 §Subtitles says "PGS/VobSub cannot go into MP4". FFmpeg muxes VobSub into MP4 and reads it
back:

```
$ ffmpeg -i vobsub.mkv -map 0:s:0 -c copy out.mp4      # exit 0
$ ffprobe … out.mp4  →  codec_name=dvd_subtitle, codec_tag_string=mp4s
```

HandBrake allows it too (`libhb/common.c` `hb_subtitle_can_pass`: `VOBSUB` for
`HB_MUX_AV_MP4`). PGS has no MP4 tag (`libavformat/movenc.c` `codec_mp4_tags`), so PGS into MP4
stays impossible.

### 2. A filter with two implementations has one preset field

03 §Filters gives Denoise two implementations (`hqdn3d`, `nlmeans`), Deinterlace two (`bwdif`,
`yadif`) and Sharpen two (`unsharp`, `cas`). HandBrake stores the implementation in a separate
field (`PictureDenoiseFilter`: `nlmeans` | `hqdn3d`, `PictureSharpenFilter`: `unsharp` |
`lapsharp`, `PictureDeinterlaceFilter`: `decomb` | `yadif` | `bwdif`). Reframe's
`FilterConfig` (C-2, `reframe.models.job`) has only `preset`, `tune` and `custom`.

### 3. HandBrake values that FFmpeg cannot express exactly

The plan asks for "HandBrake values mapped to FFmpeg parameters, with the mapping
documented". Some HandBrake filters are HandBrake's own code with no exact FFmpeg twin:

- NLMeans: FFmpeg's `nlmeans` is spatial only and has one strength for all planes. HandBrake's
  per-plane strength, origin tune, frame count and prefilter have no equivalent.
- Comb detection (HandBrake's decomb detector) has no FFmpeg filter; the plan already names
  `idet`.
- Detelecine: HandBrake's pullup settings (`skip-top` …) do not apply to `fieldmatch`.
- Chroma smooth Very strong is amount 2.4; FFmpeg's `unsharp` stops at -2.
- `tonemap` (the CPU path) has no BT.2390 curve.
- `libplacebo` is listed by `ffmpeg -filters` but fails without a Vulkan driver
  (`VK_ICD_FILENAMES=/nonexistent.json`: "Error initializing filters … Generic error in an
  external library"), so "if available" is not enough to choose it.

## Decision

1. **VobSub can be copied into MP4** (`containers.toml`: `mp4.subtitles.copy =
   ["mov_text", "dvd_subtitle"]`). Only PGS into MP4 is a validation error.
2. **The second implementation is a family of presets with a prefix**, so no model change is
   needed: Denoise `hqdn3d-ultralight` … `hqdn3d-strong`, `hqdn3d-custom` (NLMeans keeps the
   plain names `ultralight` … `strong`, `custom`, with the tunes); Deinterlace
   `yadif-default`, `yadif-skip-spatial`, `yadif-bob`, `yadif-custom` (bwdif keeps `default`,
   `bob`, `custom`); Sharpen `cas-light`, `cas-medium`, `cas-strong`, `cas-custom` (unsharp
   keeps `ultralight` … `verystrong`, `custom`, with the tunes). Each preset names the
   implementation its chains use (`FilterPreset.chains` is keyed by implementation), and
   `FilterDef.implementation_for()` returns it. Colorspace and tone mapping keep one preset
   list with a chain per implementation (`zscale` and `libplacebo`), and the builder picks
   the first one that works.
3. **The mapping is documented in `filters.toml`** (header and each preset's `handbrake`
   field): NLMeans `s = patch · strength / 10` from the two weight formulas, with the luma
   values, clamped to 1 … 30; HQDN3D 1:1; deblock exactly as HandBrake converts it
   (`libhb/deblock.c`); unsharp and chroma smooth 1:1 (HandBrake's filters are ports of
   FFmpeg's `unsharp`), Very strong chroma smooth written as -2; interlace detection with
   `idet` (Less sensitive raises `intl_thres` to 1.5, Fast equals Default); detelecine with
   `fieldmatch,decimate` defaults; the CPU tone mapping path uses Hable for BT.2390. The
   libplacebo implementations carry `needs_vulkan = true`.

## Consequences

- C-8 reports "bitmap subtitle into MP4" only for PGS. VobSub in MP4 plays in fewer players
  than MOV_TEXT; the help can say so (F-8).
- The filter UI (F-8) shows the prefixed presets as a second group per filter, or splits the
  preset id at the prefix. If a later model change adds an implementation field to
  `FilterConfig`, the prefixed ids map 1:1 to (implementation, preset) — a schema bump with a
  migration.
- NLMeans output differs from HandBrake's at the same preset (no temporal frames, one
  strength); the Grain tune denoises luma lightly instead of not at all.
- C-4 or C-7 must check that `libplacebo` really runs (a one-frame test) before it is chosen;
  otherwise use `zscale,tonemap`.

## Plan changes

- `docs/plan/03-features.md` §Filters: the Denoise, Deinterlace, Sharpen and Chroma smooth
  preset lists, and "libplacebo if available and Vulkan works".
- `docs/plan/03-features.md` §Subtitles, Output tracks: VobSub can be copied into MP4.
- `docs/plan/05-core.md` §C-8: "PGS subtitle into MP4" instead of "bitmap subtitle into MP4".
