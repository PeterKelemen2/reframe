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
settings section, the preview panel) names it: the walk starts at the top of the region and
ends when the focus leaves it or comes back to its first stop (a modal dialog's focus trap).
axe and the motion check always take the whole page (changed by FG, below). Without a region,
the walk takes the whole page from its top: the probe focuses `body` (tabindex -1 for the
moment), so the first Tab goes to the first stop of the page and the element the set-up left
the focus on is a stop like the others. Neither browser wraps round in headless mode, so a
whole-page walk ends at the last stop: Chromium leaves the focus on it, Firefox moves it out
of the page but leaves that element as `document.activeElement` (`document.hasFocus()` turning
false ends the walk). A walk of 250 stops fails the screen: it needs a region. So the shell's
columns are walked on the shell's whole-page screens (`workspace-empty`, `toast` and
`status-error` with a file open, `settings`), not again on each tab of the picture and tracks
areas.

**axe.** `@axe-core/playwright` 4.14.0 (axe-core 4.14.0), pinned exactly, with the tags
`wcag2a wcag2aa wcag21a wcag21aa wcag22a wcag22aa`, on the whole page. Violations count; of
axe's "incomplete" results, the probe measures the text contrasts it can (below, FG) and the
others are noted on the test. axe runs on the app as served (`dist/`), with the app's CSP; no
bypass is needed.

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
  just outside the element on each side (a slider's handle sticks out of its track); the
  contrast reached on at least half of the sides counts (FG: it was the best side). A border, fill or text colour that changes is measured against its unfocused
  colour, since it was there before: a grey border that turns indigo is 1.3:1, too little to
  show the focus, and is reported. This is stricter than 1.4.11 alone and closer to 2.4.13;
  it is the answer to K1's question (its list, item 4). The shared layer now gives form fields
  a ring, so they pass.
- `obscured` (2.4.11): something else that paints (a background, a picture) covers the part of
  the stop inside the window at its centre and at four inner corners, hit tested with
  `pointer-events` forced on (FG).
- `trap`, `region-exit`, `unreached` (FG): Tab stops of the region or page that the walk never
  reached.

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
The check runs after the set-up, after the switch to dark (so the transitions of a theme
change are seen) and after the focus walk (FG).

**Targets.** A finding names its element with a CSS selector the probe makes: the element's tag,
its own classes (BEM classes first, PrimeVue's otherwise, state classes left out) and the
attributes that name a place (`data-path`, `data-action`, …), after the nearest ancestor that
names an area (`data-card`, `data-panel`, a dialog, …). Ids with digits (generated) are never
used. Attributes that name a list item (`data-variable`, `data-preset`, …) are written without
their value, so one fault of a row is one finding.

**Known lists.** `known/<area>.ts` holds `{ screen, check, theme?, browser?, rule, target }`
(FG made `rule` required; the target matches exactly).
An entry without `theme` stands for both themes, without `browser` for both browsers. The
`browser` field is an addition to the breakdown's contract: some findings are of one engine
only (Firefox paints some focus differently), and an entry that must happen in both would fail
in the other. The gate fails on a finding that no entry matches and on an entry that matched
nothing; its message prints the unlisted findings as entries to paste.

**Runtime.** `npm run e2e` on this host, the whole run with the server start and the build:
before, 1 min 20 s (24 tests); after, 4 min 23 s and 4 min 25 s in two runs in a row (124
tests: the flows and layout tests, 42 screens, the list test and the gate's own tests, in
both browsers). Under the load of four agents at once a run took up to 10 min. The new runtime
after FG is under "Review fixes (FG)". The two
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

### Review fixes (FG)

Done on 2026-11-14 on Linux (this host), headless Chromium and Firefox of Playwright 1.64.1,
on m10-hardening with FP's phase 1 merged (edb476b). Review R1 showed parts of the app that the
gate never checked; R2 found two flaky tests and an `obscured` with no proof. What changed:

- **Whole pages are walked from the top** (R1-1). The walk used to start where the set-up left
  the focus and never wrapped, so the workspace with a file open was walked from its middle
  (`toast` 3 stops, `crop-manual` 51 of about 100, `login` 1 stop and that one never judged).
  The probe now focuses `body` first (above, "`region`"): `toast` is walked from the rail
  through the header, the sources, the tabs, the Tags panel, the preview panel and the status
  bar to the toast.
- **axe takes the whole page on every screen** (R1-2); a region only narrows the walk. What
  only regioned screens showed is walked on a whole-page screen too: `group` lost its region
  (the banner) and walks the workspace in group mode, with the season group of the sources
  tree; new screens `settings` (the settings page with its navigation) and `status-error` (the
  status bar and the editor in the error state, a file open). FP's flat tree removed the
  `label-content-name-mismatch` R1 saw on the group row. With these, every part a screen shows
  is under axe on that screen and under the walk on at least one screen. The breakdown's ids
  are kept. R1 counted 41 screens; there were 42 (the gate's run had 86 tests: 42 screens and
  the list test, in two browsers), now 44.
- **Each stop's own indicator** (R1-3). A part around the stop (a parent, the next sibling)
  counts only when it holds no other focus target (a Tab stop or an item an arrow reaches): a
  toolbar's `:focus-within` change says nothing about which button has the focus. The item an
  arrow key reaches inside a stop's widget is judged too: tabs (Right/Left), tree items, menu
  items and options (Down/Up), and the option an `aria-activedescendant` names (in a listbox, a
  tree, a grid, an open combobox). The gate presses the arrow, judges what it reached, and
  presses the opposite arrow. An option is judged against its look once it is pointed at no
  more, not against the look from before the walk (it may have been the pointed one then). A
  border change counts with its own side's width (the language picker's active option is a
  left bar only; reading the top border's width, which is 0, missed it).
- **Paint as it is painted** (R1-4). Colours are faded by the opacity of the element and its
  ancestors; a `background-image` gradient gives each of its colours and the worst counts; an
  ancestor that clips its overflow (or `contain: paint`) cuts the ring away where it lies
  outside it; the contrast that counts is the one reached on at least half of the sides (not
  the best side); each side is looked at across from the middle of what can be seen of the
  stop, and the ring is measured while the stop has the focus (the next stop's focus may have
  scrolled it away by the time it is judged). `obscured` hit tests with `pointer-events`
  forced on and counts only what paints (a background, a picture), so an overlay with
  `pointer-events: none` hides a stop.
- **Pixels where computed colours cannot be right** (R1-4). A stop next to a picture (an
  `img`, `canvas`, `video` or `url()` background, found by hit testing 3 px outside it), with a
  picture inside it, or under a filter or a blend mode, is judged by screenshots: its box and
  8 px round it, focused and unfocused, in both themes. The pixels that changed by 3:1 must add
  up to a 1 px line round the part of the stop that can be seen (half of 2.4.13's 2 px); the
  area of the stop that has the focus now is left out. On the app these are mostly the preview
  panel's thumbnails and the boxes that hold a frame or the crop magnifier.
- **Traps and regions left early** (R1-5). At the end of a walk, the Tab stops of the region
  (or the page) that were there from its start and were never reached are findings: `trap`
  when Tab left the focus where it was with stops after it, `region-exit` when the focus left
  the region with stops after it, `unreached` for each one otherwise. PrimeVue's focus-trap
  sentinels (`data-p-hidden-focusable`) hand the focus on at once and are not counted.
- **Motion during and after the walk** (R1-6). The motion check runs once more after the walk
  (a `:focus-visible` transition shows only then), `Animation.play` of an animation built by
  hand is recorded, and a script tween is: frame callbacks that change an element's `style`
  in 10 frames in a row (`frame-loop`). A smooth-scroll is no longer reported when another
  scroll call or a focus change came within its 300 ms (the arrows of a tab list scroll it).
- **axe's open contrasts** (R1-7). The colour-contrast nodes that axe leaves "incomplete" are
  measured by the probe (text colour faded by opacity, against the backgrounds and gradients
  behind it and the pseudo-elements' backgrounds), against 4.5:1, 3:1 for large text and for
  what axe takes for an icon (`shortTextContent`, `nonBmp`): `color-contrast-measured`. Not
  measured, and noted on the test as `contrast not measured`: `bgImage`, `imgNode`,
  `equalRatio`, `colorParse`, text behind a modal dialog's mask (inactive while it is open; the
  same text is checked on the screen without the dialog), disabled controls, and nodes no
  longer in the page when the probe looks. On the merged product, one run, per browser
  (Chromium / Firefox, both themes added up): behind a modal 41 / 41 (`apply-to-group`,
  `bulk-edit`, `defaults`, `job-log`, `matrix`, `queue-group`), gone 17 / 12 (`command-drawer`,
  `matrix`, `queue`, `range`: their content is rendered anew while the checks run), `imgNode`
  6 / 4 (`filters`, `split-compare`); no `bgImage`. Every other open node was measured, and
  none is below its threshold.
- **Known entries** (R1 nit): `rule` is required and the target matches exactly.
- **Flaky tests** (R2). `matrix` waits until the editor no longer resolves the matrix (the
  cells are rendered anew for each answer); `keyboard-tracks` "language picker reopens" waits
  for the dialog's enter transition to end before its Tab. On the merged product (FP's
  `dialogFocus.ts`) neither failed in 20 (language picker, Firefox) and 10 (matrix, Chromium)
  repeats without the waits, nor with them; the waits stay, since they wait for what the
  tests assume.
- **Flow 2** follows FP's flat sources tree: the members are the level-2 tree items after the
  group's row, no longer inside it (the flow failed in both browsers on the merged product).

Proof by mutation, each a test of `gate-checks.spec.ts` that fails with the defect put in the
gate and passes without it (run in Chromium; the tests pass in both browsers):

| Defect put in the gate | Test that fails |
|---|---|
| a part round several stops counts as the indicator | a change of a box round several stops is no indicator for any of them |
| opacity ignored | a ring is measured faded by the opacity of an ancestor |
| gradients ignored | a ring is measured against a gradient …; axe text contrast left open over a gradient is measured |
| clipping ignored | a ring that an ancestor clips away is no ring |
| the best side wins | a ring seen on one side only does not pass |
| no pixel judgement | a ring over a picture is judged by its pixels |
| `obscured` returns false at its top (R2) | an overlay that lets the pointer through still hides a stop |
| hit tests without `pointer-events` forced | the same |
| trap, region exit, unreached not reported | a stop that keeps the focus on Tab is a trap; a focus that leaves a region …; a stop that the walk round a region never reaches … |
| the pointed option not judged; one border width for all sides | the option a list points at shows the focus, the one an arrow key reaches too |
| no arrow keys | a tab that only an arrow key reaches is judged; the walk judges the file browser entry an arrow key points at |
| `Animation.play` or frame loops not watched | the motion check sees an animation started by hand and a script tween |
| rings measured at judge time; the visible part ignored | a ring is measured where the stop can be seen, while it has the focus |
| open contrasts not measured | axe text contrast left open over a gradient is measured |
| the walk starts where the set-up left the focus | the walk of a whole page reaches the workspace header, the sources and the editor tabs; the walk judges the element the set-up left the focus on |
| axe limited to the region | axe looks past the region (three tests: the sources tree under a dialog, the settings links, the status bar in its error state) |
| the settings page walked by one section | the settings page is walked with its links |
| no motion check after the walk | the motion check looks again after the walk |
| a known entry matches any rule, or a target by its start | `compare`: an entry with a rule matches that rule only; an entry matches its whole target only |

R1's mutations of the real screens (no focus style on the header, the sources, the editor tabs,
the login field, the file browser's cursor, the settings links; the group row, the settings
links and the error summary in a light colour) are among these tests.

**Runtime.** `REFRAME_E2E_PORT=8700 npm run e2e` on this host (load average about 3 from other
agents), the whole run with the build and the server start: 7 min 51 s and 7 min 50 s in two
runs in a row, 198 tests (the flows, layout and keyboard tests, 44 screens and the list test, the gate's
own 33 tests, in both browsers); before FG, 4 min 23 s for 124 tests. Firefox's gate file
alone takes 5.9 min. What costs most: axe on the whole page in both themes on every screen
(about 1 s more per screen), the whole-page walks (`toast`, `crop-manual`, `status-error`,
`group`, `settings`: 9 to 21 s each), and the pixel judgements of the preview panel (its
thumbnails touch each other: `preview-frames`, `split-compare` and `preview-clip` went from
3–6 s to 10–13 s).

**Known entries added** (FP's list; each with its cause in the file):

- `shell.ts`: Firefox makes a box that scrolls a Tab stop; its ring (2 px, 2 px outside) is
  cut away by the clipping ancestor: the editor's tab list viewport (`.p-tablist` clips) and the
  preview panel's content (`.preview-panel` clips) on `toast` and `status-error`, the settings
  body (`main.settings-view` clips) on `settings`.
- `picture.ts`: the same two Firefox scrollers on `crop-manual`, the preview content on
  `preview-frames` and `split-compare`; the crop magnifier's "previous frame" button, 2.88:1 in
  light (slate ring on the magnifier's grey surface); `command-drawer`: the open drawer covers
  the bottom of the Video tab, so a target partly under it keeps less than 24 px (2.5.8): the
  frame-rate help button (Chromium), the rate field's input (Firefox, dark) and the slider's
  handle (Firefox).
- `tracks.ts`: the same two Firefox scrollers on `group` (now a whole-page screen).

The Firefox scroller entries share one cause: one fix (an inset ring on a box that scrolls, or
no clipping round it) removes them from every screen.

## Task K1: the shell and the pages

Built on 2026-11-13 on Linux (this host), headless Chromium and Firefox of Playwright 1.64.1.

### What was checked, and how

Phase 1, by hand, before the gate: own `scripts/dev-server.py` servers (the e2e fixtures, the
pinned FFmpeg for real encodes, a password server for `login`) and own Playwright scripts that
walk each screen with Tab and Shift+Tab, print each stop's role, name, outline, box shadow and
`:focus-visible`, and try the keys of each widget. Screens: `workspace-empty`, a workspace with
a file, `file-browser`, `preset-picker` (list, filter, actions menu), `status-issues` (with
issues and empty), `toast`, `queue` (done, failed and waiting jobs), `job-log`, the when-done
select, `activity`, `presets` (tree, duplicate, delete dialog), `preset-name-dialog`, every web
section of Settings, `login`, the theme popover; the shortcuts Ctrl+O, Ctrl+Enter, Ctrl+1…8;
`document.getAnimations()` under reduced motion. Every script and template of the area was read
for text outside vue-i18n, numbers, lists and joined pieces. The desktop-only screens
(QuitDialog, FirstRunScreen, ReconnectOverlay, BackendErrorScreen, BootScreen,
PrivateQueueBanner) were read and their component tests checked; none had a finding.

Phase 2: the gate on the area's screens (and `crop-manual`, which checks the shell's columns),
on ports 8720/8721, and `e2e/a11y/keyboard-shell.spec.ts` for the paths only a browser shows.

### Found and fixed

Keyboard and focus:

- The file browser opened with Ctrl+O (no control focused) left the focus on the page when it
  closed: it now goes to the workspace (the editor's tab, else *Open files…*).
- The status bar's empty issue list: Tab rested on PrimeVue's invisible focus guard, and Escape
  there lost the focus. A popover panel without controls is in the Tab order now.
- Escape in Save as new / Rename with the focus on Category left the dialog open (PrimeVue's
  Select stops every Escape). Phase 1 fixed it in the dialog; G's `keyboard.ts` fixes it for
  every dialog, so the local handler went.
- A changed source could not be read again from the keyboard (its button is out of the Tab
  order): *Read it again* is in its context menu.
- The sources panel's context menu opened from the keyboard (Shift+F10, the menu key) took the
  focus only after its transition and with no item in focus, so the keys went to the tree: it
  now opens on its first item.
- Enter and Space on a button inside a group's row (*Edit group*, …) were taken by the tree.
- Type-ahead (WAI-ARIA APG listbox and tree) in the file browser's list, the preset tree and the
  sources tree.
- The preset picker's list: browsers made its scroll container a Tab stop that shows nothing,
  PrimeVue reached the list through hidden guards (Firefox stayed on them), took the filter out
  of the Tab order while the list had the focus (Shift+Tab never went back), and the list showed
  its focus only on the option. The filter and the list are the two stops both ways now, and
  the list has a ring of its own.
- The preset tree was nested, so a category's name was the text of all its presets: it is a
  flat tree with levels and places (APG allows it), a category named by its visible text.
- The sources panel's rows were named by the file name alone, but show their line and warnings
  too (2.5.3): the name is the visible text in order, the warning's "(probe warning)" after it.
- The toasts covered the queue's row actions when the focus reached them (2.4.11): on a focused
  element they cover, they go to the other end of the window, and where they would cover it
  there too they go out of sight until the focus moves on.
- Firefox gives the editor's tab panels (a scroller) a Tab stop: it shows a ring now.
- The job log's scroller showed no ring (PrimeVue's `outline: 0`); G's `main.css` now does it
  for every VirtualScroller, so the local rule went.
- Settings → Tools painted its read-only path in the disabled colours (4.07:1 in dark): the
  text keeps the text colour.

Strings and numbers:

- Through `n()` / `Intl` with the app's locale: the queue's fps, speed and percent, preset
  bitrates and quality values, the preset tree's counts, the numbers of the preset changes, the
  browser title's progress, and the InputNumbers of Settings → Preview and Queue (and the
  sandbox's) get `:locale`.
- Lists through `Intl.ListFormat` (`formatList` in `components/shell/format.ts`: `plain` lists
  names, `and` reads as part of a sentence): the file browser's filter, the first-run
  variables, the *Use bundled* note, the preset details and changes.
- One message instead of joined pieces: a step's kind and number, an encoder and its state, the
  login refusal, a preset change's members and numbered items, a value on its scale, the web
  title with the progress.

### Choices

- `·` between the facts of one line (a source's line, the status bar's queue summary, an
  activity's details, a codec rule) is a separator, not a list; it stays.
- Pixel sizes (`1920×1080`), clock times (`1:02:05`), episode codes (`S01E05`) and
  `aria-keyshortcuts` values are written as they are, without `n()`.
- After a keyboard sign-in the login screen goes and the focus is on the page, as after a page
  load: the first Tab reaches the navigation rail.

### Known-list entries left

- `presets`, dark, `indicator-contrast` on the selected preset: not a fault of the page. The
  selected row's fill is see-through (16 % of the primary colour), and the probe read canvas
  colours as if `getImageData` gave them premultiplied, so it took the fill for a light colour.
  Against the real fill the ring is 5.4:1. K2 fixes the probe and removes the entry.
- The header's Range button (`toast`) was the tracks area's; K3 fixed it and removed the entry.
- The queue's `obscured` entries (the row actions under the toasts, "Retry" in Chromium only,
  which came and went with the toasts' timing) are gone with their cause.

### Tests

Unit tests (jsdom) for each fix where the behaviour is in the component; the browser-only paths
in `keyboard-shell.spec.ts` (Ctrl+O and Enter to the workspace, a group edited from its context
menu, Tab both ways in the preset picker). Each test was checked by a mutation of the code it
covers: the test failed, and passed again after the restore.

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

**A fault of the gate, fixed.** The `video-advanced` screen in dark reported
`indicator-contrast` 1.23:1 on the reset and help buttons of a changed option. The page was
not at fault. `probe.ts` reads a colour by painting it on a canvas, and it treated
`getImageData` as premultiplied (`r * 255 / a`). The data is straight RGBA:
`color(srgb 0.506 0.549 0.973 / 0.1)` reads as `128,137,245,26` in both browsers (checked).
So a translucent background, here the 10 % tint of a changed row, became a backdrop close to the
ring's own colour. As painted, the ring is 5.2:1 on that row. The probe now takes the data as
it is. A test in `gate-checks.spec.ts` puts a white ring on the rail over white at 50 % on
black, which is mid grey and 3.95:1. It must give no finding, and it failed with the old line
in both browsers. A light grey ring (2.36:1) must still be reported. With the fix, the two
`video-advanced` entries went away, and so did the shell's dark `presets` entry on the preset
row (1.1:1). A run of the whole gate on the merged state changed no other finding.

**Known entries left in `known/picture.ts`.** One: on `crop-manual` (a whole-page screen), the
shell's source row (K1's component). It goes when K1's fix merges.

## Task K3: the tracks and the batch

Built on 2026-11-13 on Linux (this host), headless Chromium and Firefox. Phase 1 used the
area's own Playwright scripts against `scripts/dev-server.py`: a Tab walk on every screen of
the area, with the focus judged by its computed outline and shadow and by a pixel diff of the
stop focused and blurred. Phase 2 used the gate on ports 8740/8741.

### What was found and fixed

| Screen | Defect | Fix |
|--------|--------|-----|
| `range` | Arrowing through the modes checks each one (native radios, as APG asks), and each mode converted from the previous mode's conversion: ↓ from *Whole source* ended at *Frames 0–125*, cutting the last 21 ms of `chapters.mkv` | A mode converts from the last range the user set: while the arrows pass, that is the range the popover opened with. A range picked or typed in a mode becomes the base of the next. One undo step per mode stays |
| `range` | Both the checked and the first radio were tab stops; the popover's focus trap wrapped onto the unchecked *Whole source* | Roving tabindex: only the checked mode takes Tab (all take it when the checked mode is disabled) |
| `range`, Summary | Frame and chapter numbers written raw (`Frames 0 – 1440`) | `rangeLabel` takes `n` |
| `language-picker` | Reopened after a search, the first option (*As the source*) was active, so Enter changed the language | The query watcher runs at once (`flush: 'sync'`) and no longer undoes the chosen option `show` marked |
| `language-picker` | The scrolling listbox was its own tab stop (browsers make a scroller focusable) | `tabindex="-1"`: the search drives it (APG combobox) |
| `language-picker` (and its uses) | The trigger copied a field's focus ring, which has no width: a faint border change only | The app's focus ring |
| `matrix` | A row's popover with notes and no fix kept the focus on the cell; the popover lives outside the dialog, so its notes were out of reach | The summary takes the focus, and `tabindex="0"`: PrimeVue's focus trap counts a summary only by its tabindex |
| `matrix` | The rows' virtual scroller is a tab stop without an outline | The shared layer's ring (`main.css`) |
| `matrix` | `label-content-name-mismatch` on a track cell: the streams and the message had no space between them (`#3 #42 tracks`) | A space; the cell's state list goes through `formatList` |
| `naming-editor`, `summary` | `label-content-name-mismatch` on the variable chips: the name put the value in parentheses, which axe leaves out, and the code and the value ran together | `Insert {name}: {value}`, and a space between code and value |
| `toast`, `crop-manual` (the header) | `label-content-name-mismatch` on the Range button: label and length ran together | A space |
| `defaults` | Escape on a closed drop-down did not close the dialog | See below |
| strings | `toFixed`/`String()` numbers: DRC, sample rates, gain, bitrates, subtitle events, parse scores, frame numbers; hand-joined lists: skipped folders, a matrix cell's state; the output folder and its origin read as one word | `n()` (`kiloHertz(rate, n)`), `formatList`, a space. InputNumbers take `:locale` |

Each fix has a unit test that failed before it, or, for what only a browser shows, a test in
`e2e/a11y/keyboard-tracks.spec.ts` (the Range pass-through and its tab stop, the language
picker reopening and its Tab order, the matrix notes' focus). Every test was checked by a
mutation of the code it covers.

**Escape in the defaults dialog.** `keyboard.ts` lets a closed Select's Escape go on, but the
Select has also called `preventDefault`, and the dialog's own handler takes a prevented Escape
as handled by something inside (it closes only on an Escape nothing else used). So the dialog
keeps its capture handler for a closed combobox; the unit test sends cancelable events, as a
browser does, with `keyboard.ts` installed. The Range popover's handler is gone: PrimeVue's
Popover closes on any Escape that reaches the document.

### Known list

`known/tracks.ts` keeps one entry, the picture area's: the `subtitles` screen shows its
ScanControl (`label-content-name-mismatch` on `button.scan-control__start`), which task K2
fixes and removes. This task also removed its Range button from `known/shell.ts` (`toast`) and
`known/picture.ts` (`crop-manual`), and its chips from `known/picture.ts` (`summary`).

### Not changed

- The frame and time fields of the Range popover show raw numbers: they are typed and parsed.
- Lines of facts joined with ` · ` (stream labels, a track's summary, a language's codes) are
  kept: separators of data, not a sentence.
- Tab in the naming template's open `{` list takes the suggestion and keeps the focus in the
  field (shell completion); a second Tab moves on.
- The matrix keeps a table of buttons (one tab stop per cell), not an APG grid.

### Found in other areas (sent to their owners)

- The sources panel (K1): Enter or Space on *Edit group* inside a group's tree item was taken
  by the tree (it folded the group).
- The shared layer (G, all done there): Select's Escape, the menu's first item, the form-field
  ring, the menu item's ring, the virtual scroller's ring.

## Review and fix round

Two fresh reviews (Opus 5.5, `effort: high`) of `d222ee7..41178b6` were given the code and this
record's Decision, not the builders' accounts:

- R1 asked whether the gate checks what item 1 claims.
- R2 walked the keyboard paths and the strings area by area, and tested the tests.

The lead reproduced the three majors with the reviewers' scripts on ports of their own.

**The majors:**

- **R1-1: whole-page walks stopped at the end of the page.** In Chromium the walk stuck on the
  last element; in Firefox it left the page. So the workspace header, the source items, the
  editor tabs and the login field were never judged. Removing their focus styles passed the
  gate on `toast`, `crop-manual`, `summary`, `group` and `login`.
- **R1-2: regions hid UI that appears only on regioned screens.** These were the season group
  in the sources tree, the settings links and the status bar's error state. A whole-page axe
  run on `group` found a real `label-content-name-mismatch` (2.5.3) on the group row and its
  members, in both browsers and both themes.
- **R2-1: Tab or Shift+Tab in any PrimeVue popup Menu sent the focus out of the page.** The
  menus are *Add track*, *Preset actions*, *Name choices*, chapter *Export*/*Reset* and
  `Field`'s override menu. PrimeVue hides the menu on Tab without giving the focus back.

**The fixes**, each with a test that failed first, in two parallel tasks with disjoint files:

- **FG (`frontend/e2e/**`)** widened the gate. Its sub-section under Task G has the details:
  - walks start at the top of the page;
  - axe runs on the whole page of every screen;
  - new whole-page screens `settings` and `status-error`;
  - each stop is judged by its own indicator, and items reached by arrow keys are judged too;
  - the probe paints as the browser does: opacity, gradients, clipping, pixel comparison over
    pictures;
  - new findings `trap`, `region-exit` and `unreached`;
  - motion is checked after the walk;
  - axe's open contrast nodes are measured;
  - a known entry needs its rule and its exact target.

  Every check has a proof by mutation in `gate-checks.spec.ts`. The wider gate found new real
  findings: Firefox scroll boxes whose ring was clipped, a 2.88:1 ring on the magnifier, and
  `target-size` under the command drawer.
- **FP (`frontend/src/**`, two phases)**, in its own sub-section:
  - phase 1 fixed R2-1 once in `base/keyboard.ts`, R1-2's group row (the sources tree is flat
    now), the focus lost after a move to another view, the Dialog's late refocus undoing a
    fast Tab, the four identical names in Settings → Tools, two weak tests and three joined
    strings;
  - phase 2 fixed FG's new findings (an inset ring on scroll boxes, the magnifier ring, the
    Video tab laid out above the drawer) and emptied the known lists.

**The lead's checks.** Each task was merged with `--no-ff` and broken once by the lead; its
tests failed and passed again after the restore. The merges were G, K1–K3 (both phases),
FG and FP.

R1's mutation spec was run again against the widened gate. Every mutation it makes is now
caught on at least one screen. The ones a regioned screen still passes are caught on the
screen that shows that part whole:

- the header: `toast`, `crop-manual`, `group`;
- the settings links: `settings`;
- the status bar's error: `status-issues`.

**The end state (2026-11-14, ef2e7c9):**

- The three known lists and the script-text allowlist are empty.
- On Linux:
  - `uv run ruff check`, `ruff format --check`, `mypy`, `mypy --platform win32`: clean.
  - `uv run pytest -m "not needs_gpu"`: 7798 passed, 2 skipped, 26 deselected.
  - `npm run lint`, `fmt:check`, `typecheck`: clean.
  - `npm test`: 2147 passed. `npm run test:server`: 105 passed. `npm run build:web`: built.
  - `npm run e2e`: 198 passed, twice in a row, 7.7 min each. Before F-16 it was 24 tests in
    1.3 min.

**Recorded, not fixed:**

- Item 5 stands: small windows, server messages, WebKit (F-17), screen readers and the native
  dialogs are not in F-16. The owner was asked whether small windows belong in F-16; the
  default "later" stands until an answer.
- **Joined strings and the script-text check:**
  - The visually hidden `{severity}: ` prefix of an issue is split across elements in nine
    components. It needs one `{severity}: {message}` message when a second locale comes.
  - The ` → ` of the picture pipeline would point the wrong way in a right-to-left locale.
  - The script-text check's remaining blind spots are listed in FP's sub-section: `String()`
    and `${x}` numbers, hand-made plurals, `push`/`map`/`join`, joins across elements.
- **What the gate does not judge:**
  - It does not judge arrow-key moves in radios, sliders or closed comboboxes, because the
    arrows change their value.
  - Axe's open nodes behind a modal mask, nodes re-rendered before the probe looks, and nodes
    over images stay unmeasured. FG counted them, one run each (Chromium / Firefox): 41 / 41
    behind a mask, 17 / 12 re-rendered, 6 / 4 over an image.
  - The smooth-scroll check skips a scroll within 300 ms of another scroll or a focus change.
    This rule has no test.
- **The sources tree.** A season group's row now has its visible button texts in its name
  (*… Edit group Check group Add group to queue*). Axe asks for the visible text in the name,
  and the buttons sit in the row.
- **Sign-in.** After a keyboard sign-in the focus is on the page, as after any page load.
- **Flow 4 in Chromium.** The snap-note check ("Left 17 → 16" read as "Top …") failed twice
  under load, once in G's baseline and once in K3's run. It passed in every later run, the
  final two included. It is flow 4's, not F-16's.

### Review fixes (FP)

Phase 1, on 2026-11-14 on Linux (this host): headless Chromium and Firefox of Playwright 1.64.1
against `scripts/dev-server.py` (the e2e fixtures, the pinned FFmpeg), own scripts that print
the focused element after each key, before and after each fix. Each fix has a unit test that
failed before it (or a test of the i18n check where English shows no defect), and each test was
checked by a mutation of the code it covers.

The menu's Tab follows the WAI-ARIA APG menu pattern (read on w3.org on 2026-11-14): "When
focus is on a `menuitem` in a `menu` or `menubar`, move focus out of the `menu` or `menubar`,
and close all menus and submenus." A popup menu sits, for the tab order, where its button is.
Both browsers continue a Tab from an element that a capturing `keydown` listener focused
(checked with a plain page), so the fix leaves the next and the previous element to the browser.

| Finding | Fix | Test |
|---------|-----|------|
| Tab or Shift+Tab in an open popup `Menu` left the focus on the page (Chromium: the window lost it), then the nav rail or the status bar | `keyboard.ts`: on Tab in a popup Menu the focus goes back to its menu button (the element named by `aria-controls`, else the one the list took the focus from), and the browser's own Tab moves on from there, both ways. PrimeVue still closes the menu | `keyboard.test.ts`; in both browsers Tab and Shift+Tab from *Preset actions* and *Add track* now land where they land from the closed button |
| A link from the workspace to another view (the status bar's *Queue* link, *Open presets*) left the focus on the page | `focus.ts` `refocusAfterNavigation`, installed by `App.vue`: after a move to another view, a focus that went away with the old view goes to the new view's heading (`tabindex="-1"`), or for the workspace to `focusWorkspace()`. The first view of a page load takes none | `focus.test.ts`, `App.test.ts`; both browsers land on the heading |
| A Tab pressed during a Dialog's enter transition was taken back | `dialogFocus.ts`, installed by `main.ts`: PrimeVue's `onAfterEnter` focus is skipped when the focus is in the dialog already | `dialogFocus.test.ts`; in both browsers with motion on, Ctrl+O then Tab at once stays on *Cancel* (before: back on the list 800 ms later) |
| `label-content-name-mismatch` on the sources tree's group row and its members | The tree is flat, as the preset tree: members are tree items of level 2 after their group, with `aria-setsize`/`aria-posinset`; the group row has no `aria-labelledby` (its name is its content); a member's status, episode and file name are separate words. The edited group's bar runs on down its members (`::before`) | `SourcesPanel.test.ts` (the order and places; names computed as axe joins inline text); axe on the panel with a season group and with the `chapters` + `letterbox` group: no violation in either browser or theme. Home, type-ahead, the arrows, Shift+F10 unchanged |
| Settings → Tools: four fields and buttons with the same names | *Path override for {tool}*, *Test {tool}*, *Use bundled {tool}*, *Remove override for {tool}* (`aria-label`, the visible text first) | `ToolsSection.test.ts` |
| Tests that did not catch a defect | `index.test.ts`: a `{n}` message as `t(key, {other}, count)`; `motion.test.ts`: smooth `scroll` and `scrollBy` | mutations `named.n ??= second`, and the method list without `scroll` or `scrollBy`, now fail |
| Joined pieces | One message each: the Summary's filter chip (`{label}: {value}`), the rule table's row header (`Rule {n}` for screen readers, the number shown with `n()` and hidden from them), the Range button's issue description (`{severity}: {message}`) | the script-text check (below) failed on the chip before the fix |

**The script-text check** (`scriptText.ts`) now also reports `toPrecision` and a
`toLocaleString()` without a locale where a number becomes text, and values a template puts side
by side in a fixed order: `{{ a }}: {{ b }}` (any punctuation between them but ` · ` and `×`,
the data separators kept by K1 and K3), and a translation next to a value that is not one
(`{{ t('x.rule') }} {{ n }}`). On the whole code base it found the chip and nothing else.
Not taught, with the reason:

- A template literal that joins values with punctuation and no words (`` `${a}: ${b}` ``):
  in this code base nearly all of them are ids, keys, paths and ratios (about 60 findings), so
  the Range button's description was fixed by reading, not by the check.
- `String(x)` and `` `${x}` `` in a translation's values, `new Intl.NumberFormat()` without a
  locale, `Math.round` with words: the check has no types, so it cannot tell a number from a
  string.
- Text that reaches the screen through a variable, a function's return value, an array or an
  object built first, `push` and `map` before a `join`, a hand-made plural (`n === 1 ? … : …`),
  a `computed` bound to a `header`, and a raw `{{ count }}` in a template.
- A join across elements (`<span>{{ t('x') }} </span>{{ y }}`, the form the rule table had).

**Not changed:**

- The ` → ` arrow in the picture pipeline would point the wrong way in a right-to-left locale;
  English is the only locale.
- The severity prefix written before a visible message in nine components
  (`<span class="rf-sr-only">{{ severityLabel(…) }}: </span>`): the same pattern as the Range
  button's, with its colon outside a message, but split across elements; it needs one
  `{severity}:` message when a second locale comes.
- Task G's note that a Tab during a Dialog's enter transition goes to the page behind: in both
  browsers the modal dialog's focus trap focuses `[autofocus]` as the dialog mounts, so the Tab
  went inside the dialog and the late focus took it back. That is what `dialogFocus.ts` fixes.

**Phase 2** (on m10-hardening with FG merged, 95c4f10). FG's wider gate listed three new causes
in the known lists. All three are fixed, and the lists are empty. Before each fix, the gate ran
on the old code with the lists emptied and failed on the screens below. After the fixes, the
same screens passed (16 of 16).

| Gate finding | Fix |
|--------------|-----|
| Firefox makes a box that scrolls a Tab stop. Its ring (2 px, 2 px outside) was cut away by a clipping ancestor: the tab list viewport (`toast`, `status-error`, `crop-manual`, `group`), the preview panel's content (the same screens and `preview-frames`, `split-compare`), the settings body (`settings`); "1.00:1 on self" or "766 px at 3:1, 1886 needed" | `main.css`: a focused element that is not a control and has no `tabindex` (a box focused only because it scrolls) draws its ring inside itself. The other elements keep their rings. `video` and `audio` keep theirs too: in the first full run, the preview clip's `<video controls>` (`preview-clip`, Firefox) put its inset ring on the picture, and the change fell below the gate's pixel count. `:focus-visible` only, so a mouse user sees no change |
| `crop-manual`, light, both browsers: the magnifier's *Previous frame* button at the first frame (`aria-disabled`, kept focusable) faded its whole box, the ring too: 2.88:1 | `CropMagnifier.vue`: the icon and the border fade, not the button, so its focus ring keeps its colour |
| `command-drawer`: axe `target-size`. The sticky drawer lay over the Video options, so an option partly under it kept less than 24 px (Chromium: the frame-rate mode's help button; Firefox: the RF field and the slider handle) | The Video tab is as tall as the panels (`100cqh`). Its options scroll in a box of their own, with the drawer below them, so no option goes under the drawer. With the overlay gone, the drawer-height variable and its `ResizeObserver`, the panels' `scroll-padding-bottom` and the drawer's side-padding gradient are removed. `e2e/layout.spec.ts`: the test that the drawer painted over the side padding (where a field's bar showed through) is now "the open command drawer covers no Video option, the options scrolled to the top or the end". On the old code it failed in both browsers (145 px of an option under the drawer, at the top) |

`CommandPreview.test.ts` loses its test of the drawer-height variable, because the variable is
gone.
