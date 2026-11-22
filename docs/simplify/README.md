# Simplification audit (Q-6)

Goal: find code in the core package `packages/reframe` and the server `packages/reframe-server`
that is more complex than the plan and the decision records need, and plan how to remove it
before v1. The audit changed no code. A later session makes the changes from these documents,
without investigating again ([plan.md](plan.md)).

- Commit: `85d9dcb20e9bc10d6115cbebaf26dbaaef06ce14` (branch `m10-hardening`). Every line number
  in these documents refers to it.
- Date: 2026-11-15. Unattended run; the choices made in place of the owner are in
  [decisions-taken.md](decisions-taken.md).
- Decision record: [0083](../decisions/0083-simplification-step-before-v1.md). Plan:
  [09 §Q-6](../plan/09-quality-and-release.md#q-6-simplification).

## Result

| | Findings | Source lines | Test lines |
|---|---|---|---|
| Tier A (do before v1) | 51 | -1,112 | -1,110 |
| Tier B (if there is time) | 35 | -1,075 | -679 |
| Tier A + B | 86 | -2,187 | -1,789 |
| Tier C (after v1, or not worth it) | 36 | -2,040 | -3,016 |

- 131 area findings and 10 cross-cutting ones (X-01 to X-10). 18 area findings are joined into a
  cross-cutting one and counted there; 1 was rejected in verify (CMD-11).
- Lines are code lines (no comments, docstrings or blanks), removed net, estimated by the audit
  and corrected by the verify agents. Tier A + B is about 5 % of the core and server source
  (45.6k lines) and about 2.5 % of their tests (71.1k).
- NDP-02 (Tier A) also moves 669 lines, the definitions linter, out of the shipped package into
  `testing/reframe_testing`; they are not in the totals.
- Tier C holds most of the large items. They are `decision-change` findings whose record's reason
  still applies (for example TP-01, TP-11, TP-12, CMD-09, PRB-01), or changes a user would see.

The five most valuable findings:

1. [SRV-01](areas/server-service.md) (B): the core's folder probe has no production caller, and
   the "probe N files at once" loop exists three times. One `SourceService.probe_many` replaces
   them. -170 / -215.
2. [X-04](cross-cutting.md) (A): 35 test files in `tests/batch/` and `tests/validation/` load
   their shared module with the same `importlib` hack. A relative import replaces it. 0 / -495.
3. [VAL-01](areas/validation.md) (A): the fix `target` is passed through about 40 validation
   functions; it is set once instead. -110 / 0.
4. [NDP-01](areas/naming-definitions.md) and [NDP-02](areas/naming-definitions.md) (A):
   `definitions/__init__.py` and `models.py` list the same names three times (-99), and the
   669-line definitions linter, which only tests call, leaves the shipped package.
5. [CLI-01](areas/cli-remote.md) and [CLI-02](areas/cli-remote.md) (A): one helper for the
   "print one line" idiom (48 sites) and one shared preamble for `encode` and `batch`. -95, output
   byte for byte the same.

Close behind: X-07 (unused preset and facade members, B, -90 / -80) and X-01 (one geometry
rule in place of five copies, A).

## Method

1. **Phase 0, shared inputs** (in the orchestrator's scratch folder, not committed): ruff
   complexity rules (C901, PLR0911–PLR0915), `vulture --min-confidence 60`, pylint
   `duplicate-code` (8 and 5 lines), a full coverage run, code-line sizes per file, and an
   import map of core, server, tests, `scripts/` and `testing/`.
2. **Phase 1, audit:** 10 agents (Sonnet, effort xhigh), one per area of about 4–6k source lines,
   read code only and wrote [areas/](areas/). Every "unused" claim rests on a search of the whole
   repository (core, server, tests, `scripts/`, `testing/`, `frontend/`, `desktop/`).
3. **Phase 2, verify:** 10 fresh agents tried to show each finding wrong: callers again (also
   dynamic use), decision records, Windows paths, persisted compatibility, the HTTP contract. Each
   finding has a `Verdict:` line. Result: 34 confirmed, 96 adjusted (mostly caller lists, anchors
   and smaller estimates), 1 rejected; parts of about 10 more were dropped (listed under "Looked at and
   kept" in each area file).
4. **Phase 3, synthesis** (the orchestrator): tiers by the fixed rules, cross-area findings joined
   into [cross-cutting.md](cross-cutting.md), work packages in [plan.md](plan.md), choices in
   [decisions-taken.md](decisions-taken.md). Each finding has an `Orchestrator:` line with its tier
   and package.

Areas (code lines from `sizes.txt`):

| Area file | Scope | Source lines | Findings |
|---|---|---|---|
| [cli-remote](areas/cli-remote.md) | `cli.py`, `remote/` | 4.4k | 14 |
| [batch](areas/batch.md) | `batch/` | 4.7k | 17 |
| [validation](areas/validation.md) | `validation/` | 4.7k | 14 |
| [queue-jobs](areas/queue-jobs.md) | `queue/`, `jobs.py`, `tasks.py`, `mediatask.py` | 4.2k | 14 |
| [server-service](areas/server-service.md) | `packages/reframe-server`, `service.py`, `events.py` | 4.9k | 8 |
| [models-persistence](areas/models-persistence.md) | `models/`, `settings.py`, `presets/`, `jsonpatch.py` | 4.1k | 10 |
| [probe-metadata](areas/probe-metadata.md) | `probe/`, `metadata/`, `chapters.py`, `languages.py`, `textfile.py` | 5.3k | 15 |
| [command](areas/command.md) | `command/`, `dimensions.py`, `capabilities/` | 4.6k | 13 |
| [tools-platform](areas/tools-platform.md) | `tools/`, `platform/`, `paths.py`, `applog.py`, `diagnostics.py` | 4.2k | 15 |
| [naming-definitions](areas/naming-definitions.md) | `naming/`, `definitions/`, `analysis/`, `preview/` | 5.5k | 11 |

No area is partial: every audit and every verify agent finished on its first run.

## What is missing or weak

- **Coverage:** the coverage run counts every module's import-time lines as missed (the
  `reframe_testing` pytest plugin imports the package before coverage starts), so coverage gave no
  dead-code evidence. No finding relies on it.
- One test failed in the coverage run:
  `packages/reframe-server/tests/test_app.py::test_desktop_server_prints_the_ready_line_and_answers_health`
  (exit code 0 where 130 was expected after Ctrl+C). Not investigated; it may be a coverage
  artefact. 8,606 tests passed.
- `vulture`, `pylint` and ruff ran without problems. The pylint duplicate check found few blocks;
  most duplication was found by reading.
- The file-overlap table in [plan.md](plan.md) is built from the findings' "Where" and "Callers"
  bullets, not from making the changes.

## How to read the files

- [areas/](areas/): one file per area. Each finding has the fields Kind, Where, Now, Change,
  Behaviour, Contracts touched, Callers to update, Tests, Decision records, Size, Risk, Depends on,
  Confidence, then the verifier's `Verdict:` and the orchestrator's `Orchestrator:` line. "Looked
  at and kept" lists what looks complex but must stay, and why: read it before looking again.
- [cross-cutting.md](cross-cutting.md): findings that cross areas (X-nn). Read the X entry and
  the area entries it joins.
- [plan.md](plan.md): the work packages Q-6.1 to Q-6.19, the waves, and the brief for an
  implementation agent.
- [decisions-taken.md](decisions-taken.md): every choice made in place of the owner, and what
  changes if the owner chooses otherwise.

Tiers: **A** = do before v1 (good value, low risk); **B** = worth doing if there is time; **C** =
after v1 or not worth it. "→ X-nn" means the finding is joined into a cross-cutting one.

## All findings

| ID | Title | Kind | Size | Lines (src / tests) | Risk | Tier | Package | Note |
|---|---|---|---|---|---|---|---|---|
| [X-01](cross-cutting.md) | one function for the job's source geometry (deinterlace before crop) | duplication | S | -12 / -0 | low | A | Q-6.10 | CMD-01+SRV-04+VAL-11 |
| [X-02](cross-cutting.md) | one Windows `PermissionError` retry for `os.replace` | duplication | S | -24 / -30 | low | B | Q-6.12 | MOD-04+QJ-02 |
| [X-03](cross-cutting.md) | `OwnerJobs.draft` calls `JobService.draft` with a validator | duplication | S | -14 / -0 | medium | B | Q-6.15 | CLI-03+QJ-03 |
| [X-04](cross-cutting.md) | the `_load` import hack in the batch and validation tests | tests | M | -0 / -495 | low | A | Q-6.1 | BAT-06+VAL-02 |
| [X-05](cross-cutting.md) | HDR display names and the multiplication sign in one place | duplication | S | -28 / -0 | low | A | Q-6.10 | CMD-13+BAT-17 |
| [X-06](cross-cutting.md) | the subtitle codec and extension tables in one place | duplication | S | -30 / -0 | low | A | Q-6.10 | CMD-03+VAL-07 subtitle part |
| [X-07](cross-cutting.md) | preset store and facade members that nothing calls | dead-code | M | -90 / -80 | low | B | Q-6.11 | MOD-02+SRV-03 |
| [X-08](cross-cutting.md) | one constructor of `TrackMetadata` from a stream | duplication | S | -28 / -8 | low | B | Q-6.13 | PRB-06+BAT-09 item 5 |
| [X-09](cross-cutting.md) | stop writing `SourceFingerprint.probe_hash` | dead-code | S | -17 / -10 | low | B | Q-6.13 | PRB-11+MOD-07b |
| [X-10](cross-cutting.md) | one "write through a temporary file and rename" helper | duplication | S | -15 / -0 | low | C | — | CLI-09+PRB-15 |
| [CLI-01](areas/cli-remote.md) | one helper for the "print one wrapped-off line" idiom and one for `warning:` lines | duplication | M | -75 / -0 | low | A | Q-6.3 |  |
| [CLI-02](areas/cli-remote.md) | `encode` and `batch` repeat the same preamble, options and display code | duplication | M | -20 / -0 | low | A | Q-6.3 | after CLI-01 |
| [CLI-03](areas/cli-remote.md) | `OwnerJobs.draft` is a second copy of `JobService.draft` | duplication | S | (in X-03) | medium | → X-03 | — |  |
| [CLI-04](areas/cli-remote.md) | the `reframe queue` actions repeat the owner connection and its clean-up; `connect_owner` passes folders that are the defaults | structure | S | -15 / -0 | low | A | Q-6.3 |  |
| [CLI-05](areas/cli-remote.md) | `run_encode` and `run_batch` read `REFRAME_IN_PROCESS` a second time, for callers that do not exist | defensive | S | -18 / -12 | low | A | Q-6.3 |  |
| [CLI-06](areas/cli-remote.md) | dead handling of `TaskFailed` in the fetch command | dead-code | S | -14 / -22 | low | A | Q-6.3 |  |
| [CLI-07](areas/cli-remote.md) | three `StrEnum` classes repeat values that the core already has as `Literal` types | reinvented | S | -11 / -0 | low | A | Q-6.3 |  |
| [CLI-08](areas/cli-remote.md) | `_read_regular_file` copies `reframe.textfile.open_regular` | duplication | S | -11 / -0 | low | A | Q-6.3 |  |
| [CLI-09](areas/cli-remote.md) | five hand-made "write a file through a temporary file and rename it" blocks | duplication | M | (in X-10) | medium | → X-10 | — | low conf; -15; Windows retry in caches) (same family as PRB-15 -> X note |
| [CLI-10](areas/cli-remote.md) | the ended and active job-state sets are defined four times; one constant has no use | duplication | S | -5 / -0 | low | A | Q-6.3 |  |
| [CLI-11](areas/cli-remote.md) | small repeats inside `cli.py` | duplication | S | -26 / -0 | low | A | Q-6.3 |  |
| [CLI-12](areas/cli-remote.md) | test helpers that repeat each other | tests | S | -0 / -28 | low | A | Q-6.3 | tests |
| [CLI-13](areas/cli-remote.md) | the client's protocol constants are written again in the server | duplication | S | -3 / -4 | low | C | — | -3; needs 0061 item 2 edit |
| [CLI-14](areas/cli-remote.md) | the lost-connection report reads each job's state from the owner or the saved queue (decision-change, low confidence) | decision-change | M | -24 / -35 | medium | C | — | decision-change; worse report |
| [BAT-01](areas/batch.md) | Two ways to resolve "a group" that only tests call | decision-change | M | -40 / -25 | low | B | Q-6.15 | decision-change 0040 §8 accepted: 0050 item 6 never exposed group; plan 05 line 11 only facade+models public |
| [BAT-02](areas/batch.md) | `merge_template`, `SECTIONS`, `SECTION_FIELDS` and `BatchService.merge` are used by tests only | decision-change | S | -34 / -20 | low | B | Q-6.15 | decision-change 0040 §8 accepted, same reason |
| [BAT-03](areas/batch.md) | Wrappers with no production use: `draft.py`, `explain`, `explain_subtitles`, `first_of_language` | dead-code | S | -47 / -5 | low | B | Q-6.15 | plan 05:538 + status edit |
| [BAT-04](areas/batch.md) | The compiled defaults build full `OutputTrackRule`s that nothing evaluates | decision-change | M | -30 / -15 | low | C | — | decision-change 0040 §1; possible F-13 follow-up use; rule 6 |
| [BAT-05](areas/batch.md) | `_explicit_audio` and `_explicit_subtitles` repeat one pipeline | duplication | M | -20 / -0 | medium | C | — | low-medium conf, medium risk, many strings |
| [BAT-06](areas/batch.md) | 14 test files load shared helper modules with the same `importlib` hack | tests | M | (in X-04) | low | → X-04 | — |  |
| [BAT-07](areas/batch.md) | `lint_defaults(source=…)` duplicates the "used rules" logic of `resolve_tracks` | dead-code | S | -18 / -5 | low | A | Q-6.6 |  |
| [BAT-08](areas/batch.md) | `resolve` and `resolve_with_tracks` are two functions for one job | layering | S | -22 / -0 | low | A | Q-6.6 |  |
| [BAT-09](areas/batch.md) | Small duplicates inside `batch/` | duplication | S | -34 / -2 | low | A | Q-6.6 | items 1-4,6-8; item 5 in X-08 |
| [BAT-10](areas/batch.md) | Small dead items | dead-code | S | -50 / -5 | low | A | Q-6.6 | minus item 4 |
| [BAT-11](areas/batch.md) | `ForeignAudio` carries four fields nobody reads | dead-code | S | -10 / -2 | low | A | Q-6.6 |  |
| [BAT-12](areas/batch.md) | The `container_codecs` flag runs through six signatures to hide one lint code | decision-change | M | -25 / -2 | low-medium | B | Q-6.15 | decision-change on mechanism only: 0040 R1-4 behaviour kept; medium conf |
| [BAT-13](areas/batch.md) | `grouping.compare` repeats its pairing code and two helpers repeat `video_key` | duplication | S | -5 / -0 | low | C | — | -5 |
| [BAT-14](areas/batch.md) | `TrackDescriptor.bitrate` has no reader | model-redundancy | S | -8 / -2 | low | C | — | HTTP change; 0040 open q1 may want the field |
| [BAT-15](areas/batch.md) | `matrix_columns` resolves an empty source to learn the column labels | structure | S | -3 / -0 | low | C | — | -3 |
| [BAT-16](areas/batch.md) | `status` and `issues` of a `Resolution` are kept in step by hand at four places | model-redundancy | S | -0 / -0 | low | C | — | 0 lines |
| [BAT-17](areas/batch.md) | cross-area: HDR display names are written four times, `_probe_issue` twice | duplication | S | (in X-05) | low | → X-05 | — |  |
| [VAL-01](areas/validation.md) | set the fix `target` once instead of passing it through 40 functions | structure | M | -110 / -0 | low | A | Q-6.5 |  |
| [VAL-02](areas/validation.md) | the tests load `scenario.py` with the same helper in 20 files | tests | M | (in X-04) | low | → X-04 | — |  |
| [VAL-03](areas/validation.md) | five template rules repeat a job rule with the same body | duplication | M | -45 / -0 | low | B | Q-6.16 |  |
| [VAL-04](areas/validation.md) | dead code and pass-through leftovers | dead-code | S | -50 / -30 | low | A | Q-6.5 |  |
| [VAL-05](areas/validation.md) | `encoder_issues` makes a fix that validation then unpacks and replaces | layering | S | -25 / -0 | low | A | Q-6.5 |  |
| [VAL-06](areas/validation.md) | the `container.unknown` rule and 15 `container is None` guards cover a state that cannot happen | decision-change | M | -55 / -14 | medium | B | Q-6.16 |  |
| [VAL-07](areas/validation.md) | facts written again next to the command builder (subtitle formats, HDR test) | duplication | S | -5 / -0 | low | B | Q-6.16 | HDR predicate part only; subtitle part in X-06 |
| [VAL-08](areas/validation.md) | the dry run builds the same "remove" fixes as `video.py` | duplication | S | -22 / -0 | low | A | Q-6.5 |  |
| [VAL-09](areas/validation.md) | small duplicates inside `video.py` and with `definitions` | duplication | S | -30 / -0 | low | B | Q-6.16 |  |
| [VAL-10](areas/validation.md) | two ways to ask "what value does x264 or x265 use for this option" | duplication | M | -30 / -0 | medium | C | — |  |
| [VAL-11](areas/validation.md) | the job's output geometry is computed in four places | duplication | S | (in X-01) | low | → X-01 | — |  |
| [VAL-12](areas/validation.md) | small leftovers | dead-code | S | -31 / -5 | low | B | Q-6.16 | item 2 rejected |
| [VAL-13](areas/validation.md) | decision-change: the charset cache of `LocalFileSystem` (0065 FA item 1, 0070 task A item 1) | decision-change | M | -75 / -35 | medium | C | — |  |
| [VAL-14](areas/validation.md) | decision-change: NUL paths are handled in every layer (0016 RN) | decision-change | L | -70 / -200 | medium | C | — |  |
| [QJ-01](areas/queue-jobs.md) | TaskManager has a hand-made semaphore, a runtime `set_limit` and a plain-JSON result path that nothing uses | speculative-generality | S | -45 / -24 | low | B | Q-6.18 | swaps a hand-made gate for asyncio.Semaphore: task cancel path, rule 1 caution; conf medium |
| [QJ-02](areas/queue-jobs.md) | The Windows `PermissionError` retry for `os.replace` is written twice, with the same constants | duplication | M | (in X-02) | low | → X-02 | — |  |
| [QJ-03](areas/queue-jobs.md) | `OwnerJobs.draft` repeats `JobService.draft` | duplication | S | (in X-03) | low | → X-03 | — |  |
| [QJ-04](areas/queue-jobs.md) | Members of `queue/` that no production code uses | dead-code | S | -31 / -5 | low | A | Q-6.9 |  |
| [QJ-05](areas/queue-jobs.md) | Members of `jobs.py` and `mediatask.py` that no production code uses | dead-code | S | -20 / -6 | low | A | Q-6.9 | items 1-3 and the protocol member; item 4 is C |
| [QJ-06](areas/queue-jobs.md) | The same three service protocols are written three times | duplication | S | -22 / -0 | low | A | Q-6.9 |  |
| [QJ-07](areas/queue-jobs.md) | The store refuses a too-deep document when it writes; a refusal at `add` would remove that machinery | decision-change | M | -45 / -60 | medium | C | — | decision-change, behaviour change, low conf |
| [QJ-08](areas/queue-jobs.md) | Four copies of the same `ToolsService` stub and two of the same `CapabilityService` stub in the tests | tests | S | -0 / -40 | low | A | Q-6.9 | tests |
| [QJ-09](areas/queue-jobs.md) | `closed_error()` and two more lazy imports exist only to reach one exception class | structure | S | -13 / -0 | low | A | Q-6.9 |  |
| [QJ-10](areas/queue-jobs.md) | "Tool is found and has a path" is written seven times | duplication | S | -6 / -0 | low | B | Q-6.18 | -6; consolidation, no concept removed |
| [QJ-11](areas/queue-jobs.md) | The "private store in memory" is `read_only` with extra steps | structure | S | -10 / -0 | low | A | Q-6.9 | removes the memory-store concept |
| [QJ-12](areas/queue-jobs.md) | Defensive branches for a call outside an event loop | defensive | S | -8 / -0 | low | C | — | low conf |
| [QJ-13](areas/queue-jobs.md) | `HeaderEditResult.file_state` is optional, but the writer always sets it | defensive | S | -8 / -0 | low | C | — | low conf, 0080 note |
| [QJ-14](areas/queue-jobs.md) | Three functions over the default complexity limits can be split without changing behaviour | structure | M | -0 / -0 | low | C | — | 0 lines |
| [SRV-01](areas/server-service.md) | The folder probe is unused in the core, and the "probe N files at once" loop exists three times | dead-code | M | -170 / -215 | low | B | Q-6.14 |  |
| [SRV-02](areas/server-service.md) | Ship no pre-rendered language list (decision 0071 item 2 no longer holds after 0082) | decision-change | S | -15 / -6 | low | B | Q-6.14 | decision-change 0071 item 2; 0082 replaced the reason, measured 9-11 ms first request; new record in pkg |
| [SRV-03](areas/server-service.md) | Public members of the facade and the preset store that nothing uses | dead-code | M | (in X-07) | low | → X-07 | — |  |
| [SRV-04](areas/server-service.md) | The "deinterlace makes the grid progressive" rule is written five times | duplication | S | (in X-01) | low | → X-01 | — |  |
| [SRV-05](areas/server-service.md) | Test helpers copied between files | tests | M | -0 / -100 | low | A | Q-6.2 | tests |
| [SRV-06](areas/server-service.md) | `SourceService`: duplicated start-up of a probe, and a per-file lock map | structure | XS | -6 / -0 | low | C | — | XS, medium conf |
| [SRV-07](areas/server-service.md) | Clip Range answers: use `FileResponse` (decision 0049 item 4) | decision-change | M | -55 / -45 | medium | C | — | decision-change 0049 item 4, HTTP change, low conf |
| [SRV-08](areas/server-service.md) | Small leftovers in the server package | dead-code | S | -16 / -2 | low | B | Q-6.14 | touches the 0046 jail helper |
| [MOD-01](areas/models-persistence.md) | SettingsStore and PresetStore repeat the load-failure handling | duplication | M | -35 / -0 | medium | B | Q-6.11 | file keep/replace logic; medium risk; small text change in warning detail |
| [MOD-02](areas/models-persistence.md) | Preset store and service API that nothing calls | dead-code | M | (in X-07) | low | → X-07 | — | plan C-9 + 0015 §2 + 0050 item 10 name duplicate/rename; plan edit in 0083 |
| [MOD-03](areas/models-persistence.md) | `PresetStore._load` and `_incoming` read a preset file twice, in two copies | structure | M | -25 / -0 | medium | B | Q-6.11 | medium risk/conf; after MOD-01 |
| [MOD-04](areas/models-persistence.md) | The Windows `PermissionError` retry is written twice (cross-area: queue) | duplication | S | (in X-02) | low | → X-02 | — |  |
| [MOD-05](areas/models-persistence.md) | A `registry=` argument on two stores, kept only for tests | speculative-generality | S | -22 / -30 | low | B | Q-6.11 | test-cache subtlety; medium test risk |
| [MOD-06](areas/models-persistence.md) | Small dead and duplicate pieces | dead-code | S | -30 / -30 | low | A | Q-6.7 | item 3 rejected |
| [MOD-07](areas/models-persistence.md) | Two persisted fields that no code reads | dead-code | M | -8 / -0 | low | C | — | (a) C; (b) in X-09 |
| [MOD-08](areas/models-persistence.md) | `drain` and `nested` test helpers copied into many test files | tests | S | -0 / -30 | low | A | Q-6.2 | tests |
| [MOD-09](areas/models-persistence.md) | The `media_source` migration and two document kinds that no reader calls | decision-change | S | -25 / -25 | low | C | — | decision-change; 0081 review kept it |
| [MOD-10](areas/models-persistence.md) | Per-preset nesting limit makes the preset file read more complex | decision-change | S | -25 / -30 | medium | C | — | decision-change; behaviour change |
| [PRB-01](areas/probe-metadata.md) | `languages.search`, `picker_label` and `entry` have no product caller | decision-change | M | -95 / -245 | low | C | — | decision-change: 0082 + 0065 items 1,3 name search/picker_label as TS picker reference; reason still applies |
| [PRB-02](areas/probe-metadata.md) | `ProbeCache` memory layer costs more than it saves | concurrency | S | -28 / -25 | low | B | Q-6.13 | edge behaviour change: read-only cache folder re-probes |
| [PRB-03](areas/probe-metadata.md) | EBML basics exist four times (IDs, child walker, read loop, Seek entries) | duplication | S | -30 / -0 | low | B | Q-6.13 | header writer writes into user files: rule 1 caution; -30 |
| [PRB-04](areas/probe-metadata.md) | `start_probe_folder` is an unused second copy of the service's folder task | dead-code | S | -22 / -45 | low | A | Q-6.8 |  |
| [PRB-05](areas/probe-metadata.md) | `MATROSKA_READER` and the cache `options` plumbing are covered by the source hash | decision-change | S | -24 / -22 | low | C | — | decision-change 0007 RB-7; parser fingerprint does cover it, but -24 lines for reversing an explicit sentence + cache churn: rule 5/6 |
| [PRB-06](areas/probe-metadata.md) | three constructors of `TrackMetadata` from a stream, and an unused `remux_job` parameter | duplication | S | (in X-08) | low | → X-08 | — | one edge behaviour change |
| [PRB-07](areas/probe-metadata.md) | EBML test builders written four times | tests | M | -0 / -30 | low | A | Q-6.2 | tests; medium only on size |
| [PRB-08](areas/probe-metadata.md) | `batch.descriptors.CODEC_LABELS` copies `probe/names.py` | duplication | S | -20 / -0 | low | B | Q-6.13 | label text changes, user-visible, improves |
| [PRB-09](areas/probe-metadata.md) | file checks of a probe written twice (service and prober) | duplication | S | -8 / -0 | low | A | Q-6.8 | dup concept, small |
| [PRB-10](areas/probe-metadata.md) | the language-tag shape is checked in four places | duplication | S | -10 / -0 | low | A | Q-6.8 | dup concept, small |
| [PRB-11](areas/probe-metadata.md) | `layout_hash` / `SourceFingerprint.probe_hash` is written and never read | decision-change | S | (in X-09) | low | → X-09 | — |  |
| [PRB-12](areas/probe-metadata.md) | small leftovers in the prober and sampler | structure | S | -25 / -6 | low | B | Q-6.13 | medium conf |
| [PRB-13](areas/probe-metadata.md) | the fake-prober helper is written four times in the probe tests | tests | S | -0 / -20 | low | A | Q-6.8 | tests |
| [PRB-14](areas/probe-metadata.md) | small duplicates in `textfile.py` and `chapters.py` | duplication | S | -12 / -0 | low | B | Q-6.13 | medium conf |
| [PRB-15](areas/probe-metadata.md) | two folder-of-JSON caches with their own atomic write and prune | duplication | M | (in X-10) | low | → X-10 | — | low conf, Windows |
| [CMD-01](areas/command.md) | The deinterlace-before-crop geometry rule is written five times | duplication | S | (in X-01) | low | → X-01 | — | one rule in 5 places -> 1; concept |
| [CMD-02](areas/command.md) | `CapabilityService` and `DetectionOptions` have parameters and members that nothing uses | dead-code | S | -39 / -6 | low | A | Q-6.10 | adjusted: keep closest_available/definitions/detecting |
| [CMD-03](areas/command.md) | The subtitle codec and extension tables are copied between areas, and one table is an identity map | duplication | S | (in X-06) | low | → X-06 | — |  |
| [CMD-04](areas/command.md) | Hardware placeholder fill exists three times, with a defensive error type for states the linter already forbids | duplication | S | -22 / -16 | low | A | Q-6.10 |  |
| [CMD-05](areas/command.md) | `parse.py` returns fields that nothing reads | dead-code | S | -25 / -12 | low | A | Q-6.10 |  |
| [CMD-06](areas/command.md) | Dead fields, aliases and pass-through wrappers in `command/` | dead-code | S | -35 / -5 | low | A | Q-6.10 | minus render_tag |
| [CMD-07](areas/command.md) | The cache write has its own task set, shield and wait protocol | concurrency | S | -17 / -70 | medium | B | Q-6.18 | loop-blocking write: judgement, medium risk |
| [CMD-08](areas/command.md) | The cache key hashes the detection source files and the definitions | decision-change | S | -30 / -28 | low | C | — | decision-change 0008; dev-checkout reason still applies |
| [CMD-09](areas/command.md) | The capability cache itself buys about a second per start | decision-change | L | -400 / -650 | medium | C | — | decision-change, user-visible, low conf |
| [CMD-10](areas/command.md) | Five copies of "every encoder available" test helper | tests | S | -0 / -35 | medium | C | — | tests; 7 params; low conf |
| [CMD-11](areas/command.md) | `jobtype.py` decides "is this track copied" twice | duplication | S | — | low | rejected | — | rejected in verify: the two loops differ (SRT into MP4) |
| [CMD-12](areas/command.md) | `build_plan` is one 86-statement function | structure | M | -0 / -0 | medium | C | — | 0 lines, medium risk, argv is the product; rule 5 |
| [CMD-13](areas/command.md) | HDR format labels three times, the multiplication sign twice | duplication | S | (in X-05) | low | → X-05 | — | small dup |
| [TP-01](areas/tools-platform.md) | `scripts/fetch-tools.py` repeats `reframe.tools.fetch` (decision 0038 item 4) | decision-change | L | -290 / -400 | medium | C | — | decision-change 0038 item 4; reason "no path tricks" still applies, verifier |
| [TP-02](areas/tools-platform.md) | `ToolsService._discover` repeats `discover_tools`; `discover_tools_sync` is a wrapper | duplication | S | -35 / -3 | low | A | Q-6.7 |  |
| [TP-03](areas/tools-platform.md) | `run` and `run_streaming` have options that no production caller uses | dead-code | S | -25 / -50 | low | B | Q-6.17 | plan sketch 05-core.md:67 must change |
| [TP-04](areas/tools-platform.md) | two fake D-Bus servers and three copies of the fd and socket leak helpers in the platform tests | tests | M | -0 / -70 | low | A | Q-6.2 | tests |
| [TP-05](areas/tools-platform.md) | leftovers of the MKVToolNix / MediaInfo removal: `root=None` and `BUNDLED_SUBDIRS` | decision-change | S | -8 / -25 | low | C | — | root=None is 0081 item 3 on purpose; BUNDLED_SUBDIRS ~3 lines, little value |
| [TP-06](areas/tools-platform.md) | `dbus.py` and `sleep.py` features that no call needs | speculative-generality | S | -30 / -30 | low | B | Q-6.17 | medium conf; little-endian narrowing |
| [TP-07](areas/tools-platform.md) | members that only tests use | dead-code | S | -20 / -20 | low | A | Q-6.7 |  |
| [TP-08](areas/tools-platform.md) | `CancelToken.reason` is written at 13 call sites and read 0 times | dead-code | S | -10 / -6 | low | A | Q-6.9 | touches 9 files |
| [TP-09](areas/tools-platform.md) | `platform/notify.py` is a pass-through | layering | S | -14 / -12 | low | B | Q-6.17 | medium conf |
| [TP-10](areas/tools-platform.md) | the "finish after the swap" logic of `tools fetch` (decision 0038 R5-5) | decision-change | S | -37 / -60 | low | C | — | decision-change 0038 R5-5; reason still applies, only asks owner to accept stale status |
| [TP-11](areas/tools-platform.md) | drop the logind backend, and with it D-Bus file-descriptor passing (decision 0022 item 2) | decision-change | L | -200 / -400 | medium | C | — | decision-change, low conf, behaviour change |
| [TP-12](areas/tools-platform.md) | replace the stdlib D-Bus client with `jeepney` (decision 0011 item 1) | decision-change | L | -490 / -700 | high | C | — | new dependency, high risk |
| [TP-13](areas/tools-platform.md) | `launch_detached` returns a pid, so `owner._start` wraps `Popen` to get the handle back (cross-area: remote) | duplication | S | -5 / -0 | medium | C | — | low conf, Windows, -5 |
| [TP-14](areas/tools-platform.md) | the Windows execution-state thread is built as a command queue | structure | S | -25 / -0 | medium | B | Q-6.12 | Windows-only, VM check |
| [TP-15](areas/tools-platform.md) | two identical helpers in the platform package | duplication | S | -12 / -0 | low | B | Q-6.12 |  |
| [NDP-01](areas/naming-definitions.md) | `definitions/__init__.py` and `models.py` list the same names three times | duplication | S | -99 / -0 | low | A | Q-6.4 |  |
| [NDP-02](areas/naming-definitions.md) | `definitions/lint.py` is test-only code in the shipped package | layering | S | -1 / -0 | low | A | Q-6.4 | 669 lines leave the shipped package |
| [NDP-03](areas/naming-definitions.md) | Names and parameters with no production caller (no contract change) | dead-code | S | -26 / -4 | low | A | Q-6.4 | note: 0008:203 names supported_options; behaviour stays in mapping_supported |
| [NDP-04](areas/naming-definitions.md) | Three shipped model fields that are derived or never read (OpenAPI touched) | model-redundancy | S | -10 / -10 | low | B | Q-6.19 | +17 TOML lines, -3 frontend |
| [NDP-05](areas/naming-definitions.md) | Test fixtures and helpers copied between the analysis, preview and naming tests | tests | M | -0 / -60 | low | A | Q-6.2 | tests |
| [NDP-06](areas/naming-definitions.md) | The analysis tasks repeat the "run the tool, check the result" block five times | duplication | S | -10 / -1 | low | A | Q-6.4 |  |
| [NDP-07](areas/naming-definitions.md) | The loudnorm measurements are stored by two copies of one loop (cross-area: queue) | duplication | S | -1 / -0 | low | C | — | -1, message text changes, low conf |
| [NDP-08](areas/naming-definitions.md) | Inside the linter: a typed mapping, one mapping-to-target helper, one fallback-chain check, guards for empty tables | duplication | S | -18 / -0 | low | A | Q-6.4 | without _lint_chain |
| [NDP-09](areas/naming-definitions.md) | `render_value` carries a `root` parameter that nothing passes, and repeats the head of `resolve_output_name` | duplication | XS | -2 / -0 | low | C | — | -2 |
| [NDP-10](areas/naming-definitions.md) | Long functions that do many steps in a row | structure | L | -0 / -0 | medium | C | — | 0 lines |
| [NDP-11](areas/naming-definitions.md) | Small leftovers | defensive | S | -8 / -0 | low | B | Q-6.19 | -8 leftovers |
