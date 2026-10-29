# M4 task breakdown

Working notes of the lead for the branch `m4-frontend-mvp`: milestone M4, the first usable GUI
(web). The plan ([plan/06-web-app.md](plan/06-web-app.md) Part B, the parts of
[plan/03-features.md](plan/03-features.md) named below, and [plan/08-roadmap.md](plan/08-roadmap.md)
§M4) is the spec; this file says who builds which part, in which order, and what each part
must offer to the others. Decisions: [0063](decisions/0063-m4-frontend-mvp.md) (the lead's
choices and one section per task) and [0064](decisions/0064-queue-processing-event.md) (task S).
Status: [status.md](status.md). The branch is not merged into `main` until the owner says so.
If the lead's context is summarised, this file and `status.md` are the source of truth.

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| S | — | The queue-processing event of [0042](decisions/0042-one-scheduler-process-and-cli-clients.md) open question 5 (core, server, CLI) | 0042, 0047, 0061 |
| A | F-1 | Design system: tokens, light / dark / system theme, density, the base components, the dev-only sandbox, the literal-text check | 06 §F-1; 0043 item 8 |
| B | F-2 | API layer and events: typed client, auth, problem+json → toast, WebSocket with reconnect and resync, the server-mirror stores | 06 §F-2, §S-3; 0047 |
| C | F-3 | App shell: navigation rail, workspace layout, status bar, shortcuts, theme switch, toasts, login, first-run screen | 06 §F-3; 03 §App layout |
| D | F-4 | Editor state: `EditorTarget`, undo / redo as JSON patches, `useValidation`, modified vs preset | 06 §F-4; 03 §Validation |
| E | F-5 | Sources panel and the web file-browser dialog (`Platform.pickFiles`) | 06 §F-5 |
| F | F-18 | Naming editor | 06 §F-18; 03 §Output naming |
| G | F-6 | Summary tab | 03 §Summary |
| H | F-9 | Video tab without the advanced panel: `EncoderPicker`, missing-encoder banner, `QualitySlider`, `CommandPreview` | 06 §F-9; 03 §Video |
| I | F-10 | Audio and Subtitles tabs: source `TrackTable` and the basic output track editors | 06 §F-10; 03 §Audio, §Subtitles |
| J | F-12 | Presets UI | 06 §F-12; 03 §Presets |
| K | F-14 | Queue, activity and job log, the when-done selector, Stop | 06 §F-14; 03 §Queue |
| L | F-15 | Settings (basic) | 06 §F-15; 03 §Settings |
| M | F-17 | Playwright set-up and flow 3 | 06 §F-17 |

S-4 is already done ([0058](decisions/0058-s4-static-frontend.md)).

**Out of scope** (do not start): F-7, F-8, F-11, F-13, F-16, the F-9 advanced panel, the F-10
parts that M6 owns (the defaults dialog, `LanguagePicker`, `TrackMetadataEditor`, bulk edit,
external subtitles, the **Measure** button), F-17 flows 1, 2 and 4, M5 and every `D-x`.

Defaults the lead took where the plan leaves a choice (each in 0063):

- Tabs of later milestones (Dimensions, Filters, Chapters, Tags) are not shown; their
  `Ctrl+N` does nothing (`components/editor/tabs/registry.ts`).
- Settings in M4: Tools, Encoders, Output, Queue, Appearance. Languages (needs the
  `LanguagePicker`, M6) and Preview (needs F-7, M8) come later.
- The Summary tab's job type ("Remux-only jobs") comes with M6; its source thumbnail is in
  F-6 (one frame from `POST /api/preview/frames`).
- Track rows and queue rows are reordered with PrimeVue's `DataTable` row reorder plus
  move-up / move-down buttons for the keyboard: no new dependency.
- A web token reaches the app through the address fragment `#token=…` (never sent to the
  server, removed from the address at once) or the login screen, and is kept in
  `sessionStorage` for the tab.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0063, dependencies, the skeleton, `scripts/dev-server.py` | `main` (1054a64) |
| 1 | A (`high`), B (`xhigh`), S (`xhigh`) | the skeleton |
| 2 | C (`high`), D (`xhigh`) | wave 1 merged |
| 3a | E, F, G, H (`high`) | wave 2 merged |
| 3b | I, J, K, L (`high`) | wave 3a merged |
| 4 | M (`high`) | wave 3b merged |
| 5 | two fresh `xhigh` reviews (R1: API layer, events, editor state, undo, validation, queue / Stop; R2: the screens, i18n, keyboard, focus, light and dark contrast, empty and error states), the fixes (`xhigh` for blockers and majors, `high` for minors), the M4 demo headless and once headed by the lead, the docs | wave 4 merged |

At most four worktrees at a time. The lead merges each task with `--no-ff`, runs the frontend
commands (and the Python checks for S), and removes the worktree and its branch.

Every agent: `model: "opus"`, `isolation: "worktree"`, the effort above.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Paths are
relative to `frontend/src/` unless they start with `frontend/`, `docs/`, `scripts/` or
`packages/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **S** | `packages/**` (core queue and events, the server's queue router and events, `reframe.remote`, the CLI, their tests), `frontend/src/api/schema.d.ts` (regenerated only), `docs/decisions/0064-queue-processing-event.md`, the plan sections that list the events or 0042's open question | every other file of `frontend/` |
| **A** | `styles/**`, `components/base/**`, `composables/useTheme.ts`, `views/SandboxView.vue`, `i18n/checks/**` (new), `i18n/messages/en/{base,sandbox}.json` | `setup.ts`, `main.ts`, `i18n/index.ts`, every store |
| **B** | `api/**` except `api/schema.d.ts` and `api/types.ts`; `stores/{system,tasks,queue,settings}.ts`; `i18n/messages/en/api.json` | `stores/{toasts,ui,activity}.ts` (use them), `platform/**`, every view and component |
| **C** | `App.vue`, `App.test.ts`, `components/shell/**`, `views/WorkspaceView.vue`, `composables/{useShortcuts,useQueueActions}.ts`, `i18n/messages/en/shell.json` | the stores, `router/**`, the tab registry, `setup.ts` |
| **D** | `stores/{editor,validation}.ts`, `composables/{useValidation,useUndo}.ts`, `editor/**` (new: helpers), `i18n/messages/en/editor.json` | the tab components, `stores/ui.ts` |
| **E** | `stores/sources.ts`, `components/sources/**`, `platform/web.ts`, `platform/index.test.ts`, `i18n/messages/en/sources.json` | `platform/types.ts`, `platform/desktop.ts`, `platform/index.ts` |
| **F** | `components/naming/**`, `i18n/messages/en/naming.json` | `components/editor/**` |
| **G** | `components/editor/tabs/SummaryTab.vue`, `components/summary/**` (new), `i18n/messages/en/summary.json` | `components/naming/**` (use it) |
| **H** | `components/editor/tabs/VideoTab.vue`, `components/video/**`, `i18n/messages/en/video.json` | the other tabs |
| **I** | `components/editor/tabs/{AudioTab,SubtitlesTab}.vue`, `components/media/**`, `components/tracks/**` (new), `i18n/messages/en/tracks.json` | the other tabs |
| **J** | `stores/presets.ts`, `components/presets/**`, `views/PresetsView.vue`, `i18n/messages/en/presets.json` | `stores/editor.ts` (use it) |
| **K** | `components/queue/**`, `views/{QueueView,ActivityView}.vue`, `stores/activity.ts`, `i18n/messages/en/queue.json` | `stores/queue.ts` (B's; use it) |
| **L** | `components/settings/**`, `views/SettingsView.vue`, `i18n/messages/en/settings.json` | `stores/settings.ts` (B's; use it) |
| **M** | `frontend/e2e/**`, `frontend/playwright.config.ts` except the `headless` lines and the reporter | `frontend/package.json`, every file of `src/` |

**Lead-owned**: `frontend/package.json`, `frontend/package-lock.json`, `api/schema.d.ts`
(except S's regeneration), `api/types.ts`, `router/**`, `components/editor/tabs/registry.ts`,
`i18n/index.ts`, `i18n/messages/en/app.json`, `setup.ts`, `main.ts`, `notBuilt.ts`,
`stores/{toasts,ui}.ts`, `composables/useReveal.ts`, `platform/types.ts`, `platform/index.ts`,
`frontend/vite.config.ts`, the tsconfigs, `scripts/dev-server.py`. An agent that needs another
dependency, a route, a registry entry or a change of these files asks the lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own step's row (S: the C-17 row's "Not built:
  0042's open question 5" sentence).
- `docs/decisions/0063-m4-frontend-mvp.md`: each task writes only its own section ("Task X").
- `docs/plan/06-web-app.md`: a task ticks its own step's boxes, and edits its step's text only
  together with a decision (its 0063 section, or 0064).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. The signatures are in the skeleton's files (read them; they are the source); this is
their summary. A task may add members, keyword-like optional parameters with defaults, files
and components in its own folders, but not change these. `notBuilt(…)` marks a stub: replace
it, and remove the `oxlint-disable` line at the head of a stub store you build.

### Types (`api/types.ts`, lead)

Aliases of the generated schema: `JobSettings`, `JobTemplate`, `JobDraft`, `ValidationIssue`,
`Fix`, `JsonPatchOp` (one RFC 6902 operation), `FieldChange`, `MediaSource`, `SourceEntry`,
`Preset`, `QueueJob`, `JobState`, `TaskInfo`, `SystemInfo`, `AppSettings`, `NamingOptions`,
`JobNaming`, `Problem`, …; `ServerMessage`, `ClientMessage`; `ReframeEvent` (the union of core
events), `EventOf<'job.state'>`. `QueueProcessingEvent` is written by hand until S's schema
lands; then the lead makes it `Schemas['QueueProcessingEvent']`:

```ts
interface QueueProcessingEvent {
  type: 'queue.processing'
  processing: boolean          // the runner takes waiting jobs
  only: string[] | null        // only these jobs (a start with job_ids); null: every waiting job
  reason: 'start' | 'stop' | 'idle'   // idle: the jobs a start named have all ended
}
```

### The queue-processing event (S)

- Core: `reframe.models.events.QueueProcessingEvent` with the fields above, in the `Event`
  union; `QueueService.processing -> bool` and `QueueService.only -> list[str] | None`
  (running state, not saved). The service publishes the event on every change of
  `processing` or `only`: `start()` (reason `start`), `stop()` (`stop`), the runner going idle
  after the jobs a `start(job_ids=…)` named have ended (`idle`), and at `close()` nothing.
- Server: `QueueSnapshot` (`GET /api/queue`) gains `processing: bool` and
  `only: list[str] | None`. The event goes out over `WS /api/events` like any core event.
  Whether `API_VERSION` changes is S's decision in 0064 (an older client that reads the
  snapshot or the event strictly must not be used by a newer owner, 0042 item 3).
- CLI (client mode, `reframe encode` / `reframe batch`): when a `queue.processing` event with
  `processing: false` and reason `stop` arrives while the command still has waiting jobs, it
  prints one line that the queue was stopped by another front end (0042 open question 5's
  default) and goes on waiting; Ctrl+C still cancels its jobs; a later Start (any front end)
  runs them. The command itself never calls `stop`.
- `scripts/gen-api.sh` regenerates `frontend/src/api/schema.d.ts`.

### Stores (Pinia setup stores; `stores/*.ts`)

```ts
// system (B)
phase: Ref<'booting' | 'login' | 'ready' | 'offline'>
auth: Ref<AuthStatus | null>
connection: Ref<'connecting' | 'open' | 'reconnecting' | 'unauthorized' | 'closed'>
instance: Ref<string | null>
info: Ref<SystemInfo | null>
capabilities: Ref<CapabilitySnapshot | null>
definitions: Ref<Definitions | null>
languages: Ref<Language[]>
warnings: Ref<EventOf<'app.warning'>[]>
ffmpegProblem: ComputedRef<string | null>        // null when ffmpeg and ffprobe can be used
encoderStatus(id: string): EncoderStatus | undefined
login(password: string): Promise<boolean>        // false: wrong password (not toasted)
loginWithToken(token: string): Promise<boolean>
logout(): Promise<void>
resync(): Promise<void>                          // GET /api/system, /api/system/encoders
rescanEncoders(): Promise<void>; rescanTools(): Promise<void>; fetchTools(): Promise<void>
onCapabilitiesChanged(e); onToolsChanged(e); onAppWarning(e)

// tasks (B)
tasks: Ref<Record<string, TaskInfo>>
wait(taskId: string): Promise<TaskInfo>          // resolves when ended (failed too); survives a reconnect
cancel(taskId: string): Promise<void>
resync(): Promise<void>
onTaskProgress(e); onTaskDone(e)

// queue (B)
jobs: Ref<QueueJob[]>                            // queue order
processing: Ref<boolean>; only: Ref<string[] | null>
whenDone: Ref<WhenDone>
power: Ref<EventOf<'power.countdown'> | null>    // a running when-done countdown
logTicks: Ref<Record<string, number>>            // +1 per job.log event of a job (follow mode reads on)
loaded: Ref<boolean>
counts: ComputedRef<Record<JobState, number>>
overallProgress: ComputedRef<number | null>      // 0..1 over running and paused jobs; null: none
byId(id: string): QueueJob | undefined
add(settings: JobSettings[], options?: { start?: boolean }): Promise<QueueJob[]>   // at the end, never attached
start(jobIds?: string[]); stop(); pauseAll(); resumeAll(); cancelAll()
pause(id); resume(id); cancel(id); retry(id); duplicate(id); remove(id)
reorder(jobIds: string[]); setWhenDone(value: WhenDone); cancelPower()
readLog(jobId: string, from?: number): Promise<JobLogChunk>
resync(): Promise<void>                          // queue snapshot, when-done, GET /api/power
onJobState(e); onJobProgress(e); onJobLog(e); onQueueChanged(e); onQueueProcessing(e); onPowerCountdown(e)

// settings (B)
settings: Ref<AppSettings | null>; loaded: Ref<boolean>
load(): Promise<void>
update(ops: JsonPatchOp[]): Promise<SettingsChange>   // a refused patch rejects with ApiError, not toasted
set(pointer: string, value: unknown): Promise<SettingsChange>

// editor (D)
type EditorTarget =
  | { kind: 'job'; sourceId: string; job: JobSettings }
  | { kind: 'group'; groupId: string; template: JobTemplate; overrides: Record<string, JsonPatchOp[]> }  // M7
interface PatchOptions { coalesce?: string }     // patches in a row with one key: one undo step
pointerOf(path: string): string                  // 'audio[2].encoder' → '/audio/2/encoder'
pathOf(pointer: string): string
target: Ref<EditorTarget | null>
draft: Ref<JobDraft | null>                      // the last jobs/draft answer (decisions, naming, notes)
presetId: Ref<string | null>; loading: Ref<boolean>
presetChanges: Ref<FieldChange[]>                // presets/diff of currentTemplate against presetId
job: ComputedRef<JobSettings | null>
currentTemplate: ComputedRef<JobTemplate | null> // preset-level settings (presets/diff, Save as preset)
modified, canUndo, canRedo: ComputedRef<boolean>
open(sourceId: string, preset?: string | null): Promise<void>   // jobs/draft; clears the history
applyPreset(preset: string): Promise<void>       // re-draft; one undo step
loadJob(settings: JobSettings): Promise<void>    // edit-back from the queue (opens the source if needed)
get(pointer: string): unknown
patch(ops: JsonPatchOp[], options?: PatchOptions): void
set(pointer: string, value: unknown, options?: PatchOptions): void
applyFix(fix: Fix): Promise<void>                // target 'job': one undo step; 'settings': settings store
undo(); redo(); close()

// validation (D)
issues: Ref<ValidationIssue[]>; pending: Ref<boolean>
counts: ComputedRef<Record<Severity, number>>; hasErrors: ComputedRef<boolean>
issuesFor(path: string, options?: { nested?: boolean }): ValidationIssue[]   // most severe first

// sources (E)
interface ProbeRun { taskId: string; paths: string[]; progress: number | null; message: string | null }
entries: Ref<SourceEntry[]>; activeId: Ref<string | null>; probing: Ref<ProbeRun[]>
grouping: Ref<BatchGrouping | null>              // POST /api/batch/group over entries
active: ComputedRef<SourceEntry | null>
open(paths: string[], options?: { recursive?: boolean }): Promise<SourceEntry[]>
pick(): Promise<void>                            // platform.pickFiles → open (Ctrl+O)
ensure(path: string): Promise<SourceEntry>
select(id: string): Promise<void>                // active, and editor.open(id)
remove(id: string); refresh(); onServerRestart() // a new server instance: probe the open paths again

// presets (J)
presets: Ref<Preset[]>; defaultId: Ref<string | null>; loaded: Ref<boolean>
categories: ComputedRef<{ name: string; presets: Preset[] }[]>
byId(id: string): Preset | undefined
load(); create(request: PresetCreateRequest): Promise<Preset>; save(preset: Preset): Promise<Preset>
remove(id); setDefault(id)
importFile(file: File, onConflict: 'rename' | 'replace' | 'skip'): Promise<PresetImportReport>
exportPresets(ids: string[]): Promise<Blob>

// activity (K; the dispatcher calls record for every event)
entries: Ref<{ at: Date; event: ReframeEvent | QueueProcessingEvent }[]>
record(event): void; clear(): void

// toasts (lead, complete): items, push({severity, summary, detail?, life?}): number, dismiss(id)
// ui (lead, complete): activeTab: Ref<EditorTabId>, revealed, reveal(path), revealDone(request);
//   tabForPath(path): EditorTabId
```

**Events → stores** (B's dispatcher, one place): `capabilities.changed`, `tools.changed`,
`app.warning` → system; `task.progress`, `task.done` → tasks; `job.state`, `job.progress`,
`job.log`, `queue.changed`, `queue.processing`, `power.countdown` → queue; `notification` → a
toast (and `platform.notify` when the page is hidden); `resync`, a gap in `seq` and a
reconnect → `system.resync`, `tasks.resync`, `queue.resync`; a `hello` with another
`instance` → also `sources.onServerRestart`; every event → `activity.record`.

### API layer (B)

- `api/client.ts`: `api` and `apiQuiet` are openapi-fetch `Client<paths>`. `api` pushes a
  toast for a problem+json answer; `apiQuiet` does not (forms, validation). `ApiError`
  (`status`, `problem`), `unwrap(result)` returns `data` or throws `ApiError`. Credentials:
  the token from `platform.backend()` (desktop), or the tab's token (`#token=…` or the login
  screen, `sessionStorage`), or the session cookie (password mode).
- `api/boot.ts`: `boot()` once from `main.ts`: base URL and credentials, `GET /api/auth/status`
  (`system.phase` becomes `login` when needed), then the snapshots, then the event connection.
- The 202 + task flow: `tasks.wait(task_id)`.

### Components used across tasks

| Component | Owner | Props and slots |
|-----------|-------|-----------------|
| `base/Field.vue` | A | `label`, `path?` (validation path: its issues show here and `ui.reveal` finds it), `help?`, `issues?` (instead of the store's), `overridden?`, `stacked?`; default slot `{ id, invalid, describedBy }` |
| `base/Section.vue` | A | `title`, `collapsible?`, `v-model:collapsed`; slots `default`, `actions` |
| `base/Card.vue` | A | `title?`; slots `default`, `header`, `actions` |
| `base/RoleBadge.vue` | A | `role: TrackRoleInfo` (solid for `flag`, outlined otherwise, tooltip = evidence) |
| `base/CodecLabel.vue` | A | `stream: CodecInfo` (commercial name; raw codec, long name, profile in the tooltip) |
| `base/LanguageChip.vue` | A | `tag: string \| null \| undefined` |
| `base/StatusDot.vue` | A | `tone: 'ok' \| 'busy' \| 'warn' \| 'error' \| 'off'`, `label` |
| `base/KeyValue.vue` | A | `label`, `value?`; default slot replaces the value |
| `base/IssueList.vue` | A | `issues`, `compact?`; fix buttons (`editor.applyFix`), link to the field (`ui.reveal`) |
| `naming/NamingOptionsEditor.vue` | F | `v-model: NamingOptions`, `sourceIds?`, `container?`, `disabled?` (Settings → Output, preset editor) |
| `naming/JobNamingEditor.vue` | F | `disabled?`; edits the editor's job (`/output/naming`, `/output/path`) (Summary's Output card) |
| `sources/SourcesPanel.vue` | E | none (workspace column) |
| `sources/FileBrowserDialog.vue` | E | none; mounted once by `App.vue` (C keeps it); opened by the web platform's pickers |
| `presets/PresetPicker.vue` | J | none; the source header's preset choice and modified marker (C places it) |
| `editor/tabs/{Summary,Video,Audio,Subtitles}Tab.vue` | G, H, I, I | none; read and write the editor store |

Composables: `useTheme()` and `initTheme()` (A; `main.ts` calls `initTheme`),
`useValidation()` (D; the workspace view calls it once), `useUndo()` (D),
`useShortcuts()` (C; `App.vue` calls it once), `useQueueActions()` (C: `canAdd`,
`addCurrent`, `addAll`, `start`), `useReveal(path, element)` (lead, complete: the target of
`ui.reveal`; `Field` and track rows use it).

### i18n

`i18n/messages/en/<area>.json` holds the keys of `<area>.` (`video.json` → `t('video.…')`),
collected by `i18n/index.ts` with `import.meta.glob`. Each task writes only its own area file.
The tab and view names are in `app.json` (`app.tabs.<id>`, `app.views.<name>`). Every string
the user sees goes through vue-i18n; A's check fails on literal text in a `<template>` and on
a key that no message file has.

## Done when (word for word in each agent's brief)

Where the plan gives one, it is quoted first; the rest is the lead's, from 03 and the demo.
Every "in a browser" check runs headless against a real `reframe-server` started with
`scripts/dev-server.py`, in light and dark, with screenshots read by the agent.

- **S**: A test with the real queue shows `queue.processing` events for `start`, `stop` and
  `idle` with the right `only`; `GET /api/queue` carries `processing` and `only`; a real
  `reframe encode` client (real processes) whose job is waiting when another front end calls
  Stop prints that the queue was stopped by another front end and keeps waiting, then runs the
  job after a Start; Ctrl+C still cancels it.
- **A (F-1)**: "a component sandbox page (dev only) shows every base component in both
  themes." Also: the literal-text check fails on a `<template>` with literal text and on a
  missing message key (shown by its tests) and passes on the code base; theme (light, dark,
  system) and density (comfortable, compact) switch at once and are kept after a reload.
- **B (F-2)**: Every store that mirrors the server (system, tasks, queue, settings) is filled
  from its snapshot at start and kept current by events. Tests against a real `reframe-server`
  show that after a dropped connection the client reconnects with backoff and reads the
  snapshots again, that a gap in event numbers and a `resync` event cause the same resync, that
  a 4401 close is not retried with the same credentials, that a hello with another `instance`
  re-probes the sources, and that a problem+json answer becomes a toast (and through
  `apiQuiet` does not). Token and password login work in a browser.
- **C (F-3)**: In a browser: the navigation rail reaches every view; the workspace shows
  sources | tabs | preview (the preview column can be collapsed) and the status bar (output
  path, the validation summary that opens the issue list, *Add to queue*, *Add all*, *Start*);
  `Ctrl+O`, `Ctrl+Enter`, `Ctrl+1…8` and `Ctrl+Z` / `Ctrl+Shift+Z` work (undo and redo are left
  to a text field while it has the focus); the theme switch changes the theme and density at
  once; a problem shows as a toast; the login screen appears in token and password mode; with
  FFmpeg missing (an override to a missing file) the first-run screen shows the reason and where
  the binary came from, with *Use bundled FFmpeg*, *Choose path* and *Check again*, and Presets
  and Settings stay usable. (What needs a later task's screen — a job from an opened file for
  *Add to queue*, an edit to undo — C proves with unit tests against the store contracts; the
  lead checks it in a browser after wave 3a.)
- **D (F-4)**: Unit tests show that undo and redo of every kind of patch (a coalesced slider
  drag is one step) restore the exact job; that a fix's patch is one undo step; that
  `useValidation` sends at most one `jobs/validate` per 250 ms of edits and that an answer for
  an older job never overwrites a newer one; that issues are found by path; that
  `presetChanges` follows `presets/diff` after a change and after `applyPreset`. In a browser,
  `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo an encoder change, and the field outline and the
  issue follow. (The browser part needs C's shortcuts and H's Video tab: D proves the same
  against a real server in a `*.server.test.ts`; the lead checks it in a browser after wave
  3a.)
- **E (F-5)**: In a browser: the file-browser dialog shows the roots, breadcrumbs, folders and
  media files (the media filter can be turned off), selects several files, and works with the
  keyboard; opening files shows the probe progress, then the sources with their warnings; a
  season folder shows one collapsible group with its near-match markers; choosing a source
  opens it in the editor; nothing outside the roots can be reached. The desktop path goes
  through `Platform` (`pickFiles`, `pickFolder`, `onFilesDropped`) with no web-only code.
- **F (F-18)**: In a browser: the template field completes a variable after `{`; the variable
  chips show the values of the current source and insert themselves on click; the parsed-name
  panel shows the name source and why, the coloured spans over the original name and the
  editable fields, and a per-file override changes the preview; the live preview
  (`naming/preview`, debounced) follows each change. Both editors work in their places (the
  Summary card through G, Settings → Output through L, the preset editor through J).
- **G (F-6)**: 03 §Summary: "every card updates live while you edit other tabs, and every chip
  and issue links to the field it describes." Also: every card of the table in 03 §Summary
  is shown for the `multitrack` fixture (the Estimate card gives a size only in bitrate mode
  and "depends on content" in quality mode), and the Issues card groups the issues by severity
  with their fix buttons.
- **H (F-9)**: In a browser: the encoder picker groups the encoders by family, each with its
  status dot (`checking…` while detection runs) and, when unavailable, its reason; an
  unavailable encoder cannot be chosen; a job whose encoder is unavailable shows the
  non-modal banner on the Video tab with the fix buttons of its issue (*Use … (closest
  match)*, *Choose encoder*, *Check again*), and Summary shows the same issue; the quality
  slider uses the encoder's scale and shades the recommended band for the output height;
  the rate-control switch, speed preset, tune, profile, level, fast decode and bit depth come
  from the definitions; the command preview drawer shows the `jobs/plan` command, updates
  after each change, highlights it and copies it.
- **I (F-10, basic)**: In a browser with the `multitrack` fixture: the audio and subtitle
  source tables show the columns of 03 §Audio and §Subtitles (the commercial codec name, the
  bitrate and where it comes from, role badges with their evidence, flags) and expand to the
  details (delay, duration, frame count, all tags and dispositions); output tracks can be
  added (one, or *Add all*), removed and reordered (drag and keyboard), each with its action
  and encoder settings (audio: encoder, mixdown, sample rate, bitrate or quality, gain, DRC,
  loudness; subtitles: copy, burn in, convert); each change is one undo step, and validation
  issues show at the track's fields.
- **J (F-12)**: In a browser: the preset drawer shows the presets as a tree by category with
  the built-ins locked; a user preset can be created from the current settings, renamed,
  duplicated, updated, deleted and made the default (star); import (rename, replace or skip on
  a clash) and export of JSON work; choosing a preset drafts the job again; the *modified*
  marker appears after an edit, and its popover lists the changes of `presets/diff`.
- **K (F-14)**: In a browser against a real server with the real FFmpeg: the queue table shows
  the jobs with live progress, fps, speed, ETA and current size; per-job pause, resume,
  cancel, retry, duplicate, remove and edit (back into the editor), and global start, stop,
  pause, resume and cancel work; rows reorder by drag and by keyboard; the when-done selector
  sets the setting, and a when-done countdown shows and can be cancelled (dry run); the job log
  viewer shows the whole log, follows a running job and copies all; the activity view lists the
  session's events. After Stop the queue takes no new job and the running one goes on.
- **L (F-15, basic)**: In a browser: Settings shows Tools (each tool's version and where it
  comes from, a path override with *Test* and *Use bundled*, environment overrides read-only),
  Encoders (status, reason, last check, *Re-scan*, hardware test encodes on / off, the VAAPI
  device), Output (the default folder, the naming editor, default container, collision and
  partial-file behaviour), Queue (parallel jobs, when done, sleep inhibit, notifications) and
  Appearance (theme, density, UI language); a change is saved at once, and a refused value
  shows at its field; read-only settings are shown read-only.
- **M (F-17)**: 06 §F-17 flow 3: "A preset with an unavailable encoder → banner → use the
  fallback → queue." `npm run e2e` (headless Chromium and Firefox) starts its own isolated
  server through `scripts/dev-server.py`, passes flow 3 twice in a row, and leaves no process
  and no temporary folder behind.

## The M4 demo (the acceptance test; the lead runs it at the end)

In the browser: open a file from the server file browser → choose a preset → change the
encoder and quality → add and remove audio tracks → add to queue → watch progress → open the
log. Validation issues appear inline and on Summary. Plus F-17 flow 3: a preset with an
unavailable encoder → banner → use the fallback → queue. First headless (Playwright, with the
screenshots read), then once headed by the lead on `HDMI-A-1` through the guard.

## Commands

From `frontend/`: `npm ci`, `npm run lint`, `npm run fmt:check`, `npm run typecheck`,
`npm test`, `npm run build:web`, `npm run e2e` (headless only). Vitest has two projects:
`unit` (`npm test`: jsdom, `src/**/*.test.ts`) and `server` (`npm run test:server`: Node,
`src/**/*.server.test.ts`, one file at a time, for tests against a real `reframe-server`; it
needs `uv sync`, so it is kept out of `npm test`, which runs where only Node is installed). A
task with `*.server.test.ts` files runs `npm run test:server` too. From the root:
`scripts/gen-api.sh --check`; for a `packages/` change `uv run ruff check`,
`uv run ruff format --check`, `uv run mypy`, `uv run mypy --platform win32` and the tests of
what changed (`uv run pytest …`, in the foreground).

A real server for a browser check (`--help` lists the options):

```sh
npm run build:web                      # in frontend/: the server serves frontend/dist
uv run python scripts/dev-server.py --port 87N0 --fixtures multitrack,season
# → {"event": "ready", "url": …, "token": …, "open": "http://127.0.0.1:87N0/#token=…", "home": …}
```

It makes a new temporary home with its own config, data, cache, media root and output root,
copies the fixtures from `testdata/media/` into the media root, sets
`REFRAME_POWER_DRY_RUN=1`, runs `reframe-server --mode web --auth token`, and on SIGINT,
SIGTERM or SIGHUP stops the server and removes the home. `--tools-dir DIR` picks an FFmpeg
build, `--fake-ffmpeg SCENARIO.json` the fake one of `reframe_testing`, `--settings FILE`
merges settings, `--auth password` / `none` (`--password PW` sets the login password first), `--cors-origin URL` for the Vite dev server
(`REFRAME_DEV_PORT=87N1 REFRAME_DEV_BACKEND=http://127.0.0.1:87N0 npm run dev:web`; it opens
no browser).

**Ports** (rule 7): agent N uses 87N0 to 87N9. S 873x, A 871x, B 872x, C 874x, D 875x,
E 877x, F 878x, G 879x, H 870x; batch 3b reuses the free ranges: I 871x, J 872x, K 873x,
L 874x; M 875x; reviewers R1 877x, R2 878x. The lead uses 876x (8765 is the dev proxy's
default).

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
  it builds and the ones it uses, its "Done when" word for word, its section of 0063 (S: 0064),
  rules 5, 6 and 7 and the test rules word for word, its port range.
- Setup: the worktree starts at `main`: first `git merge --ff-only m4-frontend-mvp`. Then
  `uv sync`, `npm ci` in `frontend/`, and
  `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (`--tools-dir` of `scripts/dev-server.py`); `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not
  installed.
- Commits per step, step ID first (`F-5: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Update only its own
  `docs/status.md` row.
- The report: the real output of every command of rule 5 (the last lines), what the agent saw
  in its screenshots (light and dark), the test rules' checks, every deviation from the plan
  and from this file, every file touched outside its list, and what later tasks need.

## Progress

| Date | What |
|------|------|
| 2026-10-29 | **Wave 0.** Preflight on `main` 1054a64: clean tree; frontend lint, format, typecheck, 6 tests, `build:web`, `gen-api.sh --check` green; `HDMI-A-1` at 0,0 and `DP-1` at 1920,0; 21 GB free. Branch `m4-frontend-mvp`; dependencies (0063); the skeleton; `scripts/dev-server.py` (started, health and settings read with its token, stopped by SIGINT and by SIGTERM, home removed both times) |
