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

- **B1, a refused start (major).** `_send_start` only logged a refusal, so `wait` (and
  `encode`, `batch`) waited for ever when another front end removed one of the command's jobs
  before the start came. Now the refusal is kept (`queue.unknown_job` as `UnknownJobError`
  with the id that the problem names, `queue.job_state` as `JobStateError`, any other problem
  or a failed request as `RemoteError`); nothing starts (the server checks every id first);
  the next awaited call (`wait`, `cancel`, `pause`, `resume`, `retry`, `remove`, `reorder`,
  `add`) raises it once, and `close()` logs it. Tests: the contract case
  `test_a_start_of_a_job_that_left_the_queue_starts_nothing` (in-process the removal comes
  first and `start` raises at once; remotely the start request is held until the server
  removed the job; before: `TimeoutError` after 30 s),
  `test_a_start_refused_for_another_reason_is_raised_by_the_next_call` (503),
  `test_close_logs_a_start_the_server_refused`.
- **B2, jobs lost from the copy (major).** A `queue.changed` deleted every job that it did not
  list, also one that this client had just added or that a whole-queue read had brought. The
  copy now knows which jobs the event stream has shown: a `queue.changed` removes only those.
  A job of this client's add whose add event has not come yet is kept; a job of a whole-queue
  read that the stream has not shown and that a `queue.changed` leaves out makes the copy read
  again (this needs a read while events are on their way). Events that come before an add's
  answer keep the job pending until the answer fills it in; a removal that came first keeps it
  out, and a change that came first costs one read. `retry` returns its answer once the copy
  took the retry's event and writes nothing into the copy. I chose this over R1's "read on
  every unknown or missing job" because that adds a read to every add (B9). Tests:
  `test_a_job_it_just_added_stays_while_older_events_come` (events 30 ms late; before: added
  jobs missing from the copy 15 times),
  `test_a_job_of_a_whole_queue_read_stays_while_older_events_come` (before: `[False, True]`),
  `test_an_add_whose_answer_comes_after_its_events` (six rows; before: "a remove" brought the
  job back). R1's reproduction with `R1_LAG=0.03` now finds 0 of 10 jobs absent, and its CLI
  run of six files exits 0.
- **B3, the token in websockets' DEBUG log.** `connect()` gets websockets' client logger with
  DEBUG off (its frame lines); its other lines stay. `test_the_token_is_not_logged` (before:
  `> TEXT '{"type": "auth", "token": …}'`).
- **B4, the started owner's environment and messages.** The owner gets the client's
  environment without the server's own options (`owner.SERVER_OPTIONS`: host, port, mode, auth,
  token, the media and output roots, static dir, CORS origins, idle exit, owner-only, allowed
  hosts, parent pid; names in any case, as pydantic-settings reads them). Everything else is
  kept, so `PATH`, the tool paths, `REFRAME_ALLOW_SCRIPT_TOOLS`, `REFRAME_POWER_DRY_RUN` and
  the fake tools' variables reach it. Its three folders and `REFRAME_ENDPOINT_FILE` are the
  client's, as absolute paths: the owner runs in the data folder, where a relative value names
  another folder. Its stderr goes to `<data>/logs/server.log` (appended; emptied first above
  1 MiB), and a failed start's reason ends in "(see <that path>)" when the owner wrote there.
  Tests: `test_a_started_owner_that_fails_points_to_its_messages` (a real child with
  `REFRAME_AUTH=password` in the shell; before: only "exited with code 2"),
  `test_a_started_owner_has_the_clients_folders_as_absolute_paths`,
  `test_a_started_owner_leaves_out_every_option_of_the_server` (the set equals
  `ServerConfig`'s fields less the folders and the endpoint file, so a new server option fails
  it), `test_a_log_that_cannot_be_opened_does_not_stop_the_start`. Real run: `reframe encode`
  with `REFRAME_AUTH=password`, `REFRAME_TOKEN="SECRET-TOKEN-xyz "` and `REFRAME_PARENT_PID=1`
  exits 0; the owner's `REFRAME_*` variables are the three folders and the dry run.
- **B5, `REFRAME_ENDPOINT_FILE` read two ways.** One rule on both sides: blanks around the
  value are cut, and a blank value is not set. The client did this already; the server read
  `""` as `.`. `ServerConfig.endpoint_file` has a validator for it. Tests: the server's
  `test_the_endpoint_file_setting_is_read_as_the_client_reads_it` (empty, blank, padded; before:
  no file written, `'  '`, a path with spaces), the client's
  `test_the_endpoint_file_follows_the_servers_setting`.
- **B6, the token in messages.** A token that is not a header value (visible ASCII, spaces
  only inside) is refused: `find_owner` gives a `NoOwner` reason that names the file, and
  `RemoteQueue` raises `RemoteError` (`auth`) before it builds its httpx client; neither text
  holds the token. In other messages httpx's text has the token replaced by `<token>`, and an
  exception without text is named by its type. Tests:
  `test_an_owner_whose_token_cannot_be_sent_is_not_used`,
  `test_a_token_that_cannot_be_a_header_value_is_refused_unseen` (before: `connection.lost`
  with the token in the text), `test_a_token_that_is_not_ascii_is_refused` (before:
  `UnicodeEncodeError`), `test_a_request_that_fails_is_named_without_the_token`,
  `test_a_server_that_does_not_greet_is_named` (before: "cannot be reached: ").
- **B7, the lock probe: a known limit, not changed.** Not reproduced. Without the probe a
  client must start a server to learn that the lock is held (0.81–0.87 s until such a start
  exits 75, measured), or trust the pid in `queue.lock`, which a reboot makes wrong (pids are
  used again, and a live process of another program would look like the holder). The probe
  holds the lock for one non-blocking `flock` and its release. Owners that a client starts, and
  the desktop shell's sidecar once D-3 uses `find_owner`, take `server-start.lock` first and so
  never meet a probe; only a hand-started `reframe-server` or an in-process run that takes the
  lock in those microseconds exits 75 or gets a private queue with `queue.store_busy`. The
  probe writes its pid only into a lock that was free, which changes no message.
- **B8, events it cannot read.** The reader checks the message first: text that is not JSON,
  messages that are not events and events of a type it does not use are skipped (debug log);
  fields that the client does not know are left out before validation; an event of a used type
  that still cannot be read is skipped, and after a `job.state`, `queue.changed` or `resync`
  the whole queue is read. Any other failure of the reader is logged and reported as the end of
  the connection, so `wait` returns. Tests: `test_events_it_cannot_read_end_nothing` (before:
  the reader ended), `test_a_reader_that_cannot_go_on_ends_the_connection`.
- **B9, whole-queue reads.** The copy reads the whole queue only for what events do not carry:
  a run's end (output path, issues, plan), a retry that a claim failed, another front end's
  job (its settings), `resync`, an event it cannot read, and B2's rare case. An add's own
  events no longer read, and a waiting job's cancel is applied from its event (`finished_at`
  from this client's clock). Measured on 845 jobs (`GET /api/queue` 2.58 MB, one read
  0.22–0.39 s, of which the server's answer 0.17–0.27 s; a movie played, `nice -n 19`): before,
  an add 0.23–0.34 s and a cancel 0.22–0.36 s; after, an add 0.008–0.014 s (the first 0.10 s)
  and a cancel 0.003–0.008 s. Left: each connected client reads once per run end and once per
  add of another front end (adds that come during a read are in it); a route for one job
  (`GET /api/queue/{id}`) would make both cheap. Tests:
  `test_an_add_and_the_cancel_of_a_waiting_job_read_no_whole_queue` (before: 1 read), the
  "nothing" row of `test_an_add_whose_answer_comes_after_its_events` (before: 2).
- **B10, test gaps.** Each surviving mutant now fails a test: O2
  `test_the_health_check_does_not_send_the_token`, O8 `test_a_search_frees_the_start_lock`, R1
  the B1 contract case, R2 `test_a_reader_that_cannot_go_on_ends_the_connection`, R4
  `test_the_owners_countdown_is_followed_and_cancelled` (the client's countdown clears), R5
  `test_the_servers_folders_are_this_machines_in_every_text`, R6
  `test_a_server_that_stops_interrupts_its_running_and_paused_jobs`, R7
  `test_progress_does_not_change_a_job_that_ended`, R8
  `test_a_change_whose_event_does_not_come_is_read`, R9 `test_a_resync_reads_the_whole_queue`.
- **B11, nits.** `Owner.started` is removed (no caller). The copy maps `<data>`, `<config>` and
  `<cache>` back in every text the server hides them in (every field but `settings`, keys
  too); a file name that holds such a label changes as well. `when_done()` gives `"nothing"`
  when the settings do not say. The started owner's working folder stays the data folder: the
  owner keeps `queue.lock` and the database open there anyway, so it keeps nothing else busy,
  while the client's working folder is often on the media drive. The `CREATE_NO_WINDOW` path
  after a `PermissionError` has a row in `test_a_started_owner_is_detached_from_the_terminal`.
- Plan change: [05 §C-17](../plan/05-core.md#c-17-remote-queue-and-queue-commands), the
  result paragraph (what changes the copy, the refused `start`).


### The CLI

(Written by the fix agent of the CLI.)
