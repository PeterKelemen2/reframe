# 0048 — The queue, power and task routes

- Status: accepted
- Date: 2026-10-22
- Steps: S-2 (task 1c of [m3-breakdown.md](../m3-breakdown.md)); affects S-7, C-17, F-14
- Extends: [0037](0037-when-done-power-actions-and-job-notifications.md) item 2 (the when-done
  route and a running countdown)

## Context

06 §S-2 lists the Queue, Power and Tasks routes in one line each. It leaves open the status
codes, the answer of each action, what happens to a job the path jail cannot check, how the
log is read in parts, and several gaps:

- 03 §Queue says "start / pause / resume / cancel (per job **and all**)", and 0042 item 10 gives
  `reframe queue pause|resume|cancel [ID…|--all]`. The S-2 table has only
  `POST /api/queue/{start|pause|stop}`: no global resume and no global cancel.
- 0037 item 2: "The front end's when-done selector (S-2 `PUT /api/queue/when-done`, F-14) should
  cancel a running countdown when the new value is not a power action", and its consequences
  say to revisit this with S-2.
- The breakdown's rule for routers: one facade call per handler, and a handler that needs more
  says why here.

What the core does (read in `reframe/queue/service.py`, `platform/power.py`, `tasks.py`, and
shown by the route tests): `QueueService.add` validates and adds a job with errors as `failed`;
`log_path(id)` builds `<data dir>/logs/<id>.log` for any id, also one the queue does not hold;
the log file is UTF-8 (`errors="backslashreplace"`), appended to by every run and removed with
its job; `TaskManager.cancel` and `PowerService.cancel` return `False` both for "nothing to
cancel" and for an unknown id.

## Decision

1. **Routes and names** (`operationId` `<tag>_<handler>`):

   | Route | operationId | Answer |
   |-------|-------------|--------|
   | `GET /api/queue` | `queue_snapshot` | `{jobs: QueueJob[]}` in queue order |
   | `POST /api/queue` `{jobs, position?, attach?}` | `queue_add` | 201, the added `QueueJob[]` in order |
   | `POST /api/queue/start` `{job_ids?}` (body optional) | `queue_start` | 204 |
   | `POST /api/queue/stop` | `queue_stop` | 204 |
   | `POST /api/queue/pause` · `/resume` · `/cancel` | `queue_pause_all` · `queue_resume_all` · `queue_cancel_all` | 204 |
   | `PUT /api/queue/order` `{job_ids}` | `queue_reorder` | 204 |
   | `PUT /api/queue/when-done` `{when_done}` | `queue_set_when_done` | `{when_done}` now in effect |
   | `POST /api/queue/{id}/pause` · `/resume` · `/cancel` | `queue_pause_job` · `queue_resume_job` · `queue_cancel_job` | 204 |
   | `POST /api/queue/{id}/retry` | `queue_retry` | the `QueueJob` |
   | `POST /api/queue/{id}/duplicate` | `queue_duplicate` | 201, the new `QueueJob` |
   | `DELETE /api/queue/{id}` | `queue_remove` | 204 |
   | `GET /api/queue/{id}/log?from=` | `queue_log` | `{text, next, more}` |
   | `GET /api/power` | `power_pending` | `{pending: PowerCountdownEvent \| null}` |
   | `POST /api/power/cancel` | `power_cancel` | `{cancelled}` |
   | `GET /api/tasks?kind=` | `tasks_snapshot` | `TaskInfo[]`, oldest first |
   | `GET /api/tasks/{id}` | `tasks_get` | `TaskInfo` (state, progress, result) |
   | `POST /api/tasks/{id}/cancel` | `tasks_cancel` | `{cancelled}` |

   An unknown job is 404 `queue.unknown_job`, an action the job's state does not allow 409
   `queue.job_state` (the contract's handlers), an unknown task 404 `tasks.unknown`. A cancel
   answers when the cancelled jobs have stopped, as `QueueService.cancel` returns. The state
   changes also arrive as events (S-3); a 204 action has nothing else to say.
2. **Global resume and cancel are added**: `POST /api/queue/resume` and `POST /api/queue/cancel`
   (every job that has not ended). The feature list and the CLI need them; the core has them
   (`resume()`, `cancel()` without an id).
3. **Adding jobs.** Every check runs before the first job is added, so a refused request adds
   none: `attach` first, then each job's output path, then `security.jail_job` for each job.
   A job whose `output.path` is not set is refused with 422 `output.no_path` (the detail names
   `jobs[i]`): the queue would name its output when it runs, after the jail. The queue's own
   validation is not a refusal: a job with errors is added `failed` with its issues, as
   `QueueService.add` does for every front end, so C-17's `RemoteQueue` behaves like
   `QueueService`. With `position` p, job i goes to p + i, so the jobs stay together in their
   order.
4. **`attach`** is accepted in the body. A non-null value is refused with 409
   `queue.attach_unknown_client` unless `hub.client_open(attach)`; until S-7 that is never true.
5. **The queue snapshot is an object** (`{jobs}`), not a bare list, so that queue-wide state
   can be added without breaking clients. The core has no public "the queue is taking jobs"
   state yet (the UI's Start / Stop button and S-7's idle exit need it); that is a core change.
6. **The log is read by byte offset.** `from` is the byte where the answer starts; `next` is
   the `from` of the next request; `more` says that the answer was cut at 1 MiB
   (`LOG_CHUNK`) and more is already written. A UTF-8 character cut at the end (by the limit
   or by a write in progress) is not sent; it comes whole in the next answer. A log that does
   not exist yet is an empty answer, not an error. The file is read in a worker thread.
7. **The when-done route cancels a countdown the user no longer chose.** After the setting is
   saved (`settings.update`), a running countdown whose action is not the new value is
   cancelled. This answers 0037's open point and goes one step further: also a change to
   *another* power action (shut down → sleep) cancels the shut-down countdown, because the
   action the user no longer wants must not run. The new action applies when the queue next
   finishes. The same setting changed through `PUT /api/settings` does not do this; the right
   place for both is the facade's settings-change hook (`Reframe._settings_changed`), a core
   change for the lead. This route's two extra calls can then go.
8. **Handlers with more than one facade call:**
   - `duplicate`: `queue.get` + `queue.add`. The core has no copy; the copy is a new job, so it
     is validated and jailed again. The jail runs again because the saved queue may hold a job
     from a run with other roots (desktop mode allows every path). The copy goes right after the
     original.
   - `log`: `queue.get` + `queue.log_path`. `log_path` answers for any id, so the route first
     checks that the job exists (404 otherwise) and never builds a file path from an id the queue
     does not hold.
   - `set_when_done`: `settings.update` + `power.pending` + `power.cancel(id)` (item 7). The
     countdown is cancelled by its id, so a countdown that starts in between is not touched.
   - `tasks_cancel`: `tasks.get` + `tasks.cancel`, because `cancel` says `False` both for an
     unknown task (404) and for one that has ended (`{cancelled: false}`).
   - `add`: `queue.add` once per job of the request.
9. **Not exposed**, with the reason (for the S-2 facade coverage list):
   - `QueueService.wait`: a client follows the `job.state` events or reads the snapshot. A
     request held open until jobs end would hold a connection for hours. C-17's `RemoteQueue`
     builds `wait` on the event connection.
   - `QueueService.close`, `PowerService.close`, `TaskManager.close`: the app's lifespan closes
     the facade (`POST /api/system/shutdown` in desktop mode).
   - `PowerService.schedule`: only the queue starts a countdown. No client may shut down or
     suspend the server's machine on demand.
   - `PowerService.executor`, `countdown`, `closed`: the countdown's length and end are in
     `pending.seconds_left` and `pending.deadline`; the executor is the operating system's
     mechanism.
   - `TaskManager.start`: a route that runs a long operation starts its own task; a client
     cannot run code.
   - `TaskManager.value`: the Python value; `TaskInfo.result` is its JSON.
   - `TaskManager.wait`: the `task.done` event, or `GET /api/tasks/{id}`.
   - `TaskManager.limit`, `set_limit`: the concurrency per task kind is internal; no setting
     changes it.

## Consequences

- S-7 builds on `attach` and `start(job_ids=…)`: the check runs before any job is added, but
  `queue.add` awaits, so S-7 must register the added jobs with the client and handle a
  connection that closed while they were added (cancel them, as a closed connection does).
  `start(job_ids=…)` already starts only those jobs (tested through the route).
- F-14's when-done selector needs no cancel call of its own; the countdown dialog's Cancel is
  `POST /api/power/cancel`.
- A queue answer holds every `QueueJob` field, also `log_path` and the plan's file paths in the
  data folder. No client needs them (the log has its route); hiding them is a server-model
  change, left to the review.
- Easy to change: the log chunk (`LOG_CHUNK`), the 201 / 204 codes, the when-done cancel rule
  (one condition in `set_when_done`).

## Plan changes

- [06](../plan/06-web-app.md) §S-2: the Queue rows (global resume and cancel, the snapshot
  object, the log offsets, the when-done countdown rule), the Power row (the answer shapes),
  the Tasks row (`?kind=`, 404 `tasks.unknown`).

## Follow-up (review), 2026-10-22

**Finding** (R-11 of [0052](0052-m3-server-review.md)): task answers (`GET /api/tasks`,
`GET /api/tasks/{id}`) and queue answers named the server's own folders. A `frames` task's
result holds each PNG's path in the cache folder, a `preview_clip` result the clip's, and every
`QueueJob` its `log_path` in the data folder. Checked while fixing: the plan's file paths
(chapters, 2-pass statistics) lie next to the output, not in the data folder, so the note in
"Consequences" above is wrong on that point.

**Decision**

1. **The rule lives where an answer leaves the server**, not in each task that makes a result.
   `hide_server_folders(reframe, value)` (`reframe_server/folders.py`, for every answer and, later, the event hub) writes the facade's config,
   data and cache folders as `<config>`, `<data>` and `<cache>` in every string of a JSON value,
   object keys too. The longest folder is matched first (on Windows the cache folder is inside
   the data folder), and a folder's text inside a longer name (`/srv/data2`, `/mnt/srv/data`) is
   another path and is kept. Why here: many places start tasks (the core's preview and fetch
   tasks, the routers' own), a result is free JSON, and the message and error texts name folders
   too (`tools_fetch` reports "Checking the build in <the data folder>…"; an unexpected
   exception's text can name any file). One rule at the answer also covers tasks added later.
   The answer keeps its shape (a path field still holds a string), and an administrator still
   sees where below the folder a file lies.
2. **Where it applies**: the whole `TaskInfo` of both task routes (message, error, result), and
   every `QueueJob` answer (snapshot, add, retry, duplicate) except the job's `settings`. They
   come back as the client sent them, because its editor loads them again, and desktop mode
   allows any folder. `log_path` reads `<data>/logs/<id>.log`; a client reads the log with
   `GET /api/queue/{id}/log`. The handlers keep their response models, so the OpenAPI document
   does not change.
3. **Every mode**, desktop too: one code path, and no client needs the folders (reveal in folder
   uses `output_path`).
4. **Not covered here**, for the lead:
   - The `task.progress` and `task.done` events carry the same `TaskInfo` (the event hub of
     [0047](0047-event-websocket.md) sends them unchanged). The hub needs the same function.
   - The job log's text is sent as written. Its command lines name the tool's path, which is in
     the data folder when FFmpeg was fetched there. `GET /api/system` and the `tools.changed`
     event show the same tool paths, so hiding them in the log alone would hide nothing.
   - 06's "Not exposed" table lists `Reframe.config_dir`, `data_dir` and `cache_dir`, and the
     facade coverage test fails when a route reaches a listed member. The queue and task routes
     now read them, only to hide them: the row changes with the lead.

**Tests** (rules of [m3-breakdown.md](../m3-breakdown.md), 0052's test-quality table):

- Added: a real `frames` task (FFmpeg) whose result names no cache path in either task route;
  a task whose message and result name the data folder next to paths that only share its text;
  the queue answers (add, snapshot, retry, duplicate) without the data folder; a job's own
  paths in a server folder come back as sent (desktop mode).
- Deleted: the `operationId` pins of `test_queue.py`, `test_tasks.py` and `test_power.py` (the
  rule test in `test_openapi.py` and the diff of `schema.d.ts` catch a renamed id). The two
  fake-jail tests: "every job goes through the jail" goes, because the jail sweep sends
  `queue_add` with an allowed job before the refused one and checks that neither is added;
  "duplicate goes through the jail" becomes a real-jail test with a saved job whose source is a
  link out of the media root (the sweep cannot send it: the request names no path, the path
  comes from the saved queue).
  Also deleted as covered elsewhere: an invalid job added `failed` (the core's queue tests);
  cancel all (the pause and resume test ends with it); a duplicate without an output path (the
  same check as the add test, and the duplicate jail test shows the check runs); five rows of
  the unknown-job table whose 404 is the core's error and the handler of `test_app.py` (the
  duplicate and log rows stay: those routes look the job up themselves); the when-done action
  after the last job (the core's when-done tests; the route's part is the saved setting).
