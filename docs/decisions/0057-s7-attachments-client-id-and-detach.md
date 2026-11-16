# 0057 — S-7 attachments: `client_id`, `attach`, `detach`, and which end cancels

- Status: accepted; `EventHub.client_open` (item 1) is removed by [0089](0089-folder-probe-and-language-list-removed.md): `attachment()` is the one lookup
- Date: 2026-10-28
- Steps: S-7 (task B of [server-complete-breakdown.md](../server-complete-breakdown.md));
  affects C-17, S-3, S-5

## Context

[06 §S-7](../plan/06-web-app.md#s-7-local-owner-mode) and
[0042](0042-one-scheduler-process-and-cli-clients.md) item 5: after the auth on
`WS /api/events` the server answers with a `client_id`; `POST /api/queue` with
`attach: <client_id>` is refused (409) unless that connection is open; a connection that ends
without a `detach` message cancels its attached jobs that have not ended, as a cancel does; not
persisted. The contract commit left `EventHub.client_open` as a stub that returns `False`, and
the route already checked it before the jobs were added.

The plan leaves open:

1. **Which ends count.** 0042 names the client's ends (Ctrl+C, `kill -9`, a closed terminal).
   A server stop also ends every connection.
2. **What `detach` covers**: the jobs attached before it, or also the ones attached after it.
3. **The race** (breakdown, task B): `QueueService.add` awaits the validation and the file
   keys, so the connection can end between the attach check and the moment the job is in the
   queue. Nothing would then cancel that job.
4. **The order of the cancels.** The queue's `cancel(job_id)` returns once the job has
   stopped; a running job's end frees its slot and the runner takes the next waiting job at
   once.
5. **The `.part` file.** The breakdown says "its `.part` file follows the partial-file
   setting"; 06 and 0042 say "as a cancel does", and the core's cancel always removes the
   `.part` file (05 §C-11 "Cancel: kill the tree and remove the `.part` file";
   `QueueService._cleanup`: the partial-file setting applies to a failure only).
6. **Reach.** The hub is made by `app.py` (the lead's file) with the bus, the config and
   `hide`, not with the queue.

What uvicorn does (0.54.0, `ws="auto"`: websockets-sansio, websockets 17.3, Python 3.14.8;
read in `uvicorn/protocols/websockets/websockets_sansio_impl.py` and printed from the hub's
listener in the tests below; recorded in `testdata/README.md`, "uvicorn WebSocket ends (S-7
attachments)"):

| How the connection ends | The app's `websocket.disconnect` |
|-------------------------|----------------------------------|
| The client closes (close handshake) | its code, here 1000 |
| The client's socket goes away (`transport.abort()` in the tests) | 1005: `connection_lost` after the handshake, whatever the cause (source) |
| uvicorn shuts down | 1012 (`shutdown()`); the client sees close code 1012 too |
| The hub's own `close()` | none: the hub cancels its connection task |

- `connection_lost` puts the disconnect in the app's queue first and only then wakes a send
  that waits for the transport (which then raises, as Starlette's `WebSocketDisconnect`);
  `handle_close` queues the disconnect before it closes the transport. So when the hub's send
  fails because the client went away, its receive already holds the disconnect.
- The frames of one connection reach the app in the order they came: a text message sent
  before the close frame is received before the disconnect.

## Decision

1. **`client_id`.** Each authenticated connection gets `secrets.token_hex(16)`, sent as
   `Hello.client_id`. The hub registers the connection before it sends the hello (a client may
   add jobs as soon as it has read it) and forgets it when the connection ends.
   `EventHub.client_open(client_id)` is true while it is registered; `EventHub.connections`
   counts the same registry.
2. **`attach`.** `EventHub.attachment(client_id)` returns the connection's `Attachment`, or
   `None`. `POST /api/queue` takes it once, before any `await`; `None` is 409
   `queue.attach_unknown_client` and adds no job. After each `queue.add` the route calls
   `attachment.add(job)` with no `await` in between. The `Attachment` object outlives the
   hub's registry entry and knows how the connection ended: when it ended meanwhile, by the
   client and without a `detach`, the job is cancelled at once and the answer (201: the jobs
   were added) shows it `cancelled`. So no job stays attached to a client that is gone.
   The route uses `attachment()`, not `client_open()`: one lookup gives the check and the
   object, and the race needs the object.
3. **`detach`.** A client message `{"type": "detach"}` (`DetachMessage`). From then on the
   connection's end cancels none of its jobs, also jobs attached after it (06: "a connection
   that ends without a `detach` message"). There is no answer: the server reads a connection's
   messages in order, so a `detach` sent before the close is read before the end. Other client
   messages after the auth are still read and ignored.
4. **Only the client's end cancels.** The hub's listener decides: it reads the disconnect,
   and any code but 1012 means the client went away. uvicorn queues the disconnect before it
   fails a send, so this also holds when the send to the client failed first. The server's own
   ends leave the jobs to the queue: uvicorn's shutdown (1012), `EventHub.close()` (the
   lifespan cancels the connection's task) and the bus closing (the facade closes, the queue
   with it). The queue's close then does what it does on every server stop: a running job
   ends `interrupted`, a waiting one stays waiting in the store. A server stop is not the
   user's cancel (0042 Verification 4 expects `interrupted` when the server dies).
5. **The cancel.** All the jobs of the connection at once: `asyncio.gather` of
   `queue.cancel(job_id)`, so every waiting job is marked `cancelled` before a running one's
   end frees its slot (one at a time, the next waiting job of the same client would start, and
   an in-place edit that has started is let finish). A job the user removed meanwhile is
   skipped. The cancel runs in a task of the hub; `EventHub.close()` waits for these tasks
   after it has ended the connections, so the lifespan closes the queue only after them.
6. **`.part` file**: the cancel is the queue's own `cancel(job_id)`, so the `.part` file is
   removed as on any cancel; the breakdown's "follows the partial-file setting" is read as
   "as a cancel does" (06, 0042). A different rule would be a core change.
7. **Reach.** The connection takes the queue from `websocket.app.state.reframe.queue` when it
   is authenticated (the hub already reads `app.state.instance` there); `app.py` is unchanged.
8. **Not persisted.** Attachments live in the hub only; a restarted server has none.
9. **OpenAPI.** The components hold `ClientMessage` (`AuthMessage | DetachMessage`, by
   `type`) next to `ServerMessage`, and `Hello.client_id`; `frontend/src/api/schema.d.ts` is
   regenerated.

## Consequences

- C-17: read `client_id` from the hello; add jobs with `attach`; for `--detach`, send
  `{"type": "detach"}` and then close with a close handshake (the `websockets` client's
  `close()`). A close code 1012 tells the CLI that the server stopped: its running jobs end
  `interrupted` and its waiting jobs stay in the queue.
- A client that is alive but does not read (a stopped process) keeps its connection open
  (0047 follow-up, finding 2), so its jobs stay attached until it reads again or dies.
- A job that ended and that the user then retried keeps its attachment: if its client is
  still connected and later goes away, the retried job is cancelled. Revisit if a front end
  retries the jobs of a CLI that is still running.
- `start` with `job_ids` is the core's (`QueueService.start`); nothing changes there. The test
  of the attachments starts the client's jobs with `job_ids` while another front end's job
  waits ahead of them in the queue: that job is neither started nor cancelled.
- **Open**: a `detached` answer, if C-17 wants `--detach` to confirm before it exits. It would
  be a fourth `ServerMessage` member (and a change of the components test in
  `tests/test_openapi.py`).

Tests (`packages/reframe-server/tests/test_attach.py`, over real uvicorn and a `websockets`
client): a client that goes away (`transport.abort()`) has its running job stopped with its
`.part` file removed and its waiting job cancelled without being started, while another front
end's job ahead of them stays waiting; a `detach` keeps the jobs of its own connection while a
second, concurrent connection without one has its job cancelled; `attach` with the id of a
closed connection is 409 and adds nothing; a connection that ends while its job is added
(the add held after the check) gets that job cancelled, or kept after a `detach`; uvicorn's
stop (close code 1012) and the hub's close leave the jobs waiting; the hub's close waits for
the cancels; a job removed before its client goes away makes nothing fail; the components hold
`ClientMessage` and `Hello.client_id`. In `tests/test_events.py`: a client killed while the
hub waits to send to it has its job cancelled. The stub-based attach test of
`tests/test_queue.py` (it replaced `client_open` with a fake) is replaced by these.

## Plan changes

- [06 §S-7](../plan/06-web-app.md#s-7-local-owner-mode): the Attachments item and the `start`
  with `job_ids` item ticked; the Attachments item says what a `detach` covers and that a
  server stop leaves the jobs to the queue, with a link to this record.
