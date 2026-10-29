# 0042 — One scheduler process; the CLI hands its jobs to it

- Status: accepted
- Date: 2026-10-19
- Steps: C-11, C-17 (new), S-0, S-1, S-6, S-7 (new), D-2, D-3, D-5; milestone M3b (new)
- Supersedes in part: [0027](0027-one-process-owns-the-queue-store.md) item 4 and its
  consequence "M3 revisits this" (a process that cannot own the store no longer defaults to a
  private queue; that stays as the fall-back), [0017](0017-jobs-service-and-cli.md) item 16
  (sharing the queue between front ends, already changed by 0027; and "`encode` adds its jobs
  at the front")

## Context

[0027](0027-one-process-owns-the-queue-store.md) made one process own `queue.sqlite3`. A second
process runs its jobs in a private queue in memory. It works, but it is not "normal":

- The second process's jobs are not saved. No other front end and no command can see them.
- It has its own `queue.parallel_jobs` limit. Two CLIs run twice the set number of encodes,
  so the setting is not a limit any more (NVENC also limits concurrent sessions).
- The same-output and in-place checks (0016, 0027 item 5, 0034) only see the jobs of one
  process.

**What blocks sharing the store** (read in the code, 2026-10-19). SQLite is not the problem:
the store uses WAL, `busy_timeout = 5000` and `BEGIN IMMEDIATE`, which are safe for several
processes. The blockers are above it:

1. The queue's memory is the truth. `QueueService._jobs` and `_active` hold the state; the
   store only persists it.
2. A row is written whole (`INSERT OR REPLACE`), so two writers overwrite each other.
3. Restore assumes one owner: it turns every `running` or `paused` row into `interrupted`.

**Parallel encodes in one process already work** (`queue.parallel_jobs`, `_conflicts`). This
record is about several processes.

The plan already points one way. [02 rule 6](../plan/02-architecture.md#cross-cutting-rules)
says the server runs one worker and queue state lives in that process. M3 builds the queue's
REST routes and the event WebSocket anyway. 0027 left "the CLI may hand its jobs to a running
server" to M3.

**Alternatives that were rejected**

- **Every process schedules from the shared database** (atomic claims with
  `UPDATE … WHERE state = 'waiting'`). It needs a rewrite of `QueueService` (about 1 000
  lines) and new mechanisms for what one scheduler gets for free: a global slot limit,
  same-output checks across processes, cancel and pause of another process's job, progress
  through the database, liveness of an owner. Nothing in this record blocks it later, because
  the schema does not change.
- **The first CLI becomes the server.** Its Ctrl+C would end the jobs of every client that
  joined, and ownership cannot move to another process while jobs run.

A first draft of this record was reviewed before it was committed (decision 0043, findings
4–10); this version includes the fixes.

## Decision

1. **One scheduler.** The process that holds `<data dir>/queue.lock` restores the store, takes
   the jobs and runs them. Items 1, 2, 3 and 5 of 0027 stay. **No schema change**, so no
   `schema_version` bump: attachments (item 5) are running state, and the store does not keep
   them.

2. **The owner is a server process, and it publishes its address, in every mode.** After it
   holds the lock and listens, the server writes `<data dir>/server.json` (atomic write, mode
   `0600` on POSIX): `pid`, `instance` (a random id of this run), `port`, `token`, `version`,
   `api_version` (an integer, also in `GET /api/health`), `started_at`. It removes the file at
   close. The file is a hint, never the truth: a process that can take the lock knows the file
   is stale and ignores or replaces it. The server opens the queue at start-up
   (`queue.list()`), before it writes the file.

   The `token` is a **local token**: random per run, accepted as `Authorization: Bearer` in
   every auth mode (S-1), next to the mode's own login. It gives no more than read access to
   the data folder already gives: the queue database, the logs and the server's state are in
   the same folder, readable by the same user. So a CLI on a NAS (also through `docker exec`)
   uses the web server's queue.

   A server that cannot take the lock keeps 0027's behaviour (a private queue and
   `queue.store_busy`) and publishes nothing. A server started with `--owner-only` exits with
   code 75 instead.

3. **How a front end finds the owner.** The CLI (`encode`, `batch`, `queue …`) and the desktop
   shell (D-3) follow the same order:
   1. `server.json` names an endpoint whose `GET /api/health` answers with the same `instance`
      and the same `api_version` → **use that owner**.
   2. The lock is free → **start an owner**. The CLI starts
      `sys.executable -m reframe_server --owner-only --idle-exit 30` from its own environment,
      so the server has the CLI's version and no `PATH` lookup is needed (the package must be
      importable there, `importlib.util.find_spec("reframe_server")`; the frozen CLI of a
      desktop package starts the frozen server next to it). It uses `launch_detached`
      (desktop-mode rules: loopback, token, the user's whole file system) and waits at most
      10 s for `server.json`. The desktop shell starts its sidecar as in
      [07](../plan/07-desktop-app.md#sidecar-lifecycle). Two front ends that start an owner at
      the same time: one wins the lock, the other server exits with 75, both use the winner.
   3. Anything else (the lock is held and no usable endpoint: another version, an in-process
      owner; no server package; `--in-process`; the start failed) → **0027**: the in-process
      queue, private when the store is busy, with `queue.store_busy` whose detail says why
      (for another version: "Reframe X (pid N) owns the queue").

   So an app that opens while a CLI-started owner runs uses that owner, and its UI shows the
   CLI's jobs. `probe`, `plan`, `name`, `encoders`, `tools`, `presets` never touch the queue
   (0027 item 1) and do not change.

4. **The transport is the server's own REST and WebSocket** (S-2, S-3). There is no second
   protocol. `reframe.queue.QueueLike` (a `Protocol`: the methods of `QueueService` that the
   CLI calls) has two implementations: `QueueService` and `reframe.remote.RemoteQueue`.
   `reframe encode` and `reframe batch` use only the protocol, so a run in client mode and an
   in-process run behave the same. **One contract test suite runs against both.**
   `reframe.remote` is in the core package and its dependencies (`httpx`, `websockets`) are in
   the `[cli]` extra: the core still imports no FastAPI or UI code.

   In client mode the CLI probes and drafts locally (the probe cache is shared), but it runs
   **no encoder detection of its own**: it validates with `POST /api/jobs/validate`, so errors
   show before anything is queued (0017 item 15), and it shows the owner's encoder statuses.
   A second detection would run hardware test encodes next to the owner's encodes; under that
   load a test encode can fail and mark a working encoder unavailable. The server validates
   again on `add`.

5. **Attached and detached jobs.** The client opens `WS /api/events` first; after it
   authenticates, the server answers with a `client_id`. `POST /api/queue` with
   `attach: <client_id>` is refused (409) unless that connection is open, so no job is ever
   attached to a client that is already gone. A CLI's jobs are **attached** by default. When
   the connection ends without a `detach` message (Ctrl+C is the CLI's own cancel and exit
   130 as now; `kill -9`; a closed terminal), the server cancels the attached jobs that have
   not ended, the way a cancel does (a waiting job becomes `cancelled`; a running job is
   stopped and its `.part` file follows the partial-file setting). `--detach` adds the jobs,
   starts them, prints their ids and exits 0; they run on.

   **Queue order**: the CLI adds its jobs **at the end** of the queue, in every mode. With
   several clients, "at the front" (0017 item 16) would let each new command pass the ones
   before it. `start(job_ids=…)` keeps its meaning: only these jobs start; waiting jobs of
   other clients and of the UI are neither started nor cancelled.

6. **Output claims in the queue.** `QueueService.add` and `retry` fail a job (it is added
   `failed` with the issue, like any validation error) with `queue.output_claimed` when its
   output file is the output or the source of another job that is waiting, running or
   paused. Files are compared as files (`reframe.jobs.file_key`: links and hard links
   resolved; in a worker thread); an in-place edit's output is its source (0034). Before, the
   queue only kept two such jobs from running at once, and with the collision setting
   *overwrite* the second job replaced the first one's output. This holds for every front end;
   the CLI's `OutputClaims` (the files of one command) stays. `ValidationIssue.code` is free
   text, so the new code changes no persisted value.

7. **Global rules hold because there is one scheduler**: the `parallel_jobs` limit, the
   same-output and in-place checks across every client, the sleep inhibit, the when-done
   action and the settings.

8. **Lifetime.** A server that a CLI started exits after `idle_exit` seconds (default 30)
   in which there is no running job, no job that a `start` still targets, no event
   connection (an open app or browser tab keeps it) and no pending when-done countdown. A
   server of the desktop shell (D-3) or a web deployment never exits when idle.

9. **One data folder, one scheduler.** A different `REFRAME_DATA_DIR` is a separate scheduler
   (this is also how tests are isolated).

10. **`reframe queue`**: `list [--json]` · `log ID [-f]` · `pause|resume|cancel [ID…|--all]` ·
    `retry ID` · `remove ID`. With no owner, `list` and `log` open the store read-only (no
    restore, no lock). The other commands need an owner (item 3.2) and say so when none can be
    reached.

11. **Packaging and names**, so that `reframe` and its owner have the same version:
    - **Bare metal**: one environment holds both packages:
      `uv tool install 'reframe[cli]' --with reframe-server --with-executables-from reframe-server`
      puts `reframe` and `reframe-server` on `PATH` (the flags are in `uv tool install --help`,
      uv 0.12.21).
    - **Desktop packages ship the CLI.** The sidecar build (D-2) also makes a frozen `reframe`
      CLI in the same folder. The `.deb` and `.rpm` link it as `/usr/bin/reframe`; the Windows
      installer offers to add its folder to the user's `PATH`; the AppImage does not put it
      on `PATH`.
    - **`reframe` is always the CLI.** The desktop executable is `reframe-desktop` on Linux
      and `Reframe.exe` on Windows; open-with is `reframe-desktop file.mkv folder/` (D-5).

12. **Milestone.** S-7 and C-17 form the milestone **M3b — Shared queue**, after M3. It does
    not block M4 (the frontend does not need it) and is done before M5, because D-3 uses
    item 3.

## Verification

The "Done when" of C-17 and S-7, with real processes (the real `reframe-server` and `reframe`
CLI, fixture media or the fake FFmpeg):

1. Two `reframe encode` runs at once both finish, each shows its own progress, and
   `queue.parallel_jobs` holds across both.
2. SIGINT in one cancels only its own jobs.
3. `kill -9` of a client cancels its attached jobs and removes their `.part` files. A
   `--detach` job runs on.
4. `kill -9` of the server in the middle of a job: the client reports `interrupted`; the next
   command starts a new owner that restores the queue.
5. Ten clients that add jobs at the same time lose none and duplicate none.
6. A job whose output is the output of another client's waiting job is added `failed` with
   `queue.output_claimed`.
7. A server of another `api_version` is not used: the client falls back and says why.
8. The queue contract test suite passes against `QueueService` and `RemoteQueue`.
9. `attach` with the id of a closed connection is refused.

## Consequences

- Two `reframe encode` commands in two terminals both run, are saved, share one slot limit,
  and show in `reframe queue list` and in a running UI as they go. A UI started later sees
  them too.
- A queue command in the shared mode needs `reframe-server` in the CLI's environment. A
  core-only install keeps 0027 exactly.
- A server process can outlive a command by up to `idle_exit` seconds. `--in-process` avoids
  it.
- A CLI that dies (`kill -9`, closed terminal) is cleaned up at once: the server cancels its
  attached jobs and removes their `.part` files. Before, only the child-safety kill of
  FFmpeg ran at that moment; the `.part` file waited for a later owner to restore the store
  (and never, for a private queue).
- An app of another version than a running CLI-started owner gets the private queue with a
  warning that names the other version (item 3.3). With the CLI shipped in the desktop
  packages (item 11), this happens only with a second install.
- "Stop jobs and quit" in an app that uses an owner it did not start cancels the jobs through
  the API; it does not kill the owner.
- `queue.store_busy` stays, for item 3.3 only.

**Open questions** (each is built with the default; none stops the work):

1. *The numbers*: 10 s to wait for an owner, 30 s idle exit.
2. *Windows*: `launch_detached` already breaks away from Reframe's own Job Object
   (`CREATE_BREAKAWAY_FROM_JOB`; the job allows it). An outer job that forbids breakaway (some
   terminals, CI runners) ends the owner with it: attached jobs end as they would anyway,
   detached jobs become `interrupted`. Not run on Windows yet.
3. *`quit` as a when-done action* on a server that a CLI started: the server ends. On the
   desktop sidecar the UI quits (as in 0037).
4. *`reframe queue` against a server that is stopping*: a clean error, not a hang.
5. *A global Stop from the UI* also stops the waiting jobs of a CLI. Default: the CLI says
   "the queue was stopped by another front end" and goes on waiting (Ctrl+C cancels). Not
   built yet ([0061](0061-c17-remote-queue-and-queue-commands.md), the CLI's review fixes): no
   event tells a client that the queue was stopped; one is needed, with the UI's Stop in M4.

## Plan changes

- [02 §Cross-cutting rules](../plan/02-architecture.md#cross-cutting-rules) rule 6.
- [03 §Queue](../plan/03-features.md#queue): the Persistence and Output safety bullets.
- [05 §C-11](../plan/05-core.md#c-11-queue-and-job-runner): the runner and restart-recovery
  bullets.
- [05 §C-17](../plan/05-core.md#c-17-remote-queue-and-queue-commands) (new).
- [06 §S-0, S-1, S-6, S-7](../plan/06-web-app.md): `ServerConfig` options, the local token,
  the bare-metal install, the new step S-7.
- [07](../plan/07-desktop-app.md): the executable name, sidecar lifecycle step 1, D-2 (the
  frozen CLI), D-3 (find the owner first), D-5.
- [08](../plan/08-roadmap.md): the new milestone M3b and the dependency graph.
- [../status.md](../status.md): the new steps, M3b and the notes on the queue.
