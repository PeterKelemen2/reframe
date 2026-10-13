# 0014 — Validation: odd sizes, forced-only subtitles, the rules beyond the plan's list, and provisional severities

- Status: accepted (the severities in section 4 are provisional: open questions for the user)
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
   | `dimensions.crop_not_detected`, `dimensions.crop_missing` | warning | the encode works, but black bars stay; M2 has no crop detection (C-10), so every CLI job with *Automatic* crop gets it |
   | `dimensions.crop_snapped` | info | C-5 applies the snapped crop; nothing is wrong |
   | `dimensions.crop_invalid`, `dimensions.custom_par_missing` | error | an invalid value (03: the pipeline header turns red) |
   | `dimensions.outside_box` | warning | like upscaling |
   | `container.flag_unsupported`, `tool.mkvpropedit_missing` (a flag) | warning | 03 §Track metadata: "a warning explains which flags will be lost" |
   | `tool.mkvpropedit_missing` (edit in place) | error | the job cannot run |
   | `audio.bitrate_out_of_range`, `audio.mixdown_unsupported`, `audio.samplerate_unsupported` | error, with a snap fix | the plan does not say whether C-7 snaps silently |
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

## Plan changes

- `docs/plan/05-core.md` §C-8: the odd-size item, forced-only (PGS or VobSub, burned in), the
  disk-space estimate for passthrough.
- `docs/plan/03-features.md` §Subtitles → Output tracks (forced only); §Validation and error
  display (the path example).
