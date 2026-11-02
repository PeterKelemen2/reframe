# M9 task breakdown

Working notes of the lead for the branch `m9-advanced-options`: milestone M9, advanced encoder
options. The plan ([plan/08-roadmap.md](plan/08-roadmap.md) §M9, [plan/03-features.md](plan/03-features.md)
§Video and §Advanced encoder options, [plan/06-web-app.md](plan/06-web-app.md) §S-2 (Definitions,
Jobs) and §F-9) is the spec; this file says who builds which part, in which order, and what each
part must offer to the others. Decision: [0068](decisions/0068-m9-advanced-options.md) (the
lead's choices and one section per task). Status: [status.md](status.md). The template is
[m8-breakdown.md](m8-breakdown.md). If the lead's context is summarised, this file and
`status.md` are the source of truth.

M9's core part (C-6: the complete option sets with per-preset defaults, the option search, Copy
HDR metadata, the custom-parameter dry run; [0035](decisions/0035-advanced-option-sets-and-dry-run.md))
and its routes are done and merged. M9 builds the one unchecked F-9 box on them: the
`AdvancedOptions` panel in the Video tab. The lead's wave-0 check (0068 Context) found every
route the panel needs; no server task.

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| A | F-9 | `AdvancedOptions`: the panel generated from the encoder's option schema (categories in panel order with a changed-count each, the search over labels, CLI names and help text, *Show only changed*, one row per option with the control of its type, the changed highlight, reset ↺ per option, the default as placeholder text that says when it depends on the speed preset, the ⓘ help popover), the *Custom parameters* category (B's field) and B's *Copy HDR metadata* button in *HDR / colour*, a reveal of `video.advanced.*` / `video.custom_params` that shows the option | 06 §F-9; 03 §Video ("**Advanced…**"), §Advanced encoder options; 0068 items 1–7 |
| B | F-9 | `CustomParams` (the free `key=value:…` field of `video.custom_params`, editable, checked by `POST /api/jobs/dry-run` once the typing stops, its errors at the field), `CopyHdrMetadata` (*Copy HDR metadata from source*: `POST /api/jobs/hdr-metadata`, the patch as one undo step, a note when there is nothing to copy) | 06 §F-9; 03 §Advanced encoder options (custom parameters, Copy HDR metadata); 0035; 0068 items 8–9 |

**Out of scope** (do not start): M5 and every `D-x`, F-16, the Windows run and the WebKit run of
M10, the M8 owner questions (L1, L2), any change of the core's option sets, defaults, search
ranking or dry run (a defect found there goes to the lead). **Not built, recorded**: a dry run in
`jobs/validate` or at *Add to queue* (0068 Consequences).

Defaults the lead took where the plan leaves a choice: 0068 items 1–9 (read them; they are
binding).

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0068, the API check, the skeleton (`EncoderOption` type alias, `ui.advancedOpen` and the reveal that opens it, the collapsible *Advanced options* section in the Video tab with the stub `AdvancedOptions` that mounts the stubs `CustomParams` and `CopyHdrMetadata`, the read-only custom parameters field removed, `i18n/messages/en/advanced.json` and `params.json`) | `main` (7fbda7c) |
| 1 | A, B | the skeleton |
| 2 | B resumed (SendMessage) for its checks inside A's panel | A merged |
| 3 | two fresh reviews (R1: the option schema, state, undo, persistence and validation; R2: UI, keyboard, a11y, i18n, layout, the real browser; both also flag code more complicated than it needs to be), the fixes, the M9 demo headless (Chromium, Firefox, light and dark) and once headed by the lead, the docs | wave 2 merged |

B builds and checks its two components in a browser inside the stub panel (the stub mounts them),
reports, and stops; the lead resumes it after A merges to check them in A's panel (the HDR fields
filled in their rows, the custom parameters category). The lead merges each task with `--no-ff`,
runs the frontend commands, mutates once per task, and removes the worktree and its branch.

Every agent: `model: "opus"`, `effort: "high"` (the owner's rule for this run; never `xhigh`),
`isolation: "worktree"` for code.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Paths are
relative to `frontend/src/` unless they start with `frontend/`, `docs/`, `scripts/`, `testdata/`
or `packages/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **A** | `components/video/advanced/**` except B's files below (the stub `AdvancedOptions.vue` is A's; keep its mounts of B's components), `components/editor/tabs/VideoTab.vue` (+ `VideoTab.test.ts`), `i18n/messages/en/advanced.json` | B's files, `stores/**` (use them), `components/base/**` (use them), `components/video/*.{vue,ts}` outside `advanced/` except where 0068 Task A records why |
| **B** | `components/video/advanced/CustomParams.vue`, `components/video/advanced/CopyHdrMetadata.vue` (the stubs are B's), their tests (`CustomParams*.test.ts`, `CopyHdrMetadata*.test.ts`), `components/video/advanced/useParamsCheck.ts` (+ test) if it needs one, `i18n/messages/en/params.json` | every other file of `components/video/**`, `VideoTab.vue`, `stores/**` (use them), `components/filters/**` (reuse by import, do not move) |

**Lead-owned**: `frontend/package.json`, `frontend/package-lock.json`, `api/**`, `router/**`,
`components/editor/tabs/registry.ts`, `i18n/index.ts`, `i18n/messages/en/{app,video}.json`,
`setup.ts`, `main.ts`, `notBuilt.ts`, `App.vue`, `stores/**`, `views/**`, `composables/**`,
`editor/**`, `platform/**`, `components/base/**`, `frontend/vite.config.ts`, the tsconfigs,
`frontend/playwright.config.ts`, `frontend/e2e/**`, `scripts/dev-server.py`, `packages/**`. An
agent that needs another dependency, a route, a store member or a change of these files asks the
lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own sentence of the F-9 row (A: the panel; B:
  custom parameters and Copy HDR metadata), each in its own sentence.
- `docs/decisions/0068-m9-advanced-options.md`: each task writes only its own section ("Task X").
- `docs/plan/06-web-app.md`: A ticks the F-9 `AdvancedOptions` box once B is in it (the lead
  checks), and a task edits its step's text only together with a decision (its 0068 section).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. A task may add members, optional props with defaults, files and components in its own
folders, but not change these.

### Mounts (lead; in place)

- `VideoTab.vue` (A from now on) has the collapsible section *Advanced options*
  (`data-section="advanced"`, title `advanced.title`) after *Encoder settings*; it is open while
  `ui.advancedOpen` is `true` and mounts `components/video/advanced/AdvancedOptions.vue` (A) only
  then. The read-only custom parameters field is gone from *Encoder settings* (B's field replaces
  it).
- `AdvancedOptions.vue` (A) mounts `CopyHdrMetadata.vue` (B) in the *HDR / colour* category (above
  its options, while that category is shown) and `CustomParams.vue` (B) as the content of the
  *Custom parameters* category, the last one. In a search, A shows `CustomParams` when the query
  matches the category's name; *Show only changed* keeps it while `video.custom_params` is not
  empty.
- `CustomParams.vue` and `CopyHdrMetadata.vue` take no props and emit nothing: they read and edit
  the open job through the editor store. `CustomParams` renders a `Field` with
  `path="video.custom_params"` (so a reveal of that path focuses it).

### The UI store (lead, done)

`ui.advancedOpen: Ref<boolean>`: the panel is open, for the page (across tabs and jobs; `false`
at start). `ui.reveal(path)` sets it to `true` for `video.advanced.<key>` and
`video.custom_params`; A's panel then shows that option (selects its category, clears a search or
*Show only changed* that hides it) so that its `Field` (`path="video.advanced.<key>"`) reveals
itself through `useReveal`.

### The job, the editor and validation (done)

- `video.advanced: Record<string, boolean | number | string>`: only changed options, by key
  (`VideoSettings.advanced`). A key that is present is a changed option (0068 item 2). Write with
  `editor.set('/video/advanced/<key>', value)` / `editor.patch([...])` (one undo step each; a
  drag or a typing run with `{ coalesce }` then `editor.endCoalescing()`); reset with a `remove`
  op. A key with `/` or `~` is escaped as a JSON pointer (`~1`, `~0`).
- `video.custom_params: string` (`''` = none).
- `useValidation` (`jobs/validate` 250 ms after an edit) puts the option rules' issues at
  `video.advanced.<key>` (`encoder.option_invalid`, `encoder.option_unknown`,
  `encoder.option_inactive`, `encoder.lookahead_too_short`, …) and the custom-parameter file rule
  at `video.custom_params` (`encoder.custom_param_file`); `Field` shows them by `path`. Validation
  does not dry-run: an unknown or refused custom parameter (`encoder.custom_param_rejected`) comes
  only from `POST /api/jobs/dry-run` (0068 Context).
- `CommandPreview` (done, M4) asks `jobs/plan` 250 ms after the last edit while the drawer is open
  (`EDIT_DEBOUNCE`, newest answer only); the drawer is sticky at the tab's foot.

### Types (`api/types.ts`, lead, done)

`EncoderOption` (`Schemas['EncoderOption']`: `key`, `label`, `category`, `type` (`int` · `float` ·
`bool` · `enum` · `string`), `min`, `max`, `step`, `choices`, `default` (`{kind: 'fixed', value}`
· `{kind: 'preset', values: {preset: value}, tunes: [...]}` · `{kind: 'encoder', note}`), `help`,
`mapping` (`x26x_param` · `ffmpeg_arg` · `private_opt`, with the CLI `name`), `requires`,
`unit`). A video encoder's definition (`system.definitions.video_encoders[id]`) has `options:
EncoderOption[]` in definition order and `presets` (a `ChoiceSetting`: the speed presets and
their `default`).

### Routes (all there; 0068 Context)

`GET /api/definitions/encoders/{id}/options?q=` (the option search: label, key, CLI name, help;
best match first; `404 definitions.unknown_encoder`), `POST /api/jobs/hdr-metadata {job}` (a JSON
patch on the job: `add` ops at `/video/advanced/<key>`; `[]` when the source has no HDR metadata
or the encoder has no such options), `POST /api/jobs/dry-run {job}` (`ValidationIssue[]`;
`error`s at `video.custom_params`; `422 jobs.invalid` for an output outside the roots),
`POST /api/jobs/plan`, `POST /api/jobs/validate`. Calls go through `@/api/client` (`api` /
`apiQuiet`, `unwrap`); a request that keeps changing uses `editor/latest.ts` `latestRequest`.

### i18n

As M6–M8: `i18n/messages/en/<area>.json` holds the keys of `<area>.`. New areas: `advanced` (A;
`advanced.title` is there), `params` (B; empty). Option labels, help texts, choice labels and the
`encoder` default's note come from the definitions as they are (English data, as the encoder and
filter help of M4 and M8); the category names are A's keys (`advanced.category.*`).

## Done when (word for word in each agent's brief)

Every "in a browser" check runs headless against a real `reframe-server` started with
`scripts/dev-server.py` and the pinned FFmpeg, with the fixtures `hdr10` and `multitrack`, in
light and dark, with screenshots read by the agent.

- **A (F-9)**: 06 §F-9: "`AdvancedOptions` is generated from the option schema: categories,
  search, "show only changed", reset, placeholders for defaults, help popovers, "copy HDR
  metadata"." 03 §Video: "**Advanced…** opens the [advanced options](#advanced-encoder-options)."
  03 §Advanced encoder options: "**Changed values** are highlighted. Each has a reset button ↺.
  Each category shows a count of changed options." "The **default** of an option shows as
  placeholder text. If the default depends on the speed preset, the placeholder says so (x264 and
  x265 preset tables ship with the core)." "**ⓘ** opens help: what the option does, its typical
  range, and the quality/speed effect." "**Search** covers labels, CLI names and help text across
  all categories." 08 §M9 demo: "x265 advanced panel: search "psy" finds psy-rd and psy-rdoq.
  Changing b-frames highlights the field and the category count, and the command preview updates
  at once." In a browser on `hdr10` with an x265 preset: the categories in panel order with their
  counts; "psy" lists psy-rd and psy-rdoq (and only matches), a CLI name (`rc-lookahead`) and a
  word of a help text find their option, clearing the search brings the category view back;
  B-frames set to 6 highlights its row, *Frame types / GOP* shows 1, the drawer's command holds
  `bframes=6` without any other action, ↺ takes it out (count 0, `bframes` gone from the
  command), and `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo it; the B-frames placeholder names the
  preset's value and the preset (and changes when the speed preset changes), an
  encoder-decided default says so; *Show only changed* shows only changed options; every option
  type (int, float, bool, enum, string) can be set and reset; ⓘ shows the help; a validation
  issue of an option shows at its row, and revealing it from Summary opens the panel at the
  option; the panel with SVT-AV1, an NVENC encoder (not available here: the panel still shows its
  schema) and VP9; passthrough disables the controls; a group's override dot and *Reset to group*
  on an option; the keyboard alone reaches every control; it fits the column at 1920, 1440, 1280
  and 1024 px; light and dark.
- **B (F-9)**: 03 §Advanced encoder options: "**Custom parameters**: a free-form `key=value:…`
  field, appended last and validated by a dry run (`-frames:v 1 -f null`)." "A parameter the
  encoder refuses, or only logs and skips (x264, x265, SVT-AV1 and libvpx's codec controls do
  that), is a validation error from the dry run" "A parameter that makes the encoder or FFmpeg
  read or write a file (x265 `csv` / `analysis-save`, x264 `dump-yuv` / `stats`, `pass`,
  FFmpeg's `vstats_file` …) is a validation error" "**Copy HDR metadata from source** fills
  master-display and MaxCLL/MaxFALL from the probe (x265 `master-display` / `max-cll`, SVT-AV1
  `mastering-display` / `content-light`; the hardware encoders take it from the frames)." 08 §M9
  demo: ""Copy HDR metadata" fills master-display and MaxCLL on an HDR10 fixture. An unsupported
  custom parameter shows a validation error from the dry run." In a browser on `hdr10` with an
  x265 preset: typing `nosuchparam=1` shows FFmpeg's refusal at the field once the typing stops
  (only the newest text's answer), `psy-rd=2.0` shows none, `csv=out.csv` shows the file rule;
  the typed text reaches the command; a typing run is one undo step; *Copy HDR metadata* sets
  `master-display` and `max-cll` (one undo step; the command holds them); with SVT-AV1 it sets
  `mastering-display` and `content-light`; on `multitrack` (SDR) and with an encoder that takes
  HDR metadata from the frames it says why nothing was copied; a failed request shows its error;
  keyboard alone; light and dark. A real-server test (`npm run test:server`) for the dry-run error
  and the HDR copy on `hdr10`.

## The M9 demo (the acceptance test; the lead runs it at the end)

08 §M9, on `hdr10` with an x265 preset: x265 advanced panel: search "psy" finds psy-rd and
psy-rdoq. Changing b-frames highlights the field and the category count, and the command preview
updates at once. **Copy HDR metadata** fills master-display and MaxCLL on an HDR10 fixture. An
unsupported custom parameter shows a validation error from the dry run. First headless
(Playwright, Chromium light and dark, Firefox light and dark, the screenshots read), then once
headed by the lead on `HDMI-A-1` through the guard.

## Commands

As [m6-breakdown.md](m6-breakdown.md#commands). The fixtures:
`scripts/dev-server.py --fixtures hdr10,multitrack`.

**Ports** (rule 7): agent N uses 87N0 to 87N9; 8750 and 8751 belong to `npm run e2e`. A 871x,
B 872x, R1 873x, R2 874x, the lead 876x, the fix agents 877x, 878x, 879x.

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
  it builds and the ones it uses, its "Done when" word for word, its section of 0068,
  rules 5, 6 and 7 and the test rules word for word, its port range.
- Setup: the worktree starts at `main`: first `git merge --ff-only m9-advanced-options`. Then
  `uv sync`, `npm ci` in `frontend/`, and
  `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (`--tools-dir` of `scripts/dev-server.py`); `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not
  installed.
- Commits per step, step ID first (`F-9: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Update only its own
  `docs/status.md` row.
- The report: the real output of every command of rule 5 (the last lines), what the agent saw
  in its screenshots (light and dark), the test rules' checks, every deviation from the plan
  and from this file, every file touched outside its list, and what later tasks need.

### Simple code (the owner's rule, word for word in each brief)

- Build what the plan says and nothing more: no extra options, settings, modes or "might need later"
  hooks. Smallest change that makes the "Done when" lines pass.
- Look before you write: reuse the existing components, stores, API layer and helpers
  (`Field`, `Section`, `ChoiceSelect`, `EncoderPicker`, `CommandPreview`, `latestRequest`, `useCustomCheck`'s pattern, the editor store and its undo, and so on).
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

### Changes for M9 (binding, with the rules above)

- The worktree starts at `main`: every agent first runs `git merge --ff-only m9-advanced-options`.
- Commits start with the step ID (`F-9: …`) and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Stage files by name.
- Each agent updates only its own sentence of its `docs/status.md` row and writes only its own
  section of 0068.
- Scratch files: each agent keeps its scratch files (server logs, ready lines, scripts,
  screenshots) in its own `scratchpad/task-<x>/` and reads a server's URL and token only from
  the ready line of a server it started itself.
- Nothing in a test or a check writes to a media file outside the temp folders; queued jobs
  write only into the dev server's output root.
- The report starts with the agent's model ID.
## Progress

| Date | What |
|------|------|
| 2026-11-02 | **Wave 0.** Branch `m9-advanced-options` from `main` 7fbda7c. API check against a real server with the pinned FFmpeg (0068 Context): every route the panel needs is there; no server task. The lead built the skeleton (`EncoderOption`, `ui.advancedOpen` and the reveal that opens it (+ `stores/ui.test.ts`; a mutation without the open fails it), the collapsible *Advanced options* section in the Video tab with the stubs, the read-only custom parameters field removed), this file, 0068 with placeholders |
| 2026-11-02 | **Wave 1 launched**: A (871x), B (872x), each `opus` / `high` in its own worktree. B stops after phase 1 and is resumed for its checks in A's panel after A merges. Briefs in the lead's scratchpad `briefs/` |
