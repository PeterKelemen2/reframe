# naming-definitions: simplification findings

Commit: 85d9dcb. Scope: `packages/reframe/src/reframe/naming/`, `definitions/`, `analysis/`, `preview/` and their tests (`packages/reframe/tests/naming/`, `definitions/`, `analysis/`, `preview/`). Source lines: naming 1758, definitions 1917, analysis 816, preview 1046 (code lines from sizes.txt). Read in full: `definitions/__init__.py`, `models.py`, `loader.py`, `options.py`, `quality.py`, `support.py`, `search.py`, `hdr.py`, `lint.py`, `custom_params.py`; `naming/__init__.py`, `fs.py`, `clean.py`, `value.py`, `variables.py`, `resolve.py`, `source.py`, `template.py`, `sanitize.py`, `context.py`, `parse.py`; `analysis/__init__.py`, `common.py`, `loudness.py`, `bitrate.py`, `subtitles.py`, `subtitlefile.py`; `preview/__init__.py`, `common.py`, `cache.py`, `graph.py`, `crop.py`, `frames.py`, `clip.py`. Only skimmed: the data TOML files, `definitions/test_tools.py` (function names only), and the tests of the four packages (read only where a finding touches them).
Verified: 2026-11-15, 4 confirmed, 7 adjusted, 0 rejected.

## Summary

This area is mostly as large as decisions 0010, 0012, 0032, 0033 and 0035 make it. The guessit workarounds, the byte-limit rules, the format-spec limits, the library-exact custom-parameter parser, the PGS reader, two frames per run and the cache rules all trace to a record, and they stay (see "Looked at and kept"). The waste is elsewhere. First, `definitions/__init__.py` and `definitions/models.py` list the same 53 to 58 names three times, and 22 of those re-exports have no importer. Second, `definitions/lint.py` (669 code lines, 35 % of `definitions/`) has no caller outside tests, yet it ships in the product package. Third, about 20 small things have no production caller: constants, a validator, a model method, three parameters, one shipped model field that only a test reads, and one field (`VideoEncoderDef.hardware`) that the linter forces to equal `family != "software"`. Fourth, the analysis and preview tests copy the same fixtures and helpers, and the analysis tasks repeat a nine-line "run the tool, check the result" block five times. Several long functions (`parse_name`, `_job_values`, `resolve_output_name`, `make_frames`, `make_clip`) are long because they do many steps in a row, not because of the records. No `decision-change` finding: nothing here needs a decision to change. Three cross-area duplicates found here are already written up by other agents (CMD-01, CMD-03, VAL-07); they are listed under "Looked at and kept", not repeated.

Estimated total (after verify): about -180 Python source lines (plus -17 TOML lines; 669 more lines move out of the shipped package) and about -73 test lines.

## Findings

### NDP-01: `definitions/__init__.py` and `models.py` list the same names three times
- Kind: duplication
- Where: `packages/reframe/src/reframe/definitions/__init__.py:10-56` (45 names imported from `.models`), `:68-127` (`__all__`, 58 names); `packages/reframe/src/reframe/definitions/models.py:21-75` (`__all__`, 53 names). Pylint's duplicate block (`duplication.txt`) is `__init__:[73:99]` against `models:[31:57]`.
- Now: the package `__init__` re-exports 45 model names, and `models.py` lists its own public names again in `__all__`. Facts, from an AST count over `packages/`, `scripts/` and `testing/`:
  - 22 of the 45 re-exported model names have 0 importers from `reframe.definitions`: `AudioCodec`, `AudioQualityDef`, `BitrateMode`, `Choice`, `EncoderDefault`, `EncoderFamily`, `FastDecodeDef`, `FfmpegArg`, `FilterHelp`, `FilterId`, `FilterPreset`, `FilterTune`, `MixdownDef`, `OptionDefault`, `PassthruCodecDef`, `PrivateOpt`, `QualityBand`, `TrackFlag`, `TrackFlagDef`, `TwoPassDef`, `Vendor`, `VideoCodec`.
  - 10 more are imported only by tests: `AudioBitrateDef`, `BitrateLimits`, `DerivedValue`, `FixedDefault`, `HardwareSetup`, `QualityMode`, `RateControlDef`, `X26xParam`, `OPTION_CATEGORIES`, `lint_definitions`.
  - Importers mix both styles already: `Definitions` is imported 46 times from the package and 4 times from `.models`; `TRACK_FLAGS` 6 times from `.models` (it is not re-exported).
  - `models.__all__` has no star-importer (`grep "import \*"` finds none) and nobody reads `definitions.models.__all__` (the `models.__all__` readers in tests are `reframe.models`). Every name that any file imports from `reframe.definitions.models` (60 import sites) is defined in `models.py`, so mypy's no-implicit-re-export rule does not need the list there.
  - `docs/plan/05-core.md:11` says the public API is the `Reframe` facade and `reframe.models`; everything else is internal.
- Change:
  - In `definitions/__init__.py`, delete the 22 names above from the `from reframe.definitions.models import (...)` block and from `__all__` (-44 lines). Keep the rest.
  - In `definitions/models.py`, delete the whole `__all__` block (lines 21-75, -55 lines). 196 of 229 modules have an `__all__`, so a one-line comment is not needed: names that a module defines are always public.
  - Optional, same shape, -20 more lines: change the 11 test imports of the 10 tests-only names to `reframe.definitions.models` and drop them from `__init__` too.
- Behaviour: unchanged.
- Contracts touched: none (internal module; not part of the public API per 05-core).
- Callers to update: none for the 22 names (0 importers). Run `uv run mypy`, `uv run mypy --platform win32` and `uv run ruff check`; if mypy complains about a re-export, add that name back.
- Tests: none change.
- Decision records: none apply.
- Size: S; estimated lines: -99 / -0
- Risk: low. Only a mypy or ruff complaint can show up, and it is visible at once.
- Depends on: none (if NDP-03 or NDP-04 run first, the names they remove are one line fewer each).
- Confidence: high
- Verdict: CONFIRMED
- Orchestrator: Tier A, work package Q-6.4 (see ../plan.md).

### NDP-02: `definitions/lint.py` is test-only code in the shipped package
- Kind: layering
- Where: `packages/reframe/src/reframe/definitions/lint.py` (whole file, 669 code lines, 761 raw); `definitions/__init__.py:8` (import) and `:118` (`"lint_definitions"` in `__all__`); `definitions/models.py:242` (`CONDITION_FIELDS`, used only by the linter); tests: `packages/reframe/tests/definitions/test_lint.py:10` and `test_options_search_hdr.py:19` (the two importers).
- Now: `lint_definitions` has 0 callers outside tests. I grepped the whole repository (packages, `scripts/`, `testing/`, `desktop/`, `frontend/`, `.github/`, docs): only the two test files call it, and the docs name it. The plan asks for "a definitions linter **test**" (`docs/plan/05-core.md:319`, "Done when"), and no CLI, server route or startup path runs it. It is imported by `reframe.definitions.__init__` on every start (cost 0.36 ms with a warm bytecode cache, measured with `-X importtime`: not a speed problem). It is the largest file of the package: 35 % of the `definitions/` code, and 16 of the 17 `definitions/` entries in `complexity.txt` (C901 / PLR0912 / PLR0911 on `_lint_video`, `_lint_quality`, `_lint_audio_encoder`, …). Those flat check lists are fine in a test helper, but they count as product complexity.
- Change: move the file to the shared test package: `git mv packages/reframe/src/reframe/definitions/lint.py testing/reframe_testing/definitions_lint.py`. Move `CONDITION_FIELDS` from `models.py:242` into it (its only user). In the moved file the imports stay `from reframe.definitions.models import ...`. Delete the import and the `__all__` entry from `definitions/__init__.py`. The two tests change their import to `from reframe_testing.definitions_lint import lint_definitions`. `testing/` is already on mypy's `files` and ruff's `src`. Update the `lint_definitions` mention in the `docs/status.md` C-6 row ("`lint_definitions`" becomes "the definitions linter test helper"). The `ConditionField` docstring at `models.py:240-241` names `CONDITION_FIELDS`: reword it when the constant moves (NDP-03 item 2 moves that docstring under `Condition.field`). `pyproject.toml` has no per-file ruff ignore for `lint.py`, so nothing there changes.
- Behaviour: unchanged. The same checks run in the same tests.
- Contracts touched: none (not part of the public API; not exported to the server).
- Callers to update: `definitions/__init__.py`, `tests/definitions/test_lint.py`, `tests/definitions/test_options_search_hdr.py`, `docs/status.md`.
- Tests: unchanged; they are the guard (`test_lint.py` has 384 code lines of broken-data cases).
- Decision records: 0010 (follow-up item 6: the linter checks preset order and placeholders) stays: the checks stay, only the file moves. Plan 05 C-6 "Done when" asks for a linter test, which this keeps.
- Size: S; estimated lines: -1 net source (669 code lines leave the shipped package and become test infrastructure) / +0
- Risk: low. A missed import shows up at collection time.
- Depends on: none (NDP-08 edits the same file; do it after, in its new place).
- Confidence: high
- Verdict: CONFIRMED (no decision or CI step needs the linter outside tests: 0010 only says what it checks, plan C-6 asks for a linter test, the module docstring says "A test keeps the packaged data clean"; no script, workflow, CLI or server path calls it)
- Orchestrator: Tier A, work package Q-6.4 (see ../plan.md).

### NDP-03: Names and parameters with no production caller (no contract change)
- Kind: dead-code
- Where and now (each is "callers outside its own file and tests"):
  1. `definitions/models.py:126` `BITRATE_PLACEHOLDER = "{kbps}"` (and its `__all__` entry `:22`): 0 callers anywhere (src, tests, scripts, frontend).
  2. `definitions/models.py:239-241` `ConditionField = str` alias, used once at `:248` (`field: ConditionField`). The docstring that follows it explains the field.
  3. `definitions/models.py:206-208` `ChoiceSetting.default_for(bit_depth)`: 0 src callers; the only calls are `tests/definitions/test_models.py:70-71`. The frontend does the same lookup itself (`frontend/src/components/editor/tabs/VideoTab.vue:205`). The field `default_by_depth` stays (the TOML, the linter and the frontend use it).
  4. `definitions/support.py:28-32` `supported_options(encoder, status)` and its re-export (`definitions/__init__.py:66` import, `:124` `__all__`): 0 src callers (the builder `command/video.py` and validation call `mapping_supported` directly). Tests: `tests/definitions/test_quality_support_loader.py:14` (import), `:112,113,119,130,131` (five calls), and the module docstring at `:1`. `docs/decisions/0008-encoder-detection-reasons-and-filters.md:203` names `supported_options()` as a C-6 requirement (an empty `private_options` list means "not known"); that behaviour lives in `mapping_supported` and stays, the record is history and is left alone.
  5. `naming/variables.py:79-81` `NAME_TEXT_VARIABLES` (and `__all__` `:12`): 0 callers anywhere (the code decides this in `naming/context.py` with its own `text()` helper).
  6. `naming/variables.py:76` `HANDBRAKE_VARIABLES`: only `tests/naming/test_variables.py:38,74`.
  7. `naming/resolve.py:46` `OVERRIDE_FIELDS = _TEXT_OVERRIDES + _NUMBER_OVERRIDES`, exported at `resolve.py:33` and `naming/__init__.py:6,12`: 0 callers in Python (the two tuples it joins are used by `apply_overrides`). The frontend keeps its own list in `frontend/src/components/naming/fields.ts:2`.
  8. `title_index`: `naming/resolve.py:174,223` (`resolve_output_name(title_index=1)`) and `naming/context.py:118,161` (`NameContext.title_index`, `values["title"]`). The 3 production callers (`jobs.py:452`, `jobs.py:768`, `validation/context.py:101`) never pass it; one test does (`tests/naming/test_variables.py:106`, `title_index=3`). The plan says `{title}` is "Title number (disc input, post-v1), or the file's index" (`docs/plan/03-features.md:611`), so it is always 1 until disc input exists.
  9. `preview/graph.py:120,146` `job_video_graph(..., tail=)`: no caller passes `tail` (1 src call at `graph.py:166`, 5 test calls in `tests/preview/test_graph.py`).
  10. `definitions/models.py:479-484` `AudioBitrateDef.values`: 0 src callers; 3 test files call it (`tests/definitions/test_models.py:95,100,101,104`, `tests/presets/test_builtin.py:214`, `tests/definitions/test_tools.py:1223`). Optional: it costs 3 test edits for 4 lines, so only do it if the others are done.
- Change:
  1. Delete the constant and its `__all__` line.
  2. Replace `field: ConditionField` by `field: str`; delete the alias line and move its docstring under the field. The docstring names `CONDITION_FIELDS`; if NDP-02 runs, that constant has moved to the linter, so reword it to "a rule field such as `rate_control`, or `option:<key>` for another option of the same encoder".
  3. Delete `default_for`; delete the 2 assert lines in `test_choice_setting_helpers`.
  4. Delete `supported_options` and its import and `__all__` entry in `definitions/__init__.py`. In `test_quality_support_loader.py` add a local helper `def supported_options(encoder, status): return [o for o in encoder.options if mapping_supported(encoder, o.mapping, status)]` so the tests (5 calls) stay as they are, and drop `supported_options` from the import at `:14` and the docstring at `:1`. Update the C-6 row of `docs/status.md` (it names `supported_options`) and leave `docs/m2-breakdown.md` alone (history).
  5. Delete `NAME_TEXT_VARIABLES` and its `__all__` entry.
  6. Delete `HANDBRAKE_VARIABLES`; in the test use `tuple(v.name for v in VARIABLES if v.group == "handbrake")`.
  7. Delete `OVERRIDE_FIELDS` from `resolve.py` (`__all__` and line 46) and from `naming/__init__.py`.
  8. Delete the parameter and the field; `values["title"] = 1`. The test line becomes `assert render("{title:02}") == "01"`.
  9. Delete `tail` and use `tail=[f"format={pix_fmt}"]`.
  10. Optional: delete `values` and give the 3 tests a local expression.
- Behaviour: unchanged (no production caller used any of these).
- Contracts touched: none (all internal; `OVERRIDE_FIELDS` and `supported_options` are in `__all__` of internal packages only).
- Callers to update: the test files named above and `docs/status.md`.
- Tests: change `test_models.py` (2 lines), `test_quality_support_loader.py` (+3 lines helper), `test_variables.py` (2 lines); nothing else.
- Decision records: none require these. 0008 line 203 names `supported_options()` (item 4; the behaviour stays in `mapping_supported`). `docs/plan/03-features.md:611` says `{title}` is "Title number (disc input, post-v1), or the file's index" (item 8): it stays true (the file's index is 1); the parameter is the hook for post-v1 disc input and comes back with it.
- Size: S; estimated lines: -26 / -4
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (item 4: the tests call `supported_options` five times, lines 112,113,119,130,131, plus the docstring at line 1, and decision 0008:203 names it; item 2: the docstring names `CONDITION_FIELDS`, which NDP-02 moves; item 8: plan row 03:611 named; every other item re-checked with a repository-wide search and holds)
- Orchestrator: Tier A, work package Q-6.4 (see ../plan.md).
- Note (Q-6.4): item 2 moved a comment into the docstring of `Condition.field`; `Condition` is in the API, so the OpenAPI description of that field and `frontend/src/api/schema.d.ts` changed (descriptions only; D-28, review RA-1).

### NDP-04: Three shipped model fields that are derived or never read (OpenAPI touched)
- Kind: model-redundancy
- Where: `definitions/models.py:413` `VideoEncoderDef.hardware`, `:644` `ContainerDef.default_always_set`, `:727` `FilterDef.position` with `:786-791` `Definitions._filter_positions` and `:793-794` `Definitions.ordered_filters`; `definitions/data/video_encoders.toml` (16 `hardware = ...` lines, one per encoder table), `definitions/data/containers.toml:70`; `definitions/lint.py:85-86`; `capabilities/cache.py:75`; `tests/definitions/test_contract.py:32,44`.
- Now:
  - `hardware`: the linter forces `hardware == (family != "software")` (`lint.py:85-86`), so it is a stored copy of a derived value. Readers: `validation/video.py:1251`, `capabilities/detect.py:125,285,342`, and `capabilities/cache.py:75` (`model_dump(include={"id", "hardware", ...})` for the capability-cache fingerprint); `definitions/lint.py:120,137,152` read it too, and so do tests (`tests/capabilities/test_issues.py:75-79`, `test_real.py:33`, `tests/jobs/conftest.py:81`, `tests/validation/scenario.py:226-227`): all reads, so they work with a property. No code sets it except the TOML. `ReframeModel` is `extra="forbid"`, so after the change any raw data that still has `hardware` fails to validate: the 16 TOML lines, `test_lint.py:161` and `test_contract.py:32` must go in the same commit. The frontend does not read it from the definitions (its `hardware` is `EncoderStatus.hardware`, a different model).
  - `default_always_set`: 0 readers in `packages/*/src` and in the frontend (only fixtures at `frontend/src/components/tracks/testing.ts:416,457,485`). The only reader is `tests/definitions/test_tools.py:1704`, which compares it with the real MP4 muxer.
  - `position` (default 0, set by a validator): 0 readers in `packages/*/src` and in the frontend; the only readers are `ordered_filters` (itself 0 src callers, test only at `test_models.py:148-149`). The frontend orders filters by `filter_order` (`frontend/src/components/summary/filters.ts:26`, `filters/filters.ts:16`).
  - All three are in the OpenAPI schema (`Definitions` is served whole at `GET /api/definitions`): `frontend/src/api/schema.d.ts:3885-3898` (`FilterDef`, `position` at `:3898`), `:2981` (`default_always_set`), `:7689` (`hardware`).
- Change:
  - `hardware`: replace the field by `@computed_field` on a property `hardware -> bool: return self.family != "software"` (import `computed_field` from pydantic; checked: the repo's mypy config reports `Decorators on top of @property are not supported  [prop-decorator]` for this pair, so the `@property` line needs `# type: ignore[prop-decorator]`), delete the 16 TOML lines and the linter check `lint.py:85-86` and its assert in `test_lint.py:161,168` (`:161` is `enc["hardware"] = True`, which must go: the model would now reject it). In `test_contract.py` delete the `"hardware": False,` line at `:32` (the test still fails on `typo_field`) and the assert at `:44` (`encoder.hardware == (encoder.family != "software")` becomes a tautology). A computed field stays in `model_dump` (checked: `model_dump(include={"hardware"})` returns it) and in the response schema (as `readOnly`, so `schema.d.ts` gets `readonly hardware: boolean`), so the capability fingerprint (`cache.py:75`) and the API keep `hardware`; check with a one-liner that `definitions_fingerprint(load_definitions())` is the same before and after (if it is not, the capability cache is read as stale once and detection runs again: harmless but say so in the commit).
  - `default_always_set`: delete the field and the TOML line; in `test_tools.py:1704` assert `bool(first) == (container == "mp4")`.
  - `position`: delete the field, `_filter_positions`, `ordered_filters`, and the `model_validator` import (`models.py:15` becomes `from pydantic import Field`); delete `test_models.py:148-149`.
  - Run `scripts/gen-api.sh` and commit `frontend/src/api/schema.d.ts`; remove `default_always_set` from `frontend/src/components/tracks/testing.ts` (3 lines). `frontend/src/components/video/testing/definitions.json` has no `position` or `default_always_set` keys and keeps its `hardware` keys (extra keys in a JSON import do not break the type check).
- Behaviour: unchanged for users. The HTTP API response loses `default_always_set` and `position` (no client reads them) and keeps `hardware`.
- Contracts touched: HTTP/OpenAPI (frontend: regenerate `schema.d.ts`, edit `tracks/testing.ts`); persisted schema: none (definitions are package data, not user documents).
- Callers to update: as listed under Where; none for the removed fields (0 readers).
- Tests: delete `test_models.py:148-149` and the `hardware` lines of `test_lint.py:161,168`; delete `test_contract.py:32` and `:44`; change `test_tools.py:1704`.
- Decision records: none apply. (`FilterPreset.handbrake` is required by 0010 §3 and stays.)
- Size: S; estimated lines: -14 Python source (+4 for the property), -17 TOML (16 `hardware` + 1 `default_always_set`) / -10 tests, -3 frontend
- Risk: low. A stale `schema.d.ts` fails the `gen-api.sh --check` CI step, so it cannot be forgotten.
- Depends on: none (the `lint.py` edit is easier after NDP-02, in the new file).
- Confidence: medium (high for `position` and `default_always_set`; medium for `hardware` because of the OpenAPI shape of a computed field and the fingerprint check)
- Verdict: ADJUSTED (the `hardware` change also needs `test_contract.py:32,44`, a `# type: ignore[prop-decorator]` under the repo's mypy, and the extra-forbid note; TOML lines are 17, not 18; `schema.d.ts` `position` is at `:3898`; the three fields themselves have no reader in src or frontend as stated, and the computed field keeps `hardware` in the served JSON, in `model_dump(include=...)` and in the schema as `readOnly`, checked with a scratch model)
- Orchestrator: Tier B, work package Q-6.19 (see ../plan.md).

### NDP-05: Test fixtures and helpers copied between the analysis, preview and naming tests
- Kind: tests
- Where:
  - The `app` fixture (`Reframe.create(tmp/config, tmp/data, cache_dir=tmp/cache)`, yield, `close()`): `tests/analysis/test_analysis_facade.py:31-39`, `tests/analysis/test_analysis_ffmpeg.py:32-40` (identical text), `tests/preview/test_facade.py:21-28`. `tests/analysis/test_analysis_cancel.py:60-73` has the same first lines plus a probe. Cross-area: 6 more copies in `tests/test_mediatask.py:152`, `tests/validation/test_options_facade.py:24`, `tests/validation/test_dryrun_ffmpeg.py:162`, `tests/validation/test_custom_params_cqm.py:132`, `tests/batch/test_batch_service.py:51`, `tests/batch/test_file_identity.py:195`.
  - Identical helper bodies in `test_analysis_facade.py` and `test_analysis_ffmpeg.py`: `_finish` (`:42-46`, `:43-47`), `_copy` (`:48-52`, `:49-53`), `_ffmpeg` (`:55-60`, `:196-201`).
  - Three fake `NamingFs` classes: `tests/naming/conftest.py:17-38` (`FakeFs`, the general one), `tests/naming/test_variables.py:44-52` (`_Fs`: the same file times for every file), `tests/batch/test_anime_season.py:52-60` (`SeasonFs`: the same folder listing for every folder).
- Now: each copy is 5 to 10 lines, and the facade-level tests have to repeat the three-argument `Reframe.create` call to get a core.
- Change:
  - Add an async fixture `app` to `testing/reframe_testing/pytest_plugin.py` (the plugin loads for every test; a module that defines its own `app` overrides it, so server and other tests are not touched). Import `Reframe` inside the fixture, as the plugin's other fixtures do (the plugin imports `reframe` only under `TYPE_CHECKING`, so `reframe` is not imported before coverage starts). Delete the copies in the 3 files above. `test_analysis_cancel.py` keeps its own (it probes first) or uses the plugin's `app` and adds the probe in the test.
  - Add `run_ffmpeg(cwd, *args)` to `testing/reframe_testing/media.py` (next to `find_ffmpeg`) and `copy_fixture(fixture_media, name, tmp_path)`; add `finish(app, info)` as a fixture or a small function in `reframe_testing`. Use them in the two analysis files.
  - Move `FakeFs` from `tests/naming/conftest.py` into `testing/reframe_testing/naming.py` (`from reframe.naming import FileTimes` is fine there), import it in `conftest.py`, and replace `_Fs(times)` by `FakeFs(times={FILE: times})` and `SeasonFs(sources)` by `FakeFs({folder: names})`.
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the files listed under Where. The six cross-area `app` copies can use the same fixture later (not counted here).
- Tests: all stay; only helpers move.
- Decision records: 0004 (shared test infrastructure lives in `testing/reframe_testing`) is followed.
- Size: M; estimated lines: -0 source / -60 tests (about -45 in the analysis and preview tests, -15 for the fake file systems)
- Risk: low. A fixture named `app` in the plugin must not clash with a test that expects no such fixture; check with `uv run pytest --collect-only -q`.
- Depends on: none
- Confidence: medium (the line count depends on how many of the six cross-area copies the next session also converts)
- Verdict: CONFIRMED (anchors and the three fake-file-system classes checked; `SeasonFs` sources all sit in one folder per season, so `FakeFs({folder: names})` is equivalent; no `app` fixture exists in the plugin or in a `conftest.py` today)
- Orchestrator: Tier A, work package Q-6.2 (see ../plan.md).
- Q-6.2 note: `SeasonFs` in `tests/batch/test_anime_season.py` was left as it is, because Q-6.1 edits `tests/batch/` at the same time; replace it after Q-6.1 is merged.

### NDP-06: The analysis tasks repeat the "run the tool, check the result" block five times
- Kind: duplication
- Where: `analysis/bitrate.py:167-175` (`scan`), `analysis/loudness.py:118-126` (`scan`), `analysis/subtitles.py:258-263` (`_count_packets`), `:302-307` (`_read_pgs`), `:333-338` (`_count_forced`); new helper in `analysis/common.py` after `check_run` (`:76-91`).
- Now: each site does `assert tool.path is not None`, then `await run_streaming(argv(str(tool.path), ...), on_stdout_line=..., on_stderr_line=None, cancel=task.cancel, extra_env=tool.env or None)`, then `check_run(result, "<tool name>", path)`. Five copies, 36 lines in total. `require_tool` is only called from `analysis/` and `preview/` (7 call sites), and every analysis caller then asserts that the path is not `None`.
- Change: add to `analysis/common.py`
  ```python
  async def run_scan(
      tool: ToolInfo, argv: Callable[[str], list[str]], path: Path, task: TaskContext,
      on_line: Callable[[str], None],
  ) -> RunResult:
      """Run ``tool`` with ``argv(program)``, feed its stdout lines to ``on_line``, and raise
      :class:`TaskFailed` unless it exits cleanly."""
      assert tool.path is not None  # require_tool returns found tools only
      result = await run_streaming(
          argv(str(tool.path)), on_stdout_line=on_line, on_stderr_line=None,
          cancel=task.cancel, extra_env=tool.env or None,
      )
      check_run(result, tool.name, path)
      return result
  ```
  and call it as `result = await run_scan(ffprobe, lambda program: scan_argv(program, path, stream_index), path, task, on_line)`. After the change `run_streaming` and `check_run` are no longer used in `bitrate.py`, `loudness.py` and `subtitles.py` (remove the imports; `subtitles.py` keeps `CancelToken`). The `*_argv` functions keep their signatures (the parser tests call them with a plain string). `loudness.scan` still reads `result.stderr_text`. `ToolInfo.name` is `"ffmpeg"` or `"ffprobe"`, the same text the sites pass now. (The three `preview/` runs use `run`, not `run_streaming`, with a timeout and a different failure text, so they stay as they are.)
- Behaviour: unchanged (same argv, same environment, same failure messages).
- Contracts touched: none.
- Callers to update: `analysis/bitrate.py`, `analysis/loudness.py`, `analysis/subtitles.py`.
- Tests: one change. `tests/analysis/test_analysis_tasks.py:475-476` (`test_the_scans_run_their_tools_with_the_tool_environment`) patches `reframe.analysis.{bitrate,subtitles,loudness}.run_streaming` in a loop; after the change that name no longer exists in those modules (`monkeypatch.setattr` raises), so replace the loop by one `monkeypatch.setattr("reframe.analysis.common.run_streaming", spy)`. That test and `test_a_failing_ffprobe_fails_the_scan` (`:334`) then guard the behaviour; `test_analysis_parsers.py::test_check_run` calls `common.check_run` and is untouched.
- Decision records: 0032 (the scans run through `run_streaming` with the task's cancel token) is kept.
- Size: S; estimated lines: -10 / -1
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED ("Tests: none change" was wrong: `test_analysis_tasks.py:475-476` patches `run_streaming` per module and must patch `reframe.analysis.common.run_streaming` once; estimate -10, not -14, once the helper's ~15 lines and the import changes are counted; the five sites, `ToolInfo.name` being the `Literal["ffmpeg", "ffprobe"]` text and `require_tool` returning only found tools are right)
- Orchestrator: Tier A, work package Q-6.4 (see ../plan.md).

### NDP-07: The loudnorm measurements are stored by two copies of one loop (cross-area: queue)
- Kind: duplication
- Where: `packages/reframe/src/reframe/preview/clip.py:316-329` (`_measure`); `packages/reframe/src/reframe/queue/runner.py:635-657` (`QueueRunner._measure`); new function in `packages/reframe/src/reframe/queue/loudnorm.py` (after `clamp`).
- Now: both do `parse_blocks(stderr)`, compare the count with `len(step.measures)`, `clamp(block)` per block, and write `values[f"{measurement.id}.{key}"]`. The runner also writes a job-log note for clamped values; the clip drops the notes. The two functions differ only in how the failure and the notes are reported. (`preview/clip._run_plan` as a whole is a reduced copy of the runner's step loop; sharing it is not worth the pause, stall and log hooks the runner needs. See "Looked at and kept".)
- Change: in `queue/loudnorm.py` add
  ```python
  def store(measures: Sequence[Measurement], stderr: str, values: dict[str, str]) -> list[str]:
      """Put the measured values in ``values`` as ``<id>.<key>``; the clamp notes. Raises MeasureError."""
      blocks = parse_blocks(stderr)
      if len(blocks) != len(measures):
          raise MeasureError(f"printed {len(blocks)} loudnorm result(s), {len(measures)} expected")
      notes: list[str] = []
      for measurement, block in zip(measures, blocks, strict=True):
          clamped, block_notes = clamp(block)
          values.update({f"{measurement.id}.{key}": value for key, value in clamped.items()})
          notes += [f"Loudness {measurement.id}: silent or nearly silent, values clamped into loudnorm's ranges ({', '.join(block_notes)})"] if block_notes else []
      return notes
  ```
  `runner._measure` becomes `try: notes = loudnorm.store(...) except MeasureError as exc: return f"{_WHAT[step.kind]} failed: {exc}"` plus `joblog.note` per note. `clip._measure` becomes the same without notes.
- Behaviour: changes in wording of one failure message only: the count-mismatch text becomes `"<step> failed: printed 0 loudnorm result(s), 1 expected"` in both the queue job error and the preview-clip error (today both say `"<step> printed 0 loudnorm result(s), 1 expected"`). To keep the old text exactly, raise a `MeasureCountError(MeasureError)` subclass and let the callers format it without "failed:"; that costs 4 more lines.
- Contracts touched: the text of two user-visible errors (the queue job error and the preview-clip task error) changes unless the subclass variant is used; no schema, no issue code, nothing in `frontend/` or the plan matches the text (grep "loudnorm result" finds only the two source lines and the two tests).
- Callers to update: `queue/runner.py`, `preview/clip.py`.
- Tests: change the two asserts of that text: `tests/queue/test_faults.py:213` and `tests/preview/test_clip.py:577` (only if the wording changes). The rest stay as the guard.
- Decision records: 0016 (queue and job runner) and 0033 §6 (the clip runs the plan's loudness steps) are kept.
- Size: S; estimated lines: -1 / -0 (the two copies are 23 + 14 lines and become about 11 + 6; `store` is about 19 lines; with the `MeasureCountError` variant it is about +3). The gain is one place for the loop, not fewer lines.
- Risk: low.
- Depends on: none
- Confidence: low (cross-area: another agent that audits `queue/` may write a finding for `runner._measure`; do the two together, or skip: the net size is zero)
- Verdict: ADJUSTED (estimate is about -1, not -14; the failure texts of the queue job and of the preview clip are user-visible, so "Contracts touched: none" was wrong; the duplicated loop and the two test asserts at `tests/queue/test_faults.py:213` and `tests/preview/test_clip.py:577` are right; `Measurement` lives in `reframe/models/plan.py`, so `queue/loudnorm.py` can import it)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### NDP-08: Inside the linter: a typed mapping, one mapping-to-target helper, one fallback-chain check, guards for empty tables
- Kind: duplication
- Where: `definitions/lint.py` (or `testing/reframe_testing/definitions_lint.py` after NDP-02): `_lint_mapping` `:301-315` (called at `:297` and `:339`), `_option_target` `:356-365` and the same switch inlined in `_setting_targets` `:386-392`, `_lint_fallback` `:116-143` and `_lint_audio_fallback` `:540-562`, empty-table guards at `:108-111`, `:530`, `:533`, `:582-583`, `:617-618`, `:676-677`; `definitions/loader.py:22-23` (`_read`), `:31-32` (`_option_sets`).
- Now:
  - `_lint_mapping(w, enc, kind: str, mapping: object)` takes the kind and the mapping as two arguments and reads fields with `getattr(mapping, "arg", "")`, though `mapping` is the typed union `OptionMapping` that mypy can narrow on `mapping.kind`.
  - `_setting_targets` repeats the three-way "mapping to target key" switch that `_option_target` already holds (`params:<name>`, `-<name>`, `<arg without :stream>`).
  - `_lint_fallback` and `_lint_audio_fallback` both check "duplicate entries", "contains the encoder itself" and "unknown encoder" with the same code.
  - The linter skips checks when a table is empty (`defs.mixdowns and mixdown not in defs.mixdowns`, `if not containers: return`, `if not defs.filters: return`, `if encoders:`). `Definitions` is never built with empty tables (the loader always fills them; tests mutate the full raw data). With `loader._read` returning `{}` for a missing file, a missing TOML file now loads as an empty table and the linter says nothing about it.
- Change:
  - `_lint_mapping(w, enc, mapping: OptionMapping)`: branch on `mapping.kind` and read `mapping.arg` / `mapping.name` directly (callers pass `setting.mapping` and `opt.mapping`; `_option_target` already narrows `OptionMapping` on `mapping.kind`, so mypy accepts it). About -3 lines.
  - Extract `_mapping_target(mapping) -> str | None` (the body of `_option_target` after `mapping = opt.mapping`, including the `part` rule); `_option_target(opt)` and `_setting_targets` call it. About -4 lines. The `part` rule now also applies to settings' mappings; no shipped preset, tune, profile or level mapping sets `part` (only `options/x264.toml` and `options/x265.toml` do), so nothing changes.
  - Extract `_lint_chain(w, owner_id, chain, known)` for the three shared checks; the video and audio functions keep their own extra checks (video: the codec check; audio: the GPL-build check; the unknown-encoder text differs: "unknown encoder" vs "unknown audio encoder", and `test_lint.py` asserts both). Counted line by line the helper costs what it saves (0 lines): do it only for the single place of the chain rules.
  - Delete the six empty-table guards. Delete `if not data.is_file(): return {}` in `loader._read` and `if not folder.is_dir(): return sets` in `loader._option_sets`: the data is package data, and a missing file should raise, not load as empty. About -11 lines for the six guards and the two loader lines together (no test builds an empty table; `Definitions()` is never linted; `sidecar.spec` bundles the data with `collect_data`).
- Behaviour: unchanged for the shipped data. A missing TOML file now raises `FileNotFoundError` at load instead of loading empty tables.
- Contracts touched: none.
- Callers to update: none outside the two files.
- Tests: `tests/definitions/test_lint.py` stays as the guard (it has a case for each of these checks). `test_quality_support_loader.py` has loader tests (`resolve_video_encoders`) that stay.
- Decision records: 0010 follow-up item 6 is kept (the checks stay).
- Size: S; estimated lines: -18 / -0 (the lines move out of the shipped package if NDP-02 is done first)
- Risk: low.
- Depends on: NDP-02 (where the file lives); not required. NDP-04 deletes `lint.py:85-86`: do the two in either order, they touch different lines.
- Confidence: high for the mapping, target and guard parts; low for `_lint_chain` (no line gain)
- Verdict: ADJUSTED (estimate -18, not -26: `_lint_chain` saves 0 lines, the mapping part about -3, the target part about -4, guards and loader about -11; a missing `part` rule difference noted; all anchors, the empty-table claim and the loader behaviour hold)
- Orchestrator: Tier A, work package Q-6.4 (see ../plan.md).

### NDP-09: `render_value` carries a `root` parameter that nothing passes, and repeats the head of `resolve_output_name`
- Kind: duplication
- Where: `naming/value.py:35-42` (`NoFiles`), `:50-101` (`render_value`: parameters `fs`, `root`); `naming/resolve.py:196-227` (`resolve_output_name`).
- Now: the only production caller of `render_value` is `command/metadata.py:341` (through `command/builder.py:406`); it never passes `fs` or `root`. No test passes `root`; one test passes `fs` (`tests/naming/test_value.py:68`, "file-system reads only with fs"). The builder is pure, so tag values never read the file system. The first 20 lines of `render_value` (choose source, apply overrides, split the extension, build a `NameContext`, call `build_values`) are the same steps as lines 198-227 of `resolve_output_name`, with different defaults (`now`, `definitions`, `title_index`).
- Change:
  - Drop the `root` parameter of `render_value` (signature line, docstring line; `choose_source(file, mode, root=None, fs=reader)`). Keep `fs`: decision 0034 item 9 defines `render_value` as "no file-system reads unless a `NamingFs` is given", and `tests/naming/test_value.py:60-70` tests that. Dropping `fs` and renaming `NoFiles` would change that record (a `decision-change`), and it gains about 6 lines only. `NoFiles` stays as it is.
  - Optional: move `render_value` into `resolve.py` and extract `_values_for(...)` (choose source, overrides, stem, `NameContext`, `build_values`) that both functions call, returning a small frozen dataclass `(choice, fields, issues, notes, values, stem)`. Do this only if the next session wants one place to build the name context; it saves about 8 lines net.
- Behaviour: unchanged for production. (`render_value(root=...)` disappears from the module's API; `reframe.naming.render_value` is not in the public API per 05-core.)
- Contracts touched: none.
- Callers to update: `naming/value.py` only (no caller and no test passes `root`).
- Tests: none change.
- Decision records: 0034 item 9 (`render_value` reads the file system only when a `NamingFs` is given) is why `fs` stays; 0012 (naming reads the file system only through `NamingFs`) and the pure builder rule in `CLAUDE.md` are kept.
- Size: XS; estimated lines: -2 / -0 (the optional dedupe part about -8 more)
- Risk: low.
- Depends on: none
- Confidence: low (the `root` part is about 2 lines; the dataclass part is optional and only worth it for the single place)
- Verdict: ADJUSTED (decision 0034 item 9 specifies `render_value(fs=...)`, so `fs` and its test stay; only `root` can go; estimate -2 / -0, not -12 / -8; the check that no production caller or test passes `fs` or `root` besides `test_value.py:68` holds)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### NDP-10: Long functions that do many steps in a row
- Kind: structure
- Where: `naming/parse.py:278-457` `parse_name` (110 statements, complexity 36); `naming/context.py:200-301` `_job_values` (70 statements, complexity 19); `naming/resolve.py:164-300` `resolve_output_name` (54 statements, 11 parameters); `preview/frames.py:59-176` `make_frames` (81 statements, complexity 26); `preview/clip.py:105-201` `make_clip` (60 statements).
- Now: each is one straight run of steps with local state, so a reader has to hold all of it. No step is dead and the records require the behaviour; this is only about reading and testing the steps one by one.
- Change: split along the steps that already exist in the code. Keep every function private. No behaviour or message may change.
  - `parse_name` into: `_episode_anchor(text, matches)` (the code span and `is_episode`), `_kept_matches(matches, anchor)` (the `kept` set), `_name_fields(...)` (main title, name, sub title for an episode or a movie), `_episode_fields(...)` (code, season, episodes, the absolute-number rule), `_tag_spans(...)` (release tags, HDR tokens), `_score(...)`. Replace the `span()` closure by a small `_Spans` class that holds `text` and the list.
  - `_job_values` into `_chapters_label`, `_size_values`, `_codec_values`, `_hdr_value`, `_audio_values` (each returns a dict that `build_values` merges).
  - `resolve_output_name` into `_template_segments(...)` (manual name or template, with its issues and notes), `_undecodable_note(...)`, `_output_folder(...)`.
  - `make_frames` into `_plan_recipes(...)` (source and output recipes, `same_picture`, notes) and a small `_FrameRun` class that holds `made`, `failures`, the gate and `one(timestamp)`.
  - `make_clip` into `_clip_range(...)` (validate `start`, `seconds`, the end) and `_clip_plan(...)` (validate, plan, id).
- Behaviour: unchanged.
- Contracts touched: none.
- Callers to update: none outside the files.
- Tests: none change. The guards are `tests/naming/test_corpus.py` (the name corpus `testdata/names.toml`), `test_guessit_quirks.py`, `test_parse.py`, `test_resolve.py`, `test_variables.py`, `tests/preview/test_frames.py`, `test_clip.py`, `test_cancel.py`.
- Decision records: 0012 (guessit workarounds; keep each rule as it is), 0033 (two frames per run, the retry with the source frame alone) are kept.
- Size: L; estimated lines: -0 / -0 (the line count stays about the same; only the shape changes)
- Risk: medium for `parse_name` (36 branches that the corpus test exercises); low for the others.
- Depends on: none
- Confidence: low (value is readability only; do it last, or not at all)
- Verdict: CONFIRMED (anchors and the complexity numbers match `complexity.txt`; no record requires the single-function shape; it is a readability change with no line gain, as stated)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### NDP-11: Small leftovers
- Kind: defensive
- Where and now:
  1. `naming/template.py:127` `@lru_cache(maxsize=512)` on `parse_template`, with the import at `:19`: one parse of a 70-character template takes 10 µs (measured with `parse_template.__wrapped__`), and the four callers (`resolve.py:256`, `value.py:71`, `batch/metadata.py:65`, `template.py:333` in `check_template`) call it once per name or tag; no test or source touches `cache_clear` or `cache_info` of it. The cache saves nothing a user can see.
  2. `preview/clip.py:133-135`: `container = defs.containers.get(job.output.container); if container is None: raise TaskFailed(...)`. `job.output.container` is the `Container` literal and the linter requires every `Container` id to be defined; `naming/resolve.py:73` and `batch/audio_rules.py:475,599` index `defs.containers[...]` directly. No test reaches this branch (`grep "Unknown container" tests` finds nothing).
  3. `analysis/subtitlefile.py:17,20`: `__all__` re-exports `ENCODING_SAMPLE` and `detect_charset` from `reframe.textfile` that the module does not use. The only importer is `tests/analysis/test_subtitlefile.py:8`.
  4. `capabilities/hwtest.py:46` `BitDepth = Literal["8", "10"]` repeats `definitions/models.py:85` (cross-area: capabilities). `capabilities/detect.py:24` imports it from `hwtest`.
- Change:
  1. Delete the decorator and the import.
  2. `extension = defs.containers[job.output.container].extensions[0]` (3 lines removed).
  3. Remove `ENCODING_SAMPLE` and `detect_charset` from the import and from `__all__`; the test imports `detect_charset` from `reframe.textfile`.
  4. `hwtest.py` imports `BitDepth` from `reframe.definitions.models` (and `detect.py` too, as a new import line from `reframe.definitions.models`; delete `BitDepth` from its `hwtest` import block and from `hwtest.__all__` at `:27`); delete the second definition at `:46` and the `from typing import Literal` import at `:13`, which nothing else in `hwtest.py` uses.
- Behaviour: unchanged.
- Contracts touched: none.
- Callers to update: `tests/analysis/test_subtitlefile.py:8`, `capabilities/detect.py:24`, `tests/capabilities/test_hwtest.py:14`.
- Tests: none change except the two imports.
- Decision records: none apply.
- Size: S; estimated lines: -8 / -0
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (item 1 has four callers, not three; item 4 also removes the `Literal` import and the `__all__` entry in `hwtest.py` and adds one import line in `detect.py`; estimate -8; item 2's `container.unknown` validation rule (`validation/container.py:104`) is for a job file with a container the definitions lack, but `Container` is a `Literal` that the model already enforces, so `make_clip` cannot see one; items 1 to 3 re-checked and hold)
- Orchestrator: Tier B, work package Q-6.19 (see ../plan.md).

## Looked at and kept

- `definitions/lint.py` as a set of checks: plan C-6 "Done when" asks for a linter test, and 0010 follow-up item 6 adds the preset-order and placeholder checks (`_PRESET_SPEED_WORDS`, `_HARDWARE_PLACEHOLDERS`). The functions that `complexity.txt` flags (`_lint_video`, `_lint_quality`, `_lint_audio_encoder`, `_lint_container`, `_lint_implementation`) are flat lists of independent checks. Moving the constraints into Pydantic validators would move the same checks, not remove them.
- `definitions/custom_params.py` (`dict_pairs`, `_get_token`, `library_key_forms`, `file_key`, `split_custom_params`): decision 0035 (core-complete and final review follow-ups) requires it to read keys exactly as FFmpeg's `av_dict_parse_string` and as x264 / x265 do, because a wrong match opens a file. Its tests are the guard.
- `definitions/loader.py` `extends` and `option_sets`: 14 encoder tables use them; without them the 5.7k TOML lines would repeat the option sets.
- `FilterPreset.handbrake` (46 uses in `filters.toml`): decision 0010 §3 requires the HandBrake mapping to be written next to each preset.
- `definitions/hdr.py`: `x265_master_display`, `svt_mastering_display` and `content_light_text` are called by `command/video.py` and by `hdr_options` (via `jobs.py`); the docstring says the strings must be identical in both.
- `definitions/search.py` `_word_score`: a nine-step ladder of scores is the documented ranking (0068); a table would not be simpler.
- `naming/parse.py` (guessit workarounds, `no_user_config`, `guess_matches` cache): decision 0012 and its follow-up items 1 and 5; `tests/naming/test_guessit_quirks.py` shows each guessit output a rule works around. The `lru_cache` on `guess_matches` is needed: `choose_source` parses the folder name and every file in the folder for each file, which is quadratic without it.
- `naming/sanitize.py` (byte limits after every change, `_unreserve`, `_fit`), `naming/template.py` `_check_spec_size`, `format_value` error paths, number overrides `[0-9]{1,9}`: 0012 follow-up items 2 to 5, with a property test.
- `naming/fs.py` `NamingFs` protocol: 3 implementations in the product (`RealNamingFs`, `NoFiles`, `validation/fs.py` `LocalFileSystem`) and the tests' fakes; decision 0012 follow-up 1 says naming reads the file system only through it.
- `naming/context.py` `CONTAINER_LABELS` (`MKV`, `MP4`, `WebM`) is not a copy of `ContainerDef.label` (`Matroska (MKV)`): the `{container}` variable is documented as `MKV`.
- `analysis/__init__.py` and `preview/__init__.py` `start_*` wrappers: they take the snapshot of the job (`model_copy(deep=True)`) before the task starts and fix the task kind and message; the facade (`service.py`, `jobs.py`) calls them. The four cache wrappers (`frame_path`, `clip_path`, `clear_cache`, `cache_size`) are one line each.
- `analysis/common.py` `ProgressReporter`: FFmpeg prints thousands of progress lines per second; the throttle is needed.
- `analysis/loudness.scan` checks `start` and `duration`: the server validates `ge=0` and `gt=0` (`routers/sources.py:86-89`), but the core is a library API (the facade's `loudness_scan`), and `inf` passes the server's `ge=0`.
- `analysis/subtitles.py` (PGS reader, `_Progress`, `forced_subs_only` pass for VobSub): decision 0032 explains each pass; `testdata/README.md` "Analysis scans".
- `preview/frames.py` two timestamps at a time (`WORKERS = 2`), the source-frame-alone retry, `_cached_sizes`: decision 0033 §2 (measured: 5.0 s with one at a time, 4.0 s with two). Making it sequential would remove only about 6 lines, so it is not worth a `decision-change`.
- `preview/clip.py` `if plan.job_type == "metadata_edit" or plan.output_tmp.parent != cache.clips: raise ...`: the code comment calls it "never reached", but decision 0033 §6 says "a plan that would write outside the cache is refused". Kept.
- `preview/clip._run_plan` is a reduced copy of the step loop in `queue/runner.py` (write plan files, `resolve_argv`, measures, `header_edit`, rename). Sharing it needs the runner's pause, stall watchdog and job log hooks; not worth it. Only the measurement storing is worth sharing (NDP-07).
- `preview/cache.py` (`GRACE`, `STALE`, `protect`, `find_clip` listing the folder by prefix): decision 0033 §1. The `now` and `grace` parameters of `trim` and `entries` are used by `tests/preview/test_cache.py` as a clock; kept.
- Covered by other agents, not repeated here: the "deinterlace before the crop" geometry rule written five times, with `preview/graph.py:131-140` as one site (CMD-01, SRV-04, VAL-11); the bitmap-subtitle codec set, the forced-only set and the external extension table (CMD-03, VAL-07; the sites in this area are `analysis/subtitlefile.py:22` and `preview/` has none); the "every encoder available" test helper (CMD-10).
- `coverage.txt`: import-time lines (the first lines of every module, `def` lines) show as missed in every file, so I used it only for function bodies; no body in this area showed up as dead.
