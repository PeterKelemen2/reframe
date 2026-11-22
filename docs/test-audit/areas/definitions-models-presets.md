# Area definitions-models-presets: `tests/definitions/`, `tests/models/` (+ schema snapshot), `tests/presets/`, `tests/integration/`, `tests/test_settings.py`, `test_service_settings.py`, `test_jsonpatch.py` (linter: `testing/reframe_testing/definitions_lint.py`)

Baseline: 21 files, 1,170 tests, 6,418 test code lines, 102 s of test time.

All paths are relative to `packages/reframe/tests/` unless they start with `testing/` or `docs/`.
Commit 38cf3eb.

Trim reports read (`docs/test-trim-reports/`): M (models), P (probe and definitions), C (presets
part), Q (settings, service settings, jsonpatch part), B (`test_builtin_presets_are_clean`), V2
(the `test_options_search_hdr` mention). N, R, T and V1 have nothing in this area (checked with
grep). No finding below drops a test that a report kept. TDM-01 merges two kept groups (C:133
and B:144), and it says why their reasons still hold after the merge.

## Summary

Verifier summary: 3 confirmed (TDM-02, TDM-03, TDM-04), 1 adjusted (TDM-01), 0 rejected. Corrected totals: Tier A 0 tests, about 20 code lines (TDM-02 13-14, TDM-04 7; 24 with the dead `_written` of the notes). Tier A+B 104 tests, about 57 code lines (TDM-01 -12 measured, TDM-03 about -25 estimated, not applied), about 0.1 s.

4 findings. Tier A: 2 findings, 0 tests, about 20 code lines. Tier A+B: 4 findings, 104 tests,
about 56 code lines, about 0.1 s. The area is already lean: an earlier test trim
(`docs/test-trim-reports/M.md`, `P.md`, `C.md`, `Q.md`) and Q-6 (MOD-02/05/06/08, NDP-02/03/04)
removed most of the easy cases. Most of the time (51 s `test_tools.py`, 11 s
`test_options_values.py`) is real-FFmpeg oracle tests, and those stay. Another 24 s is the
Hypothesis round trip, which is the C-2 "Done when".

Best three:
1. TDM-01: the 5 per-preset checks over the 26 built-ins (3 in `presets/test_builtin.py`, the
   `integration/` file, the `batch/test_lint.py` one) become one parametrized test: -104 tests.
2. TDM-02: the three linter-mutation tests in `test_options_search_hdr.py` move to `test_lint.py`,
   which removes the second copy of `_lint_mutated`/`_option` and one duplicate assert: -13 lines.
3. TDM-03: the FFmpeg run helpers copied between `test_options_values.py`, `test_tools.py` and
   `presets/test_builtin.py` go into one shared module: about -25 lines.

**The question in the brief: do the per-preset parametrizations over the 26 built-ins assert
the same thing?** No. No two of them are equal, but they overlap a lot:
- `presets/test_builtin.py::test_video_uses_only_definition_values`, `test_filters_use_only_definition_values`
  and `test_audio_uses_only_definition_values` check the preset data against the definitions
  in test code (encoder known, codec in container, quality/bitrate range, choice and bit depth,
  option type, `params_arg`, not passthrough, filter preset and tune, audio bitrate limits and
  fixed steps, sample rate, passthru copy codecs). No product validator runs.
- `presets/test_builtin.py::test_values_come_from_handbrake` checks the values against the
  HandBrake 1.11.2 table. That is a different source of truth.
- `integration/test_builtin_presets_validate.py::test_builtin_preset_has_no_validation_errors`
  runs the product `validate_template` with every encoder available and fails **only on
  errors**. It covers every template rule (video settings, filters, container codecs,
  naming, tags), and it also runs `lint_defaults`.
- `batch/test_lint.py::test_builtin_presets_are_clean` runs `lint_defaults` (**all**
  severities) plus `container_codec_issues`. `covquery` shows that its only lines outside the
  integration test are `batch/lint.py:288-330` (`container_codec_issues`). The integration
  test checks the same condition (`encoder.codec in container.audio.encode` for the codec
  rules, the extras and the fallback encoder) through `validation/container.py:73-77, 226-228`
  as a `container.codec_unsupported` error. So the batch test differs from the integration
  test only in the warning/info issues of `lint_defaults`. Trim B kept it for that reason.

All of them take the same input (one built-in preset) and assert different things. Per the
brief, that is a merge (TDM-01), not a deletion.

## Findings

### TDM-01 One parametrized validity test per built-in preset instead of five
- Kind: layer-duplicate (plus near-copy setup)
- Where: `presets/test_builtin.py::test_video_uses_only_definition_values` (131),
  `presets/test_builtin.py::test_filters_use_only_definition_values` (185),
  `presets/test_builtin.py::test_audio_uses_only_definition_values` (196),
  `integration/test_builtin_presets_validate.py::test_builtin_preset_has_no_validation_errors` (27, whole file),
  `batch/test_lint.py::test_builtin_presets_are_clean` (116, batch area: cross-area edit)
- Now: five parametrizations, each with 26 cases, over the same `builtin_presets()` list
  (130 test ids). Three check the data against the definitions in test code. One runs
  `validate_template` and allows only non-errors. One runs `lint_defaults` and
  `container_codec_issues` and allows nothing.
- Change: parametrize as `presets/test_builtin.py::test_builtin_preset_is_valid(preset, defs)`.
  Its body holds, in order: the video body, the filters body and the audio body (one
  `container = defs.containers[...]` line is shared). Then
  `issues = validate_template(preset, _everything_available(), subject=preset.name)` and
  `assert [i for i in issues if i.severity is Severity.ERROR or i.code.startswith("defaults.")] == []`.
  Move `_everything_available` from the integration file. Delete
  `tests/integration/test_builtin_presets_validate.py` (and the empty folder). Delete
  `batch/test_lint.py::test_builtin_presets_are_clean` and its now unused `builtin_presets`
  import (line 45). Keep `test_values_come_from_handbrake` as it is: it checks a different
  source (the HandBrake table), and its failure output names the table row.
  Smaller fallback (also Tier B): only add the `defaults.` clause to the integration test and
  delete the batch test (-26 tests, about -4 lines).
- Saved: 104 tests (130 → 26), about 11 code lines (test_builtin -5 for 2 decorators, 2 defs
  and the duplicate `container` line; +21 for the helper, the validate call and imports;
  integration file -23; batch -4). About 0.1 s (the five groups took 0.03-0.04 s each).
- Guarantee kept by: the merged test. It keeps every assert of the five bodies, with the same
  input (each built-in preset, the same `load_definitions()`, the same all-available caps).
- Why nothing is lost: video, filter and audio asserts are copied unchanged. The integration
  assert `errors == []` is kept (the ERROR clause). The batch assert `lint(preset) == []`
  has two parts. `lint_defaults(defaults, container=...)` is called by `validate_template`
  with the same arguments (`validation/__init__.py:163`), and every code it emits starts
  with `defaults.` (`batch/lint.py:190-411`), so the `defaults.` clause catches it at every
  severity. `container_codec_issues` is the same check as the `container.codec_unsupported`
  error (`validation/container.py:224-228`; the `container_codec_issues` docstring says so),
  so the ERROR clause catches it. The new assert passes today: the batch test passes, so
  `lint_defaults` is empty for every built-in.
- Recorded keeps: trim C (`C.md:133`) kept the four `test_builtin` per-preset checks because
  "each validates a different data item". The merge keeps every one of those asserts, and
  `test_values_come_from_handbrake` is not merged. So the reason still holds: no data item
  loses its check. Only the number of test ids changes. Trim B (`B.md:144`) kept
  `test_builtin_presets_are_clean` because the integration test "fails only on errors", while
  the batch test also fails on lint warnings and info notes. The new `defaults.` clause
  removes that difference: every `lint_defaults` issue fails at every severity. That reason
  therefore no longer holds after the change, and the batch test must not be deleted without
  that clause.
- Docs and history: `grep docs/` finds none of the five names, except trim report
  `docs/test-trim-reports/B.md:144` (handled above). `git log -S`: the three
  test_builtin tests come from 9ed78f8 (C-9 feature), the integration test from 0bb4c52 ("M2:
  every built-in preset passes template validation", feature), and the batch test from cd41c78
  (C-12 feature). None is a bug or review fix.
- Risk: low for the guarantee. The cost is failure granularity: the first failing assert hides
  the later ones for that preset. The asserts already name the encoder, option or codec. The
  batch file belongs to another area, so its owner must agree.
- Proposed tier: B (a merge across three files and two areas)
- Confidence: high

Verdict: ADJUSTED — the merge is sound and keeps every check, but two corrections. (1) The bodies cannot be "copied unchanged": the video body binds `encoder` (`VideoEncoderDef`) and `bitrate` (`BitrateDef | None`), the audio body rebinds both (`AudioEncoderDef`, `int | None`), and `uv run mypy` then reports 7 errors in `test_builtin.py` (incompatible assignment, `"VideoEncoderDef" has no attribute "bitrate"`, unused `type: ignore`). The audio loop needs its own names (`audio_encoder`, `kbps`); after that ruff, ruff format, mypy and mypy `--platform win32` are clean. (2) Failure granularity is a worse message, not a lost guarantee (see the mutation runs): every mutation that made any of the five old checks fail also fails the merged test, but a preset with several defects now shows only the first one per run (one defect fixed per rerun), and which check failed is read from the assert line and message, not from the test name. Several asserts carry no message (`filter_id in defs.filters`, `quality.min <= rate.value <= quality.max`, `limits.min <= bitrate <= limits.max`); pytest's assertion rewriting still prints the expression and the line, and the test id still names the preset, so the failure stays diagnosable. Recorded keeps: trim C (`C.md:133`, "each validates a different data item") still holds, every data item keeps its assert; trim B (`B.md:144`, the integration test "fails only on errors") no longer holds after the `defaults.` clause, which my `lint` mutation shows (a `defaults.rule_shadowed` WARNING fails only the batch test among the old five, and fails the merged test). No plan "Done when" names either test (C-9 "Done when" names migration, export/import and the corrupt file; 08-roadmap has no built-in-validates item); no decision record names them; only `docs/test-trim-reports/B.md:144` and Q-6's `docs/simplify/areas/command.md:212` (CMD-10, Tier C, an anchor to `_everything_available` in the integration file, which moves). Numbers confirmed: 238 → 134 tests (-104), 975 → 963 code lines (-12, auditor about -11), about 0.1 s. Tier B stays (cross-area edit of `batch/test_lint.py`; the owner should accept the coarser failure report). `container_codec_issues` keeps its own tests (`batch/test_lint.py` via `lint()`, `validation/test_template.py`, `jobs/test_service.py`).
Checked: applied TDM-01 in the worktree (merged `test_builtin_preset_is_valid`, `_everything_available(defs)` moved, integration file and batch test deleted, `builtin_presets` import removed) → collect: `presets/test_builtin.py` 145 → 93, `integration/` 26 → 0, `batch/test_lint.py` 67 → 41; `runtests.sh presets/test_builtin.py batch/test_lint.py -q` → 134 passed in 3.21 s (light load, slot wait under 3 min).
Checked: mutation of built-in `fast-1080p30` in `presets/data/builtin.json` (one at a time, file restored after each), old five checks vs the merged test, `-k … fast-1080p30 -n 0`:
  - `video` (`preset: "bogus"`): old video + integration fail; merged fails (`libx264 preset 'bogus'`).
  - `filters` (deinterlace `tune: "bogus"`): old filters + integration fail; merged fails (`'bogus' in set()`).
  - `audio` (AAC `max_bitrate: 2000`): old audio + batch fail, integration passes (only an INFO `defaults.bitrate_snapped`); merged fails (`2000 <= 512`).
  - `naming` (`movie_template: "{nosuchfield}"`): only the old integration test fails; merged fails (`naming.unknown_variable` ERROR).
  - `lint` (two `hu` rules, the second shadowed): only the old batch test fails; merged fails (`defaults.rule_shadowed` WARNING).
  - `video,audio,lint` together: old: 4 tests fail (video, audio, integration, batch); merged: 1 failure that names only the video defect.
  A `level: "1.0"` mutation passed every check, old and merged (not a template error), so I replaced it with `naming`. Worktree restored with `git checkout -- packages/reframe/tests` and the JSON copy.

Orchestrator: Tier B, package Q-7.9. Use pytest's built-in `subtests` fixture (pytest 9.1) for the five checks, so one run still reports every failed check of a preset; rename the audio loop's variables (verifier); if `subtests` does not work under xdist on Windows, keep the five checks as five asserts and accept the first-failure message.

### TDM-02 The linter-mutation tests of `test_options_search_hdr.py` belong in `test_lint.py`
- Kind: shared-setup
- Where: `definitions/test_options_search_hdr.py::test_every_option_is_in_a_category_of_the_panel` (216),
  `definitions/test_options_search_hdr.py::test_an_option_that_writes_what_something_else_writes` (224-239, 6 cases),
  `definitions/test_options_search_hdr.py::test_nvenc_multipass_may_share_the_argument_of_2_pass` (242),
  helpers `_lint_mutated` (205) and `_option` (211); copies at `definitions/test_lint.py:26` and `:32`
- Now: `test_options_search_hdr.py` (its docstring calls it "the option search, the HDR options,
  option resolution and the option linter checks") holds a second copy of the linter
  harness: `_lint_mutated` and `_option` are the same code as in `test_lint.py`. The
  harness needs the imports `Callable`, `Any`, `Definitions`, `load_raw` and
  `lint_definitions`. `test_nvenc_multipass_...` starts with `assert lint_definitions(DEFS) == []`,
  which is the same input and assertion as `test_lint.py::test_the_packaged_definitions_are_clean` (15).
- Change: move the three tests unchanged into `definitions/test_lint.py` (use
  `load_definitions().video_encoders` where they read `DEFS`, and add `OPTION_CATEGORIES` to
  `test_lint.py`'s `reframe.definitions` import). Delete the two helper copies, the five
  imports and the `OPTION_CATEGORIES` import from `test_options_search_hdr.py`. Delete the
  duplicate `assert lint_definitions(DEFS) == []` line. Remove "and the option linter checks"
  from the module docstring.
- Saved: 0 tests (8 test ids move), about 13 code lines, 0 s
- Guarantee kept by: the same tests in `test_lint.py`, which use its identical `_lint_mutated`/`_option`.
  The packaged-data-clean assert is kept by `definitions/test_lint.py::test_the_packaged_definitions_are_clean` (15).
- Why nothing is lost: the inputs and asserts do not change. Only the module changes. The helper
  bodies are the same (`load_raw()`, mutate, `lint_definitions(Definitions.model_validate(raw))`,
  `next(o for o in options if o["key"] == key)`).
- Docs and history: `grep docs/` finds none of the three names. `git log -S`: all three come
  from 13e6c2f (C-6 feature), with no bug reference. Q-6 NDP-02 moved the linter to `testing/`
  but did not touch this helper copy.
- Risk: low (a move only)
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `_lint_mutated` and `_option` in `definitions/test_options_search_hdr.py:205-213` are character-for-character the same as `definitions/test_lint.py:26-34`; `Callable`, `Any`, `Definitions`, `load_raw`, `lint_definitions` and `OPTION_CATEGORIES` are used in `test_options_search_hdr.py` only by the three moved tests and the helpers (grep counts); `assert lint_definitions(DEFS) == []` repeats `test_the_packaged_definitions_are_clean` (same packaged data, same call). No doc or testdata file names the three tests; all three come from 13e6c2f (C-6 feature). My estimate of the saving is 13-14 code lines (two helpers about 7, five import lines, the `OPTION_CATEGORIES` line, the duplicate assert; `test_lint.py` gains no line if `OPTION_CATEGORIES` joins its one-line `reframe.definitions` import). Tier A stands.
Checked: `grep -cE '<name>' definitions/test_options_search_hdr.py` for each import; `git log -S test_nvenc_multipass_may_share_the_argument_of_2_pass` → 13e6c2f; `grep -rn` of the three names in docs/ and testdata/ → none. Not applied (a move only).

Orchestrator: Tier A, package Q-7.4.

### TDM-03 One shared helper for the "run FFmpeg on lavfi and read the log or SEI" code of the oracle tests
- Kind: shared-setup
- Where: `definitions/test_options_values.py` helpers `_ffmpeg` (35), `_written` (43), `_args` (57),
  `_run` (69), the `ThreadPoolExecutor` block (104-105), imports (6-10);
  `definitions/test_tools.py` `_tools` (64), `_ffmpeg` (73), `_parallel` (97), `_written` (189),
  `_mapping_args` (181), `_sei_options` (326); `presets/test_builtin.py` `_settings_sei` (503:
  the same `rb"options: ([ -~]+)"` SEI regex) and `run_params` (532: find ffmpeg plus `subprocess.run`)
- Now: three real-FFmpeg test files each find ffmpeg, run it with `-hide_banner -nostdin`, pool
  the runs in threads, turn an option value into its written text, and read x264/x265's
  settings SEI, each with its own copy. `test_options_values.py` copies `test_tools.py` almost
  line for line (`_written` is a subset, `_args` is `_mapping_args` plus the param join of
  `_encode_args`, `_run` is `_ffmpeg`, the pool is `_parallel`). Also, its pure data test
  `test_every_software_encoder_has_options_in_each_main_category` (109) sits under the
  module's `pytestmark = needs_ffmpeg`, so it is skipped on a machine without FFmpeg.
- Change: move `_ffmpeg` (as `run_ffmpeg_capture(args, timeout)`), `_parallel`, `_written` and
  `_sei_options` from `test_tools.py` to `testing/reframe_testing/encoders.py` (or `media.py`,
  which already has `find_ffmpeg`) and import them in the three files. In `test_options_values.py`,
  keep `_REFUSED`, `_COMPANIONS` and `_values`, and build the argv with `_mapping_args`-style
  code. Move `test_every_software_encoder_has_options_in_each_main_category` to
  `definitions/test_options_search_hdr.py` (no FFmpeg, next to the category test). Keep both
  file names: decision 0035:16 and `testdata/README.md:2060` name `test_options_values.py`.
  (Merging the file into `test_tools.py` would save about 40 lines, but it changes those paths.)
- Saved: 0 tests, about 25 code lines (test_options_values about -22; test_builtin about -5;
  test_tools about +2 import lines), 0 s
- Guarantee kept by: the same tests with the same FFmpeg arguments
- Why nothing is lost: the argv, timeouts and detectors stay per test. `_REFUSED` (broader than
  `test_tools._PARAM_ERRORS`) stays in `test_options_values.py`. `BAD_PARAM` stays in
  `test_builtin.py`. Watch out for this: `test_tools._encode_args` passes x26x params through
  `escape_value`, and `test_options_values._args` does not. The enum written values contain no
  `:`/`\`/`'` today, but the shared version must keep the unescaped join for this test, or
  someone must check it.
- Docs and history: `grep docs/`: `test_options_values.py` in decision 0035:16 and
  `testdata/README.md:2060, 2079` (`test_every_enum_and_bool_value_encodes`). Both stay, because
  the file name and test name stay. `git log -S`: 13e6c2f (C-6 feature).
- Risk: medium. These are the oracle tests behind `testdata/README.md`. A wrong argv in the
  shared helper would make them check something else and still pass. A verify run must
  compare the stderr of a sample of jobs before and after.
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED (Tier B, risk medium stays) — the `escape_value` difference is real: `test_tools._encode_args` (`test_tools.py:209-212`) joins x26x params with `escape_value(v)`, and `test_options_values._args` (`:57-66`) joins them raw. It changes no argv today: I ran `escape_value` over every enum and bool value of every `x26x_param` option of the software encoders (326 values) and the three `_COMPANIONS` values, and none changes. The product writes x26x params with `escape_value` (`command/video.py:147`), so a shared helper that keeps the escaped join is closer to the product and gives the same argv for this test today; the auditor's "keep the unescaped join" is safe but not needed. The file names stay, so decision 0035:16, decision 0010:10 and `testdata/README.md:623, 628, 2060` (`test_tools.py`, `test_options_values.py`) stay true. Correction: `test_options_values._written` (`:43-46`) is dead code (defined, never called), so it is not "a subset to move" but 4 lines to delete (Tier A on its own, see notes).
Checked: `uv run python -c` loop over `load_definitions()` x26x enum/bool values with `escape_value(v) != v` → 326 values, 0 differ; `grep -n _written definitions/test_options_values.py` → definition only. Not applied (not a merge or parametrization; the stderr comparison the auditor asks for is still needed when it is done).

Orchestrator: Tier B, package Q-7.9. Keep the escaped join (the product escapes the values too); delete the dead `_written` helper.

### TDM-04 Small asserts that another test makes with the same input
- Kind: other (duplicate asserts)
- Where:
  - `presets/test_builtin.py::test_the_h265_mkv_and_nvenc_1080p_presets` (103), lines 104-108 (the `mkv` half)
  - `presets/test_store.py::test_default_preset` (202), line 203 `assert DEFAULT_BUILTIN_ID == "h265-mkv-1080p"`
  - `presets/test_builtin.py::test_ids_are_unique_stable_slugs` (77), line 81 `assert {p.id for p in builtin_presets()} == set(IDS)`
- Now / Change:
  - The `mkv` asserts check name "H.265 MKV 1080p", encoder libx265, container mkv and
    FitWithin 1920x1080 for `h265-mkv-1080p`. `test_values_come_from_handbrake[h265-mkv-1080p]`
    (375) checks the encoder, container and fit box from its table row (`libx265 … 1920x1080
    … mkv`). `test_default_preset_is_h265_mkv_1080p` (119-120) checks
    `DEFAULT_BUILTIN_ID == "h265-mkv-1080p"` and its name "H.265 MKV 1080p". Delete lines
    104-108. Keep the nvenc asserts: its name and category "Hardware" are checked nowhere else.
  - `test_store.py:203` is the same assertion as `test_builtin.py:119`. Delete it. The test
    keeps using the constant.
  - `test_builtin.py:81`: `IDS` is `[p.id for p in builtin_presets()]` at import, so the line is
    always true. Q-6 MOD-06 item 4 left it in this form when it removed `builtin_ids`. Delete it.
- Saved: 0 tests, 7 code lines, 0 s
- Guarantee kept by: `presets/test_builtin.py::test_values_come_from_handbrake[h265-mkv-1080p]` (375),
  `presets/test_builtin.py::test_default_preset_is_h265_mkv_1080p` (115). For line 81, nothing
  is needed (a tautology). `test_builtin_presets_returns_copies` (125) covers a repeated call.
- Why nothing is lost: same preset id, same expected values, same equality asserts.
- Docs and history: `grep docs/` finds none of `test_the_h265_mkv_and_nvenc_1080p_presets`,
  `test_default_preset`, `test_ids_are_unique_stable_slugs`. `git log -S`: the first was renamed
  from `test_presets_of_the_m2_demo_exist` (3b0854c, rename only, no bug). The store line and
  `test_default_preset_is_h265_mkv_1080p` both come from f11a3fa (decision 0024), and the
  builtin test is its guard. Line 81 was last changed by Q-6.11 (MOD-06).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `test_values_come_from_handbrake[h265-mkv-1080p]` reads row `libx265 22 slow main10 - 10 1920x1080 -:variable mkv …` and asserts encoder, container and `FitWithin(1920, 1080)` (`test_builtin.py:388-413`); `test_default_preset_is_h265_mkv_1080p` asserts `DEFAULT_BUILTIN_ID == "h265-mkv-1080p"` and the name "H.265 MKV 1080p" (the HandBrake table's name column is `_handbrake_name`, not asserted, so the name check must stay in the default test, which it does). `test_store.py:203` is the same constant check. `test_builtin.py:81` compares `builtin_presets()` with `IDS` built from `builtin_presets()` at import: a tautology. No doc names the three tests (`test_default_preset` greps only as a prefix of the kept test). 7 code lines, 0 tests. Tier A stands.
Checked: read both tests side by side; `grep -rn` of the three names in docs/, testdata/README.md, CLAUDE.md → none.

Orchestrator: Tier A, package Q-7.4.

## Looked at and kept

- `definitions/test_tools.py` (all 102), `definitions/test_options_values.py::test_every_enum_and_bool_value_encodes`: real-FFmpeg oracle tests behind `testdata/README.md`. Their coverage groups (47, 18, 13, 12 tests with the same 71-75 lines) are subprocess artefacts.
- `definitions/test_tools.py::test_a_bad_params_entry_does_not_fail_the_encode` vs `presets/test_builtin.py::test_a_bad_parameter_key_is_only_a_warning`: the same 3 encoders, the same `bogus=1` behaviour (exit 0 plus a warning). Each is the positive control of its own file's detector (`_PARAM_ERRORS`, which many `test_tools` tests rely on with `_param_error(...) is None`, and `BAD_PARAM`, used by `test_handbrake_parameter_strings_work_in_ffmpeg`). Decision 0015:32 names the second. Kept both. (After TDM-03 the detectors still differ.)
- `definitions/test_options_values.py::_REFUSED`: it has no positive control (no test shows that it catches a refused value). This is a gap, not a redundancy.
- `definitions/test_tools.py::test_recorded_cross_option_rules`: its 3 x265 lookahead/bframes rows are also rows of `validation/test_x26x_ffmpeg.py::test_x265_lookahead_rule_matches_x265`. Its x264 trellis rows pin the exact SEI `subme` 9/10, the x265 `ref` rule and the SVT lookahead texts, which nothing else pins. README names it.
- `definitions/test_tools.py::test_software_rate_control_encodes` quality min/default/max vs `test_quality_range_ends_are_honoured`: the second encodes the same points but does not check `_param_error`. Decision 0010:114 names the second.
- `definitions/test_tools.py::test_every_software_choice_encodes` x264/x265 `presets=*@8` jobs vs `test_per_preset_defaults_match_the_library`: the same encodes, but they are a slice inside a pooled job list. Taking them out would save about 1 s CPU and add code.
- `definitions/test_models.py::test_av1_nvenc_initial_qps_are_on_the_qindex_scale` vs `test_tools.py::test_nvenc_initial_qps_span_the_build_range[av1_nvenc]` (same 9 lines): the first pins exact values (134/126/142), and the second skips without `av1_nvenc` in the build.
- `definitions/test_lint.py` parametrizations (`test_inconsistent_ranges_are_reported` 5, `test_presets_not_fastest_first_are_reported` 4) and `test_options_search_hdr.py::test_an_option_that_writes_what_something_else_writes` (6): each case asserts a different message or speed scale. The linter is in `testing/`, outside the coverage measurement, so "1 distinct set" means nothing here.
- `definitions/test_lint.py::test_every_option_has_help_and_a_mapping`: could merge with the category half of the moved category test, but trim P kept it as the literal "Done when" statement.
- `definitions/test_snap.py`, `test_quality_support_loader.py` (`test_defaults_sit_on_the_conversion_scale` 16, `test_quality_zero_is_not_offered…` 5): already trimmed by P. Each case checks one encoder's data.
- `definitions/test_quality_support_loader.py::test_conversion_is_monotonic_and_in_range` (property) vs the example tests: the property only checks bounds and order. The examples pin exact values (27, 25, 24, 35, 1, 255).
- `models/test_schema.py` (223 snapshots, 83 `$defs` checks): snapshot guard. The `$defs` check guards against context-dependent inlined schemas.
- `models/test_roundtrip.py::test_model_round_trip` (153) and `test_alias_round_trip` (14): C-2 "Done when", already trimmed by M. Groups with the same lines (`HeaderEdit`/`TrackHeaderEdit`, `Preset`/`PresetFile`/`JobTemplate`, …) are different models with different strategies.
- `models/test_json_text.py::test_display_text_never_holds_a_lone_surrogate` (13 in one group): each case pins that one model's fields use `DisplayText`.
- `models/test_models.py::test_media_source_keeps_unknown_fields`: as a 4th case of `test_unknown_fields_are_kept` it would add the `load_document` path but no saved lines (the body becomes a helper). It is a persistence guard.
- `models/test_models.py::test_unknown_fields_are_kept[settings|job_settings]` (same 12 lines): different documents, a persistence guard.
- `models/test_models.py` migration tests and `test_settings_2_*`, `test_media_source_2_*`: migration guards (MOD-09 kept the last one).
- `presets/test_builtin.py::test_values_come_from_handbrake` (26): HandBrake table. Kept out of TDM-01.
- `presets/test_builtin.py::test_every_preset_is_built_in_valid_and_ends_with_the_catch_all`: its `is_catch_all` line is enforced by the `AudioDefaults` validator (always true), but the test name states it. 1 line, not worth it.
- `presets/test_builtin.py::test_handbrake_parameter_strings_work_in_ffmpeg` vs `test_the_encoder_gets_handbrakes_settings`: no warnings vs the same SEI. Different asserts. Decision 0015 names the first.
- `presets/test_store.py::test_export_import_gives_the_same_result` vs `test_export_import_round_trip_property`: the property does not check re-reading from disk, the re-export, or `renamed`/`skipped`. The example is the C-9 "Done when" ("export → import gives the same result").
- `presets/test_store.py` subset pairs (`test_save_updates_by_id` ⊂ `test_a_failed_write_changes_nothing`, the `create_*` pair, …): different asserts. Many come from the 8bd8e52 M2 review fixes.
- `presets/test_diff.py::test_unchanged_template_has_no_changes`/`test_identity_fields_…` vs the property `test_diff_is_empty_exactly_when_the_templates_are_equal`: the examples also check `diff(preset, preset)`, identity fields and unknown fields, and the property does not.
- `test_settings.py`: deep-file `[100|600|100000]`, too-deep save `[100|400]` (trim Q kept them as M2-review boundaries), damaged contents `[NaN|99]` (different input classes). All are store guards (C-9 "Done when", Q-6.11).
- `test_service_settings.py`: the facade tests cover the store lines (for example `test_a_newer_settings_file_is_not_overwritten` ⊇ the store's newer test), but they assert the facade's own results (session value, `result.warnings`, events, rescans). `test_a_deeply_nested_settings_file_does_not_stop_the_app` is the 8bd8e52 fix ("Reframe.__init__ no longer raises RecursionError"). `test_a_too_deep_settings_value_is_an_issue[100|1000]`: 1000 is past the recursion limit.
- `test_jsonpatch.py`: RFC 6901/6902 example tables (conformance). `test_errors`/`test_more_operations` were trimmed by Q. `test_invalid_pointers` `/~2` vs `/~a` take the same regex but are different characters (1 line, kept).

## Speed notes

- `test_settings.py::test_too_deep_counts_levels_without_recursion` (1.18 s): `nested(1_000_000)`. `nested(100_000)` is still 100 times the recursion limit and keeps the "without recursion" guarantee. Saves about 1 s.
- `models/test_roundtrip.py::test_model_round_trip` (23 s for 153 cases, `max_examples=25`; `PresetFile` alone 3.3 s): the large container models (`PresetFile`, `QueueJob`, `JobSettings`) take most of it. A lower `max_examples` for them would save several seconds, but it weakens the C-2 property, so the owner must decide.

## Verifier notes

- TDM-01 alternative that keeps per-check failure reports: pytest 9.1.1 (the locked version)
  has a built-in `subtests` fixture; the merged test could run each of the five checks as a
  subtest and report every failing check of a preset in one run. Not tried; it adds lines.
- TDM-01: the old integration test was the only one of the five that caught a template
  error outside the definition checks (naming, tags, custom PAR, cross-option rules, custom
  params). The merged test keeps that because it calls `validate_template` after the
  definition asserts. But it calls it only when the definition asserts pass: a preset with a
  definition defect hides its validation errors until that defect is fixed.
- TDM-01: the audio mutation shows that the old integration test alone missed an out-of-range
  AAC bit rate (lint gives only INFO `defaults.bitrate_snapped`, no error); the batch test and the
  audio definition check caught it. With the `defaults.` clause the merged test catches it
  twice. The "smaller fallback" (only the clause in the integration test) is also safe.
- `definitions/test_options_values.py::_written` (lines 43-46) is dead code: delete it (4 code
  lines, Tier A) even if TDM-03 is not done.
- Setup note: `testdata/media` is the shared symlink from the brief's step 3; it shows as
  untracked in `git status` because `.gitignore` matches the directory form only. No tracked
  file is changed.
