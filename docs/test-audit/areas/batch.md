# Area batch: `packages/reframe/tests/batch/` (23 files, with `anime.py`, `defaults_tracks.py`, `__snapshots__/test_anime_season.ambr`)

Baseline: 23 files, 709 tests, 6,173 test code lines, 60 s of test time.

## Summary

7 findings. Tier A: 4 findings, 5 tests and about 13 code lines removed. Tier A+B: 7 findings,
7 tests and about 50 code lines removed. Almost no time is saved (well under 1 s), because
two earlier passes already trimmed this area: the C-12 trim in
`docs/test-trim-reports/B.md` and Q-6 (BAT-01..17, X-04). Of the 60 s, 38 s is
`test_batch_service.py`, which runs the real ffprobe. Its tests are facade integration tests
with inputs that no other layer has, so none is a layer duplicate. Their cost is a speed
matter (see "Speed notes").

Trim reports read: `docs/test-trim-reports/B.md` in full. It is the only one about
`tests/batch/` (`test_audio_rules.py`, `test_lint.py`, `test_selection.py`,
`test_explain.py`, `test_draft.py`, `test_selection_properties.py`, `test_explain_media.py`).
I also grepped all ten reports (B, C, M, N, P, Q, R, T, V1, V2) for this area's files and
names. V2 mentions `batch/audio_rules.py` only in its mutation table for validation tests.
V1 and Q match only on unrelated words (`validation/test_rules.py`, "after every batch").
None of the findings goes against a B.md keep. B.md's keeps are the 210 helper-agreement
cases, `test_builtin_presets_are_clean`, `test_never_bigger_than_the_source`, the
foreign-audio search and burn-in cases, and its "M6 demo item 5" tests (now
`test_the_codec_rules_example_row_by_row_through_draft_and_explain` and
`test_explain_through_the_facade_with_the_settings_languages`). All of these are under
"Looked at and kept" and are treated as guards. B.md's mutation table lists
`test_example_of_03_row_by_row` (now `test_the_codec_rules_example_row_by_row`) as the test
that kills two `channels_match` mutants. That is one more reason it stays. TBT-06 and TBT-07
touch `test_explain.py` / `test_lint.py` / `test_audio_rules.py`, but B.md neither keeps nor
deletes the tests or constants they change.

Best three:
- TBT-01: merge `test_rules.py::test_settings_of_the_other_kind_are_an_error` into the named
  review guard `test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell` (same file,
  same source, same wrong-settings rule).
- TBT-07: the example's four codec rules are written four times (`test_audio_rules.py`,
  `test_explain.py`, twice in `test_lint.py`). Use one constant in `defaults_tracks.py`
  (about -24 lines).
- TBT-06: `test_explain.py::test_the_draft_has_the_lint_for_this_source` repeats
  `test_lint.py::test_rules_this_source_does_not_use`. Since Q-6 (BAT-07), both go through
  `resolve_tracks(...).draft.issues` with the same rules and selection.

Most of the obvious duplicates in this area are guards named in decision records 0031, 0040,
0041 or in the plan's "Done when", so they stay (see "Looked at and kept").

## Findings

### TBT-01 Two tests of "a rule with settings of the other kind" on E05
- Kind: near-copy
- Where: `packages/reframe/tests/batch/test_rules.py::test_settings_of_the_other_kind_are_an_error` (242), `packages/reframe/tests/batch/test_rules.py::test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell` (481)
- Now: Both call `resolve_tracks` on `A.recorded(1, 5)` (`example()` is the same file) with an
  audio rule for Japanese that has `SubtitleOutputSettings`. The first test also has a
  subtitle rule (`^Full$`) with `AudioOutputSettings`. It asserts that `draft.audio` and
  `draft.subtitles` are empty and checks the two `(code, path)` issues. The second asserts
  `draft.audio == []`, the audio cell `("missing", "error")` with its message, and the
  issue codes `["batch.rule_settings"]`.
- Change: merge into `test_rules.py::test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell`.
  Add `wrong_sub = sub_rule(AudioOutputSettings(), title_pattern="^Full$")` to its template
  (`JobTemplate(audio_rules=[wrong], subtitle_rules=[wrong_sub])`). Assert
  `(draft.audio, draft.subtitles) == ([], [])` and keep the cell assertions. Replace the
  code list with the first test's `(code, path)` list:
  `[("batch.rule_settings", "audio_rules[0].settings"), ("batch.rule_settings", "subtitle_rules[0].settings")]`.
  Then delete `test_settings_of_the_other_kind_are_an_error`.
- Saved: 1 test, about 9 code lines (16 lines go, about 7 are added), 0.00 s
- Guarantee kept by: the merged `test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell`.
  Its inputs are both wrong-kind rules on E05. It asserts both empty track lists, both issue
  paths, and the missing/error audio cell with its message.
- Why nothing is lost: the source is the same (E05). The audio rule is the same (`["ja"]`
  vs `["jpn"]` is the same language, and spelling equivalence is pinned in
  `test_selection.py::test_language_identity`). The subtitle rule moves over unchanged. Every
  assertion of both tests stays, and the path list is stricter than the second test's code
  list. One thing changes: with a subtitle rule present, the named test no longer runs the
  subtitle defaults stage. That stage is not what it guards, and many tests cover it
  (`test_explain.py`, `test_selection_properties.py`).
- Docs and history: `test_settings_of_the_other_kind_are_an_error`: grep `docs/` gives
  nothing. `git log -S` gives only 14a5b2c ("C-12: batch engine: descriptors, fingerprints,
  grouping, rules, resolution"), the first commit of the engine, with no bug named. The target
  `test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell` is named in
  `docs/decisions/0040-batch-engine-and-reframe-batch.md:374` and
  `docs/decisions/0041-core-complete-review.md:174` (review fix 2d3390f, renamed in 3123733).
  It keeps its name.
- Risk: low. Test code only. The issue order with both rules is the one the first test already
  asserts.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Both tests read and compared line by line. `OutputTrackRule(...)` without `metadata` equals `audio_rule(...)`'s explicit `TrackMetadataTemplate()`; `["ja"]` vs `["jpn"]` is one language; `template()` is `JobTemplate(audio_rules=..., subtitle_rules=...)`. With the subtitle rule added, the audio cell filter `m.kind == "audio"` still finds exactly one cell and its status, severity and message are unchanged; the issue order is the one the deleted test asserted. The guard loses the subtitle-defaults stage (108 lines only it runs today), but each of those lines is run by 430 to 2,157 other tests (coverage db). The fix commit 2d3390f added the check for both kinds (`rules.py` audio and subtitle branches); the merged test now pins both branches under the named guard, which is stronger than today. No doc names the deleted test; `git log -S` gives only 14a5b2c. Lines: -11 code lines (`test_rules.py` 426 → 415), not -9.
Checked: applied the merge with TBT-02..06 → `runtests.sh` on the six changed files: 212 passed, 1 snapshot passed (load: 2 other pytest runs); ruff, ruff format --check and mypy clean.

Orchestrator: Tier A, package Q-7.1.

### TBT-02 `test_one_group_at_every_level`: three cases become one stricter test
- Kind: param-trim
- Where: `packages/reframe/tests/batch/test_grouping.py::test_one_group_at_every_level[strict|standard|loose]` (201)
- Now: Each case groups season 1 at its level and asserts one group of 12 members. It then
  checks that its id differs from the id at one other level: strict vs standard, standard vs
  loose, loose vs standard. The standard and loose cases make the same comparison, and
  strict vs loose is never compared. Each case loads the 12 recorded probes twice.
  `[loose]` and `[standard]` have the same line set (covmap).
- Change: rewrite as one test (`test_grouping.py::test_one_group_at_every_level`). Load
  `sources = A.season(1)` once. For each level in `MATCH_LEVELS`, take `(group,) =
  group_sources(sources, level)`, assert 12 members, and collect `group.id`. Then assert
  `len(ids) == 3`.
- Saved: 2 tests, about 2 code lines, about 0.1 s (0.16 s for the three cases today)
- Guarantee kept by: the rewritten test. It checks the same input and level set, one group
  of 12 per level, and pairwise-distinct ids.
- Why nothing is lost: every level is still grouped and checked for 12 members. The id
  assertion is stricter, because all three pairs are now compared.
- Docs and history: grep `docs/` gives nothing. `git log -S` gives 14a5b2c only (C-12 first
  commit, no bug).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: ADJUSTED — The finding is right (standard-vs-loose is compared twice, strict-vs-loose never; `MATCH_LEVELS` is already imported in `test_grouping.py` and typed as `tuple[MatchLevel, ...]`, so the `type: ignore` goes). But the loop form as written (`sources`, `ids = set()`, `for`, `(group,) =`, `assert`, `ids.add`, `assert len(ids) == 3`) is 8 code lines against 7 today: **+1 line**, not -2. A compact form saves 3 lines and keeps every check: `groups = [group_sources(A.season(1), level) for level in MATCH_LEVELS]`; `assert [[len(g.members) for g in found] for found in groups] == [[12]] * 3` (one group of 12 per level); `assert len({found[0].id for found in groups}) == 3`. Corrected: 2 tests, -3 code lines with the compact form (+1 with the auditor's loop). Tier A stays.
Checked: both forms applied in the worktree, each run with the batch tests → passed (loop form in the 212-test run; compact form in the 696-test run of `tests/batch -k "not test_batch_service"`); codelines `test_grouping.py`: compact TBT-02 alone 265 → 262; loop form together with TBT-03 265 → 265 (TBT-03 -1, loop +1).

Orchestrator: Tier A, package Q-7.1. Use the verifier's 3-line form.

### TBT-03 `test_episode_label_with_season` folds into the named `test_episode_labels`
- Kind: near-copy
- Where: `packages/reframe/tests/batch/test_grouping.py::test_episode_label_with_season` (57), `packages/reframe/tests/batch/test_grouping.py::test_episode_labels` (303)
- Now: `test_episode_label_with_season` has two assertions. With `season=True`, `A.path(1, 5)`
  becomes `S01E05`, and `/tv/Show - 07.mkv` (no season number) stays `E07`.
  `test_episode_labels` already asserts `season=True` on `Show.S01E02.mkv` → `S01E02`, the
  same class as the first assertion.
- Change: merge into `test_grouping.py::test_episode_labels`. Add both assertions (or only
  the `E07` one, which is the new class). Delete `test_episode_label_with_season`.
- Saved: 1 test, 1 code line (2 if only the `E07` assertion moves), 0.01 s
- Guarantee kept by: `test_episode_labels`, with the moved assertions.
- Why nothing is lost: the assertions move verbatim. The test that receives them keeps its
  name.
- Docs and history: `test_episode_label_with_season`: grep `docs/` gives nothing.
  `git log -S` gives 14a5b2c only. The target `test_episode_labels` is named in `0040:357`
  and `0041:138` (R2-6). It keeps its name and gains an assertion.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Both assertions move verbatim into `test_episode_labels` (named in 0040:357 and 0041:138, R2-6; it keeps its name). `A.path(1, 5)` (anime naming) and `/tv/Show - 07.mkv` (no season number → `E07`) both survive. No doc names the deleted test; `git log -S` gives 14a5b2c only. Saved 1 test, 1 code line (measured with both assertions moved).
Checked: applied → passed in the 212-test run above.

Orchestrator: Tier A, package Q-7.1.

### TBT-04 `test_codec_family`: the `opus` case repeats the `flac` case
- Kind: param-trim
- Where: `packages/reframe/tests/batch/test_descriptors.py::test_codec_family[stream11-opus]` (118)
- Now: `codec_family` (`batch/descriptors.py:80-94`) returns `_FAMILIES.get(codec, codec)`
  for audio. `flac` and `opus` are both outside `_FAMILIES`, so both test the same
  fallthrough ("a codec outside the table is its own family") with the same kind of
  assertion. They are in the same 12-case coverage group.
- Change: trim cases: drop `(audio(1, "opus"), "opus")`. Keep every other case. Each one
  pins a table entry (`mlp`, `eac3`, `aac_latm`, `mp2`, `mp3`), the `pcm_` prefix, a
  subtitle set member, the unknown subtitle codec (`arib_caption`), `None`, or video.
- Saved: 1 test, 1 code line, 0.00 s
- Guarantee kept by: `test_codec_family[stream10-flac]`: an audio codec outside `_FAMILIES`
  is its own family.
- Why nothing is lost: same branch, same kind of expected value. Neither `opus` nor `flac` is
  a table entry.
- Docs and history: grep `docs/` for `test_codec_family` gives nothing. `git log -S` for the
  `opus` case gives 14a5b2c only.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `codec_family` (`batch/descriptors.py:80-94`): for an audio stream the only branches are `codec is None`, `startswith("pcm_")`, and `_FAMILIES.get(codec, codec)`. `_FAMILIES` (`:56-66`) lists dts, truehd, mlp, ac3, eac3, aac, aac_latm, mp1, mp2, mp3; neither `flac` nor `opus` is a key, neither starts with `pcm_`, so both take the same fallthrough and return the codec name. No other table in `reframe/batch` maps `opus` (only `lint.py:47` `_ENCODER_PREFERENCE` names encoders, not ffprobe codecs). `video(0, "hevc")` also pins the fallthrough for video. `git log -S` gives 14a5b2c only. Saved 1 test, 1 code line (`test_descriptors.py` 310 → 309).
Checked: applied → passed in the 212-test run above.

Orchestrator: Tier A, package Q-7.1.

### TBT-05 `test_the_example_steps` resolves the same matrix as the snapshot test
- Kind: shared-setup (merge)
- Where: `packages/reframe/tests/batch/test_anime_season.py::test_the_example_steps` (124), `packages/reframe/tests/batch/test_anime_season.py::test_the_season_groups_and_resolves_as_the_example_matrix` (87)
- Now: Both build `matrix(A.example_template(), A.season(1))`: they group, resolve and name
  the 12 recorded episodes. The snapshot test checks the columns, every cell, the statuses,
  the names and the text snapshot. `test_the_example_steps` checks E05's decisions:
  `(1, True), (2, True), (3, False)`, the "No track rule takes this track" text, and the job
  audio `[1, 2]`. Its line set is a subset of the snapshot test's.
- Change: merge into `test_anime_season.py::test_the_season_groups_and_resolves_as_the_example_matrix`.
  After the cell checks, add `e05 = resolution.rows[4]` and the four E05 assertions. Delete
  `test_the_example_steps`. `__snapshots__/test_anime_season.ambr` does not change, because
  the snapshot text is built from `matrix_lines` and the group members only.
- Saved: 1 test, about 3 code lines, about 0.13 s (one fewer 12-episode resolve)
- Guarantee kept by: the merged snapshot test. Its input is the same, and it gets every
  assertion of `test_the_example_steps`.
- Why nothing is lost: the input is identical and every assertion moves.
- Docs and history: grep `docs/` gives nothing. `git log -S` gives 14a5b2c only. The plan
  (`docs/plan/04-batch-mode.md:238-246`, "Done when") asks for "a snapshot test", and the
  merge keeps it. Do not fold `test_e01s_audio_setup_gives_identical_audio_settings` into it
  (it has the same setup). That test is the plan's second "Done when" bullet ("Applying E01's
  manual audio setup to the group gives identical audio settings"), so it stays as its own
  test.
- Risk: low. The snapshot test gets longer, and a failure in E05's decisions now reports
  under the matrix test.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Both tests build `matrix(A.example_template(), A.season(1))` on recorded probes (no tool marker on either). The snapshot text is built from `group` and `matrix_lines(resolution)` only, so moving the E05 assertions does not touch it; the `.ambr` has one key (`test_the_season_groups_and_resolves_as_the_example_matrix`), so the test name must and does stay. Q-6.6's "Done when" (`docs/plan/09-quality-and-release.md:148`, `docs/simplify/plan.md:168`) names `tests/batch/test_anime_season.py` (snapshot) "pass unchanged": Q-6.6 is already done (`[x]`, status row 155), and the snapshot file is unchanged, so that check still holds; but the test file itself changes, so the commit should say the snapshot is unchanged. Plan 04 "Done when" bullet 1 asks for "a snapshot test", which stays; `test_e01s_audio_setup_gives_identical_audio_settings` (bullet 2) is rightly left alone. Keep the deleted docstring as a one-line comment above the E05 block. Lines: -2 code lines (`test_anime_season.py` 216 → 214), not about -3. Tier B stays.
Checked: applied → the 212-test run: `1 snapshot passed`, `git diff` showed no change to `__snapshots__/test_anime_season.ambr`.

Orchestrator: Tier B, package Q-7.11.

### TBT-06 `test_the_draft_has_the_lint_for_this_source` repeats the lint's own source test
- Kind: layer-duplicate
- Where: `packages/reframe/tests/batch/test_explain.py::test_the_draft_has_the_lint_for_this_source` (331)
- Now: The test resolves `JobTemplate(audio_defaults=EXAMPLE_DEFAULTS)` on one Hungarian
  AC-3 5.1 track. It asserts that `draft.issues` is exactly `defaults.rule_unused` for
  `codec_rules[1]` and `[2]`. `test_lint.py::test_rules_this_source_does_not_use` (353)
  uses the same four rules and the same selection (`EXAMPLE` there, `hu`/`en`, all tracks).
  Since Q-6 BAT-07 it also goes through `resolve_tracks(...).draft.issues` (`lint_with_source`,
  line 344). It asserts the same `rule_unused` code/path pairs for a one-track source
  (English AC-3 5.1 → `[0]`, `[2]`) and a two-track source. It also asserts severity INFO,
  the message, "the catch-all is never reported", and "no audio: nothing". covquery: all
  673 lines of the explain test are inside the lint test (690).
- Change: delete.
- Saved: 1 test, 8 code lines, 0.00 s
- Guarantee kept by: `test_lint.py::test_rules_this_source_does_not_use` (353). The input is
  `EXAMPLE` on `source([audio(1, "eng", "ac3", 6, 448)])`, the same pipeline and the same
  class of source (one 5.1 track of one listed language). It asserts `found(english) ==
  [("defaults.rule_unused", "audio_defaults.codec_rules[0]"), ("defaults.rule_unused",
  "audio_defaults.codec_rules[2]")]`.
- Why nothing is lost: the draft is the same and the lint is the same. The language mirrors
  the deleted test (English uses rule 2, Hungarian uses rule 1). The lint test filters on
  the `defaults.rule_` prefix, while the explain test compared the full issue list. So "no
  other draft issue for this source" is no longer pinned. If that matters, add
  `assert lint_with_source(...)` without the filter (one line) to the lint test.
- Docs and history: grep `docs/` gives nothing. `git log -S` gives cd41c78 only ("C-12:
  selection stage of the audio and subtitle defaults, explain, the defaults lint"), the first
  commit, with no bug named.
- Risk: low. The full-list detail is the only difference.
- Proposed tier: B
- Confidence: medium

Verdict: ADJUSTED — The deleted test pins two things the lint test does not: (1) the **full** issue list of the draft (no issue other than the two `rule_unused`), because `lint_with_source` filters on `defaults.rule_`; (2) a call of `resolve_tracks` without `languages` (the lint helper always passes `LanguageSettings(preferred_audio=[])`). The proposed fix, "add `assert lint_with_source(...)` without the filter (one line)", **does not work as written**: `lint_with_source` always filters, so it cannot assert the full list. A fix that keeps both details (checked): in `test_rules_this_source_does_not_use`, name the English source and compare the unfiltered draft with the filtered list:

`eng = source([audio(1, "eng", "ac3", 6, 448)])`, `english = lint_with_source(EXAMPLE, eng)`, and after the `found(english)` assertion `assert resolve_tracks(JobTemplate(audio_defaults=EXAMPLE), eng).draft.issues == english` (`resolve_tracks` and `JobTemplate` are already imported). It passes, so the English one-track source has no other draft issue. That is +2 code lines, not +1. The Hungarian-vs-English difference (rule [1] vs [0] unused) is not lost: the lint test's two-track source reports rule [1] for the same Hungarian AC-3 5.1 224 track. No doc names the deleted test; `git log -S` gives cd41c78 only. Corrected: 1 test, -6 code lines net (-8 in `test_explain.py`, +2 in `test_lint.py`); the fix is part of the change, not optional. Tier B stays.
Checked: applied delete + the 2-line fix → passed in the 212-test run above; codelines `test_explain.py` 600 → 592, `test_lint.py` 433 → 435; covquery: the deleted test's 673 lines are all inside the lint test's 690.

Orchestrator: Tier B, package Q-7.11. With the verifier's 2-line fix in `test_rules_this_source_does_not_use` (required).

### TBT-07 The example's four codec rules are written four times
- Kind: shared-setup
- Where: `packages/reframe/tests/batch/test_audio_rules.py` `EXAMPLE_RULES` (88-107), `packages/reframe/tests/batch/test_explain.py` `EXAMPLE_RULES` (50-67), `packages/reframe/tests/batch/test_lint.py::test_clean_defaults` (107-112) and `EXAMPLE` (335-341)
- Now: The same four `AudioCodecRule`s are written out in full four times: Hungarian 5.1 AC-3
  320, English 5.1 AC-3 384, stereo AAC 160, Opus catch-all 256 re-encode. Those are the rules
  of the 03 §Audio defaults example and decision 0019. `test_lint.py` writes them twice
  through its `rule()` helper (`if_fits` defaults to `passthru`, so the objects are equal).
- Change: move setup to `packages/reframe/tests/batch/defaults_tracks.py` (the shared helper
  module of this folder, already imported relatively): `EXAMPLE_CODEC_RULES: list[AudioCodecRule]`.
  `test_audio_rules.py` then has `EXAMPLE_RULES = AudioDefaults(codec_rules=EXAMPLE_CODEC_RULES)`,
  and `test_explain.py` has `EXAMPLE_RULES = EXAMPLE_CODEC_RULES`. In `test_lint.py`,
  `test_clean_defaults` uses `AudioDefaults(codec_rules=EXAMPLE_CODEC_RULES)` and `EXAMPLE`
  uses `AudioDefaults(codec_rules=EXAMPLE_CODEC_RULES, selection=...)`. Not `reframe_testing`:
  only this folder uses it, and X-04 settled on the folder's own `__init__.py` imports.
- Saved: 0 tests, about 24 code lines (about 51 go, about 19 for the constant and 3 import
  lines come back in), 0 s
- Guarantee kept by: unchanged. Every test keeps its input, which is now one object.
- Why nothing is lost: the values are identical (checked field by field: languages, source
  channels, codec, mixdown, max, `if_fits`).
- Docs and history: no test is removed. The C-12 "Done when" table test
  (`test_the_codec_rules_example_row_by_row`) keeps its rows. Only the rule list moves.
- Risk: low. A future change to one file's example would now change all four. That is
  intended, because they are meant to be the one example.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — The four rules are equal field by field in all four places (`AudioCodecRule` defaults: `languages=None`, `source_channels="any"`, `if_fits="passthru"`; `test_lint.defaults()` appends `CATCH_ALL` only when the last rule is not a catch-all, and the Opus rule is one). `test_audio_rules.py` does not import `defaults_tracks` yet, so it gains `from .defaults_tracks import EXAMPLE_CODEC_RULES`; `defaults_tracks.py` gains `AudioCodecRule` in its `reframe.models` import. `AudioCodecRule` stays imported in `test_audio_rules.py` and `test_explain.py` (used elsewhere; ruff clean). Pydantic shares the rule instances between `AudioDefaults` objects, and no test mutates them in place (`test_explain.py:271` only indexes). Lines measured: `defaults_tracks.py` +19, `test_audio_rules.py` -18, `test_explain.py` -17, `test_lint.py` -8 = **-24**, as the auditor said.
Checked: applied (with compact TBT-02) → `runtests.sh packages/reframe/tests/batch -k "not test_batch_service"`: 696 passed, 1 snapshot passed (load: shared slot); ruff, format check, mypy clean.

Orchestrator: Tier B, package Q-7.11.

## Looked at and kept

- `test_audio_rules.py::test_the_codec_rules_example_row_by_row` (4 cases) vs
  `test_explain.py::test_the_codec_rules_example_row_by_row_through_draft_and_explain`: the
  same four example rows and values, one through `apply_codec_rules` and one through
  `audio_stage` / `resolve_tracks`. The plan's C-12 "Done when" (`docs/plan/05-core.md:551-554`)
  asks for "a table test [that] reproduces the example … row by row". The audio_rules test is
  literally that table, and the explain one was M6 demo item 5 (`test-trim-reports/B.md`).
  Both stay.
- `test_main_tracks.py::test_take_none_is_an_error_only_when_no_main_track_is_taken` (3
  cases): its inputs are covered by `test_explain.py::test_no_listed_language_take_none_is_an_error_with_fixes`
  (base case "drop" → error, and the `keep_first` / `keep_all` loop). But
  `0031:257` and `0041:128` (R1-2) name it as the review-fix guard. Never drop.
- `test_selection.py::test_a_listed_commentary_does_not_count_as_found` vs
  `test_main_tracks.py::test_no_listed_language_counts_main_tracks_only`: the same input
  (`jpn` + `hun` commentary, `["hu"]`, `first_track`). They could merge, but `0031:242/248`
  and `0041:127` (R1-1) name both. Kept.
- `test_main_tracks.py::test_no_listed_language_through_the_facade` (2.6 s, real ffprobe):
  named in 0031 and 0041 (R1-1, R1-2). Kept.
- `test_anime_season.py::test_e01s_audio_setup_gives_identical_audio_settings` (equal line
  set with `test_the_example_steps`, the same setup as the snapshot test): it is the plan 04
  "Done when" bullet 2. Kept as its own test.
- `test_anime_season.py::test_an_override_survives_a_change_of_the_template` vs the
  Hypothesis test of the same name in `test_batch_properties.py`: the property never changes
  the overridden field itself (`unique=True`), and never covers job-side naming overrides,
  `row.override`, or another row following the template. Plan 04 "Done when" bullet 3. Both
  stay.
- `test_batch_service.py` (11 tests, 38 s) vs `jobs/test_cli_batch.py` vs
  `reframe-server/tests/test_batch.py`: the CLI tests check rendering and exit codes on replayed
  probes. The server tests check the route contract and the jail (overrides by source id,
  403s). The service tests are the only ones for `app.batch.derive` with the job's preset as
  base, `save_preset` followed by resolve by a case-folded preset name, `preset.not_found`
  rows, output-exists-in-a-batch, a check before naming, and a whole season through the real
  probe into the queue. No test asserts the same input at another layer. Kept (see "Speed
  notes").
- `test_file_identity.py::test_resolve_batch_through_a_linked_folder`: part 1 (already encoded
  plus `output_is_source` through a link) is also in
  `jobs/test_cli_file_identity.py::test_batch_never_writes_a_source_given_through_a_linked_folder`.
  Parts 2 and 3 (the service dedupes paths given through a link) are pinned nowhere else,
  because the CLI dedupes in `find_media_files` before the service. Kept.
- `test_file_identity.py::test_an_override_is_found_through_a_linked_folder`: the same override
  as `test_resolve.py::test_an_override_that_changes_the_compiled_rules_is_invalid`, but its
  point is finding the key through a link. Kept.
- `test_audio_rules.py::test_the_output_agrees_with_the_shared_helpers` (210 cases, 110
  distinct line sets, 0.25 s): `test-trim-reports/B.md` already cut it from 294 to 210 and
  kept every channel count and mixdown. Not reported again.
- `test_lint.py::test_builtin_presets_are_clean` (26 cases, 22 in one group): one case per
  built-in preset. `integration/test_builtin_presets_validate.py` fails only on errors, and
  this one also fails on warnings and info. B.md already kept it.
- Coverage groups checked and rejected (each case is a distinct input class or table entry
  with its own expected value):
  `test_descriptors.py::test_what_each_level_compares` (13 in one group: each change has its
  own per-level tuple);
  `test_audio_rules.py::test_passthru_codec` (9 + 3: the DTS profile cases record ffprobe's
  profile names, B.md);
  `test_requested_mixdown` / `test_channels_match` / `test_language_matches` (boundary pairs,
  already trimmed in B.md);
  `test_selection.py::test_language_identity` (5 share lines: ISO /B, /T, a name, a region, a
  script, already trimmed in B.md);
  `test_selectors.py::test_each_filter` (groups of 5/3/3/2: `en` vs `eng`, commercial name vs
  ffprobe profile, case-insensitive title, and so on);
  `test_selectors.py::test_result_rows[missing, required]` with
  `test_a_missing_required_rule_offers_to_make_it_optional` (same input, different
  assertion: match row vs fix patch);
  `test_result_rows[multiple]` / `[nth picks the second]` / `test_exact_matches_may_share_a_track`
  (different selectors and results);
  `test_derive.py::test_per_file_chapter_names_keep_the_base_presets_policy` (4 + 2: each
  name list against each base policy);
  `test_lint.py::test_audio_rules_with_one_default_track` (3 + 2: five different exemption
  rules);
  `test_lint.py::test_shadowed[earlier8]` / `[earlier9]` (mono vs stereo-or-less, 5.1-or-more
  vs stereo-or-less);
  `test_explain.py::test_burn_in` `foreign_audio` / `foreign_audio_then_first` with search on
  (two policy values; `then_first` differs when the search is off);
  `test_descriptors.py::test_subtitle_roles_without_the_prober` (hearing_impaired and captions
  are two flags);
  `test_audio_rules.py::test_the_bitrate_table_is_the_written_layout` 2.1 / 3.0(back) (two
  ffmpeg layouts that libopus refuses);
  `test_grouping.py::test_the_example_season_is_one_group` vs
  `test_two_seasons_of_one_release_are_one_group_at_the_standard_level` (different sources and
  names);
  `test_draft.py::test_multitrack` vs `test_season` (different probes).
- `test_draft.py::test_multitrack_probed_live`, `test_explain_media.py::test_foreign_audio_search_on_an_mkvmerge_file`:
  real-tool oracles (ffprobe, mkvmerge). Never drop.
- `test_descriptors.py::test_ac3_and_eac3_are_one_family`: AC-3 → E-AC-3 gives
  `[False, False, True]`, a case missing from `CASES` (whose base has no AC-3 track). It
  could become a `CASES` row only with a second reference source. Not worth it.
- `test_explain.py::test_dropped_tracks_have_a_reason_and_no_output` and
  `test_keep_everything_keeps_the_source_flags_with_one_default`: `test_defaults_properties`
  checks their generic invariants, but each also pins texts and flags that the property does
  not check.
- `test_rules.py::test_compiled_defaults_*`: Q-6 BAT-04 (Tier C). Not reported again.
- The shared helpers repeated across files (`summary`, `_codes` / `codes`, `_replace`,
  `recorded` / `_recorded`): Q-6 BAT-06 / X-04. Not reported again.

## Speed notes

- `test_batch_service.py`: 38 s for 11 tests. Each test makes a `Reframe` app and probes
  copies of the generated anime seasons with the real ffprobe (`needs_ffmpeg`). The tests
  of naming, collision and override logic do not need a real probe:
  `test_name_collisions`, `test_an_output_that_is_another_source`,
  `test_an_output_path_set_by_a_files_override_is_kept`,
  `test_output_paths_set_by_overrides_are_checked_in_the_batch[False|True]`,
  `test_a_check_sees_each_resolved_job_before_it_is_named_or_validated`,
  `test_derive_and_overrides_by_path_text` (about 25 s together). They could run
  `BatchService` on recorded probes with `BatchStubs` / `make_batch` from
  `packages/reframe/tests/jobs/test_cli_output_names.py:233-252` (placeholder files plus
  `recorded(anime(...))`), as `jobs/test_cli_file_identity.py::test_the_batch_service_keys_files_off_the_event_loop`
  already does. Keep `test_a_season_from_grouping_to_the_queue_and_its_preset_on_season_2`
  on the real probe as the end-to-end test.
- `test_batch_service.py::test_a_naming_edit_on_a_base_without_naming_keeps_the_settings_output_folder`
  (4.3 s) copies all 12 episodes of season 1 (`season(fixture_media, tmp_path, 1)`) but
  probes and uses only `files[0]`. Pass `1` as the episode (`season(..., 1, 1)`). It
  resolves nothing, so `A.recorded(1, 1)` plus `app.jobs.draft` would do.
- `test_file_identity.py::test_resolve_batch_through_a_linked_folder` (2.4 s) and
  `::test_an_override_is_found_through_a_linked_folder` (1.9 s): real ffprobe only to get
  `MediaSource`s. `BatchStubs` with recorded probes on real files and links would keep the
  file-identity point.

## Verifier notes

- Corrected totals. Tier A (TBT-01..04): 5 tests, -16 code lines with the compact TBT-02 form
  (TBT-01 -11, TBT-02 -3, TBT-03 -1, TBT-04 -1); -12 with the auditor's loop form. Tier B
  (TBT-05 -2, TBT-06 -6 net, TBT-07 -24): 2 tests, -32 lines. Tier A+B: 7 tests, -48 code lines
  (auditor: 5 / ~13 and 7 / ~50). Time saved stays well under 1 s. Collected after all Tier A+B
  test removals: 709 → 702 (`uv run pytest --collect-only -q -n 0 -p no:cacheprovider
  packages/reframe/tests/batch`).
- TBT-01: since the merged guard now carries both wrong-kind rules, it can also assert the
  subtitle cell (`[m for m in result.matches if m.kind == "subtitle"]`: missing / error with
  "the rule has audio settings: it makes no subtitle track"), which is the other half of the
  2d3390f fix and is not asserted by any test today. Optional, one or two lines.
- TBT-05: the Q-6.6 "Done when" names `test_anime_season.py` "pass unchanged". Q-6.6 is done,
  so this is no blocker, but the commit message should state that `test_anime_season.ambr` is
  unchanged (it was, in the check above).
- TBT-06: the lint test's English assertion then uses the unfiltered draft, so a future draft
  issue on that source (for example a new info note) breaks `test_lint.py` rather than
  `test_explain.py`. That is the same strictness the deleted test had, moved.
- All changes were made only in the verifier's worktree and undone (`git checkout -- .`;
  `git status` clean).

