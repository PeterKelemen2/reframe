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
