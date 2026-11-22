# Cross-cutting findings

Commit: 85d9dcb. These findings cross areas. Each one joins two or three area findings that
describe the same code from two sides. The area entries keep the details (anchors, callers,
tests); the entry here says which shape to make, which tier it has and which work package makes
it. An implementation agent reads this entry **and** the area entries it names.

Line estimates here count each line once (the area entries overlap).

### X-01: one function for the job's source geometry (deinterlace before crop)
- Kind: duplication
- Joins: [CMD-01](areas/command.md), [SRV-04](areas/server-service.md), [VAL-11](areas/validation.md)
- Where: `command/builder.py:190-193` (`_video_plan`), `preview/graph.py:131-140` (`job_video_graph`), `validation/context.py:63-82` (`JobContext.geometry`, `source_geometry`), `batch/resolve.py:84-88` (`output_size`), `reframe_server/routers/jobs.py:279-290` (`geometry`).
- Now: five places build the source geometry and turn `interlaced` off when the job deinterlaces before the crop. The three audits found the same five copies.
- Change: the shape of CMD-01. Add `job_source_geometry(stream, job)` and `job_geometry(stream, job)` to `reframe/dimensions.py`. The builder, the preview and batch call `job_geometry`; `JobContext.source_geometry` calls `job_source_geometry`; the server route keeps `source=source_geometry(stream)` (the real field order is shown) and uses `job_geometry` for the grid (SRV-04's server line). CMD-01's `encoder_and_pix_fmt` helper in `command/video.py` is part of this change. VAL-11's three-argument signature is not used.
- Behaviour: unchanged.
- Contracts touched: public core API (two new functions). HTTP: none (`POST /api/jobs/geometry` answers the same).
- Callers to update: the five places above.
- Tests: the 73 plan snapshots (`tests/command/test_snapshots.py`), `tests/dimensions/test_properties.py`, the server's geometry tests. Add one test for `job_source_geometry`.
- Decision records: 0009 (dimension maths), 0067 (picture). The rule itself does not change.
- Size: S; estimated lines: -12 / 0
- Risk: low. A wrong move changes the crop grid of interlaced sources; the snapshots catch it.
- Depends on: none. In Q-6.10, make it before CMD-04 (both edit `_video_plan`).
- Confidence: high
- Verdict: all three CONFIRMED or ADJUSTED in verify (only anchors and counts).
- Tier: A. Work package: Q-6.10.

### X-02: one Windows `PermissionError` retry for `os.replace`
- Kind: duplication
- Joins: [MOD-04](areas/models-persistence.md), [QJ-02](areas/queue-jobs.md)
- Where: `settings.py:55-60, 98-121` (`REPLACE_ATTEMPTS`, `REPLACE_DELAY`, `_replace`, `_sleep`, `replace_file`); `queue/files.py:35-60, 161-163` (`ATTEMPTS`, `DELAY`, `_sleep`, `_retry`, `replace_file`).
- Now: the same retry, with the same constants, exists twice.
- Change: MOD-04's change: one leaf module (`reframe/fsretry.py`) with the retry; both callers use it. `settings.WINDOWS` and `files.WINDOWS` stay (they also serve `_sync_folder` and `rename_no_replace`). Take the full test-seam list from QJ-02's verdict (`tests/presets/test_store.py:273,470,632`, `reframe-server/tests/test_owner.py:378`).
- Behaviour: unchanged.
- Contracts touched: none outside tests.
- Callers to update: see MOD-04 and QJ-02.
- Tests: the two retry test groups merge into one; the mocked Windows tests stay.
- Decision records: 0015, 0016, 0070 (Windows testing phase).
- Size: S; estimated lines: -24 / -30
- Risk: low on Linux. **Windows-only path: needs a check on the Windows test VM** (the retry tests, and the owner-publish test `reframe-server/tests/test_owner.py:365-390`).
- Depends on: Q-6.11 (it edits `settings.py` first).
- Confidence: high
- Tier: B (Windows VM check). Work package: Q-6.12.

### X-03: `OwnerJobs.draft` calls `JobService.draft` with a validator
- Kind: duplication
- Joins: [CLI-03](areas/cli-remote.md), [QJ-03](areas/queue-jobs.md)
- Where: `cli.py:1298-1363` (`OwnerJobs.draft`, `_Drafts`); `jobs.py:348-385` (`JobService.draft`).
- Now: the CLI client builds a draft with a second copy of `JobService.draft`.
- Change: QJ-03's shape: `JobService.draft(..., validate=None)`; `OwnerJobs.draft` probes first (a `ProbeError` is returned before an unknown preset name raises, as now), then calls `app.jobs.draft(media, chosen, output=output, validate=self._validate)`. CLI-03's shorter snippet changes the error order and is not used.
- Behaviour: unchanged.
- Contracts touched: public core API (one optional keyword). HTTP: none (the server does not pass it).
- Callers to update: `cli.py` only.
- Tests: the client-mode tests in `tests/remote/` and the draft equality test stay as the guard.
- Decision records: 0042, 0061.
- Size: S; estimated lines: -14 / 0
- Risk: medium. `JobService.draft` is used by the server and the desktop.
- Depends on: BAT-12 changes the same draft path (the `container_codecs` flag); both are in Q-6.15.
- Confidence: medium (CLI-03 CONFIRMED, QJ-03 ADJUSTED)
- Tier: B. Work package: Q-6.15.

### X-04: the `_load` import hack in the batch and validation tests
- Kind: tests
- Joins: [BAT-06](areas/batch.md), [VAL-02](areas/validation.md)
- Where: 15 files in `tests/batch/` (plus `tests/jobs/test_cli_batch.py`) and 20 files in `tests/validation/` define the same `_load(name)` helper to import a shared helper module (`anime.py`, `defaults_tracks.py`, `scenario.py`).
- Now: each file repeats an 11- to 14-line `importlib` loader.
- Change: use relative imports. VAL-02 checked `from . import scenario as sc` under the repository's pytest import mode, for the whole folder and for one file. BAT-06 proposes to move the batch helpers into `reframe_testing`; its verifier notes that an `__init__.py` in `tests/batch/` with `from . import anime as A` (as `tests/jobs/` already does) is cheaper. Try the `__init__.py` way first for both folders; fall back to BAT-06's move only if it fails. Check with `uv run pytest packages/reframe/tests/batch packages/reframe/tests/validation` and with one file run alone, and with `uv run mypy`.
- Behaviour: unchanged (tests only).
- Contracts touched: none.
- Callers to update: the 35 test files; `tests/jobs/test_cli_batch.py` (`_load_anime`, `PRESET_FILE`); `test_lint.py:519` (JSON path).
- Tests: the same tests run; none is deleted.
- Decision records: 0004 (shared testing package).
- Size: M; estimated lines: 0 / -495
- Risk: low. A module run twice under two names would show as a duplicate-class error in a test.
- Depends on: none. Make it first: later packages edit these test files.
- Confidence: high
- Tier: A. Work package: Q-6.1.
- Note (Q-6.1): partly skipped. `tests/jobs/test_cli_batch.py` (`_load_anime`) and `tests/validation/test_command_agreement.py` (`_load_command_tests`) keep their by-path loaders: pytest names a module in a folder with `__init__.py` from its topmost package (`jobs.test_cli_batch`, `validation.test_command_agreement`), so `from ..batch import anime` fails with "attempted relative import beyond top-level package". BAT-06's move into `reframe_testing` was not made for one consumer (rules 5, 6).

### X-05: HDR display names and the multiplication sign in one place
- Kind: duplication
- Joins: [CMD-13](areas/command.md), [BAT-17](areas/batch.md)
- Where: `cli.py:228-233` (`_HDR_NAMES`), `cli.py:218` (`TIMES`), `validation/filters.py:34-39, 237` (`_HDR_LABELS`), `preview/graph.py:86-91` (`_hdr_name`), `batch/grouping.py:233-235` (`_hdr`); `dimensions.py:50` (`TIMES`). BAT-17 also names the two `_probe_issue` copies.
- Now: the map `{hdr10: "HDR10", hdr10plus: "HDR10+", hlg: "HLG", dolby_vision: "Dolby Vision"}` is written four times; `TIMES` twice.
- Change: a `label` property on `HdrFormat` (a property adds no schema field) used by the four places; `cli.py` imports `TIMES` from `reframe.dimensions` and `tests/test_cli.py:28` imports it from there too (mypy strict reads the tests). `naming/context.py:53` `_HDR_LABELS` is not a copy (short tokens) and stays. BAT-17's `_probe_issue` part is made here too.
- Behaviour: unchanged.
- Contracts touched: none (no schema change).
- Callers to update: the places above.
- Tests: none deleted; the CLI, batch and preview tests are the guard.
- Decision records: none.
- Size: S; estimated lines: -28 / 0
- Risk: low.
- Depends on: Q-6.3 (it edits `cli.py` first).
- Confidence: high
- Tier: A. Work package: Q-6.10.

### X-06: the subtitle codec and extension tables in one place
- Kind: duplication
- Joins: [CMD-03](areas/command.md), the subtitle-set part of [VAL-07](areas/validation.md)
- Where: `command/subtitles.py:33-50` (`EXTERNAL_CODECS`, `_BITMAP_CODECS`, `FORMAT_ENCODERS`, `_SAME_FORMAT`), `validation/tracks.py:33-46` (`BITMAP_CODECS`, `FORCED_ONLY_CODECS`, `EXTERNAL_FORMATS`), and the other copies CMD-03 lists.
- Now: the bitmap subtitle set exists five times, the external extension table twice, the forced-only set twice, and `FORMAT_ENCODERS` is an identity map.
- Change: CMD-03's change; validation imports the sets from `reframe.command.subtitles` (VAL-07's subtitle part). `EXTERNAL_CODECS` has the same keys in the same order as `EXTERNAL_FORMATS`, so the `subtitle.external_unknown` message does not change. VAL-04 deletes `BITMAP_CODECS` first (Q-6.5).
- Behaviour: unchanged.
- Contracts touched: public core API (module names move; `tests/validation/test_ffmpeg.py:12` imports `FORCED_ONLY_CODECS`).
- Callers to update: see CMD-03 and VAL-07.
- Tests: none deleted.
- Decision records: 0026 (builder and validation agree): one table makes that agreement structural.
- Size: S; estimated lines: -30 / 0
- Risk: low.
- Depends on: Q-6.5 (VAL-04).
- Confidence: high
- Tier: A. Work package: Q-6.10.

### X-07: preset store and facade members that nothing calls
- Kind: dead-code
- Joins: [MOD-02](areas/models-persistence.md), [SRV-03](areas/server-service.md)
- Where: `presets/store.py` (`PresetStore.rename`, `duplicate`, `default_id`, `builtins=`, `_free_name`), the `PresetService` members `rename`, `duplicate`, `store`, and the other facade members SRV-03 lists (`tools.versions`, `tools.discovering`, `settings.path`, …: 9 in all).
- Now: no production caller in the core, the server, the CLI, the frontend or the desktop.
- Change: delete them as MOD-02 and SRV-03 describe. Keep `builtins=[]` at `test_store.py:516` as a test seam (it guards the built-in cache against a swapped registry) or replace it as MOD-05 describes (same package). Edit the "Not exposed" table of `docs/plan/06-web-app.md` (four own rows plus two combined rows), `docs/status.md:66`, and write a decision record that notes the change to 0015 §2 ("duplicating one makes a user preset in the Custom category") and 0050 item 10.
- Behaviour: unchanged for every user.
- Contracts touched: public core API only. No HTTP, CLI or persisted change.
- Callers to update: tests only (`test_store.py`, `test_service_settings.py` after line 397, `reframe-server/tests/test_queue.py:294` reads `settings.path`).
- Tests: delete the tests of the removed members; `test_facade_coverage.py` must still pass (its plan-row check).
- Decision records: 0015 §2, 0050 item 10 (amended by the new record).
- Size: M; estimated lines: -90 / -80
- Risk: low.
- Depends on: none.
- Confidence: high
- Tier: B (the plan's C-9 lists "duplicate"; rule 7: no client uses these members: 0 callers outside tests in the core, the server, the CLI, `frontend/src` and `desktop/`). Work package: Q-6.11.

### X-08: one constructor of `TrackMetadata` from a stream
- Kind: duplication
- Joins: [PRB-06](areas/probe-metadata.md), item 5 of [BAT-09](areas/batch.md)
- Where: `metadata/__init__.py:24-61` (`source_video_metadata`, `remux_job(definitions=)`), `batch/resolve.py:59-74` (`video_metadata`), `batch/metadata.py:30-59`.
- Now: three ways build `TrackMetadata` from a stream; for video the language rule differs from audio and subtitles.
- Change: PRB-06's change. `video_metadata` stays as a thin wrapper (it is re-exported by `reframe.batch` and `reframe.jobs` and used in `tests/jobs/test_service.py`). `docs/core-breakdown.md:205` names the old signature; it is a work-breakdown record and does not change.
- Behaviour: changes in one edge case: a video stream whose `language_ietf` is not a valid tag but whose `language` is now gets the valid one (as audio and subtitles do). This changes the video language in the encode command and in `TrackDescriptor.language` for that file.
- Contracts touched: the encode command for that edge case; no schema change.
- Callers to update: see PRB-06.
- Tests: add one test for the edge case; the batch and metadata tests stay.
- Decision records: 0034, 0065.
- Size: S; estimated lines: -28 / -8
- Risk: low.
- Depends on: none.
- Confidence: high
- Tier: B (a behaviour change, even if it fixes an inconsistency). Work package: Q-6.13.

### X-09: stop writing `SourceFingerprint.probe_hash`
- Kind: dead-code
- Joins: [PRB-11](areas/probe-metadata.md), part (b) of [MOD-07](areas/models-persistence.md)
- Where: `probe/parse.py:591-606, 682-683` (`layout_hash`, its call, `__all__` at :54, the `hashlib`/`json` imports); `models/media.py:69-70` (`SourceFingerprint.probe_hash`).
- Now: `layout_hash` is computed for each probe and stored in the fingerprint; no code reads it. The service compares only `size` and `mtime`.
- Change: the cheap option of PRB-11 (MOD-07 (b)): delete `layout_hash` and its call; keep `probe_hash` declared and optional, with a docstring that says this version does not write it. No `schema_version` change (an optional field that is no longer written needs none; older rows and cache entries that carry it stay valid). Regenerate the probe snapshots (`tests/probe/__snapshots__/test_snapshots.ambr`, 61 values become `None`) and read the diff. Edit the sketch in `docs/plan/05-core.md:115` ("path + fingerprint (size, mtime)").
- Behaviour: `reframe probe --json` and the API's source responses show `"probe_hash": null`. Nobody reads it (checked in `frontend/src`, `desktop/`). Editing `parse.py` changes the probe cache's parser fingerprint, so each cached probe runs once more.
- Contracts touched: CLI `--json` and HTTP response values (not the schema).
- Callers to update: see PRB-11 and MOD-07.
- Tests: delete `test_fingerprint_gets_the_layout_hash`, add a pass-through check; `test_prober.py:96` drops one assert.
- Decision records: none names the hash; the plan sketch does.
- Size: S; estimated lines: -17 / -10
- Risk: low.
- Depends on: none.
- Confidence: medium (the plan names the field)
- Tier: B (a value a user can see changes; the plan sketch changes). Work package: Q-6.13.

### X-10: one "write through a temporary file and rename" helper
- Kind: duplication
- Joins: [CLI-09](areas/cli-remote.md), [PRB-15](areas/probe-metadata.md)
- Where: `cli.py:3609-3620` (`write_text_file`), `settings.py:174-190` (`JsonDocumentFile.write`), `capabilities/cache.py:165-200`, `probe/cache.py:181-268`.
- Now: four hand-made atomic writes; the two caches also prune by temporary-file names.
- Change: none planned. A shared helper needs `prefix`, `suffix`, `encoding`, `durable` and the prune rules as parameters; the saving is about 15 lines, and the caches would get the Windows retry (a Windows VM check).
- Tier: C (low confidence, small saving, a Windows-only change). Not planned.
