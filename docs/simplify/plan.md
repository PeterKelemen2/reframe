# Simplification: implementation plan (Q-6)

This plan groups the Tier A and Tier B findings of the audit into work packages. Each package is
one implementation task for one agent, and one step `Q-6.n` in
[09-quality-and-release.md](../plan/09-quality-and-release.md#q-6-simplification). The findings
themselves are in [areas/](areas/) and [cross-cutting.md](cross-cutting.md); the full table is in
[README.md](README.md).

Packages Q-6.1 to Q-6.10 hold the Tier A findings (do before v1). Packages Q-6.11 to Q-6.19 hold
the Tier B findings (worth doing if there is time). Tier C is not planned.

## Rules for every package

- Line numbers in the findings refer to commit `85d9dcb`. Earlier packages move them. Find each
  place by the symbol name in the "Where" bullet, then check that the code still matches the
  "Now" bullet. If it does not match (an earlier package changed it), make the change against the
  new code when the intent is still clear; otherwise skip that finding and say so in the commit
  message and in `docs/status.md`.
- Make only the changes the findings describe. Do not investigate again, and do not add new
  simplifications. Something new goes into the step's row in `docs/status.md` as a note.
- A finding whose "Verdict" is ADJUSTED: the corrected bullets are the ones to follow. Read the
  "Orchestrator:" line under each finding: it can narrow the change (for example "items 1-3 only").
- Comments and docstrings follow the `code-comments` skill.
- A package that changes a decision (marked "decision record" below) writes a new record in
  `docs/decisions/` (the next free number at that time) and edits the plan files it names, in the
  same commit (`CLAUDE.md`).
- **Done when** (every package, in addition to its own items): `uv run ruff check`,
  `uv run ruff format --check`, `uv run mypy`, `uv run mypy --platform win32` and
  `uv run pytest -m "not needs_gpu"` pass; the tests each finding names as the guard of unchanged
  behaviour still pass; the package's own items below pass; `git diff --stat` shows a net line
  change near the estimate (a big miss is explained in the commit message); `docs/status.md`
  has the step marked done with a one-line note. A package that touches `packages/reframe-server`
  or a model in an API response also runs `scripts/gen-api.sh --check`. A package that touches
  `frontend/` also runs the frontend commands of `CLAUDE.md` (`npm run lint`, `fmt:check`,
  `typecheck`, `npm test`).
- Commit each package as one conventional commit with the step ID as scope, for example
  `refactor(Q-6.3): one print helper in the CLI`. Never push.

## How to run the tests (notes from the Q-6 run)

The Q-6 packages were made over more than one session. These notes hold for whoever continues.

- **Full suite:** `uv run pytest -m "not needs_gpu"`. It runs in parallel (pytest-xdist
  `-n auto` is in `addopts`, about 6 minutes on 12 cores; one process, `-n 0`, takes about 35;
  [decision 0084](../decisions/0084-parallel-test-runs-with-pytest-xdist.md)). The `benchmark`
  tests skip under xdist; run them with `uv run pytest -m benchmark -n 0`.
- **Who runs what:** an implementation agent runs the focused tests of its package (the folders
  its findings and its Done-when name) and the four static checks (`ruff check`,
  `ruff format --check`, `mypy`, `mypy --platform win32`), not the full suite. The orchestrator
  runs the full suite once on `m10-hardening` after each wave is merged. A failure there is
  traced to its package (`git bisect` over the merge commits if needed). A package that removes
  a public member of a service also runs `packages/reframe-server/tests/test_facade_coverage.py`:
  the "Not exposed" table of `docs/plan/06-web-app.md` may only name members that exist.
- **Known flaky tests** (fail when the machine is loaded, pass alone; rerun alone first):
  `tests/remote/test_cli_client.py::test_a_client_drafts_as_the_in_process_draft[default]`,
  `tests/platform/test_sleep_dbus.py::test_connection_stays_open_for_several_calls_and_closes`,
  and a `ResourceWarning` error in the setup or teardown of
  `packages/reframe-server/tests/test_subtitles.py::test_a_sup_file_is_a_bitmap_counted_in_display_sets`
  (an unclosed transport left by an earlier test). See `decisions-taken.md` D-25 and D-32.
- **Agent worktrees** (`isolation: "worktree"`) are created from `main`, not `m10-hardening`:
  each agent first runs `git reset --hard <SHA of the last merge>` and checks `git rev-parse HEAD`
  (D-24). The worktree has no `frontend/node_modules`; for `scripts/gen-api.sh --check` or the
  frontend commands, symlink the main checkout's `frontend/node_modules` and remove the link
  before the commit. Expected skips in a worktree: the frozen-sidecar tests and the
  `node_modules` tests. The frozen-sidecar tests run only in the main checkout, where
  `desktop/src-tauri/resources/sidecar` holds a build (a build from older code still passes
  them).
- **Progress** is in `docs/status.md` (rows Q-6.1 to Q-6.19) and in the "Implementation (Q-6)"
  part of `decisions-taken.md`.

## Work packages

Estimated lines are code lines (without comments and blanks) removed net, source / tests.

### Tier A

#### Q-6.1 Test module loaders (X-04)
- Findings: X-04 (BAT-06, VAL-02).
- Files: `packages/reframe/tests/batch/*.py`, `packages/reframe/tests/validation/*.py`,
  `packages/reframe/tests/jobs/test_cli_batch.py`; maybe new `__init__.py` files there.
- Order: try the `__init__.py` + relative import way in `tests/validation/`, then in
  `tests/batch/`; use BAT-06's move into `reframe_testing` only if the first way fails.
- Depends on: none.
- Done when: the common items; `uv run pytest packages/reframe/tests/batch packages/reframe/tests/validation`
  and one file of each folder run alone (`uv run pytest packages/reframe/tests/validation/test_template.py`)
  pass; the test count of both folders is unchanged (`--collect-only -q | tail -1` before and after).
- Estimate: 0 / -495.

#### Q-6.2 Shared test helpers
- Findings: MOD-08 (`drain`, `nested`), NDP-05 (`app` fixture, fake file systems), PRB-07 (EBML
  test builders), SRV-05 (server and core wait loops), TP-04 (fake D-Bus servers, fd and socket
  helpers).
- Files: tests only, plus `testing/reframe_testing/` (new shared helpers):
  `tests/presets/test_store.py`, `tests/test_settings.py`, `tests/test_service.py`,
  `tests/capabilities/test_service.py`, `tests/platform/test_power.py`, `tests/platform/test_sleep_*.py`,
  `tests/analysis/test_analysis_facade.py`, `tests/analysis/test_analysis_ffmpeg.py`,
  `tests/preview/test_facade.py`, `tests/naming/` (fake file systems), `tests/probe/test_matroska.py`,
  `tests/metadata/header/corpus.py`, `tests/metadata/test_metadata_*.py`, `packages/reframe-server/tests/*`.
- Order: MOD-08, NDP-05, SRV-05, PRB-07, TP-04 (the last two keep different defaults as
  parameters, see their verdicts).
- Depends on: none.
- Done when: the common items; the test count of `packages/` is unchanged; TP-04: the fake-bus
  tests pass and `tests/platform/test_sleep_real.py` was run once on this machine (it skips
  without a bus); the new shared module imports on Windows (`uv run mypy --platform win32`).
- Estimate: 0 / -290.

#### Q-6.3 CLI
- Findings: CLI-01, CLI-02, CLI-04, CLI-05, CLI-06, CLI-07, CLI-08, CLI-10, CLI-11, CLI-12.
- Files: `packages/reframe/src/reframe/cli.py`, `remote/queue.py`, `queue/service.py` and
  `queue/__init__.py` (CLI-10: `ACTIVE`), `textfile.py` (CLI-08 uses it, no change expected);
  tests `tests/test_cli.py`, `tests/jobs/conftest.py`, `tests/jobs/test_cli_*.py`,
  `tests/remote/*`, `tests/tools/test_fetch_cli.py`, `tests/conftest.py`.
- Order: CLI-01 first (it makes `_say` and `_warn`), then CLI-02 and CLI-11, then the rest; CLI-12
  last.
- Depends on: Q-6.1 (it edits `tests/jobs/test_cli_batch.py`).
- Done when: the common items; every CLI test that compares output lines passes unchanged
  (CLI-01 and CLI-02 are byte for byte); `reframe encode --help`, `reframe batch --help`,
  `reframe tools fetch --help` and `reframe queue --help` give the same text as before (compare
  with the output of the previous commit); the new `invoke` test of CLI-05 guards the 0061 C12
  usage error. Also add a line to 0038's Consequences that the CLI-side `TaskFailed` handling was
  removed (CLI-06; verifier note).
- Estimate: -195 / -62.

#### Q-6.4 Definitions and analysis
- Findings: NDP-01, NDP-02, NDP-03, NDP-06, NDP-08 (without `_lint_chain`).
- Files: `packages/reframe/src/reframe/definitions/__init__.py`, `definitions/models.py`,
  `definitions/lint.py` → `testing/reframe_testing/definitions_lint.py`, `definitions/loader.py`,
  `analysis/common.py`, `analysis/bitrate.py`, `analysis/loudness.py`, `analysis/subtitles.py`,
  `capabilities/hwtest.py` and `detect.py` (NDP-03 item 4), `tests/definitions/*`,
  `tests/analysis/test_analysis_tasks.py`, `docs/status.md`.
- Order: NDP-01, NDP-03, NDP-02 (move the linter), NDP-08 in its new place, NDP-06.
- Depends on: none.
- Done when: the common items; `tests/definitions/test_lint.py` runs against the moved linter
  and finds the same problems in a bad definition as before; `python -c "import reframe.definitions"`
  no longer imports the linter (the shipped package does not contain it).
- Estimate: -154 / -5; 669 more lines leave the shipped package.

#### Q-6.5 Validation
- Findings: VAL-01, VAL-04, VAL-05, VAL-08.
- Files: `packages/reframe/src/reframe/validation/*` (`__init__.py`, `common.py`, `context.py`,
  `video.py`, `encoder.py`, `dryrun.py`, `inplace.py`, `metadata.py`, `tracks.py`),
  `capabilities/issues.py` (VAL-05), `tests/validation/*`, `tests/capabilities/test_issues.py`.
- Order: VAL-04, VAL-01, VAL-08, VAL-05.
- Depends on: Q-6.1 (same test folder).
- Done when: the common items; `tests/validation/test_template.py`,
  `tests/validation/test_custom_params_rules.py` and the agreement tests
  (`test_command_agreement.py`, `test_audio_agreement.py`) pass; every fix `target` the frontend
  reads is the same (VAL-01: job fixes `"job"`, template fixes `"template"`, explicit `"settings"`).
- Estimate: -207 / -30.

#### Q-6.6 Batch
- Findings: BAT-07, BAT-08, BAT-09 (items 1-4 and 6-8), BAT-10 (without item 4), BAT-11.
- Files: `packages/reframe/src/reframe/batch/*` (`lint.py`, `resolve.py`, `rules.py`,
  `explain.py`, `service.py`, `descriptors.py`, `grouping.py`, `__init__.py`), `jobs.py`
  (BAT-08, about 4 lines), `tests/batch/*`, `tests/probe/test_roles_empty_subtitles.py:72` (BAT-11).
- Order: BAT-08, BAT-07, BAT-10, BAT-11, BAT-09.
- Depends on: Q-6.1.
- Done when: the common items; `tests/batch/test_anime_season.py` (snapshot),
  `tests/batch/test_batch_properties.py`, `tests/jobs/test_cli_batch.py` pass unchanged.
- Estimate: -134 / -14.

#### Q-6.7 Tools discovery and small dead members
- Findings: TP-02, TP-07, MOD-06 (without item 3).
- Files: `packages/reframe/src/reframe/tools/discovery.py`, `tools/__init__.py`,
  `tools/__main__.py`, `tools/versions.py`, `applog.py`, `platform/power.py`, `service.py`
  (`ToolsService._discover`), `models/events.py`, `models/__init__.py`, `presets/builtin.py`,
  `settings.py` (`SettingsStore.save`, the `RecursionError` branch of item 6),
  `scripts/bundle-tools.py`, tests in `tests/tools/`, `test_applog.py`, `test_settings.py`,
  `tests/presets/`, `tests/models/`.
- Order: TP-02, TP-07, MOD-06.
- Depends on: Q-6.2 (`test_settings.py`), Q-6.3 (`tests/tools/test_fetch_cli.py`).
- Done when: the common items; `uv run python -m reframe.tools` prints the same discovery result
  as before; `uv run --no-project python scripts/bundle-tools.py --help` still runs.
- Estimate: -85 / -53.

#### Q-6.8 Probe
- Findings: PRB-04, PRB-09, PRB-10, PRB-13.
- Files: `packages/reframe/src/reframe/probe/folder.py`, `probe/__init__.py`, `probe/prober.py`,
  `probe/parse.py`, `models/base.py`, `languages.py`, `service.py` (`_check_file`),
  `tests/probe/*` (`conftest.py`, `test_folder.py`, `test_prober.py`, `test_sampling*.py`),
  maybe `testing/reframe_testing/fake_tools.py`.
- Order: PRB-04, PRB-13, PRB-09, PRB-10.
- Depends on: Q-6.2 (`tests/probe/test_matroska.py`).
- Done when: the common items; the JSON Schema snapshot (`tests/models/__snapshots__/test_schema.ambr`)
  does not change (PRB-10); `tests/probe/test_folder.py::test_folder_task_events` passes.
- Estimate: -40 / -65.

#### Q-6.9 Queue, jobs and tasks
- Findings: QJ-04, QJ-05 (items 1-3 and the protocol member; not `SourceService.store`), QJ-06,
  QJ-08, QJ-09, QJ-11, TP-08.
- Files: `packages/reframe/src/reframe/queue/*` (`runner.py`, `service.py`, `store.py`,
  `errors.py`), `jobs.py`, `mediatask.py`, `tasks.py`, new `errors.py` (QJ-09),
  `capabilities/service.py`, `service.py`, `probe/prober.py`, `tools/runner.py`, `cli.py`
  (TP-08, one call), `packages/reframe-server/src/reframe_server/routers/preview.py` (TP-08, one
  argument); tests `tests/queue/*`, `tests/jobs/*`, `test_mediatask.py`, `tests/analysis/test_analysis_tasks.py`,
  `tests/preview/helpers.py`, `tests/tools/test_runner.py`, `tests/tools/test_fetch.py`,
  `tests/capabilities/test_detect.py`.
- Order: QJ-04, QJ-05, QJ-06, QJ-09, QJ-11, QJ-08, TP-08.
- Depends on: Q-6.3 (`cli.py`), Q-6.6 (`jobs.py`), Q-6.7 (`service.py`), Q-6.8 (`service.py`,
  `probe/prober.py`).
- Done when: the common items; `scripts/gen-api.sh --check` (the server is touched; no schema
  change expected); the crash-recovery and cancel tests of the queue (`tests/queue/test_faults.py`,
  `tests/queue/test_in_place_stop.py`) pass; `uv run mypy --platform win32`.
- Estimate: -106 / -57.

#### Q-6.10 Command, capabilities and shared tables
- Findings: X-01 (CMD-01, SRV-04, VAL-11), X-05 (CMD-13, BAT-17), X-06 (CMD-03, VAL-07 subtitle
  part), CMD-02 (keep `closest_available`, `definitions`, `detecting`), CMD-04, CMD-05, CMD-06
  (without `render_tag`).
- Files: `packages/reframe/src/reframe/dimensions.py`, `command/builder.py`, `command/video.py`,
  `command/subtitles.py`, `command/metadata.py`, `command/header.py`, `command/audio.py`,
  `capabilities/*` (`service.py`, `detect.py`, `hwtest.py`, `parse.py`, `cache.py`, `__init__.py`),
  `preview/graph.py`, `validation/context.py`, `validation/tracks.py`, `validation/filters.py`,
  `batch/resolve.py`, `batch/grouping.py`, `cli.py` (`_HDR_NAMES`, `TIMES`), `models/` (`HdrFormat.label`),
  `packages/reframe-server/src/reframe_server/routers/jobs.py`; tests `tests/command/*`,
  `tests/capabilities/*`, `tests/dimensions/*`, `tests/test_cli.py:28`.
- Order: X-01, CMD-04, CMD-06, X-06, X-05, CMD-05, CMD-02.
- Depends on: Q-6.3, Q-6.5, Q-6.6, Q-6.9 (shared files).
- Done when: the common items; the 73 plan snapshots (`tests/command/test_snapshots.py`) pass
  without an update; `tests/dimensions/test_properties.py` passes; `scripts/gen-api.sh --check`
  shows no schema change; the `needs_ffmpeg` command tests pass with the pinned FFmpeg.
- Estimate: -191 / -39.

### Tier B

#### Q-6.11 Settings and preset stores
- Findings: X-07 (MOD-02, SRV-03), MOD-01, MOD-03, MOD-05. **Decision record** (X-07: notes on
  0015 §2 and 0050 item 10; plan `06-web-app.md` "Not exposed" rows, `docs/status.md:66`).
- Files: `packages/reframe/src/reframe/settings.py`, `presets/store.py`,
  `service.py` (`PresetService` and the other facade members), `models/__init__.py`, `models/migrations.py`; tests
  `tests/test_settings.py`, `tests/presets/test_store.py`, `tests/test_service_settings.py`,
  `tests/models/test_models.py`, `packages/reframe-server/tests/test_queue.py`,
  `packages/reframe-server/tests/test_facade_coverage.py`.
- Order: X-07, MOD-05 (the test fixture must warm `builtin_presets()` before it swaps the
  registry), MOD-01 (`parse_document` without the `RecursionError` branch, which Q-6.7 removed),
  MOD-03.
- Depends on: Q-6.7.
- Done when: the common items; every damaged, newer and too-deep settings and presets test passes
  (about 100 tests in the three files); the warning codes are unchanged; MOD-01's changed
  `detail` texts are listed in the commit message.
- Estimate: -172 / -110.

#### Q-6.12 Windows-only paths
- Findings: X-02 (MOD-04, QJ-02), TP-14, TP-15.
- Files: new `packages/reframe/src/reframe/fsretry.py`, `settings.py`, `queue/files.py`,
  `platform/sleep.py`, `platform/dbus.py`, `platform/childproc.py`; tests `tests/test_settings.py`,
  `tests/queue/test_units.py` and the other tests that patch `queue.files`, `tests/presets/test_store.py`, `tests/platform/test_sleep_backends.py`,
  `packages/reframe-server/tests/test_owner.py`.
- Order: X-02, TP-15, TP-14.
- Depends on: Q-6.11 (`settings.py`), Q-6.17 (`platform/`).
- Done when: the common items; **on the Windows test VM** (the VM of decision 0070): `uv run pytest packages/reframe/tests/test_settings.py packages/reframe/tests/queue packages/reframe/tests/presets packages/reframe/tests/platform packages/reframe-server/tests/test_owner.py`
  passes, and `powercfg /requests` shows Reframe's request while a job runs in the desktop app
  (TP-14).
- Estimate: -61 / -30.

#### Q-6.13 Probe and metadata
- Findings: X-08 (PRB-06, BAT-09 item 5), X-09 (PRB-11, MOD-07 (b)), PRB-02, PRB-03 (IDs,
  `read_exactly`, `segment_pos` only), PRB-08, PRB-12, PRB-14.
- Files: `packages/reframe/src/reframe/probe/*` (`cache.py`, `parse.py`, `prober.py`,
  `matroska.py`, `sampling.py`, `names.py`, `__init__.py`), `metadata/*` (`__init__.py`,
  `ebml.py`, `layout.py`, `header.py`), `models/media.py`, `batch/descriptors.py`,
  `batch/rules.py`, `batch/resolve.py`, `batch/metadata.py`, `textfile.py`, `chapters.py`,
  `analysis/subtitlefile.py`, `docs/plan/05-core.md:115`; tests `tests/probe/*` (and the
  snapshot `tests/probe/__snapshots__/test_snapshots.ambr`), `tests/metadata/*`, `tests/batch/*`,
  `tests/jobs/test_service.py`, `tests/analysis/test_subtitlefile.py`.
- Order: PRB-02, X-09, PRB-12, PRB-03, PRB-14, PRB-08, X-08.
- Depends on: Q-6.6, Q-6.8.
- Done when: the common items; the probe snapshot diff shows only the 61 `probe_hash` values
  (X-09); the header writer's torn-write tests (`tests/metadata/test_metadata_edit_real.py`,
  `tests/metadata/header/`) pass unchanged (PRB-03 touches `header._read_at`); a test covers
  X-08's edge case (an invalid `language_ietf` with a valid `language` on a video stream).
- Estimate: -160 / -49.

#### Q-6.14 Folder probe, language list, server leftovers
- Findings: SRV-01, SRV-02, SRV-08. **Decision record** (SRV-01: C-3's folder probe is replaced
  by `probe_many`; plan `05-core.md` C-3 and `06-web-app.md` row `sources.probe_folder`;
  SRV-02: supersedes 0071 item 2 and its Consequences bullet).
- Files: `packages/reframe/src/reframe/service.py`, `probe/folder.py`, `probe/__init__.py`,
  `packages/reframe-server/src/reframe_server/routers/languages.py`, `routers/sources.py`,
  `routers/fs.py`, the server's other files SRV-08 names, the sidecar's PyInstaller spec `desktop/sidecar/sidecar.spec` if it names the file (SRV-02), `docs/status.md:72,164`; tests `tests/probe/test_folder.py`, `tests/probe/test_live.py`,
  `tests/probe/test_sampling.py`, `tests/test_service.py`, `packages/reframe-server/tests/test_languages.py`,
  `test_frozen_sidecar.py`, `test_sources.py`, `test_tasks.py`, and the frontend test whose
  expected text SRV-01's verdict names.
- Order: SRV-08, SRV-02, SRV-01.
- Depends on: Q-6.8 (PRB-04 first), Q-6.11 (`service.py`).
- Done when: the common items; `scripts/gen-api.sh --check`; the frontend commands; the jail
  tests (`packages/reframe-server/tests/test_jail_sweep.py`, `test_security*.py`) pass (SRV-08
  edits `_jail`); `GET /api/languages` returns the same bytes and ETag as before (SRV-02); a
  cancelled probe task kills every ffprobe and starts none after the cancel (SRV-01's ported tests).
- Estimate: -201 / -223.

#### Q-6.15 Batch API and the draft path
- Findings: X-03 (CLI-03, QJ-03), BAT-01, BAT-02, BAT-03, BAT-12. **Decision record** (amends
  0040 §8 for `resolve_group` and `merge_template`, and 0040 R1-4 / 0031 §6 for the
  `container_codecs` mechanism; plan `04-batch-mode.md` "Core API", `05-core.md:538`,
  `docs/status.md:69`).
- Files: `packages/reframe/src/reframe/batch/*` (`resolve.py`, `derive.py`, `draft.py` (deleted),
  `explain.py`, `lint.py`, `rules.py`, `service.py`, `__init__.py`), `jobs.py`, `cli.py`
  (`OwnerJobs.draft`), `validation/__init__.py`; tests `tests/batch/*`, `tests/jobs/test_service.py`,
  `tests/jobs/test_cli_file_identity.py`, `tests/remote/*`.
- Order: X-03, BAT-03, BAT-01, BAT-02, BAT-12.
- Depends on: Q-6.6, Q-6.13 (`batch/`), Q-6.9 (`jobs.py`).
- Done when: the common items; `tests/jobs/test_service.py:526` (`jobs.explain(file, webm)`) and
  `tests/batch/test_rules.py:437-456` pass (BAT-12: one issue per problem); the client-mode tests
  in `tests/remote/` pass; the frontend comment at `frontend/src/components/batch/clipboard.ts:27`
  is reworded if it names a removed symbol (then the frontend commands run).
- Estimate: -160 / -52.

#### Q-6.16 Validation rules
- Findings: VAL-03, VAL-06, VAL-07 (HDR predicate part), VAL-09, VAL-12 (without item 2).
  **Decision record** (VAL-06: amends 0014 follow-up item 3, the code `container.unknown`).
- Files: `packages/reframe/src/reframe/validation/*`, `command/builder.py` and `queue/runner.py`
  (VAL-06, cross-area guards), `queue/verify.py`; tests `tests/validation/*`,
  `tests/command/test_builder.py`, `tests/queue/test_units.py`.
- Order: VAL-12, VAL-09, VAL-07, VAL-03, VAL-06.
- Depends on: Q-6.5, Q-6.10.
- Done when: the common items; `uv run pytest packages/reframe/tests/command packages/reframe/tests/queue packages/reframe/tests/validation`;
  `tests/validation/test_template.py::test_every_template_rule_has_a_positive_case` with the two
  new positive cases (VAL-03); issue order for templates unchanged (compare once).
- Estimate: -166 / -19.

#### Q-6.17 Tool runner and platform
- Findings: TP-03, TP-06, TP-09.
- Files: `packages/reframe/src/reframe/tools/runner.py`, `platform/dbus.py`, `platform/sleep.py`,
  `platform/notify.py` (deleted), `platform/__init__.py`, `queue/whendone.py`,
  `validation/dryrun.py` (TP-03 caller), `docs/plan/05-core.md:67` (the `run_streaming` sketch),
  `docs/status.md:71`; tests `tests/tools/test_runner.py`, `tests/platform/test_sleep_*.py`,
  `tests/platform/test_notify.py`, `tests/queue/test_when_done.py`.
- Order: TP-09, TP-03, TP-06.
- Depends on: Q-6.2 (TP-04's shared fake bus), Q-6.9 (`tools/runner.py`).
- Done when: the common items; `tests/platform/test_sleep_real.py` run once on this machine
  (KDE session bus); the commit message names the little-endian narrowing (TP-06).
- Estimate: -69 / -92.

#### Q-6.18 Task manager and capability service
- Findings: QJ-01, QJ-10, CMD-07.
- Files: `packages/reframe/src/reframe/tasks.py`, `capabilities/service.py`, `service.py`
  (`tool_usable`), `queue/runner.py`, `mediatask.py`, `preview/clip.py`, `cli.py`,
  `validation/dryrun.py`; tests `tests/test_tasks.py`, `tests/capabilities/test_service.py`,
  `tests/test_service.py`, `packages/reframe-server/tests/test_tasks.py`, `test_app.py`.
- Order: QJ-10, CMD-07, QJ-01.
- Depends on: Q-6.14 (the `tasks.limit("probe_folder")` assert that SRV-01 deletes), Q-6.10
  (`capabilities/service.py`).
- Done when: the common items; `tests/test_tasks.py::test_queued_tasks_start_in_order` and
  `test_cancel_slot_handover_race` pass; the four server tests get `result_json=lambda value: value`.
- Estimate: -68 / -94.

#### Q-6.19 Definitions fields
- Findings: NDP-04, NDP-11.
- Files: `packages/reframe/src/reframe/definitions/models.py`,
  `definitions/data/video_encoders.toml`, `definitions/data/containers.toml`, the moved linter in
  `testing/reframe_testing/definitions_lint.py`, `capabilities/detect.py`, `capabilities/cache.py`;
  `frontend/src/api/schema.d.ts` (regenerated), `frontend/src/components/tracks/testing.ts`; tests
  `tests/definitions/*` (`test_contract.py:32,44`), `tests/capabilities/test_hwtest.py`.
- Order: NDP-11, NDP-04.
- Depends on: Q-6.4 (the linter's new place), Q-6.10 (`capabilities/`).
- Done when: the common items; `scripts/gen-api.sh` run and its `--check` passes; the frontend
  commands pass; the capability cache key changes once (expected: one re-detection).
- Estimate: -18 / -10 (and -17 TOML lines, -3 frontend lines).

## File overlap and waves

Packages in one wave touch different files and can run in parallel worktrees. A later wave starts
when the earlier one is merged. The table lists the shared source files that force the order;
test files follow the same order.

| Package | Main shared files | Must come after |
|---|---|---|
| Q-6.1 | `tests/batch/`, `tests/validation/`, `tests/jobs/test_cli_batch.py` | none |
| Q-6.2 | many test files, `testing/reframe_testing/` | none |
| Q-6.4 | `definitions/`, `analysis/`, `capabilities/hwtest.py` | none |
| Q-6.3 | `cli.py`, `remote/queue.py`, `queue/service.py` | Q-6.1 |
| Q-6.5 | `validation/`, `capabilities/issues.py` | Q-6.1 |
| Q-6.8 | `probe/`, `service.py`, `models/base.py` | Q-6.2 |
| Q-6.6 | `batch/`, `jobs.py` | Q-6.1 |
| Q-6.7 | `tools/`, `service.py`, `settings.py`, `models/` | Q-6.2, Q-6.3, Q-6.8 |
| Q-6.9 | `queue/`, `jobs.py`, `tasks.py`, `service.py`, `cli.py`, `capabilities/service.py`, `tools/runner.py` | Q-6.3, Q-6.6, Q-6.7, Q-6.8 |
| Q-6.10 | `command/`, `capabilities/`, `dimensions.py`, `validation/`, `batch/`, `preview/graph.py`, `cli.py`, server `routers/jobs.py` | Q-6.3, Q-6.5, Q-6.6, Q-6.9 |
| Q-6.11 | `settings.py`, `presets/`, `service.py`, `models/` | Q-6.7 |
| Q-6.13 | `probe/`, `metadata/`, `batch/`, `models/media.py` | Q-6.6, Q-6.8 |
| Q-6.16 | `validation/`, `command/builder.py`, `queue/runner.py` | Q-6.5, Q-6.10 |
| Q-6.17 | `tools/runner.py`, `platform/`, `queue/whendone.py` | Q-6.2, Q-6.9 |
| Q-6.19 | `definitions/`, `capabilities/`, `frontend/` | Q-6.4, Q-6.10 |
| Q-6.12 | `settings.py`, `queue/files.py`, `platform/` | Q-6.11, Q-6.17 |
| Q-6.14 | `service.py`, `probe/folder.py`, server | Q-6.8, Q-6.11 |
| Q-6.15 | `batch/`, `jobs.py`, `cli.py`, `validation/__init__.py` | Q-6.6, Q-6.9, Q-6.13 |
| Q-6.18 | `tasks.py`, `capabilities/service.py`, `service.py`, `cli.py` | Q-6.10, Q-6.14 |

Suggested waves:

| Wave | Packages (parallel) | Tier |
|---|---|---|
| 1 | Q-6.1, Q-6.2, Q-6.4 | A |
| 2 | Q-6.3, Q-6.5, Q-6.8 | A |
| 3 | Q-6.6, Q-6.7 | A |
| 4 | Q-6.9 | A |
| 5 | Q-6.10 | A |
| 6 | Q-6.11, Q-6.13, Q-6.16, Q-6.17, Q-6.19 | B |
| 7 | Q-6.12, Q-6.14, Q-6.15 | B |
| 8 | Q-6.18 | B |

The table comes from the "Where" and "Callers" bullets, not from a full read of every change. Before
a parallel wave is merged, compare the worktrees' `git diff --stat`; if two packages touched the
same file after all, merge them in step order and let the later one rebase.

Q-6.12 needs the Windows test VM. If the VM is not available, leave Q-6.12 open; nothing else
depends on it.

## Brief template for an implementation agent

```text
You implement work package Q-6.<n> of Reframe's simplification plan, in the worktree you are
in (branch from m10-hardening). Read CLAUDE.md first.

Your package is described in docs/simplify/plan.md, section "Q-6.<n>". Its findings are:
<IDs>. Each finding is in docs/simplify/areas/<area>.md or docs/simplify/cross-cutting.md.
Read each finding in full, including its "Verdict:" and "Orchestrator:" lines: an ADJUSTED
verdict corrects the bullets above it, and the Orchestrator line can narrow the change.

Do not investigate again and do not look for new simplifications. For each finding, in the
order the package gives:
1. Find each place by the symbol named in "Where" (line numbers are from commit 85d9dcb and
   may have moved). Check that the code still matches "Now". If an earlier package changed it
   and the intent is no longer clear, skip the finding and write why in your final message.
2. Make the change in "Change". Update the callers and tests in "Callers to update" and
   "Tests". Keep the tests named as the guard of unchanged behaviour.
3. Follow the code-comments skill for comments and docstrings.

If the package says "Decision record", write it in docs/decisions/ (next free number, template
in docs/decisions/README.md) and edit the plan files it names, in the same commit.

Then run the package's "Done when" items and the common ones in plan.md ("Rules for every
package"). Fix what fails. Mark the step done in docs/status.md (Quality and release table,
row Q-6.<n>) with a one-line note and the net line change from `git diff --stat`.

Commit once: `refactor(Q-6.<n>): <what>` with the attribution line. Do not push.

Reply with: the findings made, the findings skipped and why, the net source and test lines,
and the result of each Done-when command.
```
