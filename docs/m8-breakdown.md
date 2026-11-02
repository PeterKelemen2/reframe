# M8 task breakdown

Working notes of the lead for the branch `m8-picture`: milestone M8, picture (preview, crop,
filters). The plan ([plan/08-roadmap.md](plan/08-roadmap.md) §M8, [plan/03-features.md](plan/03-features.md)
§App layout, §Dimensions, §Filters, §Preview, §Settings, [plan/06-web-app.md](plan/06-web-app.md)
§S-2 (Preview, `jobs/geometry`), §F-7, §F-8, §F-15, §F-17) is the spec; this file says who builds
which part, in which order, and what each part must offer to the others. Decision:
[0067](decisions/0067-m8-picture.md) (the lead's choices and one section per task). Status:
[status.md](status.md). The template is [m7-breakdown.md](m7-breakdown.md). If the lead's
context is summarised, this file and `status.md` are the source of truth.

M8's core part (C-5, C-10, [0033](decisions/0033-preview-frames-crop-and-clips.md)) and the
preview routes ([0049](decisions/0049-s2-system-fs-settings-sources-preview.md)) are done and
merged. M8 builds the UI on them. The branch starts from `m7-batch-season` (d3c2467), which is
not merged into `main` yet. The lead's wave-0 check found one missing route (frames of a clip)
and two gaps (nothing writes a detected crop into a job; a detected crop marked the job
*modified*); the lead closed them in wave 0 (0067 items 1–3).

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| A | F-7 | The preview store (the strip of the shown file, the current frame, seek, the output frame of the job, view modes, zoom, the pointer), the preview panel (follows the tab; `←` / `→`), `FrameViewer` (fit / 100 % / 200 %, the strip, the timestamp seek, Source · Output · Split slider · Side by side, the overlay layer), `SplitCompare` | 06 §F-7; 03 §App layout, §Preview; 0067 items 5–7 |
| B | F-7 | The crop store (`jobs/geometry`, the crop, its detection and the `amend` of 0067 item 3, snapping to the chroma grid), the Dimensions tab (pipeline header, orientation, crop with its modes and the detection line, output size, the collapsed advanced part), `CropOverlay` (the removed area, the crop lines, drag handles and arrow keys) | 06 §F-7; 03 §Dimensions; 0009; 0067 items 3, 8 |
| C | F-7 | `CropMagnifier` (four edge strips at 2× / 4× / 8×, the tint, the crop lines at the pixel boundary, the pixel grid, the frame navigation), `CropLoupe`, `CropCheckGrid` (every sample with the overlay and its detected bars; a Web Worker computes the luma variance of the removed band; a warning badge) | 06 §F-7; 03 §Dimensions → Crop magnifier; 0001 (F-7 magnifier rules); 0067 item 8 |
| D | F-8 | The Filters tab: the filter list (toggle, implementation, preset, tune, custom), the help panel from the definitions, the Colorspace source colour box and the "what will happen" sentence with *Enable tone mapping*; the panel's split before / after on Filters (A's) | 06 §F-8; 03 §Filters |
| E | F-15, F-7 | Settings → Preview (sample frames, cache size limit, the cache size, clear cache); the live preview clip in the panel (10 / 15 / 30 / 60 s from the current frame, the task with progress and cancel, the player, the encoded frame compare, *Open in external player*) | 06 §F-15; 03 §Preview, §Settings; 0067 items 1, 4 |
| F | F-17 | Flow 4 (Playwright) | 06 §F-17 |

**Out of scope** (do not start): M5 and every `D-x` (the detached preview window too), the F-9
advanced panel (M9), F-16, the Windows run and the WebKit run of M10. **Not built, recorded**
(no step of M8 gives them): the Range selector (03 §App layout's source header), burned-in
subtitles on output frames (0033 §4; a clip shows them), crop detection for files that are never
shown in the editor (0067 Consequences).

Defaults the lead took where the plan leaves a choice: 0067 items 1–8 (read them; they are
binding).

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: this file, 0067, the clip-frames route, the preset diff change, `editor.amend`, the skeleton (type aliases, `stores/preview.ts` and `stores/crop.ts` as stubs, component stubs mounted in `PreviewPanel`, `FrameViewer`, the tab registry and `SettingsView`; the workspace starts the crop store; the panel shown by default) | `m7-batch-season` (d3c2467) |
| 1 | A, B, C, D | the skeleton |
| 2 | E (once A is merged); B and C resumed for their checks in a browser | A merged (C: B too) |
| 3 | F | wave 2 merged |
| 4 | two fresh reviews (R1: state, crop maths and coordinates, the worker, server calls, undo / redo, stale or cancelled preview requests; R2: screens, i18n, keyboard paths for the crop handles, focus, light and dark contrast, empty and error states; both also flag code more complicated than it needs to be), the fixes, the M8 demo headless (Chromium, Firefox, light and dark) and once headed by the lead, the docs | wave 3 merged |

A has no dependency. B codes against A's stub (its overlay sits in A's layer); C against A's and
B's; D needs neither for its tab (the split on Filters is A's). B, C and D do phase 1 (unit
tests against the stubs) and stop; the lead resumes each with SendMessage for its browser checks
after the stores it uses are merged. Merge order: A, B, C; D after A. At most four worktrees at a
time. The lead merges each task with `--no-ff`, runs the frontend commands, mutates once per task,
and removes the worktree and its branch.

Every agent: `model: "opus"`, `effort: "high"` (the owner's rule for this run; never `xhigh`),
`isolation: "worktree"` for code.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A
change anywhere else goes back to the lead (say so in the report; do not make it). Paths are
relative to `frontend/src/` unless they start with `frontend/`, `docs/`, `scripts/`, `testdata/`
or `packages/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **A** | `stores/preview.ts` (+ tests `preview*.test.ts`), `components/shell/PreviewPanel.vue` (keep its mounts), `components/media/FrameViewer.vue`, `components/media/SplitCompare.vue` (+ tests), new `components/preview/**`, `i18n/messages/en/preview.json` (new), the `shell.preview.*` keys of `i18n/messages/en/shell.json` | `stores/crop.ts`, `components/{dimensions,crop,filters,clip}/**`, the tabs |
| **B** | `stores/crop.ts` (+ tests `crop*.test.ts`), `components/editor/tabs/DimensionsTab.vue` (+ test), new `components/dimensions/**` (the stub `CropOverlay.vue` is its), `i18n/messages/en/dimensions.json` (new) | `stores/preview.ts`, `stores/editor.ts` (use it), `components/{media,crop,summary}/**` (use them) |
| **C** | `components/crop/**` (the stubs `CropMagnifier.vue`, `CropLoupe.vue` are its; the worker and its pure helpers), `i18n/messages/en/crop.json` (new) | `stores/**` (use them), `components/{media,dimensions}/**` |
| **D** | `components/editor/tabs/FiltersTab.vue` (+ test), new `components/filters/**`, `i18n/messages/en/filters.json` (new) | `stores/**` (use them), `components/{media,summary}/**` (use them) |
| **E** | `components/settings/PreviewSection.vue` (+ test), `components/clip/**` (the stub `PreviewClip.vue` is its), `i18n/messages/en/clip.json` (new), the `settings.preview.*` keys of `i18n/messages/en/settings.json` | `stores/**` (use them), `components/{media,shell}/**` (use them), `views/**` |
| **F** | `frontend/e2e/**` except `frontend/e2e/layout.spec.ts` and `frontend/playwright.config.ts` | every file of `src/`, `frontend/package.json` |

**Lead-owned**: `frontend/package.json`, `frontend/package-lock.json`, `api/**`, `router/**`,
`components/editor/tabs/registry.ts`, `i18n/index.ts`, `i18n/messages/en/app.json`, `setup.ts`,
`main.ts`, `notBuilt.ts`, `App.vue`, `stores/{editor,toasts,ui,validation,presets,queue,settings,sources,system,tasks}.ts`,
`views/**`, `composables/**`, `editor/**`, `platform/**`, `frontend/vite.config.ts`, the
tsconfigs, `frontend/playwright.config.ts`, `scripts/dev-server.py`, `packages/**`. An agent that
needs another dependency, a route, a registry entry or a change of these files asks the lead.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own sentence of its step's row (A, B, C: their
  parts of F-7, each in its own sentence; D: F-8; E: F-15's Preview and the clip's sentence in
  F-7; F: F-17).
- `docs/decisions/0067-m8-picture.md`: each task writes only its own section ("Task X").
- `docs/plan/06-web-app.md`: a task ticks its own step's boxes, and edits its step's text only
  together with a decision (its 0067 section).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Contracts

Binding. The signatures are in the skeleton's files (read them; they are the source); this is
their summary. A task may add members, optional parameters with defaults, files and
components in its own folders, but not change these. `notBuilt(…)` marks a stub: replace it,
and remove the `oxlint-disable` / `oxlint-enable` lines around the stubs you build.

### The preview store (`stores/preview.ts`; A builds; B, C, D, E use)

```ts
type ViewMode = 'source' | 'output' | 'split' | 'side'
type Zoom = 'fit' | 1 | 2                         // 1 and 2: CSS pixels per source pixel
interface SourcePoint { x: number; y: number }    // source picture pixels, from the top left

sourceId: ComputedRef<string | null>   // the editor's shown file
strip: ShallowRef<FrameLink[]>         // the shown file's sample frames (Settings → Preview's count), timestamp order
notes, loading, error                  // of the strip's answer
index: Ref<number | null>              // the strip frame shown; null after a seek between them
current: ComputedRef<FrameLink | null> // the source frame shown
output: ShallowRef<FrameLink | null>   // preview/render of the editor's job at current's time; null while on its way or out of date
rendering, renderError
viewMode: Ref<ViewMode>; zoom: Ref<Zoom>
pointer: Ref<SourcePoint | null>       // the pointer over the shown source picture
select(at: number): void; step(delta: 1 | -1): void; seek(seconds): Promise<void>; reload(): Promise<void>
```

The strip is asked for whenever a file is shown (any tab; `count` left out, so the server uses
Settings → Preview's count, the same times as crop detection) and again when that setting
changes. The output frame is asked for only while the panel is open and its view mode needs one,
250 ms after the last edit of the job (`EDIT_DEBOUNCE`), the newest answer only, the older
request aborted (`editor/latest.ts` `latestRequest`). A frame URL expires after a few minutes: a
failed image load asks again. Another file aborts everything of the last one.

### The crop store (`stores/crop.ts`; B builds; A, C use)

```ts
type CropMode = CropSettings['mode']      // 'auto' | 'conservative' | 'none' | 'manual'
geometry: ShallowRef<JobGeometry | null>; geometryError   // jobs/geometry of the editor's job, newest answer (one request for every user)
mode: ComputedRef<CropMode | null>
rect: ComputedRef<CropRect | null>        // the crop the job applies, on the chroma grid; null: none / not detected / no job
sourceSize: ComputedRef<{ width; height } | null>   // the source picture as decoded
editable: ComputedRef<boolean>            // manual mode
detection: ShallowRef<CropDetection | null>; detecting; detectionError   // the shown file's, kept per file for the page
snapNote: Ref<string | null>
setRect(rect, options?: PatchOptions): void   // snaps down to the grid, clamps, mode manual; one undo step or a coalesced run
setMode(mode): Promise<void>                  // one undo step; auto / conservative take the detected rect (detects first)
detect(): Promise<CropDetection>              // again
```

Coordinates: a crop is measured on the source picture as FFmpeg decodes it (display matrix
applied, the job's rotation not yet; 0009 item 1), in source pixels; the frames are that
picture at full resolution. The store writes a detected rectangle with `editor.amend` (0067
item 3), and everything else with `editor.patch` / `set`. `useGeometry` (`components/summary/`)
is the request to reuse; the store calls it once.

### Mounts (lead; the stubs are in place)

- `PreviewPanel.vue` (A) mounts `components/media/FrameViewer.vue` (A) and
  `components/clip/PreviewClip.vue` (E).
- `FrameViewer.vue` (A) has an overlay layer: an element that covers exactly the shown source
  picture (so a percentage of its box is the same percentage of the source picture), in the
  Source view mode. It holds `components/dimensions/CropOverlay.vue` (B) and
  `components/crop/CropLoupe.vue` (C); A sets `preview.pointer` from pointer events on it. B and
  C decide when they show themselves (manual crop, the Dimensions tab) and position themselves
  in that box.
- `components/media/SplitCompare.vue` (A): props `before: FrameLink` (the source frame), `after:
  FrameLink` (an output frame or a clip's frame), `geometry: Geometry | null` (the source shown
  cropped, turned and flipped as the output is), `layout?: 'split' | 'side'`. A's view modes and
  E's frame compare use it.
- `components/editor/tabs/DimensionsTab.vue` (B) mounts `components/crop/CropMagnifier.vue`
  (C) under the crop inputs in manual mode (0067 item 8).
- `views/SettingsView.vue` mounts `components/settings/PreviewSection.vue` (E) as the section
  `preview` (title key `settings.preview.title`).
- `views/WorkspaceView.vue` starts the crop store (`useCropStore()`), so detection works on any
  tab; the panel is shown by default.

### The editor (lead, done)

`editor.amend(ops: JsonPatchOp[]): void`: a change of the open single job without an undo step
(it ends a coalescing run); nothing in a group.

### Types (`api/types.ts`, lead, done)

`FrameLink`, `Frames`, `JobGeometry`, `Geometry`, `SourceGeometry`, `CropRect`, `CropSettings`,
`DimensionSettings`, `FilterDef`, `FilterConfig`, `FilterSettings`, `PreviewSettings`,
`ColorInfo`, `HdrInfo`, `VideoStream`, and by hand (task results) `CropDetection`, `CropSample`,
`PreviewClip`.

### Routes (all there; 0067 Context)

`POST /api/preview/frames {source_id, count | timestamps}`, `POST /api/preview/render {job,
timestamp}` (the source and the output frame), `POST /api/preview/cropdetect {source_id}` → task
(`CropDetection`), `POST /api/preview/clip {job, start, seconds}` → task (`PreviewClip`),
`GET /api/preview/clips/{id}/link`, `POST /api/preview/clips/{id}/frames {timestamps}` (new),
`GET` / `DELETE /api/preview/cache`, `POST /api/jobs/geometry`, `POST /api/jobs/plan`,
`POST /api/jobs/dry-run`, Settings → Preview through `useSetting`. A task's progress and result:
`stores/tasks.ts` (`wait`, `cancel`).

### i18n

As M6 and M7: `i18n/messages/en/<area>.json` holds the keys of `<area>.`. New areas: `preview`
(A), `dimensions` (B), `crop` (C), `filters` (D), `clip` (E). A changes `shell.preview.*`; E adds
`settings.preview.*` (the title is there).

## Done when (word for word in each agent's brief)

Every "in a browser" check runs headless against a real `reframe-server` started with
`scripts/dev-server.py` and the pinned FFmpeg, with the fixtures `letterbox`, `hdr10`,
`hdr10-4k` and `multitrack`, in light and dark, with screenshots read by the agent.

- **A (F-7)**: 06 §F-7: "`FrameViewer`: fit/100 %/200 %, frame strip, timestamp seek, crop
  overlay with drag handles." (the handles are B's, in A's layer). 03 §Preview: "**Frame strip**:
  N evenly spaced frames (default 10, configurable), or seek to any timestamp." "**View modes**:
  Source · Output (crop + scale + filters, rendered by FFmpeg) · Split slider · Side by side.
  Zoom: fit / 100% / 200%." 03 §App layout: "It follows the active tab. On Dimensions it shows
  crop overlays. On Filters it shows before/after." and "`←/→` move through preview frames". In a
  browser: `letterbox` gives a strip of 10 frames; a click, `←` / `→` and a seek to 2.5 s show
  that frame; each view mode and zoom works; the output frame follows an edit 250 ms after it
  (only the newest answer is shown; an answer for an older job never replaces a newer one); a
  file change aborts the last file's requests (the server's frames task is cancelled); `hdr10-4k`
  shows its HDR note; an expired frame URL is asked for again; no file, a failed strip and a
  failed render each show their state; the keyboard alone reaches every control; light and dark.
- **B (F-7)**: 06 §F-7: "Pipeline header from `jobs/geometry`." 03 §Dimensions, "Done when: …
  Manual crop shows the magnifier. The pipeline header always matches the command that the
  builder makes." 08 §M8 demo point 2: "Automatic and conservative crop give different results
  on a fixture with changing aspect ratios." In a browser on `letterbox`: Automatic shows
  `Detected 22 / 24 / 0 / 0 on 5 of 10 frames`, Conservative `0 / 0 / 0 / 0` with the note that
  the frames disagree, each with its pipeline header; opening the file in automatic mode crops
  it without an undo step and without the *modified* marker; Manual takes typed values snapped
  to the grid with a note (`141 → 140`), and the drag handles and the arrow keys on a focused
  handle move one edge (a drag or a run of key presses is one undo step); orientation, output
  size and the advanced part change the header; the header turns amber for an upscale and red
  for an invalid value; in a group the shown file's detection is shown and not written; light
  and dark, keyboard alone. A real-server test (`npm run test:server`): for crop, rotation, flip,
  size and pixel-aspect cases, the header's values equal the `crop=` and `scale=` of `jobs/plan`.
- **C (F-7)**: 06 §F-7: "`CropMagnifier`: canvas-based. It loads the full-resolution PNG and
  draws 4 edge strips at 2×/4×/8× with `imageSmoothingEnabled = false`, a removed-area tint, the
  crop lines, and a cursor loupe." "`CropCheckGrid`: every sample with the overlay. A Web Worker
  computes the luma variance of the removed band and puts a warning badge on frames that lose
  content." 08 §M8 demo point 1: "Manual crop: the magnifier shows all four edges at 4×. **Check
  crop on all frames** marks a frame where the crop removes picture content." In a browser on
  `letterbox` with manual `22 / 24 / 0 / 0`: the four strips at 4× (the canvas pixels read back:
  the crop line on the pixel boundary, the removed rows tinted); 2× and 8×; the loupe follows the
  pointer; *Check crop on all frames* shows 10 frames with their detected bars, the five 4:3
  frames (2.2–3.8 s) with the warning badge and the five letterbox frames without; with manual
  `0 / 0 / 40 / 40` the opposite five; the worker runs off the main thread; keyboard alone; light
  and dark.
- **D (F-8)**: 06 §F-8: "Filter list (toggle + preset + tune), help panel from the definitions,
  `SplitCompare` before/after on the current frame (`preview/render`)." "Colorspace
  source-colour box and the "what will happen" sentence." 08 §M8 demo point 3: "Filters: each
  filter shows its help. The before/after split works. Colorspace on an HDR source suggests tone
  mapping, and the preview shows the result." In a browser: every filter of the definitions
  shows its help (what, use when, avoid when, speed cost, settings); a filter turned on, its
  implementation, preset and tune change the job (one undo step each) and the split's output
  frame; on `hdr10` the source colour box shows BT.2020 / PQ / HDR10 with the mastering display
  and MaxCLL, Colorspace BT.709 gives the sentence and *Enable tone mapping*, which turns tone
  mapping on and the split shows the mapped frame; the custom filter is checked; keyboard alone;
  light and dark.
- **E (F-15, F-7)**: 03 §Settings: "Preview | Number of sample frames, cache size limit, clear
  cache". 03 §Preview: "**Live preview clip** (HandBrake parity): encode 10 / 15 / 30 / 60 s
  from the current position with the full job settings. The clip plays in the built-in player if
  the webview can decode it. If not, **Open in external player**." "**Encoded frame compare**:
  FFmpeg decodes frames from the preview clip to PNG, and the split view shows them next to the
  matching source frame. This works for every codec, even when the webview cannot play the
  clip." 08 §M8 demo point 4: "Preview clip: plays in-app (H.264) or compares frames
  (HEVC/AV1)." In a browser: Settings → Preview's count changes the strip, the limit is saved,
  the cache size shows and *Clear cache* empties it; on `letterbox` an H.264 clip plays in
  Chromium and Firefox; an HEVC clip in Chromium falls back to the frame compare (0067 Context),
  and *Compare frames* works for every clip; progress and *Cancel* work; keyboard alone; light
  and dark.
- **F (F-17)**: 06 §F-17 flow 4: "Manual crop → magnifier shows the crop lines → the command
  contains the matching `crop=` filter." `npm run e2e` (headless Chromium and Firefox) passes
  flow 4 twice in a row next to flows 1, 2, 3 and the layout checks, and leaves no process and no
  temporary folder behind.

## The M8 demo (the acceptance test; the lead runs it at the end)

08 §M8, on `letterbox` and `hdr10`: (1) manual crop `22 / 24 / 0 / 0` → the magnifier shows all
four edges at 4× → *Check crop on all frames* marks the five 4:3 frames; (2) Automatic
`22 / 24 / 0 / 0` on 5 of 10 frames, Conservative `0 / 0 / 0 / 0`; (3) every filter's help, the
split before / after, Colorspace BT.709 on `hdr10` suggests tone mapping, *Enable tone mapping*,
the split shows the mapped frame; (4) an H.264 clip plays in the panel, an HEVC clip compares
frames (Chromium) and *Compare frames* for AV1. Then F-17 flow 4. First headless (Playwright,
Chromium light and dark, Firefox light and dark, the screenshots read), then once headed by the
lead on `HDMI-A-1` through the guard.

## Commands

As [m6-breakdown.md](m6-breakdown.md#commands). The fixtures:
`scripts/dev-server.py --fixtures letterbox,hdr10,hdr10-4k,multitrack`.

**Ports** (rule 7): agent N uses 87N0 to 87N9; 8750 and 8751 belong to `npm run e2e`. A 871x,
B 872x, C 873x, D 874x, E 877x, F 879x, the lead 876x, R1 878x, R2 and the fix agents the
ranges free at the time.

## Fix round

(After the reviews.)

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
  it builds and the ones it uses, its "Done when" word for word, its section of 0067,
  rules 5, 6 and 7 and the test rules word for word, its port range.
- Setup: the worktree starts at `main`: first `git merge --ff-only m8-picture`. Then
  `uv sync`, `npm ci` in `frontend/`, and
  `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  The pinned FFmpeg (not in a worktree) is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`
  (`--tools-dir` of `scripts/dev-server.py`); `/usr/bin/ffmpeg` is on `PATH`. MediaInfo is not
  installed.
- Commits per step, step ID first (`F-7: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Update only its own
  `docs/status.md` row.
- The report: the real output of every command of rule 5 (the last lines), what the agent saw
  in its screenshots (light and dark), the test rules' checks, every deviation from the plan
  and from this file, every file touched outside its list, and what later tasks need.

### Simple code (the owner's rule for M8, word for word in each brief)

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

### Changes for M8 (binding, with the rules above)

- The worktree starts at `main`: every agent first runs `git merge --ff-only m8-picture`.
- Commits start with the step ID (`F-7: …`, `F-8: …`, `F-15: …`, `F-17: …`) and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Stage files by name.
- Each agent updates only its own sentence of its `docs/status.md` row and writes only its own
  section of 0067.
- Scratch files: each agent keeps its scratch files (server logs, ready lines, scripts,
  screenshots) in its own `scratchpad/task-<x>/` and reads a server's URL and token only from
  the ready line of a server it started itself.
- Nothing in a test or a check writes to a media file outside the temp folders; queued jobs
  write only into the dev server's output root.
- The report starts with the agent's model ID.

## Progress

| Date | What |
|------|------|
| 2026-11-02 | **Wave 0.** Branch `m8-picture` from `m7-batch-season` d3c2467 (M7 is not in `main`). API check against a real server with the pinned FFmpeg (0067 Context): every preview route works; headless Chromium 156 and Firefox 157 play H.264 (MP4, MKV) and AV1 clips, Chromium refuses HEVC; missing: frames of a clip, a detected crop written into the job, a detected crop not counted as *modified*. The lead built: `POST /api/preview/clips/{id}/frames` (+ 2 tests, OpenAPI regenerated; a mutation without the 404 fails), `presets.diff` without a detected `rect` (+ 2 tests; two mutations fail), `editor.amend` (+ 3 tests; three mutations fail), this file, 0067 with placeholders and the 06 §S-2 row, the skeleton (types, `stores/preview.ts` and `stores/crop.ts` stubs, component stubs and mounts, Dimensions and Filters in the tab registry, Settings → Preview's section, the panel shown by default, the workspace starts the crop store with a test; the Picture card's fallback for unbuilt tabs removed). Checks: lint, format, typecheck, 1547 unit tests, `build:web`; `reframe` presets tests 208, server `test_preview.py` and the OpenAPI, facade and jail tests 57 passed; ruff, mypy |
| 2026-11-02 | **Wave 1 launched**: A (871x), B (872x), C (873x), D (874x), each `opus` / `high` in its own worktree. B, C and D stop after phase 1 and are resumed for their browser checks after the stores they use are merged (B and D: A; C: A and B). A was told the crop handles carry `data-crop-handle` (B gives it) |
| 2026-11-02 | **C phase 1** (6fa7da0, 44 tests, 52 mutations caught; luma-variance threshold 4: bars 0.33–0.46, picture 802–8 610 on the pinned FFmpeg's `letterbox` frames) and **B phase 1** (c87f366, 55 tests incl. 7 real-server, 47 mutations caught; the header equals `jobs/plan`'s `crop=` / `scale=` for six cases; B's 576p / 480p fit boxes are 16:9, 1024×576 / 854×480, accepted by the lead: the plan names no box, and 16:9 matches 1080p and 720p) reported; both wait for their phase 2 |
| 2026-11-02 | **Merged A** (dfcca3f; 20ae158): the preview store, panel, `FrameViewer`, `SplitCompare`; 51 browser checks in Chromium and Firefox, light and dark. A's deviation: a seek past the end is a `422` (one timestamp without a frame fails the task, 0033 §2). Checks: lint, format, typecheck, 1592 unit tests, `build:web`. The lead's mutation (the output frame without the 250 ms debounce) fails `preview.test.ts`; restored, touched. Worktree removed. B resumed for phase 2; D told to go on with phase 2; **E launched** (877x) |
| 2026-11-02 | **Merged D** (merge after 1b957c1): the Filters tab (list, help, implementations with the build's availability, the colour box and its sentence with the issue's fix, the custom text checked by `jobs/dry-run`); the split on Filters checked with A's panel (Grayscale, Sharpen, `hdr10` tone mapped after the fix). 1613 unit tests, lint, typecheck, build. The lead's mutation (a filter turned on with its first preset, not its default) fails `FiltersTab.test.ts`; restored, touched. Worktree removed. D's findings for the fix round: **L1** `useValidation` treats the `403 filter.not_allowed` of a refused custom filter as a failed validation (the status bar keeps old counts, no field shows it; `jobs/plan` and `preview/render` are refused too); **L2** the dry run puts a refused filter at `video.custom_params` / `video.encoder`, not `filters.<id>.custom`, and `jobs/validate` does not dry-run, so `eq=nosuch=1` can be queued and fails at the encode; **L3** on `hdr10`, Colorspace BT.709 without tone mapping renders a posterised, green-cast frame rather than "washed out" |
| 2026-11-02 | **Merged B** (eb5ff7a; bbd2b10): the crop store, the Dimensions tab, `CropOverlay`; every Done-when line in Chromium and Firefox, light and dark, the group case; two defects found and fixed (handles half clipped at an uncropped edge; a snap note kept after an undo). The `status.md` F-7 / F-8 rows resolved per row. 1661 unit tests, lint, typecheck, build. The lead's mutation (the detected crop written with `editor.patch`, an undo step) fails 2 tests of `crop.test.ts`; restored, touched. The lead ticked 06 §F-7's `FrameViewer` box (A's viewer and B's handles). Worktree removed; C resumed for phase 2 |
| 2026-11-02 | **L3 checked by the lead** (port 8761, `hdr10`): Colorspace BT.709 alone is `zscale=p=bt709:t=bt709:m=bt709` with no tone mapping, so the fixture's bright PQ codes (a synthetic `testsrc2` tagged PQ) clip at 100 cd/m²: red turns yellow, blue cyan; with tone mapping the frame matches the untouched one. The preview runs the encode's own chain (0033 §4), so this is the real output, not a preview defect; the warning's "washed out" (the plan's 03 wording) undersells clipping. Recorded, not changed |
| 2026-11-02 | **Merged E** (29eab4c; 13d2e40, 21e963c): Settings → Preview (count, limit in MiB, cache size, *Clear cache*) and the live preview clip (10 / 15 / 30 / 60 s, progress, *Cancel*, the player with a new link then the frame compare on a video error, *Compare frames*, *Open in external player*, out of date after an edit); 42 mutations caught; Chromium plays H.264 and AV1 and falls back for HEVC, Firefox plays all. E ticked 06 §F-15 (every section of 03 §Settings now built). The F-7 row was rebuilt by the lead to three columns (A's row had kept a stray `M8` cell that B wrote into); the lead's first resolution committed conflict markers when a script assertion failed in a `;` chain, fixed by amending the merge before anything else. 1689 unit tests, lint, typecheck, build. The lead's mutation (a fixed 10 s length) fails `PreviewClip.test.ts`; restored, touched. Worktree removed |
| 2026-11-02 | **Merged C** (f107ea4; 6fa7da0, f927167): `CropMagnifier`, `CropLoupe`, `CropCheckGrid` and its worker; every Done-when line in Chromium and Firefox, light and dark (strip canvases read back pixel by pixel; badges on frames 5–9 at 22 / 24 / 0 / 0 and 0–4 at 0 / 0 / 40 / 40; 4K `hdr10-4k` checked in 0.6–1.4 s). The threshold became 64: the server's bicubic RGB conversion rings into the bars (4.9–6.1; picture at least 793; `testdata/README.md`). Retries go through A's `imageFailed`. C ticked 06 §F-7's two boxes, so every F-7 box is ticked. The F-7 row: C's sentence added to the three-column row. 1735 unit tests, lint, typecheck, build (the worker chunk is in `dist/`). The lead's mutation (the threshold back at 4) fails `cropCheck.test.ts`; restored, touched. The lead fixed 06's folder tree (the magnifier is in `crop/`; 0067 Plan changes). No worktree left; **F launched** (879x) |
| 2026-11-02 | **Merged F** (5227020; e655196): flow 4 (`e2e/flow4-manual-crop.spec.ts`; `letterbox` added to the e2e servers): detection line, *Manual*, typed 23 → 22 and 17 → 16 with their notes, the right handle moved with Shift+← and ←, the magnifier strips read back pixel by pixel at 4× and 8×, the Video tab's command holds exactly `crop=286:134:16:22`. F's runs: 22 passed twice (44.6 s, 44.5 s); clean-up after pass, forced failure and SIGINT; 8 mutations fail it (one, the strip window one row lower, rightly passes). F ticked 06 §F-17's first box (all four flows built). The lead's run: `npm run e2e` 22 passed (44.7 s); the lead's mutation (a handle key moving one pixel, not one chroma step) fails flow 4 in both browsers; restored, touched, `dist/` rebuilt. Worktree removed; no agent worktree left. **Reviews R1 and R2 launched** |

## Where M8 ended

(Written at the end of the milestone.)
