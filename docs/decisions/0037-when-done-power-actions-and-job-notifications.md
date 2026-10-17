# 0037 — When done: power actions through C-14, the countdown's life, job notifications

- Status: accepted
- Date: 2026-10-15
- Steps: C-11, C-14 (affects C-15 `reframe encode`, S-2 `PUT /api/queue/when-done`, S-3, F-14,
  the desktop notifications of 07)
- Supersedes in part: [0016](0016-queue-and-job-runner.md) §9 (the power actions: "an
  `app.warning` `queue.when_done_unavailable` says that nothing was done")

## Context

The plan says what, not how:

- 05 §C-11: "When-done actions through `platform/`."
- 05 §C-14: "Power actions: shut down, sleep (…). Always after a cancellable 60 s countdown
  event." and "Notification hook: emits an event only. The UI layer shows the notification."
- 03 §Queue: "**When done**: nothing · notify · quit · sleep · shut down (desktop and
  bare-metal only)." 03 §Settings → Queue: "Parallel jobs, when done, sleep inhibit,
  notifications". 07 §Native integrations: "Notifications (job done, queue done, error)".
- 0016 §9 fixed **when** the action runs: once, when the queue empties after a job ended on
  its own (done or failed); not when the user cancelled the last job or Reframe closed.

The power service itself (`Reframe.power`, `schedule(action, *, reason) -> countdown id`,
`cancel(countdown_id)`, `pending`, `close()`; the countdown events and the OS calls) is C-14's,
built in parallel (task 1f, decision 0036). The queue gets it as `QueueService(…, power=…)`.

Open questions the plan does not answer:

1. What happens to a running countdown when new work starts, when the queue closes, and when
   the when-done setting changes?
2. Does the action run when the last job failed?
3. What does the Notifications setting cover, next to the `notify` action, without sending the
   same news twice?
4. Which jobs get a notification, with what text, and where does it go in a run's events (0016
   §10: the end `job.state` is the last event of a run, and the C-11 "Done when" test and the
   fault tests check that)?

No tool behaviour is involved: the queue only calls the power service and the notification
hook. Nothing is recorded in `testdata/README.md` for this step.

## Decision

1. **The power actions.** `quit`, `sleep` and `shutdown` go to
   `power.schedule(action, reason="3 jobs done, 1 failed")` once, when the queue empties
   (0016 §9's rule, unchanged). The power service publishes the 60 s countdown
   (`power.countdown`) and runs the action at its end; `quit` only publishes `executing`.
   The reason is the batch summary, as in the `notify` text without the full stop. The action
   is taken before a `wait()` for the batch's last job returns, so a front end (C-15's `reframe
   encode`) finds the countdown in `Reframe.power.pending` at once.
   - Without a power service (`power=None`): `app.warning` `queue.when_done_unavailable`
     ("The queue is finished (1 job done). When done: “Sleep” is not available here, so
     nothing was done.").
   - A power service that raises in `schedule` (a bug): `app.warning`
     `queue.when_done_failed` ("… “Shut down” could not be started, so nothing was done.",
     detail: the exception). The queue goes on and `wait()` still returns. A `cancel` that
     raises is logged and ignored.
2. **The countdown's life.** The queue keeps the id of the countdown it started and cancels
   only that one (`cancel(id)`, never `cancel()`):
   - **New work starts**: when the runner takes a job (one added or retried while the queue
     runs, or `start()`), before the job's run begins. A job that is only added to an idle
     queue (after `start(job_ids=…)` went idle) is not new work until it starts.
   - **`close()`**: first thing, before any await, so no when-done action runs after it.
     (`Reframe.close()` closes `power` before the queue; a job that ends on its own in
     between could start a countdown, which the queue's `close()` then cancels.)
   - **A change of the when-done setting does not cancel it.** The queue reads the setting
     only when it empties and has no settings hook; the countdown is the moment of the action
     and has its own Cancel (`Reframe.power.cancel()`, the countdown dialog). The front end's
     when-done selector (S-2 `PUT /api/queue/when-done`, F-14) should cancel a running
     countdown when the new value is not a power action. Easy to change: the facade's
     settings-change hook could call `power.cancel()`.
   - The user's own cancel is final for that batch: the queue never starts it again. The
     next batch (jobs that end after new work started) has its own countdown.
3. **The last job failed: the action runs.** Done or failed both count as "ended on its own"
   (0016 §9). The user who sets "shut down" for the night wants the computer off in the
   morning; a failed job does not need it on (its log and the queue are kept, and it can be
   retried). This holds when every job failed, too ("0 jobs done, 2 failed").
4. **The batch.** The counts (done, failed) cover the jobs that ended since the queue last
   emptied. When the queue empties and its last job was cancelled by the user, no action runs
   and the counts start again from zero (0016 kept them, so a later run said "4 jobs done"
   for one job). Stopping the queue with jobs left keeps the batch open: the counts go on
   after `start()`.
5. **Job notifications** (`settings.queue.notifications`, default on, read when a run ends):
   a job that **ended on its own** gets one `notification` with its `job_id`:
   - `done`: "Job done", the output's final file name (after a collision rename:
     "Movie (1).mkv"), level `success`;
   - `failed`: "Job failed", "<source file name>: <the job's error>", level `error`;
   - cancelled by the user, interrupted (close, restart) and added as `failed` (never ran):
     none. The user did it, or nothing ran.

   The notification comes when the run's files are handled (the output has its final name),
   **before the run's last `job.log` batch and its end `job.state`**: the end state stays the
   last event of a run (0016 §10). A UI reads the job when it shows the notification, not
   when it gets it, so the order does not matter there.
6. **`notify` and Notifications are independent; nothing is sent twice.** Notifications
   covers the jobs (job done, error); the `notify` action covers the queue (queue done), so
   together they give 07's "job done, queue done, error".
   - `notify` sends "Queue finished" ("3 jobs done, 1 failed.", level `success`, or
     `warning` when a job failed, no `job_id`) also when Notifications is off: the user chose
     it.
   - It is **left out when the batch was one job whose own notification was sent**: "Job
     done: Movie.mkv" and "Queue finished: 1 job done." at the same moment say the same.
   - A power action sends no "Queue finished": its countdown is the queue-done signal.

## Consequences

- C-15 (`reframe encode`, task 1h): after `queue.wait(ids)` returns, `app.power.pending` is the
  countdown that its jobs started (if any); Ctrl+C cancels it with `app.power.cancel()`.
- S-3 sends `notification` and `power.countdown` events as they are. A job's notification
  comes just before its end state.
- The C-11 "Done when" test and the fault tests are unchanged and pass (no job event after the
  end state).
- The defaults are easy to change, each in one place of `reframe/queue/whendone.py`: the
  failed-last-job rule (`emptied`), the one-job de-duplication (`emptied`), the job texts
  (`job_ended`), the cancel points (`work_started`, `close`).
- Tested with a fake power service that only records (never a real power call), on the fake
  ffmpeg. Two tests run the queue with C-14's real `PowerService` and a recording executor;
  they skip while the service is the contract stub and run once 1f is merged.
- Revisit with S-2: whether the server's when-done route cancels a running countdown (item 2).

## Plan changes

None: the plan's when-done list, the 60 s countdown and the notification hook stay as they
are; this record fills in what the plan leaves open. 0016 §9's power-action part is replaced
by items 1–4.
