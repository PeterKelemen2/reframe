# Area cli-jobs-remote: `packages/reframe/tests/jobs/`, `packages/reframe/tests/remote/`, `packages/reframe/tests/test_cli.py` (+ `__snapshots__/test_cli.ambr`), helper `testing/reframe_testing/cli.py`

Baseline: 27 files, 476 tests, 7,605 test code lines, 527 s of test time.

All paths are relative to `packages/reframe/tests/` unless they start with `testing/` or `docs/`.
Line numbers are at commit 38cf3eb.

Earlier work read: `docs/simplify/areas/cli-remote.md` (Q-6; CLI-12 not reported again) and the
trim report `docs/test-trim-reports/Q.md` (the only trim report that names a test of this area;
`grep` of all ten reports for `test_cli`, `jobs/`, `remote/`). No finding below goes against a
keep in Q.md: its keeps (`test_list_marks_the_builtin_default`, `test_preset_rows_align_the_columns`,
`test_a_legacy_windows_console_encoding_does_not_crash`, `test_follow_rereads_the_queue_after_a_resync`,
`test_recorded_probes_draft_without_errors`, `test_detection_wait_default_is_read_at_creation`,
`jobs/test_encode_real.py`) are listed under "Looked at and kept"; TCL-07 moves only the setup of
the Windows-console test, its body and assertions stay.

## Summary

8 findings. Tier A: 3 tests and about 16 code lines removed (about 2.6 s). Tier A+B: 6 tests and
about 94 code lines removed (about 5.4 s). The area is lean for its size: almost all of its time
is in tests that the plan, decision 0061/0062 or the Q-6 audit name as guards (the real-process
checks 1–7 of C-17, the C-15 "season end to end" tests, the Ctrl+C / Ctrl+Z / kill -9 / lost
connection tests, the queue contract run against both queues). None of those is proposed for
removal. The best three:
- TCL-03: `test_a_sleep_countdown` is the shutdown end-to-end path again plus one text that a
  one-line unit assertion pins (delete, Tier A).
- TCL-01: `test_no_nvidia_driver` repeats the exact input and assertion of
  `test_a_status_that_changes_after_the_cache_is_printed_again` (delete, Tier A).
- TCL-07/TCL-08: one `cli_env`, one CLI subprocess helper and one real-tool folders fixture
  remove about 48 copied setup lines (Tier B).

Main questions of the brief, answered:
- CLI tests that only repeat core assertions with the same inputs: I found none that is a clean
  layer duplicate. Where the CLI and the core test the same topic (unavailable encoder, naming,
  batch resolution, preset import), the CLI test has another input (real detection through the
  fake ffmpeg, typer wiring) or pins output that no other test pins.
- `test_queue_contract.py` runs one contract against `QueueService` and `RemoteQueue` on
  purpose: kept whole.
- `test_shared_queue_real.py` vs `test_cli_client.py`: the 10 real-process tests are the plan's
  "Done when" for C-17 (`docs/plan/05-core.md` 721-722: "1–7 with real processes …
  (`tests/remote/test_shared_queue_real.py`)") and the post-review additions that
  `docs/status.md` line 42 lists; the in-process client tests are the 0061 "The CLI" fix tests,
  each named there with its "before" failure. Neither side can go.

## Findings

### TCL-01 `test_no_nvidia_driver` repeats the NVENC line check of the cache test
- Kind: near-copy
- Where: `jobs/test_cli_encoders.py::test_no_nvidia_driver` (51)
- Now: sets the scenario `detect_rule("detect_hevc_nvenc_no_driver")`, runs `reframe encoders`
  once (no cache) and asserts exit 0 and `NVENC_LINE` in the output lines.
- Change: delete
- Saved: 1 test, 5 code lines, about 1.2 s (one `reframe encoders` detection run; the file is
  13.5 s for 14 tests, `test_second_run_prints_the_cache_at_once` with two runs is 2.98 s)
- Guarantee kept by: `jobs/test_cli_encoders.py::test_a_status_that_changes_after_the_cache_is_printed_again`
  (59): the same `detect_rule("detect_hevc_nvenc_no_driver")` scenario and
  `assert NVENC_LINE in out[checking_again:]` (the same exact line, in the lines after the
  check); `capabilities/test_detect.py:104-120` pins the reason from the same recording
  (`row("hevc_nvenc") == (UNAVAILABLE, "NVIDIA driver not found")`);
  `jobs/test_cli_encoders.py::test_first_run_checks_then_lists_every_encoder` (23) pins that the
  first (uncached) run prints "unavailable: <reason>" lines (`libfdk_aac — unavailable: Not in
  this FFmpeg build`).
- Why nothing is lost: input: same recorded FFmpeg text through the same fake. Assertion: the
  same full line, exact match. The only path difference (first run vs re-check) is covered by
  the first-run test with another unavailable encoder. Coverage: only-A lines are
  `tools/runner.py` 458, 461-464 (a reader/exit race), nothing in `cli.py` or `capabilities/`.
- Docs and history: `grep -rn test_no_nvidia_driver docs/`: none. `git log -S`: 138e0bc
  "C-15: jobs service and the encoders, plan, encode and name commands" (the first commit of the
  file; no bug, review or decision).
- Risk: low
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the keeper `test_a_status_that_changes_after_the_cache_is_printed_again` runs the same `detect_hevc_nvenc_no_driver` scenario through the same detection and asserts the same exact `NVENC_LINE`. Only the deleted test asserts exit 0 with that scenario, but `test_first_run_checks_then_lists_every_encoder` asserts EXIT_OK on a run with an unavailable encoder (libfdk_aac). No document names it (grep docs/ testdata/ CLAUDE.md .github: none); added in 138e0bc (C-15), no bug or review. 1 test, 5 code lines (recounted), about 1.2 s. Tier A.
Checked: `covquery.py test_no_nvidia_driver test_a_status_that_changes_…` → only-A lines are `tools/runner.py` 458, 461-464 (reader/exit race), nothing in cli.py or capabilities/. Checked: applied TCL-01, 02, 04, 05, 06, 07, 08 together in the worktree (not TCL-03); `uv run pytest --collect-only -q -n 0 -p no:cacheprovider packages/reframe/tests/jobs packages/reframe/tests/remote packages/reframe/tests/test_cli.py` → 476 before, 471 after; ruff check, ruff format --check, `uv run mypy` and `uv run mypy --platform win32` clean; `runtests.sh packages/reframe/tests/jobs packages/reframe/tests/test_cli.py packages/reframe/tests/capabilities/test_recheck.py -q` → 263 passed, 17 snapshots passed, 0 skipped (real-FFmpeg tests ran), 101 s, 2 other pytest runs on the machine. Worktree reverted.

Orchestrator: Tier A, package Q-7.5. Add the deleted test's exit-0 assertion to the keeper (verifier).

### TCL-02 `test_second_run_prints_the_cache_at_once` and the status-change test start from the same cached first run
- Kind: near-copy
- Where: `jobs/test_cli_encoders.py::test_second_run_prints_the_cache_at_once` (39),
  `jobs/test_cli_encoders.py::test_a_status_that_changes_after_the_cache_is_printed_again` (59)
- Now: both run `reframe encoders` once to fill the cache. The first then runs it again with the
  same scenario and asserts the cached header, "Checking again…", `libx265 — available` among the
  cached lines and "(no changes)."; the second changes the scenario and asserts the changed line
  and "(1 changed since the cached result)."
- Change: merge into `jobs/test_cli_encoders.py::test_the_cache_is_printed_then_the_changes`
  (one test, three runs: fill the cache; run again unchanged with every assertion of
  `test_second_run_…`; set the no-driver scenario and run a third time with every assertion of
  `test_a_status_that_changes_…`).
- Saved: 1 test, about 2 code lines, about 1.3 s (one `reframe encoders` run less)
- Guarantee kept by: the merged test: the same three inputs (empty cache, unchanged re-run,
  changed re-run) and every assertion of both tests.
- Why nothing is lost: run 2 of the merged test is the second test's run 2 exactly; run 3 sees
  a cache written by run 2 instead of run 1, but both caches hold the same statuses (the default
  scenario, `hevc_nvenc` available), which run 3's `"hevc_nvenc — available" in
  out[:checking_again]` checks.
- Docs and history: `grep -rn` of both names in `docs/`: none. `git log -S`: both 138e0bc
  (C-15, first commit of the file).
- Risk: low (the test becomes a sequence; a failure in run 2 hides run 3)
- Proposed tier: B
- Confidence: high
Verdict: CONFIRMED — applied as one test `test_the_cache_is_printed_then_the_changes` (run 2 unchanged, then the no-driver scenario and run 3); every assertion of both tests kept; it passed (2.90 s under load, against 2.98 s for the old `test_second_run_…` alone). 1 test, 2 code lines (recounted), about 1.3 s. No document names either test. Tier B.
Checked: see TCL-01 (combined run, 476 → 471 tests, all passed).

Orchestrator: Tier B, package Q-7.10.

### TCL-03 `test_a_sleep_countdown` is the shutdown end-to-end test with another verb
- Kind: layer-duplicate
- Where: `jobs/test_cli_when_done.py::test_a_sleep_countdown` (228),
  `jobs/test_cli_when_done.py::test_countdown_text` (349)
- Now: `test_a_sleep_countdown` runs `reframe encode` of two files on the fake queue; the test's
  `Setup` watcher schedules `setup.action = "sleep"` (3 s; the `when_done(tmp_path, "sleep")`
  setting is not what picks the action, the watcher is) and asserts the two countdown lines
  "Going to sleep in 3 s — press Ctrl+C to cancel" and "Going to sleep now.".
- Change: delete `test_a_sleep_countdown`; add to `test_countdown_text` the one line
  `assert countdown_text(_event("executing", 0, "sleep")) == "Going to sleep now."`.
- Saved: 1 test, 9 code lines net (10 removed, 1 added), about 1 s
- Guarantee kept by: `jobs/test_cli_when_done.py::test_a_shutdown_countdown_is_shown_until_it_runs`
  (211): the same CLI path (encode, the countdown followed after the summary, the lines view, the
  "now" line, exit 0); `test_countdown_text` (349): `_event("tick", 7, "sleep")` → "Going to
  sleep in 7 s — press Ctrl+C to cancel" (the "in N s" form is the same for `started` and
  `tick`: `cli.py:2569-2576`), plus the added "executing" line for sleep;
  `test_countdown_view_lines_every_ten_seconds` (360): the first line and the end are printed and
  the 0 s tick is not (the 3 s case of the sleep test).
- Why nothing is lost: `countdown_text` maps the action through `_COUNTDOWN_VERB` with no other
  branch on the action; the CLI follow code does not look at the action. Coverage: test A's
  4831 lines are all in test B (only-B: `naming/parse.py` lines and the runner race).
- Docs and history: `grep -rn test_a_sleep_countdown docs/`: none. `git log -S`: d3f32ae
  "C-15: reframe tools status|fetch, reframe presets list|export|import" (first commit; no bug).
- Risk: low
- Proposed tier: A
- Confidence: high
Verdict: REJECTED — `test_a_sleep_countdown` is the only test of `"sleep" in WAITED_ACTIONS` (`cli.py:2562`). The report says the CLI follow code does not look at the action and that the `when_done(tmp_path, "sleep")` setting does not matter; both are wrong: `follow_countdown` returns at once when `when_done not in WAITED_ACTIONS` and when `event.action not in WAITED_ACTIONS` (`cli.py:2623`, `2630`). The shutdown test and `test_countdown_text` never pass the sleep setting or a sleep event through that check; no other test in tests/, reframe-server/tests does (grep `Going to sleep`, `"sleep"`). Line coverage cannot show this (a set member, the same lines run). The test stays; 0 tests, 0 lines saved. (Speed only: the test already uses a 3 s fake countdown with 0.01 s ticks.)
Checked: mutation `WAITED_ACTIONS = frozenset({"shutdown"})`, then `runtests.sh packages/reframe/tests/jobs/test_cli_when_done.py packages/reframe/tests/remote -q -m "not slow"` → 1 failed (only `test_a_sleep_countdown`: `assert [] == ['Going to sleep in 3 s …', …]`), 211 passed, 101 s, 2 other pytest runs. Mutation reverted.

Orchestrator: Tier C, not planned: rejected in verify (the only test of `"sleep" in WAITED_ACTIONS`).

### TCL-04 the dry-run error is checked in two tests, human and `--json`
- Kind: near-copy
- Where: `jobs/test_cli_plan_dry_run.py::test_custom_parameters_are_dry_run_and_errors_printed`
  (72), `jobs/test_cli_plan_dry_run.py::test_dry_run_errors_in_json` (86)
- Now: both set `dry_run.issues = [REFUSED]` and run `reframe plan movie --preset "Custom x265"`;
  the first checks the human output, the second the same command with `--json` (exit 1,
  `plan` null, the code in the draft's issues).
- Change: merge into `test_custom_parameters_are_dry_run_and_errors_printed`: after its
  assertions (so `dry_run.calls` is still checked after one call), run the `--json` command and
  keep its three assertions (exit 1, `data["plan"] is None`, the code in
  `data["draft"]["issues"]`). `test_plan_shows_the_dry_runs_warnings` (166) already has this
  human-then-JSON form.
- Saved: 1 test, about 2 code lines, about 0.4 s (one fixture setup: preset file, fake tools, one
  `Reframe` facade less; the `--json` run stays)
- Guarantee kept by: the merged test: the same fixture, the same `REFUSED` issue, both commands,
  every assertion.
- Why nothing is lost: same inputs, assertions moved unchanged.
- Docs and history: `grep -rn` of both names in `docs/`: none. `git log -S`: both d3f32ae (C-15).
- Risk: low
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — same fixtures (`movie`, `dry_run`), same `REFUSED` issue, both commands; the JSON run after the human run still gets the refused issue because `DryRun` returns `issues` on every call (it does not cache). Applied: the merged test passed. 1 test, 2 code lines (recounted), about 0.4 s. No document names either test. Tier A.
Checked: see TCL-01 (combined run).

Orchestrator: Tier A, package Q-7.5.

### TCL-05 the RA-4 check runs a copy of `test_encode_never_writes_another_file_of_the_command`
- Kind: near-copy
- Where: `jobs/test_cli_output_names.py::test_encode_does_not_say_will_be_replaced_next_to_never_overwritten`
  (362), `jobs/test_cli_output_names.py::test_encode_never_writes_another_file_of_the_command` (122)
- Now: both do `write_settings(tmp_path, collision="overwrite")`,
  `two_sources(cli_env, tmp_path, E01_OUT)` and `invoke("encode", str(folder))`. The first
  asserts `[batch.output_is_source · output.path]` in stdout and `[output.overwrite` not in
  stdout. The second asserts the exit code, both job lines, the same `output_is_source` line,
  the message, that the copy is not an output, and the summary. The coverage map lists them as
  one equal-set group (4894 lines each).
- Change: merge into `test_encode_never_writes_another_file_of_the_command` (add
  `assert "[output.overwrite" not in out`), delete the other. In the same commit, the two
  decision records that name the deleted test (0040 line 494, 0041 RA-4 row line 214) need the
  new test name, or a note.
- Saved: 1 test, 9 code lines net (10 removed, 1 added), about 1 s
- Guarantee kept by: `jobs/test_cli_output_names.py::test_encode_never_writes_another_file_of_the_command`
  with the added assertion: the exact same input and both assertions of the RA-4 test.
- Why nothing is lost: the inputs are identical line by line; the `output_is_source` assertion
  is already there; the one new assertion is the RA-4 one.
- Docs and history: `docs/decisions/0040-batch-engine-and-reframe-batch.md:494` and
  `docs/decisions/0041-core-complete-review.md:214` name it as the RA-4 test ("the reviewer's");
  `test_encode_never_writes_another_file_of_the_command` is named in 0040:322 and the 0041 R2-1
  row. `git log -S`: f754a87 (a rename "drop review and milestone IDs from test names"); the fix
  is ef2fdb6 (RA-4). Rule: a review-finding guard may go when another test pins the exact same
  input: it does.
- Risk: low for the guarantee; the cost is editing two decision records.
- Proposed tier: B
- Confidence: high
Verdict: CONFIRMED — the inputs are identical: same fixtures (`cli_env`, `queues`, `tmp_path`), `write_settings(tmp_path, collision="overwrite")`, `two_sources(cli_env, tmp_path, E01_OUT)`, `invoke("encode", str(folder))`; the reviewer's original at ef2fdb6 (`test_ra4_…` in `test_cli_final_review.py`) had the same three lines. A mutation of the RA-4 fix is caught by the merged keeper. On the records: both names are in records (the RA-4 test in 0040:494 and 0041:214; the keeper in 0040:322 and 0041:133, the R2-1 row), so keeping the RA-4 name instead does not avoid an edit: either way two records change by one test name. That is a reference update, not a change of the decision, so the README rule ("do not edit an accepted record to change its decision") does not forbid it, and the project has done it before: a139d30 "docs: records name the renamed and moved tests" edited 0040 (56 lines) and 0041 (116 lines) the same way. Keep `test_encode_never_writes_another_file_of_the_command` and change only the test name in 0040:494 and the 0041 RA-4 row (line 214), in the same commit. 1 test, 9 code lines net, about 1 s. Tier B (cost: the record edit).
Checked: mutation of `cli._with_claims` (keep `output.overwrite`, `cli.py:1789`) with the merge applied, `runtests.sh packages/reframe/tests/jobs/test_cli_output_names.py -q` → 1 failed (`test_encode_never_writes_another_file_of_the_command`, the added assertion at line 136), 12 passed. `grep -rn` of both names in docs/: the four lines above only. Mutation reverted.

Orchestrator: Tier B, package Q-7.10. Keep the keeper's name; change the RA-4 test name in 0040:494 and 0041:214 in the same commit (a reference update, as a139d30 did; the decisions do not change).

### TCL-06 `test_recorded_badges_and_bitrate_sources` asserts strings that the probe snapshots pin
- Kind: layer-duplicate
- Where: `test_cli.py::test_recorded_badges_and_bitrate_sources` (333)
- Now: runs `reframe probe` on the recordings `truehd-atmos`, `dts-hd-ma`, `pgs` and `dv-p8`
  (fake ffprobe) and asserts substrings: "TrueHD Atmos lossless", "AC-3", a "(stats tag)"
  bitrate, "(Commentary?)", `title contains "Commentary"`, "DTS-HD MA lossless", "PGS",
  `bitmap 1920×1080`, "Dolby Vision 8.1".
- Change: delete
- Saved: 1 test, 19 code lines, about 0.5 s
- Guarantee kept by: `test_cli.py::test_recorded_probe_snapshot[truehd-atmos|dts-hd-ma|pgs|dv-p8]`
  (320): the same recordings through the same fake, the whole human output compared with
  `__snapshots__/test_cli.ambr` (checked: every string above is in the snapshot; "TrueHD Atmos"
  / "lossless" and "DTS-HD MA" / "lossless" are wrapped over two lines at `COLUMNS=120`), and in
  the same test `assert_every_track` on the default-width output, which asserts each codec cell
  equals `display_codec + " lossless"` when the model says lossless, each bitrate cell with its
  source, and each role badge and evidence line.
- Why nothing is lost: same inputs; the snapshot is a stricter assertion (every line) and the
  `assert_every_track` call pins the "lossless" suffix at the unwrapped width.
- Docs and history: `grep -rn test_recorded_badges_and_bitrate_sources docs/`: none.
  `git log -S`: 6eacab2 "C-15: Reframe facade skeleton (tools, sources) and reframe probe"
  (first commit; no bug). Snapshot tests are on the never-drop list; this is not one, it is the
  weaker copy beside one.
- Risk: medium: a snapshot can be refreshed blindly with `--snapshot-update`; the explicit
  substrings say what matters. Role and bitrate-source rules have their own core tests
  (`probe/`), so a wrong refresh would still fail there.
- Proposed tier: B
- Confidence: medium
Verdict: ADJUSTED — the finding holds; the line count is 17, not 19. Every string the test asserts is in `__snapshots__/test_cli.ambr`: truehd-atmos "TrueHD Atmos" / "lossless" (wrapped), "AC-3", "385 kb/s" / "(stats tag)" in the bitrate column, "(Commentary?)", `#3  (Commentary?)  title contains "Commentary"`; dts-hd-ma "DTS-HD MA" / "lossless" (wrapped), "(Commentary?)" (the structure heuristic); pgs "PGS", "(stats tag)", "bitmap 1920×1080"; dv-p8 "HDR10 + Dolby Vision 8.1". The unwrapped "… lossless" cell at width 200 is pinned by `assert_every_track` (derived from the model, so it is the snapshot that pins the absolute text). Windows: `test_recorded_probe_snapshot` has no skip or platform branch, it runs in the Windows CI job (`-m "not needs_gpu and not benchmark"`) with the fake ffprobe, the same as the deleted test, so nothing is lost there. No document names the test; 6eacab2 (C-15), no bug. 1 test, 17 code lines, about 0.5 s. Tier B (blind `--snapshot-update` risk, as the auditor says).
Checked: read the four snapshot sections; deleted the test in the combined run (see TCL-01); 17 snapshots passed.

Orchestrator: Tier B, package Q-7.10.

### TCL-07 one `cli_env` and one CLI subprocess helper instead of two copies each
- Kind: shared-setup
- Where: `test_cli.py` fixture `fake_env` (179-192) and `run_subprocess` (558-581);
  `jobs/conftest.py` fixture `cli_env` (165-180); the inline environment and `subprocess.run`
  in `jobs/test_cli_encoders.py::test_a_legacy_windows_console_encoding_does_not_crash` (125-162).
- Now: `fake_env` is `cli_env` without the `REFRAME_IN_PROCESS=1` line (fake ffmpeg/ffprobe,
  private config/data/cache folders, `NO_COLOR`/`FORCE_COLOR` removed). `run_subprocess` and the
  encoders test both build a child environment from `fake.env()`, drop `ENV_VARS`, set the fake
  tools, private cache/config folders and `COLUMNS=120`, drop `PYTHONUTF8`, set
  `PYTHONIOENCODING`, and run `python -m reframe.cli` with a 60 s timeout.
- Change: move `cli_env` to `tests/conftest.py` (unchanged; `REFRAME_IN_PROCESS` does not change
  `probe`) and delete `fake_env` (rename its 35 uses to `cli_env`); move `run_subprocess` to
  `testing/reframe_testing/cli.py` as `run_cli(fake, tmp_path, *args, encoding)` (with
  `REFRAME_DATA_DIR` added, as the encoders test sets it) and call it from the encoders test.
  `tests/tools/test_fetch_cli.py` and `tests/capabilities/test_recheck.py` (other areas) build
  the same environment and could use `cli_env` too.
- Saved: 0 tests, about 35 code lines (`fake_env` 14; the encoders test's environment and
  `subprocess.run` about 22 replaced by one call; +1 for the data folder), 0 s
- Guarantee kept by: every test stays, with the same environment.
- Why nothing is lost: the two environments are identical except `REFRAME_IN_PROCESS`, which only
  `encode` and `batch` read, and `REFRAME_DATA_DIR`, which the shared helper sets for both (a
  private folder is the safer default; the folders guard asks for it).
- Docs and history: helpers, not tests; CLI-12 (Q-6) merged `invoke`/`WIDTH`, `user_preset`,
  `free_port`, `short_waits`, not these. The Windows-console test
  (`test_a_legacy_windows_console_encoding_does_not_crash`, named in
  `docs/decisions/` once, kept by trim report Q) keeps its body: only its setup moves.
- Risk: low
- Proposed tier: B
- Confidence: high
Verdict: ADJUSTED — works and keeps every test; it saves about 31 code lines, not 35: moving `run_subprocess` to `testing/reframe_testing/cli.py` as `run_cli` costs the new imports there (subprocess, sys, Path, ENV_VARS, FakeTools: helper +30 for a 24-line function), and the root `tests/conftest.py` needs three imports for `cli_env` (+17 for a 14-line fixture). Measured per file: test_cli.py −41 (fake_env 13, run_subprocess 24, 2 imports, 2 re-joined signatures), test_cli_encoders.py −22, jobs/conftest.py −15, reframe_testing/cli.py +30, tests/conftest.py +17 → −31. Windows: `run_cli` is the code that already ran on Windows CI (`sys.executable -m reframe.cli`, `fake.env()`); adding `REFRAME_DATA_DIR` to the probe subprocess tests only makes them more private; mypy --platform win32 is clean. Importing `reframe.cli` in the root conftest loads it for every test; the import-sensitive tests (`models/test_roundtrip.py::test_every_public_name_is_exported`, `languages/test_without_libraries.py`) still pass, and `capabilities/test_recheck.py`'s own `cli_env` (returns a Path) overrides the root one as before. Tier B.
Checked: applied (combined run, see TCL-01) → all passed; `runtests.sh packages/reframe/tests/models/test_roundtrip.py packages/reframe/tests/languages/test_without_libraries.py packages/reframe/tests/tools/test_fetch_cli.py -q -k "exported or without or fetch"` → 22 passed, 5 s; line counts with an AST/tokenize counter (no blanks, comments, docstrings) against HEAD.

Orchestrator: Tier B, package Q-7.10.

### TCL-08 one fixture for the private folders of the real-FFmpeg CLI tests
- Kind: shared-setup
- Where: the `dirs` fixture of `jobs/test_encode_real.py` (31-39) and the same lines inline in
  `jobs/test_cli_batch.py::test_a_season_encoded_end_to_end` (308-310),
  `jobs/test_cli_file_identity.py::test_a_user_file_reached_through_a_link_is_never_overwritten_by_the_real_queue`
  (255-257), `jobs/test_cli_output_names.py::test_batch_never_overwrites_a_file_named_as_an_output_with_the_real_queue`
  (320-322), `jobs/test_cli_json_paths.py::test_probe_json_with_the_real_ffprobe` (67-68),
  `jobs/test_cli_plan.py::test_real_ffmpeg_plan_of_a_fixture` (167-168).
- Now: each real-tool test sets `REFRAME_{CONFIG,DATA,CACHE}_DIR` to `tmp_path` folders with a
  two-line loop, and the queueing ones also `REFRAME_IN_PROCESS=1`.
- Change: move `dirs` to `jobs/conftest.py` (for example as `real_folders`) and use it in the five
  tests in place of the loop (their `monkeypatch` parameter goes where nothing else uses it).
  The same loop is in about ten files of other areas (`queue/`, `capabilities/`, `metadata/`,
  `tools/`, `test_service*.py`): a `private_folders` helper in `reframe_testing` would serve them
  all; that part is cross-area.
- Saved: 0 tests, about 13 code lines in this area, 0 s
- Guarantee kept by: every test stays with the same folders.
- Why nothing is lost: same environment; `REFRAME_IN_PROCESS` is read only by `encode`/`batch`,
  so setting it for the probe and plan tests changes nothing.
- Docs and history: setup only; none.
- Risk: low
- Proposed tier: B
- Confidence: high
Verdict: CONFIRMED — 13 code lines if the moved fixture keeps the name `dirs`; renaming it `real_folders` re-wraps `test_encode_a_fixture`'s signature in test_encode_real.py (measured −11 with the rename). The `IN_PROCESS_ENV` import goes from test_cli_batch.py and test_encode_real.py. Setting the folders before `fixture_media(...)` in the plan test changes nothing (fixture_media reads no REFRAME_* folder variable; it finds the tools before any test change). Windows: these are `needs_ffmpeg` tests that already run on Windows CI with the real tools; the fixture only sets environment variables. 0 tests, 0 s. Tier B.
Checked: applied (combined run, see TCL-01) → the five real-tool tests and test_encode_real.py passed.

Orchestrator: Tier B, package Q-7.10.

## Looked at and kept

Coverage groups (equal sets):
- `remote/test_shared_queue_real.py` (all 10, 71 lines): real processes, so the in-process set is
  only the test helpers. They are C-17's "Done when" checks 1–7 (`docs/plan/05-core.md:721-722`)
  and the post-review additions listed in `docs/status.md:42` and 0061 (removed waiting job,
  Ctrl+C beside the other client's job, Ctrl+Z/SIGCONT); `test_ctrl_z_pauses_the_job_and_fg_resumes_it`,
  `test_a_waiting_job_that_another_client_removes_ends_the_follow` and
  `test_a_stop_by_another_front_end_is_reported_and_the_jobs_wait_for_a_start` are named in 0061
  / 0064. All kept.
- `remote/test_cli_client.py::test_ctrl_z_pauses_the_commands_jobs_and_fg_resumes_them` /
  `::test_ctrl_z_pauses_a_job_whose_start_the_command_has_not_seen`: both named in 0061 with
  their "before" failures; they already share `_stop_and_continue`; the second adds a copy that
  is behind the owner.
- `test_cli.py::test_probe_fixture_lists_every_track[multitrack]` / `[season-e01]`: season E01 is
  a stream copy of the multitrack layout, so the derived checks take the same path. But
  `season-e01` is the M1 demo file ("`reframe probe "Show S01E01.mkv"` prints every track … `--json`
  prints the `MediaSource` model", `docs/plan/08-roadmap.md:55`), and the demo test
  `test_probe_of_a_season_episode_shows_every_track` (formerly `test_demo_season_episode`) does not
  check `--json` or every column. Moving the case into the demo test saves no lines. Kept.
- `remote/test_owner_search.py::test_a_started_owner_that_fails_points_to_its_messages[new|full]`:
  the `full` case is the log-truncation input (0061 names the test). Kept.
- `remote/test_cli_client.py::test_detach_needs_the_server` (3 cases): the lead's mutation L4 was
  caught by it (0061:171). `remote/test_cli_queue.py::test_the_queue_commands_through_the_command_line`
  overlaps two cases through typer (exit code for `encode`, message for `batch`) but asserts less
  per case. Kept.
- `remote/test_cli_queue.py::test_jobs_or_all_but_not_both[refs0-False|refs1-True]`: neither vs
  both, two input classes of one message. Kept.
- `test_cli.py::test_only_a_windows_stream_without_a_chosen_encoding_becomes_utf8`: Windows mocks
  (never drop).
- `jobs/test_cli_encoders.py::test_a_legacy_windows_console_encoding_does_not_crash` /
  `test_cli.py::test_a_pipe_gets_utf8_when_no_encoding_is_set`: subprocess Windows-console and
  pipe guards; trim report Q kept the first explicitly.
- `jobs/test_cli_when_done.py::test_no_wait_for_other_settings[nothing|quit]`: `quit` schedules a
  countdown that closing Reframe must cancel, `nothing` schedules none; trim report Q already cut
  `notify`. Kept.
- `jobs/test_service.py::test_draft_from_a_media_source_does_not_probe` /
  `::test_draft_with_the_default_preset`: another input (`MediaSource` vs `Path`) and another
  assertion (no probe).
- `jobs/test_cli_encoders.py::test_encoder_text[status3|status4]`: with and without a reason.

Subset pairs and layer overlaps:
- `remote/test_queue_contract.py` (40): one contract, two implementations, on purpose (0061;
  L3 was caught by `test_start_with_job_ids_runs_only_those[remote]`). `test_cancel_a_waiting_job`
  ⊂ `test_retry` by lines, but only the first asserts that `wait` returns the cancelled job.
- `remote/test_remote_queue.py`: 22 of its tests are named in 0061 with their "before" failure
  (R1–R9, B1, O-items); the rest (`test_its_jobs_end_with_its_connection_unless_it_detaches`,
  `test_a_start_is_sent_before_it_detaches`, `test_a_refusal_is_the_queues_error` with five
  distinct refusals, the countdown and settings tests) each pin a separate protocol behaviour.
  The many "⊂" pairs in the coverage file are the common connect/add path.
- `remote/test_cli_client.py::test_a_server_of_another_api_version_is_not_used` vs
  `remote/test_shared_queue_real.py::test_a_server_of_another_api_version_is_not_used_and_the_client_says_why`:
  the real test asserts more (whole warning line, `queue.store_busy`, summary), but it is the
  plan's check 7, `needs_ffmpeg` and `slow`; the in-process copy (about 1 s) is the fast
  localising test. `remote/test_owner_search.py::test_a_server_of_another_api_version_is_not_used_and_the_reason_names_it`
  pins the reason at the owner-search layer. Kept all three (Tier C to cut the in-process one).
- `jobs/test_cli_plan.py::test_unavailable_encoder_fails_and_names_the_closest` vs
  `jobs/test_service.py::test_unavailable_encoder_names_the_closest_one`: the CLI test gets the
  status from a real detection through the fake ffmpeg (closest match `hevc_qsv`), the core test
  from a stub snapshot (`hevc_vaapi`); different inputs. Kept.
- `jobs/test_encode_real.py` (3) and `jobs/test_cli_batch.py::test_a_season_encoded_end_to_end`:
  C-15 "Done when: the CLI can encode a season folder end to end" (`docs/plan/05-core.md`, C-15);
  `test_ctrl_c_cancels_only_its_own_jobs` is a SIGINT guard of the in-process mode (the real
  client-mode one is in `test_shared_queue_real.py`). Kept.
- `jobs/test_cli_output_names.py::test_the_row_order_is_computed_off_the_event_loop` ⊂
  `jobs/test_cli_file_identity.py::test_the_batch_service_keys_files_off_the_event_loop`: the same
  `BatchStubs` setup, different spies (`episode_key` vs `file_key`); both are review-fix guards
  named in 0040/0041. A merge would save about 10 lines and make two decision references stale:
  Tier C.
- `jobs/test_cli_file_identity.py` linked vs hard-linked pairs (encode and batch): different
  inputs, all named in 0040.
- `jobs/test_cli_plan_dry_run.py::test_no_dry_run_without_custom_or_with_builtin_parameters[Fast 1080p30]`:
  `test_needs_dry_run` pins the empty-parameters input as a unit, but "no custom parameters" and
  "built-in parameters" are two input classes at the CLI. Kept.
- `jobs/test_cli_plan_dry_run.py`: `test_a_passing_dry_run_…`, `test_plan_shows_a_skipped_dry_run`
  ⊂ `test_plan_shows_the_dry_runs_warnings` by lines: three different dry-run results (none,
  skipped, warning) with different expected notes. Kept.
- `jobs/test_cli_robustness.py::test_plan_of_an_undecodable_file_name` ⊂
  `test_plan_and_encode_print_warnings[plan]`: other input. Trim report Q already removed the
  traceback copies.
- `test_cli.py::test_text_subs_attachment` ⊂ `[text-subs]`, `test_hdr10_video_line` vs `[hdr10]`:
  the parametrized test checks consistency with the JSON, these check absolute values on real
  ffprobe output. Kept.
- `test_cli.py::test_no_colour_when_piped_or_no_color`, `test_json_is_only_the_model` ⊂
  snapshot cases: other assertions (colour, JSON form). Kept.
- `jobs/test_cli_presets.py::test_list_marks_the_builtin_default`, `test_preset_rows_align_the_columns`:
  kept by trim report Q; not reported again.
- `jobs/test_cli_encode.py::test_follow_rereads_the_queue_after_a_resync`: kept by trim report Q
  (the only test of the resync path of `_follow_jobs`).
- `remote/test_cli_queue.py::test_an_action_needs_an_owner` and
  `::test_retry_and_remove_need_an_owner[retry|remove]`: near-copies across three commands; a
  single parametrized test would save about 5 lines and no time. Too small to list as a finding.
- `jobs/test_cli_name.py`, `jobs/test_cli_batch.py` dry-run tables, `jobs/test_cli_presets.py`
  import output: the CLI's own rendering, not pinned by the core tests of naming, batch and presets.

## Speed notes

- `remote/test_cli_queue.py` lines 130, 148 and 413: `await asyncio.sleep(1.0)` before asserting
  that `queue log -f` is still following. The follow polls every 0.25 s (0061), so 0.5 s shows
  the same; about 1.5 s of waiting in total.
- `remote/test_shared_queue_real.py`: `Home.source(…, 60)` encodes a 60 s 1280×720 x264 source
  for each of `test_sigint_…`, both `test_kill_9_…` tests (two 60 s sources in one of them) and
  `jobs/test_encode_real.py::long_source` does the same. A session-scoped cache of one 60 s source
  (copied per test) would save several generations; not measured.
- `remote/test_shared_queue_real.py::test_kill_9_of_a_client_cancels_its_jobs_and_a_detached_job_runs_on`:
  `time.sleep(1.0)` to show the detached job still runs; needed as a fixed window, fine.

## Verifier notes

- Corrected totals. Tier A: TCL-01 and TCL-04 only: 2 tests, 7 code lines, about 1.6 s (the report said 3 tests, 16 lines; TCL-03 is rejected). Tier A+B: TCL-01, 02, 04, 05, 06, 07, 08: 5 tests and about 79 code lines (7 + 2 + 9 + 17 + 31 + 13), about 4.4 s (the report said 6 tests, 94 lines, 5.4 s). Measured in the worktree with all seven applied: 476 → 471 tests, −77 code lines (−79 when the moved fixture keeps the name `dirs`).
- TCL-03 shows a blind spot of the coverage method: a guarantee that is a member of a constant set (`WAITED_ACTIONS`) or a dict key runs the same lines for every value. When a test differs from its keeper only in an enum or Literal value, check what reads that value.
- TCL-01: when the merge of TCL-02 is done, adding `assert result.exit_code == EXIT_OK` to the no-driver run of the merged test (the status-change run asserts no exit code today) would keep the one assertion only the deleted test had, for one line.
- TCL-05: the record edit is two test-name substitutions; write them in the same commit as the merge (as a139d30 did) so 0040/0041 never name a missing test.
- The worktree has the untracked `testdata/media` symlink that the brief asked for; nothing else.
