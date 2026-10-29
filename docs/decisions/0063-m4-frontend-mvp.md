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

Built: `stores/sources.ts`, `components/sources/` (`SourcesPanel`, `SourceItem`,
`FileBrowserDialog`, `fileBrowser.ts` (the open picker request), `panel.ts` (rows, groups,
episode labels, the short line), `paths.ts` (breadcrumbs, joins)), `platform/web.ts` (the
three pickers), `i18n/messages/en/sources.json`.

### What was checked against the real server (2026-10-29)

`reframe-server` through `scripts/dev-server.py` with the pinned FFmpeg n9.0.2 and the fixtures
`multitrack`, `season`, `Anime.Show.S01.BluRay.x264-GRP`, `dts-hd-ma`, `interlaced`, `vfr`,
`text-subs.en.srt`:

1. **`GET /api/fs/list` lists folders and media files only** (`reframe.probe.MEDIA_EXTENSIONS`,
   0049 item 8): `text-subs.en.srt` in the media root is not in the listing, and there is no
   query parameter for other files. So the client cannot show more than media files, whatever
   its filter says (item 9 below).
2. **Paths outside the roots**: `/etc` and `<media>/..` are `403 path.outside_roots`, "The path
   is outside the allowed folders", detail "… is not inside a folder that this server may
   **write** to." (the route tries the read jail, then the write jail, and reports the second
   refusal; for a folder to read, "write" is misleading — server wording, for the lead). A file
   is `422 fs.not_a_folder`, a missing folder `404 fs.not_found`; `parent` is `null` at a root.
3. **The probe task** (`POST /api/sources`): `progress` is a **percent** (`100.0` at the end, as
   `TaskInfo` says), `message` is "Probing season" first, then "12/12 files"; the result is
   `{sources: [{id, path}], errors: [{path, code, message, detail}]}` (a missing file:
   `probe.not_found`, "The file does not exist."). An id is a hash of the path, so a probe of the
   same file gives the same id, after a restart too.
4. **`GET /api/sources` is server-wide**: it lists what every client probed. The store keeps
   its own list (what this tab opened) and takes from the listing only the ids its task gave.
5. **Grouping** (`POST /api/batch/group`, level `standard`) over the `season` folder: one group
   "Show S01" of 12, `E05` near ("1 extra track (eng AC-3 2.0 "Commentary")"), `E09` near ("1
   track missing (eng AAC-LC 2.0 "English Stereo")"). With `multitrack.mkv` open as well it
   joins that group as an exact member (the season was cut from it). An empty `source_ids` is
   `{groups: [], issues: []}`; an unknown id is `404 source.unknown`. Every open source is in
   some group (a group of one for a lone file).
6. **A probe warning**: none of the fixtures has one; `multitrack.mkv` remuxed with
   `-metadata:s:a:0 language=xx1` gives "Stream 1: language tag 'xx1' is not a language code."
   (the browser check's warning).

### Choices the plan leaves open

1. **Which sources the panel shows**: those this tab opened, in the order it opened them (item
   4). A file opened again keeps its place and gets the new probe.
2. **`open`** is one probe task per call (files and folders together); its progress shows in the
   panel per run (the server's "n/m files" once the task gives a count); paths that gave no
   source are one warning toast (`name: message: detail` per line); a failed task is an error
   toast, a cancelled one says nothing. The first new source is selected when none is active;
   `open(paths, { select: false })` (a member added to the contract) leaves the selection, and
   `ensure` uses it: `editor.loadJob` drafts nothing, and a `select` from `ensure` would start
   a newer `editor.open` that drops the queued job. A task the server no longer knows
   (`TaskLostError`: it restarted during the probe) is posted once more.
3. **`select`** sets `activeId` at once (the header names the new source while its draft
   loads), then `editor.open(id, editor.presetId)`. The source the editor already has is not
   drafted again (its edits stay). A failed draft (a toast already) makes the editor's source
   the active one again and rejects.
4. **Remove** asks first, in a bar at the top of the panel (sticky, `role="alertdialog"`, the
   focus on *Remove*, Escape keeps), not a PrimeVue `ConfirmPopup`: the popup needs the
   `ConfirmationService` in every mount and closes when the column scrolls. Delete on a group
   removes all its sources. `DELETE /api/sources/{id}`; a `404` counts as removed (the server
   forgot it already); another refusal is a toast and the source stays. The editor closes when
   its source goes, and also when the active source goes while it is still drafting (that draft
   is dropped). After a removal the focus goes to the next row.
5. **Groups**: `POST /api/batch/group` at the `standard` level (04's default; there is no
   setting for it) over the open sources that have a probe, from two sources on; the newest
   answer wins; a refused grouping lists the sources one by one and says nothing. A group with
   two or more open members takes the place of its first one; a group of one is shown as that
   source alone. Members are labelled as `reframe batch` labels them (`E05`, `S01E05` when a
   group spans seasons, the file name for a file without an episode or two of one episode),
   with a dot per member (circle: exact; diamond: near, with its differences below), and the
   header has the count, the level and the number of near matches. Groups are open by
   default; *Edit group* and *Add group to queue* are M7.
6. **A source's short line**: container, duration, the first video stream's commercial codec
   and size (`MKV · 0:04 · H.264 Constrained Baseline 320×180`); then its probe warnings. A
   source whose file changed or is gone (`source` `null`) says so with *Read it again*.
7. **Server restart and `refresh`**: the open paths are probed again in one task; each entry
   keeps its place and the active one stays active (the ids do not change, item 3); a path that
   no longer gives a source stays in the list without a probe.
8. **Keyboard in the panel**: a WAI-ARIA tree with one tab stop (the active source, else the
   first row): Up / Down / Home / End move, Right opens a group or goes to its first member,
   Left closes it or goes to the group, Enter and Space choose a source or open and close a
   group, Delete and Backspace ask to remove.
9. **The file browser** (`FileBrowserDialog`, mounted once by `App.vue`): a PrimeVue modal
   `Dialog` (`aria-modal="true"`, so the shell's shortcuts stay out: `Ctrl+O` inside it does
   not open a second one; its focus trap keeps the focus inside, and it gives the focus back to
   the element that had it when it closes). The pickers go through `fileBrowser.ts`: a pick
   while another is open cancels the older one (`[]` / `null`). Where it starts: the default
   path's folder (save), else the folder this mode showed last in this tab, else the first
   root of the kind (media for files and folders, output for save), falling back when a folder
   is gone. Roots on the left with their kind, breadcrumbs from the deepest root that holds the
   folder, *Up*, and a **Path** field: typing a path is how a folder outside the roots is
   tried, and the server's problem shows above the folder, which stays. Mouse: a click on a
   folder enters it; on a file, click / Ctrl / Shift choose as a desktop dialog does (Shift
   from the last plain or Ctrl click); a double click opens. Keyboard on the list
   (`role="listbox"`, `aria-activedescendant`): arrows, Home, End, Shift+arrows, Space
   (choose or toggle), Enter (a folder: enter; else open what is chosen, or with nothing chosen
   the file under the cursor), Backspace and Alt+Up (up), Ctrl+A (every file). Folder mode
   shows the files dimmed (they cannot be chosen) and gives the folder shown; save mode has a
   file name field (a click on a file takes its name) and gives folder + name, with no
   overwrite question (the queue's collision setting decides).
10. **The media filter (deviation).** The server lists media files only (item 1), so the
    dialog's filter can only narrow that list: a caller's `filters` (`pickFiles({ filters:
    ['srt'] })`, with or without the dot) shows a check box "Only srt", on by default, that
    can be turned off. The sources panel passes no filter, so in M4 the list is the server's
    media files with nothing to turn off. To show other files (M6's external subtitles need
    `.srt`, `.ass`, … through `pickFiles`), `GET /api/fs/list` needs an option for every file
    or for given extensions: a server change for the lead.
11. **The desktop path**: the panel calls only `platform.pickFiles`, `platform.pickFolder` and
    `platform.onFilesDropped` (registered while the panel lives); the dialog is never opened
    there. The desktop stub's `onFilesDropped` throws, so the desktop build needs D-x's
    implementation before the workspace mounts.

The test double of the sources store in `views/WorkspaceView.test.ts` (task C's file) gained
`probing` and `grouping`, which the real panel reads (commit `ca10002`, for the lead).

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

Built: `components/editor/tabs/VideoTab.vue` and `components/video/` (`EncoderPicker`,
`EncoderBanner`, `QualitySlider`, `SpeedPresetSlider`, `ChoiceSelect`, `CommandPreview`, the
helpers `encoders.ts`, `commandLine.ts`, `frameRates.ts`, `text.ts`, the composables
`useOutputLines` and `useCommandPlan`, test data in `testing/`), `i18n/messages/en/video.json`.
The advanced panel is M9.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` with the pinned FFmpeg n9.0.2 and `{"encoders": {"hardware_tests":
true}}` on this AMD desktop; `src/components/video/video.server.test.ts` does items 1–4:

1. **The picker's switch is the server's fix.** For the default preset's job set to `hevc_nvenc`
   and for the built-in *H.265 NVENC 1080p* preset, `switchEncoderOps(video, 'hevc_amf', …)` is
   the patch of the `encoder.unavailable` fix, operation for operation (encoder, quality CQ 22 →
   CQ 20 and CQ 27 → CQ 25 through the definitions' scale tables, the speed preset reset, the
   advanced options the new encoder lacks dropped), except the picker's own last operation (the
   custom parameters, "Choices" item 1).
2. **`EncodePlan.display`** is one line: each step's command shell-quoted (POSIX on Linux:
   `'title=Director'"'"'s Commentary'`), joined with ` && `, the last step `mv -f -- part final`.
   The tokenizer gives it back character for character.
3. **`jobs/plan` of a job with errors** is `422 jobs.invalid` with every issue (warnings and
   notes too) in `issues`; the preview lists the errors only.
4. **`jobs/geometry`** of `multitrack.mkv` (320×180) with the 1080p preset is 320×180 (no
   upscaling): the band of the first row (`max_height` 576). For a copied video `geometry` is
   `null` and `source` stays.
5. In headless Chromium (light and dark): the groups, dots and reasons; a click on an unavailable
   encoder changes nothing; the banner for the job (`This job uses hevc_nvenc …`) and for the
   preset (`Preset H.265 NVENC 1080p uses hevc_nvenc …`, fix *Use hevc_amf (closest match;
   quality CQ 27 → CQ 25, approximate)*); `Ctrl+Z` / `Ctrl+Shift+Z` on the encoder change take the
   banner and the field's error outline away and back; the fix, its undo; *Choose encoder* opens
   the picker with the focus on it; *Check again* runs a detection (every encoder `checking`, then
   the same results); a drag is one undo step; a typed `19.5`; two arrow keys; average bitrate
   with 2-pass changes the command (`-b:v:0 6000k`, `pass=1`); the copied text equals
   `display`.

### Choices where the plan leaves one

1. **Choosing an encoder converts, it does not clear**, with the rules of the server's
   closest-match fix (`switch_video_encoder`, ported to `encoders.ts`): the quality through the
   definitions' scale tables (rounded to the step, halves up), the bitrate into the new range,
   2-pass and turbo off where the new encoder has no 2-pass, the speed preset, tune, profile and
   level reset to the encoder's default where it lacks the value, 10-bit off where the definition
   has no 10-bit format or detection's 10-bit test failed (not while a cached result is checked
   again), a 10-bit-only profile reset with it, fast decode off where the encoder has none,
   advanced options kept only where the new encoder has the option and the value fits its type
   and range. All in one patch: one undo step. **The custom parameters are cleared** (the
   server's fix keeps them): they are written for one encoder (x265's `strong-intra-smoothing=0`
   is an error for every other one, one issue per parameter), and an info toast says so and that
   undo brings them back. The picker refuses an unavailable or failed encoder itself as well
   (PrimeVue's `Select` relies on `pointer-events: none` for disabled options).
2. **Status text**: `available` "Available"; `checking` "Checking…" (also `unknown` before the
   encoder list was read, and before any snapshot); `unavailable` / `error` "Unavailable: …" / "The
   check failed: …"; a cached failure that detection checks again "Checking again (last result:
   …)", and it can be chosen (0008's follow-up 1: the server says `encoder.checking`); `unknown`
   with hardware tests off shows the server's reason ("Not tested: …"). The reason is shown as
   text in the option, not only on hover (a disabled option takes no pointer events, so no
   tooltip), and is part of the option's accessible name.
3. **The banner** (`role="alert"`, above the tab's sections) names the preset only while the job
   still has the preset's encoder (`editor.preset.video.encoder`); after a change it says "This
   job uses …". The reason is the encoder status's; without one, the issue's message. Its fix
   buttons are the issue's (target `job` and `settings`).
4. **The recommended band** is chosen by the **short side** of the output picture (`jobs/geometry`
   `scaled_width` / `scaled_height`), not the height: a 1920×800 scope film and a 1080×1920 phone
   clip are both "1080p" content. The first band whose `max_height` holds it, the last one above
   all. Without an answer (a copied video, a failed request), the short side of the source (the
   answer's `source`, else the active source's first video stream). Asked at once for a new job,
   250 ms after an edit of the source, range, dimensions, filters or passthrough, never for other
   edits; the newest answer wins (`editor/latest.ts`). The hardware encoders' definitions have
   no bands: their slider has none.
5. **Undo steps of the sliders**: a drag is one step (`coalesce` named after the path,
   `endCoalescing()` at `slideend`); with the keyboard each key press is one (`keyup` ends the
   run; a held key is one step). A typed value is one step.
6. **Rate-control switch**: going back to the other mode brings its last value back (per job;
   a new job forgets them): the model holds one mode at a time. A new bitrate is 6000 kb/s in the
   encoder's range, 2-pass off. Turning 2-pass off turns turbo off in the same step.
7. **Frame rates**: HandBrake's list (5 … 120, the NTSC rates as exact fractions); a rate of the
   job not in the list is shown as `num/den`. The mode's help text says what Peak does (0013).
8. **Profiles** are offered for the job's bit depth (`Choice.bit_depths`); the current value is
   always offered so that its issue has something to point at. The `null` entry says the
   encoder's default for the bit depth ("Main 10 (default)"), else "Automatic" (profile, level) or
   "None" (tune).
9. **The custom parameters** show read-only (a `Field` at `video.custom_params`) so that their
   issues have a place and `ui.reveal` finds them; editing them is the advanced panel's (M9).
   Issues at `video.advanced.*` have no field before M9 (Summary lists them).
10. **The command preview is a drawer at the foot of the tab**, sticky while the tab scrolls, not
    PrimeVue's `Drawer`: that one traps the focus even when not modal, and the point of the
    preview is to edit with the command in view. Its open state is kept in this browser
    (`reframe.video.commandOpen`). It asks `jobs/plan` only while open: at once when opened or for
    a new job, 250 ms after an edit, and again when encoder statuses, tools or settings change;
    the newest answer wins, the last command stays (with "Updating…") until it comes. One line per
    step; options in the primary colour, paths green, filter graphs amber, programs bold (the
    status colours whose contrast `contrast.test.ts` checks). *Copy* copies `display` as the
    server wrote it (VueUse `useClipboard`, with the text-area fallback for a plain-HTTP LAN
    address).

### Consequences

- The client and the server both know how to switch encoders; item 1 of the real-server test
  fails when they drift.
- For G: the banner and Summary show the same `encoder.unavailable` issue from the validation
  store; the banner has `role="alert"` and the class `encoder-banner`.
- For L: the status texts are in `components/video/text.ts` (`useAvailabilityText`) and the
  mapping in `encoders.ts` (`availabilityOf`): Settings → Encoders can use both.
- For M (flow 3): the banner is `.encoder-banner`; its buttons `.encoder-banner__fix` (one per
  fix, the label is the server's), `.encoder-banner__choose`, `.encoder-banner__check`; the picker
  is `.encoder-picker` (`[role="combobox"]` inside), its options `.encoder-picker__option` with
  `[data-encoder="<id>"]` and `[data-state]` inside; fields carry `data-path`.

## Task I — F-10 Audio and Subtitles tabs

Built: `components/editor/tabs/{AudioTab,SubtitlesTab}.vue` (both are `components/tracks/TracksTab.vue`
with the list's name), `components/media/` (`TrackTable.vue`, the display helpers in `streams.ts`),
`components/tracks/` (`OutputTrackList`, `AudioTrackRow`, `SubtitleTrackRow`, `TrackRowFrame`, the
patch builders in `ops.ts`, test data from the real server in `testing.ts`) and
`i18n/messages/en/tracks.json`.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` with the pinned FFmpeg n9.0.2, fixtures `multitrack`, `dts-hd-ma`, `pgs`,
`text-subs`; `components/tracks/testing.ts` holds the definitions and probes as the server sent them.

1. **Bitrates.** `multitrack`: the AC-3 track has `bit_rate` 192 000 (`source: stream`); its two
   AAC tracks have neither `bit_rate` nor Matroska statistics tags (`source: unknown`, shown `—`).
   `dts-hd-ma`: the DTS-HD MA track is lossless and unknown (`—`, 24-bit), the AC-3 tracks 224 and
   192 kb/s from the stream. No fixture has statistics tags or `NUMBER_OF_FRAMES`, so every event
   count is `—`. `pgs`: two bitmap tracks, canvas 720×480, delay +200 ms.
2. **Encoders.** `libfdk_aac` is `unavailable` ("Not in this FFmpeg build"); the other six audio
   encoders are available. AC-3 and E-AC-3 list their allowed bitrates, AAC and Opus give ranges
   only; `libmp3lame` (and `libfdk_aac`) have a VBR quality (`-q:a` 0–9, default 2); FLAC is
   lossless. Containers: MKV copies any audio codec except a list, MP4 copies a list, WebM Opus
   and Vorbis; text subtitles go to `srt` (MKV), `mov_text` (MP4), `webvtt` (WebM).
3. **The draft** of `multitrack` with the default preset: three AAC stereo 160 kb/s tracks with
   `language` `ja` / `en` (BCP 47) and the source titles, three copied subtitles.
4. **The issues the rows show**, from `jobs/validate`: two burn-ins give `subtitle.burn_multiple` at
   the second track's action ("Only one subtitle track can be burned in; track 1 already is.");
   PGS copied into MP4 gives `subtitle.bitmap_unsupported` at each action ("MP4 cannot hold the
   bitmap subtitles of stream 1 (PGS)."); a passthru AC-3 track in MKV with gain, DRC or loudness
   set gives the warning `audio.passthru_settings_ignored` at its action.

Headless Chromium (Playwright 1.64.1, 1440×1000, light and dark) on port 8710, with the sources
store set through Pinia (E's panel is built in parallel): the tables for all four fixtures; a row
expanded with Enter and closed with Space; remove, *Add all*, *Add track* (a duplicate of the
default track is not default), undo and redo of each with `Ctrl+Z` / `Ctrl+Shift+Z`; move up twice
by keyboard with the focus following the track; a drag of the first row's handle below the fourth
(in a 1440×2400 viewport: a row is about 360 px high and a drag cannot leave the viewport); encoder,
mixdown, sample rate, bitrate, loudness, a typed gain and a DRC moved by the arrow keys, each one
undo step; passthru; VBR quality with MP3; *Reload from preset rules* and its undo; a Summary chip
landing on its row with the focus in it; the issues above at their fields; the MP4 note for text
subtitles.

### Choices where the plan leaves one

1. **Add all** adds an output track for each source track that has none yet, in source order
   (HandBrake's "Add all remaining tracks"), as one undo step; it is disabled when there is none.
   *Add track* is a menu of every source track, so a track can be added twice (two mixdowns).
2. **A new track** is the preset's own output for that source track when the editor's draft has
   one (`decisions[].outputs[0]`, `subtitle_decisions[].subtitle_outputs[0]`). Otherwise audio is
   encoded with the first encoder the container takes and the build has (AAC first), stereo (mono
   for a mono source) at the encoder's default bitrate for it; a subtitle is copied. The flags come
   from the source's dispositions; `language` and `name` are `null`, which the command builder and
   validation read as the source's (`OutputTrack.language` / `.title`). A track added while another
   track of its kind is default is not default.
3. **Another source** for a row replaces its metadata with the new source's (the row keeps its
   default flag): without the metadata editor (M6), an old title would stay on another track.
4. **Another encoder** fits the track in the same undo step: a mixdown the encoder cannot make
   becomes stereo (or its first), a bitrate outside its range for the layout or not in its list
   becomes its default for the layout, a VBR quality it lacks is cleared. **Another mixdown** moves
   a bitrate outside the new layout's range to its default. (The core snaps such values down and
   says so; HandBrake also resets the bitrate when the mixdown changes.)
5. **Passthru.** The row works out whether the track is copied as the core does (the container's
   copy list for the source codec); then it says "copied as it is" and turns the encoder settings
   off (still shown, so a value a warning names can be seen). When the container cannot hold the
   codec, the server's `audio.passthru_fallback` note at the action says what happens, and the
   encoder field is labelled *Fallback encoder*.
6. **Values offered.** Encoders: every audio encoder whose status is not `unavailable` (and the
   track's own). Bitrate: "Default (N kb/s)" (`null`), then the encoder's list or common steps
   inside its range for the layout (the source layout's when the layout is kept). Encoders with a
   VBR quality get a Bitrate / Quality switch. Gain −20 to +20 dB in steps of 1 (HandBrake's range;
   the model has no bound). DRC a slider 0–4 in steps of 0.1, "Off" at 0, with a help text that it
   acts on AC-3 and E-AC-3 sources only (`DRC_CODECS` of the command builder).
7. **Subtitles.** Convert is disabled for a bitmap track (FFmpeg has no OCR); choosing it sets the
   container's text format; leaving Convert clears the format and leaving Burn in clears forced-only
   in the same step. Burn in stays enabled for a second track: the validation error says why it
   cannot. Forced-only shows for a burn-in (or when set). A copied text track that the container
   cannot hold says it is converted (MP4: `mov_text`).
8. **Undo.** A typed gain or quality is one step until the field is left (`blur`), a DRC drag
   until the handle is let go (`slideend`) and a keyboard change until the focus leaves the slider.
   *Reload from preset rules* is `jobs/draft` with `editor.presetId`, and `editor.set` of that
   tab's list only (one step); the editor's draft (its decisions) is not replaced. An answer that
   comes after another job was opened (`editor.session`) is dropped.
9. **Issues.** A row is marked by its most severe issue (`issuesFor('audio[i]', { nested: true })`).
   Each control is a `Field` with its path; an issue at a path no shown field has (metadata, an
   external file, a quality while the bitrate is set) is listed under the row with `IssueList`
   (fix buttons and links).
10. **Table details.** `#` is the position among the source's tracks of the kind
    (`type_index + 1`); the source choice reads `2 · eng · DTS-HD MA 5.1 · English Dub` (the BCP 47
    tag when the file has one, else the tag ffprobe read, `und` without one). A disposition flag is
    shown beside the badges unless a badge set by that flag names it (`comment` under
    *Commentary*); the details list every disposition and every tag.
11. **Layout.** The output list is a PrimeVue `DataTable` over copies (`{ index, track }`: the job is
    frozen) whose header is hidden but read by screen readers (its inline `position: sticky` is
    overridden); a row has the drag handle, then its frame (number, issue mark, move up, move down,
    remove) and fields that wrap. The rows and the source table's scroll box use
    `contain: inline-size`, so a long label scrolls or wraps inside the 600–700 px tab column
    instead of widening it.

## Task J — F-12 presets UI

(Written by task J.)

## Task K — F-14 queue, activity and job log

(Written by task K.)

## Task L — F-15 settings

F-15 in its M4 part: `views/SettingsView.vue` and `components/settings/` (Tools, Encoders,
Output, Queue, Appearance). Languages (M6) and Preview (M8) are left out without a placeholder
(item 6).

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` (web mode, token) on ports 8740–8742, headless Chromium, light and dark:
one server with `--tools-dir` (the pinned FFmpeg through `REFRAME_FFMPEG` / `REFRAME_FFPROBE`)
and `--settings {"encoders": {"hardware_tests": true}}`, one with the tools from `PATH`, one
with a newer settings file. Every change below was read back with `GET /api/settings`.

- `GET /api/system` `tools`: `env_var` is set for every tool (the variable's name), `origin`
  is `env` only when it is set. MediaInfo (not installed): `missing`, `origin` `null`.
- **Web mode refuses a tool path**: `PUT /api/settings` with `/tools/mediainfo` = a path is
  `403 settings.tools_forbidden` ("A web client cannot choose the programs the server runs",
  detail "Set REFRAME_FFMPEG / REFRAME_FFPROBE on the server instead.", for any tool, no
  `issues`); `replace` with `null` is accepted (0049 item 9).
- Refusals: `/queue/parallel_jobs` 0, 2.5 or 99 is `422 settings.invalid` with one issue at
  `queue.parallel_jobs` (the model allows 1 to 16); `/encoders/vaapi_device` `/dev/dri/card1`
  is `403 settings.vaapi_device_forbidden` without issues; `/output/naming/output_folder`
  `/etc` is `403 path.outside_roots` without issues. An invalid template (`{bogus`) and an
  unknown `ui_language` (`xx`) are accepted.
- A change of `hardware_tests` or `vaapi_device` starts a detection by itself (the settings
  hook); with `/dev/dri/renderD129` (no such node here) the three VAAPI encoders are
  `unavailable`, "No VAAPI device (/dev/dri/renderD129)", `device` `null`. With hardware tests
  off every hardware encoder is `unknown`, reason "Not tested: hardware test encodes are off
  (Settings → Encoders)", `checked_at` `null`, `device` `null`. Hardware tests on (this AMD
  desktop): VAAPI available on `/dev/dri/renderD128` (the only render node; `/dev/dri` also has
  `card1`).
- `settings_read_only`: true when the settings file is newer than the server or unreadable
  (`SettingsStore._protect`); tried with `--settings {"schema_version": 999}`:
  `settings_read_only: true` and the problem `settings.newer_version`. The page shows the note
  and every control off.

### Choices where the plan leaves one

- **What *Test* does.** The server has no route that tests a path without using it, and
  `POST /api/system/tools/rescan` takes no body. *Test* saves a changed path
  (`settings.set('/tools/<tool>', path)`, an empty field is `null`: automatic), calls
  `system.rescanTools()` and shows the tool's result under the row ("Works: version …" or
  "Does not work: <reason>"). When the new path does not work it offers *Put back <old path>*
  (or *Put back automatic*), which saves the old value and re-scans. An unchanged path only
  re-scans. A refused path shows at the field and nothing is re-scanned.
- **Tool paths in web mode are read-only** (the server refuses them, see above), with a note
  that names the tool's variable; *Test* there only re-scans. *Remove override* (a Settings
  path set to `null`) works in both modes. The editable path and the *Put back* flow are for
  the desktop app; rule 7 allows only web-mode servers, so that flow is proven by unit tests
  only. An environment override is read-only in both modes, shows the program the variable
  names, and says to change or unset the variable and restart. An ffprobe found next to an
  overridden ffmpeg keeps its own field: its Settings path still wins over the sibling.
- ***Use bundled FFmpeg*** is one button of the section (the download is the FFmpeg family's):
  `system.fetchTools()`, and when its task ended `done`, the Settings paths of ffmpeg and
  ffprobe are set to `null` (they would still win over the bundled build); a failed download
  changes nothing (its toast is the API layer's). Off when the environment sets both. Not
  clicked for real (it downloads FFmpeg); unit tests.
- **VAAPI device choices.** The server lists no render nodes. The choices are *Automatic*
  (`null`), each node in a VAAPI encoder's `device`, the saved node, and *Another render
  node…*, which shows a text field; the server refuses anything but `/dev/dri/renderD<n>` in
  web mode, and the refusal shows at the field with the typed text kept.
- **Encoder table**: every video encoder of the definitions, then the audio ones, then any
  other the snapshot names; the status is H's `availabilityOf` / `useAvailabilityText` (the
  reason is in that line); the per-encoder `checked_at` ("Not checked" when `null`) and the
  snapshot's last full check. *Re-scan* is busy until `system.rescanEncoders()` returns or
  while a detection runs.
- **Saving.** Each control saves at once through `settings.set` (`useSetting`); a refused value
  stays shown at its `Field` with the server's issues, or one issue made of the problem's title
  and detail, until the next save of that control. The naming options (F's editor emits a new
  object per key) are saved 600 ms after the last edit, as one patch of the changed members; a
  waiting edit is saved when the page is left; a refusal is listed under the editor (wrapping
  the editor in a `Field` outlined every control in it).
- **When done** goes through `queue.setWhenDone` (it also cancels a countdown for another
  action). In web mode *Quit Reframe* is shown as "desktop app only" and cannot be chosen: a
  server for browsers keeps running. Sleep and Shut down stay (they act on the server's
  computer; the help says so).
- **Appearance**: theme and density through `useTheme()`; the UI language lists
  `SUPPORTED_LOCALES` by their `Intl.DisplayNames` name (English only); a saved language this
  build lacks is shown as "(not available)".
- **Read-only settings** turn every control off, theme and density included (the rail's theme
  switch still changes them for this browser). *Test* and *Check again* still re-scan.
- **Sections** show once `system.info` and the settings are loaded. `/settings#tools` (and the
  section links at the top, plain links so that none is marked as the current page) move the
  focus to the section.

### Consequences

- A server route that tests a path without saving it (`POST /api/system/tools/test {tool,
  path}`, desktop mode only) would let *Test* leave the settings alone; not needed for M4.
- `App.test.ts` mounts the real views without `matchMedia`, which PrimeVue's `Select` calls when
  it mounts: it passes only because the Settings sections wait for the settings, which that
  test never loads. A shared Vitest setup file with a `matchMedia` stub would remove the trap.

## Task M — F-17 Playwright set-up and flow 3

(Written by task M.)
