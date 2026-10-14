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

## Follow-up (M2 review), 2026-10-14

The M2 review found definition values that the tools ignore or refuse. Each was checked again
with the three builds (Arch n9.0.2, BtbN n9.0.2, BtbN n8.1.3) and, for AMF and VAAPI, the
RX 7600; `testdata/README.md` "Encoder definitions (C-6)" has the evidence.

1. **A range end must have its own effect.** SVT-AV1 `-crf 0`, VAAPI `-global_quality 0` and
   AMF AV1 QP 0 mean "not set" (the encoder's default quality), so the best end is 1 for these
   encoders; h264 / hevc VAAPI stop at 51 (52 gives the same file). `convert_quality` then
   clamps a low value to 1. x265 `ref` stops at 8 (9 and more fail with B-frames), `merange`
   at 32767, and SVT-AV1 `lookahead` is 0–120 with "encoder decides" as its default (`-1` is
   rejected). Tests: the ends of every quality range and every number option are encoded and
   compared (`test_quality_range_ends_are_honoured`, `test_option_range_ends_encode`).
2. **Rules across two options stay out of the ranges.** x265 needs `rc-lookahead` above
   `bframes`; x264 uses `subme` 10 and 11 only with `trellis=2` (else it writes 9 without a
   message). The help text says so, and `test_recorded_cross_option_rules` records the
   behaviour; validation (C-8) is the place for the check.
3. **`CodecSupport.copy_except`.** `copy = ["*"]` lets every codec through; Matroska refuses a
   set of PCM-like and other codecs ("No wav codec tag found", exit 234) and writes some that
   FFmpeg cannot read back. They are listed per track type in `copy_except`, so they are
   encoded instead of copied (PCM-like codecs that cannot be made as a stream are denied to be
   safe). The linter checks that a deny list goes with `"*"` and does not overlap the copy list.
4. **Defaults on the conversion scale.** Every default quality is what x264 RF 22 converts
   to: `h264_vaapi` 20 → 25 and `av1_qsv` 24 (HandBrake's 2160p value) → 22. Values are
   rounded half up (`round_half_up`), so a half step converts the same way on every scale.
5. **`DerivedValue.factor`.** `av1_nvenc` takes `-cq` 0–63 but `-init_qp*` 0–255
   (`ffmpeg -h encoder=av1_nvenc`): the initial QPs are the CQ value × 255/63 with the H.265
   offsets scaled the same way (∓8). Not checked on NVIDIA hardware.
6. **Preset order and placeholders are linted.** Speed presets are listed fastest first (the
   contract); SVT-AV1 was slowest first and is reversed. The linter knows the speed order of
   the x26x / QSV / VP9 words, the AMF words, NVENC `pN` and numeric presets (higher is
   faster), and reports a preset it cannot place. It also checks the placeholders of
   `hardware_setup` and that `codec_tags` name codecs the container holds.
7. **Version differences are tested, not skipped.** n8.1.3 lacks `high_quality` for
   `h264_amf` / `hevc_amf` (`supported_presets` hides it there); n8.1.3 reads svq1 back from
   Matroska, n9.0.2 does not. The tests assert what each version does.

Recorded for other steps: `av1_amf` on the RX 7600 writes 1920x1080 as 1920x1082 (and 720x480
as 768x480), while `av1_vaapi` keeps the size (`test_av1_amf_pads_the_picture`); a note in
validation (C-8) or a crop in the builder (C-7) is for the lead to decide.

The plan does not change: 05 §C-6 asks for value ranges, allowed codecs and presets, and these
are corrections of the data within that.
