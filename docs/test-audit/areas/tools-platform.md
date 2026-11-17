# Area tools-platform: `packages/reframe/tests/tools/`, `packages/reframe/tests/platform/`, `packages/reframe/tests/test_applog.py`, `test_diagnostics.py`, `test_paths.py`, `test_fsretry.py`

Baseline: 22 files, 516 tests, 6,964 test code lines, 84 s of test time.

Repository read at `38cf3eb` (`/home/peti/Programming/reframe-test-audit`). Every test file of the area was read in full, with `tools/fetch_server.py` and `testing/reframe_testing/fake_dbus.py`. Earlier work this report does not repeat: the test trim of area T (`docs/test-trim-reports/T.md`, 18 tests already removed, mutation-checked) and Q-6 `docs/simplify/areas/tools-platform.md` (TP-03, TP-04, TP-06, TP-07, TP-09 done; TP-05, TP-10, TP-11, TP-12 Tier C, so their tests are not proposed again).

## Summary

8 findings. Tier A: 5 findings, 7 tests, about 103 code lines, about 1.4 s. Tier A+B: 8 findings, 12 tests, about 132 code lines, about 1.6 s. The area is lean: most of it is guard tests (runner timeout/cancel/limit/tree kill), Windows mock tests, the M2-review D-Bus hardening tests, and the real-bus tests that record verified KDE behaviour. All of these stay. The biggest win is not a deletion. It is a speed fix: about 15 s of the 84 s is the local HTTP server's 0.5 s shutdown poll, paid by 34 fetch tests (see Speed notes).

Best three:
- TTP-02: `test_fetch.py::test_facade_fetch_makes_the_build_the_bundled_one` repeats the result of the CLI test, which prints `app.tools.current` and asserts every field the facade test checks (-1 test, -33 lines).
- TTP-04: two discovery tests became copies of their neighbours after C-18 and D-7. Merge them into those neighbours (-2 tests, -23 lines).
- TTP-01: the plain core cancel test is covered by the slow-download cancel test plus the CLI Ctrl+C test. Add one assert and delete it (-1 test, -24 lines).

## Findings

### TTP-01 The core "cancel stops the download" test is a weaker copy of the slow-download cancel test
- Kind: near-copy
- Where: `packages/reframe/tests/tools/test_fetch.py::test_cancel_stops_the_download_and_installs_nothing` (line 827), `test_fetch.py::test_a_cancel_stops_a_slow_download_at_once` (line 856), `test_fetch_cli.py::test_ctrl_c_stops_the_download` (line 318)
- Now: both core tests serve a foreign-platform archive with padding and a per-block delay (2 MiB at 0.05 s, or 4 MiB at 0.4 s). Both wait until the download has started, call `tasks.cancel(info.id)` and assert `TaskState.CANCELLED` and `leftovers(data_dir) == []`. The first test also asserts that the install folder does not exist. The second also asserts a latency below 2.5 s (decision 0038, 0041 table "E"). The CLI test runs the same 2 MiB / 0.05 s case through `cli.run_tools_fetch`, which calls the same `app.tasks.cancel(info.id)`. It asserts that `<data>/tools` is empty and that "Nothing was installed." is printed.
- Change: delete `test_cancel_stops_the_download_and_installs_nothing`. Add `assert not install_dir_for(data_dir, other, host_platform()).exists()` to `test_a_cancel_stops_a_slow_download_at_once`.
- Saved: 1 test, 24 code lines (25 deleted, 1 added), 0.51 s.
- Guarantee kept by: `test_fetch.py::test_a_cancel_stops_a_slow_download_at_once` (856): cancel during a download whose blocks are being written; asserts CANCELLED, no work folder and (after the change) no install folder. `test_fetch_cli.py::test_ctrl_c_stops_the_download` (318): the same 2 MiB / 0.05 s input; asserts the whole `tools` folder is empty, which is stricter than "no leftovers and no install folder".
- Why nothing is lost: the input class is the same (cancel during a running download of a foreign build), through the same `tasks.cancel` call. Assertions compared: CANCELLED is in the slow test; `leftovers == []` is in the slow test; "no install folder" is moved into the slow test and is also implied by the CLI test's empty `tools` folder. The deleted test also waited until the work folder existed. The slow test sleeps 0.6 s at a 0.4 s block delay after the first request, so at least one block is written.
- Docs and history: `grep -rn` docs: no hit for the deleted test. The kept test is named in `docs/decisions/0038-cli-tools-presets-and-when-done.md:220` and `0041-core-complete-review.md:179`, and it stays. `git log -S`: added in d3f32ae "C-15: reframe tools status|fetch…" (the feature commit, no bug or review finding).
- Risk: low. The kept tests are fast and not flaky.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — the two core tests have the same 274 covered lines; the extra wait of the deleted test (`while not leftovers(data_dir)`) adds nothing, because `_fetch_steps` makes the `.fetch-*` work folder (`tempfile.mkdtemp`, `fetch.py:857`) before the download thread sends its request, so `route.requests > 0` already implies it. Neither core test is POSIX_ONLY, so the keeper runs on Windows CI where the deleted one did. Not named in docs or `test-trim-reports/`; added in the C-15 feature commit d3f32ae. Numbers confirmed: 1 test, 24 code lines (25 deleted, 1 added). Small addition: the deleted test asserted the return value of `tasks.cancel(info.id)`; the keeper discards it, so write `assert tasks.cancel(info.id)` in the keeper too (same line count).
Checked: `covquery.py test_cancel_stops_the_download_and_installs_nothing test_a_cancel_stops_a_slow_download_at_once` → 274 = 274 lines, nothing only in either. Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier A, package Q-7.6. Add `assert tasks.cancel(...)` to the keeper (verifier).

### TTP-02 The facade fetch test repeats what the CLI fetch test asserts
- Kind: layer-duplicate
- Where: `packages/reframe/tests/tools/test_fetch.py::test_facade_fetch_makes_the_build_the_bundled_one` (line 1057), `test_fetch_cli.py::test_fetch_installs_the_build_that_discovery_then_uses` (line 174)
- Now: both are POSIX_ONLY. Both clear `ENV_VARS`, set an empty `PATH`, serve the fake `linux-x64` archive and fetch it through a real `Reframe` (`Reframe.create` or `open_reframe`) and its real rescan. The facade test asserts the task is DONE, then for ffmpeg and ffprobe in `app.tools.current` it asserts status FOUND, origin BUNDLED, the path `<data>/tools/ffmpeg/bin/<name>` and the version `FAKE_VERSION`. Before the fetch it asserts that ffmpeg is MISSING. The CLI prints `status_lines(app.tools.current)` (`cli.py:3344-3346`, `_fetch_report` → `_print_tool_lines`). The CLI test asserts the exact lines `ffmpeg       found    bundled  {install/bin/ffmpeg}  {FAKE_VERSION}`, the same for ffprobe, and exit 0. It also checks `tools status`, the idempotent second fetch and the request count.
- Change: delete `test_facade_fetch_makes_the_build_the_bundled_one`, and the imports that only it uses (`Reframe`, `ENV_VARS`, `ToolOrigin`). The CLI layer keeps the guarantee: its assertions are a superset, and it is the path a user takes.
- Saved: 1 test, about 33 code lines (32 in the test, 1 import line), 0.52 s.
- Guarantee kept by: `test_fetch_cli.py::test_fetch_installs_the_build_that_discovery_then_uses` (174): the same archive, environment and empty PATH, and the same `app.tools.current` after the fetch task. Status, origin, path and version of both tools are asserted through the status lines.
- Why nothing is lost: inputs are the same (an archive for the host platform, no env override, empty PATH). Status/origin/path/version are each asserted. The facade passes `platform=None`, while the CLI passes `platform=host`. The `platform=None` default is still covered by `test_fetch.py::test_fetch_installs_the_build_and_skips_an_intact_install`, which calls `start_fetch` without a platform. The "MISSING before" assert only checks the empty test environment. `covquery`: the facade test covers 7 lines the CLI test does not (`service.py:1032,1040`, the `async with` of `Reframe`, covered by many facade tests; `runner.py:458-464`, a timing-dependent branch of the background capability detection).
- Docs and history: `grep -rn` docs: no hit. `git log -S`: d3f32ae (C-15 feature commit).
- Risk: low. Both tests are POSIX_ONLY, so the platforms that run them are the same.
- Proposed tier: A
- Confidence: medium-high (the docstring says "also over an ffmpeg on PATH", but the test empties PATH, so that case is not tested by either test)

Verdict: ADJUSTED — move to Tier B. The CLI test runs in-process (`reframe_testing.cli.invoke` = typer `CliRunner` on `build_app()`, the same Python process), and both tests carry the same POSIX_ONLY skip (win32 or not linux-x64), so neither runs on Windows CI before or after: no platform is lost. The status/origin/path/version asserts are kept by the CLI status lines, as the auditor says. But one input is lost: the deleted test is the only caller of `ToolsService.fetch(manifest=...)` (`service.py:162-182`) in the whole repository. The CLI does not pass it (it monkeypatches `fetch.DEFAULT_MANIFEST`; `cli.py:3309` passes only `build` and `platform`), and the server passes only `build` (`routers/system.py:118`). After the delete, a facade that dropped the `manifest` pass-through would pass every test. The parameter has no product caller, so the loss is small, but it is a documented public facade argument: delete the test only together with that parameter (a product change, outside a test trim), or keep it. Numbers unchanged: 1 test, 33 code lines (32 + the `from reframe import Reframe` line; `ToolOrigin` and `ENV_VARS` only shorten import lines).
Checked: `grep -rn 'tools\.fetch('` over `packages/` and `testing/` → only `test_fetch.py:1077` passes `manifest=`. Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier C, not planned: the deleted test is the only caller of `ToolsService.fetch(manifest=...)`; removing the parameter is a product change outside this step (listed in README "What is missing or weak").

### TTP-03 Two `tools status` tests invoke the same command; merge them
- Kind: near-copy
- Where: `packages/reframe/tests/tools/test_fetch_cli.py::test_status_prints_the_lines_of_python_m_reframe_tools` (line 90), `test_fetch_cli.py::test_status_lines_are_shared_with_python_m_reframe_tools` (line 139)
- Now: both run `invoke("tools", "status")` with the `fake` tools (env overrides). The first asserts exit 0, the exact two tool lines, the "Fetched build: none …" line and an empty stderr. The second asserts that the CLI's first lines equal `status_lines(asyncio.run(discover_tools()))` and that the tools are in the order ffmpeg, ffprobe. Its coverage is a superset of the first (1030 ⊂ 1032 lines).
- Change: merge into `test_status_lines_are_shared_with_python_m_reframe_tools(fake, env)`: one `invoke`, then every assertion of both tests (exit code, the exact lines 0 to 2, `stderr == ""`, equality with `status_lines`). Keep the synchronous `asyncio.run(discover_tools())` form that `docs/simplify/decisions-taken.md:350` describes.
- Saved: 1 test, about 4 code lines (9 deleted, about 5 assert lines moved), about 0.05 s.
- Guarantee kept by: the merged test, with the same input and the union of the assertions.
- Why nothing is lost: same fixture state and command; every assertion of both tests stays.
- Docs and history: `test_status_lines_are_shared_with_python_m_reframe_tools` is named in `docs/simplify/decisions-taken.md:350` (it stays, under that name). The other test has no docs hit. `git log -S`: both from d3f32ae (C-15).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: ADJUSTED — the merge is sound (same `fake`/`env` fixtures, same command; every assertion kept; `test_status_lines_are_shared_with_python_m_reframe_tools` keeps its name, as `decisions-taken.md:350` needs). The keeper must take the `env` fixture too (for the install path); `fake` already depends on it, so the fixture state does not change. Corrected saving: 1 test, 3 code lines (measured 2 with an extra `out = result.stdout.splitlines()` line, 3 without it; not 4). Tier A stays.
Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier A, package Q-7.6.

### TTP-04 Two discovery tests became copies of their neighbours (after C-18 and D-7)
- Kind: near-copy
- Where: `packages/reframe/tests/tools/test_discovery.py::test_a_bundled_build_is_reported_while_an_override_works` (line 134) and `::test_settings_path_wins_over_bundled` (line 115); `::test_no_bundled_build_is_reported_without_one` (line 153) and `::test_path_is_used_without_a_bundled_build` (line 181)
- Now: (a) `test_a_bundled_build_is_reported_while_an_override_works` builds exactly the setup of `test_settings_path_wins_over_bundled`: the settings override `custom`, a bundled build under `root/ffmpeg/bin`, an empty PATH. It asserts origin SETTINGS, FOUND, `ffmpeg.bundled` and `ffprobe.bundled`. Commit 75d0f9f (C-18) removed its mkvpropedit/MediaInfo half, and what remained is the neighbour's setup. (b) `test_no_bundled_build_is_reported_without_one` builds exactly the setup of `test_path_is_used_without_a_bundled_build`: fakes on PATH, `bundled_roots=[no-root]`. It asserts origin PATH and `not bundled` for both tools. Both pairs have equal or contained coverage sets (255 = 255; 282 ⊂ 287).
- Change: add `assert tools.ffmpeg.bundled` and `assert tools.ffprobe.bundled` to `test_settings_path_wins_over_bundled`. Add `assert not tools.ffmpeg.bundled` and `assert not tools.ffprobe.bundled` to `test_path_is_used_without_a_bundled_build`. Delete the two copies.
- Saved: 2 tests, about 23 code lines (27 deleted, 4 added), about 0.16 s.
- Guarantee kept by: the two receiving tests, with the same `discover_tools(...)` arguments and the two `bundled` assertions each.
- Why nothing is lost: same inputs (fake build folders, settings dict, environ, bundled roots, search path). The copies assert origin/status, which the receiving tests already assert, plus the `bundled` flags, which are moved.
- Docs and history: `grep -rn` docs: no hit for the two deleted names. `test_path_is_used_without_a_bundled_build` is named in `docs/test-trim-reports/T.md:77` (history; it stays). `git log -S`: `test_a_bundled_build_is_reported_while_an_override_works` came from the rename in 75d0f9f "feat(C-18): mkvpropedit and MediaInfo leave tool discovery". `test_no_bundled_build_is_reported_without_one` came from 933dc22 "D-7: Use bundled per tool…" (feature commit, no bug).
- Risk: low. Neither test is Windows-specific. Both run on Windows with the `.cmd` fakes, and the merge keeps that.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — both pairs build the same `discover_tools(...)` arguments (settings `custom` + `root/ffmpeg/bin` + empty PATH; fakes on PATH + `no-root`), and every assertion of the copies is either already in the receiving test or moved. Neither is Windows-only. Not named in docs or `test-trim-reports/` (`test_path_is_used_without_a_bundled_build` appears in `T.md:77` as a keeper, and it stays). Measured: 2 tests, 23 code lines (27 deleted, 4 added).
Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier A, package Q-7.6.

### TTP-05 Two power-countdown tests repeat a neighbour's setup and inputs
- Kind: near-copy
- Where: `packages/reframe/tests/platform/test_power.py::test_defaults` (line 540) and `::test_the_deadline_uses_the_wall_clock` (line 514); `::test_sleep_runs_the_sleep_action` (line 127) and `::test_a_fractional_countdown_reaches_whole_seconds_first` (line 154)
- Now: (a) both build `PowerService(events, executor=FakeExecutor())` with the default countdown and call `schedule("shutdown")`. `test_defaults` asserts `COUNTDOWN_SECONDS == 60.0` and the phases `[("started", 60)]`. The deadline test asserts exactly one started event, with a deadline between `before + 60 s` and `after + 60 s`, which already pins the 60 s default. `test_defaults` was restored by the T trim only because of the `PowerService.countdown` getter (`T.md:28,115`). TP-07 (Q-6.7) removed that getter, so that reason is gone. (b) Both schedule `"sleep"` and assert the phase list and `executor.actions == ["sleep"]`. The sleep test uses an integer countdown of 3 with `service._sleep = instant`. The fractional test uses 2.5 with the Ticker. The sleep test also asserts that no `AppWarningEvent` is published. Equal coverage sets in both pairs.
- Change: (a) add `assert started.seconds_left == 60` to `test_the_deadline_uses_the_wall_clock` and delete `test_defaults`. (b) In the fractional test, drain the subscription once, assert the countdown phases from it, and add `assert not [e for e in events if isinstance(e, AppWarningEvent)]`. Then delete `test_sleep_runs_the_sleep_action`.
- Saved: 2 tests, about 19 code lines (22 deleted, 3 added), under 0.05 s.
- Guarantee kept by: `test_the_deadline_uses_the_wall_clock` (default countdown: deadline at +60 s and, after the change, `seconds_left == 60`); `test_a_fractional_countdown_reaches_whole_seconds_first` (the sleep action, the phases, and after the change no warning on success). The integer-countdown phase sequence stays covered by `test_full_countdown_phases_in_order_then_the_executor_runs` (60) and `test_quit_only_publishes_executing` (2).
- Why nothing is lost: the default-countdown input and the "sleep" input stay. `COUNTDOWN_SECONDS == 60.0` is a constant, and the +60 s deadline and `seconds_left == 60` check it through behaviour. A countdown of 3 with integer ticks takes the same path as the 60 s and 2 s tests.
- Docs and history: `test_defaults`: `docs/test-trim-reports/T.md:28,115` (restored for the getter that TP-07 deleted; checked: `power.py` has no `countdown` property now). `test_sleep_runs_the_sleep_action`: no docs hit. `git log -S`: all four from 70e662e "C-14: power actions with a cancellable 60 s countdown" (feature commit).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — (a) T.md restored `test_defaults` only for the `PowerService.countdown` getter; that getter is gone (removed in 96f2273 Q-6.7; `power.py` has only the `executor` and `pending` properties), so the recorded reason no longer holds. The default `now` stays covered by the deadline test, the default `sleep` by `test_the_default_sleep_counts_real_seconds`; equal coverage (126 = 126). (b) Equal coverage (133 = 133). The "no AppWarningEvent" assertion of `test_sleep_runs_the_sleep_action` is in fact vacuous today: `countdown_events()` drains the subscription first, so the second `drain()` sees only events published after that; draining once, as proposed, makes the check real. Measured: 2 tests, 19 code lines.
Checked: `covquery.py test_power.py::test_defaults test_the_deadline_uses_the_wall_clock` → 126 = 126; `covquery.py test_sleep_runs_the_sleep_action test_a_fractional_countdown_reaches_whole_seconds_first` → 133 = 133. Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier A, package Q-7.6.

### TTP-06 Two D-Bus error tests through `call()` repeat the `Connection` tests that cover the same failures
- Kind: layer-duplicate
- Where: `packages/reframe/tests/platform/test_sleep_dbus.py::test_hello_error_raises` (line 360) and `::test_connection_open_failure_closes_the_socket` (line 533); `::test_error_reply_raises_dbus_error` (line 350) and `::test_connection_close_after_an_error_reply_frees_the_socket` (line 520)
- Now: `dbus.call()` is `Connection.open(...)`, then `connection.call(...)` with a `finally: connection.close()` (`dbus.py:662-694`). (a) Both tests run the fake bus with `hello_error=True`. One goes through `call()` and asserts `DBusError` matching `Error\.Failed: no`. The other goes through `Connection.open` and asserts `DBusError` and no new fds. Coverage: the `call()` test only adds `dbus.py:679-681`, the call into `Connection.open`. (b) Both use `inhibit="error"`. The `call()` test asserts the error name, the message, `str()` and no fd leak. The `Connection` test asserts `DBusError`, `connection.closed` and no fd leak. Coverage: the `call()` test adds `call()`'s body, which the other `call()` tests also run (`test_silent_bus_times_out` takes the same `finally` on `TimeoutError`, with an fd-leak check).
- Change: (a) add `match=r"Error\.Failed: no"` to `test_connection_open_failure_closes_the_socket` and delete `test_hello_error_raises`. (b) bind the error (`as info`) in `test_connection_close_after_an_error_reply_frees_the_socket`, add the three name/message/`str` asserts, and delete `test_error_reply_raises_dbus_error`.
- Saved: 2 tests, about 11 code lines, about 0.05 s.
- Guarantee kept by: the two `Connection` tests, with the same fake-bus scenarios and all of the error assertions. `call()` closing its connection on an error stays covered by `test_silent_bus_times_out` (fd check) and by `test_broken_bus_peer_raises_only_the_documented_errors` (10 peers, no leaked sockets).
- Why nothing is lost: same scenarios (`hello_error`, `inhibit="error"`). Every assertion moves. `call()` adds no error handling of its own: it re-raises from `Connection.open` or `connection.call`.
- Docs and history: `grep -rn` docs: no hit for any of the four. `git log -S`: `test_hello_error_raises` and `test_error_reply_raises_dbus_error` come from 6af5bb6 (the first C-14 commit, no bug). The `Connection` tests come from 8a87a76 (C-14, decision 0020) and b9b4c3b (Q-6.17, which replaced the `with Connection` test).
- Risk: low to medium. TP-11 (Tier C) would delete `call()`. The `Connection` layer is the one that stays in either case, which is why it keeps these assertions.
- Proposed tier: B (0011's follow-up "raises only documented errors" is a guard area. The merge keeps every assertion, but it moves the `call()`-level error-reply check onto `Connection`.)
- Confidence: medium

Verdict: CONFIRMED (Tier B) — `call()` re-raises from `Connection.open` / `connection.call` and closes in one `finally` (`dbus.py:662-694`); the error-reply case through that `finally` is also taken by `test_silent_bus_times_out` (fd check). All name/message/`str` assertions and the `Error\.Failed: no` match move. Neither test is in the known-flaky list (`test_connection_stays_open_for_several_calls_and_closes` is, and it is not touched). Not named in docs or `test-trim-reports/`. Measured: 2 tests, 11 code lines. The small residual: `call()` itself (used by `sleep.py:181` as the logind default) loses its only error-reply leak check; that is why B, not A, is right.
Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier B, package Q-7.12.

### TTP-07 Four diagnostics-report tests build the same report; one test can check the four parts
- Kind: near-copy
- Where: `packages/reframe/tests/test_diagnostics.py::test_the_report_has_the_version_server_os_and_python_first` (line 83), `::test_each_tool_has_status_origin_path_version_flags_libraries_and_reason` (line 90), `::test_each_encoder_has_its_status_and_reason_in_a_stable_order` (line 107), `::test_a_logs_folder_that_does_not_exist_is_said` (line 182)
- Now: each calls `report(tmp_path)` with the default arguments and checks one part (head, Tools, Encoders, Logs). They form one equal-set coverage group (4 tests, 95 lines).
- Change: one test `test_the_default_report_part_by_part` that builds `text = report(tmp_path)` once and keeps all four blocks of assertions unchanged.
- Saved: 3 tests, about 5 code lines, under 0.05 s.
- Guarantee kept by: the merged test, with the same input and all four sets of assertions.
- Why nothing is lost: same input; every assertion stays. Only the failure granularity is coarser.
- Docs and history: `grep -rn` docs: no hit. `git log -S`: all from 792713e "Q-4: the app log reframe.log and the diagnostics report" (feature commit; decision 0078 names behaviours, not these tests).
- Risk: low
- Proposed tier: B (little gain; it is a consolidation, not a redundancy)
- Confidence: high

Verdict: CONFIRMED (Tier B) — same `report(tmp_path)` input; every assertion kept in the merged test. Measured: 3 tests, 6 code lines (not 5).
Checked: applied TTP-01 to TTP-07 together in the worktree (`apply.py` in `$SCRATCH/tp/`), `ruff check`, `ruff format`, `mypy` on the 6 files → clean; `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py tools/test_discovery.py platform/test_power.py platform/test_sleep_dbus.py test_diagnostics.py -q` → 233 passed in 7.57 s (before: 245 collected; after: 233), load: 3 other pytest runs on the machine. Reverted with `git checkout -- .`.

Orchestrator: Tier B, package Q-7.12.

### TTP-08 Fetch test setup and the `_alive` helper are copied between files
- Kind: shared-setup
- Where: `packages/reframe/tests/tools/test_fetch.py` (`server` fixture line 69, `POSIX_ONLY` line 62, `_ext` line 466) and `test_fetch_cli.py` (`POSIX_ONLY` line 44, `server` fixture line 59, `_ext` line 82); `_alive(pid)` in `tools/test_runner.py:32`, `tools/test_discovery.py:896` (and, cross-area, `tests/test_tasks.py:24`)
- Now: the two fetch files define the same `server` fixture (`yield from local_server()`), the same `POSIX_ONLY` marker and the same `_ext`. The same 5-line `_alive` (a psutil zombie-aware liveness check) appears in three test modules.
- Change: move `server` into a new `packages/reframe/tests/tools/conftest.py` (the folder has `__init__.py`; a conftest fixture avoids re-exporting a fixture by import). Move `POSIX_ONLY` and `_ext` into `tools/fetch_server.py`, which both files already import. Move `_alive` into `testing/reframe_testing/` (for example next to `wait_until` in `waiting.py`, or into `fake_tools.py`).
- Saved: 0 tests, about 13 code lines in this area (about 5 more in `test_tasks.py`).
- Guarantee kept by: unchanged tests.
- Why nothing is lost: only helpers move.
- Docs and history: none
- Risk: low. `testing/` is checked by `mypy --platform win32`; `_alive` only uses psutil, which works there.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED (Tier B) — the `server` fixture, `POSIX_ONLY` and `_ext` are identical in `test_fetch.py` (62, 69, 466) and `test_fetch_cli.py` (44, 59, 82); `_alive` is identical in `test_runner.py:32`, `test_discovery.py:896` (with a local `import psutil`) and `test_tasks.py:24`. Subfolder `conftest.py` files already exist (`tests/jobs`, `tests/queue`, …), so a `tests/tools/conftest.py` fits the layout. Not applied; the line saving depends on the import lines the moves add, about 8 to 13 code lines in the area.

Orchestrator: Tier B, package Q-7.12.

## Looked at and kept

- `tools/test_runner.py`, every test: the runner's timeout, cancel, output limit, tree kill, pipe drain and PDEATHSIG/job tests are guards (C-1, decisions 0005, 0022, 0084, D-45). Coverage groups checked and kept: `test_default_output_limit_is_16_mib` = `test_large_output_is_limited_and_drained` (the default limit and an explicit `max_output` are different inputs); `test_output_below_the_limit_is_complete` (the "not truncated" boundary); `test_one_token_cancels_several_runs` ⊂ `test_cancel_from_a_coroutine` (several runs on one token is its own case); `test_timeout_does_not_depend_on_sigterm` ⊂ timeout tests (it is the only SIGKILL `-9` check); `test_directory_is_a_result` = `test_not_executable_file_is_a_result` (T.md: on Windows a directory gives a different error); `test_streaming_keeps_the_tail` ⊂ `test_streaming_splits_very_long_lines` (tail and line split are different behaviours); `test_streaming_passes_lines_to_callbacks` ⊂ `test_streaming_with_async_callbacks` (sync vs async callbacks); `test_programming_errors_raise[argv2]`/`[argv3]` (timeout 0 and -1 are the boundary and the negative case).
- `tools/test_runner.py::test_line_splitting_does_not_depend_on_chunk_boundaries` (Hypothesis, private `_LineSink`): the example tests through `run_streaming` check callbacks, async callbacks and the tail, which the property does not. Both stay.
- `tools/test_runner.py::test_kill_leftovers_on_windows_kills_the_orphans`, `test_kill_leftovers_on_posix_kills_the_process_group`: Windows/POSIX branches with mocks.
- `tools/test_fetch.py::test_unsafe_member_names` (8 cases, 3 line sets), `test_an_unsafe_or_broken_archive_installs_nothing` (10), `test_a_link_chain_that_leaves_the_build_folder_is_refused` (4: the "other order" case is deliberate), `test_a_bad_manifest_is_refused` (20; `ftp` was restored by T after a mutation; `size=0` vs `size=True` are an int and a bool), `test_file_and_loopback_urls_are_allowed` (an IP and a host name): fetch security checks, decision 0038 items 4 and 5. One input class per case.
- `tools/test_fetch.py::test_another_platform_goes_next_to_the_bundled_folder` ⊂ `test_fetch_cli.py::test_fetch_for_another_platform`: only the core test asserts `rescans == 0` and that the version check did not run. Only the CLI test asserts the copy hint.
- `tools/test_fetch.py::test_a_bad_checksum_installs_nothing_and_keeps_the_old_build` vs `test_fetch_cli.py::test_a_bad_checksum_is_one_error_line`: only the core test checks that the old build is kept; only the CLI test checks the one error line.
- `tools/test_fetch.py::test_unknown_build_and_platform` vs `test_fetch_cli.py::test_unknown_build_and_platform_are_usage_errors`, and `test_an_unsupported_host_needs_a_platform` vs `test_an_unsupported_host_without_platform`: the CLI checks these before it starts the task (`cli.py:3286-3302`, its own texts), so the two layers run different code.
- `tools/test_fetch.py::test_a_cancel_after_the_swap_finishes_and_says_so` and `test_fetch_cli.py::test_the_cli_says_what_was_installed_after_an_interrupt`: R5-5 (decisions 0038, 0041); TP-10 is Tier C.
- `tools/test_fetch.py` `root=None` tests and `test_paths.py::test_bundled_subdirs`: TP-05 Tier C; `T.md`/`Q.md` restored `test_bundled_subdirs` after a mutation.
- `tools/test_fetch.py::test_a_file_url` vs `test_file_and_loopback_urls_are_allowed`: one downloads through `file:`, the other only parses the manifest.
- `tools/test_fetch.py::test_permission_errors_are_retried`, `test_sleep_ends_at_a_cancel`, `test_swap_puts_the_old_build_back_when_the_new_one_cannot_move` (private helpers): no public test reaches the Windows scanner retry, the cancel during the back-off, or the failed swap.
- `tools/test_fetch.py::test_packaged_manifest_is_a_copy_of_tools_ffmpeg_toml`, `test_the_core_and_the_script_read_the_manifest_alike`, `test_the_script_and_the_core_recognise_each_others_install`: decision 0038 item 4 (two implementations on purpose).
- `tools/test_fetch_cli.py::test_status_help`, `test_fetch_help`: they check the documented exit codes (T.md).
- `tools/test_discovery.py`: the Windows tests (`platform="win32"`), the libva group of 5 equal-set tests (each a different folder layout), `test_bundled_wins_over_path` = `test_tool_env_reaches_the_version_check` (the second checks the env reaching the version check), the `TOO_OLD` settings/env pair (different fixes), `test_broken_override_crash` (the only negative return code, T.md), `test_mkvtoolnix_and_mediainfo_are_neither_found_nor_run` (C-18 guard), `test_cancelled_discovery_leaves_no_process` (a recorded `asyncio.gather` bug), `test_main_reports_and_checks_the_origin` (`python -m reframe.tools`, used by CI).
- `tools/test_versions.py`: recorded real version outputs (`test_real_version_outputs`, 9 files, 2 line sets) and the 7 real-world version strings (T.md kept them on purpose); `test_lib_major_to_series` and `test_not_ffmpeg_output` were already trimmed by T.
- `tools/test_discovery_real.py`: a `needs_ffmpeg` oracle test.
- `platform/test_childproc.py`, all tests: Windows Job Object and `CREATE_NO_WINDOW`/breakaway mocks, PDEATHSIG. `test_launch_detached_on_posix` = `test_launch_detached_real_process` (a mock kwargs check vs a real process); `test_the_environment_stays_when_not_a_frozen_linux_app` (2 cases: not frozen on Linux vs frozen on Windows).
- `platform/test_longpath.py`: Windows `MAX_PATH` rules (decision 0070). `test_a_character_outside_the_bmp_counts_twice` = `test_a_path_is_refused_from_max_path_on` in lines, but a different input (UTF-16 length).
- `platform/test_power_executors.py`: all the Windows privilege and DLL mocks; `test_systemctl_failures_are_strings` (7 cases, 4 line sets: stderr, stderr with a leading blank line, stdout only, no text are different inputs to the last-line chooser); `test_systemctl_path_can_be_given` (the only test of the `systemctl=` argument, T.md).
- `platform/test_power_safety.py`: decision 0036 guards (no test may shut down the machine).
- `platform/test_power.py`: the power-test subset pairs (cancel, close, failing executor, quit) each assert a different phase or race; `test_quit_has_nothing_to_wait_for` (T.md, f1b33bd); `test_a_failing_sleep_without_reason` vs `test_a_failing_executor_is_one_app_warning` (a different message and no reason); `test_invalid_countdown` (-1, inf, nan are three input classes).
- `platform/test_sleep.py`: the counted inhibitor rules (decision 0011 follow-up items 3 to 5, 0022). `test_no_events_bus_is_fine` is the control of a T mutation.
- `platform/test_sleep_backends.py`: Windows `SetThreadExecutionState` mocks (TP-14 guard, Q-6.12), `test_windows_backend_accepts_a_mock_kernel32` (restored by T, runs on Windows), logind and session fakes. `test_logind_expected_failures_are_data` (4 cases, 3 on one line set): the failure texts are recorded in `testdata/README.md:937` and the cases are different error classes. `test_logind_takes_the_lock_when_logind_acts_on_idle_or_it_is_unknown` (`suspend` vs an empty reply are different inputs).
- `platform/test_sleep_dbus.py`: the golden bytes (jeepney reference), fd passing, the leak checks. `test_call_returns_the_file_descriptor_and_leaks_nothing` = `test_call_with_extra_descriptors_returns_them_all` (one fd vs two).
- `platform/test_sleep_failures.py`: `test_broken_bus_peer_raises_only_the_documented_errors` ⊂ `test_broken_bus_peer_is_unavailable_never_an_exception` (each peer case) and `test_unusable_bus_address_*` ⊂ `test_default_inhibitor_with_malformed_environment` (4 cases): the M2 review hardening (c3dc9ad, decision 0011 follow-up items 1 and 2) at two layers on purpose. The D-Bus layer pins the documented exception classes; the inhibitor layer pins "never raises". The environment test catches the `except TypeError` regression (T.md mutation table).
- `platform/test_sleep_real.py`: real-bus tests that record verified KDE/logind behaviour (`testdata/README.md:809-916`). `test_session_inhibit_appears_and_disappears` vs `test_default_inhibitor_on_this_desktop` overlap, but they need different fixtures (no logind vs logind) and assert different things (`backend.interface`, who). The two `⊂` pairs from the coverage map are different mechanisms (closing the connection vs UnInhibit; a logind lock mirrored by KDE).
- `test_applog.py`: the 0078 review items (rotation failure on Windows, a retried rotation, NaN, circular data, bytes, uvicorn levels). `test_a_value_that_is_not_json…[bytes]` = `[circular]` in lines, different inputs. `test_the_access_log_is_never_written` = `test_at_debug_uvicorn_stays_at_info…` in lines, different loggers and rules. The server's `reframe-server/tests/test_applog.py::test_at_debug_uvicorn_is_written_from_info_up_and_its_access_log_never` repeats the two at the server layer with uvicorn's real log config. It is outside this area and checks the real setup that `known_levels` imitates here, so both stay.
- `test_diagnostics.py`: `test_paths_under_the_home_folder_start_with_a_tilde` (11 cases, 4 line sets) and the Windows variant (5 cases): each case is a different boundary (a trailing dot, quotes, a new line, `ann` vs `anna`/`ann.bak`, case, a prefix) for decision 0078 items 6 and 7; `test_the_windows_os_line…` (4 cases: a missing registry, a missing `PROCESSOR_ARCHITECTURE`); `test_a_home_folder_at_the_root_changes_nothing` (3 roots); `test_the_default_home_is_the_users` = `test_the_folder_that_the_home_links_to…` in lines, different inputs (the Fedora Atomic link).
- `test_paths.py`: `test_default_environment_is_os_environ` = `test_relative_override_is_made_absolute` in lines, different behaviours.
- `test_fsretry.py`: Windows sharing-violation retry with mocks.

## Speed notes

- `tools/fetch_server.py:209` (`LocalServer`): `serve_forever()` uses the default `poll_interval=0.5`, so `close()` → `shutdown()` waits up to 0.5 s for every test that uses the `server` fixture. 34 fetch tests take 0.50 to 0.53 s each (18.1 s of the area's 84 s), most of it this wait. `threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)` should save about 15 s of test time, with no test change.
- `tools/test_runner.py::test_kill_process_tree_can_keep_the_root` (5.09 s): `psutil.wait_procs(killed, timeout=5)` waits on the grandchild. Its parent (the fake ffmpeg, kept alive by `kill_root=False`) never reaps it, so it stays a zombie until the 5 s timeout. Polling with the file's own `_alive` (zombie counts as dead) instead should save about 5 s.
- `tools/test_runner.py::test_the_pid_lets_the_caller_suspend_and_resume_the_tree` (4.74 s): the child prints 400 lines at 10 ms each (4 s). About 100 lines are enough for "more than 5 lines, suspend 0.6 s, resume, last line"; that saves about 3 s.
- `platform/test_sleep_real.py` (29 s, 5 tests of about 5.5 s): KDE makes an inhibition active about 5 s after the request (`testdata/README.md:829`). That time comes from KDE, not the test; the tests skip in CI.
- `platform/test_power.py::test_the_default_sleep_counts_real_seconds` (1.5 s): a countdown of 1.1 instead of 1.5 still gives `started 2, tick 1, executing` (about 0.4 s saved). Minor.

## Verifier notes

- Corrected totals. Tier A (TTP-01, TTP-03, TTP-04, TTP-05): 6 tests, about 69 code lines (24 + 3 + 23 + 19). Tier A+B (adds TTP-02, TTP-06, TTP-07, TTP-08): 12 tests, about 132 code lines (69 + 33 + 11 + 6 + about 13). Measured with TTP-01 to TTP-07 applied: 245 → 233 tests in the 6 files, 118 code lines removed (test_fetch.py 57, test_discovery.py 23, test_power.py 19, test_sleep_dbus.py 11, test_diagnostics.py 6, test_fetch_cli.py 2).
- Poll-interval speed note, measured: `runtests.sh tools/test_fetch.py tools/test_fetch_cli.py -q --durations=0` (106 tests) before and after `kwargs={"poll_interval": 0.05}` in `fetch_server.py:209`. Summed test time 21.3 s → 10.5 s; teardown alone 14.0 s → 1.4 s (call 6.9 → 8.5 s, setup 0.4 → 0.6 s: load noise); wall time 8.25 s → 6.97 s at `-n 4`; all 106 passed both times. Load: 3 other pytest runs on the machine. Change reverted. So the saving is about 12.6 s of teardown (the auditor estimated about 15 s).
- With that speed fix in place, the time saved by TTP-01 and TTP-02 drops from about 0.5 s each to under 0.1 s each (most of their 0.5 s is the server's shutdown wait).
- TTP-02 docstring: "also over an ffmpeg on PATH" is not tested by either test (the auditor saw this). If the facade test is kept (see the verdict), fix the docstring or put a fake ffmpeg on PATH.
- Set-up side effect: the `testdata/media` symlink of step 3 shows as untracked in `git status` (the ignore pattern matches a directory, not a symlink to one). I removed the symlink at the end so that `git status` is clean; none of this area's tests need generated media.
