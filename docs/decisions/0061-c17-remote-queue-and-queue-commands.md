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

- **Every `add` and `retry` waited on the share of a restored job without keys** (R1 B1). Each
  call took the keys of every waiting job that had none yet, in a new worker thread: a share
  that did not answer held every add (the owner's `POST /api/queue` too) and left one more
  blocked thread per attempt. Changed, of R1's suggestions the comparison without I/O and a
  check when the keys arrive: `add` and `retry` take only their own job's keys (a share that
  does not answer holds back only the jobs that use it). A job whose keys are still being taken
  is compared by its paths as written (`os.path.abspath`; `same_key` already ignores case), so
  the same spelling is claimed at once. When a restored job's keys arrive, it is checked
  against the jobs added or retried since the queue opened, and **it** fails with
  `queue.output_claimed` if one of them claims its file through a link or another spelling: it
  has not started (a job without keys is never taken), while the other job may already run.
  Restored jobs are still not checked against each other (a store of an older Reframe; the
  runner keeps such a pair apart). Waiting briefly for the job's own key task was not chosen:
  every add would then wait while a share is slow. Tests in `tests/queue/test_output_claims.py`:
  `test_adds_return_at_once_while_a_restored_jobs_share_does_not_answer` (a held `stat`; on the
  old code `TimeoutError` after 5 s), `test_a_restored_job_fails_when_its_keys_show_a_claimed_output`,
  `test_a_restored_job_cancelled_before_its_keys_arrive_stays_cancelled`,
  `test_a_restored_job_removed_before_its_keys_arrive_is_not_saved_again` (without that check,
  the late claim failed the removed job and saved it again) and
  `test_a_retried_restored_job_claims_against_the_restored_jobs_whose_keys_arrive` (symbolic
  links; skipped on Windows); the restored pairs of `restore_together` still run one after the
  other.
- **A retry without the keys of restored jobs survived** (the lead's L1, R1 C2).
  `test_a_retry_is_claimed_by_a_restored_job_whose_keys_are_being_taken`: L1 on the old code
  fails it (`WAITING is FAILED`), and so does a `_claim` that skips jobs without keys.
- **A claim checked outside the lock survived** (R1 C1).
  `test_adds_of_one_output_at_the_same_time_queue_one` now lets the four adds have their keys in
  one pass of the event loop; with C1 on the old code all four are added waiting (`4 == 1`).
- **A UNC data folder** (R1 m7). `Path.as_uri()` gives a UNC path a host. The URI is now built
  from the path's bytes (percent-encoded: `?`, `#`, `%`, a byte that is not UTF-8) with an empty
  authority, a `/` before a drive letter, and both slashes of a UNC path in the URI's path:
  `\\nas\share\…` is `file:////nas/share/…`. Checked with SQLite 3.54.0 (Python 3.14.8, Linux):
  `file://nas/share/data/queue.sqlite3?mode=ro` (also what `nturl2path.pathname2url` gives) →
  "invalid uri authority: nas"; `file:////nas/share/data/queue.sqlite3?mode=ro` → "unable to
  open database file" (parsed; no such file here); `file:////tmp/…` opens `/tmp/…`, so SQLite
  gives the VFS the whole path with both slashes, which Windows reads as the UNC path (not run
  on Windows). Test: `tests/queue/test_saved_queue.py::test_a_unc_data_folder_has_a_uri_that_sqlite_accepts`.
- **The immutable read misses every commit since the last checkpoint** (R1 m7). Checked with
  the same SQLite: a WAL database with one commit after a `TRUNCATE` checkpoint gives 2 rows with
  `mode=ro` and 1 with `mode=ro&immutable=1`, with or without an open writer; `mode=ro` fails
  only when there is no `-shm` file and the folder cannot be written ("unable to open database
  file" with a `-wal` file, "attempt to write a readonly database" without one). The docstring
  says so, and `SavedQueue.problem` does when a `-wal` file with content is there ("…; shown as
  of its last checkpoint, so newer changes in queue.sqlite3-wal may be missing"); without one
  (an owner that closed) the read is complete and there is no problem. Tests:
  `test_a_store_read_as_immutable_says_newer_changes_may_be_missing`,
  `test_a_store_without_a_wal_read_as_immutable_has_no_problem`.
- **`mode=rw` survived** (R1 S3). `test_reading_the_saved_queue_writes_nothing_to_the_store`
  reads a copy of a stopped owner's store whose newest job is only in the `-wal` file: with
  `mode=rw` the closing connection folds the `-wal` into the database file and removes it.
- **The folders guard** (R1 m9, G1). The owner search is also refused when its endpoint file
  is the session's `REFRAME_ENDPOINT_FILE` (read as the client reads it) or lies in one of the
  owner's folders. `testing/tests/test_folders_guard.py` runs a pytest session in a subprocess
  (the guard reads its session's environment at import) whose environment names temporary
  folders and an endpoint file as the owner's: each refusal is an inner test that expects the
  guard's failure, and temporary folders pass. On the old guard the two endpoint tests fail
  (`DID NOT RAISE`); each of eight mutations of the guard fails at least one.
- **`reframe queue log` was not live** (R2 F9, the core part). The timed flush of a job's log
  events also flushes the file, so a reader sees a running job's lines within the event
  interval (0.25 s). Test: `tests/queue/test_queue.py::test_a_running_jobs_log_file_has_its_lines_while_the_step_runs`
  (on the old code the file stayed empty until the step ended).


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

The CLI is built to the contract between the remote
client and the CLI: a start that the owner refuses is raised by the next awaited queue call,
`wait` raises for an id that is not in the queue, and a job that another front end removes
leaves `get()` before its `queue.changed` reaches the events. The tests are in
`tests/remote/test_cli_client.py`, `test_cli_queue.py`, `test_shared_queue_real.py`,
`tests/jobs/test_cli_encode.py` and the server's `tests/test_attach.py`.

- **C1, a removed job hung `encode` and `batch`.** The command followed only `job.state` and
  `job.progress`, and waited for every id. It now follows `queue.changed` and `resync` too.
  On each of them it reads its open jobs; a job that `get` does not return was removed. The
  command prints `[i/N] removed` and counts the job in the summary (`1 removed`), with exit 1.
  It waits only for the jobs that are still in the queue. Ctrl+C cancels and waits only for
  those jobs. A job that `get` does not return at the first read counts as removed too (R1).
  After `start(job_ids=…)` the command calls `await queue.wait([])`. That call raises a start
  that the owner refused. The command then starts the jobs that are still there. When the
  copy does not show the removal yet, it looks again every 0.1 s, at most 50 times; then the
  error ends the command. A `JobStateError` or `RemoteError` from that call ends the command
  as any other refusal does ("the jobs cannot be queued: …", or the lost-connection report).
  Tests: `test_a_job_another_front_end_removes_is_reported_and_the_command_ends`, before:
  `assert 130 == 1` (the command was still waiting when `wait_for` cancelled it after 30 s);
  `test_ctrl_c_after_another_front_end_removed_a_job`, before: `the jobs cannot be cancelled:
  no job '…' in the queue` and a summary without the removed job;
  `test_a_start_that_the_owner_refuses_is_sent_again_for_the_jobs_still_there` (a fake queue
  that follows the contract), before: `assert 130 == 1` after 30 s;
  `test_a_start_that_the_owner_keeps_refusing_ends_the_command`; with real processes
  `test_a_waiting_job_that_another_client_removes_ends_the_follow` (`reframe queue remove`,
  then `[2/2] removed` and `1 done … 1 removed`). Checked by hand against the remote client's
  branch at 9f00a95: a start that the owner refuses (the job removed in `queue.start`) gives
  `[1/2] removed`, `[2/2] done` and exit 1.
- **C2, a retried job was cancelled with the command.** The lead's decision, as a follow-up of
  [0057](0057-s7-attachments-client-id-and-detach.md) (its consequence "revisit if a front end
  retries the jobs of a CLI that is still running"): **a retry makes the job leave every
  attachment.** `POST /api/queue/{id}/retry` calls `EventHub.release(id)` for a job that has
  ended, before it awaits the retry, so no end of a connection comes in between. A refused
  retry of a running job (409) keeps the attachment. When a connection ends, the hub cancels
  only its jobs that have not ended. So a retry that comes between the end and the cancel is
  not cancelled. In the CLI a job keeps its first end (`CommandJobs`). Its later events are
  not shown and not counted. The final wait leaves it out, and Ctrl+C does not cancel it.
  Before it cancels, Ctrl+C also takes the state events that came and were not shown yet. The
  OpenAPI document does not change. Tests: `test_attach.py::test_a_job_that_another_front_end_retried_runs_on_when_its_client_goes_away`
  and `test_a_job_retried_just_after_its_client_went_away_is_not_cancelled`, before: the job
  `cancelled` instead of `running` and `waiting`;
  `test_a_retry_that_is_refused_leaves_the_job_attached`;
  `test_a_job_another_front_end_retries_is_left_to_it`, before: `assert 130 == 1` (the command
  waited for the new run); `test_ctrl_c_leaves_a_job_another_front_end_retried`, before:
  `Summary: 0 done, 0 failed, 2 cancelled` (A was cancelled);
  `test_ctrl_c_leaves_a_job_that_ended_and_was_retried_before_the_command_saw_it`.
- **C3, the "Done when" 2 tests.** Both now use `parallel_jobs` 2. The other front end's job
  runs at the Ctrl+C, runs on and ends `done`. The in-loop test checked the wrong folder for
  `.part` files: the command's outputs are next to the sources. The mutation in which Ctrl+C
  takes the running jobs from `queue.list()` fails both tests. They pass on the unfixed code:
  the code was right, the tests were too weak.
- **C4, a stopped client.** Measured: a client process that is stopped cannot answer
  uvicorn's keepalive ping. After the ping interval plus its timeout, the hub reads code 1005,
  as for a client that is gone, and cancels the client's jobs (`testdata/README.md`). The
  chosen mechanism: while a client follows its jobs on POSIX, SIGTSTP (Ctrl+Z) ends the
  follow. The command pauses its running jobs, closes its connection with `detach`, prints
  `Stopped: …` and stops itself with SIGTSTP. On SIGCONT (`fg`, `bg`) it connects again
  (no owner is started) and resumes the jobs that it paused, then follows them through the new
  connection. A Ctrl+C during that reconnection is applied once the new connection is open.
  The jobs stay detached because the API cannot attach a job that is already in the queue. So
  from the stop until the command ends, SIGTERM and SIGHUP cancel them as Ctrl+C does
  (`kill %1`, a closed terminal). Known limits: a stop that cannot be caught (SIGSTOP, a
  debugger, SIGTTOU or SIGTTIN) still lets the owner cancel the jobs after about 20–40 s. A
  `kill -9` of a stopped command leaves its jobs paused and detached until `reframe queue
  resume` or `cancel`; the owner stays because it is busy. A waiting job of the command can
  start while the command is stopped, when a slot frees. Ctrl+Z before the jobs are followed
  (while drafting or adding) stops the process as before. In-process and on Windows nothing
  changes. (b) After a lost connection the command reports each open job as it is now. The
  owner gives the state when it answers. Else the saved queue gives it, and a job there that
  was running or paused counts as `interrupted`. Else the command's own copy gives it. The
  error line is `error: <reason>.`, and the waiting jobs are named as in item 6. Item 6's
  "reports its running jobs interrupted" is now a fact read from the owner or the saved queue,
  not a guess. Tests: `test_ctrl_z_pauses_the_commands_jobs_and_fg_resumes_them` (the stop
  itself replaced; at the stop the job is `paused` and no connection is open; it ends `done`),
  before: no SIGTSTP handler, so the test does not raise the signal and fails;
  `test_a_command_that_was_stopped_cancels_its_jobs_on_sigterm`;
  `test_a_command_that_cannot_reach_the_owner_after_a_stop`;
  `test_after_a_lost_connection_the_owners_states_are_reported` (attached: `cancelled`; not
  attached: runs on; no owner: the saved queue), before: `[1/1] interrupted`, or a summary
  with `1 not finished`; with real processes `test_ctrl_z_pauses_the_job_and_fg_resumes_it`
  (SIGTSTP to the CLI in its own process group: `paused`, no connection to the owner's port;
  SIGCONT: `[1/1] resumed` and `done`).
- **C5, Ctrl+C during the adds.** The add that is under way is not cancelled with the command.
  It is waited for with `asyncio.wait`, not `shield`, because Python 3.14 reports the error of a
  shielded add whose waiter was cancelled. After Ctrl+C the command waits up to 10 s
  (`ADD_WAIT`) for that answer, then cancels the job with the others and counts it. A
  connection sends `detach` only once `--detach` has printed `Detached:`. Any earlier end (Ctrl+C,
  an error) closes it without `detach`, so the owner cancels an attached job that the command
  never learned of (R2's suggestion). Jobs that were drafted but never added count as not
  queued. Tests: `test_ctrl_c_while_detach_adds_a_job_leaves_no_job_behind`, before: `Summary: 0
  done, 0 failed, 1 cancelled` (the job of the add under way was neither counted nor
  cancelled);
  `test_a_detach_that_was_interrupted_leaves_its_jobs_to_the_owners_cancel`, before: the
  condition not met in time (a job stayed waiting); `test_ctrl_c_while_an_add_fails`.
- **C6, the owner stopping during the adds.** An add that fails with `connection.lost`, or
  any queue error after the connection was lost, gives the lost-connection report (C4 b).
  That report names the waiting jobs. Test:
  `test_an_owner_that_stops_while_the_jobs_are_added`, before: `error: the jobs cannot be
  queued: the Reframe server cannot be reached: All connection attempts failed`, without the
  jobs.
- **C7, a countdown that the command's jobs did not start.** The command follows a countdown
  only when one of its jobs ran (a `running` event, or a `started_at`). The queue cancels its
  pending countdown when a job starts, so a later countdown is newer than that job. The
  countdown subscription is made after the jobs end, and before `pending` is read, so it does
  not hold older countdowns. Test:
  `test_a_countdown_that_the_commands_jobs_did_not_start_is_not_followed`, before:
  `assert 130 == 1` (the command showed the other countdown and waited until the test's
  time-out cancelled it).
- **C8, a global Stop from another front end.** Not built, the lead's decision: no event shows
  a stop. 0042's open question 5 says so, and so does the status row.
- **C9, `log -f`.** When the owner's connection is lost before the job ended, `log -f` prints
  `error: the Reframe server stopped before job ID ended.` and ends with 1. It does the same
  without an owner when the process that holds the saved queue is gone. That case ended with 0
  before, and its test changed. The owner's copy is read on the event loop; only the saved
  queue is read in a worker thread. Tests:
  `test_following_a_log_ends_with_an_error_when_the_owner_stops_first`, before: exit 0 and no
  message; `test_following_a_log_without_a_live_owner_ends_with_an_error`;
  `test_following_the_log_of_a_job_that_an_in_process_command_runs`.
- **C10, the test gaps.** The `detections` fixture records `CapabilityService._start`, which
  covers `start` and `wait`. The draft test also has a preset with a required track rule that
  matches nothing and its own naming. New tests cover `--detach` with a file that is not
  queued (exit 1) and a command that ends by an unexpected error (no attached job is left).
  Another new test runs the owner's countdown with a power service that only records
  (`RecordingExecutor`, `when_done` "shutdown" in the owner's folder, "nothing" in the
  command's own): the command shows it, and Ctrl+C cancels it through the API. Further new
  tests: `log -f` when the owner stops, and control characters in `queue list` and `log`. The
  batch test now has a time-out. The mutations `local_power_in_client`,
  `local_when_done_in_client`, `local_validate_in_client`, `detach_exit_always_ok`,
  `no_track_issues`, `ignore_preset_naming`, `queue_rows_no_printable`, `log_no_printable` and
  `log_follow_ignores_lost` now fail a test.
- **C11.** A job that `get` does not return at the first read is handled in C1. Drafting does
  not hold the event loop: with 120 files in client mode the longest block of the loop was
  0.11 s (`encode` 13.5 s in all, `batch` 6.5 s). The client's connection answers the
  keepalive pings between files, so the connection is not opened later. Measured under load,
  with `nice -n 19` and a movie playing.
- **C12, the nits.** `REFRAME_IN_PROCESS` is read by click's own rule (`click.BOOL`, click
  8.5.0: `off`, `f` and `n` are false), and a value that is not a truth value is a usage error
  (exit 2). `reframe queue pause|resume|cancel ID` ends with 1 and an error line when the job's
  state is not one that the action works on (pause: running; resume: paused; cancel: waiting,
  running or paused), as the help says; `--all` does not change. When `server.json` names a
  server that cannot be used, `queue list` prints `The Reframe server of this data folder
  cannot be used (<reason>): the saved queue.` and `queue log` prints the same as a warning.
  `find_job("")` asks for an id. `Queued N jobs.` counts only the jobs that wait. The
  real-process tests set `REFRAME_POWER_DRY_RUN=1`, and one of them checks with psutil that the
  started owner has it. Tests: `test_reframe_in_process_is_read_as_the_command_line_reads_it`,
  `test_an_action_that_the_jobs_state_does_not_allow`,
  `test_list_and_log_say_why_a_running_server_is_not_used`,
  `test_a_job_that_is_not_in_the_queue`,
  `test_a_job_that_the_owner_adds_failed_is_not_counted_as_queued`, all failing before.
- **Found here, for the remote client (B2):** on this branch alone, before the remote client's
  fix, the real tests with two and with ten clients that add at once fail every time. A
  client's copy drops a job that was just added, and the command now reports that job as
  removed. On this branch merged with `m3b-shared-queue` at 5b23e6a (the queue core's and
  the remote client's fixes; the merge not committed here) every test passes, these two
  included: `tests/remote` 198, `tests/queue`, `tests/jobs` and `testing/tests` 667 (1
  skipped), the server's tests 550 (3 skipped).

## Follow-up, 2026-11-01: Ctrl+Z right after a job starts

`test_ctrl_z_pauses_the_commands_jobs_and_fg_resumes_them` failed in about 1 run in 13 (3 of 40
runs alone), always with `seen == [(PAUSED, 0)]` getting `(RUNNING, 0)`. Cause, read from the
command's copy of the queue at the stop: it showed the job as `waiting` in every failing run and
as `running` in every passing one. The test raised SIGTSTP once the owner had the job running,
but the event of the start had not reached the command yet, and `_stop_here` pauses only the jobs
that its copy shows as running. So the code was wrong, not the test: a Ctrl+Z in that window
detached the command with its job still running instead of paused. `_stop_here` now reads the
whole queue (`RemoteQueue.refresh`) before it looks at the states. A new test holds back the
first `running` event of the copy: `test_ctrl_z_pauses_a_job_whose_start_the_command_has_not_seen`
fails every time without the change (3 of 3) and passes with it. The original test passed 60 of
60 runs after the change.
