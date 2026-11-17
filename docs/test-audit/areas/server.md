# Area server: `packages/reframe-server/tests/` (41 files and conftest) with `testing/reframe_testing/server.py`

Baseline: 41 files, 661 tests, 7,906 test code lines, 263 s of test time.

## Summary
7 findings. Tier A: 2 findings, 4 tests, about 33 code lines, about 2.0 s. Tier A+B: 7 findings,
9 tests, about 85 code lines, about 5.9 s. The area is already well layered: every server test
goes through server code (a route, the hub, the jail, `security`, `owner`, `parent`), and
no server test imports a core module to test it directly. The only clear layer copy is the
chapter import format test, which the core test `test_chapters.py` already covers.
Best three:
- TSV-01: `test_import_tells_the_format_from_the_content` (3 cases) does again at the route what
  the core chapter tests and the server round-trip test already pin. Delete.
- TSV-05: two real-FFmpeg preview clip tests each encode a clip. One clip can serve both
  (the link and Range checks, and the frames of the clip). Merge.
- TSV-02: two tests build the same OpenAPI document (1.2 s each) and check the WebSocket message
  schemas. Merge into `test_openapi.py`.

## Findings

### TSV-01 The chapter import format test repeats core tests and the server round trip
- Kind: layer-duplicate
- Where: `packages/reframe-server/tests/test_job_output.py::test_import_tells_the_format_from_the_content` (line 308-335, 3 cases: csv, ogm, xml)
- Now: the test writes a short CSV, OGM or Matroska XML text below the media root, posts it to
  `/api/chapters/import` without a `format`, and checks the detected format and the
  `(start, name)` pairs.
- Change: delete
- Saved: 3 tests, 28 code lines, 0.75 s
- Guarantee kept by:
  - Route level: `test_job_output.py::test_an_exported_file_is_imported_with_the_same_names[csv|ogm|xml]` (line 206). It posts each format's file to `/api/chapters/import` without a `format`, and asserts `format == chapter_format`, the names (with commas, quotes, `=`, `;`, `#`, `<>`, `&` and non-ASCII), `issues == []`, and the first start (`None` for csv, `0.0` for ogm/xml).
  - Format detection: `packages/reframe/tests/test_chapters.py::test_the_format_comes_from_the_first_line` (line 171): xml, ogm, csv and no format.
  - Parsing each format: `test_chapters.py::test_csv_import_trims_names_and_takes_handbrakes_windows_lines` (line 52). Its input `'1, Opening \r\n2,"Part, one"\r\n\r\n'` is a superset of the server's CSV case (CRLF lines, a quoted comma, and also padding and a blank line), with the same expected `[(None, "Opening"), (None, "Part, one")]`. `test_ogm_round_trip_keeps_the_times_to_the_millisecond_and_one_line_per_name` (line 77) parses OGM with `HH:MM:SS.mmm` times to float starts (61.25, 122.5, ...). `test_xml_round_trip_escapes_the_markup_and_drops_what_xml_cannot_hold` (line 107) and `test_xml_reads_the_first_edition_and_leaves_out_nested_chapters_with_warnings` (line 131) parse `ChapterAtom`/`ChapterTimeStart` with nanosecond times to starts.
- Why nothing is lost: the route path is the same for all three cases: read the file in the jail, then `read_chapter_file` with format `None`. The round-trip test covers that path once per format, with the same assertions on `format` and names, and also asserts `issues` and the start. covquery: the ogm case's lines are a subset of the ogm round trip's lines, except 34 lines of background capability detection and the runner (`tools/runner.py`, `capabilities/service.py`, `service.py:189-190`), which depend on timing. Each case's exact numbers (62.5 s, 1.0 s) are core parsing, which the core tests above pin. The route's error mapping stays tested by `test_a_file_that_is_not_a_chapter_file_is_a_problem_with_the_line`, `test_a_chapter_file_that_cannot_be_read_is_a_problem` and `test_the_format_named_in_the_request_is_used`. `test_facade_coverage.py::test_every_route_is_called_by_a_route_test` still finds `/api/chapters/import` in the tests that stay.
- Docs and history: `grep -rn test_import_tells_the_format_from_the_content docs/` finds nothing. `git log -S` gives only d567c5b ("S-2: routes for the job type, the output's chapters, chapter import and export, ..."), which created the route tests. It names no bug, review finding or decision.
- Risk: low. The test only shows that the route hands an unnamed format to the core.
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the three inputs add nothing the keepers lack. The format comes only from the content: `read_chapter_file` and `parse_chapters` never look at the file name, so the `.txt` name of the deleted test is not a separate input class. The keeper `test_an_exported_file_is_imported_with_the_same_names` uses recorded probes (no `needs_ffmpeg`), so it runs in every place where the deleted test ran. The non-zero starts (62.5, 1.0) are core parsing; the core tests pin them. No doc, decision record or `docs/test-trim-reports/` file names the test. Numbers confirmed: 3 tests, 28 code lines, 0.75 s (0.36 + 0.23 + 0.16).
Checked: `covquery.py "-csv-expected" "...same_names[csv]"` and the same for xml → only A: 34 lines in each case, all of them capability detection and runner timing (as for ogm); `chapters.py` is not in the only-A set. $SCRATCH/tools/runtests.sh test_app.py test_attach.py test_events.py test_job_output.py test_openapi.py test_preview.py test_settings.py test_system.py test_facade_coverage.py -q (all seven changes applied together) → 140 passed in 62 s, 2 other pytest runs on the machine; test_job_output 31 → 28 tests; `test_facade_coverage` still passes (it finds `/api/chapters/import`).

Orchestrator: Tier A, package Q-7.5.

### TSV-02 Two tests build the OpenAPI document to check the WebSocket message schemas
- Kind: near-copy
- Where: `packages/reframe-server/tests/test_attach.py::test_the_client_messages_and_the_client_id_are_in_the_openapi_document` (line 342); `packages/reframe-server/tests/test_openapi.py::test_the_event_websocket_messages_are_in_the_components` (line 33)
- Now: each test builds `create_app(ServerConfig(host="127.0.0.1", mode="web", auth="none")).openapi()` (about 1.2 s each). The test_attach test checks the `ClientMessage` discriminator mapping (auth, detach) and `client_id` in `Hello.required`. The test_openapi test checks `ServerMessage`, `EventMessage`, `AuthMessage` and that no `/api/events` operation exists.
- Change: merge into `test_openapi.py::test_the_event_websocket_messages_are_in_the_components`. Add the `ClientMessage` mapping assertion and the `Hello.required` assertion there; it uses the module-scoped `document` fixture. Delete the test_attach test and its two imports, `create_app` and `ServerConfig`, which only that test uses.
- Saved: 1 test, about 5 code lines net (8 test lines and 2 imports removed, 5 assertion lines added), about 1.2 s
- Guarantee kept by: the merged `test_openapi.py::test_the_event_websocket_messages_are_in_the_components`. It uses the same document from the same `ServerConfig` and keeps every assertion of both tests.
- Why nothing is lost: both tests read the same document; the merge moves 5 assertion lines into the other test without a change.
- Docs and history: grep in docs/ for both names finds nothing. `git log -S`: the test_attach test comes from d63fb5a (S-7, decision 0057, which adds the feature); the test_openapi test comes from 3af3e3d (S-5, decision 0051). Neither commit names a bug.
- Risk: low
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the merged test reads the same document from the same `ServerConfig`, and the merge keeps all assertions. A note on docs: no record names either test, but decision 0057 (lines 118–127) describes this check by its content ("the components hold `ClientMessage` and `Hello.client_id`") in its list of `tests/test_attach.py` tests. After the move, that file reference is out of date. This is history and not a cited name, so it does not block the merge. If the merge is made, the commit can add a one-line note. Numbers confirmed: 1 test, net 5 code lines (8 test lines and 2 imports removed, 5 added), 1.19 s.
Checked: merge applied (assertions with `_ref(...)`, `create_app`/`ServerConfig` imports removed from test_attach) → ruff, ruff format and mypy clean; $SCRATCH/tools/runtests.sh test_app.py test_attach.py test_events.py test_job_output.py test_openapi.py test_preview.py test_settings.py test_system.py test_facade_coverage.py -q (all seven changes applied together) → 140 passed in 62 s, 2 other pytest runs on the machine; test_attach 14 → 13 tests, test_openapi 3 → 3.

Orchestrator: Tier A, package Q-7.5.

### TSV-03 Two tests check that task events hide the server's cache folder
- Kind: near-copy
- Where: `packages/reframe-server/tests/test_app.py::test_task_events_name_no_server_folder` (line 381); `packages/reframe-server/tests/test_events.py::test_a_task_event_names_the_cache_folder_by_its_label` (line 431)
- Now: the test_app test runs the app's own hub (from `create_app`) through `api.live()`, starts a real task whose result holds a cache path, and checks that `task.done` carries `<cache>/frames/f.png`. That checks the `hide=` wiring in `app.py:86`. The test_events test replaces the hub with `serving(api, hide=functools.partial(hide_server_folders, api.reframe))`. It publishes `task.progress` and `task.done` with a cache path in `message`, `error` and `result`, and checks all three fields and both event types.
- Change: merge into `test_events.py::test_a_task_event_names_the_cache_folder_by_its_label`. Use the app's own hub (`api.live()` with `signed_in`, not `serving(api, hide=...)`), so that the test also covers the wiring. Delete the test_app test. Delete the now unused `functools` and `hide_server_folders` imports of test_events.
- Saved: 1 test, about 16 code lines, about 0.4 s
- Guarantee kept by: the merged test. With the app's hub it fails when `app.py` stops passing `hide`, which the test_app test pins now. It still fails when any of the three fields or either event type is left out, which the test_events test pins now.
- Why nothing is lost: the test_app input (a `task.done` whose result holds a cache path) is contained in the test_events input (a result `{"frames": [<cache path>]}`, also in message and error, also in progress). The merged test keeps both the wiring and all the fields. One check goes: `serving()`'s "no uvicorn error was logged" check. Every other test in test_events still runs it.
- Docs and history: decision 0047 (line 199) names `test_a_task_event_names_the_cache_folder_by_its_label` as the guard of review finding R-11 ("a real hub made with `hide=functools.partial(hide_server_folders, reframe)`"). Keep that name. If the merge is made, update the parenthesis to "the app's hub". `docs/simplify/areas/queue-jobs.md:32` names `test_task_events_name_no_server_folder` among tests that "check that the server hides its folders in a task result, so they keep their value". The merge keeps that check. `git log -S`: 01ac22e (S-3, "task events show the server's folders as labels (hide=)") and 1c2371a (S-3, "...a test over the real server checks the wiring"). Both are part of the R-11 fix; the merged test keeps both inputs.
- Risk: low to medium. The real hub has the default throttle. The first progress value of an ID is sent at once, so the `task.progress` assertion still holds, but the verify step must confirm it.
- Proposed tier: B
- Confidence: medium
Verdict: ADJUSTED — the merge holds and stays in tier B, but the numbers and the doc follow-ups change. (1) Lines: 17, not about 16: the 14-line test_app test, plus 3 lines in test_events (the `import functools`, the `hide_server_folders` import and the `hide = functools.partial(...)` line). `receive_json` also goes out of the test_app import line, but that removes no line. Time: 0.37 s. (2) The merged test does catch the wiring. With `hide=` removed from `app.py:86`, it fails on the `task.progress` assertion. The throttle risk does not occur: the first progress value of an ID is sent at once, and 4 of 4 runs passed. (3) One input goes with the test_app test: a task that the real `TaskManager` starts (`tasks.start(..., result_json=...)`), with its `task.done` sent to a WebSocket client. covquery shows 50 lines of `reframe/tasks.py` that only this test runs. The merged test publishes its events by hand. The two halves stay tested: core `test_tasks.py` covers task to bus, and the merged test covers hub to client. (4) Docs to change in the same commit: decision 0047 lines 199–201. The parenthesis "a real hub made with `hide=functools.partial(hide_server_folders, reframe)`" becomes "the app's hub"; the test name stays. The 0047 audit statement (lines 188–190: "none is deleted") is history. `docs/simplify/areas/queue-jobs.md:32` (Q-6 is done) names `test_app.py:386-398`; after the merge that reference is out of date. The merged test also loses the "no uvicorn error was logged" check of `serving()`; the auditor names this.
Checked: merge applied (`api.live()` in place of `serving(api, hide=hide)`) → passed in 4 runs (one under load with 2 other pytest runs: 0.23–0.40 s); mutation `EventHub(reframe.events, config)` in app.py → `1 failed` (`['/tmp/pytest...frames/f.png'] == ['<cache>/frames/f.png']`); `covquery.py test_task_events_name_no_server_folder test_a_task_event_names_the_cache_folder_by_its_label` → only A: 76 lines (tasks.py 50, discovery timing, hub close and throttle lines).

Orchestrator: Tier B, package Q-7.10. The merged test starts one real task through the `TaskManager` (not a hand-published event), so the only server test where a real task reaches a WebSocket client stays (verifier note: 50 lines of `tasks.py`); fix the parenthesis in 0047 and `docs/simplify/areas/queue-jobs.md:32` in the same commit.

### TSV-04 Two "client drops while the hub waits to send" tests share their setup
- Kind: near-copy
- Where: `packages/reframe-server/tests/test_events.py::test_a_client_that_drops_while_the_hub_waits_to_send` (line 523); `test_events.py::test_a_client_that_drops_while_the_hub_waits_to_send_has_its_jobs_cancelled` (line 534)
- Now: both sign in, `stall()` the client until the hub cannot send, then `transport.abort()`. The first asserts that the hub's connection count and the bus's subscriber count return to `(0, before)`. The second first attaches a queued job to the client and asserts that the job ends `cancelled`.
- Change: merge into `test_a_client_that_drops_while_the_hub_waits_to_send_has_its_jobs_cancelled`. Keep its attach, and add `before = bus.subscriber_count` and the `wait_until(... == (0, before))` check after the job has ended. Delete the first test.
- Saved: 1 test, about 5 code lines, about 1.6 s
- Guarantee kept by: the merged test. Its input is a superset (the same stall and abort, plus an attached job), and it keeps both assertions.
- Why nothing is lost: the first test's state is the second's without the job. The hub frees the subscription on every disconnect, with or without an attachment (`hub.connections` and `subscriber_count` do not depend on the attachment).
- Docs and history: grep in docs/ for both names finds nothing. `git log -S`: 883b3ae (S-3, decision 0047, the hub) and d63fb5a (S-7, decision 0057, the attachments). Neither commit names a bug.
- Risk: low. An attached job could delay the hub's cleanup; the `wait_until` keeps its 10 s limit.
- Proposed tier: B
- Confidence: medium
Verdict: ADJUSTED — the merge holds and stays in tier B. Lines: net 6, not about 5. The first test (9 code lines) is deleted, and 3 lines are added to the keeper: `bus = ...`, `before = ...` and the `wait_until`. `stall(api.reframe.events, ...)` becomes `stall(bus, ...)`, with no new line. Time: about 1.6 s. Docs: `testdata/README.md:2635` names the keeper as a guard of the recorded uvicorn behaviour. The merge keeps that name. Decision 0057 describes the keeper; decision 0047 (lines 188–190) records that no test_events test was deleted, because each one caught a mutation. The merged test keeps the deleted test's only assertion, so a mutation of the subscription cleanup on a failed send is still caught. No `docs/test-trim-reports/` file names either test.
Checked: merge applied → passed in 4 runs (1.97–3.34 s for the merged test, against 2.39 s + 1.63 s before); test_events 23 → 22 tests.

Orchestrator: Tier B, package Q-7.10.

### TSV-05 Two real-FFmpeg preview clip tests can share one clip
- Kind: near-copy
- Where: `packages/reframe-server/tests/test_preview.py::test_a_clip_task_result_leads_to_a_playable_url` (line 207); `test_preview.py::test_frames_of_a_clip_are_decoded_from_the_clip` (line 227)
- Now: each test copies a fixture, probes it and encodes a preview clip with the real FFmpeg. The first uses `multitrack`, start 0.0, 1 s; it checks `/clips/{id}/link`, no cache folder in the answer, a URL lifetime of about 3600 s, and a 206 answer for `bytes=0-9`. The second uses `letterbox` with a manual crop, start 0.5, 1 s; it checks `/clips/{id}/frames`, no cache folder, 320x134 frames and a PNG served.
- Change: merge into `test_frames_of_a_clip_are_decoded_from_the_clip`. After its clip is done, also get `/api/preview/clips/{clip_id}/link` and assert the 200 answer, no cache folder in it, the lifetime and the 206 range. Delete `test_a_clip_task_result_leads_to_a_playable_url`.
- Saved: 1 test, about 12 code lines, about 1.6 s (one real clip encode)
- Guarantee kept by: the merged test. It checks the link route, the signed URL lifetime and the Range answer on a real clip, plus the frames of the clip.
- Why nothing is lost: the link and Range checks do not depend on the source or the crop: any real clip works. The `multitrack` input class has no other meaning here. `test_media.py` pins the Range details with a cache file, and `packages/reframe/tests/preview/test_clip.py` pins the clip encode itself.
- Docs and history: decision 0067 (line 63) names `test_preview.py::test_frames_of_a_clip_are_decoded_from_the_clip`. Keep that name, which this merge does. `git log -S`: 78ea634 (S-2, the preview routes) and 133df83 (M8 wave 0, decision 0067). Neither commit names a bug.
- Risk: low
- Proposed tier: B
- Confidence: medium
Verdict: CONFIRMED — the link, lifetime and Range checks do not depend on the source or the crop. Both tests are `needs_ffmpeg`, so the keeper is skipped only where the deleted test was skipped too (CI has `REFRAME_REQUIRE_FFMPEG=1`). Decision 0067 cites `test_frames_of_a_clip_are_decoded_from_the_clip` ("a cropped clip gives 320×134 frames"). The merge keeps that name and that assertion. Numbers: 1 test, 11 code lines (the auditor said about 12), about 1.6 s (one real clip encode).
Checked: merge applied → passed in 4 runs (1.7–6.3 s under load; 2.24 s before); test_preview 17 → 16 tests.

Orchestrator: Tier B, package Q-7.10.

### TSV-06 Two settings tests send the same tool-path patch
- Kind: near-copy
- Where: `packages/reframe-server/tests/test_settings.py::test_a_web_client_cannot_choose_a_program` (line 56, 2 cases: `/tools/ffmpeg`, `/tools/extra`); `test_settings.py::test_a_refused_program_names_the_variables_of_the_tools_it_sets` (line 70, 2 cases: ffprobe, ffprobe+ffmpeg)
- Now: all four cases PUT a patch that sets a tool path to `/bin/sh`, and assert `403 settings.tools_forbidden`. The first test also asserts that the tool settings did not change. The second asserts which `REFRAME_*` variables the detail names.
- Change: parametrize as `test_settings.py::test_a_refused_program_names_the_variables_of_the_tools_it_sets` with the cases `["ffprobe"] -> ["REFRAME_FFPROBE"]`, `["ffprobe", "ffmpeg"] -> both`, `["extra"] -> []`. Add the assertion `settings.get().tools.model_dump(exclude_none=True) == {}`. Delete `test_a_web_client_cannot_choose_a_program`.
- Saved: 1 test (4 to 3), about 9 code lines, about 0.1 s
- Guarantee kept by: the merged test. `/tools/ffmpeg` stays in the combined case, the unknown-key case stays, and both assertions apply to every case.
- Why nothing is lost: `/tools/ffmpeg` alone and `/tools/ffprobe` alone take the same branch (`routers/settings.py:68-76`), and the ffprobe-alone case stays. The unknown key `extra` still checks that any key under `/tools` is refused, and now also that its detail names no variable.
- Docs and history: decision 0063 (line 1958) names `test_a_refused_program_names_the_variables_of_the_tools_it_sets` (commit 9d0b8e4, "M4 FE: a refused tool path names the variables of the tools the patch sets"). Keep that name and both of its cases. `test_a_web_client_cannot_choose_a_program` comes from 78ea634 (S-2). No doc names it.
- Risk: low
- Proposed tier: B
- Confidence: medium
Verdict: CONFIRMED — `/tools/ffmpeg` alone takes the same branch as `/tools/ffprobe` alone (`_check` in `routers/settings.py:63-76`). The new `["extra"] -> []` case now also covers the branch of decision 0063 item 2 that names no variable ("Tool paths are set on the server."). The deleted test checked that branch only by its code. The test name of 0063 and its two cases stay, with the same IDs `tools0-named0` and `tools1-named1`. Numbers: 1 test (4 → 3), 10 code lines (the auditor said about 9), about 0.1 s. Optional: give the parameters `ids=` ("ffprobe", "two tools", "an unknown tool key").
Checked: merge applied → 3 cases passed in 4 runs; test_settings 14 → 13 tests.

Orchestrator: Tier B, package Q-7.10.

### TSV-07 The diagnostics "unknown settings field" test repeats the core report test
- Kind: layer-duplicate
- Where: `packages/reframe-server/tests/test_system.py::test_diagnostics_leaves_out_a_settings_field_of_a_newer_version` (line 107)
- Now: the test writes a `settings.json` that has a known field (`diagnostics.log_level`), an unknown field in a known section (`diagnostics.upload`) and an unknown top-level field (`cloud`). It then gets `/api/diagnostics` and asserts that the log level line is there and that `s3cr3t` is not.
- Change: delete
- Saved: 1 test, about 10 code lines, about 0.1 s
- Guarantee kept by: `packages/reframe/tests/test_diagnostics.py::test_the_settings_have_their_known_fields_only` (line 121). It validates `AppSettings` (the same `DocumentModel`, `extra="allow"`, that the settings store loads) with an unknown field in a known section (`diagnostics.upload_key`), an unknown top-level section (`future_section.token`) and a nested unknown field (`output.naming.later`). It asserts that `s3cr3t` is not in the whole report and that the log level line is there.
- Why nothing is lost: the core inputs are a superset of the server's input classes, and the assertions are the same. The route passes the typed `AppSettings` in effect to `build_report`; mypy enforces the type, and the other diagnostics route tests cover the route.
- Docs and history: grep in docs/ finds nothing. `git log -S`: 792713e (Q-4, "the app log reframe.log and the diagnostics report"); it names no bug. Decision 0078 item "the settings: the known fields only" names no test.
- Risk: low. It is a privacy guard, so take tier B: the route could one day pass the raw document. The core test would not see that, but the type checker would.
- Proposed tier: B
- Confidence: medium
Verdict: ADJUSTED — the deletion stays in tier B; the numbers and the risk text change. Lines: 12, not about 10 (11 test lines, and `import json` in test_system.py is then unused). Time: 0.10 s. Is the core input a superset? For the report's filter, yes. `_known` walks `type(value).model_fields` only, so an unknown top-level scalar (the server's `"cloud": "s3cr3t"`) and an unknown top-level section (the core's `future_section`) take the same path. The core test also has the nested case and asserts on the whole text. Does the server test check the HTTP output? Only in part. It reads `json()["text"]` and not the whole body. The other field, `logs_dir`, comes from `data_dir` and cannot hold settings. The server test alone covers this chain: a real `settings.json` on disk, then the settings store, then `Reframe.diagnostics` (`service.py:967`, `self.settings.get()`), then the route. No core test calls `Reframe.diagnostics`. But covquery shows no store or facade line that the other diagnostics route tests do not run as well, so only the data differs. Correction to the risk text: the route does not pass the settings, the facade does (`service.py:967`). A regression there that passes a raw document would fail mypy, as the auditor says. A new report part that leaked unknown fields would fail the core test. No record or trim report names the test.
Checked: deletion applied → test_system 15 → 14 tests, passes; `covquery.py test_diagnostics_leaves_out_a_settings_field_of_a_newer_version test_system.py::test_diagnostics_names_the_logs_folder` → only A: 5 lines (capability device detection timing), only B: 0.

Orchestrator: Tier B, package Q-7.10.

## Looked at and kept
- Coverage group `test_parent ... test_security_filtertext.py::test_ffmpeg_*` (8 tests, 71 lines): these tests run subprocesses (the server process, the real ffmpeg), so their in-process sets are small. The ffmpeg ones are oracle tests (`needs_ffmpeg`).
- `test_security_filtertext.py::test_the_parser_splits_a_graph_where_ffmpeg_does` and `::test_ffmpeg_splits_these_graphs_the_same_way` (both on `FFMPEG_READS`): one tests the parser, one is the FFmpeg oracle for the same inputs. Keep both.
- `test_security_filtertext.py::test_ffmpeg_reads_an_option_value_from_a_file_for_these_texts` (4, one line set) and `::test_free_filter_text_that_reads_a_file_is_refused` (4): oracle and refusal pairs. Each text is a separately verified way to read a file.
- `test_security_filtertext.py::test_safe_free_filter_text_passes[filters3|filters4]` (same lines): a preset with no custom text and an unknown filter id are different input classes of a security check.
- `test_static.py::test_folder_that_holds_a_server_folder_is_refused` (6 cases, 5 on one path): each case is a different server folder field, and a missed field would be a security hole. Keep all.
- `test_static.py::test_no_path_leaves_the_folder`, `::test_windows_path_in_a_request_is_never_resolved`, `::test_unknown_path_gets_index_html[GET-/apiary]`: traversal, encoded, link, NUL and Windows (UNC, drive, device) inputs; `/apiary` checks the `/api` prefix boundary.
- `test_security.py::test_a_tampered_media_url_is_refused[another path|later expiry]` (same lines): different ways to tamper with a URL.
- `test_security_jail.py::test_a_path_that_leaves_the_roots_is_refused[absolute|symlink|traversal]` (same lines): jail input classes (decision 0046).
- `test_folders.py::test_windows_folders_in_any_case_and_with_either_separator` (7 cases, 3 line sets): Windows path cases run on Linux. Keep.
- `test_owner.py::test_the_endpoint_file_setting_is_read_as_the_client_reads_it[blank|padded]`: checks that the server's setting parser and `reframe.remote.owner.endpoint_path` agree on whitespace. Empty, blank and padded are separate classes.
- `test_jail_sweep.py::test_a_link_out_of_a_root_is_refused_and_changes_nothing` (32): one case per path input of a route. It is the sweep guard (decision 0046).
- `test_facade_coverage.py`, `test_frozen_sidecar.py`, `test_openapi.py::test_the_export_is_the_served_document...`, `test_deploy.py`, `test_parent.py`, `test_owner.py` process tests: guards, or tests of real processes.
- `test_job_output.py::test_an_exported_file_is_imported_with_the_same_names[csv|ogm|xml]`: the core also pins each format's round trip (`test_chapters.py`), but this test is the only one at the route level that chains export, file and import, and it keeps TSV-01's guarantee.
- `test_job_output.py::test_a_chapter_range_with_renamed_chapters_names_their_source_slots`, `::test_generated_chapters_have_no_source_slot`, `::test_chapter_markers_off_give_none_with_the_reason`: the core (`command/test_output_chapters.py`) pins the same rows, but these route tests assert `source_name` and `origin` in the JSON answer. The real-encode oracle (`test_the_chapters_route_equals_the_chapters_of_the_encoded_file`) does not assert those fields.
- `test_jobs.py::test_geometry_crops_an_interlaced_source_as_the_builder_does[True|False]`: both cases are needed to show that the route uses the job's view (`job_source_geometry`) and not `source_geometry`. Q-6 names the server geometry tests as the guard.
- `test_subtitles.py` (all `needs_ffmpeg`): the core `analysis/test_subtitlefile.py` hands the real-ffprobe checks to this file. The utf-8, utf-8-bom, cp1250 and utf-16le cases each pin what ffprobe does with that encoding.
- `test_tasks.py::test_a_task_answer_names_no_server_folder` (real frames task) vs `::test_only_the_server_folders_are_hidden`: both come from the R-11 fix (9f74bf6). The real `FrameSet` result is an input no other test has.
- `test_system.py::test_diagnostics_names_the_logs_folder` vs `::test_diagnostics_paths_under_the_home_folder_start_with_a_tilde`: a path outside and a path under the home folder. Merging them would save about 3 lines. Not worth it.
- `test_auth.py::test_the_session_cookie_is_secure_over_https` (its lines are a subset of the login test's): it is the only https input. A parametrize would save no test.
- `test_presets.py::test_defaults_preview_explains_each_source` vs `test_jobs.py::test_explain_with_a_container`: the same expectations through two different routes.
- `test_events.py::test_a_log_burst_keeps_the_latest_lines_and_counts_the_rest` vs `::test_log_lines_are_batched_per_job` (same lines): the line cap versus batching, with different assertions.
- The many subset pairs among `test_app`, `test_security` and `test_auth` (about 1,100 shared lines): this is the shared app and middleware path. Each test asserts a different HTTP property.
- `test_spike_tools.py`, `test_spike_magnifier.py`, `test_spike_results.py` (52 tests, 758 lines): they test the desktop spike's scripts (`desktop/spike/scripts`: KWin, pointer and display-safety guards), not the server. I found no redundancy in them. They could live beside `desktop/spike`, which is a move, not a saving.

## Speed notes
- The OpenAPI document is built in 4 places: the module fixtures of `test_openapi.py` and `test_jail_sweep.py`, the test_attach test (TSV-02), and the facade coverage server. Each build takes about 1.2 s. A session-scoped fixture in `reframe_testing/server.py` would build it once per xdist worker.
- `test_owner.py::test_idle_exit_waits_for_an_event_connection_and_a_running_job` (7.1 s, `slow`) and `test_security_filtertext.py::test_no_allowed_filter_has_an_option_that_names_a_file` (5.5 s, an oracle over every allowed filter) are the slowest tests in the area. Both are guards.

## Verifier notes

- Corrected totals. Tier A: 2 findings, 4 tests, 33 code lines, about 1.9 s (same as the auditor). Tier A+B: 7 findings, 9 tests, **89** code lines (the auditor said about 85: TSV-03 +1, TSV-04 +1, TSV-05 −1, TSV-06 +1, TSV-07 +2), about 5.7 s. The suite goes from 661 to 652 tests (collect-only with all seven changes applied).
- All seven changes applied together pass ruff, ruff format, mypy (598 files) and the eight changed files plus `test_facade_coverage.py` (140 passed). The removals leave two unused imports that the report does not name: `receive_json` in test_app.py (TSV-03) and `json` in test_system.py (TSV-07). Ruff finds both.
- Decision records touched: 0047 (TSV-03: the test name stays, and the parenthesis about the hub must change in the same commit; TSV-03 and TSV-04 also make the "none is deleted" audit line of 0047 history), 0063 (TSV-06: the name and both cases stay), 0067 (TSV-05: the name and the 320×134 assertion stay), 0057 (TSV-02 and TSV-04: these lines describe tests by their content, not by name; after TSV-02 the test_attach.py location is out of date). No merge renames a test that a record cites.
- `docs/test-trim-reports/` (the earlier trim) names no server test of this report. `testdata/README.md:2635` names the TSV-04 keeper, which stays.
- TSV-03 is the only merge that lowers coverage of a real chain (TaskManager → bus → hub → client, with `result_json`). If the owner wants to keep that chain, the merged test can start one real task in place of the hand-published `task.done` and still save the test_app test.
