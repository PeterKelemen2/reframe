# 0047 — The event WebSocket: messages, throttles, slow and stuck clients

- Status: accepted
- Date: 2026-10-22
- Steps: S-3

## Context

[06 §S-3](../plan/06-web-app.md#s-3-event-websocket) asks for `WS /api/events`: the client
authenticates in its first message, then gets events as JSON with a sequence number;
`job.progress` and `task.progress` are coalesced per id (latest kept, at most 4 per second),
`job.log` lines are batched every 250 ms, a heartbeat comes every 15 s, and a slow consumer
costs bounded memory and still gets the latest values. The contract
([0045](0045-m3-server-order-and-contract.md), [m3-breakdown.md](../m3-breakdown.md) task 1b)
leaves open the message envelope, the kind of heartbeat, and whether a client that cannot keep
up gets a `resync` or is closed.

The core bus (`reframe.events`) already bounds each subscription: queued progress events are
coalesced per id; the lossy events (`job.progress`, `task.progress`, `job.log`) are dropped
beyond `max_queue`, with a `resync` marker where they were; other events grow the queue up to
a hard limit (4 × `max_queue`), and past it the subscription ends with
`resync(reason="overflow")`.

What the installed versions do (checked on 2026-10-22 with uvicorn 0.54.0, Starlette 1.9.0,
websockets 17.3, Python 3.14.8; scripts in the agent's scratchpad, a FastAPI app served by
uvicorn on loopback and a `websockets` client; `packages/reframe-server/tests/test_events.py`
relies on 1 to 5):

1. **A send to a client that does not read waits.** With `websockets` installed, uvicorn's
   default WebSocket protocol (`ws="auto"`) is `websockets-sansio`. Its `send` waits until the
   transport is writable (below its high-water mark), then writes the whole message. A client
   that paused reading took 15 to 39 messages of 128 KiB (2 to 5 MB, kernel buffers included)
   before the server's `send` waited.
2. **A close to such a client waits too.** `websocket.close(1001)` did not return within 1 s;
   uvicorn has no time limit there. A cancelled wait writes nothing.
3. **A client that goes away during a send**: the waiting send raises Starlette's
   `WebSocketDisconnect(code=1006)`.
4. **Shutdown**: uvicorn closes every open WebSocket with 1012 and gives the app a
   `websocket.disconnect` (code 1012) before the lifespan ends; then it waits until the
   connections and the app's tasks have ended.
5. **An exception that leaves the app**, `WebSocketDisconnect` included, is logged by uvicorn
   (`Exception in ASGI application` on the `uvicorn.error` logger).
6. **Pings**: uvicorn sends WebSocket pings itself (`ws_ping_interval` and `ws_ping_timeout`,
   20 s each by default) and closes a connection that does not answer. ASGI has no ping
   message, and a browser's JavaScript cannot see pings.
7. **Timers**: asyncio runs a timer when `when < time() + clock resolution`
   (`BaseEventLoop._run_once`), so up to one clock tick early.

## Decision

1. **Messages.** Every message is one JSON object with a `type`, written with `json_text`. The
   models are in `reframe_server.events`.
   - Client → server, first: `{"type": "auth", "token": "…"}` (`AuthMessage`). In password
     mode the token may be left out. Later client messages are read and ignored (S-7 adds
     `detach`).
   - Server → client, once after the auth: `{"type": "hello", "instance": "…", "heartbeat":
     15.0}` (`Hello`). `instance` is the server run's (`GET /api/health`); `heartbeat` is the
     interval in seconds. S-7 adds `client_id`.
   - Each event: `{"type": "event", "seq": n, "event": {…}}` (`EventMessage`). `event` is the
     core event (`reframe.models.Event`) unchanged. `seq` is 1 for the first event of a
     connection and one more for each next event, without gaps; a new connection starts at 1.
   - `{"type": "heartbeat"}` (`Heartbeat`), without `seq`.

   An envelope, not a `seq` field in the event: the event stays the core model, and `type`
   alone tells a server message from an event.
2. **Auth.** The first message must come within `auth_timeout` (5 s).
   `security.ws_authenticated(config, websocket, token)` decides; `token` is `None` when the
   client left it out. A first message that is not an auth message, a refusal, or no message
   in time closes the connection with **4401**. The client gets no event before its hello.
   `connections` counts the connections that passed the auth.
3. **Progress throttle.** Per job or task id (the core's `coalesce_key`): the first progress
   goes out at once; then nothing for that id for 1 / `progress_rate` seconds (0.25 s). A
   newer value in that time replaces the held one, which goes out when the time is up.
   **Log batches**: the first `job.log` line starts a `log_interval` timer (0.25 s); then one
   `job.log` message per job with all its lines, at most `max_log_lines` (1000); older lines
   beyond that are added to `dropped` (with the core's own `dropped`). **Order**: held
   progress and log lines of a job go out before its next `job.state`, held task progress
   before its `task.done`, so a client never gets progress after the end.
4. **Heartbeat.** An application message every `heartbeat` seconds (15), whatever else is
   sent: a browser cannot see protocol pings (finding 6), and a client that hears nothing for
   longer than the hello's `heartbeat` should reconnect. uvicorn's own pings stay on and find
   dead clients on the server side.
5. **Slow clients get a `resync`; the hub does not close them.** Each connection reads its
   subscription (`max_queue` 256, hard limit 1024) only between two sends. While a send waits
   (finding 1), the backlog stays in the subscription, where the core coalesces and drops it.
   The hub itself keeps only one held progress per id and the lines of the current log batch.
   So a connection's memory is bounded and the latest progress of each id is kept. A client
   that cannot keep up gets the core's `resync` and stays connected. On `resync(overflow)`
   the hub subscribes again *before* it sends the `resync`, so the snapshots that the client
   reads after it miss no later event. A dead client is closed by uvicorn's ping timeout.
6. **Close.** `close()` cancels every connection. Each one tries to send 1001 for at most
   `close_timeout` (1 s; finding 2), then frees its subscription; `close()` returns when all
   have ended. A client that does not read never gets that 1001, and its TCP connection is
   left to uvicorn. A connection that comes after `close()` is accepted and closed with 1001.
   When the bus closes first (the facade closed), each connection is closed with 1001 too.
7. **Deadlines** count as reached one clock tick early (finding 7), so the sender never
   spins until the clock reaches them.
8. **Parameters.** The intervals and limits are keyword-only `EventHub` parameters with the
   defaults above; the app uses the defaults, the tests shorter ones.

## Consequences

- The frontend's `events.ts`: send the auth message first. On 4401, do not retry with the
  same credentials (log in again, or the token is wrong). On any other close, or when nothing
  came for longer than the hello's `heartbeat`, reconnect with a backoff, then call the `GET`
  snapshots (`/api/queue`, `/api/tasks`, `/api/system/encoders`); do the same on a `resync`
  event. A hello with another `instance` than before means the server restarted: probe the
  sources again.
- The WebSocket messages are not in the OpenAPI document. The frontend needs TypeScript types
  for them and for `reframe.models.Event`: S-5 can add the four models above to the
  document's components (or export their JSON Schema).
- S-7 adds `client_id` to `Hello` and `client_open`, handles `detach` where the hub reads the
  client's messages, and cancels a connection's attached jobs when the connection ends. Idle
  exit reads `connections`.
- Each connection holds one bus subscription; every publish goes to every connection's queue.

## Plan changes

- [06 §S-3](../plan/06-web-app.md#s-3-event-websocket): the message shapes, 4401, the
  heartbeat message, the slow-client and close rules, and a link to this record.

## Follow-up (review), 2026-10-22

**Finding R-5** ([0052](0052-m3-server-review.md)): the server process did not stop (SIGINT,
`POST /api/system/shutdown`, also a second SIGINT) while an event client did not read, and the
lifespan never closed the hub and the facade. Reproduced with the reviewer's script and with a
real `reframe-server` process: still running after 15 s.

What uvicorn 0.54.0 does (read in `uvicorn/server.py` and
`uvicorn/protocols/websockets/websockets_sansio_impl.py`, checked with a server whose client
paused reading; CPython 3.14 `asyncio`):

1. `Server.shutdown()` closes the listeners, then calls `shutdown()` on every connection. For a
   WebSocket after its handshake that puts `websocket.disconnect` (1012) in the app's queue,
   writes a close frame and calls `transport.close()`. The hub's connection then ends at once
   (its listener reads the disconnect; the waiting send is cancelled): 1 s later uvicorn had no
   task left and `hub.connections` was 0.
2. `transport.close()` is not `abort()`: asyncio closes the socket and calls
   `connection_lost` only once the write buffer is empty (selector and proactor transports
   alike). A client that does not read never empties it (150 KB were left), and uvicorn removes
   a connection from `server_state.connections` only in `connection_lost`.
3. `_wait_tasks_to_complete` loops while there are connections, then awaits
   `Server.wait_closed()`, which since Python 3.12 also waits for every connection. Only
   `timeout_graceful_shutdown` (default `None`: no limit) bounds that wait. When it runs out,
   uvicorn cancels the remaining ASGI tasks (it logs `Cancel 0 running task(s), timeout
   graceful shutdown exceeded` at ERROR) and then runs the lifespan's shutdown.
4. The lifespan's shutdown comes only after that wait. A second SIGINT sets `force_exit`, which
   ends the loops but not `wait_closed()`, and skips the lifespan's shutdown.
5. uvicorn's own close timer (10 s after the app's `websocket.close`) and its ping timeout call
   `transport.close()` too, so neither frees such a connection.

An ASGI app cannot reach the transport, so the hub cannot end such a connection. The fix is in
`reframe_server.__main__.serve` (the lead's file): `timeout_graceful_shutdown=2`. The desktop
shell kills the server 5 s after it asked it to stop ([07](../plan/07-desktop-app.md)), so 2 s
leaves 3 s for the lifespan to close the hub and the facade. In-flight HTTP requests get the
same 2 s (a download to a client that does not read would hold up the shutdown the same way).
After the limit, the stuck connection stays open until the process exits. Checked with the
change applied: the real `reframe-server` stopped 2.5 s after SIGINT (exit 130) and 2.6 s
after `POST /api/system/shutdown` (exit 0), the lifespan done; the reviewer's script with the
same `uvicorn.Config` stopped after 2.2 s.

Tests (`tests/test_events.py`):

- `test_the_server_stops_while_a_client_does_not_read` runs `__main__.serve()` with real
  uvicorn, stalls an event client, asks for the shutdown over HTTP and requires the server to
  end within 5 s with the facade closed. It fails without the change (still running after 5
  s) and passes with it (3.7 s). Until the lead applies the change it is marked
  `xfail(strict=True)`; the marker goes in the same commit as the change. SIGINT is not a
  second case: uvicorn's handler sets the same `should_exit` as `request_shutdown`, and the
  path after it is the same.
- `stall()`, Windows (0052): it does not depend on a buffer size. It publishes 128 KiB
  warnings until the hub's subscription keeps a backlog for 0.2 s, which happens only while
  the hub's send waits, that is while uvicorn's transport is above its high-water mark: a
  selector transport counts its buffer, a proactor transport (Windows) also the send in flight
  (CPython's `_ProactorBaseWritePipeTransport`). `pause_reading()` holds on the proactor loop:
  the read in flight completes, its data is kept for `resume_reading()`, and no new read is
  posted. The test client does not read either way (websockets pauses its transport itself
  beyond 16 queued messages). What depends on the OS is how much the kernel takes in before
  the hub waits; the client's part is now fixed: its socket gets an 8 KiB receive buffer
  before it connects, and Linux does not auto-tune a buffer that was set (16 KB stayed
  16 KB; one left alone grew from 128 KB to 1 MB). The server's send buffer is still
  auto-tuned (on Linux up to 4 MB; the hub waited after 19 messages, about 2.5 MB). Whether
  Windows also leaves a set `SO_RCVBUF` alone was not checked; the stall publishes up to 400
  messages (52 MB), far more than either side's buffer. Not run on Windows: the Windows run
  (D-0 / Q-1.4) shows whether it holds there; no skip, because nothing found here makes it
  fail.

Audit of `tests/test_events.py` against the test rules: no test or table row follows the path
of another one (22 mutations of `events.py`, at least one per test function, were each caught
by the test written for that branch), so none is deleted.

**The server's folders in task events** (R-11, [0048](0048-queue-power-and-task-routes.md)):
`GET /api/tasks*` writes the server's config, data and cache folders as `<config>`, `<data>`
and `<cache>` (`reframe_server.folders.hide_server_folders`), but `task.progress` and
`task.done` carried the raw `TaskInfo`. `EventHub` takes a keyword-only `hide` (a function of a
JSON value; default: the value unchanged) and applies it to the `message`, `error` and
`result` of a task event's `TaskInfo` when it sends the event (a progress value held by the
throttle is hidden when it goes out). Other events are sent unchanged. Test:
`test_a_task_event_names_the_cache_folder_by_its_label` (a real hub made with
`hide=functools.partial(hide_server_folders, reframe)`; fails when any of the three fields,
or either event type, is left out).

**Changes needed from the lead**:

- `__main__.py`: `_SHUTDOWN_GRACE = 2` and `timeout_graceful_shutdown=_SHUTDOWN_GRACE` in
  `uvicorn.Config`, and the `xfail` marker of
  `test_the_server_stops_while_a_client_does_not_read` removed in the same commit.
- `app.py`: `EventHub(reframe.events, config, hide=functools.partial(hide_server_folders,
  reframe))`.

Plan change: [06 §S-3](../plan/06-web-app.md#s-3-event-websocket) says that the process stops
within the 2 s limit plus the lifespan's close, also with a client that does not read.
