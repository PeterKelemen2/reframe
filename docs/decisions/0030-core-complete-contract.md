# 0030 — The core-complete contract: facade methods, task context, new models

- Status: accepted; superseded in part by [0044](0044-code-review-follow-ups.md) (`sources.frame` and `jobs.preview_clip_path` are async)
- Date: 2026-10-15
- Steps: C-15 (facade), C-10, C-12, C-13, C-6, C-14, C-11

## Context

[05 §C-15](../plan/05-core.md#c-15-service-facade-and-cli) sketches the facade with one comment
per service: `sources: … frames, cropdetect, scans`, `jobs: … preview_clip (C-10)`,
`batch: BatchService # group, derive, resolve`. The routes of
[06 §S-2](../plan/06-web-app.md#s-2-rest-api) need more than that sketch names: the frame image
by key (`GET /api/preview/frames/{key}.png`), the clip file by id (`GET /api/preview/clips/{id}`),
the live preview of the defaults (`POST /api/presets/defaults/preview`), and nothing in the
sketch runs the when-done power actions, the custom-parameter dry run of 03 §Advanced encoder
options, or `reframe tools fetch`.

Seven tasks build the open core steps in parallel ([core-breakdown.md](../core-breakdown.md),
[0029](0029-core-before-the-ui-milestones.md)). Two of them (the C-10 scans and the C-10
picture tasks) would both add methods to `SourceService`, three would add methods to
`JobService`, and the C-10 tasks share how a task gets the tools, the source and the cache. So
the lead fixes these signatures first, as stubs that the tasks fill in.

## Decision

1. **Facade methods** (all in `reframe/service.py` and `reframe/jobs.py`, written by the lead;
   each delegates to a function in the module of the task that builds it):

   | Method | Result | Built by |
   |--------|--------|----------|
   | `sources.bitrate_scan(path, stream_index)` | `TaskInfo` → `BitrateScan` | C-10 scans |
   | `sources.subtitle_scan(path, stream_indexes=None)` | `TaskInfo` → `SubtitleScan` | C-10 scans |
   | `sources.loudness_scan(path, stream_index, *, start=None, duration=None)` | `TaskInfo` → `LoudnessMeasurement` | C-10 scans |
   | `sources.frames(path, *, count=None, timestamps=None, job=None)` | `TaskInfo` → `FrameSet` | C-10 picture |
   | `sources.frame(key)` | `Path \| None` | C-10 picture |
   | `sources.cropdetect(path, *, count=None)` | `TaskInfo` → `CropDetection` | C-10 picture |
   | `sources.store(source)` | measured values kept in memory and in the probe cache | lead |
   | `jobs.preview_clip(job, *, start, seconds)` | `TaskInfo` → `PreviewClip` | C-10 picture |
   | `jobs.preview_clip_path(clip_id)` | `Path \| None` | C-10 picture |
   | `jobs.explain(source, template=None, *, container=None)` | `TrackDraft \| ProbeError` | lead (C-12 fills `draft_tracks`) |
   | `jobs.draft_remux(source, preset=None, *, edit_in_place=True)` | `JobDraft \| ProbeError` | lead (C-13 fills `remux_job`) |
   | `jobs.search_options(encoder_id, query)` | `list[EncoderOption]` | C-6 |
   | `jobs.hdr_metadata(job, source)` | `list[JsonPatchOp]` | lead (C-6 fills `hdr_options`) |
   | `jobs.dry_run(job, source=None)`, `jobs.plan(…, *, dry_run=False)` | `list[ValidationIssue]` | C-6 |
   | `tools.fetch(*, build="default", platform=None, manifest=None)` | `TaskInfo` → `ToolFetchResult` | C-15 |
   | `Reframe.power` (`PowerService`: `schedule`, `cancel`, `pending`, `close`) | | C-14 |

   `Reframe.batch` (`BatchService`) is added with the batch engine (wave 2), with the same
   approach.
2. **One task context.** The C-10 functions get a `reframe.mediatask.MediaTaskContext` (task
   manager, tools, sources, capabilities, settings, events, cache folder, definitions) and
   start their own task. `TaskFailed` inside a task is an expected failure: the task ends
   `failed` with the message as `TaskInfo.error`. `sample_timestamps(duration, count)` gives
   the sample frames (5 % to 95 %, evenly spaced), the same for frames and crop detection.
   The default concurrency limits of the new task kinds are in `reframe.tasks.DEFAULT_LIMITS`.
3. **New models** (runtime models, `ReframeModel`, never stored as documents):
   `reframe.models.analysis` (`BitrateScan`, `SubtitleScan`, `SubtitleScanTrack`,
   `LoudnessMeasurement`), `reframe.models.preview` (`PreviewFrame`, `FrameSet`, `FrameKind`,
   `CropSample`, `CropDetection`, `PreviewClip`), `ToolFetchResult`; new fields with defaults on
   `TrackDecision` (`kind`, `selected`, `selection`, `subtitle_outputs`) and `TrackDraft`
   (`subtitle_decisions`, `issues`).
4. **Persistence.** No persisted document changes: no new value in a persisted `Literal`, no
   rename, no removal. No `schema_version` changes and no migrations. Measured values use
   fields that `MediaSource` already has (`BitrateSource.MEASURED`, `event_count_source=
   "measured"`, `forced_event_count`). A task that needs a new persisted value asks the lead
   first (persistence rules of `CLAUDE.md`).
5. **A 4K fixture.** C-10's "Done when" needs "frames for a 4K HDR fixture", but 09 §Test
   media says every fixture is short and low resolution. `hdr10-4k` (3840×2160 HEVC Main 10,
   PQ, HDR10 metadata as SEI, 5 s at 23.976 fps, keyint 48, about 6 MB, 4 s to generate) is
   the one exception; it is generated like the others and never committed.
6. **Seams kept out of shared files.** C-12's defaults lint is called by `validate_template`
   (lead-wired); C-13's rules go into the new `reframe/validation/inplace.py` (imported by the
   lead); the rule cases of C-13 and C-6 go into `tests/validation/cases_inplace.py` and
   `cases_options.py`, which `test_rules.py` loads.

## Consequences

- S-2 can map the preview, scan, defaults-preview, dry-run and fetch routes to one facade method
  each. The server still needs ids for sources (`source_id`): the facade takes paths.
- `Reframe.power` is a new attribute that 05 did not list; the queue gets it for when-done.
- A measured value survives in the probe cache until the file changes or is probed again
  without the cache.

## Plan changes

- [05-core.md §C-15](../plan/05-core.md#c-15-service-facade-and-cli): the facade sketch lists the
  methods above and `power`.
- [09-quality-and-release.md §Test media](../plan/09-quality-and-release.md#test-media): the 4K
  fixture is the one large fixture.
