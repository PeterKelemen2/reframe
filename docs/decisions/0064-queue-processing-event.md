# 0064 — The queue-processing event

- Status: accepted
- Date: 2026-10-29
- Steps: C-11, C-17, S-2, S-3 (M4 task S; [m4-breakdown.md](../m4-breakdown.md))

## Context

[0042](0042-one-scheduler-process-and-cli-clients.md) open question 5: a global Stop from the
UI also stops the waiting jobs of a CLI. The default is that the CLI says "the queue was
stopped by another front end" and goes on waiting (Ctrl+C cancels). It was not built, because
no event told a client that the queue was stopped ([0061](0061-c17-remote-queue-and-queue-commands.md),
"The CLI" C8; [0062](0062-c17-review.md) R2 F8). The M4 breakdown gives the contract: the
event `queue.processing` (`processing`, `only`, `reason`), `QueueService.processing` and
`only`, the same two fields in `GET /api/queue`, and the CLI's line.

What we found in the code (main at 1054a64):

1. **The state was private and idle was late.** `QueueService._processing` and `_only` were
   set by `start` and `stop`. `_schedule()` set them back when the jobs of a
   `start(job_ids=…)` had all ended, but `_schedule()` runs only on an add, a start, a retry,
   a reorder, the end of a run and the arrival of a restored job's keys. A waiting job that was
   cancelled or removed, or a restored job that its late output claim failed, left the runner
   "processing" for jobs that no longer waited, until something else called `_schedule()`.
   (`busy` was right already: it checks for a job the runner can take.)
2. **What an older client does with the new event and the new snapshot fields**, checked on
   2026-10-29 with the real code. `reframe/remote/queue.py` of main (taken with `git show`,
   loaded as it is) connected to a real `reframe-server` of this branch (desktop mode, private
   folders, `REFRAME_POWER_DRY_RUN=1`, FFmpeg n9.0.2). It added a job of
   `testdata/media/chapters.mkv`, started it, and followed it to `done`. Then a global start
   and a stop were sent through the API. The four `queue.processing` events (its start, its
   idle, the start, the stop) were each skipped with its debug line "skipped a
   'queue.processing' event" (`_decode` skips a type that it does not use). Its whole-queue
   read of the new snapshot (keys `jobs`, `only`, `processing`) took the jobs and ignored the
   rest (`answer.get("jobs")`). `lost` stayed `None`. The server process was ended and the
   folders removed.
3. **The frontend** is served by its own server (S-4) or comes with its own sidecar (D-3, not
   built). The generated client does not check answers at run time.
4. **A race.** `encode` and `batch` subscribe to the events before they add their jobs, then
   send `start(job_ids=…)`, then follow. A Stop that reaches the owner between the add and the
   start has its event before the start's event in the stream. The command's start then runs
   the jobs, but a command that reacts to the stop event alone says that they wait. The stream
   has no position that the start's HTTP answer could be compared with, and a start that
   changes nothing (the queue already takes every job) has no event.

## Decision

1. **The event.** `reframe.models.events.QueueProcessingEvent`, in the `Event` union after
   `queue.changed`: `type: "queue.processing"`, `processing: bool` (the runner takes waiting
   jobs), `only: list[str] | null` (only these jobs, the ones a `start` with `job_ids` named,
   in the order they were named; `null`: every waiting job, or not processing), `reason:
   "start" | "stop" | "idle"`. Every field except `type` is required, so the generated
   TypeScript type is the breakdown's interface. An id in `only` can name a job that has left
   the queue since; it stays until the runner goes idle (a front end matches `only` with its
   jobs).
2. **`QueueService.processing` and `only`** (running state, not saved). One method changes
   them and publishes the event only when the pair changes:
   - `start()`: reason `start`. A `start(job_ids=…)` while the runner takes only some jobs
     adds its ids. A start that changes nothing (the runner already takes every job, or the
     ids are already named) publishes nothing. A start whose named jobs have all ended
     already publishes `start`, then `idle`.
   - `stop()`: reason `stop`; nothing when the runner was not processing.
   - **Idle** (reason `idle`): when no job that a start named is waiting, running or paused.
     This is checked after a run ends (as before), and also at once after a waiting job is
     cancelled, after a job is removed, and after a restored job fails its late output claim.
     So the event comes when the last named job ends, however it ends.
   - `close()`: no event. `processing` becomes false and `only` null.

   Order: `idle` comes after the end state of the last named job and before a when-done
   countdown; `start` comes before the jobs it takes start running.
3. **Server.** `QueueSnapshot` (`GET /api/queue`) has `processing` and `only` (both required),
   read in the same step as the jobs. The event goes out over `WS /api/events` as it is: the
   hub sends every core event, and only progress and log events are throttled. The bus never
   drops it (it is not one of the lossy types).
4. **`API_VERSION` stays 1.** The change only adds an event type and two snapshot fields, and
   an older client works with both (Context 2), so no client of an earlier version breaks,
   which is the rule of `reframe_server.api.API_VERSION`. A newer client with an older owner of
   the same API version gets no `processing` in the snapshot (`RemoteQueue` reads "not
   processing") and no event, so the CLI waits without a word, as before (a test covers the
   snapshot). A bump would make the CLI of the previous version fall back to a private
   in-process queue with `queue.store_busy` next to a newer owner, for nothing. A later change
   that removes or renames a field or an event type, or changes what a value means, bumps it.
5. **`RemoteQueue`** forwards `queue.processing` in `events` and keeps `processing` and `only`
   in its copy: from the snapshot, then from the events in order. An owner that does not say
   means "not processing". An event of this type that cannot be read makes it read the whole
   queue, as for `job.state`. `refresh()` reads the whole queue on request. **`QueueLike`
   does not change**: only the client mode of the CLI needs the state, and it has the
   `RemoteQueue` (`QueueSession.remote`). In-process no other front end can stop the queue, and
   the command never calls `stop`.
6. **The CLI** (`encode` and `batch` in client mode, while they follow their jobs). On a
   `queue.processing` event with reason `stop` (its `processing` is false), when one of the
   command's open jobs waits and the copy shows that the queue does not take it, the command
   reads the whole queue from the owner (`refresh`). That read is sent after the command's own
   start was answered, so it rules out the race of Context 4. When a waiting job of the
   command is still not taken (not processing, or `only` without it), the command prints one
   line through its progress view and goes on following:

   ```
   The queue was stopped by another front end: the waiting jobs of this command start when it is started again (Ctrl+C cancels them).
   ```

   A read that fails prints nothing (a lost connection ends the follow as before). `start` and
   `idle` events print nothing, and so does a stop when no job of the command waits. Ctrl+C
   cancels the command's jobs as before. A later global Start (the UI's) runs them. Another
   CLI's `start(job_ids=…)` runs only its own jobs (0042 item 5), so the command waits until a
   global Start. `--detach` does not follow, so it prints nothing.
7. **Persistence.** No persisted document holds an event or the snapshot: events are running
   state and `QueueSnapshot` is an answer. The new `Literal` (`reason`) and the new union
   member (`Event`) are not in a settings, preset, queue or probe-cache file. So
   `schema_version` and the migrations do not change.

## Consequences

- **The frontend (task B, the queue store).** `GET /api/queue` gives `processing` and `only`;
  `onQueueProcessing(e)` sets them from each event. A resync reads them again with the jobs.
  `api/types.ts` can make `QueueProcessingEvent` `Schemas['QueueProcessingEvent']`, and it is
  now a member of `ReframeEvent` (the regenerated `schema.d.ts`). A queue run that a CLI
  started shows as `processing: true` with `only` set to the CLI's jobs. `only` can hold ids
  of jobs that left the queue. A server restart, or the start of a desktop app's sidecar,
  begins with `processing: false`. An event type that the store does not know should be
  ignored, as `RemoteQueue` does, so that a newer server with the same API version breaks
  nothing.
- **The Stop button (task K).** `POST /api/queue/stop` is the global Stop: running jobs go on,
  waiting jobs (also those of CLIs) are not taken, and each connected `reframe encode` or
  `batch` with a waiting job prints the line above. `POST /api/queue/start` without `job_ids`
  takes every waiting job again, also the CLIs' jobs. The button's state comes from
  `processing`. With `only` set, the queue runs only those jobs (a CLI's run); a Start without
  ids widens it to every job.
- Each connected CLI with a waiting job reads the whole queue once per stop (on 845 jobs one
  read was 0.22–0.39 s, 0061 B9). A stop is a user's action, so this is rare.
- The event also tells why the queue went idle, so an activity log can show "the jobs of a
  start ended" without guessing from job states.

Tests (each checked with a mutation of the code it tests; every mutation was caught):

- Core, `tests/queue/test_queue.py`: `test_each_change_of_what_the_queue_takes_is_published`
  (start, a start that adds ids, no event for a start that changes nothing or a second stop,
  idle after the last named job's end and before the next run; the "Done when" of task S),
  `test_a_start_goes_idle_when_its_waiting_job_is_cancelled_or_removed`,
  `test_close_publishes_no_change_of_what_the_queue_takes`; `tests/queue/test_output_claims.py`:
  `test_a_start_of_a_restored_job_that_its_keys_fail_goes_idle`.
- Server, `tests/test_queue.py`: `test_the_snapshot_says_which_waiting_jobs_the_queue_takes`.
- `RemoteQueue`, `tests/remote/test_remote_queue.py`:
  `test_the_copy_says_what_the_owners_queue_takes`,
  `test_a_refresh_reads_what_the_queue_takes_without_its_event`,
  `test_a_processing_event_it_cannot_read_reads_the_whole_queue`,
  `test_an_owner_that_does_not_say_what_it_takes_is_not_processing`.
- CLI, `tests/remote/test_cli_client.py`:
  `test_a_stop_by_another_front_end_is_reported_and_a_later_start_runs_the_job`,
  `test_a_stop_while_none_of_its_jobs_waits_is_not_reported`,
  `test_a_stop_just_before_the_commands_own_start_is_not_reported` (the race: without the
  read the line is printed), `test_a_stop_that_cannot_be_checked_with_the_owner_ends_nothing`.
- Real processes, `tests/remote/test_shared_queue_real.py`:
  `test_a_stop_by_another_front_end_is_reported_and_the_jobs_wait_for_a_start`. Two
  `reframe encode` clients wait behind a `--detach` job (one slot). The test sends
  `POST /api/queue/stop` as the UI does, and both clients print the line. The busy job is
  cancelled, and both jobs still wait 1 s later. SIGINT to one client cancels its job (exit
  130). `POST /api/queue/start` runs the other client's job to `done` (exit 0).

## Plan changes

- [02 §Events](../plan/02-architecture.md#events): the `queue.processing` row.
- [05 §C-11](../plan/05-core.md#c-11-queue-and-job-runner): a paragraph on `processing`,
  `only` and the event.
- [05 §C-17](../plan/05-core.md#c-17-remote-queue-and-queue-commands): a paragraph on the
  CLI's line.
- [06 §S-2](../plan/06-web-app.md#s-2-rest-api): the queue snapshot `{jobs, processing, only}`.
- [0042](0042-one-scheduler-process-and-cli-clients.md) open question 5: a dated pointer to
  this record.
- [../status.md](../status.md): the C-17 row.
