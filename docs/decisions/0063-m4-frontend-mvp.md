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

Built: `api/client.ts`, `api/credentials.ts`, `api/text.ts`, `api/events.ts`, `api/mirror.ts`,
`api/dispatch.ts`, `api/boot.ts`, the stores `system`, `tasks`, `queue`, `settings`, and
`i18n/messages/en/api.json`. Test helpers in `api/testing/` (a fake server and socket for unit
tests; `devServer.mjs`, `tapSocket.ts` and `serverHelpers.ts` for the `*.server.test.ts` files).

### What was checked against the real server (2026-10-29)

`reframe-server` through `scripts/dev-server.py`, Node 26.12.1 (its `WebSocket` and `fetch` are
undici 8.12.2), headless Chromium of `@playwright/test` 1.64.1:

1. **`Origin` of the event WebSocket.** Node's `WebSocket` sends no `Origin`: accepted, hello
   received. With `Origin: http://evil.example` (undici takes headers as a second argument) the
   upgrade is refused with HTTP 403 (uvicorn logs `connection rejected (403 Forbidden)`), and the
   client sees only an `error` and close code 1006 — the same as a server that cannot be
   reached. With the server's own origin: accepted. Chromium sends the page's origin, so the
   served app is accepted. Consequence: a page on an origin the server does not accept (the
   Vite dev server without `--cors-origin`) keeps reconnecting with the backoff; nothing in the
   close tells the client why.
2. **Auth of the event WebSocket**: a wrong token, `{"type": "auth"}` without a token in token
   mode, and a first message that is not an auth message each close with 4401 at once; no
   first message closes with 4401 after 5.0 s. In password mode `{"type": "auth"}` with the
   session cookie (sent by the browser; in Node through the `cookie` header) gets the hello.
3. **The hub subscribes before it sends the hello** (`_Stream.__init__` in
   `reframe_server/events.py` runs before `send(Hello…)`): a read sent after the hello misses
   no event.
4. **Problems**: a 401 is `application/problem+json` with `code` `auth.required` /
   `auth.invalid`; a 404 of an unknown job is `{"title": "No job …", "code":
   "queue.unknown_job"}`. In password mode the session cookie is `reframe_session`, `Path=/api`,
   `HttpOnly`, `SameSite=Strict` (as Chromium stored it); after a logout the old cookie gets 401.
5. **Under the app's CSP** (`script-src 'self'`), Playwright's `page.waitForFunction` with a
   string predicate fails (`'unsafe-eval'` is not allowed); `page.evaluate` with a function
   works. (For task M.)

### The resync design

Each mirrored state has a **mirror** (`api/mirror.ts`): a snapshot read, the store's event
handler, and a log of events per read under way.

- Every event a store mirrors goes through `mirror.event`: it is applied at once (the screens
  never wait for a read) and appended to the log of each read in flight. When a read's answer
  comes, the state is replaced by it and the logged events — those that arrived after the read
  was sent — are applied again on top, in order. So an event that arrives while a snapshot is
  in flight is never lost.
- An event that arrived **before** the read was sent is older than the answer (the server sent
  it before it got the request) and is not applied again. An event that arrived **after** may
  be older or newer than the answer, so the handlers are written to reach the same end state
  either way: (a) events that carry a whole value per key (`queue.changed`, `job.progress`,
  `task.*`, `tools.changed`, `capabilities.changed` per encoder, `power.countdown`,
  `queue.processing`) — the core publishes an event for every change and the server sends them
  in order, so for each key the last event is either newer than the answer or carries the value
  the answer has; (b) `job.state` is a transition and is applied only when the job is in its
  `previous` state, so an older one changes nothing and a replayed chain of transitions ends
  where the server is; (c) a task never leaves an end state, and a progress event never changes
  a job that is not running or paused. What can remain is a short-lived older value until the
  newer event (already sent) arrives. So an older snapshot never hides newer event state.
- **One read at a time.** A read asked for while one is in flight runs once more after it
  (the trigger — a reconnect, a gap, a `resync` — may be newer than the read in flight); any
  number of such calls make one more read. A handler that needs a read (a job no read has
  shown, a run's end) asks with `mirror.need()`: idle, a read starts; during a read nothing
  starts, because the event is in that read's log and its replay asks again if the answer still
  lacks it. A failed read keeps the state; a `resync`, gap or reconnect reads again.
- **Reads only after the hello.** The event connection opens first; the first snapshots are
  read when its hello arrives (or after 3 s without one, then again at the hello). Every
  `hello` after the first load, a gap in `seq` and a `resync` event call `system.resync`,
  `tasks.resync` and `queue.resync`.

The queue (`job.state` carries only the state and the error):

- A run's end, a failed start and a retry read the queue (output path, issues, times); a
  waiting job's cancel does not (its `finished_at` is this client's clock until the next read).
  A job that `queue.changed` lists and no read has shown reads the queue, except while this
  client's own add is under way (its answer brings the job; after the last add the copy reads
  only if a job is still unknown).
- An add's answer (and a duplicate's) is a snapshot of the new jobs: they are inserted with
  `mirror.track`, then the events about them that came since the request are applied again (a
  start by another front end before the answer is not lost). A new job that no `queue.changed`
  has listed yet keeps its place while an older `queue.changed` leaves it out (the CLI's
  finding R1 M2 of 0062); a job that the events listed and removed before the answer stays out;
  a read sent after the answer removes it if the server no longer has it, a read sent before
  the answer does not (a counter, `mirror.tick()`, orders the two).
- `reorder` shows the new order at once (a dragged row does not jump back), then the
  `queue.changed` confirms it; a refused reorder reads the queue again.
- `queue.processing` is dispatched by its `type` string, and the snapshot's `processing` /
  `only` are read through a local type: an older server without them leaves the copy as it was.

Tasks: `wait(id)` resolves at `task.done` (failed and cancelled too) or from a read; it holds
across a lost connection (the read after the reconnect settles it) and rejects with
`TaskLostError` only when a read **sent after the wait began** does not list the task (the server
restarted or forgot it). The copy keeps the 200 newest ended tasks (the server's
`DEFAULT_KEEP_FINISHED`).

### Choices the plan leaves open

- **Backoff** (`api/events.ts`): reconnect after 0.5 s × 2ⁿ, capped at 30 s, half of it fixed and
  half random (so clients that lost the server together do not come back together); the count
  starts again after a connection that stayed open 10 s. A connection is dead when nothing
  (event or heartbeat) came for the hello's `heartbeat` + 5 s (20 s with the server's 15 s), or
  when no hello came 10 s after the auth message; it is then closed with 4000 and reconnected.
  A server that cannot be reached at start: `phase` `offline`, retried after 1 s × 2ⁿ, capped at
  30 s, the same jitter. Later losses keep `phase` `ready` (the screens keep the copy) and show
  as `connection` `reconnecting`.
- **Phases.** `system.auth.authenticated` drives the session: becoming true (boot, `login`,
  `loginWithToken`) starts the event connection and the first load (`booting`, then `ready`);
  becoming false (a 401 answer of either client, a 4401 close, `logout`) closes the connection
  and sets `login`. A 4401 leaves `connection` `unauthorized`, and the connection is not opened
  again until new credentials are accepted.
- **Credentials.** The `#token=` fragment is read when `api/boot.ts` is evaluated, before the
  router reads the address, and removed with `history.replaceState(history.state, …)` (other
  fragment parameters stay; checked in Chromium: the address is `http://127.0.0.1:8720/`, the
  history has no entry with the token). The token goes to `sessionStorage` (`reframe.token`;
  every access in try/catch). A token the server refuses at start is forgotten; a password
  login drops a token from the address (the cookie is the credential); `logout` ends the
  cookie session and forgets the token. The desktop build takes its token from
  `platform.backend()` and does not store it.
- **Toasts.** `api` shows a problem as a toast with its `title` and `detail` as the server wrote
  them; an answer that is not a problem as "The server answered with an error (status)"; a
  failed request as "The Reframe server cannot be reached", one at a time while it shows. A 401
  is not toasted (the login screen shows it). Both clients turn a failed request into an
  `ApiError` with status 0 and code `network`, so callers handle one error type; `unwrap` throws
  `ApiError` for any non-2xx answer. A failed rescan or FFmpeg download task is a toast too.
- **Translations outside components** (`api/text.ts`): a Pinia setup store is created inside
  the app's injection context, so it injects the app's own vue-i18n instance (the locale the
  screens use); without an app (unit tests) it uses an English instance.
- **Notifications**: a toast (`warning` → `warn`, 8 s), and `platform.notify` while
  `document.hidden`.
- **Settings**: one request at a time (each answer is the whole document, and answers of
  concurrent requests can arrive out of order); `update` uses `apiQuiet`; `set` sends `add`
  where the member is missing. There is no settings event: `queue.resync` reads the settings
  again, and `queue.whenDone` follows the settings store.
- **System**: `GET /api/system/encoders` is read again after a `capabilities.changed` while the
  copy says a detection runs (`detecting` and `checked_at` come only with a read);
  `rescanEncoders` and `fetchTools` resolve after their task ended and the state was read again;
  `rescanTools` takes its answer and the `tools.changed` events that came during it. A hello
  from another `instance` also reads the definitions and languages again (a new server version
  may bring other definitions) and calls `sources.onServerRestart()`.
- **Members added** to the contracts: `system.namingVariables`, `system.toolsFetch` (the task
  id of a running FFmpeg download), `system.loadDefinitions()`; exports `TaskLostError`,
  `KEEP_ENDED`, `taskEnded`, `hasPointer`, `ConnectionState`. `queue.jobs` is a `shallowRef`:
  every change replaces the job's object, so a row component sees a new prop. `boot()` takes
  optional `BootOptions` (tests inject the backend, the fetch and the socket) and `shutdown()`
  closes the connection.

### Consequences

- A store handler never throws into the dispatcher (`guard`); the stub
  `sources.onServerRestart` is called through it and logged until task E builds it.
- `src/api/testing/devServer.mjs` is plain JavaScript with a `.d.mts` beside it, because
  `tsconfig.app.json` (which includes `*.server.test.ts`) has no Node types. A tsconfig of its
  own for the server tests (Node and DOM types) would let them be TypeScript; that is the
  lead's call.

## Task C — F-3 app shell

Built: `App.vue`, `components/shell/` (`NavRail`, `ThemeSwitch`, `ConnectionStatus`,
`ShellToasts`, `BootScreen`, `LoginScreen`, `FirstRunScreen`, `EditorTabs`, `PreviewPanel`,
`StatusBar`, `ValidationSummary`, `format.ts`, the test helper `testing.ts`),
`views/WorkspaceView.vue`, `composables/useQueueActions.ts`, `composables/useShortcuts.ts`,
`i18n/messages/en/shell.json`.

Choices where the plan leaves one:

1. **Screens per phase.** `booting` and `offline` share one screen (a spinner, or "cannot be
   reached" with "Reframe tries again on its own"; boot retries, there is no "try now" button);
   `login` is the login screen; only `ready` shows the rail and the views. A later lost
   connection keeps the screens (`connection` `reconnecting`): the rail shows a short label under
   its dot on every view (the rail's copy is the live region), the status bar the full one.
   Password mode has a *Sign out* button in the rail; token mode has none (the token would have
   to be pasted again).
2. **Login.** One field: the token (`loginWithToken`, trimmed) or the password (`login`, as
   typed). A refusal (`false`) and any other `ApiError` (a 429, a lost server: its `title` and
   `detail`) show inline at the field through `Field`'s `issues`, never as a toast.
3. **Toasts** leave the toast store only when PrimeVue's toast closes them (close button or
   `life` end), not when they are shown: the API client shows one "cannot be reached" toast at a
   time by looking for it in the store. The shell starts showing store items when its `Toast`
   has mounted: PrimeVue's toast drops messages added before it listens (found by a unit test;
   a toast pushed during the boot was lost). A toast's `detail` keeps its line breaks (*Add
   all*'s list).
4. **First-run screen** replaces only the workspace view; the rail, Queue, Presets, Activity
   and Settings stay. It shows the server's reason (`system.ffmpegProblem`), then ffmpeg and
   ffprobe each with status, origin ("From an environment variable", "From a path in the
   settings", "Bundled with Reframe", "From the system PATH", "Not found anywhere"), path,
   version and its own reason when it differs from the headline. *Use bundled FFmpeg* calls
   `fetchTools` and shows the task's progress (`tasks.tasks[system.toolsFetch]`; indeterminate
   while it has none); *Check again* is `rescanTools`; *Choose path* goes to
   **`/settings#tools`** (route `settings`, hash `#tools`): task L focuses its Tools section from
   that hash. Checked against the real server: `--tools-dir /nonexistent` sets
   `REFRAME_FFMPEG` / `REFRAME_FFPROBE`, and the server reports both `missing`, origin `env`,
   with the reason "REFRAME_FFMPEG=/nonexistent/ffmpeg: the file does not exist. The environment
   sets this path, so it cannot be changed in Reframe: change or unset REFRAME_FFMPEG and
   restart."; a settings override (`{"tools": {"ffmpeg": "/nonexistent/settings/ffmpeg"}}`)
   gives origin `settings` and "The FFmpeg path in Settings (/nonexistent/settings/ffmpeg): the
   file does not exist." The buttons stay enabled with an environment override, although only
   the environment can fix it (the reason says so).
5. **Workspace layout.** A grid of three columns: sources `minmax(14rem, 18rem)`, tabs the
   rest, preview `minmax(16rem, 24rem)` or 3 rem collapsed; one column below 60 rem. Each column
   scrolls on its own; the status bar stays at the bottom. The preview's collapsed state is kept
   in `localStorage` (`reframe.workspace.previewCollapsed`, VueUse). The source header shows the
   active source's file name (not the container's title tag) and its duration (`h:mm:ss`), with
   `PresetPicker` at its right; **the Range selector of 03's diagram is not in M4** (no step of
   M4 builds ranges in the UI). Without an active source the tab column shows an empty state
   (*Open files…* and `Ctrl+O`); the tabs show once a source is active.
6. **Tabs** are PrimeVue `Tabs` (`lazy`: only the active tab's component exists; each tab's code
   loads the first time it shows; arrow keys move between tabs), bound to `ui.activeTab`, with
   `aria-keyshortcuts` `Control+N`.
7. **Status bar.** The output path is cut at its start (the file name stays visible; the whole
   path in the tooltip). The validation summary is a button ("1 error 2 warnings 1 note", "No
   issues", "Checking…") that opens a popover with `IssueList` (compact); *Show* on an issue
   closes the popover, since the field it reveals is behind it. The queue summary ("Queue: 1
   running · 2 waiting") links to the Queue view. *Add to queue*, *Add all* and *Start* follow
   `useQueueActions`' `canAdd`, `canAddAll`, `canStart`.
8. **`useQueueActions`** (members added to the contract: `canAddAll`, `canStart`).
   `canAdd`: a job, the editor not loading, no validation pending, no error, an output path, and
   no add under way. One add at a time across all callers (a module-level flag), so a double
   click or a held `Ctrl+Enter` queues once. An added job that the queue took as `failed`
   (`queue.output_claimed`) is an error toast with its `error`, not "Added". A refused add is the
   API client's toast only. `canStart`: waiting jobs, and the runner not already taking every
   waiting job (`processing` with `only` `null`).
9. **Add all** (item 10) drafts every open source with `editor.presetId` through
   `POST /api/jobs/draft` (`apiQuiet`, in parallel), except **the source open in the editor,
   whose job is taken as edited** (a re-draft would drop the user's changes): it is added when
   its validation is not pending and has no error. Jobs with an error issue, without an output
   path, whose draft failed (the problem's title) or that the queue took as `failed` are listed
   in one warning toast (`name: reason` per line); the others are added in one request, in
   source order, with a success toast. The jobs are copies taken when Add all is clicked (an
   edit during the drafts does not change them). When the queue refuses the request, only the
   API client's toast shows.
10. **Shortcuts** (`useShortcuts`, one `keydown` listener on `window` through VueUse, removed
    with the shell). `Ctrl` or `Meta`, never with `Alt`; ignored outside phase `ready`, after
    another handler's `preventDefault`, and while the focus is inside an `aria-modal` dialog.
    `Ctrl+O` works from every view: it goes to the workspace, then `sources.pick()`; it does
    nothing while FFmpeg cannot be used or when held down. The others act only on the workspace
    (not under the first-run screen): `Ctrl+Enter` → `addCurrent` when `canAdd`, once per press;
    `Ctrl+1…8` by the physical key (`Digit1`…`Digit8`, the keypad too, so an AZERTY layout
    works), selecting the tab whose `shortcut` is N; for a tab that is not built nothing changes,
    but the browser's own tab switch is still prevented; `Ctrl+Z` → `undo`,
    `Ctrl+Shift+Z` / `Ctrl+Y` → `redo` (when `canUndo` / `canRedo`), left to the browser while
    the focus is in a text-like `input`, a `textarea` or a `contenteditable` (a check box, a
    radio button, a button still undo the editor).
11. **Taskbar.** `App.vue` sets `platform.setTaskbarProgress(queue.overallProgress)` on every
    change and at start (`null` clears it), on every view.
12. **Theme switch** in the rail: a popover with two `SelectButton`s (theme: system, light,
    dark; density: comfortable, compact) through `useTheme()`, which `App.vue` also calls once at
    start so that the settings' appearance is followed before the rail exists.

Checked in headless Chromium (Playwright 1.64.1) against `scripts/dev-server.py` on ports
8740–8743 (token mode with the `multitrack` fixture, password mode, `--tools-dir /nonexistent`,
a settings override), light and dark: every view from the rail with the current one marked;
the token leaves the address; the preview collapses to 48 px; theme and density switch at once
(root font 16 → 14 px); `Ctrl+1…8` (`Ctrl+2`, Dimensions, changes nothing); `Ctrl+O` reaches
`sources.pick` (the stub until task E); `Ctrl+Enter` with a job in the editor (set through
Pinia) sends `POST /api/queue` and shows "Added to the queue", and a second time the server's
`queue.output_claimed` as "The job was added as failed"; a refused request through `api` shows
its problem as a toast; the issue list opens from the status bar; the login screens refuse a
wrong token or password inline and accept the right one; the first-run screen with both
overrides, *Choose path* to `/settings#tools`, Presets and Settings usable.

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
