# 0027 — One Reframe process owns the queue store; another process gets a private queue

- Status: accepted
- Date: 2026-10-14
- Steps: C-11, C-15 (affects every front end: S-x, D-x)
- Supersedes in part: [0016](0016-queue-and-job-runner.md) (restore in `Reframe.create()`;
  "both would run the store's jobs"), [0017](0017-jobs-service-and-cli.md) item 16 (the CLI
  shares the store with other front ends)

## Context

The queue store is `<data dir>/queue.sqlite3`. `Reframe.create()` restored it at every start:
rows left `running` or `paused` became `interrupted`, and their `.part`, plan files and
statistics files were removed. Every CLI command calls `Reframe.create()`.

The M2 review reproduced the result: while `reframe encode long.mkv` runs in one terminal,
`reframe name long.mkv` (or `probe`, `plan`, `encoders`) in a second terminal marks the running
job `interrupted` and deletes its `.part` file. FFmpeg goes on writing into the deleted file,
and when it ends the first terminal says "wrote no output". Minutes of encoding are lost. Two
`reframe encode` commands at once had the same problem.

SQLite itself allows several processes, but the queue keeps its state in memory (the running
jobs, their processes, the runner) and writes whole rows, so two processes that both run the
same store would overwrite each other's rows.

## Decision

1. **`Reframe.create()` does not open or restore the queue store.** The queue opens it on its
   first use (any `QueueService` method). Commands that never use the queue (`probe`, `plan`,
   `name`, `encoders`) never touch it.
2. **Opening takes an exclusive OS lock** on `<data dir>/queue.lock` (POSIX `fcntl.flock`,
   Windows `msvcrt.locking` or `LockFileEx`), held until `close()`. The OS frees the lock when
   the process ends, also after a crash or `kill -9`, so a lock is never stale. The lock file
   holds the owner's pid, for messages only.
3. **Only the lock owner restores the store** (running and paused rows become `interrupted`;
   their files are cleaned up) and runs its jobs.
4. **A process that cannot take the lock** (another Reframe process owns the store) runs its
   queue on a **private store that is not kept** (SQLite in memory). It sends one `app.warning`
   with the code `queue.store_busy`: "Another Reframe process (pid N) is using the saved queue.
   The jobs of this process run here and are not kept after it ends." The `QueueService`
   contract does not change.
5. **The clean-up removes only what this process's run created**: a `.part` file, plan file
   or statistics file that existed before the job's first step started is never deleted (see
   also the M2 review finding B2: a source named `Foo.part.mkv`).

## Consequences

- Two `reframe encode` commands in two terminals both work; the second one's jobs are not
  saved. Read-only commands are safe at any time.
- A desktop or web app that starts while a CLI encode runs gets a private queue until it is
  restarted. M3 (API and desktop spike) revisits this: the CLI may then hand its jobs to a
  running server instead.
- The data folder must be on a file system with working locks (a local disk), as WAL already
  requires (0016).

## Plan changes

- [03 §Queue](../plan/03-features.md#queue): the Persistence bullet.
- [05 §C-11](../plan/05-core.md#c-11-queue-and-job-runner): the restart-recovery bullet.
