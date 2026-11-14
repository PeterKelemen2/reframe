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
- [ ] `parent_pid` (`--parent-pid`; off by default): the server watches that process and,
      when it ends, stops as `POST /api/system/shutdown` does, with a hard exit when the stop
      does not end in time. A reused pid is not taken for the parent. The desktop shell
      passes it ([07 §Sidecar lifecycle](07-desktop-app.md#sidecar-lifecycle),
      [decision 0054](../decisions/0054-d0-spike-layout-and-parent-watch.md)).
- [ ] Entry point: start uvicorn with **one worker**. In desktop mode, print one JSON line to
      stdout when ready: `{"event":"ready","port":53817}`. The token is `REFRAME_TOKEN` when it
      is set (the desktop shell sets it), else a random one per run; `server.json` holds it
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 4).

- [ ] Logs go to stderr (stdout holds only the ready line). SIGINT ends with exit code 130,
      an invalid option or configuration with 2. uvicorn waits at most 2 s for open
      connections before the lifespan closes the facade
      ([decision 0047](../decisions/0047-event-websocket.md) "Follow-up (review)"). `GET /api/health` needs no credentials
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
| Files (web) | `GET /api/fs/roots` · `GET /api/fs/list?path=&extensions=` | Server-side file browser (media files and folders only; with `extensions` (repeatable: `.srt`), the files with those extensions instead of the media files, [0065](../decisions/0065-m6-tracks-and-metadata.md#task-s6--s-2-additions)). Web mode: below the media and the output roots (the output folder picker); desktop: the whole file system |
| Subtitles | `POST /api/subtitles/inspect` `{path}` | An external subtitle file before it is added: FFmpeg's format, text or bitmap, the character encoding (byte order mark or valid UTF-8, else `null`), the event count, issues; a file a job cannot take is `422 subtitles.unsupported` ([0065](../decisions/0065-m6-tracks-and-metadata.md#task-s6--s-2-additions)) |
| Chapters | `POST /api/chapters/import` `{path, format?}` | Names (and times where the format has them) of a HandBrake CSV, OGM text or Matroska XML chapter file; the format from the content when not given; `422 chapters.unreadable` / `chapters.invalid` (with the line) ([0065](../decisions/0065-m6-tracks-and-metadata.md#task-s6--s-2-additions)) |
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
| | `POST /api/preview/clips/{id}/frames` `{timestamps}` | Frames decoded from a cached clip, for the encoded frame compare (as `frames`: the request waits; [0067](../decisions/0067-m8-picture.md) item 1) |
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
| | `POST /api/jobs/type` `{job}` | The job type and its reason, and why the job could not be edited in place (for any job; a source the server may not write is a blocker, not a refusal) ([0065](../decisions/0065-m6-tracks-and-metadata.md#task-s6--s-2-additions)) |
| | `POST /api/jobs/chapters` `{job}` | The chapters the output gets, in output time (`OutputChapters`; from the one function the command uses) |
| | `POST /api/jobs/chapters/export` `{job, format}` | Those chapters as a CSV, OGM or XML file's text with a file name; none is `422 chapters.none` |
| | `POST /api/jobs/tags` `{job}` | Each tag as it will be written, the source's values, the template errors at `tags.<name>` |
| Batch | `POST /api/batch/group` `{source_ids, level}` | Groups |
| | `POST /api/batch/derive` `{job, source_id, sections, base?}` | `JobTemplate` from a single-file job, merged into `base` (the group's template) |
| | `POST /api/batch/resolve` `{template, source_ids, overrides}` | Resolution matrix + per-file jobs + issues. `overrides` by `source_id`; the job each override makes passes the path jail inside the batch service, before it is named or validated. A row whose output is outside the output roots gets `output.folder_required` |
| | `POST /api/batch/resolve-run` `{template, source_ids, level, overrides}` | A whole run (`resolve_batch`): `{grouping, resolutions}`, the name checks over every group, earlier outputs left out; overrides and rows as `resolve` |
| | `POST /api/batch/save-preset` `{template, name, category?, description?}` | Save a group template as a preset |
| Presets | `GET/POST /api/presets` · `GET/PUT/DELETE /api/presets/{id}` | CRUD. `GET` → `{presets, default_id}`; `POST` → `201`; `PUT` takes the whole preset (create or replace, a rename too); a refused change is a problem with the issue (web mode: the store's failures name no server folder) |
| | `POST /api/presets/{id}/default` · `POST /api/presets/import?on_conflict=` · `GET /api/presets/export?ids=` | Import: the export file as the body (at most 4 MiB), a report with the issues. Export: `{document, issues}` |
| | `POST /api/presets/diff` `{template, preset_id}` | Changes for the "modified" marker |
| | `POST /api/presets/defaults/preview` `{audio_defaults, subtitle_defaults, source_ids, container?, template?}` | Track decisions with reasons, for the live preview: one `TrackDraft` per source. With `template` (the one *Apply* sends to `jobs/explain`), each preview is that template with the two defaults put in, so its explicit `audio_rules` / `subtitle_rules` apply as in *Apply*; its naming folder is jailed as in `jobs/explain` ([0065](../decisions/0065-m6-tracks-and-metadata.md#fix-round--fa-core-and-server)) |
| Naming | `POST /api/naming/preview` `{naming?, source_ids, job?, container?}` | One `NameResult` per source: name source + reason, parsed fields with positions, rendered output paths, issues (web mode: `output.folder_required` with the settings fix). The variable list comes with `GET /api/definitions` |
| Queue | `GET /api/queue` · `POST /api/queue` `{jobs, position?, attach?}` | Snapshot `{jobs, processing, only}` (whether the queue takes waiting jobs and which; each change is a `queue.processing` event, [0064](../decisions/0064-queue-processing-event.md)), add (server validates again: a job with errors is added `failed`). Every job passes the path jail before any is added; a job without `output.path` is refused (422 `output.no_path`). `attach`: a client id; the jobs follow that client's event connection (S-7); refused (409) unless it is open. Outside a job's `settings`, the server's folders show as in the task answers (`log_path`: `<data>/…`) ([0048](../decisions/0048-queue-power-and-task-routes.md)) |
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
| `queue.owns_store`, `queue.busy`, `queue.store_busy` | The server's own state: it writes `server.json` only while it owns the store, `--owner-only` exits with 75 only while another process holds the lock, and idle exit waits while the queue is busy (S-7). A client reads `GET /api/queue` and the `job.state` events |
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
      server answers `{"type": "hello", "instance", "heartbeat", "client_id"}` (S-7's
      `attach`, [decision 0057](../decisions/0057-s7-attachments-client-id-and-detach.md)) and
      then sends each event as
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

- [x] Web mode: serve `frontend/dist` with immutable cache headers for hashed assets, and
      `index.html` for unknown non-API paths.
- [x] Desktop mode: no static files (Tauri bundles the frontend).

The folder is `static_dir` (`REFRAME_STATIC_DIR`). It has no implicit default: when it is not
set, the server is API only, and a deployment (the Docker image, the bare-metal unit) sets it
to a `npm run build:web` output. Files under `assets/` get
`public, max-age=31536000, immutable`; every other file and the `index.html` fallback get
`no-cache`. A path under `/api`, a missing file under `/assets/` and a method other than
`GET` / `HEAD` keep the JSON problem 404. No file outside the resolved folder is served
(links are followed, then checked). A `static_dir` without `index.html`, or one that holds the
config, data or cache folder, the endpoint file, a media root or an output root, is refused at
start-up (exit 2)
([decision 0058](../decisions/0058-s4-static-frontend.md)).

## S-5 OpenAPI → TypeScript

- [x] `scripts/gen-api.sh` (`npm run gen:api` in `frontend/`): export `openapi.json` from
      `create_app()` without starting a server (`scripts/export-openapi.py`; the shell's
      `REFRAME_*` variables are ignored), then run `openapi-typescript` (pinned in
      `frontend/package.json`) → `frontend/src/api/schema.d.ts`, committed and left out of
      `oxfmt`. The same input gives the same bytes.
- [x] The document's components also hold the `WS /api/events` messages: `ClientMessage`
      (`AuthMessage | DetachMessage`, by `type`; `AuthMessage` is the first one, S-7 added
      `DetachMessage`) and `ServerMessage` (`Hello | EventMessage | Heartbeat`, by `type`),
      with every core event model. OpenAPI has no WebSocket operation, so there is no
      path for it ([decision 0051](../decisions/0051-openapi-types-and-route-coverage.md)).
- [x] CI check: `scripts/gen-api.sh --check` regenerates into a temporary folder and fails with
      the diff (`Q-2.3`, the `api-contract` job on Ubuntu).

## S-6 Deployment

- [x] **Docker image** (multi-stage):
  1. `node` stage builds `frontend/dist`.
  2. `tools` stage downloads the pinned FFmpeg from `tools/ffmpeg.toml` and checks its
     SHA-256 ([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)).
  3. Runtime stage: Debian slim + uv-installed `reframe-server`, the bundled FFmpeg in
     `/opt/reframe/tools/ffmpeg/`, `mkvtoolnix`, `mediainfo`, and the GPU user-space drivers
     that FFmpeg loads at runtime (Intel media driver, Mesa VA drivers, oneVPL GPU runtime; the
     Dockerfile pins the exact packages). Runs as a non-root user (`PUID`/`PGID` env).
  4. Volumes: `/config`, `/data` (queue DB, logs, cache), `/media` (read), `/output` (write).
  5. `HEALTHCHECK` on `/api/health`.
- [x] **Override in Docker**: mount your own build and set `REFRAME_FFMPEG` /
      `REFRAME_FFPROBE`, for example `-v /opt/my-ffmpeg:/opt/custom-ffmpeg:ro -e
      REFRAME_FFMPEG=/opt/custom-ffmpeg/bin/ffmpeg`.
- [x] `docker/compose.example.yml` with variants for Intel/AMD (`/dev/dri`) and NVIDIA
      (`deploy.resources.reservations.devices`), and a commented-out override example.
- [x] Bare metal: `uv tool install 'reframe[cli]' --with reframe-server
      --with-executables-from reframe-server` (one environment, so `reframe` and
      `reframe-server` have the same version;
      [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md) item 11),
      plus a systemd user unit example. The wheels
      do not contain FFmpeg. `reframe tools fetch` downloads the pinned build from the manifest
      (checksum verified) into the data dir, where it counts as the bundled build. On Windows:
      run from a terminal. A Windows service wrapper comes later.
- [x] Reverse-proxy notes (WebSocket upgrade headers, body size, timeouts).

`docker/Dockerfile`, `docker/compose.example.yml` and [deployment.md](../deployment.md)
([decision 0059](../decisions/0059-s6-docker-image-and-bare-metal.md)). The image declares no
`VOLUME`: the four folders are mount points, so a missing mount is not hidden by an anonymous
volume. It sets `auth: password`, the media and output roots and `REFRAME_STATIC_DIR`; the
Intel driver is Debian's non-free build (the free one has no H.264/HEVC encode before Ice
Lake). Until the packages are on PyPI, `uv tool install` takes the paths of a checkout.
Behind a reverse proxy in Docker the server trusts `X-Forwarded-*` from the proxy's one
address only (`FORWARDED_ALLOW_IPS`, the 0059 follow-up). The "Done when" was met on the
owner's AMD desktop on 2026-10-28 (0059, "The lead's GPU check"); Intel QSV and NVIDIA NVENC
in Docker are not verified.

Done when: `docker compose up` on a Linux host with a GPU (the owner's: AMD) shows its VAAPI
encoders as available and encodes a fixture file. Intel QSV and NVIDIA NVENC in Docker are
listed as not verified until such a host is available
([decision 0043](../decisions/0043-plan-review-before-m3.md) item 7).

## S-7 Local owner mode

Implements [decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md). Needs
S-2 and S-3. Milestone M3b, with C-17 ([05](05-core.md#c-17-remote-queue-and-queue-commands)).

- [x] **Endpoint file** (`endpoint_file`): when the server holds `queue.lock` (it opens the
      queue at start-up) and listens, it writes `server.json` (atomic, mode `0600` on POSIX)
      with `pid`, `instance`, `port`, `token`, `version`, `api_version`, `started_at`, and
      removes it at close. A server that cannot take the lock writes nothing and keeps 0027's
      private queue with `queue.store_busy`; with `owner_only` it exits with code 75. A client
      connects to `127.0.0.1` and the file's `port`
      ([decision 0056](../decisions/0056-s7-owner-endpoint-file-and-idle-exit.md)).
- [x] **Idle exit** (`idle_exit`): exit after N seconds with no running job, no job that a
      `start` still targets, no event connection and no pending when-done countdown.
- [x] **Attachments**: after a client authenticates on `WS /api/events`, the server answers
      with a `client_id`. `POST /api/queue` with `attach: <client_id>` is refused (409)
      unless that connection is open. A connection that ends without a `detach` message
      cancels its attached jobs that have not ended, as a cancel does, also a job whose add
      was under way. A `detach` also covers the jobs attached after it; a server stop
      (uvicorn's 1012, the lifespan's close) cancels nothing and leaves the jobs to the
      queue's close. Not persisted
      ([decision 0057](../decisions/0057-s7-attachments-client-id-and-detach.md)).
- [x] `POST /api/queue/start` with `job_ids` starts only those jobs; other waiting jobs are
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
├── api/              # schema.d.ts (generated), types.ts, client.ts, events.ts (WebSocket + reconnect)
├── platform/         # Platform interface + web.ts + desktop.ts (Tauri plugins)
├── stores/           # system, sources, editor, validation, presets, queue, tasks, settings,
│                     # activity, toasts, ui
├── views/            # WorkspaceView, QueueView, PresetsView, ActivityView, SettingsView,
│                     # SandboxView (dev only)
├── components/
│   ├── base/         # Field, Section, Card, RoleBadge, CodecLabel, LanguageChip, StatusDot, KeyValue,
│   │                 # IssueList
│   ├── shell/        # navigation rail, status bar, login and first-run screens, toasts
│   ├── editor/tabs/  # SummaryTab … TagsTab, and the tab registry
│   ├── sources/      # SourcesPanel, FileBrowserDialog (web)
│   ├── naming/       # NamingOptionsEditor, JobNamingEditor
│   ├── presets/      # PresetPicker, the preset drawer
│   ├── media/        # FrameViewer, SplitCompare, TrackTable
│   ├── dimensions/   # the Dimensions tab's sections, CropOverlay
│   ├── crop/         # CropMagnifier, CropLoupe, CropCheckGrid (and its worker)
│   ├── filters/      # the Filters tab's rows, help and source colour box
│   ├── clip/         # the live preview clip and its frame compare
│   ├── language/     # LanguagePicker, LanguageListEditor
│   ├── tracks/       # output track rows, TrackMetadataEditor, flag toggles, bulk edit
│   ├── defaults/     # DefaultsDialog and its live preview
│   ├── chapters/     # the Chapters tab's table, import and export
│   ├── tags/         # the Tags tab's form
│   ├── video/        # EncoderPicker, QualitySlider, AdvancedOptions, CommandPreview
│   ├── batch/        # GroupBanner, ApplyToGroupDialog, ResolutionMatrix, OverrideDot
│   ├── settings/     # the Settings sections
│   └── queue/        # QueueTable, JobLog
├── composables/      # useValidation, useGeometry, useShortcuts, useUndo, useReveal, useTheme
├── i18n/             # index.ts; messages/<locale>/<area>.json, one file per area
└── styles/           # tokens, theme preset
```

Each area of the app has its own message file and its own component folder, so that the M4
tasks never share one ([decision 0063](../decisions/0063-m4-frontend-mvp.md)); the task
breakdown and the store contracts are in [../m4-breakdown.md](../m4-breakdown.md); M6's
folders and contracts are in [../m6-breakdown.md](../m6-breakdown.md)
([decision 0065](../decisions/0065-m6-tracks-and-metadata.md)); M8's are in [../m8-breakdown.md](../m8-breakdown.md)
([decision 0067](../decisions/0067-m8-picture.md)).

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
- [x] Colour, spacing, radius and typography tokens. Light/dark theme plus a "system" option.
      Compact and comfortable density.
- [x] Base components. `Field` is the key one: label, control slot, inline help (ⓘ popover),
      the validation issue for its `path`, and an override dot (batch). Every editor control
      uses `Field`.
- [x] `RoleBadge` (solid = flag, outlined = heuristic, tooltip = evidence), `CodecLabel`
      (commercial name + raw codec in the tooltip), `LanguageChip`.
- [x] **i18n from the first view**: every string the user sees goes through vue-i18n. A CI
      check fails on literal text in a `<template>` (oxlint does not read templates; pick a
      small script or a Vitest check here)
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 8).

Done when: a component sandbox page (dev only) shows every base component in both themes.

### F-2 API layer and events
- [x] Typed client from `schema.d.ts`. Auth header or cookie. Problem+json → toast.
- [x] WebSocket client: reconnect with backoff, resync snapshots, dispatch events to stores
      (the design: [decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task B").

### F-3 App shell
- [x] Navigation rail, workspace layout (sources | tabs | preview), status bar, keyboard
      shortcuts, theme switch, toasts, a first-run screen when FFmpeg is missing.
- [x] A tab of a later milestone is not shown until it is built, and its `Ctrl+N` does nothing
      ([decision 0063](../decisions/0063-m4-frontend-mvp.md)).

### F-4 Editor state
- [x] `editor` store: an **EditorTarget** is either a single `JobSettings` or a group
      (`JobTemplate` + overrides). The tabs use one API for both. (M4 builds the job target;
      the group target is typed and comes with F-13. It also holds the file the tabs show and
      that file's job, and a scope: an edit goes into the template or into that file's
      override; [0066](../decisions/0066-m7-batch-season.md) item 1. The range always goes into
      that file's override, and the shown job carries it in both scopes;
      [0075](../decisions/0075-the-range-in-a-group-and-the-shown-job.md).)
- [x] Undo/redo as JSON patch history (Ctrl+Z / Ctrl+Shift+Z).
- [x] `useValidation`: debounced (250 ms) `jobs/validate`. Issues are indexed by path for `Field`.
- [x] "Modified vs preset" uses `presets/diff` (the design: [decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task D").

### F-5 Sources panel and opening files
- [x] Web: a server file-browser dialog (roots, breadcrumbs, media filter, multi-select). The
      server lists media files only, so the filter narrows that list to a caller's types
      ([decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task E").
- [x] Desktop: native dialogs and drag-and-drop through `Platform`
      ([decision 0069](../decisions/0069-m5-desktop-shell.md), "Task C").
- [x] Probe progress, warnings, batch groups (collapsible), near-match markers.

### F-6 Summary tab
- [x] The cards from [03 §Summary](03-features.md#summary). Chips and issues link to fields
      ([decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task G").
- [x] A **Job type** card (not a line): the job type (encode, remux, metadata edit) and why from
      `jobs/type`, updated after each edit; *Edit in place*, why the job could not edit its source
      in place, the `inplace.*` issues with their fixes; *Remux only* (`jobs/draft-remux`, one undo
      step); the source read again after an in-place edit
      ([decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task D").

### F-7 Dimensions tab, preview panel, crop magnifier
- [x] Pipeline header from `jobs/geometry`.
- [x] `FrameViewer`: fit/100 %/200 %, frame strip, timestamp seek, crop overlay with drag handles.
- [x] `CropMagnifier`: canvas-based. It loads the full-resolution PNG and draws 4 edge strips at
      2×/4×/8× with `imageSmoothingEnabled = false`, a removed-area tint, the crop lines, and a
      cursor loupe.
- [x] `CropCheckGrid`: every sample with the overlay. A Web Worker computes the luma variance
      of the removed band and puts a warning badge on frames that lose content.

### F-8 Filters tab
- [x] Filter list (toggle + preset + tune), help panel from the definitions, `SplitCompare`
      before/after on the current frame (`preview/render`).
- [x] Colorspace source-colour box and the "what will happen" sentence.

### F-9 Video tab and advanced options
- [x] `EncoderPicker` grouped by family, with status dots and reasons. The
      missing-encoder banner shows the fix buttons from the validation issue.
- [x] `QualitySlider` with the recommended band. Rate-control switch.
- [x] `AdvancedOptions` is generated from the option schema: categories, search, "show only
      changed", reset, placeholders for defaults, help popovers, "copy HDR metadata"
      (M9, [decision 0068](../decisions/0068-m9-advanced-options.md)).
- [x] `CommandPreview` drawer (`jobs/plan`), a light syntax highlighter, copy button.

### F-10 Audio and subtitles tabs
- [x] `TrackTable` (source, read-only) with expandable details, role badges, and a "Measure"
      button for unknown bitrates. (M4 built the table, [decision 0063](../decisions/0063-m4-frontend-mvp.md),
      "Task I"; M6 the "Measure" button, the subtitle event count and the loudness measurement,
      [decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task B".)
- [x] Output track editors with drag reorder, action, encoder settings, `TrackMetadataEditor`.
      (M4 built all but `TrackMetadataEditor`, which is M6; [decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task I";
      [decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task C".)
- [x] `LanguagePicker`: search dialog, favourites on top, a preview of how it is written
      (`hun · hu`). With `LanguageListEditor` for ordered language lists (M6,
      [decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task A").
- [x] Bulk edit for selected tracks. External subtitle import (file picker through `Platform`)
      (M6, [decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task C").
- [x] **Defaults dialog** (audio and subtitles), opened from the tab and from the preset editor:
      selection settings, a codec-rule table (drag to reorder, the catch-all row is locked,
      expandable rows for optional settings), passthru check boxes, fallback encoder, and the
      **live preview** table (`presets/defaults/preview`, debounced). In a batch group, the preview
      covers every file. From a tab, *Apply* replaces the job's tracks with what the defaults give
      (the job keeps no defaults of its own); in a group, *Apply* puts the defaults into the
      template and drops its explicit rules of that kind
      ([decision 0065](../decisions/0065-m6-tracks-and-metadata.md), item 4 and "Task E";
      the group case [decision 0066](../decisions/0066-m7-batch-season.md) item 10 and "Task D").

### F-11 Chapters and tags tabs
- [x] Chapter table with inline name edits, import/export, generate. Tag form with templates.

### F-12 Presets UI
- [x] Preset drawer: tree by category, built-in lock, CRUD, default star, import/export,
      "modified" marker with a diff popover. The drawer is the presets view, and the marker's
      popover opens on a click ([decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task J").

### F-13 Batch UI
- [x] Group rows in the sources panel. **Edit group** mode with banner and representative-file
      switcher.
- [x] `ApplyToGroupDialog` (section checkboxes). Copy/paste sections from the context menu.
- [x] `ResolutionMatrix`: virtualised table with ✓/≈/✗ cells, a candidate picker per cell, a
      "problems only" filter, and an editable naming column.
- [x] Override dots on `Field` with **Reset to group** and **Apply to whole group**
      ([decision 0066](../decisions/0066-m7-batch-season.md), "Task D").
- [x] Queue-group flow with the error dialog.

### F-14 Queue and activity
- [x] Queue table: drag reorder, live progress, per-job and global controls, edit-back,
      reveal in folder (desktop), when-done selector.
- [x] Job log viewer (virtual scroll, follow mode, copy all). Global activity log.

### F-15 Settings view
- [x] The sections from [03 §Settings](03-features.md#settings). The encoder table has a re-scan
      button. Tool paths have a **Test** button.
- [x] M4 ("basic") builds Tools, Encoders, Output, Queue and Appearance. Languages needs the
      `LanguagePicker` (F-10, M6) and Preview needs the preview panel (F-7, M8); each comes with
      its milestone ([decision 0063](../decisions/0063-m4-frontend-mvp.md)).
- [x] Languages (M6): favourites, preferred audio and subtitle languages
      ([decision 0065](../decisions/0065-m6-tracks-and-metadata.md), "Task A").
- [x] Preview (M8): number of sample frames, cache size limit, the cache size and *Clear cache*
      ([decision 0067](../decisions/0067-m8-picture.md), "Task E").

### F-19 Range selector
- [x] The Range button and popover in the source header from [03 §Range](03-features.md#range):
      the four modes, the modes the source cannot use disabled with the reason, chapter
      selects with names and start times, time fields that parse `H:MM:SS.mmm` / `MM:SS` /
      seconds, frames as the model has them (0-based, exclusive end), and the span kept on a
      mode change ([decision 0074](../decisions/0074-range-selector-in-m10.md)).
- [x] Each change is one JSON patch on `/range` (one undo step). The `range.*` issues show on
      its fields and on the button, with their fixes.
- [x] Group target: always the shown file's override, with the override dot and *Reset to
      group*. No *Apply to whole group*.
- [x] The Summary's Source and Estimate cards show the range. Playwright flow 5 (F-17).

(Added in M10 by [decision 0074](../decisions/0074-range-selector-in-m10.md): numbered after
F-18, built before F-16. Built on 2026-11-13: 0074 "Built"; in a group the shown job of scope
`group` carries the shown file's range, so the name, the command and the issues follow it:
[0075](../decisions/0075-the-range-in-a-group-and-the-shown-job.md).)

### F-16 i18n and accessibility
- [x] Audit that every string goes through vue-i18n (English first; the rule and its check
      start in F-1). Full keyboard paths. Visible focus. WCAG AA contrast in both themes.
      Respect `prefers-reduced-motion`.

  (Done on 2026-11-14. What the audit checks, and the gate in the end-to-end tests
  (`e2e/a11y/`) that keeps it true, are in
  [decision 0076](../decisions/0076-f16-i18n-and-accessibility-audit.md). F-17 runs the gate in
  WebKit with the flows.)

### F-17 End-to-end tests
- [x] Playwright against `reframe-server` with fixture media and fake FFmpeg:
  1. Open a file → set an audio language and commentary flag → queue → done → re-probe shows
     the flags.
  2. Open a season folder → edit group → check the matrix → queue the group.
  3. A preset with an unavailable encoder → banner → use the fallback → queue.
  4. Manual crop → magnifier shows the crop lines → the command contains the matching
     `crop=` filter.
  5. Open `chapters.mkv` → Range *Chapters* 2–3 → the header shows the range and its length,
     the output name has `{chapters}` = `2-3`, and the command drawer has the matching `-ss`
     and `-t` → queue → the queued job has the range (F-19, M10;
     [decision 0074](../decisions/0074-range-selector-in-m10.md)).

  (M4 built the set-up and flow 3, in headless Chromium and Firefox, each with its own server;
  [decision 0063](../decisions/0063-m4-frontend-mvp.md), "Task M". M6 built flow 1, which
  probes the job's output through the server; [decision
  0065](../decisions/0065-m6-tracks-and-metadata.md), "Task G". M7 built flow 2, which reads
  the queued group through the server; [decision 0066](../decisions/0066-m7-batch-season.md),
  "Task E". M8 built flow 4, which reads the magnifier's canvases back against the frame;
  [decision 0067](../decisions/0067-m8-picture.md), "Task F". M10 built flow 5 with F-19, which
  reads the queued job back through the server; [decision
  0074](../decisions/0074-range-selector-in-m10.md), "Built".)
- [x] Each flow comes with its screens: the Playwright set-up and flow 3 in M4, flow 1 in M6,
      flow 2 in M7, flow 4 in M8, flow 5 with F-19 in M10. M10 runs all five in Chromium and WebKit
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 8).

### F-18 Naming editor
- [x] Template field with `{` autocomplete and variable chips (current values, click to insert).
- [x] **Parsed name** panel: name source + reason, coloured spans over the original name,
      editable fields (per-file override).
- [x] Live preview (`naming/preview`, debounced). Used in Settings → Output, the preset editor,
      the Summary Output card, and the batch matrix naming column.
      (The matrix's naming column shows the names of `batch/resolve-run`, which names each file
      with the same naming code, again after each change: [0066](../decisions/0066-m7-batch-season.md), "Task C".)