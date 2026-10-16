# 0035 — The complete option sets, option rules, custom parameters and the dry run

- Status: accepted
- Date: 2026-10-15
- Steps: C-6 (M9 core part); affects C-7, C-8, C-15 (`reframe plan`), F-9

## Context

05 §C-6 asks for the option sets of 03 §Advanced (coverage table) with per-preset defaults
for x264 / x265; 03 adds the option search, **Copy HDR metadata** and custom parameters
"validated by a dry run (`-frames:v 1 -f null`)". Checking every option with the real encoders
(FFmpeg n9.0.2 Arch with x264 core 165, x265 4.3, SVT-AV1 v4.2.0, libvpx 1.17.0; the BtbN
n9.0.2 and n8.1.3 builds; AMF and VAAPI on an AMD RX 7600, Mesa 26.2.4) showed where the
plan's list, the encoders and the M2 builder do not fit. The evidence is in
`testdata/README.md` "Advanced encoder options (C-6, complete option sets)" and in
`tests/definitions/test_tools.py`, `test_options_values.py`,
`tests/validation/test_options_ffmpeg.py`, `test_dryrun*.py`, `test_options_facade.py`.

## Decision

### 1. What the option sets hold

| Encoder | Options | Notes |
|---------|---------|-------|
| x264 | 52 | Every option of 03's row except `range` |
| x265 | 81 | Every option of 03's row, plus the x264 equivalents and the colour tags |
| SVT-AV1 | 38 | 03's row plus AQ, variance boost details, loop filters, colour, HDR10, parallelism, tiles |
| VP9 (libvpx) | 17 | New `options/vp9.toml` |
| NVENC | 24 / 26 / 24 (H.264 / H.265 / AV1) | From `ffmpeg -h` only: **not verified** on hardware |
| QSV | 17 / 19 / 12 | From `ffmpeg -h` only: **not verified** on hardware |
| AMF | 28 / 24 / 25 | Every option encoded on the RX 7600 |
| VAAPI | 8 / 8 / 7 | Every option encoded on the RX 7600 (radeonsi) |

Left out, with the reason:

- x264 `range`: FFmpeg's libx264 wrapper writes the input's range over it (`range=pc` on a
  `tv` input stays `tv`, and the reverse; ffprobe of the raw stream). The output range follows
  the source (or the colour filter); the help says so.
- QSV levels (03: "profile/level"): FFmpeg passes the generic `-level` number to libvpl, whose
  H.265 / AV1 numbering cannot be checked without Intel hardware. Not offered, as before.
- Options the RX 7600 driver refuses: h264_amf `bf_delta_qp` / `bf_ref_delta_qp`
  ("AMF_INVALID_ARG … BPicturesDeltaQP"), hevc_amf `me_half_pel` off (the encoder does not
  open), av1_amf `align` (no mode avoids the padding of 0010's follow-up; 64x16 fails for
  640x360), VAAPI `low_power` ("Function not implemented"), `b_depth` above 1 ("B-frame as L1
  reference not supported"), `blbrc` ("Driver does not support BLBRC").
- SVT-AV1 `matrix-coefficients=identity` (only for 4:4:4), VP9 `aq-mode=equator360` (360°
  video), the VP9 colour tags (FFmpeg's colour tagging applies to every encoder).

The categories are those of the panel (`OPTION_CATEGORIES`: Basic, Rate control, Frame types
/ GOP, Motion / analysis, Psycho-visual, Loop filters, HDR / colour, Performance); the linter
refuses another. A tier (H.265 NVENC, VAAPI H.265 / AV1) is in **Basic**, next to profile and
level.

### 2. Defaults

A per-preset table is what the library writes into its settings SEI for each preset (x264,
x265), with the tunes that change the value; x265 `lookahead-slices` is read from a 1280x720
encode (x265 turns it off below 720 lines). SVT-AV1 defaults that its `SVT [config]` log shows
are fixed values; everything an encoder does not print (libvpx, NVENC, QSV, AMF, VAAPI, most
SVT-AV1 filters) is **"encoder decides"** with a note, never a guessed number.

### 3. Options the builder leaves out, and option rules

Validation and the builder resolve an option's `requires` with one function
(`reframe.definitions.option_context`, decision 0026). Three new codes, each recorded with the
encoder:

- `encoder.option_inactive` (**warning**): the job sets an option whose condition does not
  hold, so the builder does not write it; the encoders ignore such values too (x265 `amp`
  without `rect` writes `amp=0`, `rd-refine` below RD 5, `limit-tu` at TU inter depth 1,
  `dynamic-rd` without VBV, `hrd` / x264 `nal-hrd` without VBV, SVT-AV1 variance-boost
  settings without variance boost …). Fixes: remove the option, or set the other option.
- `encoder.option_ignored` (**warning**): the encoder changes a value the job sets: x264 with
  `bluray-compat` (B-frames 3, weighted P 1, strict B-pyramid, without a message), x265
  `max-tu-size` / `qg-size` above the CTU, `limit-refs` 2–3 with `pmode`, SVT-AV1 forward
  keyframes with hierarchical levels other than 4.
- `encoder.option_conflict` (**error**): the encoder refuses to start: x265 `min-cu-size`
  above the CTU, SVT-AV1 `min-qp` above `max-qp` or `qm-min` above `qm-max`, libvpx `qmin`
  above `qmax` or a CQ value outside them.

They are registered as job rules in `validation/levels.py` (with the x265 level rule). A
template rule needs a positive case in `tests/validation/test_template.py`, which another task
owns: presets get these checks once the lead adds it.

### 4. Custom parameters of encoders without a params argument

The M2 builder appended custom parameters only to `-x264-params` / `-x265-params` /
`-svtav1-params`; for NVENC, QSV, AMF, VAAPI and VP9 they were dropped without a word. Now each
`key=value` entry becomes the encoder's own option, last (`-rc-lookahead:v:0 20`; a bare key is
`1`, `\:` keeps a colon). An unknown name makes FFmpeg stop ("Unrecognized option"), which the
dry run reports. No built-in preset has custom parameters on such an encoder, so no plan
changes.

### 5. The dry run

`reframe.validation.dryrun.dry_run` builds C-7's plan of the job with only its video (no
audio, subtitles, chapters, tags or 2-pass, fast start off), replaces the output with
`-frames:v 1 -f null -` and runs it through `reframe.tools.run` with a 30 s timeout. It reads
FFmpeg's log, not only the exit code:

- x264 (`Error parsing option 'bogus = 1'.`), x265 (`Unknown option: bogus.`, `Invalid value
  for me: foo.`) and SVT-AV1 (`Error parsing option bogus: 1.`) only log a refused parameter
  and encode on with exit code 0. **Such a line is an error** (`encoder.custom_param_rejected`
  on `video.custom_params`, or `encoder.option_rejected` on `video.advanced.<key>`), because
  the job would silently run without the parameter the user typed. FFmpeg's own refusals
  (`Unrecognized option`, `Error setting option`) are the same.
- A failed start (exit code ≠ 0, or "Could not open encoder" / "Nothing was written" with exit
  code 0, as av1_amf does) is an error with the encoder library's own message (`x265
  [error]: …`, `Svt[error]: …`, libvpx's "Additional information"), attributed to a parameter
  when the message names it ("min CU size" names `min-cu-size`), else
  `encoder.dry_run_failed`.
- An encoder warning that names one of the job's parameters (`limit-tu disabled, requires
  tu-inter-depth > 1`) is a **warning** (`encoder.dry_run_warning`); warnings about other
  things (x265's "Source height < 720p") are not issues.
- No FFmpeg or a timeout: `encoder.dry_run_skipped` (warning). A cancelled run: no issues.

Every refused parameter has a fix that removes it (the other entries keep the text as typed).

### 6. Copy HDR metadata

`hdr_options` fills x265 `master-display` (chromaticities in 0.00002, luminance in 0.0001
cd/m²) and `max-cll`, and SVT-AV1 `mastering-display` (plain numbers) and `content-light`, with
the same formatters the builder uses for an HDR output. On the `hdr10` fixture the values are
exactly those it was made with, and an x265 and an SVT-AV1 encode with them carry the same
metadata (AV1 rounds to 1/65536, 1/256 and 1/16384). NVENC, QSV, AMF and VAAPI H.265 take the
metadata from the frames, x264 and VP9 cannot carry it: no options, an empty patch.

## Consequences

- F-9 shows 8–81 options per encoder in the panel's categories; NVENC and QSV options must be
  checked when hardware is available (the GPU tests run them when the encoder works).
- A job with an inactive option validates with a warning instead of silently losing it.
- Open product questions (defaults chosen, easy to change): an inactive option is a warning,
  not an error; a parameter that x264 / x265 / SVT-AV1 only log is an error in the dry run;
  the dry run's timeout is 30 s; the dry run tests the video only.
- `reframe plan` (C-15) asks for the dry run when a job has custom parameters.

## Plan changes

- [03-features.md §Advanced encoder options](../plan/03-features.md#advanced-encoder-options):
  custom parameters of encoders without a params argument, what the dry run reports, which
  encoders Copy HDR metadata fills, inactive / ignored / refused options; the coverage table
  without x264 `range`, QSV without levels, and a VP9 row.

## Follow-up, 2026-10-15

- The three option-rule codes need only the video settings, so they are now a template rule as
  well (`validation/levels.py`): a preset with `amp` but no `rect`, or SVT-AV1 `min-qp` above
  `max-qp`, is reported when it is saved or checked, with fixes on the template
  (`tests/validation/test_template.py` has a positive and a negative case for each code).
- `test_hardware_choices_rate_control_and_options_encode` asserts what each FFmpeg version
  does with a choice it lacks (`_ADDED_IN`: `high_quality` of `h264_amf` / `hevc_amf` must fail
  on n8.1.3 and work on n9.0.2), as the help-output test already did. The definitions do not
  change: `supported_presets` hides the preset where the build lacks it.
- The x265 in every build here is 4.3 (Arch) or 4.3+49 (both BtbN builds), not 4.1 as the M2
  notes said; the comments and `testdata/README.md` say so.

## Follow-up (core-complete review, 2026-10-16)

**R5-2.** The warnings of §5 (`encoder.dry_run_warning`, `encoder.dry_run_skipped`) did not
reach the user: `JobService.plan(…, dry_run=True)` returns only the plan when the dry run has
no error (a plan carries no issues), and `reframe plan` used it. The dry run itself is
unchanged; `reframe plan` now calls `JobService.dry_run` and shows all of its issues with the
draft's, and says the parameters were checked only when the test encode ran (decision 0038,
follow-up). `JobService.plan`'s docstring says that its plan carries no warnings.
Tests: `tests/jobs/test_cli_review_fixes.py` (`test_plan_shows_a_skipped_dry_run`,
`test_plan_shows_the_dry_runs_warnings`).
