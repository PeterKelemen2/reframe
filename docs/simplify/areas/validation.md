# validation: simplification findings

Commit: 85d9dcb.
Verified: 2026-11-15, 2 confirmed, 12 adjusted, 0 rejected (one sub-item of VAL-12 rejected).

Scope: `packages/reframe/src/reframe/validation/` (24 files) and `packages/reframe/tests/validation/` (33 files). Source lines: 4683 code lines (5754 raw); tests 7300 code lines. Read in full: every file in `validation/` (video.py, dryrun.py, output.py, subtitles.py, filters.py, audio.py, container.py, dimensions.py, tracks.py, fs.py, encoder.py, range.py, levels.py, metadata.py, tags.py, naming.py, chapters.py, inplace.py, registry.py, context.py, common.py, source.py, tools.py, `__init__.py`), decision records 0014, 0026, 0065 (item FA 1), 0070 (task A), 0016 (RN), and the parts of `command/`, `capabilities/issues.py`, `definitions/options.py`, `probe/hdr.py` that validation mirrors. Only skimmed: the test files (read: `scenario.py` head, `test_engine.py` head, `test_rules.py` head and tail, `test_template.py` head, `test_no_mkvtoolnix.py`, `test_text_charset.py`; the rest by `grep` on names, imports and helpers).

## Summary

The rules themselves are small and each one is tied to a decision record or a verified tool behaviour, so most of the size is real. The complexity that is not required sits in four places. First, the fix `target` ("job" or "template") is passed down through about 40 functions and about 160 lines, but it can be set once in `validate_template`. Second, five template rules repeat a job rule with the same body. Third, several facts are written again next to the command builder, the probe or the definitions (subtitle codec sets, the HDR test, the "no 10-bit" patch, the "remove option or parameter" fixes, option value labels). Fourth, the tests load `scenario.py` by file path with the same 14 lines in 20 files, although a plain relative import works in this repository's pytest mode (checked). There is also a small set of dead leftovers from C-18 (mkvpropedit removal). Two findings are `decision-change`: the charset cache (0065 FA 1, 0070 A.1) and NUL paths handled in every layer (0016 RN). They are not counted in the totals. Verify made VAL-06 a third (it removes a code that 0014 lists); its numbers are still in the totals.

Totals without the two decision-change findings: about -400 source lines and about -330 test lines.

## Findings

### VAL-01: set the fix `target` once instead of passing it through 40 functions
- Kind: structure
- Where: `validation/__init__.py:64-80` (`_run`) and `:137-172` (`validate_template`); `validation/context.py:43` (`JobContext.target`), `:120` (`TemplateContext.target`), `:44` (`JobContext.subject` stays); `validation/common.py:69-70` (`fix`), `:90-118` (`switch_container_fixes`); and every function that takes `target`: 157 lines with `target=` or `target:` in 18 files (video.py 47, encoder.py 18, filters.py 15, container.py 11, output.py 11, subtitles.py 10, audio.py 9, levels.py 8, dimensions.py 7, common.py 4, and 1 to 3 each in chapters, context, inplace, metadata, naming, range, tags, tracks).
- Now: every function that makes a `Fix` takes `target: FixTarget = "job"` and every call passes `target=ctx.target` or `target=target`. There are 39 `target: FixTarget` parameters, 38 lines that hold only `target=...,`, and 77 more inline `target=` arguments. The value is only ever "job" (a `JobContext`) or "template" (a `TemplateContext`); the one other value, `"settings"`, is written explicitly (`output.py:347`, and the `tool.fixes` of `ToolInfo`). `JobContext.target` is never set to anything but its default (callers: `validate()` and two tests, none pass it). `ctx.target` and `target` are used for nothing but `Fix.target`.
- Change: stop passing `target`. In `validate_template` (and only there) re-target the fixes the rules made:
  ```python
  def _for_template(issue: ValidationIssue) -> ValidationIssue:
      if not any(f.target == "job" for f in issue.fixes):
          return issue
      fixes = [f.model_copy(update={"target": "template"}) if f.target == "job" else f
               for f in issue.fixes]
      return issue.model_copy(update={"fixes": fixes})
  # in validate_template: issues = [_for_template(i) for i in _run(TEMPLATE_RULES, context)]
  ```
  Then delete the parameter `target` from: `common.fix` (keep the keyword for the two explicit `"settings"` uses), `common.switch_container_fixes`, `video.py` (`_switch_fix`, `video_availability_issues`, `video_bit_depth_issues`, `video_choice_issues`, `video_option_issues`, `video_rate_control_issues`, `video_x26x_rule_issues`, `video_fast_decode_issues`, `video_option_rule_issues`, `_set_option`, `_remove_option`, `_condition_fix`, `_inactive_issues`, `_vbv_rules`, `_x264_rules`, `_x265_rules`, `_svt_rules`, `_min_max_conflict`, `_vp9_rules`, `_remove_param`, `_param_file_issues`, `_own_option_issues`, `video_custom_param_issues`, `video_custom_param_override_issues`, `_encode_fix`, `video_container_issues`), `encoder.audio_encoder_issues`, `container._audio_codec_issue`, `dimensions._custom_par_issue`, and every `target=ctx.target` in the rule modules. The calls in `validation/naming.py:55` and `validation/tags.py:39,78` into `reframe.naming.check_template(target=)` and `reframe.command.metadata.tag_template_issues(target=)` stop passing it. Those two functions keep their `target` parameter: `check_template` is public (`reframe.naming`) and `tests/naming/test_template.py:350` calls it with `target="template"`, and `command/metadata.py:357` passes `tag_template_issues`'s `target` through. Remove `JobContext.target`, `TemplateContext.target` and the `FixTarget` imports that become unused. `capabilities.encoder_issues(target=)` then has only test callers (`tests/capabilities/test_issues.py:280-295`); leave it or drop it in the same change.
- Behaviour: unchanged. Fixes of a job keep `target="job"`, fixes of a template get `"template"`, explicit `"settings"` fixes stay. Messages, codes and patches do not change.
- Contracts touched: none (the OpenAPI schema of `Fix` is unchanged; `FixTarget` in `models/issues.py` stays).
- Callers to update: all rule modules in `validation/` (list above); `dryrun.py` already uses the default. Outside the area: none (`check_template` and `tag_template_issues` keep their `target`; see Change).
- Tests: none to delete. These stay as the guard: `test_custom_params_rules.py:194,286`, `test_template.py:403,440` (they assert `f.target == "template"`), `scenario.py:286-289,361` (apply by target), `test_rules.py:233` (the explicit `"settings"` fix). Add one test: a template rule that makes a fix with a `"settings"` target keeps it (the "Always overwrite" fix is a job rule, so register a small fake rule with `monkeypatch` on `TEMPLATE_RULES`).
- Decision records: 0014 (fixes are applied and re-validated; unchanged).
- Size: M; estimated lines: -110 source / -0 tests
- Risk: low. A template fix that must stay `"job"` would be re-targeted by mistake; none exists (`grep 'target="'` in `validation/` finds only `output.py:347`, which is `"settings"`). Run `test_template.py` and `test_custom_params_rules.py`.
- Depends on: none (VAL-03, VAL-05, VAL-08 get shorter after it)
- Confidence: high
- Verdict: ADJUSTED (`check_template` and `tag_template_issues` keep their `target`: `tests/naming/test_template.py:350` calls the public `check_template` with `target="template"`; `_run` is at `:64-80`. Attack failed otherwise: `target` is only read by `Fix(target=)`, no code branches on it, `lint_defaults` and `lint_track_rules` already make `"template"` fixes, `JobContext.target` is never passed, and the frontend only reads `fix.target` (`stores/editor.ts:544,556,1382`, `useValidation.ts:24`), whose values stay the same.)
- Orchestrator: Tier A, work package Q-6.5 (see ../plan.md).

### VAL-02: the tests load `scenario.py` with the same helper in 20 files
- Kind: tests
- Where: `tests/validation/` `def _load(name)` plus `sc = _load("scenario")` in `test_audio_agreement.py:37`, `test_command_agreement.py:69`, `test_custom_params_cqm.py:52`, `test_custom_params_rules.py:27`, `test_default_tracks.py:37`, `test_dryrun_ffmpeg.py:41`, `test_dryrun.py:42`, `test_engine.py:49`, `test_hdr_ffmpeg.py:38`, `test_inplace_fs.py:21`, `test_inplace.py:18`, `test_levels_ffmpeg.py:20`, `test_no_mkvtoolnix.py:15`, `test_nul_paths.py:24`, `test_option_values.py:16`, `test_paths.py:32`, `test_rules.py:49` (also `_load("cases_*")` at `:1525` and `:1646`), `test_snap_notes.py:18`, `test_template.py:36`, `test_x26x_ffmpeg.py:20`; the docstring of `scenario.py:1-3`.
- Now: each file has an 11-line `_load` (spec from file location, `sys.modules`, `exec_module`) plus the imports `importlib.util`, `sys`, `ModuleType`, and a blank line pair. The comment says "pytest runs with `--import-mode=importlib`: a helper next to the tests is loaded by path". That is not needed: `packages/reframe/tests/queue/` has no `__init__.py` and its tests use `from .conftest import ...` in the same mode. Checked in a scratch folder with `--import-mode=importlib` and no `__init__.py`: `from . import scenario as sc` and `from .scenario import X` both work from two test files. Also `scenario` is executed 20 times today (20 module copies); a relative import loads it once. Three more helpers repeat: `Case` (dataclass) and `video()`, `caps()`, `both()`, `container()` are written twice, in `test_rules.py:60-110` and `test_template.py:60-118`.
- Change: in each file replace the `_load` block and the three imports with `from . import scenario as sc` (and `from .scenario import ...` where names are used). In `test_rules.py` use `from . import cases_inplace, cases_metadata, cases_options` and call `module.cases(_HELPERS)`; at `:1646` use `cases_metadata` directly. In `test_command_agreement.py` the second loader `_load_command_tests` (lines 50-67, loads `tests/command` as a package by hand) can become `from ..command import conftest as cmd_conftest, test_snapshots`; verify with one run (optional, separate step). Move `Case`, `both`, `Mod` into `scenario.py` (the field name that differs, `s.job.video` vs `s.template.video`, stays in each file's `video()` and `container()`). Update the docstring of `scenario.py`.
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the 20 test files above.
- Tests: all stay. After the change, `uv run mypy` checks `sc.*` calls against `scenario.py`'s annotations (today `sc` is a `ModuleType`, so every call is `Any`); fix the few signatures that mypy then reports (`scenario.py` returns `Any` in places). Run `uv run pytest packages/reframe/tests/validation -q`, once with the whole folder and once with a single file, because module names come from the path.
- Decision records: 0004 (shared testing package) does not require this loader; none other.
- Size: M; estimated lines: -0 source / -300 tests (20 files x 14 lines for the loader and its imports, plus about 35 for the duplicated `Case` helpers; some imports such as `sys` and `Path` are still used and stay)
- Risk: low. The import mode could behave differently when a file is run alone (checked once: it works); mypy may report new errors.
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (checked in a scratch tree with `--import-mode=importlib` and no `__init__.py`: `from . import scenario as sc` and `from .scenario import X` work for the whole folder and for one file, and `scenario` runs once. 20 `def _load` found. `scenario` is not assertion-rewritten today or after. `FIXES_CHECKED` in it is never read, see the end of this file.)
- Orchestrator: joined into X-04 (see ../cross-cutting.md); that entry decides the tier and the work package.

### VAL-03: five template rules repeat a job rule with the same body
- Kind: duplication
- Where: `validation/encoder.py:88-95` (`video_encoder`) and `:129-136` (`template_video_encoder`); `:97-107` (`video_encoder_settings`) and `:139-149` (`template_video_settings`); `validation/dimensions.py:199-203` (`custom_par`) and `:206-210` (`template_custom_par`); `validation/filters.py:213-218` (`filters`) and `:220-225` (`template_filters`); `validation/levels.py:150-164` (`advanced_option_rules`, `custom_params`, `custom_param_overrides`) and `:166-175` (`template_advanced_option_rules`, which runs the same three in one function); `validation/registry.py:79-98` (`job_rule`, `template_rule`); `validation/context.py` (both contexts).
- Now: 10 template rules (`grep -c '@template_rule'`), 44 job rules. Five template rules are the job rule with `ctx.job.` replaced by `ctx.template.` (`video`, `filters`, `dimensions`, `output.container` exist on both `JobSettings` and `JobTemplate`). The two contexts already share `caps`, `definitions`, `container`, `subject`, `target`.
- Change: give both contexts a property `doc` (`JobContext.doc` returns `self.job`, `TemplateContext.doc` returns `self.template`; type `JobSettings | JobTemplate`). Add one decorator that registers a rule in both lists:
  ```python
  def shared_rule(area: Area, *codes: str) -> Callable[[_Both], _Both]:
      def register(check: _Both) -> _Both:
          JOB_RULES.append(Rule(area, check.__name__, check, codes))
          TEMPLATE_RULES.append(Rule(area, check.__name__, check, codes))
          return check
      return register
  type _Both = Callable[[JobContext | TemplateContext], Iterable[ValidationIssue]]
  ```
  Write the five rules once with `ctx: JobContext | TemplateContext` and `ctx.doc.video` / `ctx.doc.filters` / `ctx.doc.dimensions`. In `levels.py` register `advanced_option_rules`, `custom_params`, `custom_param_overrides` with `shared_rule` and delete `template_advanced_option_rules`. Delete `template_video_encoder`, `template_video_settings`, `template_custom_par`, `template_filters`. Optional second step: `video_container_issues` and `_audio_codec_issue` take a `switch: SwitchContainer | None` callback only because the job version filters containers with `job_fits`; let `switch_container(ctx, allowed)` accept either context (for a template: no `output`, no `holds`) and drop the `SwitchContainer` alias, the `switch_to` inner function and the two lambda arguments (about -15 more).
- Behaviour: unchanged. Issue order for a template stays the same (area order, then registration order: the shared rules register in the same sequence the template rules have today). `Rule.codes` of the template list stay a subset of the job list. The template rules get the job rules' names (`template_video_encoder` becomes `video_encoder`, and so on): the name shows only in the `validation.rule_failed` message and in the test ids of `test_every_template_rule_has_a_positive_case`.
- Contracts touched: none.
- Callers to update: `validation/encoder.py`, `dimensions.py`, `filters.py`, `levels.py`, `registry.py`, `context.py`; `__init__.py` re-exports nothing of these.
- Tests: none to delete. These stay: `test_template.py` (all), `test_rules.py:1554-1563` (`template_declared <= declared`), `test_engine.py:76-81` (area order; add `shared_rule` to the decorator test at `:107-116`). Splitting `template_advanced_option_rules` into three template rules makes `test_template.py::test_every_template_rule_has_a_positive_case` (`:410-420`, runs each template rule alone over `CASES`) demand a positive case for `custom_params` and `custom_param_overrides`, and `CASES` has option cases only (`:358-376`): add two cases (a custom parameter that names a file; an override of an option), or register the three calls as one shared rule (`advanced_rules`) and add none.
- Decision records: 0014 (every code has a positive and a negative test; unchanged).
- Size: M; estimated lines: -45 source (-60 with the optional second step) / -0 tests
- Risk: low to medium. A template rule that needs something only a job has would show as a mypy error (`ctx.doc` has only the shared fields), which is the intended guard. Issue order for templates must be compared once (`test_template.py` asserts some orders).
- Depends on: VAL-01 (not required, but the shared rules then lose the `target` argument)
- Confidence: high
- Verdict: ADJUSTED (tests: the split needs two new positive template cases, see Tests; the rule names change. Checked and holds: 10 template rules, 44 job rules, the five bodies differ only in `ctx.job` / `ctx.template`, registration order per area stays the same, no code or severity differs between a job rule and its template twin.)
- Orchestrator: Tier B, work package Q-6.16 (see ../plan.md).

### VAL-04: dead code and pass-through leftovers
- Kind: dead-code
- Where:
  - `validation/metadata.py:26-45` (`_written_languages`). 0 callers in the repository (`grep -rn _written_languages` finds only the definition; vulture lists it). It served the mkvpropedit "BCP 47 tag lost" rule that C-18 removed (commit 7247ae5).
  - `validation/common.py:73-77` (`tool_problem`) and its `__all__` entry (`:40`), and the `ToolInfo` import (`:25`). 0 callers; `cli.py:3264` has its own `tool_problem`.
  - `validation/tracks.py:34` (`BITMAP_CODECS`) and its `__all__` entry (`:18`). 0 importers anywhere (tests, scripts, server).
  - `validation/inplace.py:24-27` (`source_writable`) and its `__all__` entry (`:21`). It returns `fs.writable_file(path)`. One production caller: `inplace.py:in_place_source` (`:85`). Tests: `test_inplace.py:73-84`, `test_inplace_fs.py:83-99`.
  - `validation/registry.py:29-57`: `Area = Literal[12 names]` (`:29`) and `AREAS: tuple[Area, ...] = (the same 12 names)` (`:44`).
- Now: see "Where". `source_writable` adds no check: the docstring only names the view method. `AREAS` repeats the Literal.
- Change: delete `_written_languages`; delete `tool_problem` and the import; delete `BITMAP_CODECS`; replace `source_writable(ctx.fs, source)` by `ctx.fs.writable_file(source)` and delete the function; write `AREAS: tuple[Area, ...] = get_args(Area)` (import `get_args` from `typing`) and delete the second list. Remove the matching `__all__` entries.
- Behaviour: unchanged.
- Contracts touched: none (the names are not used outside `validation/` and its tests).
- Callers to update: `validation/inplace.py`; tests `test_inplace.py` and `test_inplace_fs.py` (import of `source_writable`).
- Tests: delete, do not rewrite. `test_inplace.py:73-84` (`test_source_writable`; its `LocalFileSystem` half repeats `test_inplace_fs.py::test_local_writable_file`, its `Answers` half checks only the pass-through) and the import `:15`; in `test_inplace_fs.py` the class `WindowsView` and `test_source_writable_asks_the_view_with_windows_paths` (`:73-86`, a stub that is asked through the pass-through) and the last assert of `test_every_view_answers_writable_file` (`:99`) and the import `:18`. `test_read_only_source_through_the_view` (`test_inplace_fs.py:139`) already guards that `in_place_source` asks the view.
- Decision records: none apply (C-18 / 0080 explains why `_written_languages` is dead).
- Size: S; estimated lines: -50 source / -30 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (tests are deleted, not rewritten: after the change they would test only a stub; estimate -30 tests. Callers re-checked: each name has 0 users outside the lines listed, none in scripts, testing, server, frontend or docs; 0034 only records the history of `source_writable`.)
- Orchestrator: Tier A, work package Q-6.5 (see ../plan.md).

### VAL-05: `encoder_issues` makes a fix that validation then unpacks and replaces
- Kind: layering
- Where: `validation/video.py:199-224` (`video_availability_issues`), `:184-196` (`_switch_fix`, the `closest` flag), `validation/encoder.py:55-85` (`audio_encoder_issues`); `capabilities/issues.py:71-160` (`encoder_issues`, the fix at about `:140-150`).
- Now: `encoder_issues` (callers in production: only these two functions) builds a "Use X (closest match)" fix with a `ReplaceOp`. Both validation functions then read `old_fix.patch[0]`, check `isinstance(first, ReplaceOp)`, take `first.value` as the new encoder id, and build another patch from it (`switch_video_encoder` for video, `switch_audio_encoder` for audio). Each has an `else`/`if new is None` branch marked `# pragma: no cover - encoder_issues makes only replace fixes` (`video.py:221`, `encoder.py:79`). About 50 lines exist only to rewrite what the first function made.
- Change: let `encoder_issues` take the patch maker:
  ```python
  def encoder_issues(..., fix_ops: Callable[[str], tuple[list[JsonPatchOp], str | None]] | None = None):
      ...
      if closest is not None and closest != encoder_id:
          ops, note = fix_ops(closest) if fix_ops else ([ReplaceOp(path=field_pointer(path), value=closest)], None)
          detail = "closest match" + (f"; {note}" if note else "")
          fixes.append(Fix(label=f"Use {closest} ({detail})", patch=ops, target=target))
  ```
  In validation: `video_availability_issues` becomes `return encoder_issues(video.encoder, caps, definitions, path="video.encoder", subject=subject, fix_ops=lambda new: switch_video_encoder(video, new, definitions, caps))`; `audio_encoder_issues` becomes `encoder_issues(encoder_id, caps, ctx.definitions, path=path, subject=ctx.subject, fix_ops=lambda new: (switch_audio_encoder(path, ctx.definitions.audio_encoders[new], ctx.definitions, track=track, stream=stream), None))`. Delete the `closest` flag of `_switch_fix` (the label code stays for `video_container_issues`). The labels stay the same: today video gives `Use X (closest match; <note>)` and audio gives `Use X (closest match)`.
- Behaviour: unchanged (same labels and patches).
- Contracts touched: public core API of `reframe.capabilities.encoder_issues` (new optional keyword; the default keeps today's behaviour, so its tests stay).
- Callers to update: `validation/video.py`, `validation/encoder.py`.
- Tests: none deleted. `tests/capabilities/test_issues.py` (the `encoder_issues` tests, `:102-295`) stays as the guard of the default. `tests/validation/test_rules.py` (`test_closest_match_respects_detected_10bit`) stays.
- Decision records: 0008 (encoder issue codes), 0014 item 5 (closest-match fix switches the whole video setting); both unchanged.
- Size: S; estimated lines: -25 source (validation -34, capabilities +9) / -0 tests
- Risk: low.
- Depends on: none (cross-area: capabilities)
- Confidence: high
- Verdict: CONFIRMED (`encoder_issues` has only these two production callers; labels and patches of the new shape equal today's; the audio `audio_encoders[new]` index is safe because `lint.py:_lint_audio_fallback` fails the build on a fallback id without an audio definition; 0008 describes C-8 adding the quality conversion to the fix, which stays true.)
- Orchestrator: Tier A, work package Q-6.5 (see ../plan.md).

### VAL-06: the `container.unknown` rule and 15 `container is None` guards cover a state that cannot happen
- Kind: decision-change (defensive code; the code `container.unknown` that 0014 follow-up item 3 lists goes)
- Where: `validation/container.py:103-115` (`known_container`), `:76` (`_audio_codec_issue`), `:158`, `:220`; `validation/chapters.py:34`; `validation/audio.py:63`; `validation/naming.py:31`; `validation/metadata.py:105`; `validation/tracks.py:110`; `validation/subtitles.py:177` (`bitmap_copy`), `:221` and `:252` (`conversions`: `container is not None and ...`); `validation/video.py:1311` (`video_container_issues`: `definitions.containers.get`); `validation/output.py` (`output_path_issues(container: ContainerDef | None)` and its `container is not None and` test; `output_path` passes `ctx.container`); `validation/inplace.py:41` (`ctx.container ... if ... is not None else ".mkv"`); `validation/context.py:46-48`, `:122-124` (`container` returns `ContainerDef | None`).
- Now: `JobSettings.output.container` is `Container = Literal["mkv", "mp4", "webm"]` (`models/job.py:64`) and `Definitions.containers` is `dict[Container, ContainerDef]` loaded from the packaged `containers.toml` only (`load_definitions`, no user override). A job with another container is rejected when it is parsed. `definitions/lint.py:614-621` (`_lint_containers`) already fails the build when any `Container` value has no definition (`tests/definitions/test_lint.py:357` shows the message, and `:15` asserts that the shipped definitions lint clean). So `ctx.container is None` is unreachable in production. The only way to reach `container.unknown` is `setattr(job.output, "container", "avi")` in a test (`test_rules.py:727-733`, `:1579-1584`). Cross-area, the same guard exists in `command/builder.py:327-328`, `command/audio.py:219-225` (`_container`), `queue/verify.py:193-194`. The docstring of `known_container` says "a hand-edited or newer job file", but the persistence rules reject such a file at load (a new `Literal` value needs a `schema_version` bump).
- Change: (1) `definitions/models.py`: no change needed (the linter test already guards it); optionally add a `model_validator` on `Definitions` that requires all `Container` ids when `containers` is not empty. (2) `JobContext.container` and `TemplateContext.container` return `ContainerDef` (`self.definitions.containers[self.job.output.container]`); remove every `None` guard above and the `ContainerDef | None` types. (3) Delete the rule `known_container` and the code `container.unknown`. (4) Cross-area, in the same change: `command/builder.py:327-328`, `command/audio.py` `_container()` and `queue/verify.py:193-194` index `containers[...]`; delete the three `unknown container` refusals and the refusal case in `test_command_agreement.py:268`. (5) Move the lint guarantee into one sentence in the `Definitions` docstring.
- Behaviour: unchanged for every job that can be parsed. The code `container.unknown` can no longer appear. The frontend does not use it (`grep -rn container.unknown frontend desktop packages/reframe-server docs/plan`: no match).
- Contracts touched: public core API (`PlanError("unknown container")` and the issue code `container.unknown` disappear); no HTTP schema change (the code is a free string).
- Callers to update: the places in "Where"; `command/builder.py`, `command/audio.py`, `queue/verify.py`; `queue/runner.py:716` (passes `self._defs.containers.get(...)` to `output_path_issues(container=)`; index it instead). `tests/validation/test_paths.py:69` and `test_nul_paths.py:181` pass a real container and need no change.
- Tests: delete the `test_rules.py` case "unknown container" (`:726-733`); do not delete `test_switch_container_keeps_every_track_valid` (`:1579-1584`): it is the only assertion that `tracks.job_fits` leaves WebM out of the "Switch to" fixes, so give it another vehicle (an issue whose fix list comes from `switch_container`, such as the copied PGS track in MP4 of `:1565-1574`, asserting that only "Switch to MKV" is offered); delete the `Refusal("unknown container", ...)` line in `test_command_agreement.py:268`; `tests/command/test_builder.py:104`, `tests/command/test_tracks.py:145` and `tests/queue/test_units.py:273` change with the cross-area step. `test_lint.py:357` (lint reports a missing container) stays as the guard.
- Decision records: 0014 "Follow-up (M2 wave 2b)" item 3 lists `container.unknown` as one of the five builder refusals that became validation errors (so the decision record must get one line: removed because the type makes it impossible; 0026 does not mention it). This is a `decision-change` of that item. 0014's reason (what `build_plan` refuses must be a validation error) stays true, because the builder refusal goes too; the condition is that the persisted `Container` Literal and the packaged definitions can never disagree (true today: the lint test enforces it, `naming/resolve.py:73` and `batch/audio_rules.py:475,599` already index `containers[...]`, and every test that reaches the state forces it with `setattr` or `# type: ignore`). The totals in the Summary count this finding; subtract about -45 source / -14 tests from them.
- Size: M; estimated lines: -45 source in `validation/` (about -55 with the three outside places) / -14 tests
- Risk: medium. The cross-area part touches the builder and the queue verifier; run `uv run pytest packages/reframe/tests/command packages/reframe/tests/queue packages/reframe/tests/validation`.
- Depends on: none
- Confidence: medium (the Literal and the lint make it unreachable, but it spans four areas and a decision record)
- Verdict: ADJUSTED (Kind is `decision-change`, see Decision records; `queue/runner.py:716` was missing from the callers; anchors `context.py:46-48,122-124` and `inplace.py:41`; the test `test_switch_container_keeps_every_track_valid` is kept and re-aimed, not deleted. The unreachability holds: `Container` is a Literal, `Definitions.containers` is `dict[Container, ...]`, and the frontend and server do not use the code.)
- Orchestrator: Tier B, work package Q-6.16 (see ../plan.md).

### VAL-07: facts written again next to the command builder (subtitle formats, HDR test)
- Kind: duplication (cross-area: command, analysis, batch, probe)
- Where: `validation/tracks.py:33-45` (`BITMAP_CODECS` `:34`, `FORCED_ONLY_CODECS` `:36`, `EXTERNAL_FORMATS` `:39`), `:163-176` (`subtitle_input`); `validation/subtitles.py:52-53`, `:81-83` (`sources`, `charsets`); `validation/filters.py:41` (`_HDR_TRANSFERS`), `:227-231` (`is_hdr`), uses at `:253`, `:280`.
- Now:
  - `EXTERNAL_FORMATS` (`.srt` to `subrip`, `.ass` and `.ssa` to `ass`, `.vtt` to `webvtt`, `.sup` to `hdmv_pgs_subtitle`, plus the kind) repeats `command/subtitles.py:34-40` (`EXTERNAL_CODECS`), which `analysis/subtitlefile.py:13` already imports. The kind is "bitmap" exactly for `.sup`.
  - The set `{hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle, xsub}` is written 5 times: `probe/names.py:170`, `command/subtitles.py:41`, `analysis/subtitlefile.py:22`, `batch/descriptors.py:107`, `validation/tracks.py:34` (dead, see VAL-04). `FORCED_ONLY_CODECS` is written twice: `validation/tracks.py:36` and `batch/explain.py:66`.
  - `validation.filters.is_hdr` says HDR when `hdr.formats` is set or the transfer is PQ or HLG. The builder's `command.filtergraph.is_hdr` (`:150`) says HDR only when `hdr.formats` is set. `probe/hdr.py:parse_hdr` sets `formats` for every PQ or HLG stream (`HDR_TRANSFERS` exists at `probe/hdr.py:36-38`, the same set as `_HDR_TRANSFERS`), so for a probed source both agree; for a hand-built or API-sent `MediaSource` with a PQ transfer and no `hdr`, validation warns about HDR handling the builder does not do (against 0026 "builder and validation agree").
- Change: in validation, delete `EXTERNAL_FORMATS`; use `EXTERNAL_CODECS` from `reframe.command.subtitles` and derive the kind with the bitmap test of the command module (make `command.subtitles._is_bitmap` public as `is_bitmap_codec`): in `subtitle_input`: `codec = EXTERNAL_CODECS.get(suffix)`, `kind = "bitmap" if codec is not None and is_bitmap_codec(codec) else "text"`; in `charsets`: skip when `codec is None or is_bitmap_codec(codec)`; `known = ", ".join(EXTERNAL_CODECS)` (same order as now). Delete `is_hdr` and `_HDR_TRANSFERS` from `validation/filters.py` and import `is_hdr` from `reframe.command.filtergraph`. For the other copies (outside this area): one `BITMAP_SUBTITLE_CODECS` and one `FORCED_ONLY_CODECS` in `reframe.models.media` (lowest module that `batch`, `analysis`, `command`, `probe` and `validation` can all import; `batch` cannot import `validation`, which imports `batch`).
- Behaviour: unchanged for probed sources. Changes only for a `MediaSource` with a PQ or HLG transfer and no `hdr` info: no HDR warning (the builder does not treat it as HDR either).
- Contracts touched: none (core internal).
- Callers to update: `validation/subtitles.py`, `validation/tracks.py`, `validation/filters.py`; `tests/validation/test_ffmpeg.py:12,62` (imports `FORCED_ONLY_CODECS` from `validation.tracks`).
- Tests: the `hdr_source` helper in `test_rules.py:251-253` makes HDR by transfer only; change its 8 direct uses (`:900`, `:906`, `:974`, `:975`, `:982`, `:983`, `:990`, `:991`; `:257` is the call inside `hdr10_source`) to `hdr10_source` (`:255-258`, the form the probe reports) and delete `hdr_source` or keep it as the base of `hdr10_source`.
- Decision records: 0026 (builder and validation agree) supports it; 0014 follow-up item 2 (HDR to 8-bit) is unchanged.
- Size: S; estimated lines: -12 source in `validation/` (about -25 across the other areas) / -0 tests
- Risk: low.
- Depends on: VAL-04 (it deletes `BITMAP_CODECS` first)
- Confidence: high for the subtitle sets, medium for the HDR predicate
- Verdict: ADJUSTED (the test helper has 8 direct uses, not 9. Checked and holds: `EXTERNAL_CODECS` has the same keys in the same order as `EXTERNAL_FORMATS`, so the `subtitle.external_unknown` message is unchanged; `.sup` is the only bitmap entry; `probe/hdr.py:parse_hdr` gives non-empty `formats` for every PQ or HLG stream (HDR10, HLG, or Dolby Vision profile 5), so the two `is_hdr` agree for probed sources; the five copies of the bitmap set exist at the listed places. Note `probe/names.py:170` already has a public `BITMAP_SUBTITLE_CODECS`.)
- Orchestrator: Tier B, work package Q-6.16; part of it is joined into X-06 (see ../cross-cutting.md). The subtitle-set part is joined into X-06 (Tier A, Q-6.10). The HDR predicate part stays here, Tier B (Q-6.16), because it changes the result for a source with a PQ/HLG transfer and no HDR info.

### VAL-08: the dry run builds the same "remove" fixes as `video.py`
- Kind: duplication
- Where: `validation/dryrun.py:65-66` (`_without`), `:269-293` (`_Attribution._param_target`, `_option_target`); `validation/video.py:738-743` (`_option_pointer`, `_remove_option`), `:1066-1080` (`_remove_param`), `:468-473` (inline `reset` fix in `video_option_issues`).
- Now: `_Attribution._param_target` builds "Remove <entries> from the custom parameters" with `whole_param` and the `:`-join of the other entries; `video._remove_param` does the same (same label text, same patch, plus the case of no known parameter). `_option_target` builds the fix "Reset <key> to its default" with `RemoveOp(path=format_pointer(["video", "advanced", key]))`; `video_option_issues` makes the identical fix inline, and `video._remove_option` makes the same patch with another label. The dry run already imports from `video.py` (`video_custom_param_issues`, `video_option_rule_issues`).
- Change: make `_remove_param` and `_remove_option` public in `video.py` (`remove_param_fix`, `remove_option_fix(key, label=None)`), and in `video_option_issues` use `remove_option_fix(key, f"Reset {key} to its default")`. In `dryrun.py` delete `_without`, and let `_param_target` return `_Target("video.custom_params", "encoder.custom_param_rejected", (remove_param_fix(self.params, param),))` and `_option_target` return `_Target(f"video.advanced.{key}", "encoder.option_rejected", (remove_option_fix(key, f"Reset {key} to its default"),))`. Delete the then-unused imports (`format_pointer`, `RemoveOp`, `replace`, `fix`, and `whole_param` from `reframe.definitions.custom_params`; `Fix` and `CustomParam` stay in use). Also drop the re-exports `CustomParam` and `split_custom_params` from `dryrun.__all__` (only `tests/validation/test_dryrun.py:34` uses `split_custom_params` through it; import it from `reframe.definitions.custom_params` there).
- Behaviour: unchanged (same labels and patches).
- Contracts touched: none.
- Callers to update: `validation/dryrun.py`, `validation/video.py`, `tests/validation/test_dryrun.py`.
- Tests: none deleted; `test_dryrun.py` (refused parameter tests) and `test_dryrun_ffmpeg.py` stay as the guard.
- Decision records: 0035 (dry run and fixes), 0070 task A item 2 (the fix for a Windows path entry; it is in `whole_param`, which both paths still use).
- Size: S; estimated lines: -22 source / -0 tests
- Risk: low.
- Depends on: VAL-01 (the signatures use `target`; do VAL-01 first or keep the `target` argument)
- Confidence: high
- Verdict: ADJUSTED (`whole_param` also becomes an unused import in `dryrun.py`. Checked and holds: label text, patch and `rest` string of `_param_target` and `_remove_param` are identical for a non-None param, and `_option_target` equals the inline `reset` fix of `video_option_issues`; `CustomParam` is used by no other module through `dryrun`, `split_custom_params` only by `test_dryrun.py:34`.)
- Orchestrator: Tier A, work package Q-6.5 (see ../plan.md).

### VAL-09: small duplicates inside `video.py` and with `definitions`
- Kind: duplication
- Where: `validation/video.py:746-753` (`_value_label`); `:163-172` (the 10-bit block of `switch_video_encoder`) and `:244-252` (`_bit_depth_ops`); `:130`, `:147`, `:525`, `:563` (rate control patches); `:151` and `:581` (the kbps clamp); `:769-775` (`_int`) and `validation/levels.py:54-67` (`x265_min_cu_size`); `definitions/options.py:82-91` (`_value_text`).
- Now:
  - `_value_label(option, value)` (bool as on/off, choice label, else number) is the same function as `definitions/options._value_text` (used by `describe_condition`), except that it formats numbers with `_num` (`f"{value:g}"`), which prints `1234567` as `1.23457e+06` and `1000000` as `1e+06` (checked: `uv run python -c "print(f'{1234567:g}')"`). Used in 6 messages (`:766`, `:882`, `:888`, `:952` twice, `:1224`).
  - `switch_video_encoder` repeats `_bit_depth_ops(video, new, 8)` by hand (set 8-bit, reset the profile when the profile does not allow 8-bit) with one added test `reset not in ops`.
  - The two patches "to average bitrate" (`AverageBitrate().model_dump(mode="json")`) and "to constant quality" (`ConstantQuality(value=quality.default).model_dump(mode="json")`) and the kbps clamp are built twice, once in `switch_video_encoder` and once in `video_rate_control_issues`.
  - `x265_min_cu_size` coerces an option value with the same try/`int()`/bool-check that `_int` does.
- Change: make `_value_text` public (`value_text`) in `definitions/options.py` and delete `_value_label` (messages with numbers of 1,000,000 or more now print in full; no other change). Replace the 10-bit block by `ops += [op for op in _bit_depth_ops(video, new, 8) if op not in ops]`. Add three helpers `_to_bitrate_patch()`, `_to_quality_patch(quality)`, `_clamp_kbps(kbps, bitrate)` and use them in both places. In `levels.py` call `_int` (make it `option_int` in `video.py` or `definitions/options.py`) and then test `in (8, 16, 32)`.
- Behaviour: changes only the text of messages that show a number of 1e6 or more, or a float with more than 6 significant digits (`_num(0.1234567)` is `0.123457`, `str` gives `0.1234567`); an old formatting defect.
- Contracts touched: none.
- Callers to update: `validation/video.py`, `validation/levels.py`, `definitions/options.py` (export).
- Tests: none deleted; `test_option_rules.py`, `test_option_values.py`, `test_engine.py:140-202` (`switch_video_encoder` tests) stay as the guard.
- Decision records: 0014 follow-up (the closest-match fix leaves no new error), 0035; unchanged.
- Size: S; estimated lines: -30 source / -0 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the behaviour note also covers floats with more than 6 significant digits. Checked and holds: `_value_label` and `_value_text` differ only in the number branch; `_bit_depth_ops` plus `reset not in ops` equals the hand-written 10-bit block; `_int` and the try/`int()` in `x265_min_cu_size` are the same test; the six `_value_label` uses are at the listed lines.)
- Orchestrator: Tier B, work package Q-6.16 (see ../plan.md).

### VAL-10: two ways to ask "what value does x264 or x265 use for this option"
- Kind: duplication
- Where: `validation/video.py:612-631` (`_option_value`), `:633-636` (`_set_option`), `:639-695` (`video_x26x_rule_issues`); `:778-815` (`_Options`, `_Options.effective` `:806`); `:1020-1062` (`video_option_rule_issues` dispatch); `validation/encoder.py:33-50`, `:107`, `:149` (`SETTING_CODES` holds `encoder.lookahead_too_short`, `encoder.subme_needs_trellis`; `video_encoder_settings` and `template_video_settings` call `video_x26x_rule_issues`); `definitions/options.py:62-72` (`effective_option`).
- Now: three functions answer "the value the encoder uses for option `key`": `_option_value` (job value, else the preset's table value, with tune handling and an `is set` flag), `_Options.effective` (written value, else `option_default(option, preset)`), and `definitions.options.effective_option`. `_option_value` is used only by the two rules in `video_x26x_rule_issues` (x265 `lookahead_too_short`, x264 `subme_needs_trellis`); every other option rule goes through `_Options`, which also skips options the builder skips (bad value, unsupported, inactive `requires`), as `_option_value` does not. Two entry points (`video_x26x_rule_issues` in the settings rule, `video_option_rule_issues` in the option rule) each registered for jobs and templates, so four registrations carry x26x rules.
- Change: move the lookahead rule into `_x265_rules(opts, target)` and the subme rule into `_x264_rules`; read the values with `opts.effective(key)` and the "is set" flag as `key in opts.written` in place of `_option_value`. No `tune_known` parameter is needed: the x265 rule reads `bframes` and `rc-lookahead` with `tune_known=True` and applies the tune itself, and libx264 `subme` and `trellis` have `tunes = []` in the definitions (checked with `load_definitions()`), so the tune branch of `_option_value` is never taken for them. Do not give the existing `_Options.effective` a tune check: its callers' options are `fixed` or have no tune effect today, but it would change them silently if a definition changed; delete `_option_value` and `video_x26x_rule_issues`; remove `encoder.lookahead_too_short` and `encoder.subme_needs_trellis` from `SETTING_CODES` and add them to `OPTION_RULE_CODES`; delete the two `yield from video_x26x_rule_issues` lines in `encoder.py`.
- Behaviour: codes, messages and fixes unchanged. Order changes: the two issues move after `encoder.level_too_low` in the `encoder` area (they come from `advanced_option_rules`, registered in `levels.py` after `x265_level`). An option the builder skips (inactive, bad value) no longer feeds these two rules (more accurate than today).
- Contracts touched: none.
- Callers to update: `validation/video.py`, `validation/encoder.py`; `tests/validation/test_x26x_ffmpeg.py:15,59` calls `video_x26x_rule_issues(video, sc.DEFS)`: call `video_option_rule_issues(video, caps, defs)` and filter on the two codes.
- Tests: none deleted. `test_x26x_ffmpeg.py` (real x265 and x264 matrix) and `test_rules.py:504-544` (lookahead and subme cases) are the guard of unchanged behaviour. Check any test that asserts the order of encoder-area issues.
- Decision records: 0014 "Follow-up (M2 review, second round)" items 1 and 2 (the two rules and their verified x265/x264 behaviour); unchanged.
- Size: M; estimated lines: -30 source / -0 tests
- Risk: medium. The tune handling is subtle; `test_x26x_ffmpeg.py` runs the real encoders and must pass unchanged.
- Depends on: none (VAL-01 makes the diff smaller)
- Confidence: low (a refactor of verified rules for a modest gain; do it only if you want one rule engine for the advanced options)
- Verdict: ADJUSTED (the `tune_known` parameter was unnecessary, see Change; estimate -30 source. Behaviour note: the "is set" flag moves from `key in video.advanced` to `key in opts.written`, which differs only for an option the builder skips, as the finding already says. Order change in the encoder area confirmed: `lookahead_too_short` and `subme_needs_trellis` move after `encoder.level_too_low`.)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### VAL-11: the job's output geometry is computed in four places
- Kind: duplication (cross-area: command, batch, preview)
- Where: `validation/context.py:71-82` (`source_geometry`) and `:63-69` (`geometry`); `command/builder.py:190-193`; `batch/resolve.py:84-88`; `preview/graph.py:137-140`.
- Now: each place starts from `source_geometry(video_stream)`, sets `interlaced=False` when `"deinterlace"` is in the job's filters, and calls `compute_geometry(src, job.dimensions)`. validation's docstring says "as the command builder sees it".
- Change: add `job_geometry(video: VideoStream, dimensions: DimensionSettings, filters: FilterSettings) -> tuple[SourceGeometry, Geometry]` in `reframe/dimensions.py` and call it from the four places. In `context.py`, `source_geometry` and `geometry` become two reads of that tuple (or `geometry` keeps the passthrough test). The builder, preview and batch use only the `Geometry` (their `geometry_src` has no other use), so a smaller shape also works: one function `progressive_source(video, filters) -> SourceGeometry` (the `source_geometry` plus the deinterlace line) and each place calls `compute_geometry(progressive_source(video, job.filters), job.dimensions)`.
- Behaviour: unchanged.
- Contracts touched: public core API (one new function in `reframe.dimensions`).
- Callers to update: the four places above.
- Tests: add one unit test for `job_geometry` (deinterlace turns `interlaced` off); the existing tests of the four callers stay as the guard.
- Decision records: 0009 (dimension maths), 0026 (builder and validation agree).
- Size: S; estimated lines: -4 in `validation/` (about -12 across the four areas) / +10 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (anchors: `context.py:63-69` and `:71-82`, `batch/resolve.py:84-88`, `preview/graph.py:137-140`; a smaller one-function shape added. The four copies are the same code, and `reframe/dimensions.py` can import `FilterSettings` without a cycle.)
- Orchestrator: joined into X-01 (see ../cross-cutting.md); that entry decides the tier and the work package. Joined into X-01. Use the function names of CMD-01, not `job_geometry(video, dimensions, filters)`.

### VAL-12: small leftovers
- Kind: dead-code
- Where and change (each item stands alone):
  - `validation/__init__.py:83-117` and `:137-172`: the `rules=` parameter of `validate` and `validate_template` has only test callers (`test_audio_agreement.py:195`, `test_engine.py:103`, `test_template.py:417`); production passes none. Remove it and let those tests monkeypatch `JOB_RULES` / `TEMPLATE_RULES` (`test_engine.py:107` already does this for `job_rule`). About -8 source, tests change by a few lines. Two cautions. `validate` and `validate_template` read the names imported into `reframe.validation`, so patch `reframe.validation.JOB_RULES` / `TEMPLATE_RULES` (not only `registry.*`). And `validate_template(rules=...)` also turns the lint off (`if rules is None:` before `lint_defaults` and `lint_track_rules`): `test_every_template_rule_has_a_positive_case` (`test_template.py:410-420`, one rule at a time) would then pass on a lint issue for a rule with no case, so filter its issues by `registered.codes`.
  - `validation/video.py:109-182` (`switch_video_encoder(caps=None)`): both production callers pass `caps` (`_switch_fix` and `_encode_fix`); only the tests `test_option_rules.py:91` and `test_engine.py:150,166,198,202` omit it (`switch_video_encoder` is in `reframe.validation.__all__`, no caller outside tests; `_switch_fix(caps=None)` at `:191` loses its default too). Make `caps` required and remove the `None` case of `_rechecking` (`:227`) and the `if caps is not None` guard (`:162`). About -5; tests pass `sc.make_caps({})`.
  - `validation/container.py:207-213` (`_metadata_blocks`) and `validation/metadata.py:18-23` (`_blocks`): the same generator over video, audio and subtitle metadata, one skips burned-in subtitles. Make one `metadata_blocks(ctx, *, written_only=False)` in `common.py` or `metadata.py`. About -8.
  - `validation/audio.py:54`, `validation/container.py:92`, `:161`, `validation/subtitles.py:28` (`_drop`): the fixes "Remove this audio track" and "Remove this subtitle track" are built in four places. One helper `drop_track(kind, index)` in `common.py`. About -8.
  - `validation/subtitles.py:179` (`bitmap_copy`) and `:230-233` (`conversions`): the test "can burn" (`not video.passthrough and not any burn`) is written twice. One helper `can_burn(ctx)`. About -4.
  - `validation/video.py:1285-1348` (`video_container_issues(passthrough_known=...)`): a flag argument that only tells a template (no source) from a job. Let `template_video_codec` return `[]` for passthrough before the call and `video_codec` do the same when the source has no video stream; then drop the parameter. About -3.
  - `validation/audio.py:179-186` (`_dropped_as_upmix`): builds a copy of the encoder with every mixdown listed (`encoder.model_copy(update={"mixdowns": ...})`) to learn whether the no-upmix rule dropped the mixdown. Split the first four lines of `definitions/models.py:AudioEncoderDef.snap_mixdown` (the no-upmix step) into a public `drop_upmix(requested, source_channels, mixdowns)` and call it here. About -8 in validation (+3 in definitions).
- Behaviour: unchanged.
- Contracts touched: public core API for the `rules=` removal (core internal only; no caller outside tests), for `switch_video_encoder(caps=)` becoming required, and for `drop_upmix` (new).
- Tests: `test_engine.py:96-105` (failing rule test), `test_audio_agreement.py:195` (restricts the rule list to encoder, container and audio), `test_template.py:417` change to use `monkeypatch`; the `switch_video_encoder` tests pass a caps snapshot. All other tests stay.
- Decision records: none apply.
- Size: S; estimated lines: -33 source / -5 tests
- Risk: low.
- Depends on: none
- Confidence: medium (each item is small; the `rules=` removal makes the agreement test a little longer)
- Verdict: ADJUSTED (the `next_free_path(limit=)` item is rejected: the keyword is how `test_paths.py:149` reaches the overflow branch without 9999 fake files, and a constant would need a monkeypatch for -2 lines; item 1 had a hidden coupling, the lint switch; item 3 touches an exported name. The other items hold: `_dropped_as_upmix` equals the first step of `snap_mixdown`, `can_burn` and the drop fixes are repeated as described, `passthrough_known` is set only by `video_codec` as `stream is not None`.)
- Orchestrator: Tier B, work package Q-6.16 (see ../plan.md).

### VAL-13: decision-change: the charset cache of `LocalFileSystem` (0065 FA item 1, 0070 task A item 1)
- Kind: decision-change
- Where: `validation/fs.py:27` (`_CHARSET_CACHE`), `:89-148` (the Windows `ctypes` block `_FileBasicInfo`, `_kernel32`, `_change_time`, and the POSIX `_change_time` at `:147`), `LocalFileSystem.__init__` (`_charsets`, `_lock`), `:210-240` (`text_charset`); `threading` and `functools.cache` imports; `tests/validation/test_text_charset.py:30-40` (`test_a_file_saved_again_with_the_same_size_and_time_is_read_again`) and `:43-56` (`test_an_unchanged_file_is_read_once`).
- Now: `text_charset` keeps the answer per path, device, inode, size, mtime and change time for 256 files, so an edit's validation "costs a `stat`" (0065 FA item 1). On Windows `st_ctime` is the creation time, so 0070 task A item 1 added about 55 lines of `ctypes` (`GetFileInformationByHandleEx`, `FILE_BASIC_INFO.ChangeTime`) only to make the cache key right. `reframe.textfile.read_charset` reads at most 16 MiB (`ENCODING_SAMPLE`) and does `isascii` plus one UTF-8 incremental decode; for a normal subtitle file (a few hundred KB) this takes about a millisecond.
- Change: what would have to be true: a validation that reads every external text subtitle again on each edit is fast enough. Measure `read_charset` for the largest realistic file (an ASS file with embedded fonts, a few MB) before deciding, also on a network share (SMB or NFS, which 0070 tests): without the cache every validation after an edit reads each external text subtitle in full over the network, and a season has one file per episode. The `ctypes` block and `_change_time` are Windows-only code (`# pragma: no cover`): removing them needs one run of `test_text_charset.py` on the Windows test VM. If yes: delete the cache, the lock, `_change_time` (both versions), the `ctypes` block and the two cache tests; `text_charset` becomes `read_charset(path)` in a `try/except (OSError, ValueError)`. If large files matter, lower `ENCODING_SAMPLE` for validation (a different sample size changes detection of a bad byte late in the file; not recommended) instead.
- Behaviour: unchanged results; more reads per validation (one read per external text subtitle per edit).
- Contracts touched: none.
- Callers to update: `validation/fs.py` only.
- Tests: delete the two cache tests; `test_what_is_not_a_readable_file_has_no_encoding`, `test_a_fifo_named_like_a_subtitle_file_does_not_block_validation` and `test_the_encoding_of_a_file_follows_its_changes` stay.
- Decision records: 0065 FA item 1 and 0070 task A item 1 (both state the cache and its key). Update both with one line.
- Size: M; estimated lines: -75 source / -35 tests (not counted in the totals)
- Risk: medium. Validation of a job with a multi-megabyte subtitle file becomes slower on every edit in the UI; measure first.
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (test anchors `:30-40` and `:43-56`; the condition now names network shares and the Windows VM run. Checked: the `ctypes` block, `_change_time`, `threading` and `functools.cache` are used only by the cache; 0065 FA item 1 and 0070 task A item 1 state the cache and its key, so both records need the one line.)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### VAL-14: decision-change: NUL paths are handled in every layer (0016 RN)
- Kind: decision-change
- Where: in this area: `validation/__init__.py:120-135` (`_source_path_issues`, code `source.path_unusable`), `validation/output.py:191-204` (`_nul_issue`) and its use in `output_path_issues` (`:243`), `validation/dryrun.py:498-511` (the NUL block of `dry_run`), `validation/fs.py:12-18`, `:166-239` (a `has_nul` guard in 9 places of `LocalFileSystem`: `exists`, `is_dir`, `writable_dir`, `writable_file`, `free_bytes`, `same_file`, `text_charset`, `list_files`, `file_times`); `tests/validation/test_nul_paths.py` (205 code lines). Outside this area: `queue/runner.py:1030-1045` (`queue.path_unusable`), `service.py:374,416,495,656`, `queue/files.py:79-160`, `tests/test_service_nul_paths.py`.
- Now: 0016 RN says "only the API can send a path with a NUL (JSON allows `\u0000`)". Instead of refusing it once, each layer checks it and reports it as an issue (validation `output.not_writable` and `source.path_unusable`, queue `queue.path_unusable`, probe `not_found`, dry run `encoder.dry_run_skipped`). Python's `os.path.exists`, `isdir` and `isfile` already answer `False` for a NUL path (checked on 3.13), so the guards in `exists`, `is_dir`, `writable_dir` and `writable_file` do nothing; only `free_bytes`, `same_file` and `text_charset` need an `except ValueError`.
- Change: what would have to be true: a NUL character in a path may be refused as a 422 at the API (a request error), not shown as a validation issue. Then add one check to the path fields of the models (`SourceRef.path`, `OutputSettings.path`, the external subtitle path, `NamingOptions.output_folder`) and delete the rest. A smaller step that needs no decision change: in `LocalFileSystem` drop the `has_nul` guard from `exists`, `is_dir`, `writable_dir`, `writable_file` and catch `(OSError, ValueError)` in `free_bytes`, `same_file`, `text_charset` (about -12 lines, `test_nul_paths.py` stays as the guard; keep the guards in `list_files` and `file_times`, whose base class raises). Windows behaviour of the `os.path` calls with a NUL differs in places (0070: `realpath`), so run `test_python_facts_behind_the_rule` and `test_nul_paths.py` once on the Windows test VM.
- Behaviour: changes: a request with a NUL path gets a 422 instead of an issue (the full change); none for the smaller step.
- Contracts touched: persisted schema (no new field; a validator on existing path fields), HTTP/OpenAPI (a request with a NUL path gives 422; the schema text does not change; check the frontend path inputs, which cannot type a NUL).
- Callers to update: the places in "Where".
- Tests: full change: delete `test_nul_paths.py` (205 lines) and `test_service_nul_paths.py`, add one model test; smaller step: none.
- Decision records: 0016 RN (and 0070 task A "Platform expectations" NUL notes). Needs a new record.
- Size: L; estimated lines: -70 source in `validation/` and -200 tests (about -60 more outside; not counted in the totals); the smaller step: -12 / -0
- Risk: medium for the full change (one boundary replaces guards in many layers; a path field that is missed would raise `ValueError` again).
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (the guard count is 9, not 11 uses; the smaller step needs a Windows VM run; `list_files` and `file_times` keep their guards. Checked on Python 3.14.9: `os.path.exists`, `isdir`, `isfile` answer False and `os.stat`, `os.access`, `shutil.disk_usage` raise `ValueError` for a NUL path, as 0016 RN says; the decision-change is honest about needing a 422 at the API and a new record.)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

## Looked at and kept

- VAL-12 (item) `next_free_path(limit=)` as a constant: rejected in verify. The keyword is how `test_paths.py:149` tests the overflow branch without 9999 fake files; a constant needs a monkeypatch for -2 lines.
- `video.py` per-encoder rule functions (`_x264_rules`, `_x265_rules`, `_svt_rules`, `_vp9_rules`, `_min_max_conflict`): a data table in the definitions would need a new schema, loader, linter and tests, and the rules differ in shape (cross-option comparisons, tune effects, `bluray-compat` limits). It would be larger than the code it replaces.
- `video.py` `_TEXT_FORMATS` and the HDR text regexes (`_x265_master_display_problem`, `_svt_mastering_display_problem`, `_light_level_problem`): required by 0035/0068 follow-ups and checked against the real encoders in `test_option_formats_ffmpeg.py`.
- `tracks.job_fits` and `_subtitle_fits` repeat the three container rules as a test: the "Switch to" fix must add no error (0014 M2 review item 3). Running the rules instead would recurse through `switch_container`.
- `Rule.codes` declared by hand next to each rule: `test_rules.py:1553-1563` uses them for "every code has a case" (plan C-8 "every rule has a positive and a negative test"). A source scan would replace them, but the declared list is the registry contract.
- `ctx.geometry`, `ctx.source_geometry`, `range_duration`, `frame_count` follow the builder by design; `test_command_agreement.py:515-535` checks `range_duration == plan.expected_duration` (0026).
- `test_command_agreement.py` reading every `raise PlanError` from the source: required by 0014 follow-up item 3 and 0026.
- `dryrun.py` `_Attribution`, `_PARAM_PROBLEMS`, `_CONTROL_OPTIONS`, `control_names`, the tag-level parsing: recorded real encoder log behaviour (`testdata/README.md`, 0035); the 51-statement `parse_dry_run` is one pass over the log lines, and splitting it adds names, not removals.
- `output.free_of_source` loop of up to 100 names: needed when a candidate's `.part`, chapter or pass-log name is the source (0014 M2 review item 1; the `pragma: no cover` return is the only unreachable line).
- `tracks.encoded_audio` / `EncodedAudio` next to `command.planned_audio`'s `PlannedAudio`: not a 1:1 copy (`bitrate` is `None` when the track sets none; `table` and `source_channels` are added), so the wrapper does work.
- `dimensions._axes` and `_invalid_axes` re-derive which crop axes `compute_geometry` refused, and `crop` reads the geometry notes by text (`"no " in n and "crop is applied" in n`). A structured field on `Geometry` would remove this, but it changes the model that the API returns (OpenAPI and `frontend/src/api/`). Not worth the contract change.
- `audio.py` four rules each call `_encoded_tracks` (the builder's plan is made four times per validation): speed only, not simpler.
- `fs.py` Windows branches (`_can_open_for_update`, `_can_create_file`, the `ctypes` block): 0070, unit-tested with mocks on Linux. Only the cache that needs `_change_time` is questioned (VAL-13).
- `levels.X265_LEVELS` (13 rows) and `x265_level_fits`: 0014 follow-up item 4 and R5-4, checked against the real x265 (`test_levels_ffmpeg.py`).
- `__init__.py` side-effect imports with `_audio` aliases: registration by import is how the registry fills; replacing it by a loop adds no clarity.
- `container.py` `_AUDIO_PREFERENCE` tuple: HandBrake's order of fallback encoders; moving it to the definitions adds a field for one reader.
- Cross-area note for the lead, not an audit of those areas: five test fake file systems exist (`tests/validation/scenario.py:FakeFs`, `tests/naming/conftest.py:FakeFs`, `tests/naming/test_variables.py:_Fs`, `tests/batch/test_anime_season.py:SeasonFs`, `tests/validation/test_inplace.py:Answers`); the first two implement the same interface.

## Noted by the verifier (not verified)

- `packages/reframe/tests/validation/scenario.py:345` `FIXES_CHECKED` is appended to in `check_fix` (`:330`) and read nowhere; its comment promises a coverage assertion that does not exist. Delete both lines.
- `packages/reframe/src/reframe/command/filtergraph.py:116` `_is_hdr` and `:150` `is_hdr` (and `_setparams` / `colour_params`) are private and public twins that only call each other; outside this area.
