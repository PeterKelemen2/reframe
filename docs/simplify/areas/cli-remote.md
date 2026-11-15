# cli-remote: simplification findings

Commit: 85d9dcb.
Verified: 2026-11-15, 5 confirmed, 9 adjusted, 0 rejected.

Scope: `packages/reframe/src/reframe/cli.py`, `packages/reframe/src/reframe/remote/` (`__init__.py`, `owner.py`, `queue.py`), with `packages/reframe/tests/test_cli.py`, `packages/reframe/tests/jobs/test_cli_*.py`, `packages/reframe/tests/remote/`, `packages/reframe/tests/tools/test_fetch_cli.py`. Source lines: 4356 code lines (cli.py 3338, remote 1018). Read in full: `cli.py`, `remote/__init__.py`, `remote/owner.py`, `remote/queue.py`. Only skimmed: the tests (helper lists, the tests that guard a finding, `test_cli_client.py` test names), `reframe/jobs.py` (`JobService.draft`), `reframe/settings.py` (`JsonDocumentFile`), `reframe/textfile.py`, `reframe/tasks.py`. Decision records read: 0017, 0038, 0061 (all), 0062 (table), 0040 and 0042 (CLI parts), 0078 (CLI parts).

## Summary

Most of the complexity in this area is required. The remote queue copy (`RemoteQueue`), the owner search, the Ctrl+C / Ctrl+Z / lost-connection handling and the multi-client follow code (`CommandJobs`, `_Following`, `_start`, `_held`) come from 0061 and 0062, and each part has a measured or reviewed reason. They are listed in "Looked at and kept". What is left is mostly repetition inside `cli.py`: the same print idiom 48 times, the same typer options and the same file/preset checks in `encode` and `batch`, a second copy of `JobService.draft` (`OwnerJobs.draft`), code that handles states the core fixed long ago (`TaskFailed`), and helpers that repeat what the core or typer already do (`write_text_file`, `_read_regular_file`, the three `StrEnum`s, `in_process_default`). Dead code is small (one constant in `remote/queue.py`, the `TaskFailed` handling). Several findings are cross-area (jobs, settings, textfile, queue, server owner). No finding changes a CLI flag, exit code or output line. The estimated total is about -230 source lines and -65 test lines, without the decision-change finding.

## Findings

### CLI-01: one helper for the "print one wrapped-off line" idiom and one for `warning:` lines
- Kind: duplication
- Where: `cli.py`, 48 calls of the form `console.print(Text(...), soft_wrap=True)` (132 lines now), at lines 1061, 1072, 1076, 1088, 1098, 1118, 1124, 1154, 1158, 1475, 1570 (`EncodeView.line`), 1775, 1786, 1797, 1809, 1998, 2005, 2008, 2076, 2078, 2080, 2298, 2423, 2475, 2577, 2593, 2603, 2609, 2814, 3024, 3026, 3032, 3169, 3191, 3215, 3222, 3246, 3293, 3306, 3351, 3354, 3411, 3480, 3482, 3596, 3661, 3727, 3738. And 10 `print(_one_line(f"warning: …"), file=sys.stderr)` calls at 847 (`WarningPrinter.show`), 1449-1455 (`open_queue`), 1692 (`run_encode`), 2533 (`run_batch`), 2842-2844 (`name_targets`), 3003 (`_owner_or_saved`), 3077 (`run_queue_log`), 3499-3506 (`_fetch_report`), 3643 (`run_presets_export`), 3646-3650 (`run_presets_export`).
- Now: every line of output is written as `console.print(Text(printable(x), style=s), soft_wrap=True)`. Ruff's format makes this 3 to 5 lines each. `printable` (control characters shown as U+FFFD, 0038 R5-9 and RA-2) is called at 59 places by hand (counted with the AST; `grep` shows 60 lines because of the `def`), and RA-2 was a list of places that forgot it. The same is true of warnings: `_error` exists for `error:` lines, but warnings repeat `print(_one_line(f"warning: …"), file=sys.stderr)`. I measured the 48 calls with the AST: 132 lines now, about 60 after the change.
- Change: add next to `_error` (line 823):
  ```python
  def _say(console: Console, text: str, style: str = "") -> None:
      """One line, not wrapped; control characters of ``text`` are shown as U+FFFD."""
      console.print(Text(printable(text), style=style), soft_wrap=True)

  def _warn(message: str) -> None:
      """One ``warning:`` line on stderr."""
      print(_one_line(f"warning: {message}"), file=sys.stderr)
  ```
  Replace each of the 48 calls by `_say(console, text, style)` and drop the inner `printable(…)`. `EncodeView.line` becomes `_say(target, text, style)`. Replace the 10 warning prints by `_warn(…)`. Leave alone the calls with `crop=False` (2462, 3035), `overflow=` (659, 974) and `Text.assemble`, and the `_indented` / `_labelled` callers. No site has a `\n` in its text (checked), so `printable` on a static string changes nothing. One warning print (3646-3650) has no `_one_line` today; its text has no control characters, so the output is the same.
- Behaviour: unchanged (byte for byte; `printable` and `_one_line` are no-ops on text without control characters).
- Contracts touched: none (CLI output stays the same).
- Callers to update: only `cli.py`.
- Tests: none change. `tests/jobs/test_cli_control_characters.py` stays as the guard that every human line goes through `printable`; it now also covers the new helper.
- Decision records: 0038 (R5-9, RA-2) and 0017 item 24. The change keeps them and makes `printable` one choke point for these lines.
- Size: M; estimated lines: -75 / -0
- Risk: low. One typo in a style string or a lost `soft_wrap` would show in the CLI tests that compare lines.
- Depends on: none (CLI-02 and CLI-11 touch some of the same lines; do this one first).
- Confidence: high
- Verdict: ADJUSTED (only the count of `printable` calls: 59, not 60. Everything else re-checked and right: the 48 sites with their line numbers and the 132 lines (AST), the 10 warning prints, no `\n` or `\t` in any site's text, so `printable` on the 20 sites that lack it today changes no byte; the texts of those sites are static, numbers, `label`, job ids, or text that already went through `printable`/`display_path`, and `printable` is idempotent)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-02: `encode` and `batch` repeat the same preamble, options and display code
- Kind: duplication
- Where: `cli.py`: `run_encode` 1666-1710 and `run_batch` 2498-2550 (the media-file checks 1686-1695 and 2527-2536 are the same 10 lines); `_draft_files` 1762-1824 and `_batch.prepare` 2596-2617 (labels, the `[n/N] name → output` line and the `not queued:` line); typer declarations in `build_app` for `encode` 3851-3872 and `batch` 3951-3978 (`--recursive`, `--detach`, `--in-process` are written out twice, 22 lines each time); the four blocks `chosen = find_preset(app, preset); if isinstance(chosen, str): _error(chosen); return EXIT_USAGE` at 1186-1189, 1702-1705, 2537-2540, 2857-2860.
- Now: the two commands were written one after the other and copy each other. The typer options are word for word the same, including the long help strings (a third copy of the idea is `_PresetOption` and `_OutputOption`, which are already aliases at the top of the file).
- Change:
  1. Add `_RecursiveOption`, `_DetachOption`, `_InProcessOption` as `Annotated[...]` aliases next to `_PresetOption` in the `else:` block at line 122-151. Use them in `encode` and `batch` (`recursive: _RecursiveOption = False` and so on). Saves about 16 lines. Ordering trap: `_InProcessOption` has `envvar=IN_PROCESS_ENV`, and `IN_PROCESS_ENV` is defined at line 1238, after that block, so the alias would raise `NameError` at import. Move the `IN_PROCESS_ENV = "REFRAME_IN_PROCESS"` constant (with its comment, lines 1235-1238) above the `try:` import block, or define the three aliases after line 1238 under `if _CLI_EXTRA:` (`typer` is only bound when the extra is installed). The three option definitions are word for word the same in `encode` (3852-3872) and `batch` (3952-3978), checked.
  2. Add one helper and use it in both commands:
     ```python
     async def _media_files(app: Reframe, paths: Sequence[Path], recursive: bool) -> list[Path] | int:
         """The media files of ``paths``, else the exit code (after the error lines)."""
         found = await app.jobs.media_files(paths, recursive=recursive)
         for missing in found.missing:
             _error(f"{display_path(missing)}: {missing_text(missing, _MISSING)}")
         if found.missing:
             return EXIT_NOT_FOUND
         for folder in found.empty:
             _warn(f"{folder}: no media files in this folder.")
         if not found.files:
             _error("no media files to encode.")
             return EXIT_NOT_FOUND
         return found.files
     ```
     Call: `files = await _media_files(app, paths, recursive)` then `if isinstance(files, int): return files`.
  3. Add `_labels(count: int) -> list[str]` (the `[{n:>{width}}/{total}]` list that both commands build). Do not add a `_not_queued` helper: the two `not queued:` lines (1809-1815 and 2609-2615) differ in text (`{issue_counts(draft.issues)}` and `{issue_counts(row.issues)} (see Problems)`), and after CLI-01 each is one `_say(console, f"{' ' * len(label)} not queued: …", "bold red")` call. Optional: a `_preset(app, name) -> Preset | None` that prints the error, to replace the four `find_preset` blocks with `if (chosen := _preset(app, preset)) is None: return EXIT_USAGE`.
  4. Flag argument: `_batch(service, session: QueueSession | None, …)` uses `session is None` to mean "dry run". Split it into the resolve-and-print part (shared) and the queue part, so that `run_batch` calls the first for `--dry-run` and both otherwise. This does not save many lines; it removes the flag.
- Behaviour: unchanged.
- Contracts touched: CLI (none changes: same flags, help text and messages; the help text comes from the same strings).
- Callers to update: `cli.py` only.
- Tests: none change. `tests/jobs/test_cli_encode.py`, `test_cli_batch.py` and the help-text tests guard it.
- Decision records: 0017, 0040, 0061 item 5. Unchanged.
- Size: M; estimated lines: -20 / -0
- Risk: low. Typer reads the aliases at import time; a wrong alias would show in `reframe encode --help`.
- Depends on: CLI-01 (do it first, so `_warn` and `_say` exist).
- Confidence: high
- Verdict: ADJUSTED (`_InProcessOption` cannot sit in the `else:` block at 122-151: `IN_PROCESS_ENV` is defined at 1238, so import would fail; media-file block is 10 lines at 1686-1695 and 2527-2536, not 11; `_not_queued` dropped, the two lines differ and CLI-01 already makes each one call; estimate -22 becomes -20. Helper `_media_files` keeps order, text and exit codes of the original blocks, checked)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-03: `OwnerJobs.draft` is a second copy of `JobService.draft`
- Kind: duplication (cross-area: jobs)
- Where: `cli.py:1298-1363` (`OwnerJobs`, mainly `draft` 1309-1344) and `_Drafts` 1266-1273; `reframe/jobs.py:348-385` (`JobService.draft`).
- Now: in client mode the command drafts locally and the owner validates (0061 item 4). `OwnerJobs.draft` does this by copying the whole pipeline of `JobService.draft`: probe, resolve the preset, naming options, `draft_from_preset` in a thread, `name_job`, keep the track-stage errors and `batch.*` issues, build `JobDraft`. Only the last step differs (`await self._validate(job)` instead of `JobService._validate`). The test `test_a_client_drafts_as_the_in_process_draft` (`tests/remote/test_cli_client.py:146`) exists to catch the two copies drifting apart (it asserts `client == local`). `OwnerJobs.draft` also accepts `preset: Preset | str | None` and a `MediaSource` source, with a `find_preset` fallback and a `raise ValueError(chosen)` that nothing reaches: `_draft_files` is the only caller and always passes a `Path` and a `Preset` (callers outside tests: 1; `BatchService` calls only `name_job` and `validate`).
- Change:
  - `JobService.draft(self, source, preset=None, *, output=None, validate: Callable[[JobSettings], Awaitable[list[ValidationIssue]]] | None = None)`. In the body replace `*await self._validate(job, media, naming)` with `*await (validate(job) if validate is not None else self._validate(job, media, naming))`. Docstring: "``validate``: validates the drafted job instead of this service (a client whose queue's owner decides)".
  - `OwnerJobs.draft(self, source: Path, preset: Preset, *, output: Path | None = None) -> JobDraft | ProbeError: return await self._app.jobs.draft(source, preset, output=output, validate=self._validate)`.
  - Narrow `_Drafts.draft` to `(source: Path, preset: Preset, *, output: Path | None = None)`. `JobService.draft` still satisfies it.
  - Remove the now unused `draft_from_preset`, `Severity` (if unused) imports of `cli.py`. `name_job` and `validate` of `OwnerJobs` stay (the `_Jobs` protocol of `BatchService` needs them).
- Behaviour: unchanged (the draft is the same; `client == local` still holds).
- Contracts touched: public core API (`JobService.draft` gets an optional keyword; not an HTTP parameter, so the OpenAPI schema does not change; the server does not pass it).
- Callers to update: `cli.py` (`OwnerJobs`, `_Drafts`), `reframe/jobs.py`. No other caller of `OwnerJobs.draft`.
- Tests: keep `test_a_client_drafts_as_the_in_process_draft` (it guards the equality and the `validate` hook). Add one line to a jobs test that `draft(validate=…)` uses the given validator (the client test covers it already).
- Decision records: 0061 item 4 ("OwnerJobs: draft_from_preset, name_job") is kept: the client still drafts locally and the owner validates. 0017 items 1-4 are unchanged.
- Size: S; estimated lines: -22 / -0 (about -25 in `cli.py`, +3 in `jobs.py`)
- Risk: medium. It touches `JobService.draft`, which the server and the desktop use. The equality test and the client-mode tests guard it.
- Depends on: none
- Confidence: medium (I did not run the tests; I compared the two bodies line by line)
- Verdict: CONFIRMED (both bodies compared again: same preset-naming source, same `draft_from_preset(..., container_codecs=False)` call, same track-issue filter, same `JobDraft` fields; `OwnerJobs.name_job` copies the job and `JobService._name` mutates it, which gives the same result; `OwnerJobs.draft` has one caller, `_draft_files`, plus `tests/remote/test_cli_client.py:163-164`; nothing patches `JobService.draft`; `Severity` stays imported, 17 other uses)
- Orchestrator: joined into X-03 (see ../cross-cutting.md); that entry decides the tier and the work package. Joined into X-03 with QJ-03. Use the shape of QJ-03 (the probe stays first in `OwnerJobs.draft`), not the shorter shape here.

### CLI-04: the `reframe queue` actions repeat the owner connection and its clean-up; `connect_owner` passes folders that are the defaults
- Kind: structure
- Where: `cli.py`: `_owner_for` 3133-3140, `run_queue_action` 3156-3194, `run_queue_retry` 3197-3228, `run_queue_remove` 3231-3249; `connect_owner` 1409-1431; its four callers at 1442-1444 (`open_queue`), 1491-1493 (`reconnect`), 2991-2993 (`_owner_or_saved`), 3134-3136 (`_owner_for`).
- Now: each of the three actions does `remote = await _owner_for(...)`, `if remote is None: return EXIT_FAILED`, `try: … finally: await remote.close(detach=True)`. `connect_owner(data_dir, *, config_dir, cache_dir, start)` takes the config and cache folders only to pass them to `RemoteQueue.connect`. In the CLI they are always `paths.config_dir()` and `paths.cache_dir()` (`open_reframe` makes `Reframe` from the same `paths.*()` calls; checked in `Reframe.create`, lines 1038-1040 of `service.py`), and `RemoteQueue.__init__` already defaults to exactly those (`config_dir or paths.config_dir()`). Only the test fixture `tests/remote/conftest.py:83-88` passes other folders, and it calls `RemoteQueue.connect` directly.
- Change:
  - `connect_owner(data_dir: Path, *, start: bool = True)`: drop `config_dir` and `cache_dir` and the two keywords in the `RemoteQueue.connect(...)` call; the four callers shrink.
  - Replace `_owner_for` by an async context manager:
    ```python
    @asynccontextmanager
    async def _owner(action: str) -> AsyncIterator[RemoteQueue | None]:
        found = await connect_owner(paths.data_dir())
        if isinstance(found, str):
            _error(f"{action} needs the Reframe server that owns the queue: {found}.")
            yield None
            return
        try:
            yield found
        finally:
            await found.close(detach=True)
    ```
    Each action becomes `async with _owner("reframe queue retry") as remote:` followed by `if remote is None: return EXIT_FAILED`, and loses its own `try`/`finally`.
- Behaviour: unchanged.
- Contracts touched: none. `connect_owner` is public in the module but has no caller outside `cli.py` and two monkeypatches in tests that use `*args, **kwargs` (`tests/remote/test_cli_client.py:769-776` and `:804`), so they do not change.
- Callers to update: the four above, and `run_queue_action`, `run_queue_retry`, `run_queue_remove`.
- Tests: none change.
- Decision records: 0061 item 8 (`retry` and `remove` need an owner and start one). Unchanged.
- Size: S; estimated lines: -15 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (`open_reframe` builds `Reframe` from `paths.config_dir()`, `paths.data_dir()` and `paths.cache_dir()`, so `app.config_dir`/`app.cache_dir` are the defaults of `RemoteQueue.__init__`; `connect_owner` has no caller outside `cli.py` and the two `*args, **kwargs` monkeypatches; the CLI tests run under `cli_env`, which sets the three folder variables)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-05: `run_encode` and `run_batch` read `REFRAME_IN_PROCESS` a second time, for callers that do not exist
- Kind: defensive
- Where: `cli.py:1243-1263` (`in_process_default`, `_in_process`), `run_encode` 1666-1680, `run_batch` 2498-2524 (the `in_process: bool | None = None` parameter and the `if in_process is None: return EXIT_USAGE` branch), `build_app` 3863-3872 and 3969-3978 (`envvar=IN_PROCESS_ENV`).
- Now: typer's `--in-process` option already has `envvar=IN_PROCESS_ENV`. Click reads the variable and rejects a bad value with exit 2 before `run_encode` runs. I checked this with `REFRAME_IN_PROCESS=garbage reframe encode x.mkv` through `CliRunner`: exit 2, "Invalid value for '--in-process' (env var: 'REFRAME_IN_PROCESS'): 'garbage' is not a valid boolean". So the typer path always passes a `bool`, and `_in_process(None)` runs only when a test calls `run_encode` or `run_batch` directly without `in_process` (0061 item 9 and C12). `in_process_default` has 0 callers outside `cli.py` and the code imports `click` just for it.
- Change: `in_process: bool = False` in `run_encode` and `run_batch`. Delete `in_process_default`, `_in_process`, the lazy `import click`, and the two `None` returns. Keep `IN_PROCESS_ENV` (typer's `envvar`, and tests set it for the typer path).
- Behaviour: unchanged for the command line. A direct caller that relied on the variable has to pass `in_process=True`.
- Contracts touched: none for users. `run_encode` and `run_batch` are module functions used by tests only.
- Callers to update: tests that call `run_encode` / `run_batch` directly under `cli_env` (which sets `REFRAME_IN_PROCESS=1`): `tests/jobs/test_cli_encode.py:210, 463, 489, 520, 559`, `tests/jobs/test_cli_when_done.py:224`, `tests/jobs/test_cli_batch.py:274` get `in_process=True`; `tests/remote/test_cli_client.py:242` (`in_process=options.get("in_process")` becomes `bool(options.get("in_process"))`). A test that forgets it would start a real server, and the folders guard (`reframe_testing.folders_guard`) fails it loudly.
- Tests: replace `test_reframe_in_process_is_read_as_the_command_line_reads_it` (`tests/remote/test_cli_client.py:1141-1161`, parametrized) by a short test through `invoke("encode", "x.mkv", env={IN_PROCESS_ENV: "garbage"})` that asserts exit 2 and `"'garbage' is not a valid boolean"` in the output (0061 C12 requires the usage error, and no other test sets the variable to a bad value: `cli_env` and the other tests only set `1`). Its "off" case (client mode) needs no replacement: with `in_process: bool = False` it is the default of every direct call in `tests/remote`.
- Decision records: 0061 C12 says the variable is read by click's rule and a bad value is a usage error. That is still true, and click does it.
- Size: S; estimated lines: -18 / -12
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the garbage-value case is the only guard of 0061 C12: do not just delete the test, replace it by an `invoke` test of the typer path, so the test saving is about -12, not -18; the caller list of direct `run_encode`/`run_batch` calls under `cli_env` is complete, checked with `rg`; the typer path gives exit 2 for `REFRAME_IN_PROCESS=garbage`, run again)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-06: dead handling of `TaskFailed` in the fetch command
- Kind: dead-code
- Where: `cli.py:45` (`from reframe.mediatask import TaskFailed`), `15` (`import logging`), `3362-3366` (`task_error`), `3452` (its one call), `4171-4184` (`_ExpectedTaskFailure`, `_quiet_expected_failures`), `4190` (the call in `_run`). Tests: `tests/tools/test_fetch_cli.py:25` (import `task_error`), `431-436` (`test_task_error_drops_the_expected_failure_prefix`), `439-460` (`test_an_expected_task_failure_is_not_logged_with_a_traceback`).
- Now: 0038 item 9 added a log filter and a `removeprefix("TaskFailed: ")` because the task manager logged a `TaskFailed` with a traceback and gave `TaskInfo.error` the prefix. Its own Consequences say "The CLI handles both forms" and that the core would be fixed; it was (commit fb895a9, test `tests/test_tasks.py::test_an_expected_failure_is_its_message_without_a_traceback`). `reframe/tasks.py:281-284` now does `log.info(...)` with no `exc_info` and `task.info.error = str(exc) or type(exc).__name__` for `TaskFailed`. So the filter (which matches `record.exc_info` holding a `TaskFailed`) never matches, and the prefix is never there. Callers: `task_error` 1 (plus its test), `_quiet_expected_failures` 1 (plus its test).
- Change: delete `task_error`, `_ExpectedTaskFailure`, `_quiet_expected_failures` and its call in `_run`, and the imports `TaskFailed` and `logging`. In `run_tools_fetch` use `reason = (final.error or "no reason given") if final.state is TaskState.FAILED else "it was cancelled"`.
- Behaviour: unchanged (the filter and the prefix strip do nothing today).
- Contracts touched: none.
- Callers to update: `cli.py` only.
- Tests: delete the two tests named above and the `task_error` import. The fetch failure tests (`test_fetch_cli.py`, "error: the fetch failed: …") stay as the guard.
- Decision records: 0038 item 9 and its Consequences. The core part is built (fb895a9); the CLI part is the leftover.
- Size: S; estimated lines: -14 / -22
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (`tasks.py:281-284` catches `TaskFailed` before `Exception`, logs with `log.info` and no `exc_info`, and sets the error to the bare message; the filter only matches a record whose `exc_info` holds a `TaskFailed`, which the `reframe.tasks` logger never gets; `logging` is used nowhere else in `cli.py`)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-07: three `StrEnum` classes repeat values that the core already has as `Literal` types
- Kind: reinvented
- Where: `cli.py:3521-3541` (`LevelChoice`, `ConflictChoice`, `PlatformChoice`), `3938-3946` and `3995` (`--level`, `level.value`), `4155-4163` and `4166` (`--on-conflict`, `on_conflict.value`), `4090-4097` and `4106` (`--platform`, `target.value`), import of `StrEnum` at line 32.
- Now: `LevelChoice` lists the values of `reframe.models.batch.MatchLevel` (`Literal["strict", "standard", "loose"]`), `ConflictChoice` those of `reframe.presets.store.ConflictPolicy` (`Literal["rename", "replace", "skip"]`). `PlatformChoice` lists two of the three values of `reframe.tools.fetch.PLATFORMS` (the CLI offers the platforms of the desktop packages; `tools/ffmpeg.toml` does have a `linux-arm64` build, but "only the arm64 Docker image ships it"; the `Literal` keeps the two values, so behaviour does not change). Typer 0.27.3 (the pinned minimum is `typer>=0.27.3`) takes `Literal` options. I checked it with a script: the `--help` line (`<strict|standard|loose>`, `[default: standard]`) and the error text for a bad value ("'bad' is not one of 'strict', 'standard', 'loose'.", exit 2) are the same for a `StrEnum` and for a `Literal`, also with `from __future__ import annotations` and with `Literal[...] | None`. Callers of the three classes outside `cli.py`: 0.
- Change: delete the three classes. `level: Annotated[MatchLevel, typer.Option("--level", help=...)] = "standard"` and pass `level=level`; `on_conflict: Annotated[ConflictPolicy, typer.Option(...)] = "rename"` and pass `on_conflict=on_conflict`; `target: Annotated[Literal["linux-x64", "windows-x64"] | None, typer.Option(...)] = None` and pass `platform=target`. Drop the `StrEnum` import, add `Literal` to the `typing` import. `MatchLevel` and `ConflictPolicy` are already imported in `cli.py`.
- Behaviour: unchanged (help and errors identical, as checked).
- Contracts touched: CLI help text (identical).
- Callers to update: `cli.py` only.
- Tests: none change.
- Decision records: 0040 item 7 and 0038 item 12 name the option values only.
- Size: S; estimated lines: -11 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (the aside "the manifest has no `linux-arm64` archive" was wrong: the manifest has one for the Docker image; the change is unchanged. Re-run: `--help` text, `[default: …]`, bad-value error and exit 2 are identical for `StrEnum` and `Literal` under `from __future__ import annotations` with typer 0.27.3; `MatchLevel` and `ConflictPolicy` are module-level runtime imports, so typer can resolve the annotations)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-08: `_read_regular_file` copies `reframe.textfile.open_regular`
- Kind: duplication (cross-area: textfile)
- Where: `cli.py:3672-3685` (`_read_regular_file`), `3688-3720` (`read_preset_file`), `import stat` at line 18; `reframe/textfile.py:66-100` (`NotARegularFileError`, `open_regular`).
- Now: `open_regular(path)` already opens a path without blocking (`O_NONBLOCK`, `O_BINARY`), checks it with `fstat` after the open, and raises `IsADirectoryError` for a folder and `NotARegularFileError` for a FIFO, socket or device, with the Windows `EACCES` case for folders. `_read_regular_file` is the same code (same flags, same `fstat` checks) returning error strings instead of raising. `open_regular` has two other callers (`chapters.py:336`, `analysis/subtitlefile.py:27`).
- Change: in `read_preset_file`:
  ```python
  try:
      if str(path) == "-":
          raw = sys.stdin.buffer.read(MAX_PRESET_FILE + 1)
      else:
          with open_regular(path) as f:
              raw = f.read(MAX_PRESET_FILE + 1)
  except FileNotFoundError: …                       # unchanged
  except IsADirectoryError: …                       # unchanged text: "is a folder, not a preset file."
  except NotARegularFileError:
      return EXIT_NOT_FOUND, f"{name} is not a regular file (a device, a pipe or a socket): it is not read."
  except OSError as exc: …                          # unchanged; after NotARegularFileError (it is an OSError)
  ```
  Delete `_read_regular_file`, the `isinstance(raw, str)` branch and `import stat`; add `from reframe.textfile import NotARegularFileError, open_regular`.
- Behaviour: unchanged (the same three messages and exit codes; the first `path.is_dir()` check is covered by `open_regular`).
- Contracts touched: none.
- Callers to update: `cli.py` only.
- Tests: none change. `test_import_never_reads_a_device_or_a_fifo`, `test_import_refuses_a_file_larger_than_the_cap` and `test_import_from_stdin_is_capped` (`tests/jobs/test_cli_presets.py`) guard it.
- Decision records: 0038 "The size of `presets import`" (cap 16 MiB, no device, no FIFO). Kept.
- Size: S; estimated lines: -11 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: CONFIRMED (the three messages and exit codes are the same; `open_regular` also covers the Windows `EACCES` folder case that `path.is_dir()` covers today; `stat` has no other use in `cli.py`; no CLI test covers the "is a folder" message, so add one line to `tests/jobs/test_cli_presets.py` for it)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-09: five hand-made "write a file through a temporary file and rename it" blocks
- Kind: duplication (cross-area: settings, capabilities, probe)
- Where: `cli.py:3609-3620` (`write_text_file`); `reframe/settings.py:174-190` (`JsonDocumentFile.write`); `reframe/capabilities/cache.py:177-186`; `reframe/probe/cache.py:214-229`. (`reframe_server/login.py` already goes through `JsonDocumentFile`.)
- Now: all four do `mkstemp(dir=folder, prefix=…, suffix=…)`, `os.fdopen(fd, "w", …)`, write, `os.replace`, and `unlink` the temporary file on failure. `settings.py` adds `fsync`, a folder sync and the Windows retry of `os.replace` (`replace_file`); the other three do not. The CLI's copy is used once (`presets export -o FILE`) and has 4 test uses (`tests/jobs/test_cli_presets.py:26, 227-232`).
- Change: one function in `reframe/settings.py` next to `replace_file`, for example `write_text_atomic(target: Path, text: str, *, prefix: str, suffix: str = ".tmp", encoding: str = "utf-8", newline: str | None = "\n", durable: bool = False) -> None` (raises `OSError`; with `durable` it does the `fsync` and folder sync). `prefix` and `suffix` are required: the temporary names are not the same and the caches' `prune` finds crash leftovers by them (`capabilities/cache.py` `prune`: files named `.tmp-*.json`; `probe/cache.py` `prune`: any `*.tmp`; the CLI and `JsonDocumentFile` use `.<name>.*.tmp`), so one fixed name would stop the leftover clean-up. `probe/cache.py` writes `ensure_ascii=True` text with `encoding="ascii"` and `newline=None`; `capabilities/cache.py` streams `json.dump(entry, f, indent=1)` with the default newline, which becomes `json.dumps(...)` of the text first. The two caches keep their own error handling (`put` returns `False` or logs), so each wraps the call in its own `try`. `JsonDocumentFile.write` calls it with `durable=True`; `capabilities/cache.py` and `probe/cache.py` call it with the default; the CLI's `write_text_file` is deleted and `run_presets_export` calls it. The two caches get the Windows retry of `os.replace`, which they lack today.
- Behaviour: unchanged for the CLI (still no parent folder is created, so `presets export -o no/such/folder/p.json` still ends with exit 1; `JsonDocumentFile.write` creates folders, so the new helper must not). Caches: a Windows `PermissionError` on the rename is retried first. Not measured on Windows.
- Contracts touched: none (public core API gains one function; `reframe.cli.write_text_file` goes, its only callers are tests).
- Callers to update: `cli.py:3657`, `settings.py`, `capabilities/cache.py`, `probe/cache.py`; `tests/jobs/test_cli_presets.py` (the import, and `test_write_text_file_leaves_no_temporary_file` moves to a settings test).
- Tests: move `test_write_text_file_leaves_no_temporary_file` to `tests/test_settings.py`; the cache tests stay.
- Decision records: 0015 (stores) and 0038 item 11 ("written through a temporary file and a rename"). Kept.
- Size: M; estimated lines: -9 in this area, about -6 more in the other three files (-15 in all: the helper is about 22 lines and each of the four copies is 10 to 12) / -0
- Risk: medium (the caches are on a hot path; keep `durable=False` there). If the other areas do not want it, leave the CLI's copy as it is: calling `JsonDocumentFile.write` from the CLI is not equivalent, because it creates the parent folders and the CLI must not. The Windows retry of `os.replace` (6 attempts, 50 ms doubling, up to about 1.5 s in a worker thread) is new for the two caches: that is a Windows-only change in behaviour and needs a check on the Windows test VM (ssh TestWin@192.168.122.4) before it lands; or give the helper a `retry: bool` and keep the caches without it.
- Depends on: none
- Confidence: low (the saving is small once `prefix`/`suffix`/`encoding` are parameters, and the caches' `prune` depends on the temporary names)
- Verdict: ADJUSTED (the proposed signature lacked `prefix` and `suffix`, which `prune` of both caches relies on; total saving about -15, not -33; the Windows retry in the caches needs a Windows VM check, not just "not measured"; confidence medium becomes low)
- Orchestrator: joined into X-10 (see ../cross-cutting.md); that entry decides the tier and the work package.

### CLI-10: the ended and active job-state sets are defined four times; one constant has no use
- Kind: duplication / dead-code (cross-area: queue)
- Where: `cli.py:1516` (`FINAL_STATES`), `2901` (`_ACTIVE_STATES`); `remote/queue.py:53-54` (`ENDED`, `_ACTIVE`) and `71-72` (`FORWARDED`); `queue/service.py:62-63` (`ENDED`, `_ACTIVE`; `ENDED` is exported by `reframe.queue` and used by the server in `events.py:35` and `routers/queue.py:16`).
- Now: `cli.py` already imports `ENDED` from `reframe.queue` (line 88) and uses it at 3093 and 3097, yet also defines `FINAL_STATES` with the same four states (used at 1868, 1884, 1900, 1911, 2295; callers outside `cli.py`: 1, `tests/jobs/test_cli_when_done.py:143`). `remote/queue.py` defines `ENDED` and `_ACTIVE` again. `FORWARDED = frozenset(_MODELS)` at `remote/queue.py:72` has 0 users anywhere (vulture reports it).
- Change: export `ACTIVE = frozenset({JobState.RUNNING, JobState.PAUSED})` next to `ENDED` in `reframe.queue` (defined once, in `queue/service.py` or better in `reframe/models/queue.py` beside `JobState`; `queue/service.py` then imports both and drops its `_ACTIVE`, used at lines 374 and 643, and its `ENDED` line). `cli.py`: delete `FINAL_STATES` and `_ACTIVE_STATES`, use `ENDED` and `ACTIVE` (`_ACTIVE_STATES` is used at 2221, 2253, 2932 and 3152). `tests/jobs/test_cli_when_done.py:143` uses `cli.FINAL_STATES`: it imports `ENDED` from `reframe.queue` instead. `remote/queue.py`: `from reframe.queue import ACTIVE, ENDED` (it already imports `reframe.queue.errors` and `reframe.queue.logs`) and delete its two sets and `FORWARDED` with its comment. Leave `_ENDED_ON_ITS_OWN` (`cli.py:3113`) and `whendone.py:39`: they are different sets.
- Behaviour: unchanged.
- Contracts touched: public core API (one added name, `reframe.queue.ACTIVE`). The server is not touched.
- Callers to update: the places above.
- Tests: `tests/jobs/test_cli_when_done.py:143` (`cli.FINAL_STATES` becomes `ENDED`); no test is removed.
- Decision records: none.
- Size: S; estimated lines: -5 / -0
- Risk: low
- Depends on: none
- Confidence: high
- Verdict: ADJUSTED (`FINAL_STATES` has one caller outside `cli.py`: `tests/jobs/test_cli_when_done.py:143`, not 0; `queue/service.py` must be listed as a file to change; `FORWARDED` has 0 users, checked with `rg` over the repository)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-11: small repeats inside `cli.py`
- Kind: duplication
- Where and change (each item is independent; line counts are code lines):
  1. `run_probe` 776-790 repeats `_probe_failed` 1222-1227 (fetch the ffprobe status, print `error_message`, map the exit code). Replace the block in `run_probe` by `return await _probe_failed(app, outcome)`. -5.
  2. Three JSON writers: `_write_json` 772-773 (a one-line wrapper with one caller), `_write_model_json` 886-894, `_write_json_value` 3600-3606. Callers also dump models by hand (`_batch` 2570-2575, `run_queue_list` 3019). Keep one `_write_json(value)` that first turns models, and lists and dicts of models, into JSON data with a small recursive `_jsonable`, then writes. Call it with models directly. -5.
  3. The sentence "`X is not usable (status, origin): reason`" is written three times: `error_message` 539-545, `run_encoders` 1030-1033, `tool_problem` 3267-3270 (which adds the fetch hint). One `_not_usable(info)` returning the shared part; `tool_problem` appends the hint. -4.
  4. `_CapabilitySource` 1038-1042 is a Protocol with one real implementation (`CapabilityService`, `app.capabilities`) and no test that calls `_follow_encoders` (0 callers outside `cli.py`). Type the parameter as `CapabilityService` (`from reframe.capabilities import CapabilityService`; `cli.py` does not import it yet, so under `TYPE_CHECKING` is enough). -3.
  5. `_unicode(console)` 2404-2405 is `not console.options.ascii_only` in rich (checked: same result for `utf-8`, `utf_8`, `ascii`). Replace the two uses (2424, 2451). -2.
  6. `task = asyncio.current_task(); if task is not None: task.uncancel()` at 2017-2020, 2724-2727, 3423-3426. One `_uncancel()` helper (3 call lines plus a 4-line helper replace 12 lines: -2; the fourth site, `task.uncancel()` at 2386 in `_stop_here`'s wait loop, is different and stays). -2.
  7. Aliases of exit codes: `EXIT_PROBE_FAILED` = `EXIT_FAILED` (1) and `EXIT_NO_FFPROBE` = `EXIT_NO_TOOL` (4), lines 169-176. Keep one name each (`EXIT_FAILED`, `EXIT_NO_TOOL`) and drop both from `__all__` (lines 157 and 160); the test references are renamed: `tests/test_cli.py` (import at 23 and 26, uses at 319, 416, 421, 430 and 439, 464, 475) and `tests/jobs/test_cli_plan.py` (import at 13, use at 138); `tests/jobs/test_cli_encoders.py` and `tests/tools/test_fetch_cli.py` do not use these two names. -4.
  8. `render_source` 721 repeats `fmt_size(a.size).split(' (')[0]` although `fmt_bytes` (924) is that. -0, one call.
  9. The "key and value rows" loop `_indented(console, Text(printable(value)), _INDENT + 9, first=f"{'':{_INDENT}}{key:<8} ")` is written in `_draft_header` 1143-1144, `render_name` 2827-2828 and (with width 10) `render_source` 691-693. One `_rows(console, rows, width)`. -2.
- Behaviour: unchanged.
- Contracts touched: none (item 7 renames two constants that only tests use).
- Callers to update: `cli.py`, and the tests in item 7.
- Tests: none removed.
- Decision records: 0017 item 21 (exit codes keep their numbers).
- Size: S; estimated lines: -26 / -0
- Risk: low
- Depends on: CLI-01 for item 3 (`_warn`), otherwise none.
- Confidence: high
- Verdict: ADJUSTED (items 1, 2, 3, 5, 8, 9 confirmed; item 4 needs an import, -3; item 6 is -2; item 7 names the wrong test files and forgets `__all__` (-4); total -26, not -28. Item 5 checked against rich: `not console.options.ascii_only` equals `_unicode` for `utf-8`, `utf_8`, `UTF8`, `utf-16`, `ascii`, `cp1252`, `latin-1`, `None`, empty. Item 9: `render_source` passes no `indent` but `lead = max(indent, len(first))` gives the same 13 columns as `_INDENT + 1 + 10`, so one `_rows(console, rows, width)` is exact)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md).

### CLI-12: test helpers that repeat each other
- Kind: tests
- Where: `invoke` and `WIDTH`: `tests/test_cli.py:86, 93-94` and `tests/jobs/conftest.py:44, 229-230` (identical bodies, `invoke(*args, env=None)`), `tests/tools/test_fetch_cli.py:45, 52-53` (`invoke(*args)`, no `env` parameter: the shared one with `env=None` is a superset; `tests/capabilities/test_recheck.py:51` repeats the call inline). `user_preset`: `tests/jobs/test_cli_presets.py:41-47` and `_user_preset` in `tests/jobs/test_cli_control_characters.py:24-29` (same body; one reads `BUILTINS`, the other `builtin_presets()`). `free_port`: `tests/remote/test_owner_search.py:69-73` and `tests/remote/test_remote_queue.py:35-39` (identical). `short_waits`: three fixtures that differ: `tests/remote/test_cli_client.py:98-101` sets `HELD_WAIT` and `START_WAIT` to 0.3, `test_cli_queue.py:28-30` sets only `HELD_WAIT` to 0.3, `test_owner_search.py:89-92` sets both to 0.4.
- Now: copies that would have to change together.
- Change: put `invoke` and `WIDTH` in `tests/conftest.py` (or `reframe_testing`) once and import them; one `user_preset` in `tests/jobs/conftest.py`; one `free_port` and one `short_waits` (both waits 0.4) in `tests/remote/conftest.py`. Check that `test_cli_queue.py` does not need `START_WAIT` untouched (it only sets `HELD_WAIT`; with `start=False` the start wait is not used).
- Behaviour: unchanged.
- Contracts touched: none.
- Callers to update: the test files above.
- Tests: these are the tests.
- Decision records: 0004 (shared testing package).
- Size: S; estimated lines: -0 / -28
- Risk: low
- Depends on: none
- Confidence: medium (the `short_waits` merge needs one run of `tests/remote`)
- Verdict: ADJUSTED (the `invoke` in `test_fetch_cli.py` has no `env` parameter and the three `short_waits` fixtures set different things; `free_port` and `user_preset` are the same. No change in the estimate)
- Orchestrator: Tier A, work package Q-6.3 (see ../plan.md). Made in Q-6.3 with the other CLI findings, because CLI-05 and CLI-11 edit the same test files.

### CLI-13: the client's protocol constants are written again in the server
- Kind: duplication (cross-area: server-owner)
- Where: `remote/owner.py:56` (`API_VERSION = 1`), `58` (`ENDPOINT_FILE = "server.json"`), `70` (`EXIT_STORE_BUSY = 75`); `reframe_server/api.py:27` (`API_VERSION = 1`), `reframe_server/owner.py:34-35` (`ENDPOINT_FILE`, `EXIT_STORE_BUSY`).
- Now: both sides define the same three constants. A test (`test_the_client_speaks_the_api_version_of_the_server_of_its_own_version`, `tests/remote/test_owner_search.py:351-354`) checks the two `API_VERSION`s are equal (0061 item 2: "a test checks that it equals the server's"). The server cannot import `reframe.remote.owner` because that module imports `httpx` (the `[cli]` extra).
- Change: define the three constants once in `reframe/models/queue.py` next to `ServerEndpoint` (which both sides already share) and import them in `remote/owner.py`, `reframe_server/api.py` and `reframe_server/owner.py`. Keep the names exported from `reframe.remote.owner` (tests import `ENDPOINT_FILE` from there) and from `reframe_server.owner`. Each module must import the names (`from reframe.models.queue import API_VERSION`), not use them through the module: `tests/remote/test_shared_queue_real.py:419-427` (`OTHER_API`) and `tests/remote/test_owner_search.py:109` set `API_VERSION = 2` on the server's three modules (`reframe_server.api`, `reframe_server.owner`, `routers.health`) to play another server, and that only works while each module has its own binding and the client keeps its own. Delete the equality test. In the same commit edit 0061 item 2 ("The client's `API_VERSION` is a constant of the core; a test checks that it equals the server's": now one constant) and keep the rule of 0064 item 4 (it names `reframe_server.api.API_VERSION`) in the docstring there.
- Behaviour: unchanged.
- Contracts touched: HTTP: none (the value of `API_VERSION` does not change, so the OpenAPI schema and `GET /api/health` stay the same). Public core API: three names added to `reframe.models.queue`.
- Callers to update: the five definitions above.
- Tests: delete `test_the_client_speaks_the_api_version_of_the_server_of_its_own_version` (4 lines).
- Decision records: 0061 item 2 (its last sentence names the two constants and the equality test, so it needs an edit in the same commit), 0056 item 2, 0064 item 4.
- Size: S; estimated lines: -3 / -4
- Risk: low
- Depends on: none
- Confidence: medium (small gain; do it only together with other server-owner work)
- Verdict: ADJUSTED (0061 item 2 states the duplicated constant and its test, so a decision record has to change with the code; the subprocess tests that patch `API_VERSION` per module are listed above; the five definitions and their line numbers are right)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

### CLI-14: the lost-connection report reads each job's state from the owner or the saved queue (decision-change, low confidence)
- Kind: decision-change
- Where: `cli.py:2232-2257` (`_now`), `2260-2282` (`_report_lost`), `QueueSession.data_dir` (1381, 1504), the `read_saved_queue` import (line 93). Tests: `tests/remote/test_cli_client.py:750-792` (`test_after_a_lost_connection_the_owners_states_are_reported`).
- Now: after the connection is lost, `_now` opens a new connection to the owner, else reads the saved queue (a job that was running or paused there counts as `interrupted`), else uses the command's copy. This is 0061 C4 (b) and 0062 R1 M3: the report is "a fact read from the owner or the saved queue, not a guess". `RemoteQueue._lose` (`remote/queue.py:741-756`) already marks the copy's running and paused jobs `interrupted` and publishes the events.
- Change (only if the decision is dropped): report the copy's state (`session.queue.get`), as the first design did. Delete `_now` and the `data_dir` plumbing, and the `reconnect` use in `_report_lost` (`reconnect` stays: `_stop_here` needs it). About -24 source and -35 test lines.
- What would have to be true: the owner is always on the same machine (`http://127.0.0.1`), so a lost connection is nearly always an owner that died. Then the saved queue gives `interrupted` for running jobs, the same as the copy. The two differ when a job ended `done` just before the loss (the copy still says running, then `interrupted`), and when the owner is alive and cancelled an attached job (the copy says `interrupted`, the owner says `cancelled`). I would keep the decision: the report is where a user decides to retry or not, and the cost is 24 lines. Not counted in the totals.
- Behaviour: changes (the report can say `interrupted` for a job that finished or was cancelled).
- Contracts touched: CLI output after a lost connection.
- Callers to update: `_report_lost`, `QueueSession`, `open_queue`.
- Tests: delete or rewrite `test_after_a_lost_connection_the_owners_states_are_reported`.
- Decision records: 0061 C4 (b), 0062 R1 M3.
- Size: M; estimated lines: -24 / -35 (not counted)
- Risk: medium (a worse report for the user)
- Depends on: none
- Confidence: low
- Verdict: CONFIRMED (a decision-change that names 0061 C4 (b) and 0062 R1 M3 and says honestly that it would keep the decision; line anchors, `RemoteQueue._lose` at 741-756 and the test at 745-792 are right)
- Orchestrator: Tier C (not planned before v1; the reason is in ../README.md).

## Looked at and kept

- `RemoteQueue`'s copy of the queue, its sets (`_seen`, `_awaited`, `_pending`, `_stirred`, `_gone`, `_retries`), `_apply_state`, `_apply_order` and the whole-queue reads: 0061 B2 and B9 (measured on 845 jobs: an add 0.23-0.34 s before, 0.008-0.014 s after), 0062. Complexity 12 in `_apply_state` is the price of that.
- `RemoteQueue.start` in a background task with the refusal kept for the next awaited call (`_pending_starts`, `_start_error`, `_started`, `_settle`) and `_start` / `START_TRIES` in the CLI: 0061 B1 and C1. It exists because `QueueLike.start` is synchronous, like `QueueService.start`; making it async touches more than 150 call sites in tests and the server.
- `RemoteQueue.reorder` has no caller in the CLI, but `QueueLike` lists it (05 §C-17, line 669) and the contract tests run it against both queues.
- `OwnerSearch.run` (complexity 18, 11 returns), `HELD_WAIT`, `START_WAIT`, `server-start.lock`, exit code 75: 0061 item 2 and B7, 0071 (Windows cold start). `find_owner(command, launch, platform, environ)` and `owner_command(executable, frozen, find_spec)` are test seams for fault injection (`tests/remote/test_owner_search.py`).
- `owner._start`'s `popen` closure around `launch_detached` (it needs the exit code, 0061 item 5; the `CREATE_NO_WINDOW` path is Windows code and is checked on the VM, 0070).
- `usable_token`, `_reason` (token redaction), `_NoFrameLog`, `_unhide` (the server's `<data>`, `<config>`, `<cache>`), `_decode` (unknown fields, unreadable events): 0061 B3, B6, B8 and item 3.
- `_StopRequest`, `_stop_here`, `_stop_process`, `QueueSession.use` and `unreachable` (Ctrl+Z): 0061 C4 and the follow-up of 2026-11-01 (`remote.refresh()` before reading states), 0062 R1 M3 (a major finding).
- `CommandJobs` (first end of each job wins), `_Following`, `_follow_jobs`, `_held` and `STOPPED_BY_OTHERS`, `_wait_present`, `_cancel_jobs`, `_answer` and `ADD_WAIT`: 0061 C1, C2, C5, 0064.
- In-process queue, `_LocalPower`, `get_queue`, `--in-process`, and the fall-back to the in-process queue when no owner can be used: 0042 ("that stays as the fall-back": a CLI without `reframe-server` installed), 0017 item 19 (`get_queue` is the test seam; 10 test uses).
- `PowerLike` (two real implementations: `_LocalPower` and `RemotePower`; plus the test fake) and `_Drafts` (two implementations).
- `printable`, `_one_line`, `display_path`, `_text`: 0038 R5-9 and RA-2 (each human line must pass `printable`).
- `read_preset_file` caps and `MAX_PRESET_FILE`: 0038 "The size of `presets import`".
- `WarningPrinter` (`finish`, the 5 s timeout): 0017 item 22.
- `_follow_encoders` (complexity 15) and its first-event cases: 0017 items 10-11 (the exact output is specified).
- `run_tools_fetch`'s pre-checks (build, platform), `_marker_identity` and the "installed before the interrupt" report: 0038 items 7-8 and R5-5 (distinct exit codes 1 and 2; the interrupt report).
- `make_console` width rule for pipes (`DEFAULT_PIPE_WIDTH`), `_configure_stream` and `main`: the Windows and pipe behaviour that tests check (0017 item 24).
- `run_plan` handling of the dry run and of `plan.failed` issues (uncovered lines 1213-1214): 0017 item 6 and 0038 R5-2. It is a documented contract, only untested.
- `EncodeView`, `CountdownView`, `FetchView` (a bar on a terminal, lines otherwise): 0017 item 17, 0038 items 8 and 14. Their `live=` parameter is used only by tests, but it saves nothing worth a change.
- vulture hits in `cli.py` (`STRICT`, `LOOSE`, `REPLACE`, `SKIP`, `LINUX_X64`, `WINDOWS_X64`, `_root`, the `queue_*`, `tools_*`, `presets_*` functions): enum members and typer commands, used by name through typer. The only real hit in this area is `FORWARDED` (CLI-10).
- Test size: `tests/remote/test_cli_client.py` (922 code lines) and `test_shared_queue_real.py` follow the kept code above. `run_encode(..., preset=None, output=None)` is repeated in 38 calls because `preset` and `output` are required keywords; giving them `None` defaults would shorten the calls but not remove lines, so I did not list it.

## Noted by the verifier (not verified)

- `cli.py:3402-3404` (the message when no FFmpeg build is pinned for this computer) lists `PLATFORMS` (`linux-x64, linux-arm64, windows-x64`) as the values of `--platform`, but the option accepts only `linux-x64` and `windows-x64` (`PlatformChoice`), while `tools/ffmpeg.toml` has a `linux-arm64` build. Either the message or the option is out of line; no decision record says which.
- `docs/decisions/0038` item 9 still describes the CLI-side `TaskFailed` log filter and prefix strip as built; when CLI-06 lands, a line in 0038's Consequences should say the CLI part was removed after the core fix (fb895a9).
