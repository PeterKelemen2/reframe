# 0049 — S-2 routes: system, files, settings, sources and preview

- Status: accepted
- Date: 2026-10-22
- Steps: S-2 (task 1d of [m3-breakdown.md](../m3-breakdown.md))

## Context

[06 §S-2](../plan/06-web-app.md#s-2-rest-api) lists the routes but leaves open: what a
long-running rescan answers, what a frame or clip answer holds when the cache folder must not
appear in it, how a `<video>` gets a signed clip URL, which `Range` requests a clip answers,
how `POST /api/sources` turns folders into files, what a web client may browse and which
settings it may change ([0045](0045-m3-server-order-and-contract.md) item 11).

Behaviour checked on 2026-10-22 (FastAPI 0.159.1, Starlette 1.9.0, uvicorn 0.54.0, httpx
0.28.1), each kept as a test:

- When a client closes the connection while the handler still works, uvicorn delivers
  `http.disconnect` to `request.receive()` once the body has been read
  (`test_preview.py::test_a_client_that_goes_away_cancels_the_frames_task`, over a real
  uvicorn server: an httpx client with a 1 s timeout).
- Starlette's `FileResponse` answers a malformed `Range` with a `400` in plain text, several
  ranges with `multipart/byteranges`, and raises `RuntimeError` (a 500) when the file is gone
  between the lookup and the send (`starlette/responses.py`, `FileResponse.__call__`). The
  preview cache evicts files at any time (LRU, 0033), so the clip route does not use it.

## Decision

1. **Frames wait, other preview work is a task.** `POST /api/preview/frames` and
   `POST /api/preview/render` start the frames task and wait for it (06: "Frame list
   (timestamps + URLs)"). The handler also waits for the client: when the client goes away, or
   the request is cancelled, it cancels the task. A failed task is a `422 preview.failed`
   (title: the task's error), a task cancelled elsewhere (`POST /api/tasks/{id}/cancel`) a
   `409 preview.cancelled`, a task cancelled by shutdown a `503 server.closing`. `frames`
   takes `count` or `timestamps`, not both (a `422 request.invalid`). Crop detection, the
   clip and the scans answer `202` as 06 says.
2. **No cache path in an answer.** A frame answer is `{frames: [{key, kind, timestamp, width,
   height, cached, url}], notes}`: `PreviewFrame.path` is left out, `url` is
   `security.sign_media_url(config, "/api/preview/frames/<key>.png")` (default lifetime).
   `GET /api/preview/cache` is `{size}`, `DELETE` `{freed}`.
3. **Clip URL.** New route `GET /api/preview/clips/{id}/link` (authenticated,
   `preview_clip_link`): `{url}`, signed for one hour, or `404 preview.unknown_clip`. The
   client takes the id from the clip task's result (`PreviewClip.id`). One hour because a
   `<video>` asks for byte ranges again while it plays and seeks; a frame URL is used once.
4. **Media files.** `GET /api/preview/frames/{key}.png`: `ETag` is the quoted key (the key
   names the content), `304` when `If-None-Match` holds it, `Cache-Control: private,
   max-age=3600`; the PNG is read in a worker thread, and a frame evicted after the lookup is a
   `404 preview.unknown_frame`. `GET /api/preview/clips/{id}`: one `bytes=a-b`, `bytes=a-` or
   `bytes=-n` range is a `206` with `Content-Range`; several ranges, or a header that does not
   parse, give the whole file (`200`; RFC 9110 lets a server ignore `Range`); a range that
   starts at or after the end is a `416` problem with `Content-Range: bytes */<size>`. The file
   is opened (and its size read) in a worker thread before the answer starts, and streamed from
   that open file, so an eviction during the transfer does not cut it. `If-Range` is not
   supported: a clip id names its content. Both routes depend on
   `security.require_media_access` themselves (the media router has no `require_auth`).
5. **`POST /api/sources` `{paths, recursive?}`.** Every path goes through `security.jail_read`
   first; one path outside the roots refuses the whole request (`403`) and no task starts. The
   task `probe_sources` expands folders with `Reframe.jobs.media_files` (hidden files and
   partial outputs left out, a file named twice probed once, a missing path and a folder
   without media files reported) and probes each file with `Reframe.sources.probe`, four at a
   time, so one request is one task with one progress. The brief named the folder probe
   (`sources.probe_folder`); it lists partial outputs (`*.part.mkv` of a running job) and runs
   as a second task per folder, so it is not exposed. `recursive` (default `false`) is new:
   the core's folder expansion has it. The result is `{sources: [{id, path}], errors: [{path,
   code, message, detail}]}`, the sources in path order; `code` is `probe.<kind>` or `sources.no_media`.
   Each source is added to the `SourceRegistry` when the task ends.
6. **Routes that take a `source_id`** resolve it with `SourceRegistry.get` (`404
   source.unknown`, `409 source.stale`), then call one facade method: two calls per handler.
   The registry's path passed the jail when it was probed and the roots do not change while
   the server runs, so it is not jailed again. `GET /api/sources` lists `{id, path, source}`;
   `source` is `null` for a file that changed or is gone (probe it again). `DELETE` forgets
   the id (`204`; unknown: `404 source.unknown`).
7. **System.** `GET /api/system` is `{mode, auth, platform, tools, problems,
   settings_read_only}` (`platform`: `sys.platform`); the store problems are read in a worker
   thread, because the preset store reads `presets.json` at its first use. `POST
   /api/system/encoders/rescan` is a `202` task (`encoders_rescan`, result: the
   `CapabilitySnapshot`): with hardware tests it runs test encodes for many seconds. `POST
   /api/system/tools/rescan` answers the `ToolSet` (four version checks with a timeout).
   `POST /api/system/shutdown` is a `204` in desktop mode and a `403 system.desktop_only` in
   web mode. `tools/fetch` takes `{build?}` only: the platform is the server's own, and a
   manifest would be a server file named by the client.
8. **Files.** `GET /api/fs/roots` is `{roots: [{name, path, kind}]}`: web mode the media
   roots then the output roots (resolved, like every listing); desktop mode the home folder,
   then `/` or the drives (`os.listdrives()` on Windows). `GET /api/fs/list?path=` lists
   folders first, then media files (`reframe.probe.MEDIA_EXTENSIONS`), each in natural order;
   hidden entries are left out; `parent` is `null` at a root (web) or at the file system
   root. A path passes `jail_read` or, failing that, `jail_write`: the breakdown says "below
   the media roots", but Settings → output folder must browse below an output root, and a
   client may write there anyway. Problems: `404 fs.not_found`, `422 fs.not_a_folder`,
   `403 fs.unreadable`.
9. **Settings.** `PUT /api/settings` takes a JSON patch. Before the update, the handler
   applies it to a copy (`reframe.jsonpatch.apply_patch`, `AppSettings` validation) and
   compares the result with the current settings, so a replace of the whole document or a new
   key under `tools` is caught as well as `/tools/ffmpeg`. Web mode refuses a patch that sets
   a tool path (`403 settings.tools_forbidden`); removing one is allowed (the "Use bundled"
   fix of a `ToolInfo` lets discovery choose again). Every folder of the settings (a `Path`
   field outside `tools`, now the fixed output folder) whose value the patch changes goes
   through `security.jail_write`, in both modes (the jail allows everything in desktop mode); a
   folder the patch does not change is not checked again. A patch the store rejects is a `422`
   with the store's issues (`code`: the first issue's). The answer is `{settings, changes,
   saved, warnings}`: `SettingsUpdate` is a dataclass, not a model.
10. **`operationId`s**: `system_info`, `system_encoders`, `system_rescan_encoders`,
    `system_rescan_tools`, `system_fetch_tools`, `system_shutdown`, `fs_roots`, `fs_list`,
    `settings_get`, `settings_update`, `sources_probe`, `sources_list`, `sources_get`,
    `sources_remove`, `sources_bitrate_scan`, `sources_subtitle_scan`,
    `sources_loudness_scan`, `preview_frames`, `preview_render`, `preview_cropdetect`,
    `preview_clip`, `preview_clip_link`, `preview_cache_size`, `preview_clear_cache`,
    `preview_frame_file`, `preview_clip_file`.
11. **Facade methods these routes do not expose**: `tools.versions` (the `ToolSet` of
    `GET /api/system` holds each version), `tools.fetch`'s `platform` and `manifest` (item 7),
    `capabilities.wait` (`GET /api/system/encoders` never waits; `capabilities.changed`
    events follow a detection), `capabilities.closest_available` (validation uses it inside
    the core), `sources.probe_folder` (item 5), `sources.store` and `sources.update` (the
    scans store what they measured themselves), `settings.path` (a server path the client
    cannot use), and the lifecycle members `start`, `close`, `current`, `discovering`,
    `detecting`, `cache`.

## Consequences

- A frames request holds an HTTP connection for as long as FFmpeg runs (about a second per
  pair of timestamps, 0033); the task limit (`frames`: 2) bounds the work, not the requests.
- `GET /api/tasks/{id}` and the `task.done` event show a frames or clip task's raw result,
  which holds cache paths (`PreviewFrame.path`, `PreviewClip.path`). The routes here never
  answer with them; hiding them there is for the tasks route or the core models (reported to
  the lead).
- A signed URL that expires while a `<video>` still plays fails its next range request; the
  client asks for a new link.

## Plan changes

- [06](../plan/06-web-app.md) §S-2: the rows of System, Files, Sources and Preview (rescan
  answers, `recursive`, the clip link, what a web client may browse and change).
