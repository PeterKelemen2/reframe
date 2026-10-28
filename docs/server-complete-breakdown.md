# Server-complete task breakdown

Working notes of the lead for the branch `server-complete`: the server side of S-7, S-4 and
S-6, built before their milestones ([decision 0055](decisions/0055-server-complete-order.md)).
The plan ([plan/06-web-app.md](plan/06-web-app.md) §S-4, §S-6, §S-7, and
[0042](decisions/0042-one-scheduler-process-and-cli-clients.md) items 2, 5 and 8) is the spec;
this file says who builds which part, in which order, and what each part must offer to the
others. Status: [status.md](status.md). The branch is not merged into `main` by this work. If
the lead's context is summarised, this file and `status.md` are the source of truth.

## Scope and order

| Task | What is built here | Plan |
|------|--------------------|------|
| A | S-7 owner: the queue opened at start-up, `server.json` with the local token, `--owner-only` (exit 75), idle exit | 06 §S-7; 0042 items 2, 8 |
| B | S-7 attachments: `client_id` in `hello`, `attach`, `detach`, a closed connection cancels its attached jobs; `start` with `job_ids` proved | 06 §S-7; 0042 item 5 |
| C | S-4: `static_dir` in web mode, immutable hashed assets, the SPA fallback; none in desktop mode | 06 §S-4 |
| D | S-6: the Docker image, the compose example, bare metal with a systemd user unit, reverse-proxy notes | 06 §S-6 |

Out of scope: C-17 (what it needs is listed at the end), every `F-x`, `D-1` to `D-9`.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: decision 0055, this breakdown, the contract commit | `main` (6e8ba14) |
| 1 | A, B, C, at the same time | the contract |
| 2 | D | wave 1 merged |
| 3 | two reviews by fresh agents (given the code and the authors' reports, not the lead's conclusions) of `git diff main...server-complete`, then the fixes | wave 2 merged |
| 4 | the lead: the full suite in chunks; the real server demo (the `server.json` lifecycle, `--owner-only` exit 75, idle exit, the attach cases over a real WebSocket); the frozen sidecar rebuilt, its test and a cold start under 2 s; D's `docker compose up` with the GPU, in a slot the owner gives; a docs commit | wave 3 fixes merged |

### Effort and model

Every agent: `model: "opus"`, `isolation: "worktree"`. `effort: "xhigh"`: A, B and both
reviews. `effort: "high"`: C, D and the fixes of minors and docs; a fix of a blocker, a major,
a concurrency or a process-cleanup finding is `xhigh`.

## Who owns which files

An agent edits only the files it owns. Two agents never own the same file. A change anywhere
else goes back to the lead (say so in the report; do not make it). Paths are relative to
`packages/reframe-server/src/reframe_server/` (code) and `packages/reframe-server/tests/`
(tests) unless they start with `docs/`, `docker/`, `scripts/`, `frontend/` or `testing/`.

| Task | Owns | Must not touch |
|------|------|----------------|
| **A** | `owner.py`, `idle.py`, `tests/test_owner*.py`, `tests/test_idle*.py` | `app.py`, `__main__.py`, `config.py` (the calls are wired), `events.py`, the routers, `security.py`, the core |
| **B** | `events.py`, `openapi.py` (only to add the client messages to the components), `routers/events.py`, `routers/queue.py`, `tests/test_attach*.py`, new cases in `tests/test_events.py` and `tests/test_queue.py`, `frontend/src/api/schema.d.ts` (regenerated with `scripts/gen-api.sh`) | `owner.py`, `idle.py`, `app.py`, `security.py`, the core |
| **C** | `static.py`, `tests/test_static*.py` | `app.py` (`create_app` calls `static.install` last), `security.py`, `config.py`, the routers, `frontend/` |
| **D** | `docker/` (Dockerfile, compose example, entrypoint, its README if useful), `.dockerignore`, `docs/deployment.md` (bare metal, systemd user unit, reverse proxy), `tests/test_deploy*.py` if a test meets the test rules | every Python module, `frontend/`, `tools/ffmpeg.toml`, `scripts/fetch-tools.py` (use them) |

**Lead-owned**: `api.py`, `app.py`, `config.py`, `deps.py`, `errors.py`, `sources.py`,
`__main__.py`, `routers/__init__.py`, `routers/health.py`, `tests/conftest.py`,
`tests/test_app.py`, `testing/reframe_testing/server.py`, every file of the core package
`packages/reframe/`, `packages/reframe-server/pyproject.toml`, `uv.lock`.

**Shared files** (the lead resolves merge conflicts):

- `docs/status.md`: each task updates only its own step's row (A and B both write the S-7
  row: A its first sentence block, B a block that starts with "Attachments:").
- `docs/plan/06-web-app.md`: a task edits only its own step's section, and only together with
  its decision record (ticking a checkbox is part of the step).
- `testdata/README.md`: real tool behaviour a task relied on, under a heading of its task.

## Decision record numbers

One record per task; a review fix adds a dated section to the record of the task that wrote
the step.

| 0055 | 0056 | 0057 | 0058 | 0059 | 0060 |
|------|------|------|------|------|------|
| lead (order, contract) | A | B | C | D | lead (review) |

## Contracts

Signatures are binding. A task may add keyword-only parameters with defaults, extra functions
and new models in its own files, but not change these. Read the code of the contract commit;
this is its summary.

### Built by the lead (contract commit)

- `reframe.models.ServerEndpoint` (`DocumentModel`: a newer server's fields are kept):
  `pid`, `instance`, `port` (1–65535), `token` (`repr=False`), `version`, `api_version`,
  `started_at` (aware). It is the content of `server.json`.
- `QueueService.owns_store -> bool`: this process holds `queue.lock` and keeps its jobs in the
  saved queue (`False` before the first use, for a private queue, and after `close()`).
- `QueueService.busy -> bool`: a job is running or paused, or the runner will still take a
  waiting job (a `start` targets it, also a restored job whose file keys are still being
  read). A waiting job that no `start` targets does not count.
- Existing and unchanged: `Reframe.data_dir`, `PowerService.pending` (a countdown, or an action
  that still executes), `EventHub.connections` (open, authenticated connections),
  `EventHub.client_open(client_id) -> bool` (a stub that returns `False`), `API_VERSION`
  (`api.py`, also in `GET /api/health`), `config.secret_token`, `config.endpoint_file`,
  `config.idle_exit`, `config.owner_only`, `config.static_dir`.
- The facade's two new members are in the "Not exposed" table of 06.

### Stubs the tasks fill in (signatures fixed)

`owner.py` (A). `ENDPOINT_FILE = "server.json"`, `EXIT_STORE_BUSY = 75`, `class StoreBusy`.

```python
def start(app: FastAPI) -> None          # the lifespan, after Reframe.create: open the queue
def publish(app: FastAPI, port: int) -> Path | None   # serve(), once uvicorn listens
def withdraw(app: FastAPI) -> None       # the lifespan's close, before reframe.close()
```

- `start`: opens the queue (`reframe.queue.list()`; the core takes the lock without waiting,
  on the event loop, once). When the queue does not own the store and `config.owner_only` is
  set: `app.state.exit_code = EXIT_STORE_BUSY`, then `raise StoreBusy`. uvicorn's start-up
  then fails and `serve()` returns `app.state.exit_code`. Without `owner_only` nothing more:
  the core already keeps a private queue and publishes `queue.store_busy`.
- `publish`: only when `reframe.queue.owns_store`. Writes `ServerEndpoint` to
  `config.endpoint_file` or `<reframe.data_dir>/server.json`: atomic (a temporary file in the
  same folder, then `os.replace`), mode `0600` on POSIX from its creation, replacing a stale
  file. Returns the path; `None` when nothing was written.
- `withdraw`: removes the file only if it still names this run's `instance`.

`idle.py` (A).

```python
def is_idle(app: FastAPI) -> bool
async def watch(app: FastAPI, seconds: float, request_shutdown: Callable[[], None]) -> None
```

- idle = not `reframe.queue.busy`, `hub.connections == 0`, `reframe.power.pending is None`;
  `watch` calls `request_shutdown()` after `seconds` of idleness in a row and runs until
  `serve()` cancels it. `serve()` starts it only when `config.idle_exit` is set.

`static.py` (C).

```python
def install(app: FastAPI, config: ServerConfig) -> None   # create_app, after every router
```

`events.py` (B): `EventHub.client_open` is the stub; B adds the rest in its own files.

`app.state.exit_code` (default 1) is what `serve()` returns when the app does not start.

### Per task

**A — S-7 owner** (0056). Done when (06 §S-7, the parts of A, word for word from the "Done
when"): "httpx tests show that the file is written after the server listens and removed at
close, that a stale file left by `kill -9` is replaced, that `owner_only` exits with 75 on a
busy lock, that idle exit waits for a running job, … and that the local token works in
`password` mode".

- The token is never logged and never in an answer (`GET /api/health` has `instance` and
  `api_version`, not the token).
- `server.json` is written only after the queue is open, the lock is held and the server
  listens; a server that cannot take the lock writes nothing (the private queue with
  `queue.store_busy`).
- Prove with the real `reframe-server` process (`subprocess`, as `tests/test_parent.py`
  does): the file appears after the port answers, has mode `0600`, holds a token that the API
  accepts in `password` mode, and is gone after SIGINT; a file left by `kill -9` is replaced
  by the next owner; `--owner-only` against a held lock exits 75 and writes nothing; idle exit
  waits for a running job (the fake FFmpeg) and an open event connection.
- Windows: the file mode, `os.replace` over a file another process has open, and anything
  else that differs, mock-tested on Linux (decision 0053).
- Open question for A to answer in 0056 (default: loopback and the port): what a client
  should connect to when the server listens on a non-loopback address only. A new field in
  `ServerEndpoint` goes back to the lead.

**B — S-7 attachments** (0057). Done when (06 §S-7, the parts of B, word for word): "httpx
tests show … that a closed connection cancels its attached jobs (and a `detach` does not),
that `attach` with the id of a closed connection is refused, … and that `start` with
`job_ids` leaves other waiting jobs alone."

- `hello` gets `client_id` (random per connection). `POST /api/queue` with `attach` is
  refused with 409 `queue.attach_unknown_client` unless that connection is open (the route
  already checks `hub.client_open`); the added jobs are attached to it.
- A `detach` client message: the jobs stay when the connection ends afterwards.
- A connection that ends without `detach` cancels its attached jobs that have not ended, the
  way a cancel does (a waiting job becomes `cancelled`; a running one is stopped and its
  `.part` file follows the partial-file setting). Not persisted.
- The race: the connection closes between the attach check and the add. The added jobs must
  still be cancelled; prove it.
- Run `scripts/gen-api.sh` and commit `frontend/src/api/schema.d.ts`.

**C — S-4 static** (0058). 06 §S-4 has no "Done when"; it is done when tests show:

- web mode serves `static_dir`: hashed assets with `Cache-Control: public, max-age=31536000,
  immutable`, `index.html` revalidated (`no-cache`);
- an unknown non-API `GET` gets `index.html`; an unknown `/api/*` path stays the JSON problem
  404; desktop mode serves no static file;
- the S-1 security headers, the Host check and the CSP apply to static answers;
- `..`, an encoded `..` (`%2e%2e`, `%2f`) and a symlink out of the folder never leave it;
- where the default `static_dir` comes from is decided and recorded (a change of `config.py`
  or of the package build goes back to the lead with the proposal);
- a real `npm run build:web` output is served (in the report).

**D — S-6 deployment** (0059). Done when (06 §S-6, word for word): "`docker compose up` on a
Linux host with a GPU (the owner's: AMD) shows its VAAPI encoders as available and encodes a
fixture file. Intel QSV and NVIDIA NVENC in Docker are listed as not verified until such a
host is available ([decision 0043](decisions/0043-plan-review-before-m3.md) item 7)."

- A multi-stage image: a `node` stage builds `frontend/dist`; a `tools` stage fetches the
  pinned FFmpeg of `tools/ffmpeg.toml` and checks its SHA-256; a Debian slim runtime with
  `reframe-server` installed with uv, FFmpeg in `/opt/reframe/tools/ffmpeg/`, `mkvtoolnix`,
  `mediainfo` and pinned VAAPI user-space drivers; non-root through `PUID` / `PGID`.
- Volumes `/config`, `/data`, `/media` (read), `/output` (write); a `HEALTHCHECK` on
  `/api/health`.
- `docker/compose.example.yml` for Intel/AMD (`/dev/dri`) and NVIDIA
  (`deploy.resources.reservations.devices`), with a commented override (`REFRAME_FFMPEG`).
- Web mode off loopback refuses `auth: none` and needs an output folder: the image sets the
  roots and an auth mode, and the docs show `reframe-server --set-password` in the container.
- Bare metal: `uv tool install 'reframe[cli]' --with reframe-server
  --with-executables-from reframe-server` and a systemd user unit; reverse-proxy notes
  (WebSocket upgrade headers, body size, timeouts).
- **No GPU in D's runs**: D builds and runs the image without `/dev/dri` (a software encode of
  a fixture). The lead runs the VAAPI check in wave 4, in a slot the owner gives.
- Docker here has no buildx: the image builds with the classic builder.
- Fixtures and temporary folders only, never the owner's media, config or data. D removes
  every container, image, volume and network it made, and lists them in the report.

## For C-17 (recorded, not built)

- Read `server.json` through `reframe.models.ServerEndpoint`; check `instance` and
  `api_version` against `GET /api/health` (0042 item 3).
- Start an owner with `--owner-only --idle-exit 30`; exit 75 means another owner won.
- Open `WS /api/events`, read `client_id` from `hello`, add jobs with `attach`, send
  `detach` for `--detach`.
- 0042 Verification checks 1 to 8 are C-17's.

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


## Every agent prompt on this branch also includes

The two sections above are copied word for word from [m3-breakdown.md](m3-breakdown.md). On
this branch:

- Setup: the worktree starts at `main`. Run `git merge --ff-only server-complete` (it holds
  `m3-api-spike` already), then `uv sync`. B and D also run `npm ci` in `frontend/`
  (`scripts/gen-api.sh` needs it).
- The owned and forbidden files, the contracts and the "Done when" lines of the task, word for
  word, and its decision number.
- Any manual run uses temporary `REFRAME_CONFIG_DIR`, `REFRAME_DATA_DIR` and
  `REFRAME_CACHE_DIR`. Nothing reads or writes the owner's `queue.lock`, `server.json`,
  settings, queue or cache.
- The lead's "Displays" section, word for word.
- A mutation check per test function, and coverage with `--cov-branch`.
- The report with the real output of each command; pytest in the foreground; heavy runs with
  `nice -n 19`; the `code-comments` skill.
- Commits: `git -c user.name=PeterKelemen2 -c user.email=peter.kelemen456@gmail.com commit …`,
  ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- No `sudo`. Real tool behaviour (Docker, uvicorn, FFmpeg) is checked on the real tools.

## Progress

| Date | What |
|------|------|
| 2026-10-28 | **Wave 0.** Preflight on `main` 6e8ba14: a clean tree; the checks green on that tree (ruff, format, mypy ×2, `gen-api.sh --check`, the frontend commands, cargo, core 6385 passed, server 481, testing 202); `docker info` 29.9.2 without sudo (no buildx: the classic builder only); `/dev/dri/renderD128` (group `render`, 987). Decision 0055, this breakdown, then the contract commit |
| 2026-10-28 | **Contract commit** 3b1da22: `QueueService.owns_store` and `busy` (tests in `tests/queue/test_owner.py`, `test_queue.py`, `test_job_keys.py`, including a restored job whose keys are still being read), `ServerEndpoint` (test and schema snapshot), the stubs and their call sites, the 06 "Not exposed" row. The lead's 6 mutations all caught. Wave 1 started: A and B (`xhigh`), C (`high`) |
| 2026-10-28 | **Merged C** (8e2efbc; d93c570, 6c1e2bc). S-4: `static.install` replaces the router's `default` handler, so every API route wins and the middleware applies; `assets/` immutable, the rest and the fallback `no-cache`; `/api`, a missing `/assets/` file and other methods keep the problem 404; per-request resolve-and-jail. No implicit default `static_dir` (0058; proposals for the lead: `--static-dir`, the build in the wheel, refuse a folder without `index.html`, all left open). 22 tests; the agent's 16 mutations caught. The lead's 3: a folder counts as a file and the fallback cached for good were caught; **the folder not resolved survived** (no test of a linked `static_dir`): sent back, fixed in 6c1e2bc with a test that swaps the link. Checks on the merge: ruff, format, mypy ×2, `gen-api.sh --check`, 102 targeted tests |
| 2026-10-28 | **Merged A** (11f2735; 34c0f22). S-7 owner: `owner.start` opens the queue; `publish` through the core's `JsonDocumentFile` (mkstemp 0600, atomic, never raises); `withdraw` only for this run's `instance`; `idle.watch` polls at most every 0.25 s. Clients connect to `127.0.0.1` and the file's port (0056). 10 tests (4 with the real process); the agent's 20 mutations caught; the lead's 3 (no queue opened at start-up, `--owner-only` refusing the owner, the file naming another port) caught. **A found the contract wrong**: uvicorn 0.54.0 calls `sys.exit(3)` when the lifespan's start-up or the bind fails (`uvicorn/server.py` lines 118 and 192), so `serve()` never returned `app.state.exit_code`; the lead's fix 5f417ee catches it in the server's task, with a new test (a taken port exits 1; it exited 3 before) and the owner-only test no longer `xfail` (exits 75). `testdata/README.md`: the S-4 and S-7 sections both kept (merge conflict) |
| 2026-10-28 | **Merged B** (c9a07d3; d63fb5a; follow-up 82bbefb merged in the next commit). S-7 attachments: `Hello.client_id` (random per connection, registered before the hello); `POST /api/queue` looks up the connection's `Attachment` once, before any await, and attaches each job right after its add, so a client that goes away during the add still has the job cancelled; a `detach` message (also for later jobs); a gone client's jobs are cancelled together (`gather`), a server stop (uvicorn's 1012, `EventHub.close()`) cancels nothing; `ClientMessage` (`AuthMessage | DetachMessage`) in the OpenAPI components and `schema.d.ts`. The old mocked `test_queue.py` attach test is replaced by real-connection tests (the lead agreed). 11 tests in `test_attach.py`, 1 new in `test_events.py`; the agent's 20 mutations caught. The lead's 3: a clean close (1000) as a server stop and only the first job cancelled were caught; **any client message detaching survived**: sent back, fixed in 82bbefb with a test of a stray message. Known edge (0057): a job that ended and is then retried stays attached. Merge conflicts: the S-7 row (A's text plus B's "Attachments:" block) and `testdata/README.md` (all three sections kept). Checks on the merge: ruff, format, mypy ×2, `gen-api.sh --check`, the frontend commands, server + testing `726 passed, 1 skipped`. The lead updated 06 §S-3 (hello fields), §S-5 (`ClientMessage`) and the S-2 row (7ad5297) |
| 2026-10-28 | **Merged D** (6a85a6f, 816cdca). S-6: a four-stage image (frontend; Debian 13 + uv-managed CPython 3.14.8; tools with the pinned FFmpeg and its SHA-256; the venv) on a Debian 13 runtime with exact-version `mesa-va-drivers`, `intel-media-va-driver-non-free`, `libmfx-gen1.2`, `mkvtoolnix`, `mediainfo`, `tini`; base images pinned by digest; classic-builder syntax only; `tini -e 143` and an entrypoint that drops to `PUID:PGID` with the `/dev/dri` groups (`setpriv --no-new-privs`); host `0.0.0.0`, port 8765, `auth: password`, the roots and `REFRAME_STATIC_DIR`; no `VOLUME` (mount points only); compose with `reframe` (`/dev/dri`) and `reframe-nvidia` (profile); `docs/deployment.md` (Docker, `--set-password`, the override, bare metal from checkout paths with a systemd user unit, nginx and Caddy). Checked by D without a GPU: build in 74 s, 1.24 GB; `docker compose up` healthy; login; a libx265 encode of `multitrack` into `/output`; stop during an encode (0.41 s, `.part` and `server.json` removed, the job `interrupted`); the override; nginx with `REFRAME_ALLOWED_HOSTS`. The lead's Docker check: images, containers, volumes and networks equal the snapshot from before phase 2; no build cache. Tests: `test_deploy.py` (2); the lead's 3 mutations: non-JSON roots and the output root moved were caught, **a loopback host survived**: fixed in 816cdca. Server + testing on the merge: `729 passed, 1 skipped`. The "Done when" (VAAPI in Docker) waits for the lead's GPU run |
| 2026-10-28 | **Wave 3: two reviews** (fresh agents, `xhigh`, at 401b89b). R1 (S-7 and the contract): no blocker or major; minors: `--owner-only` exited 75 also for an unusable lock, close code 1001 in 0056 is really 1012, the exit window, a validation error echoing the token, `REFRAME_TOKEN` in `server.json`, two test gaps. R2 (S-4, S-6): **blocker** (Windows) `static.py` resolved a UNC, drive or device path before its containment check; **major** the reverse-proxy notes and compose ports were wrong for Docker; minors (a `static_dir` holding the data folder served `server.json`; `test_deploy.py` gaps; host folders made as root; `cp -r`; `PUID` compared as text) and nits. **The lead re-checked both before any fix**: the join with `PureWindowsPath` and `ntpath.realpath` → `_getfinalpathname` (3.14.8 lines 674, 709); the image built here (classic builder, 85 s) with `-p 127.0.0.1::8765`: five wrong logins then the owner's right one `429 auth.rate_limited`, every client logged as `172.17.0.1`; with `FORWARDED_ALLOW_IPS=172.16.0.0/12` twelve spoofed wrong logins never 429 and a `Secure` cookie over plain HTTP. Removed again; Docker state equal to the snapshot (a multi-ID `docker rmi` fails here: one at a time) |
| 2026-10-28 | **Wave 3 fixes merged.** A (944ad22; 1445b74): `QueueService.store_busy`, exit 1 for an unusable lock, `hide_input_in_errors`, the idle-exit stop test, 0056 follow-up (1012, the exit window, `REFRAME_TOKEN` kept); the lead's 3 mutations caught (one re-run alone: a same-size mutation restored within a second left a stale `.pyc`). The lead's 4cf2b39: `serve()` no longer loses a cancel of itself while it waits for the idle watch (A's find; test failed before with `result=0`). Fix X (7cdd446; 1a737f7, 7036c0d, 517682a): the Windows path rule before any file-system call; a `static_dir` without `index.html` or holding the config, data or cache folder, the endpoint file, a media or an output root exits 2; the lead's 3 mutations caught. Fix Y (9ecc7f6, 58cdac9; a83aacc, 2a67146): the Docker proxy set-ups proved with real containers, the entrypoint's numeric `PUID`, `test_deploy.py` 8 tests; the lead's mutations: `--no-new-privs` removed survived (fixed in 2a67146), the root group added survived (accepted: needs a fake `/dev/dri`). Docker state equal to the snapshot. Server + testing on the merges: `749 passed, 1 skipped`. Decision 0060 |
| 2026-10-28 | **Wave 4, the lead's final checks** on 58cdac9. Full suite in chunks (foreground, nice 19): core `1947 passed, 1 skipped, 25 deselected` + `4446 passed, 1 deselected`; server + testing `749 passed, 1 skipped`; frontend lint, fmt, typecheck, 6 tests; ruff, format, mypy ×2, `gen-api.sh --check`. **Real server demo** (real `reframe-server`, real FFmpeg, temporary folders): `server.json` 0600 with the owner's pid, instance, port and api_version, health's instance equal; a second `--owner-only` exits 75 and leaves the file; a client that attached a running job and started only it, killed with SIGKILL: the job `cancelled`, its `.part` removed, the UI's waiting job still `waiting`; `attach` with that client's id 409 `queue.attach_unknown_client`, no job added; a detached client's job stays `waiting`; idle exit 0 after 2.6 s, the file removed; password mode: 401 without a token, 200 with the file's token, the jobs restored; SIGINT 130 and the file removed; a file left by `kill -9` replaced by the next owner; the token in no log line, no "never retrieved". (The first run of the demo script crashed on the lead's own bug — a job's plan read before it existed — and left a client and a server; both were killed by pid and the folder removed; the script then waited for the plan and killed what it started.) **Frozen sidecar** rebuilt (25 s, 83 MB, 1373 files), `test_frozen_sidecar.py` 3 passed, cold start to the ready line warm 0.747 / 0.756 s, evicted 0.832 / 0.854 s (median / worst, 10 runs, load 1.2–1.7). **GPU check** in the owner's slot: the "Done when" of S-6 met (0059, "The lead's GPU check"); the first run's job had x265 fields left and was refused by validation, the second cleared them. Docker state equal to the snapshot |
