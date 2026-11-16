# Review of the Tier B packages (Q-6.11, Q-6.13 to Q-6.19)

- Range: `git diff 4f398542..7a2051d6` on `m10-hardening` (packages Q-6.11, Q-6.13, Q-6.14,
  Q-6.15, Q-6.16, Q-6.17, Q-6.18, Q-6.19; Q-6.12 is not done and is not reviewed).
- Date: 2026-11-17. Read-only review: no code, test or doc was changed.
- Read: `CLAUDE.md`; `docs/simplify/plan.md` (rules and the Tier B packages); every finding
  that these packages name in `docs/simplify/areas/*.md` and `cross-cutting.md` (with their
  Verdict, Orchestrator and Note lines); `decisions-taken.md` D-24 onward; records 0085 to 0090;
  the package commit messages; the Q-6 rows and the changed rows of `docs/status.md`; the plan
  and record edits in the range.
- Compared: the code at 7a2051d6 with the code at 4f398542 (`git show 4f398542:<path>`) for each
  changed symbol. For Q-6.16, the rule registry at both commits (old source exported with
  `git archive` to a scratch folder) to compare the rule order. For Q-6.13, the old
  `CODEC_LABELS` table against `probe.names.codec_name`. For Q-6.14, the bytes and the ETag of
  `GET /api/languages` against the shipped `data/languages.json` at 4f398542.
- Ran (all passed): `uv run pytest` on `tests/test_settings.py`, `tests/presets`,
  `tests/test_service_settings.py`, `tests/models/test_models.py`, `tests/tools/test_runner.py`,
  `tests/platform`, `tests/queue/test_when_done.py`, server `tests/test_queue.py` (624 passed);
  `tests/probe`, `tests/metadata/test_remux_job.py`, `tests/definitions`,
  `tests/analysis/test_subtitlefile.py` (882 passed, 2 skipped); `tests/validation`,
  `tests/batch`, `tests/jobs/test_service.py`, `tests/jobs/test_cli_file_identity.py`,
  `tests/command/test_builder.py` (2258 passed); `tests/remote` (209 passed); core
  `test_tasks.py`, `test_service.py`, `capabilities/test_service.py`, `probe/test_folder.py` and
  server `test_sources.py`, `test_languages.py`, `test_tasks.py`, `test_settings.py`,
  `test_facade_coverage.py`, `test_attach.py` (129 passed). The full suite was not run.

Result: 0 blocker, 1 major, 4 minor.

## Findings

### RB-1 — `track_label` shows a raw codec name where it showed "unknown codec"

- Severity: major (an unannounced change that a user sees; low impact)
- Package: Q-6.13 (PRB-08)
- Where: `packages/reframe/src/reframe/batch/descriptors.py`, `track_label`.
- What is wrong: PRB-08's Behaviour line, the commit message and the Consequences of 0086
  announce one change only: a codec that `probe/names.py` knows but the old `CODEC_LABELS` did
  not now gets its proper name ("Nothing else"). There is a second change. A codec that
  **neither** table knows now shows its raw ffprobe name, where the old code showed
  "unknown codec". Subtitle descriptors always have `profile=None`, so every subtitle label
  goes through this path. Audio uses it only when there is no profile.
- Evidence:
  - At 4f398542 the code was
    `descriptor.profile or CODEC_LABELS.get(descriptor.codec or "", "unknown codec")`.
  - At 7a2051d6 it is
    `descriptor.profile or (codec_name(descriptor.codec) if descriptor.codec else "unknown codec")`.
  - `codec_name` gives back the codec itself when no table holds it:
    `codec_name("pcm_s16le") == "pcm_s16le"` and `codec_name("rawvideo") == "rawvideo"`.
  - Example: a `jacosub` subtitle is now labelled `eng jacosub`. It used to be
    `eng unknown codec`.
  - The finding's own Change line asked for exactly this code. Only the Behaviour text is
    incomplete.
- Fix: add one sentence to the Consequences of 0086, as a dated note and not a rewrite (a
  codec that neither table knows now shows its raw codec name, not "unknown codec"). Add the
  same sentence as a note under PRB-08. The other option is to keep "unknown codec" for codecs
  that `names` does not know. The note is the smaller change.

### RB-2 — `docs/status.md` still lists `presets.rename` and `presets.duplicate` as "Not exposed"

- Severity: minor
- Package: Q-6.11 (X-07)
- Where: `docs/status.md:87`, the S-2 row.
- What is wrong: the row says "Not exposed: `batch.merge` (removed, 0090), `presets.rename`,
  `presets.duplicate` (reasons in 0050)". Q-6.11 deleted both facade members (0085). The plan
  table in `06-web-app.md` and record 0050 were updated, but this row was not. Q-6.15 edited
  the same row for `batch.merge` and also left these two names.
- Evidence: `rg -n "presets.rename" docs/status.md` finds line 87. `PresetService` at
  7a2051d6 has no `rename` or `duplicate`.
- Fix: write "`presets.rename`, `presets.duplicate` (removed, [0085](...))", or remove the
  two names.

### RB-3 — `SourceService.probe_many(concurrency=0)` hangs where it used to raise

- Severity: minor
- Package: Q-6.14 (SRV-01)
- Where: `packages/reframe/src/reframe/service.py`, `SourceService.probe_many`.
- What is wrong: `concurrency` is not checked. `asyncio.Semaphore(0)` is accepted, so every
  `one()` waits forever. At 4f398542, both `SourceService.probe_folder` (`service.py:354`) and
  `probe.folder.probe_folder` (`folder.py:134`) raised
  `ValueError("concurrency must be at least 1, got …")`. No production caller passes
  `concurrency`, so no user sees this. It is a hang trap in a public core method that replaces
  a checked one.
- Fix: put `if concurrency < 1: raise ValueError(...)` back at the top of `probe_many`, and add
  a one-line test.

### RB-4 — `StaticBody.of_content` has no caller left except `StaticBody.of`

- Severity: minor (dead code)
- Package: Q-6.14 (SRV-02)
- Where: `packages/reframe-server/src/reframe_server/routers/definitions.py`,
  `StaticBody.of_content`.
- What is wrong: the only other caller was the old `languages._body`, which read the shipped
  `languages.json` bytes. SRV-02 removed that file, and `languages._body` now goes through
  `StaticBody.of`.
- Evidence: `rg -n of_content packages` finds only the definition (`definitions.py:34`) and the
  call inside `of` (`:31`). No test uses it.
- Fix: put the body of `of_content` into `of` and delete `of_content`.

### RB-5 — the `tasks.py` module docstring gives the concurrency limit wrongly

- Severity: minor
- Package: Q-6.18 (QJ-01)
- Where: `packages/reframe/src/reframe/tasks.py`, the module docstring.
- What is wrong: Q-6.18 changed "At most ``limit(kind)`` tasks of one kind run at the same
  time" to "Tasks of one kind run at most ``DEFAULT_LIMITS[kind]`` at the same time". The real
  limit is `self._limits.get(kind, DEFAULT_LIMIT)`. A kind that is not in `DEFAULT_LIMITS` (for
  example `probe_sources` or `encoders_rescan`) gets `DEFAULT_LIMIT`, and `limits=` overrides
  the values. The text also suggests a `KeyError` for kinds that are not in the table.
- Fix: write "at most their limit (``DEFAULT_LIMITS``, else ``DEFAULT_LIMIT``)".

## What was checked, in order

1. **Q-6.11 (X-07, MOD-01, MOD-03, MOD-05)**
   - `SettingsStore.load` and `PresetStore._load` / `_incoming` / `_parse_file` were compared
     branch by branch with the old ladders:
     - missing, unreadable and corrupt files;
     - a newer or a bad `schema_version`;
     - a validation error and a migration error;
     - a missing `presets` and a `presets` that is not a list;
     - the re-count after a migration;
     - deep entries and the order of the damaged entries.
   - Only the announced texts changed: the "migration failed:" prefix of `presets.corrupt` and
     `presets.import_invalid`, and preset warnings are now logged. The warning codes and the
     "no preset list." message are unchanged.
   - `_place` now calls `unique_name(..., entries=)`, which is the old `_free_name` loop under
     the store's RLock.
   - No removed member (`rename`, `duplicate`, `default_id`, `builtins=`, `registry=`,
     `migrate_document`, `document_version`, `is_newer`, `register_migration`,
     `_load_settings`, `discovering`, `versions`, `settings.path`, `sources.cache`) is left in
     `packages`, `testing`, `docs/plan` or `testdata/README.md`.
   - `docs/plan/05-core.md:595` and the "Not exposed" rows are edited. Records 0015, 0049 and
     0050 got dated notes, not rewrites; 0085 is new.
   - One leftover: RB-2.
2. **Q-6.13 (X-08, X-09, PRB-02, PRB-03, PRB-08, PRB-12, PRB-14)**
   - X-08 has its edge-case test.
   - `probe_hash` is no longer written. `fingerprint` is still set, and there is no
     `schema_version` change (0086).
   - The probe cache `get` and the prune count were checked.
   - The header writer's IDs and defaults are equal at runtime to the old constants.
     `read_exactly` keeps its short-read loop. `segment_pos` is gone.
   - The BOM codec list is equal to the old one. `shown()` is equal to both old copies.
   - The PRB-08 label table: all 24 old entries give the same text. The one gap is RB-1.
   - The changed info-level log text in sampling is not a warning or an issue. It is not
     reported.
3. **Q-6.14 (SRV-01, SRV-02, SRV-08)**
   - `GET /api/languages` gives the same bytes (73,834) and ETag as the shipped file at
     4f398542.
   - The sidecar spec entry is gone.
   - `probe_many` keeps the list order and the progress text. After a cancel it starts no new
     ffprobe; the ported tests exist.
   - The task kind `probe_folder` is gone from the core, the frontend label and the `en` locale.
     The `TaskInfo.kind` description change in `schema.d.ts` is announced in D-39.
   - SRV-01 item 4 (`BatchService._probe_all` still has its own `PROBE_CONCURRENCY`) is not
     done, with a note in D-39, 0089 and the status row.
   - The settings jail `_folders` gives the same paths.
   - Two leftovers: RB-3 and RB-4.
4. **Q-6.15 (X-03, BAT-01, BAT-02, BAT-03, BAT-12)**
   - `JobService.draft(validate=)` was compared with the old `OwnerJobs.draft`: the same probe,
     preset error, naming, issue filter and issue order.
   - BAT-12: `explain` adds the codec lint under the same condition as before. Only the
     issue's position changed, and 0090 announces it.
   - Rows are now in episode order and the near-match check is in `resolve_batch`, as 0090
     says.
   - The `clipboard.ts` comment is reworded. Plan 04 and 05 are edited. 0031 and 0040 got
     status notes only.
   - `schema.d.ts` is unchanged.
5. **Q-6.16 (VAL-03, VAL-06, VAL-07, VAL-09, VAL-12)**
   - The template rule order is unchanged. The four twin rules now carry the job rules' names,
     as announced.
   - `JOB_RULES` went from 44 to 43 rules; the only difference is `known_container` (0087).
   - These keep their behaviour: `passthrough_known`, `drop_upmix`, `_can_burn`, `option_int`
     and `_bit_depth_ops`.
   - The `value_text` change and the `is_hdr` change are announced in 0087. `container.unknown`
     is not used anywhere outside the core.
   - The builder got no I/O.
   - Note (not a finding): `batch/lint.py` `container_codec_issues` and five other places
     outside VAL-06's "Where" list still guard `defs.containers.get(...) is None`. The guard
     was there before this range, and 0087 says every container has a definition. It can go
     in a later cleanup.
6. **Q-6.17 (TP-03, TP-06, TP-09)**
   - `run` always uses `stdin=DEVNULL`.
   - `run_streaming` passes `timeout=None`, `cwd=None` and `DEFAULT_STREAMING_TAIL`, as its old
     defaults did. The tree kill, drain and cancel code is not touched.
   - The plan sketch at `05-core.md:67` is edited.
   - The D-Bus client:
     - a `B` flag is now a `DBusProtocolError` (tested);
     - the types `i` and `y` are gone and `b` is kept (Note under TP-06, 0088);
     - a body with an unknown type is skipped;
     - `_Reader.byte` is still used for signatures and header codes.
   - `SessionInhibitBackend` walks `(PM_INTERFACE, PORTAL_INTERFACE)`.
   - `WhenDoneActions._notify` publishes the same `NotificationEvent`.
   - `docs/status.md` (C-14 row) and the `platform/__init__.py` docstring are reworded.
   - No `notify`, `unique_name`, `interfaces=` or stdin use is left.
7. **Q-6.18 (QJ-01, QJ-10, CMD-07)**
   - The semaphore gate keeps the FIFO order and the hand-over when a waiter is cancelled.
   - Every production task returns a pydantic model, so dropping the plain-JSON result path
     changes no result.
   - `ToolInfo.usable` is a property: the schema snapshot and `schema.d.ts` are unchanged. It
     is used at all 7 places.
   - The capability cache is written on the loop with its `try/except` kept.
   - The `tasks.limit` / `set_limit` plan row is removed.
   - One leftover: RB-5.
8. **Q-6.19 (NDP-04, NDP-11)**
   - `hardware` is derived and `readonly` in the API, and it stays in the capability
     fingerprint.
   - The TOML, the linter, the tests, `schema.d.ts` and `tracks/testing.ts` changed together.
   - NDP-11 item 3 was first skipped with a note, then done in b5df471.
9. **`CLAUDE.md` rules in the whole range**
   - The core imports no server or UI code.
   - No new subprocess.
   - No persisted model or `Literal` changed. `probe_hash` keeps its field; the reason is in
     0086.
   - Every plan edit has a record (0085 to 0090) or a D-entry.
   - No record body is rewritten.
   - No step IDs or history in the added code comments.
