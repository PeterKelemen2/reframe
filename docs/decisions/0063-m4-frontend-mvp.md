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

Built: `views/QueueView.vue`, `views/ActivityView.vue`, `stores/activity.ts` and
`components/queue/` (`QueueTable`, `QueueControls`, `WhenDoneSelect`, `PowerBanner`, `JobLog`,
`useJobLog.ts`, `format.ts`, `activityLines.ts`), `i18n/messages/en/queue.json`.

### What was checked against the real server (2026-10-29)

`scripts/dev-server.py` (web mode, token, port 8730, `--tools-dir` the pinned FFmpeg n9.0.2,
fixtures `multitrack` and `hdr10-4k`), headless Chromium, light and dark. The slow jobs are the
4K fixture at 3840×2160 with libx265 `placebo` (about 40 s each here; `veryslow` was 27 s,
too short to stop the queue under it).

- **The dry run** was confirmed before the countdown from the server process itself:
  `/proc/<pid>/environ` of `python -m reframe_server --mode web --auth token …` had
  `REFRAME_POWER_DRY_RUN=1` and the temporary `REFRAME_CONFIG_DIR` / `REFRAME_DATA_DIR`. Only
  *Sleep* was tried, and each countdown was cancelled after 2 s (`GET /api/power` then
  `pending: null`). *Shut down* was never chosen.
- **Stop**: with one job running and two waiting, *Stop* gave `processing: false`; the running
  job ran on to `done` (21–24 s later) and 3 s after that both waiting jobs were still
  `waiting` with `processing: false` (store and `GET /api/queue`).
- **`processing` / `only` in the store** follow the real events
  (`components/queue/queue.server.test.ts`): `POST /api/queue/start {job_ids: [A]}` (another
  front end) gives `processing: true, only: [A]`; the store's `start()` widens it to
  `only: null`; `stop()` gives `false` and the waiting job stays waiting after the running one
  is cancelled; a start whose named job had ended gives `start` then `idle` (`false, null`).
  The activity log has the reasons in order: start, start, stop, start, stop, start, idle.
  Removing the store's `only` update makes the test fail.
- **The job log**: `GET /api/queue/{id}/log` is empty before the first run; while x265 encodes
  a 4K file the log grows only at the run's start (about 50 lines) and at its end (the stats,
  the steps, the rename: 67 lines), so the follow mode was seen to keep the view at the end
  when the end lines came, and to leave it where it was after a scroll up. A log read on from
  `next` at its end answers `{text: "", next, more: false}`. Copy all gave the server's whole
  log byte for byte (4106 characters, the first line `=== Reframe job …: run started …`).
- **When done**: `PUT /api/queue/when-done` with `sleep` is read back as
  `settings.queue.when_done`; the countdown came at once after the last job ended
  (`power.countdown` `started`, then `tick` once a second; the banner showed "in 58 s").
- **Reorder**: a keyboard move up sent the two jobs (`PUT /api/queue/order` with the moved job
  and its neighbour in their new order); a drag sent every job; `GET /api/queue` had the same
  order both times.

### Choices where the plan leaves one

- **The activity bound.** At most 1000 entries (`MAX_ENTRIES`); older ones are dropped. Events
  that come several times a second (`job.progress`, up to 4 per second per job; `job.log`;
  `task.progress`; a countdown's `tick`) and a `queue.changed` that only added jobs keep only
  their latest entry per job, task or countdown: the newer one replaces the older. So a long
  encode leaves one progress entry, not thousands, and B's dispatcher still records every
  event (its test reads them back). The view shows none of these entries: a job's addition is
  its `job.state` with `previous: null`, a removal or a reorder is a `queue.changed` compared
  with the order before (the first one with the queue store's jobs). A removed job keeps its
  name: the dispatcher records an event before the queue store applies it, so the store still
  has the job then.
- **The log follow rule.** The log is read whole from byte 0 in chunks until `more` is false,
  then read on from `next` each time `queue.logTicks[id]` changes and once more when the job
  ends (the end lines can come after the last `job.log` event). A tick during a read makes one
  more read after it, however many ticks came. A line cut by a chunk end is joined. The view
  follows (stays at the end) when it opens and after each new line, unless the user has
  scrolled up: a scroll leaves follow mode when the view is more than 4 px from the end and
  enters it again at the end; *Follow* jumps back. The scroll to the end waits one frame (the
  virtual scroller sizes its content after its own update) and is skipped when the user
  scrolled up in that frame.
- **The log viewer** is a PrimeVue `Drawer` (modal, Escape closes it); on close the focus goes
  back to the row's log button. A line's height is 1.4 rem in pixels (the virtual scroller needs
  pixels); long lines scroll sideways, they do not wrap.
- **Start and the run state.** Start is enabled when the queue is stopped with waiting jobs, and
  while `only` is set (then labelled *Start all*: a Start without ids widens the run to every
  waiting job). The UI never starts with ids. `only` is matched with the jobs in the queue for
  the count ("only the jobs another front end started (1)").
- **When done in web mode** follows task L: *Quit* is shown as "Quit Reframe (desktop app
  only)" and cannot be chosen (`system.info.mode !== 'desktop'`); *Sleep* and *Shut down* act
  on the server's computer, as the help says. The selector waits for the settings (the value is
  a setting).
- **Reveal in folder** shows only when `platform.kind === 'desktop'`, for a done job: calling
  `revealInFolder` to find out would open a file manager on the desktop.
- **A failed job** shows its error and its issues (message and severity, no fix buttons: the fixes
  are for the editor's job) in an expanded row under it; *Edit* takes the job to the editor.
- **Icon-only buttons** in the table do not shrink: a small icon-only PrimeVue button has less
  room than an 18 px icon, and the icon (a flex item) shrank to 10 px (measured in Chromium).
  The same happens in the track rows (finding L9).

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

Built: `frontend/playwright.config.ts` (the servers, `retries: 0`, timeouts, one worker per
project), `frontend/e2e/support/servers.ts` (the `webServer` entries), `support/app.ts` (open
the app, open a file through the file browser, wait for a store value, read and act on the
queue), `support/test.ts` (the `test` with the queue fixture), the scenario
`e2e/fake-ffmpeg.json`, the settings `e2e/settings.json`, and flow 3,
`e2e/flow3-unavailable-encoder.spec.ts`.

### What was checked against the real tools (2026-10-29)

1. **The FFmpeg of the tests.** `scripts/dev-server.py --fake-ffmpeg e2e/fake-ffmpeg.json
   --settings e2e/settings.json` (hardware test encodes on), with the pinned FFmpeg n9.0.2 first
   on `PATH`, gives in `GET /api/system/encoders`: `libx264`, `libx265`, `libsvtav1`,
   `libvpx-vp9` available; `h264_nvenc`, `hevc_nvenc`, `av1_nvenc` unavailable "NVIDIA driver
   not found"; the QSV encoders "No Intel QSV device (needs an Intel GPU with its media
   driver)"; the AMF encoders "AMD AMF runtime not found (libamfrt64.so.1)"; the VAAPI encoders
   "VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error)"; `libplacebo` a
   filter failure "No working Vulkan driver"; `ffmpeg_version` the pinned build's. The built-in
   *H.265 NVENC 1080p* on `multitrack.mkv` then shows the banner "Preset *H.265 NVENC 1080p*
   uses `hevc_nvenc`, which is not available: NVIDIA driver not found" with the fix *Use
   libx265 (closest match; quality CQ 27 → RF 22, approximate)*, and the job encodes to `done`
   with the real libx265.
2. **The stop.** Playwright 1.64.1 starts each `webServer` command through a shell spawned
   `detached` (a new process group: `sh`, `uv`, `dev-server.py`, `reframe_server`, its
   ffmpeg). Without `gracefulShutdown` it ends the group with SIGKILL, which would leave the
   server's home behind; with `gracefulShutdown: { signal: 'SIGTERM', timeout }` it sends
   SIGTERM to the group, waits until the shell's output pipes close (every process of the
   group holds them, so this is when `dev-server.py` has finished), and sends SIGKILL only after
   the timeout. It starts the `webServer` entries one after the other, before any global set-up,
   and stops them on SIGINT too (read in `playwright/lib/runner/index.js` and
   `playwright-core/lib/coreBundle.js`). `uv run` (0.13.5) passes SIGTERM on to its child and
   waits for it: SIGTERM to the `uv` process alone stopped the server and removed the home.
   `dev-server.py` acts on the first signal only, so the group's SIGTERM plus uv's forwarded one
   do no harm.
3. **Nothing left behind**, checked with `pgrep -af "dev-server|reframe_server"` and
   `ls -d /tmp/reframe-dev-*` after two passes in a row, after a forced failure, and after
   SIGINT to the whole process group of `npm run e2e` (what Ctrl+C in a terminal sends) while
   both tests ran: no process and no home of this run (npm exited with 130 after about 1 s).

### Choices where the plan leaves one

1. **The fake FFmpeg passes through.** 06 asks for fake FFmpeg; flow 3 needs an encoder that is
   unavailable with a reason, and a closest match that is the same on every machine. With the
   real FFmpeg the answer depends on the machine (this AMD desktop: `hevc_amf`; no GPU:
   `libx265`; an NVIDIA GPU: NVENC works and the flow cannot run). The scenario answers every
   hardware test encode (`-i color=size=640x360 … -c:v <hw>`) with a captured real failure of
   its family (`fake_data/`, NVENC: "Cannot load libcuda.so.1") and passes every other call to
   the real `ffmpeg` / `ffprobe` (`exec`), so the probe and the encode are real. The closest
   match of `hevc_nvenc` (chain QSV, AMF, VAAPI, libx265) is then always `libx265`, the plan's
   own example (03 §Missing encoder behaviour), and the flow names it. Which real FFmpeg: the
   folder in `REFRAME_TEST_TOOLS_DIR`, else the pinned build in `.tools/`, put first on the
   servers' `PATH`; else the `ffmpeg` already on `PATH` (it needs libx265).
2. **One server per browser project** (Chromium 8750, Firefox 8751), each a new home with the
   `multitrack` fixture and the known token `reframe-e2e-token`; the page opens `/#token=…`.
   The projects run at the same time; inside a project the tests take turns (`workers: 1` per
   project), and the auto fixture `ownQueue` (`e2e/support/test.ts`) gives the queue back as it
   found it: Stop if it was not processing, cancel the test's running or paused jobs, wait for
   them to end, remove the test's jobs. A test finds its own job as the one whose id was not in
   the queue before. Without the fixture a second run on the same server fails ("the job was
   added as failed": *multitrack.mp4* is also the output of a waiting job; or the job runs at
   once because the queue was left started). What it does not give back: the output file of a
   finished job stays in the output root, so a later flow on the same fixture sees that file.
3. **`dist/` is built on every run**: the first `webServer` command is
   `npm run build:web && uv run python scripts/dev-server.py …` (about 1 s), and Playwright
   starts the second server only after the first answers.
4. **Server output is not shown** (`stdout` / `stderr: 'ignore'`): the server logs every
   request. `DEBUG=pw:webserver npm run e2e` shows it.
5. **No retries** (`retries: 0`), screenshots only on failure, traces kept on failure (in
   `e2e/.results/`, git-ignored). Store values are waited for with `expect.poll` over
   `page.evaluate` of a function (the app's CSP refuses a string), through the app's Pinia; the
   flow itself acts only through the UI.

### Consequences

- **`scripts/dev-server.py` leaves its home behind when it fails before the server starts**
  (a missing fixture, an unreadable `--settings` file): the home is made with `mkdtemp` before
  the `try` whose `finally` removes it (`--fixtures multitrack,nonexistent` left
  `/tmp/reframe-dev-rvl_8n8e`). For the lead: wrap everything after `mkdtemp`.
- A second Ctrl+C within the stop makes Playwright exit at once and kill the group with
  SIGKILL, which can leave a home behind; one Ctrl+C is clean.
- CI (Q-1.1) needs, for `npm run e2e`: Python with `uv sync`, `testdata/media/multitrack.mkv`
  (`scripts/make-testdata.py`), `npm ci`, the browsers (`npx playwright install chromium
  firefox`, CI only), an FFmpeg with libx265 in `REFRAME_TEST_TOOLS_DIR` or on `PATH` (the
  bundled build in the job's `REFRAME_DATA_DIR` is not seen: `dev-server.py` gives the server
  its own data folder), and the ports 8750 and 8751 free.
- 09 §Q-2 names Chromium and WebKit; M4 runs Chromium and Firefox (the browsers in the cache);
  06 §F-17 leaves WebKit for M10.

## Review, 2026-10-29

Two fresh reviews at 57eb8cc (R1: the API layer, events, stores, editor state, undo, validation,
the queue and Stop; R2: the screens, i18n, keyboard, focus, contrast, empty and error states):
R1 found 2 majors and 3 minors, R2 1 blocker, 6 majors, 11 minors and 7 nits; with the lead's
integration findings L1–L17 they are assigned in [m4-breakdown.md](../m4-breakdown.md),
"Fix round". The lead reproduced every blocker and major before the fixes. R2 reported that one of
its scripts chose *Shut down* as the when-done action (it counted arrow presses, which skip the
disabled *Quit*); the server ran with `REFRAME_POWER_DRY_RUN=1` (R2 checked
`/proc/<pid>/environ` first) and the countdown was cancelled after about 2 s.

### Fix round — FA (theme and base)

2026-10-30. Checked against a real server (`scripts/dev-server.py`, the real FFmpeg with hardware
test encodes on, `multitrack`, `pgs`, `hdr10`) in headless Chromium and Firefox, light and dark,
and with `npm run e2e`.

1. **R2-1 (blocker): screen-reader text made the page taller than the window.** An absolutely
   positioned box with no offset stays at its static place. In a scrolled column with no
   positioned parent its containing block is the page, so each `.rf-sr-only` span low in a long
   column made the page taller than the one-window shell. `.rf-sr-only` now has
   `inset-block-start: 0; inset-inline-start: 0`, so it adds nothing to the page. Before: Summary
   3,366 px in a 900 px window (4,011 / 4,024 px in the 720 px window of the e2e run, Chromium /
   Firefox), Settings 4,407 px (1,458 px), and a section link scrolled the window by 392 and 663 px.
   After: every screen (empty workspace, Summary, Video, Audio, Subtitles, Settings before and after
   a section link, Queue, Presets, Activity) is exactly the window's height in both browsers and
   both themes, and a section link scrolls only the Settings column. Test: `e2e/layout.spec.ts`
   (the page is no taller than the window and not scrolled on Summary and Audio with a file open,
   on Settings before and after a section link, and on the Queue with a job). With the old rule,
   Summary and Settings fail in both browsers. The Queue check passes with the old rule too (its
   hidden texts are inside PrimeVue's DataTable, which is positioned), so it only guards the
   Queue view. `overscroll-behavior: contain` on the column scrollers (C's and FC's files) is not
   needed now, because the page has nothing to scroll. It is still harmless as a second guard.
2. **R2-2 / L4 (major): the compact issue list gave the message 0 px.** In compact mode the fixes
   were a third grid column that did not wrap. The fixes now go on their own wrapping row under
   the message, as in the full list. Compact keeps only the tighter padding and type. Before: the
   message box was 0 × 1,299 px beside "Use hevc_amf (closest match; quality CQ 27 → CQ 25,
   approximate)". After: 470 px wide in the status bar's list at 1,440 px. Test: the e2e spec
   (with the NVENC preset under the fake FFmpeg, the closest-match issue's message is wider than
   200 px). With the old rule it is 0 px in both browsers.
3. **R2-5 and R2-6 (majors): text and control contrast.** The preset now sets Aura's component
   tokens:
   - Solid info, success, warn, help and danger buttons use the 700 shade with white text in light
     (hover 800, pressed 900, focus ring 700). Outlined and text buttons use the 700 shade in light.
     Secondary text is slate-600 in light and zinc-300 in dark.
   - Outlined borders are 3:1 against the surface: slate-500 / zinc-500, the 600 shade of a
     severity, and primary 500.
   - Toasts and messages have opaque tints (50 in light, 950 in dark). Their titles use the 700
     shade (yellow 800) in light and the 300 shade in dark.
   - In a SelectButton the unselected labels are slate-600, and the checked option is **filled
     with the primary colour**. This is a visible change of design: a white chip in a light-grey
     group was 1.1:1, and a border alone was a weaker sign of the selection.
   - The switch's off track is slate-500 / zinc-500. In dark its handle is zinc-950 (a light
     handle on the lighter hover track was below 3:1). The slider's track is slate-500 /
     zinc-500, and its handle has a ring in the primary colour.

   | Pair | Light before → after | Dark before → after |
   |------|----------------------|---------------------|
   | *Modified* marker (outlined warn) on the surface | 2.80 → 5.18 | 7.83 → 7.83 |
   | its border | 1.35 → 3.56 | 3.42 → 4.98 |
   | the countdown's *Cancel* (white on solid warn) | 2.80 → 5.18 | 6.92 → 6.92 |
   | read-only settings note (message warn) | 2.85 see-through → 6.62 | 6.73 see-through → 11.06 |
   | toast titles: warn, success, error, info | 2.85, 3.16, 4.43, 4.77 (see-through) → 6.62, 4.79, 5.91, 6.16 | 6.73, 5.92, 3.98, 3.96 (see-through) → 11.06, 10.62, 8.51, 8.15 |
   | outlined *Delete* (outlined danger) | 3.76 → 6.47 | 6.40 → 6.40 |
   | white on solid danger | 3.76 → 6.47 | 5.84 → 5.84 |
   | unselected SelectButton label | 4.34 → 6.92 | 7.76 → 7.76 |
   | outlined secondary text on an error issue (red-50 / red-950) | 4.35 → 6.93 | 6.30 → 10.92 |
   | switch off track on the surface | 1.48 → 4.76 | 1.70 → 3.67 |
   | switch handle on the off track | 1.48 → 4.76 | 4.07 → 4.12 |
   | slider track on the surface | 1.23 → 4.76 | 1.70 → 3.67 |
   | slider handle ring on the surface | 1.23 → 6.29 | 1.70 → 5.94 |
   | SelectButton checked option against its group | 1.10 → 5.74 | 1.34 → 6.67 |
   | outlined secondary border on the surface | 1.23 → 4.76 | 1.70 → 3.67 |
   | focus ring of a solid warn button | 2.80 → 5.18 | 7.83 → 7.83 |

   "See-through" rows are measured over the content background. Test: `styles/contrast.test.ts`
   mounts Button, Toast, Message, Tag, SelectButton (with options, for the toggle buttons' own
   variables), ToggleSwitch, Slider, Select and Listbox, so that PrimeVue writes their variables.
   It then checks text pairs (4.5:1) for every button kind and state, outlined and text buttons
   on the surfaces and on the issue backgrounds, toasts, messages, tags, SelectButton labels and
   list options. It checks control pairs (3:1) for outlined borders, the buttons' focus rings,
   the switch, the slider and the checked option. It also requires opaque toasts. A see-through
   background (a hover tint) is measured on the content background. With the preset before this
   change, 6 of 6 tests failed with 132 pairs. Measured on the page with R2's `nontext.js`
   (Video tab), the values match the table. The only low row is "slider handle" at 1.32 / 1.62:
   that row measures the handle's ring against the 3 px track under it. The handle is 20 px
   across, its ring is 6.29 / 5.94 against the surface, and its centre is 4.76 / 4.12 against the
   track. The filled range (indigo) differs from the track (grey) by hue only (1.3:1). The handle
   shows the value.
4. **L15: a disabled button in dark looked enabled.** PrimeVue fades a disabled button to 60 %,
   so a disabled *Add to queue* kept its indigo. `main.css` now paints a disabled solid button of
   the primary or a coloured severity with the form field's disabled colours (slate-200 /
   slate-500 in light, zinc-700 / zinc-400 in dark). Secondary, outlined, text and link buttons
   keep the fade, which reads as disabled for greys. A busy (loading) button keeps its colour. The
   painted disabled *Add to queue* against the enabled *Open files…* changed from 2.25 to 5.10 in
   light and from 2.01 to 3.50 in dark. Its label changed from 1.92 to 3.86 (light) and from 2.01
   to 4.07 (dark). WCAG asks nothing of a disabled control; 3:1 is our floor, so that the label
   stays readable. Tests: the e2e spec measures the two painted fills in light and dark (≥ 3:1;
   2.25 without the rule). `contrast.test.ts` checks the disabled greys: the label 3:1, and the
   fill 3:1 against every enabled solid fill (Aura's 500 shades were 1.85 to 2.27 from
   slate-200).
5. **R2-9 / L9: icons shrank in small icon-only buttons.** The small size's padding wins over the
   icon-only padding and leaves 10 px, and the lucide icon is a flex item, so it shrank. One rule
   in `main.css` (`.p-button svg { flex: none }`) fixes it. Test: the e2e spec (the header's and a
   track row's icons have their own width; 10 of 18 px without the rule). The local copy in
   `QueueTable.vue` (K's file) is left as it is.
6. **R2-15: the outline of a field missed the checked option.** `Field` no longer sets
   `--p-togglebutton-border-color`. A SelectButton inside a field with an error or a warning gets
   one outline round the group. Checked on an HDR10 source with 8-bit chosen: amber-700 (light)
   and amber-400 (dark) round both options. There is no unit test: jsdom does not apply the
   scoped style.
7. **R2-16: PrimeVue's own texts bypassed vue-i18n.** `components/base/primevueLocale.ts` builds
   PrimeVue's `locale` from `base.json` (`base.primevue.*`), and `setup.ts` passes it. The
   locale covers the texts of the components the app uses: empty and filtered lists, the live
   regions of Select and Listbox, the close, previous and next buttons, DataTable row
   announcements and the confirm dialog. PrimeVue keeps its defaults for the other components.
   PrimeVue puts a count into `{0}` itself, after vue-i18n, so no plural form can be chosen.
   The counted texts are therefore worded to read right for any count: "Options selected: 1",
   "Options found: 3". The locale is built once at the start: a second UI language needs it to
   follow `i18n.global.locale`. Test: `components/base/primevueLocale.test.ts` mounts Listboxes
   with the app's plugins. The live region says "Options selected: 1" ("1 items selected" without
   the locale), and an empty list says "No options" and "Nothing selected".
8. **R2-17: weak focus of list options.** The option of a Select or Listbox under the keyboard or
   the pointer now has an inset 2 px ring in the primary colour (6.29 / 5.94 against the list),
   in addition to the tint (1.10:1). Checked with the arrow keys in an open Select in Chromium and
   Firefox, light and dark.
9. **R2-25: a field's gutter bar shows over the open command drawer.** This is not a stacking
   problem. The bar is drawn 8 px left of the field, in the Video tab's side padding. The drawer
   (`.command-preview`: sticky, `z-index: 1`) does not cover that padding, so the bar shows
   *beside* the drawer, not over it. No stacking change on the bar can hide it. The drawer
   (`components/video/CommandPreview.vue`, not FA's) needs to cover the side padding, for example
   with
   `.command-preview::before { content: ''; position: absolute; inset-block: -1px; inset-inline: calc(-1 * var(--rf-space-4)); z-index: -1; background: var(--rf-color-surface); }`.
   Checked by injecting this rule in the browser: the bar no longer shows next to the open drawer.
   Applied 2026-11-01 with one change: that rule also paints over the drawer's own border, side
   shadow and rounded corners (its `::before` sits above them), so the built rule fills only
   the two padding strips (a hard-stop gradient with a clear middle). Test:
   `e2e/layout.spec.ts`, "the open command drawer covers the padding where a field's bar is
   drawn" (what is hit 6 px left of the drawer is the drawer). Checked with a bar injected
   beside the drawer, headless Chromium and Firefox, light and dark: the bar shows above the
   drawer, not beside it, and the border and corners are as before.

### Fix round — FB (the job that is queued)

2026-10-30. Each fix with a test that fails without it: the new tests were run against the code
before the fix (all 12 of `addToQueue`, `OutputCard`, the two of `sources` fail there, R1's
reproductions as assertions), and 45 mutations of the fix each failed a test. Browser checks: R1's
scripts and FB's own (`review-r1/`, the scratchpad's `fix-fb/`), headless Chromium against
`scripts/dev-server.py` (pinned FFmpeg n9.0.2, `multitrack`, `hdr10-4k`).

**The design: an add takes the job the screen shows.** Two things can show a value that the job
does not have: a field that writes only when it loses the focus (PrimeVue's `InputNumber` writes on
blur or Enter, and returns early from its keydown while Ctrl is held; the naming fields), and an
edit that waits for the server before it writes (the naming editor's preview, the Output card's
extension below). So:

- **Pending edits** (editor store): `beginEdit(edit)` / `endEdit(edit)` with
  `PendingEdit = { flush(), failure }` (a reactive object of its owner); `editing` is true while
  one is on its way, `editFailure` gives the reason of one whose request failed; `flushEdits()`
  asks each to come in at once (no debounce; once more after a failure). A new session drops them.
- **`validation.flush()`** sends a debounced validation at once (one under way goes on:
  `latestRequest.flush()`), or asks again after a failed one.
- **`addCurrent`, `Ctrl+Enter` and *Add all*** first commit the focused text field (blur it, then
  give it the focus back: `editor/focus.ts`), call `flushEdits()`, and wait — a Vue watcher with
  the default flush, so that an edit landing and the check it starts are seen together — until
  no edit is on its way, the editor is not loading and the check has answered (flushed when
  nothing else is waiting; a failed check asked once more; 20 s at most). Another session opened
  meanwhile ends the add silently. Then the job *as it is* is added, or a warning toast says why
  not: its first error, "could not be checked", "the output name could not be updated: …", no
  output path, or still being checked after 20 s.
- **`canAdd`** no longer turns false for a pending check or an edit on its way: the add waits for
  them. A click on *Add to queue* right after typing blurs the field on mousedown, the value goes
  into the job and the check starts; the button stays enabled under the pointer (R1-3). It still
  needs the last check's issues to have no error, an output path, no draft loading and no add
  under way. `Ctrl+Enter` calls `addCurrent` even when `canAdd` is false: the value typed into
  the focused field may be what fixes the job. `QueueActions.busy` is added (an add, with its
  wait, is under way) for the status bar's button. This replaces C's item 8 on `canAdd` and the
  "still being checked" line of item 9 (*Add all* waits instead).
- **The naming editor** (replaces F's items 2 and 3 where they differ): an edit, typed or not
  (mode, *Use the preset's template*, name source, chips, "Use {…}", field overrides), is a
  pending edit while the fields show a naming the job does not have, and goes into the job only
  with its preview's name: naming and path in one patch, so they are always one undo step (R1
  suspected 2: the path no longer follows the naming as a later step). A blur previews at once
  and ends the typing's undo step when it lands (it no longer puts the naming in without its
  path). A failed preview keeps the edit out of the job, shows why, and is a failed pending edit
  (`editFailure`); an add asks it again and adds nothing while it fails (R1 suspected 3: a job
  never has a naming whose path it lacks, so no *Use this path* is needed for it). An answer for
  a job that changed after the request went out is not taken: the job is named again as it is.
  An edit on its way when the editor unmounts (leaving Summary) still goes into the job; a
  failure then is a toast "The output name was not changed".
- **A container change** (the Output card) writes the container and the path with the
  container's first extension in one patch with its own coalescing key; for a container with
  more than one extension (MP4: `.mp4`, `.m4v`) `naming/preview` of the job with the new
  container gives the naming's extension (`mp4_extension`, Auto's rule), which follows under the
  same key, so it is one undo step — unless the job changed since (an undo wins). Until it comes
  it is a pending edit. A failed request keeps the first extension, which validation accepts. A
  container change from elsewhere (a validation fix) brings its own path; one without (a script
  through `editor.set`) still gets *Use this path* from the naming editor.

Findings and tests:

1. **R1-1** (`Ctrl+Enter` without the typed value). Tests: `addToQueue.test.ts` (real editor and
   validation stores, a PrimeVue `InputNumber`, the naming editor, the shortcut: the typed quality
   30 and the typed template with its path are queued; the focus is back in the box);
   `useQueueActions.test.ts` (a field that writes on blur; the wait for a check, for an edit, for
   both in turn). Chromium: `ctrl-enter-quality` queues `{"mode":"quality","value":30}` (was 22),
   `ctrl-enter-naming` queues `{main_title} MYNAME` with `…/multitrack MYNAME.mkv` (was `null`).
2. **R1-2** (a naming change without typing). Tests: `JobNamingEditor.test.ts` (*Use the preset's
   template* and *Manual name* are pending edits until they land; `flushEdits` sends them at
   once), `addToQueue.test.ts` (*Reset* then Add queues `null` and the path it gives).
   Chromium: `naming-mode-add` and `naming-mode-add-gap` (`R1_GAP=200`): Add enabled, the queued
   naming is the new one (manual `multitrack`; template `null` after Reset).
3. **L1** (a container change keeps the old extension). Tests: `OutputCard.test.ts` (MP4: `.mp4`
   at once, one undo step back to MKV and `.mkv`; the naming's `.m4v` in the same step; an undo
   before the answer is not overwritten; a failed request keeps `.mp4`; WebM asks nothing).
   Chromium: MP4 then *Add to queue* at once queues `mp4 …/multitrack.mp4`; with
   `mp4_extension: m4v` the path goes `.mp4` → `.m4v`; one `Ctrl+Z` gives `mkv …/multitrack.mkv`.
4. **R1-3** (a click on *Add* right after typing). Tests: `useQueueActions.test.ts` (`canAdd`
   with a pending check or an edit on its way), `addToQueue.test.ts` (the blur of the box leaves
   *Add* enabled and the add queues 30). Chromium: `click-add-quality` 1 added with 30 (was 0
   added), `naming-click-add` 1 added with `{main_title} CLICKADD`.
5. **R1-4** (leaving Summary before the preview answers). Tests: `JobNamingEditor.test.ts` (an
   unmounted editor's edit lands with its path in one undo step; the job changed meanwhile is
   named as it is; a failure is a toast and drops the edit). Chromium: `naming-tab-switch-add`
   and `-human` queue `{main_title} TABSWITCH` with the path the naming gives;
   `naming-tab-switch` (click and `Ctrl+2`) leaves the job with the template and its path.
6. **R1-5** (removing the editor's source while another drafts). `removeMany` closes the editor
   with `close({ keepLoading: true })` when its source goes while another, still active, source
   is drafting: that draft still comes in. Tests: `sources.test.ts`, `editor.test.ts`; R1's
   `sources-race.test.ts` passes.
7. **R1 suspected 5** (*Add* after a failed validation). The add asks again and adds nothing when
   that fails too. Tests: `useQueueActions.test.ts`, `useValidation.test.ts` (`flush` after a
   failure). Chromium (`jobs/validate` answered 503 by the page's route): two requests refused, 0
   added, the toast; after the route is gone, *Add* queues the job with 24.
8. **L2** (the Output card shows the name twice; given to FB by the lead): the card's Folder, File
   name and Name source rows are gone. The naming editor shows the name
   (`[data-testid="naming-result"]`), folder (`job-folder`), path (`job-path`), the job's name
   source setting (the Select, `[data-option="name_source"]`) and, in the parsed-name panel, the
   chosen source with its reason (`.parsed-name__source`, `[data-testid="name-reason"]`). Tests:
   `OutputCard.test.ts`, `JobNamingEditor.test.ts`. `SummaryTab.test.ts` (FD's) still reads
   `[data-field="file-name"]` and `[data-field="name-source"]`: left to the lead.
9. **L13** (*Browse…* icon a square): the fluid path field squeezed the button and the button its
   icon to 5 × 16 px; neither shrinks now (16 × 16, light and dark). No unit test: jsdom lays
   nothing out.
10. **R2-8**, the naming Selects (name source, word separator) take `aria-labelledby` from `Field`.
    Tests: `JobNamingEditor.test.ts`, `NamingOptionsEditor.test.ts`.
11. **R2-20**: a probe failure's detail follows a message that ends a sentence with a space:
    "bad.mkv: ffprobe could not read the file (exit code 1). /tmp/…/bad.mkv: Invalid data found
    when processing input" (real server); a title without a full stop keeps ": ". Test:
    `sources.test.ts`.

### Fix round — FC (shell, focus, queue and presets screens)

2026-10-30. Checked against `scripts/dev-server.py` (web mode, token; the pinned FFmpeg n9.0.2;
`multitrack` and `hdr10-4k`; for the first-run screen `--tools-dir /nonexistent` and a Settings
path to a missing file) in headless Chromium and Firefox, light and dark, with the keyboard
only, after merging FA and FB. Each fix has a unit test that fails without it. 56 mutations of
the fixes were run: 54 failed a test (four of them only after a test was made stricter), two are
equivalent (see the end).

1. **R2-3 (major): the focus fell to the page after an action.** Three causes, three fixes.
   - *A button that its own action disables* (*Add to queue*, *Add all*, *Start* in the status
     bar and the Queue view, *Pause all*, *Make default*, *Export*, *Check again*, *Use bundled
     FFmpeg*, the countdown's *Cancel*; the queue's *Edit* while it loads). A browser moves the
     focus of a button that turns `disabled` to the page. `components/shell/FocusSafeButton.ts`
     wraps PrimeVue's Button: while the button has the focus, "disabled" is `aria-disabled` and
     PrimeVue's `p-disabled` class (it looks disabled, a click or Enter does nothing); once the
     focus leaves, it is disabled for real and leaves the tab order. PrimeVue's `loading` also
     disables, so a busy button shows a spinning icon instead. The status bar's state stays
     `canAdd` / `canAddAll` / `canStart`; FB's `busy` puts the spinner and `aria-busy` on the
     button that started the add (*Add all* for its own, *Add to queue* for the button and
     `Ctrl+Enter`).
   - *A queue row whose buttons change with the job's state.* Before the jobs change, the table
     notes the focused row button (job, action, place); after the change, when the focus has
     gone to the page, it goes to the same action in that row, else to the row's new state
     action (Pause → Resume, Resume → Pause, Cancel → Retry, Retry → Cancel), else to the
     button in the same place. A removed row's place goes to the next job's same button (else
     the new last row's); an empty queue gives the focus to *Go to the workspace*.
   - *A control that a navigation or a new element replaces.* Opening the first source (from
     *Open files…* or `Ctrl+O`) replaces the empty state's button with the tabs: the focus goes
     to the selected editor tab, and removing the last source gives it to *Open files…*. *Edit*
     in the queue and *Use for the open job* in the Presets view focus the workspace's selected
     tab after the navigation. *Duplicate* focuses the copy in the preset tree; a deletion (the
     confirmation gives the focus back to the deleted preset's button) focuses the preset now
     shown, once both the answer and the dialog's close have come (`@after-hide`).

   Where the focus lands now (Chromium and Firefox, the same): *Open files…* → the Summary tab;
   *Add to queue*, *Add all*, *Start*, *Stop*, *Pause all* → themselves; a row's *Pause*
   (Space) → its *Resume*, Enter → *Pause*; *Cancel* of a running job → *Retry*; *Retry* →
   *Cancel*; *Duplicate* → itself; *Remove* → the same place of the next row; *Cancel all* →
   the dialog's *Keep them*, Escape → *Cancel all*; *Edit* → the Summary tab; Presets
   *Duplicate* → the copy in the tree; *Make default* → itself; *Delete* → the dialog's
   *Cancel*, then after the deletion → the preset shown in the tree; *Use for the open job* →
   the Summary tab. Tests: `StatusBar.test.ts` (each of the three buttons keeps the focus while
   its action makes it unavailable, ignores a second press, is disabled once the focus leaves;
   the add's wait on the right button), `QueueControls.test.ts` (*Start*, *Pause all*),
   `QueueTable.test.ts` (Pause, Resume, Retry, Cancel of a waiting and of a running job; a
   removal, the next and the last row, the empty queue; a progress update leaves the focus
   alone; *Edit* keeps the focus while it loads and then focuses the workspace's tab),
   `WorkspaceView.test.ts` (the opened source, the last one removed, a control that stays, the
   tab as other screens' target), `PresetsView.test.ts` (Duplicate, Delete, Make default, Use
   for the open job), `FirstRunScreen.test.ts` (*Check again* while it checks).
2. **R2-4 (major): popovers did not take the focus.** PrimeVue's Popover is appended to the end of
   the page with a focus trap and `aria-modal`, but it focuses only an `[autofocus]` inside.
   `focusFirstIn` (`components/shell/focus.ts`) focuses the first control of the panel on the
   popover's `show`, or the panel itself (`tabindex="-1"`) when it has none: the Appearance
   popover (its theme choice), the issue list (its first fix or *Show*; the list itself when it
   is empty) and the *Modified* changes (*Save as new preset…*). Tab then stays inside (PrimeVue's
   trap) and Escape closes and gives the focus back to the trigger. In Chromium and Firefox: 6 Tab
   presses in Appearance, 4 in the issue list and 5 in the changes all stayed inside. After
   *Update preset* in the changes the focus goes to the preset button (the marker goes once the
   job matches); after *Save as new* to the preset button, or to the marker when the dialog was
   cancelled (`PresetNameDialog` emits `closed` after its leave). Tests: `ThemeSwitch.test.ts`,
   `StatusBar.test.ts`, `PresetPicker.test.ts`.
3. **R2-7 (major): the countdown showed only on the Queue view.** `PowerBanner` moves from
   `QueueView.vue` into `App.vue`, above the router view, as a strip across the main column:
   announced by its `role="alert"` text, with *Cancel* in the tab order before the view. The
   views no longer take `100vh` each; the shell's main column is the window's height and each
   view (Settings too, by the shell's rule) fills what the banner leaves, so the page is exactly
   the window's height with and without the banner on every view (720 px window, Chromium and
   Firefox). When the banner goes with the focus on *Cancel*, the focus goes to the rail's link of
   the current view. Checked with `REFRAME_POWER_DRY_RUN=1` confirmed in `/proc/<pid>/environ` of
   the `reframe_server` process before the first countdown; only *Sleep*, chosen by its label in
   the selector and read back from `GET /api/settings` before a job was started; on the
   Workspace view the banner showed "The queue is finished. When done: Sleep. in 59 s" with
   *Cancel* (reached with Shift+Tab from the tab list), and Enter cancelled it after about 1.6 s
   (`GET /api/power` `pending: null`); when-done was set back to *Do nothing* at once. Twice,
   Chromium light and Firefox dark. Test: `App.test.ts` (one banner with *Cancel* on the
   workspace, presets, settings and queue views; Cancel cancels; the focus goes to the rail; a
   countdown that ends elsewhere does not move a focus that was not on it).
4. **R2-11: toasts covered the header and were see-through.** The shell's toasts sit at the bottom
   right, above the status bar: the status bar publishes its height as
   `--shell-status-bar-height` while it is shown, and the toast host's `bottom` adds it. The
   theme's toast tint is laid over the surface colour without the blur (FA's tokens are opaque
   now; the layer keeps a see-through token opaque too). Tests: `ShellToasts.test.ts`,
   `StatusBar.test.ts` (the height published and withdrawn).
5. **R2-12: the placeholder preview narrowed the tabs.** The preview column starts collapsed and
   keeps the user's choice: a new storage key, `reframe.workspace.previewHidden`, written only by
   the toggle (the old key had `false` written by default). The tab column is 856 px at 1280 ×
   720 and 1,016 px at 1440 × 900 (520 and 680 px with the preview open); an opened preview stays
   open after a reload. Test: `WorkspaceView.test.ts`.
6. **R2-10: raw JSON in the Modified popover.** `presets/diff` gives a whole object when a union
   member changes its kind. The rate control now reads "Constant quality CQ 27 → Average bitrate
   6,000 kb/s" (each side on its own encoder's scale: the encoder change's preset value for the
   preset side), the size as the presets view says it, a preset's inherited naming as "The naming
   of Settings → Output" and an own naming by its movie template; any other object lists its
   members in words ("Preset: light"). Checked on the NVENC preset with x264 and 6,000 kb/s.
   Tests: `PresetPicker.test.ts`, `format.test.ts`.
7. **R2-13 / L17: raw task kinds in Activity.** Each kind the server starts (`probe_sources`,
   `probe_folder`, `encoders_rescan`, `tools_fetch`, `bitrate_scan`, `subtitle_scan`, `loudness`,
   `frames`, `cropdetect`, `preview_clip`) has a name: "Reading sources: done". Another kind is
   shown with spaces and a capital. Test: `activityLines.test.ts`.
8. **R2-14: a failed copy repeated its reason.** The row lists the job's issues without those whose
   message the error already quotes ("The job has errors: X" once, then only the other issues).
   An automatic free name for a copy stays out of M4 (a queue change). Test:
   `QueueTable.test.ts`.
9. **R2-20 (queue wording).** "Stopped: 1 job waits for Start" / "Stopped: 2 jobs wait for
   Start"; while the runner takes every job, "Running: 2 waiting jobs start in turn", and with
   none left "Running: jobs added now start in turn". Test: `QueueControls.test.ts`.
10. **R2-23: the Preset column of a changed job.** The column ("Preset and encoder") shows the
    job's own video encoder under the preset's name, or "Video copied". Test:
    `QueueTable.test.ts`.
11. **L3 / L10 / R2-22: the first-run screen's actions.** *Use bundled FFmpeg* is offered only when
    no failing tool is set by the environment (`REFRAME_FFMPEG` outranks Settings and a bundled
    build), and *Choose path* only in the desktop app without such an override (the server
    refuses tool paths from a browser, `403 settings.tools_forbidden`). A note says what to do
    instead and names the variables. *Use bundled FFmpeg* also removes the Settings paths of
    ffmpeg and ffprobe after a download that ended `done` (as Settings → Tools does), else the
    Settings path would still win. *Check again* says "Checked again at 12:42:46 AM: nothing has
    changed." when the tools are as they were (a status region; the time makes a second press
    heard). Checked: with the environment override only *Check again* and the note; with a
    Settings path in web mode *Use bundled FFmpeg* and *Check again* and the browser note. Not
    clicked for real: *Use bundled FFmpeg* (it downloads FFmpeg). Tests:
    `FirstRunScreen.test.ts`.
12. **R1 suspected 4: *Save as new preset* read the job after the await.** It now notes the
    editor's session and preset before `POST /api/presets` and makes the job follow the new
    preset only when both are unchanged (another source, or another preset applied, while the
    request was out is left alone); the "Saved as" toast shows either way. Test:
    `PresetPicker.test.ts` (both cases).
13. **R2-8 (queue part): the when-done select was named by its value.** It takes
    `aria-labelledby` from its `Field`. Test: `QueueControls.test.ts`.

Equivalent mutations (not defects): `t(key, { n })` instead of `t(key, n)` for a plural (vue-i18n
picks the plural form from `n` either way); `loading` instead of `disabled` on a
`FocusSafeButton` (the wrapper's explicit `disabled: false` overrides PrimeVue's loading-disable,
so the button stays focusable; the code does not rely on it).

For other tasks: FA's grey disabled look (`main.css`, `.p-button:disabled:not(…)`) does not reach
a `FocusSafeButton` that keeps the focus while unavailable: it has the class `p-disabled` and
`aria-disabled="true"`, not `:disabled`, and shows PrimeVue's 60 % fade of its colour. The rule's
selector can take `.p-button:is(:disabled, .p-disabled)`.

### Fix round — FD (the tabs, sources and settings screens)

2026-10-30. Each fix with the test that fails without it (checked by breaking the fix); the
browser checks in headless Chromium against `scripts/dev-server.py` (pinned FFmpeg n9.0.2,
`multitrack` and `pgs`), at 1440 and 1280 px, light and dark.

1. **R2-8, comboboxes named by their value.** PrimeVue's `Select` puts `role="combobox"` on a
   span, which `<label for>` cannot name, and fills its `aria-label` with the chosen value.
   Every `Select` of the audio row (source, encoder, mixdown, sample rate, bitrate, loudness),
   the subtitle row (source, format) and Settings (default container, VAAPI device, when done,
   language) takes `aria-labelledby` from its `Field`. The Video tab's lists and the encoder
   picker already did ("Video encoder"). Tests: `TracksTab.test.ts` (each list of an audio and
   a subtitle row named by its label), one per Settings section (`comboboxName` in
   `settings/testing.ts`). In Chromium: `combobox "Sample rate": As source`, `combobox "When
   done": Do nothing`. The naming editors' lists are FB's ("Keep the source's" in Settings →
   Output is still named by its value).
2. **R2-18, the quality slider.** It catches the handle's keys before PrimeVue's `Slider`, which
   moves one `step` for every key: an arrow moves 0.5 on a scale finer than whole numbers
   (x264, x265, NVENC: step 0.1), else the scale's step (1); PageUp / PageDown 5 on the 0–51 and
   0–63 scales and 25 on the 0–255 AV1 scales (AMF, VAAPI: their tables map 120 to x264's 24, so
   25 is about 5 RF there); Home / End the ends. A typed value keeps any value of the scale
   (19.3). Each key press is still one undo step. Tests: `QualitySlider.test.ts` (each key on
   the RF scale, a whole-number and a 0–255 scale, a typed 19.3). In Chromium: 22 → 22.5 →
   27.5 → 51 → 0, four `Ctrl+Z` back to 22.
3. **R2-19, Summary chips.** An output flag is left out when a role badge set by the source's
   disposition names it (commentary → Commentary, hearing impaired → SDH, forced → Forced,
   visual impaired → Description), as `TrackTable` does; beside a role guessed from the title
   or the layout the flag stays. Tests: `tracks.test.ts`. In Chromium: "Director's Commentary
   Commentary (Set by a disposition flag in the file)", one Commentary.
4. **R2-21, sizes.** The file browser uses the Summary's `formatBytes` (B, KiB, MiB, GiB):
   `multitrack.mkv` is 370 KiB in both. Bitrates stay decimal (kb/s). Test:
   `FileBrowserDialog.test.ts` (1.4 MiB for 1,500,000 bytes).
5. **R2-24.** (a) The Summary tab has a visually hidden h2 "Summary": the outline is h1 (the
   source), h2, the cards' h3, their h4. Test: `SummaryTab.test.ts` (the first heading is h2, no
   level skipped). (b) A source tree item is named by `aria-labelledby` (its file name; for a
   member the match, the episode and the file) and described by `aria-describedby` (its line,
   differences, staleness, warnings), so "Remove …" is no longer part of its name; the warnings
   list loses its `aria-label` ("Probe warnings"), which would replace the warnings in that
   description, and each warning starts with a hidden "Probe warning:". Test:
   `SourcesPanel.test.ts`. In Chromium: `treeitem "multitrack.mkv"`. (c) The file list's empty
   note is a sibling of `role="listbox"`, laid over the empty list, and describes it. Test:
   `FileBrowserDialog.test.ts`.
6. **L2, the Output card's name shown twice**: the duplication is in `OutputCard.vue` (FB's);
   `SummaryTab.vue` only places the card. Left to FB through the lead (see the report).
7. **L8 / L16, cut values.** The audio row's fields can be 11rem wide: the keep values of the
   sample rate and the mixdown are "As source" (were "Same as source", "Keep the source layout"),
   a longer value of a row's list wraps instead of being cut ("Default (160 kb/s)", "Streaming
   (−16 LUFS)"), and a number keeps its unit on its line (no-break spaces in `tracks.json`). The
   encoder picker's value wraps, so the id goes to a second line at 1280 px. No unit test: jsdom
   lays nothing out; checked in Chromium (no `.p-select-label` with `scrollWidth >
   clientWidth`).

### Fix round — FE (server texts)

2026-10-30. Three texts that the screens show as they come from the server. No status, problem
code, title or response model changed; no OpenAPI text changed. Each test fails with the old
text (checked by putting it back). Before and after: `curl` against `scripts/dev-server.py`
(web mode, pinned FFmpeg n9.0.2, MediaInfo not installed).

1. **L6 / R2-20, a refused folder listing.** `GET /api/fs/list` tries the read check, then the
   write check, and answered with the second refusal: "/etc is not inside a folder that this
   server may write to." also when the user browses to open a file. The route now replaces
   the detail of a `path.outside_roots` refusal (same 403, code and title): "/etc is outside
   the server's media and output folders. Browse from one of them." Both kinds are named
   because the listing accepts both (the output folder picker browses below an output root).
   A `path.invalid` (400) passes unchanged. The text is made in `routers/fs.py`;
   `security.py` is unchanged, so every other refusal keeps "may read from" / "may write to".
   Test: `test_fs.py::test_a_folder_outside_the_roots_is_refused_as_outside_media_and_output`.
2. **L12, `settings.tools_forbidden`.** The detail said "Set REFRAME_FFMPEG / REFRAME_FFPROBE
   on the server instead." for every tool. It now names the variable of each tool the refused
   patch sets, in discovery's order, from `reframe.tools.ENV_VARS` (no second list): "Set
   REFRAME_MEDIAINFO on the server instead.", "Set REFRAME_FFMPEG / REFRAME_MKVPROPEDIT on the
   server instead.". A key under `tools` that is no tool (the model keeps unknown fields) has no
   variable: "Tool paths are set on the server." Test:
   `test_settings.py::test_a_refused_program_names_the_variables_of_the_tools_it_sets`.
3. **R2-20, the reason of a missing optional tool.** Decision: one text for both modes, made in
   the core. The core does not know the mode, and a web-mode text from the server would mean
   rewriting the core's reasons; both modes honour the variable. Before: "mediainfo was not
   found (optional: install it, or set its path in Settings)." After: "mediainfo was not found
   (optional: install it, or set REFRAME_MEDIAINFO to its path)." The same line serves
   mkvpropedit (REFRAME_MKVPROPEDIT). Desktop mode loses the hint to Settings, where the reason
   is shown next to the tool's path field anyway. Not changed: the reason of a missing FFmpeg
   ("Set its path in Settings or REFRAME_FFMPEG, or run `reframe tools fetch`.") already names
   a way that works in web mode. Tests: `test_system.py::test_a_missing_optional_tool_tells_a_web_client_what_it_can_do`
   (web mode, an empty `PATH`: both optional tools missing, the variable named, no
   "Settings"), and `test_discovery.py::test_nothing_found` names the variable.


## M4 demo, 2026-11-01 (headless)

The roadmap's M4 flow, run against the real server and the real pinned FFmpeg (n9.0.2): a
throwaway Playwright script (not committed), headless Chromium at 1440×900, `scripts/dev-server.py`
with `--tools-dir` (no fake FFmpeg) and the `multitrack` and `hdr10-4k` fixtures. 28 screenshots,
17 of them read. No console error or warning in any run. The headed demo on `HDMI-A-1` is **not**
run.

**The flow, as it ran**

1. `Ctrl+O`, the server's file browser, `multitrack.mkv`: the Summary shows the source (320×180,
   25 fps, 3 audio and 3 subtitle tracks), the picture pipeline and the output; the status bar
   shows the output path and "1 note" (crop detection did not run).
2. The preset list, then *Fast 1080p30*. Video tab: encoder list with each encoder's state,
   *x265* chosen, quality typed as RF 24. The command drawer shows the real command
   (`-c:v:0 libx265 -crf:v:0 24 -preset:v:0 fast …`).
3. Audio tab: *Remove track 3*, *Add track* (a menu of the three source streams), *Remove track 3*
   again: two output tracks.
4. *Add to queue*, Queue view, *Start*: Waiting, Running, Done (100 %) in 0.5 s. *Show the log*:
   125 lines of the real FFmpeg output, ending "Job done after 0.5 s".
5. The finished file read with the pinned `ffprobe`: MP4; HEVC (`hvc1`) 320×180; two AAC tracks
   (`jpn`, `eng`; the removed commentary track is not there); three `mov_text` subtitles with
   their dispositions; no `.part` file left.
6. A job that takes time, so that progress can be watched: `hdr10-4k.mkv`, *Fast 2160p60 4K HEVC*
   (10-bit, HDR10). The row went from 3.3 % (0.7 fps, 0.11×, 3:59 left, 256 KiB) through 62.5 %
   (7.0 fps, 0.54×, 0:07, 4.8 MiB) to Done, and its log was open and growing (50 lines) while it
   ran.
7. Validation inline and on Summary, with `{"encoders": {"hardware_tests": true}}` (flow 3 on real
   hardware; this machine has an AMD GPU): the preset *H.265 NVENC 1080p* gives the banner "The
   video encoder is not available … NVIDIA driver not found", an error under the encoder field
   with its bar, "1 error" in the status bar, a disabled *Add to queue*, and "Error (1)" with
   *Show* and the fix on Summary. *Use hevc_amf (closest match; quality CQ 27 → CQ 25,
   approximate)* clears the banner, enables *Add to queue*, and the job runs to Done with a real
   `hevc_amf` encode. *Show* on the Summary error switches to the Video tab and the encoder field
   is in view and marked.

**Defect found and fixed**

- **The tabs shared one scroll offset.** After *Remove track 3* on the Audio tab, *Summary*
  opened scrolled down (155 px in that run, 300 px when measured), with the top of the Source card
  cut off (the panel is the one scroller of every tab). `EditorTabs.vue` now resets it when the tab changes. Failing first:
  `components/shell/EditorTabs.test.ts` got 300 instead of 0. Checked in the browser as above,
  and *Show* still lands on its field.

**Looked at, not changed**

- The queue table at 1440 px: the Source and Output cells are exactly as wide as a 14-character
  name (`multitrack.mkv` fits, one character more breaks it, and in one run `multitrack.mk` / `v`
  did), because FPS, Speed, Time left, Size and the progress bar keep 60–144 px each while they
  are empty. No failing check could be written (the e2e run at 1440 px keeps the name on one
  line), so it stays a layout question for the queue table, not a defect with a test.
- Summary lists the issues in its last card, below Output; an error shows at once in the status
  bar and inline on its field, so only the list is out of sight until the tab is scrolled.
- Opening a second file does not select it while another file is open (the store selects the
  first one only: `activeId === null`); the new file is listed in the sources panel.

Checks after the fix: frontend lint, format, typecheck, 1008 unit tests, `build:web`,
`npm run e2e` (14 passed).
