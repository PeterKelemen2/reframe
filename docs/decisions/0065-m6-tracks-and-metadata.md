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
called from the two `requests.ts` modules (typed by the generated schema since S6's merge).

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
   none, which the encode reads as the source's title, or `Chapter N` for an untitled chapter).
   An untitled chapter copied as it is has the name `""` (S6); its field shows *No name*. Typing coalesces under
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
   interval of this job; turning it off writes `null`. The interval takes 0.01 to 600 minutes
   with two decimals, so that the seconds-long fixtures can show several chapters.
7. **Tags** write on each keystroke under the coalescing key `tags.<name>` (one undo step per
   field until it loses the focus); an emptied field writes `null`. *Written* is the rendered
   value, "copied from the source" for an unset tag while *Passthru common metadata* is on and
   the source has a value, else "Not written". The issues at `tags.<name>` are the validation
   store's and `jobs/tags`'s, each shown once; their "did you mean" fixes are buttons
   (`TemplateFixes`) that put the fixed template into the tag. `jobs/tags` is asked again
   250 ms after any edit (a tag can name any naming variable) and after a change of Settings.

### Checked in a browser (2026-11-01)

Headless Chromium (`/usr/bin/chromium`: the Playwright cache was not on this machine) against
`scripts/dev-server.py` with the pinned FFmpeg n9.0.2, fixtures `chapters`, `multitrack`,
`season` (and `--output-fixtures multitrack`), light and dark, after S6's merge:

1. The `chapters` fixture shows four chapters (0 / 1 s, 1 / 1.5 s, 2.5 / 1.5 s, 4 / 1 s:
   Opening, Part One, Part Two, Credits). A rename writes `["Opening", "The Middle", "Part Two",
   "Credits"]` and shows it after the next answer; Ctrl+Z brings `names: null` back. *To Chapter
   1, Chapter 2, …* and *To the source names* work. *Create chapter markers* off shows "The output
   gets no chapters. Create chapter markers is off."
2. Import through the file browser, which lists `names.csv`, `names.txt` and `names.xml` in the
   media root: a HandBrake CSV (with a quoted name holding a comma), an OGM text file and a
   Matroska XML file each set the four names in one undo step. The XML file's fourth start
   (4.2 s) gives the warning "Chapter 4 starts at 0:00:04.200 in the file and at 0:00:04.000 in
   the output"; the others say "4 names imported from …".
3. Export: `chapters.chapters.csv` (`1,Intro`…), `chapters.chapters.txt` (`CHAPTER01=…`,
   `CHAPTER01NAME=Intro`…) and `chapters.chapters.xml`, each with the renamed first chapter.
4. Generate every 0.02 min on `multitrack` (no chapters; before: "The source has no chapters.")
   shows four generated chapters (1.2 s each, the last 0.421 s).
5. Tags: Title's source value is "Reframe chapters fixture", shown as copied while unset;
   `{na` completes to `{name}`, `{file_name}`, `{folder_name}`; `{name} – test` is written as
   `chapters – test`; `{nam}` in Genre shows "Unknown variable {nam} (position 1). Did you mean
   {name}?" at the field, and its fix puts `{name}` there. On `season/Show.S01E02.Title.mkv`,
   `{name}< – S{season:02}E{episode:02}>` is written as `Show – S01E02`.
6. An encode of `chapters.mkv` (H.265 MKV 1080p) with the third chapter renamed and that Title
   tag ends `done`; ffprobe of the output gives the chapters `Opening, Part One, Renamed Three,
   Credits` and the format tag `title=chapters – test`.

## Task C — F-10 `TrackMetadataEditor`, bulk edit, external subtitles

Built in `components/tracks/`: `TrackMetadataEditor.vue`, `BulkEditDialog.vue`,
`ExternalSubtitleFields.vue`, the pure patch builders and name values in `metadata.ts`, the
inspection cache and the file picking in `external.ts`; the rows, `OutputTrackList` and the
messages changed. The stub's props are unchanged; one optional prop is added, `collapsible`.

1. **The block.** Language: the `LanguagePicker` (clearable; *None* is "As the source
   (Japanese)", for an external file "Not set (written as und)"; `container` is the job's, so the
   ISO 639-2 code shown is the one written). Name: a text field (`null` shows the source title as
   its placeholder, `""` shows "No title"); typing is one undo step until the field is left.
   Flags: six toggles, each one undo step. Every field is a `Field` with its validation path
   (`audio[2].metadata.default`), so issues show at it; the fixes of the block's issues are
   buttons under the flags (`metadata.several_defaults` → *Keep only audio track 1 default*,
   `tool.mkvpropedit_missing` and `container.flag_unsupported` → *Clear the … flag*,
   `metadata.language_tag_lost` → *Write it as por*). The row no longer lists these issues
   again (its `fieldPaths` include the block's paths).
2. **Folded in a row.** In an audio or subtitle row the block is folded behind one line
   (*Metadata* `Japanese · “Japanese 5.1” · Default`); it opens by itself when one of its fields
   gets an issue and when `ui.reveal` asks for one of its paths, before the field takes the
   focus. On the Video tab it is open. A burned-in subtitle's block is turned off with a note:
   validation writes no metadata for it.
3. **Name templates.** `TrackMetadata.name` stays text. There is no route that renders a track
   name template, and porting the naming template syntax (`<…>` groups, format specs) into the
   client would be a second renderer that can drift from `batch/metadata.py`. So the name field
   has a menu *From this track* with the codec rules' templates, each rendered at edit time with
   this track's values and shown with its template (`Japanese 2.0 AAC` —
   `{lang_name} {channels} {codec}`): audio `{lang_name|lang_native} {channels} {codec}`,
   `{lang_name|lang_native} {channels}`, `{lang_name}`, `{lang_native}`, `{title}`; subtitles and
   video `{lang_name}`, `{lang_native}`, `{lang_name} {codec}`, `{title}`. The values are the
   core's: the language of the block (else the source track's), its English and capitalised
   native name, the output layout (the mixdown's `channels − lfe`.`lfe`, else the source layout
   for a copied track), the output codec (the encoder's label, the source codec for a copied
   passthru, the conversion format or the file's format for subtitles), the source title. A
   template with an empty value is not offered. The chosen text is stored; it does not follow a
   later language change. The menu also has *Keep the source title* (`null`) and *Write no
   title* (`""`).
4. **Bulk edit.** A selection column (a check box per row, Space toggles it) and a bar above
   the list with *Select all* (shown from two tracks), the count, *Edit selected…* and *Clear
   the selection*. The dialog changes only what is set: *Set the language* plus the picker, and
   per flag *Leave / On / Off*; *Apply* is off until something is set; one `editor.patch`, so one
   undo step. The selection is by place, so it is cleared when the list's tracks or their order
   change (a move, an add, a remove, an undo of those, another job), and kept when a selected
   track's settings change.
5. **External files.** *Add external subtitle…* (Subtitles tab) → `platform.pickFiles({
   multiple: true, filters: ['.srt', '.ass', '.ssa', '.vtt', '.sup'] })` → `subtitles/inspect`
   for each file (a refused file is the API client's toast and is left out) → one copied track
   per file at the end of the list, all in one undo step, never default. No dialog in between:
   the row offers every setting, and keeps offering it later. The file name gives the language
   and flags when its last parts say so (`Film.pt-BR.forced.srt`, `.sdh.`, `.cc.`; not `hi`,
   which is Hindi; only the parts right before the extension, so a title word is never taken for
   a code). The row shows the file (its path in the tooltip), `SRT · 120 events · UTF-8` (a
   `.sup`: *display sets*), the inspection's warnings about the file, the time offset (ms,
   negative too; typing is one undo step) and the character encoding (an editable list of the
   common code pages and ISO 8859 sets by iconv's names; the first entry is *As detected: UTF-8*
   or *Not detected: choose one*). As S6 found: `charset` stays `null` for UTF-8 and UTF-16; a
   file whose encoding was not detected shows `subtitle.charset_unknown` at the encoding until
   one is chosen; a UTF-16 file shows `subtitle.utf16` there. A bitmap file has no encoding
   field, and *Convert* is off for it. The row asks `subtitles/inspect` itself (quietly) when the
   page has no answer for the path (after a reload from the preset or an edit-back).
6. **The external file's own fields.** `ExternalSubtitle.language`, `name` and `flags` say what
   the file is; the output's `metadata` says what is written, and its `null` means "as the
   file". The block of an external track writes both in one patch, so they are always equal and
   the file reads as the user described it everywhere (the builder takes the source language
   and title from `ExternalSubtitle`, the flags from `metadata`).

**Checked** in headless Chromium against `scripts/dev-server.py --port 8750` with the pinned
FFmpeg (n9.0.2), light and dark, 2026-11-01. `subtitles/inspect` of the files used:
`text-subs.en.srt` `subrip` UTF-8 2 events, `text-subs.en.ass` `ass` UTF-8 3, a `.sup` made with
`mkvextract` from `pgs.mkv` `hdmv_pgs_subtitle` bitmap 12 display sets, a `.vtt` `webvtt` UTF-8 2,
an `.ssa` `ass` UTF-8 2, a CP1250 `.srt` (made with `iconv`) `subrip`, `charset: null`, with
`subtitle.charset_unknown`. **M6 demo 3** through the UI on `multitrack` (H.265 MKV 1080p):
audio 1 Hungarian, *Original language*, the name from the menu (`Hungarian 2.0 AAC`); audio 2
`pt-BR`, `Português (Brasil)`; audio 3 `pt-BR`, *Commentary*, `Comentário do diretor`; subtitle 1
Hungarian, *Hearing impaired* (SDH), `Magyar SDH`; the CP1250 file with *CP1250* and −200 ms; the
`.vtt` file as `pt-BR`, `Legendas` → queue → done. Re-probed with the pinned ffprobe, `mkvmerge -J`
and the server (`POST /api/sources`): audio `hun` "Hungarian 2.0 AAC" default+original; `por` /
`LanguageIETF pt-BR` "Português (Brasil)"; `por` / `pt-BR` "Comentário do diretor" comment;
subtitles `hun` "Magyar SDH" default+hearing_impaired, the source's `eng` "English SDH"
hearing_impaired and "Signs & Songs" forced, `hun` (the CP1250 file, its text decoded: "Árvíztűrő
tükörfúrógép", the events 200 ms earlier), `por` / `pt-BR` "Legendas" (WebVTT). The BCP 47 tags
come from the post-mux mkvpropedit step; ffprobe shows `por` only, as 0034 says.

**Open**, for the lead: validation does not know an external text file whose encoding was not
detected (only `subtitles/inspect` says so), so a job with such a file and no `charset` can be
queued and fails in FFmpeg; the row shows the warning. A rule in `jobs/validate` (or the dry run)
would close it. PrimeVue's popup menu closes when the page scrolls, so the name menu of a row
near the bottom of the window closes if the page scrolls under it.

## Task D — F-6 the job type, remux and in-place edits

Built: the Summary's **Job type** card (`components/summary/JobTypeCard.vue`, `useJobType.ts`,
`inPlace.ts`), `editor.applyRemuxDraft`, `components/summary/useInPlaceReload.ts` (mounted once
in `App.vue` by the lead) and the in-place line of the queue table.

**What the server does** (checked 2026-11-01 against `scripts/dev-server.py --fixtures
multitrack --output-fixtures multitrack` with the pinned FFmpeg n9.0.2 and mkvpropedit 101.0;
`src/components/summary/jobType.server.test.ts` repeats it):

- `jobs/type` for the default draft of the writable copy: `encode`, "Encode: the video is
  encoded with x265.", blockers `the video is encoded`, `audio track 1 (AC-3) is encoded`.
  `jobs/draft-remux {edit_in_place: true}` of that MKV gives the output path = the source and
  `metadata_edit` ("Metadata edit: only the track metadata changes, so mkvpropedit edits
  multitrack.mkv in place, in seconds."); changed flags stay `metadata_edit`; a removed audio
  track is `remux` with "… It cannot be edited in place: the audio tracks are not the source's
  audio tracks in source order." and `inplace.not_possible` (fix "Write a new file (multitrack
  (1).mkv)") plus `output.same_as_source`; MP4 is `remux` with two blockers (the container, a
  subtitle MP4 cannot copy). The media root's copy: the first blocker is "multitrack.mkv is in a
  folder that this server may only read", also for an encode; its remux draft already carries
  `inplace.not_allowed` with the fix "Write a new file in <output root>", which sets
  `<output root>/multitrack.mkv`: there the file exists, and validation then says
  `output.renamed` (info).
- **The core sets `edit_in_place` for any source** in `remux_job`; only the path and container
  change is MKV-only. A remux draft of an MP4 with `edit_in_place: true` is therefore an
  `inplace.not_possible` error.
- After an in-place job ends `done`, the queue snapshot keeps `plan.job_type`
  `metadata_edit` and `output_path` = the source, and **`GET /api/sources/{id}` gives the
  edited file at once** (200, not a 409 `source.stale`): the runner's uncached re-probe replaces
  the source the service knows. So `sources.reload` is enough; no probe task is needed.
- **M6 demo 4**: flags only (audio 1 default off, audio 2 default on, subtitle 2 forced) →
  `metadata_edit`; from *Add to queue* and *Start* in the browser the job ran 0.076 s
  (`started_at` 16:52:57.399596 → `finished_at` 16:52:57.475584; 0.074 s and 0.083 s in the
  other runs), the source was read again and the Audio tab's source table showed *Default* on
  track 2 instead of track 1.

**Choices.**

1. **A card, not a line of the Output card**, second in the grid (beside Source on a wide
   screen): the type as a badge (Encode neutral, Remux info, Metadata edit ok colour) with the
   server's reason as it is; then *Edit in place*; then what is in its way; then *Remux only*.
   06 §F-6 said "the job type line"; the plan is updated in this commit.
2. **When it asks**: `jobs/type` with the whole job (nearly every part counts: tracks,
   chapters, tags, container, the switch), at once for a new job and when the card mounts (the
   tabs are mounted only while shown, so coming back to Summary after edits on other tabs asks
   at once), 250 ms after the last edit, through `latestRequest` (only the newest answer). The
   last answer stays with *Updating…* while a newer one is on its way; another job's answer is
   cleared at once. A refused request shows "The job type cannot be found: <problem title>".
3. **The blockers** (`in_place_blockers`, all of them) show whenever there are any, with the
   switch on or off ("Edit in place is not possible because: …"): the issue names only the
   first ("(and 1 more)"). With none and the switch off, the card says that only metadata
   changes and that Edit in place would change the file in seconds.
4. **The switch** writes only `/output/edit_in_place` (one undo step each way). A path that is
   not the source is left to the server's `inplace.output_ignored` and its fixes (*Edit
   <source>* / *Write a new file*), so the switch never moves the user's path. Its `Field` is
   the reveal target of `output.edit_in_place` but lists no issues itself; the card lists the
   in-place issues (`inplace.*`, and any other at `output.edit_in_place`, such as
   `tool.mkvpropedit_missing`) through `IssueList` with their fix buttons, and marks the switch
   invalid on an error. The Issues card still lists them too.
5. **The plain notice** ("The source file itself is changed: <path>. No new file is written,
   so the output name and folder are not used.") shows while the switch is on *and* the answer
   is `metadata_edit`, so it goes at once when the switch is turned off, before the next answer.
6. **Remux only** calls `editor.applyRemuxDraft({ editInPlace })` with the job's preset (one
   undo step that also brings the earlier draft back, as `applyPreset`). `editInPlace` is true
   only for a Matroska source that is not WebM (`isMatroska`, the core's `is_matroska_source`
   rule), because of the core's behaviour above. A writable-ness check is not made: in web mode
   a source in a read-only folder gets `inplace.not_allowed` with the server's fix (decision
   item 5). A refused draft is the API client's toast; the job stays.
7. **After an in-place edit** (`useInPlaceReload`, for the lead's `App.vue`): when a job with
   `settings.output.edit_in_place` that has run (`started_at`) enters an ended state, the open
   source with that path is read again (`sources.reload`). Every ended state counts, not only
   `done`: a cancelled or interrupted edit may already have written the file (0034, R4-7), and
   reading an unchanged file gives the same source back, a changed and unchecked one a 409 that
   the panel shows as changed. Ends that came before the window's first read of the queue do
   not count; a job first seen already ended after it (another window ran it) does; a retry
   counts again; the server's times arriving after the end do not.
8. **The queue table** shows an in-place job's target as "Source, edited in place" (pen icon;
   the tooltip names the source path: "mkvpropedit changes … itself: no new file is
   written."), never the output path, which such a job does not write.

**Checked** in headless Chromium (Playwright 1.64.1, 1440 × 1000 and 390 × 844) against
`scripts/dev-server.py --port 8771 --fixtures multitrack,text-subs --output-fixtures
multitrack,chapters` with the pinned FFmpeg, light and dark, a fresh server home for each run.
The flags (and in a second step a language) were changed through the editor store with
`page.evaluate`, since the tracks' metadata block is task C's; everything else through the UI.
For this check only, `useInPlaceReload()` was added to `App.vue` in the build and taken out
again (not committed). Every in-place edit went to `<server home>/output/multitrack.mkv` (the
script refused any other path). Three edits 80 ms apart sent one `jobs/type` request. A second
opened file is not selected (M4's recorded limit), so the check selected it in the sources panel.

Tests: `useJobType.test.ts` (6), `JobTypeCard.test.ts` (13), `useInPlaceReload.test.ts` (9),
`inPlace.test.ts` (2), `stores/editor.test.ts` (6 for `applyRemuxDraft`), `QueueTable.test.ts`
(1), `SummaryTab.test.ts` (the card in the grid), `jobType.server.test.ts` (3, real server).
44 mutations, each failed its test file (two survived the first run: an equivalent mutant,
replaced, and a queue test whose output path was the source, strengthened).

## Task E — F-10 the defaults dialog and its live preview

Built: `stores/defaults.ts` and `components/defaults/` (`DefaultsDialog`, `SelectionForm`,
`CodecRuleTable` with `CodecRuleExtras`, `PassthruForm`, `SubtitleOptions`, `DefaultsPreview`,
`IssueLines`; `model.ts`, `options.ts`, `codecs.ts`, `preview.ts`).

**What the server gives** (checked 2026-11-01 against `scripts/dev-server.py` with the pinned
FFmpeg; kept in `stores/defaults.server.test.ts`):

- M6 demo 5 on `dts-hd-ma` with the rules `Hungarian 5.1 or more → AC-3 5.1, max 320`,
  `English 5.1 or more → AC-3 5.1, max 384` above the built-in *H.265 MKV 1080p*'s catch-all
  (AAC stereo 160, re-encode) and AC-3 ticked as a passthru codec (that preset allows none):
  track 1 (hun DTS-HD MA 5.1) rule 1, AC-3 5.1 · 320 kb/s, "Lossless source → encode at the max",
  with `measure` (no bitrate in the file); track 2 (eng AC-3 5.1 224 kb/s) rule 2, passthru,
  "AC-3, 5.1, 224 ≤ 384: passthru"; track 3 (eng AC-3 2.0 192 kb/s) rule 3, AAC stereo 160,
  "Rule 2 needs 5.1 or more. Rule 3 matches. The rule says re-encode, 192 > 160 → encode at the
  max". With no language in the preset or Settings every track is kept, and burn-in and foreign
  audio search do not run (0031 item 1).
- Issue paths index the rules from 0 (`audio_defaults.codec_rules[1]`, `….max_bitrate`,
  `….codec`, `….extras.extra_outputs[0].codec`, `audio_defaults.passthru.fallback_encoder`); the
  messages count from 1 ("Rule 2 never applies"). Fixes target `template` and patch
  `/audio_defaults/…`; a codec the container cannot hold also offers `/output/container`.

**Choices.**

1. **A copy is edited.** The dialog edits a copy of the defaults (`completeAudio` /
   `completeSubtitles` fill what a hand-written preset leaves out and keep unknown members).
   Nothing changes before *Apply* or *Save*; *Cancel* and Escape drop the copy.
2. **The preview.** `presets/defaults/preview` with the edited defaults (the other kind is the
   template's: the subtitle defaults need the audio language), the target's container and one
   source: the editor's job, else the active source; none: the preview says why. It is sent at
   once when the dialog opens, 250 ms after the last edit, and at once when the source is read
   again (a **Measure** in the preview's reason cell, where the server sets `measure`). The
   editor's `latestRequest` aborts a waiting or running request, so an older answer is never
   shown; while a newer one is due the table is marked busy and the fixes are off (their paths
   are the shown answer's). A refusal shows its detail instead of the table (no toast: the
   preview runs at every edit).
3. **Issues at their places.** Each rule has a stable key; an issue's rule index is turned into
   the key of the request it answers, so it stays with its rule when the rules move before the
   next answer. A rule's issues (its own and its fields') show in a line under the rule, with
   their fixes; the selection, passthru and subtitle fields show theirs; the rest are listed under
   the preview, whose header counts them all. A fix is offered only when each of its operations
   stays inside the edited defaults: switching the container is not the dialog's to do.
4. **Languages.** "Use the preferred … languages of Settings → Languages" is `languages: null`
   (the list of Settings is shown); unticking it starts an own list with that list. An empty own
   list means Settings too (0031), and the dialog says so.
5. **The codec-rule table** is a plain table, one `tbody` per rule (its row, its issue line and its
   expanded settings), dragged by its handle and moved by buttons that keep the focus. The
   catch-all is locked: a lock instead of the handle, *Any language* and *Any*, no move or remove,
   and the rule above it cannot move below it. *Add rule* inserts above the catch-all a rule with
   *5.1 or more* and the catch-all's codec and max (a second *Any / Any* rule would make the
   catch-all unreachable). One language is chosen in the row (`LanguagePicker`, *Any language* as
   none); several are edited in the expanded row (`LanguageListEditor`), which also holds the
   sample rate, gain, DRC, loudness, name template, *only for the first track of this language* and
   the extra outputs. A snapped max bitrate is the server's `defaults.bitrate_snapped` note with
   its fix; the client does not snap.
6. **Targets** (decision item 4). *Job*: the defaults of the job's preset
   (`editor.currentTemplate`). *Apply* sends `jobs/explain` with the template and the edited
   defaults and sets `/audio` or `/subtitles` to the answer: one undo step; an answer that comes
   after another job was opened is dropped, and the dialog closes when another job is opened.
   *Save to preset…* (a user preset) asks first, then writes only this kind's defaults into it and
   stays open, so that they can still be applied. A built-in preset offers *Save as new preset…*:
   a new user preset from the job's template with the edited defaults (as *Save as new preset* of
   the preset picker); the job keeps its preset. *Preset*: a user preset's *Save* (on once
   something changed) writes only this kind's defaults and closes; a built-in's are read-only
   (every control off, no fixes, *Close* only; *Measure* still works). *Group*: a toast says that
   it is not built yet; no dialog.
7. **Escape** is the dialog's own (on the dialog, and on the page when the focus is on no control
   and no dialog of its own is above it), so that the language picker, the confirmation and the
   name dialog close alone. PrimeVue's `Select` stops every Escape, open or not: Escape on a
   focused select does not close the dialog.
8. A window under 48rem wide or 40rem high gets one scroll area instead of the two panes.

**Limits.** No lint without an open source (no route lints a template alone). *Apply* replaces
every subtitle track, external files too, as *Reload from preset rules* does (one undo brings them
back). The source cell names the track as the source table does and adds its stream index
(`stream #4`), because the reasons name tracks by stream index (`best quality takes #4`).

**Checked** in headless Chromium (Playwright 1.64.1) against `scripts/dev-server.py --port 8780
--fixtures dts-hd-ma,multitrack,text-subs` with the pinned FFmpeg, light and dark at 1440 × 900,
and 390 × 844: demo 5 built through the UI (rows as above); typing `320` (keys 60 ms apart) sent
one preview, 387 ms after the first key; Escape in the language picker leaves the dialog open;
keyboard and drag moves (a drop on the catch-all does nothing); a shadowed rule and a snapped
max with their fixes at the rules; an extra output in the preview; **Measure** in the preview
(the reason follows the measured bitrate); *Apply* (the Audio tab shows AC-3 320, passthru, AAC
160), `Ctrl+Z` and `Ctrl+Shift+Z`; Escape after an edit leaves the job as it was; the subtitle
dialog on `multitrack` (English, first track, foreign audio search, burn-in) and *Apply*; the
presets view: a built-in read-only, a user preset's subtitle defaults saved (read back with
`GET /api/presets/{id}`); the empty state without a source; the focus starts on the close button
and returns to *Defaults…*. Tests: 58 unit tests (store 27, model 9, preview text 4, rule
table 6, dialog 6, selection 2, preview table 4) and 4 in `stores/defaults.server.test.ts`
against a real server; every test function was failed by a mutation of the code (62 mutations). One survived at first:
the Escape test sent no `code`, which PrimeVue reads; the test was fixed and the confirmation's
own Escape handler, which no mutation could break, removed.

## Task G — F-17 flow 1

(Written by G.)

## Review

(Written by the lead after the reviews: the findings, their outcomes, the fix rounds.)

## M6 demo

(Written by the lead.)
