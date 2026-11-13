# 0076 — F-16: what the i18n and accessibility audit checks, and how

- Status: accepted
- Date: 2026-11-13
- Steps: F-16 (F-17, F-19)

## Context

The whole of [06 §F-16](../plan/06-web-app.md#f-16-i18n-and-accessibility) is one bullet:

> Audit that every string goes through vue-i18n (English first; the rule and its check start in
> F-1). Full keyboard paths. Visible focus. WCAG AA contrast in both themes. Respect
> `prefers-reduced-motion`.

[0043](0043-plan-review-before-m3.md) item 8 moved i18n to F-1 and left the accessibility work
and the final audit to F-16. The frontend (138 components, checked on 2026-11-13) already has:

- vue-i18n for every template string, with two checks in `src/i18n/checks/`. One finds
  literal text in a `<template>`. The other finds message keys that `en` does not have. Keys
  built at run time are not seen.
- `src/styles/contrast.test.ts`: the contrast of PrimeVue's own variables in our preset, in
  both themes.
- In `tokens.css`, `prefers-reduced-motion: reduce` sets PrimeVue's and our transition
  durations to 0.
- A global `:focus-visible` ring in `main.css`.
- Keyboard work in each milestone: shortcuts, the matrix, the crop keys, the Range popover.

Nothing checks the rendered app as a whole. There is no axe or similar tool, no check that
each focused element shows its focus, and no check that animations stop under reduced motion.
Numbers are formatted in two ways: some go through vue-i18n's `n()`, many through `toFixed`,
which always writes a period. Strings built in scripts (toasts, refusals, accessible names set
in code) are seen by no check.

## Decision

1. **What the audit checks.** F-16 is done when each point holds on every screen of the web UI,
   in Chromium and Firefox (headless), in the light and the dark theme:
   1. **Strings.** Every text a user reads or hears goes through vue-i18n:
      - template text and visible attributes (the existing check);
      - strings built in scripts: toasts, refusals, accessible names, `title` and
        `aria-*` set in code;
      - PrimeVue's own strings (`primevueLocale.ts`).

      Numbers, dates and lists are formatted with the app's locale (`n()`, `d()` or `Intl`
      with `locale`), not with `toFixed` or string joins. Text is never built by joining
      translated pieces in a fixed order; one message with placeholders does it, and
      plurals use vue-i18n's plural forms. English is the only locale (`SUPPORTED_LOCALES`).
   2. **Full keyboard paths.**
      - Every action of the UI can be done with the keyboard alone, in a logical tab order.
      - There is no keyboard trap. A modal dialog or popover keeps the focus inside while it
        is open, closes on Escape and gives the focus back to what opened it.
      - Each custom widget follows its WAI-ARIA Authoring Practices pattern (its role, its
        keys).
      - An action that is drag-only today (crop handles, the split-compare divider, a drop of
        files) has a keyboard way.
      - The shortcuts of [03 §App layout](../plan/03-features.md#app-layout) work.
   3. **Visible focus.**
      - Every element that takes the focus from the keyboard shows a focus indicator
        (WCAG 2.2: 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured (Minimum)).
      - The indicator has 3:1 contrast with what is next to it (1.4.11).
   4. **WCAG AA contrast in both themes.**
      - Text: 4.5:1, large text 3:1 (1.4.3).
      - UI parts and graphics that carry meaning: 3:1 (1.4.11). These include borders of
        inputs, states, icons without text and chart marks.
      - Disabled controls are exempt, as WCAG says.
   5. **Reduced motion.** With `prefers-reduced-motion: reduce`, no CSS transition or
      animation runs (no running `document.getAnimations()`, every computed duration 0), and
      nothing scrolls smoothly. Video does not start by itself: it never does in Reframe;
      playing is the user's action.
2. **How: a gate in the end-to-end tests (task G).**
   - A Playwright spec visits a fixed list of screens. Each screen gets an id, set-up steps
     and the area that owns it (the list is in the M10 breakdown, "F-16").
   - On each screen, in both themes, it runs axe-core with the WCAG 2.0/2.1/2.2 A and AA rules.
   - It tabs through the screen and checks that each stop shows a focus indicator.
   - With reduced motion emulated, it checks that nothing animates.
   - A finding that is known and not fixed yet sits in its area's list
     (`e2e/a11y/known/<area>.ts`). The gate fails on a finding that is not listed, and on a
     listed one that no longer happens, so the lists only shrink.
   - At the end of F-16 the lists are empty, except entries this record names with a reason.
3. **The new dependency.** `@axe-core/playwright` (a dev dependency). No tool in the project
   checks the rendered page against WCAG; writing contrast and ARIA rules by hand would copy
   axe badly. The token test stays: it checks every variable, including states that no screen
   shows.
4. **Ports.** `e2e/support/servers.ts` takes its first port from the environment
   (`REFRAME_E2E_PORT`, default 8750), so that agents can run the flows and the gate on ports of
   their own at the same time.
5. **Not in F-16** (each can come later with its own record):
   - **A layout for windows below about 1100×700 logical pixels.** `docs/status.md` "Not
     verified" left it to "F-16 or a later step". The plan's F-16 asks for AA contrast, not
     the whole of WCAG AA. Reflow (1.4.10) and text resize (1.4.4) are not checked. This is
     a question for the owner; the default is "later".
   - **Server messages.** The texts of validation issues, fixes and errors come from the
     server in English. They are data, shown as they are: translating them is a server
     change for a second locale.
   - **WebKit** (Safari, WebKitGTK of the Linux desktop) is F-17's.
   - **Screen readers.** A real test with Orca or NVDA is recorded as not verified. The audit
     checks the roles, names and states that axe and the keyboard walk can see.
   - **The native dialogs and the tray menu of the desktop app.** They belong to the
     operating system.

## Consequences

- The gate adds a few minutes to `npm run e2e`. It is the record of what F-16 checked: each
  screen, each theme, each check.
- Each component area fixes its own findings, so the agents never edit the same file
  ([m10-breakdown.md](../m10-breakdown.md) "F-16").

## Task G: the gate and the shared layer

Built on 2026-11-13 on Linux (this host), headless Chromium and Firefox of Playwright 1.64.1.

### The gate

`frontend/e2e/a11y/gate.spec.ts` runs one test per screen of `screens/{shell,picture,tracks}.ts`
(the ids of the breakdown), in both browsers. A screen is `{ id, area, setup, region? }`.
`setup` starts on a blank page and reaches the screen through the UI (`openApp` and the
helpers of `steps.ts`). The page is prepared before the set-up: light theme, reduced motion
emulated, and the gate's probe (`page/probe.ts`) installed as an init script. Then, on the one
set-up, the checks run in this order:

1. Light theme: the motion check, then axe. Dark theme (`emulateMedia`, the app follows the
   system theme): the motion check, then axe.
2. The focus walk, last, because Tab moves the focus. It judges each stop in both themes: the
   probe toggles the app's dark class for the look of the other theme, so one walk serves both.

**`region`.** A screen that is a part of the page (a dialog, a popover, an editor tab, a
settings section, the preview panel) names it: axe checks only it, and the walk starts in it
and ends when the focus leaves it. Without a region, the whole page, and the walk starts where
the set-up left the focus and ends when the focus comes back to its first stop, leaves the
page or stays put. (Firefox, headless: a Tab past the last element moves the focus out of the
page but leaves that element as `document.activeElement`; `document.hasFocus()` turning false
ends the walk.) A walk of 250 stops fails the screen: it needs a region. So the shell's columns are checked on the shell's screens (`workspace-empty`,
`toast` with a file open), not again on each tab of the picture and tracks areas.

**axe.** `@axe-core/playwright` 4.14.0 (axe-core 4.14.0), pinned exactly, with the tags
`wcag2a wcag2aa wcag21a wcag21aa wcag22a wcag22aa`. Only violations count; axe's "incomplete"
results (contrast over an image, for example) are not findings. axe runs on the app as served
(`dist/`), with the app's CSP; no bypass is needed.

**The focus walk** (0076 item 1 point 3). Before the walk, the probe takes the unfocused look
of every element that can take the focus (in the region), in both themes: computed outline,
box shadow, border colours and width, background, text colour and underline of the element,
its `::before`/`::after`, three parents (with their pseudo-elements), its next sibling (with
its pseudo-elements), three children and the option its `aria-activedescendant` names. The
look is taken before the walk because PrimeVue's Select keeps its focused look for 100 ms
after a blur; an element made during the walk is judged after a 200 ms wait instead. After each
Tab, the stop is looked at again, and when the focus has moved on, it is judged:

- `no-indicator`: nothing shown changed (parts with opacity below 0.1, `visibility` other than
  visible, a clip path or a size below 2 px do not count, so the outline of a hidden native
  input is not an indicator).
- `indicator-contrast`: the best change is below 3:1. A mark that appears (outline, outer or
  inner shadow, underline) is measured against what it lies on: the colour found by hit testing
  just outside the element on each side (a slider's handle sticks out of its track), the best
  side counts. A border, fill or text colour that changes is measured against its unfocused
  colour, since it was there before: a grey border that turns indigo is 1.3:1, too little to
  show the focus, and is reported. This is stricter than 1.4.11 alone and closer to 2.4.13;
  it is the answer to K1's question (its list, item 4). The shared layer now gives form fields
  a ring, so they pass.
- `obscured` (2.4.11): something else covers the part of the stop inside the window at its
  centre and at four inner corners.

Proof by mutation, kept as tests in `gate-checks.spec.ts`: removing the rail links'
`:focus-visible` outline makes the walk report `no-indicator` at
`nav.nav-rail a.nav-rail__link[data-view="workspace"]` in both themes, and a ring in the
surface's colour makes it report `indicator-contrast`.

**The motion check** (0076 item 1 point 5). The probe records, from the first script of the
page: `transitionrun` events (a transition with a duration), `animationstart` events of
animations with a duration, `Element.animate` calls with a duration, and smooth scrolls. A
scroll is judged by its effect: the call returns before the position moves and the position
moves within the next 300 ms. (Both browsers scroll smoothly on request even with reduced
motion emulated: checked on 2026-11-13, a `scrollIntoView({ behavior: 'smooth' })` left the
scroller at 0, two frames later Chromium was still at 0 and Firefox at 19 px, and both reached
2500 px later. So the check waits 300 ms, not two frames, before it reads what moved.) Each check also reports the
running `document.getAnimations()`, and every element (and its `::before`/`::after`) whose
computed transition or animation duration is above 0 or whose `scroll-behavior` is smooth.
The check runs after the set-up and after the switch to dark, so the transitions of a theme
change are seen.

**Targets.** A finding names its element with a CSS selector the probe makes: the element's tag,
its own classes (BEM classes first, PrimeVue's otherwise, state classes left out) and the
attributes that name a place (`data-path`, `data-action`, …), after the nearest ancestor that
names an area (`data-card`, `data-panel`, a dialog, …). Ids with digits (generated) are never
used. Attributes that name a list item (`data-variable`, `data-preset`, …) are written without
their value, so one fault of a row is one finding.

**Known lists.** `known/<area>.ts` holds `{ screen, check, theme?, browser?, rule?, target }`.
An entry without `theme` stands for both themes, without `browser` for both browsers. The
`browser` field is an addition to the breakdown's contract: some findings are of one engine
only (Firefox paints some focus differently), and an entry that must happen in both would fail
in the other. The gate fails on a finding that no entry matches and on an entry that matched
nothing; its message prints the unlisted findings as entries to paste.

**Runtime.** `npm run e2e` on this host, the whole run with the server start and the build:
before, 1 min 20 s (24 tests); after, 4 min 23 s and 4 min 25 s in two runs in a row (124
tests: the flows and layout tests, 42 screens, the list test and the gate's own 7 tests, in both browsers). Under the load of
four agents at once a run took up to 10 min. The two
browsers run side by side, each with one worker on its own server (the queue is shared).

### `REFRAME_E2E_PORT`

`e2e/support/servers.ts`: the first port comes from `REFRAME_E2E_PORT` (default 8750), Chromium
on it and Firefox on the next. A value that is not a port stops the run with an error. The
servers also serve `text-subs.en.srt`, for the `subtitles` screen's external subtitle.

### The shared layer

- `tokens.css`: under reduced motion every duration and delay is 0, not 0.01 ms. With 0.01 ms a
  transition still runs: `transitionrun` fires and the style read at once is the old one, so
  the gate found transitions on every element. Vue's and PrimeVue's transitions end at once at
  0 (they wait for an event only when the duration is above 0). Test: the gate's motion check
  (352 findings on `workspace-empty` before).
- `theme.ts`: form fields (InputText, InputNumber, Textarea, Select, AutoComplete) draw a 2 px
  ring of the primary colour when focused (Aura's `formField.focusRing` is 0). Tests:
  `contrast.test.ts` (the ring's width and its 3:1 against the field and the surfaces) and the
  gate.
- `main.css`: the focused menu item (Menu, ContextMenu) gets the inset ring the focused list
  option has (its tint is 1.1:1); PrimeVue's VirtualScroller gets a focus ring (Aura sets
  `outline: 0`).
- `components/base/keyboard.ts`, installed by `main.ts`: Escape on a closed Select reaches the
  Dialog or Popover around it (PrimeVue's Select stops every Escape), and a popup Menu puts its
  first item in focus when it opens (APG menu button). Tests: `keyboard.test.ts`. The areas'
  own Escape handlers (PresetNameDialog, DefaultsDialog, RangeSelector) can go in phase 2.
- `i18n/index.ts`: a count goes into `{n}` and `{count}` formatted with the locale
  (`1,234 files`, not `1234 files`), whether it is the plural argument or a named `n`/`count`.
  vue-i18n puts it in raw. Test: `i18n/index.test.ts`.
- `components/base/motion.ts`, installed by `main.ts`: while reduced motion is asked for, a
  scroll that code asks to be smooth jumps (PrimeVue's Listbox scrolls its options into view
  smoothly). Test: `motion.test.ts`.
- `useReveal.ts`: in a group of buttons the pressed one takes the focus (the Summary's "10-bit"
  link landed on "8-bit"). Test: `Field.test.ts`.
- `primevueLocale.test.ts`: every locale text that a PrimeVue component the app imports reads
  comes from the messages, except the texts of features the app does not use (DataTable
  filters and row editing, the Paginator), listed in the test.

Not changed, with the reason:

- A modal Dialog takes the focus after its enter transition (about 200 ms with motion on), so a
  Tab in that time goes to the page behind. With reduced motion the transition is 0. Not fixed:
  PrimeVue focuses in `onAfterEnter`.
- The readonly input of Settings → Tools paints the disabled colours (4.07:1 in dark); that is
  ToolRow's choice of tokens (K1), not the tokens' contrast: disabled controls are exempt.

The shared findings that K1, K2 and K3 sent in phase 1, and what became of each:

| Finding | Done |
|---------|------|
| Select stops every Escape, so its dialog stays open | `keyboard.ts`, for every dialog; the local handlers can go |
| A popup Menu opened with Enter has no item in focus | `keyboard.ts` |
| VirtualScroller removes its outline | `main.css` |
| Inputs, Select, InputNumber show focus by a border colour only | the form-field ring; the gate measures a changed border against its old colour |
| A Menu's focused item is a faint tint | `main.css`, the ring of the focused list option |
| Counts go into `{n}`/`{count}` raw | `i18n/index.ts` formats them |
| InputNumber uses the browser's locale | `:locale="locale"` on each, as the areas did; the script-text check reports one without it |
| 0.01 ms durations under reduced motion | 0 |
| `useReveal` focuses the first button of a SelectButton | the pressed one |
| The split-compare ring is drawn on a frame's `::after` | the walk looks at the parents' and the next sibling's pseudo-elements |
| A modal Dialog takes the focus only after its enter transition | not changed (above) |

### The i18n checks

`src/i18n/checks/scriptText.ts` reads the scripts of `.ts` and `.vue` files and the bound
expressions of templates (`:pt="{ root: { 'aria-label': 'x' } }"`, `:model`, `{{ }}`), with the
TypeScript parser, and reports:

- a string literal with a letter as the value of a key a user reads (`summary`, `detail`,
  `label`, `title`, `aria-label`, … : the template check's visible attributes and the aria
  names), through `?:`, `??`, `||` and `+`; a value written like a name in code (`title`,
  `audio_codec`) is not text;
- `setAttribute('aria-label' | 'title' | …, 'x')`, `el.title = 'x'`, `el.textContent = 'x'`
  and the other text properties, and `alert`/`confirm`/`prompt('x')`;
- text joined from translated pieces: `t('a') + t('b')`, a template literal with a translation
  and words, `[t('a'), t('b')].join(…)`;
- a number written with `toFixed` where it becomes text: in a translation's values, in a
  template literal with words, in `{{ }}`;
- a PrimeVue `InputNumber` without `locale` (the rule the areas follow: `:locale="locale"` from
  `useI18n()` on each; PrimeVue has no app-wide setting for it).

Strings the check cannot see: text returned by a function and shown elsewhere, and numbers
formatted in one place and shown in another. Over the whole code base on the merged state
(m10-hardening with K1–K3 phase 1), the findings are in `checks/allowed.ts`, one entry per
finding; the check fails on a finding not there and on an entry that is gone.

### Known-list entries left

Filled from a run of the gate on m10-hardening with K1–K3 phase 1 merged (9caed63 and this
task's fixes). Every entry is a finding the areas fix in phase 2; none is meant to stay. Each
list names the screen's area; some elements belong to another area, as the comments say.

- `shell.ts`: the preset list takes the focus with no option in focus (both browsers), and
  Firefox stops on the Listbox's hidden first and last elements; a preset category's name and
  a source row's name are not their visible text; a preset row's focus in dark (1.1:1); the
  queue table's row actions are `obscured` at the point the focus lands (both browsers;
  "Retry" in Chromium only); Settings → Tools paints a read-only path in the disabled colours
  (4.07:1 in dark); the header's Range button's name does not start with its text (tracks
  area's component).
- `picture.ts`: on `crop-manual` (a whole-page screen) the shell's source row and the Range
  button; the naming chips on `summary` (tracks area's component); in dark, the reset and help
  buttons of a changed option's tinted row show their focus at 1.23:1.
- `tracks.ts`: a matrix cell, the naming chips and the Subtitles tab's scan button (picture
  area's ScanControl) have names that do not start with their visible text.

## Task K1: the shell and the pages

(Filled in after the task.)

## Task K2: the picture and the video

Done on 2026-11-13 on Linux (this host). Each screen of the area was walked with the keyboard,
headless Chromium and Firefox of Playwright: `summary`, `dimensions`, `crop-manual` (the
magnifier, the crop check dialog), `filters`, `video`, `video-advanced`, `command-drawer`,
`preview-frames`, `split-compare`, `preview-clip`. The browser scripts drove a real server with
the pinned FFmpeg, so the frames and clips were real. After that came the gate (phase 2).

**Keyboard and focus.**

- The Summary's picture-pipeline link (`dimensions`) and its count of changed advanced
  options (`video.advanced`) left the focus on `<body>`: no field answered the reveal. Now the
  Dimensions tab answers the first one, and the advanced panel's toggle answers the second;
  that reveal also opens the panel (`stores/ui.ts`).
- The crop handles are APG sliders. Home and End go to 0 and to the largest crop that leaves
  a picture, and Page Up and Page Down move eight chroma steps. `aria-valuemax` is that largest
  crop, not the picture's size. The arrows move a handle the way they point, so Up lowers the
  top crop. The APG allows that ("reversing the direction of the value change … could create a
  more intuitive experience", checked against the APG page). Page Up and Page Down do the same
  on the top and bottom handles.
- The split-compare ring lay over the picture in the primary colour: 1.36:1 against the test
  pattern's blue bar. Now it is white beside black, so one of the two stands out on any
  picture. The gate looks at it on the frame's `::after`: with the ring taken out, the walk
  reports `no-indicator` at `input.split-compare__range` in both themes and both browsers
  (checked by mutation).
- The preview clip's player is named. It never starts by itself: `autoplay` is off, checked in
  both browsers and in a unit test.
- Scan buttons (`ScanControl`, also on the tracks area's screens): an accessible name now
  starts with the button's visible text, for speech input ("Count events of every subtitle
  track", "Measure loudness of track 2", "Measure again: loudness of track 2"). This was the
  `subtitles` screen's `label-content-name-mismatch`.
- Already right, no change: the RF and speed sliders (keys, `aria-valuetext`), the encoder
  picker, the advanced panel (search, *Show only changed*, reset), the command drawer
  (a disclosure with a named, focusable code region), the frame strip (`aria-current`, a
  focusable stage that scrolls with the arrows at 100 % and 200 %), and the crop check dialog
  (focus inside, Escape gives it back to its opener). Motion: the area starts no smooth scroll
  and no animation loop. Each `requestAnimationFrame` of the magnifier and the loupe draws one
  frame.

**Strings and numbers.**

- `summary/format.ts`, `media/streams.ts`, `advanced/options.ts` and the dimensions header
  take vue-i18n's `n` as they take `t`. Sizes, bitrates, aspect ratios, frame rates (the
  frame-rate list's labels were hard-coded), quality values, kHz, delays, loudness, event and
  frame counts and the HDR mastering values use the app's locale. Unit tests check this in a
  `de` locale. `formatBytes` needs `n` from every caller (K1's three included); `kiloHertz`
  takes it optionally until the tracks area's two callers pass it.
- InputNumber: `:locale="locale"` on each one (seek, bitrate, RF, advanced options, size,
  PAR). Without it, in a German browser, a typed 2.5 s seek went to 25 s and the bitrate
  showed `6.000 kb/s`.
- Text joined from pieces is one message: rotation with flip, bitrate with 2-pass, delay units
  (`ms`/`s` were written in code), colour with HDR formats, `{ratio}:1`, and the Summary's
  track counts. Lists use `Intl.ListFormat` (HDR formats, dispositions). Plurals are added for
  one sample frame and one counted event. Those messages name the track `{track}`: vue-i18n
  takes a numeric `n` as the plural count when `count` is not a number.
- Kept as they are: ` · ` and ` → ` between independent facts that come from different
  messages (the Summary's video line, the picture pipeline) are separators, not grammar.
  Timecodes (`formatTime`, `preciseDuration`) are times, not numbers. Small integers and
  pixel sizes without grouping (`320×180`, degrees) read the same in any locale with Latin
  digits. The magnifier's strips follow the pointer along the edge. That is a view, not an
  action, so there is no keyboard way to move them.

**Known entries left in `known/picture.ts`.**

- `crop-manual` (a whole-page screen): the shell's source row (K1's) and the header's Range
  button (K3's). They go when those areas' fixes merge.
- `summary`: the naming editor's variable chips (K3's).
- `video-advanced`, dark: `indicator-contrast` 1.23:1 on the reset and help buttons of a
  changed option. This is a fault of the gate, not of the page. `probe.ts` reads a colour by
  painting it on a canvas and treats `getImageData` as premultiplied (`r * 255 / a`). The data
  is not premultiplied: `color(srgb 0.506 0.549 0.973 / 0.1)` reads as `128,137,245,26` in both
  browsers (checked). So the translucent tint of a changed row becomes a backdrop near the
  ring's own colour. As painted, the ring is 5.2:1 on that row. With the line changed to
  `[r, g, b, a / 255]` (tried locally, not committed), these two entries go, and so does the
  shell's dark preset-row entry (1.1:1); no other finding of the gate changed. The fix
  belongs to the gate.

## Task K3: the tracks and the batch

(Filled in after the task.)

## Review and fix round

(Filled in after the reviews.)
