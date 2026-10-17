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

The evidence is in `testdata/README.md` "Advanced encoder options (C-6, complete option sets)",
section "Core-complete review".

- **R5-1 (blocker): custom parameters that read or write files.** The custom parameters
  reached the encoder unchanged, including keys that make the encoder or FFmpeg write a file:
  `reframe plan` dry-runs a user preset's parameters, so importing a shared preset with
  `analysis-save=FILE` and only planning with it overwrote FILE (5984 bytes of x265 analysis
  data, exit 0). Changed:
  1. A validation rule (job and template; `validation/levels.py`,
     `video_custom_param_issues`): `encoder.custom_param_file` (error) for a key that names a
     file, `encoder.custom_param_unknown` (error) for an own option outside the allow-list,
     each with a fix that removes the entry. The data is
     `reframe/definitions/data/custom_params.toml` (`reframe.definitions.custom_params`).
     - **x264, x265, SVT-AV1** (a params argument): a **deny-list** of the keys that name a
       file, each checked with the encoder (written: x265 `csv`, `analysis-save`,
       `analysis-reuse-file`, `stats`; x264 `dump-yuv`, `stats`; read: x265 `analysis-load`,
       `scaling-list` (except `default` / `off`), `lambda-file`, `dhdr10-info`, `nalu-file`,
       `film-grain`, `aom-film-grain`, `fovea-gaze-file`; x264 `cqmfile`, `opencl-clbin`), plus
       `pass` (x264 / x265 write `x26?_2pass.log` into the working folder; Reframe runs 2-pass
       itself), plus the file options of the encoders' own programs that the libraries refuse
       today (`qpfile`, `zonefile`, `recon`, SVT-AV1's `stat-file`, `fgs-table`, …), in case a
       later library takes them. A deny-list is enough here because the library reads only its
       own keys, and each key was looked up in the library's help and strings. Keys are
       compared as the libraries read them (`_` as `-`, a leading `--`, a `no` / `no-` prefix:
       x265 reads `no-csv=F` as `csv=true` and writes a file named `true`) and as FFmpeg splits
       the text (`av_dict_parse_string`: quotes and `\` escapes).
     - **VP9, NVENC, QSV, AMF, VAAPI** (each entry written as `-<name>:v:0`): an
       **allow-list**, because FFmpeg reads such a name as any of its own options first, and
       many of those read or write files (`vstats_file`, `progress`, `passlogfile`,
       `stats_enc_post`, `print_graphs_file`, `report`, `/filter` reads the value from a file),
       or change the command in other ways (`c`, `map`, `filter`). A deny-list of FFmpeg's
       options would have to follow every FFmpeg release. Allowed: the encoder's private
       options (this build's list from encoder detection, `EncoderStatus.private_options`; else
       the list recorded from the three builds) and the 70 generic encoder options
       (AVCodecContext, flags `E..V`), never FFmpeg's file options, and not QSV `qsv_params` /
       `load_plugins` (they pass text to a library that cannot be checked without Intel
       hardware). A test checks the recorded lists against the build (`ffmpeg -h full`,
       `-h encoder=<id>`).
  2. The dry run runs validation's check first and **never starts FFmpeg** with a refused
     parameter (the errors are its result), and runs FFmpeg in a new temporary working folder
     (new keyword `work_dir`), removed afterwards; a relative source path is made absolute.
  3. Every refusal has a fix that removes the entry (all custom parameters when only FFmpeg's
     quote handling finds the key).
  Tests: `tests/validation/test_custom_params_rules.py`, `test_custom_params_ffmpeg.py`,
  `test_dryrun_review_fixes.py` (`test_r5_1_*`: the reviewer's reproduction through
  `Reframe.jobs.plan(…, dry_run=True)` leaves the file unchanged), `cases_options.py`,
  `tests/definitions/test_custom_params.py`. Not changed: the command builder still writes
  what it is given (validation runs before every plan, every queue run and every preview
  clip); a guard there would change the builder tests of another task (a suggestion for the
  lead).
- **R5-3: libvpx codec controls.** libvpx refuses some values through a codec control: FFmpeg
  logs "Failed to set VP8E_SET_ARNR_MAXFRAMES codec control: Invalid parameter" (and libvpx's
  "Additional information: arnr_max_frames out of range [0..15]"), exits with 0 and encodes
  without the value; the dry run passed. Now such a line is an error: attributed to the
  parameter when the control maps to one (`ARNR_MAXFRAMES` → `arnr-maxframes`; FFmpeg's
  other names, such as `CPUUSED` → `cpu-used`, are listed), else `encoder.dry_run_failed` on
  `video.custom_params`. Tests: `test_r5_3_*` (recorded log and the real libvpx).
- **R5-7: VBV without both values.** x264 and x265 drop `vbv-maxrate` without `vbv-bufsize`
  (x264 silently), and `vbv-bufsize` without `vbv-maxrate` at a constant quality. Now
  `encoder.option_inactive` (warning) for each, with a fix that removes it. A buffer alone
  with an average bitrate is used (the encoders make it constant bitrate, with a log line)
  and is not reported. Tests: `test_option_rules_review_fixes.py::test_r5_7_*`,
  `test_option_formats_ffmpeg.py::test_r5_7_vbv_with_the_encoders` (x264's SEI, x265's log).
- **R5-8: the HDR texts.** `master-display`, `max-cll` (x265) and `mastering-display`,
  `content-light` (SVT-AV1) took any text; x265 with `master-display=garbage` writes no
  mastering display (exit 0), and SVT-AV1 with text after the tags never ends. Now each has a
  format check (`encoder.option_invalid`, error, with the reset fix): x265
  `G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min)` in that order with whole numbers (chromaticities up to
  50000, luminance up to 2³²−1; spaces before a number are allowed, as x265 allows them),
  SVT-AV1 the same tags in any order with plain numbers (chromaticities 0–1, luminance up to
  the PQ maximum of 10000 cd/m²: above about 8.4 million it overflows), and `MaxCLL,MaxFALL`
  with two whole numbers up to 65535 for both. Texts that the encoders accept but change
  (a value that wraps or is clipped, trailing text x265 ignores) are refused as well. The
  values Copy HDR metadata writes pass the check (a test). Tests: `test_r5_8_*` in
  `test_option_rules_review_fixes.py` and `test_option_formats_ffmpeg.py` (the side data that
  the encoders write).
- **R5-10: references.** `validation/dryrun.py` and `tests/validation/test_dryrun.py` named a
  `test_dryrun_ffmpeg.py` that does not exist; they now name `test_options_facade.py` and
  `test_dryrun_review_fixes.py`.
- **Attribution of a log line to a whole key** (suspected in the review, real): an encoder
  warning was given to the first job parameter whose name appeared as a word, so x265's
  "--rd-refine disabled, requires RD level > 4" went to `rd` ("RD level"), because the `--` in
  front of `rd-refine` hid it. Now a key as typed (also after `--`) wins over a looser form (any
  case, words split by spaces), then the earliest in the line, then the longest. Test:
  `test_a_warning_goes_to_the_key_it_names_not_to_a_short_key_in_its_text` and the real x265
  run after it.

**R5-2.** The warnings of §5 (`encoder.dry_run_warning`, `encoder.dry_run_skipped`) did not
reach the user: `JobService.plan(…, dry_run=True)` returns only the plan when the dry run has
no error (a plan carries no issues), and `reframe plan` used it. The dry run itself is
unchanged; `reframe plan` now calls `JobService.dry_run` and shows all of its issues with the
draft's, and says the parameters were checked only when the test encode ran (decision 0038,
follow-up). `JobService.plan`'s docstring says that its plan carries no warnings.
Tests: `tests/jobs/test_cli_review_fixes.py` (`test_plan_shows_a_skipped_dry_run`,
`test_plan_shows_the_dry_runs_warnings`).

Plan change: [03-features.md §Advanced encoder options](../plan/03-features.md#advanced-encoder-options),
the custom-parameters bullet (parameters that name files are refused, the allow-list of own
options, the dry run never runs with them).

## Follow-up (final review, 2026-10-17)

A final review of the fix rounds (reviewer R-C, on `core-complete` 5dbf152) found two defects.
The evidence is in `testdata/README.md` "Advanced encoder options (C-6, complete option sets)",
section "Final review". Every test named here failed on 5dbf152.

- **RC-1 (major): x264 `cqm` with a file name.** `[file_keys.libx264]` had `cqmfile` but not
  `cqm`. x264 reads every `cqm` value as a file name unless the value contains `flat` or `jvt`.
  With the pinned n9.0.2, `-x264-params cqm=/…/nope.cfg` gives `[libx264] can't open file
  '/…/nope.cfg'` (exit 187), and x264 reads and applies a valid matrix file (the settings SEI
  says `cqm=2`, as with `cqmfile`). So a shared preset with `cqm=<path>` passed validation,
  `reframe plan` dry-ran it, and `reframe encode` read the file. The temporary working folder
  of the dry run does not help: x264 reads an absolute path from anywhere. Changed
  (`definitions/data/custom_params.toml`, `definitions/custom_params.py`):
  1. `cqm` is a file key of x264 ("reads quantisation matrices from this file unless the value
     is flat or jvt"), with the names `flat` and `jvt` in `[value_exceptions]`.
  2. A name is compared as the library compares it, with the value that the library gets
     (after FFmpeg's quotes and escapes; spaces and quotes are no longer stripped first). x264
     `cqm` takes every value that **contains** a name (the new table `[value_match]`,
     `cqm = "contains"`): `./flat` and `/x/jvt/matrix.cfg` are the presets for x264 and it
     opens no file, so Reframe accepts them too. x265 `scaling-list` takes only the **whole**
     value: `DEFAULT`, `./default` and `default ` (an escaped space) are files. Both are
     case-sensitive (`FLAT` is a file). Validation also checks the text as Reframe splits it
     (the quotes stay), so a quoted name such as `scaling-list='default'` is refused, although
     x265 gets `default`: a refusal on the safe side, for a spelling nobody needs.
  3. Through a `no` prefix the library gets `true` or `false`: x264 `nocqm=flat` and x265
     `no-scaling-list=default` open a file named `true` in the working folder. So a name never
     applies to a key read through the prefix. This also closes the same gap of R5-1 for
     `scaling-list`.

  Validation refuses `cqm=<file>` (`encoder.custom_param_file`, with the fix that removes the
  entry). The dry run runs the validation check first and does not start FFmpeg, so `reframe
  plan` and `reframe encode` refuse it too. `cqm=flat` and `cqm=jvt` stay valid and are
  dry-run.

  **The extra search for "a name or a file name" keys.** Every token in the strings of
  `libavcodec.so.63` (68604) went to x264, x265 and SVT-AV1 as a key: with an absolute path, a
  relative name, and relative names with 12 file extensions. Each key that the library did not
  refuse then ran alone (and with `pass=1`) with an `LD_PRELOAD` logger of `open` / `fopen`.
  Keys that open the file they get: x264 `cqm`, `cqmfile`, `dump-yuv`, `stats`; x265
  `analysis-load`, `analysis-save`, `aom-film-grain`, `csv`, `film-grain`, `lambda-file`,
  `nalu-file`, `scaling-list`, `stats`; SVT-AV1 none (no key takes a path or a file name).
  All of them are on the deny list. Only `cqm` and `scaling-list` take a name or a file name.

  Tests: `tests/validation/test_custom_params_rules.py` (`cqm=<path>`, `cqm=FLAT`,
  `nocqm=flat`, `scaling-list=default\ `, `no-scaling-list=default` are refused; `cqm=flat`,
  `cqm=jvt`, `cqm='jvt '` pass); `test_custom_params_ffmpeg.py`
  (`test_rc_1_x264_reads_and_applies_the_file_a_cqm_value_names`;
  `test_rc_1_a_value_that_is_a_name_or_a_file_name`: validation refuses exactly the values
  that x264 / x265 open; `cqm` in the keys that libx264 takes);
  `test_custom_params_final_review.py` (the dry run does not start FFmpeg; the reviewer's
  reproduction through `Reframe.jobs.plan(…, dry_run=True)`, `dry_run` and `validate`);
  `tests/definitions/test_custom_params.py`.
- **RC-2 (minor): signs and spaces in the HDR texts.** The R5-8 formats refused a leading
  `+`. x265 (`sscanf` `%hu` / `%u`) and SVT-AV1 accept it and write the same values as without
  it (`G(+13250,…)` gives the same mastering display as `G(13250,…)`). Now a number can have a
  sign: `+N` and `-0` are accepted (the encoders write `N` and `0`), and every other negative
  number is refused (x265 wraps `-1` to 65535; SVT-AV1 writes `-0.265` as 0.735). The check
  with the encoders found three more texts that the formats accepted and the encoders do not:
  a no-break space (or another Unicode space) before a number, digits of other scripts (both
  from Python's `\s` and `\d`), and a vertical tab or form feed before the whole text (Python's
  `strip()`; FFmpeg removes only space, tab, CR and LF around a value, then x265 cannot parse
  the text and SVT-AV1 never ends). Now the space before a number is C's white space
  (`isspace`), the digits are ASCII, and the text is stripped as FFmpeg strips it
  (`validation/video.py`). Tests:
  `test_option_rules_review_fixes.py::test_rc_2_signs_and_spaces_as_the_encoders_read_them`,
  `test_option_formats_ffmpeg.py::test_rc_2_signs_and_spaces_with_the_encoders` (validation
  accepts a text exactly when the encoder writes the same side data as for the plain text).
- **RC-3 (minor, found during the search; a known limit, not fixed).** The first note here
  blamed the text `deblock=abc`. The cause is the picture width with the deblocking filter off:
  x265 4.3 with deblocking off (`no-deblock=1`, `deblock=false`, or a `deblock` value that
  x265 cannot read) never finishes a picture narrower than about 256 pixels (192×108 to
  224×126 checked). FFmpeg sits at 0 % CPU and ignores SIGTERM. The lead checked it in
  Reframe: the dry run gives the warning `encoder.dry_run_skipped` ("did not finish within
  30 s") after 30.0 s; a queued encode fails with "FFmpeg made no progress … (no output, no
  CPU use) and was stopped" at the stall limit (600 s by default; 20 s in the lead's
  reproduction), and the process is killed. Validation checks the custom parameters of x265
  only for file keys, so nothing refuses such a job before it runs. Not cheap to fix: a
  validation rule needs x265's exact condition. Recorded in
  [0041](0041-core-complete-review.md) (final review).

No plan change: 03 §Advanced encoder options already says that parameters that name files are
refused.
