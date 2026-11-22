# 0089 — The core's folder probe and the shipped language list are removed

- Status: accepted
- Date: 2026-11-16
- Steps: Q-6.14 (findings SRV-01, SRV-02 and SRV-08 of the simplification audit); C-3, C-15,
  S-2, D-2

## Context

C-3 asks for a "folder probe: a task with a concurrency limit (default 4) that reports
progress". The core had it three times over: `reframe.probe.probe_folder`, the task wrapper
`SourceService.probe_folder` (task kind `probe_folder`), and, outside it, the server's own loop
in `POST /api/sources` (task kind `probe_sources`). [0049](0049-s2-system-fs-settings-sources-preview.md)
item 5 made the server list folders itself (`jobs.media_files`: one task per request, partial
outputs left out), so `SourceService.probe_folder` had no caller outside tests: neither the
server nor the CLI started it. The batch engine has a fourth copy (`BatchService._probe_all`).

[0071](0071-server-start-and-windows-cold-start.md) item 2 ships the language list rendered
(`reframe_server/data/languages.json`, 73,834 bytes) because building it from `langcodes` took
277 ms at the first `GET /api/languages`. [0082](0082-own-language-data-table.md) replaced
`langcodes` and `language_data` with a generated table. Measured in a fresh process (Linux):
`language_list()` 9.2–9.4 ms at the first call, the model and JSON 1.8 ms. The shipped file
saved about 11 ms at the first request, and cost a generated file, a regenerate command, a
freshness test, a PyInstaller data entry and a second copy of the language table.

## Decision

1. **`SourceService.probe_many(files, *, concurrency=4, cancel=None, on_progress=None)`
   replaces the folder probe.** It probes a list of files through `SourceService.probe`,
   `concurrency` at a time, and returns the results in the order of the list. After `cancel`
   no new ffprobe starts (the rest are `CANCELLED` errors); a cancelled call (the token or the
   calling task) returns only after every ffprobe it started is gone (a `TaskGroup`, not
   `gather`). `on_progress(done, total)` is called after each file. Listing a folder stays with
   the caller (`reframe.probe.list_media_files`, `jobs.media_files`).
2. **Removed:** `SourceService.probe_folder`, `reframe.probe.probe_folder`,
   `FolderProbeResult` (also from `reframe.service`), the task kind `probe_folder` and its
   default limit, and its frontend label. `POST /api/sources` uses `probe_many` with the task's
   cancel token; its task kind, message, progress text and result do not change.
3. **`SourceService` counts the users of a cancel token.** `probe_many` hands one token to many
   `probe` calls; the first call to end no longer drops it from the tokens that
   `SourceService.close()` cancels.
4. **No shipped language list** (supersedes 0071 item 2 and its first Consequences bullet).
   The route builds the body from `language_list()` at the first request and keeps it. The
   body and the `ETag` are the same bytes as the shipped file's (compared before and after).
   The sidecar's PyInstaller spec no longer collects `reframe_server` data. The Windows check
   of 0071 (the first request with the frozen sidecar on the VM) is still to be made; if it
   goes over about 50 ms, a shipped body is the fallback.
5. **Server leftovers removed:** `EventHub.client_open` (0057 item 1; `attachment()` is the
   one lookup), `SourceRegistry.path`, `routers.jobs.without_output`. The settings jail walks
   the settings with the job jail's walker (`security.model_paths`), so a folder inside a list
   or a mapping of the settings is checked too (there is none today).

## Consequences

- C-3's "folder probe" item is now "many files"; a UI that wants a folder lists it first.
- The batch engine keeps its own probe loop (`BatchService._probe_all`); moving it onto
  `probe_many` is left for a later change (it would also give the batch the cancel-safe
  `TaskGroup`).
- The first `GET /api/languages` in a process costs about 11 ms on Linux.

## Windows check (2026-11-17)

Item 4's check, on the Windows test VM of 0070 with the frozen sidecar (`reframe-server.exe
--mode web --auth none`, a fresh process and data folder each time, `curl` `time_total` of the
first and second `GET /api/languages`, six processes each):

| Frozen sidecar | First request | Second request |
|---|---|---|
| Before this record (the shipped body, `8996e82`) | 31–37 ms | 1.7–1.9 ms |
| After it (built at the first request, `98b8b94`) | 58–72 ms | 1.8–5.4 ms |

Building the body costs about 30 ms at the first request on Windows (11 ms on Linux); the
first request is over item 4's "about 50 ms". Whether the shipped body comes back is the
owner's decision (pending).

## Plan changes

- `05-core.md` C-3: the folder probe item becomes `probe_many`; the facade sketch names
  `probe_many`.
- `06-web-app.md`: the `sources.probe_folder` row of "Not exposed" is removed.
