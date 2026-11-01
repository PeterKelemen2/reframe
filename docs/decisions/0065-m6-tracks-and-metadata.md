# 0065 — M6, tracks and metadata: the missing routes, the shared skeleton, and the open choices

- Status: accepted
- Date: 2026-11-01
- Steps: S-2 (additions), F-6, F-10, F-11, F-15, F-17

## Context

M6 ([08 §M6](../plan/08-roadmap.md#m6--tracks-and-metadata)) builds the UI of tracks and
metadata on the core that `core-complete` finished (C-10, C-12, C-13;
[0029](0029-core-before-the-ui-milestones.md)). Its tasks and waves are in
[m6-breakdown.md](../m6-breakdown.md). Before any agent, the lead checked what the API offers
(2026-11-01, on `main` 4ae0988, routes read from `reframe_server/routers/`, two answers checked
against a real server):

- There: the three scans (`POST /api/sources/{id}/streams/{index}/bitrate-scan`,
  `/api/sources/{id}/subtitle-scan`, `/api/sources/{id}/streams/{index}/loudness`, each a task),
  `POST /api/presets/defaults/preview` (with `source_ids`, so a batch group can use it later),
  `POST /api/jobs/draft-remux`, `GET /api/languages`, `LanguageSettings` (favourites, preferred
  audio and subtitle languages) in the settings.
- Not there: chapter import and export (core and server), the list of chapters the output gets
  (the command builder computes it inside `chapter_plan` only), tag values with their naming
  variables filled in (`render_tag` has no route), the job type's reason (`jobtype.job_type`
  returns it; the API gives only `EncodePlan.job_type`, and only for a job without errors),
  files other than media files in `GET /api/fs/list` (M4's recorded limit L5), anything about
  an external subtitle file before it is added.
- In web mode an in-place edit of a source in a media root is refused (`inplace.not_allowed`
  from `jobs/validate`, a 422 from `jobs/plan`): reading needs a media root, writing an output
  root. A copy in a folder that is both plans as `metadata_edit` (checked with the new
  `dev-server.py --output-fixtures`).

M4's recorded limits ([m4-breakdown.md](../m4-breakdown.md#where-m4-ended-2026-11-01)) that M6
touches: **L5** (a `fs/list` option for other files) is built by S6 for the external subtitle
import. The others stay as they are: L7 (the desktop platform stub, M5), L14 (an output that
another waiting job claims is known only at the add), a duplicate's automatic free name, the
queue table's narrow Source and Output columns at 1440 px, Summary's issue list below the Output
card, a second opened file not selected while another is open.

## Decision

1. **Task S6** adds the missing routes (contract in the breakdown): `POST /api/jobs/type`,
   `POST /api/jobs/chapters`, `POST /api/chapters/import`, `POST /api/jobs/chapters/export`,
   `POST /api/jobs/tags`, `POST /api/subtitles/inspect`, and `extensions` for
   `GET /api/fs/list`. The logic is in the core; the chapter list and the command come from one
   function, so the Chapters tab and the encode never differ.
2. **Folders.** `LanguagePicker` and `LanguageListEditor` are in `components/language/`;
   `TrackMetadataEditor`, the flag toggles and the bulk edit dialog are in `components/tracks/`,
   beside the track rows that place them. 06 §Structure named `components/metadata/`; it is
   updated in this commit. Each task owns its own folders.
3. **Chapter import** takes the names, by position. The times of an OGM or XML file are compared
   with the output's chapters (a warning when the count or a start differs) and not kept:
   `ChapterSettings` holds names only, and HandBrake's import also takes names only. Times of
   their own would be a new persisted field.
4. **Job-level defaults.** The dialog opened from the Audio or Subtitles tab starts from the
   defaults of the job's preset and, on *Apply*, replaces the job's tracks of that list with what
   the defaults draft (one undo step). The job keeps no defaults of its own: `JobSettings` has
   none, and adding them is a persisted-schema change that M6 does not need. Edited defaults
   are kept by saving them into a user preset; a built-in preset's defaults are shown
   read-only. The batch-group target is typed and not built (M7).
5. **In-place edits in web mode** stay as the server has them: allowed only for a source in a
   folder that is both a media root and an output root. The UI shows the server's
   `inplace.not_allowed` with its reason. `scripts/dev-server.py --output-fixtures` makes such a
   folder for checks.
6. **External subtitle encoding.** `subtitles/inspect` detects UTF-8 (with or without a byte
   order mark) and UTF-16 (byte order mark) only; anything else is "not detected" and the user
   picks an encoding. No new dependency.
7. **Tabs.** Chapters (`Ctrl+7`) and Tags (`Ctrl+8`) join the tab registry; Settings shows
   Languages between Output and Queue (03 §Settings order).

## Consequences

- The routes of S6 are additions; an older client is not affected (S6 records whether
  `API_VERSION` changes).
- Edited defaults that are not saved into a preset are lost when the job is drafted again;
  *Reload from preset rules* uses the preset's defaults.
- A chapter file's own times cannot be imported. A user who needs them edits the source's
  chapters outside Reframe.

## Plan changes

- 06 §Structure: `components/language/` and the metadata components under `components/tracks/`.

## Task S6 — S-2 additions

(Written by S6.)

## Task A — F-10 `LanguagePicker`, F-15 Settings → Languages

(Written by A.)

## Task B — F-10 the Measure button and the scans

Built: `stores/scans.ts`, `sources.reload`, and the scans in `components/media/TrackTable.vue`
(with `ScanControl.vue`, a start button that becomes a progress bar and a cancel button while
the task runs).

Choices:

1. **One run per target, joined.** A target is the source, the kind and the stream (`null`: a
   subtitle scan of every track). A second click on a target that runs, also before the
   server's 202 has come, joins the first call (the same promise); no second task starts. A
   one-track subtitle count while every track is being counted joins that scan, and the table
   turns the tracks' own *Count* buttons off meanwhile. A scan of every track may start while a
   one-track count runs: the server merges both (`SourceService.update`).
2. **The run stays until the source is read again.** For a bitrate or subtitle scan that ends
   `done`, the run (its progress bar) is removed only after `sources.reload`, so the cell never
   shows `—` and **Measure** again between the end and the measured value.
3. **Failures.** A refused start (404, 409, 422) is the API client's toast and leaves no run.
   A `failed` task is an error toast ("The bitrate could not be measured", the task's error as
   the detail); a task the server forgot (`TaskLostError`) is the same toast. A `cancelled` task
   is quiet. Neither reads the source, so the table stays as it was. A bitrate scan that ends
   `done` with `bitrate.source` `unknown` (no packets with a size and a time) is a warning
   toast; the source is read again all the same.
4. **`sources.reload(id)`**: `GET /api/sources/{id}` with the quiet client; the entry is
   replaced in its place (`activeId`, the editor's job and the other entries stay), then the
   batch grouping is asked again (measured values change roles, which the grouping compares).
   **404** (`source.unknown`: the server restarted or another client removed it): the entry's
   path is probed again; the id is the same (a hash of the path), so the editor's job still finds
   it. **409** (`source.stale`: the file changed since the probe): `source` becomes `null`, as
   `refresh` gives it, and the panel shows the file as changed. Any other refusal is a toast and
   rejects. An id that is not open sends nothing.
5. **Where the controls are.** Audio: **Measure** beside the `—` of an unknown bitrate (the
   accessible name names the track: "Measure the bitrate of track 1"); *Measure loudness* in the
   expanded row, which then shows integrated loudness (LUFS), true peak (dBTP) and loudness range
   (LU), one decimal, `—` where FFmpeg gives `-inf` (`null`). Subtitles: *Count events* above the
   table (every track), *Count* beside an unknown count, and in the expanded row of a counted
   track (to count again, and so to get the forced events of a PGS track whose count came from a
   statistics tag). The row shows `12` and `2 forced`; the details show *Forced events* for every
   PGS and VobSub track (unknown until counted).
6. **Which source a `TrackTable` scans**: a new optional prop `sourceId` (`null`: no scan
   controls); without it, the editor job's source (`useJobSource`), so `TracksTab` needs no
   change.
7. The loudness is kept in `scans.loudness` by `sourceId:streamIndex` for the session only; the
   whole track is measured (the route's `start` / `duration` are not used).

Checked against a real `reframe-server` with the pinned FFmpeg (n9.0.2), 2026-11-01, and kept in
`stores/scans.server.test.ts`:

- `dts-hd-ma` stream 1 (DTS-HD MA): `bitrate` `{value: null, source: 'unknown'}` before; the
  bitrate scan gives `2 140 063` b/s (375 packets, 1 069 764 bytes, 3.999 s), and
  `GET /api/sources/{id}` then holds `{value: 2140063, source: 'measured'}`. The table shows
  `2140 kb/s` / `measured`.
- `pgs`: the subtitle scan gives 12 events (2 forced) and 4 events (2 forced);
  `event_count_source` `measured`. `vobsub`: 2 (0 forced) and 1 (0 forced).
- Loudness of `dts-hd-ma` stream 1: integrated −22.47 LUFS, true peak −20.0 dBTP, LRA 2.2 LU.
- **The role heuristics see the measured values**: a file made with the pinned ffmpeg (eng AC-3
  5.1 at 192 kb/s, then an untitled eng Opus 2.0 at 48 kb/s, which ffprobe gives no bitrate for)
  has `main` / `heuristic` on its second track before; after the scan, `commentary` /
  `heuristic` with "2.0 at 49 kb/s after the 6-channel track #0 in the same language (eng)".
- Cancel: the scan of that file (10 minutes of 2.5 ms Opus packets, 1.7 s to scan) cancelled at
  once ends `cancelled`; the source keeps `unknown` and its roles.
- A failure: `multitrack.mkv` made unreadable (`chmod 000`) after it was opened; **Measure**
  gives a `failed` task with "The file cannot be read. ([Errno 13] Permission denied: …)" as
  its error; the toast shows it and the row still shows `—` and **Measure**.
- Scan times: a bitrate scan reads ffprobe's packets (about 140 000 packets a second); a
  loudness scan decodes the track (an hour of AC-3 5.1: about 40 s).

The browser check (headless Chromium, light and dark) showed cancel for real with a one-hour
file made with the pinned ffmpeg in the server's temp media root (AC-3 5.1 plus Opus 2.0 with
2.5 ms packets: the bitrate scan takes about 10 s, the loudness scan of the 5.1 track about
40 s).

M6 demo 2 needed no change: `multitrack` track 3 shows a solid *Commentary* badge with no
click; its tooltip reads "Set by a disposition flag in the file" and "disposition comment".

## Task F — F-11 Chapters and Tags tabs

(Written by F.)

## Task C — F-10 `TrackMetadataEditor`, bulk edit, external subtitles

(Written by C.)

## Task D — F-6 the job type, remux and in-place edits

(Written by D.)

## Task E — F-10 the defaults dialog and its live preview

(Written by E.)

## Task G — F-17 flow 1

(Written by G.)

## Review

(Written by the lead after the reviews: the findings, their outcomes, the fix rounds.)

## M6 demo

(Written by the lead.)
