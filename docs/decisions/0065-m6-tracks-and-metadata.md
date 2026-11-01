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

Built on branch `worktree-agent-a7cf1dd08f96c6537` (2026-11-01). The routes, with their
response models (in `reframe.models`; none is persisted, none has a `schema_version`):

| Route | Answer | Core |
|-------|--------|------|
| `POST /api/jobs/type` `{job}` | `JobTypeInfo {job_type, reason, in_place_blockers}` | `reframe.command.jobtype.job_type_info` (`Reframe.jobs.job_type`) |
| `POST /api/jobs/chapters` `{job}` | `OutputChapters {origin, chapters, reason}`, `OutputChapter {number, start, end, name, source_name, source_index}` | `reframe.command.output_chapters` (`Reframe.jobs.output_chapters`) |
| `POST /api/jobs/chapters/export` `{job, format}` | `ChapterExport {format, file_name, content}` | `reframe.chapters.chapter_export` |
| `POST /api/chapters/import` `{path, format?}` | `ChapterImport {format, chapters, issues}`, `ImportedChapter {start, name}` | `reframe.chapters.read_chapter_file` |
| `POST /api/jobs/tags` `{job}` | `RenderedTags {values, source, issues}`; `values` and `source` are `TagValues` (the eight tag names, each `string \| null`) | `reframe.command.metadata.rendered_tags` (`Reframe.jobs.rendered_tags`) |
| `POST /api/subtitles/inspect` `{path}` | `SubtitleFileInfo {path, format, bitmap, charset, events, issues}` | `reframe.analysis.subtitlefile.inspect_subtitle_file` (`Reframe.sources.inspect_subtitle`) |
| `GET /api/fs/list?path=…&extensions=…` | `FsListing` (unchanged) | the router |

`ChapterFormat` (`csv` \| `ogm` \| `xml`) and `ChapterOrigin` are type aliases in
`reframe.models`. Tool behaviour these rely on: testdata/README.md "Subtitle files, tags and
chapter files".

1. **One chapter function.** `reframe.command.metadata.planned_chapters` gives the output's
   chapters and whether `-map_chapters 0` writes them; `chapter_plan` (the command) and
   `output_chapters` (the route, with `build_plan`'s range resolution) both call it. A source
   chapter without a title that is copied as it is has the name `""`, since FFmpeg writes no
   `ChapterDisplay` for it; renamed or edge-cut chapters go through the FFMETADATA file, where
   such a chapter is `Chapter N` (as before). One change of the command: a copy whose range
   holds no chapter now writes `-map_chapters -1` instead of `0` (the output is the same: no
   chapters). The route's answer equals the re-probed encode for renamed chapters, a chapter
   range, a time range (copied chapters) and generated chapters (real encodes, both in the tests
   and against a real server with the pinned FFmpeg).
2. **`source_index`** (the lead's addition to the contract): the 0-based source chapter, which
   is the slot of `ChapterSettings.names` (indexed by source chapter, so with a range it differs
   from `number - 1`); `null` for a generated chapter, whose name is `names[number - 1]`.
3. **`jobs/type` never refuses an in-place edit.** In web mode a source that the write jail
   refuses (a media root that is not an output root) is one more blocker, `<name> is in a folder
   that this server may only read`: after "the source is not an MKV file" when that is there,
   else first. It also counts for the job type, so with *Edit in place* on, the answer is the
   remux / encode type with "It cannot be edited in place: …", as the plan would treat it;
   `jobs/validate` still reports `inplace.not_allowed` with its fix. The blockers are given for
   every job (with *Edit in place* off too).
4. **Chapter import.** The format comes from the content when the request names none (`<` →
   XML, `CHAPTER` → OGM, `<number>,` → CSV). The text is UTF-8 or UTF-16 with a byte order mark,
   else UTF-8, else Latin-1 with the warning `chapters.not_utf8`. At most 4 MiB. Failures are a
   422: `chapters.unreadable` (missing, a folder, too large, an I/O error) or `chapters.invalid`
   (the detail starts with `Line N:` where the line is known). CSV: HandBrake's form (RFC 4180;
   checked in HandBrake's source, not by running HandBrake), the name trimmed, a warning
   (`chapters.numbers`) when the numbers are not 1, 2, 3 …. OGM: `CHAPTERnn=` and
   `CHAPTERnnNAME=` in any order; a name without a time has `start: null` and a warning. XML:
   the first `EditionEntry` (`chapters.editions` when there are more), its top-level
   `ChapterAtom`s (`chapters.nested` when inner ones are left out), the first `ChapterString`;
   an entity declaration is refused (no new dependency such as `defusedxml`: the reader is
   expat with entity declarations turned into an error). The import gives names and times; the
   UI compares them (decision item 3).
5. **Chapter export.** CSV `number,name` with RFC 4180 quoting and LF; OGM with millisecond
   times, UTF-8 without a byte order mark (mkvmerge v103 reads it, also under `LC_ALL=C`), a line
   end in a name becomes a space; XML as mkvextract writes it, without UIDs, `ChapterLanguage`
   `und`, no `ChapterDisplay` for a chapter without a name, characters that XML 1.0 cannot hold
   replaced with a space. `file_name` is the output's name without its extension (else the
   source's) plus `.chapters.csv`, `.chapters.txt` or `.chapters.xml`. A job whose output gets no
   chapters is a 422 `chapters.none` with the reason as the detail.
6. **Tags.** `values` are rendered as the plan renders them: the job's preset's naming options,
   else the settings', the output size of the job, `{date}` and `{time}` as of the request. An
   unknown variable renders empty (as in the encode), a syntax error leaves the template as
   typed. `issues` are only the template errors (`naming.template_syntax`,
   `naming.unknown_variable` with its "did you mean" fixes, `naming.bad_format_spec`) at
   `tags.<name>`; validation does not report tag templates. `source` comes from the probed
   container tags under the builder's FFmpeg keys, without case (Matroska writes `ARTIST`,
   MP4 `artist`), the title from the container title.
7. **Subtitle files.** ffprobe `-show_streams -count_packets` through `reframe.tools.run`;
   `events` are its packets, for a `.sup` the display sets (`read_display_sets`, the subtitle
   scan's count: the sup demuxer gives one packet per segment). `charset` (decision item 6):
   `UTF-8` from a BOM or valid UTF-8 (the first 16 MiB), `UTF-16LE` / `UTF-16BE` from a BOM,
   else `null`. Issues (warnings): `subtitle.charset_unknown` (`charset`),
   `subtitle.utf16` (FFmpeg reads UTF-16 subtitle files wrongly: save as UTF-8),
   `subtitle.format_mismatch` (the content is another format than the name ending says),
   `subtitle.no_events`. A file a job cannot take (another ending than `.srt`, `.ass`, `.ssa`,
   `.vtt`, `.sup`, or no subtitles FFmpeg can read) is a 422 `subtitles.unsupported`; a missing
   file a 404 `probe.not_found`; other probe failures keep their `probe.*` problem.
8. **`fs/list?extensions=`**: repeatable, any case, with or without the dot; a value that is
   empty or holds `.`, `/`, `\` or NUL is a 422 `fs.bad_extension`. The web file browser asks
   for the filter's extensions only when one of them is not a media file's
   (`listedExtensions` in `components/sources/fileBrowser.ts`, whose list mirrors
   `reframe.probe.MEDIA_EXTENSIONS`); then it shows the filter as a note (*Only srt, ass*)
   instead of the switch, since there is nothing else to show. No filter or media extensions
   only: as before.
9. **`API_VERSION` stays 1**: new routes and one optional query parameter; no field, route or
   meaning of an earlier version changes, so no client of an earlier version breaks.
10. Every new path input is in the jail sweep (`test_jail_sweep.py`); the facade's new members
    (`jobs.job_type`, `jobs.output_chapters`, `jobs.rendered_tags`, `sources.inspect_subtitle`)
    are reached by routes.

## Task A — F-10 `LanguagePicker`, F-15 Settings → Languages

**What the server has and accepts** (checked 2026-11-01 against `scripts/dev-server.py` with
the pinned FFmpeg, `curl` with the run's token):

- `GET /api/languages` holds 429 entries: every ISO 639-2 individual language, macrolanguage
  and special code (`und`, `mul`, `zxx`, `mis`) as a base language, and 11 variants
  (`variant: true`): `en-GB`, `en-US`, `es-419`, `es-ES`, `fr-CA`, `pt-BR`, `pt-PT`,
  `sr-Cyrl`, `sr-Latn`, `zh-Hans`, `zh-Hant` (`reframe.languages.COMMON_VARIANTS`). No listed
  language has an `iso639_3` that differs from its `iso639_2t`; languages that only ISO 639-3
  has (`yue`, `cmn`, `arb`) are not listed.
- `PUT /api/settings` checks a language tag's shape only (`LanguageTag`,
  `^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$`): `["de-AT","pt-BR","sr-Latn-RS"]`, `["xx-YY-ZZ"]`,
  `["zz"]` and `["en-u-ca-gregory"]` are saved, `["pt_BR"]` is a 422 with an issue at
  `languages.favourites.0`. Job tracks use the same type. So the client decides which tags are
  real languages; the core normalises later (`reframe.languages.normalize`: `ger-AT` → `de-AT`,
  `pt_br` → `pt-BR`; it also takes `en-XX`, `en-Qaaa` and variant subtags such as `sl-rozaj`).

**Decision.**

1. **The search runs in the browser** (`components/language/catalog.ts`), on the list from
   `GET /api/languages`, with the ranking of `reframe.languages.search`: tag, ISO code, exact
   English name, exact native name, name prefix, word prefix, substring; matching favourites
   form their own group first, in the order of the settings. Case and accents are folded
   (`francais` finds French). No new route: one list, read once, keeps every keystroke local.
2. **A typed variant of a listed language** is offered when its base language is listed and
   its script and region are known: `de-AT`, `ger-AT` (→ `de-AT`), `zh-hant-tw`
   (→ `zh-Hant-TW`), `es-MX`. The names come from the base entry and `Intl.DisplayNames`
   (`German (Austria)`, as the core names them); the ISO 639-2 codes are the base language's,
   as the core writes them. Not offered: private-use or unknown regions and scripts (`en-XX`,
   `en-ZZ`, `en-Qaaa`), variant and extension subtags (`sl-rozaj`, `en-u-…`), and languages
   that only ISO 639-3 has (`yue`): the client has no macrolanguage table, so it could not show
   their ISO 639-2 code (the core writes `yue` as `chi`). The picker is so stricter than the
   server, never looser. Checked in Node and Chromium: `Intl.getCanonicalLocales` would rewrite
   `tl` to `fil` and `sh` to `sr-Latn`, which the core keeps apart, so the language subtag comes
   from the list and only the region goes through `Intl`.
3. **What is written** is shown on each entry: `Hungarian · hun (ISO 639-2) · hu (BCP 47)`.
   The ISO 639-2 code is /B for MKV and WebM and /T for MP4: the optional prop `container`
   (default MKV) picks it, as `reframe.languages.picker_label` does.
4. **Escape** closes only the picker: the Dialog's own Escape listener is off and the picker
   stops the key on its dialog, so a picker inside another dialog (the defaults dialog) does not
   close that one too.
5. **Settings → Languages** shows a list change before the server answers (and the server's
   answer after it), so that a second move builds on the first and the focus follows the moved
   language; a refused list stays shown with its issue (`useSetting`).

**Props added** (all optional, the stubs' props unchanged): `LanguagePicker`: `noneLabel` (the
text of *None*), `container`, `exclude` (tags not offered); `LanguageListEditor`: `inputId`,
`labelledby` (for a `Field`), `container`.

**Checked** in headless Chromium (Playwright 1.64.1) against `scripts/dev-server.py
--port 8711` with the pinned FFmpeg, light and dark, 1440 × 900 and 390 × 844: the search by
`Hungarian`, `magyar`, `hu`, `hun`, `ger`, `deu`, `Deutsch`, `pt-BR`, `pt_br`, `es-419`,
`zh-Hans`, `sr-Latn`, `de-AT`, `zh-hant-tw` and `Brazil` gives the right first entry, `en-XX`
none; keyboard alone (Enter or ArrowDown or a letter on the control, typing, arrows, Enter,
Escape from the search field and from the dialog's close button, the focus back on the
control); add, move up (the focus stays on the moved language), drag, remove (the focus on the
next one) in the three lists, each saved at once; the new favourites lead the next picker; a
refusal (the request rewritten on its way so that the real server refuses it) shows at its
field with the list kept. Unit tests: 42; each test function was failed by a mutation of the
code (40 mutations); the six that survived the first run showed redundant code (removed) or a
weak test (fixed).

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
