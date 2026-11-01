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

(Written by B.)

## Task F — F-11 Chapters and Tags tabs

Built: `components/editor/tabs/{Chapters,Tags}Tab.vue`, `components/chapters/` (`ChapterRow`,
`chapters.ts`, `useOutputChapters.ts`, `requests.ts`), `components/tags/` (`tags.ts`,
`useRenderedTags.ts`, `requests.ts`), `i18n/messages/en/{chapters,tags}.json`. S6's routes are
called only from the two `requests.ts` modules, with a cast of the path until they are in
`schema.d.ts`.

### The contract question

`ChapterSettings.names` is indexed by **source** chapter: the core's renaming
(`command/metadata.py`, `_renamed`) takes `names[i]` for source chapter `i` and drops the
chapters outside the range. `OutputChapter` had only its place in the output, so with a chapter
or time range the tab could not tell which name an output row is. At F's request the lead added
`OutputChapter.source_index` (0-based source chapter; `null` for a generated chapter, whose
names are by output position) to the contract (d09da36). The tab writes a name at
`source_index ?? number - 1`. No client-side mapping from the range was built: the member is
required in the contract.

### Choices where the plan leaves one

1. **A rename** writes the whole names list: the other chapters of the output as the table
   shows them, names of source chapters outside the output as they were (`''` where there was
   none, which the encode reads as "the source's title"). Typing coalesces under
   `chapters.names[<slot>]` until the field loses the focus, so one field edit is one undo step;
   Enter ends the edit. While the field has the focus it shows what was typed (an emptied name
   would otherwise jump to the source's title).
2. **The table shows the job's names first** and the server's answer for the rest: the answer
   comes 250 ms after the edit and may be older than an undo.
3. **Reset names**: *To the source names* is `names: null`; *To Chapter 1, Chapter 2, …* writes
   `Chapter N` by output position at each chapter's slot (the label is translated). For
   generated chapters the two are the same, so the menu has one item (`null`).
4. **Import** sends `format: null` (the server tells the format from the content) and applies
   the names by position over the output's chapters, as one undo step. A start in the file that
   differs from the output's by more than 10 ms, a different count, and the server's `issues`
   are listed in a warning under the toolbar; an unreadable file is an error there with the
   server's reason, and nothing changes. The file chooser filters `.csv`, `.txt`, `.xml`. An
   answer that comes after another job was opened is dropped.
5. **Export** is a menu of the three formats; the file is a Blob download (as the presets view
   does) of `content` named `file_name`.
6. **Generate chapters** shows only when the open source has no chapters (or, when the source
   is not known, when the job already generates). Turning it on takes 5 minutes, or the last
   interval of this job; turning it off writes `null`.
7. **Tags** write on each keystroke under the coalescing key `tags.<name>` (one undo step per
   field until it loses the focus); an emptied field writes `null`. *Written* is the rendered
   value, "copied from the source" for an unset tag while *Passthru common metadata* is on and
   the source has a value, else "Not written". The issues at `tags.<name>` are the validation
   store's and `jobs/tags`'s, each shown once; their "did you mean" fixes are buttons
   (`TemplateFixes`) that put the fixed template into the tag. `jobs/tags` is asked again
   250 ms after any edit (a tag can name any naming variable) and after a change of Settings.

### Checked in a browser (2026-11-01, before S6's merge)

Headless Chromium (`/usr/bin/chromium`: the Playwright cache was not there) against
`scripts/dev-server.py` with the pinned FFmpeg, fixtures `chapters`, `multitrack`, `season`,
light and dark. Against the real server the two tabs show their failure states ("could not be
read: Not Found") and the tag fields complete `{na` to `{name}`, `{file_name}`, `{folder_name}`.
With S6's routes answered by `page.route` (shapes of the contract; times of the `chapters`
fixture): the table, an inline rename and its undo, both resets, *Create chapter markers* off
with the reason, generated chapters for `multitrack`, the eight tags with written and source
values, a template error with its fix. The checks of the real routes wait for S6 (listed in
the report and in `status.md`).

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
