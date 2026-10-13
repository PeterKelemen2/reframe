# 0010 — Definitions: VobSub in MP4, filter implementations, HandBrake filter mapping

- Status: accepted
- Date: 2026-10-13
- Steps: C-6 (affects C-7, C-8, F-8)

## Context

C-6 writes the encoder, container and filter definitions and checks them against FFmpeg
n9.0.2 (`packages/reframe/tests/definitions/test_tools.py`, `testdata/README.md` "Encoder
definitions (C-6)"). Three things in the plan did not match what the tools do or what the
data model could hold.

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

### 2. A filter with two implementations

03 §Filters gives Denoise two implementations (`hqdn3d`, `nlmeans`), Deinterlace two (`bwdif`,
`yadif`) and Sharpen two (`unsharp`, `cas`); Colorspace and Tone mapping have `zscale` and
`libplacebo`. HandBrake stores the implementation in a field of its own
(`PictureDenoiseFilter`: `nlmeans` | `hqdn3d`, `PictureSharpenFilter`: `unsharp` |
`lapsharp`, `PictureDeinterlaceFilter`: `decomb` | `yadif` | `bwdif`), and each implementation
has its own presets (Yadif has "Skip spatial check", Bwdif does not). Reframe's
`FilterConfig` (C-2) had only `preset`, `tune` and `custom`.

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
2. **`FilterConfig` gets `implementation: str | None`**, as in HandBrake. `None` = the
   filter's default: the first implementation the build can run that has the chosen preset.
   A new field needs no schema bump (CLAUDE.md "Persistence rules": older versions keep
   unknown fields). In the definitions each implementation (`FilterImplementation`) has its
   own presets, tunes and default preset, with HandBrake's names: Denoise NLMeans (default;
   Ultralight … Strong, Custom, with the tunes) or HQDN3D (Ultralight … Strong, Custom);
   Deinterlace Bwdif (default; Default, Bob, Custom) or Yadif (Default, Skip spatial check,
   Bob, Custom); Sharpen Unsharp (default; Ultralight … Very strong, Custom, with the tunes) or
   CAS (Light, Medium, Strong, Custom: no HandBrake equivalent, HandBrake's LapSharp is not in
   FFmpeg); Tone mapping libplacebo (default) or zscale + tonemap; Colorspace zscale (default)
   or libplacebo. `FilterDef.implementation_for(config, available)` and
   `FilterDef.chain_for(config, available)` resolve a config; an explicit implementation that
   cannot run resolves to nothing (the validation reports it) instead of falling back. The
   linter checks that every implementation's presets are complete (a default, a chain for
   every preset and every tune, only the implementation's own filters).
3. **The mapping is documented in `filters.toml`** (header and each preset's `handbrake`
   field): NLMeans `s = patch · strength / 10` from the two weight formulas, with the luma
   values, clamped to 1 … 30; HQDN3D 1:1; deblock exactly as HandBrake converts it
   (`libhb/deblock.c`); unsharp and chroma smooth 1:1 (HandBrake's filters are ports of
   FFmpeg's `unsharp`), Very strong chroma smooth written as -2; interlace detection with
   `idet` (Less sensitive raises `intl_thres` to 1.5, Fast equals Default); detelecine with
   `fieldmatch,decimate` defaults; the CPU tone mapping implementation offers Hable (its
   default), Mobius and Reinhard. The libplacebo implementations carry `needs_vulkan = true`.

## Consequences

- C-8 reports "bitmap subtitle into MP4" only for PGS. VobSub in MP4 plays in fewer players
  than MOV_TEXT; the help can say so (F-8).
- C-8 reports an unknown implementation, a preset or tune that the chosen implementation does
  not have, and an implementation the build cannot run. The filter UI (F-8) shows an
  implementation picker for the filters that have more than one.
- NLMeans output differs from HandBrake's at the same preset (no temporal frames, one
  strength); the Grain tune denoises luma lightly instead of not at all.
- Whether `libplacebo` really runs (a one-frame test) is checked by C-4 before it is chosen;
  otherwise the default falls to `zscale`.

## Plan changes

- `docs/plan/03-features.md` §Filters: the implementations and preset lists of Denoise,
  Deinterlace, Sharpen and Chroma smooth, the implementation choice, and "libplacebo if
  available and Vulkan works".
- `docs/plan/03-features.md` §Subtitles, Output tracks: VobSub can be copied into MP4.
- `docs/plan/05-core.md` §C-8: "PGS subtitle into MP4" instead of "bitmap subtitle into MP4".
