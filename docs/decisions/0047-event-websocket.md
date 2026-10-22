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
