# Decisions taken in place of the owner

The audit ran unattended (2026-11-15). Each choice below was made by the orchestrator with the
decision rules of the audit brief, so the work did not stop. Each one is easy to change: the last
line of each entry says what changes in [plan.md](plan.md) if the owner chooses the other option.

The decision rules, in order (a higher rule wins): 1 correctness and data safety; 2 the plan,
the decision records and `CLAUDE.md`; 3 no change a user sees; 4 fewer concepts, then fewer
lines; 5 less risk before v1; 6 when in doubt, be conservative; 7 a `decision-change` is accepted
(Tier B at most) only when the record's reason no longer applies, with evidence.

**Check these first:** D-4 (how a plan edit counts), D-10 (the `container.unknown` code), D-11
(the folder probe), D-13 (`probe_hash`), D-17 (`default_container` is not wired), and the
rejected decision-changes with the biggest saving: D-18 (TP-11 and TP-12, the D-Bus client),
D-19 (TP-01, `fetch-tools.py`), D-20 (CMD-09, the capability cache).

## How the audit was run

### D-1 Area split
- Question: the brief suggested 11 areas. `service.py` + `remote/` + `events.py` were about 2k
  lines, below the 4–7k target.
- Options: keep 11 areas; join `remote/` to the CLI and `service.py` + `events.py` to the server.
- Chosen: 10 areas: `cli-remote` (cli.py, remote/), `server-service` (the server, service.py,
  events.py), the other eight as suggested. `remote/` is used only by the CLI; `service.py` is the
  server's door into the core, so core/server duplication is seen by one agent.
- Rule: brief ("join or split areas so that each agent has about 4–7k source lines").
- If the other option: nothing changes in the plan.

### D-2 Coverage is not evidence of dead code
- Question: `coverage.txt` shows every module's import-time lines (`def`, `class`, imports) as
  missed, because the `reframe_testing` pytest plugin imports the package before coverage starts.
  Total coverage reads 78 %.
- Chosen: the agents were told not to use coverage misses as evidence; every dead-code claim rests
  on a repository-wide caller search instead. One test failed in the coverage run
  (`packages/reframe-server/tests/test_app.py::test_desktop_server_prints_the_ready_line_and_answers_health`:
  the server process exited 0 where 130 was expected after Ctrl+C, under coverage). It was not
  investigated (out of scope); run it alone to see if it is a coverage artefact.
- Rule: 6.
- If the other option: a coverage run with `--cov` started before the plugin
  (`coverage run -m pytest`) would give real misses; it would not change a finding.

## Tier rules the brief left open

### D-3 What is a "contract" for Tier A
- Question: Tier A needs "no contract touched". Many findings remove a name from a core module.
- Options: treat every core Python name as a contract (almost nothing is Tier A); or treat as
  contracts only what a user, a file or another program sees: CLI, HTTP/WebSocket/OpenAPI,
  persisted files, the desktop, encode results, messages, and the members of the `Reframe`
  facade.
- Chosen: the second. Plan `05-core.md` (line 11) says only the facade and `reframe.models` are
  public and the rest "can change"; decision 0079 keeps the core off PyPI for v1.
- Rule: 4, 5.
- If the other option: most Tier A dead-code findings (they remove module names) move to Tier B;
  the waves stay the same.

### D-4 A finding that needs a plan or decision text edit
- Question: some plain findings (dead code, duplication) remove something the plan or a record
  names, often only in a sketch (`05-core.md:67` `run_streaming(..., timeout=None)`, `05-core.md:115`
  "probe hash", C-3's folder probe, C-9's preset "duplicate").
- Chosen: treat them as `decision-change` findings under rule 7: Tier B at most, and only when the
  feature the text served is gone (no caller in the core, the server, the CLI, `frontend/src` or
  `desktop/`). The package writes the record and the plan edit. This put TP-03, BAT-03, SRV-01,
  X-07 and X-09 into Tier B.
- Rule: 2, 7.
- If the other option (plan sketches are not the spec): TP-03, BAT-03 and X-09 move to Tier A
  (packages Q-6.7, Q-6.6 and Q-6.8); the records are still written.

### D-5 Medium confidence that is only about the size
- Question: PRB-07, PRB-13 and CLI-12 (test helpers) say "confidence: medium", but only about
  how many lines the change saves, not about whether it is right.
- Chosen: Tier A. The tests run either way.
- Rule: 4.
- If the other option: they move to a Tier B package; Q-6.2, Q-6.3 and Q-6.8 lose them.

## Decision-change findings accepted (Tier B, the package writes a new record)

### D-6 BAT-01 and BAT-02: `resolve_group`, `merge_template` (0040 §8)
- Evidence: 0050 item 6 already left `group` out of the route; no production caller in the core,
  server, CLI or frontend (the frontend has its own merge; `clipboard.ts:27` names the sections).
- Chosen: accepted, Q-6.15. The record amends 0040 §8 and plan 04 "Core API".
- If rejected: drop BAT-01 and BAT-02 from Q-6.15 (-74 source / -45 tests less).

### D-7 BAT-12: the `container_codecs` flag (0040 R1-4, 0031 §6)
- Evidence: the records' rule (one issue per problem) is kept; only the mechanism changes (the
  preview adds the codec issue itself). Guards: `tests/jobs/test_service.py:526`,
  `tests/batch/test_rules.py:437-456`.
- Chosen: accepted, Q-6.15 (confidence medium).
- If rejected: drop BAT-12 from Q-6.15 (-25 source).

### D-8 SRV-02: no pre-rendered language list (0071 item 2)
- Evidence: 0082 made the language table generated Python; measured on this commit:
  `language_list()` 9.2–9.4 ms and `render()` 1.8 ms on the first request (not at start-up).
- Chosen: accepted, Q-6.14. The record supersedes 0071 item 2 and its Consequences bullet.
- If rejected: drop SRV-02 (-15 source and one 73 KB generated file stay).

### D-9 TP-03, BAT-03: options and wrappers the plan sketches name
- See D-4. Accepted, Q-6.17 and Q-6.15.

### D-10 VAL-06: the issue code `container.unknown` (0014 follow-up item 3)
- Question: the container field is a `Literal` and the definitions linter checks it, so a job
  with an unknown container cannot be parsed; 15 guards and one issue code cover that state.
- Options: Tier B (accept, with a record); Tier C (keep the guards).
- Chosen: Tier B, Q-6.16. This was a close call: confidence is medium because the change spans
  validation, the builder and the queue verifier. No client uses the code (checked in
  `frontend/`, `desktop/`, the server).
- Rule: 7 (the type now makes the state impossible).
- If rejected: drop VAL-06 from Q-6.16 (-55 source / -14 tests).

### D-11 SRV-01: the folder probe (plan C-3, 0049 item 5)
- Evidence: 0049 item 5 says the server expands folders itself (`jobs.media_files`); the core's
  `probe_folder` has no production caller; the probe loop exists three times.
- Chosen: accepted, Q-6.14. `SourceService.probe_many` replaces it; the record says C-3's
  "folder probe" item is replaced. PRB-04 (Tier A, Q-6.8) first deletes the unused second copy.
- If rejected: drop SRV-01 (-170 / -215, the biggest Tier B saving).

### D-12 X-07: preset `rename` / `duplicate` and 7 more facade members (0015 §2, 0050 item 10)
- Evidence: 0 callers outside tests; the plan's "Not exposed" table lists them as kept for later.
- Chosen: accepted, Q-6.11. This removes members of the facade, which plan 05 calls public.
- If rejected: drop X-07 (-90 / -80); the "Not exposed" rows stay.

### D-13 X-09: stop writing `probe_hash` (plan sketch 05-core.md:115)
- Question: the two verifiers disagreed: one called it plain dead code, the other a
  `decision-change` because the plan names the field.
- Chosen: `decision-change`, accepted at Tier B (Q-6.13), in the cheap form: the field stays
  declared and optional, it is no longer written, no `schema_version` bump. `reframe probe --json`
  and the API then show `"probe_hash": null`.
- Rule: 3 (a value a user can see changes), 7.
- If rejected: drop X-09 (-17 / -10).

## Decision-change findings not accepted (Tier C)

Each stays in its area file with the condition that would have to become true.

### D-14 PRB-01: `languages.search` and `picker_label` (0082, 0065 items 1 and 3)
- Reason kept: 0065 names them as the reference for the TypeScript picker; that reason still
  applies. Saving if taken: -95 / -245.

### D-15 PRB-05: `MATROSKA_READER` in the cache options (0007 RB-7)
- The parser fingerprint does cover the reader version, but the record says the number stays, and
  the saving is 24 lines plus one re-probe of every cached file. Rule 5, 6.

### D-16 Other rejected decision-changes
- TP-05 (0081 item 3 keeps zip archives without a top folder on purpose), TP-10 (0038 R5-5: a
  cancel after the swap still refreshes the tool status; the finding asks to accept a stale
  status), MOD-09 (0081's own review kept the `media_source` migration), MOD-10 (0015: a too-deep
  preset loses only itself; the change would back up the whole file), CMD-08 (0008: the cache key
  hashes the detection source so a developer checkout sees edits), BAT-04 (0040 §1: compiled
  rules as `OutputTrackRule`s; a later F-13 step may want to turn them into editable rules),
  CLI-13 (0061 item 2, 3 lines), CLI-14 (0061 C4: the report would be worse), QJ-07 (a changed
  API answer for a too-deep job), SRV-07 (0049 item 4: Range answers; the clip URL also goes to a
  browser tab and the desktop's external player), VAL-13 (0065 FA item 1: the charset cache;
  needs a timing measurement on network shares), VAL-14 (0016 RN: NUL paths in every layer).

### D-17 MOD-07 (a): `output.default_container` is stored but nothing reads it
- Question: plan `03-features.md:821` lists "default container" under Settings → Output. The
  frontend writes it; no core or server code reads it.
- Options: remove it (schema bump, migration, UI change); wire it (use it where a draft has no
  preset); leave it.
- Chosen: not a simplification (the plan asks for the feature, rule 2 and 3). Left as an open item
  for the owner: wire it or remove it. `align_av_start` has the same shape (status.md already says
  it "is ignored").
- If the owner wants it removed: a new Tier B package (settings `schema_version` 3, a migration
  that pops the field, the frontend control, its i18n strings and tests).

### D-18 TP-11, TP-12: the logind backend and the own D-Bus client (0022 item 2, 0011 item 1)
- TP-11 (-200 / -400) drops the logind lock: a headless host with an idle action would suspend
  during an encode. TP-12 (-490 / -700) replaces the stdlib D-Bus client with `jeepney`, a new
  dependency with its own notice, and re-verifies every failure path. Both low confidence.
- Reason kept: rule 1 (an idle suspend during an encode) and rule 5.

### D-19 TP-01: `scripts/fetch-tools.py` repeats `reframe.tools.fetch` (0038 item 4)
- -290 / -400, the biggest single duplicate. 0038 item 4 keeps the script free of the project so
  CI and the Docker build can run it before `uv sync` ("no path tricks"). The verifier checked
  that loading the core module by path works in every place the script runs, so the change is
  possible, but the record's reason still applies. Rule 7.
- If the owner accepts path loading: a new Tier B package (CI and Docker build in its Done when).

### D-20 CMD-09: drop the capability cache (0008)
- -400 / -650. Each start would show every encoder as "checking…" until detection ends, and
  queueing waits. Rule 3; low confidence. CMD-07 (Tier B) and CMD-08 (Tier C) are the small
  versions.

## Disagreements between agents that the orchestrator settled

### D-21 X-03: the shape of the draft merge
- CLI-03 (CONFIRMED) gave a short `OwnerJobs.draft` that resolves the preset before it probes;
  QJ-03's verifier showed this flips the error a bad source with a bad preset name gives. Chosen:
  QJ-03's shape (probe first). Rule 1/3.

### D-22 X-01: one geometry helper, three proposals
- CMD-01 (`job_source_geometry(stream, job)`, `job_geometry(stream, job)`), SRV-04 (the first
  only), VAL-11 (`job_geometry(video, dimensions, filters)`). Chosen: CMD-01's names, SRV-04's
  server line. All three were checked against the same five call sites.

### D-23 X-04: how the tests import their shared module
- BAT-06 proposed moving `anime.py` into `reframe_testing`; VAL-02 checked that a relative import
  works in this repository's pytest mode; the batch verifier noted the `__init__.py` way. Chosen:
  try the relative import (with `__init__.py`) first in both folders. Rule 5 (the smaller diff).

## Close tier calls

- QJ-01 (replace the hand-made task gate with `asyncio.Semaphore`): Tier B, not A. It is on the
  task cancel path; the verifier ran the tests with a semaphore and only the `set_limit` test
  failed, as expected. Rule 1, 6.
- MOD-01, MOD-03 (the settings and preset load paths): Tier B. This code decides whether a file is
  kept or replaced by a backup. Rule 1.
- PRB-03 (EBML helpers): Tier B. The header writer writes into the user's files and its torn-write
  recovery reads through `header._read_at`. Rule 1.
- PRB-02 (drop the probe cache's memory layer): Tier B. With a cache folder that cannot be
  written, a file is probed again in the same run. Rule 3.
- PRB-08, VAL-09, X-08: Tier B because a text or a value a user sees changes (better codec labels,
  number formatting, a video language edge case), even where the change fixes an inconsistency.
- TP-14, TP-15, X-02: Tier B because they change Windows-only code; Q-6.12 needs the Windows VM.
- CMD-12, QJ-14, NDP-10 (long functions split, no line saving): Tier C. Rule 5.
- QJ-10, NDP-11, CLI-10: small consolidations. QJ-10 and NDP-11 are Tier B (no concept removed);
  CLI-10 is Tier A (it removes a duplicate set and one unused constant in a package that edits the
  same lines anyway).
- QJ-05 item 4 (`SourceService.store`): Tier C, because 0030's contract table names it.

## Leads the verifiers noted but nobody verified

They are not findings. A later session can look at them.

- `cli.py:3402-3404`: the "no FFmpeg build pinned" message lists `linux-arm64` as a `--platform`
  value, but the option accepts only `linux-x64` and `windows-x64`.
- `validation/filters.py:227` `is_hdr(stream)` and `command.filtergraph.is_hdr` have the same name
  and different results (part of VAL-07's HDR question).
- `command/jobtype._copy_type` describes a job whose SRT tracks become `mov_text` in MP4 as "copied
  without re-encoding".
- `JsonDocumentFile.write` with `max_depth=None` refuses a 63–64-level preset that
  `PresetStore.save`'s per-entry check passes (`presets.write_failed` instead of `preset.invalid`).
- `scripts/bundle-tools.py:94-182` is a third manifest validator next to the core's and
  `fetch-tools.py`.
- `tests/validation/scenario.py:345` `FIXES_CHECKED` is written and never read.
- `command/filtergraph.py:116, 150`: private and public twin functions that only call each other.

## Implementation (Q-6)

The packages were made unattended (2026-11-16) by one agent each, in the waves of
[plan.md](plan.md). Owner answers to D-1 to D-23: none changed, the defaults are used. The
choices below were taken by the agents or by the orchestrator, with the same decision rules.

### D-24 Worktrees start from `main`
- Question: the agents' isolated worktrees are created from `main`, not from `m10-hardening`.
- Chosen: each agent first resets its worktree branch to the `m10-hardening` commit of the last
  merge and checks `git rev-parse HEAD`. Nothing else changes.
- Rule: 2 (the packages are built on `m10-hardening`).
- If the other option: none; a worktree on `main` lacks M10.

### D-25 Baseline tests that fail under load
- Question: the baseline run at `8bf1df6` (while three agents ran their own suites) failed
  `tests/probe/test_live.py::test_probe_budgets` (5.95 s against a 5 s budget) and
  `tests/remote/test_cli_client.py::test_a_client_drafts_as_the_in_process_draft[default]`.
  Both pass when run alone.
- Chosen: count them as load-dependent baseline failures, not a package's fault. A package is
  blamed for them only if they also fail alone. `test_desktop_server_prints_the_ready_line_and_answers_health`
  passed in this run (not under coverage).
- Rule: 6.
- If the other option: a separate fix step for the two tests.

### D-26 Q-6.1: two by-path loaders stay
- Question: `tests/jobs/test_cli_batch.py::_load_anime` and
  `tests/validation/test_command_agreement.py::_load_command_tests` load a module from another
  test folder. A relative import cannot leave the test package (pytest names the module after the
  topmost folder with an `__init__.py`).
- Options: keep the two loaders; move `anime.py` into `reframe_testing` (BAT-06's fallback).
- Chosen: keep them; a note is under X-04. The other 33 loaders are gone.
- Rule: 5, 6 (the smaller diff).
- If the other option: move `anime.py` and the command-test module into `reframe_testing`.

### D-27 Q-6.2: shared helper defaults
- `wait_until` and `wait_until_sync` default to 30 s (SRV-05 said 10 s for the async one): no wait
  is shorter than before, so no test gets flakier; the longer old waits (60 s, 120 s) stay at their
  calls. Rule 5.
- `Api.add_source` returns the id only, not `(id, path)`: every caller but one needs only the id.
  Rule 4.
- The shared `ebml.element` keeps the fixed 8-byte size field by default, so tests that count byte
  offsets do not change; `corpus.element` passes the shortest width. Rule 5.
- Not done: `SeasonFs` in `tests/batch/test_anime_season.py` (in Q-6.1's file at the same time)
  and the six cross-area `app` fixture copies the finding does not count. Note under NDP-05.

### D-28 Q-6.4: OpenAPI description, optional parts
- NDP-03 item 2 moved a comment into the docstring of `Condition.field`; `Condition` is in the API,
  so the OpenAPI description and `frontend/src/api/schema.d.ts` changed (comments only). Accepted:
  no field or type changes. Rule 3 holds (nothing a user sees).
- Not done: NDP-03 item 10 (`AudioBitrateDef.values`) and NDP-01's optional move of tests-only
  imports: outside the package estimate, and in preset tests that Q-6.2 edited at the same time.
  Rule 5.
- `capabilities/hwtest.py` and `detect.py` (named for NDP-03 item 4) do not refer to
  `supported_options`; not touched.

### D-29 Q-6.3: where the shared CLI test helper and `ACTIVE` live
- `invoke` and `WIDTH` moved to `testing/reframe_testing/cli.py`, not `tests/conftest.py`:
  `tests/` is not a package, so its subfolders cannot import from that conftest. The finding
  allows either place. Rule 4.
- `reframe.queue.ACTIVE` is defined in `queue/service.py` next to `ENDED`, not in
  `models/queue.py`: it keeps the change in the package's files. Rule 5.
- The inline `CliRunner` call in `tests/capabilities/test_recheck.py` stays (outside the
  package's files); noted in the status row.

### D-30 Q-6.5: `encoder_issues(target=)` stays
- VAL-05 allowed keeping or dropping the `target` keyword of `capabilities.encoder_issues`. Kept:
  the smaller change. Rule 6. Fix targets were compared before and after over the validation,
  batch and presets tests (18,823 issues, the same).

### D-31 Q-6.8: `test_folder_task_events` is kept
- Question: PRB-04's "Tests" bullet deletes `test_folder_task_events`; the package's Done-when
  says it must pass, and the verdict notes it is the only exact event-sequence check.
- Chosen: keep it under the same name, pointed at `Reframe.sources.probe_folder` (the copy that
  stays). The test-line saving is about 60 lines smaller than estimated.
- Rule: 2 (the plan's Done-when), 6.
- If the other option: delete it; Q-6.14 (SRV-01) ports the folder tests anyway.

### D-32 A teardown error in `test_subtitles.py` under load
- `packages/reframe-server/tests/test_subtitles.py::test_a_sup_file_is_a_bitmap_counted_in_display_sets`
  got an error in setup or teardown in four package runs (a `ResourceWarning` for an unclosed
  asyncio transport left by an earlier test, raised when it was collected). Each run had three
  suites on the machine at once; the file passes alone and the server suite passes. Not in the
  baseline or the wave 1 merged run.
- Chosen: not blamed on a package while it does not show in the merged-wave run; watched in each
  merged run. Rule 6.

### D-33 Parallel test runs; agents run focused tests
- Question: a full run took about 35 minutes, three times per wave in the agents and once after
  the merge.
- Chosen (by the owner, 2026-11-16): pytest-xdist for every test run, in `addopts` (decision
  0084; a full run about 6 minutes),
  and the agents run only their package's focused tests and the static checks from wave 3 on;
  the orchestrator runs the full suite after each merge. See "How to run the tests" in
  [plan.md](plan.md).
- If the other option: each agent also runs the full suite (now about 6 minutes with `-n auto`).

### D-34 Q-6.7: the "Not exposed" table loses two rows without a new record
- Question: TP-07 removed `PowerService.closed` and `countdown`. `docs/plan/06-web-app.md` lists
  them in the "Not exposed" table, and `test_facade_coverage.py` fails while a row names a member
  that no longer exists. D-4 treats removing something the plan names as a decision change.
- Chosen: the table's own rule (a row whose member no longer exists goes) asks for the edit, so
  it is bookkeeping, not a change of course; no record in Q-6.7. Q-6.11, whose record (X-07)
  amends the same table, names these two rows too. The same holds for `batch.definitions`
  (Q-6.6, BAT-10 item 2), removed from the table after the wave 3 merged run failed on it.
- Rule: 2, 5.
- If the other option: a short record for Q-6.7 that names the two rows.

### D-35 Q-6.6 and Q-6.7: small choices of the agents
- Q-6.6: `explain.py` imports the private `selection._track` instead of making it public (as
  `descriptors` already does with `_EXTRA_ROLES`); the `rule_unused` tests go through
  `resolve_tracks` with a small helper (tests +2 lines instead of -14); decision 0031 §6 names
  the new entry point `lint_defaults(defaults, used=...)`, as BAT-07 asks. Rule 4, 5.
- Q-6.7: the optional `ToolLocation.env_var` part of TP-02 is not done (outside the estimate);
  `test_status_lines_are_shared_with_python_m_reframe_tools` stays synchronous and calls
  `asyncio.run(discover_tools())`. Rule 5.

### D-36 Q-6.9: shared stubs and where `SourceProber` lives
- QJ-08 allowed an optional shared `StubSources`; it was made, with the analysis stub's behaviour
  (a deep copy on probe, an update applied to the last stored source); `test_mediatask` never
  reads `.stored`. Rule 4.
- QJ-06: the one `SourceProber` protocol moved into `mediatask.py` as the base of
  `SourceAccess`, so `mediatask` stays a leaf module (no import of `queue.runner`). Rule 5.
- QJ-05 removed `JobService.detection_wait`; its row left the "Not exposed" table (D-34).

### D-37 Q-6.10: small choices of the agent
- `encoder_and_pix_fmt` takes the job (CMD-01's signature); in `_video_plan` the container-codec
  check now runs after the pixel-format check, as CMD-01 says.
- `filter_test_argv` raises `ValueError` for a name not in `FILTER_TESTS` (before: `KeyError`);
  nothing calls it with another name.
- CMD-02 drops `filter_tests` from the capability cache key: one re-detection after the update.

### D-38 Wave 6 (Q-6.11, Q-6.13, Q-6.16, Q-6.17, Q-6.19): choices of the agents
- Decision record numbers were assigned before the wave (0085 to 0088; 0089 and 0090 for
  wave 7), so two packages could not take the same one. Q-6.19 needed none (no plan or record
  names its fields).
- Q-6.11: SRV-03 items 2 and 3 are done too (SRV-03 is joined fully into X-07, and X-07's
  estimate counts them); `is_newer` is inlined into `parse_document`; record 0085 also amends
  0049 item 11 and the `Reframe` sketch in `05-core.md`, and names the four table rows of D-34
  (review RA-2). MOD-01's changed texts: the prefix "migration failed: " in the detail of
  `presets.corrupt` and in the message of `presets.import_invalid`; preset warnings are logged
  like settings warnings.
- Q-6.13: `textfile.BYTE_ORDER_MARKS`, `models.text.shown` and `matroska.read_exactly` are public
  instead of private names imported across modules; the probe workers' log lines share one
  wording.
- Q-6.16: "VAL-12 without item 2" was read as the rejected `next_free_path(limit=)` item, so every
  listed item is done; the lint guarantee on `Definitions.containers` is a comment, not a field
  docstring (a docstring would change the API schema); template rules now carry the job rule's
  name (one rule written once, VAL-03).
- Q-6.17: TP-06 keeps the reader type `b` (the real-bus test needs it; note under TP-06); the
  streaming tests keep their hang guards with `asyncio.timeout` after `run_streaming` lost
  `timeout=` (sent back once for this).
- Q-6.19: NDP-11 item 3 touched Q-6.13's files in the same wave; the orchestrator made it after
  the merge.
