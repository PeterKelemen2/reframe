# 0092 — No Reframe Python code in a forked child

- Status: accepted
- Date: 2026-11-18
- Steps: C-1 (child safety), Q-7

## Context

C-1 sets `PR_SET_PDEATHSIG` on Linux "with ctypes `prctl` in `preexec_fn`". The `preexec_fn` was a
Python closure in `reframe/platform/childproc.py`: it called `prctl`, then killed the child if its
parent had already died (`os.getppid()` changed before `prctl` took effect).

Two whole-suite coverage runs hung for good: the first per-test coverage run of the Q-7 audit
(audit decision D-4, C tracer with per-test contexts) and the coverage rerun of package Q-7.3 on
2026-11-17 (`sys.monitoring` tracer, 23:03 to 23:52 until the child was killed by hand). Both
times an xdist worker had forked a child for a tool, and the child stayed in `futex_wait` before
`exec` while the worker waited for it.

The Python documentation says `preexec_fn` is not safe in a process with threads: the child can
deadlock before `exec`. Coverage 7.16's `sys.monitoring` tracer (`coverage/sysmon.py`,
`sysmon_py_start`) takes its locks (`lock_data`, `self.lock`) the first time a code object of a
measured file runs. The closure ran only in children, never in the parent, so in every child it
was new code of a measured file. When another worker thread held one of those locks at the moment
of the fork, the child's copy of the lock was held forever.

A probe shows it without coverage (`sys.monitoring` tool whose `PY_START` callback, in a forked
child, takes a lock the parent holds, for code under the `reframe` package only, as coverage
does): the spawn hangs with the old `preexec_fn` (`timeout 15` → exit 124) and returns at once
with the new one (exit 0). A stress run without such a lock (6 spawning threads, 4 threads making
new code; 3,629 spawns plain and 1,123 under coverage) did not hang: the window is short, so the
hang is rare.

Any `preexec_fn` makes CPython call `PyOS_AfterFork_Child()` in the child, which runs the
`os.register_at_fork` hooks (Python code from the standard library). Coverage measures only
`reframe` and `reframe_server`, so it takes no lock for those.

## Decision

1. The `preexec_fn` is libc's `prctl` with its arguments bound (`functools.partial(prctl,
   PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)`). No Reframe Python code runs between `fork` and `exec`.
   Where libc has no `prctl`, there is no `preexec_fn`.
2. The re-check of the parent after `prctl` is dropped: it needs Python code in the child.
3. The tests that pass their own `preexec_fn` (SIGINT back to its default for a real CLI process)
   use `functools.partial(signal.signal, signal.SIGINT, signal.SIG_DFL)`.
4. `test_a_tracer_lock_held_at_the_fork_does_not_block_a_spawn` runs the probe in a subprocess.

## Consequences

- A tracer or profiler that measures Reframe's code (coverage, `--cov`) can no longer block a
  spawn this way. The per-test timeout of Q-7.13 stays the guard against any other hang.
- Lost: if Reframe dies in the microseconds between `fork` and `prctl` in the child, the tool is
  not killed by the death signal. The runner's tools write to pipes that only Reframe reads, so
  such a tool dies of `SIGPIPE` on its next write to stdout or stderr; one that writes nothing
  until the end runs to its end.
- `test_preexec_kills_itself_when_the_parent_is_already_gone` is removed with the re-check.
- Not changed: a `preexec_fn` still makes every spawn a full fork (audit SPD-06, Tier C).

## Plan changes

- `docs/plan/05-core.md` C-1: the child-safety line says the `preexec_fn` is a C callable.
