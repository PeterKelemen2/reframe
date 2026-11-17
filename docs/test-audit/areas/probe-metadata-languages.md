# Area probe-metadata-languages: `packages/reframe/tests/probe/`, `tests/metadata/` (with `header/`), `tests/languages/`, `tests/test_languages.py`, `tests/test_chapters.py`

Baseline: 38 files, 1,191 tests, 7,888 test code lines, 296 s of test time.

All paths are relative to `packages/reframe/tests/` at commit 38cf3eb unless they start with
`docs/`, `testing/` or `packages/`. Read: CLAUDE.md, pyproject pytest options,
`testing/reframe_testing/` (`ebml.py`, `mkvtoolnix.py`, `fake_tools`), `docs/simplify/plan.md`,
Q-6 area file `docs/simplify/areas/probe-metadata.md`, decisions 0080, 0081, 0082 (and the
places of 0007, 0034, 0041 that name tests of this area), plan C-20 "Done when", and the earlier
trim reports **`docs/test-trim-reports/N.md`** (languages and naming), **`P.md`** (probe and
definitions), and the parts of **`Q.md`** (keeps `metadata/test_metadata_edit_real.py` whole) and
`C.md` that touch this area. No finding removes a test that those reports keep; where a finding
touches a test they name, it says so.

## Summary

17 findings: 8 Tier A, 7 Tier B, 2 Tier C.

- Tier A: 7 tests, about 58 code lines, about 0.2 s of measured test time, plus an unmeasured
  saving in `languages/test_equivalence.py` (TPM-01).
- Tier A + B: 15 tests, about 131 code lines, about 13 s of test time (most of it TPM-02 and
  TPM-13), plus TPM-01.

The best three:

1. TPM-01: `test_equivalence._differences` loops function by function over up to 215,688 tags,
   so the 4096-entry LRU caches of `normalize` thrash and every tag is parsed and normalised
   five times on each side. Looping tag by tag computes it once. Same inputs, same functions,
   same assertion. It applies to the 181 s file; the gain needs measuring.
2. TPM-02: CI never deselects `slow`, so the "fast subset" tests of `test_equivalence.py`
   compare inputs that the slow sweeps compare again (about 10 s: a 13.4 s test whose
   `normalize`/`english_name`/`native_name` inputs are all in the 88 s sweep, plus two tests that
   are strict input subsets of two other sweeps).
3. TPM-12/TPM-10: two real-file tests (`test_the_reprobe_shows_only_the_files_bcp47_tags`,
   `test_probe_shows_language_ietf`) repeat a real-tool setup and assertion that a sibling test
   already has. Merging keeps every assertion and saves a real queue run or a real
   mkvpropedit + ffprobe run each.

The area was already trimmed (P, N reports) and Q-6 did PRB-07 and PRB-13. Most of what is
left is real-tool, oracle, fault-injection, snapshot or data-table tests. Those stay.

## Findings

### TPM-01 Compute each tag once in the equivalence sweeps (loop order of `_differences`)
- Kind: other (speed with the same guarantee)
- Where: `languages/test_equivalence.py::_differences` (170-178). It is used by
  `test_registry_aliases_extlangs_grandfathered_and_odd_tags` (181),
  `test_listed_languages_with_sample_regions_and_scripts` (185),
  `test_listed_languages_with_every_region_and_script` (192, 88.5 s),
  `test_every_registry_language_with_a_region_and_a_script` (201, 10.6 s),
  `test_characters_whose_case_forms_are_ascii` (321, 7.5 s) and the property test (350).
- Now: `for name in functions: for value in values:`. The test runs each function over the whole
  input list before it starts the next. In both implementations, `english_name`, `native_name`,
  `to_matroska_legacy`, `to_mp4`, `to_matroska_ietf`, `base_language`, `short_code` and `entry`
  start with `normalize(value)` (`languages.py:576-579`, `oracle.py:266-268`). `normalize` is
  memoised by `functools.lru_cache(maxsize=4096)` on `_normalize_code` and `_parse` (ours
  `languages.py:448, 474`; oracle `oracle.py:156, 184`). With 215,688 inputs per pass, the cache
  is always cold, so each tag is normalised and parsed again for each of the 5 (or 10)
  functions, on both sides.
- Change: swap the two loops: `for value in values: for name in functions:`. Nothing else
  changes. The tests compare the same (function, value) pairs with the same `got != want` and
  `== []` assertions. Only the order of a failure list changes.
- Saved: 0 tests, 0 lines. Time is **not measured**: at most 4 of the 5 normalisations per tag
  on each side, which is a share of 88.5 + 13.4 + 10.6 + 3.8 + 7.5 s. The oracle already caches
  `Language.get` in langcodes' unbounded `_PARSE_CACHE`, so it gains less than ours. The verify
  agent must time `uv run pytest -n 0 packages/reframe/tests/languages/test_equivalence.py
  --durations=0` before and after. If the gain is small (under about 10 %), drop the finding.
- Guarantee kept by: the same tests: every (function, input) pair of today, the same comparison.
- Why nothing is lost: the functions are pure. An LRU hit returns what a recomputation would
  return, so the order of the calls cannot change a result.
- Docs and history: `test_equivalence.py` is the C-20 "Done when" 1 test (0082 item 5,
  `docs/plan/05-core.md:857`); its corpus and functions stay exactly the same. All tests from
  9254919 (feat C-20).
- Risk: low (a loop order in a test helper).
- Proposed tier: A (if the measured gain holds)
- Confidence: medium (on the size of the gain); high (on the guarantee)

Verdict: CONFIRMED — the swap compares exactly the same (function, value) pairs with the same `_call` and `got != want`; each failure tuple is still `(name, value, want, got)`, so a failure still names the function and the input (only the order of the list, and so which 20 show, changes). `_differences` is called with lists everywhere (one pass over `values` now instead of N, so a generator would also work). Measured gain (CPU time, same inputs, interleaved): 30 % on the 88 s sweep (63.2/63.7 s → 44.2/44.4 s CPU), 25-33 % on the registry-language sweep, about 48 % on the sample test and 47 % on the registry/odd test: far above the 10 % bar. Tier A stands. Estimated saving per full run: about 26 s of the 88 s sweep, about 6 s of the 13.4 s sample test, about 3 s of the 10.6 s test, about 1.8 s of the 3.8 s test, and an unmeasured share of the 7.5 s case-forms test: about 37-40 s of the file's 181 s (about 20 %).
Checked: `runtests.sh packages/reframe/tests/languages/test_equivalence.py -n 0 --durations=0` before → 16 passed in 189.4 s (load 39.6 at start, 9.8 at end; 81.96 s every-region, 17.95 s sample, 9.15 s registry-language, 9.57 s case-forms, 5.25 s registry/odd). After the swap → 16 passed in 241.8 s, but the load was about twice as high (load 18-24; the unaffected `test_search_every_name_in_every_locale` went 48.0 → 94.6 s and `test_names_of_listed_languages_in_every_locale` 0.75 → 1.57 s), with every-region 78.55 s, sample 9.33 s, registry-language 18.46 s, case-forms 13.20 s, registry/odd 1.96 s. The pytest pair is not comparable under that load, so the two orders were also timed interleaved in one process on the same inputs, caches cleared before each run, after a warm-up (`uv run python $SCRATCH/vpml/bench_order.py`, load 22-33 on 12 threads) → registry/odd ×10 functions (14,066 values): by function 5.24 / 6.08 s, by value 2.92 / 3.11 s wall; sample ×5 (22,572): 20.99 / 17.82 s → 10.57 / 9.16 s wall; registry languages ×3 (41,070): 13.45 / 11.76 s → 9.50 / 8.68 s wall (second run, CPU: 10.56 / 9.93 s → 8.28 / 6.59 s); every region ×5 (215,688): first run too noisy (by function 47.2 s at load 13.7 and 109.2 s at load 32.9; by value 69.4 / 66.1 s at load 30-32), second run with CPU time at load 15-19: by function 66.10 / 64.89 s wall, 63.19 / 63.68 s CPU; by value 46.03 / 46.13 s wall, 44.18 / 44.36 s CPU. 0 differences in every run.

Orchestrator: Tier A, package Q-7.7. In the speed package, together with SPD-02 (the same test file); measured −22 % CPU, not −30 %.

### TPM-02 The fast subsets of `test_equivalence.py` repeat the slow sweeps in every run
- Kind: layer-duplicate (a subset test beside its superset sweep)
- Where:
  - `languages/test_equivalence.py::test_listed_languages_with_sample_regions_and_scripts` (185):
    418 listed bases × (34 regions + 20 scripts) = 22,572 tags; `normalize`, `validate`,
    `english_name`, `native_name`, `entry`. 13.36 s.
  - `::test_search_names_in_other_locales` (271): `search` over `_locale_names()[::40]`. 1.16 s.
  - `::test_prefix_matches_of_names` (228): `normalize` over `_with_suffixes(_locale_names()[::5])`.
    0.65 s.
- Now: the module docstring says "The full sweeps are `slow`; the other tests run a fixed subset
  of the same corpus". No run deselects `slow`. `pyproject.toml` only registers the marker, and
  the CI commands, CLAUDE.md, `docs/simplify/plan.md` and the Windows VM notes all run with
  `-m "not needs_gpu"` or `-m "not needs_gpu and not benchmark"`. 0082 "Built: L" says "CI runs
  both (it does not deselect `slow`)". So every run compares these inputs twice:
  - every tag of the sample test is in the input of `test_listed_languages_with_every_region_and_script`
    (all registry regions and scripts include the 34 + 20 samples: the sample has `DD`, `BU`,
    `QM`, `XZ`, `AA`, `ZZ`, `Qabx`, which are all registry region/script subtags or range ends,
    `_plain(_subtags(...))`), for `normalize`, `english_name` and `native_name`. Only
    `validate` and `entry` are not in the slow sweep;
  - `_locale_names()[::40]` is a subset of `_locale_names()` in
    `test_search_every_name_in_every_locale` (same function `search`, no favourites, same
    comparison);
  - `_with_suffixes(_locale_names()[::5])` is a subset of
    `_with_suffixes(_locale_names())` in `test_every_key_of_the_name_tables` (same function
    `normalize`).
- Change: in the sample test, keep only the functions that no sweep has:
  `functions = ("validate", "entry")`. Delete `test_search_names_in_other_locales` and
  `test_prefix_matches_of_names`. Change the module docstring line about the fast subset. (The
  other choice is to add `validate` and `entry` to the 88 s sweep and delete the sample test. It
  makes the sweep slower by about two fifths, so it is not proposed.)
- Saved: 2 tests, about 6 code lines, about 1.8 s plus about 8 s of the 13.4 s test (3 of its 5
  functions, estimated, not measured).
- Guarantee kept by: `::test_listed_languages_with_every_region_and_script` (192):
  `normalize`/`english_name`/`native_name` over a superset of the tags;
  `::test_search_every_name_in_every_locale` (276): `search` over every locale name;
  `::test_every_key_of_the_name_tables` (233): `normalize` over all suffixed forms; the sample
  test keeps `validate` and `entry` over its 22,572 tags.
- Why nothing is lost: each removed comparison is the same function on the same input with the
  same assertion (`ours == oracle`) inside a test that every run executes. What is lost: a
  developer who runs `-m "not slow"` gets fewer checks. No document or CI job does that today.
- Docs and history: `grep -rn` over `docs/` (without the trim reports) finds none of the three
  names; 0082 "Built: L" describes a "fast part 19 s" and a "slow part about 130 s", and the
  C-20 "Done when" names the corpus, which the sweeps keep in full. All three tests are from
  9254919 (feat C-20), not from a fix.
- Risk: low to medium (it gives up the fast part as a stand-alone check, which 0082 describes).
- Proposed tier: B (it changes the fast/slow split that 0082 "Built: L" records; that text needs a
  one-line update)
- Confidence: high

Verdict: ADJUSTED — nothing deselects `slow` (CI `ci.yml:107` `-m "not needs_gpu and not benchmark"`, `:418` `-m "needs_ffmpeg and not needs_gpu and not benchmark"`, `:462` benchmark only; no script in `scripts/`; 0082:150 "CI runs both (it does not deselect `slow`)"; CLAUDE.md, `docs/simplify/plan.md`, 0084 and the 38cf3eb Windows notes all run without `-m "not slow"`; `pyproject.toml:108` only registers the marker), so the premise holds and the two deletions are confirmed (`_locale_names()[::40]` and `_with_suffixes(_locale_names()[::5])` are literal slices of the sweeps' inputs). But the sample test is NOT a subset of the 88 s sweep: region `172` and script `Kawi` are not in `language_data`'s registry, so `_plain(_subtags("region"/"script"))` does not have them, and the 836 tags `<base>-172` / `<base>-Kawi` (a CLDR macro-region outside the IANA registry, a script newer than the registry) get `normalize`/`english_name`/`native_name` only in the sample test. Correction: the sample test keeps `("validate", "entry")` over the 22,572 tags AND `("normalize", "english_name", "native_name")` over `_combined(_listed_bases(), ("172",), ("Kawi",))` (2 lines more; or add `"172"`/`"Kawi"` to the sweep's region/script lists). Numbers: 2 tests and about 4 code lines net (not 6); time about 1.5-2 s of the sample test (not about 8 s: after TPM-01 the whole sample test is about 7 s and `validate` + `entry` are most of it) plus about 1.9 s for the two deleted tests: about 3.5-4 s in all, not about 10 s. Tier B stands (0082 "Built: L" text needs the line).
Checked: `uv run python $SCRATCH/vpml/chk.py` (sample values not in the sweep's registry lists) → `missing regions ['172']`, `missing scripts ['Kawi']`. `uv run python $SCRATCH/vpml/bench_split.py` (with the TPM-01 order, warm, load 28) → today's 5 functions 7.20 / 7.26 s, adjusted split 5.91 / 5.42 s. The adjusted change applied in the worktree: `runtests.sh test_equivalence.py -n 0 -k sample_regions` → 1 passed (10.1 s alone, cold tables); file collects 14 tests instead of 16.

Orchestrator: Tier B, package Q-7.11. As adjusted: the sample test keeps `validate` and `entry` over all its tags and the three other functions over the `172`/`Kawi` tags; update 0082 "Built: L" in the same commit.

### TPM-03 A smaller input set or a stored oracle for the 88 s and 46 s sweeps
- Kind: other
- Where: `languages/test_equivalence.py::test_listed_languages_with_every_region_and_script`
  (192, 88.5 s), `::test_search_every_name_in_every_locale` (276, 45.9 s)
- Now: the first compares 5 functions over 215,688 tags, the second `search` over 38,345 names.
- Change (two options, neither proposed for now):
  1. White-box reduction: `to_matroska_legacy` and `to_mp4` are functions of the primary
     language subtag of `normalize(value)` in both modules (`languages.py:587-600`,
     `oracle.py:277-290`). They could be compared over one tag per distinct normalised primary
     language (about 420 tags plus one invalid input) instead of all 215,688. This would save 2
     of the 5 functions (estimate: up to 40 % of 88 s).
  2. Store the oracle's results once per `langcodes`/`language_data` version (a generated,
     compressed result file, like the tables) and compare `reframe.languages` with the stored
     file. This roughly halves both sweeps. `gen-language-data.py --check` would also check the
     stored results.
- Saved: up to about 35 s (option 1) or about 65 s (option 2), estimated.
- Guarantee kept by: option 1 only while the implementation stays a function of the language
  subtag. Option 2 only while the stored file is rebuilt with each library update.
- Why it is Tier C: option 1 replaces a black-box guarantee with a white-box argument. C-20
  "Done when" 1 names "every listed base language with every region and script" for
  `to_matroska_legacy` and `to_mp4`. Option 2 is a CI and tooling change. The native names
  (the per-locale region names) need the full cross product in any case. Each (locale, region)
  pair reads a different entry of the locale-names table.
- Docs and history: 05-core.md:857 (C-20 "Done when" 1), 0082 item 5 and "The equivalence
  check"; the Q-6 area file keeps `test_equivalence.py` ("the oracle is the check for each
  CLDR update").
- Risk: medium
- Proposed tier: C
- Confidence: medium

Verdict: CONFIRMED — Tier C, not proposed; C-20 "Done when" 1 and 0082 item 5 name the full cross product. Note: TPM-01 already takes about 30 % of the 88 s sweep's CPU time without any white-box argument.

Orchestrator: Tier C, not planned: kept (see the verdict).

### TPM-04 `test_the_matroska_reader_is_hashed` is a weaker copy of one parametrized case
- Kind: near-copy
- Where: `probe/test_cache_fingerprint.py::test_the_matroska_reader_is_hashed` (58)
- Now: it asserts `"probe/matroska.py" in cache_mod._PARSER_FILES`.
  `::test_a_change_to_a_reader_changes_the_fingerprint[probe/matroska.py]` (50) changes a copy
  of `matroska.py` and asserts that the fingerprint changes.
- Change: delete.
- Saved: 1 test, 2 code lines, about 0 s.
- Guarantee kept by: `probe/test_cache_fingerprint.py::test_a_change_to_a_reader_changes_the_fingerprint[probe/matroska.py]`:
  same file, and a stricter assertion (the behaviour, not the list membership).
- Why nothing is lost: if `matroska.py` leaves `_PARSER_FILES`, the parametrized case fails too.
- Docs and history: none name it. Both tests come from 9c91444 (RB-7). 0041 and 0007 name
  `test_a_change_to_a_reader_changes_the_fingerprint` as the RB-7 guard, and it stays.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — 0041:222 names only the parametrized test as RB-7's guard; the deleted one (also 9c91444) asserts list membership, and the `[probe/matroska.py]` case fails if `matroska.py` leaves `_PARSER_FILES`. 1 test, 2 code lines.
Checked: deleted in the worktree; `runtests.sh test_cache_fingerprint.py …` → part of 294 passed.

Orchestrator: Tier A, package Q-7.3.

### TPM-05 Two tests pin `Prober.cache_options()`
- Kind: near-copy
- Where: `probe/test_prober.py::test_cache_options_name_the_reader` (328),
  `probe/test_matroska_limits_and_ietf.py::test_the_cache_options_name_the_new_reader` (255)
- Now: the first asserts `cache_options() == {"matroska": MATROSKA_READER}`, the second
  `cache_options()["matroska"] == 4`.
- Change: merge into `test_matroska_limits_and_ietf.py::test_the_cache_options_name_the_new_reader`
  with `assert Prober("ffprobe").cache_options() == {"matroska": 4}`. Delete the `test_prober.py`
  test and its `MATROSKA_READER` import (line 25, its only use).
- Saved: 1 test, about 3 code lines.
- Guarantee kept by: the merged test: the exact dict (one key) and the literal value 4.
- Why nothing is lost: `{"matroska": 4}` holds both assertions: no other key, and the value that
  makes older entries misses. A change of `MATROSKA_READER` already fails the second test.
- Docs and history: only `docs/simplify/areas/probe-metadata.md:94` (PRB-05, Tier C, "not
  planned before v1"; it would delete both tests together with the option). The first test is
  from 5384c5e (feat C-19). The second is from fee150b (review R4-2..R4-6) and stays.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `cache_options()` is `{"matroska": MATROSKA_READER}` and `MATROSKA_READER = 4` (`prober.py:81,173`); the import at `test_prober.py:25` has no other use. The kept test is fee150b's (R4-2..R4-6 review); its input is unchanged and its assertion is stricter. PRB-05 (Tier C) is not affected. 1 test, about 3 lines.
Checked: applied; `runtests.sh test_prober.py test_matroska_limits_and_ietf.py …` → part of 294 passed.

Orchestrator: Tier A, package Q-7.3.

### TPM-06 `test_the_byte_sum_check_covers_every_stream` is inside the compressed-track test
- Kind: near-copy
- Where: `probe/test_bitrate.py::test_the_byte_sum_check_covers_every_stream` (133)
- Now: two stats streams (900 + 200 bytes) in a 1000-byte file give `stale == {0, 1}`.
- Change: delete.
- Saved: 1 test, 4 code lines.
- Guarantee kept by: `probe/test_bitrate.py::test_a_compressed_track_is_left_out_of_the_size_check`
  (154), first assertion: three streams (900 + 50 + 300 bytes) in a 1000-byte file, no
  `compressed` argument, give `set(stale) == {0, 1, 2}`. Each stream alone is under the size,
  and each one is marked. `test_an_uncompressed_overrun_still_makes_every_uncompressed_track_stale`
  (176) checks the same rule with `compressed`.
- Why nothing is lost: same function, same input class (sum over size, each stream under it),
  the same "every stream is stale" assertion, with more streams.
- Docs and history: none. 3d2e602 (M1 review fixes, a feature list, no bug or ID named for this
  test). The coverage map puts it in the same 51-line group as `test_stale_stats[stream0]`.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — the kept test's first assertion is the same function on the same input class (every stream under the size, the sum over it, no `compressed`), with three streams; covquery: deleted 51 lines ⊂ kept 53 lines. 3d2e602 names no bug for it. 1 test, 4 lines.
Checked: `covquery.py test_the_byte_sum_check_covers_every_stream test_a_compressed_track_is_left_out_of_the_size_check` → only A: 0 lines; applied, `test_bitrate.py` → part of 294 passed.

Orchestrator: Tier A, package Q-7.3.

### TPM-07 Merge the two huge-`TimestampScale` regression tests
- Kind: near-copy (merge)
- Where: `probe/test_sampling.py::test_a_huge_timestamp_scale_keeps_the_rates_unknown` (576),
  `::test_a_huge_timestamp_scale_does_not_fail_the_folder` (587)
- Now: both probe `_huge_timestamp_scale_file(...)` with a fake ffprobe that returns
  `_video(0), _audio(1)`, duration 4.0. The first asserts that the video and audio rates are
  `BitrateInfo()`. The second probes it beside a good file and asserts that both are
  `MediaSource`, in order, and that the good file's audio is `ESTIMATED`.
- Change: merge into `test_a_huge_timestamp_scale_does_not_fail_the_folder`. Add
  `assert [sources[0].video[0].bitrate, sources[0].audio[0].bitrate] == [BitrateInfo(), BitrateInfo()]`.
  Delete the first test.
- Saved: 1 test, about 6 code lines (8 removed, 2 added), 0.06 s.
- Guarantee kept by: the merged folder test: the same damaged file (same helper), the same
  stream layout, the same "rates unknown" assertion, and the folder assertions.
- Why nothing is lost: the fake ffprobe answers the same streams for both files. The JSON names
  the good file, but the parser takes the path it is given. The damaged file goes through the
  same `MatroskaError` path (an unsigned integer over 8 bytes) and has no cache in both tests.
- Docs and history: `docs/simplify/areas/server-service.md:69` (SRV-01) says to rewrite, not
  delete, the folder test. It stays. Both tests come from 916314b, "fix(C-19): a huge
  TimestampScale no longer raises out of the probe", which is a bug fix. The merged test keeps
  that exact input and both assertions.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — the merged folder test keeps 916314b's exact damaged input (the same `_huge_timestamp_scale_file` bytes, the same fake ffprobe streams `_video(0), _audio(1)`, duration 4.0, a first probe with no cache) and gains the "rates unknown" assertion; covquery: deleted 745 lines ⊂ folder test 1023. The only difference is the file name (`huge.mkv` → `e01.mkv`) and the folder around it. Keep SRV-01's "rewrite, not delete" note on the folder test in mind: whoever rewrites it must keep this assertion.
Checked: applied in the worktree; `runtests.sh` on test_sampling.py, test_matroska.py, test_matroska_limits_and_ietf.py, test_metadata_unusual_files.py, test_metadata_edit_real.py with TPM-07..TPM-12 applied → 108 passed (114 before), load ~25.

Orchestrator: Tier A, package Q-7.3.

### TPM-08 `test_a_sample_that_cannot_read_the_file_leaves_the_rates_unknown` is the `unreadable` case of a later test
- Kind: near-copy
- Where: `probe/test_sampling.py::test_a_sample_that_cannot_read_the_file_leaves_the_rates_unknown` (539)
- Now: `sample_clusters` raises `PermissionError`, and the test asserts that
  `audio[0].bitrate == BitrateInfo()` on `_two_audio_file`.
- Change: delete. To keep the subclass as an input, `_first_sample_cannot_read` (612) can raise
  `PermissionError("the share went away")` instead of `OSError(...)`. It takes the same branch,
  so this is optional.
- Saved: 1 test, about 9 code lines, 0.08 s.
- Guarantee kept by: `probe/test_sampling.py::test_a_sample_that_could_not_run_is_not_cached[unreadable]`
  (630): same file (`_two_audio_file`), `sample_clusters` raises `OSError`, and the first probe
  asserts `once.audio[0].bitrate == BitrateInfo()`. The test also asserts the re-sample.
- Why nothing is lost: `PermissionError` and `OSError` both end in `except OSError` of
  `prober._worker` (`prober.py:461`). The assertion is the same, and the input is otherwise the
  same. The coverage map shows A (831 lines) ⊂ B (1061).
- Docs and history: none. 5384c5e (feat C-19). The later test is from eee854b (a fix) and stays.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `PermissionError` and `OSError` both end in `except OSError` of `_worker` (`prober.py:461`); covquery: deleted 831 lines ⊂ `[unreadable]` 1061. 5384c5e is a feature commit. 1 test, about 9 lines.
Checked: deleted in the worktree → part of the 108 passed above.

Orchestrator: Tier A, package Q-7.3.

### TPM-09 Merge the time-limit sample test into the not-cached test
- Kind: near-copy (merge)
- Where: `probe/test_sampling.py::test_a_sample_over_the_time_limit_leaves_the_rates_unknown`
  (485), `::test_a_sample_that_could_not_run_is_not_cached[timed-out]` (630)
- Now: both make the first sample overrun `SAMPLE_TIMEOUT` (0.05 s and 0.2 s) on
  `_two_audio_file`. The first asserts that both audio rates are unknown, that
  `warnings == []`, and that `stop()` is true. The second asserts that `audio[0]` is unknown,
  then that the next probe samples again. It only checks `stop()` implicitly: its stub loops
  until `stop()`.
- Change: in the parametrized test, record the `stop` callback of `_first_sample_times_out`.
  For `timed-out`, assert `stop()`, `once.warnings == []` and
  `[a.bitrate for a in once.audio] == [BitrateInfo(), BitrateInfo()]`. Delete the first test.
- Saved: 1 test, about 14 code lines, 0.1 s.
- Guarantee kept by: the merged `[timed-out]` case: the same overrun, the same three
  assertions, and the cache assertions.
- Why nothing is lost: same file, same code path (`TimeoutError` in `_worker`). Each assertion
  of the deleted test moves into the merged test.
- Docs and history: none. 5384c5e (feat C-19).
- Risk: low to medium (the stub must keep returning once `stop()` is true)
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — covquery: deleted 833 lines ⊂ `[timed-out]` 1062. The deleted stub ignores `stop` and blocks on an event, the kept one polls `stop()`; the deleted test has no time assertion, so a prober that waited for its worker would pass both, and nothing is lost by the change of stub. Applied as a module list `_STOPS` filled by `_first_sample_times_out` and checked for the `timed-out` case (`stop()` true, `warnings == []`, both audio rates unknown): passes. Saved 1 test, about 11 code lines net (not 14). Tier B stands.
Checked: applied → part of the 108 passed above; `test_sampling.py` 554 → 523 code lines for TPM-07+08+09 together (auditor: 29).

Orchestrator: Tier B, package Q-7.11.

### TPM-10 `test_probe_shows_language_ietf` repeats the real-file BCP 47 probe test
- Kind: near-copy (merge)
- Where: `probe/test_matroska.py::test_probe_shows_language_ietf` (224) and its helper `_raise`;
  `probe/test_matroska_limits_and_ietf.py::test_bcp47_comes_from_the_track_in_matroska_and_from_the_iso_code_elsewhere` (337)
- Now: both copy the `multitrack` fixture, set `LanguageIETF` with the real mkvpropedit, and
  probe with the real ffprobe:
  - the first sets a1 = hun/hu and a2 = por/pt-BR and asserts the audio
    `(language, language_ietf)`. Then it makes `read_matroska` raise and asserts that the audio
    tags are `None` and that there is no "Matroska" warning;
  - the second sets a2 = por/pt-BR and asserts the tag of all 7 streams and the audio languages.
    Then it checks the MP4 and `und` cases.
- Change: in the second test, set a1 = hun/hu as well, in the same mkvpropedit call. Assert
  `_all_ietf == [None, "hu", "pt-BR", None, None, None, None]` and audio languages
  `["hun", "por", "eng"]`. Add the "reader raises" part (monkeypatch `matroska.read_matroska`, a
  second probe with `use_cache=False`, audio tags `None`, no "Matroska" warning). Delete the
  first test and `_raise`.
- Saved: 1 test, about 15 code lines, 0.32 s (one fixture copy, one mkvpropedit run, two real
  probes).
- Guarantee kept by: the merged test: both edited tracks, all streams, the damaged-reader path,
  MP4 and `und`.
- Why nothing is lost: every assertion of the first test is in the merged one. The second
  test's R4-3 rule ("a Matroska track without `LanguageIETF` gets no tag from its legacy
  language") is still asserted on a3 (`eng` → `None`) and on the three subtitles.
- Docs and history: none name `test_probe_shows_language_ietf` (f1c4a9c, C-13). The second test
  (5384c5e, the renamed `test_probe_with_mediainfo_on_keeps_only_the_files_bcp47_tags` of
  0007/0034/0041 R4-3) stays and gains assertions.
- Risk: low
- Proposed tier: B (it changes the input of a regression test)
- Confidence: medium

Verdict: ADJUSTED — as written, the merge changes the input of the R4-3 regression test (0041:151, renamed from `test_probe_with_mediainfo_on_keeps_only_the_files_bcp47_tags`): `a1` is the only `jpn` track of `multitrack` (ffprobe: v und, a jpn/eng/eng, s eng×3), and R4-3's bug derived both `jpn → ja` and `eng → en`; setting `a1 = hun/hu` takes the `jpn`-without-`LanguageIETF` case out of the regression test (it would survive only in `test_probe_of_a_file_with_a_seek_position_past_2_63`). Correction: do not add the `a1` edit; move only the "reader raises" part into the regression test, after its existing assertions and on its existing file (`monkeypatch.setattr(matroska, "read_matroska", _raise)`, a second `Prober(ffprobe).probe(copy, use_cache=False)`, audio tags `[None, None, None]`, no "Matroska" warning), and delete `test_probe_shows_language_ietf`. The "two audio tracks edited with real mkvpropedit, real probe" input of the deleted test is then held by `test_languages_names_and_flags_the_reprobe_shows_them_all` (a1 = hu, a2 = pt-BR, s1 = hu, real writer, real re-probe, Linux and Windows CI). covquery: the deleted test's only own lines are the `damaged` branch of `_worker` (`prober.py:458-466`), which the moved part keeps. Saved 1 test, about 17 code lines net (move `_raise` with it or import it). Tier B stands (the regression test gains a second probe but keeps its exact file and assertions).
Checked: the adjusted variant applied → part of the 108 passed above (mkvpropedit, mkvmerge and ffprobe present, no skips).

Orchestrator: Tier B, package Q-7.11. As adjusted: move only the "reader raises" assertions; the R4-3 test's file stays unchanged.

### TPM-11 Merge `test_apply_matroska_sets_ietf_by_kind_and_order` into the two `apply_matroska` tests
- Kind: near-copy (merge)
- Where: `probe/test_matroska.py::test_apply_matroska_sets_ietf_by_kind_and_order` (144);
  `probe/test_matroska_limits_and_ietf.py::test_matched_tracks_get_the_files_value_or_none`
  (215), `::test_tracks_that_do_not_match_change_nothing` (230)
- Now: all three call `apply_matroska` on `parse_probe("fixtures/multitrack.mkv")` with a
  `MatroskaFile` of video, audio×3, subtitle×3:
  - the first test, matched: pt-BR, None, en-GB on the audio gives
    `["pt-BR", None, "en-GB"]`. Mismatched (one subtitle popped): it returns `False`, the exact
    warning text, and all audio `None`;
  - `test_matched_tracks…`: a2 = pt-BR with preset values gives `None` everywhere except a2;
  - `test_tracks_that_do_not_match…`: mismatched, with a preset a1 = "ja", returns `False` and
    keeps "ja".
- Change: in `test_matched_tracks…`, use `_file(None, None, "pt-BR", "en-GB", None, None, None)`
  and expect `[None, None, "pt-BR", "en-GB", None, None, None]`. In `test_tracks_that_do_not_match…`,
  give the file audio values (`_file(None, "pt-BR", None, "en-GB", …)` minus one subtitle), and
  assert the exact warning text and `[a.language_ietf for a in source.audio] == ["ja", None, None]`.
  Delete the first test.
- Saved: 1 test, about 15 code lines.
- Guarantee kept by: the two merged tests: order by kind with two tagged audio tracks, `None`
  over preset values, `False` on a mismatch, the warning text, nothing written on a mismatch
  (non-`None` values in the file, a preset value kept).
- Why nothing is lost: each input class and assertion of the deleted test is in one of the two.
- Docs and history: `test_matched_tracks…` is the R4-3 guard (0034:227, 0041:151). It keeps its
  rule ("tags derived from jpn/eng are not the file's": a1 and the subtitles still go to `None`).
  The deleted test is from f1c4a9c (C-13) and no document names it.
- Risk: low
- Proposed tier: B (it changes the input of a regression test)
- Confidence: medium

Verdict: ADJUSTED — as written, the merge changes the input of the R4-3 guard `test_matched_tracks_get_the_files_value_or_none` (0034:227, 0041:151): its `a3` preset `en` (derived from `eng`) would be overwritten by `en-GB` instead of going to `None`, so one of R4-3's own cases moves out. Not needed: the deleted test's matched half (two tagged tracks of one kind land by order) is already in `test_a_value_that_is_not_a_language_tag_is_not_used` (R4-4), whose file tags subtitles 1 and 3 (`de`, `pt-BR`) and asserts `[…, "de", None, "pt-BR"]`. Correction: leave `test_matched_tracks…` unchanged; only change `test_tracks_that_do_not_match_change_nothing` (5384c5e, not a regression test) to give the file audio values (`_file(None, "pt-BR", None, "en-GB", None, None, None)` minus a subtitle) and assert the exact warning text and `["ja", None, None]`; delete the C-13 test. covquery: deleted test's own lines vs each keeper are `prober.py:481-485` (mismatch warning) and `486-496` (matched loop), both still run. Saved 1 test, about 19 code lines net. Tier B stands.
Checked: the adjusted variant applied → part of the 108 passed above.

Orchestrator: Tier B, package Q-7.11. As adjusted: leave the R4-3 guard unchanged; extend only `test_tracks_that_do_not_match_change_nothing`.

### TPM-12 `test_the_reprobe_shows_only_the_files_bcp47_tags` repeats the reprobe test of the real edit
- Kind: near-copy (merge)
- Where: `metadata/test_metadata_unusual_files.py::test_the_reprobe_shows_only_the_files_bcp47_tags`
  (75); `metadata/test_metadata_edit_real.py::test_languages_names_and_flags_the_reprobe_shows_them_all` (186)
- Now: both draft a remux of the `multitrack` copy through the real facade and queue, and set
  audio 0 = hu, audio 1 = pt-BR, the commentary flag on audio 2, and subtitle 0 = hu. They run the
  in-place edit and re-probe. The edit_real test also sets names, `original`,
  `hearing_impaired` and the title, and asserts (language, ietf, title, three flags) for the 3
  audio tracks and subtitle 0, including `("eng", None)` for the untouched audio 2. The
  unusual_files test asserts (language, ietf) for audio and all 3 subtitles, and that
  `mkvmerge -J` agrees when MKVToolNix is there.
- Change: in `test_languages_names_and_flags…`, add the rows `("eng", None)` for
  `out.subtitles[1:]` and the `mkvmerge(env.source)` agreement block (`[t.get("language_ietf")
  for t in tracks[1:]] == ["hu", "pt-BR", None, "hu", None, None]`). Delete the other test.
- Saved: 1 test, about 14 code lines, 1.09 s (one app start, one real edit, one re-probe).
- Guarantee kept by: the merged test: the same edits (a superset), every stream's
  (language, ietf), and the MKVToolNix agreement.
- Why nothing is lost: the rule under test is "untouched tracks have no `LanguageIETF`; no tag
  is derived from `eng`". The merged test asserts it on audio 2 and subtitles 1-2, after the
  same kind of edit. The deleted test's own setup is a subset of the other's.
- Docs and history: 0034:231 and 0041:151 (R4-3) name it under its old name
  `test_with_mediainfo_on_the_reprobe_shows_only_the_files_bcp47_tags` (renamed in ce19c10 when
  MediaInfo left; the MediaInfo-on part of the regression is gone with 0081). The edit_real test
  is R4-6's guard (0034:266, 0041:154), and trim report Q keeps `test_metadata_edit_real.py`
  whole. This finding only adds assertions there. The R4-3 table row in 0041 needs the new name.
- Risk: low
- Proposed tier: B (a renamed regression test of a review finding)
- Confidence: medium

Verdict: REJECTED — the deleted test is a named regression test (R4-3, 0041:151 and 0034:231 under its old name; renamed in ce19c10, from fee150b), and the keeper does not pin its exact input: the R4-6 test's edit also sets three names, `original`, `hearing_impaired` and the container title, so the writer makes a different file (longer elements, possibly another layout) before the re-probe. Under the rule (a regression test stays unless another test pins the exact same input) it stays. It is also needs_ffmpeg only (no `needs_mkvtoolnix`), so it runs on the Windows CI job, and its `mkvmerge -J` block is an oracle comparison. If the owner wants the merge anyway, the mechanics work: applied in the worktree it passed (the merged R4-6 test keeps its < 1 s `seconds(ended)` check, the new assertions come after it), saving 1 test, about 15 code lines net and about 1.1 s, and 0041's R4-3 row must then name the R4-6 test.
Checked: merge applied (assertions added to `test_languages_names_and_flags_the_reprobe_shows_them_all`, the unusual-files test deleted) → part of the 108 passed above; `git log -S` → ce19c10 (rename), fee150b (original).

Orchestrator: Tier C, not planned: rejected in verify (named R4-3 regression test; the keeper does not pin its input).

### TPM-13 The plain multi-cluster sample test is the attachment test without the attachment
- Kind: near-copy
- Where: `probe/test_sampling_media.py::test_a_multi_cluster_ffmpeg_file_is_sampled_at_offsets`
  (114); `::test_an_ffmpeg_attachment_is_not_counted_as_video` (176)
- Now: the first encodes `_generated` (20 s 720p MPEG-2 + AAC, clusters ≤ 0.5 s), asserts that it
  is over 8 MiB, that `check_against_the_block_scan == 2`, and that the video has 10-32 samples.
  The second remuxes the same `_generated` output with a 4 MiB attachment (same
  `-cluster_time_limit 500`) and asserts the attachment, `check_against_the_block_scan == 2` and
  10-32 samples.
- Change: move `assert out.stat().st_size > 8 * 1024 * 1024` into `_generated` (97), where it
  guards every user, and delete the first test.
- Saved: 1 test, about 5 code lines, 2.46 s (one 20 s MPEG-2 encode and probe).
- Guarantee kept by: `::test_an_ffmpeg_attachment_is_not_counted_as_video` (176): an FFmpeg
  file of the same streams and clusters, sampled at offsets (10-32 samples), with both rates
  close to the exact block scan.
- Why nothing is lost: the sampling path is the same. Each window reads clusters, and the
  attachment sits in front of them. The kept test asserts the same rates and sample count. The
  only input left out is "FFmpeg file without an attachment, larger than the windows", which
  differs from the kept input by an element that the sampler skips.
- Docs and history: none. 5384c5e (feat C-19). The attachment test is from 1c7e4cd (a fix) and
  stays.
- Risk: low to medium (a sampling bug that only shows without an attachment would be missed)
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED — covquery: deleted 1218 lines ⊂ attachment test 1230 (only the attachment's `parse.py` lines extra). Both are `needs_ffmpeg` only, so the keeper runs wherever the deleted test ran (Linux and Windows CI). Risk stays low-medium (an FFmpeg file without an attachment is no longer sampled on its own; the plain fixtures of `test_every_fixture_stream_has_a_rate…` are probed but are mostly not larger than the windows). Tier B stands.
Checked: `covquery.py test_a_multi_cluster_ffmpeg_file_is_sampled_at_offsets test_an_ffmpeg_attachment_is_not_counted_as_video` → only A: 0 lines.

Orchestrator: Tier B, package Q-7.11.

### TPM-14 One copy of the file surgery helpers for the bogus Seek entry and the invalid `LanguageIETF`
- Kind: shared-setup
- Where: `probe/test_matroska_limits_and_ietf.py::_with_bogus_seek_entry` (267),
  `::_with_bad_tag` (359); `metadata/test_metadata_unusual_files.py::_header` (22),
  `::with_bogus_seek_entry` (34), `::with_bad_tag` (59)
- Now: two copies of each surgery. The two `with_bogus_seek_entry` write the same bytes. The
  probe copy uses `seek(_TRACKS, 2**64 - 1)` = `element(0x4DBB, element(0x53AB, 1654AE6B) +
  element(0x53AC, b"\xff" * 8))`, the metadata copy writes that element out. The metadata copy
  parses with its own `_header`, a copy of `reframe.probe.matroska._header` that PRB-07 left
  behind. The two `with_bad_tag` differ only in how they find mkvpropedit (an argument against
  `mkvtoolnix_tool`).
- Change: move `with_bogus_seek_entry(path)` and `with_bad_tag(path, mkvpropedit, bad)` to
  `testing/reframe_testing/ebml.py` (or `mkvtoolnix.py` for the second). Use
  `reframe.probe.matroska._header`, as `tests/metadata/header/corpus.py:19` already does. The
  four tests import them. Delete the copies and the `_header` copy.
- Saved: 0 tests, about 30 code lines (about 65 removed, about 35 added).
- Guarantee kept by: the same tests on byte-identical files.
- Why nothing is lost: the helpers make the same bytes (checked above). The tests' inputs and
  assertions do not change.
- Docs and history: the users are R4-2 regression tests (fee150b). They stay unchanged. PRB-07
  (Q-6.2, done) did the EBML builders, not these surgeries.
- Risk: low
- Proposed tier: A
- Confidence: medium (the verify agent runs the five users, three of which need MKVToolNix)

Verdict: CONFIRMED — both surgeries produce byte-identical files on `multitrack` (the bogus Seek entry, and the bad tag for `en_US` and `j\na;x`); `mkvtoolnix_tool` and the probe test's `_tool` both `shutil.which` and skip, so passing the tool path as an argument keeps each test's skip behaviour. About 73 code lines go (two bogus-seek copies, two bad-tag copies, the `_header` copy), about 35-40 come back in `reframe_testing`: about 30-35 net. The R4-2/R4-4 users keep their inputs. Tier A stands.
Checked: `uv run python $SCRATCH/vpml/bytes_cmp.py` → `seek identical: True` (and differs from the source), `bad tag identical: b'en_US' True`, `b'j\na;x' True`. Not refactored in the worktree; the four users passed in the 108-test run.

Orchestrator: Tier A, package Q-7.3.

### TPM-15 Two parametrization rows that another test already holds
- Kind: param-trim
- Where:
  - `test_chapters.py::test_the_file_is_read_as_utf8_utf16_or_latin1[1,Caf\xe9\n-names3-codes3]` (204, row at 201);
  - `test_languages.py::test_search_ranking[tgl-first11]` (353, row at 349).
- Now:
  - the Latin-1 row (`b"1,Caf\xe9\n"`) is read through the Windows-1252 path. It asserts the name
    and the `chapters.not_utf8` code;
    `test_a_file_that_is_not_utf8_is_read_as_windows_1252_where_it_can_be[Windows-1252]` (334)
    takes the same path and asserts the name, the code and "read as Windows-1252". The coverage
    map puts both in one 56-line group. Its `[Latin-1 (ISO 8859-1)]` row covers the real
    Latin-1 fallback;
  - `search("tgl")[:1] == ["tl"]`: `test_search_finds_every_entry_first` (491) asserts
    `search(key)[0] == item` for every ISO code of every entry, and `tl`'s ISO 639-2/B is `tgl`
    (`test_language_entry_fields`).
- Change: drop both rows. In the chapters test, the `codes` parameter is then always `[]`.
  Assert `result.issues == []` and rename the test `test_the_file_is_read_as_utf8_or_utf16`.
- Saved: 2 tests, about 4 code lines.
- Guarantee kept by: the two tests named above.
- Why nothing is lost: same function, same path, same or stricter assertion.
- Docs and history: none name either. The chapters test is from 4e50294 (S-2 tests), the
  Windows-1252 test from 9d91074. `test_search_ranking` is from 4ddd077 (C-6). Trim report N
  already removed the other ISO-code rows of this table with the same argument ("
  `test_search_finds_every_entry_first` checks the tag, every ISO code"), and `tgl` is one of
  them. PRB-01 (Tier C) keeps `search` and its tests, and this trim does not remove `search`
  coverage.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `b"1,Caf\xe9\n"` decodes to the same text in Windows-1252 and Latin-1, so it takes the Windows-1252 path that `[Windows-1252]` takes with a stricter assertion (the `read as` text and exactly one issue); the `[Latin-1 (ISO 8859-1)]` row holds the real fallback. `tl` is `LanguageEntry(tag='tl', iso639_2b='tgl', variant=False)`, so `test_search_finds_every_entry_first` asserts `search("tgl")[0]` is `tl`; trim report N dropped the other ISO-code rows on that argument. 2 tests, about 4 lines.
Checked: both rows dropped → `test_chapters.py`, `test_languages.py` part of 294 passed.

Orchestrator: Tier A, package Q-7.3.

### TPM-16 Run the entry-variant property test over every entry instead of 300 samples
- Kind: property-covers (the other way: an exhaustive loop beats sampling a finite domain)
- Where: `test_languages.py::test_property_normalize_variants_of_an_entry` (522);
  `::test_container_codes_round_trip_for_every_entry` (451)
- Now: Hypothesis samples 300 (entry, form) pairs from 429 entries × 5 forms (2,145 pairs). The
  exhaustive tests beside it cover the name forms and `normalize(tag) == tag`, but not the
  upper-case, `_` and ISO-code forms of every tag.
- Change: move the five forms into `test_container_codes_round_trip_for_every_entry` as a loop
  over every entry and form, with the same assertions. Delete the Hypothesis test.
- Saved: 1 test, about 4 code lines; time about the same (2,145 cached `normalize` calls against
  300 Hypothesis examples, 0.14 s).
- Guarantee kept by: the extended exhaustive test: every pair instead of a sample, the same
  assertions.
- Why nothing is lost: the domain is finite and small. Trim report N kept this test because "it
  is the only test of upper-case and `_` forms of every tag". The loop keeps that test, now for
  every tag, so N's reason still holds after the change.
- Docs and history: none. 4ddd077 (C-6).
- Risk: low
- Proposed tier: B (a rewrite)
- Confidence: high

Verdict: CONFIRMED — N kept the property test only as "the only test of upper-case and `_` forms of every tag"; the loop tests every (entry, form) pair with the same four assertions, so N's reason is met. Applied (the loop inside `test_container_codes_round_trip_for_every_entry`, messages `(item.tag, form)`): passes, and the test stays under 1.3 s. Lines: about 0-4 net (the loop needs the same form table; `entries` may become unused). Tier B stands.
Checked: applied → `test_languages.py` part of 294 passed; not in the top 5 durations (< 1.25 s).

Orchestrator: Tier B, package Q-7.11.

### TPM-17 The `DocTypeVersion` oracle matrix runs one in-process path per edit for "title only"
- Kind: param-trim
- Where: `metadata/header/test_header_oracle.py::test_the_doc_type_version_is_raised_as_mkvpropedit_does`
  (192): 3 files × 5 edits × 4 versions × 2 CRC = 120 cases, 27.6 s, 43 distinct line sets
- Now: for "title only", the 8 version×CRC cases of each file share one line set (the coverage
  map has 3 groups of 8). The edit does not touch `Tracks`, so the writer never raises the
  version. Each case still runs mkvpropedit and compares.
- Change (not proposed): keep "title only" at versions 1 and 4 only (12 → saves 12 cases, about
  2.8 s).
- Why it is Tier C: these are `needs_mkvtoolnix` oracle cases. Each compares with what
  mkvpropedit 103 does on that version. The decision says so: 0080 "Built" item 3: "The oracle
  tests compare both with mkvpropedit on `DocTypeVersion` 1 to 4 copies, with and without an
  EBML `CRC-32`". A trim gives up the check that mkvpropedit leaves the version alone for a
  title edit at versions 2 and 3.
- Docs and history: 0080 item 3 of the FW/FE review fixes; review table "DocTypeVersion not
  raised".
- Risk: medium
- Proposed tier: C
- Confidence: high

Verdict: CONFIRMED — Tier C, not proposed; these are `needs_mkvtoolnix` oracle comparisons named by 0080 "Built" item 3 ("DocTypeVersion 1 to 4 copies, with and without an EBML CRC-32", 0080:334). No oracle comparison may be dropped.

Orchestrator: Tier C, not planned: kept (see the verdict).

## Verifier summary

17 findings: 13 CONFIRMED (TPM-01, 03, 04, 05, 06, 07, 08, 09, 13, 14, 15, 16, 17; the numbers of TPM-01, 09 and 14 are restated in their verdicts), 3 ADJUSTED (TPM-02, 10, 11), 1 REJECTED (TPM-12).

Corrected totals:

- Tier A (TPM-01, 04, 05, 06, 07, 08, 14, 15): 7 tests, about 58-63 code lines (TPM-14 about 30-35), plus TPM-01's measured speed-up: 25-48 % of each `_differences` sweep, about 37-40 s of the file's 181 s per full run.
- Tier A + B (adds TPM-02 adjusted, 09, 10 adjusted, 11 adjusted, 13, 16): 14 tests (TPM-12 rejected), about 115-125 code lines (A 58-63 + TPM-02 4 + TPM-09 11 + TPM-10 17 + TPM-11 19 + TPM-13 5 + TPM-16 0-4); test time about 0.2 s (A) + about 3.5-4 s (TPM-02 adjusted) + 0.1 + 0.3 + 2.5 s ≈ 7 s, plus TPM-01's speed-up.
- Test counts checked in the worktree: the five probe/metadata files 114 → 108 (TPM-07..12 applied, TPM-12 included there); the six files of TPM-04/05/06/15/16 300 → 294; `test_equivalence.py` 16 → 14. Without TPM-12, Tier A+B removes 14 tests.

## Looked at and kept

- `languages/test_equivalence.py::test_the_kelvin_sign_is_not_a_k`: its inputs are in
  `test_characters_whose_case_forms_are_ascii`, but it pins absolute values (`fuj`, `None`) and
  the scan entry. It is the R2 regression (0082 "Review fixes" 1).
- `languages/test_equivalence.py::test_names_of_listed_languages_in_every_locale`: its raw names
  are not keys of the tries (those are normalised), so `test_every_key_of_the_name_tables` does
  not contain them.
- `languages/test_equivalence.py` property tests (random input outside the corpus),
  `test_language_list`, `test_matches_and_same_language`,
  `test_every_registry_language_with_a_region_and_a_script` (only 5 % overlap with the 88 s
  sweep, and it holds the unlisted languages): C-20 "Done when" corpus.
- `languages/test_ties.py` (84 cases, 18 line sets): each row is one tie that 0082 "Ties"
  fixes, and the tests run without the libraries.
- `languages/test_without_libraries.py`: C-20 "Done when" 3.
- `test_languages.py` example tables (`test_normalize`, `test_invalid`, `test_container_codes`,
  `test_names`, `test_same_language`, `test_matches`, the B/T pairs): they pin absolute values
  without the dev libraries. The equivalence tests only compare against the oracle. Trim report
  N already trimmed them to one row per input class.
- `test_languages.py` real-tool tests (`test_ffmpeg_writes_language_verbatim`, 9 cases in one
  line set; the mkvpropedit cross-checks): verified tool behaviour.
- `metadata/header/test_header_oracle.py` (all 166): `needs_mkvtoolnix` oracle (0080 item 5);
  see TPM-17 for the one trim considered. `test_the_writer_and_mkvpropedit_read_back_the_same`
  has 36 cases and 34 line sets. `test_six_thousand_character_names…[mkvpropedit-moved]` and
  `[reframe-moved]` share a line set but are two different file layouts.
- `metadata/header/test_header_faults.py`, `test_header_layouts.py`, `test_header_refusals.py`,
  `test_header_properties.py`, `test_own_thread.py`: 0080 items 3-4 (refusals, torn writes,
  fault injection, OwnThread). `test_a_torn_copy…[9]` and `[200]` share lines but are different
  tear lengths. The refusal tests each build another hostile layout.
- `metadata/test_metadata_edit_real.py` (all): trim report Q keeps it whole. The three
  "under a second" / flags tests each classify a different edit as `metadata_edit`, and each
  needs a fresh source.
- `metadata/test_remux_job.py`: 5 tests in a subset chain. Each asserts another branch
  (in place, new file, not mkv, exact metadata, broken ietf).
- `probe/test_recorded_probes.py` against `probe/test_snapshots.py` (the coverage map pairs
  them by recorded file): the snapshot is stricter, but snapshots are refreshed in bulk with
  `--snapshot-update` (PRB-11 plans exactly that for 61 of them). The named field assertions are
  what survives a careless refresh. P kept "recorded-probe and snapshot tests".
- `probe/test_live.py` against `test_sampling_media.py::test_every_fixture_stream_has_a_rate…`
  (equal or contained line sets): real ffprobe, different assertions (structure against rates).
- `probe/test_prober.py::test_relative_path_is_made_absolute`,
  `::test_concurrent_probes_of_one_file_share_one_ffprobe` (equal line sets with
  `test_probe_parses_the_output`): another input (a relative path) or another behaviour (single
  flight, from the M1 review).
- `probe/test_cache.py` (`test_invalidation`, `test_a_tool_change_is_overwritten`,
  `test_corrupt_entry…`), `test_cache_nesting.py` boundaries, `test_cache_file_names.py`:
  already trimmed by P, and each one is a key or boundary rule of C-3.
- `probe/test_cache_fingerprint.py::test_a_change_to_a_reader_changes_the_fingerprint` (8 cases,
  1 line set): each case is another hashed file. RB-7 guard.
- `probe/test_names.py`, `test_roles.py`, `test_parse.py::test_field_order`, `test_hdr.py`
  tables (cases in a few line sets): one map entry or keyword per row (P kept them by rule).
- `probe/test_matroska.py::test_generated_fixture_and_mkvpropedit_edits`: the reader against
  `mkvmerge -J` (oracle).
- `probe/test_matroska_limits_and_ietf.py::test_probe_of_a_file_with_a_seek_position_past_2_63`
  against `metadata/test_metadata_unusual_files.py::test_an_in_place_edit_of_a_file_with_a_seek_position_past_2_63_is_refused`:
  the probe against the writer's refusal (R4-2). Different layers, different assertions.
- `probe/test_sampling.py::test_the_prober_estimates_and_reruns_the_commentary_heuristic`
  (contained in three other tests' lines): it is the only one that asserts the estimates and
  the heuristic re-run.
- `test_chapters.py` mkvmerge-behaviour tests (`test_ogm_lines_end_only_where_mkvmerge_ends_them`,
  4 cases in 1 line set, etc.): each separator is a verified mkvmerge behaviour.

## Speed notes

- `languages/test_equivalence.py::test_listed_languages_with_every_region_and_script` (88 s) and
  `::test_search_every_name_in_every_locale` (46 s) are single tests, so under xdist each one
  occupies one worker. Parametrizing them over slices of the input (for example 8 slices of the
  listed bases) keeps the same total work and comparisons, and shortens the tail of a parallel
  run. The suite's wall time was 374 s, so the gain is small unless these two end the run.
- `probe/test_sampling_media.py::_generated` (a 20 s 720p MPEG-2 encode) runs in 4 tests (3
  after TPM-13). A module-scoped fixture that encodes once per worker, with each test using or
  copying its output, saves up to 2-3 encodes (about 1.5-2 s each).
- `languages/test_equivalence.py::_case_maps_to_ascii` (a scan of all of Unicode, about 1 s) is
  computed in each worker that runs `test_the_kelvin_sign_is_not_a_k` or
  `test_characters_whose_case_forms_are_ascii`. This is minor.

## Verifier notes

- The auditor's subset check for TPM-02 missed that two sample values (`172`, `Kawi`) are not registry subtags. Any later change to the sweeps' region/script lists should keep those two (or move them into the slow sweep).
- `test_equivalence.py` timings in `durations.txt` are under xdist load; single tests in this file move by 2x with the machine's load (the unaffected `test_search_every_name_in_every_locale` went 48 s → 95 s between two of my runs). Compare speed changes in this file interleaved in one process, not with two pytest runs.
- TPM-10 and TPM-11 as written would each have changed an input of an R4-3 guard (the only `jpn` track; the `en`-derived `a3`). The adjusted versions keep both guards' inputs and move only the deleted tests' extra assertions.
- The 916314b input survives TPM-07 unchanged, but SRV-01 (`docs/simplify/areas/server-service.md:69`) plans a rewrite of the folder test; that rewrite must keep the huge-scale file and the new "rates unknown" assertion.
- No finding removes or weakens a `needs_mkvtoolnix` oracle comparison (TPM-17 stays Tier C; TPM-12, which would have moved an `mkvmerge -J` agreement block, is rejected).
- The worktree edits were undone (`git checkout -- .`) and the `testdata/media` link removed; `git status` clean at 38cf3eb.
