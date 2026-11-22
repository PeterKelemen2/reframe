# command: simplification findings

Commit: 85d9dcb. Scope: `packages/reframe/src/reframe/command/`, `packages/reframe/src/reframe/dimensions.py`, `packages/reframe/src/reframe/capabilities/`, with `packages/reframe/tests/command/`, `tests/dimensions/`, `tests/capabilities/`. Source lines: 2402 (command) + 493 (dimensions.py) + 1751 (capabilities) = 4646 code lines. Read in full: `command/` (all 11 files), `dimensions.py`, `capabilities/` (all 10 files), decisions 0013 and 0026, 0008 (design and review sections). Only skimmed: the tests (`test_service.py`, `test_parse.py`, `test_hwtest.py`, `test_properties.py`, `test_command_agreement.py` head, `command/conftest.py`, parts of `test_tracks.py`), decision 0009 (grep only), decisions 0019, 0021, 0023, 0025, 0035 (not read; they decide audio-rule, libplacebo and option-set behaviour that I did not touch). Outside the scope I only read the lines that duplicate something in scope (`preview/graph.py`, `validation/context.py`, `validation/tracks.py`, `analysis/subtitlefile.py`, `batch/`, server `routers/jobs.py`).

Verified: 2026-11-15, 6 confirmed, 6 adjusted, 1 rejected.

## Summary

The command builder is mostly as large as the decisions make it. The big shapes (`PlanError` plus the agreement test, the audio layout tables, the quoting, the `-ss 0` and frame-rate rules, the reason table of the capabilities) are required by 0013, 0026 and 0008 and stay. The waste is in four places. First, the same small rule is written several times: the deinterlace geometry rule exists 5 times, the bitmap subtitle codec set 5 times, the external subtitle extension table 2 times, the hardware placeholder fill 3 times. Second, the capability service has constructor parameters that no caller uses, and its parser returns data nobody reads. Third, the capability cache carries a source-hash key and a writer-task protocol that the plan does not need (two findings are `decision-change`). Fourth, the builder has a handful of dead fields and pass-through wrappers. `command/errors.py` at 0% coverage is not dead code: the coverage run shows every module's import-time lines as missed (even `command/__init__.py` shows 0%), and `PlanError` has 31 raise sites in `command/` and 8 catch sites.

## Findings

### CMD-01: The deinterlace-before-crop geometry rule is written five times
- Kind: duplication
- Where: `packages/reframe/src/reframe/command/builder.py:190-193` (`_video_plan`); `packages/reframe/src/reframe/preview/graph.py:131-140` (`job_video_graph`, cross-area: preview); `packages/reframe/src/reframe/validation/context.py:72-82` (`JobContext.source_geometry`, cross-area: validation); `packages/reframe-server/src/reframe_server/routers/jobs.py:283-291` (`geometry`, cross-area: server); `packages/reframe/src/reframe/batch/resolve.py:84-88` (`output_size`, cross-area: batch); new code in `packages/reframe/src/reframe/dimensions.py` after `source_geometry` (line 135-159).
- Now: every one of these does `source_geometry(stream)`, then `model_copy(update={"interlaced": False})` when `"deinterlace" in job.filters.root`, then `compute_geometry(...)`. The rule decides the encoded output size (the crop grid), so a sixth copy that forgets it gives a wrong preview or a wrong validation. `preview/graph.py:131-140` is also a near copy of the front half of `_video_plan` (lines 181-193): the encoder lookup, the `pix_fmts.get("10" if settings.bit_depth == 10 else "8")` lookup, and both `PlanError` texts ("unknown video encoder ... (validation reports it)", "has no N-bit mode") exist twice.
- Change: in `dimensions.py` add
  ```python
  def job_source_geometry(stream: VideoStream, job: JobSettings) -> SourceGeometry:
      """source_geometry(stream), with interlaced off when the job deinterlaces before the crop."""
      geometry = source_geometry(stream)
      if "deinterlace" in job.filters.root:
          return geometry.model_copy(update={"interlaced": False})
      return geometry

  def job_geometry(stream: VideoStream, job: JobSettings) -> Geometry:
      return compute_geometry(job_source_geometry(stream, job), job.dimensions)
  ```
  (`JobSettings` is in `reframe.models`, which `dimensions.py` already imports from.) Use `job_geometry` in `builder._video_plan`, `preview/graph.py`, `batch/resolve.output_size`. Use `job_source_geometry` in `JobContext.source_geometry`. In the server route use `source=source_geometry(stream)` (the undeinterlaced one, as now) and `geometry=job_geometry(stream, job)`. In `command/video.py` add `encoder_and_pix_fmt(job, defs) -> tuple[VideoEncoderDef, str]` holding the two lookups and the two `PlanError`s; call it from `_video_plan` and from `preview/graph.job_video_graph`. In `_video_plan` the `encoder.codec not in container.video.encode` check then comes after the pix_fmt check instead of before it; both are validation-reported, so only a job that fails both would show another message.
- Behaviour: unchanged (same maths, same messages).
- Contracts touched: public core API (two new functions in `dimensions.py`); none for HTTP (the `/jobs/geometry` answer is the same).
- Callers to update: the five places above.
- Tests: none removed. `tests/dimensions/` gets one test for `job_source_geometry` (deinterlace turns `interlaced` off). The builder, preview, validation and server tests stay as the guard.
- Decision records: 0009 (crop grid, item on interlaced sources) is kept; the rule moves, it does not change.
- Size: S; estimated lines: -5 / -0 (the value is one rule in one place, not the line count)
- Risk: low. A wrong move changes the crop grid of interlaced sources; the 73 plan snapshots and `tests/dimensions/test_properties.py` catch it.
- Depends on: none (CMD-04 and CMD-12 edit `_video_plan` too; do CMD-01 first)
- Confidence: high
- Verdict: CONFIRMED (checked: exactly these five copies, no sixth; `job_video_graph` is used only by `preview/graph.output_recipe`; `dimensions.py` already imports `reframe.models`; `preview/graph.py` already imports `reframe.command.video`. Fixed: 73 plan snapshots, not 68)
- Orchestrator: joined into X-01 (see ../cross-cutting.md); that entry decides the tier and the work package. Joined into X-01 with SRV-04 and VAL-11. This entry's shape (`job_source_geometry` and `job_geometry`) is the one to make; SRV-04 gives the server line.

### CMD-02: `CapabilityService` and `DetectionOptions` have parameters and members that nothing uses
- Kind: dead-code
- Where: `packages/reframe/src/reframe/capabilities/service.py:93-131` (`CapabilityService.__init__`), `:150` (`_watch_tools`), `:227-241` (`_options`); `capabilities/detect.py:64` (`MAX_PARALLEL_HELP`), `:82-101` (`DetectionOptions`), `:201-202`; `capabilities/hwtest.py:55-57` (`FILTER_TESTS`), `:121-132` (`TestOutcome`), `:135-152` (`filter_test_argv`), `:187`; `capabilities/cache.py:126`; `capabilities/__init__.py` exports.
- Now: facts, from `rg` over `packages/`, `testing/`, `scripts/`:
  - `CapabilityService(...)` is constructed 3 times: `reframe/service.py:965` (passes only `cache_dir`) and `tests/capabilities/test_service.py:91` and `:579`. The test harness passes `platform`, `gpu_fingerprint`, `render_nodes` only. So the parameters `definitions`, `test_timeout`, `list_timeout`, `max_parallel_tests` and `watch_tools` have 0 callers, with their 5 attributes and the 3 pass-through lines in `_options`.
  - Members with 0 production callers, **kept** (verify): `CapabilityService.closest_available` (tests `test_service.py:146, 345-364`; plan 05 §C-4 line 234 specifies `closest_available(encoder_id)` in exactly this one-argument form, and `docs/m2-breakdown.md:101` lists the method), `CapabilityService.definitions` (tests `test_service.py:578-590`), `CapabilityService.detecting` (tests `test_service.py:170, 387, 520, 586` and `reframe-server/tests/test_system.py:119`). All three are rows of the plan's "Not exposed" table (`docs/plan/06-web-app.md` lines 216, 219, 221), and `packages/reframe-server/tests/test_facade_coverage.py` fails on a row whose member no longer exists. Removing them needs the three rows edited in the same commit and 6 test edits for about 11 source lines: not worth it.
  - `DetectionOptions.max_parallel_tests` and `.max_parallel_help` are never set by anyone (the service passes the default). `DetectionOptions.filter_tests` is set by no production code; only `tests/capabilities/test_cache.py:66, 81` varies it. `FILTER_TESTS` is `{"libplacebo": "libplacebo"}`: one entry whose value equals its key.
  - `TestOutcome.duration` is set (`hwtest.py:187`) and never read; `detect._log_outcome` measures its own time.
- Change:
  - `CapabilityService.__init__(events, tools, settings, *, cache_dir, platform=None, render_nodes=None, gpu_fingerprint=None)`. Use `load_definitions()` and the module constants directly. Always subscribe to `tools.changed` in `start()`. Keep the properties `definitions` and `detecting` and the method `closest_available` (see "Now").
  - `DetectionOptions`: delete `max_parallel_tests`, `max_parallel_help`, `filter_tests`. The semaphores use `MAX_PARALLEL_TESTS` and `MAX_PARALLEL_HELP` directly. Keep `test_timeout` and `list_timeout` (`test_detect.py:165, 296, 526` set them).
  - `FILTER_TESTS = ("libplacebo",)` (a tuple); `filter_test_argv` writes `"-vf", name` and refuses a name not in the tuple. `detect.py:231` uses `FILTER_TESTS`. The cache key loses its `filter_tests` entry (`hwtest.py` is in the detector hash already, so a code change still invalidates).
  - Delete `TestOutcome.duration`.
  - In `capabilities/__init__.py` remove the exports that nothing outside the package imports (`DEFAULT_VAAPI_DEVICE`, `FILTER_TESTS`, `LIST_TIMEOUT`, `MAX_PARALLEL_TESTS`, `TEST_TIMEOUT`, `current_os`, `uses_vaapi_device`). The only external users of the facade are `CapabilityService`, `encoder_issues`, `field_pointer`, `filter_test_argv`, `hardware_test_argv`.
- Behaviour: unchanged. One-time cache miss after the change (the key loses `filter_tests`); the cache rebuilds itself.
- Contracts touched: public core API (`CapabilityService` constructor, `DetectionOptions` fields, exports of `reframe.capabilities`). None for HTTP or CLI.
- Callers to update: `tests/capabilities/test_cache.py:66, 81` (the `filter_tests` entries); `tests/capabilities/test_detect.py` if it sets `max_parallel_*` (no hit). `service.py` loses the `closest_available` import only if the method goes (it stays).
- Tests: trim the two `test_cache` lines; the rest stay as the guard.
- Decision records: 0008 (cache key, detection order, `libplacebo` run test) is kept. 0021 (libplacebo run test) is kept: the test still runs.
- Size: S; estimated lines: -39 / -6
- Risk: low
- Depends on: none (CMD-09, if taken, deletes the `cache.py:126` and `test_cache.py` parts)
- Confidence: high
- Verdict: ADJUSTED (the three members `closest_available`, `definitions`, `detecting` are kept: the plan's "Not exposed" table names them and `test_facade_coverage.py` enforces it, plan 05 C-4 specifies `closest_available(encoder_id)`, and `detecting` has 4 more test callers in `test_service.py` than listed; the constructor, `DetectionOptions`, `TestOutcome.duration`, `FILTER_TESTS` and export parts are confirmed: 0 callers of `definitions`, `test_timeout`, `list_timeout`, `max_parallel_tests`, `watch_tools`; `max_parallel_*` and `filter_tests` set by nobody; estimate recomputed)
- Orchestrator: Tier A, work package Q-6.10 (see ../plan.md).

### CMD-03: The subtitle codec and extension tables are copied between areas, and one table is an identity map
- Kind: duplication
- Where: `command/subtitles.py:33-50` (`EXTERNAL_CODECS`, `_BITMAP_CODECS`, `FORMAT_ENCODERS`, `_SAME_FORMAT`), `:104-105` (`_is_bitmap`), `:126-142` (`_output_codec`); cross-area: `validation/tracks.py:33-46` (`BITMAP_CODECS`, `FORCED_ONLY_CODECS`, `EXTERNAL_FORMATS`), `analysis/subtitlefile.py:13, 22, 66-68, 84` (`BITMAP_CODECS`, uses `EXTERNAL_CODECS`), `probe/names.py:169-170` (`BITMAP_SUBTITLE_CODECS`, used by `probe/parse.py:485`), `batch/descriptors.py:107, 119` (`_BITMAP_SUBTITLES`), `batch/explain.py:66, 326` (`FORCED_ONLY_CODECS`).
- Now: the set `{"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}` is written 5 times (command, analysis, validation, probe, batch). The set `{"hdmv_pgs_subtitle", "dvd_subtitle"}` (forced-only) is written 2 times (validation, batch). The extension table is written twice: `command.subtitles.EXTERNAL_CODECS` (ext to codec) and `validation.tracks.EXTERNAL_FORMATS` (ext to codec and kind); the validation comment says "The command builder reads these too". `FORMAT_ENCODERS` maps `srt` to `srt`, `ass` to `ass`, `webvtt` to `webvtt`, `mov_text` to `mov_text` (an identity map over the `SubtitleFormat` literal; 0 users outside `_output_codec`, and it is in `__all__`). `_SAME_FORMAT` is the same map from codec names, where only `subrip` becomes `srt`.
- Change: one owner for each table.
  - `probe/names.py` keeps `BITMAP_SUBTITLE_CODECS` and gains `FORCED_ONLY_SUBTITLE_CODECS`. The five other places import them (`command/subtitles.py` drops `_BITMAP_CODECS` and `_is_bitmap`: `codec in BITMAP_SUBTITLE_CODECS`).
  - `command/subtitles.py` owns `EXTERNAL_FORMATS: dict[str, tuple[str, SubtitleKind]]` (moved from `validation/tracks.py`). `analysis/subtitlefile.py` uses `EXTERNAL_FORMATS[suffix][0]`; `validation/tracks.py` and `validation/subtitles.py` import it. Delete `EXTERNAL_CODECS`.
  - Delete `FORMAT_ENCODERS`: `_output_codec` returns `track.convert_to` or `container.text_subtitle_target` directly (they are encoder names already). Reduce `_SAME_FORMAT` to `{"subrip": "srt"}` and write `recode_codec = _SAME_FORMAT.get(codec, codec)`.
- Behaviour: unchanged.
- Contracts touched: public core API (module-level names move; `validation.tracks.FORCED_ONLY_CODECS` is imported by `tests/validation/test_ffmpeg.py:12`).
- Callers to update: `validation/subtitles.py:20-21, 52, 53, 81, 281`, `validation/tracks.py:18-20, 34-46, 175`, `analysis/subtitlefile.py`, `batch/descriptors.py`, `batch/explain.py`, `tests/validation/test_ffmpeg.py:12`.
- Tests: none removed; one import changes. `test_snapshots.py` and the subtitle tests in `tests/command/test_tracks.py` guard the output codec.
- Decision records: 0013 (subtitle burn-in, external files) is kept.
- Size: S; estimated lines: -22 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (checked: the five copies of the bitmap set and both forced-only copies exist; `recode` is only true for non-bitmap external files, so `_SAME_FORMAT.get(codec, codec)` under `recode` is the same; `reframe.command` already imports `reframe.probe`; `validation` gains an import of `reframe.probe.names` (no import linter, no cycle). Extra: `validation.tracks.BITMAP_CODECS` has no reader at all, so it is simply deleted)
- Orchestrator: joined into X-06 (see ../cross-cutting.md); that entry decides the tier and the work package.

### CMD-04: Hardware placeholder fill exists three times, with a defensive error type for states the linter already forbids
- Kind: duplication
- Where: `command/builder.py:79-80` (`DEFAULT_VAAPI_DEVICE`), `:157-160` (`_fill`), `:194-201` (`_video_plan`); `command/video.py:105-108` (`_fill`); `capabilities/hwtest.py:38` (`DEFAULT_VAAPI_DEVICE`), `:48`, `:60-74` (`DefinitionError`, `resolve_placeholders`), `:85-118` (`hardware_test_argv`), `:213-219` (`run_hardware_test`); `definitions/models.py:390-396` (`HardwareSetup`).
- Now: `{name}` substitution is `_fill` in `builder.py`, `_fill` in `video.py` (the same 3 lines), and `resolve_placeholders` in `hwtest.py` (11 lines). `builder._video_plan` and `hwtest.hardware_test_argv` both build `init_args` and `tail` from `HardwareSetup` the same way, and both fall back to `format=<pix_fmt>` / `-pix_fmt` when the tail is empty. `DEFAULT_VAAPI_DEVICE = "/dev/dri/renderD128"` is defined in both modules (the builder comment says "the definitions' default"). `DefinitionError` has two raise sites: an unknown placeholder (the definitions linter already refuses it: `definitions/lint.py:154-156`, test `test_lint.py:296`) and a missing pixel format (the linter refuses a missing 8-bit format at `lint.py:87`; detection only runs the 10-bit test when `"10" in encoder.pix_fmts`, `detect.py:408`). `run_hardware_test` catches it and returns "The encoder definition is broken". The builder has no such check and does not need one.
- Change: in `definitions/models.py` add `DEFAULT_VAAPI_DEVICE`, `fill_placeholders(text, values)` (3 lines, plain `str.replace` loop) and
  ```python
  class HardwareSetup:
      def resolve(self, values: Mapping[str, str]) -> tuple[list[str], list[str]]:
          return ([fill_placeholders(a, values) for a in self.init_args],
                  [fill_placeholders(f, values) for f in self.filter_tail])
  ```
  `builder._video_plan` and `hwtest.hardware_test_argv` call `setup.resolve(values)`. `video.py` imports `fill_placeholders`. Delete `builder._fill`, `video._fill`, `DefinitionError`, `resolve_placeholders`, the second `DEFAULT_VAAPI_DEVICE`, the `try/except DefinitionError` in `run_hardware_test`, and the pix-format raise in `hardware_test_argv` (use `encoder.pix_fmts[bit_depth]`; a `KeyError` here is a bug the linter rules out).
- Behaviour: unchanged for every shipped definition (the linter enforces both conditions).
- Contracts touched: public core API (`hwtest.DefinitionError`, `resolve_placeholders`, `builder.DEFAULT_VAAPI_DEVICE` removed from `__all__`).
- Callers to update: `command/builder.py`, `command/video.py`, `capabilities/hwtest.py`, `capabilities/detect.py:21` (imports `DEFAULT_VAAPI_DEVICE`), `capabilities/__init__.py:20, 41`; `reframe_testing/capture_fake_data.py` does not import the removed names (checked).
- Tests: delete `tests/capabilities/test_hwtest.py:101-106` (`test_definition_errors`) and `:137-143` (`test_run_definition_error_is_data`), the `DefinitionError` import at line 14, and then the helper `broken` (lines 97-98) and the `HardwareSetup` import (line 15), which nothing else uses. Keep the rest.
- Decision records: 0008 (hardware test encode) is kept.
- Size: S; estimated lines: -22 / -16
- Risk: low. A definition with a typo placeholder would reach FFmpeg unfilled; `test_lint.py` stops it before release.
- Depends on: none (edits `_video_plan` like CMD-01 and CMD-12; `DEFAULT_VAAPI_DEVICE` also in the `capabilities/__init__.py` export edit of CMD-02)
- Confidence: high
- Verdict: CONFIRMED (checked: definitions come only from the bundled TOML, `load_definitions()` has no user override, and `test_lint.py` covers both conditions; `detect.py:408` runs the 10-bit test only when `"10" in encoder.pix_fmts`; tests bullet extended)
- Orchestrator: Tier A, work package Q-6.10 (see ../plan.md).

### CMD-05: `parse.py` returns fields that nothing reads
- Kind: dead-code
- Where: `capabilities/parse.py:22-24` (`MediaKind`, `_KINDS`), `:37-45` (`EncoderListing`), `:48-63` (`EncoderHelp`), `:66-85` (`parse_encoders`), `:102-155` (`parse_encoder_help`); `capabilities/detect.py:30-36, 271, 276, 304, 310, 313`; `capabilities/__init__.py:30-33, 51-52`.
- Now: `detect.py` uses the encoder listing only as membership (`listing.get(id) is not None`, lines 276, 304, `key in listing` at 313). `EncoderListing.kind`, `.description` and `.experimental` are read by nothing but `tests/capabilities/test_parse.py:17-29`. `EncoderHelp.name`, `.description` and `.hardware_devices` are read only by `test_parse.py` (lines 74, 81-100); `detect.read_help` uses `private_options`, `presets`, `pix_fmts`. vulture also flags `experimental` and `hardware_devices`.
- Change: `parse_encoders(text) -> frozenset[str]` (the names; same `_SEPARATOR` and `_ENCODER_LINE` logic; delete `_KINDS`, `MediaKind`, `EncoderListing`, the `desc` group may stay in the regex). `EncoderHelp` keeps `private_options`, `presets`, `pix_fmts`; `parse_encoder_help` keeps `help_name` as a local to return `None` for text that is not encoder help; drop the `description`, `devices` and `hardware devices` branch. `detect.classify` and `read_help` take `frozenset[str]` (`encoder.id in listing`).
- Behaviour: unchanged.
- Contracts touched: public core API (`EncoderListing` removed from `reframe.capabilities`).
- Callers to update: `capabilities/detect.py`, `capabilities/__init__.py`, `tests/capabilities/test_parse.py`.
- Tests: in `test_parse.py` trim `test_encoder_list_of_the_pinned_build` to the count and the legend checks; delete the `.name`, `.description`, `.hardware_devices` asserts (lines 24-25, 74, 81, 99). `test_every_definition_encoder_but_libfdk_aac_is_in_the_pinned_build` uses `known - encoders`; it keeps working with a set. The real-output parsing tests stay (they guard the verified FFmpeg format in `testdata/README.md`).
- Decision records: 0008 (parse of `-encoders`, `-filters`, `-h encoder=`) is kept.
- Size: S; estimated lines: -25 / -12
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (checked: `detect.py` uses the listing only as membership; the other readers of `parse_encoder_help`, `tests/validation/test_custom_params_ffmpeg.py:288` and `tests/definitions/test_tools.py:259`, read only `private_options` and `presets`. Add `detect.py:234` (`... else {}` becomes `frozenset()`) to the anchors)
- Orchestrator: Tier A, work package Q-6.10 (see ../plan.md).

### CMD-06: Dead fields, aliases and pass-through wrappers in `command/`
- Kind: dead-code
- Where and now (each item, with callers found by `rg` over `packages/`, `testing/`, `scripts/`):
  - `command/video.py:235-236` `encoder_option_keys`: 0 callers, also none in tests (vulture hit confirmed).
  - `command/audio.py:301-323` `AudioOut.copy`, `.encoder`, `.loudness`, `.fallback`: set in `audio_output` (lines 358, 362-364, 383) and read by nothing in `src/`. Tests read two: `tests/command/test_tracks.py:257` (`out.copy`) and `:266` (`aac.fallback`). `PlannedAudio` keeps `copy`, `encoder`, `fallback` because decision 0013 names them; only `AudioOut` loses them.
  - `command/header.py:155-183` `FixupTrack`: a second track record that `builder._fixup_step` (`builder.py:498`) builds from `OutputTrack` by `FixupTrack(t.type, t.index + 1, t.language)`. `OutputTrack` (`metadata.py:75-93`) has the same three values (`type`, `index`, `language`), and `header.py` already imports from `metadata.py`.
  - `command/filtergraph.py:116-117, 150-152` `_is_hdr` and `is_hdr`; `:141-147, 155-158` `_setparams` and `colour_params`: the public name only returns the private one (callers of the public names: `preview/graph.py:18-20, 94, 104, 172`, `tests/command/test_filtergraph.py`).
  - `command/video.py:251` `_UNKNOWN` equals `filtergraph.py:52` `_UNKNOWN_COLOUR`; `video.hdr_params:257-260` re-writes `filtergraph._known` (`:112-113`) inline.
  - `quote = quote_posix if shell == "posix" else quote_windows` is written 3 times: `quoting.py:95`, `builder.py:623`, `header.py:193`.
  - `command/jobtype.py:43` `OTHER_TAGS` is `metadata.TAG_KEYS` without `title`, in the same order.
- Change:
  - Delete `encoder_option_keys`.
  - `AudioOut` keeps `index`, `stream`, `args`, `filter`, `drc`, `global_args`, `analyse_filter`, `measurement_id`. `audio_output` builds `AudioOut(index, stream)`; the copy case returns early. Drop the two test asserts (the args assert on the next lines already shows a copy and the fallback encoder).
  - `fixup_edit(path, tracks: Sequence[OutputTrack])` uses `_TRACK_TYPES[t.type]` and `number=t.index + 1`; `builder._fixup_step` passes `tracks`. Delete `FixupTrack`.
  - Rename `_is_hdr` to `is_hdr` and `_setparams` to `colour_params`; delete the wrappers.
  - `video.py` imports `known_colour` (the renamed `_known`) from `filtergraph.py`; delete `_UNKNOWN`.
  - `quoting.py` gets `def quoter(shell: Shell) -> Callable[[str], str]`; `command_line`, `_display` and `edit_line` call it.
  - `jobtype._tags_besides_title` iterates `TAG_KEYS` and skips `"title"`; delete `OTHER_TAGS`.
- Behaviour: unchanged.
- Contracts touched: public core API (names in `command.metadata`, `command.header`, `command.audio`).
- Callers to update: the lists above; `tests/command/test_metadata_edit.py:12, 206-209` (builds `FixupTrack`; use `OutputTrack(type, index, TrackMetadata(), language, None)` with `("a", 0, "pt-BR")`, `("a", 1, "de")`, `("s", 0, None)`, `("s", 1, "yue")`: `number` is `index + 1`, so the indexes are 0-based per type), `tests/command/test_tracks.py:257, 266`.
- Tests: two asserts deleted; one test's call sites changed; the `FixupTrack` test stays in the new form.
- Decision records: 0013 (`PlannedAudio` fields, display quoting) is kept; 0034 and 0080 (header edits) are kept.
- Size: S; estimated lines: -35 / -5
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the `render_tag` item is rejected: it is not a plain pass-through. `render_tag` makes `options`, `output_size`, `now` and `definitions` required keyword arguments, while `render_value` defaults them to `None`, so a caller that forgets `output_size` or `definitions` would silently get empty `{width}`/`{resolution}` or a reloaded definitions set; and it names the "no file-system reads" case. Estimate drops from -55 to -35. The other seven items are confirmed: `encoder_option_keys` has 0 references anywhere; `AudioOut.copy/encoder/loudness/fallback` are read only by `test_tracks.py:257, 266`; `OutputTrack.type` and `StreamType` are the same literal; `OTHER_TAGS` equals `TAG_KEYS` minus `title` in the same order; `video.py` already imports from `filtergraph.py`, so no cycle)
- Orchestrator: Tier A, work package Q-6.10 (see ../plan.md).

### CMD-07: The cache write has its own task set, shield and wait protocol
- Kind: concurrency
- Where: `capabilities/service.py:128` (`_writes`), `:184-202` (`close`), `:252-253` (`_detect`), `:308-309` (the `await self._store(...)` call in `_run`), `:313-327` (`_store`, `_put`); tests `tests/capabilities/test_service.py:474-501, 503-527, 529-557`.
- Now: after a detection, `_store` starts the write as a separate task (`asyncio.to_thread`), adds it to a set, shields it, and `close()` and the next `_detect` both wait for the set, so that a cancelled detection cannot leave a half-run write, an older result cannot overwrite a newer one, and a short CLI run keeps its result. The file write itself is already atomic (`CapabilityCache.put` writes a temp file and `os.replace`s it). The write is one small JSON file (a few KB) plus a folder listing of at most 9 files.
- Change: call `self._put(key, final)` directly in `_run`, with no `await` between the call and `_finish` (a blocking write of a few milliseconds, once per detection). A task can only be cancelled at an `await`, so a started write always ends, a later detection cannot interleave with it, and `wait()` still returns after the result is in the cache (0008 review item 1). Delete `_writes`, `_store`, the `asyncio.to_thread` and `shield`, the `_writes` wait in `_detect` and in `close()`. `_put` keeps its `try/except` ("cache errors never fail a detection").
- Behaviour: unchanged for users. The event loop blocks for one small file write per detection (on Windows with a virus scanner this can be tens of milliseconds).
- Contracts touched: none
- Callers to update: `service.py` only.
- Tests: delete `test_close_finishes_a_started_cache_write` (503-527) and `test_a_new_detection_waits_for_the_last_cache_write` (529-557), which test the removed protocol; then drop `import threading` (line 7), which only they use (`running_detections`, line 50, is still used at line 614). Keep `test_closing_on_the_final_event_keeps_the_cache` (440) and `test_a_failing_cache_write_is_not_fatal` (559). `test_wait_and_rescan_return_after_the_cache_write` (474-501) passes unchanged (it patches `CapabilityCache.put` and checks the order "cached", "final event"); no trim needed. Also change the `close()` docstring sentence "A cache write that has started is finished first" and the module docstring of `service.py` if it says so.
- Decision records: 0008 ("`wait()` returns only after the new result is in the cache", close waits for replaced detections) is kept; it does not ask for a writer thread. The off-loop rule is the `CapabilityCache` docstring's own; change that sentence.
- Size: S; estimated lines: -17 / -70
- Risk: medium. A blocking write on the loop thread is a judgement call; a slow disk would stall the WebSocket for the write time. If the owner objects, keep the thread but drop `_writes` by awaiting `asyncio.shield(asyncio.to_thread(...))` inline (about -10 / -30).
- Depends on: none (superseded by CMD-09 if that is taken)
- Confidence: medium
- Verdict: CONFIRMED (checked: after `detect_capabilities` returns, `_run` has no `await` between the write and `_finish`, so a started write cannot be cancelled, and a later detection cannot interleave because `_detect` first awaits `previous`; 0008 does not ask for a writer thread; the loop-blocking risk is real but small (one file of a few KB plus a listing of at most 9 files). Anchors and the tests bullet corrected)
- Orchestrator: Tier B, work package Q-6.18 (see ../plan.md).

### CMD-08: The cache key hashes the detection source files and the definitions
- Kind: decision-change
- Where: `capabilities/cache.py:48-67` (`_DETECTOR_MODULES`, `detector_fingerprint`), `:70-82` (`definitions_fingerprint`), `:99-107`, `:128-138` (`cache_key`); tests `tests/capabilities/test_cache.py` (the `detector` and `definitions` lines, `:15, 69`).
- Now: decision 0008 §3 and plan 05 §C-4 say the key includes "a hash of the definition fields that detection reads and a hash of the detection code". `detector_fingerprint()` reads five `.py` files from the package folder and falls back to `reframe-<version>` when it cannot. Checked in verify: the local PyInstaller build `desktop/src-tauri/resources/sidecar/_internal/reframe/` (git-ignored) holds only the data folders `definitions`, `presets` and `tools`, no `.py` file, so `read_bytes()` raises `OSError` and the `reframe-<version>` fallback is the only path in the frozen Linux build (the Windows build is made the same way, not checked). Also, every start already runs the full detection again and replaces the cached statuses (0008: "Each start runs the test encodes again ... The cache only removes the 'checking...' period"), so a stale entry after a code or definitions change is shown for seconds at most. A cached `available` does stay final, but definitions and detection code change only between releases.
- Change: replace both hashes with the Reframe version: `CacheKey.detector = f"reframe-{__version__}"`. Delete `_DETECTOR_MODULES`, `detector_fingerprint`, `definitions_fingerprint`, the `functools` and `hashlib` use for them, and the `definitions` key field (keep `detector` as the version field).
- Behaviour: changes for developers only: after editing detection code or definitions in a checkout, the old cached result shows until the background check ends (seconds). Users see no change (one cache miss after each release, as now).
- Contracts touched: none (the cache is not a document, 0008).
- Callers to update: `capabilities/cache.py` (`cache_key` loses its `definitions` parameter), `capabilities/service.py:_key` (lines 329-337: drops `definitions=self._definitions`), `capabilities/__init__.py` (no export of the two fingerprint functions today; nothing to do), `tests/capabilities/test_cache.py`.
- Tests: in `test_cache.py` delete `test_definition_changes_change_the_key` (94-113), the assert at 68, the imports at 14-15, and the `definitions=DEFS` argument of the 4 `cache_key(...)` calls (lines 34, 82, 118, 120); rewrite the assert at 69 to compare `key.detector` with `f"reframe-{__version__}"`; about 28 lines. Keep the key tests for path, size, mtime, version, env, gpu, options.
- Decision records: 0008 §3 "Cache" bullet and plan `05-core.md` §C-4 "Cache" must be edited in the same commit. For the decision to change, it must be true that a stale result for a few seconds in a development checkout does not matter, and that the frozen build never read the source files (check this first with the built sidecar).
- Size: S; estimated lines: -30 / -28
- Risk: low
- Depends on: none (superseded by CMD-09 if that is taken)
- Confidence: medium
- Verdict: ADJUSTED (the condition "the frozen build never read the source files" is checked and holds, see Now; callers list was missing `service.py:_key` and the `cache_key(definitions=...)` parameter, and the test edit is about 28 lines, not 15. The `decision-change` kind, the named records (0008 §3 "Cache" bullet, plan 05 §C-4) and the stated conditions are honest; `docs/plan/02-architecture.md:139, 159` do not list the two hashes, so they need no edit)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### CMD-09: The capability cache itself buys about a second per start
- Kind: decision-change
- Where: `capabilities/cache.py` (164 code lines), `capabilities/fingerprint.py` (96), `capabilities/service.py` (`_gpu`, `_gpu_source`, `_key`, `_store`, `_put`, `_writes`, the cache branch of `_run`: about 60 lines), `capabilities/issues.py:100-112` (the "checked again" branch), `validation/video.py:226-230, 270-285` (`_rechecking`), `diagnostics.py:155-156`, `models/capabilities.py:88-89` (`from_cache`), frontend `frontend/src/components/video/encoders.ts:79, 175` and `frontend/src/components/settings/EncodersSection.vue:131`, `frontend/src/api/schema.d.ts:2620`.
- Now: plan 05 §C-4 requires the cache, but 0008 says it only removes the "checking..." period: every start runs the full detection anyway (0.2 s on the capture machine with VAAPI and AMF; hardware tests are limited to 10 s each, 3 in parallel). The cache costs: the key (path, size, mtime, version, env, GPU fingerprint, options, two hashes), the GPU fingerprint reader for Linux and for the Windows registry (with its `Registry` protocol and a fake for tests), the atomic writer and pruning, the "cached result is checked again" state (`from_cache` plus `detecting`) that three modules and the frontend read, and the 0008 review fix 1 that exists only because a cached `unavailable` can be stale. Without a cache, a start shows `checking` for the length of the detection, which is already what a first start and `rescan()` do. It also lets the VAAPI node listing move into `detect.py` (it is eager in the service only because the cache key needs the nodes).
- Change: delete `cache.py`, `fingerprint.py`, the key and cache code in `service.py`, `from_cache` handling in `issues.py`, `validation/video.py`, `diagnostics.py`, the frontend. Keep `CapabilitySnapshot.from_cache` out of the model (or keep it always `False` to leave the OpenAPI schema as it is). Move `render_nodes` listing into `_Detection.run` (lazy, only when a VAAPI encoder is pending) and drop `DetectionOptions.render_nodes`.
- Behaviour: changes. For the first moments after each start, every encoder shows `checking...` and queueing waits for the result (03 §Encoders: "Detection still running: the picker shows checking..., queueing waits"). The user decides if the wait is acceptable on the slowest machine (the Windows VM, an NVIDIA or Intel GPU where a hardware test takes seconds).
- Contracts touched: HTTP/OpenAPI if `from_cache` is removed (frontend change: `schema.d.ts`, `encoders.ts`, `EncodersSection.vue`, the i18n key `settings.encoders.fromCache` in `frontend/src/i18n/messages/en/settings.json:55`, the fixture `frontend/src/components/video/testing/capabilities.json`, and the tests `stores/system.test.ts:54`, `components/video/encoders.test.ts:118`, `components/settings/encoders.test.ts:24`, `EncodersSection.test.ts:52`, `api/boot.test.ts:45`; core: the JSON-schema snapshot `packages/reframe/tests/models/__snapshots__/test_schema.ambr:1663`); persisted data: the cache folder `capabilities/` is orphaned (harmless); `docs/plan/05-core.md` §C-4, `02-architecture.md:139` and `:159`, `docs/status.md` (C-4 row), decision 0008.
- Callers to update: the files above and `packages/reframe/src/reframe/service.py:965` (no change in the call).
- Tests: delete `test_cache.py` (169 lines), `test_fingerprint.py` (149), `test_recheck.py` (64), the cache tests in `test_service.py` (about 250 lines: 211-262, 402-471, 474-570), the `from_cache` tests in `test_issues.py`, `tests/validation/` rechecking tests, frontend tests for `rechecking`.
- Decision records: 0008 §3 (cache, GPU fingerprint) and review fix 1; plan 05 §C-4 "Cache"; 02 §Bundled FFmpeg. For the decision to change: measure start-to-final-snapshot time on the slowest target machine; if it is below about 2 s, the cache is not worth its parts.
- Size: L; estimated lines: -400 / -650 (not counted in the totals below)
- Risk: medium. A user with a slow hardware test sees `checking` for longer after every start. Nothing can damage output files, queue or settings.
- Depends on: supersedes CMD-07 and CMD-08, and the cache parts of CMD-02 (`cache.py:126`, `test_cache.py:66, 81`)
- Confidence: low
- Verdict: ADJUSTED (the kind `decision-change`, the named records and the measurable condition are honest; plan 02 `:159` states the cache as an architecture row and `docs/status.md` has a C-4 row about it, and the contracts list missed the schema snapshot, the i18n key and the frontend fixtures and tests; every `from_cache` reader the finding lists exists at the stated line)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### CMD-10: Five copies of "every encoder available" test helper
- Kind: tests
- Where: `tests/command/conftest.py:64-92` (`caps`), `tests/preview/helpers.py:47-61` (`caps`), `tests/jobs/conftest.py:67-95` (`caps`), `tests/queue/conftest.py:106-113` (`all_caps`), `tests/presets/test_builtin.py` (`_everything_available`, moved there from `tests/integration/test_builtin_presets_validate.py`); the shared home would be `testing/reframe_testing/capabilities.py` (45 lines).
- Now: each helper loops over `definitions.video_encoders` and `audio_encoders`, builds an `EncoderStatus` per id, collects the filter names from `definitions.filters`, and returns a `CapabilitySnapshot`. They differ in details: `unavailable` ids, `libplacebo` usable, failed or untested, `filters=None`, the VAAPI device, `in_build`, `checked_at`.
- Change: one `available_caps(*, unavailable: Mapping[str, str] | None = None, state: EncoderState = EncoderState.AVAILABLE, libplacebo: bool | None = True, filters: bool = True, devices: Mapping[str, str] | None = None, supports_10bit: bool | None = None, in_build: bool | None = None, detecting: bool = False)` in `reframe_testing/capabilities.py` (the verified call sites need `state` (`queue/test_faults.py:472, 491` pass `EncoderState.CHECKING`), `devices` (a per-encoder map, two `command` tests), `supports_10bit=True` (the builtin-preset test) and `libplacebo` whose default differs: `True` in `command`, `False` in `preview`); the five helpers become one-line calls or aliases. `tests/validation/test_rules.py:95` and `test_template.py:91` have a different `caps(states, **kw)` shape; leave them.
- Behaviour: unchanged (tests only).
- Contracts touched: none
- Callers to update: the five modules above and their importers.
- Tests: the helpers go; every test that uses them stays.
- Decision records: 0004 (shared testing package).
- Size: S; estimated lines: -0 / -35
- Risk: medium. Defaults differ between the old helpers (`libplacebo`, `device` for VAAPI, `in_build`, `hardware`, `checked_at`, `supports_10bit`, `filters=None`), each old call site must keep its own; the 73 plan snapshots and the five suites guard it. There are more `caps`-like builders with other shapes (`tests/validation/scenario.py:217`, `tests/capabilities/test_issues.py:28`): leave them.
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (the five copies exist, but the proposed signature did not cover the real call sites (`state`, per-encoder `devices`, `supports_10bit`); anchors fixed; risk raised to medium and confidence lowered to low, because the saving of about 35 lines needs 7 parameters)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### CMD-12: `build_plan` is one 86-statement function
- Kind: structure
- Where: `command/builder.py:306-465` (`build_plan`: C901 26, PLR0912 24 branches, PLR0915 86 statements, 8 parameters), `:142-155` (`_Video`), `:163-238` (`_video_plan`), `:578-583` (`_pairs`, `_contains_pair`), `command/metadata.py:136-145, 288-307` (`ChapterPlan.map_from`), `command/video.py:366-424` (`video_encoder_args`: C901 12).
- Now: `build_plan` builds the inputs, maps, filters, metadata, flags, steps and display in one body with 3 nested closures. `_Video` is built positionally with 8 values (`builder.py:180`, `235`). `ChapterPlan.map_from` is `None`, `0` or `-1` (a magic number, `FROM_FILE`), which the builder turns into the strings `"-1"`, `"0"` or an input index. `_pairs` and `_contains_pair` exist to de-duplicate one list (`copy_args`, which holds exactly one entry: `truehd = ["-strict", "-2"]` in `definitions/data/containers.toml:87`).
- Change (readability, no net lines): split `build_plan` into `_source_inputs(...)` (seek, `-i`, external inputs, chapter input and map), `_maps(...)` (video map and filter, audio and subtitle maps, attachments), `_metadata_args(...)` (stream metadata, tags, flags) and `_steps(...)`. Build `_Video` with keywords and defaults for the passthrough case. Replace `map_from` by `copied: bool` plus `file`. Replace `_pairs`/`_contains_pair` by `if args not in seen: flags += args`. Split the rate-control block of `video_encoder_args` (`video.py:379-413`) into `_rate_args(encoder, video, run, passlog)`.
- Behaviour: unchanged.
- Contracts touched: none (the plan argv is guarded by `test_snapshots.py`, 73 jobs, and `test_integration.py` with real FFmpeg).
- Callers to update: `builder.py`, `metadata.py`, `video.py`, `tests/command/test_tracks.py:492-522` (`map_from` asserts become `copied` asserts), `tests/command/test_output_chapters.py:156`.
- Tests: none deleted; the snapshots are the guard of unchanged output.
- Decision records: 0013 (argument order) is kept; the order of the final `ffmpeg_argv` list must not change.
- Size: M; estimated lines: -0 / -0
- Risk: medium. The argv order is the product; the snapshots catch any change, and the real-FFmpeg tests need `needs_ffmpeg`.
- Depends on: CMD-01, CMD-04, CMD-06 (touch the same lines of `_video_plan` and `_fixup_step`; do those first)
- Confidence: medium
- Verdict: CONFIRMED (checked: complexity numbers match `complexity.txt`; `copy_args` has exactly one entry in `containers.toml:87`; the builder reads only `map_from == 0` and `file is not None`, so `copied` plus `file` carries the same three states; `_Video` is built positionally at 180 and 235; the 73 plan snapshots, not 68, guard the argv. Note `copy_args` is a generic `dict[str, list[str]]` in the schema: the pairwise de-duplication of `_pairs` handles a multi-pair entry, `if args not in seen` handles it only as a whole list)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### CMD-13: HDR format labels three times, the multiplication sign twice
- Kind: duplication
- Where: cross-area: `cli.py:228-233` (`_HDR_NAMES`), `validation/filters.py:34-39, 237` (`_HDR_LABELS`), `preview/graph.py:86-90` (`_hdr_name`, same four names keyed by string value); `cli.py:218` (`TIMES`) and `dimensions.py:50` (`TIMES`, exported, used by `validation/dimensions.py:13`).
- Now: `HdrFormat` (`models/media.py:190-194`) has four members, and three modules keep their own copy of the display names `HDR10`, `HDR10+`, `HLG`, `Dolby Vision`. `cli.py` defines `TIMES` again; `tests/test_cli.py:28` imports it from `reframe.cli`.
- Change: a `label` property on `HdrFormat` (a plain property is not a Pydantic field, so the OpenAPI schema does not change) and delete the three dicts. In `cli.py` write `from reframe.dimensions import TIMES` (it stays importable from `reframe.cli`).
- Behaviour: unchanged.
- Contracts touched: public core API (new property); none for HTTP.
- Callers to update: `cli.py`, `validation/filters.py`, `preview/graph.py`, and `packages/reframe/tests/test_cli.py:28` (`TIMES` imported from `reframe.cli`; mypy runs `strict` over `packages/reframe/tests`, so a name that `cli.py` only imports is an implicit re-export error: import it from `reframe.dimensions` there).
- Tests: none removed; one import changes.
- Decision records: none.
- Size: S; estimated lines: -10 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED ("it stays importable from `reframe.cli`" is true at runtime but not for `uv run mypy`, so `tests/test_cli.py:28` must change; the three display-name copies and the second `TIMES` are confirmed. `naming/context.py:53` `_HDR_LABELS` is not a fourth copy: it uses the short tokens `DV`, `HDR10+`, `HDR10`, `HLG` for file names. `preview/graph._hdr_name` keeps its `or "HDR"` fallback for an empty list)
- Orchestrator: joined into X-05 (see ../cross-cutting.md); that entry decides the tier and the work package.

## Looked at and kept

- CMD-11 `jobtype.py` decides "is this track copied" twice: rejected in verify. The two copies are not equal. `_copy_type` does not check whether the container can copy a subtitle codec (an SRT copy into MP4 stays a "remux", converted on the way: `containers.toml` has `mp4.subtitles.copy` without `subrip`; run in verify, `job_type` of `multitrack.mkv` to MP4 with passthrough video and copied SRT tracks returns `remux`), while `_subtitle_blockers` does; a shared `_subtitle_problem` would turn that job into an "encode" with a new message. The audio loops also differ (`_audio_blockers` checks the track order first). A flag to keep both behaviours, plus the `"cannot be copied"` string test the finding admits is not pretty, leaves nothing to save (about 12 lines). The reason texts are pinned by `tests/command/test_tracks.py:582-599`, not by `test_metadata_edit.py:52`.
- CMD-06 (part) `render_tag`: rejected in verify. It is a stricter wrapper, not a pass-through: `options`, `output_size`, `now` and `definitions` are required keyword arguments, where `render_value` defaults them to `None` (a forgotten `output_size` or `definitions` would silently empty `{width}` or reload the definitions).
- `PlanError` and its 31 raise sites in `command/` plus `tests/validation/test_command_agreement.py`: decisions 0013 (Consequences) and 0026 require that the builder refuses what validation reports. `PlanError` is also data for 8 catch sites (`preview/clip.py`, `preview/frames.py`, `preview/graph.py`, `validation/dryrun.py`, `jobs.py`, `batch/audio_rules.py`, `queue/runner.py`, `builder.output_chapters`), so the checks are not only defensive.
- `command/errors.py` at 0% coverage: an artefact. The report lists import-time lines of every module as missed (`command/__init__.py` also shows 0%).
- `ENCODER_LAYOUTS`, `LAYOUT_CHANNELS` and `_kept_layout` in `command/audio.py`: 0013 follow-up (libopus layouts), checked against the real encoder by `test_layout_tables_match_ffmpeg`.
- `frame_rate_factor`, `_drops_before_start` (`-ss 0`), `-copypriorss`, the 1 ms chapter edge rule: 0013 follow-ups, with the verified FFmpeg behaviour in `testdata/README.md`.
- `command/quoting.py` (posix and windows quoting): 0013 follow-up item 5, tested with bash, zsh and fish.
- `hdr_params` branches per `params_arg` (x265, x264, SVT-AV1): 0013 §3. Moving them to the definitions needs a new schema and saves nothing net.
- `command/header.py`, `in_place_edit`: 0034 and 0080 (own Matroska header writer).
- `dimensions._snap_size`, `_span`, `_crop`, `chroma_steps` and its tables: 0009; `tests/dimensions/test_properties.py` checks `compute_geometry` against an independent oracle and `tests/dimensions/test_ffmpeg.py:129` checks `chroma_steps` against real FFmpeg for every pixel format. A rewrite would risk the output size for nothing the plan asks.
- `capabilities/reasons.py` rule table: 0008 and `testdata/README.md` ("Hardware encoder failures"). The 25 patterns are the recorded FFmpeg texts.
- `capabilities/fingerprint.py` `Registry` protocol and `_WinReg`: 0008 §7 (winreg unit-tested on Linux with a fake); the Windows path is not dead code. (It goes only if CMD-09 is taken.)
- `CapabilityService._watch`, `_identity`, `_detections` and the wait for a replaced detection in `close()`: 0008 review fix 6 and "a new ffmpeg starts a new detection".
- The pre-check for an unusable ffmpeg in both `service._run:275` and `detect_capabilities:483`: the service one skips the cache stat and key; the `detect_capabilities` one serves direct callers (3 parametrized tests in `test_detect.py`). Merging saves 5 lines and moves tests.
- `definitions: Definitions | None = None` with `load_definitions()` fallback in 9 functions of `command/`: every production caller passes it, but 100+ test calls omit it. The saving is about 18 lines for a large test edit.
- `planned_audio(container: ContainerDef | Container)` with `_container()` (`audio.py:219-225`): production callers pass a `ContainerDef`; 13 test calls pass an id. Saving 7 lines for 13 test edits; not worth it.
- `build_video_graph`, `audio_output`, `plan_subtitles`, `hdr_params` complexity (C901 11-17): each is a flat sequence of the rules in 0013; splitting would not remove code. `build_plan` is the one that is too long (CMD-12).

## Noted by the verifier (not verified)

- `validation/filters.py:227` defines its own `is_hdr(stream)`, which is also true for a PQ or HLG transfer without HDR side data, next to `command.filtergraph.is_hdr`, which needs a probed HDR format: same name, different result.
- `command/jobtype._copy_type` returns "Remux: the video and every audio and subtitle track are copied without re-encoding." for a job whose copied SRT tracks go into MP4 and are converted to `mov_text` (run in verify on `multitrack.mkv`); the text is not exact for that job.
