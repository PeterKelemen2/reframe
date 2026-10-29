# 0062 — Review of C-17: findings, the lead's checks, and outcomes

- Status: accepted
- Date: 2026-10-29
- Steps: C-17 (with S-7's attachments); milestone M3b

## Context

C-17 was merged into `m3b-shared-queue` with the lead's checks
([0061](0061-c17-remote-queue-and-queue-commands.md), "The lead's checks"). The milestone's
review then ran as for every milestone: two fresh agents at effort `xhigh` reviewed
`git diff main...m3b-shared-queue` at c84c6cb. They were given the code, the plan and the
authors' records, not the lead's conclusions.

- **R1**, the core (`reframe.remote`, the output claims, the saved queue, the test guard):
  1 blocker, 3 majors, 9 minors, 6 nits. Of its 30 mutations, 13 were caught, 14 survived and
  3 were equivalent.
- **R2**, the CLI (client mode, `--detach`, `reframe queue`, the real-process checks):
  1 blocker, 2 majors, 8 minors, 5 nits. Of its 23 mutations, 10 were caught and 13 survived.

Before any fix the lead ran every blocker and major again, and each one reproduced:

- R1 B1: `ADD DID NOT RETURN in 3 s (threads blocked on the share: 2)`, and 7 threads were
  blocked after six attempts.
- R1 M1: `wait() DID NOT RETURN IN 8 s`.
- R1 M2: with the events 30 ms behind the REST answers, `start(job_ids)` raised
  `UnknownJobError` for a job that had just been added.
- R1 M3: `reframe encode` was stopped with SIGSTOP. The job was `cancelled` on the owner after
  29 s, and the client printed `interrupted`.
- R2 F1: with real processes, `reframe encode` still ran 90 s after its last job ended.
- R2 F2: `the retried job ended cancelled with the command`.
- R2 F3: the mutation that cancels every running job of the queue passed both "only its own
  jobs" tests.

Three fix agents worked at the same time, each on its own files: A (the queue core), B (the
remote client) and C (the CLI and the server's attachments). B and C built to a written
contract. Each part is recorded in 0061, "Follow-up: the review fixes".

## Decision

| # | Severity | Finding | Outcome |
|---|----------|---------|---------|
| R1 B1 | blocker | Every `add` and `retry` waited on the share of each restored job that had no keys yet | Fixed (A). An add or a retry takes only its own job's keys. A restored job without keys is compared by its paths as written, with no file-system call. When its keys arrive it is checked again, and on a clash the restored job fails, never the newer one. Re-run: the add returned in 0.00 s, with one thread on the share (the restored job's own) |
| R2 F1 | blocker | `encode`/`batch` never ended after another front end removed one of its waiting jobs | Fixed (C). The command follows `queue.changed` and `resync`, prints `[i/N] removed`, counts it in the summary, exits 1, and starts the jobs that are still there again after a refused start. Re-run with real processes: `[2/2] removed`, then `Summary: 1 done, 0 failed, 0 cancelled, 1 removed, 0 not queued.`, exit 1 |
| R1 M1 | major | A start that the owner refused was only logged, so `wait` hung | Fixed (B). The next awaited call raises the refusal (the B–C contract, item 1), and the CLI handles it (C). Re-run: `wait` raised `UnknownJobError` |
| R1 M2 | major | A `queue.changed` older than an add removed the new job from the copy | Fixed (B). A `queue.changed` removes only jobs that the stream has shown, and it reads the whole queue when it cannot tell. The lead's mutation LB1 (the job kept in `get()` but not in `list()`) survived at first; B's tests now check `list()` too. Re-run with a 30 ms lag: no job missing; an encode of 6 files exited 0 |
| R1 M3 | major | A stopped client had its running job cancelled after about 30 s | Fixed for Ctrl+Z (C). SIGTSTP pauses the command's running jobs, closes with `detach` and stops the command. SIGCONT reconnects, resumes the jobs and follows them. After a lost connection, the jobs' states are read from the owner or the saved queue. Re-run with SIGTSTP for 50 s: the job stayed `paused`, then ended `done`, exit 0. Known limits: SIGSTOP and a debugger; `kill -9` of a stopped command leaves its jobs paused |
| R2 F2 | major | A job retried by another front end was cancelled when the original command closed | Fixed (C) as the lead decided: a retry releases the job from every attachment (the retry route, `EventHub.release`). A connection's end cancels only jobs that have not ended, and the command keeps each job's first end. This revisits [0057](0057-s7-attachments-client-id-and-detach.md)'s Consequences. Re-run: the retried job ran on after the command ended |
| R2 F3 | major (tests) | The "only its own jobs" tests gave the other client only a waiting job | Fixed (C). `parallel_jobs` is 2, so the other client's job is running when the SIGINT comes, and it then ends `done`. R2's mutation now fails both tests |
| R1 m1 | minor | The token was in websockets' DEBUG log | Fixed (B): the client's websockets logger logs nothing at DEBUG |
| R1 m2 | minor | The started owner inherited the server's `REFRAME_*` options; its stderr was lost | Fixed (B). The server's options are removed and the folders are passed as absolute paths. stderr goes to `<data>/logs/server.log`, and a failed start points to it |
| R1 m3 | minor | `REFRAME_ENDPOINT_FILE` was read two ways | Fixed (B): a blank value means unset on both sides |
| R1 m4 | minor (plausible) | The client's look at `queue.lock` holds it for a moment | Kept, as a known limit (B). Without the look, the client would have to start a server (0.81–0.87 s to exit 75), and a pid in the lock file is not reliable after a reboot. Owners started by clients take `server-start.lock` first |
| R1 m5 | minor | An event that the reader could not read ended the connection | Fixed (B): it checks the type first and skips what it does not use or cannot read |
| R1 m6 | minor | Every add and every end cost each client a read of the whole queue | Reduced (B). On 845 jobs an add went from 0.23–0.34 s to 0.008–0.014 s, and a cancel from 0.22–0.36 s to 0.003–0.008 s. Each client still reads once per run end and once per add by another front end; a route for one job would remove both reads (not built) |
| R1 m7 | minor | The saved queue of a UNC data folder could not be read, and the docstring understated the immutable fallback | Fixed (A). The URI keeps both slashes of a UNC path. An immutable read says that the changes in the `-wal` file may be missing. Not run on Windows |
| R1 m8, m9 | minor | Weak tests (14 mutants survived); the guard missed `REFRAME_ENDPOINT_FILE` and had no test | Fixed (A, B). New tests kill each named mutant. The guard covers the endpoint file and is tested by an inner pytest session |
| R1 nits | nit | `Owner.started`, folder labels in texts, the `when_done()` fallback, the `CREATE_NO_WINDOW` row | Fixed (B). The owner's working folder stays the data folder (it holds the lock and the store) |
| R2 F4, F5 | minor | Ctrl+C during the adds of `--detach` left a job waiting; an owner that stopped during the adds left jobs without naming them | Fixed (C, with B's text for an empty exception) |
| R2 F6 | minor | A token that is not a valid header value appeared in warning and error lines | Fixed (B). Such a token is refused without showing it, and httpx's error text is redacted |
| R2 F7 | minor | The command followed a countdown that its jobs did not start | Fixed (C): it follows a countdown only after one of its jobs ran |
| R2 F8 | minor | Another front end's Stop leaves the command waiting without a word | Not built, as the lead decided: no event shows a stop. It is to be built with the UI's Stop (M4). Recorded in [0042](0042-one-scheduler-process-and-cli-clients.md) open question 5 and in the C-17 status row |
| R2 F9, F10 | minor | `log -f` was not live, and ended with 0 when the owner stopped | Fixed. A flushes the log file with the log's events. C makes `log -f` end with an error and exit 1, and reads the copy on the event loop |
| R2 F11–F16 | minor, nits | Weak CLI tests, the `REFRAME_IN_PROCESS` rule, exit codes of actions the state refuses, messages, `REFRAME_POWER_DRY_RUN` in the real-process tests, the status row's wording | Fixed (C). One real-process test checks the owner's environment |
| Lead L1 | test gap | `retry` without the restored jobs' keys survived | Fixed (A): a test with a retry against a restored job whose keys are being taken |
| Lead | nit | `Queued 1 job.` was printed for a job the owner added `failed` | Fixed (C): it counts only waiting jobs |
| Lead LA3 | test gap | A restored waiting job that is cancelled and then retried while its keys are taken keeps keys taken seconds before the retry's | Accepted: same job, same paths, a window of one slow share |

## Consequences

- The lead's mutations of the fixes: A 3 (2 caught, LA3 accepted), B 3 (2 caught, LB1
  closed by B), C 3 (all caught).
- On the merged branch (e55998e): ruff, the format check, mypy (Linux and win32) and
  `scripts/gen-api.sh --check` pass. The whole suite (`-m "not needs_gpu"`, four parts) had
  7,373 passed, 2 skipped and none failed.
- Every blocker and major was re-run on the merged branch, with the results in the table.
- C-17's checks 1–7 were run again with real processes on the merged branch (the lead's
  script, as in 0061). All pass, and every process was ended. Check 1: the two jobs did not
  overlap (one ended 1.7 ms before the other started). Check 4 now reports the job's state from
  the saved queue. Check 6 no longer prints `Queued 1 job.`.
- **The M3b demo** ([08](../plan/08-roadmap.md#m3b--shared-queue)) ran for real on Linux on
  2026-10-29, on the merged branch, with real FFmpeg and private folders:
  1. Two `reframe encode` runs of two files each, with `parallel_jobs` 1. A third command's
     `reframe queue list` showed `4 jobs: 3 waiting, 1 running.` Ctrl+C in the first run
     gave exit 130 and `2 cancelled`. The second run ended `2 done` with exit 0, and no
     `.part` file was left.
  2. Two runs, with `parallel_jobs` 2. After `kill -9` of one, its job was `cancelled` and
     its `.part` file removed, while the other job was still `running`. The other run then
     ended `1 done` with exit 0.
  3. A third client whose output a `--detach` job already claimed exited 1 with
     `[queue.output_claimed · output.path]`, and its job was `failed`. The claiming job stayed
     `waiting`.
- Known limits:
  - SIGSTOP or a debugger on a client: the owner cancels its jobs after 20–40 s.
  - `kill -9` of a command stopped with Ctrl+Z leaves its jobs paused.
  - The client's look at `queue.lock` (R1 m4).
  - A whole-queue read per run end.
  - 0042 open question 5.
  - Nothing ran on Windows.
- For later (C's note): the OpenAPI descriptions of `Hello.client_id` and `AddJobs.attach` do
  not say that a retry releases a job. Changing them regenerates `schema.d.ts`; no client
  depends on the text.

## Plan changes

None beyond 0061's follow-up: 05 §C-17 (B, C), 0042 open question 5 (C), and the C-17 and
M3b rows of `docs/status.md`.
