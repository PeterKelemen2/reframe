# M3 server task breakdown

Working notes of the lead for the server part of milestone M3: S-0, S-1, S-2, S-3, S-5 and
Q-2.3. The plan ([plan/06-web-app.md](plan/06-web-app.md) Part A, [plan/08-roadmap.md](plan/08-roadmap.md)
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

**Out of scope** (write down what a scope step needs from them; do not build it): S-4 (M4), S-6
(M10), S-7 + C-17 (M3b), D-0 and Q-1.4 (the desktop / a Windows run), every F-x.

**Branch**: `m3-api-spike`, made from `main` (origin's branch of that name is already in
`main`). Each task works in its own worktree branch made from `m3-api-spike`; the lead merges
it with `--no-ff` after every check passes, including the test rules. `m3-api-spike` is not
merged into `main` in this work: M3 also needs D-0 and Q-1.4. Never push.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: decision 0045, this breakdown, the contract commit (S-0 done) | `main` |
| 1 | 1a S-1 security · 1b S-3 events · 1c S-2 queue, power, tasks · 1d S-2 system, fs, settings, sources, preview · 1e S-2 definitions, languages, jobs, naming, batch, presets | the contract |
| 2 | 2a S-5, Q-2.3, the S-2 facade coverage test, the jail sweep over every path route | wave 1 merged |
| 3 | review (a fresh agent, given the code, not the lead's conclusions) of `git diff main...m3-api-spike`: correctness, security and test quality. Fixes go to the task that wrote the step (effort `high`) | wave 2 |

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

## For later steps (recorded, not built)

- S-7: `server.json` (`endpoint_file`), idle exit (`hub.connections`, the queue, the power
  countdown), `client_id` in the hub's first answer and `client_open`, `attach` in
  `POST /api/queue`, `--owner-only` exit 75, the queue opened at start-up.
- S-4: static files and the SPA fallback (`static_dir`); the security headers of 1a apply
  to them.
- D-0 / Q-1.4: the desktop spike and a Windows run of the server tests.

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
