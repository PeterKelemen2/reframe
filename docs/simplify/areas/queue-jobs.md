# queue-jobs: simplification findings

Commit: 85d9dcb. Scope: `packages/reframe/src/reframe/queue/`, `jobs.py`, `tasks.py`, `mediatask.py`, with `packages/reframe/tests/queue/`, `tests/jobs/`, `tests/test_tasks.py`, `tests/test_mediatask.py`. Source lines: 3329 in `queue/` (runner 910, service 831, store 379, progress 207, verify 170, files 125, whendone 121, lock 118, logs 102, errors 91, client 83, watchdog 74, loudnorm 56, process 30, clock 19, `__init__` 13) + 922 in `jobs.py` (570), `tasks.py` (268), `mediatask.py` (84). Read in full: every file of `queue/`, `jobs.py`, `tasks.py`, `mediatask.py`, `tests/queue/conftest.py`; decisions 0016 (all follow-ups), 0061/0062 (the parts on keys and claims), 0064 (skimmed), plan rows for facade members in `06-web-app.md`. Only skimmed: the other files in `tests/queue/` and `tests/jobs/` (read only where a finding removes something they test), decisions 0027, 0034, 0037, 0042, 0078, 0080 (searched for the points that matter here).

Verified: 2026-11-15, 4 confirmed, 10 adjusted, 0 rejected.

Note on evidence: `coverage.txt` lists the `def` line of nearly every function as missed (module-level statements are not measured in that run), so it is only used where I also checked by reading code and tests.

## Summary

The queue is complex, but almost all of that complexity is required: the one-writer store, the file keys and claims, the restore of restored jobs, the pause/cancel/close paths and the in-place header edit all trace to decisions 0016, 0027, 0034, 0061/0062, 0064 and 0080, and are listed in "Looked at and kept". The real slack is at the edges. `TaskManager` carries a hand-made semaphore, a runtime `set_limit` and a "plain JSON value" result path that no production code uses. A Windows retry loop is written twice (settings and queue files), the CLI repeats `JobService.draft` in `OwnerJobs.draft`, and three service protocols are written three times each. A group of small members has no production caller (`_output_key`, `Outcome.stop_reason`, `QueueStore.positions`, `job_from_preset`, `MediaTaskContext.events`, and more). One finding is a `decision-change` (the store's write-side nesting guard). Estimated total, without the decision-change: about -200 source lines and -110 test lines (after verification).

## Findings

### QJ-01: TaskManager has a hand-made semaphore, a runtime `set_limit` and a plain-JSON result path that nothing uses
- Kind: speculative-generality
- Where: `packages/reframe/src/reframe/tasks.py:105-139` (`_Gate`), `:154-172` (`TaskManager.__init__`: `limits`, `default_limit`, `keep_finished`), `:174-190` (`limit`, `set_limit`, `_gate`), `:308-317` (`TaskManager._to_json`), `:347-end` (`_is_json`); imports `deque`, `contextlib` (used only by `_Gate`).
- Now: `_Gate` is "an `asyncio.Semaphore` whose limit can change". The limit can change only through `TaskManager.set_limit`, which has 0 callers outside tests (`tests/test_tasks.py:374,377,390`, `tests/preview/test_clip.py:167`). `TaskManager.limit()` has 0 callers outside `_gate` and tests (`tests/test_tasks.py:177,178,378`). The only production construction is `TaskManager(self.events)` (`service.py:956`), so `default_limit` and `limits` are test knobs only. `_to_json` has a branch for a task that returns a plain list, dict or number (`_is_json`, 13 lines with a NaN/inf check). Every production task returns a pydantic model (`BitrateScan`, `SubtitleScan`, `LoudnessMeasurement`, `FrameSet`, `CropDetection`, `PreviewClip`, `ToolFetchResult`, `CapabilitySnapshot` in `routers/system.py:100-105`, `ProbeSummary` in `routers/sources.py:100-143`) or passes `result_json` (`probe/folder.py:220`, `service.py:405`). Plain values are returned only by tests: `tests/test_tasks.py:325-332` and four server tests (verified: they would fail without the plain-JSON path, see "Callers to update"). The plan says the limit is internal: `docs/plan/06-web-app.md:231` ("The concurrency per task kind is internal; no setting changes it").
- Change: replace `_Gate` with `asyncio.Semaphore`. The queue and cancel-handover tests already exist.
  ```python
  self._gates: dict[str, asyncio.Semaphore] = {}
  def _gate(self, kind: str) -> asyncio.Semaphore:
      gate = self._gates.get(kind)
      if gate is None:
          gate = self._gates[kind] = asyncio.Semaphore(self._limits.get(kind, DEFAULT_LIMIT))
      return gate
  ```
  Delete `_Gate`, `TaskManager.limit`, `TaskManager.set_limit`, the `default_limit` keyword and `_is_json`. Keep `limits` (6 tests use it after `test_set_limit_starts_waiting_tasks` is gone; `_check_limit` stays for it) and `keep_finished` (1 test). `_to_json` becomes: `result_json` if given; else `value.model_dump(mode="json")` for a `BaseModel`; else `None`. Remove the unused imports. `_run` stays as it is (`await gate.acquire()`, `acquired` flag, `gate.release()` in `finally`).
  Same commit: delete the row for `tasks.limit`, `tasks.set_limit` in `docs/plan/06-web-app.md:231` (`packages/reframe-server/tests/test_facade_coverage.py` fails on a row whose member no longer exists).
- Behaviour: unchanged for every production task. A task that returns a plain list or dict would now get `TaskInfo.result = None` (none does).
- Contracts touched: public core API (`TaskManager.limit`, `set_limit`, `default_limit`; none is reached by a route, see the plan row). No HTTP, OpenAPI or persisted change.
- Callers to update: `tests/preview/test_clip.py:167` and `tests/preview/helpers.py:168-175` (`make_env` gets a `limits` keyword and passes it to `TaskManager`); no source caller. Four server tests return a plain dict and read it back through `GET /api/tasks/{id}` or the event stream (`TaskInfo.result`): `packages/reframe-server/tests/test_tasks.py:17-19` (`_done`, used by `test_a_finished_task_is_listed_with_its_result` `:22` and `test_kind_keeps_the_tasks_of_one_kind` `:32-33`), `:83-88` (`fetch` of `test_only_the_server_folders_are_hidden`), `packages/reframe-server/tests/test_events.py` (`test_a_task_event_names_the_cache_folder_by_its_label`). Each must pass `result_json=lambda value: value` to `tasks.start(...)` (or return a small model); these tests check that the server hides its folders in a task result, so they keep their value.
- Tests: delete `test_set_limit_starts_waiting_tasks` (`tests/test_tasks.py:364-383`); in `test_limits_must_be_positive` (`:384-391`) drop the `default_limit=0` and `set_limit("k", 0)` cases (`:388-390`); drop the `tasks.limit(...)` asserts in `test_per_kind_limit_holds` (`:177-178`); in `test_result_conversion` (`:314-340`) drop the cases for a list, `nan`, `{1: 2}`, `(1, 2)` and `object()` and keep the model case and the `result_json` case. In `test_per_kind_limit_holds` keep the check of the default limit of `probe_folder` as `DEFAULT_LIMITS["probe_folder"] == 2`. Keep as guards: `test_per_kind_limit_holds`, `test_queued_tasks_start_in_order`, `test_cancel_a_queued_task`, `test_cancel_slot_handover_race` (this one proves that the Semaphore hands a slot over correctly when a waiter is cancelled; run it first).
- Decision records: 0030 (default limits live in `DEFAULT_LIMITS`, which stays), 0048 (item at line 116 says limit and `set_limit` are internal). No decision asks for a runtime change of a limit.
- Size: S; estimated lines: -45 source / -24 tests (the 4 server tests get +1 line each)
- Risk: low. `asyncio.Semaphore` fairness differs from the hand-made gate only in edge cases that `test_queued_tasks_start_in_order` and `test_cancel_slot_handover_race` cover.
- Depends on: none
- Confidence: medium (high that the members are unused. I checked on Python 3.14.9 with a small script that `asyncio.Semaphore(1)` gives the slot on to the third waiter when the second one, which was just granted it, is cancelled: the order was `[1, 3]`. The two ordering tests are still the guard. The verifier ran `tests/test_tasks.py` with `TaskManager._gate` replaced by an `asyncio.Semaphore` (plugin in the scratchpad, nothing written to the repository): 17 passed, only `test_set_limit_starts_waiting_tasks` failed, as expected)
- Verdict: ADJUSTED (the plain-JSON result path is also used by 4 server tests, `test_tasks.py` x3 and `test_app.py` x1, which need `result_json=lambda value: value`; `CapabilitySnapshot` and `ProbeSummary` added to the model list; `limits` count 6; test estimate -24)
- Orchestrator: Tier B, work package Q-6.18 (see ../plan.md).

### QJ-02: The Windows `PermissionError` retry for `os.replace` is written twice, with the same constants
- Kind: duplication (cross-area: settings)
- Where: `packages/reframe/src/reframe/settings.py:56-60` (`REPLACE_ATTEMPTS`, `REPLACE_DELAY`, `WINDOWS`), `:98-121` (`_replace`, `_sleep`, `replace_file`), `__all__` lines 38 and 47; `packages/reframe/src/reframe/queue/files.py:36-40` (`ATTEMPTS`, `DELAY`, `WINDOWS`), `:45-60` (`_sleep`, `_retry`), `:161-163` (`replace_file`).
- Now: `settings.replace_file(source, target)` and `queue.files.replace_file(source, target)` are the same function: 6 attempts, first pause 0.05 s that doubles, retry only on Windows and only for `PermissionError`, the last attempt raises. `settings.replace_file` has 2 call sites, both in `settings.py` (`:185`, `:207`); nobody outside `settings.py` imports it. `queue/files.py` cannot be imported from `settings.py` today: `reframe.queue.store` imports `reframe.settings`, so `settings -> reframe.queue` (whose `__init__` loads `service`) is a cycle. That is why the loop was copied. Each copy has its own tests of the same loop (4 tests in `tests/test_settings.py:350-405`, 1 in `tests/queue/test_units.py:319-354`). `tools/fetch.py:590` (`_retry_on_permission`: 5 attempts, 0.5 s times the attempt number, no Windows test) is a third, different loop; it is not part of this finding.
- Change: new leaf module, for example `packages/reframe/src/reframe/platform/retry.py`, with `WINDOWS`, `ATTEMPTS`, `DELAY`, `_sleep`, `retry_on_permission(call)` and `replace_file(source, target)` moved from `queue/files.py` unchanged. `queue/files.py` imports `retry_on_permission` for `remove_files` and `rename_no_replace` and re-exports `replace_file` (`runner.py:737` and `tests/queue/test_faults.py:602` use `files.replace_file`). `settings.py` imports `replace_file` from it; delete `REPLACE_ATTEMPTS`, `REPLACE_DELAY`, `_replace`, `_sleep` and its own `replace_file`, and remove `REPLACE_ATTEMPTS` from `settings.__all__`. `settings.WINDOWS` stays: `_sync_folder` (`settings.py:213`) uses it, and so does `files.WINDOWS` in `rename_no_replace` (`queue/files.py:169`); a test that sets `WINDOWS` must now also set the flag of the new module (`retry.WINDOWS`) for the retry to run. The seam `settings._replace` goes: the tests patch `os.replace` instead (as `tests/queue/test_units.py:338-339` and `reframe-server/tests/test_owner.py:379` already do). Move the retry tests to one test module.
- Behaviour: unchanged.
- Contracts touched: none public (`reframe.settings.replace_file` and `REPLACE_ATTEMPTS` are in `settings.__all__` but have 0 callers outside `settings.py` and `tests/test_settings.py`).
- Callers to update: `settings.py:185,207`; `queue/files.py` (internal uses); tests that patch `files.WINDOWS`/`files._sleep` (`tests/queue/test_units.py:301,324,326,364,365`) and `settings_module.WINDOWS`/`_replace`/`_sleep` (`tests/test_settings.py:275,307,355-357,369-371,383-384,399-400`) now patch the new module or `os.replace`. Missed in the first list: `tests/presets/test_store.py:273,470,632` (patch `settings_module._replace`) and `packages/reframe-server/tests/test_owner.py:378` (patches `settings_module.WINDOWS`; the endpoint file is written through `JsonDocumentFile`, so this is the test of the retry on the real server path).
- Tests: merge the 4 settings tests and the queue test of the retry loop into one set (about -30 lines). `test_rename_without_hard_links` and `test_remove_files_reports_problems` stay.
- Decision records: 0015 (atomic writes in settings), 0016 (Windows retry, "on Windows, a call that hits a file that another process holds open is retried"), 0053 (Windows code is written to the plan and mocked on Linux). The loop stays; only the copy goes.
- Size: M; estimated lines: -22 source / -30 tests
- Risk: low on Linux. A patched module name in the Windows-mocked tests is the one thing that breaks if missed. The retry is a Windows-only path (mocked on Linux): **this change needs a check on the Windows test VM** (run `tests/test_settings.py`, `tests/presets/test_store.py`, `tests/queue/test_units.py`, `packages/reframe-server/tests/test_owner.py` there; `PermissionError` of `os.replace` on an open file is the real case).
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (callers list incomplete: `tests/presets/test_store.py:273,470,632` and `reframe-server/tests/test_owner.py:378`; `settings.WINDOWS` and `files.WINDOWS` stay for `_sync_folder` and `rename_no_replace`, so the tests must set the flag of the new module as well; the change needs a Windows VM check)
- Orchestrator: joined into X-02 (see ../cross-cutting.md); that entry decides the tier and the work package.

### QJ-03: `OwnerJobs.draft` repeats `JobService.draft`
- Kind: duplication (cross-area: cli)
- Where: `packages/reframe/src/reframe/cli.py:1298-1356` (`OwnerJobs.draft` at about `:1307-1343`); `packages/reframe/src/reframe/jobs.py:348-385` (`JobService.draft`; the validation call is `:377`).
- Now: both build a `JobDraft` the same way: probe the source, take the preset, take the naming options (`preset.naming` else `settings.output.naming`), run `draft_from_preset(..., container_codecs=False, languages=settings.languages)` in a thread, name the job with `name_job`, keep the track issues that are errors or start with `batch.`, then add the validation issues and build `JobDraft(job, decisions, subtitle_decisions, naming, issues, notes)`. The only differences: validation goes to the queue owner (`remote.validate`) so that no encoder detection runs here, and an unknown preset is a CLI error (`find_preset`) instead of a `preset.not_found` issue. `OwnerJobs.name_job` and `.validate` are pass-throughs that exist so that `BatchService(jobs=OwnerJobs)` type-checks; they stay.
- Change: give `JobService.draft` an optional validator and let `OwnerJobs.draft` call it.
  ```python
  # jobs.py
  async def draft(self, source, preset=None, *, output=None,
                  validate: Callable[[JobSettings], Awaitable[list[ValidationIssue]]] | None = None):
      ...
      checked = await validate(job) if validate is not None else await self._validate(job, media, naming)
      issues = [*issues, *track_issues, *checked]
  # cli.py
  async def draft(self, source, preset=None, *, output=None):
      app = self._app
      media = source if isinstance(source, MediaSource) else await app.sources.probe(source)
      if isinstance(media, ProbeError):
          return media
      chosen = preset if isinstance(preset, Preset) else find_preset(app, preset)
      if isinstance(chosen, str):
          raise ValueError(chosen)
      return await app.jobs.draft(media, chosen, output=output, validate=self._validate)
  ```
  The probe stays first in `OwnerJobs.draft`: it returns the `ProbeError` before an unknown preset name raises, as now (resolving the preset first, as a shorter snippet would, changes which error a bad source with a bad preset name shows). `JobService.draft` given a `Preset` returns it with no issue, so the CLI error path is unchanged. The `track_issues` filter and the `JobDraft` construction then exist once.
- Behaviour: unchanged (same order of issues: preset issues (none for a `Preset`), track issues, validation). Production calls pass a `Preset` (`cli.py:1783`); only a test passes a name.
- Contracts touched: public core API (`JobService.draft` gets one optional keyword). No HTTP change: the server does not pass it.
- Callers to update: `cli.py:1307-1343` only. `tests/remote/test_cli_client.py:164` (`OwnerJobs(app, app.jobs.validate).draft(...)`) is the guard.
- Tests: none deleted; `tests/jobs/test_service.py` draft tests stay; add one case: `draft(..., validate=fn)` uses `fn` and does not wait for detection (the existing `OwnerJobs` test already shows the second half).
- Decision records: 0061 (CLI validates through the owner), 0017 (jobs service). No record asks for a second copy of the draft.
- Size: S; estimated lines: -14 source (-17 in `cli.py`, +3 in `jobs.py`) / 0 tests
- Risk: low. Compare the two implementations once more when making it: `OwnerJobs.draft` reads `app.settings_snapshot()` and `JobService.draft` reads `self._settings()` (the same function, `Reframe.settings_snapshot`, `service.py:990`); `JobService._sources` is `Reframe.sources`, the same object that `OwnerJobs.draft` probes with.
- Depends on: none
- Confidence: medium
- Verdict: ADJUSTED (the proposed `OwnerJobs.draft` resolved the preset before probing, which changes the error order for a bad source plus a bad preset name; probe first as now; estimate -14)
- Orchestrator: joined into X-03 (see ../cross-cutting.md); that entry decides the tier and the work package. Joined into X-03 with CLI-03. This entry's shape (probe first) is the one to make.

### QJ-04: Members of `queue/` that no production code uses
- Kind: dead-code
- Where and now (each item: callers searched in `packages/*/src`, `scripts/`, `testing/`, `packages/*/tests`):
  1. `queue/service.py:84-95` `_source_key` and `_output_key`: 0 production callers (`_source_key` is called only by `_output_key`). `_job_keys` (`:112`) is the real code. Tests use them as an oracle: `tests/queue/test_in_place_scheduling.py:17,38,39,60`, `tests/queue/test_job_keys.py:20,99,143,346`.
  2. `queue/runner.py:162` `Outcome.stop_reason` and its 5 writes (`runner.py:821,827,838,866`, `service.py:840`): 0 production readers (the queue reads `active.stop_reason`). One test reads it: `tests/queue/test_in_place_stop.py:355`.
  3. `queue/store.py:385-387` `QueueStore.positions`: 0 callers; the queue renumbers with whole rows (`_save_many`). One test: `tests/queue/test_store.py:78`.
  4. `queue/logs.py:70-75` `JobLog.write(..., event=False)` and its branch: 0 production callers (only `tests/queue/test_units.py:206`).
  5. `queue/progress.py:169,234` `ProgressTracker.active_time`: 0 readers (vulture also flags it); one test assertion `tests/queue/test_progress.py:198`.
  6. `queue/runner.py:209,230` `JobRunner(shell=...)`: `JobRunner` is built once (`service.py:226`) and never passes `shell`; `self._shell = default_shell()` is enough.
  7. `queue/runner.py:210,216,590-595` `resumed` is optional with an `if self._resumed is not None` guard, but the one construction always passes it.
- Change: delete each item. For 1: tests call `service._job_keys(job)` and read `.output` and `.source` (`active_for` becomes `keys = _job_keys(job); ActiveJob(job_id=..., output_key=keys.output, source_key=keys.source, in_place=...)`). For 2: drop the field and the `stop_reason=` arguments. For 7: make `resumed` required and drop the guard.
- Behaviour: unchanged.
- Contracts touched: none (all internal; `Outcome` is not exported from `reframe.queue`).
- Callers to update: the tests named above.
- Tests: change 6 test files by one assertion or call each (1: `test_in_place_scheduling.py`, `test_job_keys.py`; 2: `test_in_place_stop.py:355`; 3: `test_store.py:78` (drop the `positions` call and build `job("b", 5)` instead of `job("b", 1)`); 4: `test_units.py:206` (drop the call and its expected `"file only"` entry at `:213`); 5: `test_progress.py:198`); no test is deleted. Checked: no doc under `docs/plan` or `docs/decisions` names any of these members.
- Decision records: none apply (0016 describes the behaviour, not these members).
- Size: S; estimated lines: -31 source / -5 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (details only: 6 test files, not 4; item 3 and item 4 each need two edits in their test; all 7 items are dead as claimed, checked in `packages/*/src`, tests, `testing/`, `scripts/`)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md).

### QJ-05: Members of `jobs.py` and `mediatask.py` that no production code uses
- Kind: dead-code
- Where and now:
  1. `jobs.py:256-270` `job_from_preset` and `__all__` line 65: 0 production callers; 2 test calls (`tests/jobs/test_service.py:303,491`). It is a wrapper over `draft_from_preset` that drops the track draft. The `TrackDecision` import goes with it if nothing else uses it.
  2. `jobs.py:344-346` `JobService.detection_wait` (property): 0 callers except `tests/jobs/test_service.py:369`. The code reads `self._detection_wait`.
  3. `mediatask.py:99` `MediaTaskContext.events` (and the `EventBus` import, line 20): 0 reads in `analysis/`, `preview/`, `probe/`, `mediatask.py` (grep `ctx.events`, `media.events`, `tctx.events`). It is set at 4 construction sites: `service.py:974-983`, `tests/test_mediatask.py:117`, `tests/analysis/test_analysis_tasks.py:111`, `tests/preview/helpers.py:182`. The task manager has its own event bus.
  4. `mediatask.py:63-66` `SourceAccess.store`: the Protocol member that no task uses (the scans call `update`; `analysis/__init__.py:28,43` docstrings name `ctx.sources.store` wrongly). `SourceService.store` (`service.py:442`) has 0 production callers too; it is used by `tests/test_mediatask.py:196,214` and `tests/test_service_nul_paths.py:99` to seed a source.
- Change: delete 1, 2 and 3. For 4: drop the member (and its docstring mention) from `SourceAccess`; optionally also delete `SourceService.store` (cross-area: `service.py`) and let the 3 tests seed with `update(source, lambda _latest: source)`. If `SourceService.store` goes, the plan rows must go in the same commit.
  Same commit: `docs/plan/06-web-app.md:218` (`jobs.detection_wait`) and, for the optional part of 4, `:224` (`sources.store`, `sources.update` becomes `sources.update`) edit the "Not exposed" table: `tests/test_facade_coverage.py` fails on a row whose member no longer exists.
- Behaviour: unchanged.
- Contracts touched: public core API (`reframe.jobs.job_from_preset`, `JobService.detection_wait`, `MediaTaskContext.events`, and optionally `SourceService.store`). No HTTP or persisted change.
- Callers to update: the 4 `MediaTaskContext(...)` sites (drop `events=`); `tests/jobs/test_service.py:303,491` (use `draft_from_preset(...)`, which returns `(job, tracks, notes)`); `tests/jobs/test_service.py:362-369` (`test_detection_wait_default_is_read_at_creation`: assert `service(Stubs())._detection_wait == 1.5`).
- Tests: no test deleted; the changes above.
- Decision records: for 1, 2, 3 and the `SourceAccess.store` part of 4, none (0030 lists the facade members, and none of these is one of them). For the optional deletion of `SourceService.store`: 0030 (the contract table, line 37: `sources.store(source)`) and 0049 item 11 (line 113: `sources.store` and `sources.update` "not exposed") name it, so that part needs a note in 0030 as well as the plan row. 0051 requires the plan table to match.
- Size: S; estimated lines: -23 source / -6 tests
- Risk: low
- Depends on: none
- Confidence: high (1, 2, 3), medium (4: public member of `SourceService`, named in 0030)
- Verdict: ADJUSTED (4: the optional deletion of `SourceService.store` is in the 0030 contract table and 0049 item 11; the claim "0030 does not require these" holds only for 1, 2, 3 and the protocol member; items 1, 2, 3 confirmed, the 4 `MediaTaskContext(...)` sites and the 2 test calls of `job_from_preset` checked)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md). Items 1-3 and the protocol member are Tier A (Q-6.9). Item 4 (`SourceService.store`) is Tier C: 0030's contract table and 0049 item 11 name it.

### QJ-06: The same three service protocols are written three times
- Kind: duplication
- Where: tools: `queue/runner.py:80-83` (`ToolsSource`), `jobs.py:94-97` (`ToolDiscovery`), `mediatask.py:47-50` (`ToolsLookup`). Capabilities: `queue/runner.py:86-92` (`CapabilitiesSource`), `jobs.py:100-106` (`Capabilities`), `mediatask.py:80-86` (`CapabilitiesLookup`); also `cli.py:1038-1043` (`_CapabilitySource`, cross-area). Sources: `queue/runner.py:95-104` (`SourceProber`) equals `mediatask.py:53-77` (`SourceAccess`) without `store` and `update`; `jobs.py:78-81` (`SourceProber`) has only `probe(path)`.
- Now: 3 identical `status()` protocols and 3 identical `snapshot` + `wait()` protocols, each used as the type of one constructor parameter (`QueueService`, `JobRunner`, `JobService`, `MediaTaskContext`). The real objects (`ToolsService`, `CapabilityService`, `SourceService`) satisfy all of them. 0 other users: the names appear only in their own module plus `queue/service.py:46-50` (imports). The test stubs show why the jobs one differs: `tests/jobs/conftest.py:137` `Stubs.probe(path)` takes no keywords.
- Change: keep one `ToolsLookup` and one `CapabilitiesLookup` in `mediatask.py` (it already holds them, and `jobs.py` already imports from it) and import them in `queue/runner.py`, `queue/service.py` and `jobs.py`; delete the other four. Make the runner's `SourceProber` the base of `SourceAccess` (`class SourceAccess(SourceProber, Protocol)` adds `update`), or keep `queue.runner.SourceProber` as the single probe protocol and import it into `mediatask.py`. Leave `jobs.SourceProber` (different signature). Remove the deleted names from the two `__all__` lists. Check `uv run python -c "import reframe.queue, reframe.jobs"` for an import cycle (`reframe.tools` imports `reframe.mediatask`, and `mediatask` imports `reframe.tools.CancelToken`; the edge `queue -> mediatask` is new).
- Behaviour: unchanged.
- Contracts touched: none (the protocols are not part of the API; 0 uses in the server, tests or scripts).
- Callers to update: `queue/runner.py:197-199`, `queue/service.py:46-50,203-205`, `jobs.py:316-319`.
- Tests: none.
- Decision records: none.
- Size: S; estimated lines: -22 source / 0 tests
- Risk: low (type-check only; run `uv run mypy` and `uv run mypy --platform win32`)
- Depends on: QJ-05 if `SourceAccess.store` is removed first (else keep `store` out of the shared base)
- Confidence: medium
- Verdict: CONFIRMED (the protocols are identical; no test, script or server code names them; `import reframe.mediatask` already loads before `reframe.queue` in `reframe.service`, and `mediatask` imports nothing from `queue`, so the new edge `queue -> mediatask` makes no cycle; tests are type-checked too (`files` in `[tool.mypy]` includes `packages/*/tests`))
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md).

### QJ-07: The store refuses a too-deep document when it writes; a refusal at `add` would remove that machinery
- Kind: decision-change
- Where: `packages/reframe/src/reframe/queue/store.py:97-102` (`_Refused`), `:141-150` (`_document`), `:153-173` (`row_of`: three `functools.partial` dumps and the marker), `:176-180` (`_refused`), `:271-272` (`self._refused`), `:351-380` (`QueueStore.upsert` filter loop and the `queue.job_not_saved` warning), module docstring lines 14-18; `queue/service.py` (no change, `row_of` keeps its signature).
- Now: decision 0016 (follow-up 1i, "JSON nested more than 64 levels") says a document nested more than 64 levels is never written: `row_of` puts a marker string in the column, `upsert` leaves the row out, the job stays in the queue in memory, and one `queue.job_not_saved` warning is published per job. About 45 lines of code and, in `tests/queue/test_store_nesting.py`, the tests at `:243-300` and `:316-end` (about 60 lines). The decision says that only a hand-made or API-made document can be that deep (Reframe's own documents need fewer than 10 levels), and the only way such a document enters the store is `QueueService.add` (`settings` is not edited after that; `plan` and `issues` come from the planner and validator).
- Change: only if the decision is changed. What would have to be true: a job that cannot be saved is acceptable as "refused at add" instead of "runs, but is not saved". Then `QueueService.add` checks the document once (for example `too_deep(settings.model_dump(mode="json"))`, with `ValueError` and `RecursionError` caught) and adds the job as `failed` with a `queue.too_deep` error issue, exactly as it adds a job with validation errors. `_Refused`, `_document`, `_refused`, `self._refused`, the `upsert` loop and the `queue.job_not_saved` warning go; `row_of` is a plain tuple. **Gap found in verify**: a job added as `failed` still holds its deep `settings` and is written by `add` (`_save_many`), so `row_of` could not become a plain tuple, and the next start would skip that row as damaged (`queue.rows_skipped`). The change only works if `add` refuses the document before it builds the `QueueJob` (and before `job.model_copy(deep=True)` and `_runner.check`, which also see the deep document), by raising `ValueError` (the routes then need a 4xx mapping) or by returning a failed job whose `settings` are replaced, not kept. The load side (`_parse`, `_derived`, `_TooDeep`, the skipped-row warning) stays: a hand-edited file must still load. A cleaner place for the same rule is the persisted-document model (`DocumentModel`, which has `extra="allow"`), because settings and presets have the same rule (0015 section 3); that is another area.
- Behaviour: changes. A job nested more than 64 levels (API only) is `failed` with an error at `add` instead of running unsaved with a warning.
- Contracts touched: persisted queue file (no change to the file), HTTP/WS: `app.warning` code `queue.job_not_saved` disappears and a new issue code or an error response appears (checked: `job_not_saved` is not in `frontend/src` or `packages/reframe-server/src`; `docs/status.md:68` and decision 0016 name it).
- Callers to update: `service.py` `add` (one check), the tests below.
- Tests: delete the write-side tests in `tests/queue/test_store_nesting.py` (`test_a_job_nested_too_deeply_is_never_written` `:239-271`, `test_deep_issues_are_never_written` `:274-283`, `test_a_store_that_saves_nothing_gives_no_warning` `:286-293` (needs QJ-11's `read_only` or goes), and the keep-a-deep-job half of `test_the_queue_starts_with_a_deep_row_and_keeps_a_deep_job` `:316-326`); add one `add` test. The load-side tests stay. 0016's consequence "A job of 65 levels goes through `QueueService.add` (tested end to end)" also changes.
- Decision records: 0016 (follow-up 1i, point 2 "Writing"), 0015 section 3. Needs a new record and a note in 0016.
- Size: M; estimated lines: -45 source / -60 tests (not counted in the total)
- Risk: medium. It changes what a user of the API sees for a very odd input; the check must run before anything that walks the document (`model_copy(deep=True)`, validation, `model_dump`; the decision records that `model_dump` raises `ValueError` past 255 levels).
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (the proposed "failed job with an issue" still carries the deep settings and would be written, so the write-side machinery cannot go with it; `add` must refuse before building the job; frontend and server grep for `job_not_saved` done: no hits)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### QJ-08: Four copies of the same `ToolsService` stub and two of the same `CapabilityService` stub in the tests
- Kind: tests
- Where: `Tools.status()` stubs: `tests/test_mediatask.py:63-69` (`_Tools`), `tests/analysis/test_analysis_tasks.py:50-56` (`_Tools`), `tests/preview/helpers.py:90-96` (`Tools`), `tests/queue/conftest.py:165-170` (`StubTools`); the shared one already exists: `testing/reframe_testing/capabilities.py:36-56` (`StubTools`, a superset with `gate`, `calls`, `current`). Fixed-snapshot stubs: `tests/test_mediatask.py:94-100` (`_Caps`) and `tests/analysis/test_analysis_tasks.py:83-89` (`_Caps`) are identical (8 lines each). `_Sources` in those two files (`:71-92`, `:58-81`) differ only in `probe` returning a deep copy and in how `update` picks its base.
- Now: 6 copies of 4 to 8 lines of the same stub; `MediaTaskContext(...)` is also built by hand in 3 test files with almost the same arguments.
- Change: use `reframe_testing.capabilities.StubTools` in the four places; add one `FixedCaps` (and, if wanted, one `StubSources` with the `store` and `update` list) to `testing/reframe_testing/` and import it in `test_mediatask.py` and `test_analysis_tasks.py`. Leave `preview/helpers.py` `Sources`/`Caps` (real prober, `detected` snapshot) and `queue/conftest.py` `StubCaps`/`StubSources` (own semantics) alone.
- Behaviour: unchanged (tests only).
- Contracts touched: none (the `testing/` package is test support, decision 0004).
- Callers to update: the 4 test modules named.
- Tests: all tests in them stay; only the stub definitions go.
- Decision records: 0004 (shared testing package).
- Size: S; estimated lines: -0 source / -40 tests
- Risk: low
- Depends on: QJ-05 if `SourceAccess.store` is removed (then the shared sources stub has no `store`)
- Confidence: high
- Verdict: CONFIRMED (the four `Tools` stubs have the same body; `reframe_testing.capabilities.StubTools(tools)` takes the same constructor argument and keeps `.tools`; the two `_Caps` are identical; the two `_Sources` differ as stated)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md). It is made with the other queue findings, because it edits the same test files.

### QJ-09: `closed_error()` and two more lazy imports exist only to reach one exception class
- Kind: structure
- Where: `packages/reframe/src/reframe/queue/errors.py:17,43-47` (`closed_error`), used at `queue/runner.py:45,253,793` and `queue/service.py:40,988`; `packages/reframe/src/reframe/capabilities/service.py:63-72` (`_closed_error`, `_is_closed_error`, used at `:206,257`); the class is `packages/reframe/src/reframe/service.py:103-107` (`ReframeClosedError`).
- Now: `reframe.service` imports `reframe.queue` and `reframe.capabilities`, so those packages cannot import `ReframeClosedError` from it. The queue wraps the lazy import in a function that returns the class (so the runner writes `closed = closed_error()` and `except (_Stopped, closed_error()):`); the capability service has two such functions. Two packages, three functions, one 4-line class.
- Change: move `ReframeClosedError` to a leaf module with no imports (for example `packages/reframe/src/reframe/errors.py`) and have `reframe.service` re-export it (`from reframe.errors import ReframeClosedError`, kept in `__all__`). The queue and the capability service import it at module level: `except (_Stopped, ReframeClosedError):`, `raise ReframeClosedError`. Delete `closed_error`, `_closed_error`, `_is_closed_error`.
- Behaviour: unchanged (same class, same message).
- Contracts touched: public core API (`reframe.service.ReframeClosedError` keeps its import path; server imports it at `reframe_server/errors.py:17` and `routers/preview.py:14`).
- Callers to update: `queue/runner.py:45,253-254,793`, `queue/service.py:40,988`, `capabilities/service.py:63-72,206,257`.
- Tests: none change (they import `ReframeClosedError` from `reframe.service`).
- Decision records: none.
- Size: S; estimated lines: -13 source / 0 tests
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (only these three lazy-import helpers exist; `ReframeClosedError.__module__` changes to `reframe.errors`, which no test, handler or message uses)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md).

### QJ-10: "Tool is found and has a path" is written seven times
- Kind: duplication (cross-area: service, capabilities, preview, validation)
- Where: `service.py:110-112` (`tool_usable`; callers `service.py:629`, `cli.py:97,540,1029,3307`, `tests/test_service.py:33,280`); `queue/runner.py:185-186` (`_usable`, used at `:406`); `mediatask.py:127-130` (inline in `require_tool`); `preview/clip.py:239`; `capabilities/service.py:275`; `capabilities/detect.py:483`; `validation/dryrun.py:480`. (`tools/__main__.py:57` tests the status only; not this.)
- Now: `info.status is ToolStatus.FOUND and info.path is not None` (or its negation) appears as 1 function in the facade, 1 private copy in the runner, and 5 inline copies (`mediatask.py`, `preview/clip.py`, `capabilities/service.py`, `capabilities/detect.py`, `validation/dryrun.py`): 7 places, not 8.
- Change: add a property `ToolInfo.usable` to `models/tools.py` (`return self.status is ToolStatus.FOUND and self.path is not None`; a plain property is not part of the pydantic schema, so there is no OpenAPI change) and use it everywhere; delete `tool_usable` (update the 4 `cli.py` uses and 1 test) and `_usable`. Where code uses `info.path` right after the check, keep an `assert info.path is not None` for mypy (the runner already does).
- Behaviour: unchanged.
- Contracts touched: public core API (`reframe.service.tool_usable` is in `service.__all__`; its only users are `cli.py` and one test). Optionally keep `tool_usable` as a one-line alias.
- Callers to update: the 7 places above.
- Tests: `tests/test_service.py:280` uses `tool_usable`; change it to `.usable`. Add one model test for the property.
- Decision records: none.
- Size: S; estimated lines: -6 source / 0 tests (the facade function and the runner copy are 3 lines each; each of the 5 inline sites is one line for one line, and mypy needs an `assert info.path is not None` at the sites that pass `.path` on, such as `capabilities/service.py` and `capabilities/detect.py`)
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (7 places, not 8; 5 inline copies, not 6; net saving about -6 lines, not -10; checked that `tool_usable` has no user besides `cli.py`, `service.py:629` and `tests/test_service.py`)
- Orchestrator: Tier B, work package Q-6.18 (see ../plan.md).

### QJ-11: The "private store in memory" is `read_only` with extra steps
- Kind: structure
- Where: `packages/reframe/src/reframe/queue/store.py:19` (module docstring), `:268` (`self.memory`), `:279-282` (`use_memory`), `:363` (`not self.read_only and not self.memory`), `:394-396` (`_connect`: the `:memory:` branch); callers `queue/service.py:614,626`.
- Now: a process that does not own the queue lock calls `use_memory()`. Its store then creates a real SQLite database in RAM and writes every job change into it, and nothing ever reads it back (`load` is never called in that state; the jobs live in `QueueService._jobs`). `read_only = True` already gives the same result: `_open_for_write` returns `None`, nothing is written, and the `queue.job_not_saved` warning is suppressed by the same condition.
- Change: `QueueService._ensure_open` sets `self._store.read_only = True` in the two places; delete `memory`, `use_memory`, the `_connect` branch and the `not self.memory` term. Update the docstring of `read_only` ("nothing is written": newer file, unreadable file, or another process owns it).
- Behaviour: unchanged for users (no file is written either way; a job change no longer fills a RAM database).
- Contracts touched: none.
- Callers to update: `service.py:614,626`; `tests/queue/test_queue.py:817` (`assert h.queue._store.memory` becomes `.read_only`); `tests/queue/test_store_nesting.py:286-293` (`store.use_memory()` becomes `store.read_only = True`).
- Tests: no test deleted.
- Decision records: 0027 (a second process keeps a private queue and does not touch the file) is kept as it is.
- Size: S; estimated lines: -10 source / 0 tests
- Risk: low
- Depends on: none (if QJ-07 lands, the `not self.read_only` term goes with the loop)
- Confidence: high
- Verdict: CONFIRMED (`load` is never called after `use_memory` in `_ensure_open`; nothing reads the RAM database back; `read_only` is read only inside `store.py`; `test_a_store_that_cannot_be_written` keeps passing since `_open_for_write` then makes no connection at all)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md).

### QJ-12: Defensive branches for a call outside an event loop
- Kind: defensive
- Where: `packages/reframe/src/reframe/queue/service.py:661-666` (`_ensure_open`: `except RuntimeError` after `get_running_loop`, which runs `_remove_leftovers` inline), `:795-798` (`_want_keys`: the same try/except). The third guard of the first version of this finding, `:1040-1047` (`_call`: `except RuntimeError` for a save after `close()`), is **not** part of the change (see Verdict).
- Now: `_ensure_open` runs on the first call to `list()`, `get()`, `log_path()` and the async methods. Every production caller is on the event loop thread: the server's `owner.start` runs in the lifespan (`reframe_server/owner.py:64`), the route handlers are `async def`, and the CLI calls the queue from coroutines. No test calls the queue outside a loop (`tests/queue/` has no sync test that builds a `QueueService`; `coverage.txt` shows `service.py` lines 663-666 and 797-798 never run in the whole suite, and I found no test that names them). (Not so for the `_call` guard: it is for a save after `close()`. `close()` waits for the active and background tasks, but not for a public method that is waiting for `self._lock`: `add`, `remove` and `retry` call `_check_open()` before `async with self._lock:` and not after, and `remove` saves twice in the lock. If `close()` ends the store in between, `submit` on the shut-down store raises `RuntimeError`; `coverage.txt` shows `:1044-1045` never run, but the race is real.)
- Change: remove the two guards: call `asyncio.get_running_loop()` without a try (a first `list()` outside a loop would raise `RuntimeError: no running event loop`), drop the `leftovers` inline branch and the `_want_keys` try/except. Keep the `except RuntimeError` in `_call`. If any caller outside a loop is found, keep the first guard only.
- Behaviour: changes only for a caller outside an event loop (none found): its first `list()` raises instead of running the clean-up inline.
- Contracts touched: public core API (`QueueService.list`/`get` before a loop exists).
- Callers to update: none found; ask the owner before removing if a script or the desktop shell calls `Reframe.queue.list()` from a sync thread.
- Tests: none.
- Decision records: none (grep for "outside a loop" in `docs/` found nothing).
- Size: S; estimated lines: -8 source / 0 tests
- Risk: low for the two remaining guards (no caller outside a loop in `packages/*/src`, `scripts/`, `testing/`; `_schedule` already calls `get_running_loop()` unguarded at `:729`)
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (the `_call` guard is reachable: `add`, `remove`, `retry` re-check `_check_open()` before taking `self._lock`, not after, so a save after `close()` can happen; it is dropped from the change; -8 lines; "Depends on" of QJ-14 unchanged)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### QJ-13: `HeaderEditResult.file_state` is optional, but the writer always sets it
- Kind: defensive (cross-area: metadata)
- Where: `packages/reframe/src/reframe/metadata/header.py:111` (`file_state: HeaderFileState | None = field(default=None, kw_only=True)`), `queue/runner.py:871-890` (`_FILE_STATE`, `_UNKNOWN_STATE`, `_STATUS_STATE`, `_state_text`).
- Now: all 7 places in `header.py` that build a `HeaderEditResult` set `file_state` (`:633,637,640,644,662,666,693`). Only test code builds one without it (8 sites: `tests/queue/conftest.py:139`, `tests/queue/test_in_place_stop.py:33`, `tests/queue/test_faults.py:299`, `tests/metadata/test_metadata_edit_real.py:372,396,408,700`, `tests/preview/test_clip.py:334`). `_STATUS_STATE` exists only to guess a state for such a result.
- Change: make `file_state` required, delete `_STATUS_STATE` and the fallback in `_state_text` (`return _FILE_STATE[result.file_state]`); keep `_UNKNOWN_STATE` (the writer-raised-an-exception path in `_to_its_end` uses it).
- Behaviour: unchanged for every real result.
- Contracts touched: none (`HeaderEditResult` is a dataclass in the writer, not a model of the API).
- Callers to update: the 8 test sites above (add `file_state="new"` or `"unchanged"`; the `failed` case of `test_metadata_edit_real.py:406-410` is removed).
- Tests: no test deleted.
- Decision records: 0080 item 1 writes the field as `file_state: Literal[...] | None` with keyword-only defaults, and item 4 gives the text "Reframe cannot tell what the file holds now." "when the result says nothing (a writer that raised)". The states stay; the `| None` and the default change the contract in 0080, so add a one-line note to 0080 in the same commit.
- Size: S; estimated lines: -8 source / 0 tests
- Risk: low
- Depends on: none
- Confidence: low (value is low; one test case tests the `None` branch on purpose)
- Verdict: ADJUSTED (8 test sites without `file_state`, not 7: `tests/queue/conftest.py:139`, `test_in_place_stop.py:33`, `test_faults.py:299`, `test_metadata_edit_real.py:372,396,408,700`, `tests/preview/test_clip.py:334`; the parametrised case at `test_metadata_edit_real.py:406-410` asserts "Reframe cannot tell what the file holds now." for a `failed` result without a state, so it is deleted or moved to the writer-raised path (`test_faults.py` `test_a_writer_that_raises_is_an_internal_error`); 0080 names `| None` and the default)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### QJ-14: Three functions over the default complexity limits can be split without changing behaviour
- Kind: structure
- Where: `queue/runner.py:357-435` (`JobRunner._steps`: complexity 15, 10 returns, 14 branches), `queue/runner.py:753-` (`_edit_in_place`: complexity 14, 7 returns), `queue/service.py:598-674` (`QueueService._ensure_open`: complexity 14, 13 branches) (`complexity.txt`; the limits are ruff's `C901`/`PLR09xx` defaults, which the project's `[tool.ruff.lint] select` does not enable, so no check fails today).
- Now: `_steps` mixes the pre-flight (source clash, plan files), the loop, and for each tool step the tool lookup and the `resolve_argv` failure texts. `_edit_in_place` mixes the loop with the check of the edited source. `_ensure_open` mixes taking the lock with restoring the store.
- Change (optional, no net lines): `_steps`: extract `async def _preflight(job, plan, source) -> Outcome | None` (lines 365-382; it awaits `asyncio.to_thread`) and `_tool_argv(step, prepared, values, plan) -> tuple[ToolInfo, list[str]] | Outcome` (lines 400-420). `_edit_in_place`: extract `_check_edited(job, active, joblog, prepared, source, tracker, plan) -> Outcome` for the part after the `try` block. `_ensure_open`: extract `_acquire_owner() -> bool` (lines 609-635) and `_restore(loaded)` (lines 636-674). Do this last, after QJ-04 and QJ-12, so the line numbers do not move twice.
- Behaviour: unchanged.
- Contracts touched: none.
- Callers to update: none (private).
- Tests: none change; `tests/queue/` is the guard.
- Decision records: none.
- Size: M; estimated lines: 0 / 0
- Risk: low
- Depends on: QJ-04, QJ-12
- Confidence: low (value is low: no lint gate asks for it)
- Verdict: ADJUSTED (the limits are not part of the project's lint; `_preflight` must be `async`; line anchors 357, 753, 598 confirmed; confidence low)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

## Looked at and kept

- `QueueStore` runs every call on one dedicated thread (`submit`, `asyncio.wrap_future`): the order of writes is the point (0016 "one writer"); `asyncio.to_thread` would not keep it.
- File keys, `_Keys`, `_keys`/`_keying`/`_unchecked`, `_want_keys`, `_keys_in_background`, `_claim(skip=)` and `_written_key` in `queue/service.py`: 0016 follow-up RB-1 (the event loop never waits for a share) and 0061/0062 R1 B1 (an `add` or `retry` never waits for a restored job's keys; the restored job fails later on a clash). About 120 lines, but each part answers a recorded blocker.
- `ActiveJob.control` lock, `holds_inhibit`, `_hold_inhibit`/`_release_inhibit`, `_resumed_for_stop` and the `resumed` callback: 0016 follow-up items 3 to 4 and RB-5 (pause, resume, cancel and the sleep inhibit must not interleave; a paused in-place edit that a stop resumes is shown running).
- `LockBackend` protocol with `FlockBackend` and `MsvcrtBackend`, `StoreLock`: 0027 and the Windows rules (0053); both backends are unit-tested with mocks.
- `Clock` protocol with one real class: the tracker and watchdog need `monotonic` and `wall` together (0016 sleep-aware ETA) and tests replace the clock.
- `QueueLike` protocol: two implementations (`QueueService` and `reframe.remote.RemoteQueue`) (0061).
- `read_saved_queue` (`queue/client.py`): 3 callers in `cli.py` (`_now` `:2246`, `_owner_or_saved` `:3001`, `_saved_state` `:3119`) that read the jobs when no process owns the queue (0061). It repeats the version check and the row loop of `QueueStore.load` (about 10 lines); the two differ on purpose (read-only, immutable fallback, no lock).
- `_text`/`_untext`/`_path`/`_unpath` (BLOB for lone surrogates) and `printable` next to `models.text.replace_undecodable`: 0016 point 5 and 0044 say both stay (log lines and job errors show the escape, display text shows the replacement character).
- `loudnorm._UNKNOWN` (NaN "never seen"): 0016 decides it.
- `start(job_ids=)`, `only`, `processing`, `QueueProcessingEvent`: 0042 and 0064; the CLI and `POST /api/queue/start` use them (`cli.py:2101,2176,3221`, `routers/queue.py:125,156`).
- `QueueJob.log_path` is stored and returned although it is `log_file(data_dir, id)` for every job: the plan lists the column (`05-core.md:477`) and the API field (`06-web-app.md:178`) and the frontend schema has it; every reader's `job.log_path or log_file(...)` fallback is for jobs without one. Not worth a schema change.
- `OutputClaims` (`jobs.py`) and `QueueService._claim`: different scope (one command; the whole queue), different issue codes (`batch.*`; `queue.output_claimed`), both decided (0040, 0016/0042). `jobs.file_key` is the string form of `queue.files.FileKey` by 0040's follow-up.
- `JobService._validate` (waits at most 60 s for encoder detection) and `JobRunner._prepare` (waits for it without a limit, cancellably): the rules differ on purpose.
- `JobRunner._steps` `header_edit` branch next to `_edit_in_place`: different stop semantics for a write that already happened (0034, 0080).
- `JobService.search_options`, `hdr_metadata`, `job_type`, `output_chapters`, `rendered_tags`: thin, but they bind the service's definitions and the server's routes call them (`routers/definitions.py:90`, `routers/jobs.py:334,348,359,370,385`).
- `JobRunner.persist` callback and `QueueService.__init__` seams (`stall_after`, `step_time_limit`, `watchdog_tick`, `log_interval`, `lock_backend`, `clock`, `fs`, `inhibitor`, `definitions`): test seams for time and files; the facade passes only `naming` and `power`.
- `QueueStore` `BEGIN IMMEDIATE`, `busy_timeout`, WAL, `synchronous=FULL`: power-cut safety (0016) and the readers of `read_saved_queue`.
- `tests/jobs/fake_queue.py` (`FakeQueue`, 268 lines): 63 references in the CLI tests (`conftest.py`, `test_cli_encode.py`, `test_cli_when_done.py`, `test_cli_robustness.py`, `test_cli_batch.py`); replacing it with the real queue plus the fake FFmpeg would touch many tests for little gain.
- `queue/progress.py`, `queue/watchdog.py`, `queue/whendone.py`, `queue/verify.py`, `queue/process.py`, `queue/lock.py`, `queue/logs.py`: read in full; each is small, pure or decided (0016, 0037) and has no unused member beyond the items in QJ-04.

## Noted by the verifier (not verified)

- QJ-01 (removes `TaskManager.limit`) and the server-service area's finding that deletes the `tasks.limit("probe_folder")` assert (`docs/simplify/areas/server-service.md:65`) touch the same test lines; make them in one commit or in a fixed order.
- QJ-02: the retry is also used by the server's endpoint file (`reframe_server/owner.py`, `login.py` write through `JsonDocumentFile`), so the Windows VM check should include the owner-publish test (`test_owner.py`, the case at `:365-390`).
- `docs/core-breakdown.md:75,157` names `job_from_preset`, `ToolsLookup`, `CapabilitiesLookup` and `SourceAccess`; it is a work-breakdown document, not the spec, and does not need to change with QJ-05 or QJ-06.
