# Redundant-test audit: implementation plan (Q-7)

This plan groups the Tier A and Tier B findings into work packages. Each package is one task for
one agent and one step `Q-7.n` in
[09-quality-and-release.md](../plan/09-quality-and-release.md#q-7-test-trimming). The findings are
in [areas/](areas/) and [speed.md](speed.md); the summary is in [README.md](README.md).

Packages Q-7.1 to Q-7.7 hold Tier A; Q-7.8 to Q-7.13 hold Tier B. Tier C is not planned.

## Rules for every package

- Line numbers in the findings refer to commit `38cf3eb`. Earlier packages move them. Find each
  test by its name, check that it still matches the finding's "Now" bullet, and make the change
  against the current code when the intent is still clear; otherwise skip that finding and say so
  in the commit message and in `docs/status.md`.
- Make only the changes the findings describe. Read the whole finding: the `Verdict:` line
  corrects the bullets above it (an ADJUSTED verdict gives the correction to follow), and the
  `Orchestrator:` line can add a condition (for example "start one real task", "use `subtests`").
  Do not investigate again and do not trim more. Something new goes into the step's row in
  `docs/status.md` as a note.
- **A merge keeps every input and every assertion** of both tests, and the name of the test that a
  decision record, a plan "Done when", `docs/status.md`, `testdata/README.md` or a report in
  `docs/test-trim-reports/` names. Where a finding says a record or plan line names a removed test,
  change that line in the same commit (a test-name reference only; no decision changes).
- Comments and docstrings follow the `code-comments` skill.
- **Done when** (every package, in addition to its own items):
  1. the focused tests of the package's folders pass (list below), and each changed file run
     alone passes (`uv run pytest <file>`);
  2. `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`,
     `uv run mypy --platform win32`;
  3. the test count changed by the estimate: `uv run pytest --collect-only -q -n 0 -p no:cacheprovider <folders> | tail -1`
     before and after; a different count is explained in the commit message;
  4. **the coverage comparison** (below) shows no covered line of `reframe` or `reframe_server`
     lost, or the commit message names each lost line and the test that still pins its
     behaviour;
  5. `docs/status.md` has the step marked done with a one-line note (tests and code lines removed,
     from the count and `git diff --stat`).
- Commit each package as one conventional commit with the step ID as scope, for example
  `test(Q-7.2): merge the duplicate queue and when-done tests`. Never push.

## Coverage comparison

Run once on the package's base commit and once after the change, on an otherwise idle machine
(about 7 minutes each, the full suite under xdist):

```sh
# rc file, outside the repository (the paths are examples)
cat > /tmp/q7-cov.toml <<'EOF'
[tool.coverage.run]
branch = true
source = ["reframe", "reframe_server"]
parallel = true
patch = ["subprocess"]
data_file = "/tmp/q7-cov/.coverage"
disable_warnings = ["module-not-measured", "no-data-collected", "module-not-imported"]
EOF
rm -rf /tmp/q7-cov && mkdir -p /tmp/q7-cov
uv run coverage run --rcfile=/tmp/q7-cov.toml -m pytest -m "not needs_gpu" -q -p no:cacheprovider
uv run coverage combine --rcfile=/tmp/q7-cov.toml -q
uv run coverage json --rcfile=/tmp/q7-cov.toml -o /tmp/q7-before.json -q   # -after.json the second time
```

`patch = ["subprocess"]` (coverage 7.10 or later) measures every xdist worker and every Python
subprocess (the CLI, the server, the fake tools) from its start, so import-time lines are counted
too. Baseline at `38cf3eb`: 98 % of 30,622 statements and 96 % of 9,226 branches. Then compare the
`executed_lines` and `executed_branches` of every file:

```python
import json, sys
a, b = (json.load(open(p))["files"] for p in sys.argv[1:3])
for f in sorted(a):
    lost = sorted(set(a[f]["executed_lines"]) - set(b.get(f, {}).get("executed_lines", [])))
    arcs = sorted({tuple(x) for x in a[f].get("executed_branches", [])} - {tuple(x) for x in b.get(f, {}).get("executed_branches", [])})
    if lost or arcs: print(f, "lines", lost, "branches", arcs)
```

A lost line that a timing difference explains (a retry or poll branch reached in one run and not
the other) is checked by running the comparison once more; name it in the commit message if it
stays. The comparison runs the full suite: the orchestrator runs it for one package at a time
(it needs an idle machine), or the agent runs it when it is the only test-running agent.

## How to run the tests

The notes of [docs/simplify/plan.md](../simplify/plan.md) "How to run the tests" hold: agents run
focused tests only; the orchestrator runs the full suite after each wave is merged; the known
load-sensitive tests are listed there; agent worktrees start from `main` (`git reset --hard <SHA>`
first). At most 3 agents run tests at the same time. `-n auto` starts one worker per **physical**
core (6 on the owner's machine), see [speed.md](speed.md).

## Which model

The owner asked whether Haiku agents are enough ([decisions-taken.md](decisions-taken.md) D-12).
Recommendation:

- **Opus for every package.** Every package holds at least one merge (an assertion moved into
  another test), and the merges, the record and plan-text edits, the timing-sensitive tests and the
  coverage comparison are where a silent loss can happen. The whole trim saves about 1,000 lines,
  and verify rejected or corrected about one finding in four.
- **Haiku is enough only for single findings** that are a plain deletion with a named keeper, a
  parametrize-row trim, or a helper move whose recipe a verifier applied and ran: TVL-05, TVL-06,
  TVL-08, TBT-04, TQA-08, TPM-04, TPM-06, TPM-08, TPM-14, TPM-15, TCD-02, TCD-04, TCD-11, TNP-03,
  TTK-11, TTK-12, TTK-13. To use it, the orchestrator splits these out of their package into a
  Haiku agent's task and runs the rest of the package with Opus.
- Either way, one Opus review of each wave's diff before it is merged: does every deleted test
  have its keeper, does every merge keep every input and assertion, did the coverage comparison
  run.

## Work packages

Estimates are tests removed / code lines removed (no blanks, comments or docstrings), as corrected
in verify. Folders are under `packages/reframe/tests/` unless they start with `packages/` or
`testing/`.

### Tier A

#### Q-7.1 Validation and batch (A)
- Findings: TVL-03, TVL-05, TVL-06, TVL-08 ([validation](areas/validation.md)); TBT-01, TBT-02,
  TBT-03, TBT-04 ([batch](areas/batch.md)).
- Files: `validation/cases_options.py`, `test_inplace_fs.py`, `test_default_tracks.py`, the files
  with `_found_tools()` / `_source()` copies (TVL-08), `scenario.py`; `batch/test_rules.py`,
  `test_grouping.py`, `test_descriptors.py`.
- Order: the validation findings, then the batch findings.
- Done when: the common items; `uv run pytest packages/reframe/tests/validation packages/reframe/tests/batch`.
- Estimate: 11 / 71.

#### Q-7.2 Queue and analysis (A)
- Findings: TQA-01 to TQA-09 ([queue-analysis](areas/queue-analysis.md)).
- Files: `queue/test_queue.py`, `test_when_done.py`, `test_faults.py`, `test_in_place_scheduling.py`,
  `test_output_claims.py`, `test_job_keys.py`, `test_store.py`, `test_store_nesting.py`,
  `test_progress.py`.
- Order: TQA-08 (helpers) first, then TQA-01 to TQA-07, TQA-09.
- Done when: the common items; `uv run pytest packages/reframe/tests/queue packages/reframe/tests/analysis`
  passes **5 times in a row** (the merged tests are timing-sensitive; TQA-02 keeps its 0.1 s
  settle); the mutation checks of the verdicts still fail the merged tests (TQA-01/02: when-done
  after a cancelled last job, and after a stop with jobs waiting; TQA-05: the notification ignores
  the renamed output).
- Estimate: 7 / 85.

#### Q-7.3 Probe, metadata and languages (A)
- Findings: TPM-04, TPM-05, TPM-06, TPM-07, TPM-08, TPM-14, TPM-15
  ([probe-metadata-languages](areas/probe-metadata-languages.md)). TPM-01 is in Q-7.7 (the same
  file as SPD-02).
- Files: `probe/test_cache_fingerprint.py`, `test_prober.py`, `test_bitrate.py`, `test_sampling.py`,
  `test_matroska_limits_and_ietf.py` and the metadata test with the second surgery copy (TPM-14),
  `test_chapters.py`, `test_languages.py` (TPM-15 rows), a new helper module in
  `testing/reframe_testing/` (TPM-14).
- Done when: the common items; `uv run pytest packages/reframe/tests/probe packages/reframe/tests/metadata`;
  the `needs_mkvtoolnix` tests that use the moved surgery helpers ran (not skipped) on this
  machine; TPM-07 keeps 916314b's exact damaged-file input.
- Estimate: 7 / 58.

#### Q-7.4 Command, capabilities, dimensions and definitions (A)
- Findings: TCD-01, TCD-02, TCD-03, TCD-04, TCD-05, TCD-09, TCD-11
  ([command-capabilities-dimensions](areas/command-capabilities-dimensions.md)); TDM-02, TDM-04
  ([definitions-models-presets](areas/definitions-models-presets.md)).
- Files: `capabilities/test_detect.py`, `test_hwtest.py`, `test_reasons.py`, `test_service.py`;
  `command/test_metadata_edit.py`; `dimensions/test_ffmpeg.py`; `definitions/test_lint.py`,
  `test_options_search_hdr.py`; `presets/test_builtin.py`, `presets/test_store.py`.
- Done when: the common items; `uv run pytest packages/reframe/tests/capabilities packages/reframe/tests/command packages/reframe/tests/dimensions packages/reframe/tests/definitions packages/reframe/tests/presets`;
  the 73 plan snapshots unchanged; R.md's placeholder mutation (TCD-03 verdict) still fails a
  capture-replay test.
- Estimate: 10 / 80.

#### Q-7.5 Server, CLI, naming and preview (A)
- Findings: TSV-01, TSV-02 ([server](areas/server.md)); TCL-01, TCL-04
  ([cli-jobs-remote](areas/cli-jobs-remote.md)); TNP-01, TNP-02, TNP-03
  ([naming-preview-service](areas/naming-preview-service.md)).
- Files: `packages/reframe-server/tests/test_job_output.py`, `test_attach.py`, `test_openapi.py`;
  `jobs/test_cli_encoders.py`, `jobs/test_cli_plan_dry_run.py`; `preview/test_clip.py`,
  `preview/test_frames.py`; `naming/test_sanitize.py`.
- Done when: the common items; `uv run pytest packages/reframe-server/tests packages/reframe/tests/jobs packages/reframe/tests/preview packages/reframe/tests/naming`;
  `packages/reframe-server/tests/test_facade_coverage.py` passes; decision 0057's reference to the
  OpenAPI check in `test_attach.py` is updated (TSV-02 verdict).
- Estimate: 9 / 62.

#### Q-7.6 Tools, platform and the testing package (A)
- Findings: TTP-01, TTP-03, TTP-04, TTP-05 ([tools-platform](areas/tools-platform.md)); TTK-01,
  TTK-03, TTK-04, TTK-05, TTK-07, TTK-09, TTK-10, TTK-11, TTK-12
  ([testing-package](areas/testing-package.md)).
- Files: `tools/test_fetch.py`, `test_fetch_cli.py`, `test_discovery.py`; `platform/test_power.py`;
  `testing/tests/test_third_party_notices.py`, `test_sources_fetch.py`, `test_release_workflow.py`,
  `test_fetch_tools.py`, `test_fake_ffmpeg.py`, the files of TTK-11, `test_testing_package.py`
  (deleted).
- Done when: the common items; `uv run pytest packages/reframe/tests/tools packages/reframe/tests/platform testing/tests`;
  the 0079 guards these files hold still fail on their mutations where the verdict names one
  (TTK-05: SF3/SF15).
- Estimate: 27 / 164.

#### Q-7.7 Speed (A)
- Findings: SPD-01, SPD-02, SPD-04 (POSIX launcher only), SPD-07 ([speed.md](speed.md)); TPM-01
  ([probe-metadata-languages](areas/probe-metadata-languages.md)); the fetch test server's shutdown
  poll (`serve_forever(poll_interval=0.05)`, the tools-platform verifier's note, measured in
  [speed.md](speed.md) "All levers together").
- Reference: [speed-levers.diff](speed-levers.diff) is the exact change the speed verifier
  measured at `38cf3eb` (373.3 / 374.4 s → 294.2 / 295.3 s, 6 workers, idle machine). Apply it
  (rebased on the earlier packages) rather than writing the levers again.
- Files: `pyproject.toml` (`"--dist", "worksteal"` in `addopts`), `languages/test_equivalence.py`
  (tag-major loop; the 88 s sweep split `[part::8]`, the search sweep `[part::4]`),
  `testing/reframe_testing/fake_tools.py` (the POSIX launcher imports `fake_ffmpeg`; the Windows
  `.cmd` launcher stays as it is until Q-7.13 checks it on the VM), `tools/fetch_server.py`,
  `tools/test_runner.py`; decision 0084 (an "Amended" note, as its earlier amendment: the
  scheduler is `worksteal`, and its advice to use `xdist_group` with `--dist loadgroup` no longer
  applies; `-n 0` and `--pdb` are unchanged).
- Order: the `test_equivalence.py` change (SPD-02 with TPM-01), then the fake launcher, the fetch
  server and the runner tests, then `addopts` last.
- Done when: the common items (the coverage comparison may show only timing lines); the full suite
  runs twice on an idle machine with every test passing, the count is the base's plus 10 (the
  split makes 12 ids of 2), and the wall time is near 295 s at the base of `38cf3eb` (state the base
  and both times in the commit message); `uv run pytest packages/reframe/tests/languages --collect-only -q`
  lists the parts `[0]`…`[7]` and `[0]`…`[3]`; `testing/tests/test_fake_ffmpeg.py` passes;
  `uv run mypy --platform win32`.
- Estimate: 0 tests removed (+10 ids), a few lines; full run −79 s on the owner's machine (−21 %).
  Windows: expected 1–2 minutes of the VM's 12 (not measured).

### Tier B

#### Q-7.8 Validation grids and cases (B)
- Findings: TVL-01, TVL-02, TVL-04, TVL-07, TVL-09, TVL-10, TVL-11, TVL-12
  ([validation](areas/validation.md)).
- Files: `validation/test_snap_notes.py`, `test_audio_agreement.py`, `test_rules.py`,
  `test_template.py`, `cases_options.py`, `test_option_values.py`, `test_default_tracks.py`,
  `test_dryrun_ffmpeg.py`, `test_custom_params_cqm.py`, `test_options_facade.py`, `test_dryrun.py`,
  `test_command_agreement.py`; `command/test_builder.py` (TVL-11); the definitions test that
  receives TVL-12's case.
- Order: TVL-02 first (the largest), then the rest.
- Done when: the common items; `uv run pytest packages/reframe/tests/validation packages/reframe/tests/command`;
  TVL-02: the five checks of the verdict are in `check_notes`, the `3.0` row is in the matrix, and
  the verdict's mutations (`$SCRATCH` script described in the verdict) fail the strengthened
  matrix: upmix note severity, unsupported-mixdown severity, Dolby Pro Logic II fallback,
  lossless-bitrate branch, snapped-bitrate severity, and the fix value `"stereo"` for `None`;
  TVL-01: the code comment names the two clean tests as the negative test of the codes;
  `test_every_plan_error_is_covered` passes (TVL-11).
- Estimate: 261 / 104.

#### Q-7.9 One validity test per built-in preset (B)
- Findings: TDM-01, TDM-03 ([definitions-models-presets](areas/definitions-models-presets.md)).
- Files: `presets/test_builtin.py`, `integration/test_builtin_presets_validate.py` (deleted),
  `batch/test_lint.py` (`test_builtin_presets_are_clean` goes), `definitions/test_options_values.py`,
  `definitions/test_tools.py`, a new shared module in `testing/reframe_testing/` (TDM-03).
- Order: TDM-01, then TDM-03.
- Done when: the common items; `uv run pytest packages/reframe/tests/presets packages/reframe/tests/definitions packages/reframe/tests/batch packages/reframe/tests/integration`;
  the verifier's five preset mutations (`fast-1080p30`: video speed preset, deinterlace tune, AAC
  bit rate, naming template, a shadowed codec rule) each fail the merged test, and with
  `subtests` a preset with three defects reports three failures; the `needs_ffmpeg` oracle tests
  of `test_tools.py` and `test_options_values.py` ran (not skipped).
- Estimate: 104 / 37.

#### Q-7.10 Server, CLI, naming and preview merges (B)
- Findings: TSV-03, TSV-04, TSV-05, TSV-06, TSV-07 ([server](areas/server.md)); TCL-02, TCL-05,
  TCL-06, TCL-07, TCL-08 ([cli-jobs-remote](areas/cli-jobs-remote.md)); TNP-04, TNP-05
  ([naming-preview-service](areas/naming-preview-service.md)).
- Files: `packages/reframe-server/tests/test_app.py`, `test_events.py`, `test_preview.py`,
  `test_settings.py`, `test_system.py`; `jobs/test_cli_encoders.py`, `test_cli_output_names.py`,
  `jobs/conftest.py`, `test_encode_real.py`, `test_cli.py`, `packages/reframe/tests/conftest.py`,
  `testing/reframe_testing/cli.py`; `preview/test_facade.py`, `test_service.py`,
  `test_service_nul_paths.py`; decisions 0040, 0041 (TCL-05 test name), 0047 (TSV-03 text),
  `docs/simplify/areas/queue-jobs.md:32`.
- Order: TCL-07 and TNP-05 first (both edit the root `conftest.py`), then the rest.
- Done when: the common items; `uv run pytest packages/reframe-server/tests packages/reframe/tests/jobs packages/reframe/tests/remote packages/reframe/tests/preview packages/reframe/tests/test_cli.py packages/reframe/tests/test_service.py packages/reframe/tests/test_service_nul_paths.py`;
  TSV-03's merged test starts a real task and fails with `hide=` removed from `app.py`;
  TCL-05's merged test fails with the RA-4 fix undone (`cli.py`, see the verdict).
- Estimate: 9 / 149.

#### Q-7.11 Batch, command and probe merges (B)
- Findings: TBT-05, TBT-06, TBT-07 ([batch](areas/batch.md)); TCD-07, TCD-08, TCD-10
  ([command-capabilities-dimensions](areas/command-capabilities-dimensions.md)); TPM-02, TPM-09,
  TPM-10, TPM-11, TPM-13, TPM-16 ([probe-metadata-languages](areas/probe-metadata-languages.md)).
- Files: `batch/test_anime_season.py`, `test_explain.py`, `test_lint.py`, `test_audio_rules.py`,
  `defaults_tracks.py`; `capabilities/test_issues.py`, `command/test_filtergraph.py`,
  `command/test_builder.py`, `command/test_metadata_edit.py`; `languages/test_equivalence.py`
  (TPM-02, after Q-7.7's split), `probe/test_sampling.py`, `test_sampling_media.py`,
  `test_matroska.py`, `test_languages.py`; decision 0082 "Built: L" (TPM-02).
- Done when: the common items; `uv run pytest packages/reframe/tests/batch packages/reframe/tests/capabilities packages/reframe/tests/command packages/reframe/tests/probe packages/reframe/tests/languages packages/reframe/tests/test_languages.py`;
  the anime-season snapshot is unchanged (TBT-05); TBT-06 has the verifier's 2-line fix; TPM-10
  and TPM-11 leave the R4-3 regression tests' inputs unchanged.
- Estimate: 13 / 113.

#### Q-7.12 Shared helpers in tools, platform and the testing package (B)
- Findings: TTP-06, TTP-07, TTP-08 ([tools-platform](areas/tools-platform.md)); TTK-06, TTK-13
  ([testing-package](areas/testing-package.md)).
- Files: `platform/test_sleep_dbus.py`, `test_diagnostics.py`, `tools/conftest.py` (new),
  `tools/test_fetch.py`, `test_fetch_cli.py`, `tools/fetch_server.py`, `tools/test_runner.py`,
  `tools/test_discovery.py`, `test_tasks.py`; `testing/reframe_testing/scripts.py` (new) and the 11
  files with a by-path script loader; `testing/tests/test_sources_fetch.py`.
- Order: TTK-13, TTP-08, then TTP-06, TTP-07, TTK-06.
- Done when: the common items; `uv run pytest packages/reframe/tests/tools packages/reframe/tests/platform packages/reframe/tests/test_diagnostics.py packages/reframe/tests/test_tasks.py testing/tests`;
  the two `fetch-tools.py` loads in one process pass (`-n 0`, the verdict's check); TTK-06's
  mutation (`sorted(top or below)` → `sorted(top)` in `scripts/sources-fetch.py`) fails the merged
  test.
- Estimate: 6 / 137.

#### Q-7.13 Speed (B)
- Findings: SPD-05, SPD-08 ([speed.md](speed.md)); the Windows half of SPD-04.
- Files: `pyproject.toml` and `uv.lock` (`pytest-timeout` as a dev dependency; `timeout = 600`,
  `timeout_method = "thread"`, `faulthandler_timeout = 590`, and a `filterwarnings` entry that
  ignores syrupy's `UserWarning` after a worker crash), `remote/test_shared_queue_real.py`
  (SPD-08: each generated source once per session), `testing/reframe_testing/fake_tools.py`
  (the Windows `.cmd` launcher with a one-line `-c` body); `CLAUDE.md` Commands (one line on the
  timeout) and decision 0084 (a note).
- Order: SPD-05, SPD-08, then the Windows launcher on the Windows test VM.
- Done when: the common items; a throwaway test that sleeps past a lowered timeout (for example
  `--timeout 5` on the command line) ends its worker, xdist starts a new one, the run goes on, the
  dump shows the hanging stack and the summary is printed (then delete the test); the Windows
  launcher: one fake call timed on the VM before and after, `testing/tests/test_fake_ffmpeg.py`
  and the full suite (`-m "not needs_gpu and not benchmark"`, `REFRAME_REQUIRE_FFMPEG=1`) pass on
  the VM; without the VM, the Windows launcher part stays open (nothing depends on it).
- Estimate: 0 tests; SPD-08 about 4–5 s wall on Linux; SPD-05 saves nothing but ends any hang
  after 10 minutes with a stack dump instead of blocking a run until the 30-minute CI job limit.

## File overlap and waves

Packages in one wave touch different files and can run in parallel worktrees (at most 3 agents
run tests at a time). A later wave starts when the earlier one is merged and the orchestrator's
full run passed.

| Package | Shared files that force the order | Must come after |
|---|---|---|
| Q-7.1 | `validation/cases_options.py`, `batch/` | none |
| Q-7.2 | `queue/` | none |
| Q-7.3 | `probe/`, `metadata/`, `test_languages.py` | none |
| Q-7.4 | `capabilities/`, `command/test_metadata_edit.py`, `definitions/`, `presets/test_builtin.py` | none |
| Q-7.5 | server tests, `jobs/test_cli_encoders.py`, `preview/` | none |
| Q-7.6 | `tools/test_fetch*.py`, `testing/tests/test_fake_ffmpeg.py` | none |
| Q-7.7 | `pyproject.toml`, `languages/test_equivalence.py`, `reframe_testing/fake_tools.py`, `testing/tests/test_fake_ffmpeg.py`, `tools/fetch_server.py`, `tools/test_runner.py` | Q-7.6 |
| Q-7.8 | `validation/`, `command/test_builder.py` | Q-7.1 |
| Q-7.10 | server tests, `jobs/`, root `conftest.py`, `preview/test_facade.py` | Q-7.5 |
| Q-7.12 | `tools/`, `testing/tests/`, `reframe_testing/` | Q-7.6, Q-7.7 |
| Q-7.11 | `batch/test_lint.py`, `command/test_builder.py`, `languages/test_equivalence.py`, `probe/` | Q-7.1, Q-7.3, Q-7.4, Q-7.7, Q-7.8 |
| Q-7.9 | `batch/test_lint.py`, `presets/test_builtin.py`, `definitions/` | Q-7.4, Q-7.11 |
| Q-7.13 | `pyproject.toml`, `uv.lock`, `reframe_testing/fake_tools.py`, `remote/test_shared_queue_real.py` | Q-7.7, Q-7.10, Q-7.12 |

| Wave | Packages (parallel) | Tier |
|---|---|---|
| 1 | Q-7.1, Q-7.2, Q-7.3 | A |
| 2 | Q-7.4, Q-7.5, Q-7.6 | A |
| 3 | Q-7.7 | A |
| 4 | Q-7.8, Q-7.10, Q-7.12 | B |
| 5 | Q-7.11, Q-7.13 | B |
| 6 | Q-7.9 | B |

The table comes from the findings' "Where", "Change" and "Guarantee kept by" bullets. Before a
wave is merged, compare the worktrees' `git diff --stat`; if two packages touched the same file,
merge them in step order and let the later one rebase.

## Brief template for an implementation agent

```text
You implement work package Q-7.<n> of Reframe's redundant-test plan, in the worktree you are in.
First run `git reset --hard <SHA of the last merge>` and check `git rev-parse HEAD` (agent
worktrees start from main). Read CLAUDE.md first.

Your package is in docs/test-audit/plan.md, section "Q-7.<n>". Its findings are: <IDs>. Each is
in docs/test-audit/areas/<area>.md (or docs/test-audit/speed.md). Read each finding in full,
including its "Verdict:" and "Orchestrator:" lines: an ADJUSTED verdict corrects the bullets above
it, and the Orchestrator line can add a condition.

Do not investigate again and do not look for more tests to trim. For each finding:
1. Find the tests by name (line numbers are from commit 38cf3eb and may have moved). Check that
   the code still matches "Now". If an earlier package changed it and the intent is no longer
   clear, skip the finding and say why in your final message.
2. Make the change in "Change", as the verdict corrects it. A merge keeps every input and every
   assertion of both tests and the name a document cites. Where the finding names a record or plan
   line that cites a removed test, change that line in the same commit.
3. Run the mutation or repeat checks the package's "Done when" names.
4. Follow the code-comments skill for comments and docstrings.

Then run the package's "Done when" and the common items of plan.md ("Rules for every package").
The coverage comparison runs the full suite twice: run it only if you are told you are the only
test-running agent; otherwise say in your final message that it is left to the orchestrator.
Mark the step done in docs/status.md (row Q-7.<n>) with a one-line note: tests and code lines
removed.

Commit once: `test(Q-7.<n>): <what>` with the attribution line. Do not push.

Reply with: the findings made, the findings skipped and why, the tests and code lines removed,
and the result of each Done-when command.
```
