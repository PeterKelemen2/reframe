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

Built: `stores/editor.ts`, `stores/validation.ts`, `composables/useValidation.ts`,
`composables/useUndo.ts` (unchanged: it was already a view of the store), the helpers in
`editor/` (`pointer.ts`, `patch.ts`, `history.ts`, `template.ts`, `latest.ts`; test data and the
server tests' FFmpeg lookup in `editor/testing/`) and `i18n/messages/en/editor.json`.

### What was checked against the real server (2026-10-29)

`reframe-server` through `scripts/dev-server.py` with the pinned FFmpeg n9.0.2 (`--tools-dir`),
on this AMD desktop; `src/stores/editor.server.test.ts` does each of these:

1. **Which encoder is unavailable.** `scripts/dev-server.py` turns the hardware test encodes
   off, and then every hardware encoder of the build is `unknown` ("Not tested: hardware test
   encodes are off"), which validation reports as the warning `encoder.untested`, not
   `encoder.unavailable`. With `PUT /api/settings` `/encoders/hardware_tests` `true` and a
   rescan: `hevc_nvenc` (and the other NVENC and QSV encoders) `unavailable`, reason "NVIDIA
   driver not found"; AMF and VAAPI `available`; `libfdk_aac` `unavailable` ("Not in this
   FFmpeg build"). The test picks `hevc_nvenc` when it is unavailable, else any unavailable
   video encoder of the definitions.
2. **The issue and its fix.** With the default preset's job and `video.encoder` set to
   `hevc_nvenc`: `encoder.unavailable` at `video.encoder`, "hevc_nvenc (NVIDIA NVENC H.265) is
   not available: NVIDIA driver not found.", one fix, "Use hevc_amf (closest match; quality CQ 22
   → CQ 20, approximate)" (target `job`; three `replace` operations: the encoder, the quality,
   the speed preset to `null`). The closest match on this machine is `hevc_amf`, not `libx265`:
   the fallback chain takes the first available encoder. After the fix the issue is gone, after
   an undo it is back, after a redo gone again. `presets/diff` after the encoder change:
   `[{path: "video.encoder", kind: "changed", preset_value: "libx265", value: "hevc_nvenc"}]`.
   (The x265 speed preset and custom parameters give more errors with NVENC; the store keeps
   them all, the test looks at `video.encoder`.)
3. **A value of the wrong type** (`"fast"` for the quality) is a 422 `request.invalid` whose
   `errors[].loc` holds the tag of the union member: `["body", "job", "video", "rate_control",
   "quality", "value"]`.
4. **`currentTemplate` of every built-in preset** (26) drafted for `multitrack.mkv` is unmodified
   for `POST /api/presets/diff` (`[]`).

### The undo history

- **Patches.** The job is immutable: each change makes a new job (a JSON copy, the patch
  applied with `rfc6902`, the result frozen deep), so the history can keep the documents it
  diffs, and a component that writes into the job (a `v-model` on a member) throws instead of
  changing it without an undo step and a validation. A patch applies whole or not at all:
  `applyPatch` goes on after a failed operation, so the store applies the operations one by one
  to a copy and throws `PatchError` at the first that fails (the job stays the same object). A
  `replace` or `add` of the whole document (`''`) is applied too (`rfc6902` refuses it).
- **Steps.** Each step keeps two patches, `redo` and `undo`, computed by `createPatch` from the
  job before and after (not the caller's operations): the same code for every kind of operation
  (`add`, `remove`, `replace`, `move`, `copy`, `test`), and the step is exact. `createPatch`
  turns a key that is removed and added again into a `remove` and an `add`, which puts the key
  last; filter and advanced-option order is shown, so an object whose keys a member-wise patch
  would reorder is replaced whole. The tests compare `JSON.stringify` of the job, key order
  included.
- **Bound: 200 steps**; the oldest is dropped. A step is a few hundred bytes (a preset change
  some kilobytes).
- **Coalescing.** Patches in a row with the same `coalesce` key are one step, from the job before
  the first to the job after the last. Any other patch (another key or none), an undo, a redo,
  `endCoalescing()`, `open`, `applyPreset`, `loadJob` and `close` end the run. A run that comes
  back to where it began leaves no step. A patch that changes nothing adds no step, keeps the
  job object and keeps the steps to redo; any other patch drops them. Keys are not timed: two
  drags of one slider with nothing between are one step unless the component calls
  `endCoalescing()` when it is let go (or puts a gesture number in the key).
- **A preset change** (`applyPreset`) is one step, from the job as it is when the new draft
  comes (an edit made while it loads is in the step it undoes to). The step also brings back the
  draft of its side (the track decisions of that preset). `presetId` is the job's `preset_id`,
  so an undo brings back the preset too.
- **A history that does not fit the job** (only when something wrote `target` past the store):
  the undo fails, the history is cleared and the job stays.

### `currentTemplate`: from a job back to a template

The inverse of `build_job` (`reframe.batch.resolve`) and the same rules as
`reframe.batch.derive.derive_template`, with the preset as the base:

| Template field | From |
|----------------|------|
| `schema_version`, `audio_defaults`, `subtitle_defaults`, `audio_rules`, `subtitle_rules` | the preset (a job holds concrete tracks) |
| `output` | the job's `output` without `path`, `naming` and `edit_in_place` |
| `dimensions`, `crop_policy` | the job's dimensions. Crop: `manual` → policy `fixed` with its rectangle; `none` → the preset's policy; `auto` / `conservative` → the preset's crop and policy when the job's crop is what a draft of the preset gives (a rectangle measured on another file is dropped, or `manual` under `fixed`), else policy `detect_per_file` and no rectangle (measured on this file) |
| `filters`, `tags` | the job |
| `video` | the job's, with the preset's `metadata` (the job's is the source track's) |
| `chapters`, `chapter_name_policy` | the job's `enabled` and `generate_every`; the names: `Chapter 1 … n` → `generated`, other names → `source`, no names → the preset's policy (no names is both "the source's" and "the source has none") |
| `naming` | the preset's own (`null` stays `null`: Settings → Output); the job's naming `template` (as both movie and episode template) and `name_source` over the preset's naming options, or over Settings → Output's when the preset has none; a manual name and field overrides are per file |
| the preset's `id`, `name`, `category`, `description`, `built_in` | left out |

The preset comes from the presets store when it holds it, else from `GET /api/presets/{id}`
(once per preset id; task J's store does not load yet). `currentTemplate` is `null` while the
preset is not known (and when it does not exist): then nothing is diffed and `modified` is
false.

### `presetChanges`

`POST /api/presets/diff` (`apiQuiet`) of `currentTemplate` against `presetId`: at once after
`open`, `loadJob`, `applyPreset`, an undo or redo to another preset, and when the preset arrives;
250 ms after the last edit otherwise. An edit that leaves the template as it was (a track, the
output path) sends nothing (the template and the preset are compared as JSON). A new job or
another preset clears the list at once. The newest request wins: a new one aborts the one under
way and an older answer is never taken (the same runner as validation, below). A 404 (the preset
was deleted) clears the list; another failure keeps it. `refreshPresetChanges()` asks again (task
J, after saving the preset).

### Validation

- **Ordering.** `editor/latest.ts`: one request at a time for state that keeps changing. Each
  `schedule(delay)` bumps a generation number, clears the timer and aborts the request under
  way (`AbortController`); a request reads the job when it goes out; an answer (or a failure)
  is taken only while its generation is the newest. So an answer for an older job never
  replaces a newer one, and a closed editor or a new job cancels what is on its way.
- **When.** 250 ms after the last edit (a trailing debounce: nothing goes out while edits come
  closer together than that). A new job without a draft (`loadJob`) at once; also at once when
  `useValidation` starts (a remount: what changed meanwhile is not known) and when the event
  connection is `open` again after a failed validation. 250 ms after a change of what the
  issues depend on besides the job: `system.capabilities` (a detection, *Check again*),
  `system.info` (tools), `settings.settings` (a settings fix, Settings), and
  `validation.revalidate()`.
- **`pending`** is true from the change (the job watcher is `flush: 'sync'`) until the answer
  for the job as it is now, or a failure. The issues shown meanwhile are the last answer's for
  the same job (fields do not flicker while typing); a new job clears them at once.
- **The draft's issues show until the first answer: none is asked for.** `jobs/draft` validated
  that same job, so after `open` and `applyPreset` the draft's issues are shown and no request
  goes out until something changes. The draft also has issues that `jobs/validate` never gives:
  the track stage's (`batch.*`, `defaults.*`, at paths in the preset's rules) and
  `preset.not_found`. They are added to every answer while the job is still the drafted one
  (JSON-equal, so an undo back to it brings them back) and dropped once it is edited: they say
  how the preset met the source, and an error among them would otherwise block *Add to queue*
  for a job the user has since changed (the server's queue never sees them).
- **Fixes with target `template`** are removed from the issues of a job (only the batch editor,
  M7, can apply one); `applyFix` of one throws.
- **A job the server cannot read** (422 `request.invalid`, a value of the wrong type) is shown as
  one `error` per field, code `request.invalid`, with the server's message, at the field's path:
  the location is followed through the job and a part that is not a member is skipped (the tag
  of a union member, `quality`), unless it is the last (a missing field).
- **Another failure** (no answer, 5xx): `pending` false, `failed` true, the issues kept;
  retried at the next change or when the connection is open again.
- `useValidation()` validates while its caller's scope lives (the workspace view); its
  watchers and the request stop with it.

### Choices the plan leaves open

- `open(sourceId)` without a preset uses `presets.defaultId`, else `null` (the server's
  default). It does not keep the current preset by itself; a caller that should (HandBrake
  keeps the selected preset for the next title) passes `editor.presetId`.
- A failed `open`, `applyPreset` or `loadJob` rejects (the `ApiError` of the draft is a toast
  already) and leaves the editor as it was; an older one's answer after a newer call is
  dropped. `loading` is true while the newest runs.
- `loadJob` makes the job's source the active one (`sources.activeId`) and has no draft (track
  decisions describe a draft, not a queued job). It imports the sources store when it runs: the
  sources store opens sources in the editor, and a static import both ways is an import cycle
  (oxlint `import/no-cycle`; a dynamic import in one direction is not one). Vite's build says
  the dynamic import does not move the module into another chunk; that is expected.
- `patch` and `set` throw while no job is open, and `PatchError` for a patch that does not
  apply. `applyFix` never rejects for a fix that cannot be applied: a job fix that does not fit
  the job any more (it changed after the check) and a settings fix the server refuses are
  toasts ("The fix could not be applied", with the reason).
- Members added to the contracts: editor `session` (+1 for each new target), `preset` (the
  job's preset document), `endCoalescing()`, `refreshPresetChanges()`, and the exports
  `EDIT_DEBOUNCE` (250) and `PatchError`; validation `failed`, `requests`, `session`,
  `revalidate()`. `presetId` is a computed (read only): it follows the job's `preset_id`.
- The server tests take FFmpeg from `REFRAME_TEST_TOOLS_DIR`, else from the build that
  `scripts/fetch-tools.py` put into `.tools/`, else the server finds one
  (`editor/testing/tools.mjs`).

## Task E — F-5 sources panel and the file browser

(Written by task E.)

## Task F — F-18 naming editor

Built in `components/naming/`: `TemplateField`, `VariableChips`, `ParsedNamePanel`,
`TemplateFixes`, `NamingIssues`, `Disclosure`, the helpers `template.ts` (completion), `path.ts`
(the job's folder), `spans.ts`, `preview.ts`, `fields.ts`, and the two editors of item 8;
`i18n/messages/en/naming.json`; a "Naming editors" section of the dev-only sandbox.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` with the pinned FFmpeg n9.0.2, copies of `multitrack.mkv` under the
release names of 03 §Output naming's examples; `src/components/naming/naming.server.test.ts`
does each of these:

1. `Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson/hacksawridge.2160p.remux-henderson.mkv`:
   name source **folder**, "Folder name: 8 fields recognised, title with word separators (10
   points); file name: 3 fields recognised (3 points)", `Hacksaw.Ridge.mkv`.
   `The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm/The.Sopranos.S03E02.Proshai.Livushka…mkv`:
   name source **file**, "Only the file name has an episode number (S03E02), so it is used",
   `season_pack` true although the folder holds one file, `template_kind` `episode`,
   `The.Sopranos.S03E02.Proshai.Livushka.mkv`. Both as 03 says.
2. **Spans** use guessit's property names besides the `ParsedName` fields (`other`,
   `audio_codec`, `audio_channels`, `hdr`, `video_codec`, `video_profile`, `language`), and two
   can cover the same characters (`HEVC` as `video_codec` and `video_profile`). Positions are
   Python string indices (code points). The panel shows the first span at a position and gives
   every property that is not a name field one "other tag" colour.
3. **A source reports the issues of the template it used only**: with the episode template
   `{main_titel}`, a movie gets no issue. The issues of a template are always at
   `output.naming.template`, also for naming options (no job), and their "did you mean" fix is
   one `add` of the whole fixed template.
4. A template with errors names the file after the source file (`hacksawridge.2160p.remux-henderson.mkv`);
   the preview's `path` is the naming options' folder joined with `relative_path` (the
   dev server's settings have a fixed folder in its output root).

### Choices the plan leaves open

1. **The output folder of one job** is the folder of its naming options (the preset's, else
   Settings → Output), as the draft names it. *Choose folder…* (`platform.pickFolder`) puts the
   job into another folder, and *Use the naming options' folder* takes it back; both are one
   undo step on `/output/path`. `JobNaming` has no folder, so the job's folder lives in its
   path: it is the path without the name the template gave (`relative_path` of the last preview
   of the job as it is, compared without the extension, since a container change replaces it);
   a path that does not end with that name (changed by a fix or by hand) is taken as a file in
   its folder. A naming change keeps that folder. No schema change, and undo, `loadJob` and the
   queue keep the folder because it is in the job.
2. **Edits are previewed before they reach the job.** The fields edit a working copy of
   `output.naming`; 250 ms after the last change `naming/preview` names the job with it, and the
   answer's name goes into the job together with the naming: one `editor.patch` with
   `/output/naming` and `/output/path`. Typing in one field coalesces
   (`output.naming.template`, `…manual_name`, `…field_overrides`) until the field loses the
   focus. When a field loses the focus with an edit not yet in the job, the naming goes in at
   once (a click on *Add to queue* blurs the field first; validation is then pending, so
   `canAdd` is false until the job is checked) and the path follows with the preview's answer
   under the same coalescing key, so both are still one undo step, which ends there. A failed
   preview still puts the naming into the job (the path stays) and says why.
3. **Changes from elsewhere** (undo, a preset, a container or size change) never write the path:
   a write after an undo would drop the redo steps. The editor previews the job again, takes
   back the job's naming when it changed, and when the job's path is not what its naming gives
   now (a container change) shows that path with *Use this path*. Validation's own extension fix
   covers the container case as well.
4. **Per-file overrides** are editable in `JobNamingEditor` only. `NamingOptionsEditor` shows
   the parsed-name panel read only: naming options apply to every file, and an override belongs
   to one job.
5. **Template issues** show at their template field (`Field`'s `issues`, from the preview),
   with their "Use {…}" fixes as buttons that put the fixed template into that field; other
   issues of the preview (`output.folder_required`, `naming.no_output_folder` at the folder
   field) show as messages without fix buttons, since `IssueList`'s fixes patch the editor's job,
   which is not what the options editor edits. `NamingOptionsEditor` checks a template that no
   source used (the episode template with only movies open) with one more preview on the first
   source with both templates set to it (item 3 above). Without sources there is no preview and
   no check.
6. **Completion** is a combobox of our own on PrimeVue's `InputText` (`role="combobox"`,
   `aria-activedescendant`): PrimeVue's `AutoComplete` completes the whole value, not the word
   at the caret. Format specs offered after `name:`: `02`, `03` (numbers), `upper`, `lower`,
   `title` (text), `%Y-%m-%d`, `%d.%m.%Y`, `%Y`, `%H-%M`, `%H-%M-%S` (dates), the kinds of
   `NamingVariable.kind`. Variable descriptions are the server's text, as issue messages are.
7. **Name source per job**: "As the naming options say" is `name_source: null` (a Select has no
   option for `null`, so it has its own value).
8. A folder picker that rejects (the web one before task E) is a warning toast, "A folder cannot
   be chosen here: type its path"; the folder stays.
9. Members added to the contracts: both editors have `compact?` (the chips and the parsed name
   start folded).

## Task G — F-6 Summary tab

Built: `components/editor/tabs/SummaryTab.vue`, `components/summary/` (the seven cards,
`SummaryLink`, the pure helpers `format.ts`, `estimate.ts`, `pipeline.ts`, `filters.ts`,
`tracks.ts`, the composables `useGeometry`, `useThumbnail`, `useJobSource`, test data in
`testing.ts`) and `i18n/messages/en/summary.json`.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` with the pinned FFmpeg n9.0.2, fixtures `multitrack`, `hdr10`,
`letterbox`; `src/components/summary/summary.server.test.ts` repeats items 2 and 3.

1. **The thumbnail flow.** `POST /api/preview/frames {source_id, count: 1}` is not a 202: the
   request waits for the frames task and answers `{frames, notes}` at once (0.1 s for the
   fixture). `count: 1` gives the middle of the file (2.0 s of 4.021 s). The frame's `url` is
   relative (`/api/preview/frames/<key>.png?exp=…&sig=…`), signed for about 5 minutes (`exp` is
   now + 300 s), and loads **without** the bearer token (an `<img>` cannot send it): `200`,
   `image/png`, `ETag` the key, `Cache-Control: private, max-age=3600`; a changed `sig` is a
   `401`. The app's CSP (`img-src 'self' data: blob:`) lets it load: same origin. HDR10 frames
   come tone mapped, with a note ("…tone mapped to SDR for display with zscale + tonemap").
2. **`POST /api/jobs/geometry`** reads the job's source, `dimensions`, `video.passthrough` and
   whether `filters` has `deinterlace` (the route's code). For `letterbox.mkv` with a manual
   crop of 22 / 24 lines: crop 320×134, aspect 2.388; with pixel aspect custom 4:3: scaled
   240×134, `output_sar` 4:3; passthrough: `geometry: null`; a draft whose automatic crop has
   not been detected: no crop, with the notes "Automatic crop: detection has not run yet…" and
   "Upscaling is off…". A size mode the server does not know is a 422 `request.invalid`.

### Choices where the plan leaves one

1. **Thumbnail.** One source frame, `count: 1` (the server picks the middle), through
   `apiQuiet` (no toast: the card shows a placeholder), aborted when the source changes or the
   card unmounts (the server cancels the task). The link is made absolute against the client's
   base URL (the desktop app's server is not the page's origin). A source without video asks
   for nothing. Links are kept per source id for 50 minutes: a new request signs a new URL, and
   a new URL would download the full-resolution PNG again (megabytes for 4K) every time the
   lazily mounted tab is shown, while the browser keeps the image under the old URL for an
   hour. When the image fails to load (the browser no longer has it and the link expired), the
   card asks once for a new link.
2. **Picture pipeline.** `jobs/geometry` at once for a new job, 250 ms after the last edit that
   changes what the route reads (an audio edit sends nothing), through D's `latestRequest`, so
   an older answer never replaces a newer one; another job's line is cleared at once. A step is
   shown only when it changes something: `crop W×H` when a side is cropped, `rotate N°`,
   `scale W×H` when the size differs from the cropped one; then the display aspect (`2.39:1`)
   and "square pixels" or "pixel aspect N:D". The line is amber when the server says
   `upscaled`, red with the problem's title when it cannot be computed; the geometry's notes
   are listed under it.
3. **Filter chips.** A filter is on when the job's `filters` has it (the definitions have no
   "off" preset). Chips in the filter chain's order (`definitions.filter_order`): every filter
   that is on, with the label of its preset in the chosen implementation, plus Deinterlace,
   Colorspace and Tone mapping as "off" (the three of 03's example), named as the definitions
   name them ("HDR → SDR tone mapping").
4. **Estimate.** Only in bitrate mode (and for a copied video): (video kb/s + Σ audio kb/s) ×
   1000 / 8 × the range's duration (full: the container's duration; time, chapters and frames
   ranges: their part). An encoded audio track counts at its bitrate, or, without one, at the
   encoder's default for its mixdown (`definitions.audio_encoders[…].bitrate.by_mixdown`; a
   kept layout by the source's channel count). **A passthru track counts at the source
   stream's bitrate** (`bitrate.value`, from the stream or the Matroska statistics); one
   without a known bitrate, a VBR-quality track and a lossless encoder are left out and the card
   says how many. A copied video counts at the source's video bitrate, or the card says it
   cannot be estimated. Subtitles, chapters and the container's overhead are not counted.
   Sizes in binary units (KiB, MiB, GiB), as Linux and Windows file managers show them.
5. **Video line** of the Source card: the commercial codec name, `W×H`, the rate (the average
   rate, else `r_frame_rate`; three decimals at most, "(variable)" for VFR), the HDR formats
   (HDR10, HDR10+, HLG, Dolby Vision) and the colour (`BT.2020 PQ`, `BT.709`; the transfer is
   named only for PQ and HLG; nothing when the stream does not tag it).
6. **Name source** on the Output card: the draft's choice and reason while the job's naming and
   container are the drafted ones; otherwise (an edited naming, a job from the queue without a
   draft) the job's setting: Automatic, File name, Folder name, or Manual name. F's
   `JobNamingEditor` below it shows the live parsed name.
7. **Links.** A track chip calls `ui.reveal('audio[i]')` / `'subtitles[i]'`; each value of the
   Video card is a link to its field (`video.encoder`, `video.rate_control`, `video.preset`,
   `video.bit_depth`, `video.advanced`, `video.passthrough`). A link whose tab is not built
   (`tabForPath` gives `summary`: the pipeline, `dimensions`; a filter chip, `filters.<id>`) is
   plain text until that tab exists. The Picture card is the reveal target of `dimensions.*`
   and `filters.*` paths while their tabs do not exist (item 5 of the lead's decision), so the
   *Show* of a crop issue lands there. A chip carries the colour and icon of its most severe
   issue (`issuesFor('audio[i]', { nested: true })`).
8. **Layout.** `repeat(auto-fill, minmax(min(100%, 20rem), 1fr))` with dense flow: one column in
   the 600–700 px tab column, two or more on wider screens. Output, Tracks and Issues span the
   whole row; the Source card puts the thumbnail (at most 18 rem) beside the facts when there
   is room.
9. **The source** is the sources store's entry for the editor target's `sourceId`. Without one
   (not open in this window) or with `source: null` (changed since the probe), the card says
   so and shows the file name from the job; the other cards still work.

Checked in headless Chromium (Playwright 1.64.1, 1440×1000) against `scripts/dev-server.py` on
port 8790, light and dark (the sources store set through Pinia, since E's panel is built in
parallel): every card for `multitrack`; the thumbnail loaded (320×180); bitrate mode 6000 kb/s
gives "About 3.1 MiB" (video 6000 + audio 3 × 160 kb/s over 4 s), undo gives "Depends on
content", redo the size again; the MP4 button sets the container (and shows *Web optimized*),
MKV hides it; a toggle is one undo step; `hevc_nvenc` gives errors, a warning and a note in
three groups with their fix buttons; an issue's *Show* and a Video link go to the Video tab, a
chip to the Audio tab with `revealed` `audio[1]`; the crop note's *Show* highlights the Picture
card; a job without a draft shows every card; `hdr10` gives `HEVC Main 10 · 320×180 · 25 fps ·
HDR10 · BT.2020 PQ`; `letterbox` with a manual crop `320×180 → crop 320×134 · 2.39:1 · square
pixels`, and width 1280 with upscaling the amber line with `scale 1280×536`.

## Task H — F-9 Video tab

(Written by task H.)

## Task I — F-10 Audio and Subtitles tabs

(Written by task I.)

## Task J — F-12 presets UI

Built: `stores/presets.ts`, `components/presets/` (`PresetPicker`, `PresetChanges`,
`PresetNameDialog`, `PresetTree`, `PresetDetails`, `PresetNaming`, `PresetImport`, the pure
helpers in `format.ts`, test data in `testing.ts`), `views/PresetsView.vue` and
`i18n/messages/en/presets.json`.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` with the pinned FFmpeg n9.0.2, fixture `multitrack`;
`src/stores/presets.server.test.ts` repeats items 1 to 5 and 7.

1. **`GET /api/presets`**: 26 built-ins, categories General, Web, Devices, Matroska,
   Hardware, Production in that order, every built-in with `naming: null`; `default_id`
   `h265-mkv-1080p`.
2. **A name clash** (`POST /api/presets`, and `PUT` for a rename) is `409
   preset.name_conflict`, its issue at the path `name` with one fix (target `template`) that
   replaces `/name` with the next free name. The server makes it from the name as typed, trimmed:
   `"  mine "` against `Mine` offers `mine (2)`; against a built-in the message says "A built-in
   preset named …". A blank name is `422 preset.name_empty` at `name`. The server offers the
   name; the client does not compute one.
3. **Built-ins**: `PUT` (also with `built_in: false` in the body) and `DELETE` are `409
   preset.built_in` ("… Duplicate it to make a copy you can change."). An unknown id is `404
   preset.not_found`, also for `presets/diff`.
4. **The default**: `POST …/{id}/default` answers the preset; deleting the default preset makes
   `h265-mkv-1080p` the default again (the answer of `DELETE` does not say so: the list must be
   read).
5. **Export and import**: `GET /api/presets/export?ids=` gives `{document, issues}`; a built-in
   can be exported. Importing that document again: `rename` stores it under a new id and
   `Name (2)` (`renamed: [{name, new_name}]`); `replace` overwrites the user preset (same id,
   `replaced: [name]`); `skip` leaves it out (`skipped: [name]`). A built-in in the file under
   `replace` is stored renamed (`H.265 MKV 1080p (2)`) as a user preset that keeps its category
   (`Matroska`). A file entry without an `id` is skipped with a `preset.invalid` warning; `{}` is
   `200` with a `presets.import_invalid` error issue; a body that is not a JSON object (`[1]`,
   text) is `422 presets.import_invalid`. After the default was deleted, an import set the
   file's `default_preset_id` as the default (0015: only when the target has none of its own).
6. **The browser** (headless Chromium, light and dark): an export downloads through
   `<a download>` with a Blob URL under the app's CSP; an import through `<input type="file">`
   (Playwright's file chooser) is read in the page and sent as the request body.
7. **A preset made from the open job**: with `editor.currentTemplate` saved by
   `POST /api/presets` and the job's `/preset_id` and `/preset_name` patched, `presets/diff`
   gives `[]`; after another edit, `PUT` of `currentTemplate` into the preset and
   `refreshPresetChanges()` give `[]` again.

### Choices where the plan leaves one

1. **When the list is read** (there is no preset event, and another front end can change
   presets): at the first use (`ensureLoaded`, from the picker's mount), every time the presets
   view opens and every time the picker's list opens, after a change whose answer does not
   describe the list (deleting the default, an import, a `404` from a preset deleted
   elsewhere), and when the event connection is `open` again after a loss. A change's answer is
   put into the list at once (create, save, set default). Requests go one at a time, so a read
   never returns the list from before a change sent earlier.
2. **A name clash**: the server's free name is shown at the name field as a button (*Use
   “Mine (2)”*); nothing is saved until the user takes it or types another. *Duplicate* sends
   the preset's own name and, on the clash, takes the free name at once (`Name (2)`, as 03 says);
   a built-in's copy goes into `Custom` (0015).
3. **Inherit naming** (`naming: null`): a switch *Use the naming of Settings → Output* above the
   naming editor. On, the editor shows Settings → Output's naming read-only. Turning it off
   gives the preset a copy of Settings → Output's naming, saved at once; turning it on saves
   `null`. Edits (`NamingOptionsEditor` emits a whole object per keystroke) are saved 600 ms
   after the last one, and at once when another preset is shown or the view closes. A built-in
   shows its naming read-only. The preview uses the open sources and the preset's container.
4. **The preset drawer is the presets view** (`/presets`): the tree by category on the left,
   the chosen preset's details on the right. The rail reaches it, and the picker's *Open
   presets* opens it at the job's preset (`?preset=<id>`). *Use for the open job* (and Enter in
   the tree, or a double-click) drafts the job with the preset and goes back to the workspace.
5. **The picker** is a button with the preset's name that opens a filterable listbox (PrimeVue
   `Listbox` in a `Popover`), grouped by category, built-ins with a lock, the default with a
   star. Not PrimeVue's `Select`: it calls `matchMedia` when it mounts, which jsdom lacks, and
   the shell's tests (`App.test.ts`, `WorkspaceView.test.ts`) mount the header without a stub.
   The list is read again when it opens. The focus goes back to the button after a choice.
6. **The *modified* marker** opens its popover on a click or Enter, not on hover (03 says
   "hover"): the same for the keyboard and touch. It lists each change of `presets/diff` as
   its setting in words (`Audio defaults › Codec rule 1 › Maximum bitrate`, from
   `presets.field.<key>` messages; a key without one is shown with spaces), the preset's value
   struck out and the current one (encoder and container ids as their labels from the
   definitions). The popover offers *Save as new preset…*, *Update preset* (a user preset
   only; a built-in says it cannot be changed) and *Open presets*; the header's ⋯ menu offers the
   same while the job is not modified.
7. ***Save as new preset*** saves `currentTemplate` (name, category, description), and the job
   then follows the new preset: `/preset_id` and `/preset_name` in one undo step, so the marker
   goes away and an undo brings the old preset back. ***Update*** from the picker saves into the
   job's own preset; in the view, updating a user preset that is not the job's asks first.
8. **Delete** asks in a modal dialog (the button and Delete in the tree). **Rename** edits the
   name, category and description in the same dialog as *Save as new*.
9. **Import**: the file is read in the page; when a preset in it has the id or the name of a
   known one (names compared as the server does), the dialog lists them and asks for rename
   (the default), replace or skip, else the file is imported at once. The server's report is
   shown (imported, renamed with old → new, replaced, skipped, issues); a file refused as a
   whole shows the server's reason. **Export**: one preset as `<name>.json`, *Export user
   presets* as `reframe-presets.json`; presets of a newer Reframe in an export are a warning
   toast.
10. **The tree**: an ARIA tree (categories are expandable items with a group of presets), one
    item in the tab order, the selection follows the focus. Arrow keys, Home, End; Right opens a
    category or goes to its first preset, Left closes it or goes to the category; Enter applies
    a preset or opens / closes a category; Delete asks to delete a user preset.
11. Members added to the contract: `ensureLoaded()`, the exports `templateOfPreset(preset)`,
    `suggestedName(error)`, `ImportConflict`, `PresetImportReport`, `PresetCategory`.

## Task K — F-14 queue, activity and job log

(Written by task K.)

## Task L — F-15 settings

(Written by task L.)

## Task M — F-17 Playwright set-up and flow 3

(Written by task M.)
