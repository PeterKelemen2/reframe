# Test trim, area Q

Area Q holds the CLI, facade, settings, events, tasks, jobs and queue tests (36 files; the
list is in the task). Branch `test-trim-Q`. `test-trim/Q` cannot exist because the branch
`test-trim` exists, so git refuses `refs/heads/test-trim/Q`. The R area uses the same
`test-trim-<area>` form.

## Numbers

| | Before | After |
|---|---|---|
| Tests (area files) | 696 | 657 (−39, −5.6 %) |
| Wall time, with branch coverage, run 1 | 241 s | 123 s |
| Wall time, with branch coverage, run 2 | 116 s | 135 s |

Other agents ran their suites on the same machine at the same time. Because of that, the wall
times are noisy and do not show a real difference. The area was already lean. Most of its tests
are fault-injection, recovery, in-place job, when-done, M2-review regression or real-tool tests,
and these stay.

How the runs were made: the file list was sorted by directory first. With the list in the
task's order (`jobs/x.py`, then `test_y.py`, then `jobs/z.py`), pytest loses the fixtures of
`jobs/conftest.py` and `queue/conftest.py` for the later files (63 setup errors, "fixture
'cli_env' not found"). This comes from how pytest collects the arguments, not from the tests.

## Coverage gate

`covcmp.py before.json after.json` on the final state, two runs:

```
run 1
LOST packages/reframe/src/reframe/capabilities/detect.py: lines [184, 185, 195, 196, 197, 349, 350] branches [(194, 195), (348, 349)]
LOST packages/reframe/src/reframe/queue/progress.py: lines [] branches [(259, 262)]
LOST packages/reframe/src/reframe/queue/runner.py: lines [458] branches [(457, 458)]
LOST packages/reframe/src/reframe/tools/runner.py: lines [294, 295, 423] branches [(376, 374), (422, 423)]
before 71.219% 3839/6918 branches 16682/21896 lines
after 71.167% 3833/6918 branches 16673/21896 lines
TOTAL LOST: 17

run 2
LOST packages/reframe/src/reframe/queue/progress.py: lines [] branches [(259, 262)]
LOST packages/reframe/src/reframe/queue/runner.py: lines [458] branches [(457, 458)]
LOST packages/reframe/src/reframe/service.py: lines [] branches [(561, -558)]
LOST packages/reframe/src/reframe/tools/runner.py: lines [] branches [(376, 374)]
before 71.219% 3839/6918 branches 16682/21896 lines
after 71.208% 3835/6918 branches 16683/21896 lines
TOTAL LOST: 5
```

All these items are races. The **unchanged** suite, run a second time (`before2.json`), loses
these items against its own first run:

```
covcmp before.json before2.json
LOST packages/reframe/src/reframe/queue/progress.py: lines [] branches [(259, 262)]
LOST packages/reframe/src/reframe/queue/runner.py: lines [458] branches [(457, 458)]
LOST packages/reframe/src/reframe/tools/runner.py: lines [294, 295] branches [(376, 374)]
TOTAL LOST: 6
covcmp before2.json before.json
LOST packages/reframe/src/reframe/probe/cache.py: lines [273, 274] branches []
LOST packages/reframe/src/reframe/tools/runner.py: lines [378, 379] branches []
TOTAL LOST: 4
```

The items that changed between the two final runs are timing-dependent code:

- `detect.py` and `service.py:561`: background encoder detection that is cut off when a test
  closes Reframe. They are lost in run 1 and covered in run 2.
- `tools/runner.py`: `kill_tree` when the process has already gone, and a token that was
  already cancelled.
- `queue/progress.py`: a clock branch.

So the gate was checked against the stable set: the lines and branches that **both** baseline
runs covered, compared with the union of the two final runs:

```
unioncmp before.json before2.json -- after.json after2.json
STABLE vs UNION LOST: 0
```

`queue/runner.py:458` (`_wait_resumed`: `raise _Stopped` when a paused job is cancelled at a step
boundary) needs a separate note. Only a race in
`test_queue.py::test_a_cancelled_resume_does_not_unbalance_the_sleep_inhibit` reaches it. The
whole original `test_queue.py` hit the line in 4 of 9 runs. The trimmed file hit it in 0 of 10
runs without `test_when_done_notify` and `test_power_actions_without_a_power_service`, and in
1 of 6 runs with `test_when_done_notify` put back. Both of those tests run after the covering
test. So the effect is timing, not protection, and `before2` missed the line too.
`test_when_done_notify` was kept anyway (see "Uncertain, kept"). The line needs a test that
reaches it every time (see "Gaps found").

A first trim also deleted
`jobs/test_service.py::test_detection_wait_default_is_read_at_creation`. The gate showed that
this test was the only one to cover `JobService.detection_wait` (`jobs.py:366`), so it was
restored.

## Deleted tests (39)

**Help text (click `--help` output, not behaviour), 4**
- `jobs/test_cli_encode.py::test_help`
- `jobs/test_cli_encoders.py::test_help_mentions_the_line_format`
- `jobs/test_cli_plan.py::test_help`
- `jobs/test_cli_presets.py::test_help`

**Tests of test doubles or test helpers (no `reframe` code), 4**
- `jobs/test_fake_queue.py` (file removed): `test_order_states_and_files` and
  `test_errors_add_a_failed_job_and_a_running_one_cannot_be_removed`. These test
  `tests/jobs/fake_queue.py`. The CLI tests that use the fake exercise its behaviour, and the
  real queue has its own tests in `queue/`.
- `jobs/test_service.py::test_default_capabilities_snapshot_has_every_encoder` (the `caps()`
  helper of `jobs/conftest.py`).
- `test_service.py::test_pid_helper_ignores_ended_processes` (the test file's `alive()`).

**Near-duplicates (same input, weaker assertions than a test that stays), 3**
- `jobs/test_cli_robustness.py::test_name_of_an_undecodable_file_name_is_never_a_traceback`
  (same invocation as `test_name_of_an_undecodable_file_name`, which requires exit 0).
- `jobs/test_cli_robustness.py::test_plan_and_encode_of_an_undecodable_name_are_never_a_traceback[plan]`
  and `[encode]` (same as `test_plan_of_…` and `test_encode_of_an_undecodable_file_name`).

**Parametrized cases with no new branch, 22**
- `jobs/test_cli_robustness.py::test_app_warnings_are_printed`: 11 codes down to 1
  (`queue.store_busy`). `WarningPrinter` is generic: it does not branch on the code.
- `jobs/test_cli_when_done.py::test_no_wait_for_other_settings[notify]`: the CLI tests
  `when_done not in WAITED_ACTIONS`, and `notify` takes the same branch as `nothing`.
- `queue/test_queue.py::test_power_actions_without_a_power_service[quit|sleep|shutdown]`: the
  same `power is None` branch. `test_when_done.py::test_without_a_power_service_nothing_is_done`
  checks it with the exact message, and `test_each_power_action_runs_once_…` covers each action.
- `queue/test_when_done.py::test_the_summary_is_the_reason[0-2-…]`: the same plural and "failed"
  branches as `(3, 0)` and `(2, 1)`.
- `test_settings.py::test_damaged_contents_count_as_corrupt`: `when_done "explode"` and
  `tools "ffmpeg"`. Both take the same `ValidationError` path as `parallel_jobs 99`.
- `test_service_settings.py::test_an_invalid_change_is_an_issue_and_changes_nothing[when_done explode]`
  (same validation path as `parallel_jobs 99`).
- `test_jsonpatch.py::test_more_operations`: three `test` op cases (`None`, `1` vs `1.0`, a
  nested object). `test_json_equal` covers JSON equality, and RFC A.8 covers the dispatch of
  the op.
- `test_jsonpatch.py::test_errors`: `move` from a missing member. It takes the same `_remove`
  "no member" branch as `remove /b`.

**Trivial, constants, or third-party behaviour, 6**
- `test_cli.py::test_version`: `test_main_runs_the_app` runs the same command through
  `cli.main()`.
- `test_package.py::test_anyio_plugin_runs_async_tests`: a tautology. Hundreds of async tests
  in the suite show the same thing.
- `test_events.py::test_events_round_trip_through_the_adapter`: a Pydantic round trip. Mutation
  M10 shows that `models/test_models.py` guards the union.
- `test_mediatask.py::test_every_c10_task_kind_has_a_limit`: a test of a constant table (key
  presence only).
- `test_service.py::test_default_settings_are_app_settings_defaults`:
  `test_settings.py::test_missing_file_gives_defaults_and_writes_nothing` covers it.
- `test_settings.py::test_two_corrupt_loads_keep_both_backups`:
  `test_backup_names_do_not_collide` covers the same collision rule exactly (mutation M4).

## Mutation checks

Each mutation was made in production code. The remaining tests were run, and then
`git checkout` reverted the change. After every batch, `git status packages/reframe/src` was
empty.

| # | Mutation | Result |
|---|---|---|
| M1 | `WarningPrinter` subscribes to `app.warnings` (a wrong type) | killed: `test_app_warnings_are_printed[queue.store_busy]` |
| M2 | `printable()` returns the text unchanged | killed: `test_display_path_replaces_undecodable_bytes` |
| M14 | `display_path()` returns `str(path)` (only the 3 kept undecodable-name CLI tests run) | killed: `test_name_of_an_undecodable_file_name` |
| M3 | no `queue.when_done_unavailable` warning without a power service | killed: `test_when_done.py::test_without_a_power_service_nothing_is_done` |
| M4 | backup names without the `-n` counter | killed: `test_backup_names_do_not_collide` |
| M5 | `json_equal` treats `bool` as a number | killed: `test_json_equal` |
| M6 | the `test` op uses Python `==` | **survived**, so the two bool-vs-int `test_errors` cases were restored. Then killed: `test_errors[doc17-…]` |
| M7 | `_remove` without the "no member" check | killed: `test_a13_duplicate_members_parse_to_the_last_value` |
| M8 | `sample_timestamps`: `duration <= 0` becomes `== 0` | **survived**, so `test_no_timestamps[-1.0-3]` was restored. Then killed |
| M9 | `BUNDLED_SUBDIRS["ffprobe"] = "ffprobe"` | **survived** (`test_data_dir_holds_the_fetched_tools` *skips* when the bundled build is not found), so `test_paths.py::test_bundled_subdirs` was restored. Then killed |
| M10 | `NotificationEvent` taken out of the `Event` union | killed: `models/test_models.py::test_event_types_match_the_union` (outside the area) |
| M11 | `Reframe` taken out of `reframe.__all__` | **survived**, so `test_service.py::test_reframe_is_exported` was restored. Then killed |
| M12 | `except ValidationError` becomes `except ZeroDivisionError` in the settings load | survived, but this mutation proves nothing: `ValidationError` is a `ValueError`, so the next handler marks the file corrupt anyway. M15 replaces it |
| M15 | the detail of a damaged settings value becomes `"x"` | killed: `test_damaged_contents_count_as_corrupt[…parallel_jobs 99…]` |
| M16 | the message of `settings.invalid` (an update) becomes `"x"` | survived, **also with the original test file**: no loss (see "Gaps found") |
| M13 | `json_equal(None, None)` is false | killed: `test_json_equal` |

## Uncertain, kept

- `queue/test_queue.py::test_when_done_notify`: a near-duplicate of
  `test_when_done.py::test_notify_after_several_jobs`. It was kept because its removal
  correlated with fewer hits of the `runner.py:458` race (see "Coverage gate").
- `jobs/test_service.py::test_detection_wait_default_is_read_at_creation`: trivial, but it is
  the only test that covers `JobService.detection_wait`.
- `jobs/test_cli_encoders.py::test_a_legacy_windows_console_encoding_does_not_crash`: subprocess
  runs that overlap with `test_cli.py::test_non_utf8_stdout_does_not_crash` (other commands, and
  the arrow character).
- `jobs/test_cli_encode.py::test_follow_rereads_the_queue_after_a_resync`: it has no assertion,
  but it is the only test that runs the resync path of `_follow_jobs`.
- `queue/test_store_nesting.py::test_python_facts_behind_the_rule`: it tests CPython and
  Pydantic behaviour, but decision 0016 cites it as the record of the rule.
- `test_settings.py::test_deeply_nested_file_is_corrupt_not_a_crash[100|600|100000]` and
  `test_too_deep_settings_are_not_saved…[100|400]`: regression boundaries from the M2 review,
  one for each failure mode (depth check, `deepcopy`, `json` recursion, Pydantic dump).
- `jobs/test_service.py::test_recorded_probes_draft_without_errors` (7 recorded probes): each
  probe has other stream types.
- `test_cli_presets.py::test_list_marks_the_builtin_default` and
  `test_preset_rows_align_the_columns`: they overlap with `test_list_shows_builtins_then_user_presets…`.
- `queue/test_faults.py` (all of it), `test_owner.py`, `test_integration.py`,
  `test_in_place_scheduling.py`, `metadata/test_metadata_edit_real.py`, `jobs/test_encode_real.py`
  and `test_tasks.py`: fault injection, regression, "Done when" and real-tool tests. Nothing
  was removed from them.

## Gaps found (no change made)

- `queue/runner.py:458` (cancel of a paused job at a step boundary) has no test that reaches it
  every time. Only a race reaches it.
- No test checks the message of `settings.invalid` from `Reframe.settings.update`: mutation M16
  survives with the original tests too.
- `test_service.py::test_data_dir_holds_the_fetched_tools` skips, and does not fail, when the
  bundled ffprobe is not found. This is why M9 needed `test_bundled_subdirs`.

## Unused fixtures

None. The deletions made no fixture in `conftest.py` or `testing/` unused.
`tests/jobs/fake_queue.py` is still used by the CLI tests.

## Checks

`uv run ruff check`, `uv run ruff format --check`, `uv run mypy` and
`uv run mypy --platform win32` are clean. The area tests give 657 passed (two runs, with
coverage).
