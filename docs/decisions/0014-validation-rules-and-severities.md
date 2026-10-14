# 0014 — Validation: odd sizes, forced-only subtitles, the rules beyond the plan's list, and provisional severities

- Status: accepted (the severities in section 4 are provisional: open questions for the user); the severities of `dimensions.crop_not_detected` and of the audio range rules are superseded by [0024](0024-m2-wave-2-product-decisions.md)
- Date: 2026-10-13
- Steps: C-8 (affects C-11, C-15, F-x issue display)

## Context

05 §C-8 lists the rules; 03 §Validation says what an issue is and that `error` blocks *Add to
queue*. Building them showed four things the plan does not settle.

1. **Odd sizes for 4:2:0.** C-5 rounds every output size to a multiple of the modulus *and* of
   the chroma step, and puts the cropped size on the chroma grid
   ([0009](0009-dimension-maths-conventions.md) items 3 and 5). An odd 4:2:0 size cannot come
   out of `compute_geometry`, so a rule for it could never fire and could not have a positive
   test.
2. **Forced-only subtitles.** 03 §Subtitles: "**Forced only** uses the PGS decoder option
   `forced_subs_only`". Checked with FFmpeg n9.0.2 (Arch and the pinned build) and n8.1.3
   (testdata/README.md "Validation (C-8)", `tests/validation/test_ffmpeg.py`):

   ```console
   $ ffmpeg -h decoder=pgssub | grep forced     # also decoder=dvdsub; not dvbsub, subrip, ass
     -forced_subs_only  <boolean>    .D...S..... Only show forced subtitles (default false)
   $ ffmpeg -forced_subs_only 1 -i vobsub.mkv -map 0:s:0 -c copy copy.mkv      # 2 events → 2
   $ ffmpeg -forced_subs_only 1 -i vobsub.mkv -map 0:s:0 -c:s dvdsub dec.mkv
   Output file is empty, nothing was encoded                                   # no forced events
   $ ffmpeg -forced_subs_only 1 -i text-subs.mkv -map 0:s:0 -c:s ass t.mkv
   … a private option of some decoder which was not actually used for any stream   # 2 → 2
   ```

   So the option works for VobSub too, and only when the track is decoded (a burn-in). A
   copied track keeps every event.
3. **Rules the list does not name.** A job can be wrong in ways the list does not mention, and
   C-7 refuses a job with errors (`PlanError`): an audio or subtitle source stream that does
   not exist, an audio bitrate, mixdown or sample rate the encoder cannot do, a filter preset
   or tune the implementation does not have, a speed preset / tune / profile / level the
   encoder does not have, rate control outside the encoder's range, a subtitle conversion
   FFmpeg cannot do (bitmap → text), a missing external subtitle file, an invalid language, a
   passthru the container cannot hold (03 "auto passthru"), an empty or missing output path,
   a wrong extension, a missing drive.
4. **Severities.** The plan gives a severity for upscaling and HDR → SDR (warning) and, through
   [0008](0008-encoder-detection-reasons-and-filters.md), for the encoder codes. For the rest
   it gives none.

## Decision

1. **No odd-size rule.** `tests/validation/test_engine.py::test_no_odd_sizes` (hypothesis, 300
   cases: sizes, pixel aspects, interlacing, modulus 2 to 16, fit boxes, crops) proves that a
   4:2:0 output is never odd and that an applied crop is on the chroma grid. C-5's notes give
   the dimension issues instead: crop invalid (not applied on an axis), crop snapped, crop
   detection not run, manual crop without values, upscaled, output outside the fit box, and a
   custom pixel aspect without a value.
2. **Forced only** is valid only for a **burned-in** track whose codec is
   `hdmv_pgs_subtitle` or `dvd_subtitle` (external `.sup` counts as PGS). Anything else is
   `subtitle.forced_only_unsupported` (error; fix: keep all events).
3. **The extra rules are added** (codes in the rule table of the C-8 report and in each
   rule's registration). Every code has a positive and a negative test, and every fix is
   applied and re-validated (`tests/validation/test_rules.py`, `test_template.py`).
4. **Provisional severities**, chosen as the conservative option and kept in one place each
   (the rule that makes the issue):

   | Code | Severity | Why |
   |------|----------|-----|
   | `dimensions.crop_not_detected` | ~~warning~~ **info** ([0024](0024-m2-wave-2-product-decisions.md) item 3, until crop detection exists in M8) | the encode works, but black bars stay; M2 has no crop detection (C-10), so every CLI job with *Automatic* crop gets it |
   | `dimensions.crop_missing` | warning | a manual crop without values: no crop is applied |
   | `dimensions.crop_snapped` | info | C-5 applies the snapped crop; nothing is wrong |
   | `dimensions.crop_invalid`, `dimensions.custom_par_missing` | error | an invalid value (03: the pipeline header turns red) |
   | `dimensions.outside_box` | warning | like upscaling |
   | `container.flag_unsupported`, `tool.mkvpropedit_missing` (a flag) | warning | 03 §Track metadata: "a warning explains which flags will be lost" |
   | `tool.mkvpropedit_missing` (edit in place) | error | the job cannot run |
   | `audio.bitrate_out_of_range`, `audio.mixdown_unsupported`, `audio.samplerate_unsupported` | ~~error~~ **info**, with a snap fix ([0024](0024-m2-wave-2-product-decisions.md) item 4: C-7 snaps) | the plan does not say whether C-7 snaps silently |
   | `audio.passthru_fallback` | info | 03: passthru *falls back* to the encoder |
   | `encoder.fast_decode_unsupported`, `metadata.language_invalid` | warning | the value would be ignored / written as `und` |
   | `subtitle.forced_only_unsupported`, `subtitle.convert_target_missing` | error | the output would differ from what was asked |
   | `range.outside` (starts after the end, empty, no chapters) | error | |
   | `range.end_beyond` | warning | the encode stops at the end of the source anyway |
   | `output.exists` (collision `ask`) | error | `CollisionPolicy`: "the CLI and the queue treat it as an error with fixes" |
   | `output.renamed` (`auto_rename`) / `output.overwrite` | info / warning | |
   | `output.extension_mismatch` | warning | |
   | `output.disk_space` | warning | it is an estimate |
   | `validation.rule_failed` | error | a rule that raises (a bug) must not let the job through unchecked |

5. **Smaller choices**, each easy to change:
   - The disk-space estimate also covers video passthrough (the source video bitrate, or the
     file size for the range) besides average bitrate; constant quality has no estimate.
   - `AudioOutputTrack.encoder` `None` is validated as `aac` (the default fallback encoder of
     `PassthruPolicy`); the job does not know its preset's fallback.
   - The closest-match fix switches the whole video setting, not just the encoder: quality
     converted (C-6 `convert_quality`, "approximate" in the label), bitrate clamped, 2-pass
     and 10-bit turned off and preset / tune / profile / level reset where the new encoder has
     none, unknown advanced options dropped. So the fix leaves no new error behind.
   - Collisions: the free name is `Name (1).mkv`, `Name (2).mkv`, … (`next_free_path`, for
     C-11's auto-rename too). The `ask` error has a second fix on Settings ("Always
     overwrite").
   - Issue paths use the job's own field names: `audio[2].encoder` (03 §Validation showed
     `audio.tracks[2].encoder`; the model has no `tracks`).

## Consequences

- C-7 can trust a job without errors: every value it reads has been checked against the
  definitions and the build.
- The provisional severities may change after the user's answer; each is one argument in one
  rule. Changing `error` ↔ `warning` changes what blocks *Add to queue* and C-11's start check.
- A tool fix (target `settings`) removes its issue only after tool discovery runs again; the
  tests simulate that rediscovery.
- With the shipped definitions FFmpeg writes every flag that each container stores
  (`mkvpropedit_flags` is empty), so the flag half of "mkvpropedit is needed" only fires with
  other definitions; the edit-in-place half fires today.

## Follow-up (M2 wave 2b, 2026-10-14)

Decision [0024](0024-m2-wave-2-product-decisions.md) items 3 and 4 are built, and two checks
were added: an HDR source encoded to 8-bit, and a test that everything C-7's `build_plan`
refuses is a validation error. 83 issue codes now (75 before).

1. **Info notes that say what will change.** `dimensions.crop_not_detected` ("Crop detection
   is not available yet: automatic crop leaves the picture uncropped.") and every audio value
   the encoder cannot do are info. Validation computes the written values with C-6's shared
   helpers (`snap_mixdown`, `snap_samplerate`, `AudioBitrateDef.snap` down, and
   `channels_mixdown` for the bitrate table of a kept layout), the same as C-7 and C-12, and
   the text names them ("AC-3 cannot make 7.1: audio track 1 is written as 5.1.", "AC-3 has
   no 700 kb/s for 5.1 (224 to 640 kb/s, fixed steps): audio track 1 is written at
   640 kb/s."). The fixes set the written value, so applying one removes the note. Two new
   info codes: `audio.mixdown_upmix` (a mixdown with more channels than the source, or Dolby
   Pro Logic II of a source that is not surround: the source layout stays, 0019 item 3) and
   `audio.quality_unsupported` (a VBR quality on an encoder without VBR: the builder writes
   the default bitrate). A mixdown fix is never Dolby Pro Logic II and never an upmix. A
   "same as source" sample rate that the encoder does not list is resampled without a note
   (HandBrake does the same; Opus has no 44.1 kHz, so a note would be on most Opus jobs).
   A bitrate or VBR quality on a lossless encoder (FLAC) is not written by the builder: the
   same two codes say so, and the fix removes the value (found by the audio agreement test
   of codec rules, builder and validation, `tests/validation/test_audio_agreement.py`).
2. **HDR to 8-bit** (`filter.hdr_8bit`, warning, path `video.bit_depth`): an HDR source
   (HDR10, HDR10+, HLG, Dolby Vision), no tone mapping and no Colorspace filter, 8-bit
   output. Checked with FFmpeg (testdata/README.md "Validation (C-8)"): the plan only changes
   the pixel format, and the output stays tagged BT.2020 PQ with the HDR10 metadata, so it is
   8-bit HDR, which bands, not a washed-out SDR picture. Fixes: tone mapping (when an
   implementation can run), 10-bit (when the encoder can do it; a profile without 10-bit is
   reset). It does not overlap with `filter.hdr_without_tonemap`, which needs a Colorspace
   conversion to an SDR transfer (the output is tagged SDR and looks washed out); the
   BT.2020 Colorspace preset (`bt2020-10`, an SDR transfer) now counts as such a conversion.
3. **What `build_plan` refuses is an error.** `tests/validation/test_command_agreement.py`
   builds a job for every `raise PlanError` in `reframe.command` (it reads them from the
   source, so a new one without a case fails). Five were not validated and are new errors:
   `source.no_video`, `container.unknown`, `range.no_frame_rate` (a frame range on a source
   without a frame rate), `subtitle.external_unknown` (an external file that is not `.srt`,
   `.ass`, `.ssa`, `.vtt` or `.sup`) and `encoder.fast_decode_tune_conflict` (x265: fast
   decode is a tune, and x265 takes one tune). Two `PlanError`s cannot come from a job (the
   pass number of a 2-pass run; a composite x26x parameter whose other part has no default:
   every shipped part has one, tested). One case disagreed: a chapter range that ends after
   the last chapter is `range.end_beyond` (warning: "the encode stops at the last chapter"),
   but `build_plan` refused it. Decision [0026](0026-builder-and-validation-agree.md): C-7
   clamps the end, as it does for time and frame ranges; a test checks the clamped plan and
   the warning.
4. **C-7's snapshot jobs validate without errors.** `encoder.option_unknown` stays an error
   (an option the user typed is never dropped silently); C-7's snapshot job with an unknown
   x264 option no longer has it (0026).

## Follow-up (M2 review, 2026-10-14)

The milestone review found these; each has a regression test
(`tests/validation/test_review_fixes.py`, new rule cases in `test_rules.py`, new refusals in
`test_command_agreement.py`). 88 issue codes now.

1. **A file the job writes is the source** (finding B2, decision
   [0027](0027-one-process-owns-the-queue-store.md) item 5): `output.same_as_source` (error)
   now checks every file of the plan, named by the command builder's own functions
   (`partial_path`, `pass_log_files`): the output, `<name>.part.<ext>`, the FFMETADATA
   chapters file and the x264 / x265 statistics files. Each is compared with
   `fs.same_file` (through links) and by its normalised name. The fix ("Save as Name (1).mkv")
   picks a name whose files do not clash either. **Deviation:** the name compare ignores
   case only for Windows paths. On a case-sensitive file system `movie.mkv` next to
   `Movie.mkv` is another file (an existing test says so); a case-insensitive POSIX file
   system (APFS) is found by `fs.same_file`, because a clashing name is the source and
   exists. `validation.output.source_clash` / `written_paths` can serve the queue's own
   check before the first step.
2. **Two refusals of the builder were not errors**: video passthrough of a source whose
   codec ffprobe could not name (`container.codec_unsupported`, every container; a template
   has no source and is not checked), and a chapter range made only of zero-length chapters
   (`range.outside`).
3. **No fix adds an error** (the generic fix check now asserts it): "Switch to …" changes the
   output's extension with the container and is only offered for containers that hold every
   track of the job; "Encode the video" also switches to an encoder the container holds;
   the closest-match encoder fix turns 10-bit off when detection found that the new
   encoder's 10-bit test failed; "Burn it in" is not offered when another track is burned
   in.
4. **Silent losses are issues**:
   - `metadata.language_tag_lost` (warning): an MKV track whose language is a BCP 47 tag
     that ISO 639-2 cannot say (`pt-BR`, `zh-Hant`), with mkvpropedit not found: only the
     ISO 639-2 code is written. Fix: write that code on purpose.
   - `audio.passthru_settings_ignored` (warning): gain, DRC or loudness normalisation on a
     passthru track that is copied. Fixes: encode the track (its encoder, else AAC), or
     drop the settings.
   - `encoder.level_too_low` (error): an x265 level whose limits the output picture or
     frame rate exceeds; x265 refuses to start. The limits are H.265 table A.8 on the
     picture padded to x265's minimum coding unit (16 for `ultrafast`, 8 otherwise),
     checked with the real x265 (testdata/README.md). Fixes: the smallest level that fits,
     or let x265 choose. The frame rate is the chosen one, else the source's average.
     Only x265 is checked (the finding; x264 and the hardware encoders are not).
5. **Smaller points**:
   - A manual output path is checked against C-16's file-name rules
     (`reframe.naming.sanitize`): a path part longer than 255 bytes (the file name counted
     with the `.part` the queue adds) is `output.name_too_long` (error, every OS); a
     reserved Windows name (`CON.mkv`) or a character Windows does not allow is
     `output.name_not_portable`, an error for a Windows path and a warning elsewhere (the
     file may move). Fix: C-16's safe name.
   - The JSON-pointer pattern of `reframe.models.issues` matches a newline too
     (`^(/[\s\S]*)?$`), so an advanced-option key or a filter id with a newline gives its
     issue instead of `validation.rule_failed` (the JSON-schema snapshot changed).
   - `naming.no_output_folder` of a job points at `output.path` (a job has no
     `naming.output_folder`; its folder setting is Settings → Output or the preset's).
   - A job that deinterlaces measures the crop on the frame's chroma grid, as the builder
     does (C-5 gets `interlaced=False`): a 2-line crop of an interlaced 4:2:0 source is no
     longer reported as snapped.

## Follow-up (M2 review, second round, 2026-10-14)

From the other agents' review fixes (C-4, C-6, C-7). 90 issue codes now.

1. **x265 `rc-lookahead` must be above `bframes`** (`encoder.lookahead_too_short`, error; 0
   with 0 B-frames is allowed). The values the encoder uses come from the job's advanced
   options, else C-6's per-preset tables; the `animation` tune adds 2 B-frames and
   `zerolatency` sets both to 0, and options the job sets win over the tune (checked with
   x265: `tests/validation/test_x26x_ffmpeg.py`). Fixes: a lookahead one above the
   B-frames, or fewer B-frames.
2. **x264 `subme` 10 or 11 needs `trellis` 2** (`encoder.subme_needs_trellis`, warning): x264
   uses `subme` 9 otherwise, without a message (its settings SEI says `subme=9`), also for
   the `veryslow` / `placebo` presets with trellis 0 or 1. Fixes: trellis 2, or subme 9.
   `aq-mode` 0 does not lower it (checked).
3. **A cached "no 10-bit" that detection checks again** (`from_cache` and `detecting`) is
   not final: `encoder.checking` (info) at `video.bit_depth` instead of `encoder.no_10bit`,
   as C-4 does for the encoder status; fixes do not act on it either.
4. **C-7's written layout** (`PlannedAudio.layout`): validation now takes every written audio
   value from `reframe.command.planned_audio`, so the bitrate table follows the written
   channels. A layout libopus refuses that C-7 makes into another (`2.1` → stereo, `6.0` →
   5.0) is `audio.mixdown_unsupported` (info): "Opus cannot keep 2.1: audio track 1 is
   written as stereo.", with a fix only where a mixdown writes that layout (stereo, 5.1). A
   kept layout the encoder cannot make reads "cannot keep" (was "cannot make").
   **Open (C-12):** a codec rule caps the bitrate with the table of the source's channel
   count, C-7 with the written layout's (Opus "keep" on `2.1`: C-12 36 kb/s, C-7 13 kb/s;
   on `7.1(wide)`: 48 vs 37). The agreement test marks the three Opus cases (strict xfail).

## Plan changes

- `docs/plan/05-core.md` §C-8: the odd-size item, forced-only (PGS or VobSub, burned in), the
  disk-space estimate for passthrough.
- `docs/plan/03-features.md` §Subtitles → Output tracks (forced only); §Validation and error
  display (the path example).
- Follow-up (M2 wave 2b): `docs/plan/05-core.md` §C-8: the HDR-to-8-bit warning, the audio
  notes, and "what the command builder refuses is an error".
- Follow-up (M2 review): `docs/plan/05-core.md` §C-8: the Output bullet (every file the job
  writes, the file-name rules) and the silent losses.
