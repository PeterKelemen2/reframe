# 06 — Web App (FastAPI + Vue 3)

The web app has two parts:

- **`reframe-server`**: a FastAPI package that exposes the core facade over HTTP and a
  WebSocket.
- **`frontend/`**: a Vue 3 single-page app. The desktop app ([07](07-desktop-app.md)) uses
  **the same frontend**, so every frontend step here also delivers the desktop UI.

---

# Part A — Server (`reframe-server`)

## Shape

```
packages/reframe-server/src/reframe_server/
├── __init__.py
├── app.py              # create_app(config) -> FastAPI ; lifespan creates/closes the Reframe facade
├── config.py           # ServerConfig (pydantic-settings, env prefix REFRAME_)
├── security.py         # auth modes, token/cookie checks, path jail
├── errors.py           # ValidationIssue / problem+json mapping
├── events.py           # WebSocket hub
├── routers/            # system, fs, sources, definitions, languages, presets, jobs, batch, preview, queue, settings
├── static.py           # serves the built frontend (web mode)
└── __main__.py         # `python -m reframe_server` / `reframe-server` entry point (uvicorn, 1 worker)
```

The server holds no editing state ([02 §State model](02-architecture.md#state-model)). Its
routers are thin. Each handler calls one facade method and maps the result.

## S-0 Package skeleton

- [ ] `create_app(config: ServerConfig) -> FastAPI` with a lifespan that runs
      `await Reframe.create(...)` and `await reframe.close()`.
- [ ] `ServerConfig`: `host` (default `127.0.0.1`), `port` (0 = random free port), `mode`
      (`web` | `desktop`), `auth` (`none` | `token` | `password`), `token`, `media_roots`,
      `output_roots`, `static_dir`, `cors_origins`, `config_dir`, `data_dir`, and for
      [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md)
      `endpoint_file` (the path of `server.json`; on by default in every mode),
      `idle_exit` (seconds; off by default) and `owner_only`; and `allowed_hosts` (S-1).
- [ ] Entry point: start uvicorn with **one worker**. In desktop mode, print one JSON line to
      stdout when ready: `{"event":"ready","port":53817}`. The token is `REFRAME_TOKEN` when it
      is set (the desktop shell sets it), else a random one per run; `server.json` holds it
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 4).

- [ ] Logs go to stderr (stdout holds only the ready line). SIGINT ends with exit code 130,
      an invalid option or configuration with 2. `GET /api/health` needs no credentials
      ([decision 0045](../decisions/0045-m3-server-order-and-contract.md)).

Done when: `uv run reframe-server` starts and `GET /api/health` returns version info.

## S-1 Security

- [ ] **Auth modes**:
  - `token` (always used in desktop mode): `Authorization: Bearer <token>`. For `<img>` and
    `<video>` URLs, a short-lived signed query parameter (`?sig=`) is used, because those
    elements cannot send headers. The WebSocket gets the token in its first message.
  - `password` (web, single user): login form → HTTP-only, SameSite=Strict session cookie.
    The password hash (stdlib scrypt, [decision 0046](../decisions/0046-s1-login-sessions-jail-and-request-checks.md))
    is **not** in the settings: it lives in
    `<config dir>/auth.json` (mode `0600`), written by `reframe-server --set-password` and
    `PUT /api/auth/password` (which needs the current password). `GET/PUT /api/settings`
    never read or write it ([decision 0043](../decisions/0043-plan-review-before-m3.md)
    item 3). Sessions live in memory (30 days; a restart ends them); wrong passwords are
    limited to 5 per client (IPv4 address or IPv6 /64) per minute, then 429.
  - `none`: allowed only when bound to `127.0.0.1`. A startup warning says so.
  - **Local token** ([decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md)
    item 2): the random token in `<data>/server.json` (mode `0600`) is accepted as
    `Authorization: Bearer` in every mode, next to the mode's own login. A CLI on the same
    machine (also through `docker exec`) uses it.
  - Routes (no credentials needed but where named): `GET /api/auth/status` (`{mode,
    authenticated}`: the frontend's choice between a login form and the token),
    `POST /api/auth/login`, `POST /api/auth/logout`, `PUT /api/auth/password` (credentials
    and the current password) ([0046](../decisions/0046-s1-login-sessions-jail-and-request-checks.md)).
  - Credentials are checked **before a request body is read** (FastAPI reads and parses the
    body before its dependencies run): a body without credentials is a 401, except a login,
    whose body may have at most 64 KiB (else 413) (0046 "Follow-up (review)").
- [ ] **Path jail**: every path from the client is resolved (`Path.resolve(strict=False)`, which
      follows symlinks) and must be inside `media_roots` (for reading) or `output_roots` (for
      writing). Web mode enforces this. Desktop mode allows the whole filesystem of the
      current user. In every mode a path that is not absolute or holds a NUL is a 400. A
      job's paths are found by walking the model: `output.*` is written, the rest is read,
      and an in-place edit also writes its source
      ([0046](../decisions/0046-s1-login-sessions-jail-and-request-checks.md)). Web mode also
      refuses a job whose free filter text (`filters.*.custom`) names a filter outside an
      allow-list, has a `;` or a link label, cannot be read safely, in a `custom` preset
      would start another filter, or has an option name that starts with `/` (the ffmpeg
      tool then reads the value from a file) (403 `filter.not_allowed`; 0046 "Follow-up" and
      "Follow-up (review)").
- [ ] **Host check** (against DNS rebinding), in every mode: a request or WebSocket upgrade
      whose `Host` is not a loopback name (`127.0.0.1`, `localhost`, `[::1]`, any port) or
      in `allowed_hosts` is refused. `allowed_hosts` defaults to the loopback names, plus the
      bound address and the machine's host name when the server binds another address (on a
      wildcard bind, `0.0.0.0` or `::`, every IP address); a reverse proxy's name is added by
      hand, and a list that is set replaces these defaults. A WebSocket `Origin` must be the
      server's own or a Tauri origin ([decision 0043](../decisions/0043-plan-review-before-m3.md)
      item 3); so must the `Origin` of a `POST`, `PUT`, `PATCH` or `DELETE` that has one
      (`cors_origins` and pages of `allowed_hosts` names count too;
      [0046](../decisions/0046-s1-login-sessions-jail-and-request-checks.md)).
- [ ] CORS: off in web mode (same origin) unless `cors_origins` names origins. In desktop mode,
      allow the Tauri origins (`tauri://localhost`, `http://tauri.localhost`) and
      `cors_origins`.
- [ ] Security headers on every response, a 500 included (CSP, `X-Content-Type-Options`,
      frame-ancestors none). The docs page `/api/docs` gets a CSP that allows its CDN script and style.

Done when: tests prove that `../` traversal, symlink escape, absolute paths outside the roots,
a missing or wrong token and a foreign `Host` are all rejected, that `GET /api/settings`
holds no secret, and that a settings patch cannot change the password.

## S-2 REST API

Errors use `application/problem+json`. Long operations return `202 {task_id}`. Their
progress arrives as events.

Responses and WebSocket events are written with `reframe.models.json_text`, and request
bodies are read with `json.loads` + `model_validate`: a path with a byte that is not UTF-8 is
a `\udcXX` escape, which `model_dump_json()` cannot write and `model_validate_json` refuses
([0044](../decisions/0044-code-review-follow-ups.md)).

| Area | Method & path | Purpose |
|------|---------------|---------|
| System | `GET /api/health` | Version, `api_version`, `instance` (random id of this run), uptime |
| | `GET /api/system` | Tool statuses, versions, platform, mode |
| | `GET /api/system/encoders` · `POST /api/system/encoders/rescan` → 202 | Capability statuses, re-detection (a task: hardware test encodes take seconds; [0049](../decisions/0049-s2-system-fs-settings-sources-preview.md)) |
| | `POST /api/system/shutdown` | Graceful shutdown (desktop mode only, else 403) |
| | `POST /api/system/tools/rescan` · `POST /api/system/tools/fetch` `{build?}` → 202 | Tool discovery again; download the pinned FFmpeg (`tools.fetch`). `GET /api/system` also returns the start-up problems of the settings and preset stores |
| Tasks | `GET /api/tasks?kind=` · `GET /api/tasks/{id}` · `POST /api/tasks/{id}/cancel` | Running and finished tasks (optionally of one kind), one task's state and result, cancel (`{cancelled}`). An unknown id is 404 `tasks.unknown`. The server's config, data and cache folders show as `<config>`, `<data>`, `<cache>` ([0048](../decisions/0048-queue-power-and-task-routes.md)) |
| Files (web) | `GET /api/fs/roots` · `GET /api/fs/list?path=` | Server-side file browser (media files and folders only). Web mode: below the media and the output roots (the output folder picker); desktop: the whole file system |
| Sources | `POST /api/sources` `{paths, recursive?}` → 202 | Probe files/folders (task; its result names each `source_id` and each error). Every file found in a folder passes the read jail too: a link out of the roots is an error, never probed ([0049](../decisions/0049-s2-system-fs-settings-sources-preview.md#follow-up-review-2026-10-22)) |
| | `GET /api/sources` · `GET /api/sources/{id}` · `DELETE /api/sources/{id}` | Probed sources |
| | `POST /api/sources/{id}/streams/{index}/bitrate-scan` → 202 | Measure the bitrate |
| | `POST /api/sources/{id}/subtitle-scan` → 202 | Event counts, forced flags |
| | `POST /api/sources/{id}/streams/{index}/loudness` `{start?, duration?}` → 202 | EBU R128 loudness of one track |
| Preview | `POST /api/preview/frames` `{source_id, count \| timestamps}` | Frame list (timestamps + signed URLs; the request waits for the frames, a client that goes away cancels them) |
| | `GET /api/preview/frames/{key}.png` | Frame image (cached, ETag) |
| | `POST /api/preview/render` `{job, timestamp}` | Output frame with filters → URL |
| | `POST /api/preview/cropdetect` `{source_id}` → 202 | Crop detection per sample |
| | `POST /api/preview/clip` `{job, start, seconds}` → 202 | Encoded preview clip |
| | `GET /api/preview/clips/{id}/link` | A signed clip URL for `<video>` (one hour) |
| | `GET /api/preview/clips/{id}` | Clip file (HTTP Range: one range → 206, outside the file → 416) |
| | `GET /api/preview/cache` · `DELETE /api/preview/cache` | Size of the frame and clip cache; clear it |
| Definitions | `GET /api/definitions` | `{definitions, naming_variables}`: encoders, option schemas, filters, containers, the naming variables (cached, ETag; `304` on `If-None-Match`) |
| | `GET /api/languages` | Language list for the picker (cached, ETag) |
| | `GET /api/definitions/encoders/{id}/options?q=` | Option search of the advanced panel (`search_options`, ranked); an unknown encoder is `404` |
| Jobs | `POST /api/jobs/draft` `{source_id, preset_id}` | `JobSettings` built from a preset. Web mode: an output outside the output roots adds `output.folder_required` |
| | `POST /api/jobs/validate` `{job}` | `ValidationIssue[]`. Web mode: an output outside the output roots is the error `output.folder_required` (fixes: a fixed output folder in the settings; with one output root, the job's output moved into it), not a 403 ([0050](../decisions/0050-s2-jobs-batch-presets-routes.md#follow-up-2026-10-22-web-mode-output-folder-and-override-jail)). An in-place edit of a source the server may not write is the error `inplace.not_allowed` (fix: write a new file in the first output root), not a 403 ([0050](../decisions/0050-s2-jobs-batch-presets-routes.md#follow-up-review-2026-10-22)) |
| | `POST /api/jobs/plan` `{job}` | `EncodePlan` (command preview, job type); a job with errors is `422 jobs.invalid` with the issues ([0050](../decisions/0050-s2-jobs-batch-presets-routes.md)) |
| | `POST /api/jobs/geometry` `{job}` | Pipeline header values: `{source, geometry}` (`geometry` `null` for a copied video) |
| | `POST /api/jobs/explain` `{source_id, template?, container?}` | Why each track was selected (`TrackDecision` with reasons) |
| | `POST /api/jobs/draft-remux` `{source_id, preset_id?, edit_in_place}` | Metadata-only job (`metadata_edit` or remux); `output.folder_required` as `draft`; an in-place edit in web mode gets `inplace.not_allowed` instead (as `validate`) |
| | `POST /api/jobs/dry-run` `{job}` | One-frame test of custom encoder parameters → `ValidationIssue[]`; an output outside the output roots or a refused in-place edit is `422 jobs.invalid` (as `plan`) |
| | `POST /api/jobs/hdr-metadata` `{job}` | **Copy HDR metadata** → JSON patch for the job |
| Batch | `POST /api/batch/group` `{source_ids, level}` | Groups |
| | `POST /api/batch/derive` `{job, source_id, sections, base?}` | `JobTemplate` from a single-file job, merged into `base` (the group's template) |
| | `POST /api/batch/resolve` `{template, source_ids, overrides}` | Resolution matrix + per-file jobs + issues. `overrides` by `source_id`; the job each override makes passes the path jail inside the batch service, before it is named or validated. A row whose output is outside the output roots gets `output.folder_required` |
| | `POST /api/batch/resolve-run` `{template, source_ids, level, overrides}` | A whole run (`resolve_batch`): `{grouping, resolutions}`, the name checks over every group, earlier outputs left out; overrides and rows as `resolve` |
| | `POST /api/batch/save-preset` `{template, name, category?, description?}` | Save a group template as a preset |
| Presets | `GET/POST /api/presets` · `GET/PUT/DELETE /api/presets/{id}` | CRUD. `GET` → `{presets, default_id}`; `POST` → `201`; `PUT` takes the whole preset (create or replace, a rename too); a refused change is a problem with the issue (web mode: the store's failures name no server folder) |
| | `POST /api/presets/{id}/default` · `POST /api/presets/import?on_conflict=` · `GET /api/presets/export?ids=` | Import: the export file as the body (at most 4 MiB), a report with the issues. Export: `{document, issues}` |
| | `POST /api/presets/diff` `{template, preset_id}` | Changes for the "modified" marker |
| | `POST /api/presets/defaults/preview` `{audio_defaults, subtitle_defaults, source_ids, container?}` | Track decisions with reasons, for the live preview: one `TrackDraft` per source |
| Naming | `POST /api/naming/preview` `{naming?, source_ids, job?, container?}` | One `NameResult` per source: name source + reason, parsed fields with positions, rendered output paths, issues (web mode: `output.folder_required` with the settings fix). The variable list comes with `GET /api/definitions` |
| Queue | `GET /api/queue` · `POST /api/queue` `{jobs, position?, attach?}` | Snapshot `{jobs}`, add (server validates again: a job with errors is added `failed`). Every job passes the path jail before any is added; a job without `output.path` is refused (422 `output.no_path`). `attach`: a client id; the jobs follow that client's event connection (S-7); refused (409) unless it is open. Outside a job's `settings`, the server's folders show as in the task answers (`log_path`: `<data>/…`) ([0048](../decisions/0048-queue-power-and-task-routes.md)) |
| | `POST /api/queue/{id}/{pause\|resume\|cancel\|retry\|duplicate}` · `DELETE /api/queue/{id}` | Per-job actions |
| | `POST /api/queue/{start\|stop\|pause\|resume\|cancel}` · `PUT /api/queue/order` | Global actions (pause, resume and cancel act on every job). `start` takes an optional `job_ids`: only those jobs start |
| | `GET /api/queue/{id}/log?from=` | Log (incremental, by byte offset: `{text, next, more}`) |
| | `PUT /api/queue/when-done` | When-done action. A running countdown for another action is cancelled |
| Power | `GET /api/power` · `POST /api/power/cancel` | The pending when-done countdown (`{pending}`); cancel it (`{cancelled}`). Only the queue starts one |
| Settings | `GET/PUT /api/settings` | App settings |

- [ ] Stable `operationId`s (`sources_probe`, `jobs_validate`, …): `<tag>_<handler name>`. The
      generated client uses them as function names.
- [ ] Errors: `{type, title, status, detail, code, issues, errors}`; `code` is a stable dotted
      identifier; a request validation error names the field, never its value. A `source_id`
      is a hash of the absolute path; the server keeps the probed sources in memory, so the
      client probes again after a restart. In web mode a settings patch cannot name a
      program (`/tools/…`; removing one is allowed), `encoders.vaapi_device` may only be a
      render node (`/dev/dri/renderD<n>`) or empty, and a folder in it must be below an
      output root; the checks run under the settings store's lock ([decision 0045](../decisions/0045-m3-server-order-and-contract.md),
      [0049](../decisions/0049-s2-system-fs-settings-sources-preview.md)).

Done when: an httpx `AsyncClient` test suite covers every route against a facade that runs on
fixture media and a fake FFmpeg, and every public method of the facade
([decision 0030](../decisions/0030-core-complete-contract.md)'s list, `Reframe.batch`,
`Reframe.power`, `Reframe.tasks`) is reached by a route or listed here as not exposed, with
the reason ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 2).

### Not exposed

Every other public member of the facade is reached by a route.
`tests/test_facade_coverage.py` reads which members each route reaches from the router code,
and fails on a public member that no route reaches and this table does not list, and on a
row whose member a route reaches or that no longer exists
([decision 0051](../decisions/0051-openapi-types-and-route-coverage.md)).

| Member | Why no route reaches it |
|--------|-------------------------|
| `Reframe.create`, `Reframe.close`, `queue.close`, `power.close`, `tasks.close`, `tools.close`, `capabilities.close`, `sources.close`, `events.close` | The app's lifespan creates and closes the facade; a desktop client stops the server with `POST /api/system/shutdown` |
| `tools.start`, `capabilities.start`, `tools.current`, `tools.discovering`, `capabilities.detecting`, `power.closed`, `events.closed` | Lifecycle state. `GET /api/system` waits for a running discovery; `GET /api/system/encoders` and the `tools.changed` / `capabilities.changed` events show the rest |
| `settings.path` | A server folder: a client cannot use it, and an answer must not show it (the queue and task routes read `Reframe.config_dir`, `data_dir` and `cache_dir` only to write them as `<config>`, `<data>`, `<cache>`) |
| `Reframe.settings_snapshot` | The same settings as `settings.get` (`GET /api/settings`) |
| `batch.definitions`, `capabilities.definitions` | The same definitions as `jobs.definitions` (`GET /api/definitions`) |
| `jobs.detection_wait` | A setting of the service: how long validation waits for encoder detection |
| `tools.versions` | `GET /api/system` gives each tool's version in its `ToolSet` |
| `capabilities.wait` | `GET /api/system/encoders` never waits; `capabilities.changed` events follow a detection |
| `capabilities.closest_available` | Validation uses it inside the core |
| `presets.find` | The routes take ids; `jobs/draft`, `explain` and the batch routes accept a name or an id through the facade's own lookup |
| `sources.probe_folder` | `POST /api/sources` expands folders itself (`jobs.media_files`): one task per request, without partial outputs ([0049](../decisions/0049-s2-system-fs-settings-sources-preview.md) item 5) |
| `sources.store`, `sources.update` | The scans store what they measured themselves |
| `sources.cache`, `sources.media`, `presets.store`, `tasks.events` | The objects the services are wired with (probe cache, the media task context, the preset file store, the event bus); clients reach them through the service methods and `WS /api/events` |
| `events.publish`, `events.subscriber_count` | Only the core publishes events; a client receives them on `WS /api/events` |
| `queue.wait` | A client follows the `job.state` events or reads `GET /api/queue`; a request held open until jobs end would hold a connection for hours |
| `power.schedule` | Only the queue starts a countdown: no client may shut down or suspend the server's machine on demand |
| `power.countdown`, `power.executor` | The countdown's length and end are in `pending.seconds_left` and `pending.deadline`; the executor is the operating system's mechanism |
| `tasks.limit`, `tasks.set_limit` | The concurrency per task kind is internal; no setting changes it |
| `batch.merge` | `POST /api/batch/derive` with `base` covers *Apply to group*; a client copies sections itself |
| `presets.rename` | `PUT /api/presets/{id}` with the new name |
| `presets.duplicate` | `GET /api/presets/{id}`, then `POST /api/presets` |

## S-3 Event WebSocket

- [ ] `WS /api/events`. The client authenticates in its first message
      (`{"type": "auth", "token": …}`; in password mode the session cookie may stand in for the
      token). A wrong first message, or none within 5 s, closes the connection with 4401. The
      server answers `{"type": "hello", "instance", "heartbeat"}` and then sends each event as
      JSON: `{"type": "event", "seq": n, "event": {…}}`
      ([decision 0047](../decisions/0047-event-websocket.md)).
- [ ] **Coalescing**: `job.progress` and `task.progress` are coalesced per id (only the latest
      is kept, max 4 per second). `job.log` lines are batched every 250 ms. What is held back
      for a job or task goes out before the event that ends it.
- [ ] Heartbeat every 15 s: a `{"type": "heartbeat"}` message (a browser cannot see WebSocket
      pings). Each event has a sequence number (from 1 on each connection, no gaps). After a
      reconnect, or a `resync` event, the client calls the `GET` snapshots (`/api/queue`,
      `/api/system/encoders`) to resync.
- [ ] A client that cannot keep up gets a `resync` and stays connected. Shutdown closes every
      connection with 1001 within about 1 s, also one whose client does not read. The server
      process stops (SIGINT, `POST /api/system/shutdown`) within uvicorn's graceful-shutdown
      limit of 2 s plus the lifespan's close, also while such a client is connected
      ([decision 0047](../decisions/0047-event-websocket.md), follow-up).

Done when: a test with a slow consumer shows bounded memory and latest-value delivery.

## S-4 Static frontend and SPA fallback

- [ ] Web mode: serve `frontend/dist` with immutable cache headers for hashed assets, and
      `index.html` for unknown non-API paths.
- [ ] Desktop mode: no static files (Tauri bundles the frontend).

## S-5 OpenAPI → TypeScript

- [x] `scripts/gen-api.sh` (`npm run gen:api` in `frontend/`): export `openapi.json` from
      `create_app()` without starting a server (`scripts/export-openapi.py`; the shell's
      `REFRAME_*` variables are ignored), then run `openapi-typescript` (pinned in
      `frontend/package.json`) → `frontend/src/api/schema.d.ts`, committed and left out of
      `oxfmt`. The same input gives the same bytes.
- [x] The document's components also hold the `WS /api/events` messages: `AuthMessage` (the
      client's first message) and `ServerMessage` (`Hello | EventMessage | Heartbeat`, by
      `type`), with every core event model. OpenAPI has no WebSocket operation, so there is no
      path for it ([decision 0051](../decisions/0051-openapi-types-and-route-coverage.md)).
- [x] CI check: `scripts/gen-api.sh --check` regenerates into a temporary folder and fails with
      the diff (`Q-2.3`, the `api-contract` job on Ubuntu).

## S-6 Deployment

- [ ] **Docker image** (multi-stage):
  1. `node` stage builds `frontend/dist`.
  2. `tools` stage downloads the pinned FFmpeg from `tools/ffmpeg.toml` and checks its
     SHA-256 ([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)).
  3. Runtime stage: Debian slim + uv-installed `reframe-server`, the bundled FFmpeg in
     `/opt/reframe/tools/ffmpeg/`, `mkvtoolnix`, `mediainfo`, and the GPU user-space drivers
     that FFmpeg loads at runtime (Intel media driver, Mesa VA drivers, oneVPL GPU runtime; the
     Dockerfile pins the exact packages). Runs as a non-root user (`PUID`/`PGID` env).
  4. Volumes: `/config`, `/data` (queue DB, logs, cache), `/media` (read), `/output` (write).
  5. `HEALTHCHECK` on `/api/health`.
- [ ] **Override in Docker**: mount your own build and set `REFRAME_FFMPEG` /
      `REFRAME_FFPROBE`, for example `-v /opt/my-ffmpeg:/opt/custom-ffmpeg:ro -e
      REFRAME_FFMPEG=/opt/custom-ffmpeg/bin/ffmpeg`.
- [ ] `docker/compose.example.yml` with variants for Intel/AMD (`/dev/dri`) and NVIDIA
      (`deploy.resources.reservations.devices`), and a commented-out override example.
- [ ] Bare metal: `uv tool install 'reframe[cli]' --with reframe-server
      --with-executables-from reframe-server` (one environment, so `reframe` and
      `reframe-server` have the same version;
      [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 11),
      plus a systemd user unit example. The wheels
      do not contain FFmpeg. `reframe tools fetch` downloads the pinned build from the manifest
      (checksum verified) into the data dir, where it counts as the bundled build. On Windows:
      run from a terminal. A Windows service wrapper comes later.
- [ ] Reverse-proxy notes (WebSocket upgrade headers, body size, timeouts).

Done when: `docker compose up` on a Linux host with a GPU (the owner's: AMD) shows its VAAPI
encoders as available and encodes a fixture file. Intel QSV and NVIDIA NVENC in Docker are
listed as not verified until such a host is available
([decision 0043](../decisions/0043-plan-review-before-m3.md) item 7).

## S-7 Local owner mode

Implements [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md). Needs
S-2 and S-3. Milestone M3b, with C-17 ([05](05-core.md#c-17-remote-queue-and-queue-commands)).

- [ ] **Endpoint file** (`endpoint_file`): when the server holds `queue.lock` (it opens the
      queue at start-up) and listens, it writes `server.json` (atomic, mode `0600` on POSIX)
      with `pid`, `instance`, `port`, `token`, `version`, `api_version`, `started_at`, and
      removes it at close. A server that cannot take the lock writes nothing and keeps 0027's
      private queue with `queue.store_busy`; with `owner_only` it exits with code 75.
- [ ] **Idle exit** (`idle_exit`): exit after N seconds with no running job, no job that a
      `start` still targets, no event connection and no pending when-done countdown.
- [ ] **Attachments**: after a client authenticates on `WS /api/events`, the server answers
      with a `client_id`. `POST /api/queue` with `attach: <client_id>` is refused (409)
      unless that connection is open. A connection that ends without a `detach` message
      cancels its attached jobs that have not ended, as a cancel does. Not persisted.
- [ ] `POST /api/queue/start` with `job_ids` starts only those jobs; other waiting jobs are
      neither started nor cancelled.

Done when: httpx tests show that the file is written after the server listens and removed at
close, that a stale file left by `kill -9` is replaced, that `owner_only` exits with 75 on a
busy lock, that idle exit waits for a running job, that a closed connection cancels its
attached jobs (and a `detach` does not), that `attach` with the id of a closed connection is
refused, that the local token works in `password` mode, and that `start` with `job_ids` leaves
other waiting jobs alone.

---

# Part B — Frontend (`frontend/`, shared by web and desktop)

## Stack

Vue 3.5+ · TypeScript 6 (strict) · Vite · Pinia · Vue Router · oxlint · oxfmt · PrimeVue 4 (styled mode, custom
Aura preset) · Lucide icons · VueUse · vue-i18n · `openapi-fetch` · Vitest · Playwright.

PrimeVue stays on 4 (MIT) with `@primeuix/themes` 2.x, and TypeScript stays on 6 (vue-tsc
needs it). See [decision 0003](../decisions/0003-frontend-held-back-majors.md).

## Structure

```
frontend/src/
├── api/              # schema.d.ts (generated), client.ts, events.ts (WebSocket + reconnect)
├── platform/         # Platform interface + web.ts + desktop.ts (Tauri plugins)
├── stores/           # system, sources, editor, validation, presets, queue, tasks, settings
├── views/            # WorkspaceView, QueueView, PresetsView, ActivityView, SettingsView
├── components/
│   ├── base/         # Field, Section, Card, RoleBadge, CodecLabel, LanguageChip, StatusDot, KeyValue
│   ├── editor/tabs/  # SummaryTab … TagsTab
│   ├── media/        # FrameViewer, CropMagnifier, CropCheckGrid, SplitCompare, TrackTable
│   ├── metadata/     # TrackMetadataEditor, LanguagePicker, FlagToggles, BulkEditDialog
│   ├── video/        # EncoderPicker, QualitySlider, AdvancedOptions, CommandPreview
│   ├── batch/        # GroupBanner, ApplyToGroupDialog, ResolutionMatrix, OverrideDot
│   └── queue/        # QueueTable, JobLog
├── composables/      # useValidation, useGeometry, useShortcuts, useUndo
├── i18n/
└── styles/           # tokens, theme preset
```

## Platform adapter

This is the only place where web and desktop differ:

```ts
export interface Platform {
  kind: 'web' | 'desktop'
  backend(): Promise<{ baseUrl: string; token?: string }>
  pickFiles(opts: { multiple: boolean; filters?: string[] }): Promise<string[]>   // web: server file browser dialog
  pickFolder(opts?: { title?: string }): Promise<string | null>
  pickSavePath(opts: { defaultPath: string }): Promise<string | null>
  onFilesDropped(cb: (paths: string[]) => void): () => void                     // web: no-op
  revealInFolder(path: string): Promise<void> | null                           // web: null (hidden)
  openExternal(target: string): Promise<void>
  notify(title: string, body: string): Promise<void>                           // web: Notification API
  setTaskbarProgress(value: number | null): void                               // web: document.title
}
```

The build selects the implementation with `import.meta.env.VITE_PLATFORM`. The desktop build
imports Tauri plugins only in `desktop.ts`, so the web bundle never contains them.

## Steps

### F-0 Scaffold
- [ ] Vite + Vue + TS + Pinia + Router + PrimeVue + vue-i18n + oxlint + oxfmt + vue-tsc + Vitest.
- [ ] Lint and format:
  - `.oxlintrc.json` with the `typescript`, `vue`, `import`, `unicorn` and `promise` plugins.
    Correctness rules are errors.
  - `.oxfmtrc.json`. Pin the exact oxfmt version, because it is still in beta and its output
    can change between releases.
  - oxlint does not lint `<template>` blocks. vue-tsc with `vueCompilerOptions.strictTemplates`
    checks the templates instead (unknown props, events and components; wrong types).
  - Scripts: `lint` (oxlint), `fmt` / `fmt:check` (oxfmt), `typecheck` (vue-tsc --noEmit).
- [ ] Dev proxy `/api` → `127.0.0.1:8765`. `npm run dev:web` and `npm run build:web|build:desktop`.

Done when: the build passes strict type checks, `oxlint` and `oxfmt --check` in CI. Check
oxfmt's output on a few `.vue` files with templates once before you commit to its settings.

### F-1 Design system
- [ ] Colour, spacing, radius and typography tokens. Light/dark theme plus a "system" option.
      Compact and comfortable density.
- [ ] Base components. `Field` is the key one: label, control slot, inline help (ⓘ popover),
      the validation issue for its `path`, and an override dot (batch). Every editor control
      uses `Field`.
- [ ] `RoleBadge` (solid = flag, outlined = heuristic, tooltip = evidence), `CodecLabel`
      (commercial name + raw codec in the tooltip), `LanguageChip`.
- [ ] **i18n from the first view**: every string the user sees goes through vue-i18n. A CI
      check fails on literal text in a `<template>` (oxlint does not read templates; pick a
      small script or a Vitest check here)
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 8).

Done when: a component sandbox page (dev only) shows every base component in both themes.

### F-2 API layer and events
- [ ] Typed client from `schema.d.ts`. Auth header or cookie. Problem+json → toast.
- [ ] WebSocket client: reconnect with backoff, resync snapshots, dispatch events to stores.

### F-3 App shell
- [ ] Navigation rail, workspace layout (sources | tabs | preview), status bar, keyboard
      shortcuts, theme switch, toasts, a first-run screen when FFmpeg is missing.

### F-4 Editor state
- [ ] `editor` store: an **EditorTarget** is either a single `JobSettings` or a group
      (`JobTemplate` + overrides). The tabs use one API for both.
- [ ] Undo/redo as JSON patch history (Ctrl+Z / Ctrl+Shift+Z).
- [ ] `useValidation`: debounced (250 ms) `jobs/validate`. Issues are indexed by path for `Field`.
- [ ] "Modified vs preset" uses `presets/diff`.

### F-5 Sources panel and opening files
- [ ] Web: a server file-browser dialog (roots, breadcrumbs, media filter, multi-select).
- [ ] Desktop: native dialogs and drag-and-drop through `Platform`.
- [ ] Probe progress, warnings, batch groups (collapsible), near-match markers.

### F-6 Summary tab
- [ ] The cards from [03 §Summary](03-features.md#summary). Chips and issues link to fields.

### F-7 Dimensions tab, preview panel, crop magnifier
- [ ] Pipeline header from `jobs/geometry`.
- [ ] `FrameViewer`: fit/100 %/200 %, frame strip, timestamp seek, crop overlay with drag handles.
- [ ] `CropMagnifier`: canvas-based. It loads the full-resolution PNG and draws 4 edge strips at
      2×/4×/8× with `imageSmoothingEnabled = false`, a removed-area tint, the crop lines, and a
      cursor loupe.
- [ ] `CropCheckGrid`: every sample with the overlay. A Web Worker computes the luma variance
      of the removed band and puts a warning badge on frames that lose content.

### F-8 Filters tab
- [ ] Filter list (toggle + preset + tune), help panel from the definitions, `SplitCompare`
      before/after on the current frame (`preview/render`).
- [ ] Colorspace source-colour box and the "what will happen" sentence.

### F-9 Video tab and advanced options
- [ ] `EncoderPicker` grouped by family, with status dots and reasons. The
      missing-encoder banner shows the fix buttons from the validation issue.
- [ ] `QualitySlider` with the recommended band. Rate-control switch.
- [ ] `AdvancedOptions` is generated from the option schema: categories, search, "show only
      changed", reset, placeholders for defaults, help popovers, "copy HDR metadata".
- [ ] `CommandPreview` drawer (`jobs/plan`), a light syntax highlighter, copy button.

### F-10 Audio and subtitles tabs
- [ ] `TrackTable` (source, read-only) with expandable details, role badges, and a "Measure"
      button for unknown bitrates.
- [ ] Output track editors with drag reorder, action, encoder settings, `TrackMetadataEditor`.
- [ ] `LanguagePicker`: search dialog, favourites on top, a preview of how it is written
      (`hun · hu`).
- [ ] Bulk edit for selected tracks. External subtitle import (file picker through `Platform`).
- [ ] **Defaults dialog** (audio and subtitles), opened from the tab and from the preset editor:
      selection settings, a codec-rule table (drag to reorder, the catch-all row is locked,
      expandable rows for optional settings), passthru check boxes, fallback encoder, and the
      **live preview** table (`presets/defaults/preview`, debounced). In a batch group, the preview
      covers every file.

### F-11 Chapters and tags tabs
- [ ] Chapter table with inline name edits, import/export, generate. Tag form with templates.

### F-12 Presets UI
- [ ] Preset drawer: tree by category, built-in lock, CRUD, default star, import/export,
      "modified" marker with a diff popover.

### F-13 Batch UI
- [ ] Group rows in the sources panel. **Edit group** mode with banner and representative-file
      switcher.
- [ ] `ApplyToGroupDialog` (section checkboxes). Copy/paste sections from the context menu.
- [ ] `ResolutionMatrix`: virtualised table with ✓/≈/✗ cells, a candidate picker per cell, a
      "problems only" filter, and an editable naming column.
- [ ] Override dots on `Field` with **Reset to group** and **Apply to whole group**.
- [ ] Queue-group flow with the error dialog.

### F-14 Queue and activity
- [ ] Queue table: drag reorder, live progress, per-job and global controls, edit-back,
      reveal in folder (desktop), when-done selector.
- [ ] Job log viewer (virtual scroll, follow mode, copy all). Global activity log.

### F-15 Settings view
- [ ] The sections from [03 §Settings](03-features.md#settings). The encoder table has a re-scan
      button. Tool paths have a **Test** button.

### F-16 i18n and accessibility
- [ ] Audit that every string goes through vue-i18n (English first; the rule and its check
      start in F-1). Full keyboard paths. Visible focus. WCAG AA contrast in both themes.
      Respect `prefers-reduced-motion`.

### F-17 End-to-end tests
- [ ] Playwright against `reframe-server` with fixture media and fake FFmpeg:
  1. Open a file → set an audio language and commentary flag → queue → done → re-probe shows
     the flags.
  2. Open a season folder → edit group → check the matrix → queue the group.
  3. A preset with an unavailable encoder → banner → use the fallback → queue.
  4. Manual crop → magnifier shows the crop lines → the command contains the matching
     `crop=` filter.
- [ ] Each flow comes with its screens: the Playwright set-up and flow 3 in M4, flow 1 in M6,
      flow 2 in M7, flow 4 in M8. M10 runs all four in Chromium and WebKit
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 8).

### F-18 Naming editor
- [ ] Template field with `{` autocomplete and variable chips (current values, click to insert).
- [ ] **Parsed name** panel: name source + reason, coloured spans over the original name,
      editable fields (per-file override).
- [ ] Live preview (`naming/preview`, debounced). Used in Settings → Output, the preset editor,
      the Summary Output card, and the batch matrix naming column.
