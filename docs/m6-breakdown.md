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
| **D** | `components/summary/**`, `components/editor/tabs/SummaryTab.vue`, `components/queue/**` (only for an in-place job's line), `i18n/messages/en/{summary,queue}.json`, one new action in `stores/editor.ts` (the remux-only draft as one undo step, modelled on `applyPreset`) and its tests | the rest of `stores/editor.ts`, `stores/{sources,queue,validation}.ts` (use them), `App.vue` (the lead mounts D's after-edit reload composable) |
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
| `POST /jobs/chapters` | `{job}` | `OutputChapters {origin: 'source' \| 'generated' \| 'none', chapters: OutputChapter[], reason}`; `OutputChapter {number, start, end, name, source_name, source_index}` (`source_index`: the 0-based source chapter, which `ChapterSettings.names` is indexed by; `null` for a generated chapter, whose names are by output position — added 2026-11-01 at F's request) | The chapters the output gets, in output time: the range, renamed names, generated chapters, the container's support, *Create chapter markers* off. One core function that `chapter_plan` uses too, so the table and the command never differ |
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
- Scratch files: the agents share one scratchpad folder. Each agent keeps its scratch files
  (server logs, ready lines, scripts, screenshots) in its own `scratchpad/task-<x>/` and reads a
  server's URL and token only from the ready line of a server it started itself.
- D and E: nothing in a test or a check may write to a media file outside the temp folders.
  An in-place edit runs only on a copy inside a temp folder (`dev-server.py --output-fixtures`,
  or a test's `tmp_path`), never on `testdata/media/` or the main checkout's files.

## Findings for the fix round (the lead's, from the reports and the checks)

| # | Severity | Finding | Seen |
|---|----------|---------|------|
| L1 | major (server) | `jobs/validate` does not know an external text subtitle whose encoding was not detected (`subtitles/inspect` `charset: null`, no `charset` chosen): the job can be queued and fails in FFmpeg (exit 69, "Invalid UTF-8", S6's check). The row shows the warning, nothing blocks *Add to queue*. Expected: a validation issue (error) at `subtitles[i].source.charset`, with the encodings as fixes or a pointer to the field | C's report, S6's tool check |
| L2 | to check (core) | After one chapter rename, the other untitled source chapters are written as `Chapter N` (core `_renamed`); with `names: null` they get no name | F's report |
| L3 | to check | A chapter rename sets the preset's *modified* marker | F's report |
| L4 | known limit (M4) | A second opened file is not selected while another is open; every agent's script had to click it (C, E, F) | M4 "Where M4 ended" |

## Fix round (wave 4; binding for the fix agents)

The two reviews (R1: 2 majors, 5 minors, 5 minors and nits from its Python sub-review; R2: 2 majors, 8 minors, 8 nits) and the lead's findings L1–L3. The lead reproduced every major (Progress, 2026-11-01). No blocker. Four fix tasks with disjoint files. A fix of a major comes with a test that fails before it (a pytest, a unit test, a `*.server.test.ts` or a Playwright spec). Each task writes its own dated section "Fix round — FX" in 0065 "Review".

| Task | Effort | Findings | Owns |
|------|--------|----------|------|
| **FA** core and server | `xhigh` | **R1-M1 / L1**: validation error for an external text subtitle whose encoding is not known (inspect `charset: null`, no `charset` set; the job today ends `done` with U+FFFD text) and for a UTF-16 file (FFmpeg loses letters either way, S6) — at `subtitles[i].source.charset`, with a fix where one exists; **R2-M1 / R1-m5**: tag template errors in `jobs/validate` (the codes and paths `jobs/tags` gives, `tags.<name>`; severity so that a template FFmpeg would write broken blocks *Add to queue*), and the run-time failures of a tag with a NUL byte or of 200 000 characters; **R1-M2 (server part)**: `presets/defaults/preview` takes the template *Apply* uses (contract below); S6 minors s1 (absurd numbers in chapter files → 422, not 500), s2 (a FIFO / non-regular file → 422 at once), s3 (OGM lines split only on `\n` / `\r\n`; the CP1252 fallback), s4 (`subtitle.no_events` when ffprobe omits `nb_read_packets`), s5 (`generate_every` too small: a validation issue and a bounded chapter count, computed off the event loop; no persisted-schema change unless recorded with a migration); L2 (after one rename the other untitled chapters become `Chapter N`: decide and record); the sub-review's nits as FA sees fit | `packages/**`, `frontend/src/api/schema.d.ts` (regenerated), `testdata/README.md` (its heading) |
| **FB** defaults dialog, shortcuts | `xhigh` | **R1-M2 (frontend part)**: the preview sends the template *Apply* uses; a preset (or job preset) with explicit `audio_rules` / `subtitle_rules` says in the dialog that the rules override these defaults; R1-m1 (`Ctrl+Z` / `Ctrl+Enter` act on the job behind a modal dialog after a click on its text: no editor shortcut while a modal is open); R1-m4 (*Save* of defaults reverts another window's changes: read the preset again and change only the defaults); R2-4 (read-only built-in defaults hard to read and cut); R2-5 (the preview's busy state below AA); R2-1 for the dialog (focus after *Measure* in a preview row); the defaults nits (repeated accessible names in a rule's extras, literal fragments in `CodecRuleTable` / `SelectionForm`, the 230 px pane at 1280×800) | `frontend/src/components/defaults/**`, `frontend/src/stores/defaults.ts`, `frontend/src/composables/useShortcuts.ts`, `frontend/src/i18n/messages/en/defaults.json` |
| **FC** tracks, scans, language | `high` | R1-m3 (a bulk edit can change a track the user did not select: the selection keyed by row identity); R2-3 (a single track's selection box does nothing); R2-6 (the Subtitles toolbar at 1280 and 390); R2-1 for Measure / Count / loudness (focus to a sensible control, a polite announcement at the end) and for bulk *Apply* / *Clear*; R2-8 (the picker's error state when `GET /api/languages` failed); show FA's new `subtitles[i].source.charset` issue at the encoding field once, without repeating the inspect warning; the nits in `TrackMetadataEditor` / `ExternalSubtitleFields` (literal `'und'`, quotes and separators), the picker's count including *None*, digit grouping of kb/s | `frontend/src/components/{tracks,media,language}/**`, `frontend/src/stores/scans.ts`, `frontend/src/i18n/messages/en/{tracks,media,language}.json` |
| **FD** chapters, tags, summary, queue | `xhigh` | **R2-M2** (clearing the *Generate chapters* interval: the field shows the job's value again, or clearing turns generation off; no field that disagrees with the job); R2-2 ("1 chapters"); R2-5 for the chapters table and tag values; R2-1 for chapter *Export* / *Import* / Enter in a name, *Remux only* and the in-place fix, the tag fix; R1-m2 / R2-7 (*Remux only* must not turn *Edit in place* on without saying so, and not when `jobs/type` says the folder is read-only); the tags' issues shown once when FA's validation also reports them; L3 (a chapter rename sets the preset's *modified* marker: decide and record); the nits: the chapter import error bullet, "every" + field + "min" fragments, the queue's in-place tooltip not keyboard-reachable and "Video copied" for a metadata edit | `frontend/src/components/{chapters,tags,summary}/**`, `frontend/src/components/editor/tabs/{ChaptersTab,TagsTab,SummaryTab}.vue`, `frontend/src/components/queue/**`, `frontend/src/i18n/messages/en/{chapters,tags,summary,queue}.json` |

**Contract FA → FB (preview).** `DefaultsPreviewRequest` gains an optional `template: JobTemplate | null`. With it, each source's preview is `jobs.explain(source, template with audio_defaults / subtitle_defaults of the request put in)`, so a template's explicit `audio_rules` / `subtitle_rules` apply exactly as in *Apply*; without it, nothing changes. Template paths are jailed as `jobs/explain` does. FB sends the same template that *Apply* sends. Additive: `API_VERSION` stays 1.

**Contract FA → FC, FD (issues).** The new validation issues carry these paths. The UI shows each issue once, at its field. Where a route (`subtitles/inspect`, `jobs/tags`) already reports the same code at the same field, it is not repeated.
- The encoding issue: `subtitles[i].source.charset`.
- The tag issues: `tags.<name>`, with the same codes as `jobs/tags`.

Not fixed in M6 (recorded): R2's suspicion about the file browser's Path + Go race (M4 code); R1's suspicions (another window's table after *Measure*: no source-change event; the `subtitles/inspect` cache for the page's life); L4 (M4's second opened file not selected).

## Progress

| Date | What |
|------|------|
| 2026-11-01 | **Wave 0.** Preflight on `main` 4ae0988: clean tree; 9.9 GB free (a worktree with `node_modules` and `.venv` is about 0.5 GB). Wave 0 check of the API: the scans (`/api/sources/{id}/streams/{index}/bitrate-scan`, `/subtitle-scan`, `…/loudness`), `presets/defaults/preview` (with `source_ids`, so the batch case can come later), `jobs/draft-remux`, the language list and `LanguageSettings` exist; missing: chapter import / export, the output's chapter list, rendered tags, the job type's reason (only `job_type` inside `jobs/plan`), `fs/list` for other file types (M4's L5), an external subtitle's encoding → **task S6** (wave 1, `xhigh`). Checked against a real server: an in-place edit of a source in the media root is `inplace.not_allowed`; a copy in a folder that is a media and an output root plans as `metadata_edit` (`dev-server.py --output-fixtures`, new). Branch `m6-tracks-and-metadata`; this file; 0065 with placeholders; the skeleton (stubs, registry, Settings section, the defaults buttons, the dialog mounted, types). Checks: lint, format, typecheck, 1008 unit tests, `build:web`, `gen-api.sh --check`, ruff, mypy |
| 2026-11-01 | **Wave 1 started**: S6 (`xhigh`, 874x; also owns the file browser's `extensions` pass-through, 9480280), A (`high`, 871x), B (`high`, 872x), F (`high`, 873x). F builds against S6's contract and reports with the checks that wait for S6; the lead resumes F after S6's merge |
| 2026-11-01 | **Stopped by the owner during wave 1** (no agent running; branch at d09da36 + this row; nothing of wave 1 merged). F's question answered before the stop: `OutputChapter.source_index` added to S6's contract (d09da36). Where each agent stopped; the worktrees are kept under `.claude/worktrees/` (do not remove them: three hold uncommitted work), no server process or `/tmp/reframe-dev-*` folder left: **S6** (`agent-a7cf1dd08f96c6537`, branch `worktree-agent-a7cf1dd08f96c6537`): no commit; uncommitted core work only — new `reframe/chapters.py` (386 lines) and `reframe/models/output.py` (131), changes in `command/{__init__,builder,jobtype,metadata}.py`, `models/{__init__,media}.py` (+231 / −33); it was about to check the chapter writer against mkvmerge / mkvextract / ffprobe; no route, no test, no frontend part yet. **A** (`agent-a8baa5dcebcca1392`): no commit; uncommitted `LanguagePicker`, `LanguageListEditor`, `LanguagesSection`, new `language/catalog.ts` (226), messages (+940 / −11); it was in its browser check. **B** (`agent-abae74f79ef70efb2`): no commit; uncommitted `TrackTable`, `streams.ts`, new `ScanControl.vue` (84), `stores/scans.ts`, `sources.reload`, messages (+473 / −25); it was reading its light-theme screenshots. **F** (`agent-aebdc9afcfb296360`): one commit f001e78 "F-11: Chapters and Tags tabs against S6's contract" (18 files, +2020; lint and typecheck clean on it); it was fixing lint / type errors of later, uncommitted-or-reverted work (its tree is clean at f001e78); the real-server checks wait for S6. **Resume**: either resume each agent (it keeps its context) or start fresh agents on these worktrees with their briefs; none of the four has run the full rule-5 commands, the mutation checks or written its 0065 section yet |
| 2026-11-01 | **Resumed at the owner's request** ("Continue work"): S6, A, B and F resumed with their context, in their kept worktrees, from where they stopped; each told to commit in steps |
| 2026-11-01 | **Finding (F)**: the agents share one scratchpad folder; A's check script read `scratchpad/server.log` (F's, port 8730) and drove F's server with F's token (a `PUT /api/settings`). Every agent now uses `scratchpad/task-<x>/` (new line in "Changes for M6", for every later brief); A repeats its checks after the resume on its own server, F restarts its own |
| 2026-11-01 | **F reported** (branch `worktree-agent-aebdc9afcfb296360` at 0ec0018: f001e78 the tabs, 3bb93e5 merge of the milestone branch, 0ec0018 a stronger test + its status row + 0065 Task F): the Chapters and Tags tabs against S6's contract (S6's routes only in `components/{chapters,tags}/requests.ts`, with a cast until the schema has them; renames at `source_index`); lint, format, typecheck, `npm test` 1061 passed, `build:web`, `gen-api --check` green; 53 tests, 60 mutations all killed (M43 survived first; the test was rewritten). Checked in headless Chromium against a real server with S6's routes answered by `page.route` (the look and the behaviour, not a Done-when check). **Waits for S6**: the real chapters / names / import / export / generate / tags, an encode with renamed chapters and a Title re-probed, removing the casts, the F-11 box. Not merged yet; F's worktree is kept for its resume after S6. Notes from F: the *modified* marker shows after a chapter rename (the template's chapter name policy; to look at with E / the reviews); **the Playwright browser cache was gone** (the disk was cleaned: 47 GB free now): the lead reinstalled `chromium-1248`, `chromium_headless_shell-1248`, `firefox-1555` with `npx playwright install chromium firefox` (990 MB), the builds M4 used |
| 2026-11-01 | **Merged B** (a7fd2b8; 2a8cdb1…6ba6057): F-10's Measure and the scans (`stores/scans.ts` with one run per target, the run kept until the reload so the cell never flashes, failures toasted, a cancel quiet; `sources.reload` with 404 → probe again, 409 → `source: null`; `ScanControl.vue`; loudness kept in the store; subtitle counts per track or all). Real server: DTS-HD MA measured 2140 kb/s (`source: measured`), loudness −22.5 LUFS / −20.0 dBTP / 2.2 LU, PGS 12 / 2 forced; a measured 49 kb/s 2.0 track turns into a heuristic *Commentary*; cancel shown for real on a one-hour file; the `multitrack` commentary badge solid with "Set by a disposition flag in the file" (demo 2, no change needed). Checks on the merge: lint, format, typecheck, 1037 unit tests, `build:web`. The agent: 40 mutations killed. The lead's mutation (a one-track subtitle count sending `stream_indexes: null`) failed `scans.test.ts`. B's worktree removed |
| 2026-11-01 | **Merged A** (b01b516; 896a2f2…4a1f127): `LanguagePicker` (search in the browser over `GET /api/languages` — 429 entries, 11 region / script variants —, the core's ranking ported, favourites first, `Hungarian · hun (ISO 639-2) · hu (BCP 47)`, typed variants of listed languages such as `de-AT`, keyboard alone; extra optional props `noneLabel`, `container`, `exclude`), `LanguageListEditor`, Settings → Languages. Found: the server checks only a tag's shape (`xx-YY-ZZ`, `zz` are saved), so the picker is stricter than the server; it does not offer ISO 639-3-only languages (`yue`, `cmn`), variant / extension subtags or unknown regions (recorded in A's 0065 section; open question for the owner). Merge conflict: the F-10 row (B's and A's sentences combined against the merge base). The lead also updated the Features rows "Rich audio …" and "Languages". Checks on the merge: lint, format, typecheck, 1079 unit tests, `build:web`. The agent: 40 mutations killed. The lead's mutation (favourites listed again under all languages) failed `catalog.test.ts`. A's worktree removed. **E started** (wave 2, `xhigh`, 878x): it needs only A |
| 2026-11-01 | **Merged S6** (63cd783…4f28a4e): `jobs/type` (with a web-mode "may only read" blocker), `jobs/chapters` (`OutputChapter.source_index`; `name` `""` for an untitled copied chapter), `chapters/import`, `jobs/chapters/export` (`<stem>.chapters.csv/.txt/.xml`; CSV as RFC 4180, from HandBrake's source, HandBrake itself not run), `jobs/tags` (`TagValues`), `subtitles/inspect`, `fs/list?extensions=`, the file browser's pass-through; all models in `reframe.models`, `API_VERSION` stays 1; problem codes `chapters.unreadable`, `chapters.invalid`, `chapters.none`, `subtitles.unsupported`, `fs.bad_extension`. Real tools (recorded in `testdata/README.md`): a CP1250 / Latin-1 SRT fails to decode without `-sub_charenc` (exit 69); **UTF-16 with a BOM is broken in FFmpeg** (U+FFFD without `-sub_charenc`, every event lost with `-sub_charenc UTF-16LE`) → `subtitle.utf16` warning; `.ssa` reports `ass`; mkvmerge reads the exported OGM and XML. S6's own note: `chapters.mkv` has 4 chapters (also Credits 4–5 s). The lead switched `api/types.ts` to `Schemas[…]` (`ChapterFormat = ChapterExport['format']`). Checks on the merge: lint, format, typecheck, 1080 unit tests, `build:web`, `gen-api --check`, ruff, format, mypy ×2, S6's tests + models `661 passed`. The agent: 66 mutations killed. The lead's mutation (`source_index` = the output position) failed `test_output_chapters.py`. S6's worktree removed. **Next**: F resumed for its real-server checks; **C** (`high`, 875x) and **D** (`xhigh`, 877x) started |
| 2026-11-01 | **Merged F** (f001e78…f8c25e2): F-11 done. Chapters tab (the output's chapters from `jobs/chapters`, inline renames at `source_index`, *Create chapter markers*, resets, import of CSV / OGM / XML through the file browser with `fs/list?extensions=` and a warning when a start differs, export in three formats, *Generate chapters* — interval 0.01–600 min —, *No name* for an untitled copied chapter); Tags tab (`TemplateField` per tag, written and source values from `jobs/tags`, errors with fixes at the field). Real server: 4 rows on `chapters.mkv`, `Show – S01E02` for an episode's Title, an encode re-probed with `Renamed Three` and `title=chapters – test`. Checks on the merge: lint, format, typecheck, 1133 unit tests, `build:web`. The agent: 60 mutations killed (after the S6 merge too). The lead's mutation (export always asks for CSV) failed 2 tests. F's worktree removed. **Open for the reviews (R1)**: (1) after one rename, the other untitled source chapters are written as `Chapter N` (core `_renamed`), while with `names: null` they get no name; (2) a chapter rename sets the preset's *modified* marker (template diff). F's note that the Playwright cache is missing was from before the lead's reinstall (the cache is there) |
| 2026-11-01 | **Merged C** (bf6c9ed; c737758…e3e0bc0): `TrackMetadataEditor` (language through the picker with *As the source (…)*, name as text with a menu of the codec rules' name templates rendered for the track — no free template field, no route renders one —, six flags, the fixes of `metadata.several_defaults` and `tool.mkvpropedit_missing`; folded in audio and subtitle rows, opened by an issue or a reveal; off for a burned-in track), bulk edit (a selection column, one `editor.patch`), external subtitles (`pickFiles` with five filters, `subtitles/inspect`, the language and flags from the file name, offset, the encoding list with *As detected* / *Not detected*, `charset` `null` for UTF-8 and UTF-16). **Demo 3 passes**: hun / pt-BR / names / commentary, SDH, original → queue → done; ffprobe, `mkvmerge -J` and the server show every value (`LanguageIETF` `pt-BR` through mkvpropedit); a CP1250 external SRT with −200 ms decoded correctly. Merge conflict: the F-10 / F-11 rows (per row against the merge base). Checks on the merge: lint, format, typecheck, 1171 unit tests, `build:web`. The agent: 52 mutations killed. The lead's mutation (bulk *Off* written as on) failed `BulkEdit.test.ts`. C's worktree removed |
| 2026-11-01 | **Merged E** (2a623ee; 3d58340…355dd45): the defaults dialog (selection with `LanguageListEditor`, the codec-rule table with drag and keyboard moves, the catch-all locked, expandable optional settings and extra outputs, passthru and fallback, the subtitle options; the live preview at once and 250 ms after the last edit through the editor's latest-request helper, issues keyed per rule so they stay at their rule while it moves; *Apply* via `jobs/explain` as one undo step; *Save to preset…* for a user preset, *Save as new preset…* for a built-in; a built-in preset read-only; the group target a toast). **Demo 5 passes** (rules built through the UI): DTS-HD MA → rule 1 → AC-3 5.1 320 "Lossless source → encode at the max" (with **Measure**); AC-3 5.1 224 → rule 2 → passthru "AC-3, 5.1, 224 ≤ 384: passthru"; AC-3 2.0 → rule 3 → AAC stereo 160. Merge conflicts: the F-10 row (C's and E's sentences combined; F-10 now **Done**) and the F-10 boxes of 06 (C's box and E's box, both ticked). The lead updated the Features row "Audio and subtitle output tracks …". Checks on the merge: lint, format, typecheck, 1229 unit tests, `build:web`. The agent: 62 mutations killed. The lead's mutation (a built-in preset's defaults editable) failed 3 tests. E's worktree removed. **G started** (wave 3, `high`, 879x); D still running |
| 2026-11-01 | **Merged D** (3bb6f6f; 5529050…86705d4): the Summary *Job type* card (the type and the server's reason from `jobs/type`, at once and 250 ms after an edit, newest answer only; *Edit in place* with every blocker shown also before it is on; the plain warning that the source itself changes; the `inplace.*` issues with fixes; *Remux only* through the new `editor.applyRemuxDraft` as one undo step, in-place asked only for a Matroska source), `useInPlaceReload` (an open source read again when an in-place job that ran ends: done, failed, cancelled or interrupted), the queue's "Source, edited in place". **Demo 4 passes**: flags only → `metadata_edit`, `done` in 0.076 s (0.074 s, 0.083 s in other runs), the source read again with the new flags; flags + language stay `metadata_edit`; a removed track gives `remux` with the reason. Every in-place write was under a `/tmp/reframe-dev-*` home. Merge conflict: two Features rows (each changed on one side; taken per row against the merge base). The lead mounted `useInPlaceReload()` in `App.vue`; removing that line failed no test, so the lead added an `App.test.ts` case (fails without the line, passes with it; b50da91). Checks on the merge: lint, format, typecheck, 1267 unit tests, `build:web`. The agent: 44 mutations killed. The lead's mutation (the blockers shown only with the switch on) failed `JobTypeCard.test.ts`. D's worktree removed. **Every build task but G is merged** |
| 2026-11-01 | **Merged G** (834d190; 3d0fc9b, ecf2fb8): F-17 flow 1 (`e2e/flow1-audio-language-commentary.spec.ts`: `Ctrl+O` → `multitrack.mkv` → *H.264 MKV 1080p* → audio track 2 Hungarian through the picker + *Commentary* → add, start, `done` → the output probed through the API, all three audio tracks compared exactly; `probeFile` in `e2e/support/app.ts`; the e2e servers start with `--output-fixtures chapters` so the output root is readable). G: two runs of 18 passed; 4 mutations (3 in the app, 1 in the core) each failed at the probe; nothing left after a pass, a forced failure and SIGINT; the 06 F-17 boxes stay open (flows 2 and 4). G's note: PrimeVue's `ToggleSwitch` keeps its own state when its `modelValue` does not follow (a refused flag edit would show a wrong switch). The lead's mutation (the builder ignores the chosen language) failed flow 1 (the job itself `failed`: the core's re-probe check saw the wrong language). G's worktree removed |
| 2026-11-01 | **Wave 3 done; checks alone on the merged branch** (no agent running): lint, format, typecheck, `npm test` 1267 passed, `build:web`, `gen-api.sh --check`; `npm run test:server` 12 files, 49 tests; `npm run e2e` 18 passed (26.9 s); the full Python suite in four chunks, `nice -n 19`, `-m "not needs_gpu"`: remote + jobs + CLI 468 passed (5:47), queue / preview / probe / analysis / metadata / platform 1290 passed, 1 deselected, the rest of the core 4954 passed, 1 skipped, 25 deselected, server + testing 810 passed, 1 skipped; no process or `/tmp/reframe-dev-*` left. **Wave 4 started**: R1 (`xhigh`, 871x) and R2 (`xhigh`, 872x), fresh, told not to read "Findings for the fix round" and "Progress" |
| 2026-11-01 | **R2's review** (at 44de4b0; headless Chromium and Firefox, real servers): no blocker, 2 majors, 8 minors, 8 nits; every main flow worked with the keyboard alone (demos 1, 2, 4, 5, bulk edit, external subtitle, chapter import / export). **R2-M1**: a tag template error shows as "Error" on the Tags tab only; `jobs/validate` does not report tag templates, so the status bar, the Issues card and *Add to queue* ignore it and the job writes a broken Title. **R2-M2**: clearing the *Generate chapters* interval leaves the field empty while the job keeps `generate_every: 5`. Minors: R2-1 focus drops to `body` after Measure / Count / loudness start, cancel and end, bulk *Apply* / *Clear*, *Remux only*, the in-place and tag fixes, chapter *Export* / *Import* and Enter in a name, and nothing announces a scan's end; R2-2 "1 chapters" (no plural); R2-3 a single track's selection box does nothing; R2-4 a built-in preset's read-only defaults at 3.86:1 and cut values; R2-5 the faded busy states (defaults preview, chapters, tags) below AA; R2-6 the Subtitles toolbar wraps at 1280 and overflows at 390; R2-7 *Remux only* in a read-only media root makes an error job at once; R2-8 no error state in the picker when `GET /api/languages` fails. Nits: literal punctuation and fragments (`'und'`, `“…”`, `' · '`, "every" + field + "min"), no digit grouping, a lower-case server detail as a bullet, the raw Pydantic pattern of a refused language, repeated accessible names in a rule's extras, the picker's count with *None*, the in-place tooltip not keyboard-reachable and "Video copied" for a metadata edit, a 230 px editing pane at 1280×800, the bulk dialog's flag rows at 390. **The lead reproduced both majors**: R2-M1 against a real server (8762): `jobs/validate` → only `dimensions.crop_not_detected`, `jobs/tags` → two `naming.unknown_variable` errors at `tags.title`; R2-M2 with R2's script on the lead's server (8763): `after clearing — field: "" | job: {"generate_every":5}`, "1 generated chapter". R2's worktree removed (nothing committed); R1 still running |
| 2026-11-01 | **R1's review** (at 44de4b0): no blocker, 2 majors, 5 minors, and from its Python sub-review 5 minors and nits; no path makes an in-place edit write a file the user did not choose. **R1-M1** (= L1, corrected): an external SRT whose encoding was not detected is queued and the job ends **`done`** with U+FFFD text (not "fails in FFmpeg" as C's 0065 note says); a UTF-16 file loses its first letter. **R1-M2**: `presets/defaults/preview` uses only the two defaults, *Apply* uses the job's whole template, so with a preset's explicit `audio_rules` the preview shows a result *Apply* does not write. Minors: R1-m1 shortcuts under a modal after a click on its text; R1-m2 *Remux only* always asks for *Edit in place* on an MKV; R1-m3 a bulk edit after a reorder of two outputs of one stream changes the other track; R1-m4 *Save* of defaults reverts another window's preset changes; R1-m5 = R2-M1; s1–s5 in S6's code. **The lead reproduced both majors** with R1's scripts on his own server (8764): R1-M2 `PREVIEW [(1, ac3, 320), (2, aac, 160), (3, aac, 160)]` vs `APPLY [(2, aac, 96), (3, aac, 96)]`; R1-M1 `inspect charset null`, `validate [crop_not_detected]`, `end done`, the extracted subtitle "Invalid UTF-8 in decoded subtitles text". R1's worktree removed (nothing committed). **The fix round planned** ("Fix round" above; placeholders in 0065) |
| 2026-11-01 | **Fix round started**: FA (`xhigh`, 873x, core and server), FB (`xhigh`, 874x, defaults dialog and shortcuts), FC (`high`, 875x, tracks / scans / language), FD (`xhigh`, 877x, chapters / tags / summary / queue). FB, FC and FD build against FA's contracts; the lead resumes them after FA's merge for their real-server checks |
| 2026-11-01 | **Merged FD** (merge after 8657ce0; c8ff151…8657ce0): R2-M2 (the cleared interval shows the job's value again on blur / Enter; only the switch turns generation off; one message "every {field} min"), the same field-keeps-a-refused-value defect found and fixed in the queue's **When done** select (a refused choice stayed shown), tag issues shown once at the validation's severity (a `jobs/tags` issue only when validation has none with that code at that path), *Remux only* follows the *Edit in place* switch (replaces D's choice 6: in place only when the switch is on and the source is Matroska; **M6 demo 4's steps change**: switch on, *Remux only*, then the flags — run by FD: `metadata_edit`, `done` in 0.099 s), plurals, busy states at AA (7.58 / 6.91), focus after Import / Export / Enter / *Remux only* / the fixes, the nits. Checks on the merge: lint, format, typecheck, 1285 unit tests, `build:web`. The agent: 27 mutations killed. The lead's mutation (*Remux only* in place for any MKV) failed 2 tests. FD's worktree kept for its resume after FA (the tag-issue real-server check). **L3 decided** (FD's analysis, the lead's choice): a preset holds only `chapter_name_policy`; `names: null` → `source`, every name `Chapter N` → `generated`, other names → the preset's own policy (two wrong cases under a `generated` preset reproduced by FD); core part sent to FA, `editor/template.ts` (+ test) given to FD on its resume, with `components/base/Section.vue` (its header actions do not wrap at 390 px, so the Chapters tab is wider than the window). `Ctrl+N` leaving the focus on `body` sent to FB (`useShortcuts`) |
| 2026-11-01 | **Merged FC** (after 63933a4; 7 commits `F-10:`): R1-m3 (`followSelection` in `tracks/ops.ts`: a reorder moves each selected place with its track, metadata or one track's settings keep the places, anything else clears; R1's `s4.mjs` now puts Commentary on the selected track), R2-3 (no selection column for one track), R2-6 (the toolbar wraps inside the panel at 1280 and 390), R2-1 (Start ⇄ Cancel focus hand-over, a `leave` emit → the row's toggle, a polite live region per source table announcing each scan's result or its cancel; after bulk *Apply* / *Clear* the focus on *Select all*), R2-8 (the picker's error box with *Read the list again* through `system.loadDefinitions()`), the encoding field showing validation's issues (it used to replace them, so FA's error would never have shown) with the inspect warning suppressed while validation reports one, the nits (summary from messages with `Intl.ListFormat`, the picker's count without *None*, kb/s grouping). C's 0065 note corrected in FC's section. Checks on the merge: lint, format, typecheck, 1312 unit tests, `build:web`. The agent: 34 mutations killed. The lead's mutation (the selection kept by place) failed 3 tests. FC's worktree kept for its resume after FA (the charset check) — with `components/settings/LanguagesSection.vue` given to it for the raw Pydantic pattern of a refused language (FC's report) |
| 2026-11-01 | **FB reported** (branch `worktree-agent-a6e4242f2ff348f40` at 615ce90; **merge only after FA**: the preview sends `template`, which today's server refuses with a 422): R1-M2 frontend part (the preview sends the template *Apply* sends; a notice when the template's own track rules decide the tracks; temporary `PreviewRequest` type in `stores/defaults.ts`), R1-m1 (no shortcut while any `[aria-modal="true"]` is in the page, except one in its leave transition — found in the browser), `Ctrl+1…8` focuses the tab button with `focusVisible`, R1-m4 (*Save* reads the preset again and replaces only that kind's defaults; a 404 is a toast; a change between the read and the write is still lost: presets have no version check), R2-4 (a built-in's defaults as text, ≥ 14.6:1), R2-5 (a moving bar and "Updating…" instead of opacity), R2-1 (after *Measure* the focus goes to the row header through `ScanControl`'s `leave`, with an announcement), the nits. 1324 unit tests; 39 mutations killed. **Waits for FA**: the generated type, `defaults.server.test.ts` (3 fail today by design), `t2_rules.py` / `s2.mjs` showing PREVIEW = APPLY. FB noted one `TracksTab.test.ts` timeout (5 s) under load, passed on re-run: watch for flakiness |
| 2026-11-01 | **Merged FA** (635551e; 9d91074…eaf88c0) **and FB** (9c2bcbd). FA: `subtitle.charset_unknown` / `subtitle.utf16` / `subtitle.charset_mismatch` errors at `subtitles[i].source.charset` through `FileSystemView.text_charset` (BOM or valid UTF-8 in the first 16 MiB, cached by path, device, inode, size and times; no ffprobe in validation; no "convert" fix); R1's `t3_charset.py` now `validate error subtitle.charset_unknown`, the job `failed` at the add instead of `done` with U+FFFD, and with `charset: CP1250` a real encode reads "Árvíztűrő tükörfúrógép"; tag template errors in `jobs/validate` with `jobs/tags`'s codes, `metadata.nul_character`, `metadata.tag_too_long` (3000 characters, from Linux `MAX_ARG_STRLEN` 131 072 and the measured command lengths; Windows' 32 767 from the documentation, not checked: M10); `DefaultsPreviewRequest.template` (R1's `t2_rules.py`: PREVIEW = APPLY `[(2, aac, 96), (3, aac, 96)]`); s1–s5 (`chapters.too_many` with a fix, at most 1000 generated chapters, `jobs/chapters` and export off the loop: `1e-300` answers in 0.003 s); **L2 decided**: an untitled source chapter stays untitled after a rename (generated chapters keep `Chapter N`); **L3** core rule in `batch/derive.py`; recorded tool behaviour in `testdata/README.md`. 44 mutations killed. Checks on both merges: lint, format, typecheck, 1324 unit tests, `build:web`, `gen-api --check`, ruff, format, mypy ×2, `defaults.server.test.ts` 5 passed (FB's three by-design failures now pass). The lead's mutation on FA (no error for an undetected encoding) failed 3 tests. FA's worktree removed. **FB, FC, FD resumed** for their post-FA parts (FB: the generated type and the browser re-runs; FC: the charset error in the browser, plus `LanguagesSection.vue`'s raw Pydantic message; FD: the tag issues, `chapters.too_many`, L3 in `editor/template.ts`, `base/Section.vue` wrapping at 390, `npm run e2e`) |
