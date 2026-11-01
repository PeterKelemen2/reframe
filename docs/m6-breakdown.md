# M6 task breakdown

Working notes of the lead for the branch `m6-tracks-and-metadata`: milestone M6, tracks and
metadata. The plan ([plan/08-roadmap.md](plan/08-roadmap.md) §M6,
[plan/06-web-app.md](plan/06-web-app.md) §F-10, §F-11, §F-15, §F-17, and
[plan/03-features.md](plan/03-features.md) §Summary, §Audio, §Subtitles, §Track metadata &
languages, §Chapters, §Tags, §Remux-only jobs, §Settings) is the spec; this file says who builds
which part, in which order, and what each part must offer to the others. Decision:
[0065](decisions/0065-m6-tracks-and-metadata.md) (the lead's choices and one section per task).
Status: [status.md](status.md). The template is [m4-breakdown.md](m4-breakdown.md). If the lead's
context is summarised, this file and `status.md` are the source of truth.

M6's core parts (C-10 scans, C-12 rule engine and defaults, C-13 metadata and in-place edits) are
done and merged ([0029](decisions/0029-core-before-the-ui-milestones.md)); M6 builds the UI on
them, and S6 adds the routes the UI needs that the server does not have.

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| S6 | S-2 (additions) | The routes F-11, the external subtitle import and the Summary job type need: the output's chapters, chapter import and export, rendered tags, the job type with its reason, `fs/list` for other file types (M4's L5), an external subtitle file's format and character encoding | 06 §S-2; 03 §Chapters, §Tags, §Subtitles, §Remux-only jobs |
| A | F-10, F-15 | `LanguagePicker`, `LanguageListEditor`, Settings → Languages | 06 §F-10, §F-15; 03 §Track metadata & languages, §Settings |
| B | F-10 | The **Measure** button and the three scans (bitrate, subtitle events, loudness): task progress, cancel, the source read again when a scan ends | 06 §F-10; 03 §Audio, §Subtitles |
| F | F-11 | Chapters and Tags tabs | 06 §F-11; 03 §Chapters, §Tags |
| C | F-10 | `TrackMetadataEditor` (audio, subtitles and video), bulk edit, external subtitle import (through `Platform`) | 06 §F-10; 03 §Track metadata & languages, §Subtitles |
| D | F-6 (rest) | The Summary tab's job type (encode, remux, `metadata_edit`) and why; *Edit in place*; a remux-only draft; the `inplace.*` issues | 06 §F-6; 03 §Summary, §Remux-only jobs |
| E | F-10 | The **Defaults dialog** (audio and subtitles) with its live preview, from the tabs and the presets view | 06 §F-10; 03 §Audio defaults, §Subtitles |
| G | F-17 | Flow 1 (Playwright) | 06 §F-17 |

**Out of scope** (do not start): F-7, F-8, F-13, F-16, the F-9 advanced panel, F-17 flows 2 and
4, M5 and every `D-x`. The batch-group case of the defaults dialog is typed (`DefaultsTarget`
`kind: 'group'`) and not built (M7).

Defaults the lead took where the plan leaves a choice (each in 0065):

- Folders: `LanguagePicker` and `LanguageListEditor` in `components/language/`;
  `TrackMetadataEditor`, the flag toggles and the bulk edit dialog in `components/tracks/`
  (the plan's structure named `components/metadata/`; 06 §Structure is updated).
- Chapter import takes the **names**, by position; the times a file holds are compared with
  the output's chapters (a warning when they differ) and not kept: `ChapterSettings` holds
  names only, as HandBrake's import does.
- The defaults dialog opened from a tab edits the defaults of the job's preset and applies them
  to the job's tracks (one undo step); the job keeps no defaults of its own (`JobSettings` has
  none). Saving them goes into a user preset; a built-in preset's defaults are shown read-only.
- An in-place edit in web mode needs a source the server may read and write: a folder that is
  a media root and an output root. Otherwise the server gives `inplace.not_allowed`.
- External subtitles: the character encoding is detected from a byte order mark or valid UTF-8
  only (no new dependency); anything else is "not detected" and the user picks one.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0065, the skeleton, `scripts/dev-server.py --output-fixtures` | `main` (4ae0988) |
| 1 | A (`high`), B (`high`), F (`high`), S6 (`xhigh`) | the skeleton |
| 2 | C (`high`; needs A's `LanguagePicker` and S6), D (`xhigh`; needs S6), E (`xhigh`; needs A) | wave 1 merged |
| 3 | G (`high`) | wave 2 merged |
| 4 | two fresh `xhigh` reviews (R1: API layer use, stores, scans, the defaults preview's debounce and stale answers, undo / redo of track edits, the in-place and job-type paths, validation; R2: the screens, i18n, keyboard, focus, light and dark contrast, empty and error states), the fixes (`xhigh` for blockers and majors, `high` for minors), the M6 demo headless and once headed by the lead, H (comment trim, `haiku`, only if the owner agrees), the docs | wave 3 merged |

F runs beside S6 and codes against S6's contract (the hand-written types in `api/types.ts`);
its checks against a real server wait for S6's merge (the lead tells F, or resumes it).

At most four worktrees at a time. The lead merges each task with `--no-ff`, runs the frontend
commands (and the Python checks for S6), mutates once per task, and removes the worktree and
its branch.

Every agent: `model: "opus"` (H: `haiku`), an explicit `effort` (the table above),
`isolation: "worktree"` for code.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Paths are
relative to `frontend/src/` unless they start with `frontend/`, `docs/`, `scripts/`, `testdata/`
or `packages/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **S6** | `packages/**` (the server's routers and their models, the core functions they call, their tests), `frontend/src/api/schema.d.ts` (regenerated only), `components/sources/{FileBrowserDialog.vue,fileBrowser.ts}` and their tests (only so that `platform.pickFiles({ filters })` lists those files through `fs/list?extensions=`), `testdata/README.md` (its own heading) | every other file of `frontend/` |
| **A** | `components/language/**`, `components/settings/LanguagesSection.vue`, `i18n/messages/en/language.json`, the `languages` keys of `i18n/messages/en/settings.json` | the other Settings sections, `views/SettingsView.vue` |
| **B** | `components/media/**`, `stores/scans.ts`, `sources.reload` in `stores/sources.ts` (that function only), `i18n/messages/en/media.json` | the rest of `stores/sources.ts`, `components/tracks/**` |
| **F** | `components/editor/tabs/{ChaptersTab,TagsTab}.vue`, `components/chapters/**`, `components/tags/**`, `i18n/messages/en/{chapters,tags}.json` | `components/naming/**` (use it) |
| **C** | `components/tracks/**`, `components/editor/tabs/{AudioTab,SubtitlesTab}.vue`, `i18n/messages/en/tracks.json` | `components/language/**` (use it), `components/media/**`, `components/editor/tabs/VideoTab.vue` (the lead placed the video track's `TrackMetadataEditor`) |
| **D** | `components/summary/**`, `components/editor/tabs/SummaryTab.vue`, `components/queue/**` (only for an in-place job's line), `i18n/messages/en/{summary,queue}.json` | `stores/editor.ts`, `stores/sources.ts` (use them) |
| **E** | `components/defaults/**`, `stores/defaults.ts`, `i18n/messages/en/defaults.json` | `components/language/**` (use it), `components/tracks/**`, `components/presets/**` |
| **G** | `frontend/e2e/**` except `frontend/e2e/layout.spec.ts` and `frontend/playwright.config.ts` | every file of `src/`, `frontend/package.json` |

**Lead-owned**: `frontend/package.json`, `frontend/package-lock.json`, `api/schema.d.ts`
(except S6's regeneration), `api/types.ts`, `router/**`, `components/editor/tabs/registry.ts`,
`i18n/index.ts`, `i18n/messages/en/app.json`, `setup.ts`, `main.ts`, `notBuilt.ts`, `App.vue`,
`stores/{toasts,ui,editor,validation}.ts`, `composables/**`, `platform/**`,
`views/SettingsView.vue`, `components/editor/tabs/VideoTab.vue`, the defaults buttons of
`components/tracks/OutputTrackList.vue` and `components/presets/PresetDetails.vue`,
`frontend/vite.config.ts`, the tsconfigs, `frontend/playwright.config.ts`,
`scripts/dev-server.py`. An agent that needs another dependency, a route, a registry entry or a
change of these files asks the lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own step's row (A: F-15's row and the
  `LanguagePicker` part of F-10's; B, C, E: their parts of F-10's row, each in its own
  sentence; S6: the S-2 row; F: F-11; D: F-6; G: F-17).
- `docs/decisions/0065-m6-tracks-and-metadata.md`: each task writes only its own section
  ("Task X").
- `docs/plan/06-web-app.md`: a task ticks its own step's boxes, and edits its step's text only
  together with a decision (its 0065 section).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. The signatures are in the skeleton's files (read them; they are the source); this is
their summary. A task may add members, optional parameters with defaults, files and
components in its own folders, but not change these. `notBuilt(…)` marks a stub: replace it,
and remove the `oxlint-disable` line at the head of a stub store you build.

### S6: the new routes

All under `/api`, in `reframe-server`, each with a typed response model (the TypeScript names
below are the Python models' names; the lead switches `api/types.ts` to `Schemas['…']` after
the merge). The core logic lives in `packages/reframe` (pure where it can be), the routes jail
every path (`security.jail_read` / `jail_write`), and `scripts/gen-api.sh` regenerates
`schema.d.ts`. Whether `API_VERSION` changes is S6's call in its 0065 section (these are
additions).

| Route | Body | Answer | Notes |
|-------|------|--------|-------|
| `POST /jobs/type` | `{job}` | `JobTypeInfo {job_type, reason, in_place_blockers}` | `reframe.command.jobtype.job_type` and `in_place_blockers` (for any job, so the UI can say why *Edit in place* cannot be used before it is chosen; for a non-MKV source the first blocker says so). Reads the source; refuses no in-place edit (validation reports `inplace.*`) |
| `POST /jobs/chapters` | `{job}` | `OutputChapters {origin: 'source' \| 'generated' \| 'none', chapters: OutputChapter[], reason}`; `OutputChapter {number, start, end, name, source_name}` | The chapters the output gets, in output time: the range, renamed names, generated chapters, the container's support, *Create chapter markers* off. One core function that `chapter_plan` uses too, so the table and the command never differ |
| `POST /chapters/import` | `{path, format?: 'csv' \| 'ogm' \| 'xml' \| null}` | `ChapterImport {format, chapters: ImportedChapter[], issues}`; `ImportedChapter {start: number \| null, name}` | CSV as HandBrake writes it, OGM text (`CHAPTERnn=` / `CHAPTERnnNAME=`), Matroska XML; `null`: from the content. Read jail; a file that cannot be read is a 422 problem with the line; a size limit |
| `POST /jobs/chapters/export` | `{job, format}` | `ChapterExport {format, file_name, content}` | The output's chapters (as `/jobs/chapters`) in the format; `file_name` from the output's stem. A job without chapters is a 422 problem |
| `POST /jobs/tags` | `{job}` | `RenderedTags {values, source, issues}` (each keyed by the eight `TagSettings` names) | `values`: each tag as it will be written (`render_tag`, `null` when unset); `source`: the source file's value; `issues`: template errors at `tags.<name>` |
| `GET /fs/list?path=…&extensions=.srt&extensions=.ass` | — | `FsListing` (unchanged) | `extensions` (repeatable, case-insensitive): list files with these extensions instead of media files; folders as before. Without it nothing changes |
| `POST /subtitles/inspect` | `{path}` | `SubtitleFileInfo {path, format, bitmap, charset, events, issues}` | An external subtitle file before it is added: FFmpeg's codec name (`subrip`, `ass`, `ssa`, `webvtt`, `hdmv_pgs_subtitle`), text or bitmap, the character encoding from a byte order mark or valid UTF-8 (else `null`), the event count. Read jail; an unsupported file is a 422 problem |

Every format and every FFmpeg / ffprobe / mkvmerge behaviour S6 relies on is checked against the
real tools (mkvmerge reads OGM and XML chapter files; ffprobe on a non-UTF-8 SRT) and recorded in
a test or in `testdata/README.md`.

### Types (`api/types.ts`, lead)

New aliases: `AudioCodecRule`, `AudioDefaults`, `SubtitleDefaults`, `Chapter`,
`ChapterSettings`, `TagSettings`, `TagName`, `TrackMetadata`, `TrackFlags`, `ExternalSubtitle`,
`EncodePlan`, `JobType`, `TrackDraft`, `TrackDecision`, `LanguageSettings`,
`DefaultsPreviewRequest`. The scan results (`BitrateScan`, `SubtitleScan`,
`SubtitleScanTrack`, `LoudnessMeasurement`) are written by hand (a task's `result` is untyped in
the schema). S6's types are written by hand until its merge.

### Stores

```ts
// scans (B; stores/scans.ts)
type ScanKind = 'bitrate' | 'subtitle' | 'loudness'
interface ScanRun { sourceId: string; kind: ScanKind; streamIndex: number | null; taskId: string; progress: number | null }
runs: Ref<ScanRun[]>
loudness: Ref<Record<string, LoudnessMeasurement>>    // by `${sourceId}:${streamIndex}`
running(sourceId, kind, streamIndex?: number | null): ScanRun | undefined
measureBitrate(sourceId, streamIndex): Promise<void>  // then sources.reload(sourceId)
scanSubtitles(sourceId, streamIndexes?: number[]): Promise<void>   // then sources.reload(sourceId)
measureLoudness(sourceId, streamIndex): Promise<LoudnessMeasurement | null>
cancel(run: ScanRun): Promise<void>

// sources (B adds one action; the rest is M4's)
reload(id: string): Promise<void>     // GET /api/sources/{id}, put in its place

// defaults (E; stores/defaults.ts)
type DefaultsKind = 'audio' | 'subtitles'
type DefaultsTarget = { kind: 'job' } | { kind: 'preset'; presetId: string } | { kind: 'group'; groupId: string }  // group: M7
visible: Ref<boolean>; kind: Ref<DefaultsKind>; target: Ref<DefaultsTarget | null>
open(which: DefaultsKind, whose: DefaultsTarget): Promise<void>
close(): void
```

The editor store (M4, lead-owned now) is used as M4's contract says: read with `editor.get` /
`editor.job`, write with `editor.set` / `editor.patch` (one undo step each; coalescing keys
named after the validation path, `editor.endCoalescing()` at the end of a gesture),
`beginEdit` / `endEdit` for an edit that is on its way into the job.

### Components used across tasks

| Component | Owner | Props and slots |
|-----------|-------|-----------------|
| `language/LanguagePicker.vue` | A | `v-model: string \| null` (BCP 47), `label?`, `inputId?`, `labelledby?`, `placeholder?`, `disabled?`, `invalid?`, `clearable?` (offers *None* = `null`) |
| `language/LanguageListEditor.vue` | A | `v-model: string[]`, `label`, `disabled?` |
| `tracks/TrackMetadataEditor.vue` | C | `list: 'video' \| 'audio' \| 'subtitles'`, `index?`, `disabled?`; edits `/<list>/<index>/metadata` (`/video/metadata`) |
| `defaults/DefaultsDialog.vue` | E | none; mounted once by `App.vue`, opened through the defaults store (*Defaults…* on the track lists, *Audio defaults…* / *Subtitle defaults…* in the presets view) |
| `editor/tabs/{Chapters,Tags}Tab.vue` | F | none; read and write the editor store |

The registry shows all six built tabs plus Chapters and Tags (`Ctrl+7`, `Ctrl+8`). Settings
shows Languages between Output and Queue.

### i18n

As M4: `i18n/messages/en/<area>.json` holds the keys of `<area>.`. New areas: `language`
(A), `media` (B), `chapters` and `tags` (F), `defaults` (E). The lead added
`tracks.output.defaults`, `presets.details.audioDefaults` / `subtitleDefaults`,
`video.sections.metadata` and `settings.languages.title`.

## Done when (word for word in each agent's brief)

Every "in a browser" check runs headless against a real `reframe-server` started with
`scripts/dev-server.py` and the pinned FFmpeg, in light and dark, with screenshots read by the
agent.

- **S6**: Each route answers as the contract says against a real server with the pinned
  FFmpeg: `jobs/type` gives `metadata_edit` for a flags-only change of an MKV with *Edit in
  place*, `remux` and `encode` with their reasons, and the blockers otherwise; `jobs/chapters`
  equals the chapters the encoded file has (re-probed) for a renamed source, a chapter range and
  generated chapters; a CSV, OGM and XML file that `jobs/chapters/export` wrote is read back by
  `chapters/import` with the same names, and mkvmerge accepts the OGM and XML files; `jobs/tags`
  renders `{name}< – S{season:02}E{episode:02}>` for an episode; `fs/list` with `extensions`
  lists `.srt` and `.ass` files; `subtitles/inspect` names the format, the event count and the
  encoding of a UTF-8 and of a non-UTF-8 SRT; every path outside the roots is refused in web
  mode. `scripts/gen-api.sh --check` passes; the Python commands are green.
- **A (F-10, F-15)**: In a browser: the `LanguagePicker` finds a language by English name,
  native name, ISO 639-1, 639-2 and 639-3 code and full BCP 47 tag (`pt-BR`, `es-419`,
  `zh-Hans`, `sr-Latn`), lists the favourites first, shows what will be written
  (`Hungarian · hun (ISO 639-2) · hu (BCP 47)`), and works with the keyboard alone; Settings →
  Languages edits the favourites and the preferred audio and subtitle languages (add, remove,
  reorder), each change saved at once and a refused value shown at its field; a new favourite
  is first in the picker at once.
- **B (F-10)**: In a browser: the `dts-hd-ma` fixture's DTS-HD MA track shows `—` and
  **Measure**; Measure shows the task's progress and can be cancelled, and when it ends the
  bitrate appears, marked as measured, without opening the file again (M6 demo 1); a subtitle
  scan fills the event counts (and the forced counts of a PGS track, `pgs` fixture); a loudness
  scan of an audio track shows integrated loudness, true peak and loudness range; the
  `multitrack` commentary track shows its badge with no click, and its tooltip says where the
  role came from (M6 demo 2); a failed or cancelled scan leaves the table as it was, with a
  toast for a failure.
- **F (F-11)**: 06 §F-11: "Chapter table with inline name edits, import/export, generate. Tag
  form with templates." In a browser with the `chapters` fixture: the Chapters tab shows the
  output's chapters (number, start, duration, name), a name edits inline (one undo step), *Create
  chapter markers* turns them off, the names reset to the source names or to `Chapter N`, import
  of a CSV, OGM and Matroska XML file sets the names, export in each format downloads the output's
  chapters, and *Generate chapters every N minutes* shows the generated chapters for a source
  without chapters; the Tags tab edits the eight tags with naming-variable completion, shows each
  value as it will be written and the source's value, and a template error shows at its field;
  an encode with renamed chapters and a Title tag, re-probed, has them.
- **C (F-10)**: In a browser: every output audio and subtitle track, and the video track, has
  the metadata block (language through the `LanguagePicker`, name as text or a name template, the
  six flags), each change one undo step and issues at their fields; selected tracks are edited
  together (language or flags for all, one undo step); an external `.srt`, `.ass`, `.ssa`,
  `.vtt` or `.sup` file is added through `Platform.pickFiles` with its language, name, flags,
  time offset and character encoding (the detected one shown and changeable); M6 demo 3 passes:
  set languages (`hu`, `pt-BR`), names and flags (commentary, SDH, original) → queue → done →
  the re-probe shows them all.
- **D (F-6)**: 03 §Remux-only jobs: "The Summary tab shows which job type you will get, and
  why." In a browser: the job type (encode, remux, metadata edit) and its reason update after
  each edit (the newest answer only); *Edit in place* for an MKV turns a metadata-only change into
  a `metadata_edit` job, and when it cannot be one the reason and the `inplace.*` issues show
  with their fixes (another container, a changed track set or order, a source the server may not
  write); a remux-only job can be drafted; M6 demo 4 passes: change only flags on an MKV → the
  job type is `metadata_edit` and the queued job finishes in under a second; the source is read
  again and shows the new flags. Nothing in a test or a check writes to a media file outside
  the temp folders.
- **E (F-10)**: In a browser: *Defaults…* on the Audio and Subtitles tabs and *Audio
  defaults…* / *Subtitle defaults…* in the presets view open the dialog: the selection settings
  (languages through `LanguageListEditor`), the codec-rule table (drag to reorder, the catch-all
  row locked, expandable rows for the optional settings), the passthru check boxes and the
  fallback encoder (audio); the selection, foreign audio search, burn-in and default track
  (subtitles); and the live preview table (`presets/defaults/preview`, 250 ms after the last
  edit, only the newest answer shown, one row per source track with its reason). M6 demo 5
  passes on `dts-hd-ma`. Applying the defaults to the job replaces its tracks in one undo step; a
  user preset's defaults are saved into it; a built-in's are read-only. Unit tests show the
  debounce and that a stale answer is never shown. The batch-group target is typed, not built.
- **G (F-17)**: 06 §F-17 flow 1: "Open a file → set an audio language and commentary flag →
  queue → done → re-probe shows the flags." `npm run e2e` (headless Chromium and Firefox) passes
  flow 1 twice in a row next to flow 3 and the layout checks, and leaves no process and no
  temporary folder behind.

## The M6 demo (the acceptance test; the lead runs it at the end)

1. A DTS-HD MA track with no bitrate in the file → **Measure** → a bitrate appears.
2. A commentary track shows its badge with no click. The tooltip says where the role came from.
3. Set languages (`hu`, `pt-BR`), names and flags (commentary, SDH, original) → queue → the
   re-probe shows them all.
4. Change only flags on an MKV → the job type is `metadata_edit` and finishes in under a second.
5. Audio defaults `Hungarian 5.1 or more → AC-3 5.1, max 320` and `English 5.1 or more → AC-3
   5.1, max 384`: the live preview shows that DTS-HD MA becomes AC-3 320, an AC-3 224 kb/s source
   is passed through, and a stereo track falls to the next rule. Each row has a reason.

Plus F-17 flow 1: open a file → set an audio language and commentary flag → queue → done →
re-probe shows the flags (Chromium and Firefox, headless). First headless (Playwright, with the
screenshots read), then once headed by the lead on `HDMI-A-1` through the guard.

The fixtures: `dts-hd-ma` (hun DTS-HD MA 5.1 without a bitrate, eng AC-3 5.1 224 kb/s, eng AC-3
2.0 192 kb/s) for 1 and 5; `multitrack` (eng *Director's Commentary* with the comment flag) for 2
and 3; for 4 an MKV copied with `dev-server.py --output-fixtures`, which the server may write.

## Commands

As [m4-breakdown.md](m4-breakdown.md#commands). New: `scripts/dev-server.py --output-fixtures
NAMES` copies fixtures into the output root and makes it a media root too, so that an in-place
edit is allowed in web mode (a source in the media root alone gives `inplace.not_allowed`).

**Ports** (rule 7): agent N uses 87N0 to 87N9. A 871x, B 872x, F 873x, S6 874x, C 875x,
D 877x, E 878x, G 879x; reviewers R1 871x, R2 872x; fix agents take the ranges free at the
time. The lead uses 876x (8765 is the dev proxy's default).

## Rules for every agent (word for word in each brief)

### Rule 5: the code

- Use CLAUDE.md. Comments follow the `code-comments` skill: they say why, and never contain
  step IDs, plan sections or history. Strict TypeScript. PrimeVue 4 and TypeScript 6 stay
  (0003). Every visible string goes through vue-i18n.
- All of this is green before a step is done, from `frontend/`: `npm run lint`,
  `npm run fmt:check`, `npm run typecheck`, `npm test`, `npm run build:web`. From the root:
  `scripts/gen-api.sh --check`, and for any `packages/` change `uv run ruff check`,
  `uv run ruff format --check`, `uv run mypy`, and the tests of what changed.
- Frontend work is checked in a real browser, not only with unit tests: headless Chromium (the
  Playwright cache has chromium and firefox) against a real `reframe-server`. The agent reads
  its screenshots (with the Read tool) and says what it saw, for light and dark.
- Real behaviour of FFmpeg or the server is checked against the real thing and recorded in a
  test or a decision record, not taken from memory.

### Rule 6: displays, windows and the pointer (binding for the lead and every agent)

The owner has two displays: `HDMI-A-1` (secondary, at 0,0, 1920x1080) and `DP-1` (primary, at
1920,0), where a movie may be playing. Nothing may open a window on `DP-1`, take its keyboard
focus, move the pointer onto it or click on it. Do not ask the owner which display is which.

- **Default: headless.** Subagents run Playwright headless (Chromium or Firefox), which opens no
  window. A subagent never opens a window and never uses the real pointer or keyboard. That means
  no headed browser (`headless: false`, `--headed`), no `playwright test --ui`, `codegen`,
  `show-report` or `open`, no `vite --open`, no `xdg-open`, no desktop app, no `xdotool`,
  `ydotool`, `kdotool` or `/dev/uinput`, and no browser-use plugin (it drives the owner's own
  Chrome). If a subagent thinks it needs a headed check, it says so in its report and does the
  check headless.
- **Headed checks and clicking around are done only by you, one at a time** (there is one
  display and one pointer, so never while another headed run is active), and only through the
  spike's guard in `desktop/spike/scripts`: start the browser under
  `uv run python -m desktop.spike.scripts.windows run -- <command>`, or with
  `windows.Session.wrapper(binary, spot)` as Playwright's `executablePath`, with `spot` inside
  `HDMI-A-1` (x 0 to 1919, y 0 to 1079); click and move only through `pointer.for_session` (it
  refuses a point outside `HDMI-A-1`). Read its "Window session" section first.
- The guard starts a program only when the owner's cursor and the active window are on
  `HDMI-A-1`. Before your first headed step, ask the owner once to put the mouse and the active
  window there, and tell them when you are done.
- If the guard refuses or raises (`Refused`, `WrongOutput`), or does not work, stop that headed
  step. Do not retry in a loop and do not open the window by another way. Do the check headless
  and report it as "not checked headed".
- Gaps the guard does not close (README): the owner moving the cursor to `DP-1` during the
  program's start (about 0.5 s), a later window of an admitted program (a dialog, a popup, a
  second window), and a program started outside the session. So keep headed runs short, open
  no native dialog, file chooser or second window in them, and close what you start
  (`windows.terminate`).

("You" is the lead. The skeleton enforces part of it: `playwright.config.ts` fixes
`headless: true` in every project and has no HTML reporter, which opens a browser when a test
fails; `package.json` has no `--ui`, `--headed` or `open` script; `vite.config.ts` has no
`server.open`.)

### Rule 7: safety

- Every server an agent starts uses isolated data, config and cache folders in a temp directory
  (copy how the existing `reframe-server` subprocess tests do it, and use
  `reframe_testing.folders_guard`), `REFRAME_POWER_DRY_RUN=1`, `--mode web --auth token`, and
  media and output roots inside the temp directory. Never use the owner's real data directory,
  and never a `when_done` of `sleep` or `shutdown` without the dry-run flag.
- Give each agent its own port range (agent N gets 87N0 to 87N9; the Vite dev proxy defaults to
  8765, so set it from an env var in your skeleton) so that parallel agents do not collide.
- Disk space is limited: at most 4 worktrees at once, and remove each worktree and its branch
  as soon as it is merged. Run the full Python suite only alone and in the foreground, in chunks
  that fit the 10-minute command limit. While agents run, run only static checks and targeted
  tests.
- Merge conflicts are almost always adjacent rows of `docs/status.md`: resolve per row against
  the merge base.

(`scripts/dev-server.py` does the first point for a browser check; a test that starts a server
from pytest uses the `reframe_testing` server harness and `folders_guard`.)

### Test rules

A test is meaningful only if it fails when the code has a defect that a user would see. Before
you write a test, name that defect in one sentence. If you cannot name one, do not write the
test.

- Write tests for: what your "Done when" requires; each store action's contract (the request
  it sends, the state after the answer, every expected failure); event handling, ordering,
  reconnect and resync; undo / redo; every branch you wrote, one case per branch.
- Do not write tests of Vue, Pinia, PrimeVue, vue-i18n, openapi-fetch or the browser
  themselves; snapshot tests of whole components; tests that a mock returned what the test
  told it to; tests of the skeleton's stubs or of test helpers.
- Mutation check before you report: for each test file, break the code it tests on purpose at
  least once per test function (drop the debounce, invert a condition, skip the resync, apply
  a patch twice). The test must fail, then pass again when you restore the code. A test that
  still passes is wrong: fix it or delete it.
- In the report: the tests per file, the mutations and their results.

## Every agent prompt includes

- The task, its step, the plan sections to read, the owned and forbidden files, the contracts
  it builds and the ones it uses, its "Done when" word for word, its section of 0065,
  rules 5, 6 and 7 and the test rules word for word, its port range.
- Setup: the worktree starts at `main`: first `git merge --ff-only m6-tracks-and-metadata`. Then
  `uv sync`, `npm ci` in `frontend/`, and
  `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (`--tools-dir` of `scripts/dev-server.py`); `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not
  installed.
- Commits per step, step ID first (`F-10: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Update only its own
  `docs/status.md` row.
- The report: the real output of every command of rule 5 (the last lines), what the agent saw
  in its screenshots (light and dark), the test rules' checks, every deviation from the plan
  and from this file, every file touched outside its list, and what later tasks need.

### Changes for M6 (binding, with the rules above)

- The worktree starts at `main`: every agent first runs
  `git merge --ff-only m6-tracks-and-metadata`.
- Commits start with the step ID (`F-10: …`, `F-11: …`, `S-2: …`) and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (Haiku agents:
  `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`).
- Each agent updates only its own `docs/status.md` row (or its own sentence of a shared row) and
  writes only its own section of 0065.
- Ownership: each task has its own folders ("Who owns which files"); anything else goes back to
  the lead.
- D and E: nothing in a test or a check may write to a media file outside the temp folders.
  An in-place edit runs only on a copy inside a temp folder (`dev-server.py --output-fixtures`,
  or a test's `tmp_path`), never on `testdata/media/` or the main checkout's files.

## Progress

| Date | What |
|------|------|
| 2026-11-01 | **Wave 0.** Preflight on `main` 4ae0988: clean tree; 9.9 GB free (a worktree with `node_modules` and `.venv` is about 0.5 GB). Wave 0 check of the API: the scans (`/api/sources/{id}/streams/{index}/bitrate-scan`, `/subtitle-scan`, `…/loudness`), `presets/defaults/preview` (with `source_ids`, so the batch case can come later), `jobs/draft-remux`, the language list and `LanguageSettings` exist; missing: chapter import / export, the output's chapter list, rendered tags, the job type's reason (only `job_type` inside `jobs/plan`), `fs/list` for other file types (M4's L5), an external subtitle's encoding → **task S6** (wave 1, `xhigh`). Checked against a real server: an in-place edit of a source in the media root is `inplace.not_allowed`; a copy in a folder that is a media and an output root plans as `metadata_edit` (`dev-server.py --output-fixtures`, new). Branch `m6-tracks-and-metadata`; this file; 0065 with placeholders; the skeleton (stubs, registry, Settings section, the defaults buttons, the dialog mounted, types). Checks: lint, format, typecheck, 1008 unit tests, `build:web`, `gen-api.sh --check`, ruff, mypy |
