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

(Written by A.)

## Task B — F-10 the Measure button and the scans

(Written by B.)

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
