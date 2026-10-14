# 0016 — Queue and job runner: store, run order, sleep-aware ETA, watchdog, finalize, close

- Status: accepted; restore in `Reframe.create()` and "two processes would both run the
  store's jobs" are superseded by [0027](0027-one-process-owns-the-queue-store.md) (see
  "Follow-up (M2 review)")
- Date: 2026-10-14
- Steps: C-11 (affects C-14, C-15, S-x, F-x queue views)

## Context

05 §C-11 lists the store columns, the runner loop, the progress parser, logs, pause, cancel,
the final rename, restart recovery, when-done and sleep inhibit. The M2 contract
(`docs/m2-breakdown.md`, "Wave 3 offers") fixes the `QueueService` methods. Building them left
open questions that the plan does not answer:

- what the store does with a damaged, newer or unwritable file, and with rows it cannot read;
- what the methods do with an unknown job or a job in the wrong state;
- how progress, speed and ETA behave when a job is paused or the PC sleeps (decision 0020:
  "the encode pauses with the system and continues after wake");
- which time limits a step has, given that an encode has none;
- the values that replace `-inf` loudnorm measurements;
- when the output is checked, and what happens to a complete output whose name is taken;
- what `close()` does to running jobs, and what "the queue empties" means for when-done.

What we checked with the real tools (records in `testdata/README.md`, "Queue and job runner
(C-11)"; both FFmpeg n9.0.2 builds):

1. FFmpeg's `speed=` and `fps=` in `-progress` are averages since the process started, on a
   clock that runs while the process is stopped: after a 3 s `SIGSTOP` (psutil `suspend()`),
   `speed` fell from 1.15x to 0.444x and recovered slowly.
2. FFmpeg ≥ 7 prints a `-progress` block every `-stats_period` (0.5 s) also before the first
   packet (`frame=0`, `out_time_us=N/A`); a block stops coming only when the process does
   not run.
3. A silent track gives `"input_i" : "-inf"`, `"input_tp" : "-inf"`,
   `"target_offset" : "inf"`; a near-silent one (pink noise at −84 dBTP) gives
   `input_i` `-inf` and `target_offset` `inf` with a finite `input_tp`. With
   `offset=99` (the top of loudnorm's range) the second pass turns that noise into
   full-scale noise (−9.6 LUFS, peak 0 dBFS); with `offset=0` it stays as it was.
4. A silent input **shorter than 3 s** fails the second pass whatever the measured values:
   loudnorm's first-frame path computes its gain from the input's own −inf loudness and the
   encoder gets NaN samples ("Input contains (near) NaN/+-Inf", exit 234). A 2 s output
   range of a longer silent source works (loudnorm reads 3 s before the output limit stops
   the input).
5. An MP4 output's chapters are a `bin_data` data stream in ffprobe, not a subtitle.

## Decision

### 1. The store

- `<data dir>/queue.sqlite3`, one table with the 05 §C-11 columns; schema version in
  `PRAGMA user_version` (1). The file is created at the first write, not by
  `Reframe.create()`.
- All store calls run on **one dedicated thread**, in the order the queue made them; rows
  are serialised on the event loop and written whole (`INSERT OR REPLACE`), several rows
  (positions) in one transaction. WAL journal, `synchronous=FULL`: a crash loses nothing that
  was written. The jobs live in memory; `list()` and `get()` never touch the file.
- `settings_json` is migrated with `load_document("job_settings", …)` and keeps unknown
  fields (written back unchanged). `plan_json` and `issues_json` are derived: if they do
  not load they are dropped from memory (the runner plans and validates again anyway).
- A row that does not load (a newer `JobSettings` schema, an unknown state) stays in the file
  untouched and is not shown: one `app.warning` `queue.rows_skipped`.
- A **newer** file (`user_version` > 1) is not read and never written (`queue.newer_version`;
  the queue starts empty and is not saved this session). The version is read before the WAL
  journal is switched on, because that changes the file header. A **corrupt** file is renamed
  to `queue.corrupt-<time>.sqlite3` and a new one is started (`queue.corrupt`). A file that
  cannot be opened is left alone (`queue.unreadable`). A write that fails later (disk full)
  gives `queue.not_saved` once; the queue goes on in memory.

### 2. The API beyond the contract

- **Keyword-only addition, `start(*, job_ids=None)`** (the lead's request for C-15's
  `reframe encode`, which shares the persistent queue with other front ends): only these jobs
  are taken, while waiting, in queue order, `parallel_jobs` at a time; other waiting jobs keep
  their state and position. When none of them is waiting or running, the runner goes idle
  (as after `stop()`). A call while the runner is taking jobs never narrows what it takes
  (`start()` without ids takes every job; ids are added to an earlier set). `start` and
  `stop` are runtime state only: a restored queue is idle until `start()`.
- **Misuse raises** (these methods return `None` or a job, so a value cannot say it):
  `reframe.queue.UnknownJobError` (a `KeyError`) for an id that is not in the queue;
  `JobStateError` for `remove` of a running or paused job and `retry` of a running, paused or
  done job; `ReframeClosedError` after `close()` (`list`, `get`, `wait`, `log_path` still
  work). `retry` of a waiting job returns it unchanged. `pause`/`resume` of a job in another
  state do nothing.
- `add` validates with a fresh probe (cached), the discovered tools and the capability
  snapshot **as it is** (it does not wait for detection: `encoder.checking` is info). A job
  with errors is added as `failed` (with `finished_at` and `error` "The job has errors: …").
  A source that cannot be probed is the error `queue.source_unreadable`.
- `reorder(ids)`: the given jobs take the places the same jobs had, in the given order; the
  other jobs do not move (the whole list or any part of it can be given).
- `remove` also removes the job's log file. `retry` keeps the job's place and appends a new
  run to its log.
- `cancel(None)` cancels **every job that has not ended**: running and paused ones (tree
  killed, `.part` removed) and waiting ones (marked `cancelled`). `cancel` returns when the
  cancelled jobs have ended and their files are handled. A front end that shares the queue
  should cancel its own ids, or other front ends' waiting jobs are cancelled too.
- `wait(None)` waits for the jobs in the queue at the call; a waiting job ends only while
  the runner takes it. A job removed meanwhile is left out of the result.
- A **paused job keeps its slot**: its process is suspended, not ended.
- `Reframe.create()` loads the store through the private `QueueService._restore()` (the
  contract allows no other public member: whether the runner takes jobs and where the store
  is are private). The constructor takes the services as small protocols (`tools.status()`,
  `capabilities.snapshot` / `wait()`, `sources.probe()`), a `naming` callable (the job's
  preset's naming options, else Settings → Output), the inhibitor, clocks, the file-system
  view and the limits below, so tests run every path with stand-ins.

### 3. Running a job

- Prepare: probe the source again (cached), read the tools, validate (in a worker thread);
  when an issue is `encoder.checking`, wait for `capabilities.wait()` and validate again;
  any error fails the job with its issues; then `build_plan(…, naming=…, now=…)`
  (`PlanError` → `queue.plan_failed`). A cancel during prepare stops it at once.
- The output folder is created (validation allows a folder that can be made), then
  `EncodePlan.files` are written (UTF-8, LF).
- **Two jobs with the same output path never run at the same time** (both would write the
  same `<name>.part.<ext>`): the second waits and the next job in the queue runs; at its end
  the collision policy names it (`Name (1).mkv` with `auto_rename`).
- Step argv: `[tool path, *resolve_argv(step.argv, measured)]`, with the tool's `env`; a
  missing measured value fails the job ("needs the measured value a0.input_tp").

### 4. Progress, speed and ETA (sleep-aware)

- Percent: the steps' weights normalised (analyse 0.05, pass 1 0.4, pass 2 0.6, encode 1,
  mkvpropedit 0.01, finalize 0); within a step `out_time / expected_duration`
  (`progress=end` = 1). It never goes back.
- Speed and fps are Reframe's own (fact 1): the change of `out_time` and `frame` between two
  blocks over the time between them, smoothed (exponential, time constant 8 s). FFmpeg's
  values are used only before the second block of a step, and never after a pause.
- ETA = `(100 − percent) / rate`, `rate` = smoothed percent per **active** second. An
  interval is not used (only re-anchors) when: the job was paused (pause and resume reset the
  reference point); the wall clock ran more than 2 s ahead of (or behind) the monotonic clock
  (Linux: the monotonic clock stops during a suspend); or the interval is longer than 30 s
  (an OS whose monotonic clock counts the suspend; fact 2 says no live FFmpeg is silent that
  long). So after a wake the speed and the ETA continue from where they were. Tested with
  injected clocks (`tests/queue/test_progress.py`).

### 5. Time limits

- An encode has **no wall-clock limit**.
- **Stall watchdog** for FFmpeg steps: stopped when, for 10 minutes of active time, the
  `-progress` values did not change (`out_time`, `frame`, `total_size`), no stderr line came,
  **and** the process tree used less than 5 % of one core (psutil CPU times). The CPU check
  keeps a slow encoder with a long look-ahead (no new frame for minutes, all cores busy) from
  being killed; a hung network read or GPU driver uses no CPU. The job fails: "FFmpeg made no
  progress for 10 minutes (no output, no CPU use) and was stopped."
- **Short steps** (`mkvpropedit`): 5 minutes of active time.
- Both count in ticks of 5 s, each counting at most 10 s, so a system sleep adds at most one
  tick whatever the clocks say; paused time does not count and a pause resets the idle time.
- Probes (source, output check) keep C-3's own timeouts.

### 6. Loudnorm values

- Each analyse step's block is stored as `<id>.<key>`. The values the second pass reads are
  put into the ranges of `ffmpeg -h filter=loudnorm`: `measured_I` −99…0, `measured_TP`
  −99…99, `measured_LRA` 0…99, `measured_thresh` −99…0, `offset` −99…99. `-inf` takes the
  low end and `inf` the high end, **except `target_offset`: any infinite value becomes 0**
  (fact 3: 99 dB of gain on a near-silent track is full-scale noise). NaN (never seen) takes
  loudnorm's own "not measured" defaults. The log lists every changed value.
- Not handled: a silent track shorter than 3 s still fails in FFmpeg (fact 4); the job fails
  with FFmpeg's reason. Revisit if it matters (the builder could leave loudnorm out for a
  track that measured `-inf`, which needs a plan change).

### 7. Finalize and the output check

- **The `.part` file is re-probed and checked before it is renamed** (the plan says rename,
  then re-probe). A bad output never takes the final name, and is handled like any failed
  output (the partial-file policy). The probe does not use the cache.
- Checked: one video stream, one audio stream per output audio track, one subtitle stream
  per subtitle track that is not burned in, and each stream's language in the container's
  form (the track's language, else the source track's; `und` when none). Attachments and data
  streams (fact 5) are not compared. A mismatch fails the job and names each difference
  ("3 audio tracks expected, 2 found; subtitle track 2: language eng expected, ger found").
- Rename with `settings.output.collision`, read at that moment: a free name is taken without
  ever replacing a file (Windows `os.rename`; POSIX a hard link plus unlink, with a
  check-then-rename fallback where hard links do not exist; a name taken in between is looked
  up again); `auto_rename` → `next_free_path`; `overwrite` → `os.replace`, retried on Windows
  while the target is open in another program (6 tries, about 1.5 s, as decision 0015).
- `ask`: the job fails with C-8's `output.exists` issue (its fixes "Save as …" and "Always
  overwrite"), and **the complete `.part` file is kept** whatever `partial_file` says: an
  encode of hours is not thrown away because of a name.

### 8. Clean-up and close

- When a run ends, `EncodePlan.files` and `temp_files` are always removed. The `.part` file:
  removed on cancel; on failure when `partial_file` is `delete` (kept on `keep`, and in the
  `ask` case above); renamed on success.
- **`close()`**: no new jobs; running and paused jobs are stopped and end **`interrupted`**
  (as after a crash; "Reframe was closed while the job was running."), their `.part` files
  removed as on cancel; a job that was scheduled but had not started stays `waiting`. Then
  the inhibitor is closed and the store flushed. `Reframe.close()` closes the queue first.
- **Restore**: `running` and `paused` rows become `interrupted` ("Reframe stopped while the
  job was running."); their plan files and temporary files are removed in the background,
  and their `.part` file as for a failure (by `partial_file`).

### 9. When done, sleep inhibit

- When-done runs once when the queue empties after a job ended on its own (done or failed):
  nothing runs and nothing is left that the runner would take (no waiting job; with
  `start(job_ids=…)`, none of those). Not when the user cancelled the last job or Reframe
  closed.
- `nothing`; `notify` → a `notification` event ("Queue finished", "3 jobs done, 1 failed.",
  level `success` or `warning`). `quit`, `sleep`, `shutdown` need C-14's power actions: an
  `app.warning` `queue.when_done_unavailable` says that nothing was done.
- Sleep inhibit (when `queue.sleep_inhibit`): `acquire("Reframe is encoding <file>")` when a
  job starts running and when it resumes, `release()` once when it is paused or ends,
  `close()` with the queue. Each job holds at most one count.

### 10. Events, log, failure texts

- Order: `add` → `job.state` (`previous=None`), `queue.changed`. A run → `job.state`
  (`running`), `job.progress` (0 %), then progress and log while it runs, `job.state`
  `running` ↔ `paused`; at the end the last `job.progress` (100 % when done), the last
  `job.log` batch, then `job.state` with the end state and `error`, after the files are
  handled. `remove` and `reorder` → `queue.changed`; `retry` → `job.state`.
- Log file `<data dir>/logs/<job id>.log`: a header per run, each step's full command line
  (measured values filled in), every stderr line, how each step ended (exit code, seconds),
  the outcome and the total time. `job.log` events: at most one per 0.25 s per job with at
  most 200 lines; the oldest lines of a busier interval are counted in `dropped`.
- `error` is one short reason: a known cause first ("No space left on device: the disk is
  full."), else the first two lines in the last 40 that read like errors, without FFmpeg's
  `[module @ 0x…]` prefixes and the generic follow-ups ("Conversion failed!"); for a
  non-zero exit the last plain line as a fallback (not for a crash). Prefixed with what
  failed and how: "The encode failed (exit code 1): …", "ffmpeg crashed during pass 2
  (signal 11 (SIGSEGV)).".

## Consequences

- C-15 and the server code against the contract plus `start(job_ids=…)`, the three
  exception classes; `QueueService` has no other public member.
- A UI shows a speed and an ETA that hold still while paused and after a wake; FFmpeg's own
  `speed` is never shown after a pause.
- A truly hung FFmpeg is stopped after 10 active minutes; an encode that uses CPU is never
  stopped by time.
- Two Reframe processes sharing one data folder would both run the store's jobs; the desktop
  app is single-instance (D-x), and SQLite keeps the file consistent. Revisit with the
  server (S-x) if it can run next to the desktop app.
- WAL needs a local folder for the data dir (not a network share); `REFRAME_DATA_DIR` on a
  share is not supported for the queue.

## Plan changes

- `docs/plan/05-core.md` §C-11: the success bullet (the output is checked before the rename;
  `ask` keeps the complete `.part` file), the store, timeout, close and ETA notes point here.
- `docs/plan/03-features.md` §Queue: output safety names the `ask` case and the output check.

## Follow-up (M2 review), 2026-10-14

### Context

The M2 review found two blockers and three smaller faults in the queue:

1. **B1.** Every `Reframe.create()` restored the store, so any second Reframe process (even
   `reframe name` or `probe`) marked the first process's running job `interrupted` and removed
   its `.part` file; the first encode then ended "wrote no output". Reproduced by
   `tests/queue/test_owner.py::test_a_second_process_leaves_a_running_encode_alone` (two real
   processes): the saved row said `interrupted` while the job ran.
2. **B2.** A source named `Foo.part.mkv` with the output `Foo.mkv`, or an output folder that is
   a link to the source's folder: the `.part` file (or the final name) is the source. The job
   wrote over the source and was reported done, or failed and its clean-up removed the
   source. Reproduced by `test_faults.py::test_a_source_named_like_the_part_file` and
   `test_an_output_folder_that_links_to_the_source_folder[final|part]`.
3. `pause()` and `resume()` of one job at the same time: with a slow suspend the job stayed
   `paused` with its process stopped, and `resume()` had done nothing
   (`test_queue.py::test_pause_and_resume_at_the_same_time`).
4. `holds_inhibit` was set before the awaited `acquire()`. When the caller of `resume()` was
   cancelled during the acquire (the inhibitor undoes that count), the job later released a
   count it did not hold and so freed another running job's lock
   (`test_a_cancelled_resume_does_not_unbalance_the_sleep_inhibit`).
5. A file name that is not UTF-8 (`bad\xffname.mkv`, Python's lone surrogate `\udcff`)
   crashed `add`: `model_dump_json` refuses lone surrogates, and SQLite text must be UTF-8
   (`test_lone_surrogates_round_trip_in_the_store`, `test_a_file_name_that_is_not_utf8`).

Each test failed before its fix and passes after it.

### Decision

1. **Decision 0027 items 1–4.** `Reframe.create()` does not open the store. Any
   `QueueService` method opens it at its first use (blocking once: the lock is taken without
   waiting and the store is a small local file). The opener takes an exclusive lock on
   `<data dir>/queue.lock` (`reframe.queue.lock`: POSIX `flock`; Windows `msvcrt.locking` on one
   byte at 1 GiB, so the pid text at the start stays readable, mock-tested) and writes its pid
   there; it holds the lock until `close()`. The lock descriptor is not inherited by FFmpeg.
   Only the owner restores (running and paused rows become `interrupted`, leftover files are
   removed) and runs the store's jobs. A process that cannot take the lock keeps its jobs in a
   private SQLite database in memory and sends `app.warning` `queue.store_busy` ("Another
   Reframe process (pid N) is using the saved queue. The jobs of this process run here and
   are not kept after it ends."). A lock file that cannot be created (the data folder is not
   writable) gives the same private queue with `queue.unreadable`. After `close()` the queue
   does not open the store any more. Two `QueueService` objects in one process on one data
   folder behave like two processes (an `flock` of another open file description conflicts).
2. **Decision 0027 item 5 (the run-time guard; C-8 adds the same check to validation).**
   Before the first step, the `.part` file, every plan file, every statistics file and the
   final name are compared with the source: `os.path.samefile` when both exist (links, hard
   links), else the paths after resolving links, compared without case (this errs on the safe
   side on Linux). A clash fails the job with the error issue `queue.writes_source`
   ("Foo.part.mkv is the source file itself (…): the job would write over or remove its
   source, so nothing was written or removed."); nothing is written or removed. Every
   clean-up (end of a run, restore) also skips a path that is the job's source.
3. **One lock per job** (`ActiveJob.control`) orders `pause`, `resume`, the start-of-run
   inhibitor acquire and the end-of-run release; a pause or resume of a job whose run ended
   does nothing.
4. **The job holds its inhibitor count only once `acquire()` returned**; the release gives
   back only a count that the job holds.
5. **File names that are not UTF-8.** The store writes JSON columns with `json.dumps(…,
   ensure_ascii=True)` from `model_dump(mode="json")` (a lone surrogate becomes a `\udcXX`
   escape that `json.loads` restores; the text stays UTF-8) and reads them with `json.loads`.
   A path or error text with lone surrogates is a BLOB of its exact code units (UTF-8 with
   `surrogatepass`); plain text stays TEXT, so older files read the same. Such a path is
   stored and loaded back unchanged. Messages, `job.state` errors, `job.log` lines and the log
   file show it as the escape `\udcff` (valid UTF-8, so a JSON encoder or a log never fails);
   plan files are written with `surrogateescape`, so FFmpeg gets the original bytes.

### Consequences

- `reframe probe`, `plan`, `name` and `encoders` never touch the queue store, and a second
  `reframe encode` runs on its own private queue next to the first.
- A desktop or web app started while a CLI encode runs gets a private queue until it is
  restarted (0027).
- Not fixed here (other steps): C-16's naming rule fails on a name with a lone surrogate
  (`reframe/naming/sanitize.py` `_size` encodes as strict UTF-8; validation then reports
  `validation.rule_failed`), and a `QueueJob` or `JobSettings` with such a path still cannot
  go through `model_dump_json()` (the server will need `model_dump(mode="json")` plus an ASCII
  JSON encoder, as the store does).

### Plan changes

- None in this commit: 0027 changed 03 §Queue and 05 §C-11.
