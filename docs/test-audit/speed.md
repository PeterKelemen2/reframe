# Speed audit of the Python test suite (Phase 1b)

All paths and line numbers refer to `38cf3eb848e6267522daac27eb219e75993b2e36`. Nothing was
committed; the worktree has no change to tracked files (`git status`: only the `testdata/media`
symlink from the set-up).

Machine: AMD Ryzen 5 5600, **6 physical cores, 12 logical**, 31 GB, `/tmp` on tmpfs.
Tools: pytest 9.1.1, pytest-xdist 3.8.0, Hypothesis 6.169.0, Python 3.14.8.

## The premise of the brief is off by a factor of two

`-n auto` does **not** start 12 workers on this machine. xdist's `auto` asks psutil for the
*physical* core count (`xdist/plugin.py:31-32`), and psutil is installed (the tests use it), so
`-n auto` starts **6 workers** (checked: `created: 6/6 workers`). `-n logical` would start 12.

So the baseline's 1,797 s of test time on 6 workers needs at least about 300 s, not 150 s. The
time not spent running tests in parallel is about **73 s of 373 s**, not 220 s:

- worker start and collection: about 4.6 s (every worker has collected at 3.7–4.6 s; they collect
  at the same time);
- gaps between tests inside a worker: under 1 s per worker in total;
- **the tail: about 50–65 s.** Four workers finish, and one or two run on alone (below).

A small scheduling simulator (`speed/sim.py`, a copy of xdist's `load` and `worksteal`
algorithms fed with recorded per-test times) reproduces the real runs within 1 %: 369 s for the
baseline junit times (real: 373 s) and 516 s for run 1's times (real: 517 s). The tier and
saving claims below use both the real runs and this simulator.

## Measurements

Every full run used `uv run pytest -m "not needs_gpu" -q -p no:cacheprovider` plus a timeline
plugin from the scratchpad (`-p timeline_plugin`, `PYTHONPATH=speed/plugins`; it only records
wall clock and CPU time per test). "Other runs" = samples (every 15 s) in which another agent's
`pytest`/`coverage run` was running. "CPU busy" = the whole machine, from `/proc/stat`.

| Run | Command (extra args) | Load during the run | Wall | Result |
|-----|----------------------|---------------------|------|--------|
| baseline (owner) | none (`-n auto` = 6 workers, `--dist load`) | nothing else running | 372.8 s | 8,576 passed, 14 skipped |
| 1 | none (6 workers, `load`) | other test runs in about half the samples from minute 3.5 on, load average up to 40 | 522.3 s | 8,576 passed, 14 skipped |
| 2 | `--dist worksteal` + language split (SPD-02) | other runs in 24/32 samples, CPU busy 97 %, load avg mean 25 | 471.5 s | 8,586 passed, 14 skipped |
| 3 | `-n logical --dist worksteal` + split (12 workers) | other runs in 3/22 samples, CPU busy 99 %, load avg mean 29 | 325.9 s | 8,586 passed, 14 skipped |
| 4 | `--dist worksteal` + split (6 workers) | **no other runs (0/22)**, CPU busy 89 %, load avg mean 17 | **322.4 s** | 8,586 passed, 14 skipped |

(8,586 = 8,576 + 10: the split turns 2 tests into 12.)

Worker finish times (s), which show the tail:

| Run | Finish times of the workers | Spread |
|-----|-----------------------------|--------|
| 1 (`load`) | 382, 382, 384, 388, **483** (test_shared_queue_real), **517** (test_equivalence) | 135 s |
| 2 (`worksteal` + split, loaded) | 447, 450, 452, 458, 461, 468 | 21 s |
| 3 (12 workers) | 269 … 322 | 53 s |
| 4 (`worksteal` + split, quiet) | 309, 311, 315, 315, 317, 319 | 10 s |

In run 1, worker gw5 got `languages/test_equivalence.py` as part of one contiguous chunk and ran
all 16 of its tests one after the other: 307 s from second 200 to 507 (the 88 s test took 152 s
under that load). gw1 did the same with `remote/test_shared_queue_real.py`. `--dist load` sends
contiguous chunks of the collection (`xdist/scheduler/load.py:279-288`: first chunk = 1/4 of a
worker's share, about 360 tests), and a worker never gives back what it was sent.

Simulator, baseline (unloaded) per-test times, wall time in s:

| Collection | Workers | `--dist load` | `--dist worksteal` | ideal (sum / workers + 4 s start) |
|------------|---------|---------------|--------------------|------------|
| as now | 6 | 369 | 350 | 304 |
| language sweeps split (SPD-02) | 6 | 372 | **318** | 304 |
| as now | 12 | 241 | 221 | 154 (not reachable: see SPD-03) |
| split | 12 | 281 | 168 | 154 (not reachable) |

Focused runs (fake-tool-heavy folders: `packages/reframe/tests/{capabilities,queue,probe,jobs}`
and `testing/tests/test_fake_ffmpeg.py`, 1,374 tests, `--dist worksteal`, 6 workers, no other
test runs in any of them; run in the order A1, B1, B2, A2):

| Run | Fake launcher | Wall | Sum of test times |
|-----|---------------|------|-------------------|
| A1 | as now (`runpy.run_path`) | 59.7 s | 339 s |
| B1 | import from the cached `.pyc` (SPD-04) | 54.0 s | 306 s |
| B2 | import from the cached `.pyc` | 57.2 s | 319 s |
| A2 | as now | 64.0 s | 366 s |

Micro-measurements (Linux, load average 4–15 while measured):

- `uv run pytest --collect-only -q -n 0`: 16.8 s wall, 16.1 s CPU, with a coverage run on the
  machine (load 13.7); cProfile without load: 9.5 s, of which test-module imports with assertion
  rewrite 4.3 s, node creation for 8,616 items about 2.7 s, `models/test_schema.py` module level
  1.4 s (it builds 223 JSON schemas at import). In a worker (with warm `.pyc`) collection ends
  2.3 s after `pytest_configure`.
- Fake `ffmpeg -version` start: 26–34 ms; `python -I -c pass` 8.6 ms; the fake's imports about
  10 ms (`json` 2.7, `pkgutil` via `runpy` 2.3, `subprocess` 2.3, `site` 1.6, `typing` 1.5,
  `pathlib` 1.4 ms) plus compiling `fake_ffmpeg.py` (481 lines) on every call.
- One full run (run 4) made **17,862 fake-tool calls** in 1,302 fake-tool folders, and left
  48,522 files (1.3 GB) in its pytest base temp folder.
- `reframe.cli` import 0.77 s, `reframe_server.app` 1.25 s, `reframe.service` 0.72 s (each CLI
  started by a test pays this).
- Spawn of `/bin/true` from a 300 MB process: 0.40 ms without `preexec_fn` (vfork), 4.91 ms with
  a `preexec_fn` (fork, page tables copied, Python runs in the child).
- `test_equivalence.py`, CPU time per function of the 88 s test (215,688 tags): `native_name`
  50.2 s, `english_name` 11.4 s, `normalize` 6.7 s, `to_matroska_legacy` 6.3 s, `to_mp4` 6.1 s;
  a second `normalize` pass 4.6 s (caches help little, so splitting costs little). Split runs
  (`-n 12`, load 13): 8 parts of the 88 s test 14–18 s each, 4 parts of the 46 s test 22–24 s
  each; both tests together 27.9 s wall.
- `tools/test_runner.py` alone (`-n 0`): `test_kill_process_tree_can_keep_the_root` 5.06 s,
  `test_the_pid_lets_the_caller_suspend_and_resume_the_tree` 4.77 s,
  `test_timeout_kills_the_whole_tree` 3.02 s, `test_a_grandchild_holding_the_pipe_does_not_block`
  2.03 s; all four use under 0.2 s of CPU.

## Findings

### SPD-01 — `--dist worksteal` instead of `load`

- **Where:** `pyproject.toml` `[tool.pytest.ini_options]` `addopts` (lines 8-17).
- **Now:** `--dist load` (xdist's default). Contiguous chunks of about 360 tests go to each
  worker and stay there, so a file of long tests runs on one worker while the others are idle at
  the end (run 1: spread 135 s).
- **Change:** add `"--dist", "worksteal"` to `addopts`. An idle worker takes half of the queue
  of the worker with the most queued tests.
- **Saved:** alone, simulated 369 → 350 s (−19 s) on the baseline times; together with SPD-02,
  measured **372.8 → 322.4 s (−50 s, −14 %)** on a quiet machine (run 4 vs the baseline;
  the simulator says 318 s), and the finish spread drops from 135 s to 10 s. Under load the
  effect is bigger: run 1's times simulated with worksteal + split lose the 135 s tail (run 2
  ended with a 21 s spread under a load average of 25). Windows: the VM uses the same
  scheduler with 6 workers and the same collection order, so the same tail exists there;
  expect a similar share (about 10–15 % of the 12 minutes, 1–2 minutes), more if the CPU-only
  language sweeps are relatively slower on the VM.
- **Guarantee kept by:** the same tests run; only which worker runs them changes. Two full runs
  with worksteal passed (runs 2 and 4, 8,586 passed each).
- **Risk:** a test that relies on running after another test in the same worker (order
  dependence) could fail; none did in two full runs. Module-scoped fixtures can be set up on two
  workers (busy sum 1,856 s vs 1,797 s, +3 %, which includes the split's cost). CI gets the
  change through `addopts` (no workflow edit). `-n 0` is not affected.
- **Proposed tier:** A (one config line, no guarantee lost; the CI effect is only scheduling).
- **Confidence:** high (two real runs plus a simulator that matches real runs within 1 %).

Verdict: CONFIRMED — worksteal keeps every test (8,586 passed + 14 skipped in both lever runs, the same ids as the split collection) and removes the tail. One number is off: with all levers on an idle machine the finish spread is 21–24 s, not 10 s. The four search parts of SPD-02 (19–24 s each under load) now form the tail. `-n 0` is not affected: xdist sets `dist = "no"` when `numprocesses == 0` (`xdist/plugin.py:325-327`), so `-n 0 --pdb` still works. Windows: the scheduler is controller-side Python (`xdist/scheduler/worksteal.py`) with no platform code, and a crashed worker's pending tests go back to the queue (`remove_node`, :252-280). Not run on Windows. Side effect: decision 0084 ("Consequences") tells authors to use `@pytest.mark.xdist_group` with `--dist loadgroup`, and `worksteal` ignores `xdist_group`. No test uses the mark today (grep), but the change needs an amendment to 0084 in the same commit.
Checked: `fullrun.sh v0-baseline` / `v3-baseline` (no change) → 373.3 s / 374.4 s, worker finish times 279…368 and 275…369 (spread 89 s / 94 s; gw5 or gw4 ran `test_equivalence.py` alone at the end). `fullrun.sh v1-all` / `v2-all` (all levers) → 294.2 s / 295.3 s, finish times 267…291 and 271…292. No other pytest before any run (`ps`), 1-min load 1.9–2.0 at each start, mean of the 15-s samples during the runs 11.2–12.4.

Orchestrator: Tier A, package Q-7.7. Amend 0084 (its `xdist_group` / `--dist loadgroup` advice does not apply under worksteal).

### SPD-02 — split the two slowest language sweeps into parametrized parts

- **Where:** `packages/reframe/tests/languages/test_equivalence.py:191-197`
  (`test_listed_languages_with_every_region_and_script`, 88 s) and `:275-277`
  (`test_search_every_name_in_every_locale`, 46 s).
- **Now:** one test each; the 88 s test alone bounds a 6-worker run from below and, with
  `--dist load`, the whole file (180 s) lands on one worker.
- **Change (as tried):**

  ```python
  @pytest.mark.slow
  @pytest.mark.parametrize("part", range(8))
  def test_listed_languages_with_every_region_and_script(part: int) -> None:
      ...
      tags = _combined(_listed_bases(), regions, scripts)[part::8]

  @pytest.mark.slow
  @pytest.mark.parametrize("part", range(4))
  def test_search_every_name_in_every_locale(part: int) -> None:
      assert _search_differences(_locale_names()[part::4])[:20] == []
  ```

- **Saved:** only together with SPD-01 (with `--dist load` all parts still go to one worker:
  simulated 372 s, no gain). With SPD-01: see SPD-01 (318 s simulated, 322 s measured, vs
  350 s for worksteal alone, so about −30 s of the −50 s). Windows: same share.
- **Guarantee kept by:** the stride slices `[part::N]` cover every tag and every name exactly
  once, and every part asserts that there is no difference. Only the failure message
  (`[:20]`) is per part.
- **Risk:** low. Total CPU of the sweeps rises a little (per-process caches are warmed per part;
  measured about +15 %), but it runs in parallel.
- **Proposed tier:** A.
- **Confidence:** high.

Verdict: ADJUSTED — the guarantee holds. `[part::8]` and `[part::4]` split the lists into disjoint parts that together cover every item. Each part asserts `[] == …[:20]`, and the ids `[0]`…`[7]` and `[0]`…`[3]` are deterministic (xdist accepted the collection of all 6 workers twice). The run gains 10 ids: 8,576 → 8,586 passed, 14 skipped. Correction: the CPU cost of the split is about 2–6 %, not about 15 %. Measured alone and in parallel on an idle machine: the 88 s sweep takes 55.6 s CPU unsplit vs 8 × 7.4 = 59 s split (+6 %); the search sweep takes 47.0 s vs 4 × 11.7–12.0 s = 47.5 s (+1 %). Stride and contiguous chunks cost the same. In the full runs, the search parts take 19–24 s each (sum 76–86 s vs 46–48 s unsplit). The cause is load, not the split: they run while all 6 workers are busy (SMT), whereas the unsplit test ran at the baseline's idle tail. Combined with TPM-01 (see "All levers together"), the parts of the 88 s sweep take 8.4–10 s each in the full run.
Checked: `python vspeed/tpm01.py fn|tag <test file> [3 8]` (4 processes at the same time, load 1–2) → fn 55.6 s, fn part 3/8 7.4 s; `python vspeed/search_split.py <file> all|stride|chunk 4 …` (4 processes, load 3–4) → all 47.0 s, stride parts 11.8–12.0 s, chunk parts 11.7–12.0 s, 0 differences in each. Full-run durations from `--durations=15` of `v1-all` / `v2-all`.

Orchestrator: Tier A, package Q-7.7.

### SPD-03 — `-n logical` (12 workers) is not faster

- **Where:** `addopts` `-n auto`.
- **Now:** 6 workers (physical cores).
- **Change tried:** `-n logical --dist worksteal` + split (run 3).
- **Saved:** nothing: 325.9 s with 12 workers vs 322.4 s with 6 (run 4); the difference is 1 %,
  inside the noise. The machine is CPU-bound at 6 workers already (89 % busy; FFmpeg runs are
  multi-threaded), so 12 workers only share the same cores: the sum of test times doubles
  (3,499 s vs 1,856 s). The real-time tests suffer most:
  `test_two_encodes_at_once_both_finish_and_share_the_slot_limit` took 88 s with 12 workers
  against 29 s with 6, so the load-sensitive tests get closer to their limits. Windows: the VM
  already runs 6 workers on 6 processors, and decision 0084 found 3 workers no faster; no
  change expected.
- **Guarantee kept by:** n/a.
- **Risk:** more load-sensitive failures.
- **Proposed tier:** C (keep `-n auto`).
- **Confidence:** high for this machine. (A CI runner whose psutil reports 2 physical cores for
  4 vCPUs might gain from `logical`; not measured.)

Verdict: CONFIRMED — `-n logical` (12 workers) is not faster. The report's comparison (run 3 vs run 4) was made at different loads, so I measured again on an idle machine with a focused set. Result: `-n 6` took 169.7 s and 159.2 s, `-n 12` 167.5 s, 154.1 s and 155.4 s wall (pytest's own times: 168.5 s, 158.1 s / 166.4 s, 153.0 s, 155.4 s). The means are 164.5 s vs 159.0 s, a 3 % difference, smaller than the 10 s spread between runs of the same setting. In 2 of the 3 `-n 12` runs, one test ended in an error (`1 error`); the output of those two runs was not kept, so the test is not identified. A third `-n 12` run, made to catch it, passed. The two `-n 6` runs passed. This fits the report's point that 12 workers bring the load-sensitive tests closer to their limits. The SPD-03 claim, the Tier C, and the advice to keep `-n auto` all stand.
Checked: `bash vspeed/nlogical.sh` (folders `validation`, `jobs`, `remote`, `reframe-server/tests`, 2,574 tests, levers applied, `-n 6` / `-n 12` alternated, each started at 1-min load < 3, nothing else running) → `n=6 169.7 s | 2567 passed, 7 skipped`; `n=12 167.5 s | 2566 passed, 7 skipped, 1 error`; `n=12 154.1 s | 2566 passed, 7 skipped, 1 error`; `n=6 159.2 s | 2567 passed, 7 skipped`; repeat `-n 12` (`vspeed/n12.out`) `155.4 s | 2567 passed, 7 skipped`. Load before each run 2.6–2.8.

Orchestrator: Tier C, not planned: not faster (re-measured).

### SPD-04 — the fake tools import `fake_ffmpeg` from its cached `.pyc`

- **Where:** `testing/reframe_testing/fake_tools.py:437-455` (`posix_launcher`) and
  `:474-485` (`windows_launcher`).
- **Now:** every fake call (17,862 per full run) starts the base interpreter with `-I` and runs
  `runpy.run_path(fake_ffmpeg.py)` (POSIX) or `python -I fake_ffmpeg.py --fake-tool …`
  (Windows `.cmd`). Both compile the 481-line source on every call (no `.pyc` for a script or
  `run_path`), and `runpy` imports `pkgutil`.
- **Change (as tried, POSIX):**

  ```python
  "import os, sys\n"
  f"os.environ.setdefault({SCENARIO_ENV!r}, {str(scenario)!r})\n"
  f"os.environ.setdefault({LOG_ENV!r}, {str(log)!r})\n"
  f"sys.path.append({str(script.parent)!r})\n"
  "import fake_ffmpeg\n"
  f"sys.exit(fake_ffmpeg.main({tool!r}, sys.argv[1:]))\n"
  ```

  (`append`, not `insert(0, …)`, so no module in `reframe_testing/` can shadow a standard
  module.) The Windows `.cmd` launcher would get the same `-c` body instead of running the
  script file. Optional next step, not measured: import `subprocess`, `typing` and `pathlib`
  in `fake_ffmpeg.py` only where they are used (about 5 ms more per call).
- **Saved:** one fake start 26.0 → 21.2 ms (−4.8 ms). Focused runs: wall 61.9 → 55.6 s mean
  (−10 %), sum of test times 352 → 312 s (two runs each, alternated, no other test runs).
  Full suite, projected: 17,862 × about 5 ms ≈ 90 s of test time ≈ **15 s wall** at 6 workers
  (about 4–5 %); not measured as a full run. Windows: more, because interpreter start and
  source compilation cost more there and every call also starts `cmd.exe`; if a fake call costs
  even 50 ms more on Windows than on Linux, the fake calls alone add about 15 minutes of test
  time (2.5 minutes of wall time on 6 workers), so this is worth checking on the VM first
  (`Measure-Command { .\ffmpeg.cmd -version }` in a `fake_tools` folder, with and without the
  change).
- **Guarantee kept by:** the same fake code runs with the same arguments and environment; the
  pid is the same (the launcher still `exec`s / is the process). The launcher-text tests
  (`testing/tests/test_fake_ffmpeg.py:709`, `:739`) need their expectations updated.
- **Risk:** low. The `.pyc` is written by the first call (CPython writes it atomically, so
  parallel workers are safe).
- **Proposed tier:** A.
- **Confidence:** medium-high on Linux (measured, two pairs, same direction, about 10 %);
  medium for the Windows size (reasoned, not measured).

Verdict: ADJUSTED — the Linux saving repeats. Four points need correction or adding:

(1) On POSIX no launcher-text test needs a change. `test_fake_ffmpeg.py:709` checks `exec … -I -c` (the `sh` fallback still has it) and `:739` checks only the shebang line: 201 passed / 1 skipped unchanged. The tests that would change are the Windows ones: `:757` (the `--fake-tool` run line) and `:794` (the full `.cmd` text).
(2) Windows: the `.cmd` launcher cannot take "the same `-c` body", because a `.cmd` line cannot hold newlines. The `.cmd` already sets both environment variables, so it needs a one-line `"<python>" -I -c "import sys; sys.path.append(r'<dir>'); import fake_ffmpeg; sys.exit(fake_ffmpeg.main('ffmpeg', sys.argv[1:]))" %*`, with `%` doubled as `_cmd_quote` does. With `-c`, `sys.argv[1:]` are the tool's arguments. Not run on Windows, so the Windows gain is still unmeasured (the report says so).
(3) `.pyc` and `-I`: the import works under `-I` (only `sys.path.append` is needed; `-I` means `-P`, so the script directory is not on `sys.path`, and nothing in `reframe_testing/` can shadow the standard library). `-I` ignores `PYTHONDONTWRITEBYTECODE` and `PYTHONPYCACHEPREFIX`, so the fake always writes `testing/reframe_testing/__pycache__/fake_ffmpeg.cpython-314.pyc` (git-ignored). This is the same file the pytest process writes when it imports `reframe_testing.fake_ffmpeg`. A stale `.pyc` happens only when the source changes within the same second and keeps the same size: CPython's timestamp check (shown below). Every module the test process imports has the same risk, so this adds no new risk class. If `__pycache__` cannot be written (read-only checkout), the import compiles in memory and works, at today's speed. The CI checkout is writable. When two processes write the `.pyc` at the same time, including the Windows case where `os.replace` fails on an open file, the `OSError` is swallowed (`importlib/_bootstrap_external.py` `set_data`, :996-1007).
(4) Full-suite effect, measured with all levers rather than projected: the test time of every file except `test_equivalence`, `tools/test_fetch*` and `tools/test_runner` falls from 1,510/1,520 s to 1,412/1,417 s (−100 s, −6.6 %). That fits the report's projection of about 90 s of test time (about 15 s wall).
Checked: `python vspeed/bench_launch.py ft/old ft/new` (5 rounds × 60 alternating `ffmpeg -version` calls, load 1.2) → old 25.3–26.3 ms (median 25.9), new 20.9–21.9 ms (median 21.3): −4.6 ms. `bash vspeed/pyc_check.sh` → a same-second, same-size edit gives the stale value `X = 1`; a later edit gives the new value; `PYTHONDONTWRITEBYTECODE=1` with `-I` still writes the `.pyc`; an unwritable folder still imports (no `__pycache__`). `uv run pytest testing/tests/test_fake_ffmpeg.py packages/reframe/tests/tools/{test_runner,test_fetch,test_fetch_cli}.py` with the change → 201 passed, 1 skipped. `python vspeed/groups.py <timelines>` → the "rest" sums above.

Orchestrator: Tier A, package Q-7.7. POSIX launcher only; the Windows `.cmd` launcher needs a one-line `-c` body and a check on the Windows test VM first (measure one fake call before and after).

### SPD-05 — a per-test timeout (pytest-timeout)

Not a speed lever but the answer to the hang in the orchestrator's coverage run, where one
hung test blocked the run for an hour.

- **Where:** `pyproject.toml` (dev dependency group and `[tool.pytest.ini_options]`).
- **Now:** no per-test timeout. CI jobs have `timeout-minutes: 30` (`.github/workflows/ci.yml:37`),
  which kills the job without a stack trace; a local run waits for ever.
- **Change:** add `pytest-timeout` (current stable, pinned in `uv.lock`) and

  ```toml
  timeout = 600
  timeout_method = "thread"
  ```

  *Value:* the longest single test seen today was 152 s (the unsplit 88 s language test under a
  load average of about 35, run 1) and 108 s (`test_sigint_in_one_client_cancels_only_its_own_jobs`,
  same run); after SPD-02 the longest is about 30 s. The VM is about 2× slower. 600 s leaves a
  margin of 4× over the worst case seen and still ends a hang within 10 minutes (and inside CI's
  30-minute job limit).
  *Method:* `thread` on Linux and Windows (Windows has only `thread`). On a timeout it dumps
  every thread's stack and ends the worker with `os._exit`; xdist reports
  "worker crashed while running <test>", starts a new worker and runs the rest. This ends any
  hang, also one where the main thread waits in C code or on a lock, and a hung child loses its
  reader (and with `PR_SET_PDEATHSIG` already set, dies with the worker). The `signal` method
  (SIGALRM, Linux default) keeps the worker but needs the main thread to get back to Python,
  and it would leave the forked child holding the pipes. pytest-timeout does not fire while a
  debugger is active, so `-n 0 --pdb` stays usable. pytest's own `faulthandler_timeout` only
  dumps stacks and does not end the hang, so it is not enough alone. No test uses SIGALRM
  (checked).
- **Saved:** a hang costs at most 10 minutes instead of the whole run; no effect on a normal run.
- **Guarantee kept by:** no test changes; tests with their own limits keep them.
- **Risk:** a legitimately slow test on a very slow machine could hit 600 s; none is near it.
- **Proposed tier:** B (new dev dependency and a CI-visible behaviour).
- **Confidence:** high.

**Can the runner's subprocess start deadlock outside coverage?** Short look:
`reframe.tools.runner._execute` (`runner.py:412-420`) passes `childproc.spawn_options()`,
which on Linux is `start_new_session=True` **and** `preexec_fn=linux_preexec()`
(`platform/childproc.py:288-294`, `:63-90`). A `preexec_fn` makes CPython fork (not vfork)
and run Python code in the child between `fork` and `exec`: `PyOS_AfterFork_Child()` (the
`os.register_at_fork` child hooks of loaded modules) and then the closure, which calls `prctl`
through ctypes and `os.getppid()`. The Python documentation says `preexec_fn` is not safe with
threads and the child "could deadlock before exec is called"; the probe and batch code run
`asyncio.to_thread` work (`probe/prober.py:188,325,457`, `batch/service.py:155,187,258`) while
the runner forks. Under coverage the tracer runs Python in the child for the closure as well,
so a lock that another thread held at the fork (coverage's own, or one taken by a tracer
callback) never gets released; that fits the child in `futex_wait`. Outside coverage the code
in the child is tiny and every at-fork hook of the standard library re-creates its locks, so the
risk is low (no hang in any of today's 5 non-coverage full runs, about 18,000 fake spawns each)
but not zero. Shell-level `start_new_session` alone is safe (done in C). Removing the risk
would mean no `preexec_fn` (another way to get the parent-death signal); that is a product
change, not a test-speed one. The per-test timeout above covers the tests either way.

Verdict: ADJUSTED — `pytest-timeout` 2.4.0 with `timeout_method = "thread"` works with xdist 3.8.0 and worksteal on Linux. A hung test ends its worker, xdist reports `worker 'gwN' crashed while running '<test>'`, starts a new worker, and puts the crashed worker's pending tests back in the queue. Three problems the report does not mention:

(a) Under xdist the stack dump of pytest-timeout is not visible: it writes to the worker's terminal writer, which xdist does not show. Only the "crashed while running" line remains. pytest's own `faulthandler_timeout` writes to stderr and is visible under xdist (checked). So add `faulthandler_timeout` a little below `timeout` (for example 590 with `timeout = 600`). The report calls `faulthandler_timeout` "not enough alone", which is right, but it is needed for the stacks.
(b) After any worker crash, syrupy 6.1.1 warns at session end ("N selected test(s) missing from collected items"). `filterwarnings = ["error"]` turns that warning into an exception in `pytest_sessionfinish`. pytest then prints a traceback instead of the FAILURES section and the summary. The run continued (522 passed), but the report of which test hung was lost. Add `"ignore:syrupy:UserWarning"` (or a narrower message match) to `filterwarnings` together with the timeout. With it, the output is correct: `2 failed, 522 passed`, exit 1.
(c) A child that the test starts directly (not through `reframe.tools.run`, so without `PR_SET_PDEATHSIG`) outlives the killed worker. A `sleep 1000` was left running and I killed it by hand. Only children of `reframe.tools.run` die with the worker.
Windows (not run): `thread` is the only method pytest-timeout has there, and it ends the worker with `os._exit` the same way. The worksteal and crash handling are platform-independent Python, and `faulthandler_timeout` works on Windows. Value: 600 s is safe. After the split, the slowest test in both lever runs was 26.2 s (`test_sigint_in_one_client_cancels_only_its_own_jobs`). The worst value in the report's loaded runs was 152 s, for the unsplit sweep that is now gone. Even with the VM at 2× and a heavy load, no test comes near 600 s, and 600 s stays within CI's `timeout-minutes: 30`. 300 s would also be safe; 600 s is a reasonable cautious value.
Checked: throwaway `packages/reframe/tests/test_zz_hang_tmp.py` (one test waits on `threading.Event().wait()`, one on `subprocess.run(["sleep","1000"])`, 40 trivial tests) plus `packages/reframe/tests/naming`, `uv run --with pytest-timeout pytest -o timeout=5 -o timeout_method=thread -n 3` with worksteal in `addopts` → workers gw0 and gw3 replaced, the run continued, then a syrupy `UserWarning` traceback in `pytest_sessionfinish` and no summary. Again with `-W "ignore:syrupy:UserWarning"` → `2 failed, 522 passed in 12.72s`, exit 1, no stack dump. Again with `-o faulthandler_timeout=4` → the main thread's stack (`test_zz_hang_tmp.py, line 8 in test_hang_on_a_lock`) is printed. Test file deleted afterwards.

Orchestrator: Tier B, package Q-7.13. Only together with `faulthandler_timeout = 590` (the stack dump is not shown under xdist otherwise) and an `ignore:...:UserWarning:syrupy` filter (syrupy warns after a worker crash, and `filterwarnings = error` loses the summary).

### SPD-06 — the `preexec_fn` also costs a fork per spawn

- **Where:** `packages/reframe/src/reframe/platform/childproc.py:288-294`.
- **Now:** every runner spawn on Linux forks the whole worker (measured 4.9 ms vs 0.4 ms with
  vfork, from a 300 MB process).
- **Change:** none proposed for speed: the `preexec_fn` gives the product's parent-death
  guarantee (`PR_SET_PDEATHSIG`).
- **Saved:** at most about 18,000 spawns × 4.5 ms ≈ 80 s of test time ≈ 13 s wall; Windows: not
  affected (no fork there).
- **Proposed tier:** C (product behaviour; see SPD-05 for the safety side).
- **Confidence:** medium (the per-spawn cost is measured; the worker size is assumed).

Verdict: CONFIRMED — `childproc.spawn_options()` adds `preexec_fn=linux_preexec()` on Linux (`childproc.py:291-294`), so every runner spawn takes CPython's fork path. The finding proposes no change (Tier C), so there is no guarantee to break. Not re-measured; the figure of 4.9 ms per spawn is the report's own.
Checked: read `packages/reframe/src/reframe/platform/childproc.py:286-294` → as described.

Orchestrator: Tier C, not planned: a product change.

### SPD-07 — fixed waits in four runner tests

- **Where:** `packages/reframe/tests/tools/test_runner.py:551-571`, `:628-652`.
- **Now:** `test_kill_process_tree_can_keep_the_root` waits the full 5 s of
  `psutil.wait_procs(killed, timeout=5)` every time: the killed grandchild is a zombie of the
  still-running root, and psutil counts a zombie as running. 
  `test_the_pid_lets_the_caller_suspend_and_resume_the_tree` lets a child print 400 lines with
  10 ms between them (4 s).
- **Change:** wait with `wait_until_sync(lambda: not any(_alive(pid) for pid in grandchildren), 5)`
  (the same `_alive` the assertion uses, which treats a zombie as dead); print 100 lines.
- **Saved:** about 5 + 3 s of test time, under 2 s wall. Windows: similar.
- **Guarantee kept by:** the same assertions (grandchildren dead, root alive and not stopped;
  a suspended process prints nothing for 0.3 s and finishes after resume). 100 lines at 10 ms
  still last 1 s, well past the 0.6 s the test holds the suspension.
- **Risk:** low.
- **Proposed tier:** A, but low value; do it only if the file is touched anyway.
- **Confidence:** high for the first (deterministic 5.06 s), medium for the second.

Verdict: CONFIRMED — the same assertions remain. `wait_until_sync` raises `TimeoutError` after 5 s where the old code went on to the assertion; either way the test fails if a grandchild survives. The second test needs `lines[-1] == "99"`. Saving: `test_kill_process_tree_can_keep_the_root` 5.08 s → below 0.81 s, and `test_the_pid_lets_the_caller_suspend_and_resume_the_tree` 4.65 s → 1.62 s. Under load the 100-line child still outlived the 0.6 s suspension in 12 of 12 runs. In the full runs, `tools/test_runner.py` test time fell from 21.9 s to 14.1/14.2 s.
Checked: `uv run pytest -n 0 packages/reframe/tests/tools/{test_runner,test_fetch,test_fetch_cli}.py --durations=6` before / after (load 3.3 / 2.3) → 150 passed in 39.41 s / 17.84 s (this includes the fetch poll lever). `bash vspeed/spd07_load.sh` (18 CPU-hog processes, 1-min load climbing to 11.8 and more) → 12 × `2 passed`.

Orchestrator: Tier A, package Q-7.7.

### SPD-08 — `test_shared_queue_real.py`: generated sources and CLI polls

- **Where:** `packages/reframe/tests/remote/test_shared_queue_real.py:132-163` (`Home.source`),
  `:197-200` (`Home.state`).
- **Now:** every test generates its sources with FFmpeg: six 60 s 720p sources (3.3 s each
  under load) and several shorter ones, about 22 s of multi-threaded CPU per run of the file.
  `home.state()` in `wait_until_sync` polls start a whole `reframe` CLI each time (0.77 s of
  imports).
- **Change:** generate each (duration, name-free) source once per session into the fixture
  cache (`reframe_testing.media`) and copy it into the test's home; poll the owner's HTTP API
  instead of the CLI where the CLI's output is not what the test checks.
- **Saved:** about 20–30 s of test time ≈ 4–5 s wall on 6 workers. Windows: somewhat more
  (CLI start is slower).
- **Guarantee kept by:** the same sources (copied) and the same states.
- **Risk:** the poll change touches what the test exercises; the source cache is safe.
- **Proposed tier:** B (low value).
- **Confidence:** medium.

Verdict: CONFIRMED — the code is as described. Six `Home.source(..., 60)` calls make 60 s 720p x264 sources (Attached, Busy ×2, First, Long, Detached), plus 2–8 s ones. `Home.state` reads `self.jobs()` through the CLI, and the file has 6 `home.state(` polls. The saving (about 4–5 s wall) and Tier B were not re-measured. The low value fits: in the lever runs the file's tests run in parallel with the language parts and are not the tail on their own.
Checked: `grep -o '\.source([^)]*)' packages/reframe/tests/remote/test_shared_queue_real.py | sort | uniq -c` → as above; read `:132-163`, `:197-200`.

Orchestrator: Tier B, package Q-7.13.

## Why the Windows VM takes about 12 minutes (from the code; not measured)

The VM runs the same 6 workers as this machine, so the extra 6 minutes are costs that scale
worse on Windows:

1. **Process starts.** A full run makes 17,862 fake-tool calls; on Windows each is `cmd.exe`
   plus `python.exe` (two process creations, Defender scans) and compiles `fake_ffmpeg.py` from
   source. Every CLI test starts a `python -m reframe.cli` (0.77 s of imports on Linux), and
   every encode or probe starts FFmpeg. Process creation and interpreter start are several times
   slower on Windows; this is the likeliest main cause. SPD-04 reduces part of it.
2. **Temporary files.** One run writes 48,522 files (1.3 GB) under the pytest base temp, and
   pytest deletes the run from three runs ago. On NTFS with real-time scanning this costs far
   more than on Linux's tmpfs `/tmp`. A Defender exclusion (or a Dev Drive) for the VM's
   `%TEMP%` and the clone is a machine setting, not a code change; worth trying on the VM.
3. **The same scheduling tail** as on Linux: SPD-01 and SPD-02 apply unchanged.
4. Not a cause: SPD-06 (no fork on Windows).

## Looked at and not worth it

- **Collection:** about 2.3 s per worker after start-up, paid in parallel by all workers
  (about 4.6 s of a 322 s run). `models/test_schema.py` spends 1.4 s at import building 223
  schemas; making it lazy would save about 1 s per worker. No.
- **Worker start-up and gaps between tests:** under 5 s and under 1 s per worker. No.
- **`--dist loadfile` / `loadgroup`:** they keep a file on one worker, which is exactly the
  problem (test_equivalence 180 s, test_shared_queue_real 144 s in one worker). Worse than
  `worksteal`.
- **Ordering the longest tests first** (a `pytest_collection_modifyitems` hook with a duration
  list): with `load` the first contiguous chunk would carry every long test to one worker;
  with `worksteal` + SPD-02 the finish spread is already 10 s. Not needed.
- **More splitting:** after SPD-02 the longest tests are about 15–30 s
  (`test_shared_queue_real.py`, `test_encode_real.py`), and the spread is 10 s. No.
- **Sleeps and polls:** the low-CPU waiting in tests adds up to about 150 s of test time
  (25 s wall) in a loaded run, spread over many files. The largest blocks are real external
  behaviour and must stay: `platform/test_sleep_real.py` (5 × about 5 s: KDE PowerDevil applies
  an inhibition after its own delay), `test_timeout_kills_the_whole_tree` (`timeout=3` is the
  behaviour under test and must leave time for the grandchild to start),
  `test_a_grandchild_holding_the_pipe_does_not_block` (2 s = the runner's pipe-drain grace),
  `test_release_workflow.py` (GnuPG key generation, already module-scoped). Polls use 10–20 ms
  intervals (`reframe_testing/waiting.py`). Only SPD-07 is a free win.
- **Hypothesis settings:** `max_examples` are set per test (25–500) with no global profile; the
  property-test files are not among the slow ones. No.
- **Fixture scopes:** setup and teardown together are 111 s of the 1,797 s; the slowest setups
  are a fixture media generation (7 s, once) and module-scoped GnuPG keys. No wider scope is
  worth the isolation it would cost.
- **`-n logical`:** SPD-03.

## All levers together

Change set "all" (diff: `vspeed/all-levers.diff`, applied by `vspeed/apply_all.py`):

- SPD-01: `"--dist", "worksteal"` added to `addopts`.
- SPD-02 + TPM-01 in `test_equivalence.py`. `_differences` loops tags on the outside and functions on the inside: `pairs = [(name, ours, theirs) …]` is built once, then `for value in values: for name, ours, theirs in pairs:`. The 88 s sweep is split `[part::8]` and the search sweep `[part::4]`. The two changes are independent. The split only chooses which tags a part gets, and the swapped loops check every (function, tag) pair of that part exactly once. The tag-major loop also reads `values` only once.
- SPD-04: POSIX launcher `sys.path.append(<dir>)`, then `import fake_ffmpeg`, then `fake_ffmpeg.main(...)`.
- SPD-07: `wait_until_sync(lambda: not any(_alive(pid) for pid in grandchildren), 5)` in place of `psutil.wait_procs(killed, timeout=5)`; 100 lines in place of 400 (`lines[-1] == "99"`).
- Fetch server: `threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)` (`packages/reframe/tests/tools/fetch_server.py:209`).

Every run: `vspeed/fullrun.sh NAME --durations=15` = `uv run pytest -m "not needs_gpu" -q -p no:cacheprovider -p timeline_plugin --durations=15` with the report's timeline plugin, `-n auto` = 6 workers. Before each run `ps -eo etime,args | grep '[p]ytest'` was empty, and each run waited until the 1-min load average was below 2. "Load" = the 1-min load average at the start / the mean / the maximum of the 15-s samples during the run (the load comes from the run itself). Runs in the order v0, v1, v2, v3.

| Run | Change set | Load (start / mean / max) | Wall | Passed / skipped | Worker finish times (s) | Spread |
|-----|------------|---------------------------|------|------------------|-------------------------|--------|
| v0 | none (first run in this worktree: test `.pyc` cold, workers finished collecting at 9.0 s instead of 3.7 s) | 1.84 / 12.2 / 16.5 | **373.3 s** | 8,576 / 14 | 279, 279, 280, 282, 305, 368 | 89 s |
| v1 | all | 1.98 / 12.4 / 18.6 | **294.2 s** | 8,586 / 14 | 267, 269, 273, 278, 286, 291 | 24 s |
| v2 | all | 1.87 / 11.2 / 17.2 | **295.3 s** | 8,586 / 14 | 271, 271, 273, 277, 287, 292 | 21 s |
| v3 | none (warm) | 1.92 / 11.8 / 18.3 | **374.4 s** | 8,576 / 14 | 275, 275, 276, 278, 306, 369 | 94 s |

- **Result: 373.3 / 374.4 s → 294.2 / 295.3 s, −79 s (−21 %).** The baseline repeats the owner's 372.8 s. The four runs are within 1 s of each other per change set.
- Counts: 8,586 = 8,576 + 10 (the split makes 8 ids from one test and 4 from another). No other count changed, and there were no failures.
- Sum of test time: 1,735 / 1,753 s (baseline) → 1,639 / 1,645 s (levers). By group (`vspeed/groups.py`), baseline → levers:
  - `tools/test_fetch*`: 19.0 → 7.1 / 7.4 s (fetch poll);
  - `tools/test_runner.py`: 21.9 → 14.1 / 14.2 s (SPD-07);
  - everything else except `test_equivalence`: 1,510 / 1,520 → 1,412 / 1,417 s (mainly SPD-04);
  - `test_equivalence.py`: 184 / 192 → 206 / 206 s. This group gets *longer*: in the baseline the 88 s and 46 s sweeps ran at the idle tail, while split they run under full SMT load. TPM-01's CPU saving (−22 %, below) is hidden by that load in the full run, but it makes the parts shorter and the tail smaller.
- Most of the wall saving comes from the scheduling: the baseline's last worker ran 90 s alone. The rest comes from about 100 s less test time in total (≈ 17 s wall on 6 workers).
- Slowest 10 tests, v1 (v2 in brackets where it differs):
  1. `remote/test_shared_queue_real.py::test_sigint_in_one_client_cancels_only_its_own_jobs` 26.2 s (22.5)
  2. `languages/test_equivalence.py::test_search_every_name_in_every_locale[0]` 24.4 s (22.5)
  3. `remote/test_shared_queue_real.py::test_two_encodes_at_once_both_finish_and_share_the_slot_limit` 23.0 s (23.6)
  4. `remote/test_shared_queue_real.py::test_kill_9_of_a_client_cancels_its_jobs_and_a_detached_job_runs_on` 20.1 s (21.9)
  5. `test_search_every_name_in_every_locale[1]` 19.5 s (19.6)
  6. `remote/test_shared_queue_real.py::test_a_stop_by_another_front_end_is_reported_and_the_jobs_wait_for_a_start` 19.5 s (21.2)
  7. `test_search_every_name_in_every_locale[2]` 19.4 s (v2: `[3]` 22.4 s)
  8. `remote/test_shared_queue_real.py::test_ctrl_z_pauses_the_job_and_fg_resumes_it` 19.4 s (17.4)
  9. `remote/test_shared_queue_real.py::test_a_job_whose_output_another_clients_waiting_job_writes_is_added_failed` 14.4 s (13.7)
  10. `remote/test_shared_queue_real.py::test_a_waiting_job_that_another_client_removes_ends_the_follow` 14.2 s (14.2)

  The 8 parts of the 88 s sweep took 8.4–10.0 s each. Baseline v3, for comparison: 92.5 s (sweep), 48.3 s (search), 27.4 s, 22.6 s, 19.6 s, …
- The tail with all levers is the search parts (`[3]` ended the run at 290.5 s in v1) together with `test_shared_queue_real.py`. Splitting the search into 8 instead of 4 parts could take a few more seconds off. Not measured.

**TPM-01 alone** (tag-major vs function-major loops, the 88 s sweep's 5 functions, same process start, 4 processes at once on an idle machine): whole sweep 55.6 → 43.2 s CPU (−22 %); one eighth (`[3::8]`) 7.4 → 5.7 s (−23 %). Both orders compared 1,078,440 (function, tag) pairs and found 0 differences. The saving is a little below the "about 30 %" given to me.

**Fetch poll alone:** not isolated. `tools/test_fetch*` test time fell 19.0 → 7.2 s in the full runs (−11.8 s), close to the area verifier's −12.6 s.

## Verifier notes

- Set-up: worktree at `38cf3eb848e6267522daac27eb219e75993b2e36` (`git rev-parse HEAD` checked), `uv sync`, `testdata/media` symlinked to the shared media. The 4 full runs allowed were used for v0–v3. At the end the worktree was restored with `git checkout -- .`, the throwaway test and the symlink were removed, and `git status` was clean. Nothing was committed.
- **Item 4 (6 workers):** `uv run python -c "import psutil, os; print(psutil.cpu_count(logical=False), os.cpu_count())"` → `6 12`. `uv run pytest packages/reframe/tests/naming` → `created: 6/6 workers`, `6 workers [482 items]`, and `-v` shows `[gw0]`…`[gw5]`. `lscpu`: Ryzen 5 5600, 6 cores, 2 threads per core. xdist's `auto` uses `psutil.cpu_count(logical=False)` (`xdist/plugin.py:31-32`). Confirmed. On CI, `PYTEST_XDIST_AUTO_NUM_WORKERS` overrides this if ever needed.
- **Baseline cold vs warm:** v0 was the first run after `git reset` (workers needed 9.0 s to collect, v3 3.7 s). This did not change the wall time (373.3 vs 374.4 s), because the baseline is bound by the tail.
- **What I could not check:** anything on Windows (no VM access in this task). SPD-04's Windows gain and its `.cmd` form, worksteal under Windows xdist, and pytest-timeout on Windows rest on reading the code, not on runs. The report's simulator was not re-run. The measured runs replace it for the combined levers.
- **Tier A recommendation** (measured together, −21 % wall, guarantee kept): SPD-01 (with the 0084 amendment about `xdist_group`), SPD-02, TPM-01 (in the same commit as SPD-02, since both change `test_equivalence.py`), SPD-04 POSIX (Windows `.cmd` as a one-line `-c` once checked on the VM), the fetch poll (`poll_interval=0.05`), SPD-07. SPD-05 is Tier B as proposed, but only together with `faulthandler_timeout` and the syrupy warning filter (SPD-05 verdict). SPD-03 and SPD-06 stay C, and SPD-08 stays B.
