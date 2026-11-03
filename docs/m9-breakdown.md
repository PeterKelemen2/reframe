# M9 task breakdown

Working notes of the lead for the branch `m9-advanced-options`: milestone M9, advanced encoder
options. The plan ([plan/08-roadmap.md](plan/08-roadmap.md) §M9, [plan/03-features.md](plan/03-features.md)
§Video and §Advanced encoder options, [plan/06-web-app.md](plan/06-web-app.md) §S-2 (Definitions,
Jobs) and §F-9) is the spec; this file says who builds which part, in which order, and what each
part must offer to the others. Decision: [0068](decisions/0068-m9-advanced-options.md) (the
lead's choices and one section per task). Status: [status.md](status.md). The template is
[m8-breakdown.md](m8-breakdown.md). If the lead's context is summarised, this file and
`status.md` are the source of truth. M9 is done on Linux on the branch `m9-advanced-options`
(2026-11-03); it is not merged into `main` and not pushed: the owner decides.

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

## Fix round (binding for the fix agents)

The two reviews (R1: 2 blockers, 2 majors, 3 minors, 1 nit; R2: 1 blocker (R1's), 2 majors, 7
minors, 5 nits) and the lead's L1, L2: 0068 "Review, 2026-11-02" (read it; its decisions 10–13
are binding). The lead reproduced every blocker and major and fixed R1-m2 / R2-m3 (80ff653).
Three fix tasks with disjoint files, each `opus` / `high`. A fix of a blocker or major comes with
a test that fails before it. Each task writes its own subsection "Fix round — FX" in 0068.

| Task | Findings | Owns |
|------|----------|------|
| **FA** panel, focus, layout | R1-M1 and R1-m3 (decimals; a blur that did not change the text writes nothing), R2-M1 (focus never under the drawer: `scroll-padding-bottom` of the tab's scroller follows the drawer's height) with L1 (the open drawer takes at most about 40 % of the tab's height; its command scrolls inside it), R2-M2 (the focus stays in the panel when its row goes), R1-n1 / R2-m2 (the search status), R2-m1, R2-m5 (category, search and *Show only changed* kept for the page), R2-m6 (`Field`'s ⓘ popover: named, not modal, `aria-controls`), R2-m7 (the selected category also by a mark of at least 3:1), the nits (the custom category without a heading that repeats the label; the help and its "Command line" as one i18n message; the "default" line in the control's `aria-describedby`; one reset style), L2 | `components/video/advanced/**` except FB's files, `components/editor/tabs/VideoTab.vue` (+ test), `components/shell/EditorTabs.vue` (+ test), `components/video/CommandPreview.vue` (+ test), `components/base/Field.vue` (+ test; the popover only), `i18n/messages/en/advanced.json` |
| **FB** Copy HDR, custom parameters | R1-B1 (decision 12: off in a group, with its note), R1-m1 (an answer for a job whose encoder or shown file changed is dropped), R2-m4 (a dry-run refusal is announced: a live region), the nit (the copy's note names the rows' labels, not CLI keys, without a built-up list) | `components/video/advanced/{CustomParams,CopyHdrMetadata}.vue`, `useParamsCheck.ts`, their tests, `i18n/messages/en/params.json` |
| **FC** core | R1-B2 / R2-B1 (decisions 10 and 11), R1-M2 (decision 13) | `packages/reframe/**` (the built-in presets' data, validation, the definitions' notes, their tests), `testdata/README.md` (its own heading); runs the frontend checks too |

FA, FB and FC do not depend on each other: the override issue of FC shows at the option's row
through `Field` (by path), with no frontend change. Merge order: FC, FB, FA. Ports: FA 878x, FB
879x, FC 877x.

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
| 2026-11-02 | **Merged A** (f8050b7; f90105b, ea763cf): `AdvancedOptions`, `OptionRow`, `options.ts`, `useOptionSearch.ts`; 29 checks in Chromium and Firefox, light and dark; views of SVT-AV1, NVENC, VP9; group override; 35 mutations caught. 1808 unit tests, lint, typecheck. The lead's mutation (the default text reads the encoder's default preset before the job's) fails 7 tests; restored, touched. Worktree removed. A's observation: with the panel closed, the Video tab already overflows its column by 5 px at 1280 and 253 px at 1024 (the column is 228 px there; `Field`'s inline layout and the M4 controls), for R2. **B phase 1 reported** (51dcd30): both components and tests; real-server tests drive `useParamsCheck` and the store in Node, because in jsdom Vite rewrites `devServer.mjs`'s `new URL('../../../../', import.meta.url)` (a lead-owned file); B resumed for phase 2 |
| 2026-11-02 | **Merged B** (f447955; 57635ff, 51dcd30, merge 43c490a, ffa09d0): `CustomParams`, `useParamsCheck`, `CopyHdrMetadata`; phase 2 inside A's panel, 15 checks in Chromium and Firefox, light and dark (the copy's rows highlighted and *HDR / colour* 0 → 2, one undo step; the dry-run error above the drawer; the reveal of `video.custom_params`). 1826 unit tests, lint, typecheck. The lead's mutation (an emptied text keeps the waiting check) fails `CustomParams.test.ts`; restored, touched. Worktree removed. B found that a reveal focused a field's ⓘ button rather than its control (its field shows the help as a line now); **the lead fixed `useReveal`** (the field's control first; a test in `Field.test.ts` that failed before) |
| 2026-11-02 | **Reviews R1 and R2 launched** (873x, 874x; `opus` / `high`, fresh, worktrees) on 96b456c. Briefs in the lead's scratchpad `briefs/R1.md`, `R2.md` |
| 2026-11-02 | **R1 and R2 reported** (`claude-opus-5-5` each); every blocker and major reproduced by the lead (0068 "Review, 2026-11-02"; `lead/r1repro/`, `lead/r2repro/`): R1-B1 (Copy HDR in a group), R1-B2 = R2-B1 (built-in presets' custom parameters win over the panel; x265 last-wins checked with the pinned FFmpeg), R1-M1, R1-M2, R2-M1 (20 of 22 focus stops under the drawer), R2-M2 (focus to `<body>`). The lead fixed R1-m2 / R2-m3 (80ff653: Ctrl+Z in a number field). Fix round planned (section "Fix round"; 0068 decisions 10–13) |
| 2026-11-02 | **Fix round launched**: FC (877x, core), FB (879x), FA (878x), each `opus` / `high` in its own worktree from d79c856. The reviewers' worktrees removed (no commits; their repros copied into the lead's scratchpad) |
| 2026-11-02 | **Merged FB** (add10f1; a9f17f6): R1-B1 (Copy HDR off in a group with its note; on the real `HDR.Show.S01` group E02 keeps `max-cll=500,100`), R1-m1 (answers dropped after an encoder or shown-file change, also in `useParamsCheck`), R2-m4 (the status line always rendered, a refusal announced), the copy's note by the rows' labels; 8 tests failed before the fix; 13 mutations caught. Video unit tests 130, lint, typecheck. The lead's mutation (`inGroup` always false) fails `CopyHdrMetadata.test.ts`; restored, touched. Worktree removed. Recorded: the hardware encoders have no *HDR / colour* category, so their "takes it from the frames" note is reached only in the unit test (no button is offered for them) |
| 2026-11-02 | **Merged FA** (9f5ab94; 7480606): R1-M1 / R1-m3 (10 decimals, a pass through an unchanged field writes nothing), R2-M1 / L1 (the drawer publishes its height; the tab's scroll padding follows it; the open drawer at most `40cqh`; `tab.mjs` 0 of 22 under the drawer), R2-M2 (focus to the category or the search), the search status, R2-m1, R2-m5 (`advanced/view.ts`), R2-m6 (`Field`: `aria-controls`, not modal, named; a new optional prop `description`, accepted by the lead), R2-m7, the nits, L2; 14 tests failed before; 14 mutations caught. The `status.md` F-9 row resolved (FA's sentence after FB's). 1848 unit tests, lint, format, typecheck. The lead's mutation (the unchanged-text check inverted) fails 2 tests; restored, touched. Worktree removed |
| 2026-11-02 | **Merged FC** (436370a; a373d5e): the ten built-in presets set their options in `video.advanced` (only SVT-AV1 `keyint=10s` stays a custom parameter, with the info); `encoder.custom_param_overrides` (warning with the panel's value, info without; x264 / x265 / SVT-AV1 by the key forms, the other encoders by the private or generic option); the HDR notes; 42 of 52 built-in plans identical, the other 10 differ only in how a value is written (`4.0` → `4`, `b-pyramid` `0` → `none`, a passlog path), and the x264 / x265 settings SEI is identical to HandBrake's strings; 14 mutations. FB's `CopyHdrMetadata.server.test.ts` expected the preset's job without options: fixed by the lead (32ec4b2). The lead's mutation (the warning branch as info) fails `test_custom_params_rules.py`; restored, touched. No worktree left |
| 2026-11-03 | **Every blocker and major re-run on the merged branch** (0068 "Re-run of the repros"): all show the fix. **Final checks, run alone on Linux**: Python `pytest -m "not needs_gpu"` in four chunks 1777 + 2391 + 2664 + 824 = **7656 passed**, 2 skipped, 26 deselected; ruff, ruff format, mypy, mypy `--platform win32` clean; `gen-api.sh --check` up to date; `npm run lint`, `fmt:check`, `typecheck` clean; `npm test` 1848 passed; `build:web` built; `npm run test:server` 67 passed; `npm run e2e` 22 passed (43.2 s), no server and no `/tmp/reframe-dev-*` left |
| 2026-11-03 | **M9 demo, headless** (Chromium light and dark, Firefox light and dark, 9 of 9 each) and **headed** once in Chromium on `HDMI-A-1` through the window guard after the owner placed the cursor and the active window there (9 of 9; nothing on `DP-1`): 0068 "M9 demo". **Docs reconciled**: `status.md` (the M9 row Done on Linux, not merged; F-9 Done; the feature row), 06 §F-9's box ticked, 0068 Plan changes, this section and "Where M9 ended". **Not merged into `main`, not pushed** |

## Where M9 ended (2026-11-03)

M9 is done on Linux on the branch `m9-advanced-options` (from `main` 7fbda7c); not merged into
`main`, not pushed. Built: A (`AdvancedOptions`, `OptionRow`, the option search, the default
texts), B (`CustomParams` with the dry run, `CopyHdrMetadata`), the lead's skeleton
(`ui.advancedOpen`, the reveal that opens the panel), and from the review FA (decimals, focus,
the drawer's height and scroll padding, the search status, the panel's state for the page, `Field`'s
help popup), FB (no copy in a group, stale answers, the live dry-run result), FC (the built-in
presets' options in `video.advanced`, `encoder.custom_param_overrides`, the HDR notes) and the
lead's two fixes (a reveal focuses the control; Ctrl+Z in a number field undoes the editor).

| Check (alone, Linux, 2026-11-03) | Result |
|-------|--------|
| `npm test` | 1848 passed |
| `npm run test:server` | 67 passed |
| `npm run e2e` | 22 passed |
| Python `pytest -m "not needs_gpu"` | 7656 passed, 2 skipped, 26 deselected |
| lint, format, typecheck, `build:web`, `gen-api.sh --check`, ruff, ruff format, mypy ×2 | clean |
| M9 demo | headless 4 × 9 of 9; headed (Chromium, `HDMI-A-1`) 9 of 9 |

1. **Recorded, not fixed**:
   - a custom parameter FFmpeg refuses shows at the field (the dry run) only: `jobs/validate` and
     *Add to queue* do not dry-run, so such a job can be queued and fails at the encode (as M8's
     L2);
   - switching the encoder keeps an option whose key the new encoder also has (x265 `aq-mode` →
     SVT-AV1 `aq-mode`), although the values mean different things there (M4's
     `switchEncoderOps` rule; seen more often now that the built-in presets set options);
   - a user preset saved from an old built-in keeps its custom parameters; its rows show the
     override issue (no migration);
   - the hardware encoders have no *HDR / colour* category, so *Copy HDR metadata* is not offered
     for them and its "takes it from the frames" note is reached only in a unit test;
   - with the preview panel open, the Video tab overflows its column by 5 px at 1280 px and by
     253 px at 1024 px (M4's controls; the advanced panel adds none);
   - each ArrowUp in a number field is its own undo step (as every number field of the app); an
     issue of an option in another category has no mark in the category list; Firefox makes the
     drawer's scrolling command a Tab stop; Ctrl+Z inside a text option undoes one character in
     Chromium and the whole run in Firefox;
   - no real-server test of the group case of *Copy HDR metadata* (the two-episode HDR group is
     not a fixture of `scripts/make-testdata.py`; checked by hand, 0068).
2. **Not built**: a dry run in validation or at *Add to queue*; a fix that moves a custom
   parameter into the panel; the M8 open items (the Range selector and the rest of m8-breakdown
   "Where M8 ended").
3. **Owner questions**, with their defaults kept:
   - a dry run in `jobs/validate` / at *Add to queue* for custom parameters (and M8's custom
     filter)? Default: not;
   - keep options with the same key when the encoder changes, or drop them across encoder
     families? Default: kept (M4's rule);
   - *Copy HDR metadata* for a single job writes what the command already writes from the source
     (it makes the values visible and editable): keep the button? Default: kept (03);
   - migrate user presets' custom parameters into `video.advanced`? Default: not;
   - the built-in presets' options now show as changed (highlighted and counted) in the panel:
     wanted? Default: yes (0068 items 2 and 10);
   - "the command preview updates at once" is the drawer's next answer, 250 ms after the edit
     (measured 328–331 ms); the panel is an inline section of the Video tab, not a dialog (0068
     items 1 and 3).
4. **Not verified**: Windows and GitHub CI (nothing pushed); WebKit (M10).

