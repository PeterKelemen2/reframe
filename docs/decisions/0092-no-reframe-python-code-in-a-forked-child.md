# 0092 — No Reframe Python code in a forked child under a tracer

- Status: accepted
- Date: 2026-11-18
- Steps: C-1 (child safety), Q-7

## Context

C-1 sets `PR_SET_PDEATHSIG` on Linux "with ctypes `prctl` in `preexec_fn`". The `preexec_fn` is a
Python closure in `reframe/platform/childproc.py`: it calls `prctl`, then kills the child if its
parent has already died (`os.getppid()` changed before `prctl` took effect).

Two whole-suite coverage runs hung for good: the first per-test coverage run of the Q-7 audit
(audit decision D-4, C tracer with per-test contexts) and the coverage rerun of package Q-7.3 on
2026-11-17 (`sys.monitoring` tracer, 23:03 to 23:52 until the child was killed by hand). Both
times an xdist worker had forked a child for a tool, and the child stayed in `futex_wait` before
`exec` while the worker waited for it.

The Python documentation says `preexec_fn` is not safe in a process with threads: the child can
deadlock before `exec`. Coverage 7.16 (both tracers) takes its data lock (`lock_data`) the first
time a code object of a measured file runs. The closure ran only in children, never in the parent,
so in every child it was new code of a measured file. When another worker thread held that lock
at the moment of the fork, the child's copy of the lock stayed held forever. A count of
`lock_data` calls made in forked children over 3 spawns under coverage: 3 with the closure, 0
with a C callable, for both the C tracer and `sys.monitoring`.

A probe shows it without coverage: a `sys.monitoring` tool whose `PY_START` callback, in a forked
child, takes a lock that the parent holds, for code under the `reframe` package only (as coverage
does). The spawn hangs with the closure (`timeout 15` → exit 124) and returns at once when the
`preexec_fn` is a C callable (exit 0). A stress run without such a lock (6 spawning threads,
4 threads making new code; 3,629 spawns plain, 1,123 under `sys.monitoring` coverage, 3,566 under
the C tracer) did not hang: the window is short, so the hang is rare.

Any `preexec_fn` makes CPython call `PyOS_AfterFork_Child()` in the child, which runs the
`os.register_at_fork` hooks of the standard library (`threading`, `logging`, `random`, `asyncio`)
before the `preexec_fn`. Coverage measures only `reframe` and `reframe_server`, so it takes no
lock for those. The hooks take about 1 ms (median 1.1 ms, at most 2.8 ms, measured with
`reframe.tools` and the server loaded); the parent check covers that time.

Without the parent check, a tool whose parent dies in that window keeps running. The runner gives
tools pipes for stdout and stderr, but FFmpeg ignores `SIGPIPE`: with both pipes closed it runs an
encode to its end (verified, `testdata/README.md` "Verified tool behaviour"). So the check matters
for Reframe itself.

## Decision

1. Without a tracer or profiler (`sys.gettrace()`, `sys.getprofile()` and no `sys.monitoring`
   tool), the `preexec_fn` stays the Python closure with the parent check.
2. Under a tracer or profiler, the `preexec_fn` is libc's `prctl` with its arguments bound
   (`functools.partial(prctl, PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)`), so the child runs none of
   Reframe's Python code; without `prctl` there is no `preexec_fn`.
3. The tests that pass their own `preexec_fn` (SIGINT back to its default for a real CLI process)
   use `functools.partial(signal.signal, signal.SIGINT, signal.SIG_DFL)`.
4. `test_a_tracer_lock_held_at_the_fork_does_not_block_a_spawn` runs the probe in a subprocess; it
   exits with 97 after 3 s instead of hanging when the child runs Reframe's code.

## Consequences

- A coverage run (`--cov`, the Q-7 coverage comparison) or a debugger can no longer block a spawn
  this way. The per-test timeout of Q-7.13 stays the guard against any other hang.
- Under a tracer only: if the process dies within about 1 ms after a fork, the tool keeps running
  (an FFmpeg encode to its end). Reframe as shipped runs without a tracer and keeps the check.
- The choice is made per spawn, so a tracer started later (a debugger attached to the running
  app) takes effect at the next spawn.
- Not changed: a `preexec_fn` still makes every spawn a full fork (audit SPD-06, Tier C).

## Plan changes

- `docs/plan/05-core.md` C-1: the child-safety line names the closure and the tracer case.
