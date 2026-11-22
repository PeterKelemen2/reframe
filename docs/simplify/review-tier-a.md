# Review of the Tier A packages (Q-6.1 to Q-6.10)

- Range: `8bf1df6..33839380` on `m10-hardening` (the ten `refactor(Q-6.n)` commits, their merges,
  `817993d`, the `docs(Q-6)` and `docs(status)` commits, and the two `test(Q-2)` commits for
  pytest-xdist).
- Date: 2026-11-16. A read-only review: no code, test or doc was changed.
- Read: `CLAUDE.md`; `docs/simplify/plan.md` (Q-6.1 to Q-6.10, "Rules for every package");
  every finding these packages name in `docs/simplify/areas/*.md` and
  `docs/simplify/cross-cutting.md` (X-01, X-04, X-05, X-06); `decisions-taken.md` D-24 to D-37;
  the diff of every source file in the range and the test diffs that the findings name.
- Ran (old tree = `git archive 8bf1df6` in a scratch folder, run with the same venv and
  `PYTHONPATH` pointing at it):
  - `--help` of every `reframe` command and subcommand, old against new: byte-identical.
  - The bad-value errors of `batch --level`, `presets import --on-conflict`,
    `tools fetch --platform` and `REFRAME_IN_PROCESS=garbage`: same text and exit code 2.
  - `python -m reframe.tools`: same output and exit code.
  - The OpenAPI document (`scripts/export-openapi.py`) old against new: one difference
    (RA-1). `scripts/gen-api.sh --check`: up to date.
  - The JSON Schema of every persisted document model (`DOCUMENT_MODELS`): identical.
  - The validation rule registry (areas, rule names, codes, order) and `AREAS`: identical.
  - Collected test IDs, old against new: the only removed tests are the ones the findings
    delete (CLI-05, CLI-06, VAL-04, CMD-04, MOD-06 item 1); the only added ones are the ones
    the findings ask for (CLI-05, VAL-01, X-01).
  - `vulture` (offline) over `packages`, `testing`, `scripts`, old against new: no new unused
    name. Every `__all__` entry of `reframe`, `reframe_server` and `reframe_testing` resolves.
  - `test_facade_coverage.py` on the tree of merge `0f2adbd` (RA-2).
  - `uv run ruff check`, `ruff format --check`, `mypy`, `mypy --platform win32`: clean.
  - Focused tests (xdist): `tests/command`, `validation`, `queue`, `jobs`, `batch`,
    `capabilities`, `dimensions`, `probe`, `models`, `tools`, `remote`, `analysis`, `presets`,
    `definitions`, `platform`, `preview`, `naming`, `test_cli.py`, `test_service.py`,
    `test_tasks.py`, `test_settings.py`, `test_mediatask.py`, `test_applog.py`, and all of
    `packages/reframe-server/tests`: 7,332 passed, 3 skipped (two benchmark skips under xdist,
    one `libfdk_aac` skip). 91 syrupy snapshots (the 73 plan snapshots among them) passed
    without an update. `test_template.py`, `tests/batch/test_rules.py` and
    `tests/jobs/test_cli_batch.py` also pass alone with `-n 0`.

Result: no blocker, no major, 3 minor findings.

## Findings

### RA-1 (minor) — Q-6.4: the OpenAPI description of `Condition.field` changed

- File and symbol: `packages/reframe/src/reframe/definitions/models.py`, `Condition.field`;
  `frontend/src/api/schema.d.ts`.
- What: NDP-03 item 2 says "Contracts touched: none", but moving the alias comment into a field
  docstring adds a `description` to `Condition.field` in the OpenAPI document, and the
  generated `schema.d.ts` changed. No field, type or route changed.
- Evidence: the only difference between the old and new OpenAPI documents is
  `"description": "A rule field such as ``rate_control``, or ``option:<key>`` for another
  option of the same\nencoder."` on `Condition.field`. Commit `a02f97c` and D-28 record it, but
  the finding NDP-03 does not.
- Fix: nothing in the code. Add an implementation note under NDP-03 in
  `docs/simplify/areas/naming-definitions.md` (as Q-6.2 did under NDP-05), so the finding
  shows the description change.

### RA-2 (minor) — Q-6.6 (also Q-6.7, Q-6.9): rows of the plan's "Not exposed" table

- File and symbol: `docs/plan/06-web-app.md`, the "Not exposed" table; `BatchService.definitions`
  (BAT-10 item 3).
- What: (a) commit `624b6c2` removed `BatchService.definitions` but left the
  `batch.definitions` row in the table. `test_facade_coverage.py` fails on that commit and on
  merge `0f2adbd`. The row was removed by a separate commit, `817993d`, after the merged-wave
  run failed. (b) Q-6.6, Q-6.7 and Q-6.9 together removed four rows of a plan file
  (`batch.definitions`, `power.closed`, `power.countdown`, `jobs.detection_wait`). No
  decision record was written. D-34 accepts this as bookkeeping and says the Q-6.11 record
  (X-07) will name the rows.
- Evidence: `pytest packages/reframe-server/tests/test_facade_coverage.py` on the tree of
  `0f2adbd` gives
  `FAILED ...::test_the_not_exposed_list_names_public_members_that_no_route_reaches` ("Left
  contains one more item: 'batch.definitions'"). `git show 817993d` edits only that row.
  BAT-10 item 3 does not name the plan row, whereas QJ-05 does ("Same commit:
  docs/plan/06-web-app.md:218").
- Fix: nothing to undo. Make sure the Q-6.11 decision record names all four removed rows, not
  only the two that D-34 names. In the brief for the Tier B packages, add: "a package that
  removes a public facade member edits the Not exposed table in the same commit and runs
  `test_facade_coverage.py`". The plan's test notes already ask for this run, but the brief
  template does not.

### RA-3 (minor) — Q-6.9: stale wording "private store in memory" after QJ-11

- File and symbol: `packages/reframe/src/reframe/queue/service.py`, docstring of
  `QueueService._ensure_open` ("A process that cannot take the lock keeps its jobs in a private
  store in memory"); the comment in `packages/reframe/tests/queue/test_queue.py`,
  `test_a_store_that_cannot_be_written` ("the queue goes on in a private store in memory").
- What: QJ-11 removed the in-memory SQLite store (`QueueStore.use_memory`, `memory`). A process
  without the lock now sets `read_only`: the store writes nothing, and the jobs live only in
  `QueueService._jobs`. The two texts still describe the removed store. The store's own module
  docstring was updated ("its jobs in memory only (:attr:`QueueStore.read_only`)").
- Evidence: `git show 1450128 -- packages/reframe/src/reframe/queue/store.py` (the memory
  store is gone); `queue/service.py:595,607` set `self._store.read_only = True`. The
  docstring at about line 585 was not changed.
- Fix: reword the docstring to "keeps its jobs in memory only (the store writes nothing)", and
  the test comment the same way. Decision 0016 line 382 uses the same words as history; leave
  it unchanged.

## What was checked, in order

1. Q-6.3 CLI: the full `cli.py` diff; `_say` and `_warn` against the old print calls
   (every old site that lacked `printable` prints static text, numbers or text that was already
   made printable, `preset_rows` included); `_write_json`/`_jsonable` against the three old
   writers; `_rows` widths; `_not_usable`; `_probe_failed` exit codes (`EXIT_FAILED` = 1,
   `EXIT_NO_TOOL` = 4, the same numbers as the removed aliases); `_media_files`, `_preset`,
   `_labels`; the `_show_batch` and `_queue_batch` split (the dry-run line, the JSON and the
   exit codes); the `_owner` context manager (it still closes the owner with `detach=True`, also
   on cancel); `read_preset_file` with `open_regular` (the same three messages and exit codes; a
   test for "is a folder" exists); the `Literal` options; `ACTIVE`/`ENDED` in the CLI and in
   `remote/queue.py`; the removed `TaskFailed` filter. Help and error output compared with the
   old tree: identical. No finding.
2. Q-6.9 queue, jobs and tasks: `Outcome.stop_reason` (`_stopped` still maps the reason to the
   state and error); `JobRunner(resumed=)` required; `ReframeClosedError` in `reframe.errors`
   (`except` order in `CapabilityService._detect` kept); QJ-11 `read_only` (no new warning: the
   `queue.job_not_saved` condition and `_open_for_write` behave as with the memory store);
   `TaskManager.cancel` and `CancelToken.cancel` without a reason (nothing reads it; the server's
   preview route and the CLI fetch interrupt still cancel); the shared protocols. The queue fault
   and in-place stop tests pass. Finding RA-3.
3. Q-6.5 validation: VAL-01 `_for_template` (no old rule wrote `target="job"` explicitly; every
   old template rule passed `ctx.target`); VAL-05 `encoder_issues(fix_ops=)` labels; VAL-08
   `remove_param_fix` and `remove_option_fix` against the dry run's old fixes; VAL-04 `AREAS`
   and the rule registry (identical). No finding.
4. Q-6.10 command and capabilities: `job_geometry`/`job_source_geometry` against the five old
   copies (builder, preview, batch, validation, server route); `encoder_and_pix_fmt` (the same
   `PlanError` texts as the builder and the preview); `HardwareSetup.resolve` and the `format=`
   tail; `EXTERNAL_FORMATS`, `_SAME_FORMAT.get(codec, codec)` (`recode` is true only for text
   external files, whose codecs are all in the old map), `FORMAT_ENCODERS` as an identity map;
   `HdrFormat.label` (four maps); `fixup_edit` with `OutputTrack`; `OTHER_TAGS` against
   `TAG_KEYS`; `parse_encoders` membership; the capability cache key losing `filter_tests`
   (announced in CMD-02 and D-37); `hardware_test_argv` without `DefinitionError` (the 10-bit
   test runs only when the definition has a 10-bit format, CMD-04 verdict). No finding.
5. Q-6.6 batch: `resolve` merged with `resolve_with_tracks`; `draft_from_preset` builds the
   `TrackDraft` from the resolution (equal for a preset without an override, BAT-08);
   `lint_defaults(used=)`; `language_label` and `language_code` replaced by the same library
   calls; `flag_extra_role` (the same role order); `ForeignAudio`. The anime snapshot and the
   batch tests pass. Finding RA-2.
6. Q-6.7 tools and dead members: `ToolsService._discover` through `discover_tools` (same
   defaults, thread and TaskGroup); the removed `RecursionError` branches (depth is checked first
   in both places); `presets.diff` with `json_equal`; `backup()` without `label`. Finding RA-2
   (rows `power.closed`, `power.countdown`).
7. Q-6.8 probe: `stat_regular` (the same errors for the prober and `_check_file`);
   `is_language_tag` and `LANGUAGE_TAG_PATTERN` against the three old regexes and the
   `TypeAdapter` check; `start_probe_folder` removed (D-31 keeps the event test). No finding.
8. Q-6.4 definitions and analysis: `run_scan` (the same argv, environment and `TaskFailed`
   texts, `tool.name` is `ffmpeg`/`ffprobe`); the linter moved to `reframe_testing` (nothing in
   the shipped package or the sidecar spec imports it); the loader raises for a missing TOML file
   (announced in NDP-08); `title_index` and `tail=` removed. Finding RA-1.
9. Q-6.1 and Q-6.2 tests: test IDs, old against new (only the deletions and additions the
   findings name); the new `reframe_testing` modules; the plugin's `app` fixture (local fixtures
   still override it). No finding.
10. `test(Q-2)` commits: `-n auto` in `addopts`, the benchmark skip in xdist workers, the CI
    benchmark job with `-n 0`, the surrogate escape in `pytest_runtest_logreport`. Nothing
    broken.
11. `CLAUDE.md` rules over the whole diff: the core imports no server or UI code; every new
    subprocess goes through `reframe.tools.run*` (`run_scan` uses `run_streaming`); no new
    exception for an expected failure (`filter_test_argv`'s `ValueError` and the
    `hardware_test_argv` `KeyError` are invariants of the shipped definitions, D-37 and CMD-04);
    the command builder does no I/O; no persisted schema changed (no migration needed); no step
    ID or history in an added code comment or docstring. The decision-record edits (0031, 0038)
    are the ones the findings ask for. Finding RA-2 for the plan table.
12. Skipped or partial findings: each one has a note in a commit message, in `docs/status.md` or
    under its finding (X-04's two loaders, NDP-05's `SeasonFs` and `app` copies, the CLI-12
    `test_recheck.py` call, NDP-03 item 10, BAT-09 item 9 (outside the package), BAT-10 item 4
    (rejected in verify), QJ-05 item 4 (Tier C), CMD-06 `render_tag` (rejected), PRB-04's kept
    test). The optional `ToolLocation.env_var` part of TP-02 is noted only in D-35, and it is
    optional. No finding.
13. Dead code: removed names searched in `packages`, `testing`, `scripts`, `frontend/src`,
    `docs/plan` and `docs/status.md`. The remaining hits are history (status notes, breakdowns,
    trim reports, decision records) or a different symbol with the same name (the frontend's
    own `OVERRIDE_FIELDS`, the test-local `supported_options` helper). Vulture shows no new
    unused name, and every `__all__` entry resolves. No finding.
