# Redundant-test audit (Q-7)

Goal: a smaller Python test suite that gives every guarantee it gives today. The audit looked for
tests that assert what another test already asserts, parametrizations whose cases take the same
path, copies of one test with small changes, and the same behaviour checked at several layers.
Speed was the secondary goal. The audit changed no product code and no test; a later session makes
the changes from these documents without investigating again ([plan.md](plan.md)).

- Commit: `38cf3eb848e6267522daac27eb219e75993b2e36` (branch `m10-hardening`). Every path and line
  number in these documents refers to it.
- Date: 2026-11-17. Unattended run; the choices made in place of the owner are in
  [decisions-taken.md](decisions-taken.md).
- Decision record: [0091](../decisions/0091-test-trimming-step.md). Plan:
  [09 §Q-7](../plan/09-quality-and-release.md#q-7-test-trimming).
- Earlier work this audit builds on: the test trim of 2026-10-17 (907 tests removed,
  [test-trim-reports/](../test-trim-reports/)) and the test findings of Q-6
  ([simplify/](../simplify/README.md)). Neither is reported again.

## Baseline

| | Value |
|---|---|
| Tests collected | 8,616 (26 `needs_gpu`) |
| Tests run by `-m "not needs_gpu"` | 8,590: 8,576 passed, 14 skipped |
| Test code lines (no blanks, comments, docstrings) | 80,773: 76,286 in test files, 4,487 in `testing/reframe_testing/` |
| Full run on Linux (owner's machine, idle) | 372.8 s (6 min 13 s); repeated 373.3 s and 374.4 s |
| Sum of all test times | about 1,800 s |
| Full run on the Windows test VM | about 12 minutes ([0084](../decisions/0084-parallel-test-runs-with-pytest-xdist.md) "Windows"; not measured again) |
| Whole-run coverage of `reframe` and `reframe_server` | 98 % of 30,622 statements, 96 % of 9,226 branches |

`-n auto` starts **6 workers** on the owner's machine (xdist counts physical cores: 6 physical,
12 logical), not 12 as the brief and 0084 assumed. With 1,800 s of test time, 6 workers need at
least 300 s; about 73 s of the 373 s were lost, almost all of it in the tail of `--dist load`
(one worker ran all of `languages/test_equivalence.py` alone for 90 s at the end). See
[speed.md](speed.md).

Other numbers (in the orchestrator's scratch folder, not committed): 41 `slow`, 967
`needs_ffmpeg`, 201 `needs_mkvtoolnix`, 2 `benchmark` tests; 37 Hypothesis tests in 20 files;
375 snapshot cases in 5 `.ambr` files; 101 parametrized tests with more than 10 cases hold 3,571
of the 8,616 tests; 69 test files use `fake_tools`, 50 `fixture_media`, 63 start a subprocess
directly.

## Result

| | Findings | Tests removed | Test code lines removed | Full run (Linux) |
|---|---|---|---|---|
| Baseline | | 8,616 | 80,773 | 373 s |
| Tier A (Q-7.1 to Q-7.7) | 58 | -71 (+10 ids from a split) | about -520 | about 293 s (295 s measured for the speed levers) |
| Tier B (Q-7.8 to Q-7.13) | 41 | -393 | about -540 | about 285 s (estimate) |
| Tier A + B | 99 | -464 (5.4 %) | about -1,060 (1.3 %) | about 285 s (-24 %) |
| Tier C (not planned) | 11 | | | |

- 110 findings: 102 in 11 areas and 8 on speed. Verify confirmed 87, adjusted 20 (mostly
  numbers, three with a changed input or an added check), rejected 3 (TCL-03, TCD-06, TPM-12: each
  the only test of one input, or a guard a record names).
- Lines are code lines removed net (new helpers subtracted), as corrected in verify; most are
  measured in the verifiers' worktrees, some estimated (marked "about" in the findings).
- Run time: the Tier A speed levers were measured together twice on an idle machine (373.3 /
  374.4 s → 294.2 / 295.3 s). The tests that Tier A and B remove take about 30 s of test time,
  about 5 s of wall time on 6 workers; SPD-08 (Tier B) is estimated at 4–5 s. Windows: the same
  scheduler change should save 1–2 minutes of the VM's 12 (not measured).
- The suite was already lean: the October trim and Q-6 removed most of the easy cases, and much of
  the rest is guards that a decision record, a plan "Done when" or a trim report names. **The large
  gain is speed, not size.**

Per area (code lines and test time from the baseline):

| Area file | Scope | Tests | Lines | Test time | Findings (A/B/C) | Removed A+B (tests / lines) |
|---|---|---|---|---|---|---|
| [validation](areas/validation.md) | `tests/validation/` | 1,492 | 7,052 | 109 s | 4 / 8 / 1 | 267 / 159 |
| [batch](areas/batch.md) | `tests/batch/` | 709 | 6,173 | 60 s | 4 / 3 / 0 | 7 / 48 |
| [server](areas/server.md) | `packages/reframe-server/tests/` | 661 | 7,906 | 263 s | 2 / 5 / 0 | 9 / about 86 |
| [queue-analysis](areas/queue-analysis.md) | `tests/queue/`, `analysis/`, tasks, events | 402 | 7,325 | 81 s | 9 / 0 / 0 | 7 / 85 |
| [cli-jobs-remote](areas/cli-jobs-remote.md) | `tests/jobs/`, `remote/`, `test_cli.py` | 476 | 7,605 | 527 s | 2 / 5 / 1 | 5 / 79 |
| [probe-metadata-languages](areas/probe-metadata-languages.md) | `tests/probe/`, `metadata/`, `languages/` | 1,191 | 7,888 | 296 s | 8 / 6 / 3 | 14 / 118 |
| [command-capabilities-dimensions](areas/command-capabilities-dimensions.md) | `tests/command/`, `capabilities/`, `dimensions/` | 744 | 7,605 | 178 s | 7 / 3 / 1 | 14 / 81 |
| [tools-platform](areas/tools-platform.md) | `tests/tools/`, `platform/`, applog, diagnostics | 516 | 6,964 | 84 s | 4 / 3 / 1 | 11 / 96 |
| [definitions-models-presets](areas/definitions-models-presets.md) | `tests/definitions/`, `models/`, `presets/`, settings | 1,170 | 6,418 | 102 s | 2 / 2 / 0 | 104 / 57 |
| [naming-preview-service](areas/naming-preview-service.md) | `tests/naming/`, `preview/`, facade | 688 | 4,722 | 66 s | 3 / 2 / 0 | 4 / 46 |
| [testing-package](areas/testing-package.md) | `testing/tests/` | 567 | 6,628 | 29 s | 9 / 2 / 2 | 22 / 205 |
| [speed](speed.md) | the whole run | | | | 4 / 2 / 2 | -79 s measured (A) |

The five most valuable findings:

1. **SPD-01 + SPD-02 + TPM-01** with SPD-04, SPD-07 and the fetch server's poll interval
   ([speed.md](speed.md), Q-7.7, A): `--dist worksteal`, the two slowest language sweeps split into
   12 parametrized parts and run tag by tag, the fake tools imported from their `.pyc`. Every full
   run 21 % shorter (-79 s), every test kept, every language tag still checked once.
2. **TVL-02** ([validation](areas/validation.md), Q-7.8, B): -238 test cases. The mixdown and
   bitrate "follow the helper" grids compared the C-6 helpers with themselves; the audio agreement
   matrix with five added checks covers a superset of their inputs and catches every mutation the
   grids caught, and four the grids missed.
3. **TDM-01** ([definitions-models-presets](areas/definitions-models-presets.md), Q-7.9, B): -104
   tests. Five per-preset checks over the 26 built-in presets in three files become one test with
   `subtests`; five planted defects each still fail it.
4. **TTK-13, TCL-07, TPM-14, TVL-08** (B and A): shared helpers in place of copies, about -180
   lines; the largest is one `load_script` helper for 11 by-path script loaders (-92).
5. **SPD-05** ([speed.md](speed.md), Q-7.13, B): a per-test timeout (`pytest-timeout`, thread
   method, 600 s, with `faulthandler_timeout`). It removes nothing, but the first coverage run of
   this audit hung for an hour on a forked child (D-4), and today a hang blocks a run until the
   CI job's 30-minute limit, with no stack trace.

Close behind: the queue findings TQA-01 to TQA-09 (all Tier A; the mutation checks showed the
kept tests are the stricter ones).

## Method

1. **Phase 0, measurements** (orchestrator): a baseline run with per-test durations (junit XML);
   counts per marker, Hypothesis, snapshots, parametrizations and subprocess use; code lines per
   folder; a per-test coverage map (pytest-cov `--cov-context=test`, C tracer) turned into groups
   of tests with equal or contained line sets per area; and a whole-run coverage baseline with
   `coverage run` and `patch = ["subprocess"]` (D-3).
2. **Phase 1, audit:** 11 agents (Opus), one per area of 4.7k–7.9k test lines, read every test of
   their area with the coverage groups, the decision records, `docs/status.md`, the trim reports
   and `git log -S` of every test they proposed to touch. They ran no tests (D-2). One more agent
   (Phase 1b) measured the speed levers in its own worktree.
3. **Phase 2, verify:** 12 fresh agents (Opus) in worktrees tried to prove each finding wrong:
   inputs and assertions side by side, documents and history, Windows and CI paths. Most applied
   the proposed changes, ran the tests (at most 3 runs at a time, D-2), ran mutations of the
   product code to show the kept test still fails, and recounted tests and lines. Every finding
   has a `Verdict:` and `Checked:` lines. The speed verifier measured all Tier A levers together.
4. **Phase 3, synthesis** (orchestrator): tiers by the rules in D-7, work packages in
   [plan.md](plan.md), choices in [decisions-taken.md](decisions-taken.md). Each finding has an
   `Orchestrator:` line with its tier and package.

Tiers: **A** = clearly redundant, no guarantee lost, low risk, inside one area; **B** = a merge or
rewrite with some risk, a record or plan-text edit, a cross-area change, a shared helper, or a CI
or dependency change; **C** = not worth it or loses a guarantee (listed so that the next audit does
not report it again).

## What is missing or weak

- **Windows was not measured.** The VM's numbers come from 0084. The Windows half of SPD-04 (the
  `.cmd` launcher) and the Windows time saving are reasoned from the code; Q-7.13 checks them on
  the VM.
- **The per-test coverage map is weak evidence.** It has no import-time lines and no subprocess
  code (the CLI, server and fake-tool processes); it only showed where to look. No finding rests
  on it alone.
- **The area auditors ran no tests**, and two of them finished before they knew of the earlier
  trim (D-5); their verifiers made up for both.
- **The plan's coverage comparison was not run per finding** in the audit. The verifiers used the
  per-test map and focused runs; each package runs the whole-run comparison ([plan.md](plan.md)).
  The baseline JSON is not committed; regenerate it on the package's base commit.
- The `Checked:` lines name scripts in the orchestrator's scratch folder (`$SCRATCH/...`); those
  files are not kept. The commands and results in the lines are the record.
- **Gaps found, not redundancy** (not planned; for a later step):
  - `ToolsService.fetch(manifest=...)` has one caller, the core test TTP-02 would have deleted
    (TTP-02 is Tier C because of it).
  - `_REFUSED` in `definitions/test_options_values.py` is never shown to catch a refused value; the
    pure test `test_every_software_encoder_has_options_in_each_main_category` sits under
    `needs_ffmpeg` by mistake (TDM-03 notes).
  - The `runner.py:458` race (`_wait_resumed`) has no test that reaches it every time (TQA notes,
    trim Q).
  - Two mutations no test catches: dropping the channel limit in `snap_mixdown`'s fallback (cannot
    change the result with today's data) and a changed default of `hardware_test_argv(vaapi_device=)`
    (no production caller omits it).
  - The runner's `preexec_fn` (the parent-death signal on Linux) makes every spawn fork and run
    Python in the child, which the Python docs call unsafe with threads (SPD-06, Tier C; SPD-05
    limits the damage).
  - Decision 0084 and the plan say "12 workers"; `-n auto` gives one per physical core (6 here).

## How to read the files

- [areas/](areas/) and [speed.md](speed.md): the findings. Each has Kind, Where, Now, Change,
  Saved, Guarantee kept by, Why nothing is lost, Docs and history, Risk, Proposed tier,
  Confidence, then the verifier's `Verdict:` and `Checked:` lines and the orchestrator's
  `Orchestrator:` line. An ADJUSTED verdict corrects the bullets above it. "Looked at and kept"
  in each area file lists what looks redundant but stays, and why: read it before looking again.
  Each area file ends with the verifier's notes.
- [plan.md](plan.md): the work packages Q-7.1 to Q-7.13, the coverage comparison, the waves and
  the brief for an implementation agent.
- [speed-levers.diff](speed-levers.diff): the exact Tier A speed change the verifier measured at
  `38cf3eb`.
- [decisions-taken.md](decisions-taken.md): every choice made in place of the owner, and what
  changes if the owner chooses otherwise.

## All findings

The corrected numbers of each finding are in its `Verdict:` line.

| ID | Title | Verdict | Tier | Package |
|---|---|---|---|---|
| [TVL-01](areas/validation.md) | Negative cases that are the clean scenario | CONFIRMED | B | Q-7.8 |
| [TVL-02](areas/validation.md) | The mixdown and bitrate "follow the helper" grids are inside the audio agreement matrix | ADJUSTED | B | Q-7.8 |
| [TVL-03](areas/validation.md) | Two option cases copy the R5 tests of `test_option_values.py` | CONFIRMED | A | Q-7.1 |
| [TVL-04](areas/validation.md) | The x265 VBV buffer case copies `test_a_vbv_buffer_without_a_maximum_rate` | CONFIRMED | B | Q-7.8 |
| [TVL-05](areas/validation.md) | `test_read_only_source_through_the_view` is the same scenario as two other tests | CONFIRMED | A | Q-7.1 |
| [TVL-06](areas/validation.md) | The in-place default-track test is a rule case | CONFIRMED | A | Q-7.1 |
| [TVL-07](areas/validation.md) | Template default-track lint is tested in `batch/test_lint.py`; keep one wiring test | CONFIRMED | B | Q-7.8 |
| [TVL-08](areas/validation.md) | `_found_tools()` and `_source()` are copies of `scenario.make_tools()` / `make_source()` | CONFIRMED | A | Q-7.1 |
| [TVL-09](areas/validation.md) | Two "the dry run never starts FFmpeg" tests are one test with two row lists | CONFIRMED | B | Q-7.8 |
| [TVL-10](areas/validation.md) | The facade's libvpx `arnr-maxframes=16` dry run repeats the R5-3 real-tool test | CONFIRMED | B | Q-7.8 |
| [TVL-11](areas/validation.md) | (cross-area) `command/test_builder.py::test_refusals` repeats `PlanError` agreement rows | CONFIRMED | B | Q-7.8 |
| [TVL-12](areas/validation.md) | The `split_custom_params` text test belongs in the definitions tests | CONFIRMED | B | Q-7.8 |
| [TVL-13](areas/validation.md) | `test_no_odd_sizes` is a weaker copy of the dimensions properties | CONFIRMED | C | — |
| [TBT-01](areas/batch.md) | Two tests of "a rule with settings of the other kind" on E05 | CONFIRMED | A | Q-7.1 |
| [TBT-02](areas/batch.md) | `test_one_group_at_every_level`: three cases become one stricter test | ADJUSTED | A | Q-7.1 |
| [TBT-03](areas/batch.md) | `test_episode_label_with_season` folds into the named `test_episode_labels` | CONFIRMED | A | Q-7.1 |
| [TBT-04](areas/batch.md) | `test_codec_family`: the `opus` case repeats the `flac` case | CONFIRMED | A | Q-7.1 |
| [TBT-05](areas/batch.md) | `test_the_example_steps` resolves the same matrix as the snapshot test | CONFIRMED | B | Q-7.11 |
| [TBT-06](areas/batch.md) | `test_the_draft_has_the_lint_for_this_source` repeats the lint's own source test | ADJUSTED | B | Q-7.11 |
| [TBT-07](areas/batch.md) | The example's four codec rules are written four times | CONFIRMED | B | Q-7.11 |
| [TSV-01](areas/server.md) | The chapter import format test repeats core tests and the server round trip | CONFIRMED | A | Q-7.5 |
| [TSV-02](areas/server.md) | Two tests build the OpenAPI document to check the WebSocket message schemas | CONFIRMED | A | Q-7.5 |
| [TSV-03](areas/server.md) | Two tests check that task events hide the server's cache folder | ADJUSTED | B | Q-7.10 |
| [TSV-04](areas/server.md) | Two "client drops while the hub waits to send" tests share their setup | ADJUSTED | B | Q-7.10 |
| [TSV-05](areas/server.md) | Two real-FFmpeg preview clip tests can share one clip | CONFIRMED | B | Q-7.10 |
| [TSV-06](areas/server.md) | Two settings tests send the same tool-path patch | CONFIRMED | B | Q-7.10 |
| [TSV-07](areas/server.md) | The diagnostics "unknown settings field" test repeats the core report test | ADJUSTED | B | Q-7.10 |
| [TQA-01](areas/queue-analysis.md) | Cancel-all is tested twice with the same setup | CONFIRMED | A | Q-7.2 |
| [TQA-02](areas/queue-analysis.md) | Stop with jobs left: `test_stop_takes_no_new_jobs` repeats the when-done stop test | CONFIRMED | A | Q-7.2 |
| [TQA-03](areas/queue-analysis.md) | `test_close_during_a_countdown` is covered by three other close-cancels-the-countdown tests | CONFIRMED | A | Q-7.2 |
| [TQA-04](areas/queue-analysis.md) | `test_the_action_runs_when_the_last_job_failed` is the first half of `test_new_work_cancels_the_countdown[retry]` | CONFIRMED | A | Q-7.2 |
| [TQA-05](areas/queue-analysis.md) | The renamed-output notification is a one-line addition to `test_collision_auto_rename` | CONFIRMED | A | Q-7.2 |
| [TQA-06](areas/queue-analysis.md) | "An encode of a file that is edited in place is not claimed" is one assertion of the scheduling test | CONFIRMED | A | Q-7.2 |
| [TQA-07](areas/queue-analysis.md) | `test_plan_json_round_trip` is a second store round trip with one more field | CONFIRMED | A | Q-7.2 |
| [TQA-08](areas/queue-analysis.md) | Two hand-copied test helpers that a shared one already does | CONFIRMED | A | Q-7.2 |
| [TQA-09](areas/queue-analysis.md) | Two suspend ETA tests are one parametrized test | CONFIRMED | A | Q-7.2 |
| [TCL-01](areas/cli-jobs-remote.md) | `test_no_nvidia_driver` repeats the NVENC line check of the cache test | CONFIRMED | A | Q-7.5 |
| [TCL-02](areas/cli-jobs-remote.md) | `test_second_run_prints_the_cache_at_once` and the status-change test start from the same cached first run | CONFIRMED | B | Q-7.10 |
| [TCL-03](areas/cli-jobs-remote.md) | `test_a_sleep_countdown` is the shutdown end-to-end test with another verb | REJECTED | C | — |
| [TCL-04](areas/cli-jobs-remote.md) | the dry-run error is checked in two tests, human and `--json` | CONFIRMED | A | Q-7.5 |
| [TCL-05](areas/cli-jobs-remote.md) | the RA-4 check runs a copy of `test_encode_never_writes_another_file_of_the_command` | CONFIRMED | B | Q-7.10 |
| [TCL-06](areas/cli-jobs-remote.md) | `test_recorded_badges_and_bitrate_sources` asserts strings that the probe snapshots pin | ADJUSTED | B | Q-7.10 |
| [TCL-07](areas/cli-jobs-remote.md) | one `cli_env` and one CLI subprocess helper instead of two copies each | ADJUSTED | B | Q-7.10 |
| [TCL-08](areas/cli-jobs-remote.md) | one fixture for the private folders of the real-FFmpeg CLI tests | CONFIRMED | B | Q-7.10 |
| [TPM-01](areas/probe-metadata-languages.md) | Compute each tag once in the equivalence sweeps (loop order of `_differences`) | CONFIRMED | A | Q-7.7 |
| [TPM-02](areas/probe-metadata-languages.md) | The fast subsets of `test_equivalence.py` repeat the slow sweeps in every run | ADJUSTED | B | Q-7.11 |
| [TPM-03](areas/probe-metadata-languages.md) | A smaller input set or a stored oracle for the 88 s and 46 s sweeps | CONFIRMED | C | — |
| [TPM-04](areas/probe-metadata-languages.md) | `test_the_matroska_reader_is_hashed` is a weaker copy of one parametrized case | CONFIRMED | A | Q-7.3 |
| [TPM-05](areas/probe-metadata-languages.md) | Two tests pin `Prober.cache_options()` | CONFIRMED | A | Q-7.3 |
| [TPM-06](areas/probe-metadata-languages.md) | `test_the_byte_sum_check_covers_every_stream` is inside the compressed-track test | CONFIRMED | A | Q-7.3 |
| [TPM-07](areas/probe-metadata-languages.md) | Merge the two huge-`TimestampScale` regression tests | CONFIRMED | A | Q-7.3 |
| [TPM-08](areas/probe-metadata-languages.md) | `test_a_sample_that_cannot_read_the_file_leaves_the_rates_unknown` is the `unreadable` case of a later test | CONFIRMED | A | Q-7.3 |
| [TPM-09](areas/probe-metadata-languages.md) | Merge the time-limit sample test into the not-cached test | CONFIRMED | B | Q-7.11 |
| [TPM-10](areas/probe-metadata-languages.md) | `test_probe_shows_language_ietf` repeats the real-file BCP 47 probe test | ADJUSTED | B | Q-7.11 |
| [TPM-11](areas/probe-metadata-languages.md) | Merge `test_apply_matroska_sets_ietf_by_kind_and_order` into the two `apply_matroska` tests | ADJUSTED | B | Q-7.11 |
| [TPM-12](areas/probe-metadata-languages.md) | `test_the_reprobe_shows_only_the_files_bcp47_tags` repeats the reprobe test of the real edit | REJECTED | C | — |
| [TPM-13](areas/probe-metadata-languages.md) | The plain multi-cluster sample test is the attachment test without the attachment | CONFIRMED | B | Q-7.11 |
| [TPM-14](areas/probe-metadata-languages.md) | One copy of the file surgery helpers for the bogus Seek entry and the invalid `LanguageIETF` | CONFIRMED | A | Q-7.3 |
| [TPM-15](areas/probe-metadata-languages.md) | Two parametrization rows that another test already holds | CONFIRMED | A | Q-7.3 |
| [TPM-16](areas/probe-metadata-languages.md) | Run the entry-variant property test over every entry instead of 300 samples | CONFIRMED | B | Q-7.11 |
| [TPM-17](areas/probe-metadata-languages.md) | The `DocTypeVersion` oracle matrix runs one in-process path per edit for "title only" | CONFIRMED | C | — |
| [TCD-01](areas/command-capabilities-dimensions.md) | The hardware-tests-off and default detections in `test_detect.py` run the same detection two or three times | CONFIRMED | A | Q-7.4 |
| [TCD-02](areas/command-capabilities-dimensions.md) | Three hand-written test-encode commands are pinned exactly by the capture-replay tests | CONFIRMED | A | Q-7.4 |
| [TCD-03](areas/command-capabilities-dimensions.md) | `test_vaapi_command` is also pinned by the VAAPI captures | CONFIRMED | A | Q-7.4 |
| [TCD-04](areas/command-capabilities-dimensions.md) | `test_the_last_line_is_never_the_reason` repeats a `test_real_failures` row | CONFIRMED | A | Q-7.4 |
| [TCD-05](areas/command-capabilities-dimensions.md) | `test_the_gpu_fingerprint_is_read_once` repeats the flow of `test_rescan_ignores_the_cache` | CONFIRMED | A | Q-7.4 |
| [TCD-06](areas/command-capabilities-dimensions.md) | `test_a_10bit_test_with_another_pixel_format_fails` repeats the hwtest case one layer up | REJECTED | C | — |
| [TCD-07](areas/command-capabilities-dimensions.md) | The issue tests and their "apply the fix to a job" twins compute the same issue | CONFIRMED | B | Q-7.11 |
| [TCD-08](areas/command-capabilities-dimensions.md) | `test_colour_params_is_the_graphs_setparams` and `test_setparams_only_for_an_untagged_source` build the same graphs | CONFIRMED | B | Q-7.11 |
| [TCD-09](areas/command-capabilities-dimensions.md) | `test_metadata_edit_plan_needs_no_tool` repeats the job of `test_metadata_edit_plan_edits_the_source` | CONFIRMED | A | Q-7.4 |
| [TCD-10](areas/command-capabilities-dimensions.md) | The MKV half of `test_a_header_edit_step_for_mkv_without_any_mkvtoolnix_but_not_for_webm` is in `test_metadata_edit.py` | CONFIRMED | B | Q-7.11 |
| [TCD-11](areas/command-capabilities-dimensions.md) | `dimensions/test_ffmpeg.py::test_interlaced_fixture` runs no FFmpeg filter. It only re-checks pure tests on a probed fixture | CONFIRMED | A | Q-7.4 |
| [TTP-01](areas/tools-platform.md) | The core "cancel stops the download" test is a weaker copy of the slow-download cancel test | CONFIRMED | A | Q-7.6 |
| [TTP-02](areas/tools-platform.md) | The facade fetch test repeats what the CLI fetch test asserts | ADJUSTED | C | — |
| [TTP-03](areas/tools-platform.md) | Two `tools status` tests invoke the same command; merge them | ADJUSTED | A | Q-7.6 |
| [TTP-04](areas/tools-platform.md) | Two discovery tests became copies of their neighbours (after C-18 and D-7) | CONFIRMED | A | Q-7.6 |
| [TTP-05](areas/tools-platform.md) | Two power-countdown tests repeat a neighbour's setup and inputs | CONFIRMED | A | Q-7.6 |
| [TTP-06](areas/tools-platform.md) | Two D-Bus error tests through `call()` repeat the `Connection` tests that cover the same failures | CONFIRMED | B | Q-7.12 |
| [TTP-07](areas/tools-platform.md) | Four diagnostics-report tests build the same report; one test can check the four parts | CONFIRMED | B | Q-7.12 |
| [TTP-08](areas/tools-platform.md) | Fetch test setup and the `_alive` helper are copied between files | CONFIRMED | B | Q-7.12 |
| [TDM-01](areas/definitions-models-presets.md) | One parametrized validity test per built-in preset instead of five | ADJUSTED | B | Q-7.9 |
| [TDM-02](areas/definitions-models-presets.md) | The linter-mutation tests of `test_options_search_hdr.py` belong in `test_lint.py` | CONFIRMED | A | Q-7.4 |
| [TDM-03](areas/definitions-models-presets.md) | One shared helper for the "run FFmpeg on lavfi and read the log or SEI" code of the oracle tests | CONFIRMED | B | Q-7.9 |
| [TDM-04](areas/definitions-models-presets.md) | Small asserts that another test makes with the same input | CONFIRMED | A | Q-7.4 |
| [TNP-01](areas/naming-preview-service.md) | The clip off-loop test makes the same two clips as the cached-clip test | ADJUSTED | A | Q-7.5 |
| [TNP-02](areas/naming-preview-service.md) | The settings default count of the frames task: one assert in a test that already sets the preview settings | CONFIRMED | A | Q-7.5 |
| [TNP-03](areas/naming-preview-service.md) | `test_multibyte_characters_are_never_split` is covered by a stricter example and by the property test | CONFIRMED | A | Q-7.5 |
| [TNP-04](areas/naming-preview-service.md) | The facade clip test repeats the server's clip-route tests | CONFIRMED | B | Q-7.10 |
| [TNP-05](areas/naming-preview-service.md) | The `env` fixture (and the fake-tools `fake` fixture) copied between the facade test files | ADJUSTED | B | Q-7.10 |
| [TTK-01](areas/testing-package.md) | One test for "which archives a platform's notices list" and "their licence texts" | CONFIRMED | A | Q-7.6 |
| [TTK-02](areas/testing-package.md) | `bundles()` per kind of source: the end-to-end notices test already checks every archive on every platform | CONFIRMED | C | — |
| [TTK-03](areas/testing-package.md) | Trim the "all four or none" subsets of the notices options from 14 to 8 | CONFIRMED | A | Q-7.6 |
| [TTK-04](areas/testing-package.md) | Three more same-setup pairs in `test_third_party_notices.py` | CONFIRMED | A | Q-7.6 |
| [TTK-05](areas/testing-package.md) | Merge the two Ubuntu source-package fetch tests | CONFIRMED | A | Q-7.6 |
| [TTK-06](areas/testing-package.md) | One btbn-stage test for "several commits in sub folders" and "each sub folder's licence" | CONFIRMED | B | Q-7.12 |
| [TTK-07](areas/testing-package.md) | Release workflow: two pairs to parametrize, one damage case on the same path | CONFIRMED | A | Q-7.6 |
| [TTK-08](areas/testing-package.md) | The "draft deleted, not reused" test and the interrupted-upload test | CONFIRMED | C | — |
| [TTK-09](areas/testing-package.md) | `test_fetch_tools.py`: one manifest helper for the two `main` tests, one parametrized `verify_file` reject test | ADJUSTED | A | Q-7.6 |
| [TTK-10](areas/testing-package.md) | Fake ffmpeg: `test_hang_times_out` is inside `test_asyncio_timeout_and_tree_kill`; one inline progress parser repeats `parse_blocks` | CONFIRMED | A | Q-7.6 |
| [TTK-11](areas/testing-package.md) | Small parameter trims that take the same path as another case or test | CONFIRMED | A | Q-7.6 |
| [TTK-12](areas/testing-package.md) | Delete the C-0 "package is importable" placeholder | CONFIRMED | A | Q-7.6 |
| [TTK-13](areas/testing-package.md) | One `load_script` helper in `reframe_testing` for the by-path script loaders | CONFIRMED | B | Q-7.12 |
| [SPD-01](speed.md) | `--dist worksteal` instead of `load` | CONFIRMED | A | Q-7.7 |
| [SPD-02](speed.md) | split the two slowest language sweeps into parametrized parts | ADJUSTED | A | Q-7.7 |
| [SPD-03](speed.md) | `-n logical` (12 workers) is not faster | CONFIRMED | C | — |
| [SPD-04](speed.md) | the fake tools import `fake_ffmpeg` from its cached `.pyc` | ADJUSTED | A | Q-7.7 |
| [SPD-05](speed.md) | a per-test timeout (pytest-timeout) | ADJUSTED | B | Q-7.13 |
| [SPD-06](speed.md) | the `preexec_fn` also costs a fork per spawn | CONFIRMED | C | — |
| [SPD-07](speed.md) | fixed waits in four runner tests | CONFIRMED | A | Q-7.7 |
| [SPD-08](speed.md) | `test_shared_queue_real.py`: generated sources and CLI polls | CONFIRMED | B | Q-7.13 |
