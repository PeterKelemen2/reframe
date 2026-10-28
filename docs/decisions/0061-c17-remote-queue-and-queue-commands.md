# 0061 — C-17: the remote queue, the owner search and `reframe queue`

- Status: accepted
- Date: 2026-10-28
- Steps: C-17 (and C-11 for the output claims); milestone M3b

## Context

[05 §C-17](../plan/05-core.md#c-17-remote-queue-and-queue-commands) builds
[0042](0042-one-scheduler-process-and-cli-clients.md) on the server side of S-7
([0056](0056-s7-owner-endpoint-file-and-idle-exit.md),
[0057](0057-s7-attachments-client-id-and-detach.md)). What we found while we built it:

1. **The contract is partly synchronous.** `QueueService.get`, `list`, `start` and `log_path`
   do not await, and the plan says that `QueueService` implements `QueueLike` unchanged. A
   client of a server cannot ask the server in a synchronous call. The server has no route
   for one job (`GET /api/queue` returns every job), and a `job.state` event carries no
   `output_path`, `issues` or settings.
2. **`Reframe.create()` starts encoder detection at once.** A command cannot know before it
   creates the facade whether it will be a client, and a client must run no detection of its
   own (0042 item 4). `JobService.draft` validates inside, and a validation of an encoder
   that was never detected starts a detection (`CapabilityService.wait`).
3. **`QueueService.stop()` stops the whole queue.** The CLI's Ctrl+C called it before it
   cancelled its own jobs. In a shared queue it also stops other clients' jobs. The plan's
   method list for `QueueLike` has no `stop`.
4. **The plan's owner command starts a web-mode server.** `python -m reframe_server
   --owner-only --idle-exit 30` binds loopback in web mode with no media or output roots, so
   the path jail refuses every job. 0042 item 3 says "desktop-mode rules: loopback, token,
   the user's whole file system".
5. **`launch_detached` returns only the pid.** The client needs the exit code of the server it
   started: 75 (another owner won) and 1 (no owner will come) mean different things (0056
   follow-up 1).
6. **Clients that start at the same time each start a server.** Ten `reframe encode` commands
   in an empty data folder started ten servers; nine exited 75. A client that tries
   `queue.lock` to see whether it is free holds it for a moment, and a server that starts in
   that moment also exits 75.
7. **What the client sees when the server goes** (websockets 17.3, uvicorn 0.54.0, measured
   with a real server, recorded in `testdata/README.md`): after `kill -9` of the server the
   client's `recv` raises `ConnectionClosedError` with no close frame (`rcvd` `None`, close
   code 1006) within 5 ms; after uvicorn's shutdown the close code is 1012 (0056 follow-up 4).
8. **Reading the saved queue without the owner** (SQLite 3.54.0, Python 3.14.8, recorded in
   `testdata/README.md`): `mode=ro` reads a WAL database, also while the owner writes it, and
   leaves `-wal` and `-shm` files when there were none; in a folder the user cannot write it
   fails with "attempt to write a readonly database", and `mode=ro&immutable=1` reads it.
9. **An incident while this step was built.** CLI tests that call `run_encode` directly (not
   through typer) ran in the new client mode and started real servers in their temporary
   folders. One test had set `queue.when_done` to `shutdown` in its temporary settings: the
   real server started a real 60-second shutdown countdown, and only the test's own Ctrl+C
   (which cancelled the countdown through the API) stopped it. The `PowerGuard` of the test
   plugin covers the pytest process only, not a server it starts.

## Decision

1. **`QueueLike`** (`reframe.queue.client`, exported by `reframe.queue`): `add`, `list`,
   `get`, `start(job_ids=…)`, `wait`, `cancel`, `pause`, `resume`, `retry`, `remove`,
   `reorder`, `log_path`, with `QueueService`'s signatures. `stop` is not in it, and the CLI's
   Ctrl+C no longer calls it: it cancels its waiting jobs, then its running ones, by id.
2. **The owner search** (`reframe.remote.find_owner`), in 0042 item 3's order:
   - `server.json` (`REFRAME_ENDPOINT_FILE` when set, as the server reads it) whose
     `GET /api/health` on `127.0.0.1` answers with the file's `instance` and this client's
     `api_version` is the owner. Another `api_version` is not used, and the reason names the
     version, the pid and both API versions. The client's `API_VERSION` is a constant of the
     core; a test checks that it equals the server's.
   - Else, for a command that may start an owner, the client takes `<data>/server-start.lock`
     (an OS lock, as `queue.lock`): one client starts the owner, the others wait for its
     endpoint. Only the holder looks at `queue.lock` (it takes it and frees it at once). Free:
     it starts `python -m reframe_server --mode desktop --host 127.0.0.1 --port 0
     --owner-only --idle-exit 30` (a frozen CLI: the frozen `reframe-server` next to it)
     through `launch_detached`, and waits at most 10 s. Exit 75: another owner won, its
     endpoint is waited for. Another exit code: no owner, the reason names the code. Held, with
     no endpoint that answers: an owner that is starting or in its exit window is waited for at
     most 5 s, then the holder is "another Reframe process (pid N)".
   - The started owner's handle comes from a `popen` passed to `launch_detached`; its reaper
     thread sets the exit code. On Windows the owner also gets `CREATE_NO_WINDOW`, so it does
     not end with the terminal's console.
   - `reframe queue list` and `log` look only at `server.json`: no lock, no start.
3. **`RemoteQueue`** (`reframe.remote.queue`): `connect` opens `WS /api/events` (it keeps an
   idle owner running), reads `client_id` from the hello, then `GET /api/queue` and
   `GET /api/power`.
   - A copy of the queue answers `get` and `list`. Only the event stream changes it, in the
     order the server sent the events. A job it does not know, or a job that ended, makes it
     read the whole queue (with the copy's lock held, so the answer is newer than every event
     applied before it). An event that is older than such a read can move a job only between
     states that have not ended; only a retry leaves an end.
   - A call that changes a job returns once the copy shows the change (at most 10 s, then the
     whole queue is read). `start` sends its request in the background; the next awaited call
     and `close` wait for it.
   - `add` attaches the job to the connection. `close(detach=True)` sends `{"type":
     "detach"}`, then closes with a handshake.
   - `events` forwards `job.state`, `job.progress`, `queue.changed`, `power.countdown` and
     `resync`, after the copy took them. When the connection ends without `close`, the copy's
     running and paused jobs become `interrupted`, `events` closes, `wait` returns and other
     calls raise `RemoteError` (`connection.lost`). `log_path` and `output_path` that the
     server wrote as `<data>/…`, `<config>/…` or `<cache>/…` are this machine's folders again.
   - The problems map to the queue's errors: `queue.unknown_job` → `UnknownJobError`,
     `queue.job_state` → `JobStateError`, the rest → `RemoteError` with the problem's code.
4. **Client mode of `encode` and `batch`.** The facade is created without encoder detection;
   the command starts it only when its jobs run in-process. A client drafts and names its jobs
   here, as `JobService.draft` does (`OwnerJobs`: `draft_from_preset`, `name_job`), and the
   owner validates them (`POST /api/jobs/validate`); `batch` gets a `BatchService` whose
   validation is the owner's. The command prints `Queue: Reframe V (pid N), shared with the
   other Reframe programs of this data folder.` The when-done countdown is the owner's: its
   setting (`GET /api/settings`) and its countdown events; Ctrl+C cancels it through the API.
   `batch --dry-run` validates in-process, as `reframe plan` does (neither touches the queue).
5. **Attached, `--detach`, `--in-process`.** The jobs are added at the end of the queue in
   every mode, attached by default. `--detach` adds them, starts them, prints `[n/N] job ID`
   and `Detached: …`, and ends with 0 (1 when a job was not queued); it needs an owner (exit 1
   with the reason) and cannot be combined with `--in-process` or `--dry-run` (exit 2).
   `--in-process`, also as `REFRAME_IN_PROCESS=1` (for scripts and the CLI tests), is 0027's
   queue. When no owner can be used the command says why on one `warning:` line and runs the
   jobs in-process; the core's `queue.store_busy` follows when the store is busy.
6. **A server that goes away while a client follows its jobs.** The client reports its running
   jobs `interrupted` and ends with 1. Its waiting jobs stay waiting in the saved queue, not
   started (attachments are not saved); the error line names them and says how to start
   (`reframe queue retry ID`) or cancel them. The client does not start a new owner for them.
7. **Output claims** (0042 item 6) in `QueueService.add` and `retry`: under the queue's lock,
   so two adds of one output at once queue one. Keys of restored jobs that are still being
   taken in the background are taken first. A claimed retry makes the job `failed` with the
   issue (an expected failure is data, not an exception); a retry that passes drops the old
   claim issue. The runner's check that keeps two such jobs from running at once stays, for
   stores that an older Reframe saved; its tests set that up through a restored store.
8. **`reframe queue`.** `list [--json]` and `log ID [-f]` use the owner when one answers, else
   the saved queue read-only (`read_saved_queue`: no lock, no restore, nothing started; a job
   that was running when its owner stopped still says `running`). `pause|resume|cancel [ID…
   | --all]`, `retry ID` and `remove ID` need an owner and start one when none runs. `retry`
   also starts the job. A job is named by its id or any start of it that names one job; `list`
   shows 8 characters. Exit codes: 0, 1 (no such job, a refused action, no owner), 2 (usage).
   `log` reads the log file (the client and the owner share the data folder).
9. **Tests never reach the owner's folders or start a server from pytest**
   (`reframe_testing.folders_guard`, autouse): the queue lock, the owner search and a started
   server fail a test in the platform's default folders and in the folders of the session's
   environment, and a test that would start a real server from the pytest process fails. The
   real-process tests start the CLI as subprocesses with private folders and settings whose
   when-done action is "nothing", and kill the servers of their folder at the end.

## Consequences

- Two terminals, a CLI and an open UI share one scheduler; the `parallel_jobs` limit, the
  output claims and the when-done action hold across them.
- A job's end costs each connected client one read of the whole queue. A route for one job
  (`GET /api/queue/{id}`) would make that cheaper; not needed now.
- `reframe queue log` reads the file, not `GET /api/queue/{id}/log`: the same data folder is
  the condition of the local token anyway.
- The waiting jobs of a client whose server went away stay unstarted until someone starts or
  cancels them; until then they claim their outputs, so the same command run again reports
  those files `queue.output_claimed`.
- Not verified on Windows: the detached owner (`CREATE_NO_WINDOW`, breakaway; unit-tested with
  mocks), the start lock (`msvcrt` locking), the real-process tests (skipped there).
- D-3 can use `reframe.remote.find_owner` with its own `launch`.

## Plan changes

- [05 §C-17](../plan/05-core.md#c-17-remote-queue-and-queue-commands): the items ticked, the
  owner command with desktop mode, and a result paragraph.
- [05 §C-11](../plan/05-core.md#c-11-queue-and-job-runner): the output-claims sentence says it
  is built.

## The lead's checks (2026-10-28)

Before the merge into `m3b-shared-queue`, on the step's branch at e729196:

- `ruff check`, the format check, `mypy` (Linux and `--platform win32`) and
  `scripts/gen-api.sh --check` pass. Tests: the server and `testing` suites 746 passed and
  4 skipped; `tests/remote` with `tests/queue` 373 passed; `tests/jobs`, `tests/platform` and
  the CLI tests 462 passed.
- The lead's five mutations; four were caught:
  - L2, a `server.json` of another run on the port is used:
    `test_a_file_of_another_run_on_the_port_is_stale`;
  - L3, the server's `<data>/…` paths are not mapped back: the contract suite
    (`test_start_with_job_ids_runs_only_those[remote]`);
  - L4, `--detach` with `--in-process` is accepted: `test_detach_needs_the_server`;
  - L5, a claimed source is reported as a claimed output:
    `test_an_in_place_edit_of_a_waiting_jobs_source_is_added_failed`;
  - **L1 survived**: `retry` without `_take_missing_keys()`, so a restored job whose keys are
    still being taken claims nothing against a retry. Sent to the fix round.
- Checks 1–7 again with the lead's own script. It ran this branch's `reframe` CLI as
  subprocesses, the servers they started and `/usr/bin/ffmpeg` n9.0.2, with private folders
  and `REFRAME_POWER_DRY_RUN=1`:
  1. Both clients exit 0. Each output names only its own file (10 progress lines each). The
     second job started 1.7 ms after the first ended. One owner.
  2. SIGINT: exit 130, its job `cancelled`, no `.part` left. The other client's job then
     ends `done` (exit 0).
  3. After `kill -9` of the attached client, its job is `cancelled` and its `.part` is
     removed. The `--detach` job is still `running` 3 s later (49 %); `reframe queue cancel`
     with an 8-character id prefix then cancelled it.
  4. `kill -9` of the server (the pid in `server.json`): the client exits 1 with
     `[1/1] interrupted`. The saved queue, read without an owner, says `running`. The next
     `reframe encode` started a new owner, and the job became `interrupted` ("Reframe stopped
     while the job was running.").
  5. Ten `encode --detach` at once: all exit 0; 10 jobs, 10 ids, 10 sources; one owner.
  6. The third client exits 1 with `[queue.output_claimed · output.path]`, and its job is
     `failed`. The `--detach` job stays `waiting`. The client also printed `Queued 1 job.`
     for that failed job (a nit, sent to the fix round).
  7. A server with `api_version` 2: the client ran the job in-process (exit 0) after two
     warnings: the API versions, then `queue.store_busy`.

  Every process was ended and the folders were removed.
- The incident (Context item 9): `launch_detached` passes no `env`, so the started server
  inherited the test's environment with `PYTEST_CURRENT_TEST` set. When the countdown ended,
  `reframe.platform.power.refusal()` would have refused `systemctl poweroff`. Checked: a
  process that a test started through `launch_detached` read
  `PYTEST_CURRENT_TEST='…::test_a_detached_child_sees_the_running_test (call)'`, and its
  `power.refusal()` returned "refused: a test is running (PYTEST_CURRENT_TEST is set)". The
  fix round also sets `REFRAME_POWER_DRY_RUN=1` in the real-process tests.

## Follow-up: the review fixes

Two reviews of the merged step (R1: the core, R2: the CLI; 2026-10-28) and the lead's checks
above. [0062](0062-c17-review.md) lists every finding and its outcome. Three fix agents
worked on separate files; each wrote its own part below.

### The queue core

(Written by the fix agent of the queue core.)


### The remote client

(Written by the fix agent of the remote client.)


### The CLI

(Written by the fix agent of the CLI.)
