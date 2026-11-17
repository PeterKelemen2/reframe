# Area queue-analysis: `packages/reframe/tests/queue/`, `packages/reframe/tests/analysis/`, `packages/reframe/tests/test_tasks.py`, `test_mediatask.py`, `test_events.py`

Baseline: 28 files, 402 tests, 7,325 test code lines, 81 s of test time.

All paths and line numbers refer to commit `38cf3eb` of `/home/peti/Programming/reframe-test-audit`.
Test paths below are relative to `packages/reframe/tests/`.

## Summary

9 findings, all Tier A: 7 tests and about 87 code lines removed, about 1.4 s of test time.
There are no Tier B findings, so Tier A+B is the same: 9 findings, 7 tests, about 87 lines.
Two candidates went against a recorded keep or guard of the earlier test trim, so they were
moved to "Looked at and kept" (see the end of that section).

Trim reports read: `docs/test-trim-reports/Q.md` (CLI, facade, settings, events, tasks, jobs,
queue) and `R.md` (capabilities, preview, analysis), both in full. `M.md`, `N.md` and `T.md` were
searched for this area's files and have nothing about them. The rest (B, C, P, V1, V2) cover
other folders.

This area was trimmed before: by Q-6 (QJ-01, QJ-04, QJ-08, NDP-05) and by the earlier test trim
(`Q.md`, `R.md`). Most of what is left is fault injection, regression (R4-x, RB-x, C-17 fixes)
or real-tool tests, and those stay. The remaining slack is mostly in `queue/test_when_done.py`
and `queue/test_queue.py`. These two files were written one day apart (C-11, `a1b362a` and
`777607f`), and several when-done tests repeat a `test_queue.py` test with the same setup.

Best three:
- TQA-01: merge `test_queue.py::test_cancel_all_cancels_waiting_jobs_too` and `test_when_done.py::test_cancel_all_runs_no_action` (same setup, both sets of assertions in one test).
- TQA-02: merge `test_queue.py::test_stop_takes_no_new_jobs` into `test_when_done.py::test_no_action_when_stopped_with_jobs_left` (the same stop-with-jobs-left run; the when-done branch does not depend on the action).
- TQA-03: delete `test_when_done.py::test_close_during_a_countdown`. Three other tests already check that close cancels the queue's countdown, and one of them checks it by id.

## Findings

### TQA-01 Cancel-all is tested twice with the same setup
- Kind: near-copy
- Where: `queue/test_queue.py::test_cancel_all_cancels_waiting_jobs_too` (317), `queue/test_when_done.py::test_cancel_all_runs_no_action` (366)
- Now: Both set `parallel_jobs = 2`, use the `LONG` hanging encode, add 3 jobs, start, wait until two of them run, then call `cancel()` with no id. `test_queue` asserts: every job is cancelled, the `.part` files are gone, no leftovers, the waiting job goes `waiting → cancelled`, no `notification` event, and a cancel of an ended job does nothing. `test_when_done` sets `when_done = "shutdown"` with the `FakePower` fixture and asserts: every job is cancelled, `power.scheduled == []`, no notification.
- Change: merge into `queue/test_when_done.py::test_cancel_all_runs_no_action`. Use the body of the `test_queue` test (its `position=2` add, its waits for the first progress and for the two `.part` files, and all its assertions). Add `h.settings.queue.when_done = "shutdown"` and `assert power.scheduled == []`. Delete the `test_queue` test.
- Saved: 1 test, about 11 code lines (19 + 13 become about 21), about 0.3 s
- Guarantee kept by: the merged `test_when_done.py::test_cancel_all_runs_no_action`. It has the union of the inputs (3 jobs, 2 slots, one added at `position=2`, when-done `shutdown`) and the union of the assertions.
- Why nothing is lost: The inputs differ only in the add position (kept) and the when-done setting (`shutdown` is kept; `test_queue` used the default `nothing`, which `emptied()` returns on at the same `last not in _ENDED_ON_ITS_OWN` check, `queue/whendone.py:123`). The coverage map shows that the `test_when_done` lines are a subset of the `test_queue` lines (3395 ⊂ 3414); the 19 extra lines come from the `test_queue` waits, which are kept.
- Docs and history: `grep docs/` finds neither name. `test_cancel_all_cancels_waiting_jobs_too` was added in `a1b362a` (C-11 feature), `test_cancel_all_runs_no_action` in `777607f` (C-11 when-done feature). Neither commit is a bug fix.
- Risk: low. Both tests run the same harness. The merged test still waits for the same events.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — The merged test reaches the same state at the same moment as both originals: two jobs with live processes (progress seen and both `.part` files written, which is a later point than `running_process`), one waiting, then `cancel()`. All assertions of both tests are kept; `power.scheduled == []` is now checked on the full 3-job/position=2 input. Mutation check: with the `last not in _ENDED_ON_ITS_OWN` clause removed from `WhenDoneActions.emptied`, the merged test fails, and the deleted `test_queue` version passes (with when-done `nothing` it cannot see this bug), so the merge keeps the strong side. Measured: 1 test, 11 code lines (as stated), about 0.14 s.
Checked: apply in worktree, `$SCRATCH/tools/runtests.sh packages/reframe/tests/queue -q` → 270 passed (all 9 applied, queue folder 277 → 270); `test_when_done.py test_queue.py` 5 times → 62 passed ×5 (load: 1–2 other pytest runs); `-k cancel_all_runs_no_action or no_action_when_stopped or new_work_cancels` 5 times → 4 passed ×5; mutant (`emptied` without the cancelled-last check) → merged test FAILED, `test_cancel_all_cancels_waiting_jobs_too` passed.

Orchestrator: Tier A, package Q-7.2.

### TQA-02 Stop with jobs left: `test_stop_takes_no_new_jobs` repeats the when-done stop test
- Kind: near-copy
- Where: `queue/test_queue.py::test_stop_takes_no_new_jobs` (380), `queue/test_when_done.py::test_no_action_when_stopped_with_jobs_left` (328)
- Now: Both use the same scenario (`progress(blocks=3, interval=0.05)`, `write_output`) and the same steps: add A and B, start, wait until A runs, `stop()`, wait for A, then assert that B is `waiting`. `test_queue` (when-done `notify`) also asserts `not _processing` right after the stop, sleeps 0.1 s before the B check, asserts no queue notification, and asserts that A's own notification is `success`. `test_when_done` (when-done `shutdown`) asserts that nothing is scheduled. Then it starts again and asserts that the batch's countdown names "2 jobs done".
- Change: merge into `test_when_done.py::test_no_action_when_stopped_with_jobs_left`. Add `assert not h.queue._processing` after `stop()`. Add `await asyncio.sleep(0.1)` before the B check, because it gives a wrongly taken job time to run. Add `assert [(n.job_id, n.level) for n in notifications(h, job=True)] == [(first.id, "success")]`. Delete the `test_queue` test.
- Saved: 1 test, about 12 code lines (15 deleted, 3 added), about 0.25 s
- Guarantee kept by: the merged test. It keeps the same input, plus the restart part.
- Why nothing is lost: The "queue did not empty" branch returns in `QueueService._when_done` (`queue/service.py:938-939`, `elif not drained and any(... WAITING ...): return`) before `emptied()` reads the action. So `notify` and `shutdown` take the same path, and "nothing scheduled" with `shutdown` is the same check as "no queue notification" with `notify`. The other `test_queue` assertions (`_processing`, the 0.1 s settle, the job's own notification) move over unchanged. Coverage: the `test_queue` lines are a subset of the `test_when_done` lines (3486 ⊂ 3504).
- Docs and history: `grep docs/` finds neither name. Added in `a1b362a` and `777607f` (C-11 features, not fixes).
- Risk: low. Keep the 0.1 s sleep, or the check of B loses its strength.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Same scenario, same steps; the moved assertions sit at the same points (`_processing` right after `stop()`, the 0.1 s settle after `wait([first])`, job notification before the restart). The deleted test's `queue_notifications == []` was in fact weaker than `power.scheduled == []`: with `notify` and one done job that already notified, `emptied()` returns silently (`whendone.py:127-128`), so it could not see a wrong when-done run. Mutation check: with the `return  # stopped with jobs left` in `QueueService._when_done` made a no-op, the merged test fails and `test_stop_takes_no_new_jobs` passes. Measured: 1 test, 11 code lines (not 12: `test_when_done.py` needs `import asyncio` for the sleep), about 0.3 s minus the added 0.1 s sleep.
Checked: same runs as TQA-01 (5× file pair → 62 passed ×5; 5× -k selection → 4 passed ×5); merged test 0.60 s; mutant (`_when_done` stop branch) → merged test FAILED, `test_stop_takes_no_new_jobs` passed.

Orchestrator: Tier A, package Q-7.2.

### TQA-03 `test_close_during_a_countdown` is covered by three other close-cancels-the-countdown tests
- Kind: near-copy
- Where: `queue/test_when_done.py::test_close_during_a_countdown` (249)
- Now: One job runs, when-done `shutdown` starts `countdown-1`, and `queue.close()` is called. The test asserts `cancel_calls == ["countdown-1"]`, no countdown pending, `run_out() is None`, nothing executed, and the fake's started/cancelled events.
- Change: delete
- Saved: 1 test, 11 code lines, about 0.2 s
- Guarantee kept by: `queue/test_when_done.py::test_the_user_cancels_the_countdown` (228). After the second batch, `queue.close()` cancels the pending `countdown-2` by its id: `cancel_calls == [None, "countdown-1", "countdown-2"]`, `cancelled == ["countdown-1", "countdown-2"]`, and `executed == []`. Also `::test_with_the_power_service_new_work_and_close_cancel` (607), where the real `PowerService` publishes a `cancelled` event for the countdown that the close cancels and `executor.actions == []`. Also `::test_a_power_service_that_cannot_cancel_breaks_nothing` (424), where close calls `cancel("countdown-2")`.
- Why nothing is lost: The input "close while the queue's countdown is pending" is in all three tests. The action (`shutdown` vs `sleep`) does not matter for the cancel at close. "Nothing pending afterwards" follows from `cancelled` holding the id, because `FakePower._end` clears `_pending`. The started/cancelled event pair comes from the fake itself, not from the queue. Coverage: subset of `test_the_user_cancels_the_countdown` (3482 ⊂ 3486).
- Docs and history: `grep docs/` finds nothing. Added in `777607f` (C-11 when-done feature).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Close goes through one path (`WhenDoneActions.close` → `_cancel_countdown`, cancel by the stored id). `test_the_user_cancels_the_countdown` pins it exactly: its `cancel_calls` list ends with exactly one close call by id (`countdown-2`), `cancelled` holds it (so pending is cleared and `run_out()` would be `None`), `executed == []`. The started/cancelled event pair is the fake's own. The name prefix `test_close_during_a_countdown` also matches `platform/test_power.py::test_close_during_a_countdown_cancels_and_never_executes` (PowerService's own close; not touched). Mutation check: `close()` made a no-op is killed by `test_the_user_cancels_the_countdown`, `test_a_power_service_that_cannot_cancel_breaks_nothing` and `test_with_the_power_service_new_work_and_close_cancel` with the test deleted. Measured: 1 test, 11 code lines, about 0.12 s.
Checked: `$SCRATCH/tools/runtests.sh packages/reframe/tests/queue/test_when_done.py test_faults.py test_store.py -q` with the merges applied and three mutants → 5 expected failures (3 of them for the close mutant), 71 passed.

Orchestrator: Tier A, package Q-7.2.

### TQA-04 `test_the_action_runs_when_the_last_job_failed` is the first half of `test_new_work_cancels_the_countdown[retry]`
- Kind: near-copy
- Where: `queue/test_when_done.py::test_the_action_runs_when_the_last_job_failed` (218), `queue/test_when_done.py::test_new_work_cancels_the_countdown` (263)
- Now: `test_the_action_runs_when_the_last_job_failed` sets when-done `shutdown`, uses the `BAD` scenario, runs one job "Bad", and asserts `power.scheduled == [("countdown-1", "shutdown", "0 jobs done, 1 failed")]`. The `[retry]` case of `test_new_work_cancels_the_countdown` makes exactly the same run first (`shutdown`, `BAD`, `run_one(h.job("Bad"))`, `power.pending is not None`). It then asserts `[(s[0], s[2]) for s in power.scheduled] == [("countdown-1", "0 jobs done, 1 failed"), ...]`, that is, the id and the reason but not the action.
- Change: delete `test_the_action_runs_when_the_last_job_failed`. In `test_new_work_cancels_the_countdown`, compare the whole tuples: `power.scheduled == [("countdown-1", "shutdown", <reason>), ("countdown-2", "shutdown", "1 job done")]`.
- Saved: 1 test, about 7 code lines, about 0.2 s
- Guarantee kept by: `test_new_work_cancels_the_countdown[retry]`, which has the same input and, after the change, the same assertion on `countdown-1`.
- Why nothing is lost: The setting, the scenario and the job name are the same, and the run's assertions match. Coverage: subset (3302 ⊂ 3544).
- Docs and history: `grep docs/` finds nothing. Added in `777607f` (C-11 feature). The rule ("a failed job does not need the computer to stay on") is written in the module docstring of `reframe/queue/whendone.py`.
- Risk: low. The `[retry]` case must stay. A later trim of that parametrization must keep `retry`.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `[retry]` runs the identical first half (`shutdown`, `BAD`, `run_one(h.job("Bad"))`), and with whole-tuple comparison it asserts the same `("countdown-1", "shutdown", "0 jobs done, 1 failed")`; `scheduled` is append-only, so checking it at the end of the test sees the same first entry. The deleted test's `ended.state is FAILED` is implied by the reason text. Both `[add]` and `[retry]` pass with the full tuples. `[retry]` must stay (as the auditor says). Measured: 1 test, 7 code lines, about 0.07 s.
Checked: 5× `-k ... new_work_cancels` (both cases) → passed ×5; full queue folder → 270 passed.

Orchestrator: Tier A, package Q-7.2.

### TQA-05 The renamed-output notification is a one-line addition to `test_collision_auto_rename`
- Kind: near-copy
- Where: `queue/test_when_done.py::test_a_renamed_output_is_named_in_the_notification` (499), `queue/test_faults.py::test_collision_auto_rename` (370)
- Now: The when-done test writes `out/Movie.mkv`, runs one job (`auto_rename`, the default), and asserts `output_path == "Movie (1).mkv"` and that the job's notification says "Movie (1).mkv". `test_collision_auto_rename` writes `Movie.mkv` and `Movie (1).mkv`, runs one job, and asserts `Movie (2).mkv`, the user's file untouched, the `output.renamed` issue and the log line. It checks no notification.
- Change: merge. Add `[note] = h.of_type("notification")` and `assert note.message == "Movie (2).mkv"` to `test_collision_auto_rename`, then delete the when-done test. The harness has job notifications on and when-done `nothing` by default, so that is the only notification.
- Saved: 1 test, about 7 code lines, about 0.2 s
- Guarantee kept by: `queue/test_faults.py::test_collision_auto_rename`, whose input (the final name taken, so the job is renamed) is a superset.
- Why nothing is lost: In both inputs the notification text comes from `outcome.output_path` (`WhenDoneActions.job_ended(output=...)`). Two taken names instead of one only changes the number. The `power` fixture of the deleted test plays no part (when-done `nothing`). Coverage: subset (3490 ⊂ 3494).
- Docs and history: `grep docs/` finds nothing. Added in `777607f` (C-11 feature, not a fix).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — In the harness the only notification of `test_collision_auto_rename` is the job's (when-done `nothing`, notifications on); the added `[note] = h.of_type("notification")` / `"Movie (2).mkv"` passes (needs `# type: ignore[union-attr]` on `note.message`, mypy clean). Mutation check: `job_ended` using `job.settings.output.path` instead of `output` is killed only by the renamed-output assertion (`test_job_notifications` uses an unrenamed output), so the moved assertion is load-bearing and must land in `test_collision_auto_rename`. Q.md keeps `test_faults.py` whole; this only adds to it. Measured: 1 test, 7 code lines, about 0.12 s.
Checked: mutant (`path = job.settings.output.path or output`) with the merge applied → `test_faults.py::test_collision_auto_rename` FAILED.

Orchestrator: Tier A, package Q-7.2.

### TQA-06 "An encode of a file that is edited in place is not claimed" is one assertion of the scheduling test
- Kind: near-copy
- Where: `queue/test_output_claims.py::test_an_encode_of_a_file_that_is_edited_in_place_is_not_claimed` (104), `queue/test_in_place_scheduling.py::test_an_encode_waits_for_an_in_place_edit_of_its_source` (89)
- Now: The claims test adds `in_place_job(h)`, then `h.job("Encode")`, and asserts that the encode is `waiting`. The scheduling test adds the same two jobs in the same order, starts the queue, and asserts that the edit ended before the encode started. That fails with `StopIteration` if the encode was added `failed`, but it does not say why.
- Change: merge. Add `assert encode.state is JobState.WAITING, encode.issues` after the second `add` in `test_an_encode_waits_for_an_in_place_edit_of_its_source`, then delete the claims test.
- Saved: 1 test, about 6 code lines, about 0.1 s
- Guarantee kept by: `queue/test_in_place_scheduling.py::test_an_encode_waits_for_an_in_place_edit_of_its_source`, with the same input and the same assertion after the change. The hard-link variant `queue/test_job_keys.py::test_an_encode_of_a_hard_link_waits_for_the_in_place_edit` (163) already asserts it this way.
- Why nothing is lost: same jobs, same order, same state check. Coverage: subset (2357 ⊂ 3707).
- Docs and history: `grep docs/` finds nothing. Added in `38f76cd` (C-17 output-claims feature).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Same two jobs added in the same order; the new assertion runs at add time, before `start()`, which is the same moment as in the claims test. `parallel_jobs = 2` and the scenario are set before the adds but play no part in the add-time claim check. Neither test is named in docs (decisions 0061/0064 name other tests of `test_output_claims.py`). Measured: 1 test, 6 code lines, about 0.01 s.
Checked: queue folder with all merges → 270 passed.

Orchestrator: Tier A, package Q-7.2.

### TQA-07 `test_plan_json_round_trip` is a second store round trip with one more field
- Kind: near-copy
- Where: `queue/test_store.py::test_plan_json_round_trip` (198), `queue/test_store.py::test_round_trip_keeps_unknown_fields` (60)
- Now: Both open a store, `upsert` a job, close it, open it again, `load`, and compare. The plan test sets only `plan=EncodePlan(...)`. The round-trip test sets state, issues, times, output and log paths, error and unknown fields, then asserts `restored.model_dump() == first.model_dump()`.
- Change: merge. Build the `EncodePlan` in `test_round_trip_keeps_unknown_fields` and pass `plan=plan` to `first`. The existing whole-model comparison then also checks the plan. Delete `test_plan_json_round_trip`.
- Saved: 1 test, about 7 code lines (16 deleted, about 9 added), under 0.1 s
- Guarantee kept by: `queue/test_store.py::test_round_trip_keeps_unknown_fields`, which compares the whole job after the change.
- Why nothing is lost: The plan test's only lines of its own are `store.py:165, 217-218` (writing and reading a non-null `plan_json`), and the merged job reaches them. Equality of the plan is part of the `model_dump()` comparison.
- Docs and history: `grep docs/` finds neither name. Both were added in `a1b362a` (C-11).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — The store keeps a non-null plan on a `FAILED` row (the merged test passes), and `restored.model_dump() == first.model_dump()` compares the plan. Mutation check: `row_of` writing `plan_json = NULL` always is killed by the merged `test_round_trip_keeps_unknown_fields`. Measured: 1 test, 7 code lines (the file also loses its two trailing blank lines, which `ruff format` wants removed), under 0.01 s.
Checked: mutant (`row_of` with `if True` for the plan) → `test_store.py::test_round_trip_keeps_unknown_fields` FAILED.

Orchestrator: Tier A, package Q-7.2.

### TQA-08 Two hand-copied test helpers that a shared one already does
- Kind: shared-setup
- Where: `queue/test_store_nesting.py` `queue_at` (289-301) and its `QueueService` import (27); `queue/test_job_keys.py::test_busy_while_a_restored_job_waits_for_its_keys` (292), lines 305-319.
- Now: (a) `test_store_nesting.py` has its own `queue_at(h)`. It is `conftest.queue_at(h)` without the `stall_after=None, watchdog_tick=0.05, log_interval=0.02` test settings. Its only user, `test_the_queue_starts_with_a_deep_row_and_keeps_a_deep_job`, only lists and closes the queue, so those settings do not matter. (b) `test_busy_while_a_restored_job_waits_for_its_keys` patches `os.stat` and `os.lstat` by hand so that a path under the share waits for an `Event` off the loop thread. That is exactly `test_output_claims.hold_share(monkeypatch, share)`, which also records the blocked threads.
- Change: (a) import `queue_at` from `.conftest` and delete the local copy and the `QueueService` import. (b) In the test, write `held = hold_share(monkeypatch, share)` (import it from `.test_output_claims`, as the file already imports from `.test_in_place_scheduling`) and change `answer.set()` to `held.answer.set()`.
- Saved: 0 tests, about 22 code lines (12 + 10)
- Guarantee kept by: the same tests, with the same behaviour under test.
- Why nothing is lost: (a) the extra options only change the watchdog and the log rate of running jobs, and this test runs none. (b) Both helpers block `stat`/`lstat` of paths under the share only in worker threads, until the event is set.
- Docs and history: `queue_at` in `test_store_nesting.py` comes from `524af77` (C-3/C-11 nesting) and was moved in `b595257`. `hold_share` comes from `aaa2422` (C-17 fix "output claims never wait on the share of another job"). The busy test comes from `3b1da22` (S-7). No test is removed.
- Risk: low. `test_job_keys.py` holds the known load-sensitive test (`test_choosing_a_job_never_reads_a_slow_share_on_the_event_loop`), but this change does not touch it or `slow_share`.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — (a) the nesting test only lists and closes the second queue, so `stall_after`/`watchdog_tick`/`log_interval` do not matter. (b) `hold_share` blocks the same calls (`os.stat`/`os.lstat`, paths under the share, worker threads only, 10 s wait) and captures the loop thread at call time, as the hand copy did; both `answer.set()` calls become `held.answer.set()`. Importing `hold_share` from `.test_output_claims` adds no cycle (that module imports only `.conftest` and `.test_in_place_scheduling`). The busy test is not the load-sensitive `slow_share` test. ruff and mypy clean. Measured: 0 tests, 22 code lines.
Checked: queue folder with all merges → 270 passed; `uv run ruff check` and `uv run mypy` → clean.

Orchestrator: Tier A, package Q-7.2.

### TQA-09 Two suspend ETA tests are one parametrized test
- Kind: near-copy
- Where: `queue/test_progress.py::test_eta_survives_a_linux_suspend` (159), `::test_eta_survives_a_suspend_that_both_clocks_count` (168)
- Now: The two tests have the same body: `eta_around_a_gap(mono_gap=..., wall_gap=...)`, then the speed is unchanged and the ETA is 2.5 s less. Only the gaps differ (0.5/3600 and 3600/3600), and the second adds `assert MAX_INTERVAL < 3600.0`.
- Change: parametrize as `queue/test_progress.py::test_eta_survives_a_suspend` with ids `linux` (0.5, 3600) and `both-clocks` (3600, 3600). Keep the `MAX_INTERVAL` assertion; it holds for both cases.
- Saved: 0 tests (2 cases remain), about 4 code lines
- Guarantee kept by: the parametrized test, with both cases.
- Why nothing is lost: same inputs, same assertions.
- Docs and history: `grep docs/` finds nothing. Both were added in `a1b362a` (C-11).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Same inputs and assertions; decision 0016 describes the two suspend cases and both stay as cases. Numbers: 0 tests, 3 code lines (not about 4) with the compact form `@pytest.mark.parametrize(("mono_gap", "wall_gap"), [(0.5, 3600.0), (3600.0, 3600.0)], ids=["linux", "both-clocks"])`; a `pytest.param` form with comments saves nothing (−1). Keep the two docstring reasons as the ids or a comment.
Checked: parametrized version applied → queue folder 270 passed; code lines measured with `tools/codelines.py` (183 → 180).

Orchestrator: Tier A, package Q-7.2.

## Looked at and kept

Coverage groups checked:
- `analysis/test_subtitlefile.py` BOM cases (7 in one group, 2 more pairs): each case is a different BOM or encoding (the UTF-32LE BOM starts with the UTF-16LE BOM, so their order matters). They are table rows, not one path.
- `test_mediatask.py::test_no_timestamps` (4 cases, 1 line set): None, 0, a negative duration and a count of 0 are separate boundary classes. Mutation M8 of `test-trim-reports/Q.md` restored `[-1.0-3]`.
- `test_mediatask.py::test_timestamps_are_rounded_to_milliseconds` / `::test_timestamps_skip_the_first_and_last_five_percent`: same lines, different inputs and assertions.
- `queue/test_store_nesting.py::test_a_row_nested_too_deeply_is_skipped_and_kept_untouched[65|300|1000|200000]`: each depth breaks a different reader (our limit, Pydantic's dump, `deepcopy`, `json.loads`). The cases guard the order of the depth check against those readers. The earlier trim kept the same set for settings.
- `queue/test_progress.py`: the three suspend and stall tests use different clock behaviours (only the near-copy pair is TQA-09). `test_parser_na_and_padded_values` and `test_parser_reads_the_real_long_captures` have different inputs.
- `analysis/test_analysis_tasks.py::test_loudness_with_wrong_arguments_fails` (nan and inf share lines with -1 and 0): `docs/test-trim-reports/R.md` and naming-definitions "Looked at and kept" keep nan and inf as separate "just outside" values (`inf` passes the server's `ge=0`).
- `analysis/test_analysis_parsers.py::test_covered_time_from_the_packet_ends` / `::test_covered_time_starts_at_the_first_packet`: B-frame order and a non-zero start are different inputs.
- `queue/test_metadata_edit_runner.py::test_anything_else_is_refused[<lambda>2|<lambda>3]`: `output_tmp` and `output_final` are separate fields of the "never write the source" guard.
- `queue/test_when_done.py::test_the_summary_is_the_reason[1-0|3-0]`: singular and plural. The earlier trim already removed `(0, 2)`.
- `queue/test_faults.py::test_a_source_named_like_the_part_file` / `::test_an_output_folder_that_links_to_the_source_folder[part]`: different inputs (a name, a linked folder) for the same refusal.
- `queue/test_output_claims.py::test_adds_of_one_output_at_the_same_time_queue_one` / `::test_claims_compare_files_not_spellings`: concurrency vs a symlinked folder.
- `queue/test_in_place_scheduling.py::test_conflict_rule` / `queue/test_job_keys.py::test_a_hard_link_to_the_source_is_the_same_file`, and `test_an_encode_waits_…` / `test_an_encode_of_a_hard_link_waits_…`, `test_two_in_place_edits_…` / `…_through_a_link_…`: a plain path, a hard link and a symlink are different key paths (path vs `(st_dev, st_ino)`), and the symlink tests skip on Windows.
- The large when-done and queue subset pairs (3,4xx-line sets): they come from the shared harness run, not from the same assertions. Each pair not listed in a finding asserts something different (a settings change, new work, a broken power service, a real `PowerService`, `start(job_ids)` idle).

Dropped from the findings because of the earlier test trim (`docs/test-trim-reports/Q.md`):
- `queue/test_queue.py::test_when_done_notify`: a near-copy of `test_when_done.py::test_notify_after_several_jobs`. The coverage sets are equal (3523 lines), and the only assertion that only this test makes is the title "Queue finished", which could move. But `Q.md` ("Uncertain, kept", lines 85-88 and 180-182) kept it on purpose, because removing it correlated with fewer hits of the `runner.py:458` race (`_wait_resumed`). That race is still there (`Q.md` "Gaps found": no test reaches it every time), so the reason still holds. Once a test reaches `runner.py:458` every time, this test can merge into `test_notify_after_several_jobs` (1 test, about 17 lines).
- `queue/test_when_done.py::test_each_power_action_runs_once_after_the_queue_empties[quit|sleep|shutdown]`: three cases with one line set (3528). `sleep` and `shutdown` also reach the power service in other tests (the real-`PowerService` `sleep` test and `test_new_work_cancels_the_countdown`). But `Q.md` deleted `test_power_actions_without_a_power_service[quit|sleep|shutdown]` because this test "covers each action", so the earlier trim treats it as the per-action guard. It stays (a trim would have saved 2 tests, about 0.5 s).

Named guards and regression tests:
- `queue/test_job_keys.py::test_the_keys_are_what_the_rule_compares`: it repeats two asserts of `test_conflict_rule`, but decision 0041 (RB-1) names it as the guard of the keys-off-the-loop fix. It stays.
- `queue/test_in_place_stop.py::test_an_encode_is_still_killed_at_once`: close to `test_queue.py::test_cancel_a_running_job[False]`, but decision 0034 names it (review R4-7, `870717e`). It stays.
- `queue/test_queue.py::test_a_running_jobs_log_file_has_its_lines_while_the_step_runs`: a fix commit (`cb1ed7a`), named in decision 0061. It stays.
- `queue/test_units.py::test_an_ffmpeg_error_exit_on_windows_is_a_failure_not_a_crash`: a one-case parametrization that could join `test_the_last_line_is_the_reason_of_a_failure_not_of_a_crash`, but it is the regression test of a Windows fix (`5829bd1`, Q-1.4). It stays.
- `queue/test_when_done.py::test_close_with_running_jobs_runs_no_action`: close to `test_queue.py::test_close_interrupts_running_jobs_and_restart_recovers`, but that test has a second, waiting job. That job stops the when-done check for another reason, so only this test closes a queue with nothing else waiting.
- `queue/test_queue.py::test_when_done_nothing_and_sleep_inhibit_off`: the only test of `sleep_inhibit = False`.
- `queue/test_no_mkvtoolnix.py` (both runs): they overlap with `test_faults.py::test_the_fixup_writes_the_part_file_without_any_mkvtoolnix` and `test_in_place_stop.py::test_an_edit_runs_no_program_and_is_checked`. Those check only fake-tool invocations, while `Spawned` sees every process. This is the decision 0080 guard.
- `queue/test_owner.py` Windows lock tests (`test_windows_lock_with_a_mocked_msvcrt`, `test_windows_lock_errors`), `queue/test_units.py` Windows retry and suspend-order mocks, and the D-45 `fake_tools` paths: Windows paths that run with mocks. They stay.
- `queue/test_faults.py`, `test_in_place_stop.py`, `test_integration.py`, `test_owner.py`: crash, cancel and real-tool guards. The earlier trim also left them whole.
- `queue/test_store_nesting.py::test_python_facts_behind_the_rule` and `queue/test_job_keys.py::test_python_facts_behind_the_rule`: records of Python behaviour behind a rule (decision 0016).
- `queue/test_faults.py::test_durations_in_messages` (private `_duration`): no public test pins the duration wording.

Layer duplicates:
- `packages/reframe-server/tests/test_queue.py`, `test_tasks.py`, `test_events.py`: route- and hub-level contracts (status codes, problem codes, folder labels, WebSocket throttling). The core tests keep the semantics. No server test repeats a core assertion closely enough to drop either side.
- `tests/remote/test_queue_contract.py` (`service` and `remote` params, about 20 tests per param): the `service` half repeats core queue behaviour (add with a position, a claimed output, start with ids, cancel, retry, remove, reorder, unknown ids). But `docs/plan/05-core.md:722` names this file as check 8 of C-17 ("what a front end sees does not depend on which one it has"), so the in-process half is the reference of that contract. It is outside this area; this is noted for the remote area's auditor, Tier C from here.
- `queue/test_facade.py::test_create_restores_and_close_interrupts` vs `test_queue.py::test_close_interrupts_running_jobs_and_restart_recovers`: the facade test also checks the real wiring (the store path, nothing written before a job is added).
- Loudnorm silent-track clamp at three layers (`test_units.py::test_loudnorm_of_a_silent_track_is_clamped`, `test_faults.py::test_silent_track_values_are_clamped_for_the_encode`, `test_integration.py::test_two_pass_loudnorm_with_a_silent_track`): the unit test checks the values, the fault test checks the encode's command line (`measured_thresh…linear=true`, not in the real test), and the real test checks FFmpeg's result. Each layer asserts something the others do not.
- `test_mediatask.py::test_require_tool` / `::test_require_source_…` vs `analysis/test_analysis_tasks.py::test_scans_fail_without_their_tool` / `::test_scans_fail_with_the_probe_error`: the unit tests cover `TOO_OLD` and the "message (detail)" form; the scan tests show that each scan asks for the right tool.
- `analysis/test_analysis_facade.py` concurrency tests (`test_two_bitrate_scans_keep_both_measurements`, `test_subtitle_scan_and_bitrate_scan_keep_both`) vs `::test_concurrent_updates_are_serialised`: the first two show that each real scan uses `update` with the latest source; the third tests `update` alone. `StubSources` cannot show the race.
- `analysis/test_analysis_ffmpeg.py` restart halves (bitrate and PGS counts read back from the probe cache by a new `Reframe`) and `test_mediatask.py::test_store_keeps_a_measured_bitrate`: three "survives a restart" checks of different field families. Each is cheap inside a real-tool test that runs anyway.
- `analysis/test_analysis_ffmpeg.py::test_measured_counts_feed_the_forced_heuristic` vs `analysis/test_analysis_tasks.py::test_subtitle_scan_recomputes_the_forced_heuristic`: the real test also records a tool fact (FFmpeg writes no `NUMBER_OF_FRAMES`); the fake test checks the detail text.
- `test_tasks.py`, `test_events.py`: every test has its own path (same thread vs another thread, a queued cancel vs a cancel before start, and so on). QJ-01 already removed the dead limit and JSON tests.

Already done or decided by Q-6 and not repeated here: QJ-01 (`test_tasks.py`), QJ-04 (oracle calls), QJ-07 (write-side nesting tests, a decision change), QJ-08 and NDP-05 (stubs and the `app` and `finish` helpers).

## Speed notes
- `queue/test_owner.py::test_a_second_process_leaves_a_running_encode_alone` (5.9 s): the fake encode sleeps 2.5 s so that the `.part` file outlives two child-process start-ups. A fake action that waits for a trigger file would make it shorter and less load-sensitive.
- `queue/test_faults.py::test_a_slow_step_that_prints_is_not_stalled`: 12 blocks at 0.1 s (1.2 s) against `stall_after = 0.3`. Halving both would save about 0.6 s, but it would be more sensitive to load. Leave it unless time matters.
- The fixed sleeps in `test_queue.py` (0.3 or 0.4 s in the pause tests), in `test_in_place_stop.py::still_waiting` (0.2 s) and in `test_in_place_scheduling.py` (0.3 s) are "nothing happens" waits. They are short, and they are needed.

## Verifier notes

Result: 9 confirmed, 0 adjusted, 0 rejected. Corrected totals (Tier A = Tier A+B): 7 tests and about 85 code lines (11 + 11 + 11 + 7 + 7 + 6 + 7 + 22 + 3; the report said about 87), and about 0.6 s of test time, not 1.4 s (the 7 removed tests take 0.80 s of call time in `junit.xml`; TQA-02 adds a 0.1 s sleep and TQA-01 now runs the longer `test_queue` waits). Test count with all 9 applied: area 402 → 395, `tests/queue` 277 → 270.

- The 7 removals and merges were applied together in the worktree and run: `tests/queue` 270 passed; `test_when_done.py` + `test_queue.py` 5 times, 62 passed each time; the three merged tests of TQA-01, 02 and 04 5 times alone, 4 passed each time (1–2 other pytest runs on the machine). `ruff check`, `ruff format --check` (after removing the trailing blank lines `test_store.py` keeps when its last test goes) and `mypy` are clean.
- Mutation checks (production code changed, then reverted): the when-done keepers of TQA-01 and TQA-02 kill mutants that the deleted `test_queue.py` tests let survive (when-done after a cancelled last job; when-done after a stop with jobs left). So `test_queue.py`'s when-done assertions in those two tests were the weaker side, and the merge direction is right.
- TQA-05: the renamed-output notification is the only test that kills a `job_ended` mutant that ignores `output`. Whoever implements the merge must keep the assertion in `test_collision_auto_rename`, not drop it as noise.
- `runner.py:458` race (Q.md "Coverage gate"): TQA-01 and TQA-02 delete two more `test_queue.py` tests that run after `test_a_cancelled_resume_does_not_unbalance_the_sleep_inhibit`. Q.md saw the hit rate of that line move with the file's contents and judged it timing, not protection; under xdist (decision 0084) the tests of a file no longer run in one process in file order, so this is not a reason to keep them. It still has no test that reaches it every time (Q.md "Gaps found").
- No removed test runs only on Windows or needs a real tool; all run on fake tools on both CI runners, as do their keepers.
