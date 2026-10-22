# 0045 — M3 server: order, dependencies and the contract

- Status: accepted
- Date: 2026-10-22
- Steps: S-0, S-1, S-2, S-3, S-5, Q-2.3; milestone M3 (server part)

## Context

M3's server steps are built the way the core-complete steps were
([core-breakdown.md](../core-breakdown.md)): the lead writes a breakdown
([m3-breakdown.md](../m3-breakdown.md)) and a contract, then agents build in waves on the
branch `m3-api-spike`, and a fresh agent reviews the result. The plan (06 Part A) leaves open
which libraries the server uses, how a route finds a source (the facade takes paths, the API
takes `source_id`; [0030](0030-core-complete-contract.md) "Consequences"), how a route reaches
the facade, and how JSON with a path that is not UTF-8 is written
([0044](0044-code-review-follow-ups.md) item 3).

What the installed versions do (checked on 2026-10-22 with FastAPI 0.159.1, Starlette 1.9.0,
uvicorn 0.54.0, websockets 17.3, pydantic-settings 2.16.1, httpx 0.28.1, Pydantic 2.14.0;
scripts run in the lead's scratchpad, the results are asserted by
`packages/reframe-server/tests/test_app.py`):

1. **httpx's `ASGITransport` does not run the lifespan.** A FastAPI app whose lifespan appends
   to a list answers a request through `ASGITransport`, and the list stays empty. Entering
   `app.router.lifespan_context(app)` by hand runs it (`start` … `stop`).
2. **httpx has no WebSocket client.** `httpx` has no name with "socket" in it, and
   `AsyncClient` has no `websocket_connect`.
3. **FastAPI's own body reader is `json.loads` + Python-mode validation.** `fastapi/routing.py`
   reads a body with `await request.json()` (Starlette: `json.loads`) and validates the value
   with the field's Python validator. A body `{"path": "/media/bad\udcffname.mkv"}` (ASCII
   text with the escape) reaches the handler as the string with the lone surrogate. So the
   rule of 0044 holds for every declared body parameter; no custom reader is needed, and the
   request models stay in the OpenAPI document.
4. **FastAPI's default response path cannot write such a path.** With a `response_model` and no
   response class, FastAPI 0.159 serializes with Pydantic's `dump_json` (a "fast path";
   `use_dump_json` is true only when the route's response class is the default placeholder),
   which raises `PydanticSerializationError … surrogates not allowed`. With any response class
   set, FastAPI dumps to Python data and calls the class's `render`; a `render` that uses
   `reframe.models.json_text` writes `"/media/bad\udcffname.mkv"` as ASCII.
5. **A real uvicorn and the `websockets` client work together** with `-W error` (the test
   suite turns warnings into errors): a server on `127.0.0.1:0`, `lifespan="off"`, a
   `websockets.asyncio.client.connect` with an `Origin`; the handler sees the `Host` and
   `Origin` headers.
6. **uvicorn re-raises a captured signal** after its clean shutdown: SIGINT ends
   `asyncio.run(server.serve())` with `KeyboardInterrupt` after "Application shutdown
   complete".

## Decision

1. **Dependencies.** Runtime (`reframe-server`): `fastapi`, `uvicorn`, `websockets` (uvicorn's
   WebSocket protocol, and later the CLI's client of 0042), `pydantic-settings`. Dev:
   `httpx` (the route tests' `AsyncClient`). No extra WebSocket test library: WebSocket tests
   run the app in a real uvicorn on a free loopback port and connect with `websockets`
   (`reframe_testing.server.Api.live()`). This tests the real upgrade path, with the `Host`
   and `Origin` headers that S-1 checks.
2. **Lifespan in tests.** The harness (`reframe_testing.server.make_api_factory`) enters the
   lifespan itself and gives the httpx clients the same app; the live server runs with
   `lifespan="off"`, so one facade serves both.
3. **JSON.** Every response is written by `reframe_server.api.JsonTextResponse`
   (`json_text`, ASCII), set on the app and on every router (`api_router`), so FastAPI never
   takes the `dump_json` path. Request bodies are declared as normal FastAPI parameters
   (finding 3). Errors are `application/problem+json` (`reframe_server.api.Problem`:
   `type`, `title`, `status`, `detail`, `code`, `issues`, `errors`), written the same way. A
   request validation error lists the field and the message, never the value (it may be a
   password); an unexpected error is a 500 with no detail.
4. **`operationId`** is `<tag>_<handler name>` (`api.operation_id`); a router is made with
   `api_router(tag)`, and a handler is named for what it does (`probe` in `sources` is
   `sources_probe`).
5. **Sources.** `source_id` is the first 24 hex digits of the SHA-256 of the absolute path's
   bytes (`os.fsencode`), so probing the same file again gives the same id. The server keeps a
   registry `source_id` → path in memory (`reframe_server.sources.SourceRegistry`); the
   source itself comes from `Reframe.sources.get(path)`, so a file that changed since its probe
   is a 409 `source.stale`, and an unknown id a 404 `source.unknown`. After a restart the
   registry is empty and the client probes again.
6. **Access to the facade.** The lifespan creates the facade (`Reframe.create(config_dir,
   data_dir)`) and the event hub and stores them on `app.state`; handlers get them through
   `reframe_server.deps` (`ReframeDep`, `ConfigDep`, `HubDep`, `SourcesDep`). A request
   while the facade is closed is a 503 `server.closing`.
7. **Configuration.** `ServerConfig` (pydantic-settings, prefix `REFRAME_`, then the command
   line): desktop mode always uses token auth; an unset `auth` is `none` on a loopback host and
   an error elsewhere; `auth: none` off loopback is refused. The token is a `SecretStr`:
   `REFRAME_TOKEN`, else `secrets.token_urlsafe(32)`, one per process. Fields for S-7
   (`endpoint_file`, `idle_exit`, `owner_only`) exist now and do nothing yet.
8. **Entry point.** `reframe-server` (`reframe_server.__main__:main`): one uvicorn worker; all
   logs go to stderr; in desktop mode the only stdout line is `{"event":"ready","port":N}`
   once the server listens (port 0 picks a free one). A SIGINT ends with exit code 130, as the
   CLI's Ctrl+C does (finding 6). An invalid option or configuration exits 2.
9. **Health.** `GET /api/health` needs no credentials (a container health check and the CLI's
   owner check of 0042 call it): `version`, `api_version` (1), `instance` (random per app),
   `uptime`. It returns nothing else.
10. **Order.** Wave 0 (the lead): the contract and S-0. Wave 1, five tasks in parallel: S-1,
    S-3, and S-2 cut in three. Wave 2: S-5 and Q-2.3, and the S-2 facade coverage test. Wave 3:
    a fresh review. The tasks and their files are in [m3-breakdown.md](../m3-breakdown.md).
11. **Web-mode settings.** In web mode, a settings patch that names a program
    (`/tools/…`) is refused (403): a client of a web server must not choose which program
    the server runs. A Docker or bare-metal deployment sets `REFRAME_FFMPEG` /
    `REFRAME_FFPROBE` instead (S-6). A folder in a settings patch (the fixed output folder)
    must pass the write jail. Desktop mode allows both.
12. **Models.** Domain data stays in `reframe.models` (the one schema of `CLAUDE.md`). An API
    envelope (a request body such as `{source_id, preset_id}`, a response wrapper such as
    `Health`, `Problem`, `TaskAccepted`) is a server model, defined next to its route. A new
    domain model goes into `reframe.models` through the lead.
13. **Paths in routes.** Every path from a client goes through `security.jail_read`,
    `jail_write` or `jail_job` (called as `security.<name>`, so a test can replace it), before
    the facade sees it.

## Consequences

- One facade per app run; a test that needs another configuration makes another app.
- The API's source ids live only as long as the server process; the client re-probes after a
  reconnect to a new `instance`.
- A FastAPI upgrade that changes finding 3 or 4 breaks
  `test_a_path_that_is_not_utf8_goes_in_and_out`, not a user.
- The interactive docs page is `GET /api/docs` (Swagger UI, which loads its script and style
  from a CDN); the security headers of S-1 must leave it working or the page moves behind a
  setting. The OpenAPI document is `GET /api/openapi.json`.

## Plan changes

- [06](../plan/06-web-app.md) Part A: S-0 (exit codes, logs on stderr, health needs no
  credentials, `source_id`), S-2 (the problem body, `operationId`, web-mode settings).
