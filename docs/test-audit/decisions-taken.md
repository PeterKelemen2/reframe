# Redundant-test audit: decisions taken in place of the owner

The audit ran unattended on 2026-11-17. The owner answered a few questions during the run (see
D-12, D-13); every other choice below was made by the orchestrator, using the brief's order:
(1) no guarantee lost, (2) the plan, the decision records and `CLAUDE.md`, (3) CI on Ubuntu and
Windows keeps working, (4) more test code removed, (5) less risk, (6) when in doubt, keep the
test. Each entry says what changes if the owner chooses otherwise.

## How the audit was run

### D-1 Eleven areas, not 8–10

The brief asked for 8–10 areas of about equal size. With the folder boundaries, 11 areas of
4.7k–7.9k test code lines came out more even than 10 (one area would have been 11k lines). The
`testing/tests/` folder (release and packaging scripts, test infrastructure) is its own area
because its code (`scripts/`, `reframe_testing`) is not in the coverage map.
If the owner wants fewer areas next time: join `naming-preview-service` with
`definitions-models-presets`.

### D-2 The area auditors ran no tests; the verifiers ran them through a gate

The brief allowed "at most 3 test-running agents at once". The area auditors read code, the
coverage map and the history only, so all 11 ran at the same time without a worktree. The 12
verifiers ran in worktrees and could all read at the same time, but every test run went through
`scratchpad/tools/runtests.sh`, which holds one of 3 machine-wide `flock` slots (2 while the speed
agent was still measuring) and runs pytest with 4 xdist workers. So at most 3 test runs were on
the 12 logical cores at a time, but up to 9 agents existed at once.
If the owner wants "agents", not "test runs", limited: run the verifiers in waves of 3; the
results do not change, the wall time of the audit triples.

### D-3 Coverage: two runs, two recipes

- The per-test map (which tests run the same lines) needs pytest-cov contexts. They do not work
  with coverage's default `sysmon` core on Python 3.14 ("dynamic contexts aren't supported"), and
  `filterwarnings = ["error"]` turns that warning into a setup error in every test. The run used
  `COVERAGE_CORE=ctrace` and `-W ignore::coverage.exceptions.CoverageWarning`. Import-time lines
  are missing from it (the `reframe_testing` plugin imports the package before pytest-cov starts),
  and code run in a subprocess is not in it. It was used only to show where to look.
- The whole-run coverage that the work packages compare against uses `coverage run` with
  `patch = ["subprocess"]` (coverage 7.16): the xdist workers and every Python subprocess (the CLI,
  the server, the fake tools) are measured from their start, so import-time lines are covered.
  Result at `38cf3eb`: 98 % of 30,622 statements, 96 % of 9,226 branches, in 6 min 49 s with
  xdist. The recipe is in [plan.md](plan.md) "Coverage comparison".

### D-4 The coverage run hung once; the fork was killed

The first per-test coverage run stopped at 96 % for an hour:
`tests/batch/test_batch_service.py::test_a_season_from_grouping_to_the_queue_and_its_preset_on_season_2`
had forked a child for an ffprobe run, and the child stayed in `futex_wait` between `fork` and
`exec` while holding the pipes the worker read. Killing the child let the run finish with the
baseline's result. Not a product bug in the normal run (5 full runs that day had no hang), but
the runner's `preexec_fn` makes it possible in a threaded process (speed finding SPD-05/SPD-06),
and the suite has no per-test timeout, so a hang blocks a run for good. This is why SPD-05 (a
per-test timeout) is planned.

### D-5 The earlier test trim was found during the run

`docs/test-trim-reports/` (the test trim of 2026-10-17, 907 tests removed, merged in `5dbf152`)
was not in the brief. One auditor found it; the orchestrator then told every running agent to read
the reports of its area and to treat a test a report keeps or names as a guard like one a decision
record names. The server and tools-platform auditors had already finished; their verifiers
checked every finding against the reports instead (`T.md` for tools-platform). The two briefs in
the scratchpad were updated for the later agents.
If the owner sees a finding that goes against a recorded keep without a reason: it is a mistake;
the finding's verdict should say why the keep's reason no longer holds.

### D-6 The validation verifier's worktree was removed while it waited on background work

Its report had been delivered in full; the worktree had no change. Nothing depends on it.

## Tier rules

### D-7 What makes Tier A

Tier A: CONFIRMED or ADJUSTED in verify, no guarantee lost, low risk, no edit of a decision
record or plan text, and inside one area. Tier B: a merge or rewrite with some risk (timing, a
moved assertion), a change that needs a decision-record or plan-text edit, a change across areas,
a shared helper, or a CI or dev-dependency change. Tier C: rejected in verify, or a guard named
by a record or "Done when" that the rules keep.
If the owner wants a smaller Tier A: move the merges (not the deletions) to B.

### D-8 TTP-02 goes to Tier C (verifier: Tier B)

The core facade fetch test is the only caller of `ToolsService.fetch(manifest=...)`. Deleting it
leaves that input untested; deleting the parameter too is a product change, which this step does
not make. Listed in [README.md](README.md) "What is missing or weak" for a later simplification.
If the owner wants it gone: remove `manifest=` from `ToolsService.fetch` and the test in one
commit (−1 test, −33 lines, and the parameter).

### D-9 TSV-03 keeps a real task in the merged test

The verifier found that the merge, as written, loses the only server test in which a task started
by the real `TaskManager` reaches a WebSocket client (50 lines of `tasks.py` only it runs). The
package must start one real task in the merged test instead of publishing the event by hand. This
costs about 3 of the 17 lines saved.

### D-10 TDM-01 uses `subtests`

The five per-preset checks become one parametrized test (−104 tests). The verifier showed every
defect still fails the merged test, but a run then reports only the first failed check of a
preset. The package uses pytest's built-in `subtests` fixture (pytest 9.1) so that each check
still reports on its own; if `subtests` misbehaves under xdist (on Windows CI too), the five
checks stay as five asserts and the first-failure message is accepted.
If the owner prefers clear failures over fewer test ids: keep the five tests (Tier C) and only add
the `defaults.*` clause to the integration test and delete the batch duplicate (−26 tests).

### D-11 TVL-01 reads "every rule has a negative test" per rule, not per case

`05-core.md:436` says every **rule** has a positive and a negative test, and 0014 item 3 and
`docs/status.md` say the same per code. The 16 removed `test_negative` cases all run the clean
job or template, which `test_clean_job_has_no_issues` / `test_clean_template_has_no_issues`
already check without any issue. Tier B, with a code comment that names those two tests as the
negative test of these codes.
If the owner reads the wording as "one negative case per code in the table": drop TVL-01
(+16 tests back, 0 lines).

### D-12 Model choice for the implementation (owner's question during the run)

The owner asked whether Haiku agents are enough for the changes. [plan.md](plan.md) recommends
Opus for every package (each holds at least one merge) and allows Haiku only for 17 listed
single findings (plain deletions with a named keeper, row trims, verified helper moves), split out
of their package, with one Opus review of each wave's diff. Reason: the whole trim saves about
1,000 lines; a silently weakened guard costs more than the tokens, and the verifiers rejected or
corrected about one finding in four.
If the owner wants to save more: run the Tier A packages with Sonnet and keep Opus for the Tier B
packages and the reviews.

### D-13 No code changes in this run (owner's question during the run)

Confirmed to the owner: the audit changes no product code and no tests; the agents' trial
edits stayed in their worktrees and were undone.

## Disagreements and corrections settled by the orchestrator

### D-14 TVL-11: which of the two refusal tests stays

The validation auditor proposed deleting `command/test_builder.py::test_refusals` in favour of
`validation/test_command_agreement.py::test_plan_errors_are_validation_errors`; the command
verifier agreed (the agreement rows also check the validation code, and
`test_every_plan_error_is_covered` keeps a row per `raise PlanError`), with a tightened match for
the WebM passthrough row. The validation verifier found that 3 of the 10 jobs differ in details
that do not change the error. Settled: delete `test_refusals`, tighten the match, package Q-7.8.

### D-15 TCL-05: a test name in two accepted records

The RA-4 test that TCL-05 merges is named in 0040:494 and 0041:214. `docs/decisions/README.md`
says "do not edit an accepted record to change its decision"; replacing a test name changes no
decision, and `a139d30` did the same for renamed tests. Settled: the keeper keeps its name, and
the two lines get the keeper's name in the same commit.

### D-16 TPM-02: the `slow` marker is never deselected

Nothing (CI, `scripts/`, `CLAUDE.md`, the plan) runs `-m "not slow"`, and 0082 says CI runs both,
so a fast test that is a strict input subset of a slow sweep repeats work in every run. The
verifier corrected the subset claim (region `172` and script `Kawi` are not in the registry), so
the sample test keeps those tags.
If the owner wants a fast local loop with `-m "not slow"` later: keep the two deleted fast tests
(+2 tests, +4 lines).

### D-17 Speed levers that touch shared files go in their own packages

SPD-01 (`addopts`), SPD-02 and TPM-01 (both `test_equivalence.py`), SPD-04 (`fake_tools.py`) and
the fetch server's poll interval change shared files that several area packages also touch, so
they are packages of their own (Q-7.7 and Q-7.13), after the area packages of their wave.

### D-18 Q-7 does not block the release

Q-6's Tier A steps were made a release-checklist item (0083) because they change shipped code.
Q-7 changes only tests and test configuration: nothing a user gets changes. So the record adds Q-7
to M10 without a release-checklist item; the Tier A steps are recommended before v1 because
they make every later run shorter and every later test change smaller, but they can come after.
If the owner wants Q-7 before v1: add "The Tier A steps of `Q-7` are done" to the release
checklist in `08-roadmap.md`.

### D-19 The step is called "test trimming" and uses the ID Q-7

`Q-7` was free in `09-quality-and-release.md`. The earlier trim (2026-10-17) had no step ID; its
reports stay where they are.

## Close calls

- **TSV-07** (the server's "unknown settings field" diagnostics test, a privacy guard): Tier B,
  not C. The verifier confirmed the core test's input is a superset for the report's filter; the
  server test's only own part is its test data.
- **TNP-04** (the core facade clip test, covered by the server's clip-route tests): Tier B. A run
  of only the core package loses one line (`JobService.preview_clip`); CI always runs both
  packages.
- **TCD-03** moved from B to A in verify: the trim report R mutation it was named for is caught by
  the capture-replay tests.
- **TVL-13, TTK-02, TTK-08, TPM-17, TCD-06**: truly redundant or nearly so, but named by a decision
  record (0014, 0079, 0080, 0008) as guards, so Tier C. A record edit could release them; not
  worth a record change for 1–7 tests each.

## Implementation (Q-7)

The packages are made by agents in the waves of [plan.md](plan.md), merged into the branch
`q7-trim` (from `m10-hardening` at `1819150`) and merged into `m10-hardening` at the end. The
choices in D-1 to D-19 stay as written.

### D-20 Sonnet and Haiku agents in place of Opus (owner's choice)

The owner chose Sonnet for the implementation agents and Haiku for the clean removals, in place of
[plan.md](plan.md) "Which model" (Opus for every package; D-12). Haiku (effort medium) makes only
the 17 findings that "Which model" lists as plain deletions, row trims or verified helper moves,
as the first commit of their package; a Sonnet agent then makes the rest of the package on top of
that commit (effort high, xhigh for Q-7.2, Q-7.8 and Q-7.9). One Sonnet review (effort xhigh) reads
each package's diff before its wave is merged. Test runs go through a gate that allows 3 runs at
a time with 4 xdist workers each (as D-2).

### D-21 Test names in the Q-6 area files follow a deleted test

The Q-6 area files (`docs/simplify/areas/`) name tests as guards. Where a Q-7 package deletes or
merges such a test, the line names the keeper, also when the finding does not ask for the edit
(TVL-05 in `validation.md`, TPM-05 in `probe-metadata.md`). A trim report of 2026-10-17
(`docs/test-trim-reports/`) changes only where a finding names the line (R.md for TCD-01 and
TCD-03, T.md for TTP-05), as plan.md's rules say; where the line tells what that trim did, the
old name stays and a note names the keeper (T.md line 28). V2's line on TVL-05's test stays: the
finding does not name it, and it already says the test may be deleted.

### D-22 A merge keeps an assertion that another test also makes

TCL-01's verdict says the exit code of the deleted `test_no_nvidia_driver` is also checked by
`test_first_run_checks_then_lists_every_encoder`. The package carried `assert result.exit_code ==
EXIT_OK` into the keeper anyway; the review flagged it as a change no finding names. Kept: the
plan's rule is that a merge keeps every assertion, and the line only makes the keeper stricter.

### D-23 A trim-report line that names a removed test gets a note even when no finding names it

`docs/test-trim-reports/N.md` names `test_property_normalize_variants_of_an_entry` as a keep; TPM-16
(Q-7.11) replaced it, and its "Docs and history" says "none". The line gets the D-21 kind of note
(the old name stays, the note names the keeper), so that no document names a test that no longer
exists without saying where it went.

### D-24 SPD-08: the sources are cached, the CLI polls stay

SPD-08's change has two halves: generate each source once into the fixture cache, and poll the
owner's HTTP API instead of the CLI where the CLI's output is not what the test checks. The finding
itself says the poll change "touches what the test exercises", and plan.md's Q-7.13 text names only
the sources. By the order "less risk; when in doubt keep the test", Q-7.13 caches the sources
(`reframe_testing.media` recipes in `testdata/media/queue-sources/`, built with `-y -nostdin` into
a temporary folder) and leaves the CLI polls as they are.
If the owner wants the polls changed: a later package swaps `Home.state` for an HTTP read where the
test checks no CLI output (about 0.77 s per poll on Linux, more on Windows).
