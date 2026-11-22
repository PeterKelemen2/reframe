# batch: simplification findings

Commit: 85d9dcb.
Verified: 2026-11-15, 5 confirmed, 12 adjusted, 0 rejected (one sub-item, BAT-10.4, rejected and moved to "Looked at and kept").
Scope: `packages/reframe/src/reframe/batch/` (+ `models/batch.py`, and the callers named per finding), tests in `packages/reframe/tests/batch/`. Source lines: 4683 code lines (sizes.txt: 5876 raw); tests/batch 6422 code lines (7671 raw). Read in full: every file in `batch/` (16 files), `models/batch.py`, `routers/batch.py`, the `resolve_with_tracks` / `draft_tracks` call sites in `jobs.py` and `cli.py`, plan 04, decisions 0031, 0040 (all follow-ups), 0050 items 6 and 10, 0066 (batch parts). Only skimmed: all test files (read where a finding touches them), `audio_rules.py` lines 349-460 (the `_encode` sentence builder, kept), decisions 0019, 0075.

## Summary

The area is large because three decisions fix its behaviour in detail (0031 selection reasons, 0040 relaxation, file identity, collisions, 0019 codec rules). Most of that is required and is listed under "Looked at and kept". The removable weight sits in three places. First, a set of public entry points that the plan lists but that no production code calls any more: `resolve_group`, `BatchService.resolve(group=)`, `merge_template` with `SECTIONS` / `SECTION_FIELDS` / `BatchService.merge`, `draft_tracks` (one caller), `first_of_language`, `explain`, `explain_subtitles`, `lint_defaults(source=)`. Each exists only for its own tests. Second, the "defaults compiled into rules" layer builds full `OutputTrackRule` objects that nothing evaluates, and `_explicit_audio` / `_explicit_subtitles` repeat one pipeline. Third, small duplicates (`_describe` twice, `_layout` twice, the disposition-flag role chain twice, the HDR name table four times) and 14 test files that load their helper modules with the same 11-line `importlib` hack. pylint found almost no textual duplication in `batch/`; the duplication is structural. Estimated total: about 375 source lines and about 280 test lines. Coverage (`coverage.txt`) is not usable here: it counts every `def` and import line as missed (modules were imported before measurement), so it gave no dead-code hints. No finding touches the HTTP contract except BAT-14 (one OpenAPI field removed).

## Findings

### BAT-01: Two ways to resolve "a group" that only tests call
- Kind: decision-change
- Where: `packages/reframe/src/reframe/batch/resolve.py:292-333` (`resolve_group`), its `__all__` entry (line 48), the `Mapping` / `Path` / `BatchGroup` imports it alone uses (lines 11-12, 26); `packages/reframe/src/reframe/batch/service.py:274-324` (`BatchService.resolve`: the `group` parameter at 280, `members` at 297, `prepare()` at 299-303, the `near` handling at 310-312, `group=group` at 320) and `service.py:128-137` (`_ordered`); `batch/__init__.py` (`resolve_group` in the import at line 42 and `__all__` at line 86); plan `docs/plan/04-batch-mode.md` "Core API" (the `resolve_group` line).
- Now: `resolve_group` has 0 callers in `src/` of both packages; its 7 other call sites are tests (`test_resolve.py` 143, 153, 199, 215, 242; `test_anime_season.py` 75, 267; plus the two import lines). `BatchService` does not use it: `resolve` and `resolve_batch` have their own per-file loops. The `group` parameter of `BatchService.resolve` has 0 production callers: the route `/batch/resolve` does not pass it (`routers/batch.py:155`; decision 0050 item 6 says it is not exposed), `cli.run_batch` uses `resolve_batch`. Its 4 callers are tests (`test_batch_service.py` 104, 142, 162; `jobs/test_cli_file_identity.py` 240). It only adds two things: the group's order (`_ordered` with a rank dict) and the `batch.near_match` issue. `resolve_batch` already does the near issue (covered by `tests/jobs/test_cli_batch.py:142`), and the plain episode order is what the route needs.
- Change: Delete `resolve_group` (and the imports only it uses). In `BatchService.resolve` remove `group`; replace `prepare()` / `_ordered` by `patches, ordered = await asyncio.to_thread(lambda: (_patches(overrides), sorted(_keyed(probed), key=lambda item: episode_key(item[1]))))`; delete `_ordered`; drop the `near` lines; build `BatchResolution(columns=..., rows=..., issues=...)` without `group`. Sketch of the loop:
  ```python
  for key, path, found in ordered:
      if isinstance(found, ProbeError):
          rows.append(Resolution(path=path, issues=[*template_issues, _probe_issue(found)], status="error"))
          continue
      row, _ = await self._row(chosen, found, patches.get(key), naming, template_issues, check)
      rows.append(row)
  ```
  Update plan 04 "Core API" (drop `resolve_group`) in the same commit as a short decision record (0040 section 8 names `resolve_group(…)`).
- Behaviour: unchanged for every production path (route and CLI). The `BatchResolution.group` field stays (`resolve_batch` fills it; the frontend reads `resolution.group.name`, `MatrixDialog.vue:27`).
- Contracts touched: public core API (`reframe.batch.resolve_group`, `BatchService.resolve(group=)`); no HTTP change (the route never sent `group`).
- Callers to update: tests only: `tests/batch/test_resolve.py` (143, 153, 199, 215, 242), `tests/batch/test_anime_season.py` (75, 267: use a loop `[resolve(template, sources_by_path[m.path], overrides.get(str(m.path))) for m in group.members]` in the existing `matrix()` helper), `tests/batch/test_batch_service.py` (104, 142, 162: drop `group=`; without a group E05's row is `ok` (0066: `batch/resolve` does not mark a near member), so the `statuses` assertion at 113-114 becomes `["ok"] * 10 + ["error", "ok"]` and the E05 near-match assertions at 115-119 move to a `resolve_batch` call or are dropped, since `test_cli_batch.py:142` covers it), `tests/jobs/test_cli_file_identity.py:240` (and the docstring at 230 "with a group"). In `service.py` also drop the `BatchGroup` and `GroupMember` imports (lines 31, 34) that `resolve` and `_ordered` alone use.
- Tests: delete `test_resolve_a_group` (`test_resolve.py:136-155`, the one test of `resolve_group` itself: error row for a member without a source, override keys); the other `resolve_group` uses in `test_resolve.py` (199, 215, 242) and `test_anime_season.py` (75, 267) only use it as a loop over the members, so they switch to the loop above. Keep every `resolve` / `resolve_batch` test.
- Decision records: 0040 section 8 gives `resolve_group`'s signature as the core API and plan 04 "Core API" lists it, so this is a decision change, done with a new record that amends 0040 section 8 and the plan edit. 0050 item 6 already says `group` is not exposed. What would have to be true: nobody outside tests calls `resolve_group` or `BatchService.resolve(group=)` (verified above for core, server, CLI, frontend), and plan 05 line 11 says only the `Reframe` facade and `reframe.models` are public, everything else "can change".
- Size: M; estimated lines: -40 source / -25 tests
- Risk: low. Only tests call the removed paths.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (kind is decision-change: 0040 section 8 and plan 04 name `resolve_group`; 7 call sites not 9; the `test_batch_service.py` near-match lines are 113-119 and E05's expected status changes too; `service.py` `BatchGroup` / `GroupMember` imports go as well)
- Orchestrator: Tier B, work package Q-6.15 (see ../plan.md).

### BAT-02: `merge_template`, `SECTIONS`, `SECTION_FIELDS` and `BatchService.merge` are used by tests only
- Kind: decision-change
- Where: `packages/reframe/src/reframe/batch/derive.py:47-57` (`SECTIONS`), `58-68` (`SECTION_FIELDS`), `80-92` (`merge_template`), `__all__` entries (lines 39-44, keep `as_template`, `derive_selector`, `derive_template`); `packages/reframe/src/reframe/batch/service.py:245-249` (`BatchService.merge`) and the `merge_template` import (line 25); `batch/__init__.py` (lines 12-18 import list, `"SECTIONS"`, `"merge_template"` in `__all__`); plan `docs/plan/04-batch-mode.md` "Core API" (`merge_template` line).
- Now: `merge_template` has one caller in `src/`: `BatchService.merge`, a one-line pass-through that vulture reports unused (`vulture.txt:118`). `BatchService.merge` has 0 callers in `src/` of both packages; decision 0050 item 10 and plan 06 line 232 say it is not exposed because `batch/derive` with `base` covers *Apply to group*. `derive_template` does not call `merge_template`; it builds its own `update` dict. `SECTION_FIELDS` is read only by `merge_template` and by one test; `SECTIONS` only by `merge_template` and two tests. Tests call them: `test_derive.py:148, 239-255`, `test_batch_service.py:89, 274`.
- Change: Delete the four items. `TemplateSection` (the model `Literal`, `models/batch.py:42`) stays: it is the request type of `/batch/derive`. In `test_derive.py:148` use `set(get_args(TemplateSection))` for "every section". In `test_batch_service.py:89` replace `app.batch.merge(template, JobTemplate(naming=A.EXAMPLE_NAMING), {"naming"})` with `template.model_copy(update={"naming": A.EXAMPLE_NAMING})`; at line 274 use `derived.model_copy(...)` or drop the merge assertion. Remove the plan 04 line `def merge_template(...)`.
- Behaviour: unchanged (no production path used it).
- Contracts touched: public core API (`reframe.batch.merge_template`, `SECTIONS`, `BatchService.merge`); no HTTP change.
- Callers to update: `tests/batch/test_derive.py` (imports 13, 16-17, 21; test at 236-254), `tests/batch/test_batch_service.py` (89, 274); the comment at `frontend/src/components/batch/clipboard.ts:27` ("the core's `SECTION_FIELDS`"): the frontend's own `SECTION_FIELDS` / `SECTIONS` stay and become the only list, so reword the comment (frontend text only, no code).
- Tests: delete `test_merge_takes_only_the_sections`; its last assertion (`as_template` drops preset-only fields) is also covered where `derive_template` is tested with a preset base; keep one such assertion if it is not.
- Decision records: 0040 section 8 ("`merge_template` as 04 says") and "Open product questions" item 5 (0040:293 names `derive.SECTION_FIELDS`: "Output options are in no *Apply to group* section"; after the change that fact is the `TemplateSection` literal plus the body of `derive_template`), plan 04 "Core API" line 231, 0050 item 10 (already says `batch.merge` is not exposed), 0066 line 28 (about the behaviour that `_kept_required` fixed; does not need the function). So this is a decision change: a plan 04 edit plus a short decision record. What would have to be true: nothing outside tests calls `merge_template` / `batch.merge` (verified for core, server, CLI; the frontend merges sections itself in `clipboard.ts`), and plan 05 line 11 says only the facade and `reframe.models` are public.
- Size: S; estimated lines: -34 source / -20 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (kind is decision-change: 0040 section 8 and plan 04 name `merge_template`; the frontend comment at `clipboard.ts:27` and 0040:293 mention `SECTION_FIELDS`; test is at 236-254)
- Orchestrator: Tier B, work package Q-6.15 (see ../plan.md).

### BAT-03: Wrappers with no production use: `draft.py`, `explain`, `explain_subtitles`, `first_of_language`
- Kind: dead-code
- Where: `packages/reframe/src/reframe/batch/draft.py:1-58` (whole file: `draft_tracks`, `first_of_language`); `packages/reframe/src/reframe/batch/explain.py:253-271` (`explain`) and `631-651` (`explain_subtitles`); `batch/__init__.py` (`draft_tracks`, `first_of_language`, `explain`, `explain_subtitles` in imports and `__all__`); `packages/reframe/src/reframe/jobs.py:20` and `646-650` (the one production use of `draft_tracks`); plan `docs/plan/05-core.md:538` (`explain(defaults, source) -> list[TrackDecision]`).
- Now: `draft_tracks(source, template, *, definitions, languages)` is `resolve_tracks(template, source, definitions=..., languages=...).draft`. Its one production caller is `JobService.explain` (`jobs.py:649`). `first_of_language(streams)` has 0 production callers; the real logic is written inline twice (`explain.py:146-159`, `rules.py:501-525`); only `test_draft.py:193-194` calls the list version. `explain` and `explain_subtitles` are `audio_stage(...).decisions` / `subtitle_stage(...).decisions`: 0 callers outside tests (`test_explain.py:132, 159, 289, 302, 314` and `576, 674, 682`). The server's `/jobs/explain` goes through `JobService.explain`, not `batch.explain`.
- Change: Delete `draft.py`, `explain()` and `explain_subtitles()`. In `jobs.py:648-650` the call is `asyncio.to_thread(draft_tracks, media, chosen, definitions=..., languages=...)` (positional `media, chosen`, the reverse of `resolve_tracks(template, source)`), so make it `asyncio.to_thread(lambda: resolve_tracks(chosen, media, definitions=self.definitions, languages=languages).draft)` (import `resolve_tracks` from `reframe.batch.rules`). Tests: `draft_tracks(media, template, ...)` becomes `resolve_tracks(template, media, ...).draft` (argument order differs); `explain(d, s, ...)` becomes `audio_stage(d, s, ...).decisions`; `explain_subtitles(...)` becomes `subtitle_stage(...).decisions`. Plan 05 line 538: say that `audio_stage` / `subtitle_stage` give the decisions and `JobService.explain` feeds the preview.
- Behaviour: unchanged.
- Contracts touched: public core API (`reframe.batch.draft_tracks`, `explain`, `explain_subtitles`, `first_of_language`); no HTTP change.
- Callers to update: `jobs.py:20, 649`; tests: `tests/batch/test_main_tracks.py` (7 call sites of `draft_tracks`: 76, 128, 140, 203, 241, 255, 263), `test_explain.py` (`draft_tracks` 15 call sites plus the import at line 15, `explain(` 7, `explain_subtitles(` 3), `test_selection_properties.py:15, 261`, `test_lint.py:15, 358`, `test_rules.py:17, 451`, `tests/presets/test_builtin.py:612-621`, `tests/batch/test_explain_media.py:11, 71, 89`, `tests/jobs/test_service.py:15, 91`, `test_draft.py` (7 call sites; rename to a test of `resolve_tracks`; delete the `first_of_language` test at 178-194).
- Tests: only mechanical edits; the behaviour tests all stay. Delete the `first_of_language` assertion test.
- Decision records: 0040 section 1 ("`draft_tracks` is now a thin wrapper"), 0017 line 37, 0031 section 6 mention `draft_tracks` by name as history; no behaviour requirement. Plan 05 line 538 lists `explain(defaults, source) -> list[TrackDecision]` for C-12 ("It feeds the live preview": the preview in fact goes through `JobService.explain`), and `docs/status.md:69` names `explain` / `explain_subtitles` / `draft_tracks` as built; edit both in the same commit with a short decision record. Plan 05 line 11 ("everything else is internal and can change") makes this allowed.
- Size: S; estimated lines: -47 source / -5 tests
- Risk: low
- Depends on: none (do it before BAT-07, which also edits tests that call `lint_defaults`).
- Confidence: high
- Verdict: ADJUSTED (two more caller files: `tests/batch/test_explain_media.py` and `tests/jobs/test_service.py`; the `jobs.py` call goes through `asyncio.to_thread` with positional args, so it needs a lambda; plan 05:538 and `status.md:69` edits)
- Orchestrator: Tier B, work package Q-6.15 (see ../plan.md).

### BAT-04: The compiled defaults build full `OutputTrackRule`s that nothing evaluates
- Kind: decision-change
- Where: `packages/reframe/src/reframe/batch/rules.py:79-87` (`CompiledGroup`, `_SORT_OF_TIE_BREAK`), `171-188` (`CompiledRule.rule`), `190-249` (`compile_defaults`), `318-324` (`_slot`), `260-315` (`_attribute` calls `_slot`), `resolve.py:226-231` (`_part`, unchanged); plan `docs/plan/04-batch-mode.md:104-113`; decision 0040 section 1 bullet "No explicit rules".
- Now: `compile_defaults` builds an `OutputTrackRule` per part (selector with `languages` / `exclude_roles` / `roles` / `sort`, `multiple`, `settings=AudioCodecRules(...)`, `required=False`). The decision says these rules "only name the columns and show where each track came from". The only read of `CompiledRule.rule` in production is `_slot`, which looks for `"und"` in `rule.rule.selector.languages` (set by `compile_defaults` itself at line 225-226). `compiled_rules_moved` compares `(group, slot)` only; `_attribute` uses `group`, `slot`, `language`, `words`. The frontend and the server get `MatrixColumn.label` and `TrackMatch.defaults`, never the compiled rule. The rule selectors are checked only by `test_rules.py:298-347`. So about 30 lines (selectors, `AudioCodecRules` settings, `extras`, `sort`, `_SORT_OF_TIE_BREAK`) exist to model something that is never run. Plan 04 says the defaults "compile into `OutputTrackRule`s ... one rule engine"; the real engine is the selection stage, as 0040 says.
- Change: Replace `CompiledRule.rule` by what is used. New shape:
  ```python
  @dataclass(frozen=True, slots=True)
  class CompiledRule:
      kind: Kind
      group: CompiledGroup
      words: str
      slot: int | None = None
      language: str | None = None
      first_language_und: bool = False   # the first language's rule also takes undetermined tracks
  ```
  `compile_defaults` then creates `CompiledRule(kind, "language", language_code(tag), slot, tag, slot == 0 and selection.undetermined == "first_language")`, `CompiledRule(kind, "no_match", "no listed language")`, and so on, with no `TrackSelector`, no `AudioCodecRules`, no `rule()` closure, no `extras`, no `sort`. `_slot` becomes `language_slot(effective_language(stream), listed, "first_language" if rule.first_language_und else "other")`. Delete `_SORT_OF_TIE_BREAK` and the imports that become unused in `rules.py`: `_EXTRA_ROLES` (line 36) and `TrackRole` (line 55; its only use is the foreign-audio selector at line 245). `TrackSelector` and `AudioCodecRules` stay (used by `_selector_source`, `_target`, `_explicit_audio`). Edit plan 04 lines 104-113 and 0040 section 1 via a new decision record: "the defaults compile into matrix columns (one per part), not into `OutputTrackRule`s".
- Behaviour: unchanged (columns, cells, messages, `compiled_rules_moved` are the same).
- Contracts touched: none outside core internals (`reframe.batch.compile_defaults` is exported from `batch/__init__.py` but imported only by `resolve.py` and `test_rules.py`; changes its return type's attributes).
- Callers to update: `batch/resolve.py:257-258` (uses `_part`, no change), `tests/batch/test_rules.py:298-347` (`test_compiled_defaults_without_languages`, `test_compiled_defaults_with_every_part`).
- Tests: in those two tests drop the `rule.rule.multiple`, `.required`, `.settings`, `.selector.*` assertions (about 15 lines); keep the label and `words` assertions and `test_every_selected_track_is_in_its_compiled_column`, which guard the real behaviour.
- Decision records: 0040 section 1 and plan 04 say "compile into `OutputTrackRule`s". The decision itself already says the selector cannot express the rules. What would have to be true to change it: nobody reads a compiled rule as data (verified: server, frontend, CLI do not). If the UI (F-13 follow-ups) later wants to turn a compiled column into an editable explicit rule, that conversion can be written then from the selection settings.
- Size: M; estimated lines: -30 source / -15 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (plan 04 paragraph is lines 103-113; `CompiledRule.rule` is read only by `_slot`; `compiled_rules_moved` compares `(group, slot)` only)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-05: `_explicit_audio` and `_explicit_subtitles` repeat one pipeline
- Kind: duplication
- Where: `packages/reframe/src/reframe/batch/rules.py:493-595` (`_explicit_audio`) and `598-679` (`_explicit_subtitles`), plus `_settings_issue` (462-469), `_no_track_cell` (472-481), `_KindResult` (484-490).
- Now: both functions do the same steps: `describe_kind`, `rule_label` per rule, `match_rules`, a loop over picks with the "settings of the other kind" check (`_settings_issue` + `_no_track_cell`), a `_Taken` record per source track (`how.append(_how(...))`), `_defaults_flag`, grouping outputs by source stream into `by_stream` (lines 561-563 and 648-650), then a loop over the source tracks that builds either the "No track rule takes this track" decision (570-574 and 656-665) or a selected `TrackDecision` with `selection="; ".join(how)`, `reason=". ".join(reasons)`, and the columns line (594 and 678). Only the middle differs (codec rules and fixed audio settings vs a subtitle output). About 45 of the 180 lines are the repeated frame.
- Change: One generic driver with the per-kind part as a function:
  ```python
  def _explicit(kind, rules, source, produce, eligible_of, decision_extra) -> _KindResult: ...
  ```
  where `produce(pick, rule, label, track, taken) -> list[_Output]` is the audio or subtitle body (the `for track in pick.tracks:` loop body), `eligible_of(produced)` gives `[True] * n` for audio and `action != "burn"` for subtitles, and `decision_extra(found, outputs)` supplies `rule` / `measure` / the default note for audio. Keep `_Taken`, `_defaults_flag`, `_how` as they are. Merge the two `"No track rule takes this track"` blocks into one `_unselected(index, kind)`.
- Behaviour: unchanged. All reason strings, notes and decision order must stay byte-identical; `test_rules.py`, `test_anime_season.py` (snapshot), `test_batch_properties.py` and the CLI batch tests are the guard.
- Contracts touched: none
- Callers to update: `rules.py:721, 741` only.
- Tests: no change; they guard the behaviour.
- Decision records: 0040 sections 1-2 (behaviour kept).
- Size: M; estimated lines: -20 source / 0 tests (the driver needs a generic signature and two nested `produce` callbacks, which eat part of the 45 repeated frame lines; the audio side also carries the `seen` / `first_of` state)
- Risk: medium. Many strings; a missed note changes `reframe plan` output.
- Depends on: BAT-04 (both edit `rules.py`; do BAT-04 first so the diff stays small).
- Confidence: low-medium (the exact saving depends on how the driver is written; skip it if the result reads worse than two plain functions)
- Verdict: ADJUSTED (estimate -35 is too high, about -20; confidence lowered)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-06: 14 test files load shared helper modules with the same `importlib` hack
- Kind: tests
- Where: `def _load` (11 lines, same body) in `packages/reframe/tests/batch/` at `test_anime_season.py:35`, `test_batch_properties.py:40`, `test_grouping.py:35`, `test_lint.py:46`, `test_batch_service.py:36`, `test_derive.py:46`, `test_main_tracks.py:39`, `test_explain.py:48`, `test_descriptors.py:42`, `test_file_identity.py:32`, `test_resolve.py:30`, `test_selection_properties.py:35`, `test_selection.py:32`, `test_rules.py:50`; the helper modules `packages/reframe/tests/batch/anime.py` (163 lines) and `packages/reframe/tests/batch/defaults_tracks.py` (111 lines); 15 alias lines such as `audio: Callable[..., AudioStream] = T.audio` (`test_explain.py` 4, `test_lint.py` 2, `test_main_tracks.py` 3, `test_selection_properties.py` 3, `test_selection.py` 3).
- Now: pytest runs with `--import-mode=importlib` (`pyproject.toml:95`), so a test file cannot import a sibling module. Each file therefore loads `anime.py` or `defaults_tracks.py` with `spec_from_file_location` (10 lines plus 3 imports: `importlib.util`, `sys`, `ModuleType`), and re-types the helpers it uses because the loaded module is untyped. About 14 lines per file, about 195 in total. `testing/reframe_testing/` already exists for exactly this (it is on `mypy_path`, `known-first-party` and is imported as `from reframe_testing import media`).
- Change: Move `anime.py` to `testing/reframe_testing/anime_season.py` and `defaults_tracks.py` to `testing/reframe_testing/tracks.py`; in each test file replace `_load` and the aliases with `from reframe_testing import anime_season as A` / `tracks as T`. In the moved `anime.py` fix `ROOT = Path(__file__).resolve().parents[4]` (becomes `parents[2]`) and `PRESET_FILE` (keep the JSON in `packages/reframe/tests/batch/data/` and build its path from `ROOT`, or move it to `testdata/batch/anime-season.preset.json`; update the `__main__` docstring line and docs 0040 section 9 / 0068 that name the file). Optional second step in the same pass: the stream builders `audio` / `subtitle` / `video` / `source` repeat in `test_selectors.py:31-37`, `test_descriptors.py:57-71`, `test_grouping.py:108-130` with slightly different defaults, and `summary()` is defined twice (`test_audio_rules.py:83`, `test_explain.py:69`), `_codes` / `codes` three times, `_replace` twice; merge only the identical ones (about -30 more lines).
- Behaviour: unchanged (tests only).
- Contracts touched: none. Cross-area: the same `_load` hack exists in `tests/validation/` (test_hdr_ffmpeg, test_nul_paths, test_no_mkvtoolnix, test_inplace, test_template, test_custom_params_*, test_dryrun_ffmpeg, test_paths, test_inplace_fs) and `tests/models/test_roundtrip.py`; a shared `reframe_testing` module would remove those too (another area's agent).
- Callers to update: the 14 test files above, plus `tests/jobs/test_cli_batch.py` (its own 11-line `_load_anime` at line 26 loads `tests/batch/anime.py` by path; it also reads `A.PRESET_FILE` at 67 and 76, so it must move too or the old file stays), `tests/batch/test_lint.py:519` (builds the preset JSON path with `Path(__file__).with_name("data")`; it breaks if the JSON moves), `docs/decisions` references to the old paths (0040:255 names `packages/reframe/tests/batch/data/anime-season.preset.json`, 0068:410) are history and can stay.
- Tests: all stay; only their imports change. `uv run pytest packages/reframe/tests/batch packages/reframe/tests/jobs/test_cli_batch.py` and `uv run mypy` must stay green. The moved modules join `testing/` in the ruff and mypy targets (already typed).
- Decision records: 0004 (shared test infrastructure lives in `testing/` as `reframe_testing` because `--import-mode=importlib` cannot import sibling test modules): this change is what 0004 asks for.
- Size: M; estimated lines: -0 source / -195 tests (-225 with the optional second step)
- Risk: low
- Depends on: none (do it first or last; it touches the imports of every test file that other findings also edit)
- Confidence: high
- Verdict: ADJUSTED (a 15th consumer, `tests/jobs/test_cli_batch.py`, also loads `anime.py` and reads `PRESET_FILE`; `test_lint.py:519` uses the JSON path)
- Orchestrator: joined into X-04 (see ../cross-cutting.md); that entry decides the tier and the work package.

### BAT-07: `lint_defaults(source=…)` duplicates the "used rules" logic of `resolve_tracks`
- Kind: dead-code
- Where: `packages/reframe/src/reframe/batch/lint.py:426-462` (`lint_defaults`), `360-423` (`lint_rules`), import `audio_stage` (line 15); `rules.py:760-770` (the production "used" computation); `validation/__init__.py:158-163` (the one production caller).
- Now: `lint_defaults(defaults, *, container, source, definitions, preferred_languages, container_codecs)` runs `audio_stage` on `source` to compute the used rules, then calls `lint_rules`. The only production caller (`validation/__init__.py:158`) passes neither `source` nor `preferred_languages`. The real "rule unused" lint comes from `resolve_tracks`, which computes the same `used` set (`rules.py:762-763`) and calls `lint_rules` directly. A third copy of the three-line `used` computation is in `tests/batch/test_rules.py:441-443`. So `lint_defaults` is `lint_rules` plus a test-only path, and `lint.py` imports `explain` only for that path.
- Change: Delete the old `lint_defaults`; rename `lint_rules` to `lint_defaults` (same parameters: `defaults, *, container, definitions, used, container_codecs`); drop the `audio_stage` import; update `rules.py:764` and `validation/__init__.py:11, 158`. Tests that used `source=`: use `resolve_tracks(JobTemplate(audio_defaults=...), media, languages=LanguageSettings(preferred_audio=[...])).draft.issues` and filter on the code, or call `lint_defaults(..., used={...})` for the pure cases.
- Behaviour: unchanged (production never passes `source`).
- Contracts touched: public core API (`reframe.batch.lint_defaults` loses two keywords).
- Callers to update: `rules.py:33, 764`, `validation/__init__.py:11, 158`, `tests/batch/test_lint.py` (350-385 use `source=` / `preferred_languages=`; line 399 uses `lint_rules`), `tests/batch/test_rules.py:22, 447`, `batch/__init__.py`.
- Tests: rewrite the two tests `test_rules_this_source_does_not_use` and `test_unused_uses_the_selection_and_settings` against `resolve_tracks`; they keep their assertions (they check `defaults.rule_unused`).
- Decision records: 0031 section 6 ("`defaults.rule_unused`: with a source"): still produced by the job path. Update the section title note: the lint's entry point is `lint_defaults(defaults, used=...)`. Also drop the `MediaSource` import in `lint.py` (line 36; only `lint_defaults(source=)` uses it).
- Size: S; estimated lines: -18 source / -5 tests
- Risk: low
- Depends on: BAT-03 (both rewrite the same `draft_tracks` test calls)
- Confidence: high
- Verdict: CONFIRMED (`validation/__init__.py:158` passes neither `source` nor `preferred_languages`; `lint.py` also loses its `MediaSource` import)
- Orchestrator: Tier A, work package Q-6.6 (see ../plan.md).

### BAT-08: `resolve` and `resolve_with_tracks` are two functions for one job
- Kind: layering
- Where: `packages/reframe/src/reframe/batch/resolve.py:158-223` (`resolve`, `resolve_with_tracks`); `packages/reframe/src/reframe/jobs.py:21, 286-294` (`draft_from_preset`, the only caller of `resolve_with_tracks`).
- Now: `resolve` is a 12-line wrapper that calls `resolve_with_tracks` and drops the second value. `resolve_with_tracks` returns `(Resolution, TrackResolution)`; its docstring says the `TrackResolution` carries "the matrix columns of the patched template and the track draft". The columns have no reader (`matrix_columns` calls `resolve_tracks` itself); the only use of the second value is `tracks.draft` in `draft_from_preset`. For a plain preset (no override) `resolution.issues` equals `tracks.draft.issues`, and `resolution.decisions` / `subtitle_decisions` / `notes` are the same lists. So the second return value only saves one `TrackDraft(...)` construction.
- Change: Merge into one `resolve(...) -> Resolution` (move the body of `resolve_with_tracks` into it, keep the `container_codecs` flag until BAT-12). In `draft_from_preset` call `resolve(...)` and build `TrackDraft(audio=job.audio, subtitles=job.subtitles, decisions=r.decisions, subtitle_decisions=r.subtitle_decisions, issues=r.issues)`; keep its return type `(job, TrackDraft, notes)` so its callers (`job_from_preset`, `JobService._compose`, `cli.py:1325`, `tests/batch/anime.py:67`, `test_descriptors.py:339`) do not change.
- Behaviour: unchanged.
- Contracts touched: core internals; `jobs.py` (other area) changes by about 4 lines. Cross-area note: `cli.py:1325-1345` (`OwnerJobs.draft`) and `jobs.py:372-391` (`JobService.draft`) both rebuild a `JobDraft` from `draft_from_preset` output with the same six-line "keep errors and `batch.*` issues" filter; one shared function would remove that copy (jobs / cli area).
- Callers to update: `jobs.py:21, 286`, `batch/service.py:27` (imports `resolve`: no change).
- Tests: none change.
- Decision records: 0040 section 1 (one way to make a job from a template: still true); 0040 lines 348 and 470 name `resolve_with_tracks` as history.
- Size: S; estimated lines: -22 source / 0 tests
- Risk: low
- Depends on: none (do before BAT-12)
- Confidence: high
- Verdict: CONFIRMED (for a preset with no override `resolution.issues` / `decisions` equal `tracks.draft`'s; `TrackResolution` import in `resolve.py` also goes)
- Orchestrator: Tier A, work package Q-6.6 (see ../plan.md).

### BAT-09: Small duplicates inside `batch/`
- Kind: duplication
- Where and change, each a separate small edit:
  1. `rules.py:450-459` (`_describe_audio`) is identical to `audio_rules.py:540-549` (`_describe`). Keep one (make the `audio_rules` one public, `describe_output`) and import it in `rules.py`. About -10.
  2. `rules.py:136-138` (`_layout`) equals `audio_rules.py:158-160` (`_layout_label`); `defs.mixdowns.get(...)` fallback never triggers because `Mixdown` is a literal of the definitions. Make `_layout_label` public and import it. About -3.
  3. `audio_rules.py:485-489` (`snap_note`) is a wrapper with the same signature as `_snap_note` (492-504); one external caller (`lint.py:282`). Rename `_snap_note` to `snap_note` and delete the wrapper. About -5.
  4. `descriptors.py:136-147` (`_flag_extra_role`) repeats the disposition chain at the end of `selection.py:160-178` (`extra_role`): comment, visual_impaired/descriptions, clean_effects, same order. Add `flag_extra_role(stream) -> tuple[TrackRole, str] | None` to `selection.py` (evidence strings `"disposition comment"` etc. already there), call it from `extra_role` and from `stream_roles` (take `[0]`), delete `_flag_extra_role` in `descriptors.py` (`stream_roles` keeps its own use of `_EXTRA_ROLES`). About -10.
  5. The stream language `value = stream.language_ietf or stream.language; (languages.normalize(value) or value) if value else None` is in `descriptors.py:216-217` and `resolve.py:62-63` (video streams). `effective_language` (metadata.py:30) does the same for audio and subtitles and also skips a broken `language_ietf`. Widen its parameter to include `VideoStream` and use it in both places. About -4. Behaviour changes only for a video stream with a broken `LanguageIETF` and a valid `language` (it now keeps the valid language instead of the broken tag); say so in the commit.
  6. The triple `lang` / `lang_name` / `lang_native` is built four times: `audio_rules.py:562-566`, `rules.py:373-375`, `387-389`, `406-410`. Add `language_values(language) -> dict[str, Value]` in `metadata.py`. About -4.
  7. `explain.py:76-77` `_track` equals `selection.py:227-228` `_track`; import one. About -3.
  8. `language_label` (`selection.py:151-153`) is `languages.english_name`; `language_code` (`descriptors.py:173-175`) is `languages.to_matroska_legacy`. Both are one-line wrappers used in 5 modules (`explain`, `lint`, `rules`, `selection`, `descriptors`/`rules`). Replace with the library calls. About -8; do this only if the call-site edits are acceptable.
  9. `{source_codec}` is computed two ways: `audio_rules._source_label` (passthru table label, `audio_rules.py:163-168`) for codec-rule tracks, `descriptors.codec_label` (`CODEC_LABELS`) for fixed-settings tracks (`rules._audio_values`, line 380). They can differ when `display_codec` is empty. Decide on one; this one changes a name template result in that edge, so leave it for the owner to decide and do not count it in the estimate.
- Now: each item is a verbatim or near-verbatim copy; none has its own tests.
- Behaviour: unchanged except item 5 (edge case) and item 9 (not done unless chosen).
- Contracts touched: none for items 1-4 and 6-8 (`snap_note` stays exported under the same name). Item 5 is not contract-free: in its edge case (a video stream with a broken `LanguageIETF` and a valid `language`) the video track's language in the job (`video_metadata`, so the `-metadata:s:v` language in the encode command) and `TrackDescriptor.language` of that video track change, which reaches the `/batch/group` response and `reframe batch --json`.
- Callers to update: the files named in each item; `lint.py` import of `snap_note` stays valid.
- Tests: none change except where a test imports a renamed private name (`grep -rn "_describe\|_layout_label\|_snap_note" tests/batch`: 0 hits).
- Decision records: none.
- Size: S; estimated lines: -36 source (items 1-8) / -2 tests
- Risk: low (item 5: low-medium, an edge behaviour)
- Depends on: BAT-04 and BAT-05 touch `rules.py` too; do this one after them.
- Confidence: high for items 1-4, 6, 7; medium for 5 and 8
- Verdict: ADJUSTED (items 1-4, 6-9 verified as stated; item 5's "Contracts touched: none" is wrong in its edge case: the video language in the encode command and in the `TrackDescriptor` API model changes)
- Orchestrator: Tier A, work package Q-6.6; part of it is joined into X-08 (see ../cross-cutting.md). Items 1-4 and 6-8 are Tier A (Q-6.6). Item 5 (video language) is joined into X-08 (Tier B). Item 9 is not done.

### BAT-10: Small dead items
- Kind: dead-code
- Where and change:
  1. `metadata.py:17-27` `NAME_TEMPLATE_VARIABLES` (and its entries in `metadata.py:15` `__all__`, `batch/__init__.py:31, 50`): 0 references in `src/`, tests, `scripts/`, the frontend and the docs besides its own definition. Delete. About -13.
  2. `lint.py:48-56` `CODES`: used only by two assertions (`test_lint.py:92, 428`). Delete it and the two assertions. About -9 source / -2 tests.
  3. `service.py:167, 173, 175-179` (`BatchService(definitions=...)`, `_definitions`, the lazy `definitions` property): 0 callers pass `definitions=` (`service.py:994`, `cli.py:1486`, `test_cli_output_names.py:249`). `load_definitions()` is `@cache`d (`definitions/loader.py:105`), and every function it feeds already does `definitions or load_definitions()`. Delete the parameter and property, pass `definitions=None` through (3 sites: `service.py:317, 399, 436`). About -10.
  4. (Dropped in verify, see "Looked at and kept": `select_tracks`'s `kind` inference.)
  5. `grouping.py:97-99` `episode_label` (single file): 0 production callers; 3 test uses (`test_grouping.py:71, 75, 76`). Delete; tests use `episode_labels([path], season=...)[0]`. About -4 / -1.
  6. `batch/__init__.py` re-exports 45 names (`__all__`); 9 are imported from the package by nobody (src, tests, scripts, server; checked with an AST scan of `from reframe.batch import ...` in `packages/`, `testing/`, `scripts/`, `desktop/`): `MATCH_LEVELS`, `NAME_TEMPLATE_VARIABLES`, `NEAR_MAX_DIFFERENCES`, `PASSTHRU`, `Selection`, `TrackResolution`, `audio_stage`, `episode_key`, `subtitle_stage`. Remove them from the import list and `__all__` (tests import them from their modules). About -15.
- Now: found with `rg -w` over `packages/`, `testing/`, `scripts/`, `frontend/src` (counts above).
- Behaviour: unchanged.
- Contracts touched: public core API (names only).
- Callers to update: as named per item.
- Tests: as named (about -5 lines).
- Decision records: none.
- Size: S; estimated lines: -51 source / -5 tests (item 6 overlaps the `__init__` edits of BAT-01 to BAT-03; count once)
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (item 4 rejected: the inference is test-only, but `run()` in `test_selection.py` is generic over audio and subtitle streams and 32 tests call it, plus `test_main_tracks.py` 87-111 and `test_selection.py:465`, so the one-line inference only moves into the test helper: net about -1 line; `__all__` has 45 names not 41; items 1-3, 5, 6 verified)
- Orchestrator: Tier A, work package Q-6.6 (see ../plan.md).

### BAT-11: `ForeignAudio` carries four fields nobody reads
- Kind: dead-code
- Where: `packages/reframe/src/reframe/batch/explain.py:274-287` (`ForeignAudio`), `331-395` (`foreign_audio_search`, three `ForeignAudio(...)` constructions at 343-345, 348-356, 382, 384-395).
- Now: production reads `foreign.track`, `foreign.forced_only` and `foreign.note` (`explain.py:455, 563, 579, 600`; `rules.py:272-275`). `audio_language` and `user_language` are never read anywhere (only passed to the constructor, 4 times). `searched` is read only by tests (`test_explain.py:532, 543, 550, 710` and `tests/probe/test_roles_empty_subtitles.py:72`; vulture flags it, `vulture.txt:117`). `evidence` is read by one test (`test_explain.py:471`); production uses the same words inside `note`.
- Change: Reduce `ForeignAudio` to `track`, `forced_only`, `note`. The three early-return constructions become `ForeignAudio(note=...)`. Tests: replace `not x.searched` by an assertion on `note` (it starts with `"Foreign audio search: not run"` or `"…: no audio language"`), and `.evidence == ...` by `... in note`.
- Behaviour: unchanged.
- Contracts touched: none (runtime dataclass, not a model).
- Callers to update: `explain.py` only; tests above (two files: `tests/batch/test_explain.py` and `tests/probe/test_roles_empty_subtitles.py`).
- Tests: change 6 assertions (`test_explain.py` 471, 532, 543, 550, 710; `test_roles_empty_subtitles.py:72`); no test deleted.
- Decision records: 0031 section 5 (behaviour kept: the note text stays).
- Size: S; estimated lines: -10 source / -2 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (a sixth assertion, `tests/probe/test_roles_empty_subtitles.py:72`, reads `found.searched`; it is in the probe tests)
- Orchestrator: Tier A, work package Q-6.6 (see ../plan.md).

### BAT-12: The `container_codecs` flag runs through six signatures to hide one lint code
- Kind: decision-change
- Where: `lint.py:366, 408-409, 433, 441, 461` (`lint_rules`, `lint_defaults`, `_container_issues` at 311-357); `rules.py:708, 712, 769` (`resolve_tracks`); `resolve.py:165, 169, 178, 190, 207` (`resolve`, `resolve_with_tracks`); `jobs.py:278, 283, 291, 425` (`draft_from_preset`, `JobService._compose`); `cli.py:1331`; `service.py:438` (`BatchService._row`); `validation/__init__.py:162`.
- Now: decision 0040 R1-4 ("one issue per problem") adds a keyword-only `container_codecs: bool = True` to `resolve_tracks`, `resolve`, `resolve_with_tracks`, `draft_from_preset`, `lint_rules` and `lint_defaults`, so that `defaults.codec_not_in_container` is left out when C-8 reports `container.codec_unsupported`. Four callers pass `False` (`validation`, `JobService.draft` path, `OwnerJobs.draft`, `BatchService._row`); the only caller that wants `True` is the live preview (`JobService.explain`), because C-8 does not run there. A flag that is passed down six signatures for one caller's benefit.
- Change: Take the check out of the lint: `lint_defaults` / `resolve_tracks` never emit `defaults.codec_not_in_container`; make `_container_issues` public as `container_codec_issues(defaults, container, defs)`. `JobService.explain` appends it after `resolve_tracks`, only when the template has no explicit audio rules (the lint runs only then). Delete the parameter and its docstring lines in all six functions and the `False` arguments at the four call sites (about 30 lines gone, about 5 added).
- Behaviour: unchanged for the preview (same issue; its position in `issues` moves after the other lint issues, which only matters when both a bitrate note and a container error exist). Unchanged elsewhere.
- Contracts touched: public core API (one keyword removed from six functions).
- Callers to update: those listed in "Where".
- Tests: `test_lint.py:336` (the `container_codecs=False` assertion becomes "the lint never reports it"); `tests/validation/test_template.py:386` keeps its meaning; `test_a_codec_the_container_cannot_hold_is_one_issue` stays as the guard.
- Decision records: 0040 R1-4 (0040:347) and 0031 section 6 name the parameter, and `docs/core-breakdown.md:324` lists `lint_defaults(…, container_codecs=…)` in the wave contract. The behaviour they require (one issue per problem) is kept; only the mechanism changes. What would have to be true: the preview can append the codec issue itself (it can: `JobService.explain` already post-processes the draft). The guard is `tests/jobs/test_service.py:526` (`jobs.explain(file, webm)`) and `test_rules.py:437-456`, which compare the draft's issues with `lint_rules`.
- Size: M; estimated lines: -25 source / -2 tests
- Risk: low-medium (touches jobs, cli, validation: other areas)
- Depends on: BAT-07 and BAT-08 (they rename or merge the functions this flag passes through)
- Confidence: medium
- Verdict: CONFIRMED (the flag is declared in six signatures, not seven: `lint_rules`, `lint_defaults`, `resolve_tracks`, `resolve`, `resolve_with_tracks`, `draft_from_preset`; the issue's order in the preview moves after `defaults.rule_unused` too, not only after the bit-rate notes)
- Orchestrator: Tier B, work package Q-6.15 (see ../plan.md).

### BAT-13: `grouping.compare` repeats its pairing code and two helpers repeat `video_key`
- Kind: duplication
- Where: `packages/reframe/src/reframe/batch/grouping.py:154-222` (`compare`: the pairing of a missing and an added track of one kind at 180-189 and again at 195-205), `225-235` (`_size`, `_hdr`); `descriptors.py:290-300` (`video_key`).
- Now: both branches pair "gone" and "added" tracks of the same kind (`next((n for n in added if n.kind == old.kind), None)`, then missing / changed / extra). `_size(fp)` recomputes what `video_key(fp)[0]` returns (the size or resolution class), with `"none"` for no size.
- Change: Extract `_pair(gone: Sequence[TrackDescriptor], added: list[TrackDescriptor]) -> tuple[list[str], list[str], list[str]]` (missing, changed, extra labels). Loose: `missing, changed, extra = _pair(gone, added)`. Ordered: per non-equal opcode call `_pair(group.tracks[a1:a2], list(file.tracks[b1:b2]))` and extend. Replace `_size(fp)` by `video_key(fp)[0] or "none"`.
- Behaviour: unchanged.
- Contracts touched: none.
- Callers to update: `grouping.py` only.
- Tests: none change (`test_grouping.py`, `test_batch_properties.py` guard it; `test_a_changed_track_counts_once_at_every_level`, `test_loose_pairs_changed_tracks_by_kind`).
- Decision records: 0040 R2-4 (a changed track counts once at every level): kept.
- Size: S; estimated lines: -5 source / 0 tests (almost all from deleting `_size` (-6); the two pairing blocks are 8 and 9 lines and `_pair` plus its call sites is about the same, so that part removes one copy of the logic, not lines)
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (estimate -15 is wrong, about -5; `_size` is the only real line saving)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-14: `TrackDescriptor.bitrate` has no reader
- Kind: model-redundancy
- Where: `packages/reframe/src/reframe/models/batch.py:69-70` (`TrackDescriptor.bitrate`); `packages/reframe/src/reframe/batch/descriptors.py:208, 214, 226, 242` (`bitrate` local and the keyword); `tests/batch/test_descriptors.py:114-115`.
- Now: the field is filled in `describe_stream` and read by one test assertion. No level compares it (decision 0040 section 3: "04's descriptor table has no bit rate"), and the frontend does not read the fingerprint (`BatchGroup.fingerprint` appears only in test fixtures). It is part of the API response of `/batch/group` and of `reframe batch --json`.
- Change: Delete the field, the local variable and its assignments, and the two test assertions.
- Behaviour: changes: one key less in `fingerprint.tracks[*]` of the group response and of `reframe batch --dry-run --json`. The plan's descriptor table never listed it.
- Contracts touched: HTTP/OpenAPI (`TrackDescriptor` schema loses `bitrate`; run `scripts/gen-api.sh` to refresh `frontend/src/api/schema.d.ts`; no frontend source reads it; frontend test fixtures `frontend/src/components/range/testing.ts:72` use `tracks: []`); CLI `--json`.
- Callers to update: `frontend/src/api/schema.d.ts` (generated, `scripts/gen-api.sh`) and the schema snapshot `packages/reframe/tests/models/__snapshots__/test_schema.ambr` (the `TrackDescriptor.bitrate` entry; refresh it with `uv run pytest packages/reframe/tests/models --snapshot-update` and read the diff: only that field may change).
- Tests: delete `test_descriptors.py:114-115`.
- Decision records: 0040 section 3 (no level compares bit rates) and 0040 "Open product questions" item 1 ("Strict compares no bit rate (`descriptors.track_key`)", listed as easy to change). If the owner decides strict should compare bit rates, the field is what that change needs, so drop this finding in that case. The plan's descriptor table (04 line 19) has no bit rate.
- Size: S; estimated lines: -8 source / -2 tests
- Risk: low
- Depends on: none
- Confidence: medium (high that nothing reads the field; medium that the owner wants it gone while the strict-level question is open)
- Verdict: ADJUSTED (the test-schema snapshot `test_schema.ambr` must change too; one anchor is `descriptors.py:226` not 225; 0040's open question 1 may want the field, so confidence lowered)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-15: `matrix_columns` resolves an empty source to learn the column labels
- Kind: structure
- Where: `packages/reframe/src/reframe/batch/resolve.py:276-289` (`matrix_columns`, with the `source` parameter); `rules.py:484-490` (`_KindResult.columns`), `594, 678` (columns lists), `695-699` (`_compiled_columns`), `681-695` (`TrackResolution.columns`), `731-758` (constructors).
- Now: the columns depend only on the template (explicit rules: `rule_label`; defaults: `compile_defaults`). `matrix_columns` nevertheless builds a dummy `MediaSource` and runs the whole track stage (selection, codec rules, lint) on it, then reads `tracks.columns`. Every `resolve_tracks` call in every file's resolution also builds `columns` and throws them away. The `source` parameter of `matrix_columns` has 0 callers that pass it (callers: `service.py:317, 399`, tests only without `source=`).
- Change: Write the columns directly:
  ```python
  def matrix_columns(template, *, definitions=None, languages=None) -> list[MatrixColumn]:
      defs = definitions or load_definitions()
      columns = [VIDEO_COLUMN]
      for kind, rules in (("audio", template.audio_rules), ("subtitle", template.subtitle_rules)):
          if rules:
              columns += [MatrixColumn(kind=kind, rule=n, label=rule_label(kind, n, r, defs)) for n, r in enumerate(rules)]
          else:
              preferred = (languages.preferred_audio if kind == "audio" else languages.preferred_subtitle) if languages else ()
              columns += _compiled_columns(compile_defaults(template, kind, preferred=preferred))
      return [*columns, NAME_COLUMN]
  ```
  Remove `columns` from `_KindResult` and `TrackResolution`, and the two column lists in `_explicit_*`. `_compiled_columns` is private to `rules.py`: make it public (or move it next to `matrix_columns`) for the sketch above.
- Behaviour: unchanged (same labels); `matrix_columns` no longer runs the lint or the selection.
- Contracts touched: core internals; `reframe.batch.matrix_columns` loses the unused `source` keyword; `TrackResolution.columns` is removed (read by tests only).
- Callers to update: `resolve.py` imports; none outside `batch/` in `src/`.
- Tests: `test_resolve.py:158-176, 235` and `test_anime_season.py` call `matrix_columns(template)` and stay. Three tests read `TrackResolution.columns` and must switch to `matrix_columns(template, ...)`: `test_rules.py:166` (`result.columns[:2]`), `test_rules.py:378` (`result.columns` audio labels), `test_derive.py:267` (`result.columns` audio labels); pass the same `languages=` (if the test uses one) to `matrix_columns`.
- Decision records: 0040 sections 1 and 8 (one column per rule): kept.
- Size: S; estimated lines: -3 source / 0 tests (the gain is removing the dummy-source trick and per-file column work)
- Risk: low
- Depends on: BAT-04 and BAT-05 (same functions)
- Confidence: medium
- Verdict: ADJUSTED (the finding said no test changes, but three tests read `TrackResolution.columns`: `test_rules.py:166, 378`, `test_derive.py:267`; `_compiled_columns` must become public)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-16: `status` and `issues` of a `Resolution` are kept in step by hand at four places
- Kind: model-redundancy
- Where: `packages/reframe/src/reframe/batch/service.py:385-389` (near issue in `resolve_batch`), `454-462` (`_row`), `584-587` (`_collisions`); `packages/reframe-server/src/reframe_server/routers/batch.py:111-123` (`_checked`); `batch/resolve.py:144-155` (`row_status`) and `217`; `models/batch.py:170-171` (`status`).
- Now: `status` is derived from `matches` and `issues` (`row_status`), but it is a stored field, so every place that changes `issues` through `model_copy(update=...)` has to pass a matching `"status": row_status(...)` (3 places in core, 1 in the server). A new site that forgets it leaves a wrong status. A `@computed_field` is not an option here: `ReframeModel` is `extra="forbid"` and no model uses `computed_field` (a dumped row could not be validated again; also a new pattern for the OpenAPI types).
- Change: Add `Resolution.with_issues(self, issues: Sequence[ValidationIssue]) -> Resolution` returning `self.model_copy(update={"issues": [*issues], "status": row_status(self.matches, issues)})`, and move `row_status` into `models/batch.py` (models must not import `batch`). Use it at the four sites; in `_collisions` and `_row` build the new issue list first, then one call.
- Behaviour: unchanged. HTTP contract unchanged (a method adds no field).
- Contracts touched: none; the server router imports `row_status` from core: switch it to `row.with_issues(...)` (`routers/batch.py:12, 119-121`).
- Callers to update: the four sites; `tests/batch/test_resolve.py:14` imports `row_status` from `reframe.batch.resolve` (keep a re-export or update the import).
- Tests: none change.
- Decision records: none.
- Size: S; estimated lines: about 0 source / 0 tests (the new method and the moved `row_status` add about 8 lines; the four `"status": row_status(...)` entries and the server's `row_status` import remove about 8). The gain is that no site can forget the status, not size.
- Risk: low
- Depends on: BAT-01 (it removes one `status="error"` construction)
- Confidence: medium-low (no line saving; do it only if the file is open anyway)
- Verdict: ADJUSTED (estimate -10 is wrong, about 0; confidence lowered)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### BAT-17: cross-area: HDR display names are written four times, `_probe_issue` twice
- Kind: duplication
- Where: HDR name map `{hdr10: "HDR10", hdr10plus: "HDR10+", hlg: "HLG", dolby_vision: "Dolby Vision"}` in `packages/reframe/src/reframe/batch/grouping.py:233-235` (`_hdr`), `preview/graph.py:87-91` (`_hdr_name`), `cli.py:228-233` (`_HDR_NAMES`), `validation/filters.py:36-41` (`_HDR_LABELS`). (`naming/context.py:52-57` uses `"DV"` for a different purpose and is not a copy.) And `packages/reframe/src/reframe/batch/service.py:140-147` (`_probe_issue`) is identical to `packages/reframe/src/reframe/jobs.py:246-253` (`_probe_issue`); `queue/runner.py:1046-1051` (`_source_issue`) has the same message shape with another code.
- Now: cross-area: preview, cli, validation, jobs, queue. `service.py` already imports `reframe.jobs` (`file_key`, line 29), so the import costs nothing.
- Change: Give `HdrFormat` (`models/media.py:190`) a `label` property (or one `HDR_NAMES` dict next to the enum) and use it in the four places; make `jobs._probe_issue` public as `probe_issue` and import it in `batch/service.py`. In batch: delete `grouping._hdr` (-5) and `service._probe_issue` (-8); other areas: about -15.
- Behaviour: unchanged.
- Contracts touched: none (`HdrFormat` is an API enum but a property adds no schema field).
- Callers to update: the files above.
- Tests: none.
- Decision records: none.
- Size: S; estimated lines: -13 source in batch (about -28 including the other areas) / 0 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (all four HDR maps and both `_probe_issue` copies verified; `HdrFormat` gets a property, no schema change)
- Orchestrator: joined into X-05 (see ../cross-cutting.md); that entry decides the tier and the work package.

## Looked at and kept

- `service.py` file identity (`_probe_all`, `_patches`, `_keyed`, `_output_keys`, `_collisions`, `file_key` use) and the two-pass `resolve_batch` (rows first, then left-out outputs, then grouping, then the near issue spliced in at `at = len(template_issues)`): decisions 0040 R2-1, R2-7, RA-1. The near issue cannot be added earlier because grouping needs the left-out outputs, which need the resolved rows.
- BAT-10.4 `select_tracks` `kind` inference and `Selection.kind`: rejected in verify. The inference is only used by tests, but `run()` in `test_selection.py` is generic over audio and subtitle streams (32 callers), and `test_main_tracks.py` 87-111 and `test_selection.py:465` call `select_tracks` without `kind`, so the one-line inference moves into the test helper: net about -1 line.
- `select_tracks` (95 statements, 32 branches): every branch is a rule of 0031 sections 1-4 and every string is pinned by tests and `reframe plan` output. Splitting it into stage functions would not delete a line.
- `audio_rules._encode` (82 statements): decisions 0019, 0023, 0025; the sentence strings are the `reframe plan` reasons; `_written` / `planned_audio` keeps the builder, validation and the rules on one bit-rate table.
- `selectors.match_rules` (70 statements): relaxation order and "a relaxed rule never takes another rule's exact match" are 0040 section 2 and plan 04.
- `overrides.py` (`structural_op`, `_changes_rules`, stale and invalid issues) and `resolve.compiled_rules_moved`: 0040 section 5, R2-3, RA-3. Needed by the matrix columns.
- `descriptors._digest` (sha256 of the level's keys) and the `BatchGroup.id` hash in `grouping._group`: group ids must be stable across processes; the digest is part of the API model.
- `BatchResolution.group`: the frontend reads `resolution.group.name` (`MatrixDialog.vue:27`) from `resolve-run`.
- `Resolution` vs `JobDraft` field overlap: the editor treats a matrix row as a draft on purpose (`frontend/src/stores/editor.ts:180`); `JobDraft.job` and `naming` are required while `Resolution.job` is optional, so one cannot extend the other.
- `Resolution.override` echo, `Resolution.decisions` / `subtitle_decisions` / `notes`: 0040 section 5 and section 8; the frontend uses decisions and notes of a row.
- `service._Sources` / `_Presets` / `_Jobs` protocols and `jobs: object` with `cast`: a second real implementation of `_Jobs` exists (`OwnerJobs` in `cli.py:1486`, the remote-owner path) and tests pass stubs. Not speculative. (The `object` plus `cast` could be a typed `_Jobs` parameter; not checked with mypy, so not listed.)
- `Pick[S]`, `Selection[S]`, `select_tracks[S]` generics: `audio_stage` needs `AudioStream`-specific attributes on picks.
- `report.py` ASCII marks and `unicode=False`: 0040 section 7 (non-UTF-8 stdout).
- `explain.forced_evidence` ranks and `foreign_audio_search`: 0031 section 5; `FORCED_MAX_RATIO` shared with the probe on purpose.
- `grouping.compare` loose vs ordered algorithms: 0040 section 3 and R2-4 (different matching on purpose).
- `lint.py` fixes (`_move_fixes`, `_reachability`, `_bitrate_issue`, `_container_issues`): 0031 section 6 (every code has a JSON-patch fix).
- `models/batch.py` `TrackMatch.severity` (derivable from `status`) and `MatrixColumn.defaults` / `TrackMatch.defaults`: the frontend reads both (`matrix.ts:56`).
- `build_job` / `derive_template` `OutputOptions` <-> `OutputSettings` dump-and-validate round trip: keeps unknown fields (`DocumentModel`, persistence rules).
- Coverage hints: `coverage.txt` lists definition and import lines as missed for all `batch/` modules (measurement artifact), so no coverage-based dead code was claimed; one unrelated test failed in that run (`test_desktop_server_prints_the_ready_line_and_answers_health`).

## Noted by the verifier (not verified)

- BAT-06: `tests/jobs/`, `tests/command/`, `tests/preview/`, `tests/remote/` and `tests/tools/` already have an `__init__.py` and use relative imports (`from .conftest import ...` in `tests/jobs/test_cli_batch.py`). A cheaper alternative to moving `anime.py` / `defaults_tracks.py` into `reframe_testing` is an `__init__.py` in `tests/batch/` and `from . import anime as A`. Not tried with pytest `--import-mode=importlib` or mypy.
- BAT-14 / 0040 open question 1: if the owner wants strict grouping to compare bit rates, keep `TrackDescriptor.bitrate`.
