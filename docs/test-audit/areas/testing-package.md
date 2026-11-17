# Area testing-package: `testing/tests/` (tests of `reframe_testing` and of the release and packaging scripts in `scripts/`), plus repeated setup that `testing/reframe_testing/` could hold

Baseline: 23 files, 567 tests, 6,628 test code lines (plus 4,487 lines of `reframe_testing` helpers), 29.5 s of test time.

All paths and line numbers refer to `/home/peti/Programming/reframe-test-audit` at 38cf3eb. Per-test times come from `$SCRATCH/junit.xml` (the baseline run).

## Summary
There are 13 findings. Tier A (9 findings) removes 22 tests and about 105 code lines. Tier A+B (11 findings) removes 23 tests and about 210 code lines. TTK-02 and TTK-08 are Tier C: a decision record names those tests as mutation guards, so they stay. Almost no test time is saved (about 0.7 s), because this area's time is in the real-FFmpeg fixture checks and the fake-process tests. Those tests pin verified tool behaviour or process behaviour, and all of them stay.

**Verifier summary:** 13 findings: 12 confirmed, 1 adjusted (TTK-09), 0 rejected. Corrected totals: Tier A 21 tests and about 95 code lines; Tier A+B 22 tests and about 205 code lines (TTK-02 and TTK-08 stay, Tier C).

The three best:
- TTK-13 (B): every script test file repeats the same 8-line `_load_script` by-path loader (10 copies, plus one in `packages/reframe/tests/tools/test_fetch.py`). One `reframe_testing.scripts.load_script(name)` saves about 90 lines.
- TTK-09 (A): the two `main` tests of `test_fetch_tools.py` copy a 19-line TOML manifest and the same setup. A helper, plus one parametrized `verify_file` reject test, saves about 38 lines and 1 test.
- TTK-04 + TTK-01 (A): in `test_third_party_notices.py`, five pairs of tests build the same state and then assert different things. Merging each pair into one test saves 7 tests and about 24 lines, and every assertion stays.

`packages/reframe/tests/tools/test_fetch.py` and `testing/tests/test_fetch_tools.py` test different code: `reframe.tools.fetch` and the standalone stdlib `scripts/fetch-tools.py` (decision 0038, TP-01 Tier C). The two meet only in two cross-tests, which check the manifest read and the install marker of one against the other. No duplicate is reported there.

## Earlier test trim (5dbf152)
I read all ten reports in `docs/test-trim-reports/` (B, C, M, N, P, Q, R, T, V1, V2), searching them for every file in this area, for `reframe_testing`, `testing/`, `scripts/`, `fetch-tools` and `_load_script`. None of them touches a test in `testing/tests/`. Their only mentions of `testing/` say that no helper there lost its last user. T.md works on `packages/reframe/tests/tools/test_fetch.py`: its flaky `test_fetch_installs_the_build_and_skips_an_intact_install` and the `ftp://` case of `test_a_bad_manifest_is_refused`. TTK-13 changes only that file's `_load_script` loader. It removes or changes no test that T.md names, so no earlier decision is proposed again.

## Findings

### TTK-01 One test for "which archives a platform's notices list" and "their licence texts"
- Kind: near-copy
- Where: `testing/tests/test_third_party_notices.py::test_the_notices_list_only_the_archives_that_the_platform_bundles` (503, 4 cases), `::test_the_notices_carry_the_licence_text_of_each_archive_the_platform_bundles` (803, 4 cases)
- Now: both tests are `@pytest.mark.usefixtures("no_sections")` and `@pytest.mark.parametrize("platform", sorted(BUNDLED))`. Both run `tpn.main(["--platform", platform, "--out", out, *_sources(tmp_path)])` on the same `MANIFEST` and the same default sums and texts. The first test checks the source URL line and the listed `sha256  archive` lines against `BUNDLED[platform]`. The second checks, in the licence-texts section, that each archive's "Source archive:" line and its text appear exactly when the platform bundles it.
- Change: merge into `test_the_notices_list_only_the_archives_that_the_platform_bundles`, renamed for example `test_the_notices_list_and_carry_the_texts_of_only_the_archives_the_platform_bundles`. Add the `_section(...)` loop of the second test after the existing asserts.
- Saved: 4 tests, about 7 code lines, about 0.02 s
- Guarantee kept by: the merged test, with the same 4 platform cases, the same `_sources(tmp_path)` input and every assertion of both tests.
- Why nothing is lost: the input is the same (fixture, options and platform list), so the merged test has the union of the assertions.
- Docs and history: there is no grep hit by function name in `docs/`. 0079 line 1131 describes the second test ("the texts per platform [every archive on every platform; no section; the `:amd64` suffix kept]"). Those mutations stay caught, because the assertions do not change. `git log -S`: c444a83 "feat(Q-5): each package's notices list only its platform's part…" and 8f2ba04 "feat(Q-5): the full licence text of every bundled part…" (owner's answer 0079 item 11). Neither is a bug fix.
- Risk: low. The merged test fails at the first wrong assertion, so the message names a single failure where the two tests could show two.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — same fixture, same 4 platform cases, same `_sources(tmp_path)`; the second test's loop drops in after the first test's asserts (rename its `text` local, e.g. `licence`, because `text` is already the file's content). Keep the docstring "The owner's rule: every bundled part's licence text…" on the merged test. 0079 line 1131's three mutations (every archive on every platform; no section; `:amd64` suffix kept) are still asserted. No doc names either test by function name; both from features (c444a83, 8f2ba04). Measured together with TTK-03 and TTK-04: see TTK-04.
Checked: applied TTK-01 + TTK-03 + TTK-04 in the worktree; `pytest --collect-only` test_third_party_notices.py 94 → 81 (−13 = 4 + 6 + 3); `runtests.sh testing/tests/test_fetch_tools.py testing/tests/test_sources_fetch.py testing/tests/test_third_party_notices.py -q` → 180 passed, 1 skipped (no frozen sidecar, as at baseline), 1.9 s, slot free; ruff, ruff format, mypy green.

Orchestrator: Tier A, package Q-7.6.

### TTK-02 `bundles()` per kind of source: the end-to-end notices test already checks every archive on every platform
- Kind: layer-duplicate
- Where: `testing/tests/test_third_party_notices.py::test_each_kind_of_source_goes_to_the_packages_that_bundle_it` (520-538, 7 cases)
- Now: the test calls `tpn.bundles(entry, p)` for 7 of the 10 `MANIFEST` archives and checks that the set of platforms equals a hand-written set that mirrors `BUNDLED`.
- Change: delete (proposed only; see Proposed tier).
- Saved: 7 tests, 18 code lines, 0.01 s
- Guarantee kept by: `::test_the_notices_list_only_the_archives_that_the_platform_bundles` (503). For all 10 `MANIFEST` archives × all 4 platforms, it asserts `sorted(_listed_archives(text)) == sorted(BUNDLED[platform])`. The listed archives are `platform_sources(...)`'s `wanted`, which is `[entry for entry in entries if bundles(entry, platform)]` (`scripts/third-party-notices.py:342`).
- Why nothing is lost: the end-to-end test's inputs are a superset of the unit test's, and its assertion (exact set equality per platform) is as strict.
- Docs and history: 0079 line 905 lists "`test_third_party_notices.py` the kinds per platform [TN-repo, TN-repo2]" as a mutation guard of the R1 review round. 48b7560 added the `repository` (type2-runtime) case. The record does not name the function, but this test is the "kinds per platform" guard it means.
- Risk: medium, because a decision record names it as a guard.
- Proposed tier: C. The rules say a guard named in a decision record is never dropped. The guarantee is in fact kept by the end-to-end test, so if the owner wants it, the test can go in the same commit as a one-line note in 0079.
- Confidence: high (that it is redundant); the tier comes from the rule.

Verdict: CONFIRMED (stays, Tier C) — 0079 line 905 "`test_third_party_notices.py` the kinds per platform [TN-repo, TN-repo2]" is this test (c444a83 added it; the only test calling `tpn.bundles` per kind). The end-to-end test does reach `bundles()` for all 10 archives × 4 platforms with exact set equality, so the redundancy claim holds, but the guard rule keeps it. Do not count it in any total.

Orchestrator: Tier C, not planned: kept (see the verdict).

### TTK-03 Trim the "all four or none" subsets of the notices options from 14 to 8
- Kind: param-trim
- Where: `testing/tests/test_third_party_notices.py::test_the_sources_options_are_given_all_four_or_none` (628-640, 14 cases: every subset of size 1, 2 and 3)
- Now: every case reaches the same check, `if None in given and any(value is not None for value in given): parser.error(...)` (`scripts/third-party-notices.py:829`), and asserts `SystemExit` code 2.
- Change: trim the cases to sizes 1 and 3 (`for size in (1, 3)`): each option given alone (4 cases) and each option left out alone (4 cases). The 6 pairs go.
- Saved: 6 tests, 0 code lines, about 0.03 s
- Guarantee kept by: the size-1 cases fail if any option is missing from the `given` list (that option alone would then pass without an error). The size-3 cases fail if the check treats "three of four" as enough.
- Why nothing is lost: a pair adds no input class beyond what the single cases and the triples give. With one option missing from `given`, a pair either gives that option alone, which is the single case, or gives two listed options, which also errors in a single case.
- Docs and history: there is no grep hit by name. 0079 line 1133, "the four options together [`--sources-texts` optional]": that mutation (texts left out of `given`) is caught by the kept `[3]` and `[0, 1, 2]` cases. 8f2ba04 (feature).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `main` has one check (`None in given and any(...)`, line 829); sizes 1 and 3 give 8 cases that catch each option left out of `given` (its single case passes) and a "three is enough" mutation (the triples). A pair adds no input class. 0079 line 1133 "the four options together [`--sources-texts` optional]" stays caught by `[3]` and `[0, 1, 2]`. 6 tests, 0 code lines (the change is `(1, 2, 3)` → `(1, 3)`).
Checked: applied (see TTK-01); 14 → 8 cases, all pass.

Orchestrator: Tier A, package Q-7.6.

### TTK-04 Three more same-setup pairs in `test_third_party_notices.py`
- Kind: near-copy
- Where:
  - (a) `::test_a_bundled_archive_missing_from_the_sums_is_an_error` (564) and `::test_another_platforms_archive_missing_from_the_sums_is_not_this_ones_concern` (578)
  - (b) `::test_the_bundled_ffmpeg_gets_its_pin_with_the_source_links` (166) and `::test_a_library_built_into_a_tool_gets_its_pin_and_licence` (192)
  - (c) `::test_a_library_without_its_licence_file_is_an_error` (219) and `::test_a_library_pinned_for_another_platform_gets_no_entry` (227)
- Now:
  - (a) The same sums, every `MANIFEST` archive except libva. The first test runs main for linux-x64 and expects code 1 with "the sums have no line for libva…". The second runs main for windows-x64 and expects 0.
  - (b) The same layout, `ffmpeg` with `LICENSE.txt` and `LICENSE-libva.txt`, then `tool_entries(tools, REPO_ROOT/"tools", "linux-x64")`. The first test checks entry 0 (ffmpeg); the second checks the names and entry 1 (libva).
  - (c) The same layout, `ffmpeg` without the libva licence. linux-x64 raises "LICENSE-libva.txt"; windows-x64 gives only the ffmpeg entry.
- Change: merge each pair into its first test, adding the second test's call and assertions. This is how `test_a_bundled_archive_without_licence_texts_is_an_error` (840) already asserts linux and windows in one test.
- Saved: 3 tests, about 17 code lines (a: 8, b: 6, c: 3), about 0.02 s
- Guarantee kept by: the merged tests, with the same inputs and all assertions.
- Why nothing is lost: each pair has the same setup, the inputs differ only in the platform argument, and both calls stay.
- Docs and history: there is no grep hit by name. (a) c444a83 (feature). (b) and (c): 7ae6ed2 and 02af157 (D-8 features; 02af157 mentions 0072's "FB fix-round" paragraph about libva). The assertions of that round all stay.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — each pair has the same setup and differs only in the platform argument. (a) needs an `options = _sources(tmp_path, sums=sums)` local so the second `main` call fits; the first call's `capsys` read and `not out.exists()` come before the windows run, so no assertion is weakened. (b) `[entry, libva] = …` already pins the two names; the merged test needs a second pin variable (use `libva_pin`, not a reused `pin`, for reading). Review R1-6 in 0072 ("libva missing from the notices", fixed by FB) is the history of (b)/(c); all its assertions stay. No doc names these tests.
Checked: applied (see TTK-01); TTK-01 + TTK-04 measured −26 code lines (auditor 7 + 17 = 24); 3 tests.

Orchestrator: Tier A, package Q-7.6.

### TTK-05 Merge the two Ubuntu source-package fetch tests
- Kind: near-copy
- Where: `testing/tests/test_sources_fetch.py::test_an_ubuntu_source_package_is_its_dsc_and_every_file_it_lists` (362), `::test_an_ubuntu_archive_keeps_no_owner_or_time_of_the_fetching_host` (532)
- Now: both call `entry = _launchpad(tmp_path, monkeypatch)` and `sf.fetch_all([entry], out)`. The first checks the members and `_texts(out) == {}`. The second opens the tar and checks every member's uid, gid, uname, gname and mtime. The coverage map groups them (2 tests, 28 lines).
- Change: merge into `test_an_ubuntu_source_package_is_its_dsc_and_every_file_it_lists` and add the owner and time assertions.
- Saved: 1 test, about 5 code lines, about 0.02 s
- Guarantee kept by: the merged test, with the same `_launchpad` input and the assertions of both tests.
- Why nothing is lost: the input and the fetch call are the same.
- Docs and history: there is no grep hit by name. 0079 line 901, "archive times and owners [SF3, SF15]": the assertion stays, so the mutation is still caught. The second test came from 48b7560 "fix(Q-5): … (review R1's findings)" ("archive reproducibility"). Its exact input and assertion are kept in the merged test.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — same `_launchpad` input and the same `fetch_all` call; the owner/time assertion (0079 line 902 "archive times and owners [SF3, SF15]", added by 48b7560's R1 fix) moves unchanged, so SF3/SF15 stay caught. The `assert members` non-empty check is implied by the kept member-list assertion. Saved 1 test, 6 code lines (auditor ~5).
Checked: applied with TTK-06; test_sources_fetch.py 38 → 36 collected; −23 code lines for TTK-05 + TTK-06 together; all pass (run above).

Orchestrator: Tier A, package Q-7.6.

### TTK-06 One btbn-stage test for "several commits in sub folders" and "each sub folder's licence"
- Kind: near-copy
- Where: `testing/tests/test_sources_fetch.py::test_a_stage_may_pin_one_repository_at_several_commits` (221), `::test_a_stage_that_checks_out_into_sub_folders_gives_each_ones_licence` (590)
- Now: both build a `btbn-stage` entry whose commands `git-mini-clone` twice into two sub folders and set `SCRIPT_REPO2`/`SCRIPT_COMMIT2`. The first uses one repository at two commits and checks the archive members. The second uses two repositories and checks `_texts(...)` per sub folder.
- Change: merge into `test_a_stage_may_pin_one_repository_at_several_commits`. Write another `LICENSE` text in the second commit (one more line) and add the `_texts(...)[entry["archive"]] == {"sdk11/LICENSE": ..., "sdk13/LICENSE": ...}` assertion.
- Saved: 1 test, about 14 code lines, 0.15 s
- Guarantee kept by: the merged test. It keeps the regression input of 7f18fbc (one repository pinned at several commits) and the licence-per-sub-folder assertion.
- Why nothing is lost: the licence lookup ("one folder down for a stage with several checkouts") does not depend on whether the checkouts come from one repository or two. The second test's "two repositories" input is the one input that goes away.
- Docs and history: there is no grep hit by name. 0079 line 1122, "sub-folders [no fallback]": still caught by the new assertion. 7f18fbc "fix(Q-5): a BtbN stage may pin one repository at several commits" is a regression test whose input stays. 8f2ba04 (feature).
- Risk: medium. This is a rewrite of a regression test's file contents, and one input class (two repositories) is lost.
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED (Tier B kept) — the licence lookup (`select_licence_files`, "one folder down") does not depend on the repository; `check_stage_pins` with two different URLs is the one input class lost, and the removed test never asserted on pins (no `capsys` "checked" line), so no assertion goes. The 7f18fbc regression input (one repository, two commits, `.git`-suffix normalised between `SCRIPT_REPO` and `SCRIPT_REPO2`) stays exactly. Saved 1 test, 17 code lines (auditor 14).
Checked: applied (second commit also writes `LICENSE` = "MIT 11"; new assertion `_texts(out)[entry["archive"]] == {"sdk11/LICENSE": "MIT 11", "sdk13/LICENSE": "MIT"}`) → passes; mutation `return sorted(top or below)` → `sorted(top)` in scripts/sources-fetch.py makes the merged test fail (0079 line 1122 "sub-folders [no fallback]" still caught; this one-test run used `-n 0` outside the gate, 0.3 s), mutation reverted.

Orchestrator: Tier B, package Q-7.12.

### TTK-07 Release workflow: two pairs to parametrize, one damage case on the same path
- Kind: near-copy + param-trim
- Where: `testing/tests/test_release_workflow.py::test_sums_that_do_not_list_the_manifests_archives_stop_the_run` (282), `::test_sums_without_the_licence_texts_stop_the_run` (296), `::test_sources_whose_sums_do_not_match_the_archives_are_not_uploaded` (455), `::test_sources_whose_licence_texts_are_not_in_the_sums_are_not_uploaded` (467), `::test_a_published_but_incomplete_sources_release_stops_the_run[no licence texts]` (242-262 `DAMAGE`)
- Now:
  - The first pair rewrites the published `SHA256SUMS` asset without some lines and expects "<name>: not in its SHA256SUMS". Both go through the same line, `archives = {*archive_names(manifest), TEXTS}`, in `find_sources` (`scripts/release-workflow.py:254`).
  - The second pair changes one local file after the sums were written (`lame.tar.xz` or `licence-texts.json`) and expects `publish_sources` to refuse it with no `gh release` call. Both use `archives = [*archive_names(manifest), TEXTS]` (line 289).
  - The damage cases "an archive missing" (drop `lame.tar.xz`) and "no licence texts" (drop `licence-texts.json`) both reach `asset_problems` with the name listed in the sums, so both give "<name>: missing" (lines 110-126). No code treats `licence-texts.json` differently there.
- Change:
  - Parametrize the first pair as `test_sums_that_leave_out_a_file_stop_the_run`, with the cases (the kept-lines filter, the expected name): `(first two lines, "lame.tar.xz")` and `(every line but the texts, TEXTS)`.
  - Parametrize the second pair as `test_sources_whose_sums_do_not_match_a_file_are_not_uploaded`, with `name` in (`"lame.tar.xz"`, `TEXTS`).
  - Delete the `DAMAGE["no licence texts"]` case.
- Saved: 1 test, about 15 code lines, < 0.01 s
- Guarantee kept by: both inputs of each pair stay as cases. The TEXTS-specific guarantees (TEXTS must be in the sums, and must be uploaded with the archives) stay pinned by the TEXTS cases of the two parametrized tests. "A listed file missing from the release" stays pinned by `DAMAGE["an archive missing"]`.
- Why nothing is lost: the parametrized tests keep every input and every assertion. The deleted damage case goes through the same code with a different name, and its only difference (that `TEXTS` is in the sums at all) is the TEXTS case of the first parametrized test.
- Docs and history: there is no grep hit by name. 0079 lines 686-691 (RW3–RW8, RW34) and 1127 ("sums without the texts", "texts written after the sums not uploaded") describe these as mutation guards. All those inputs stay. 33f739f (feature, the FW round) and 8f2ba04 (feature, FL round).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — read side by side: both sums tests reach `archives - set(sums)` (line 254), both upload tests reach `wrong` (lines 289-293); `DAMAGE["no licence texts"]` reaches `asset_problems` "missing" exactly like "an archive missing" (TEXTS is in `wanted` only because the sums list it). A mutation dropping TEXTS from `wanted` is caught by `test_a_complete_sources_release_is_reused_with_its_sums` ("not a file of this release"). RW3–RW8/RW34 and 0079 line 1127 inputs all stay. Detail: the parametrized sums test's `match` needs `re.escape(name)` (both names have a `.`). Parametrizing the two pairs keeps 4 cases, so only the DAMAGE case counts: 1 test, ~15 lines by estimate (not applied; low risk).

Orchestrator: Tier A, package Q-7.6.

### TTK-08 The "draft deleted, not reused" test and the interrupted-upload test
- Kind: near-copy
- Where: `testing/tests/test_release_workflow.py::test_a_draft_left_by_an_interrupted_run_is_deleted_not_reused` (204), `::test_an_interrupted_upload_is_not_published_and_the_next_run_starts_over` (411)
- Now: the second test makes, through a real interrupted `publish_sources`, the same draft that the first test builds by hand (manifest.json and SHA256SUMS). It then asserts `find_sources(...) is False`. It does not assert `github.releases == []` or that no SHA256SUMS was written, which are the first test's assertions.
- Change: proposed only. Add `assert github.releases == []` and `assert not (tmp_path / "SHA256SUMS").exists()` after `find_sources` in the second test, then delete the first.
- Saved: 1 test, 12 code lines, < 0.01 s
- Guarantee kept by: the extended second test.
- Why nothing is lost: the draft content is the same, and both assertions move.
- Docs and history: 0079 line 686, "drafts deleted, not reused (RW1)". The record names this test (by description and mutation id) as the M1 guard. 33f739f.
- Risk: medium, because it is a named guard.
- Proposed tier: C (the rules say keep it)
- Confidence: high (that it is redundant)

Verdict: CONFIRMED (stays, Tier C) — 0079 line 686 "drafts deleted, not reused (RW1)" and line 706 "found/not found (RW1, RW28)". The interrupted test reaches the same draft only through the fake's upload order; RW1's hand-made draft does not depend on it. Keep. Do not count it.

Orchestrator: Tier C, not planned: kept (see the verdict).

### TTK-09 `test_fetch_tools.py`: one manifest helper for the two `main` tests, one parametrized `verify_file` reject test
- Kind: shared-setup + near-copy
- Where: `testing/tests/test_fetch_tools.py::test_main_prints_only_the_bin_dir` (399, 38 code lines), `::test_main_install_dir_prints_its_bin_dir` (539, 39 code lines), `::test_verify_file_rejects_wrong_hash` (254), `::test_verify_file_rejects_wrong_size` (261)
- Now:
  - The two `main` tests have the same 19-line TOML manifest literal, its `write_text`, `archive`/`pbuild`, and the same two monkeypatches (`download`, `detect_platform`). They differ only in `--dest` or `--install-dir`, the expected bin dir and the stderr text.
  - The two reject tests differ only in the passed hash or size and in the `match`.
- Change:
  - Add a module helper, `_cli_manifest(tmp_path, monkeypatch) -> Path`, that writes the manifest and sets both monkeypatches. Each `main` test keeps only its call and its assertions.
  - Parametrize the two reject tests as `test_verify_file_rejects(sha, size, match)` over `(other hash, 7, "SHA-256")` and `(right hash, 8, "size")`.
- Saved: 1 test, about 38 code lines, < 0.01 s
- Guarantee kept by: both `main` tests stay, with their inputs and assertions. Both reject cases stay as parameters.
- Why nothing is lost: only setup moves. The parametrization keeps both inputs.
- Docs and history: there is no grep hit in `docs/`. 80ae8a0 (Q-1.2, feature), 5c52d85 (C-1, feature). These are tests of the script copy, which 0038 keeps on purpose (TP-01 Tier C), and no test is removed in favour of a core test.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: ADJUSTED — the helper is sound (only setup moves, both `main` tests keep their calls and assertions), but the numbers are wrong: parametrizing the two `verify_file` reject tests keeps 2 collected cases, so **0 tests** are saved, not 1; and the measured saving is **25 code lines**, not 38 (the helper itself carries the 19-line manifest literal plus ~8 setup lines; the parametrize decorator costs what the second reject test saved). Tier A stays.
Checked: applied (`_cli_manifest(tmp_path, monkeypatch) -> Path` + `test_verify_file_rejects(data, size, match)`); test_fetch_tools.py 64 → 64 collected; 506 → 481 code lines; all pass (run above), ruff/format/mypy green.

Orchestrator: Tier A, package Q-7.6.

### TTK-10 Fake ffmpeg: `test_hang_times_out` is inside `test_asyncio_timeout_and_tree_kill`; one inline progress parser repeats `parse_blocks`
- Kind: near-copy
- Where: `testing/tests/test_fake_ffmpeg.py::test_hang_times_out` (227), `::test_progress_blocks_then_output` (337, lines 364-370)
- Now:
  - `test_hang_times_out` runs a `hang()` rule, waits 0.5 s on `Popen.wait` and expects `TimeoutExpired`, then kills the tree.
  - `test_asyncio_timeout_and_tree_kill` (687) runs `spawn_grandchild()` and then `hang()`, expects `TimeoutError` from `asyncio.wait_for(proc.wait(), timeout=0.5)`, and then checks the tree kill. It has no skip mark, so it runs on Linux and Windows.
  - `test_progress_blocks_then_output` parses the progress blocks with a 7-line loop that is the body of `parse_blocks` (386), except that `parse_blocks` also asserts that the trailing block is empty.
- Change: delete `test_hang_times_out`. In `test_progress_blocks_then_output`, replace lines 364-370 with `blocks = parse_blocks(r.stdout.decode())`.
- Saved: 1 test, about 15 code lines (9 + 6), 0.51 s
- Guarantee kept by: `test_asyncio_timeout_and_tree_kill` (687). The hang action keeps the fake alive for more than 0.5 s (the same bound, the same kind of assertion), with a superset of the actions. `test_ignore_sigterm_needs_sigkill` (639) and `test_kill_leftovers_kills_every_logged_process` (609) also rely on `hang()`.
- Why nothing is lost: the hang action is the same code. The asyncio test has the same 0.5 s timeout assertion and adds the grandchild. `parse_blocks` is stricter than the inline loop.
- Docs and history: there is no grep hit in `docs/`. All three came with 6aa66e0 (Q-2.1, the initial fake). None is a fix.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `test_asyncio_timeout_and_tree_kill` has no skip mark (runs on Windows CI too), drives the same `hang()` action with the same 0.5 s bound and adds the grandchild; the sync `Popen.wait(timeout=…)` on a hanging fake is still exercised by `test_ignore_sigterm_needs_sigkill` (POSIX) and `test_kill_leftovers_kills_every_logged_process` (all platforms, though without a timeout assertion). `parse_blocks` is defined at module level, so calling it from the earlier test is fine, and it is stricter. No doc names either test; 6aa66e0 (Q-2.1, feature). 1 test, 15 code lines (9 + 6), 0.512 s (junit).

Orchestrator: Tier A, package Q-7.6.

### TTK-11 Small parameter trims that take the same path as another case or test
- Kind: param-trim
- Where:
  - (a) `testing/tests/test_bundle_tools.py::test_files_the_script_did_not_make_are_refused_and_kept[other/x]` (266-276)
  - (b) `testing/tests/test_appimage_libs.py::test_each_appdir_file_maps_to_the_package_it_was_copied_from[usr/lib/libgtk-3.so.0-libgtk-3-0]` and `[usr/lib/libblkid.so.1-libblkid1]` (149-162)
  - (c) `testing/tests/test_updater_manifest.py::test_each_updatable_install_gets_its_own_target[Reframe_1.0.0_x64-setup.exe-windows-x86_64-nsis]` (98-107)
- Now:
  - (a) In `_clear_destination`, `other/x` and `mkvtoolnix/mkvpropedit.exe` both take the same path: a folder, not `.bundle-*`, and `_made_here` is False (the name is not in `FOLDER_TOOLS`, and there is no marker), so it is "unknown". `scripts/bundle-tools.py:207-235`.
  - (b) `test_the_appdir_gives_the_packages_of_its_distro_files_only` (166) has an AppDir whose only distro files are exactly `usr/lib/libgtk-3.so.0` and `usr/lib/libblkid.so.1`. `appdir_packages` calls `owner()` for each and requires exactly one owner per file (otherwise it raises). The test asserts `== ["libblkid1", "libgtk-3-0"]`.
  - (c) `test_the_manifest_has_the_shape_the_updater_reads` (79) builds a manifest from `Reframe_1.1.0-rc.1_x64-setup.exe` and asserts the exact `"windows-x86_64-nsis"` key, through `platform_of`.
- Change: delete case (a) `other/x`. Keep `mkvtoolnix/mkvpropedit.exe`, which 0079 names as the guard. Delete the 2 cases of (b) and the nsis case of (c).
- Saved: 4 tests, 4 code lines, about 0.01 s
- Guarantee kept by: (a) `[mkvtoolnix/mkvpropedit.exe]`, the same path and assertion. (b) `test_the_appdir_gives_the_packages_of_its_distro_files_only` (166). The other three `owner` cases (immodules sub folder, the basename fallback `usr/lib/im-xim.so`, the doc-folder link) stay. (c) `test_the_manifest_has_the_shape_the_updater_reads` (79).
- Why nothing is lost: each deleted case goes through the same code as a kept test, with the same or a stricter assertion.
- Docs and history: there is no grep hit by name. (a) `other/x` is from 679cc21 (D-7, feature). The kept mkvtoolnix case is from dd3f468 "fix(Q-5): no mkvpropedit in the Windows installers", and 0079 line 997 names it ("an unmarked one refused [any folder accepted]"). (b) a2c03e3 and (c) ab664cf are features.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — (a) `other/x` and `mkvtoolnix/mkvpropedit.exe` both fail `_made_here` (`FOLDER_TOOLS` is `{"ffmpeg": …}` only, no marker) and go to `unknown`; the kept case is the 0079 line 997 guard. (b) both cases go through `owner()`'s "ending" step and `appdir_packages` asserts the exact `["libblkid1", "libgtk-3-0"]` with one owner per file; both tests are `@dpkg_only`, so no skip asymmetry. (c) `NSIS = "Reframe_1.1.0-rc.1_x64-setup.exe"` hits the same `_x64-setup.exe` ending; no skip mark on either. 4 tests; about 3 code lines (removing `"other/x"` leaves the list on one line).

Orchestrator: Tier A, package Q-7.6.

### TTK-12 Delete the C-0 "package is importable" placeholder
- Kind: other
- Where: `testing/tests/test_testing_package.py::test_testing_package_is_importable` (5); the whole file
- Now: the test asserts `reframe_testing.__doc__` is truthy.
- Change: delete the file.
- Saved: 1 test, 4 code lines, 0.00 s
- Guarantee kept by: every other file in `testing/tests/` imports `reframe_testing` (for example `test_processes.py:6`, `test_fake_ffmpeg.py:21`), and every pytest session loads `-p reframe_testing.pytest_plugin`. If the package could not be imported, the whole run would fail.
- Why nothing is lost: the package docstring has no reader.
- Docs and history: there is no grep hit in `docs/`. It came from e5fb4e4 "C-0: shared testing package…", whose Done-when is "pytest and mypy pass", not this test.
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — 4 code lines, the file is not listed anywhere (pyproject `testpaths` names the folder only; no CI or doc reference); every other file in the folder imports `reframe_testing`, and the plugin `-p reframe_testing.pytest_plugin` loads it for every session. 1 test, 4 lines.

Orchestrator: Tier A, package Q-7.6.

### TTK-13 One `load_script` helper in `reframe_testing` for the by-path script loaders
- Kind: shared-setup
- Where: `_load_script()` (8 code lines each, the same body, plus `import importlib.util`, `from types import ModuleType` and often a `SCRIPT` constant used only there) in `testing/tests/test_appimage_libs.py:21`, `test_bundle_tools.py:28`, `test_fetch_tools.py:31`, `test_release_notes.py:23`, `test_release_workflow.py:32`, `test_sources_fetch.py:27`, `test_sources_manifest.py:24`, `test_stamp_version.py:25`, `test_third_party_notices.py:24`, `test_updater_manifest.py:39`; and `packages/reframe/tests/tools/test_fetch.py:156`.
- Now: each file loads `scripts/<name>.py` by path (the names have hyphens) under a module name of its own, and registers it in `sys.modules` for dataclasses.
- Change: add `testing/reframe_testing/scripts.py` with `load_script(file_name: str, module_name: str | None = None) -> ModuleType`. It resolves `REPO/scripts/<file_name>` and does the same five steps. The default module name comes from the file name; `test_fetch.py` keeps its own name (`fetch_tools_script`), so the two copies of `fetch-tools.py` do not replace each other in one xdist worker. Each file then has `xx = load_script("release-workflow.py")`. Optional second step: move the archive builders of `packages/reframe/tests/tools/fetch_server.py` (`sha256`, `tar_xz`, `tar_file`, `tar_link`) to `reframe_testing/archives.py` and drop the identical `_sha256`, `_tar_xz`, `_file` and `_symlink` in `test_fetch_tools.py` (about 20 more lines).
- Saved: 0 tests, about 90 code lines (11 × about 9.5, less a helper of about 12). The optional step saves about 20 more. 0 s.
- Guarantee kept by: unchanged tests. Only the loader moves.
- Why nothing is lost: the loader does the same thing. The tests and their assertions do not change.
- Docs and history: decision 0004 asks for shared test infrastructure in `reframe_testing`. X-04 (Q-6.1) covered the same kind of loader only in `tests/batch` and `tests/validation`. It did not cover these script loaders, so this is not a repeat. Its note about rule "5, 6" (no shared module for one consumer) does not apply: this helper has 11 consumers.
- Risk: low to medium. The module names must stay distinct where two test files load one script, and mypy must accept `ModuleType` attribute access as today.
- Proposed tier: B (a cross-file refactor; no guarantee is touched)
- Confidence: high

Verdict: CONFIRMED (Tier B) — all 11 loaders have the same five steps (spec by path, two asserts, `module_from_spec`, `sys.modules[spec.name] = module` **before** `exec_module`, return); only comments differ. Module names are the file stem with `-` → `_` in all 10 `testing/tests` files; `packages/reframe/tests/tools/test_fetch.py` uses `fetch_tools_script` and calls the loader inside two tests (not at import), which the helper keeps by passing the name. No workflow runs any of these files on its own: `.github/workflows/ci.yml` runs only `uv run pytest -m …` on the whole `testpaths` (lines 107, 418, 462); the release workflow runs the scripts, not their tests; no script imports another script. `reframe_testing` is on the path only through pytest's `pythonpath = ["testing"]` (not installed), so `Path(__file__).resolve().parents[2] / "scripts"` is the repository, as `reframe_testing/media.py:33` already does on the Windows CI runner; `--import-mode=importlib` does not apply to it (a normal package import), and under xdist each worker loads it once. Keep `SCRIPT` in `test_release_notes.py` and `test_sources_manifest.py` (used elsewhere there). Saving: ~10 code lines per file (8 loader lines + `importlib.util` + `ModuleType` + `SCRIPT`, minus one import), ~9 where `SCRIPT` stays: 9 × 10 + 2 × 9 − 16 (helper) ≈ 92, as claimed (~90). The optional second step: `fetch_server.py`'s `sha256`/`tar_xz`/`tar_file`/`tar_link` are byte-identical to `test_fetch_tools.py`'s `_sha256`/`_tar_xz`/`_file`/`_symlink` (read, not applied).
Checked: wrote `testing/reframe_testing/scripts.py` (`load_script(file_name, module_name=None)`, 16 code lines) and applied it to `testing/tests/test_release_workflow.py`, `testing/tests/test_fetch_tools.py` and `packages/reframe/tests/tools/test_fetch.py` (`load_script("fetch-tools.py", "fetch_tools_script")`): −10, −11, −10 code lines; ruff, ruff format, `mypy` and `mypy --platform win32` green (599 files); `runtests.sh` on the 5 edited files (-n 4) → 334 passed, 1 skipped, 7.7 s; `runtests.sh -n 0 test_fetch_tools.py tools/test_fetch.py -k "script or main or verify or install"` (both fetch-tools copies in one process) → 35 passed; `runtests.sh -n 0 test_release_workflow.py` alone → 67 passed. Windows itself not run (no VM in this check); the path code is the same as `media.py`'s, which the Windows CI job uses.

Orchestrator: Tier B, package Q-7.12.

## Looked at and kept
- `test_media_fixtures.py` (36 tests; coverage group "29 tests, 71 lines"): each test probes another generated fixture or a real FFmpeg behaviour. The same line set only reflects that ffprobe runs in a subprocess.
- `test_media_fixtures.py::test_matroska_disposition_round_trip` (12 cases, 1 line set): an oracle for each disposition (the "Matroska muxer: dispositions" table in `testdata/README.md`). Every case has another input and another expected result.
- `test_media_fixtures.py::test_truehd_encoder_has_no_7_1`, `::test_single_streams_get_no_default_flag`, `::test_forced_subs_only_does_not_drop_pgs_display_sets`, `::test_interlaced`, `::test_letterbox_changes_aspect`: verified tool behaviour, recorded in `testdata/README.md`.
- `test_media_fixtures.py::test_vfr_mp4` / `::test_vfr_mkv`: near-copies, but their assertions differ (`avg_frame_rate > 0` against `"0/0"`). A merge saves about 3 lines.
- `test_media_generator.py::test_anime_seasons`, `::test_the_bitmap_and_lossless_fixtures_are_written_in_python` against `test_media_fixtures.py::test_anime_seasons`, `::test_dts_hd_ma*`, `::test_pgs`: recipe-level unit tests (no FFmpeg; they point at the recipe step) against probes of the output. Different code and different failure points.
- `test_media_generator.py::test_cli` and `::test_find_ffmpeg_honours_the_environment` (same 117 lines): different assertions (CLI exit codes and messages against environment discovery).
- `test_media_generator.py::test_season_names_and_variants`: the exact literal names. `test_incremental_generation_with_the_fake` checks only a glob and the count.
- `test_media_generator.py::test_replace_retries_on_permission_error`, `::test_manifest_read_retries_on_permission_error`, `::test_manifest_reads_hold_the_lock`: Windows paths tested with mocks.
- `test_fake_ffmpeg.py::test_exit_code_for_os_fits_a_c_int` and `::test_windows_crash_exit_code_is_computed_without_overflow`: the second runs the Windows branch of `_crash` on Linux with a mock (a Windows-path test).
- `test_fake_ffmpeg.py::test_tree_kill_leaves_no_process` and `::test_asyncio_timeout_and_tree_kill`: the first also asserts the grandchild's ppid and the launcher's pid relation (cmd.exe on Windows). The second is the asyncio path.
- `test_fake_ffmpeg.py::test_encoders_and_banner` and `::test_launcher_works_with_asyncio_create_subprocess_exec`: the same output check, but launched through subprocess against asyncio.
- `test_fake_ffmpeg.py` group "49 tests, 5 lines": all subprocess work. Rejected as a hint.
- `test_capabilities_helpers.py::test_the_test_encode_captures_are_listed_with_their_files` against `test_fake_ffmpeg.py::test_every_capture_has_its_files`: the file-existence part overlaps, but the first asserts the `machine`/`stderr`/`env` fields of the detect captures, which the second does not. `test_stub_tools_gate` and `test_tool_set` (same 1 line): different behaviour.
- `test_pytest_plugin.py` (two coverage pairs): different environments (missing tools, required tools, broken tools, working tools) and outcomes.
- `test_folders_guard.py`, `test_processes.py`, `test_windows_packaging.py`: one test each, no overlap.
- `test_fixture_writers.py::test_rle_round_trip` (6 cases): short run, the 64+ boundary, a run over 255 (a second length byte), a colour run. These are boundary classes. `reframe_testing` is not in the coverage map, so this was checked by reading `pgs.rle_line`'s format.
- `test_fetch_tools.py::test_manifest_validation_rejects` (17), `::test_member_path_rejects_unsafe_names` (9), `::test_tar_with_escaping_symlink_is_rejected` (3): every case is another malformed input class (bool as a size, missing against malformed sha, `\`, `:`, absolute, `C:`).
- `test_fetch_tools.py` against `packages/reframe/tests/tools/test_fetch.py`: different code (the script against `reframe.tools.fetch`); decision 0038, TP-01 Tier C. `test_install_bundled_is_what_discovery_finds` (script install, then core discovery) is not the same as the core's `test_the_script_and_the_core_recognise_each_others_install` (the install marker), so both stay.
- `test_fetch_tools.py::test_install_bundled_replaces_an_empty_folder`: an empty existing folder is another input than the missing folder of `test_install_bundled_lays_out_bin_and_lib`.
- `test_sources_fetch.py` group "10 tests, 6 lines": scripts are not measured. Every test has another entry kind or licence layout.
- `test_sources_fetch.py::test_a_tarball_must_have_its_pinned_checksum` / `::test_a_damaged_tarball_is_fetched_again` / `::test_a_latin_1_licence_and_a_link_to_a_licence_are_read` (same 24 lines): different behaviour.
- `test_sources_manifest.py`: five tests build the same default manifest (`_build(tmp_path)`) and assert different entries. A merge would lose test focus and save only time (see Speed notes).
- `test_third_party_notices.py::test_a_source_with_neither_a_licence_file_nor_a_committed_text_is_an_error` against `::test_a_bundled_archive_without_licence_texts_is_an_error`: both reach `texts.get(archive, ())` and are empty. The first has the real `[]` that `sources-fetch.py` writes for an archive whose licence is committed; the second has a missing key. 0079 line 1133 names both.
- `test_third_party_notices.py::test_a_package_without_a_licence_text_gets_the_committed_one` against `::test_the_frontend_packages_without_a_licence_file_get_the_committed_text`: `with_texts` on its own (3 inputs) against the `javascript_entries` path.
- `test_third_party_notices.py` parametrized format errors (sources manifest 5, sums 3, texts 4): each is another malformed shape.
- `test_release_workflow.py::test_a_tag_that_is_not_a_final_version_the_msi_can_take_is_refused` (7), `::test_each_secret_a_release_needs_is_named_before_anything_is_built` (7), `::test_only_the_highest_version_is_the_latest` (6): each case is another boundary or branch (the per-field MSI limits, Unicode digits, numeric against string order, the certificate combinations). 0079 m6–m8 names them.
- `test_release_workflow.py::test_a_draft_left_by_an_interrupted_run_is_deleted_not_reused`: see TTK-08 (named guard RW1).
- `test_stamp_version.py::test_set_refuses_a_version_it_cannot_spell_in_order_and_writes_nothing` (12): Unicode digits in two positions, a newline, empty, `+local`, leading zeros, `v` prefix. These are distinct classes. `::test_cargo_takes_the_semver_spelling…` and `::test_the_tauri_cli_takes…`: real-tool oracles.
- `test_linux_packaging.py::test_the_sources_variables_are_set_all_four_or_none` (4): each variable left out once is the case that catches it missing from the shell check (0079 "the four variables [three]").
- `test_bundle_tools.py` subset pairs (coverage): only the `reframe.tools.fetch` part is measured. The script's layout logic differs per test.
- `test_appimage_libs.py`, `test_docker_image.py`, `test_updater_manifest.py` (except TTK-11): every test has another input or another script step. 0079 names most of them as mutation guards (AL-*, RT1–RT4, DK2).

## Speed notes
- `test_fake_ffmpeg.py::test_hang_times_out`: a 0.5 s wait, removed by TTK-10.
- `test_fake_ffmpeg.py::test_hang_and_grandchild_end_after_the_max_lifetime`: sets `MAX_LIFETIME_ENV` to `"1"` and asserts ≥ 1.0 s. `max_lifetime()` accepts fractions (`"2.5"` is tested), so `"0.5"` would save about 0.5 s. This is risky on Windows, where Python's start-up may take most of 0.5 s before the grandchild is logged.
- `test_sources_manifest.py`: 9 tests each run the fake BtbN `generate.sh` through `_build` (0.05–0.08 s each). A module-scoped default build would save about 0.3 s. Not worth it.
- The area's time is `test_media_fixtures.py` (7.1 s, the session's `media.generate()` and real ffprobe/ffmpeg), `test_fake_ffmpeg.py` (5.6 s, real processes) and the GnuPG test in `test_release_workflow.py` (3.6 s, real key generation, already module-scoped). None of these waits longer than it needs.

## Verifier notes
- Corrected numbers per finding (tests, code lines): TTK-01 + TTK-04 (7, 26 measured), TTK-03 (6, 0), TTK-05 (1, 6), TTK-07 (1, ~15), TTK-09 (0, 25 measured), TTK-10 (1, 15), TTK-11 (4, ~3), TTK-12 (1, 4) → Tier A 21 tests, ~95 lines. Tier B: TTK-06 (1, 17 measured), TTK-13 (0, ~92) → A+B 22 tests, ~205 lines. Test time saved stays ~0.7 s (0.51 s of it TTK-10).
- TTK-09's helper keeps the "Pretend the host is another platform…" comment once, in the helper; both `main` tests depend on that monkeypatch, so it must stay in the helper and not be dropped as "setup".
- TTK-13: three more loaders with the same body load test helpers, not scripts (`tests/models/test_roundtrip.py` strategies.py, `tests/languages/test_equivalence.py` oracle.py, `tests/jobs/test_cli_batch.py` anime.py); D-26 kept `_load_anime` because a shared module for one consumer was not worth it. Once `reframe_testing` has a by-path loader, a `load_path(path, name)` beside `load_script` would cover those three too; not checked here, and it touches a recorded D-26 choice.
- TTK-13's module names must stay distinct only where one process loads one script twice (today only `fetch-tools.py`: `fetch_tools` and `fetch_tools_script`); a reused name would not break the tests (each holds its own module object), but keeping distinct names avoids a replaced `sys.modules` entry under `-n 0`.
- Set-up: the `testdata/media` symlink the brief asks for shows as untracked (`?? testdata/media`) in this worktree's `git status`: `.gitignore` matches `testdata/media/` as a folder, not a symlink. Every tracked file is unchanged.
