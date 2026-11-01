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

## Fix round (wave 5; binding for the fix agents)

The two reviews (R1: 2 majors, 3 minors; R2: 1 blocker, 6 majors, 11 minors, 7 nits) and the lead's
integration findings below. The lead reproduced every blocker and major (Progress, 2026-10-29).
Five fix tasks with disjoint files; a fix of a blocker or major comes with a test that fails
before it (a unit test, a `*.server.test.ts`, or a Playwright spec in `frontend/e2e/`); each task
writes its own dated section "Fix round — X" of 0063.

| Task | Effort | Findings | Owns |
|------|--------|----------|------|
| **FA** theme and base | `xhigh` | **R2-1** (blocker: `.rf-sr-only` without `top`/`left` makes the document 3,300+ px tall; the window scrolls away), **R2-5** and **R2-6** (text and control contrast below AA: PrimeVue component tokens — buttons, toasts, messages, togglebutton / selectbutton, toggleswitch, slider, outlined borders — in both themes; extend `contrast.test.ts`), **R2-2** / L4 (compact `IssueList` squeezes the message to 0 px), R2-9 / L9 (icons in icon-only buttons shrink: one rule in `main.css`), R2-15 (a field's outline on a SelectButton misses the checked option), R2-16 (PrimeVue's own strings bypass vue-i18n: its `locale` from the messages), R2-17 (weak focus highlight of options), R2-25 (a field's gutter bar paints over the command drawer), L15 (a disabled button in dark looks enabled) | `frontend/src/styles/**`, `frontend/src/components/base/**`, `frontend/src/setup.ts` (PrimeVue `locale` only), `frontend/src/i18n/messages/en/base.json`, `frontend/e2e/layout.spec.ts` (new: the document is no taller than the window on the main screens) |
| **FB** the job that is queued | `xhigh` | **R1-1** (`Ctrl+Enter` adds without the value typed in the focused field), **R1-2** (a naming change without typing reaches the job only after the preview; *Add* stays enabled and queues the old naming), **L1** (a container change keeps the old extension), R1-3 (a click on *Add* right after typing does nothing), R1-4 (leaving Summary before the preview answers never updates the path), R1-5 (removing the editor's source while another draft loads leaves that source with no job), R1 suspected 5 (*Add* enabled after a failed validation), L13 (the *Browse…* icon renders as a square), the naming parts of R2-8 (comboboxes named by their value), R2-20's probe toast "(exit code 1).:" | `frontend/src/composables/{useQueueActions,useShortcuts,useValidation}.ts`, `frontend/src/stores/{editor,validation,sources}.ts`, `frontend/src/editor/**`, `frontend/src/components/naming/**`, `frontend/src/components/summary/OutputCard.vue`, `frontend/src/i18n/messages/en/{editor,naming}.json` |
| **FC** shell, focus, queue and presets screens | `xhigh` | **R2-3** (focus falls to `body` after *Add to queue*, *Add all*, *Start*, a row's pause / resume / retry, the empty state's *Open files…*, *Duplicate*, *Edit*), **R2-4** (popovers do not take the focus: Appearance, the Modified changes, the issue list), **R2-7** (the when-done countdown shows only on the Queue view: mount it in the shell), R2-11 (toasts cover the header and are see-through: bottom right, opaque), R2-12 (the placeholder preview column narrows the tabs: collapsed by default), R2-10 (raw JSON in the Modified popover), R2-13 / L17 (raw task kinds in Activity), R2-14 (a failed duplicate repeats its message; say why it failed), R2-20's queue wording, R2-23 (the Preset column of a changed job), L3 / L10 / R2-22 (the first-run screen offers *Use bundled FFmpeg* / *Choose path* where they cannot help: environment overrides, web mode), R1 suspected 4 (*Save as new preset* reads the job after the await), the queue parts of R2-8 | `frontend/src/App.vue`, `frontend/src/components/shell/**`, `frontend/src/views/{WorkspaceView,QueueView,PresetsView,ActivityView}.vue`, `frontend/src/components/queue/**`, `frontend/src/stores/activity.ts`, `frontend/src/components/presets/**`, `frontend/src/i18n/messages/en/{shell,queue,presets}.json` |
| **FD** the tabs, sources and settings screens | `high` | R2-8 (comboboxes named by their value: tracks, settings, the encoder picker if needed), R2-18 (the quality slider steps 0.1 per key: larger steps, PageUp / PageDown), R2-19 (Summary chips repeat role and flag), R2-21 (the file browser's sizes are 1000-based, Summary's 1024-based), R2-24 (Summary jumps from h1 to h3; a source tree item's name includes "Remove …"; an empty `<p>` inside the file list's `listbox`), L2 (the Output card shows the name twice), L8 (the sample-rate select is too narrow), L16 (the encoder picker cuts the id at 1280 px) | `frontend/src/components/{tracks,media,settings,video,sources}/**`, `frontend/src/components/summary/**` except `OutputCard.vue`, `frontend/src/components/editor/tabs/*.vue`, `frontend/src/views/SettingsView.vue`, `frontend/src/i18n/messages/en/{tracks,settings,video,summary,sources}.json` |
| **FE** server texts | `high` | L6 / R2-20 (a refused `fs/list` says "may **write** to" for a read), L12 (the `settings.tools_forbidden` detail names the FFmpeg variables for every tool; MediaInfo's reason says to set its path in Settings, which web mode refuses) | `packages/reframe-server/**` (the routers and their tests), `packages/reframe/**` only where the text is made |

Not fixed in M4 (recorded): L5 (a `fs/list` option for other files: M6's external subtitles),
L7 (the desktop stub: M5), L14 (an output that another waiting job claims is known only at the
add: the queue decides it, validation does not see the queue), R2-14's automatic free name for a
duplicate (a queue change), the suspected R1 items 1, 2, 3, 6, 7 (each checked by FB where it
touches its files).

## Integration findings (the lead's checks between merges; for the fix round of wave 5)

| # | Severity | Finding | Seen |
|---|----------|---------|------|
| L1 | major | A container change on the Summary Output card (G) leaves `output.path` with the old extension (MP4 chosen, `…/multitrack.mkv` kept); validation gives only the warning `output.extension_mismatch`, so *Add to queue* stays enabled. F's `JobNamingEditor` does not rewrite the path after a change from elsewhere (by design, so that redo is not lost) and offers *Use this path*. Expected: the container change and the new extension are one undo step | 2026-10-29, headless Chromium, real server, after merging F |
| L2 | minor | The Output card shows its own Folder / File name / Name source rows and then F's editor below them, which shows the name again | same run |
| L4 | minor | A's `IssueList` in compact mode squeezes the message to a few characters when a fix label is long ("Use hevc_amf (closest match; quality CQ 27 → CQ 25, approximate)"); the status bar's popover uses compact mode (H's note) | H's report |
| L5 | open (default taken) | `GET /api/fs/list` lists only folders and media files (`MEDIA_EXTENSIONS`) and has no option for others, so the dialog's media filter can only narrow to a caller's `filters` and "turned off" shows nothing more in M4. Default: no server change in M4; M6's external-subtitle import needs a route option (`?all=true` or `?extensions=`) and adds it | E's report |
| L6 | minor (server) | A refused `fs/list` of a folder outside the roots says "not inside a folder that this server may **write** to" also for a read: the route tries the read check, then the write check, and reports the second refusal | E's report |
| L7 | note for M5 | The desktop platform stub's `onFilesDropped` and `setTaskbarProgress` throw, so a desktop build would fail when the workspace mounts; it cannot boot anyway (`backend()` rejects) until D-x replaces the stub | E's report |
| L8 | minor | Audio row: the sample-rate select is too narrow ("Same as sou…") at a 1440 px window | the lead's flow check |
| L9 | minor | Track rows: the move and remove icons are small and faint (the trash icon in dark especially; I's own note). Cause (K, measured in Chromium): in a small icon-only PrimeVue button an 18 px lucide icon (a flex item) shrinks to 10 px; `.p-button svg { flex: none }` fixes it (K did it in `QueueTable.vue`; `TrackRowFrame` needs the same) | I's report, the lead's flow check, K's report |
| L10 | minor | In web mode the server refuses tool paths (`403 settings.tools_forbidden`, L checked), so Settings shows them read-only; the first-run screen's *Choose path* then leads to a field that cannot be changed (with L3: decide what the first-run screen offers in web mode) | L's report |
| L11 | **fixed** (lead) | No shared Vitest set-up stubbed `matchMedia`; `App.test.ts` passed only because the Settings sections wait for settings it never loads (PrimeVue `Select` calls `matchMedia` when it mounts), and J avoided `Select` for it. Fixed: `src/testing/setup.ts` (the unit project's `setupFiles`) defines it when jsdom lacks it; 809 tests pass | L's and J's reports |
| L12 | minor (server) | The 403 detail of `settings.tools_forbidden` says "Set REFRAME_FFMPEG / REFRAME_FFPROBE" for every tool, mediainfo included | L's report |
| L13 | minor | F's *Browse…* button in the naming options editor renders its icon as a small square in Chromium | L's report |
| L14 | minor | A job whose output another waiting job already claims is added `failed` (`queue.output_claimed`, decided at the add) while the status bar said "No issues": the user learns it only from the toast after *Add to queue* | M's report |
| L15 | minor | In dark, the disabled *Add to queue* looks almost like the enabled one | M's report |
| L16 | minor | At 1280 px the encoder picker cuts the encoder id ("NVIDIA NVENC H.265 h…") | M's report |
| L17 | minor | Activity lines for tasks show the raw task kind ("Task probe_sources done"): no i18n names for task kinds yet | K's report |
| L3 | minor | The first-run screen keeps *Use bundled FFmpeg* and *Choose path* enabled for an environment override, which they cannot fix (C's own note) | C's report |

## Progress

| Date | What |
|------|------|
| 2026-10-29 | **Wave 0.** Preflight on `main` 1054a64: clean tree; frontend lint, format, typecheck, 6 tests, `build:web`, `gen-api.sh --check` green; `HDMI-A-1` at 0,0 and `DP-1` at 1920,0; 21 GB free. Branch `m4-frontend-mvp`; dependencies (0063); the skeleton; `scripts/dev-server.py` (started, health and settings read with its token, stopped by SIGINT and by SIGTERM, home removed both times) |
| 2026-10-29 | **Wave 1 started**: A, B, S. **Merged A** (db71339; 6090fd3): F-1 (tokens, light / dark / system, density, the base components, the dev-only sandbox, the literal-text and message-key checks as Vitest tests). Checks on the merge: lint, format, typecheck, 60 tests, `build:web` (no sandbox chunk). The lead's 3 mutations caught (literal text and a `title` in another task's template; an unknown key in a `.ts` file; `Field` dropping the store's warnings). Screenshots read (light and dark). The lead's follow-ups from A's notes: the sandbox messages out of the production bundle, `useReveal` without smooth scrolling under reduced motion, `v-tooltip` typed (`src/directives.d.ts`) |
| 2026-10-29 | **Merged S** (78c1099; 8737129): `QueueProcessingEvent` (core, published on every change of `processing` / `only`, idle at once after a cancel, removal or failed late claim), `GET /api/queue` `{jobs, processing, only}`, `RemoteQueue` keeps them, the CLI's line after a whole-queue read (the add/stop race), `API_VERSION` stays 1 (main's client checked against the new server), decision 0064. The agent's 21 mutations caught. Checks on the merge: ruff, format, mypy, `gen-api.sh --check`, the frontend commands. The lead: `api/types.ts` uses the generated event type; `dev-server.py` `SIGHUP` only off Windows (`mypy --platform win32` failed on it; now green); `env.d.ts` formatted. The lead's 3 mutations: `stop` not published and the snapshot hiding a narrowed run were caught; **`idle` reported like `stop` by the CLI survived** (a second, false line after another CLI's narrowed run ends): sent back to S |
| 2026-10-29 | **Merged S's follow-up** (5f01ddb; 6b55463): `test_the_idle_end_of_another_commands_start_is_not_reported_as_a_stop` (three jobs, so the command's follow loop has handled the idle event while one still waits); the lead's mutation now fails it (`1 failed`) and passes when restored. S's worktree removed |
| 2026-10-29 | **Merged B** (f8e3e15; b48bfed): F-2 (`api/client.ts` with `api` / `apiQuiet`, `credentials.ts` (the `#token=` fragment), `events.ts` (auth first, heartbeat silence, backoff 0.5 s × 2ⁿ to 30 s with jitter, no retry after 4401, gaps), `mirror.ts` (snapshot reads with the events that arrive during a read applied again on top, one read at a time), `dispatch.ts` (guarded handlers, the activity log, notifications), `boot.ts` (the connection first, the snapshots at its hello), the stores system, tasks, queue, settings). The agent: 126 unit and 10 real-server tests, 125 + 13 mutations. Merge conflict: the F-1 / F-2 status rows (resolved per row). **Found on the merge**: `typecheck` failed, because B's `api/testing/devServer.d.mts` was never committed (the root `.gitignore` ignores `*.mts`, meant for MPEG-TS video); the lead un-ignored `*.d.mts` and added it. Checks: lint, format, typecheck, 180 unit tests, `test:server` 10 passed (no server or home left), `build:web`, `gen-api.sh --check`. The lead's 3 mutations caught (no replay of events logged during a read: 5 tests fail; a reconnect after 4401: 2 fail; `job.state` applied from another state: 1 fails). Note for K and R1: the real server's `queue.processing` reaches the store only through unit-tested code so far (the field names match S's model exactly) |
| 2026-10-29 | **Wave 1 done.** Full Python suite alone, in the foreground, `nice -n 19`, `-m "not needs_gpu"`: remote + jobs + CLI `467 passed` (5:28); queue, preview, probe, analysis, metadata, platform `1283 passed, 1 deselected`; the rest of the core `4883 passed, 1 skipped, 25 deselected`; server + testing `757 passed, 1 skipped`. Wave 2 started: C (`high`), D (`xhigh`) |
| 2026-10-29 | **Merged C** (3a3ae80; 0e870c2, dfc6f25): F-3 (screens per `system.phase`, the rail with the connection state and the theme switch, toasts shown from the store once PrimeVue's `Toast` is mounted, the first-run screen, the workspace with header, three columns, empty state and status bar, `useQueueActions` with `canAddAll` / `canStart` added, `useShortcuts`). Add all adds the open source as edited (not drafted again): recorded in C's 0063 section. Checks on the merge: lint, format, typecheck, 249 unit tests, `build:web`. The agent's 114 mutations caught; the lead's 3 caught (undo inside a text field; *Add to queue* with an error; the taskbar progress wrong). Screenshots read (the issue popover with the real `hevc_nvenc` reason, the first-run screen in dark). **Open minor for the fix round**: with an environment override, *Use bundled FFmpeg* and *Choose path* stay enabled although they cannot fix it |
| 2026-10-29 | **Merged D** (4456c93; c38fa3b): F-4 (`editor/` helpers: pointers, all-or-nothing patches on a frozen job, a 200-step history with coalescing runs, `currentTemplate` that every one of the 26 built-ins drafts back to unmodified; the editor store with `presetId` following `job.preset_id` so undo brings the preset back; `useValidation` with a 250 ms debounce, the latest request only (abort), the draft's own issues until the first answer, a 422 shown at its fields). Real server: with hardware tests **off** every hardware encoder is only `unknown` (`encoder.untested`); with them on, `hevc_nvenc` is `unavailable` ("NVIDIA driver not found") and the fix is *Use hevc_amf (closest match; quality CQ 22 → CQ 20, approximate)*: the closest available encoder here is AMF, not libx265. Merge conflict: the F-3 / F-4 rows. Checks on the merge: lint, format, typecheck, 352 unit tests, `test:server` 15 passed (nothing left behind), `build:web` (one warning: `sources.ts` imported both ways, D's lazy import that keeps `import/no-cycle` quiet). The agent's 98 mutations caught; the lead's 3 caught (coalescing across keys; an older validation answer shown; `applyPreset` not recorded). **`dev-server.py`**: D found that a second signal during the stop left the home behind; the lead's first fix (handlers swapped in `finally`) had a window where the second signal killed the script and orphaned the server (seen, killed, home removed); the fix: the handler stops only on the first signal and ignores the rest (two rounds of four signals: no process, no home) |
| 2026-10-29 | **Paused by the owner after wave 2** (branch at 390068d; no agent running, no worktree). Done: wave 0 (skeleton), wave 1 (A, B, S), wave 2 (C, D), all merged and checked; full Python suite green after wave 1 (7,390 passed). **Next, when the owner resumes:** wave 3a — E (F-5, ports 877x), F (F-18, 878x), G (F-6, 879x), H (F-9, 870x), all `high`, briefs as in "Every agent prompt includes" plus these notes from waves 1–2: (1) the editor's job is frozen: read with `editor.get` / `editor.job`, write with `editor.set` / `editor.patch` (one undo step each), coalescing keys named after the validation path plus `editor.endCoalescing()` at the end of a gesture; `presetId` is read only; (2) `validation.issues` is a `shallowRef` (assign arrays); a row uses `issuesFor('audio[2]', { nested: true })`; (3) `dev-server.py` turns hardware test encodes off, so hardware encoders are only `unknown` (`encoder.untested`); for a real *unavailable* encoder (`hevc_nvenc`: "NVIDIA driver not found", fix *Use hevc_amf (closest match …)*) pass `--settings` with `{"encoders": {"hardware_tests": true}}` (H, M); (4) server tests need `REFRAME_TEST_TOOLS_DIR` set to the pinned FFmpeg bin in a worktree; (5) E: `select(id)` calls `editor.open(id, editor.presetId)`, no watcher on `activeId` (`loadJob` sets it), the file dialog is `aria-modal`, the panel keeps the class `sources-panel`; (6) F has no place in the app until G, J and L place its editors: let F add one section to the dev-only `SandboxView.vue` for its browser check (A is done with that file); (7) G: `editor.draft` is `null` for a queued job; track chips call `ui.reveal('audio[i]')`, whose targets I builds in 3b; (8) under the app's CSP Playwright's `waitForFunction` needs a function, not a string. Then wave 3b (I, J, K, L), wave 4 (M), wave 5 (reviews, fixes, the demo; the lead's integrated browser checks of C's and D's deferred Done-when parts after 3a). Open minor for the fix round: the first-run screen keeps *Use bundled FFmpeg* and *Choose path* enabled for an environment override |
| 2026-10-29 | **Resumed at the owner's request; wave 3a started**: E (F-5, 877x), F (F-18, 878x; may add one section to the dev-only `SandboxView.vue` for its browser check), G (F-6, 879x), H (F-9, 870x), all `high`, with the notes of the previous row in their briefs |
| 2026-10-29 | **Merged G** (425fe90; b2d3cf6): F-6 (seven cards; the thumbnail is a synchronous `POST /api/preview/frames` with `count: 1`, a relative URL signed for 300 s that loads under the CSP without the token, kept per source for 50 min; the estimate in bitrate mode only, passthru at the source's bitrate, unknown bitrates left out and counted; links to unbuilt tabs as plain text, the Picture card the target of `dimensions.*` / `filters.*`). The agent's mutations caught (two equivalent survivors replaced by real defects). Checks on the merge: lint, format, typecheck, 396 unit tests, `build:web`. The lead's 3 mutations caught (an estimate in quality mode; passthru not counted; a chip revealing the next track). **Open, to check after F's merge**: a container change on the Output card does not change the output path's extension |
| 2026-10-29 | **I started early** (F-10, 871x, `high`) in the slot G freed: it needs only what is merged (the editor, the base components, G's chip paths). Wave split changed accordingly: 3b is now J, K, L as slots free up, still at most four worktrees |
| 2026-10-29 | **Merged F** (5b87be9; e8a3642, 20773be, efde0f8): F-18 (`TemplateField` with completion after `{` and format specs, `VariableChips`, `ParsedNamePanel` with coloured spans and per-file overrides, `NamingOptionsEditor` emitting a new object per change, `JobNamingEditor` writing `/output/naming` and `/output/path` in one undo step on blur or the preview's answer; the folder of one job taken from its path). Real server: Hacksaw Ridge → folder (`Hacksaw.Ridge.mkv`), Sopranos → file (`The.Sopranos.S03E02.Proshai.Livushka.mkv`). **Found on the merge**: 9 of G's Summary tests failed, because G's sample draft lacks `naming.relative_path` (the real server always sends it) and F's editor now renders where the stub rendered nothing; the lead mocked `JobNamingEditor` in `SummaryTab.test.ts` (G's tests are about G's cards) — all 9 pass. The lead's headless check of the merged Summary tab against a real server: findings L1, L2 above |
| 2026-10-29 | F: checks on the merge (after the lead's test fix): lint, format, typecheck, 461 unit tests, `build:web`. The lead's 3 mutations on F caught (no completion after `{`: 6 tests; the path written as a separate undo step: 1; the name not put into the job after its preview: 4). F's worktree removed. **J started** (F-12, 872x, `high`) |
| 2026-10-29 | **Merged H** (merge of 074932f): F-9 without the advanced panel (the picker by family with status text, refusing unavailable encoders itself; the banner with the issue's fixes, *Choose encoder*, *Check again*; the rate-control switch, `QualitySlider` with the band of the output's short side; frame rate, speed preset, tune, profile, level, fast decode, bit depth; passthrough; `CommandPreview` as an in-tab drawer asking `jobs/plan` only while open). Real server: the client's encoder switch equals the `encoder.unavailable` fix op for op (custom parameters aside: H clears them on a switch, with a toast). **D's deferred browser part done by H**: `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo an encoder change, the banner and the field outline follow, and the fix is one undo step. Checks on the merge: lint, format, typecheck, 545 unit tests, `build:web`. The lead's 3 mutations caught (an unavailable encoder chosen; the banner for another encoder issue; the copied text changed). H's worktree removed; **L started** (F-15, 874x, `high`); K waits for E (`sources.ensure` for the edit-back) |
| 2026-10-29 | **Merged E** (1124067; ca10002, 499b329, 94f858f, e707fb9): F-5 (the sources store with `open(paths, { recursive, select })`, `ensure` without changing the selection, `select` carrying the editor's preset, `onServerRestart` re-probing and keeping the active source; the panel as a tree with groups, near-match markers and differences, warnings, keyboard use, a remove bar; the web file-browser dialog in files / folder / save modes, `aria-modal`, roots, breadcrumbs, a path field, multi-select; the web platform's pickers). E also gave C's `WorkspaceView.test.ts` sources double the contract's `probing` and `grouping` (kept). Merge conflict: the F-5 / F-6 rows. Checks on the merge: lint, format, typecheck, 626 unit tests, `build:web`. The lead's 3 mutations: the preset not carried and the active source lost after a restart were caught; **a double-click on a file in folder mode survived** (it would confirm the current folder): sent back to E. Findings L5–L7 above |
| 2026-10-29 | **E's follow-up merged** (b214640; 0cb3ebc): a double click on a file in folder mode does not choose the folder; the lead's mutation now fails it. **K started** (F-14, 873x, `high`) in E's slot. **Merged I** (d23b699; 419cc0d): F-10's M4 part (`TrackTable` with the bitrate's source, roles with evidence, expandable details; output rows with source, action, encoder settings, reveal targets `audio[i]` / `subtitles[i]`, issues at the fields; *Add track*, *Add all* — the remaining source tracks —, *Reload from preset rules*, remove, drag and keyboard reorder; each change one undo step). Merge conflict: the F-9 / F-10 rows. Checks on the merge: lint, format, typecheck, 696 unit tests, `build:web`. The lead's 3 mutations: *Add all* adding duplicates and an encoder change keeping an invalid bitrate were caught; **the remove button removing the track before it survived** (the tests removed only the first track): sent back; **I's follow-up merged** (dc27081; e10f9ad), the mutation now fails it |
| 2026-10-29 | **The lead's integrated check** (headless Chromium, real server, the real FFmpeg, only the UI): `Ctrl+O` → the file browser → `multitrack.mkv` → the tabs; Audio: remove output track 2 (3 → 2), `Ctrl+Z` (→ 3); validation settled with no error; `Ctrl+Enter` → `waiting …/output/multitrack.mkv` and the toast *Added to the queue*; *Start* → `done` and the server's *Job done* notification as a toast; no console error. This closes C's deferred browser part (*Add to queue* with a job from an opened file, undo of an edit); D's deferred part was done by H. Findings L8, L9 |
| 2026-10-29 | **Merged L** (merge of 64bcab8): F-15 basic (Tools with status, version, origin; *Test* = save a changed path, re-scan, offer to put the old one back; tool paths read-only in web mode, where the server refuses them; environment overrides read-only; *Use bundled FFmpeg* as one section button that also removes the Settings paths of ffmpeg and ffprobe once the download is done; Encoders with re-scan, hardware tests, the VAAPI node; Output with F's editor saved 600 ms after the last edit as one patch; Queue with *Quit* desktop-only; Appearance through `useTheme`; read-only settings tried with `schema_version: 999`). Checks on the merge: lint, format, typecheck, 743 unit tests, `build:web`. The lead's 3 mutations caught (when-done not set; the naming save without its debounce; an environment override editable). L's note on *Quit* passed to K. Findings L10–L13. L's worktree removed |
| 2026-10-29 | **Merged J** (merge of dd63c8c, 23f2c5d, e7abb40): F-12 (the store read at first use, when the view or the picker's list opens, after a change whose answer does not describe the list, and after a reconnect; the picker as a button with a filterable `Listbox` in a `Popover`, the *Modified* marker and its changes popover on click or Enter — 03 says hover: recorded in J's section and F-12's box —, *Save as new* (the job follows the new preset in one undo step), *Update*; the `/presets` view with the tree, details, rename, duplicate, star, delete with a modal confirmation, import with rename / replace / skip and its report, export; inherit naming as a switch). Real server: a clash is `409 preset.name_conflict` with a fix offering the next free name; built-ins `409 preset.built_in`. Checks on the merge: lint, format, typecheck, 809 unit tests, `build:web`. The lead's 3 mutations caught (the picker not drafting again; a built-in offered rename; the offered free name ignored). The lead's `src/testing/setup.ts` (L11). J's worktree removed. **M started** (F-17, 875x, `high`): flow 3 needs J, H and C, all merged |
| 2026-10-29 | **Merged M** (merge of 0011085): F-17's M4 part (one `scripts/dev-server.py` per project through Playwright's `webServer`, Chromium 8750 and Firefox 8751, the build first; `gracefulShutdown` SIGTERM to the process group; an auto fixture that gives the queue back as each test found it; a pass-through fake FFmpeg in which every hardware test encode gets a captured real failure, so the closest match of `hevc_nvenc` is `libx265` on every machine; flow 3 through the UI to a real libx265 `done`). M ran it twice, with a forced failure and with SIGINT: nothing left behind; 4 mutations of app code each failed it. **`dev-server.py` fix** (M's find): a failure before the server started (a missing fixture, a bad settings file) left the home behind; now the handlers come first, the home is checked before anything is made, and everything after it is inside the clean-up (both failures: no home left); `npm run e2e` after the change: `2 passed (11.4s)`, nothing left. Checks on the merge: lint, format, typecheck, 809 unit tests. Findings L14–L16. M's worktree removed |
| 2026-10-29 | **Merged K** (merge of 89a0e7c, 24fc82a): F-14 (`QueueTable` with the live columns, actions per state, edit-back, drag and keyboard reorder, a failed job's issues; `QueueControls` with the run state from `processing` / `only`, Start / *Start all*, Stop, pause / resume / cancel all; `WhenDoneSelect` with *Quit* desktop-only; `PowerBanner`; `JobLog` in a drawer with a virtual scroller, follow mode, copy all; `ActivityView` with the activity store keeping only the latest progress, log and tick per job, task or countdown, at most 1000 entries). Real server (`queue.server.test.ts`): another front end's `start {job_ids}` → `processing` with `only`; the store's `start()` widens it; `stop()` → not processing, a waiting job stays waiting; `start` then `idle` after a stop with an ended job — **this closes the lead's open check of `queue.processing` against the real server**. In the browser: after Stop the running job ran on to `done` and both waiting jobs stayed `waiting`; when done *Sleep* with the dry run (checked in `/proc/<pid>/environ`), the countdown shown and cancelled. Checks on the merge: lint, format, typecheck, 903 unit tests, `build:web`. The lead's 3 mutations caught (Stop sending a pause; edit-back not loading the job; the log not reading on). Finding L17; L9's cause. K's worktree removed. **Every build task is merged** |
| 2026-10-29 | **Wave 4 done.** Alone, with no agent running: `npm run test:server` `9 passed` files, `38 passed` tests (55 s), nothing left behind; `npm run e2e` `2 passed (10.5s)`, nothing left behind. No `packages/` or `testing/` change since the full Python suite of 9b7018d. **Wave 5 started**: R1 (API layer, events, stores, editor state, undo, validation, concurrency, the queue and Stop end to end; 877x) and R2 (the screens, i18n, keyboard, focus, light and dark contrast, empty and error states, layout; 878x), both `xhigh`, fresh, told not to read this file's "Integration findings" and "Progress" |
| 2026-10-29 | **R1's review** (at 57eb8cc): 2 majors, 3 minors, all reproduced by R1 (scripts in the scratchpad `review-r1/`). R1-1 major: `Ctrl+Enter` adds the job without the value typed in the focused field (PrimeVue `InputNumber` writes on blur; the naming editor holds its edit until the preview) — the toast says added, the queue gets the old quality / naming. R1-2 major: a naming change without typing (mode switch, *Reset template*, name source, fixes, chips, overrides) reaches the job only after the preview (~280 ms) while *Add to queue* stays enabled and queues the old naming. R1-3 minor: a click on *Add* right after typing does nothing (the blur makes validation pending under the pointer). R1-4 minor: leaving Summary before the preview answers commits the naming but never the path. R1-5 minor: removing the editor's source while another's draft loads leaves that source active with no job. Seven suspected, not reproduced. **The lead reproduced both majors** on his own server (8761): `ctrl-enter-quality` (box "RF 30.0", queued 22), `ctrl-enter-naming` (queued template `null`, editor `{main_title} MYNAME`), `naming-mode-add` (Add enabled right after *Reset template*, queued `{main_title} CUSTOM`). R1's worktree removed (nothing committed) |
| 2026-10-29 | **R2's review** (at 57eb8cc): 1 blocker, 6 majors, 11 minors, 7 nits. **The lead reproduced** (server 8780, R2's scripts and his own): R2-1 (document 3,366 px in a 900 px window; one wheel scroll moved the window 2,466 px), R2-2 (the issue message box 0 × 1,299 px), R2-3 (focus on `body` after opening from the empty state and after *Add to queue*), R2-4 (the Appearance popover open with the focus still on its trigger), R2-5 / R2-6 by the WCAG formula from the token pairs R2 named (slate-500 on slate-100 4.32:1, orange-500 on white 2.81:1, slate-300 on white 1.48:1), R2-7 in the code (`PowerBanner` mounted only by `QueueView.vue`). R2's safety note: one script chose *Shut down* as when-done (arrow presses skip the disabled *Quit*); the dry run was in effect (checked in `/proc/<pid>/environ`) and the countdown was cancelled after about 2 s. R2's worktree removed. **The fix round planned** ("Fix round" above; placeholders in 0063) |
| 2026-10-29 | **Fix round started**: FA (`xhigh`, 871x), FB (`xhigh`, 872x), FC (`xhigh`, 873x), FD (`high`, 874x) in four worktrees; FE (`high`, server texts) waits for a free slot |
| 2026-10-30 | **Merged FD** (7 commits, 0ce1c16…b9a3de8): R2-8 (track rows and Settings Selects named by their label), R2-18 (the quality slider 0.5 / 1 per arrow, a page 5 — 25 on the 0–255 scales —, Home / End), R2-19, R2-21 (KiB everywhere), R2-24 (headings from h2; a source's name without its buttons; the empty note outside the listbox), L8, L16. Checks on the merge: lint, format, typecheck, 924 unit tests, `build:web`. L2 is in `OutputCard.vue` (FB's this round): FD's notes passed to FB; `SummaryTab.test.ts` (FD's) will need its name selectors moved after FB's merge (the lead). FD's worktree removed; **FE started** (874x) |
| 2026-10-30 | **Merged FE** (05e5c37, 9d0b8e4, ee7f8fe, 03b8881): L6 (a refused listing: "… is outside the server's media and output folders. Browse from one of them."), L12 (`settings.tools_forbidden` names the variables of the tools in the patch, from `reframe.tools.ENV_VARS`), R2-20's second half (a missing MediaInfo or mkvpropedit names its variable, in both modes). Checks on the merge: ruff, format, mypy ×2, `gen-api.sh --check`, 106 targeted tests. The lead's mutation (the old listing text back) failed FE's test. FE's worktree removed. **The owner asked to stop after the running fix agents (FA, FB, FC) come back: merge, document, no new work** |
| 2026-10-30 | **Merged FB** (aa3699a…89af41c): R1-1 / R1-2 / R1-3 / R1-4 / R1-5 / R1 suspected 2, 3, 5, L1, L2, L13, R2-8 (naming), R2-20 (probe toast). Design: pending edits in the editor store (`beginEdit` / `endEdit` / `flushEdits`), `validation.flush()`; an add commits the focused field, waits for the edits, the draft and the check (at most 20 s), then adds the job as it is, or says why not in a toast; `canAdd` no longer drops under a click; a naming edit is pending until it is in the job with its path; a container change carries the extension in one undo step. R1's scripts after the fix (FB's run): every one queues what the screen shows. The lead applied FB's patch to FD's `SummaryTab.test.ts` (the Output card's name rows are gone; the naming editor's tests cover the name and reason). **Merged FA** (600fa84…9314d44): R2-1 (`.rf-sr-only` gets `inset-block-start` / `inset-inline-start` 0: every screen exactly the window's height, both browsers), R2-2 / L4 (fixes on their own row: the message box 0 → 470 px), R2-5 / R2-6 / L15 (Aura component tokens overridden: e.g. the Modified marker 2.80 → 5.18, the unselected SelectButton label 4.34 → 6.92, the switch track 1.48 → 4.76, the checked SelectButton option filled with the primary colour), R2-9, R2-15, R2-16 (PrimeVue's `locale` from `base.primevue.*`), R2-17; `e2e/layout.spec.ts` (5 tests × 2 browsers). R2-25 not fixed: the bar is drawn in the Video tab's padding beside the sticky drawer, a `CommandPreview.vue` change (FA's proposed rule recorded in its 0063 section). Checks after both merges: lint, format, typecheck, 965 unit tests, `build:web`. The lead's mutation (the switch track back to slate-300) failed `contrast.test.ts`. FA's and FB's worktrees removed |
| 2026-10-30 | **Merged FC** (2119a7e…a03594d): R2-3 (focus-safe busy buttons, the focus moved to the row's new action, to the Summary tab after opening or *Edit*, to the copy after *Duplicate*), R2-4 (popovers take the focus and keep Tab inside), R2-7 (the countdown above every view, keyboard reachable; checked with the dry run confirmed in `/proc/<pid>/environ`, *Sleep* chosen by its label, cancelled), R2-11, R2-12, R2-10, R2-13 / L17, R2-14, R2-20, R2-23, R2-8 (when-done), L3 / L10 / R2-22, R1 suspected 4. **Final checks, alone** (no agent running): frontend lint, format, typecheck, 1007 unit tests, `build:web`; `npm run test:server` 9 files, 38 tests; `npm run e2e` 12 passed (flow 3 and FA's 5 layout checks, Chromium and Firefox), nothing left behind; Python ruff, format, mypy ×2, `gen-api.sh --check`, server + testing + core tools + CLI `1041 passed, 1 skipped`. The lead's mutation on FC (the banner hidden in the shell) failed `App.test.ts`. All worktrees removed. **Stopped at the owner's request** ("Stop implementation after these agents come back. Commit their work and document the status"): no new agent, no demo, no merge into `main` |

## Where M4 stands (2026-10-30, stopped by the owner; updated 2026-11-01)

Everything the scope lists is built, merged on `m4-frontend-mvp`, reviewed twice, and every
blocker and major found is fixed with a test. Since the stop (2026-11-01): R2-25 is fixed, the
CI jobs for `npm run test:server` and `npm run e2e` are in `ci.yml` (never run), and the flaky Ctrl+Z
test is fixed (a race in the code, 0061 "Follow-up, 2026-11-01"). What is
left before the owner can merge:

1. **The M4 demo**: the headless run is done (2026-11-01, 0063 "M4 demo, 2026-11-01": one defect
   fixed, three observations recorded). What is left is the headed run. The flow, for reference: in the browser, open a file from the server file browser →
   choose a preset → change the encoder and quality → add and remove audio tracks → add to queue
   → watch progress → open the log; validation issues inline and on Summary; plus flow 3. First
   headless (Playwright, screenshots read; done), then once headed by the lead on `HDMI-A-1` through the
   spike's window guard (ask the owner first to put the mouse and the active window there).
2. **Recorded, not fixed in M4**: L5 (a `fs/list` option for other files: M6), L7 (the desktop
   platform stub: M5), L14 (an output another waiting job claims is known only at the add), a
   duplicate's automatic free name; from the headless demo: the queue table's narrow Source and
   Output columns at 1440 px, Summary's issue list below the Output card, a second opened file
   not selected while another is open.
3. **The docs reconciliation** before a merge: the F rows say "on `m4-frontend-mvp`"; the
   roadmap's M4. The final checks are done (2026-11-01, run alone, on Linux): the full Python
   suite 7395 passed, 2 skipped, 26 deselected; `npm run test:server` 38 passed; `npm run e2e`
   14 passed; the other commands from `CLAUDE.md` clean. The two CI jobs have not run on GitHub.
