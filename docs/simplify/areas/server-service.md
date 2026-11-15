# server-service: simplification findings

Commit: 85d9dcb. Scope: `packages/reframe-server/src/reframe_server/` (all files), `packages/reframe/src/reframe/service.py`, `packages/reframe/src/reframe/events.py`, and their tests (`packages/reframe-server/tests/`, `packages/reframe/tests/test_service*.py`, `test_events.py`, plus `testing/reframe_testing/server.py`). Source lines: 4030 (server) + 828 (`service.py`) + 208 (`events.py`) = 5066. Read in full: every file of `reframe_server/` (all routers, `security.py`, `login.py`, `events.py`, `parent.py`, `owner.py`, `idle.py`, `static.py`, `folders.py`, `filtertext.py`, `config.py`, `errors.py`, `api.py`, `app.py`, `__main__.py`, `openapi.py`, `deps.py`, `sources.py`), `service.py`, `events.py`, `testing/reframe_testing/server.py`, `tests/conftest.py`, `tests/test_media.py`, `tests/test_languages.py`, `tests/test_facade_coverage.py`. Also read for the findings: `probe/folder.py`, `probe/prober.py` (`_prepare`), `batch/service.py` (`_probe_all`), `presets/store.py` (rename, duplicate), the frontend files named below. Only skimmed or searched with `rg`: all other tests in the area, decisions 0030, 0045–0051, 0055–0060, 0064, 0071, 0078 (read where a finding touches them).

Verified: 2026-11-15, 0 confirmed, 8 adjusted, 0 rejected.

## Summary

The server is already thin. 87 routes, all in the plan; no route is dead; the only dead function in `reframe_server/` is `routers/jobs.py::without_output`. The complexity that remains is required by decisions (the request guards, login, jail, WebSocket hub, owner file, parent watch, media Range). The real waste is in three places. First, the folder probe: the core carries a folder-probe task that neither the CLI nor the server calls, while the server and `batch` each have their own copy of the "probe N files, 4 at a time" loop (SRV-01). Second, the facade (`service.py`) and the preset store carry public members that have no production caller (SRV-03), and the server ships a rendered language list whose only reason (langcodes was slow) was removed by decision 0082 (SRV-02). Third, test helpers are copied between files (SRV-05). Note: coverage numbers for `service.py` and `events.py` in `coverage.txt` are not usable (module-level lines show as missed, so the measurement began after import); callers were counted with `rg` instead. The shared coverage run also had one failure in this area, `tests/test_app.py::test_desktop_server_prints_the_ready_line_and_answers_health`; it was not investigated.

## Findings

### SRV-01: The folder probe is unused in the core, and the "probe N files at once" loop exists three times
- Kind: dead-code
- Where:
  - `packages/reframe/src/reframe/service.py:353-406` (`SourceService.probe_folder`), its imports at `:61-66`, `:21` (`JsonValue`), `:69` (`TaskContext`), `__all__` entry `"FolderProbeResult"` (`:76`), and the words "a folder (as a task)" in the `SourceService` docstring (`:246`).
  - `packages/reframe/src/reframe/probe/folder.py:36-37` (`DEFAULT_CONCURRENCY`, `TASK_KIND`), `:65-66` (`ProgressCallback`), `:106-119` (`FolderProbeResult`), `:122-189` (`probe_folder`), `:192-220` (`start_probe_folder`), the matching `__all__` entries (`:26-34`), and the imports they alone need. `MEDIA_EXTENSIONS`, `natural_key`, `list_media_files`, `_is_media` stay.
  - `packages/reframe/src/reframe/probe/__init__.py:16-22` and `:38-54` (re-exports of `FolderProbeResult`, `probe_folder`, `start_probe_folder`).
  - `packages/reframe/src/reframe/tasks.py:44` (`"probe_folder": 2` in `DEFAULT_LIMITS`), `packages/reframe/src/reframe/models/tasks.py:34` (docstring names `probe_folder`).
  - `packages/reframe-server/src/reframe_server/routers/sources.py:23` (`PROBES_AT_ONCE`) and `:95-143` (`probe`, the nested `work`: semaphore, `TaskGroup`, `outcomes` dict, `done` counter).
  - `packages/reframe/src/reframe/batch/service.py:53` (`PROBE_CONCURRENCY`; also in its `__all__` at `:48`), `:179-206` (`BatchService._probe_all`: semaphore plus `asyncio.gather`).
- Now:
  - `SourceService.probe_folder`: 0 callers outside tests. Callers: `tests/test_service.py:164`, `:210`, `:289`, `tests/test_service_nul_paths.py:108`; the CLI (`cli.py`) and the server never call it. Decision 0049 item 5 says the server does not expose it (it lists partial outputs and runs a second task per folder).
  - `start_probe_folder`: 0 callers outside `tests/probe/test_folder.py` (3 calls). `probe_folder()` (the function): called in production only by `SourceService.probe_folder` and `start_probe_folder`; tests call it from `tests/probe/test_folder.py`, `tests/probe/test_live.py:26,141,169,175,177` (real-media tests `test_season_folder` and the benchmark `test_probe_budgets`, which use a bare `Prober`, no facade) and `tests/probe/test_sampling.py:35,607` (`test_a_huge_timestamp_scale_does_not_fail_the_folder`). `FolderProbeResult`: used in production only by those three; tests import it in `tests/test_service.py:28`, `tests/probe/test_folder.py:17`, `tests/probe/test_live.py:26`. The string `"probe_folder"` as a task kind is also used in `packages/reframe-server/tests/test_tasks.py:22` and `packages/reframe/tests/test_events.py:43,48` (any string works there; rename for tidiness).
  - So the same job (list media files, probe 4 at a time with progress, keep the order) is written three times: `probe/folder.py:probe_folder` (+ the task wrapper twice: `start_probe_folder` and `SourceService.probe_folder`, which are the same 25 lines with a NUL check added), `routers/sources.py:probe.work`, and `batch/service.py:_probe_all`. The one that runs for users is the server's (task kind `probe_sources`). The frontend even lists `probe_folder` as "a kind the server starts" (`activityLines.test.ts:173`) but the server never starts it.
  - `folder.py`'s own comment says a `TaskGroup` is needed instead of `gather` so that a cancel waits for every ffprobe kill. `batch._probe_all` uses `gather`.
  - Sizes: `probe/folder.py` has 172 code lines, of which about 105 are the probe-folder part. `SourceService.probe_folder` is 54 lines.
- Change:
  1. In `service.py` add one method and one constant, and delete `probe_folder`:
     ```python
     PROBE_CONCURRENCY = 4

     async def probe_many(
         self, files: Sequence[str | os.PathLike[str]], *, concurrency: int = PROBE_CONCURRENCY,
         cancel: CancelToken | None = None, on_progress: Callable[[int, int], object] | None = None,
     ) -> list[MediaSource | ProbeError]:
         """Probe each file, ``concurrency`` at a time; results in the order of ``files``.
         After ``cancel`` no new ffprobe starts (the rest are CANCELLED errors)."""
         gate = asyncio.Semaphore(concurrency)
         results: list[MediaSource | ProbeError | None] = [None] * len(files)
         done = 0

         async def one(i: int, file: str | os.PathLike[str]) -> None:
             nonlocal done
             async with gate:
                 results[i] = (ProbeError(_absolute(file), ProbeErrorKind.CANCELLED, "The probe was cancelled.")
                               if cancel is not None and cancel.cancelled
                               else await self.probe(file, cancel=cancel))
             done += 1
             if on_progress is not None:
                 on_progress(done, len(files))

         async with asyncio.TaskGroup() as group:   # not gather(): see the cancel note in the old folder.py
             for i, file in enumerate(files):
                 group.create_task(one(i, file))
         return [r for r in results if r is not None]  # all are set
     ```
     (Keep the `TaskGroup` comment: a cancelled `gather` returns at the first child's end.)
  2. `routers/sources.py:probe.work` becomes: `found = await reframe.jobs.media_files(...)`, jail the files, `outcomes = await reframe.sources.probe_many(files, cancel=ctx.cancel, on_progress=lambda d, t: ctx.progress(done=d, total=t, message=f"{d}/{t} files"))`, then build the summary. Delete `PROBES_AT_ONCE`, the semaphore, the nested `one`, the `outcomes` dict and `sorted(outcomes.items())`. About 14 lines go.
  3. Delete `SourceService.probe_folder`, `probe.folder.probe_folder`, `start_probe_folder`, `FolderProbeResult`, `ProgressCallback`, `DEFAULT_CONCURRENCY`, `TASK_KIND`, the re-exports, `DEFAULT_LIMITS["probe_folder"]`, and the now-unused imports (`JsonValue`, `TaskContext` in `service.py`; `asyncio`, `dataclass`, `JsonValue`, `MediaSource`, `TaskInfo`, `Prober`, `TaskContext`, `TaskManager`, `CancelToken`, `missing_text`, `ProbeError*` in `folder.py` as the linter reports). Change the `TaskInfo.kind` docstring example to `probe_sources`.
  4. Optional second step: `batch/service.py:_probe_all` keeps its dedupe and the "a `MediaSource` is taken as it is" rule, but sends the path items through `probe_many` and drops `PROBE_CONCURRENCY` and its own gate (about -5 lines; the batch then also gets the cancel-safe `TaskGroup`).
  5. Plan and docs, same commit (CLAUDE.md rule): `docs/plan/05-core.md:184` (the "Folder probe" checkbox) and `:597` (the `probe_folder` word in the facade sketch), `docs/plan/06-web-app.md:223` (the `sources.probe_folder` row of "Not exposed"; `test_facade_coverage.py` fails on a row whose member no longer exists, so this row must go in the same commit), `docs/status.md` (`:60` C-3 row "folder probe as a task", `:72` C-15 row "a folder probe ends `done` with that error", `:164` "probe a folder as a task"), a new decision record that says the folder probe was removed because decision 0049 item 5 made the server do its own and no other caller exists. Decisions 0016 (RN follow-up), 0049 (items 5, 11), 0063, 0070 and 0081 mention `probe_folder` as history; leave them.
  6. Where `probe_many` lives: the real-media tests (`test_live.py`, `test_sampling.py`) call `probe_folder(prober, folder)` with a bare `Prober`. `SourceService.probe_many` needs a facade (or a fake `SourceService`), so decide in the step: either rewrite those three tests to loop over `Prober.probe` / build a `Reframe`, or make `probe_many` a module-level function in `probe/folder.py` that takes any `async probe(file, cancel=)` callable and let `SourceService` pass `self.probe`.
- Behaviour: unchanged for users. No encode, queue, setting or file is touched. The task kind `probe_folder` is never started today. The server's task kind `probe_sources` keeps its name, its message and its progress text.
- Contracts touched: public core API (removes `SourceService.probe_folder`, `reframe.service.FolderProbeResult`, `reframe.probe.probe_folder` / `start_probe_folder` / `FolderProbeResult`; adds `SourceService.probe_many`). HTTP/WS/OpenAPI: no route, field or schema changes. One text change in the OpenAPI document: the `TaskInfo.kind` description names `probe_folder` today (`frontend/src/api/schema.d.ts:6861`); after the docstring edit `scripts/gen-api.sh` rewrites that one comment line (the `api-contract` CI check needs the regenerated file). Frontend: the dead `probe_folder` kind goes from `frontend/src/components/queue/activityLines.ts:145-146`, `frontend/src/i18n/messages/en/queue.json:196` and, in `activityLines.test.ts`, both the `'probe_folder'` entry (`:173`) and its expected text `'Reading a folder: cancelled'` (`:187`). Desktop (`desktop/`), `scripts/`, `testing/`: no use of `probe_folder`.
- Callers to update: `tests/test_service.py` (`:28` import, `:157-172`, `:206-211`, `:280-297`, `:315-365`), `tests/test_service_nul_paths.py:104-125`, `tests/probe/test_folder.py:125-302`, `tests/probe/test_live.py` (`:26` import, `:140-153`, `:156-185`), `tests/probe/test_sampling.py` (`:35` import, `:596-608`), `tests/test_tasks.py:178`, `packages/reframe-server/tests/test_tasks.py:22` and `tests/test_events.py:43,48` (kind string only), the three frontend files above, the plan files above.
- Tests:
  - Delete: `tests/probe/test_folder.py` tests from `test_probe_folder_limit_order_progress` (`:125`) to the end (8 tests: `test_probe_folder_limit_order_progress`, `_custom_limit`, `_problems`, `test_folder_task_events`, `test_folder_task_with_fake_ffprobe`, `test_cancel_folder_task_kills_ffprobe`, `test_cancelling_probe_folder_reaps_every_ffprobe`, `test_no_new_probe_after_a_cancel`; about 178 lines, with `FakeProber`, `_fake_prober`, `_proc`; `test_natural_key`, `test_list_media_files`, `test_recursive_skips_hidden_folders` stay), `test_service.py::test_close_cancels_folder_probe_and_kills_ffprobe` (`:157-172`), `test_probe_folder_emits_task_events` (`:315-365`), the `probe_folder` lines inside `test_async_with_closes` (`:209-210`) and the probe-error test (`:288-297`), `test_service_nul_paths.py::test_folder_probe_of_a_nul_path_is_one_error`, the `tasks.limit("probe_folder")` assert.
  - Rewrite (not delete): `test_live.py::test_season_folder` and `::test_probe_budgets` (real media, the benchmark of a 24-file folder, cold and cached) and `test_sampling.py::test_a_huge_timestamp_scale_does_not_fail_the_folder`: list the files with `list_media_files` and probe them with the replacement (see point 6 of Change).
  - Add (about 55 lines, in `tests/test_service.py` or `tests/probe/`): `probe_many` keeps the order and the limit of 4 (port `test_probe_folder_limit_order_progress`), reports progress, starts no probe after a cancel (port `test_no_new_probe_after_a_cancel`, `:286`), and a cancel kills every ffprobe (port `test_cancelling_probe_folder_reaps_every_ffprobe`, `:269`). Keep the server's `test_sources.py` tests as the guard of the task result.
- Decision records: 0049 item 5 (server expands folders itself; keeps), 0016 RN follow-up (a NUL path is `not_found`: still holds through `probe`/`_check_file`). The new record must say that C-3's "folder probe" checkbox is replaced by `probe_many`.
- Size: M; estimated lines: -170 source / -215 tests (-270 deleted, +55 added)
- Risk: low. The server's probe task is the only user path, and its `test_sources.py` tests stay. The point to check: a cancelled task must still kill every ffprobe and start none after the cancel (the ported tests guard it). Two differences in the server task, both harmless: the server today passes no cancel token to `sources.probe` (it relies on the task's `CancelledError`; `probe_many(cancel=ctx.cancel)` adds the token), and `probe_many` through `SourceService.probe` hands one shared token to many `probe` calls, whose `_enter`/`_leave` keep tokens in a set, so the first call to end discards the shared token from `SourceService._tokens` (then `SourceService.close()` no longer cancels the others through it). In the server this does not matter because `Reframe.close()` runs `tasks.close()` before `sources.close()`; a caller outside a task that passes `cancel=` would need `_tokens` to count users, or `probe_many` should give each call its own token that is linked to `cancel`.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (callers were incomplete: `tests/probe/test_live.py`, `tests/probe/test_sampling.py` and two kind-string tests also use `probe_folder` and need a rewrite, 8 tests not 7 in `test_folder.py`, `docs/status.md:72,164` and the frontend test's expected text added, the shared-token point added to Risk, where `probe_many` lives to be decided; the dead-code claim, the 0049 item 5 reading, the server and batch loop copies and the contracts otherwise hold)
- Orchestrator: Tier B, work package Q-6.14 (see ../plan.md).

### SRV-02: Ship no pre-rendered language list (decision 0071 item 2 no longer holds after 0082)
- Kind: decision-change
- Where:
  - `packages/reframe-server/src/reframe_server/routers/languages.py:47-83` (`LANGUAGES_FILE`, `render`, `_body`, the `__main__` block, imports `resources`, `sys`, `Path`).
  - `packages/reframe-server/src/reframe_server/data/languages.json` (73,834 bytes, one line, generated).
  - `packages/reframe-server/tests/test_languages.py:32-35` (`test_the_shipped_list_is_the_built_one`).
  - `desktop/sidecar/sidecar.spec:14` (`"reframe_server",  # GET /api/languages answers 500` in `DATA_PACKAGES`: `languages.json` is the only data file the frozen server needs; `collect_data_files("reframe_server")` also collects the package's empty `py.typed`, which nothing reads when frozen).
- Now: decision 0071 item 2 ships the language list rendered because building it from `langcodes` took 277 ms at the first `GET /api/languages` (135 ms langcodes, 71 ms `language_data`). Decision 0082 (built 2026-11-15, C-20) replaced `langcodes` and `language_data` by a generated table that `reframe.languages` reads from `definitions/data/language-*.json.gz`. Measured on this commit (Linux, fresh process): `language_list()` first call 9.2 ms, then `render()` (model validate + JSON) 1.8 ms. The reason for the shipped file is gone. What remains is a 73 KB generated artifact, a regenerate command, a freshness test, a PyInstaller data entry, and a second language table to keep in step with the first. Decision 0082 did not mention the server's file.
- Change: write the route so that it builds the body once:
  ```python
  @functools.cache
  def _body() -> StaticBody:
      return StaticBody.of(LanguageList(languages=[Language.model_validate(e) for e in language_list()]))
  ```
  Delete `LANGUAGES_FILE`, the public `render`, the `resources` read, the `__main__` block, `data/languages.json` (and the `data/` folder), `test_the_shipped_list_is_the_built_one` (keep the two route tests), and the `"reframe_server"` line in `DATA_PACKAGES` (`collect_data_files("reframe_server")` would then collect only `py.typed`; nothing needs it frozen). Keep `asyncio.to_thread(_body)` in the handler. Add a "Follow-up (0082)" note to decision 0071 that item 2 is dropped, with the 9.2 ms measurement, and fix its "Consequences" first bullet (it names `test_the_shipped_list_is_the_built_one`); `docs/status.md` and `docs/plan` do not name the shipped list (checked).
- What must be true for the decision to change: the first `GET /api/languages` costs about 11 ms now (on the Windows VM, check once with the frozen sidecar: 0071 measured Windows at about 2 to 3 times Linux). If that stays under about 50 ms, the shipped file buys nothing.
- Behaviour: unchanged. The response body is the same bytes (the test compares them today), the ETag is the same.
- Contracts touched: none. HTTP/WS/OpenAPI: unchanged (same route, same `Language` and `LanguageList` schemas, same body). Frontend: none. Desktop: the PyInstaller spec loses one data entry; the frozen sidecar test `test_frozen_sidecar.py:134` (`GET /api/languages` has languages) is the guard.
- Callers to update: `desktop/sidecar/sidecar.spec`, `docs/decisions/0071-*.md` (follow-up), `tests/test_languages.py`.
- Tests: delete `test_the_shipped_list_is_the_built_one` and its `languages` module import; `test_the_language_list` and `test_a_client_with_the_current_list_gets_304` stay as the guard; `test_frozen_sidecar.py:134` stays.
- Decision records: 0071 (item 2 is the one being changed; items 1, 3 to 5 stay), 0082 (the reason it can change).
- Size: S; estimated lines: -15 source (and one 73 KB generated file) / -6 tests
- Risk: low. The only cost is about 11 ms at the first request (not at start-up).
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (re-measured in a fresh process on this commit: `language_list()` first call 9.2-9.4 ms, `render()` 1.8 ms, as claimed; `reframe_server` has a second non-Python file, `py.typed`, so "the only data file" is only true for what the sidecar needs; decision 0071's Consequences bullet must be edited too; the frozen-sidecar check on the Windows VM stays a condition)
- Orchestrator: Tier B, work package Q-6.14 (see ../plan.md).

### SRV-03: Public members of the facade and the preset store that nothing uses
- Kind: dead-code
- Where (all `packages/reframe/src/reframe/service.py` unless noted):
  - `PresetService.rename` and `PresetService.duplicate` (`:878-886`), and in `packages/reframe/src/reframe/presets/store.py` `PresetStore.rename` (`:321-326`) and `PresetStore.duplicate` (`:339-357`). Cross-area: presets (the store part).
  - `ToolsService.versions` (`:175-178`) and `ToolsService.discovering` (`:148-150`).
  - `SettingsService.path` (`:716-719`), `SourceService.cache` (`:286-289`), `PresetService.store` (`:831-833`).
  - `ToolsService.__init__` (`:123-140`): `timeout` is never passed (the only constructor call is `Reframe.__init__` at `:958`, which passes `bundled_roots`, `tasks`, `data_dir`), and `tasks=None, data_dir=None` plus the `RuntimeError` in `fetch` (`:204-205`) guard a call that cannot happen (the facade always passes both).
  - `Reframe._load_settings` (`:1053-1058`, "a test hook", deletes its own argument), the `settings=` parameter of `Reframe.__init__` and `Reframe.create`'s `settings = cls._load_settings(config)` (`:1041`, `:1046`), and the `initial=` parameter of `SettingsService.__init__` (`:704-715`).
- Now: counted with `rg` over `packages`, `testing`, `scripts` (production = outside `tests/`):
  - `presets.rename` / `presets.duplicate`: 0 production callers. The server has no route for them (the plan's "Not exposed" table says: rename is `PUT /api/presets/{id}`, duplicate is `GET` then `POST`). The frontend does both itself: `frontend/src/views/PresetsView.vue:92-117` (duplicate: built-in becomes category `Custom`, a name clash takes the server's free-name fix) and `:119-123` (rename). So the logic of `PresetStore.duplicate` is written again in the frontend. The CLI uses neither. The store tests call `rename` at 9 places; four of them (`test_store.py:274`, `:500`, `:592`, `:767`) use it only to cause a write or a name clash in a test of something else.
  - `tools.versions`: 0 callers, 1 test (`test_service.py:420`). `tools.discovering`: 0 callers, 4 test lines. `settings.path`: 0 callers (`test_service_settings.py:86`, server `test_queue.py:294`). `sources.cache`: 0 callers, 3 test asserts. `presets.store`: 0 callers anywhere.
  - `_load_settings` is monkeypatched by 2 tests (`test_service.py:258`, `test_service_settings.py:356`); `Reframe(settings=)` is passed by 2 tests (`test_service.py:223`, `:445`). No production code uses either.
  - `sources.store` is not in this list: decision 0030 names it in its contract table (it has 0 production callers too; keep).
- Change:
  1. Delete the 9 listed members (7 on the facade: `PresetService.rename`, `.duplicate`, `.store`, `ToolsService.versions`, `.discovering`, `SettingsService.path`, `SourceService.cache`; 2 on `PresetStore`: `rename`, `duplicate`) and their `Not exposed` rows in `docs/plan/06-web-app.md` (`test_facade_coverage.py` fails on a row whose member no longer exists, so the rows go in the same commit): own rows to delete are `settings.path`, `tools.versions`, `presets.rename`, `presets.duplicate`; `tools.discovering` is inside the "Lifecycle state" row (`tools.start`, `capabilities.start`, `tools.current`, `tools.discovering`, …) and `sources.cache` and `presets.store` are inside the "objects the services are wired with" row (`sources.cache`, `sources.media`, `presets.store`, `tasks.events`): edit those two rows. Keep `PresetStore.unique_name` (used by `_check_name`) and `_user_preset` (used by `delete`). Change `docs/plan/05-core.md:595` ("status, versions, re-scan").
  2. `ToolsService.__init__(self, events, settings, *, bundled_roots, tasks, data_dir)`: drop `timeout` (use `VERSION_TIMEOUT` at the one use), make `tasks` and `data_dir` required, delete the `RuntimeError` branch in `fetch`.
  3. Delete `Reframe._load_settings`, the `settings` parameter of `Reframe.__init__` (and its docstring lines), and `SettingsService(initial=)` (the store always loads). Tests set settings by writing `settings.json` into the test's config folder.
- Behaviour: unchanged for users, the CLI, the server and the frontend.
- Contracts touched: public core API (members above). HTTP/WS/OpenAPI: none. Persisted schema: none. CLI: none.
- Callers to update: tests only (list below, plus the server test `packages/reframe-server/tests/test_queue.py:294`, which reads `api.reframe.settings.path`: use `api.reframe.config_dir / "settings.json"`), `docs/plan/06-web-app.md` ("Not exposed" rows), `docs/plan/05-core.md:595`. `tests/test_facade_coverage.py` needs no code change (it reads the table and the facade).
- Tests:
  - Delete: `test_store.py::test_rename` (`:185-199`), `::test_duplicate_builtin_and_user_presets` (`:212-231`), the `rename` line in `::test_builtins_cannot_be_changed_renamed_or_deleted` (`:147`); `test_service_settings.py` lines `:394-397` (rename and duplicate in the facade test, which then uses `create` and `save`), `test_service_settings.py::test_settings_hook_still_overrides_the_file` (`:352-362`), the `versions` assert (`test_service.py:420`), the `discovering` asserts (`:127`, `:136`, `:450`, `:454`: use `app.tools.current is not None`), `settings.path` and `sources.cache` asserts.
  - Change: the four store tests that use `rename` to cause a write or a name clash (`test_store.py:274`, `:500`, `:592`, `:767`) call `store.save(preset.model_copy(update={"name": ...}))`. `test_settings_tool_paths_feed_discovery` writes `settings.json`. The two `Reframe(settings=AppSettings())` calls drop the argument (their config folder is empty, so the defaults load).
  - Stay: the write-failure test (`:270-278`) and the unknown-fields test (`:496-503`) as guards of the store.
- Decision records: 0030 (`sources.store` stays), 0015 §2 (store rules: a built-in cannot be changed is still tested through `save`; "duplicating one makes a user preset in the `Custom` category" would then be implemented only in `frontend/src/views/PresetsView.vue:92-117`, and no core test names it: add a follow-up note), 0049 item 11 (lists `tools.versions`, `settings.path` as not exposed: update the list), 0050 item 10 (lists `presets.rename` and `presets.duplicate` as not exposed: update the list).
- Size: M; estimated lines: -55 source / -50 tests
- Risk: low. Dead code in production; the only risk is test churn (about 10 tests touched).
- Depends on: none
- Confidence: high for the 9 members (0 production callers; re-counted with `rg` over `packages`, `testing`, `scripts`, `desktop`); medium for `_load_settings` and `settings=` (they are test seams; the replacement is to write the file, which the settings tests already do).
- Verdict: ADJUSTED (9 members, not 8; the plan rows are four own rows plus two combined rows, not the two combined ones named; `packages/reframe-server/tests/test_queue.py:294` also reads `settings.path`; decisions 0050 item 10 and 0015 §2 added; the 0-caller counts, the `ToolsService.__init__` single call and the `_load_settings` / `settings=` / `initial=` test-only use all hold)
- Orchestrator: joined into X-07 (see ../cross-cutting.md); that entry decides the tier and the work package.

### SRV-04: The "deinterlace makes the grid progressive" rule is written five times
- Kind: duplication (cross-area: command, preview, batch, validation)
- Where:
  - `packages/reframe-server/src/reframe_server/routers/jobs.py:279-290` (`geometry`).
  - `packages/reframe/src/reframe/command/builder.py:189-193`.
  - `packages/reframe/src/reframe/preview/graph.py:137-140`.
  - `packages/reframe/src/reframe/batch/resolve.py:84-88` (`output_size`).
  - `packages/reframe/src/reframe/validation/context.py:72-81` (`ValidationContext.source_geometry`).
  - Home of the fix: `packages/reframe/src/reframe/dimensions.py:135` (`source_geometry`, whose docstring already says "a job that deinterlaces before the crop passes a copy with `interlaced=False`").
- Now: five places do `src = source_geometry(stream)`, then `if "deinterlace" in job.filters.root: src = src.model_copy(update={"interlaced": False})`, then `compute_geometry(src, job.dimensions)`. The server's copy carries its own comment ("Deinterlace runs before the crop..."). If the rule changes (another filter id, a deinterlacer that keeps fields), five files must change in step, and the server's geometry header would drift from the command the encode runs.
- Change: one function in `dimensions.py`:
  ```python
  def job_source_geometry(stream: VideoStream, job: JobSettings) -> SourceGeometry:
      """``source_geometry`` as the job's encode sees it: progressive when it deinterlaces first."""
      src = source_geometry(stream)
      return src.model_copy(update={"interlaced": False}) if "deinterlace" in job.filters.root else src
  ```
  Each site becomes `job_source_geometry(video, job)`. The server handler becomes `src = source_geometry(video)`; `return JobGeometry(source=src, geometry=None if job.video.passthrough else compute_geometry(job_source_geometry(video, job), job.dimensions))` (the displayed `source` keeps the real field order; only the grid is progressive). `reframe.dimensions` already imports from `reframe.models`; `JobSettings` is there too (no import cycle: check with `uv run mypy`).
- Behaviour: unchanged.
- Contracts touched: public core API (adds one function). HTTP/WS/OpenAPI: none (`POST /api/jobs/geometry` answers the same fields; `JobGeometry.source` is still the unmodified geometry).
- Callers to update: the five sites above.
- Tests: none deleted. The existing builder, graph, resolve, validation and server geometry tests guard the unchanged results. Add one test for `job_source_geometry` (3 lines) in `tests/dimensions/`.
- Decision records: none apply (the rule is C-5/C-6 detail; 0009 is about the maths, not about this call).
- Size: S; estimated lines: -12 gross at the five sites, about -4 net after the new function (about 8 lines with its docstring) / +3 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the five sites, their line anchors and the unchanged `JobGeometry.source` all hold; the net saving is about -4 lines, not -12, because the helper and its test are added; the moved comment "Deinterlace runs before the crop..." belongs in the helper's docstring)
- Orchestrator: joined into X-01 (see ../cross-cutting.md); that entry decides the tier and the work package. Joined into X-01. Use the function names of CMD-01; the server line given here stays.

### SRV-05: Test helpers copied between files
- Kind: tests
- Where (server tests unless noted):
  - Async wait loops, 6 copies (the bodies differ in small ways: `assert` / `raise TimeoutError` / `asyncio.timeout`, sleep 0.01 or 0.02, default limit 10 or 20): `tests/test_attach.py:108` (`wait_until`), `tests/test_events.py:177` (`wait_until`, with `# noqa: ASYNC110`), `tests/test_queue.py:59` (`poll`), `tests/test_preview.py:36` (`_until`), `tests/test_sources.py:35` (`_until`), `tests/test_settings.py:31` (`_until`). Sync wait loops, 3 copies in the server tests: `tests/test_parent.py:81`, `tests/test_owner.py:123`, `tests/test_frozen_sidecar.py:151` (`wait_for`; it stops on `is not None`, the others on a truthy value). Core tests (cross-area: core tests) have at least 14 more: async `until` / `poll` in `packages/reframe/tests/test_service.py:44`, `test_service_settings.py:36`, `test_tasks.py:24`, `probe/test_folder.py:34`, `probe/test_prober.py:34`, `capabilities/test_service.py:42`, `capabilities/test_detect.py:50`, `queue/conftest.py:91` (`poll`; `queue/conftest.py:329` `wait_for` only calls it), `remote/conftest.py:111`, `metadata/test_metadata_edit_real.py:507`, `tools/test_runner.py:38` (`_wait_for`), `platform/test_sleep_failures.py:424`, `queue/test_integration.py:66` (a method), and `testing/tests/test_fake_ffmpeg.py:42`; sync `wait_until` in `remote/test_shared_queue_real.py:244`.
  - "Probe a media file and get its source id", 6 copies: `tests/test_batch.py:19` (`add_sources`), `tests/test_jobs_output_folder.py:22`, `tests/test_jobs.py:39`, `tests/test_presets.py:23`, `tests/test_naming.py:15`, `tests/test_jail_sweep.py:364` (`probed_sources`). Each does `path = api.media_file(name)`, `assert isinstance(await api.reframe.sources.probe(path), MediaSource)`, `api.app.state.sources.add(path)`.
  - `draft_job` and `add_jobs`: identical in `tests/test_attach.py:87-105` and `tests/test_queue.py:35-52` (the attach one takes an extra `attach` value).
  - `sign_in`/`hub`: the four-line WebSocket auth handshake appears in `tests/test_attach.py:67` (returns the `client_id`) and `tests/test_events.py:155` (an async context manager that yields a `Client`; different signature, not a copy); `hub(api)` is identical in both (`test_attach.py:82`, `test_events.py:99`).
  - `ready_port`: `tests/test_parent.py:72`, `tests/test_frozen_sidecar.py:57` (the second also asserts `event == "ready"`).
- Now: the harness `testing/reframe_testing/server.py` (`Api`, `make_api_factory`, `receive_json`) is clean, but each test file re-writes the small helpers on top of it. About 10 copies of a 6-line poll loop, 6 of a 6-line probe helper.
- Change:
  - New `testing/reframe_testing/waiting.py`: `async def wait_until(condition, limit=10.0)` (poll every 10 ms, raise `TimeoutError`) and `def wait_until_sync(check, limit=30.0)` (returns the truthy result). Replace the 9 server copies (6 async, 3 sync) and the core copies listed above, one commit per package. Keep a copy only where its message or step differs (check each call: `test_frozen_sidecar.wait_for` stops on `is not None`; `test_events.wait_until` uses `asyncio.timeout`). The shared helper needs `# noqa: ASYNC110` (ruff `ASYNC` is on).
  - `Api.add_source(self, name="Show S01E01.mkv") -> tuple[str, Path]` in `testing/reframe_testing/server.py` (media file, probe, register, return id and path). `test_jobs.py` keeps a 3-line wrapper that calls `serve(...)` first (its `recording=` option).
  - `Api.draft_job(name)` and `Api.add_jobs(*names, attach=None)` there too (both queue test files use them).
  - `hub` goes to the harness as `Api.hub` (property); the two `sign_in` helpers stay in their files (different shapes; sharing the four handshake lines saves about 4); `ready_port(process, limit)` goes to `reframe_testing/processes.py` (31 lines today; the frozen-sidecar copy also asserts `event == "ready"` and defaults to 30 s, the parent copy to 60 s).
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the files listed under Where.
- Tests: all affected tests stay; only helpers move.
- Decision records: 0004 (the shared testing package) says shared test infrastructure lives in `testing/reframe_testing`; this follows it.
- Size: M; estimated lines: -0 source / -100 tests for the server tests alone (about -60 more if the core tests move too)
- Risk: low. A shared poll loop with a different default timeout could make a slow test flaky: keep the per-call `limit` where it is not the default.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the copy list was incomplete and partly wrong: 3 sync copies in the server tests, not 2; at least 14 core copies, not 3, and `queue/conftest.py:329` only delegates to `poll`; the two `sign_in` helpers are not copies; the six probe-and-register helpers, `draft_job`/`add_jobs`, `hub` and `ready_port` copies hold)
- Orchestrator: Tier A, work package Q-6.2 (see ../plan.md).

### SRV-06: `SourceService`: duplicated start-up of a probe, and a per-file lock map
- Kind: structure
- Where (`packages/reframe/src/reframe/service.py`):
  - `SourceService.probe` (`:290-326`) and `SourceService.inspect_subtitle` (`:328-351`): the same 12 lines (`_check_open`, token, `_enter`, `_get_prober` with a `ReframeClosedError` branch, `_check_file`, tool error, `_leave`).
  - `_enter`/`_leave` (`:604-613`) are used only by those two methods.
  - `_file_lock`, `_locks` (`:279-281`, `:476-492`): a dict of `(Lock, [users])` so that the lock of a file is dropped when nobody waits. Kept after verify (see Change 2).
  - `_check_file` (`:650-672`) repeats 9 lines of `Prober._prepare` (`packages/reframe/src/reframe/probe/prober.py:234-243`: stat, `FileNotFoundError` text via `missing_text`, `OSError`, `S_ISREG`). Reported by the 5-line duplicate check (`duplication-5lines.txt`). Cross-area: probe.
- Now: `inspect_subtitle` and `probe` would stay in step by luck. Their only differences are the cancelled message text and what runs after the checks. The per-file lock keeps two scans of different files from waiting for each other during a stat plus a cache write, which takes milliseconds. The only production callers of `update` are the two scans (`analysis/bitrate.py:185`, `analysis/subtitles.py:389`); `store` has none (kept: 0030).
- Change:
  1. One helper:
     ```python
     async def _ready_prober(self, path) -> Prober | ProbeError:
         """The prober, or why this file cannot be probed: Reframe closing, a bad file (reported
         first), an unusable ffprobe."""
         try:
             prober = await self._get_prober()
         except ReframeClosedError:
             return ProbeError(_absolute(path), ProbeErrorKind.CANCELLED,
                               "The probe was cancelled: Reframe is shutting down.")
         problem = await asyncio.to_thread(_check_file, path)
         if problem is not None:
             return problem
         return prober if isinstance(prober, Prober) else _tool_error(_absolute(path), prober)
     ```
     `probe` and `inspect_subtitle` call it, then run their own last step; wrap `_enter/_leave` in a small `@contextlib.contextmanager` (name it differently from the `_active` counter) used by both. Counted on this commit: before, `probe` body 24 + `inspect_subtitle` body 17 + `_enter`/`_leave` 8 = 49 non-blank lines; after, 9 + 7 + `_ready_prober` 15 + the context manager 12 = 43, so about -6 lines net, not -14.
  2. DROPPED in verify: replacing `_file_lock` and `_locks` by one lock. Decision 0032 §4 and its R3-1 follow-up record "`SourceService.update` takes a lock of the file" ("one file's updates run one at a time"), and the test `tests/analysis/test_analysis_facade.py::test_concurrent_updates_are_serialised` says "per-file lock". One global lock also makes the store of file B wait for the `os.stat` and the cache read/write of file A, which can stall on a network share. The lock map stays.
  3. Optional: give `probe/prober.py` a `check_file(file) -> os.stat_result | ProbeError` used by `_prepare` and `_check_file` (`_check_file` then adds only `has_nul` and the real `open`); about 0 lines net (the 9 duplicated lines become one 12-line function plus two call sites), so only worth it to keep the two messages in step.
- Behaviour: unchanged, except the text of the cancelled error of `inspect_subtitle` (it gets the longer "The probe was cancelled: Reframe is shutting down."; no test names either text; the one test of this message, `test_service.py:198`, is for `probe`).
- Contracts touched: none (private members). HTTP/WS/OpenAPI: `POST /api/subtitles/inspect` maps `CANCELLED` to 503 `probe.cancelled` with this message; no schema change. Nothing in `frontend/src`, `desktop/` or the server tests reads the text of either message.
- Callers to update: none outside `service.py` (and `prober.py` for step 3).
- Tests: none deleted. `tests/test_mediatask.py` (update, store) and `tests/test_service.py` (probe, close) stay as guards. `rg "_locks|_file_lock" packages` finds no test.
- Decision records: 0016 RN (NUL path handling stays in `_check_file`), 0030 (`store`, `update` stay), 0032 §4 and R3-1 (the per-file lock stays).
- Size: XS; estimated lines: -6 source (step 1 only) / 0 tests
- Risk: low. Step 1 keeps the order the code has today: a file problem is reported before an unusable ffprobe, and a closing Reframe is reported first.
- Depends on: none
- Confidence: medium (a small gain; do it only together with other work in `service.py`)
- Verdict: ADJUSTED (step 2, the single lock, dropped: decision 0032 R3-1 records the per-file lock and a global lock can stall unrelated stores on a slow share; the saving of step 1 is about -6 lines, not -14, and step 3 about 0, not -8; the duplicated start-up and the `_check_file` / `_prepare` duplicate are real, the anchors and the callers of `update` hold)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### SRV-07: Clip Range answers: use `FileResponse` (decision 0049 item 4)
- Kind: decision-change
- Where: `packages/reframe-server/src/reframe_server/routers/media.py:54-92` (`clip_file`) and the helpers `_open` (`:103-110`), `_byte_range` (`:112-137`), `_offset` (`:139-144`), `_chunks` (`:146-157`), `CHUNK`, `_RANGE`, `_MAX_DIGITS`; tests `packages/reframe-server/tests/test_media.py:81-118`.
- Now: the clip route reads a `Range` header by hand (suffix, open-ended, closed, a 19-digit cap), answers 206 or 416 as a problem, ignores several ranges and a header that does not parse, opens the file first and streams from that handle. About 70 code lines plus a 9-row table and 3 416 cases in the tests. Decision 0049 item 4 gives the reasons: Starlette's `FileResponse` answers a malformed range with a plain-text 400, several ranges with `multipart/byteranges`, and fails when the cache evicts the file between lookup and send.
- Checked on this commit (Starlette 1.9.0, `uv run python -c`): `FileResponse._parse_range_header` handles one range (`bytes=0-99`), suffix, open-ended, a 5000-digit number (a malformed 400, no crash), `bytes=-0` (416 with `Content-Range: bytes */<size>`, plain text), and sets `Accept-Ranges`, `Content-Length`, `Content-Range`, `ETag` and `Last-Modified` itself.
- Change (only if the condition below holds): the handler keeps the lookup and the 404 problem, then returns `FileResponse(path, media_type=_VIDEO_TYPES.get(...), headers={"Cache-Control": "private, max-age=3600"})`. Delete `_open`, `_byte_range`, `_offset`, `_chunks`, `CHUNK`, `_RANGE`, `_MAX_DIGITS`. In `test_media.py` keep the whole-file and one-range rows and the 416 status test (change the body assertion), delete the rows for several ranges, `bytes=50-10`, `bytes=-`, the huge numbers.
- What must be true for the decision to change: (1) a clip that the cache evicts between the lookup and the send fails that one response with a 500 (`RuntimeError` in `FileResponse.__call__`, as 0049 records) instead of streaming from the open handle. An eviction after `FileResponse` has opened the file does not cut the transfer on Linux in either design, and the next range request looks the clip up again and gets 404 `preview.unknown_clip` either way. (2) The clients that fetch the clip send only one `bytes=a-` or `bytes=a-b` range. This holds for the page's `<video src>` and for a browser tab (web mode `platform.openExternal` is `window.open(link)`), but NOT provably for the desktop app's **Open in external player** (`frontend/src/components/clip/PreviewClip.vue:208`, `desktop/src-tauri/src/external.rs`, which hands the signed clip URL to the user's own player: mpv, VLC, xdg-open): the owner must check the players he uses against `FileResponse` (`bytes=0-`, a seek to the end, a second connection). (3) The 416 body may be plain text instead of a problem document.
- Behaviour: changes for non-browser clients that send several ranges (`206 multipart/byteranges` instead of `200` whole file), a malformed or over-long range (`400` plain text instead of `200` whole file or a `206` to the end: `bytes=990-<5000 nines>` is a 206 today and a 400 with `FileResponse`, checked on Starlette 1.9.0), or a range past the end (`416` plain text instead of a `preview.range_not_satisfiable` problem). The `ETag` changes from the clip id to Starlette's `mtime-size` value, and `Last-Modified` is added. A cache eviction between lookup and send gives a 500 (today: the open handle is used).
- Contracts touched: HTTP: error bodies of `GET /api/preview/clips/{clip_id}` as above (the problem code `preview.range_not_satisfiable` goes), the `ETag` value. OpenAPI: the route's `responses` (200, 206) stay; the page does not call this URL with fetch (`<video src>` only, `frontend/src` has no `'/api/preview/clips/{clip_id}'` call) and the `ClipCompare`/frames path uses other routes. But the URL is also opened outside the page: web mode opens it in a new tab and the desktop shell opens it in the user's external player (`open_external` accepts only `http://127.0.0.1…/api/preview/clips/…`), so the clients of this route include programs the project does not control.
- Callers to update: `tests/test_media.py`, decision 0049 (follow-up), `docs/plan/06-web-app.md:150` (the "one range → 206, outside the file → 416" text stays true).
- Tests: change `test_a_clip_is_served_whole_or_as_one_byte_range` (rows) and `test_a_range_outside_the_clip_is_416`; `test_a_clip_not_in_the_cache_is_404` and `test_media_urls_need_media_access` stay.
- Decision records: 0049 item 4 (changed); R-9 of its review (the 4300-digit `int()` limit: `FileResponse` was checked to refuse the long number without a 500).
- Size: M; estimated lines: -55 source / -45 tests
- Risk: medium. It changes a documented answer and drops the open-handle protection. Do it only if the owner accepts (1) to (3).
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (condition (2) was wrong: the frontend does hand the clip URL to other clients, a new browser tab and, in the desktop app, the user's external player, so "no client sends an unusual Range" is not provable from `frontend/src`; the eviction exposure is the lookup-to-send window (a 500), not a cut transfer; the `ETag` change and the 400 for an over-long `bytes=a-<huge>` were added; the Starlette 1.9.0 behaviours (400 malformed, 416 for `bytes=-0`, multi-range, no crash on 5000 digits) were re-checked and hold)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### SRV-08: Small leftovers in the server package
- Kind: dead-code
- Where (`packages/reframe-server/src/reframe_server/` unless noted):
  - `routers/jobs.py:139-141` (`without_output`): 0 callers anywhere (`rg -w without_output packages testing scripts frontend`); coverage marks line 140 as the only missed line of the file.
  - `events.py:213-215` (`EventHub.client_open`): 0 production callers; 8 test calls (`tests/test_attach.py:172`, `:173`, `:196`, `:197`, `:232`, `:269`, `:325`, `:363`). Production uses `attachment()`.
  - `sources.py:33-34` (`SourceRegistry.path`): 0 production callers; 1 test (`tests/test_batch.py:53`).
  - `owner.py:43-46` (`StoreUnusable`) and `:39-41` (`StoreBusy`): two exception classes for the same job (stop the lifespan; `serve` reads `app.state.exit_code`). Neither has an `except` in `src`; `StoreBusy` is asserted once (`tests/test_applog.py:143`). `StoreUnusable` has no test that names it. KEPT in verify: decision 0056 (R-item on `--owner-only` exit 1) records `StoreUnusable` by name, `StoreBusy` is named by 0056, 0069 (`sidecar.log`) and `testdata/README.md:2582` (the lifespan-failure log), and the class name is part of the logged text; a merge saves 4 lines.
  - `routers/settings.py:100-107` (`_folders`) walks a settings model for `Path` fields (today only `output.naming.output_folder`; `tools.*` is skipped by type `ToolPaths`); `security.py:382-395` (`_paths`) already walks any model, mapping or list for `PurePath` and yields the location.
  - `security.py:_jail` (`Path(root).resolve(strict=False)`): `config.media_roots` and `output_roots` are `list[Path]` already, so `Path(root)` does nothing.
- Now: each is 2 to 15 lines; together they are leftovers of earlier designs (the hub's `client_open` before `attachment`, the registry's `path` before `get`).
- Change: delete `without_output`; delete `client_open` and change the 8 test calls to `hub(api).attachment(id) is not None`; delete `SourceRegistry.path` and in `test_batch.py:53` use `dict(registry.items())[sid]`; make `security._paths` public as `model_paths` and write `settings._folders` as `((".".join(map(str, where)), path) for where, path in security.model_paths(model, ()) if where[0] != "tools")` (the old walker skips by type `ToolPaths`, this one by the top-level name `tools`: the same today; the `before`/`after` comparison in `_check` uses these dotted names); drop the `Path(root)` wrap in `security._jail` (`ServerConfig.media_roots` / `output_roots` are validated `list[Path]`; `routers/fs.py:186` already calls `root.resolve()` on them). The `StoreUnusable` / `StoreBusy` merge of the first draft is dropped.
- Behaviour: unchanged. The settings jail also sees a `Path` inside a list or mapping of the settings (there is none today).
- Contracts touched: none. HTTP/WS/OpenAPI: none. `_jail` is part of the 0046 path jail: run `tests/test_jail_sweep.py` and `tests/test_security*.py` after the `Path(root)` edit.
- Callers to update: `tests/test_attach.py`, `tests/test_batch.py`.
- Tests: no test is deleted; 9 test lines change.
- Decision records: 0049 item 9 (jail of settings folders stays), 0057 (names `EventHub.client_open` at item "attachments": add a note that it was removed, `attachment()` is the one lookup), 0046 (jail).
- Size: S; estimated lines: -16 source / -2 tests
- Risk: low.
- Depends on: none
- Confidence: high for the dead functions, medium for the `_folders` merge.
- Verdict: ADJUSTED (the `StoreUnusable` / `StoreBusy` merge dropped: decision 0056 names both classes, 0069 and `testdata/README.md` name `StoreBusy` in the logged failure text, and it saves 4 lines; `tests/test_applog.py:143` no longer changes; decision 0057 added; estimate -16 not -20; `without_output`, `client_open` (8 test calls, lines confirmed), `SourceRegistry.path` (1 test), the `_folders` / `_paths` overlap and the no-op `Path(root)` hold)
- Orchestrator: Tier B, work package Q-6.14 (see ../plan.md).

## Looked at and kept

- `security.py` (`_RequestGuard`, `_CredentialsFirst` with `RequestBodyLimitMiddleware`, `_SecurityHeaders`, jail, signed media URLs), `login.py` (scrypt, sessions, rate limit), `filtertext.py` (`ALLOWED_FILTERS` and the graph parser): decision 0046 and its follow-ups require them; the brief forbids weakening them.
- `routers/media.py` Range code: decision 0049 item 4 requires it as written; only SRV-07 questions it.
- `routers/presets.py::_read_limited` (hand-written 4 MiB body count): decision 0050 names the `413 presets.import_too_large` code and the test asserts it. Starlette's own limit would answer `http.413`.
- `parent.py` (pidfd, ancestor walk, Windows `Kernel32` protocol, `limit`/`hard_exit`/`platform`/`kernel32` parameters): decision 0054 and the Windows mock tests need them.
- `owner.py`, `idle.py`: decisions 0042, 0056. `static.py` (`_MEDIA_TYPES`, `_inside` Windows checks): 0058 and Windows.
- `folders.py::hide_server_folders` is applied in three places (`routers/tasks.py`, `routers/queue.py::_public`, `events.py::_send_event`): decision 0048 requires that no answer shows a server folder. One shared hook is not possible without changing the response models.
- `events.py` (server hub: `Attachment`, `detach`, progress throttle, log batches, heartbeat, close with timeout) and core `EventBus` (bounded queue, coalesce, `resync` marker, hard limit and overflow): decisions 0047 and 0057 and plan S-3 require both layers (the bus bounds memory per subscription; the hub limits the send rate and batches log lines). `Subscription.coalesced`, `overflowed`, `EventBus.subscriber_count` and the `hard_limit` argument are used only by tests, but they cost about 8 lines and `subscriber_count` is the tests' wait primitive (13 uses); not worth a finding.
- `openapi.py` (the WebSocket messages as a webhook): decision 0051 item 3.
- `tests/test_facade_coverage.py` (397 lines of AST reading): plan S-2 "Done when" and decision 0051 require the check; the type-flow in `Reach` gives the precision that a regex over the routers would lose (`get`, `list`, `update` exist on several services). The "every route is called by a test" half (`called_routes` and its helpers, about 100 lines) could be replaced, but only by a run-time route recorder with a session-end check, which is not simpler.
- `SourceService.store`: 0 production callers, but decision 0030 lists it. `SourceService.bitrate_scan`, `subtitle_scan`, `loudness_scan`, `frames`, `frame`, `cropdetect`, `preview_cache_size`, `clear_preview_cache`: one-line delegations that decision 0030 fixed as the facade's signatures.
- `PresetService` delegations and `asyncio.to_thread` wrappers (`list`, `get`, `find`, `default`, `export`, `create`, `save`, `delete`, `set_default`, `import_`): the facade is the async surface of the sync store; each is used by the CLI or the server.
- `ToolsService.fetch(platform=, manifest=)`: `platform` is used by `reframe tools fetch --platform` (`cli.py:3419`); `manifest` is the test seam of the fetch tests (decision 0030 signature).
- `SettingsService.update(check=)` and `_apply` (depth limits, schema_version guard): decisions 0045 and 0049 item 9; `Reframe.__init__(on_log_level=)`: decision 0078.
- `Reframe.close` order, `_react`, `ToolsService.status` retry loop, `SourceService._known` bounded cache, `_idle` event: needed for cancel and shutdown (decisions 0016, 0047 follow-up).
- `routers/jobs.py` guard functions (`folder_issue`, `in_place_issue`, `job_issue`, `jail_job`) and `routers/batch.py::_checked`, `routers/naming.py::_checked`, `jobs._checked`: decision 0050 follow-up (web mode answers an issue, not a 403). The three `_checked` helpers work on different models. Six handlers repeat `jail_job(...)` then `job_source(...)`; a dependency would save fewer than 5 lines.
- `routers/queue.py` (eight near-identical 204 handlers, `set_when_done` cancelling a countdown), `routers/system.py::rescan_encoders` (7-line task wrapper): the routes are plan rows; moving the task into the core would add core API for no gain.
- `routers/languages.py::Language` mirrors `reframe.languages.LanguageEntry` field by field: the server owns its OpenAPI component names; the conversion is one `model_validate`.
- `__main__._parser`: the flag names and help are user-visible; `pydantic-settings` CLI parsing would change them.
- `desktop/spike` guards are tested in `packages/reframe-server/tests/test_spike_tools.py`, `test_spike_magnifier.py`, `test_spike_results.py` (980 lines). They test the owner's window tools under `desktop/spike/scripts`, not server code. They are out of this area; the desktop area may decide whether they belong in `desktop/`.
- All 87 routes are in the plan (`GET /api/tasks/{id}`, `PUT /api/auth/password`, `GET /api/health`, `POST /api/system/shutdown` are not called by the web frontend but are plan rows used by the CLI, the desktop shell and Docker).
