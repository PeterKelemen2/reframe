# 0107 — Queue store migrations with Alembic, and the size of a finished job

- Status: accepted; the use of Alembic is superseded by [0108](0108-own-migration-runner-for-the-queue-store.md)
- Date: 2026-11-25
- Steps: C-11, F-14

## Context

A user encoded a film for 20 minutes with the BtbN n8.1.3 build (`compat`) and NVENC. At 52 %
the percent stopped, the speed showed 0 and the time left grew until it was gone, while the
frame count and the size grew. At the end the job jumped to 100 %. The queue then showed no
size for the done job.

**The stuck percent.** FFmpeg prints `out_time` from the scheduler (`fftools/ffmpeg_sched.c`):

- n8.x: `trailing_dts`, the *lowest* last DTS (plus duration) of the output streams whose
  source has not finished. A copied subtitle track stays open until the demuxer ends the input,
  so after its last line `out_time` stays at that line's end for the rest of the encode.
- n9.x: `progressing_dts`, the *highest* such DTS. It does not stop at a subtitle, but it
  stops while the stream furthest ahead ends (a short audio track), falls back when that stream
  finishes, and reads `N/A` for the last blocks.

Checked with a 30 s 1080p libx264 + AAC encode of a source with two SRT lines (the last one
ends at 6 s), `-map 0 -c:s copy -progress pipe:1 -stats_period 1`:

| Build | `out_time_us` while `frame` counts 162 → 750 |
|---|---|
| BtbN n8.1.3 | `6000000` in every block, the `progress=end` block too |
| n9.1 (Arch), n9.0.2 (pinned) | follows the video; near the end `26480000`, then `N/A` |

The tracker took the position from `out_time` only, and from `frame` only when `out_time` was
`N/A`. It now carries the position on with the frames (`frame / output frame rate`) from the
last position while `out_time` does not move forward, and takes `out_time` again as soon as it
is ahead (`ProgressTracker._position`).

**The missing size.** The plan's queue has a "current size" column: the frontend showed it
only while a job ran, and `progress` is not saved. Showing a done job's size after a restart
needs a new column in `queue.sqlite3`. The store had one schema in `PRAGMA user_version` (1),
and a file of a higher version is never read or written (decision 0016). Raising it for an
optional column would make every older Reframe refuse the whole queue.

## Decision

- **Alembic manages the store's tables.** Revisions live in `reframe/queue/migrations/versions/`
  (`r0001_jobs_table`, the table of Reframe ≤ 0.10 with `CREATE TABLE IF NOT EXISTS`, which
  adopts its files; `r0002_job_output_size`). `reframe.queue.migrations.upgrade(path)` runs
  them on the store thread when the owner opens or creates the file, after the newer-file check.
  It uses its own SQLAlchemy connection with `sqlite3` `autocommit=False`, so DDL is in the
  transaction, and `transaction_per_migration`: a revision that fails leaves the file at the
  revision before it (tested). A failed migration makes the store read-only for the session
  with `queue.unreadable`; the file is not moved aside.
- **`user_version` stays the compatibility line.** A revision only adds what an older Reframe
  can ignore (a column that may be NULL); anything else also raises `user_version`. A file at a
  revision this Reframe does not know is read and written as it is.
- **Readers without the lock do not migrate.** `read_saved_queue` (`reframe queue list` with no
  owner running) and the store read through `select_jobs`, which reads a column that the file
  does not have yet as NULL.
- **`QueueJob.output_size`**: the bytes of the finished output (from the re-probe's
  fingerprint), saved in `jobs.output_size`. The queue's size column shows it for a done job.

## Consequences

- New core dependencies: `alembic`, `sqlalchemy` (and Alembic's `mako`). The sidecar's PyInstaller
  spec collects `reframe.queue.migrations` with its `.py` files, because Alembic runs `env.py`
  and the revisions from files. Checked with a frozen build: the frozen server migrated a 0.10
  file to `0002`, and the frozen CLI read the old file unchanged.
- Importing Alembic and SQLAlchemy takes about 130 ms, a quarter of `import reframe`. They
  are imported only when a file needs a migration: the store first compares `alembic_version`
  with `migrations.HEAD` on its own connection (0.06 ms against 1.7 ms for Alembic's own check).
  `test_a_current_file_opens_without_alembic` keeps it so.
- The store keeps `synchronous=FULL`: measured on ext4, a commit takes 0.96 ms against 0.03 ms
  with `NORMAL`, but the store commits only on state changes, on its own thread, and `NORMAL`
  in WAL mode can lose the last commits at a power loss.
- Reframe 0.10 still opens a migrated file (it names its columns); the rows it writes have no
  size.
- A new revision: `uv run alembic revision --rev-id 0003 -m "…"` from the repository root
  (`[tool.alembic]` in `pyproject.toml`), then `uv run ruff format`. Add a test with a file of
  the revision before it to `test_store_migrations.py`; `test_the_revisions_form_one_line`
  lists the revisions.
- The frame fallback depends on the plan's output frame rate. For a variable-frame-rate source
  the percent can drift a little while `out_time` does not move; it never goes back.

## Plan changes

- `05-core.md` §C-11: the store's columns and its migrations.
- `03-features.md` §Queue: the size column shows the finished file's size.
