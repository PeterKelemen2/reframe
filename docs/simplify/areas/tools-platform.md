# tools-platform: simplification findings

Commit: 85d9dcb.
Verified: 2026-11-15, 3 confirmed, 12 adjusted, 0 rejected.

Scope: `packages/reframe/src/reframe/tools/`, `platform/`, `paths.py`, `applog.py`, `diagnostics.py`, with `packages/reframe/tests/tools/`, `tests/platform/`, `tests/test_paths.py`, `tests/test_applog.py`, `tests/test_diagnostics.py`. Source lines: about 4.2k code lines (tools 1712, platform 1957, applog 245, diagnostics 196, paths 61). Read in full: `tools/runner.py`, `tools/discovery.py`, `tools/fetch.py`, `tools/versions.py`, `tools/__main__.py`, `tools/__init__.py`, `tools/exitcodes.py`, `platform/childproc.py`, `platform/longpath.py`, `platform/notify.py`, `platform/power.py`, `platform/sleep.py`, `platform/dbus.py`, `paths.py`, `applog.py`, `diagnostics.py`; also `scripts/fetch-tools.py` (for TP-01). Only skimmed: all test files (read only the parts the findings name: `test_sleep_dbus.py`, `test_sleep_failures.py`, `test_sleep_backends.py`, `test_sleep_real.py`, `test_discovery.py`, `test_versions.py`, `test_fetch.py`, `test_runner.py` by grep).

Coverage note: `coverage.txt` ends with a table, but it counts module-level lines (imports, `def` lines) as missed in every file of this area (for example `applog.py` 11-69, `paths.py` 8-42). The numbers are not reliable for this area, so no finding rests on them.

## Summary

The subprocess core (`tools/runner.py`, `platform/childproc.py`) is lean for what the plan requires: one process-running path (`run` / `run_streaming`), plus `launch_detached` for user-facing programs, which the plan names as the one exception. The biggest duplication is not inside the area: `tools/fetch.py` and `scripts/fetch-tools.py` carry the same manifest checks, safe extraction, download, tree digest and marker code twice, on purpose (decision 0038 item 4). The biggest mass is the Linux sleep inhibit (`sleep.py` 627 + `dbus.py` 554 code lines, about 2k test lines): a stdlib D-Bus client with file-descriptor passing, built for the logind backend that decision 0022 keeps for headless machines. Smaller wins: a second copy of the discovery loop in `ToolsService`, options of `run` / `run_streaming` that no production caller uses, leftovers of the MKVToolNix / MediaInfo removal (`root=None`, `BUNDLED_SUBDIRS`), members used only by tests, and two copies of a fake D-Bus server in the tests. Nothing in `diagnostics.py`, `paths.py` or the Windows job and power code is worth changing; they are in "Looked at and kept".

## Findings

### TP-01: `scripts/fetch-tools.py` repeats `reframe.tools.fetch` (decision 0038 item 4)
- Kind: decision-change (also duplication, cross-area: scripts)
- Where: `scripts/fetch-tools.py` (595 raw lines, about 290 code lines of it repeat the core: `PlatformBuild`, `Build`, `_get_str`, `_get_table`, `_get_rel_path`, `_parse_platform`, `_parse_build`, `parse_manifest`, `load_manifest`, `sha256_file`, `verify_file`, `download`, `member_path`, `_check_link_target`, `_extract_tar`, `_extract_zip`, `safe_extract`, `tree_digest`, `_is_installed`, `_move_into_place`, `_write_marker`, `_check_replaceable`); `packages/reframe/src/reframe/tools/fetch.py:105-614` (the same functions, the stricter copy); `testing/tests/test_fetch_tools.py` (630 raw lines, 35 tests, about 22 of them test the repeated functions); `docker/Dockerfile:52-59`; `.github/workflows/ci.yml:68,305,389,453`; `.github/workflows/release.yml:187,387`.
- Now: two implementations of "check the manifest, download, verify SHA-256 and size, extract safely, write `.fetch-tools.json`". Decision 0038 item 4 keeps them apart on purpose: the script must run before `uv sync` (`uv run --no-project`, stdlib only) and its tests replace its module-level `download` and `detect_platform`. The two have already drifted: the core has `_check_links` (links resolved through each other, a chain that leaves the build folder is refused, complexity 15) and a `tar.bz2` mode; the script only has `_check_link_target` (one `normpath` check, no chain resolution). So the build that CI and the Docker image install is checked less strictly than the one `reframe tools fetch` installs. Two other scripts already import the core module (`scripts/bundle-tools.py:30`, `scripts/sources-fetch.py:38`, both after `uv sync`), so "no shared code" is already not true for the repo.
- Change: one implementation of the stdlib-only part. Move the pure functions (manifest parse and validation, `member_path`, `_check_links`, `_extract_tar`, `_extract_zip`, `safe_extract`, `tree_digest`, `sha256_file`, `verify_file`, `download` with its retries, marker read and write, `check_replaceable`, the swap) into a module that imports only the standard library, for example `packages/reframe/src/reframe/tools/fetchlib.py`, with its own `FetchError`, and with the cancel check passed in as a plain callable (`check_cancel: Callable[[], None] = lambda: None`) instead of `CancelToken`. `reframe.tools.fetch` keeps the task glue (`_Job`, `_fetch_steps`, progress, `_check_version` through `run`, `start_fetch`) and imports it normally. `scripts/fetch-tools.py` becomes a thin CLI (`main`, `detect_platform`, `check_version`, `install`, `install_bundled`, about 120 lines) that loads `fetchlib.py` by file path with `importlib.util.spec_from_file_location` (the module has no `reframe` import, so no `uv sync` is needed). `docker/Dockerfile:52` adds one `COPY` for that file. What would have to be true for 0038 item 4 to change: the owner accepts one path-loaded module in the script (0038 calls this "path tricks") and the script's tests are rewritten to patch the shared module. A second option, simpler but with a CI cost: `scripts/fetch-tools.py` imports `reframe.tools.fetch` directly and the CI jobs and the Docker `tools` stage run `uv sync --frozen` first. That moves `ci.yml:68` after `ci.yml:78` and needs pydantic and psutil in the Docker stage, so the path-loaded module is the better one. The two copies differ in more than the link check, and the shared module has to carry every difference as a parameter or one chosen behaviour: (1) the URL policy (`_check_url` of the core accepts `file:` and `http:` on loopback, 0038 item 5; the script accepts `https://` only), so the shared validator takes the allowed-URL check as an argument and the core passes its wider one; (2) the error classes (the script has `ManifestError`, `ChecksumError` and `UnsafeArchiveError` under `FetchError`, and `testing/tests/test_fetch_tools.py` asserts them; the core has `FetchError` only, and `cli.py` and `scripts/bundle-tools.py` catch `fetch.FetchError`), so `reframe.tools.fetch.FetchError` must stay the same class as the shared one (re-export); (3) the message texts ("download failed after" in the script, "the download failed after" in the core; both are asserted by tests); (4) `download` takes `sleep=` and `max_bytes=` in the script and `cancel=` and `progress=` in the core. In the Docker `tools` stage the new file must be copied to the path the script resolves from `REPO_ROOT` (`/src/packages/reframe/src/reframe/tools/fetchlib.py`); `.dockerignore` already lets `packages/reframe/src` into the context, so no allow-list change is needed.
- Behaviour: unchanged for the user. CI and the Docker image get the stricter link check of the core (a pinned archive with a link that leaves the folder would now be refused; the pinned BtbN archives pass it because `reframe tools fetch` installs them in tests).
- Contracts touched: none (the marker format `.fetch-tools.json` stays; the tests that check "each recognises the other's install" stay). CI workflows and the Docker image build change.
- Callers to update: `scripts/fetch-tools.py`; `packages/reframe/src/reframe/tools/fetch.py`; `scripts/bundle-tools.py:30` (`fetch.download`, `fetch.safe_extract`, `fetch.tree_digest`, `fetch.installed_build`, `fetch.verify_file`, `fetch.load_manifest`, `fetch.FetchError`); `scripts/sources-fetch.py:38`; `packages/reframe/tests/tools/test_fetch.py`, `test_fetch_cli.py`, `fetch_server.py`; `testing/tests/test_bundle_tools.py:20`; `docker/Dockerfile`.
- Tests: delete the tests of `testing/tests/test_fetch_tools.py` that test the repeated functions (manifest cases, `member_path`, `safe_extract`, `download` retries, `verify_file`; keep the CLI tests `main`, `detect_platform`, `install`, `install_bundled`, the marker round trip with the core). `packages/reframe/tests/tools/test_fetch.py` stays the guard of the shared code; add one test that the script loads the shared module. The test that the packaged `ffmpeg.toml` equals `tools/ffmpeg.toml` stays.
- Decision records: 0038 item 4 (changes), item 3 (the packaged manifest copy: unchanged), 0002 and 0005 item 4 (CI installs through the script: unchanged), 0059 (Docker `tools` stage: one more `COPY`).
- Size: L; estimated lines: -290 source (script) +0 / -400 tests (the tests of the repeated functions are rewritten against the shared module, so the net is smaller)
- Risk: medium. The CI and Docker steps run before the project is installed; a wrong path or an import of a non-stdlib module breaks every CI job and the image build. Check with a Docker build and one CI run of each workflow. The Windows CI jobs also run this script (`windows-x64`): run it on the Windows test VM.
- Depends on: none
- Confidence: medium
- Verdict: ADJUSTED (35 tests, not 34; the shared module must also carry the URL policy, the error subclasses, the message texts and the `download` seams that differ today, added to Change; `scripts/bundle-tools.py:94-182` holds a third manifest validator that this change does not touch; the decision-change condition is honest: 0038 item 4's reason is exactly "path tricks" and it still applies unless the owner accepts one path-loaded module; the CLAUDE.md `uv run --no-project python scripts/fetch-tools.py` contract, the 5 CI and 2 release call sites and the Docker stage all run from a checkout, so path loading works)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-02: `ToolsService._discover` repeats `discover_tools`; `discover_tools_sync` is a wrapper
- Kind: duplication
- Where: `packages/reframe/src/reframe/tools/discovery.py:409-430` (`discover_tools`), `discovery.py:433-455` (`discover_tools_sync`); `packages/reframe/src/reframe/service.py:229-247` (`ToolsService._discover`); `tools/__main__.py:47`; `scripts/bundle-tools.py:31,350`; `tools/__init__.py:12-13,42-44`.
- Now: `discover_tools` has 0 production callers (callers: `discover_tools_sync` and 9 test modules: `tests/tools/test_discovery.py`, `test_discovery_real.py`, four in `tests/probe/`, two in `tests/batch/`, `tests/capabilities/test_real.py`; their calls do not change). `ToolsService._discover` writes the same steps again (its comment says "Same steps as discover_tools()"): `locate_tools` in a thread, then a `TaskGroup` of `check_tool`, then `ToolSet(**...)`. `discover_tools_sync` is a 23-line pass-through that repeats all five keyword arguments, used by `__main__.py`, `scripts/bundle-tools.py` and 3 tests.
- Change: let `discover_tools` do the thread step (`located = await asyncio.to_thread(locate_tools, settings, environ=..., bundled_roots=..., search_path=..., platform=...)`), and make `ToolsService._discover` call it: `tools = await discover_tools(self._settings().tools, bundled_roots=self._bundled_roots, timeout=self._timeout)`; the `self._current = tools` and event publish stay. Delete `discover_tools_sync`; its two source callers use `asyncio.run(discover_tools(...))` (`tools/__main__.py:10,47`, `scripts/bundle-tools.py:31,350`), and its three tests (`test_discovery.py:155,182`, `test_fetch_cli.py:146-148`) are changed as under Tests. Remove it from `tools/__init__.py` and `discovery.__all__`. Optional, in the same change: `ToolLocation.env_var` always equals `ENV_VARS[name]` (all 9 `ToolLocation(...)` constructions in `discovery.py` pass it), so `_info` could read `ENV_VARS[loc.name]` and the field and the positional argument go; check that no test expects `ToolInfo.env_var is None` for a location without a path (`test_discovery.py:861`).
- Behaviour: unchanged. The `TaskGroup` rule (every version check finishes before a cancel returns) stays in the one place.
- Contracts touched: public core API (`reframe.tools.discover_tools_sync` goes; 0 users outside the repo's own scripts and tests).
- Callers to update: `packages/reframe/src/reframe/service.py`, `tools/__main__.py:10,47`, `scripts/bundle-tools.py:31,350`, `tools/__init__.py`, `packages/reframe/tests/tools/test_discovery.py:20,155,182`, `packages/reframe/tests/tools/test_fetch_cli.py:146`.
- Tests: the 3 `discover_tools_sync` tests become `async` tests that call `discover_tools` (same assertions); `test_cancelled_discovery_leaves_no_process` stays as the guard of the `TaskGroup` rule (it now also covers the service path); the `ToolsService` tests in `tests/` stay.
- Decision records: 0005 (discovery details) is untouched; no record names `discover_tools_sync`.
- Size: S; estimated lines: -35 source / -3 tests
- Risk: low. A cancel during the thread step of `locate_tools` leaves the thread running to its end (it only stats files); the service already did this.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (`discover_tools` has 9 test modules as callers, not "test_discovery.py and 4"; `discover_tools_sync` has 2 source callers and 3 tests, not "three callers"; no test patches `reframe.service.locate_tools` / `check_tool`, and the service's call has the same defaults as `discover_tools`, so the merge keeps behaviour)
- Orchestrator: Tier A, work package Q-6.7 (see ../plan.md).

### TP-03: `run` and `run_streaming` have options that no production caller uses
- Kind: dead-code
- Where: `packages/reframe/src/reframe/tools/runner.py:535-566` (`run`: `stdin`), `:507-512` (`_feed_stdin`), `:399-441` (`_execute`: `stdin` parameter, the `PIPE` / `DEVNULL` choice at 417, the stdin reader at 440-441, the `proc.stdin` check), `:569-604` (`run_streaming`: `timeout`, `max_output`, `cwd`), `:380-390` (`_check_args`), `:46-47` (`DEFAULT_STREAMING_TAIL`).
- Now: I listed all 16 production calls of `run` / `run_streaming` (`analysis/loudness.py:119`, `analysis/bitrate.py:168`, `analysis/subtitles.py:259,303,334`, `queue/runner.py:504`, `preview/clip.py:256`, `preview/frames.py:222`, `preview/crop.py:80`, `probe/ffprobe.py:209`, `validation/dryrun.py:516`, `capabilities/hwtest.py:181`, `capabilities/detect.py:217`, `tools/discovery.py:364`, `tools/fetch.py:762`, `platform/power.py:123`). `run(stdin=...)`: 0 production callers (only `tests/tools/test_runner.py:92`). `run_streaming(timeout=, max_output=, cwd=)`: 0 production callers (only `test_runner.py`; the callers pass `on_stdout_line`, `on_stderr_line`, `cancel`, `extra_env`, and `queue/runner.py` also `on_start`). Production `run_streaming` always runs with `timeout=None`, so the `None` branches of `_execute` (`deadline`, `remaining`) are the production streaming path, and only the float branch together with a streaming sink is reached by tests alone.
- Change: remove `stdin` from `run`, `_execute` and `_feed_stdin` (the child always gets the null device: `stdin=asyncio.subprocess.DEVNULL`, no stdin reader task, no `proc.stdin` check). Remove `timeout`, `max_output` and `cwd` from `run_streaming`; it passes `DEFAULT_STREAMING_TAIL` and `cwd=None` to `_execute`. Keep `_execute`'s `timeout: float | None` and its `None` handling (3 lines) or make `run_streaming` pass a very large value: keep the `None` handling, it is simpler. Keep `run`'s `cwd` (used by `validation/dryrun.py:520`), `max_output`, `extra_env`, `cancel`; keep `run_streaming`'s `on_start`. Do not touch the process-tree kill, the drain and the cancel code.
- Behaviour: unchanged (no production caller changes).
- Contracts touched: public core API (`reframe.tools.run`, `run_streaming` signatures; 0 production users of the removed options).
- Callers to update: none in production; `packages/reframe/tests/tools/test_runner.py` (tests at 84-110 for stdin; the `run_streaming` tests that pass `timeout=` at lines 405, 460, 477, 644, 665 and `max_output=` at 493 move to `run`, or are deleted when `run` has the same test).
- Tests: in `test_runner.py` change `test_stdin_cwd_and_extra_env` to drop the stdin part (cwd and extra_env stay); `test_stdin_is_the_null_device_by_default` stays (it checks the default). `test_streaming_timeout` (`test_runner.py:453`, `timeout=1` at 460) is deleted: the timeout kill is covered by the `run` tests at `:155,171,182`. The tests at 405, 477, 644 and 665 pass `timeout=` only as a hang guard: drop the argument (the project has no pytest-timeout, so a hang regression there would hang the run instead of failing; note that in the commit). `test_streaming_keeps_the_tail` (`max_output=1000` at 493) tests `_LineSink`'s tail and cannot move to `run` (which keeps the head): keep it on `run_streaming` and assert `len(result.stderr) == DEFAULT_STREAMING_TAIL` (the 3 MiB flood already exceeds it). The kill, drain, cancel, tree and line-splitting tests stay.
- Decision records: C-1 rules (timeout, cancel, output limit, tree kill) are kept: `run` still has all of them; `run_streaming` keeps cancel and its tail limit. Not a decision, but the plan: the C-1 signature sketch in `docs/plan/05-core.md:67` is `run_streaming(argv, *, on_stdout_line, on_stderr_line, cancel, timeout=None)`, so removing `timeout` means editing that line in the same commit (CLAUDE.md: the plan is the spec). The sketch of `run` (05-core.md:65) has no `stdin`, so removing `stdin` matches the plan.
- Size: S; estimated lines: -25 source / -50 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the "`timeout is None` branches only reached by tests" claim was backwards, corrected; the plan sketch `05-core.md:67` names `run_streaming(..., timeout=None)` and must be edited with the change; the `max_output=1000` test cannot move to `run`, it stays on `run_streaming` with the default tail; the other test handling is spelled out; the 16 production calls and the 0 users of `stdin`, and of `timeout` / `max_output` / `cwd` on `run_streaming`, were recounted and hold)
- Orchestrator: Tier B, work package Q-6.17 (see ../plan.md).

### TP-04: two fake D-Bus servers and three copies of the fd and socket leak helpers in the platform tests
- Kind: tests
- Where: `packages/reframe/tests/platform/test_sleep_dbus.py:215-364` (`Scenario`, `_reply`, `_error`, `_serve`, `fake_bus`); `test_sleep_failures.py:149-190` (`_read_line`, `_read_message`, `_handshake`, `_hello`) and `:291-322` (`bad_bus`); `_open_fds` in `test_sleep_dbus.py:81`, `test_sleep_backends.py:141`, `test_sleep_real.py:206`; `no_leaked_sockets` (`test_sleep_failures.py:52-62`) and `_assert_nothing_left` (`test_sleep_real.py:221-228`) with the same `warnings` + `gc.collect()` block.
- Now: `fake_bus` and `bad_bus` both create a temp dir, bind an `AF_UNIX` socket, run an accept loop in a daemon thread with a stop event, and yield `unix:path=...`. `_serve` (73 statements, ruff PLR0915, C901 19) and `_read_line` / `_read_message` / `_handshake` implement the same line-and-message reading and the same `AUTH EXTERNAL` / `NEGOTIATE_UNIX_FD` / `BEGIN` handshake twice. `_open_fds` is the same one-liner three times.
- Change: one module `testing/reframe_testing/fake_dbus.py` (the `tests/platform` folder has no `__init__.py`, so a sibling import does not work; `testing/reframe_testing` is already importable by tests) with: `serve_unix(handler) -> contextmanager[str]` (the temp dir, socket, thread, stop), `read_line`, `read_message`, `handshake(conn, buf, *, auth, fd_answer)`, `open_fds()` and `assert_no_new_fds_or_unclosed(before)`. `Scenario` / `_serve` become a handler that uses them; the `peer_*` functions of `test_sleep_failures.py` use `handshake` and `read_message`. The new module is imported at collection on Windows too (the five test files are skipped there, but their imports run) and `mypy --platform win32` checks `testing/`: keep the `AF_UNIX: int = vars(socket).get("AF_UNIX", 0)` form the test files use today and put the `/proc/self/fd` reads inside functions.
- Behaviour: unchanged (tests only).
- Contracts touched: none
- Callers to update: the five test files named above; new `testing/reframe_testing/fake_dbus.py`.
- Tests: all tests of these files stay; only helpers move.
- Decision records: none apply.
- Size: M; estimated lines: -0 source / -70 tests
- Risk: low. The real-bus tests (`test_sleep_real.py`) skip without a bus, so run the fake-bus ones and, once, the real ones on this machine.
- Depends on: none (do it first: if TP-11 or TP-12 lands later, the shared fake bus is what gets cut down, not two copies)
- Confidence: high
- Verdict: ADJUSTED (anchors and counts checked and right; added the Windows import and `mypy --platform win32` constraint on the new shared module; `fake_bus` serves one connection with `listen(1)` and `bad_bus` loops over many, so the shared `serve_unix` must offer both or take the accept count)
- Orchestrator: Tier A, work package Q-6.2 (see ../plan.md).

### TP-05: leftovers of the MKVToolNix / MediaInfo removal: `root=None` and `BUNDLED_SUBDIRS`
- Kind: decision-change for the `root=None` part (0081 item 3 keeps it on purpose), dead-code for the `BUNDLED_SUBDIRS` part
- Where: `packages/reframe/src/reframe/tools/fetch.py:404-415` (`member_path(name, root: str | None)`), `:490` (`_extract_zip(..., root: str | None, ...)`), `:513-530` (`safe_extract`: `root: str | None`, the `if root is None: raise FetchError(... needs a top folder)` branch); `packages/reframe/src/reframe/paths.py:36-37` (`BUNDLED_SUBDIRS`), `:5`, `:19`; `tools/discovery.py:139` (`subdir = paths.BUNDLED_SUBDIRS[tool]`).
- Now: `root=None` was for the MediaInfo zip (no top folder, decision 0002 item 2). No production caller passes `None` any more: `fetch.py` passes `pbuild.root` (a `str`), `scripts/bundle-tools.py:250` passes `root: str`, and `tools/bundled-tools.toml` has only libva (`root = "libva-2.24.1"`). Only 3 tests pass `None`. `BUNDLED_SUBDIRS` is `{"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg"}`: a map with one value, read once.
- Change: `root: str` everywhere in `fetch.py`; `member_path` checks `parts[0] != root` without the `is not None` test; delete the `root is None` branch of `safe_extract`. Replace `BUNDLED_SUBDIRS` by `BUNDLED_FFMPEG_DIR = "ffmpeg"` in `paths.py` (and `__all__`, the module docstring line 5); `discovery._bundled_dir` uses it and no longer needs the `tool` argument for the folder.
- Behaviour: unchanged.
- Contracts touched: none (no persisted or HTTP name changes; `paths.BUNDLED_SUBDIRS` is a core name with 2 test users).
- Callers to update: `packages/reframe/src/reframe/tools/discovery.py:139`; `packages/reframe-server/tests/test_deploy.py:128`; `packages/reframe/tests/test_paths.py:83`.
- Tests: delete `test_an_archive_without_a_top_folder_still_refuses_unsafe_names`, `test_a_zip_without_a_top_folder_is_extracted_as_it_is`, `test_a_tar_without_a_top_folder_is_refused` (`tests/tools/test_fetch.py:299-322`); replace `test_bundled_subdirs` by an assertion on the constant, or delete it (the `test_deploy.py:128` check covers it).
- Decision records: 0002 item 2 (MediaInfo pinned: superseded by 0079 item 11 and 0081). **0081 item 3 says "`reframe.tools.fetch` keeps its generic zip-without-a-top-folder support (now unused by any pin)"**, so the `root=None` removal changes that record; what would have to be true: the owner no longer wants a generic zip without a top folder for a future pin (the record already knows that no pin uses it). 0072 "Built" (T) names the same support. For `BUNDLED_SUBDIRS`: 0080 item 1 only says it loses the mkvpropedit and mediainfo entries; no record requires the mapping. `docs/test-trim-reports/Q.md:170` shows that `test_bundled_subdirs` was restored on purpose (a mutation that gave ffprobe its own folder survived), so keep an assertion that ffprobe's folder is ffmpeg's.
- Size: S; estimated lines: -8 source / -25 tests (the `BUNDLED_SUBDIRS` part alone: about -3 source, one test kept)
- Risk: low.
- Depends on: TP-01 (the same functions move there; do this one first or inside it)
- Confidence: medium for the `root=None` part (decision), high for `BUNDLED_SUBDIRS` (but worth about 3 lines)
- Verdict: ADJUSTED (kind and decision records: decision 0081 item 3 deliberately keeps the no-top-folder zip support, so that half is a decision-change, not plain dead code; the facts hold: no production caller passes `None`, `PlatformBuild.root` and the libva pin's `root` are required `str`, only 3 tests pass `None`; `BUNDLED_SUBDIRS` is read once, at `discovery.py:139`, and `_bundled_dir` keeps its `tool` argument for the binary lookup)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-06: `dbus.py` and `sleep.py` features that no call needs
- Kind: speculative-generality
- Where: `packages/reframe/src/reframe/platform/dbus.py:185-267` (`_Writer.endian`, `encode(endian=)`), `:316-337` and `:375-391` (`_Reader.endian`, `message_length`, `_endian`, `_Header.endian`), `:340-343` and `:361-366` (`_Reader.int32` and the reader types `i`, `b`, `y`), `:468` (the allowed set `"sogyuhibv"` of `_decode_body`), `:666-670` (`Connection.__enter__` / `__exit__`), `:599-602` and `:625-626` (`Connection.unique_name`); `packages/reframe/src/reframe/platform/sleep.py:392-410` (`SessionInhibitBackend(interfaces=...)` with its `ValueError` for unknown names).
- Now: the client always sends little-endian, and the pinned platforms (`linux-x64`, `linux-arm64`, `windows-x64`) are little-endian, so the bus daemon on them sends little-endian too; the big-endian writer and the big-endian reader exist for one test (`test_sleep_dbus.py:104-118`, `test_big_endian_messages_decode`). The four calls the product makes return `s`, `u`, `o`, `h` and one `v` of a string (`IdleAction`), so the reader types `i`, `b`, `y` are never parsed from a real reply. `Connection.__enter__` has 1 user (`test_sleep_dbus.py:578`); `unique_name` has 1 test assert (`test_sleep_dbus.py:540`) and 0 other users. `SessionInhibitBackend(interfaces=...)` is given by 1 test only (`test_sleep_backends.py:418-430`); production always uses `(PM_INTERFACE, PORTAL_INTERFACE)`, so the parameter and the name check serve one test.
- Change: little-endian only: `_endian` returns `"<"` or raises `DBusProtocolError("bad endianness flag")` for anything else (the test `peer_sends_bad_endianness` in `test_sleep_failures.py:228` already expects that error for a bad flag; check that a `B` flag is then an error too), and the `endian` fields and parameters go. Delete the reader types `i`, `b`, `y` and `int32` and take the three letters out of the allowed set at `dbus.py:468` (a signal body with those types then stays empty instead of raising: this must change together, or a `NameOwnerChanged`-style signal with an `i` would break the read loop). Delete `Connection.__enter__` / `__exit__` and `unique_name` (the tests use `try` / `finally` or `contextlib.closing`). Drop the `interfaces=` parameter, `self._interfaces` and the `ValueError` check of `SessionInhibitBackend` (the loop in `_open_and_inhibit` walks `(PM_INTERFACE, PORTAL_INTERFACE)`); keep the `_INHIBIT` dict, because `_end` finds the end call by the interface name that `hold` stored (a tuple of triples would need a search loop there and saves nothing). Do not touch `parse_address` / `_unescape` (0011 follow-up item 2).
- Behaviour: unchanged on little-endian hosts. A big-endian host would no longer get a sleep inhibit (not a target platform).
- Contracts touched: none
- Callers to update: `packages/reframe/src/reframe/platform/sleep.py`; tests `test_sleep_dbus.py:104-118,540,578`, `test_sleep_backends.py:418-430`.
- Tests: delete `test_big_endian_messages_decode` and `test_session_portal_only_and_unknown_interfaces` (the PM-fails-then-portal fallback has its own test); change the two `connection` tests as above; everything else stays.
- Decision records: 0011 (the client does only what the calls need: this follows it), 0011 follow-up item 2 (documented errors: unchanged).
- Size: S; estimated lines: -30 source / -30 tests
- Risk: low. The D-Bus spec says a receiver must accept both byte orders; no decision record mentions endianness, and the pinned platforms are little-endian, so this is a deliberate narrowing, to be noted in the commit.
- Depends on: none (TP-11 or TP-12 supersede parts of it: the `v` and `h` types and fd passing go there)
- Confidence: medium (the line counts are estimates; each deletion was checked against its callers)
- Verdict: ADJUSTED (the `_INHIBIT` registry sub-change is dropped: `_end` looks the end call up by interface name, so a tuple would add a search loop; only the `interfaces=` parameter and its check go; the other sub-changes were checked against all callers, including `test_sleep_real.py`, and hold; size -30 source)
- Orchestrator: Tier B, work package Q-6.17 (see ../plan.md).

### TP-07: members that only tests use
- Kind: dead-code
- Where: `packages/reframe/src/reframe/tools/versions.py:56-58` (`FfmpegVersion.is_git_build`), `:85-88` (`FfmpegVersion.meets_minimum`); `packages/reframe/src/reframe/applog.py:292-298` (`AppLog.max_bytes`, `AppLog.backup_count`); `packages/reframe/src/reframe/platform/power.py:449-456` (`PowerService.countdown`, `PowerService.closed`).
- Now: `is_git_build`: 0 callers outside `tests/tools/test_versions.py:145`. `meets_minimum`: 0 callers outside `test_versions.py` (4 asserts); `discovery._ffmpeg_info` does its own `series < versions.MIN_FFMPEG` (discovery.py:398), so the method is a second copy of the rule that nobody calls. `AppLog.max_bytes` and `backup_count`: 1 assert, `tests/test_applog.py:300`. `PowerService.countdown` and `.closed`: 2 asserts, `tests/platform/test_power.py:264,549-550`. No production, server, CLI, script or frontend use (searched `packages/`, `testing/`, `scripts/`).
- Change: delete the six members. In `test_versions.py` remove the `meets` column of `test_real_version_outputs` and the `meets_minimum` lines (`:158,228,240,281`); a `series >= MIN_FFMPEG` check is already what the `TOO_OLD` tests of `test_discovery.py` exercise. In `test_applog.py:300` assert the two constants (`applog.MAX_BYTES`, `applog.BACKUP_COUNT`) instead. In `test_power.py` assert the events instead of the properties.
- Behaviour: unchanged.
- Contracts touched: public core API (the six names; 0 users outside tests).
- Callers to update: the four test files named.
- Tests: change as above; no test is deleted except the `is_git_build` assert.
- Decision records: none apply.
- Size: S; estimated lines: -20 source / -20 tests
- Risk: low.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (anchor: `is_git_build` is `versions.py:56-58`, not 55-57; the six members were searched across `packages/`, `testing/`, `scripts/`, `desktop/` and the decision records and have no user outside the tests named; `power.closed` hits in `test_facade.py:140` and `test_cli_when_done.py:292` are the tests' own `FakePower`, not `PowerService`)
- Orchestrator: Tier A, work package Q-6.7 (see ../plan.md).

### TP-08: `CancelToken.reason` is written at 13 call sites and read 0 times
- Kind: dead-code
- Where: `packages/reframe/src/reframe/tools/runner.py:70` (`self.reason`), `:76-82` (`cancel(reason)`); writers: `tasks.py:230-235` (`TaskManager.cancel(task_id, reason)`), `tasks.py:253,279,302`, `capabilities/service.py:191,211`, `probe/prober.py:213`, `service.py:585`, `queue/runner.py:145`, `tools/fetch.py:730,752`, `cli.py:3429` (`app.tasks.cancel(info.id, "interrupted")`), `reframe-server/.../routers/preview.py:215` (`reframe.tasks.cancel(task.id, "the client went away")`).
- Now: no code reads `token.reason`. Two test asserts do (`tests/tools/test_runner.py:199,252`). The queue keeps its own `stop_reason` (`queue/runner.py:120`), so the token's copy is not what the queue uses.
- Change: `CancelToken.cancel()` takes no argument; delete `reason`; delete the `reason` parameter of `TaskManager.cancel` and the strings at the 13 call sites. `ActiveJob.stop(reason)` stays (it stores `stop_reason`).
- Behaviour: unchanged. `Reframe.tasks.cancel` loses an optional second argument (the server passes it once, `routers/preview.py:215`, and only the id in `routers/tasks.py:50`).
- Contracts touched: public core API (`CancelToken.cancel`, `TaskManager.cancel`); server code changes by one argument, the HTTP/WebSocket contract and the OpenAPI schema do not change (the reason was never in a response), so no frontend change.
- Callers to update: the files above (8 core files including `tools/runner.py`, 1 server file; 13 production call sites in all); tests: `tests/tools/test_runner.py:193,199,251,252`, `tests/capabilities/test_detect.py:372` (`token.cancel("test")`), `tests/tools/test_fetch.py:876,913,922` (`tasks.cancel(..., "interrupted")`). `tests/queue/test_in_place_stop.py:351` (`active.stop("timeout")`) stays: `ActiveJob.stop(reason)` keeps its argument.
- Tests: change the two asserts (`test_cancel_from_a_coroutine`, line 199; `test_cancelled_token_does_not_start_the_process`, line 252, whose `token.cancel("again")` becomes `token.cancel()`); the tests keep their other asserts.
- Decision records: none apply.
- Size: S; estimated lines: -10 source / -6 tests
- Risk: low, but it touches 7 files outside this area (`tasks.py`, `capabilities/service.py`, `probe/prober.py`, `service.py`, `queue/runner.py`, `cli.py`, the server's `routers/preview.py`); do it in one commit.
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (13 production call sites, not 14, in 8 core files and 1 server file, 7 of them outside this area, not 10 and 9; the full test caller list added: `test_runner.py:193,199,251,252`, `test_detect.py:372`, `test_fetch.py:876,913,922`; no reader of `token.reason` exists in `packages/`, `testing/`, `scripts/`, `desktop/` or the records)
- Orchestrator: Tier A, work package Q-6.9 (see ../plan.md).

### TP-09: `platform/notify.py` is a pass-through
- Kind: layering
- Where: `packages/reframe/src/reframe/platform/notify.py` (16 code lines), its only caller `packages/reframe/src/reframe/queue/whendone.py:24,82,90,119` (3 calls), `packages/reframe/tests/platform/test_notify.py`.
- Now: `notify(events, title, message, *, level, job_id)` builds a `NotificationEvent` and calls `events.publish`. It sits in `reframe.platform`, which is otherwise OS code. 3 call sites, all in `whendone.py`; 2 of them use the returned event.
- Change: a private method in `whendone.py`: `def _notify(self, title, message="", *, level, job_id=None) -> NotificationEvent: event = NotificationEvent(...); self._events.publish(event); return event`. Delete `platform/notify.py` and `tests/platform/test_notify.py` (the when-done tests assert the published event already).
- Behaviour: unchanged.
- Contracts touched: public core API (`reframe.platform.notify`; 1 caller). The plan names "the notification hook" for C-14; the event is still the hook (the core publishes a `notification` event and never shows one).
- Callers to update: `packages/reframe/src/reframe/queue/whendone.py:24,82,90,119`; docs: `docs/status.md:71` (the C-14 row says "The notification hook is built (`reframe.platform.notify.notify`...)": reword it to the `notification` event published by `queue/whendone.py`) and the docstring of `packages/reframe/src/reframe/platform/__init__.py` ("... and notifications"). The plan's C-14 bullet ("Notification hook: emits an event only") stays true.
- Tests: delete `tests/platform/test_notify.py`; `tests/queue/test_when_done.py` stays as the guard.
- Decision records: 0037 (notifications): unchanged; 0011 item 7 and 0029 name "the notification hook" as a C-14 deliverable, not a module. (0063:334 and 0069:774 name `platform.notify`, the frontend's TypeScript function, not this module.)
- Size: S; estimated lines: -14 source / -12 tests
- Risk: low.
- Depends on: none
- Confidence: medium (the owner may want the hook as a named module for a later notification channel; nothing in the plan needs one)
- Verdict: ADJUSTED (the change also edits `docs/status.md:71` and the `platform/__init__.py` docstring, which name the module; the one caller and the 3 call sites, 2 using the returned event, were confirmed)
- Orchestrator: Tier B, work package Q-6.17 (see ../plan.md).

### TP-10: the "finish after the swap" logic of `tools fetch` (decision 0038 R5-5)
- Kind: decision-change
- Where: `packages/reframe/src/reframe/tools/fetch.py:629-640` (`_Job.swapped`), `:675-681` (`_Job.install` sets it), `:739-757` (`_to_the_end`), `:842-881` (`_fetch_steps`: the `except asyncio.CancelledError` with `swapped` and `uncancel`, the two `_to_the_end` calls, the final `if cancel.cancelled` progress message).
- Now: once the new build is swapped in, a cancel stops nothing more: the work folder is removed and tool discovery runs to its end under `asyncio.shield`, the task still ends `cancelled`, and the last progress message says "Installed FFmpeg ... before the cancel". This is 37 lines of cancel and `uncancel` juggling. The CLI does not need it: it already compares the install marker before and after (`cli.py:3418-3440`) and prints "was installed into ... before the interrupt".
- Change: a cancel is a cancel at every step. Delete `swapped`, `_to_the_end`, the `except CancelledError` branch and the final message; the `finally` removes the work folder with a plain `await asyncio.to_thread(shutil.rmtree, work, True)` (a cut-off leaves a `.fetch-*` folder that `remove_stale_work` removes after six hours, and the next fetch removes it too). What changes for a user: a cancel in the short step between the swap and the end of tool discovery leaves the new build installed but the tool status not refreshed until the next rescan or restart. What would have to be true: the owner accepts that rare stale status (a Rescan button exists in Settings → Tools).
- Behaviour: changes (rarely): see above. The CLI message is unchanged.
- Contracts touched: none (task result and events unchanged)
- Callers to update: `packages/reframe/src/reframe/tools/fetch.py` only.
- Tests: delete `tests/tools/test_fetch.py::test_a_cancel_after_the_swap_finishes_and_says_so`; `tests/tools/test_fetch_cli.py::test_the_cli_says_what_was_installed_after_an_interrupt` stays (it drives the marker path) and must still pass.
- Decision records: 0038 R5-5 (changes), 0041 R5-5 (the review item).
- Size: S; estimated lines: -37 source / -60 tests
- Risk: low to medium (one real user-visible edge case).
- Depends on: TP-01 (the same file moves; do it after, or inside it)
- Confidence: medium
- Verdict: CONFIRMED
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-11: drop the logind backend, and with it D-Bus file-descriptor passing (decision 0022 item 2)
- Kind: decision-change
- Where: `packages/reframe/src/reframe/platform/sleep.py:60-62,163-264` (`LogindBackend`, `idle_action`, the `fd` handling), `:267-274` (`_close_fds`, `_discard_reply`), `:841` (`default_backends`), `WHAT`, `WHO`, `MODE`; `packages/reframe/src/reframe/platform/dbus.py:115-117` (`system_bus_address`), `:481-545` (`_Connection._recv` SCM_RIGHTS handling, `MAX_FDS`), `:547-558` (`NEGOTIATE_UNIX_FD`), `Reply.fds`, `Message.fds`, `decode_message`'s fd bookkeeping, the `h` and `v` types, `call()` at 686-718 (the one-shot call, used only by `LogindBackend`); tests `test_sleep_dbus.py` (fd cases), `test_sleep_backends.py` (logind cases), `test_sleep_failures.py`, `test_sleep_real.py` (logind parts).
- Now: the session inhibit (PowerManagement, then the portal) is the mechanism that works on a desktop. The logind `idle` lock is taken only when the session inhibit is not held, or when logind's `IdleAction` is not `ignore`. It needs a system-bus connection, `NEGOTIATE_UNIX_FD`, `SCM_RIGHTS` parsing with `MSG_CMSG_CLOEXEC`, fd ownership rules in four places, and a one-shot `call()`. That is about 200 of the 554 code lines of `dbus.py` and `sleep.py`'s logind part, and roughly 400 test lines (the fd and leak tests).
- Change: `default_backends` returns `[SessionInhibitBackend()]` on Linux; delete `LogindBackend`, the fd code, `call()`, the `h` and `v` reader types, `Reply.fds`. What would have to be true for 0022 item 2 to change: no supported setup depends on the logind idle lock. It does matter on a headless Linux machine (a bare-metal server, `docs/deployment.md`) whose logind has `IdleAction` other than `ignore` (the logind default is `ignore`), and on a desktop whose session inhibit fails. The owner decides whether those two cases are worth about 600 lines of code and tests. The same commit edits the plan: `docs/plan/05-core.md:570-583` (the C-14 sleep bullet names "the logind `Inhibit` D-Bus call with `what=idle` where it is needed") and `docs/plan/03-features.md:794` ("the session's inhibit and logind over D-Bus"), adds a superseding note to 0022, and rewords the C-14 row of `docs/status.md`.
- Behaviour: changes on those two setups: no logind lock, so a configured idle suspend is not stopped. The session connection negotiates file descriptors today too (`Connection.open` calls `_authenticate(conn, want_fds=True)`, `dbus.py:610`; `NEGOTIATE_UNIX_FD` at `:553-554`), so dropping fd passing also changes the session-bus handshake that PowerManagement and the portal see. The `sleep_inhibit.unavailable` event would appear on a headless host with no session bus (today logind may hold there).
- Contracts touched: none (the setting `queue.sleep_inhibit` and the event stay)
- Callers to update: `packages/reframe/src/reframe/platform/sleep.py`, `platform/dbus.py`; the four sleep test files.
- Tests: delete the logind and fd tests listed; keep the session backend, the inhibitor, the Windows backend and the fake-bus tests (TP-04's helper then needs no fd sending).
- Decision records: 0022 item 2 (changes), 0011 (the stdlib client stays, smaller), 0020 (only automatic sleep is stopped: unchanged).
- Size: L; estimated lines: -200 source / -400 tests
- Risk: medium. Not tested on GNOME or on a headless host in this audit. After the change run the session-bus tests of `test_sleep_real.py` on this machine (KDE): the handshake without `NEGOTIATE_UNIX_FD` has not been checked against a real session bus.
- Depends on: none; TP-06 shrinks if this lands
- Confidence: low
- Verdict: ADJUSTED (the plan (`05-core.md` C-14, `03-features.md:794`) and `docs/status.md` also name the logind lock and are edited in the same commit; the session connection negotiates fds too, so the handshake changes for the session backend as well, added to Behaviour and Risk; the 0022 item 2 condition ("only where it is needed") is quoted honestly)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-12: replace the stdlib D-Bus client with `jeepney` (decision 0011 item 1)
- Kind: decision-change
- Where: `packages/reframe/src/reframe/platform/dbus.py` (554 code lines), `packages/reframe/src/reframe/platform/sleep.py:277-364` (`_BusConnection`, `_open_connection`, the `_pm_*` and `_portal_*` call builders), `tests/platform/test_sleep_dbus.py` (494 raw lines), parts of `test_sleep_failures.py`.
- Now: Reframe owns a D-Bus wire-protocol client: address parsing, SASL `EXTERNAL`, marshalling, a reader, fd passing and 0011's follow-up hardening. Decision 0011 says "If Reframe ever needs more of D-Bus ... switch to jeepney". It grew from the about 340 statements 0011 expected to 438 statements (554 code lines; the units were mixed here), plus 0022's second D-Bus user (the session bus with `a{sv}`), so the "small, fixed subset" argument is weaker now.
- Change: add `jeepney` as a Linux-only dependency (`jeepney>=0.9; sys_platform == "linux"`) and use `jeepney.io.blocking.open_dbus_connection(bus=address, enable_fds=True)`, `new_method_call` and `send_and_get_reply(timeout=...)`; keep `SessionInhibitBackend` and `LogindBackend` over a 40-line adapter. Delete `dbus.py` and `test_sleep_dbus.py`. What would have to be true: the owner accepts a new dependency that has no `py.typed` (a mypy override is needed, as 0011 says), its notice entry in the third-party notices (decision 0079), and the check that its blocking I/O passes fds and honours the timeout the way the hardening tests require.
- Behaviour: unchanged for the user if the adapter matches the current error texts; the `sleep_inhibit.unavailable` detail texts would change.
- Contracts touched: dependency list, `uv.lock`, third-party notices, the sidecar bundle (`reframe-server` freezes the package).
- Callers to update: `platform/sleep.py`, `pyproject.toml`, `uv.lock`, mypy config, notices.
- Tests: delete `test_sleep_dbus.py` and the fake-bus tests of `test_sleep_failures.py`; keep the inhibitor and backend tests and the real-bus tests.
- Decision records: 0011 item 1 (changes: 0011 itself names this as the exit), 0022, 0079 (notices).
- Size: L; estimated lines: -490 source (net of the adapter) / -700 tests
- Risk: high. The hardening of 0011's follow-up (every failure is data, no socket leaks) was written against the own client; jeepney's error and timeout behaviour must be re-verified with the real-bus tests on this machine and the fake peers of TP-04.
- Depends on: replaces TP-06; compatible with TP-11 (if TP-11 lands first, the adapter needs only the session calls and `enable_fds=False`); TP-04 first
- Confidence: low
- Verdict: ADJUSTED (the growth is 340 to 438 statements, not 554: those are code lines; TP-11 is not an alternative, the two can both land; jeepney is not in `uv.lock` or any `pyproject.toml` today, so it is a new dependency with a notice entry, as the finding says; 0011 item 1 names its own exit ("needs more of D-Bus (signals, other services)") and its reasons against jeepney (no `py.typed`, fds only in blocking I/O) are quoted correctly)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-13: `launch_detached` returns a pid, so `owner._start` wraps `Popen` to get the handle back (cross-area: remote)
- Kind: duplication
- Where: `packages/reframe/src/reframe/platform/childproc.py:350-384` (`launch_detached`); `packages/reframe/src/reframe/remote/owner.py:227-261` (`_start`, its inner `popen`); `testing/tests/test_folders_guard.py:58,76`; `testing/reframe_testing/folders_guard.py:75-93`.
- Now: `launch_detached` builds its own `kwargs` (stdio to the null device, `env=user_environ(...)`, `creationflags`), then `_start` hands it a `popen` closure that overwrites `env` and `stderr`, adds `CREATE_NO_WINDOW`, calls `subprocess.Popen` and stores the handle in a list so that `_start` can return it ("the handle is only read for the exit code"). The `popen=` parameter of `launch_detached` exists for this closure and for tests.
- Change: let `launch_detached` take `env: Mapping[str, str] | None = None`, `stderr: IO[bytes] | int = DEVNULL` and `extra_creationflags: int = 0`, and return the `Popen`. `_start` becomes about 8 lines (open the log, call, close the log). Keep the `popen=` seam of `launch_detached`: the childproc tests pass fake `popen` functions to assert the keyword arguments (`test_childproc.py:247-300,372-379`), and `test_owner_search.py:285-300` monkeypatches `subprocess.Popen`. The folders guard (`folders_guard.py:93`) compares the `launcher` argument of `owner._start` with `launch_detached`, which is a different seam; `_start` keeps its `launcher` parameter.
- Behaviour: unchanged. Windows path (`CREATE_NO_WINDOW`, the breakaway retry): needs a check on the Windows test VM.
- Contracts touched: public core API (`launch_detached` return type: 1 production caller, `remote/owner.py:233`, plus the folders guard and tests).
- Callers to update: `remote/owner.py`, `testing/reframe_testing/folders_guard.py`, `testing/tests/test_folders_guard.py`, `tests/remote/test_owner_search.py:294,422,448,508`, `tests/platform/test_childproc.py:253-379`.
- Tests: the childproc tests that assert `== 4321` (the pid) change to `.pid`; the owner tests stay.
- Decision records: 0005 (the Windows breakaway and the retry inside the job: unchanged), the owner decision 0042.
- Size: S; estimated lines: -5 source (the closure goes, three parameters come) / -0 tests
- Risk: medium. The test guard that keeps tests from starting a real owner depends on the launcher seam. The Windows retry path replaces `creationflags` with `CREATE_NEW_PROCESS_GROUP`, so `extra_creationflags` must be OR-ed again in the retry, as the closure does today (it ORs `CREATE_NO_WINDOW` into the retry's flags too).
- Depends on: none
- Confidence: low
- Verdict: ADJUSTED (1 production caller, not 3; the `popen=` seam must stay for the childproc tests, so the saving is about 5 lines, not 15; the retry path must keep the extra flag; Windows VM check needed, as the finding says)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### TP-14: the Windows execution-state thread is built as a command queue
- Kind: structure
- Where: `packages/reframe/src/reframe/platform/sleep.py:516-554` (`_StateThread`: `SimpleQueue`, one `Future` per command, `submit`, `stop`), `:557-618` (`WindowsExecutionStateBackend.hold` / `free`).
- Now: one thread per hold receives two commands (`ES_CONTINUOUS | ES_SYSTEM_REQUIRED`, then `ES_CONTINUOUS`) through a queue, each with a `concurrent.futures.Future`, wrapped by `asyncio.wrap_future` and `asyncio.shield`. The thread ends when `stop` is queued. The only reason for the queue is to return each call's `(previous, last_error)` to the async caller.
- Change: a thread function `hold(k32, last_error, ready: Future, release: threading.Event)`: set the state, `ready.set_result((previous, error))` (or `set_exception`), return at once if it failed, else `release.wait()`, then `SetThreadExecutionState(ES_CONTINUOUS)` and end. `hold()` awaits `wrap_future(ready)`; on `CancelledError` or a failure it sets `release`; `free()` sets `release` and awaits `asyncio.to_thread(thread.join)`. 0011 item 4 ("a dedicated thread per hold makes both calls, then ends") is kept; the existing Windows tests (`test_sleep_backends.py:48-135`, thread identity and call order) stay as they are.
- Behaviour: unchanged. Windows-only code path: needs a check on the Windows test VM (a real `SetThreadExecutionState` on a live thread; `powercfg /requests` shows it).
- Contracts touched: none
- Callers to update: `platform/sleep.py` only.
- Tests: none deleted; `RecordingKernel32` tests stay as the guard.
- Decision records: 0011 item 4 and its follow-up item 3 (a cancelled hold clears the state): kept.
- Size: S; estimated lines: -25 source / -0 tests
- Risk: medium (Windows only, mock-tested on Linux).
- Depends on: none
- Confidence: medium
- Verdict: CONFIRMED
- Orchestrator: Tier B, work package Q-6.12 (see ../plan.md).

### TP-15: two identical helpers in the platform package
- Kind: duplication
- Where: `packages/reframe/src/reframe/platform/sleep.py:267-270` (`_close_fds`) and `platform/dbus.py:475-478` (`_close_all`); `platform/childproc.py:167-169` and `platform/sleep.py:511-513` (both `_last_error`).
- Now: identical bodies (compared by reading both). `sleep.py` already imports `dbus`. `power.py` passes `ctypes.get_last_error` inline in `Win32Libraries`, a third spelling.
- Change: `dbus.close_fds` (public name) used by `sleep.py`; one `_last_error` in `childproc.py`, imported by `sleep.py` (or both call `ctypes.get_last_error` through the `getattr` form once). Do not merge the three `Kernel32` protocols or the `_load_*` bindings: their method sets differ, and a wrong ctypes binding shows only on Windows.
- Behaviour: unchanged.
- Contracts touched: none
- Callers to update: `platform/sleep.py`, `platform/dbus.py`, `platform/childproc.py`.
- Tests: none change (the helpers are private).
- Decision records: none apply.
- Size: S; estimated lines: -12 source / -0 tests
- Risk: low.
- Depends on: none (moot if TP-11 or TP-12 lands: `_close_fds` goes)
- Confidence: high
- Verdict: CONFIRMED
- Orchestrator: Tier B, work package Q-6.12 (see ../plan.md).

## Looked at and kept

- `tools/runner.py` `kill_process_tree`, `kill_leftovers`, `_kill_and_reap`, `_wait_gone`, `PIPE_DRAIN_GRACE`, the `TimeoutError` fallback and the `_execute` structure (ruff C901 21, PLR0915 54): the C-1 rules (timeout, cancel, output limit, tree kill, pipes drained), decision 0005 and the Windows `kill_leftovers` branch. Splitting `_execute` would move code, not remove it.
- `platform/childproc.py` `KillOnCloseJob` with its three modes (`process`, `per_child`, `unavailable`) and `Kernel32` / `_load_kernel32`: decision 0005 item 1 names the `per_child` fallback; Windows only, mock-tested; any change needs the Windows test VM.
- The three `Kernel32` protocols (`childproc.py`, `power.py`, `sleep.py`), `PowrProf`, `Advapi32`, `Win32Libraries`: each lists only the functions its module calls; they are the test seam for Windows code on Linux (decision 0053).
- `platform/power.py` executors (`PowerExecutor`, `SystemctlExecutor`, `WindowsExecutor`, `UnsupportedExecutor`, `default_executor`): the protocol is the seam that lets the queue tests use a recording executor, and `refusal()` with `_run_command` / `_load_win32` keeps tests from shutting the machine down (decision 0036). Plain functions would save about 25 lines but the tests of `test_power_executors.py` build the classes with injected `run` / `libraries`.
- `platform/sleep.py` `_in_thread`, `_spawn`, `_Ticket`, the per-call tasks that hold the lock, the counted `acquire` / `release` / `close`, `InhibitState`, `not_stopped`, `last_error`: decision 0011 follow-up items 3 to 5 and 0022 ("the inhibitor says what is not stopped"). The `state`, `backend` and `not_stopped` properties are read only by tests, but they are the spec of 0011 item 6 and 0022.
- `platform/dbus.py` `parse_address`, `_unescape`, the "raises only documented errors" structure: 0011 follow-up item 2.
- `platform/longpath.py`: Windows `MAX_PATH` refusal, used by 8 modules and the server (decision 0070).
- `tools/discovery.py` `ALLOW_SCRIPT_TOOLS_ENV` and the PATHEXT branch of `_Context.exe_names`: the Windows tests run fake `.cmd` tools; the variable is set by the shared pytest plugin and by 4 test files.
- `tools/discovery.py` `_Context`, `platform=` parameters: Windows rules are tested on Linux through them (decision 0053).
- `tools/discovery.py` `_use_bundled_fix`, `_with_origin_note`, the long reason texts: user-visible strings, covered by tests.
- `tools/fetch.py` `_check_links` (C901 15), `tar.bz2` mode, `_swap_into_place`, `remove_stale_work`, `_retry_on_permission`: decision 0038 follow-ups (links resolved through each other, a killed fetch's folder, the Windows scanner retry). `tar.bz2` is used by `scripts/bundle-tools.py` for libva.
- `tools/fetch.py` `Build.release_version`, `license`, `source_commit` (vulture "unused"): validated and kept so the core accepts the same manifests as the script; they go with TP-01 if the validator is shared.
- `tools/exitcodes.py` `crashed`: one function in its own module, used by `queue/runner.py` and `capabilities/reasons.py`; decision 0070 (NTSTATUS crash codes). A move into `runner.py` would be a rename, not a simplification.
- `tools/__main__.py` `--require` and `--expect-origin`: used by `.github/workflows/ci.yml:81,405`. `--json` has no CI caller but is 3 lines.
- `paths.py` `bundled_tool_roots` and its test parameters; `config_dir` / `data_dir` / `cache_dir`: decision 0005 item 2 and 3; the three functions differ only in the variable and the platformdirs call.
- `applog.py` `_Shared`, `_File.doRollover` / `_shift`, `_Forward`, `_finite`: decision 0078 review items (the rotation failure on Windows lost 89 of 100 records; uvicorn's logger does not propagate; `json.dumps` writes `NaN`). Only one app log is open in production; the sharing exists for tests that open several in one process.
- `diagnostics.py` `home_relative`, `_homes`, `_windows_os`: decision 0078 items 6 and 7 (Fedora Atomic `/var/home`, Windows case rules); the injected `getwindowsversion` makes the Windows line testable on Linux.
- The "RunResult to failure text" pattern (`power._describe_failure`, `analysis.common.check_run`, `probe.ffprobe._failure`, `capabilities.hwtest`, `discovery.check_tool`, `fetch._check_version`, `preview.common.failure_text`): each maps to a different result type and its text is asserted by tests. A shared helper would only cover the "last stderr line" part (`discovery._last_line`, `analysis.common._detail`, `probe.ffprobe._stderr_detail`, `queue.errors.stderr_reason`) and those pick the first or the last line on purpose; not worth a finding.
- `tests/tools/test_discovery.py` (51 tests, 762 lines) and `test_runner.py` (41): each test names one rule of 0005 or C-1; no helper is repeated.

## Noted by the verifier (not verified)

- `scripts/bundle-tools.py:94-182` (`_pin`, `_rel_path`, the libva manifest checks) is a third manifest validator next to `reframe.tools.fetch._parse_*` and `scripts/fetch-tools.py`; it already imports `reframe.tools.fetch`, so it could reuse the core's helpers (`_get_str`, `_get_rel_path`) after TP-01.
- `tools/__main__.py` and `scripts/bundle-tools.py:350` are the only source users of `discover_tools_sync`; `docs/test-trim-reports/T.md:78,138` mention it as a covered test name (history, no change needed).
