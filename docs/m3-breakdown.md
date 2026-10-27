# M3 server task breakdown

Working notes of the lead for milestone M3: the server part (S-0, S-1, S-2, S-3, S-5 and
Q-2.3, waves 0 to 3) and the desktop spike D-0 on Linux (waves 4 to 6). The plan ([plan/06-web-app.md](plan/06-web-app.md) Part A, [plan/08-roadmap.md](plan/08-roadmap.md)
M3, [plan/09-quality-and-release.md](plan/09-quality-and-release.md) Q-2.3) is the spec; this
file says who builds which part, in which order, and what each part must offer to the
others. Status: [status.md](status.md). Decisions: [0042](decisions/0042-one-scheduler-process-and-cli-clients.md),
[0043](decisions/0043-plan-review-before-m3.md), [0044](decisions/0044-code-review-follow-ups.md),
[0045](decisions/0045-m3-server-order-and-contract.md). If the lead's context is summarised,
this file and `status.md` are the source of truth.

## Scope and order

| Step | What is built here | Plan |
|------|--------------------|------|
| S-0 | package skeleton, `ServerConfig`, `create_app`, entry point, health (lead, wave 0) | 06 §S-0 |
| S-1 | auth modes, local token, path jail, Host / Origin check, CORS, security headers, `auth.json`, `PUT /api/auth/password`, `--set-password` | 06 §S-1 |
| S-2 | every REST route of the 06 table, `operationId`s, problem+json; the facade coverage test | 06 §S-2 |
| S-3 | `WS /api/events`: first-message auth, coalescing, log batching, ping, sequence numbers | 06 §S-3 |
| S-5 | `scripts/gen-api.sh` → `frontend/src/api/schema.d.ts` (committed) | 06 §S-5 |
| Q-2.3 | CI regenerates the types and fails on a diff | 09 §Q-2.3 |
| D-0 | the desktop spike on Linux (Tauri 2 shell, onedir sidecar, cold start, cleanup, WebKitGTK checks) and `--parent-pid` (S-0); waves 4 to 6 | 07 §D-0, 06 §S-0, [0054](decisions/0054-d0-spike-layout-and-parent-watch.md) |

**Out of scope** (write down what a scope step needs from them; do not build it): S-4 (M4), S-6
(M10), S-7 + C-17 (M3b), D-1 to D-9, Q-1.4 (a Windows run; M10 since
[0053](decisions/0053-linux-first-windows-testing-phase.md)), every F-x.

**Branch**: `m3-api-spike`, made from `main` (origin's branch of that name is already in
`main`). Each task works in its own worktree branch made from `m3-api-spike`; the lead merges
it with `--no-ff` after every check passes, including the test rules. `m3-api-spike` is not
merged into `main` in this work: M3 also needs D-0 (on Linux,
[0053](decisions/0053-linux-first-windows-testing-phase.md)). Never push.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: decision 0045, this breakdown, the contract commit (S-0 done) | `main` |
| 1 | 1a S-1 security · 1b S-3 events · 1c S-2 queue, power, tasks · 1d S-2 system, fs, settings, sources, preview · 1e S-2 definitions, languages, jobs, naming, batch, presets | the contract |
| 2 | 2a S-5, Q-2.3, the S-2 facade coverage test, the jail sweep over every path route | wave 1 merged |
| 3 | review (a fresh agent, given the code, not the lead's conclusions) of `git diff main...m3-api-spike`: correctness, security and test quality. Fixes go to the task that wrote the step (effort `high`) | wave 2 |
| 4–6 | D-0 on Linux: 4a the shell and the sidecar, 4b the WebKitGTK checks, then a review ([D-0: waves 4 to 6](#d-0-waves-4-to-6)) | wave 3 fixes merged |

### Effort and model

Every agent: `model: "opus"`, `isolation: "worktree"`. `effort: "xhigh"`: 1a, 1b, 1c and the
review (3). `effort: "high"`: 1d, 1e, 2a and the review fixes.

## Who owns which files

An agent edits only the files it owns. Two agents never own the same file. A change anywhere
else goes back to the lead (say so in the report; do not make it). Paths are relative to
`packages/reframe-server/src/reframe_server/` (code) and `packages/reframe-server/tests/`
(tests) unless they start with `docs/`, `scripts/`, `frontend/`, `testing/` or `.github/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **1a** S-1 | `security.py` (fill in the stubs; new helpers welcome), new `auth.py` / `session.py` modules if useful, `routers/auth.py`, `tests/test_security*.py`, `tests/test_auth*.py` | `app.py` (`create_app` already calls `security.install` and adds `require_auth`), `__main__.py` (`--set-password` already calls `security.set_password_interactive`), `config.py`, other routers |
| **1b** S-3 | `events.py`, `routers/events.py`, `tests/test_events*.py` | `security.py` (call `security.ws_authenticated`), `app.py` (the lifespan already makes and closes the hub), other routers |
| **1c** S-2 queue | `routers/queue.py`, `routers/power.py`, `routers/tasks.py`, `tests/test_queue*.py`, `tests/test_power*.py`, `tests/test_tasks*.py` | `events.py` (call `hub.client_open`), `security.py`, other routers |
| **1d** S-2 system | `routers/system.py`, `routers/fs.py`, `routers/settings.py`, `routers/sources.py`, `routers/preview.py`, `routers/media.py`, `tests/test_system*.py`, `tests/test_fs*.py`, `tests/test_settings*.py`, `tests/test_sources*.py`, `tests/test_preview*.py`, `tests/test_media*.py` | `sources.py` (the registry: use it), `security.py` (call `sign_media_url`, the jail), other routers |
| **1e** S-2 jobs | `routers/definitions.py`, `routers/languages.py`, `routers/jobs.py`, `routers/naming.py`, `routers/batch.py`, `routers/presets.py`, `tests/test_definitions*.py`, `tests/test_languages*.py`, `tests/test_jobs*.py`, `tests/test_naming*.py`, `tests/test_batch*.py`, `tests/test_presets*.py` | `sources.py`, `security.py`, other routers |
| **2a** S-5, Q-2.3 | `scripts/gen-api.sh` (and a small Python helper next to it if useful), `frontend/src/api/schema.d.ts`, `frontend/package.json` + `package-lock.json` (only the `openapi-typescript` dev dependency and a script), `.github/workflows/ci.yml` (the Q-2.3 step), `tests/test_openapi*.py`, `tests/test_facade_coverage.py`, `tests/test_jail_sweep.py` | every router (a missing route or a route bug goes back to the lead, who gives it to the task that wrote it) |

**Lead-owned** (nobody else edits them; a needed change goes to the lead): `api.py`, `app.py`,
`config.py`, `deps.py`, `errors.py`, `sources.py`, `__main__.py`, `routers/__init__.py`,
`routers/health.py`, `tests/conftest.py`, `tests/test_app.py`,
`testing/reframe_testing/server.py`, every file of the core package `packages/reframe/`.

**Existing test files**: none besides the lead's. New test files carry the task's area in their
name (as above).

**Shared files** (more than one task writes them; the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own row (the server table has one S-2 row per
  task) and the feature rows its routes change, in the same commit as the step.
- `docs/plan/06-web-app.md`: a task edits only the S-2 table rows of its own routes (or its
  own step section) and only together with its decision record.
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.
- `uv.lock`, `packages/reframe-server/pyproject.toml`: a new dependency is a decision record
  item; ask the lead first (1a: `argon2-cffi` only if it chooses argon2 over stdlib scrypt).

## Decision record numbers

One record per task; a task with several topics uses sections in its one record. A review fix
adds a dated section to the record of the task that wrote the step.

| 0045 | 0046 | 0047 | 0048 | 0049 | 0050 | 0051 | 0052 |
|------|------|------|------|------|------|------|------|
| lead (contract, used) | 1a | 1b | 1c | 1d | 1e | 2a | lead (review) |

## Contracts

Signatures are binding. A task may add keyword-only parameters with defaults, extra functions
and new response models in its own files, but not change these. Read the code of the contract
commit; this is its summary.

### Built by the lead (contract commit)

- `config.ServerConfig` (pydantic-settings, prefix `REFRAME_`, then the command line): `host`,
  `port` (0: free), `mode` (`web` | `desktop`), `auth` (`none` | `token` | `password`;
  resolved: desktop is always `token`, unset is `none` on loopback and an error elsewhere,
  `none` off loopback is refused), `token` (`SecretStr`; `REFRAME_TOKEN`, else random per
  process; read it with `config.secret_token`), `media_roots`, `output_roots`, `static_dir`,
  `cors_origins`, `config_dir`, `data_dir`, `endpoint_file`, `idle_exit`, `owner_only` (the
  last three: S-7), `allowed_hosts` (`None`: the defaults of S-1). `config.auth_mode`,
  `is_loopback(host)`.
- `app.create_app(config) -> FastAPI`. The lifespan runs `Reframe.create(config_dir, data_dir)`
  and `EventHub(reframe.events, config)`, and closes the hub, then the facade. `app.state`:
  `config`, `instance` (random hex per app), `started` (monotonic), `sources`
  (`SourceRegistry`), `request_shutdown()` (the entry point makes it stop uvicorn), and while
  the lifespan runs `reframe`, `hub`. Routers are mounted under `/api`: `health`, `auth`,
  `events` and `media` without `require_auth` (they check access themselves); every other
  router with `Depends(security.require_auth)`. Docs: `/api/docs`, `/api/openapi.json`.
- `api`: `api_router(tag) -> APIRouter` (use it for every router: it sets the response class,
  the `operationId` rule `<tag>_<handler name>` and the 4XX problem responses in OpenAPI),
  `JsonTextResponse` (writes with `json_text`), `accepted(task: TaskInfo)` (the `202
  {task_id}` answer with `Location: /api/tasks/{id}`), `TaskAccepted`, `Problem`,
  `RequestError`, `API_VERSION = 1`.
- `errors`: `ProblemError(status, code, title, detail=None, *, issues=(), headers=None)`
  (raise it), `issue_problem(issue, status=422)`, `probe_problem(error)` (`ProbeError` → 404
  not found / not a file, 403 unreadable, 503 tool failed or cancelled, 504 timeout, 422
  failed / invalid output; code `probe.<kind>`), `problem_response(problem)`. Handlers map
  `UnknownJobError` → 404 `queue.unknown_job`, `JobStateError` → 409 `queue.job_state`,
  `ReframeClosedError` → 503 `server.closing`, `HTTPException` → `http.<status>`,
  `RequestValidationError` → 422 `request.invalid` (fields and messages, never values), any
  other exception → 500 `server.unexpected` (no detail).
- `deps`: `ReframeDep`, `ConfigDep`, `HubDep`, `SourcesDep` (they take an `HTTPConnection`, so
  WebSocket routes can use them).
- `sources`: `source_id(path)`, `SourceRegistry`: `add(path) -> id`, `path(id)`, `remove(id)`,
  `items()`, `async get(reframe, id) -> MediaSource` (404 `source.unknown`, 409
  `source.stale`; never runs ffprobe).
- `routers/health.py`: `GET /api/health` (`system_health`): `version`, `api_version`,
  `instance`, `uptime`; no credentials needed.
- `__main__.py`: `reframe-server` (`main(argv) -> int`): `--host --port --mode --auth
  --media-root --output-root --owner-only --idle-exit --set-password`; uvicorn, one worker,
  logs on stderr; desktop mode prints `{"event":"ready","port":N}`; SIGINT → 130; a bad
  option or config → 2.
- Tests: `tests/conftest.py` (fixtures) and `testing/reframe_testing/server.py` (the harness).
  `api` is a web-mode, token-auth server with a media root, an output root and a folder
  outside both; `make_api(mode=…, auth=…, **config)` makes any other one; `api_each_auth`
  runs a test once per auth mode; `api_client` is `api.client`. `Api`: `client` (sends the
  run's token as Bearer: accepted in every mode), `anonymous`, `app`, `reframe`, `config`,
  `token`, `fake` (the fake tools; every probe answers with the recorded `multitrack` probe),
  `media`, `output`, `outside`, `media_file(name)`, `add_fixture(name, fixture_media)` (a real
  fixture below the media root; then every call goes to the real tools), `use_real_tools()`,
  `live()` (serves the app with uvicorn on a free loopback port: `LiveServer.connect(path,
  origin=…)` is a `websockets` client). `receive_json(connection)`.

### Stubs the tasks fill in (signatures fixed)

`security.py` (1a). While they are stubs, every check lets the request in.

```python
def install(app: FastAPI, config: ServerConfig) -> None           # Host/Origin check, CORS, security headers
async def require_auth(request: Request) -> None                   # 401 ProblemError
async def require_media_access(request: Request) -> None           # what require_auth takes, or a valid ?sig
def ws_authenticated(config, websocket: WebSocket, token: str | None) -> bool
def check_host(config, host: str | None) -> bool
def jail_read(config, path: str | os.PathLike[str]) -> Path        # resolved; 403 path.outside_roots
def jail_write(config, path) -> Path
def jail_job(config, job: JobSettings) -> None                     # every path the job reads / writes
def sign_media_url(config, url_path: str, *, ttl: float = 300.0) -> str
def verify_media_sig(config, url_path: str, exp: str | None, sig: str | None) -> bool
def set_password_interactive(config) -> int                        # --set-password; exit code
```

`events.py` (1b): `EventHub(bus, config)`: `connections` (open, authenticated),
`client_open(client_id) -> bool` (S-7: `False` until then), `async serve(websocket)`,
`async close()`. `routers/events.py` already routes `WS /api/events` to `hub.serve`.

Every router module exists with `router = api_router("<tag>")`; tags: `auth`, `queue`,
`power`, `tasks`, `system` (also health; handler names must not repeat `health`), `fs`,
`settings`, `sources`, `preview` (`preview.py` and `media.py`: handler names must differ),
`definitions`, `languages`, `jobs`, `naming`, `batch`, `presets`, `events`.

### Rules for every route task

- Routers are thin: a handler calls one facade method and maps the result; a handler that
  needs two (`duplicate`: `get` + `add`) says why in its record. The core never imports
  FastAPI; nothing in `packages/reframe/` changes without the lead.
- Every path from a client goes through `security.jail_read` / `jail_write` / `jail_job`,
  called through the module (`from reframe_server import security`, then
  `security.jail_read(config, p)`), so a test can replace it. Each task proves for each of its
  routes that takes a path that the route passes it to the jail (replace the jail function
  with one that raises a 403 `ProblemError` and check the answer). Tests use paths below
  `api.media` / `api.output`, never elsewhere, so they stay green once S-1's jail is real.
- Expected failures are data: a facade result that is an issue or a `ProbeError` becomes a
  problem (`issue_problem`, `probe_problem`), never a 500. A `list[ValidationIssue]` result
  (validate, dry run) is a 200 answer.
- Long operations answer `accepted(task)`. Request bodies are normal FastAPI body parameters
  (0045 finding 3); responses are domain models of `reframe.models` or envelopes defined in the
  router module (0045 item 12).
- Name each handler for its action; the `operationId` is `<tag>_<name>`
  (`sources_probe`, `jobs_validate`, `queue_add`, …).
- A blocking file operation runs in a worker thread (`asyncio.to_thread`), never on the event
  loop.

### Wave-1 contracts per task

**1a S-1** (06 §S-1, 0043 item 3, 0042 item 2): the stubs above. `token` mode and the local
token: `Authorization: Bearer <config.secret_token>` in every mode, compared in constant time.
`password` mode: `POST /api/auth/login` `{password}` → HTTP-only, `SameSite=Strict` session
cookie (`Secure` when the request came over HTTPS), `POST /api/auth/logout`,
`PUT /api/auth/password` `{current, new}`; the hash (stdlib `hashlib.scrypt` or argon2: choose
and record) in `<config dir>/auth.json`, mode 0600, atomic write; `set_password_interactive`
(reads the password twice without echo; also from stdin when it is not a TTY). Login attempts
are rate limited. `none`: a start-up warning (in `install`). Path jail: `Path.resolve(strict=False)`,
inside a root after resolution (symlinks followed, `..` removed; a path with a NUL is refused,
never a 500); web mode only, desktop allows every path; `jail_job` checks every path in a
`JobSettings` (source, external subtitles, chapter files: read; output path, output folder:
write; walk the model so a new path field cannot be missed). Host check in every mode (HTTP
and WebSocket upgrade): loopback names (`127.0.0.1`, `localhost`, `[::1]`, any port) and
`allowed_hosts` (default: plus the bound address and the host name when the server binds
another address); WebSocket `Origin`: the server's own or a Tauri origin
(`tauri://localhost`, `http://tauri.localhost`). CORS: off in web mode, the Tauri origins in
desktop mode (`cors_origins` adds to them). Security headers on every response: CSP,
`X-Content-Type-Options: nosniff`, `frame-ancestors 'none'`; the docs page `/api/docs` must
keep working (or say what it needs). Signed media URLs: HMAC over the URL path and the expiry
with a key derived from the run's token. "Done when" (06 §S-1, word for word): *tests prove
that `../` traversal, symlink escape, absolute paths outside the roots, a missing or wrong
token and a foreign `Host` are all rejected, that `GET /api/settings` holds no secret, and
that a settings patch cannot change the password.* (The settings routes are 1d's: 1a's test
uses them through the app once 1d is merged, or checks that `auth.json` is a separate file
that the settings store never reads or writes; the lead runs the two settings checks after
both are merged.)

**1b S-3** (06 §S-3, 02 §Events): `EventHub` above. The client sends `{"type": "auth",
"token": "…"}` first (password mode: the token may be omitted; the upgrade's cookie counts);
`security.ws_authenticated` decides; a wrong or missing first message closes with code 4401
within a few seconds (a time limit for the first message). Then each event is sent as
`json_text` of `{"seq": n, "event": {…}}` (or the event with a `seq` field: choose and record)
with a sequence number per connection, starting at 1 and without gaps. `job.progress` and
`task.progress`: coalesced per id, the latest kept, at most 4 per second per id; `job.log`:
batched every 250 ms (one message with the lines of each job). A ping every 15 s (WebSocket
ping or an event: choose and record). A slow consumer: bounded memory, latest value delivered
(use the core's `EventBus.subscribe(max_queue=…)` and its `resync`, or a bounded queue of
your own); a `resync` event tells the client to call the `GET` snapshots. `close()` ends every
connection (code 1001) and returns promptly, also with a stuck client. `client_open` stays
`False` (S-7). "Done when": *a test with a slow consumer shows bounded memory and latest-value
delivery.* Also prove: reconnect gets a new sequence, cancel / disconnect of a client frees
its subscription, shutdown while events flow.

**1c S-2 queue, power, tasks**: `GET /api/queue` · `POST /api/queue` `{jobs, position?,
attach?}` (every job through `security.jail_job`; the server validates again in
`queue.add`; a job whose output path is not set yet is refused with a problem, since the
jail cannot check it) · `POST /api/queue/{id}/pause|resume|cancel|retry|duplicate` ·
`DELETE /api/queue/{id}` · `POST /api/queue/start|pause|stop` (`start` takes `{job_ids?}`) ·
`PUT /api/queue/order` · `GET /api/queue/{id}/log?from=` (incremental, by byte offset; read in
a worker thread; the answer carries the next offset) · `PUT /api/queue/when-done` (the
`queue.when_done` setting through `settings.update`) · `GET /api/power` ·
`POST /api/power/cancel` · `GET /api/tasks` · `GET /api/tasks/{id}` ·
`POST /api/tasks/{id}/cancel`. `attach`: accepted in the body; a non-null value is refused
with 409 `queue.attach_unknown_client` while `hub.client_open(attach)` is false (always,
until S-7). An unknown task id is 404 `tasks.unknown`.

**1d S-2 system, fs, settings, sources, preview**: `GET /api/system` (tool statuses,
versions, platform, mode, the settings and preset stores' start-up problems) ·
`GET /api/system/encoders` · `POST /api/system/encoders/rescan` · `POST /api/system/shutdown`
(desktop mode only, else 403; calls `app.state.request_shutdown`) ·
`POST /api/system/tools/rescan` · `POST /api/system/tools/fetch` `{build?}` → 202 ·
`GET /api/fs/roots` · `GET /api/fs/list?path=` (media files and folders only; web mode: below
the media roots; desktop: the user's whole file system) · `GET/PUT /api/settings` (PUT takes a
JSON patch; web mode: 0045 item 11) · `POST /api/sources` `{paths}` → 202 (a task of the
server's that probes files and folders and registers each source; its result names each
`source_id`) · `GET /api/sources` · `GET /api/sources/{id}` · `DELETE /api/sources/{id}` ·
the bitrate-scan, subtitle-scan and loudness routes → 202 · `POST /api/preview/frames`
`{source_id, count | timestamps}` and `POST /api/preview/render` `{job, timestamp}` (both wait
for the frames task and answer with each frame's signed URL; a client that goes away cancels
it) · `GET /api/preview/frames/{key}.png` (ETag, `require_media_access`) ·
`POST /api/preview/cropdetect` → 202 · `POST /api/preview/clip` → 202 ·
`GET /api/preview/clips/{id}` (HTTP Range, `require_media_access`; the client needs a signed
URL for `<video>`: say how it gets one) · `GET/DELETE /api/preview/cache`. No server file path
of the cache folder in an answer.

**1e S-2 definitions, languages, jobs, naming, batch, presets**: `GET /api/definitions`
(encoders, option schemas, filters, containers, the naming variables; ETag, 304 on a match) ·
`GET /api/languages` (cached) · `GET /api/definitions/encoders/{id}/options?q=` ·
`POST /api/jobs/draft|validate|plan|geometry|explain|draft-remux|dry-run|hdr-metadata`
(bodies of the 06 table; `source_id` through `SourceRegistry.get`; every job through
`security.jail_job`) · `POST /api/batch/group|derive|resolve|resolve-run|save-preset` ·
`GET/POST /api/presets` · `GET/PUT/DELETE /api/presets/{id}` · `POST /api/presets/{id}/default`
· `POST /api/presets/import` (a JSON body with a size limit) · `GET /api/presets/export` ·
`POST /api/presets/diff` · `POST /api/presets/defaults/preview` · `POST /api/naming/preview`.

### Wave-2 contract (2a)

- **S-5**: `scripts/gen-api.sh` exports `openapi.json` from `create_app(ServerConfig())`
  without a server and runs `openapi-typescript` (a pinned dev dependency of `frontend/`) →
  `frontend/src/api/schema.d.ts`, committed. Q-2.3: a CI step regenerates it and fails on a
  diff (on Ubuntu; the Windows runner only if the script runs there).
- **S-2 "Done when"**: *an httpx `AsyncClient` test suite covers every route against a facade
  that runs on fixture media and a fake FFmpeg, and every public method of the facade
  (decision 0030's list, `Reframe.batch`, `Reframe.power`, `Reframe.tasks`) is reached by a
  route or listed here as not exposed, with the reason.* 2a's test lists the public methods by
  introspection, maps each to the route(s) that reach it, and fails on a method with neither a
  route nor an entry of 06's "not exposed" list; 2a writes that list into 06. The test also
  fails on a route of the OpenAPI document that no test file calls (or 2a shows this another
  way), and on a duplicate `operationId`.
- **Jail sweep**: every route that takes a path (from the OpenAPI document and the request
  models) refuses `api.outside`, a `../` escape and a symbolic link out of a root, with the
  real S-1 jail.

## Test rules (put this section, word for word, in every agent's brief)

A test is meaningful only if it fails when the server has a real defect that a user or a
client would see. Before you write a test, name that defect in one sentence. If you cannot
name one, do not write the test.

Write tests that prove:
- What the "Done when" of your step requires.
- Each route's contract: status code, problem+json body, the response model, `operationId`,
  and the 202 + task flow.
- That each route reaches the facade with the right arguments and maps the result and every
  expected failure correctly.
- Security behaviour: traversal, symlink escape, a foreign Host or Origin, a missing or wrong
  token or signature, an expired signature, a secret leaking from a response.
- Concurrency and limits: slow consumers, coalescing, reconnect, cancel, shutdown while work
  runs.
- Every boundary and branch you wrote. Use one case per branch: a table row that follows the
  same code path as another row adds nothing.

Do not write:
- Tests of FastAPI, Starlette, Pydantic, httpx or Python behaviour. For example: "a missing
  required field gives 422", "the model serialises", "the router is a router".
- Tautologies: a test that checks a mock returned what the test told it to return, or
  repeats the code's own expression as the expected value.
- Tests of constants, defaults copied from the code, or private helpers, when a public route
  test already covers the same path.
- Cases with no new branch, Cartesian products whose extra factors do not change the code
  path, or a test that another test in the same area already covers.
- Tests of test doubles or fixtures (`fake_tools`, `api_client`) instead of server code.
- Snapshot tests of whole responses where a check of the few fields that matter would say
  why the test exists.
- A test that duplicates a core test: the core is already tested. Test the mapping, not the
  core logic again.

Checks before you report:
1. Mutation check. For each test file, break the code it tests on purpose, at least once per
   test function. Examples: remove the jail check, invert the auth result, drop the coalescing,
   return the wrong status. The test must fail, then pass again when you restore the code.
   A test that still passes is wrong: fix it or delete it.
2. Coverage. Run `uv run pytest packages/reframe-server --cov=reframe_server
   --cov-branch --cov-report=term-missing`. Every line you did not cover must be either
   unreachable or listed with a reason in your report. Do not add a test only to cover a
   line; it must also meet the rule above.
3. In the report, give: the number of tests per file, the mutations you tried and their
   result, and the uncovered lines with their reasons.

The test-trim reports in `docs/test-trim-reports/` (for example `B.md`, `R.md`) list the kinds
of tests this project already deleted as meaningless. Do not write them again.

## Every agent prompt includes

- The step, its 06 section, the owned and forbidden files, the contracts above, the "Done when"
  lines word for word, the decision number, and the test rules section word for word.
- Setup: the worktree starts at `main`; run `git merge --ff-only m3-api-spike` first, then
  `uv sync`. `.tools/` and `testdata/media/` are not in a worktree: the pinned FFmpeg is
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`;
  `/usr/bin/ffmpeg` is on `PATH`; real fixtures are generated on demand by `fixture_media`
  (or copy `/home/peti/Programming/reframe/testdata/media/.` into the worktree's
  `testdata/media/` when the lead has generated them).
- Rules: follow the `code-comments` skill; the core never imports FastAPI; routers are thin;
  expected failures are data; every `CLAUDE.md` command is green before the report
  (`uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run mypy --platform
  win32`, `uv run pytest -m "not needs_gpu"`; the frontend commands for 2a); **run pytest in
  the foreground**; several agents run at once, so a timing test that fails under load is run
  again alone before it is called a bug; update only the task's own row of `docs/status.md`;
  commit with the step ID first and the co-author line (git has no identity on this machine: `git -c user.name=PeterKelemen2 -c user.email=peter.kelemen456@gmail.com commit …`); never push; a change outside the
  owned files goes back to the lead.
- Report: the real output of each command (the last lines), the test rules' three checks
  (tests per file, mutations and results, uncovered lines with reasons), every deviation from
  the plan, the decision record, every file touched outside the owned list, and what S-7 or
  another out-of-scope step will need from this work.

## D-0: waves 4 to 6

The desktop spike, on Linux only ([0053](decisions/0053-linux-first-windows-testing-phase.md)).
Its Windows items (the sidecar on Windows, a kill from Task Manager, WebView2 rendering and
drag-and-drop paths) wait for the Windows testing phase of M10. D-1 to D-9 are not built
here. Layout, checks, versions and the parent watch:
[0054](decisions/0054-d0-spike-layout-and-parent-watch.md).

### The plan for D-0 (07 §D-0, word for word)

- [ ] Minimal Tauri app + PyInstaller **onedir** sidecar running `reframe-server` with a hello
      endpoint, on Linux. On Windows: *(Windows testing phase)*.
- [ ] Measure cold start to "ready" (target < 2 s from SSD).
- [ ] Prove cleanup: `kill -9` the Tauri process, then check that no sidecar or FFmpeg process
      remains. The same with a kill from Task Manager: *(Windows testing phase)*.
- [ ] Check drag-and-drop paths, PrimeVue rendering and canvas magnifier performance on
      WebKitGTK.
- [ ] Note any PyInstaller hidden imports (pydantic, uvicorn loops, langcodes data).

Done when: a short written result for Linux goes into `docs/decisions/0001-desktop-shell.md`
and confirms or revisits this choice. It lists the Windows items as not verified.

The `--parent-pid` addition to S-0 (06 §S-0, from 0054): `parent_pid` (`--parent-pid`; off by
default): the server watches that process and, when it ends, stops as
`POST /api/system/shutdown` does, with a hard exit when the stop does not end in time. A
reused pid is not taken for the parent.

The lead writes `0001-desktop-shell.md` from the reports of 4a and 4b, after checking their
numbers, and runs the M3 demo.

### Waves

| Wave | Task | Builds on |
|------|------|-----------|
| 4 | **4a** the shell and the sidecar: the Tauri app, the onedir build, `--parent-pid`, cold start, cleanup, hidden imports, the smoke test | `m3-api-spike` after the lead's commit of 0054 |
| 5 | **4b** the WebKitGTK checks in the 4a shell: drag-and-drop paths, PrimeVue rendering, the canvas magnifier | 4a merged |
| 6 | review (a fresh agent, given the code and the reports, not the lead's conclusions) of the D-0 work in `git diff main...m3-api-spike`, and a check that the M3 demo holds. Fixes go to the task that wrote the code (effort `high`, `SendMessage`), or to a new `high` agent | 4b merged |

Effort: 4a `xhigh`, 4b `high`, the review `xhigh`, fixes `high`. Every agent: `model: "opus"`,
`isolation: "worktree"`. Only one agent runs at a time in waves 4 to 6, so timing numbers are
not taken under the load of other agents; the lead runs nothing heavy while 4a measures.

### Who owns which files

| Task | Owns | Must not touch |
|------|------|----------------|
| **4a** | `desktop/spike/**` (except what 4b gets below), `packages/reframe-server/src/reframe_server/parent.py` (new), in `config.py` only the `parent_pid` field, in `__main__.py` only the `--parent-pid` option and starting the watch in `serve`, `packages/reframe-server/tests/test_parent*.py`, `packages/reframe-server/tests/test_frozen*.py`, a section "Follow-up (4a)" at the end of 0054, a heading "D-0 (4a)" in `testdata/README.md`, the S-0 row and the D-0 row of `docs/status.md` | every other server file, the core (`packages/reframe/`; a needed change goes to the lead), `frontend/`, `pyproject.toml` and `uv.lock` (ask the lead), `.github/`, `desktop/src-tauri/` and `desktop/sidecar/` (D-1, D-2) |
| **4b** | `desktop/spike/ui/**`, `desktop/spike/src-tauri/src/**` (the drag-and-drop event and what the check pages need; the sidecar code of 4a stays as it is unless a check needs a change, said in the report), `desktop/spike/package.json` + `package-lock.json` (dev dependencies for the checks, for example Playwright), new files in `desktop/spike/scripts/` and `desktop/spike/results/` (screenshots and measurement output, small PNG and JSON only), a section "WebKitGTK checks" in `desktop/spike/README.md`, a heading "D-0 (4b)" in `testdata/README.md`, the D-0 row of `docs/status.md` | 4a's build and measurement scripts, every server and core file, `frontend/` (no F-x components), `pyproject.toml`, `uv.lock` |

`docs/decisions/0001-desktop-shell.md` is the lead's. So are `pyproject.toml`, `uv.lock`,
`.gitignore`, the plan files and this file.

### Decision record numbers

| 0054 | 0001 |
|------|------|
| lead (layout, checks, parent watch; 4a adds a "Follow-up (4a)" section) | lead (the D-0 result) |

4b writes no record: its findings go into its report and `desktop/spike/README.md`, and the
lead puts them into 0001.

### Contracts

**Versions** (0054 item 3): crates `tauri` 2.12.5, `tauri-build` 2.7.4 (with `serde`,
`serde_json`, `tokio`, `libc` at their current stable versions), `Cargo.lock` committed; npm
`@tauri-apps/cli` 2.12.4, `@tauri-apps/api` 2.12.4, `package-lock.json` committed; Vue 3.5.43,
PrimeVue 4.5.5, `@primeuix/themes` 2.0.3, Vite 8.3.4, `@vitejs/plugin-vue` 6.0.10 (the
frontend's pins); PyInstaller 6.22.3 (in `uv.lock` already, root `dev` group). No
`tauri-plugin-shell`. A change of version is a question to the lead.

**Paths**: `desktop/spike/scripts/spike_paths.py` (in the lead's commit): `SPIKE`, `REPO`,
`TAURI`, `SIDECAR_DIST`, `SIDECAR_ONEDIR`, `FROZEN_SERVER`
(`desktop/spike/dist/reframe-server/reframe-server`). The tests also take the frozen binary
from `REFRAME_FROZEN_SERVER`.

**Isolation**: every sidecar that a script or a test starts gets its own temporary
`REFRAME_CONFIG_DIR`, `REFRAME_DATA_DIR` and cache folder. Nothing in this work reads or writes
the owner's real Reframe settings, queue or cache.

**4a, server** (06 §S-0 with 0054 item 4): `ServerConfig.parent_pid: int | None = None`
(`REFRAME_PARENT_PID`), `reframe-server --parent-pid PID`. `parent.py` watches the process
(a reused pid is not the parent: check the process start time, or a pidfd on Linux); when it
ends, `serve` stops as `request_shutdown()` does; if the server has not stopped within a fixed
time, the process exits hard. A parent that is already gone at start-up, the exit code and the
times are 4a's choices, recorded in "Follow-up (4a)". The Windows path is written and
mock-tested. Tests: a real `reframe-server` with `--parent-pid` of a stand-in parent; the
stand-in is killed with SIGKILL while a real encode runs; the server and its FFmpeg end within
the time the record gives; and a reused pid is not the parent.

**4a, shell** (07 §Sidecar lifecycle, the parts D-0 needs): the Tauri app spawns the sidecar
(the frozen onedir by default; an environment variable may point it at
`uv run reframe-server` for a comparison) with `--mode desktop --port 0 --auth token
--parent-pid <its pid>`, a token made in Rust in `REFRAME_TOKEN`, and on Linux
`PR_SET_PDEATHSIG` in `pre_exec` (say which signal and why). It reads stdout until the ready
line (20 s timeout), keeps `{baseUrl, token}` in managed state, offers `backend_info`, and the
page shows `GET /api/health`. An early exit or a timeout of the sidecar shows an error on the
page (no restart: D-3). Normal quit: `POST /api/system/shutdown`, wait up to 5 s, then kill.
The sidecar's stderr goes to a log file in its temporary data folder.

**4a, measurements and proofs** (each repeatable from `desktop/spike/scripts/` and described
in `desktop/spike/README.md`):

- The onedir build script, with each hidden import, collected package and data file next to
  the error it fixed (`reframe/definitions/data`, the built-in presets, `language_data` /
  `langcodes`, pydantic, uvicorn's loops and protocols, anything else).
- Cold start: at least 10 runs each, the median and the worst, (a) the sidecar alone, spawn to
  the ready line, and (b) the app, process start to the page showing `/api/health`; each with a
  warm page cache and with the onedir's pages evicted. `sudo` is not available: evict with
  `posix_fadvise(POSIX_FADV_DONTNEED)` on every file of the onedir and show with `fincore`
  that the pages are gone; say what this does not evict (the system libraries, WebKitGTK).
  Target < 2 s from SSD.
- Cleanup, three cases, each with a real encode running through the sidecar's API and the
  `ps` / `pgrep` output before and after: `kill -9` of the Tauri process; `kill -9` of the
  sidecar alone (and what the app shows); a normal quit. Say how long each took, and what
  became of the job and its `.part` file.
- Smoke test `tests/test_frozen_sidecar.py`: the frozen binary prints the ready line and
  answers `GET /api/health`; its cleanup case (kill the parent, nothing left). It is skipped
  with a reason when the frozen build is not there (CI does not build it).

**4b** (in the 4a shell, against the frozen sidecar):

- Drag-and-drop from Dolphin: the paths that arrive (Tauri's drag-drop event; also what the
  DOM `drop` event gives), for a file name with spaces, one with non-ASCII characters (for
  example `Ünnepi film – 2.mkv`, `日本語.mkv`), several files at once, and a folder. Native
  Wayland first; XWayland (`GDK_BACKEND=x11`) as a second case. A drag needs a real pointer:
  try to automate it; if that is not possible, build a page that logs every drop to a file and
  write the exact steps for the owner, then report to the lead, who asks the owner.
- PrimeVue 4 rendering: one spike page with DataTable (200 rows), Dialog, Select, Slider, Tabs
  and Toast, in the light and the dark theme (the preset the frontend will use), screenshots of
  each, and anything that renders differently from Firefox and Chromium.
- Canvas crop magnifier prototype (06 §F-7 describes the real one): a real 4K frame from the
  sidecar's preview API (`hdr10-4k.mkv`), four edge strips at 4× with
  `imageSmoothingEnabled = false` and a cursor loupe, redrawn on pointer movement; frame times
  (median, 95th percentile, worst; dropped frames) under pointer movement in WebKitGTK and the
  same page in Chromium. No Chromium is installed and `sudo` is not available: Playwright's own
  Chromium download needs no `sudo`. Say how the pointer movement was made (synthetic events
  or a real pointer) and what that does not measure.

### Every agent prompt for waves 4 to 6 includes

The items of §"Every agent prompt includes", adapted: the D-0 plan above and the S-0
`--parent-pid` text word for word, the owned and forbidden files, these contracts, the
isolation rule, and §"Test rules" word for word with "server" read as "server or spike" (the
coverage command stays for the server code). Also:

- Every claim about Tauri, PyInstaller, WebKitGTK or process behaviour is checked on the real
  tools, and the report gives the command and its output. Nothing is taken from memory.
- The Rust code passes `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings`; the
  spike UI builds with `vite build`.
- No `sudo`. A step that needs `sudo` or a GUI action by the owner goes back to the lead.
- Nothing runs on Windows; the Windows code paths are written and mock-tested only.

### 4b again, in two tasks (2026-10-27)

The first 4b run was lost (progress, 2026-10-27). 4b is redone from its contract above, as two
tasks that run one after the other (effort `high` each), on the owner's AMD desktop (Ryzen 5
5600, 12 threads, Radeon RX 7600, KDE Plasma 6.8 on Wayland, WebKitGTK 2.54.2). 4a measured on
the laptop (Intel UHD 620); the lead repeats its numbers here for 0001. The owner watches a
movie on `DP-1` while the work runs: every window goes on `HDMI-A-1`, no synthetic keyboard
events, pointer runs only on `HDMI-A-1` (the owner allowed them, 2026-10-27), timings are
taken under that load (the lead's brief, §Displays).

| Task | Owns | Must not touch |
|------|------|----------------|
| **4b-i** drag-and-drop paths, PrimeVue rendering, the window and pointer tools | `desktop/spike/src-tauri/src/**` (4a's `sidecar.rs` as it is, unless a check needs a change, said in the report), `desktop/spike/src-tauri/tauri.conf.json`, `desktop/spike/src-tauri/capabilities/**`, `desktop/spike/ui/**` except 4b-ii's files, `desktop/spike/package.json` + `package-lock.json`, new files in `desktop/spike/scripts/` (not `magnifier*`), `desktop/spike/results/drop-*` and `desktop/spike/results/prime*`, a section "WebKitGTK checks" in `desktop/spike/README.md` (with one line that links `MAGNIFIER.md`), a heading "D-0 (4b-i)" in `testdata/README.md` | 4a's build and measurement scripts, every server and core file, `frontend/`, `pyproject.toml`, `uv.lock`, `docs/status.md` (the lead's in phase 1) |
| **4b-ii** the canvas magnifier | `desktop/spike/ui/src/pages/MagnifierPage.vue`, `desktop/spike/ui/src/magnifier/**`, new `desktop/spike/scripts/magnifier*` files, `desktop/spike/results/magnifier*`, `desktop/spike/MAGNIFIER.md`, a heading "D-0 (4b-ii)" in `testdata/README.md` | every file of 4a and 4b-i (a change goes to the lead), every server and core file, `frontend/`, `pyproject.toml`, `uv.lock`, `docs/status.md` |

Hooks that 4b-i builds for 4b-ii (binding):

- `REFRAME_SPIKE_PAGE=<name>` makes the app show `ui/src/pages/<Name>Page.vue` (found with
  `import.meta.glob`, so a new page file needs no other change). Without it the page is 4a's,
  with its `page_ready` / `page_failed` calls unchanged (4a's scripts rely on them).
- In a browser (no Tauri) the same pages run from the built UI with
  `?page=<name>&base=<url>&token=<token>`.
- A module `ui/src/spike.js`: `backend()` → `{baseUrl, token}` (Tauri's `backend_info`, or the
  query in a browser); `log(record)` → in the app a Tauri command that prints the record as one
  JSON line on stdout (`{"event": "spike_log", "ms": …, …}`), in a browser something a
  Playwright script can collect; `snapshot(path)` → in the app a PNG of the web view itself
  (WebKitGTK's own snapshot call) or the reason it cannot be done.
- `scripts/windows.py`: put a window of the app, Dolphin or a headed browser at a fixed size
  inside `HDMI-A-1`, read back its output and geometry, keep the active window as it was, close
  it; and a wrapper that runs a command with that placement on (for 4a's `cold_start` and
  `cleanup`). `scripts/pointer.py`: the real pointer through `/dev/uinput`, every move read
  back and refused outside `HDMI-A-1`.

## For later steps (recorded, not built)

- S-7: `server.json` (`endpoint_file`), idle exit (`hub.connections`, the queue, the power
  countdown), `client_id` in the hub's first answer and `client_open`, `attach` in
  `POST /api/queue`, `--owner-only` exit 75, the queue opened at start-up.
- S-4: static files and the SPA fallback (`static_dir`); the security headers of 1a apply
  to them.
- Q-1.4: a Windows run of the server tests, in the Windows testing phase of M10 ([0053](decisions/0053-linux-first-windows-testing-phase.md)).

## Progress

| Date | What |
|------|------|
| 2026-10-22 | `m3-api-spike` made from `main` (91c5107). Tools installed on this machine first: `uv` 0.13.5, `mkvpropedit` v102.0 (the owner), the pinned FFmpeg (`scripts/fetch-tools.py`) |
| 2026-10-22 | Contract commit: dependencies, decision 0045, this breakdown, the S-0 skeleton and the stubs, the harness. Server tests: 30, every contract test mutation-checked (28 mutations, all killed). Full suite in three chunks: 1998 + 3483 + 1134 = 6615 passed, 2 skipped, 1 failed: `packages/reframe/tests/queue/test_in_place_stop.py::test_a_paused_edit_that_a_stop_resumes_is_shown_running` (both cases) fails on a clean `main` too, every run, on this machine (Python 3.14.8): the sleep inhibit is not held after the stop resumes the paused edit. A core issue, out of this scope; reported to the owner. ruff, format, mypy (both platforms), the frontend commands green |
| 2026-10-22 | **Wave 1 started** from `m3-api-spike` 393fae0: five agents (1a S-1, 1b S-3, 1c S-2 queue / power / tasks, 1d S-2 system / fs / settings / sources / preview, 1e S-2 definitions / languages / jobs / naming / batch / presets), one worktree each |
| 2026-10-22 | Merged 1c (S-2 queue, power, tasks; 0048): 39 tests, 54 mutations by the agent all caught; the lead's 3 (jail removed on add, held UTF-8 bytes counted, when-done always cancels) caught. Checks on the merge: ruff, format, mypy (both platforms) green; server 69 passed. Open for the lead / review: no public "queue is processing" state in the core (UI start/stop, S-7 idle exit); move the when-done cancel into `Reframe._settings_changed` so `PUT /api/settings` matches; `QueueJob` answers carry `log_path` and plan file paths (data folder) |
| 2026-10-22 | Merged 1e (S-2 definitions, languages, jobs, naming, batch, presets; 0050): 73 tests, 92 mutations by the agent all caught; the lead's 3 (an unknown override skipped, `name_conflict` → 422, the dry-run route's jail removed) caught. 06 conflict with 1c resolved row by row. Checks on the merge: ruff, format, mypy (both platforms) green; server 142 passed. Open: **web mode with the default naming (`same_as_source`) drafts an output next to the source in a media root, which the real jail refuses** (needs a rule: an output folder below an output root by default in web mode); `presets.write_failed` names the server's config folder; a core `job_geometry(job, source)` would remove the router's copy of the builder's deinterlace rule; the feature rows of `status.md` (Output naming, Batch) still say their routes are missing |
| 2026-10-22 | Merged 1d (S-2 system, fs, settings, sources, preview; 0049): 56 test functions, 86 mutations by the agent all caught; the lead's 3 (web tool-path check off, a byte range served from 0, no cancel when the client goes away) caught. Lead fix a472ff8: the session fixture `fixture_media` resolved ffmpeg at each call, so a test that had pointed `REFRAME_FFMPEG` at the fake regenerated the shared `testdata/media/multitrack.mkv` with garbage (found when 1d's workaround was removed); the plugin now resolves it at session set-up, the harness keeps the real tools found before it changes the environment, and `add_fixture` copies instead of linking |
| 2026-10-22 | Merged 1a (S-1; 0046): 52 test functions, 102 mutations by the agent all caught; the lead's 3 (expiry not signed, the jail compares the unresolved path, the expiry not checked) caught. Lead integration fix 7306962: 1a's two settings route checks skipped for good (FastAPI 0.159 keeps an included router as one `app.routes` entry, so their route lookup never found `/api/settings`); they now run and pass. 1d's two preview tests used a fake `sign_media_url` that the real media check refuses; they now check the real URL |
| 2026-10-22 | Merged 1b (S-3; 0047): 17 test functions, 40 mutations by the agent all caught; the lead's 3 (unbounded subscription, sequence gaps, close code 1000) caught. **Wave 1 done.** Checks on `m3-api-spike` ceb2e09: ruff, format, mypy (both platforms) green; server + testing 546 passed, 1 skipped. Open questions for the owner: the default output folder in web mode (the jail refuses `same_as_source`); free filter text (`filters.custom`, a filter's custom preset) can name files (`movie=`, `drawtext=textfile=`) that the jail never sees |
| 2026-10-22 | **Wave 2 started**: 2a (S-5, Q-2.3, the S-2 facade coverage test, the jail sweep; 0051). The owner's decisions on the two open questions: web mode **requires a fixed output folder** inside an output root (validation gives `output.folder_required` with a settings fix; 1e follow-up, 0050), and free filter text is checked against an **allow-list of filters** in web mode (`jail_job` refuses `filter.not_allowed`; 1a follow-up, 0046). Both given back to the agents that wrote the code |
| 2026-10-22 | Merged 2a (S-5, Q-2.3, S-2 facade coverage, jail sweep; 0051): 50 tests, 25 mutations by the agent all caught; the lead's 3 (presets import unjailed, a new public preset-service method, the `operationId` rule) caught. `openapi-typescript` 7.13.0 with an npm override to the project's TypeScript 6 (its peer range is 5.x); `schema.d.ts` 313 920 bytes; the WebSocket messages are in the components (through a webhook that is removed from the document); Q-2.3 is its own CI job (`api-contract`, Ubuntu). The sweep found a route bug: `batch/resolve` and `resolve-run` do not jail the per-file overrides (a probe for files outside the roots); two `xfail(strict=True)` cases, given to 1e with its follow-up. Checks on 2aa821e: ruff, format, mypy (both platforms), the frontend commands and `gen-api.sh --check` green; server + testing 594 passed, 1 skipped, 2 xfailed |
| 2026-10-22 | Merged the follow-ups: 1a (0046 follow-up: web mode checks free filter text against an allow-list of 107 video filters, a port of FFmpeg's graph parser checked with `-print_graphs_file`; 25 mutations, the lead's 3 caught) and 1e (0050 follow-up: `output.folder_required` with a settings fix in web mode; batch overrides resolved and jailed before the facade sees them, 2a's two xfail cases pass; 35 mutations, the lead's 3 caught). **Wave 2 done.** Checks on 7ba9263: ruff, format, mypy (both platforms), the frontend commands, `gen-api.sh --check` green; full suite in four chunks 652 + 3554 + 1916 + 913 = 7035 passed, 2 skipped, 0 failed (`test_in_place_stop` passed this time: intermittent, not a hard failure). Open for the review / later: `encoders.vaapi_device` in a web settings patch; `preview/render` and `clip` jail the output path of a job they never write; `GET /api/system` could report the missing web output folder; `presets.write_failed` names the config folder; `QueueJob` answers carry data-folder paths; a core `job_geometry`; a public "queue is processing" state; the when-done cancel in `Reframe._settings_changed` |
| 2026-10-22 | **Wave 3 started**: a fresh review agent (`xhigh`) on `git diff main...m3-api-spike` (7ba9263) |
| 2026-10-22 | **Review** (fresh agent, `xhigh`) on 191c4f7: 1 blocker, 6 majors, 5 minors and the test-quality table; the reviewer was stopped by an API error before its full report, the lead reran each of its experiments and reproduced every finding. List and decisions: [0052](decisions/0052-m3-server-review.md). Lead core change 2b76fab (C-9): `SettingsService.update(…, check=)` runs the caller's check under the store's lock (for R-3), with a test that fails when the check is not called. Fix round: six fresh agents (`high`), one per task (1a, 1b, 1c, 1d, 1e, 2a) |
| 2026-10-22 | **Fix round of 0052 done.** Merged, each after the lead's read of the report and the test diff, the lead's own mutations and the reviewer's script for each finding: 2a (509cc64: the sweep sends one link per input, an allowed entry first in every list, and checks that a refused request changes nothing; the lead's first check found two gaps, fixed before the merge), 1e (13f2798, 755eadd: R-7, R-10, R-12), 1a (1bf8ab2: R-1, R-6, R-8), 1d (63e6c9e: R-2, R-3, R-4, R-9; the sweep's R-2 case loses its xfail mark), 1c (20d82aa: R-11; `folders.py`), 1b (2f310c7: R-5, the stall's fixed client buffer, task events hide the folders). Lead commits: f7e68b0 (the `test_app.py` items), 35e0aa1 (C-12: `BatchService.resolve(…, check=)`, for R-7: the router could only refuse after the service had looked at the file), 1c2371a (`timeout_graceful_shutdown=2` in `__main__.serve`, the hub's `hide=` in `create_app`, a test over the real server for it). Checks on 1c2371a: ruff, format, mypy (both platforms), the frontend commands, `gen-api.sh --check` green; full suite in six chunks 614 + 256 + 1700 + 1607 + 736 + 2086: 6998 passed, 2 skipped, 1 failed (`preview/test_benchmark.py::test_4k_hdr_frame_budget`: fails on `main` too on this machine, timing). Server: 412 tests in 264 s (about 432 before the round). The demo (`reframe-server` in web mode with the 4K fixture: health, OpenAPI, the committed types, probe, draft, encode with progress over `WS /api/events`, exit 130) passes. Open for M3: D-0, Q-1.4 |
| 2026-10-23 | Decision 0053 (the owner): Linux first. Q-1.4 and D-0's Windows items move to the Windows testing phase of M10; M3 is done when D-0 passes on Linux |
| 2026-10-23 | Waves 4 to 6 planned (D-0 on Linux), decision 0054 (the spike in `desktop/spike/`, its checks, the pins, `--parent-pid` in S-0). Prerequisites checked against the Tauri 2 page: rustc / cargo 1.99.1, `webkit2gtk-4.1` 2.54.1 and the rest present; `libappindicator-gtk3` is `libappindicator` in Arch now, `libayatana-appindicator` 0.6.1 installed (no tray in the spike). PyInstaller 6.22.3 added to the `dev` group |
| 2026-10-23 | **Wave 4 started**: 4a (`xhigh`) from `m3-api-spike` cae9707 |
| 2026-10-23 | Merged 4a (78a0e75; S-0 `--parent-pid` 4bb6c45, the spike 0aabe2c): `test_parent.py` 9 functions (10 items), `test_frozen_sidecar.py` 2 (skipped without the build); 26 mutations by the agent (19 source, 7 frozen builds) all caught; the lead's 3 (age check inverted, no stop request from the watch, the server runs on with a gone parent) caught. The lead rebuilt the onedir (43 s) and the app (`tauri build --no-bundle`) on the merge and repeated the numbers: cold start, 10 runs each, sidecar alone warm median 1.26 s / worst 1.32 s, evicted 1.47 / 1.52; app to the page showing health warm 1.40 / 1.44, evicted 1.54 / 1.60 (4a: 1.18 / 1.21, 1.39 / 1.45, 1.34 / 1.37, 1.47 / 1.53); cleanup with an x265 encode running: `kill -9` of the app gone in 0.275 s, `kill -9` of the sidecar immediate (the page shows it after 0.018 s), quit 0.614 s (204 from the shutdown request, no kill); every job `interrupted` and its `.part` removed (after the sidecar kill: at the next start). Checks on 78a0e75: ruff, format, mypy (both platforms), the frontend commands, `gen-api.sh --check`, `cargo fmt --check`, `cargo clippy -D warnings` green; full suite in four chunks 626 + 2437 + 1632 + 2316 = 7011 passed, 2 skipped, 0 failed (the frozen tests ran). Open from 4a for the lead (core, after M3): a missing definitions data file loads as empty (a broken build starts with 0 encoders), `naming/parse.py` swallows every guessit error, the sidecar's MediaInfo (pymediainfo is the core's optional extra; D-2 decides), a failed lifespan start-up prints `Task exception was never retrieved … SystemExit(3)` |
| 2026-10-23 | **Wave 5 started**: 4b (`high`) from `m3-api-spike` 4664988 |
| 2026-10-23 | **4b stopped by the owner** before its report (its last step was "rebuild and rerun the input checks in all four configurations"). Its uncommitted work is saved by the lead as WIP commit 1e17c5c on the branch `worktree-agent-ae6845cfb661b864d` (worktree `.claude/worktrees/agent-ae6845cfb661b864d`); **not reviewed, not merged**. State found on disk: three check pages in the spike (`REFRAME_SPIKE_PAGE=drop\|prime\|magnifier`), `scripts/webkit_checks.py`, `browser_checks.py` + `playwright_checks.mjs` (Playwright 1.64.1, Chromium 156.0.8078.4, Firefox 157.0), `desktop_input.py` (real pointer on native Wayland without root through `/dev/uinput`, which has a user ACL). **Drag-and-drop**: `results/drop-wayland.json` and `drop-xwayland.json`, six cases each, both with Tauri's handler and the DOM's: Tauri's event gives every path exact (spaces, `Ünnepi film – 2.mkv`, `日本語.mkv`, three files, a folder); a non-UTF-8 name arrives with U+FFFD and does not exist (Dolphin already sends `%EF%BF%BD`); the DOM drop has no files and one HTML link to the first item only. The README still calls native Wayland "open" (written before the uinput runs): to correct. **PrimeVue**: 18 screenshots (WebKitGTK native Wayland, Chromium, Firefox × light / dark × base / select / dialog) and a list of differences in the README (Chromium's classic scrollbars, 2–3 px line boxes; WebKitGTK and Firefox the same to 1 px; CSP fine). **Magnifier**: page and four variants built, the README has conclusions (60 Hz in all three engines; `WEBKIT_DISABLE_DMABUF_RENDERER` drops the full redraw to about 39 fps) but **no numbers on disk** (`MAGNIFIER_RESULTS` placeholder). Still to do for 4b: rerun the input checks in the four configurations, record the magnifier table, fix the README, the checks (`cargo fmt` / `clippy`, `build:ui`, ruff / mypy, server pytest), its report; then the lead's merge checks, wave 6 (review), 0001, the M3 demo, the merge into `main` |
| 2026-10-27 | **Correction of the row above: the WIP commit is not available.** In this clone (the owner's AMD desktop; `m3-api-spike` pulled from origin on 2026-10-25) `git cat-file -t 1e17c5c` gives `fatal: Not a valid object name 1e17c5c`; there is no branch `worktree-agent-ae6845cfb661b864d`, no worktree, no `desktop/spike/results/`, and no dangling commit. The run was on the owner's laptop, which the owner had to pack (that is why it was stopped). So nothing of the first 4b run is in the repository, and the findings the row lists are not facts: 4b is redone from its contract, as 4b-i and 4b-ii ([4b again](#4b-again-in-two-tasks-2026-10-27)), and every finding is checked again. 4a's numbers are from the laptop (Intel UHD 620, 8 threads); the lead repeats them on this machine for 0001. The owner allowed pointer runs on `HDMI-A-1` |
