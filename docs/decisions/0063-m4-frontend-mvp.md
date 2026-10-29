# 0063 — M4, the frontend MVP: dependencies, the shared skeleton, and the open choices

- Status: accepted
- Date: 2026-10-29
- Steps: F-1, F-2, F-3, F-4, F-5, F-6, F-9, F-10, F-12, F-14, F-15, F-17, F-18

## Context

M4 is the first usable GUI ([08 §M4](../plan/08-roadmap.md#m4--frontend-mvp-web)). Its steps
(06 Part B) are built by thirteen tasks in five waves ([m4-breakdown.md](../m4-breakdown.md)),
several at the same time, so each task must own its files and code against fixed contracts.
The plan names the stack and the structure, but leaves open:

- three packages it names are not installed yet: `openapi-fetch`, VueUse, Playwright; and
  undo as "JSON patch history" and client-side fixes ("a fix is a JSON patch on
  `JobSettings` … applied on the client", 03 §Validation) need an RFC 6902 implementation;
- how the i18n messages are split, so that parallel tasks never edit one file;
- who owns the stores that mirror the server, and the store and component contracts;
- how a browser in `--auth token` mode gets the token;
- which tabs show while only four of the eight are built; which Settings sections are
  "basic"; the job type line of 03 §Remux-only jobs;
- how the tasks run a real server for their browser checks without touching the owner's
  folders, and how Playwright is kept headless (the owner's displays; the breakdown's rule 6).

What the packages are (checked on 2026-10-29 with `npm view`, npm 12):

```console
$ npm view openapi-fetch@latest version license dependencies
0.17.0  MIT  { 'openapi-typescript-helpers': '^0.1.0' }      # 2026-02-11
$ npm view @vueuse/core@latest version license peerDependencies engines
15.0.0  MIT  { vue: '^3.5.0' }  { node: '>=22' }             # 2026-09-16
$ npm view @playwright/test@latest version license
1.64.1  Apache-2.0
$ npm view rfc6902@latest version license                     # no dependencies
5.3.0   MIT                                                   # modified 2026-07-23
$ npm view fast-json-patch@latest version
3.1.1                                                         # last release 2022-06-17
$ ls ~/.cache/ms-playwright
chromium-1248  chromium_headless_shell-1248  ffmpeg-1013  firefox-1555
```

The browsers in the cache are the ones `playwright@1.64.1` (D-0's spike) installed, so
`@playwright/test@1.64.1` uses them without a download. openapi-fetch 0.17.0 type-checks
against the generated `schema.d.ts` with TypeScript 6.0.3 (a call with a wrong body fails
`vue-tsc`; checked with a scratch file).

`npm audit` on `main` (before any change) reported one high-severity advisory: `undici`
8.11.2, a dependency of `jsdom` 30.1.2 (dev only), fixed in 8.12.x. CI runs
`npm audit --audit-level=high` (Q-1.3), so this would have failed it.

## Decision

1. **Dependencies.** `openapi-fetch ^0.17.0`, `@vueuse/core ^15.0.0`, `rfc6902 ^5.3.0`
   (dependencies) and `@playwright/test 1.64.1` (dev, exact: its browser build must match the
   cached one). `rfc6902` over `fast-json-patch`: maintained, no dependencies, and it has both
   `applyPatch` and `createPatch` (undo needs the inverse of a change). `npm audit fix`
   updated only the lock file: `undici` 8.12.3, inside `jsdom`'s range; `npm audit` is clean.
   No other package: drag reorder uses PrimeVue's `DataTable` row reorder, and long lists use
   PrimeVue's `VirtualScroller`.
2. **i18n.** One message file per area, `src/i18n/messages/en/<area>.json`, holding the keys
   of `<area>.` (`video.json` → `t('video.…')`); `src/i18n/index.ts` collects them with
   `import.meta.glob`. Each task writes only its own area. The tab and view names are in
   `app.json`. Task A builds the check of 0043 item 8 as a Vitest test (so `npm test`, which CI
   runs, fails on literal text in a `<template>`), together with a check that every key the
   code uses exists.
3. **Store ownership.** The stores that mirror the server and are kept by events (`system`,
   `tasks`, `queue`, `settings`) belong to the API task (F-2): their consistency after a lost
   connection or a gap is one problem, solved in one place. The screen tasks use them. The
   stores and their contracts are in the breakdown and in the skeleton's files.
4. **A token in web mode** reaches the app through the address fragment `#token=…`, which the
   browser never sends to a server and which the app removes from the address at once, or
   through the login screen. It is kept in `sessionStorage` for the tab. The desktop build gets
   its token from `Platform.backend()`; password mode uses the session cookie.
5. **Tabs of later milestones** (Dimensions, Filters, Chapters, Tags) are not shown until they
   are built; their `Ctrl+N` (the tab's place in 03's order) does nothing. A validation path in
   such a tab is shown on Summary.
6. **Settings in M4** ("F-15 basic"): Tools, Encoders, Output, Queue, Appearance. Languages
   (the `LanguagePicker`, M6) and Preview (F-7, M8) come with their milestones.
7. **Summary**: the job type and its reason (03 §Remux-only jobs) come with M6, which builds
   remux and metadata-edit jobs in the UI; the Source card's thumbnail is one frame from
   `POST /api/preview/frames`, in F-6.
8. **Two naming components** instead of one: `NamingOptionsEditor` edits `NamingOptions`
   (Settings → Output, the preset editor) and `JobNamingEditor` edits the open job's naming
   (the Summary card). They share F-18's parts (template field, chips, parsed-name panel,
   preview).
9. **`IssueList`** joins the base components: the Summary Issues card and the status bar list
   issues the same way (fix buttons, a link to the field).
10. **Add all** (03 §App layout) drafts every open source with the editor's preset and adds
    those without errors; the others are listed in a toast. Batch groups (M7) change this.
11. **A real server for every browser check**: `scripts/dev-server.py` starts
    `reframe-server --mode web --auth token` in a new temporary home (config, data, cache,
    media root, output root), with `REFRAME_POWER_DRY_RUN=1` and the fixtures copied in, and
    removes the home when it stops. Each task has its own port range (87N0–87N9). The Vite dev
    server reads `REFRAME_DEV_PORT` and `REFRAME_DEV_BACKEND`.
12. **Tests against a real server** are `src/**/*.server.test.ts`, Vitest's `server` project
    (`npm run test:server`, Node environment, one file at a time). `npm test` runs the `unit`
    project only, because CI's frontend job has Node and no Python.
13. **Headless only.** `playwright.config.ts` sets `headless: true` in every project and uses
    the list reporter: the HTML reporter opens a browser when a test fails. `package.json` has
    `e2e` (`playwright test`) and no `--ui`, `--headed` or `open` script; `vite.config.ts` has
    no `server.open`. Headed checks are the lead's, through the D-0 window guard.
14. **The queue-processing event** of 0042 open question 5 is task S, recorded in
    [0064](0064-queue-processing-event.md).

## Consequences

- An agent that needs another package, route, tab or a change of a lead-owned file asks the
  lead; the contracts change only through this record.
- `notBuilt()` marks the skeleton's stubs; when M4 is done, nothing calls it and it is
  removed.
- The fragment token is visible in the address bar until the app reads it, and in the
  browser history only as the address without it (the app replaces the entry).

## Plan changes

- [06 §Structure](../plan/06-web-app.md#structure): the new folders, stores, composables and
  the per-area message files.
- [06 §F-3](../plan/06-web-app.md#f-3-app-shell): tabs of later milestones are hidden.
- [06 §F-15](../plan/06-web-app.md#f-15-settings-view): the M4 sections.

## Task A — F-1 design system

Choices where the plan leaves one, and the check behind each:

1. **Colours live in the PrimeVue preset** (`styles/theme.ts`), not in our CSS, so that one
   dark class (`.reframe-dark`) switches PrimeVue and our components together. Our own colour
   tokens are custom semantic keys of the preset, which PrimeVue writes as CSS variables:
   `--p-app-background`, `--p-app-border-color`, and `--p-status-{error,warn,info,ok,busy,off}-{color,background,border-color}`.
   `styles/tokens.css` adds spacing (`--rf-space-1…6`), radius, typography and aliases
   (`--rf-color-text`, `--rf-color-primary`, …). Aura's defaults fail WCAG AA in places, so the
   preset changes them: light primary 600 instead of 500 (white on indigo-500 is 4.47:1), light
   muted text slate-600, input borders slate-500 / zinc-500 (Aura's slate-300 is 1.5:1 against
   the field, WCAG 1.4.11 wants 3:1), light invalid border red-600. Check:
   `styles/contrast.test.ts` mounts PrimeVue with the preset, reads the `--p-*` variables it
   writes for `:root` and for `.reframe-dark`, and requires 4.5:1 for every text pair (text,
   muted text, primary, each status colour on the surfaces and on its own background, white on
   primary, field text and placeholder) and 3:1 for field and status borders, in both schemes.
   Breaking a colour on purpose (dark muted text zinc-600, light primary 500, dark field
   border zinc-700) fails it.
2. **Density** is `<html data-density>`. `compact` sets the root font size to 87.5 % and
   overrides PrimeVue's semantic padding tokens on `:root` (form field, list option,
   navigation item, popover and modal padding, icon-only button width, DataTable cells) and
   `--rf-density` (0.75), which scales our spacing. This works because PrimeVue's component
   tokens are declared on the same element and refer to the semantic ones with `var()`.
   Checked in the browser: the root font size goes from 16 px to 14 px and the controls get
   tighter.
3. **`prefers-reduced-motion: reduce`** sets `--p-transition-duration` and `--rf-duration` to
   0 and cuts every animation and transition to one 0.01 ms run (the busy dot stops turning,
   the reveal highlight does not fade). `useReveal`'s `scrollIntoView({ behavior: 'smooth' })`
   is JavaScript and not covered by CSS (see the report to the lead).
4. **Theme storage.** `useTheme` keeps `{ theme, density }` under `localStorage`
   `reframe.appearance` (read and write in `try`, a value it does not know is ignored), so
   `initTheme()` paints the first frame right. Once the settings store has loaded, a choice is
   also written with `settings.set('/appearance/theme' | '/appearance/density', …)`; a settings
   value that arrives later or changes wins and is copied to `localStorage`. While its own
   writes are in flight, `useTheme` does not take settings answers (an answer to an older
   choice would flash the old theme); after the last one it takes the settings value if it
   changed in between, and keeps the local choice if a write failed. Another tab's change
   arrives through the `storage` event. `system` follows `matchMedia('(prefers-color-scheme:
   dark)')` live. `useTheme()` starts following the settings store on its first call, so the
   app must call it once at start (the shell's theme switch does). Checked by
   `composables/useTheme.test.ts` with a test double of the settings store, and in headless
   Chromium: theme and density switch at once, survive a reload, and `system` follows an
   emulated change of the colour scheme.
5. **Base components** wrap PrimeVue (Button, Popover, the Tooltip directive, imported locally
   so that the components work without the global directive). Additions to the contract,
   all optional: `FieldSlotProps.labelId` (for group controls, `aria-labelledby`),
   `RoleBadge.kind` (`'subtitle'` names `description` "Descriptions"), `StatusDot.showLabel`,
   the CSS class `rf-kv-list` for a `<dl>` of `KeyValue`s, `rf-sr-only`. `Field` sets
   `aria-describedby` itself on the element with its slot's `id`, because InputNumber, Select
   and ToggleSwitch do not pass the attribute on. A field with an error or a warning gets a
   coloured bar in the gutter (any control) and the coloured border on PrimeVue's inputs,
   selects, text areas, check boxes, radio buttons, toggles (the focus border stays the
   primary colour). A heuristic `RoleBadge` has a dashed outline, a title one a solid outline;
   the evidence is also in a screen-reader-only text, since PrimeVue's tooltip opens on hover
   only. `StatusDot` tones differ in shape as well as colour (circle, turning arc, diamond,
   square, ring).
6. **The i18n checks** (`src/i18n/checks/`, run by `npm test`; `codebase.test.ts` runs them
   on every `src/**/*.vue` and `src/**/*.ts` except tests, `*.d.ts` and the checks):
   - *Literal text*: the `<template>` is parsed with `@vue/compiler-sfc`. It is literal text
     when it contains a Unicode letter (`\p{L}`) and is (a) a text node, (b) the value of a
     static attribute a user sees: `title`, `alt`, `placeholder`, `aria-label`,
     `aria-description`, `aria-roledescription`, `aria-placeholder`, `aria-valuetext`, and the
     PrimeVue text props `label`, `header`, `footer`, `subheader`, `legend`, `message`,
     `summary`, `detail`, `tooltip`, `badge`, `on-label`, `off-label`, `accept-label`,
     `reject-label`, `choose-label`, `upload-label`, `cancel-label`, `empty-message`,
     `empty-filter-message`, `empty-selection-message`, `selection-message`,
     `filter-placeholder`, `current-page-report-template` (kebab or camel case), and `value` on
     `Tag`, `Badge`, `Chip`, `OverlayBadge`; or (c) a string literal inside `{{ }}`, inside a
     bound one of those attributes (`:label="'Save'"`) or in `v-tooltip`, `v-text`, `v-html`,
     except the first argument of `t`, `$t`, `te`, `tc`, `tm`, `rt` and an operand of
     `===`, `!==`, `==`, `!=`. Symbols, digits and punctuation pass (`·`, `→`, `×`, `%`,
     `—`, `ⓘ`). Comments, other attributes (`class`, `id`, `data-*`, `severity`, `icon`,
     `value` on an input) and `<script>` are not read.
   - *Message keys*: every literal first argument of `t`, `$t`, `te`, `tc`, `tm` (also as a
     method, `i18n.global.t`) and every `<i18n-t keypath>` must name a message in the English
     messages (`en` of `i18n/index.ts`); `tm` must name a group. Keys built at run time
     (`t('a.' + x)`, a template literal with `${}`) are not seen: write each key as a literal
     (a `switch` over the values, as `RoleBadge` does) so that the check covers it.
   Both have tests that fail on bad input (`literalText.test.ts`, `messageKeys.test.ts`), and
   putting `<h1>Sandbox</h1>` in a view or a wrong key in a component fails `codebase.test.ts`.
7. **The sandbox** (`/sandbox`, dev only) has its own theme and density switch and shows each
   component in its states; it fills `system.languages` with five sample languages when no
   server has sent them, and gives the validation store one issue so that the store path and
   `ui.reveal` can be tried. `npm run build:web` has no Sandbox chunk (the route is behind
   `import.meta.env.DEV`); `sandbox.json` is still in the main bundle, because `i18n/index.ts`
   loads every message file.

## Task B — F-2 API layer and events

(Written by task B.)

## Task C — F-3 app shell

(Written by task C.)

## Task D — F-4 editor state

(Written by task D.)

## Task E — F-5 sources panel and the file browser

(Written by task E.)

## Task F — F-18 naming editor

(Written by task F.)

## Task G — F-6 Summary tab

(Written by task G.)

## Task H — F-9 Video tab

(Written by task H.)

## Task I — F-10 Audio and Subtitles tabs

(Written by task I.)

## Task J — F-12 presets UI

(Written by task J.)

## Task K — F-14 queue, activity and job log

(Written by task K.)

## Task L — F-15 settings

(Written by task L.)

## Task M — F-17 Playwright set-up and flow 3

(Written by task M.)
