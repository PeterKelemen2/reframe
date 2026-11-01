# M7 task breakdown

Working notes of the lead for the branch `m7-batch-season`: milestone M7, batch and season mode.
The plan ([plan/08-roadmap.md](plan/08-roadmap.md) §M7, [plan/04-batch-mode.md](plan/04-batch-mode.md)
(all of it), [plan/06-web-app.md](plan/06-web-app.md) §F-4, §F-13, §F-17, §F-18) is the spec;
this file says who builds which part, in which order, and what each part must offer to the
others. Decision: [0066](decisions/0066-m7-batch-season.md) (the lead's choices and one section
per task). Status: [status.md](status.md). The template is [m6-breakdown.md](m6-breakdown.md).
If the lead's context is summarised, this file and `status.md` are the source of truth.

M7's core part (C-12, [0040](decisions/0040-batch-engine-and-reframe-batch.md)) and the batch
routes are done and merged. M7 builds the UI on them. No route is missing (0066 Context); one
core change (a re-derived rule keeps `required`, 0066 item 2) is done by the lead in wave 0.

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| A | F-4 | The group target of the editor store: edit a group, the shown file and the scope, edits routed into the template (derive) or the file's override, undo / redo of `{template, overrides}`, the matrix's resolution, hand picks, name fields, row fixes, override queries, presets on a group | 06 §F-4, §F-13; 04 §Three ways to edit, §Per-file overrides; 0066 items 1, 3–5, 8, 9 |
| B | F-13, F-5 | Group rows in the sources panel (*Edit group*, *Check group*, *Add group to queue*, a context menu with copy / paste), the group banner (name, file count, the shown-file switcher, the scope, *Check group*, *Save as preset*, *Close group*), `ApplyToGroupDialog`, the save-as-preset dialog, the clipboard | 06 §F-13; 04 §Grouping, §Three ways to edit, §Save as preset; 0066 items 6, 8, 11 |
| C | F-13, F-18 | `ResolutionMatrix` in a dialog (virtualised, ✓ / ≈ / ✗ / – cells, candidate picker, *problems only*, sorting, the naming column with its edits, issues with fixes), *Add group to queue* with its error dialog, *Add to queue* / `Ctrl+Enter` while a group is edited | 06 §F-13, §F-18; 04 §Resolution matrix, §Output naming, §Queueing a group; 0066 items 3, 4, 7 |
| D | F-13, F-10 | Override dots on `Field` with *Reset to group* / *Apply to whole group*; the defaults dialog's group target; the Summary output card, the naming editor and the track lists working in a group | 06 §F-13, §F-10; 04 §Per-file overrides; 0066 items 5, 10 |
| E | F-17 | Flow 2 (Playwright) | 06 §F-17 |

**Out of scope** (do not start): M5 and every `D-x`, F-7, F-8, F-16, the F-9 advanced panel,
F-17 flow 4, the Chromium / WebKit run of M10.

Defaults the lead took where the plan leaves a choice: 0066 items 1–11 (read them; they are
binding).

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0066, the derive change, the skeleton (types, the editor store's group API as stubs, `GroupBanner` / `MatrixDialog` stubs mounted in `WorkspaceView`, `useQueueGroup` stub, `ui.openMatrix`) | `main` (37226c8) |
| 1 | A (risky, alone in its concern), B, C | the skeleton |
| 2 | D; B and C resumed for their checks against the real store | A merged |
| 3 | E | wave 2 merged |
| 4 | two fresh reviews (R1: the state, the matrix, overrides, undo / redo, queueing and the server calls; R2: the screens, i18n, keyboard, focus, light and dark contrast, empty and error states; both also flag code more complicated than it needs to be), the fixes, the M7 demo headless (Chromium, Firefox) and once headed by the lead, the docs | wave 3 merged |

B and C code against A's contract (the stubs in `stores/editor.ts`): their unit tests set the
store's state and spy on its actions; their checks in a browser wait for A's merge (the lead
resumes them). At most four worktrees at a time. The lead merges each task with `--no-ff`, runs
the frontend commands, mutates once per task (A twice), and removes the worktree and its
branch.

Every agent: `model: "opus"`, `effort: "high"` (the owner's rule for this run; never `xhigh`),
`isolation: "worktree"` for code.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Paths are
relative to `frontend/src/` unless they start with `frontend/`, `docs/`, `scripts/`, `testdata/`
or `packages/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **A** | `stores/editor.ts` and its tests (`editor.test.ts`, `editor.server.test.ts`, new `editor.group*.test.ts`), new `editor/group.ts` (+ test; pure helpers: which section an operation touches, which paths are per file, override merge and track guards, validation path → pointer), `editor/template.ts` (a helper to make a template from a preset, if needed), `stores/sources.ts` (only what a group needs: the active source while a group is edited, a removed member), `composables/useValidation.ts` (only if a group needs it), `i18n/messages/en/editor.json` (the `editor.group.*` keys) | every component |
| **B** | `components/sources/**`, `components/batch/**`, `i18n/messages/en/group.json` (new: the `group.*` keys), the `sources.*` keys of `i18n/messages/en/sources.json` | `stores/**`, `components/matrix/**`, `components/base/**` |
| **C** | `components/matrix/**`, `composables/useQueueGroup.ts` (+ test), `composables/useQueueActions.ts` (+ tests: the group branch of *Add to queue*), `components/shell/StatusBar.vue` (only the group case of its *Add to queue*), `i18n/messages/en/matrix.json` (new) | `stores/**` (use them), `components/naming/**` (use it), `components/sources/**`, `components/batch/**` |
| **D** | `components/base/Field.vue` (+ test), `components/defaults/**`, `stores/defaults.ts` (+ tests), `components/summary/OutputCard.vue`, `components/naming/JobNamingEditor.vue`, `components/tracks/OutputTrackList.vue` (only what a group needs), the keys of `i18n/messages/en/{base,defaults,summary,naming,tracks}.json` it adds | `stores/editor.ts` (use it), `components/matrix/**`, `components/batch/**` |
| **E** | `frontend/e2e/**` except `frontend/e2e/layout.spec.ts` and `frontend/playwright.config.ts` | every file of `src/`, `frontend/package.json` |

**Lead-owned**: `frontend/package.json`, `frontend/package-lock.json`, `api/**`, `router/**`,
`components/editor/tabs/registry.ts`, `i18n/index.ts`, `i18n/messages/en/app.json`, `setup.ts`,
`main.ts`, `notBuilt.ts`, `App.vue`, `stores/{toasts,ui,validation,presets,queue}.ts`,
`views/**`, `composables/useShortcuts.ts`, `platform/**`, `frontend/vite.config.ts`, the
tsconfigs, `frontend/playwright.config.ts`, `scripts/dev-server.py`, `packages/**`. An agent that
needs another dependency, a route, a registry entry or a change of these files asks the lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own sentence of its step's row (A: F-4; B, C,
  D: their parts of F-13, each in its own sentence; C: F-18's naming column; D: F-10's group
  case; E: F-17).
- `docs/decisions/0066-m7-batch-season.md`: each task writes only its own section ("Task X").
- `docs/plan/06-web-app.md`: a task ticks its own step's boxes, and edits its step's text only
  together with a decision (its 0066 section).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. The signatures are in the skeleton's files (read them; they are the source); this is
their summary. A task may add members, optional parameters with defaults, files and
components in its own folders, but not change these. `notBuilt(…)` marks a stub: replace it,
and remove the `oxlint-disable` / `oxlint-enable` lines around the stubs you build.

### The editor store's group target (A builds; B, C, D use)

```ts
type GroupScope = 'group' | 'file'
type RuleKind = 'audio' | 'subtitle'
type EditorTarget =
  | { kind: 'job'; sourceId: string; job: JobSettings }
  | { kind: 'group'; groupId: string; sourceId: string /* the shown file */; job: JobSettings /* what the tabs show */;
      template: JobTemplate; presetId: string | null; overrides: Record<string, JsonPatchOp[]>; scope: GroupScope }

// state
target, job (the shown job in both kinds), presetId (the group's preset in a group), currentTemplate (the template in a group),
modified, canUndo, canRedo, editing, editFailure       // as M4, for both kinds
group: ComputedRef<BatchGroup | null>                  // the edited group, from sources.grouping
resolution: ShallowRef<BatchResolution | null>         // batch/resolve-run of the group, newest answer only
resolving: Ref<boolean>

// actions (one undo step each unless said)
get / set / patch / endCoalescing / undo / redo / applyFix / applyPreset   // both kinds (0066 items 1, 8)
editGroup(groupId): Promise<void>                      // restores or starts the group's state; sources.activeId = the shown file
showFile(sourceId): Promise<void>                      // the representative switcher (no undo step)
setScope(scope): Promise<void>                         // (no undo step)
patchTemplate(ops, options?): void                     // a group's template change
mergeIntoGroup(groupId, from: JobSettings, sourceId, sections: TemplateSection[]): Promise<void>
pickTrack(sourceId, kind: RuleKind, rule, stream: number | null): void   // null = no track
resetTrack(sourceId, kind, rule): void
setNameField(sourceId, field, value: string | null): void                 // /job/output/naming/field_overrides/<field>
applyRowFix(sourceId, fix): Promise<void>              // template → template; job → that file's override; settings
overriddenAt(path): boolean                            // scope file: the shown file's override sets `path` (a validation path)
resetToGroup(path): void
applyToWholeGroup(path): Promise<void>
resolveNow(): Promise<BatchResolution>                 // after the edits on their way; what queueing uses
open / loadJob / close                                 // as M4; a group's state is kept per group id (0066 item 1)
```

Every action that changes the group resolves it again (newest answer only); `resolution`
always describes the template and overrides it was asked for or is replaced.

### UI state (`stores/ui.ts`, lead)

`matrixOpen: Ref<boolean>`, `matrixFocus: Ref<string | null>`, `openMatrix(focus?: string |
null)`: B's *Check group* and C's error dialog open the matrix through it; C's `MatrixDialog`
shows it while `matrixOpen` is true and sets it false on close.

### Composable (C builds; B uses)

`useQueueGroup(): { busy: ComputedRef<boolean>; queueGroup(groupId: string): Promise<void> }`
(`composables/useQueueGroup.ts`): edits the group when it is not the edited one, then 0066
item 7. B's group row and banner call it; C's status bar case calls it.

### Mount points (lead)

`WorkspaceView` mounts `components/batch/GroupBanner.vue` (B) above the tabs (it shows itself
while a group is edited, and *Apply to group…* / *Edit group* while a file of a group is open as
one job), and mounts `components/matrix/MatrixDialog.vue` (C) once. C mounts its queue-group error
dialog inside `MatrixDialog.vue`'s tree.

### i18n

As M6: `i18n/messages/en/<area>.json` holds the keys of `<area>.`. New areas: `group` (B),
`matrix` (C). A adds `editor.group.*`; D adds keys to the areas it owns.

## Done when (word for word in each agent's brief)

Every "in a browser" check runs headless against a real `reframe-server` started with
`scripts/dev-server.py` and the pinned FFmpeg, with the `Anime.Show.S01.BluRay.x264-GRP` and
`Anime.Show.S02.BluRay.x264-GRP` fixture folders, in light and dark, with screenshots read by the
agent.

- **A (F-4)**: 06 §F-4: "an **EditorTarget** is either a single `JobSettings` or a group
  (`JobTemplate` + overrides). The tabs use one API for both." Unit tests and a real-server test
  (`npm run test:server`) with `anime-s01`: *Edit group* on the season gives the template of the
  editor's preset and the matrix of 12 rows (E05 ⚠ near, the rest ✓ with the default preset);
  E01's audio A1 set to Opus 5.1 448 named `Japanese 5.1` and A2 to AC-3 5.1 640 through
  `editor.patch` (group scope) gives explicit rules and the matrix of 04 (E11 "A2 ✗", "S1 ≈");
  E11's fix makes A2 optional and E11 ⚠, and a later edit of A1 keeps it optional; an undo of
  each step gives back the exact template and overrides before it, a redo the one after; a hand
  pick and *No track* in one file change only that file's row, and a template change keeps them;
  a name-field correction changes only that file's output name; a scope-`file` edit changes
  only that file's job, shows `overriddenAt`, survives a template change, and *Reset to group* /
  *Apply to whole group* do what 04 says; an edit the template cannot hold (scope `group`) and a
  track added or removed in scope `file` are refused with nothing changed; a preset applied to
  a group replaces the template in one undo step; the state of a group comes back after another
  file was open; only the newest resolution is kept.
- **B (F-13, F-5)**: In a browser: opening the S01 folder shows one group of 12 with E05's
  difference; *Edit group* shows the banner `Editing group "Anime Show S01" (12 files) — showing
  E01`, the switcher shows another file, the scope switch works, *Close group* opens the shown
  file as one job; *Check group* opens the matrix (C's dialog once merged); *Apply to group…* from
  a single file of the group applies the checked sections only; *Copy audio settings* of the open
  file and *Paste audio settings* on the group and on another file do what 0066 item 6 says, one
  undo step each; *Save as preset* saves the template as a user preset that the presets view
  lists; everything works with the keyboard alone, in light and dark.
- **C (F-13, F-18)**: In a browser: *Check group* shows one row per file and one column per
  output track plus V and the output name, ✓ / ≈ / ✗ / – cells with their messages, E05 ⚠ and
  E11's cells as 04's matrix; a cell's candidate picker picks another track or no track (one
  undo step) and only that row changes; *problems only* shows E05 and E11 alone; columns sort by
  status; the naming column shows each file's name source and parsed fields, an edit of a field
  changes that file's output name only; an issue's fix works from the matrix; *Add group to
  queue* with no error queues 12 jobs in episode order with their templated names, and with
  errors shows 04's dialog (*Queue the valid files, skip the others* queues the others, *Open
  matrix*, *Cancel* queues nothing); `Ctrl+Enter` while a group is edited runs the same flow; the
  table is virtualised and keyboard-reachable; light and dark.
- **D (F-13, F-10)**: In a browser: in scope `file`, a field the file overrides shows the dot;
  its menu's *Reset to group* and *Apply to whole group* do what 04 says (one undo step each); no
  dot in scope `group` or for a job; the defaults dialog opened in a group edits the template's
  defaults, its live preview has one table per file of the group, and *Apply* turns the group's
  tracks back to the defaults in one undo step; the Summary output card, the naming editor and
  the track lists work while a group is edited (no error, the group's values shown, per-file
  fields say so).
- **E (F-17)**: 06 §F-17 flow 2: "Open a season folder → edit group → check the matrix → queue
  the group." `npm run e2e` (headless Chromium and Firefox) passes flow 2 twice in a row next to
  flows 1 and 3 and the layout checks, and leaves no process and no temporary folder behind.

## The M7 demo (the acceptance test; the lead runs it at the end)

08 §M7 with 04 §Example: open the season folder (`anime-s01`) → one group of 12 (E05 "1 extra
track") → *Edit group* → Audio: A1 = jpn TrueHD → Opus 5.1 448k, name `Japanese 5.1`, default;
A2 = eng DTS-HD MA → AC-3 5.1 640k, name `English 5.1`; Subtitles: S1 = Signs (forced), S2 =
Full (default) → *Check group*: ✓ for every file, E05 ⚠ (near), E11 ⚠ after its fix (A2
optional: "– skipped", "S1 ≈ title") → the naming template `{name} - S{season:02}E{episode:02}<
- {sub_title}>` → *Add group to queue* → 12 jobs with templated names (`Anime Show - S01E01 -
Pilot.mkv`) → *Save as preset* → open `anime-s02` → *Edit group* → pick the saved preset → ✓
for its 3 files. Then F-17 flow 2. First headless (Playwright, Chromium light and dark, Firefox,
the screenshots read), then once headed by the lead on `HDMI-A-1` through the guard.

## Commands

As [m6-breakdown.md](m6-breakdown.md#commands). The fixtures are folders:
`scripts/dev-server.py --fixtures Anime.Show.S01.BluRay.x264-GRP,Anime.Show.S02.BluRay.x264-GRP`.

**Ports** (rule 7): agent N uses 87N0 to 87N9; 8750 and 8751 belong to `npm run e2e`. A 871x,
B 872x, C 873x, D 874x, E 877x, the lead 876x, R1 878x, R2 879x; fix agents take the ranges
free at the time.

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
  it builds and the ones it uses, its "Done when" word for word, its section of 0066,
  rules 5, 6 and 7 and the test rules word for word, its port range.
- Setup: the worktree starts at `main`: first `git merge --ff-only m7-batch-season`. Then
  `uv sync`, `npm ci` in `frontend/`, and
  `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (`--tools-dir` of `scripts/dev-server.py`); `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not
  installed.
- Commits per step, step ID first (`F-13: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Update only its own
  `docs/status.md` row.
- The report: the real output of every command of rule 5 (the last lines), what the agent saw
  in its screenshots (light and dark), the test rules' checks, every deviation from the plan
  and from this file, every file touched outside its list, and what later tasks need.

### Simple code (the owner's rule for M7, word for word in each brief)

- Build what the plan says and nothing more: no extra options, settings, modes or "might need later"
  hooks. Smallest change that makes the "Done when" lines pass.
- Look before you write: reuse the existing components, stores, API layer and helpers
  (`LanguagePicker`, `TrackMetadataEditor`, `DefaultsDialog`, the editor store, `Field` and so on).
  Match the code around yours: naming, structure, comment density.
- Plain functions and plain components. No new abstraction layer, class hierarchy, plugin point or
  generic utility for one caller. Extract on the third copy, not the second.
- No defensive code for states the types or the server already rule out. Expected failures stay data
  (the project rule); do not add try/catch or fallbacks around calls that cannot fail that way.
- No new dependency unless you can say why the platform or an existing dependency cannot do it.
- Tests: one for each "Done when" line and each bug you fix, testing behaviour, not a copy of the
  implementation.
- Simple does not mean less correct. Undo, validation, the plan's i18n and keyboard rules, and file
  safety stay. If a simpler design than the plan's exists, do not switch quietly: write a decision
  record and edit the plan in the same commit.
- Load the `code-comments` skill before writing code. A comment says why. No step IDs, plan sections
  or history in code.
- The report says what you chose not to build.

### Changes for M7 (binding, with the rules above)

- The worktree starts at `main`: every agent first runs `git merge --ff-only m7-batch-season`.
- Commits start with the step ID (`F-4: …`, `F-13: …`, `F-17: …`) and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Stage files by name.
- Each agent updates only its own sentence of its `docs/status.md` row and writes only its own
  section of 0066.
- Scratch files: each agent keeps its scratch files (server logs, ready lines, scripts,
  screenshots) in its own `scratchpad/task-<x>/` and reads a server's URL and token only from
  the ready line of a server it started itself.
- Nothing in a test or a check writes to a media file outside the temp folders; queued jobs
  write only into the dev server's output root.
- The report starts with the agent's model ID.

## Progress

| Date | What |
|------|------|
| 2026-11-01 | **Wave 0.** Branch `m7-batch-season` from `main` 37226c8. API check against a real server (0066 Context): no route missing; `batch/resolve` lacks `batch.near_match`, so the matrix uses `batch/resolve-run`; `merge_template` replaces whole sections, so the derive change of 0066 item 2 (with its test; a mutation that drops the carry-over fails it). This file; 0066 with placeholders and the plan edits; the skeleton: type aliases (`BatchGroup`, `BatchResolution`, `Resolution`, `TrackMatch`, `MatrixColumn`, `TemplateSection`, `MatchLevel`, …), the group target and its API as stubs in `stores/editor.ts`, `ui.openMatrix`, `useQueueGroup` stub, `GroupBanner` and `MatrixDialog` stubs mounted in `WorkspaceView`. Checks: lint, format, typecheck, 1335 unit tests; `reframe` batch tests 704 passed, ruff, mypy |
| 2026-11-01 | **Wave 1 launched**: A (871x), B (872x), C (873x), each `opus` / `high` in its own worktree; briefs in the lead's scratchpad `briefs/` (A.md, B.md, C.md, common.md). B and C stop after phase 1 (unit-tested against the stubs) and are resumed for their browser checks after A's merge |
| 2026-11-01 | **Merged A** (3abcbef; bc3359f): the group target (0066 "Task A"). A's own mutations: 35 unit + 4 real-server, all killed after 5 added tests. The lead's mutations: `pickTrack` keeping the cell's earlier operations → `editor.group.test.ts` "a pick and no track…" fails; `mergeOverride` not replacing an earlier operation on the same path → `group.test.ts` fails; both restored and touched. `editor.group.server.test.ts` re-run by the lead: 1 passed, nothing left behind. A's deviations (recorded in its section): with the default preset E11 is ⚠ near too; E01's subtitles are already S1 forced / S2 default, so the subtitle edit of the server test is a name. Worktree removed |
| 2026-11-01 | **Merged B phase 1** (5c07ef7; 780b8be) and **C phase 1** (d935330; 2957f7f; the F-13 row's two sentences joined). Integrated checks: lint, format, typecheck, 1476 unit tests, `build:web`. C's picker lists every track of the kind (an exact match's `candidates` is the taken track only; accepted). B and C resumed for their browser checks; **D launched** (874x) |
