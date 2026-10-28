# 0056 — S-7 owner: `server.json`, `--owner-only` and idle exit

- Status: accepted
- Date: 2026-10-28
- Steps: S-7 (and, for the address a client connects to, C-17 and D-3)

## Context

[06 §S-7](../plan/06-web-app.md#s-7-local-owner-mode) and
[0042](0042-one-scheduler-process-and-cli-clients.md) items 2 and 8: the server that holds
`queue.lock` publishes `server.json` once it listens and removes it at close; with
`owner_only` a server that cannot take the lock exits with 75; with `idle_exit` it exits when
nothing needs it. The contract ([0055](0055-server-complete-order.md),
[server-complete-breakdown.md](../server-complete-breakdown.md)) fixed the functions:
`owner.start` (the lifespan), `owner.publish` (`serve()`, once uvicorn listens),
`owner.withdraw` (the lifespan's close), `idle.is_idle` and `idle.watch`. It said that when
`owner.start` raises, "uvicorn's start-up then fails and `serve()` returns
`app.state.exit_code`". The breakdown left one question open: what a client connects to when
the server listens on a non-loopback address only (default: loopback and the port).

What we found (uvicorn 0.54.0, Python 3.14, Linux, 2026-10-28):

1. **uvicorn exits the process when the lifespan's start-up fails.** `Server.startup` runs
   `sys.exit(STARTUP_FAILURE)` (3) when the lifespan fails, and also when the bind fails. The
   `SystemExit` leaves the task that runs `server.serve()`, stops the event loop, and the
   process ends with 3. `serve()` never returns `app.state.exit_code`. A real
   `reframe-server --port 0 --mode desktop --owner-only` against a held lock:

   ```
   ERROR:    Traceback (most recent call last):
     … (121 lines: a merged_lifespan frame for each of the 18 included routers)
   reframe_server.owner.StoreBusy: another Reframe process owns the queue of <data>
   ERROR:    Application startup failed. Exiting.
   Task exception was never retrieved
   future: <Task finished … coro=<Server.serve() …> exception=SystemExit(3)>
   exit code 3
   ```

2. **Which address reaches which bind.** A real `reframe-server --port 0 --auth token --host H`,
   then `GET /api/health` with httpx to each address and the port in `server.json`:

   | `--host` | Sockets | `127.0.0.1` | `[::1]` | `localhost` |
   |---|---|---|---|---|
   | `127.0.0.1` | `127.0.0.1` | yes | refused | yes |
   | `::1` | `::1` | refused | yes | yes |
   | `localhost` | `::1` and `127.0.0.1`, **two ports** | yes (the published port is the IPv4 socket's) | refused | yes |
   | `0.0.0.0` | `0.0.0.0` | yes | refused | yes |
   | `::` | `::` (IPv6 only) | refused | yes | yes |
   | `172.17.0.1` | `172.17.0.1` | refused | refused | refused |

   `localhost` resolves to `::1`, then `127.0.0.1` here; httpx tries both.

## Decision

1. **The queue opens at start-up.** `owner.start` calls `reframe.queue.list()` once, in the
   lifespan (the lock is taken without waiting). When the queue does not own the store:
   with `owner_only`, `app.state.exit_code = 75` and `StoreBusy` (its message names the data
   folder); without it, the core's private queue and `queue.store_busy`, and one warning in
   the log for the operator.

2. **Writing the file.** `owner.publish` writes `ServerEndpoint` with the core's
   `JsonDocumentFile.write`, the writer of `auth.json`: a `mkstemp` file in the same folder
   (mode `0600` from its creation on POSIX), `fsync`, `replace_file` (`os.replace`; on Windows
   a `PermissionError`, a client that has the file open, is tried again 6 times from 50 ms,
   doubling), and an `fsync` of the folder. It replaces a stale file. The fields: `pid`
   (`os.getpid()`), `instance` (`app.state.instance`, as in `GET /api/health`), `port` (from
   `serve()`), `token` (`config.secret_token`: `REFRAME_TOKEN` or the random token of the run),
   `version`, `api_version` (`API_VERSION`), `started_at` (now, UTC). Only a process that owns
   the store writes it. A file that cannot be written gives one warning with the reason and
   the path; the server runs on, and clients do not find it.

3. **Removing the file.** `owner.withdraw` reads the file and removes it only if its
   `instance` is this run's. Nothing is kept between `publish` and `withdraw`: the instance is
   random per run, so only this run can have written a file with it. A server that does not
   own the queue leaves the owner's file alone. A removal that fails (on Windows, while a
   client has the file open) is logged, and the lifespan goes on to close the queue. The file
   that stays is stale, as after `kill -9`: the client's health check fails or names another
   instance, and the next owner replaces it.

4. **The token** is never logged and never in an answer. `GET /api/health` has `instance` and
   `api_version`; `ServerEndpoint` hides the token in its `repr`.

5. **Idle exit.** `idle.is_idle`: not `queue.busy`, `hub.connections == 0` and
   `power.pending is None`; `False` once the lifespan has closed the facade (`serve()` cancels
   the watch only after uvicorn's shutdown, and an error in the watch would come out of
   `serve()`). `idle.watch` looks every `min(0.25, seconds / 4)` seconds and calls
   `request_shutdown()` once every look for `seconds` was idle, then returns (`serve()`'s
   cancel of an ended task does nothing). So:
   - a busy spell shorter than one look can go unseen;
   - a plain HTTP request is not activity. A client that needs the server to stay opens the
     event WebSocket first, as C-17 does (0042 item 5);
   - an event connection counts once it is authenticated. A client that connects in the last
     moment of the idle time can get a close (1001) from the shutdown; it then looks for an
     owner again (0042 item 3).

6. **The address a client connects to** (the open question): **`127.0.0.1` and the `port` of
   `server.json`**, then `GET /api/health` for `instance` and `api_version`.
   - It reaches every owner that the plan's front ends start (desktop-mode rules bind
     `127.0.0.1`: 0042 item 3, 07) and the documented web binds (`127.0.0.1`; `0.0.0.0` in
     Docker, where `docker exec` runs the CLI inside the container). D-1's CSP
     (`connect-src http://127.0.0.1:* ws://127.0.0.1:*`) and the diagram of 07 use it too.
   - `localhost` also reaches the IPv6 binds, but each client then tries `::1` first and is
     refused by every IPv4-only server, and the desktop CSP would need more origins. (Windows
     is said to take about 2 s for a refused connect; not checked here.)
   - A server that listens on a non-loopback address only (`--host 10.0.0.5`), or on IPv6
     only, still writes the file: it owns the queue, and the file's `pid` and `version` let a
     client say who owns it. The client's health check fails and it falls back to 0027 (the
     private queue, `queue.store_busy` that names the owner).
   - **No new field now.** If such deployments need the shared queue later: an optional
     `host` in `ServerEndpoint` (default `127.0.0.1`; a `DocumentModel`, so an older client
     ignores it), set by `serve()` from the listening socket. That is the lead's change (the
     model is in the core, the socket in `serve()`).

7. **Exit 75 needs a change in `serve()`** (Context item 1; `__main__.py` is the lead's
   file): run `server.serve()` in a coroutine that catches `SystemExit`, so that the task
   ends, `server.started` stays `False` and `serve()` returns `app.state.exit_code`. Checked
   with that change applied locally: the real `--owner-only` server exits 75 and its stderr
   has no "Task exception was never retrieved". It also makes a failed bind exit with 1
   instead of 3, as `serve()`'s docstring says. Until it lands,
   `test_owner_only_exits_75_against_a_held_lock_and_writes_nothing` is
   `xfail(strict=True, raises=AssertionError)`.

## Consequences

- Every server opens the queue at start-up, so each test app takes `queue.lock` in its own
  data folder (as 0055 said). The server suite passes with it.
- **For C-17**: read `<data>/server.json` through `ServerEndpoint`; connect to `127.0.0.1`
  and its `port`; compare `instance` and `api_version` with `GET /api/health`; exit 75 of
  `--owner-only --idle-exit 30` means that another owner won; open `WS /api/events` before
  the first `POST /api/queue`; a close (1001) right after connecting means the owner was
  stopping: look for an owner again.
- **For D-3**: the same address; the desktop app's event connection keeps a CLI-started owner.
- The stderr of an `--owner-only` server that lost: Starlette's traceback (121 lines: FastAPI
  nests the lifespan once for each of the 18 included routers), ending in
  `StoreBusy: another Reframe process owns the queue of <data>`, then
  `Application startup failed. Exiting.` C-17 reads only the exit code. A one-line message
  needs a lifespan that does not raise through Starlette: the lead's choice.
- With `--host localhost --port 0`, uvicorn listens on two ports and `serve()` publishes the
  first socket's. A client of `127.0.0.1` reaches the server only if that socket is the IPv4
  one (it was, here). The default host and the desktop rules use `127.0.0.1`.
- Not verified on Windows: the protection of the file (no POSIX mode there; the file gets
  the ACL of the data folder, which is private to the user under `%LOCALAPPDATA%`), the
  replace that waits for a reader and the removal that fails (both mocked on Linux), and the
  real-process tests (the SIGINT test is skipped on Windows).

## Plan changes

- [06 §S-7](../plan/06-web-app.md#s-7-local-owner-mode): "Idle exit" ticked. The endpoint
  file bullet says which address a client connects to; it stays open until the change to
  `serve()` lets `--owner-only` exit with 75.

## Follow-up (the lead), 2026-10-28

Decision item 7 is done in `serve()` (`__main__.py`): `server.serve()` runs in a coroutine that
suppresses `SystemExit`, so uvicorn's `sys.exit(3)` after a failed lifespan start-up or a
failed bind ends only that task, and `serve()` returns `app.state.exit_code`.

- `test_owner_only_exits_75_against_a_held_lock_and_writes_nothing` is no longer `xfail`: the
  real `--owner-only` server against a held lock exits 75 and writes no `server.json`.
- New test `test_app.py::test_a_server_whose_port_is_taken_exits_1`: the real server on a
  port that another socket holds exits 1. Before the change it exited 3, its stderr ending in
  `uvicorn/server.py", line 192, in startup … SystemExit: 3`.
- The one-line message for a losing `--owner-only` server (Consequences) is left as it is:
  C-17 reads only the exit code.
