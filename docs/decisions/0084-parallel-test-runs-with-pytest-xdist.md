# 0084 — Parallel test runs with pytest-xdist

- Status: accepted
- Date: 2026-11-16
- Steps: Q-2, Q-6
- Amended the same day: the owner asked that every test run uses xdist, so `-n auto` moved
  into `addopts` (items 1, 4, 5).

## Context

`uv run pytest -m "not needs_gpu"` runs about 8,600 tests in one process. On the owner's machine
(12 cores) it takes 33–39 minutes, and longer when several suites run at once. The Q-6
simplification runs it after every merge, so most of each wave was spent waiting for it.

A trial with `pytest-xdist` 3.8.0 (`-n auto`, 12 workers) at `2e536f4`:

- First run: 5 min 46 s, but one worker died. `test_applog.py` logs a message with a lone
  surrogate (an undecodable file name) on purpose; pytest puts captured log output into the
  test report, and xdist cannot send a string with a surrogate as UTF-8 (`execnet`
  `UnicodeEncodeError`). The worker's remaining tests did not run.
- Second run, with the report fix below: 1 failed, 8,594 passed, 12 skipped in 6 min 17 s.
  The failure was `tests/jobs/test_cli_name.py::test_template_and_preset`: xdist's temporary
  folder is 10 characters longer (`popen-gw4/`), the long `File` line wrapped at a space at the
  200-column terminal of `invoke`, and the test's row parser joins wrapped lines without that
  space. A test problem, not a product one.
- Fixture media generation is already safe across processes: it writes into a temporary folder
  and renames (two workers may make the same file once).

## Decision

1. `pytest-xdist` is a dev dependency, and `-n auto` is in `addopts`: every pytest run is
   parallel, local and CI, a full run as well as one file. `-n 0` runs in one process (for
   `--pdb` and other debugging). One test pays about a second of worker start-up.
2. The `reframe_testing` pytest plugin escapes lone surrogates in a report's captured sections
   (`backslashreplace`) before the report is sent. Only the text shown for captured output
   changes; no test result does.
3. `test_template_and_preset` runs its command with a 1,000-column terminal, so its file path
   never wraps, and `test_the_frozen_cli_names_languages_from_its_bundled_tables` gives the
   frozen CLI `COLUMNS=200` (an xdist worker has no `COLUMNS`, and at 80 columns the table
   wraps "jpn Japanese").
4. The `benchmark` tests (time budgets) skip in an xdist worker; the CI benchmark job runs them
   with `-n 0`, and locally `uv run pytest -m benchmark -n 0` does.
5. The CI workflow gets `-n auto` through `addopts` on Ubuntu and Windows. xdist was tried only
   on Linux: if the Windows runner fails under xdist, the Windows job passes `-n 0` until the
   cause is fixed (check on the Windows test VM of decision 0070).

## Consequences

- A full local run takes about 6 minutes instead of about 35.
- Tests that depend on the length of the temporary path or on running alone in the process can
  fail under xdist and pass alone. Fix the test (as in item 3), or mark it to run in one
  worker with `@pytest.mark.xdist_group` and `--dist loadgroup`.
- Timing budgets do not run in a default local run any more (item 4); run them alone with
  `-n 0` after a change that can make the probe or the preview slower.
- A later test-speed audit (fewer slow waits, fixture scopes, redundant tests) can start from
  this baseline.

## Windows (2026-11-17)

Checked on the Windows test VM of 0070 (22H2, 6 processors), `-m "not needs_gpu and not
benchmark"`, `REFRAME_REQUIRE_FFMPEG=1`:

- xdist itself works on Windows: no worker crash, about 12 minutes with `-n auto` (6 workers);
  3 workers are not faster.
- The first runs had failures that moved from run to run (12 with 6 workers, 6 with 3). The
  cause was in the test helpers, not in xdist: the `fake_tools` fixture's teardown killed
  processes by logged pid with a 2 s reuse margin, and Windows hands a pid out again within
  milliseconds, so a teardown killed other workers' processes. Fixed (the margin is 0.01 s on
  Windows; `docs/simplify/decisions-taken.md` D-45), with two smaller Windows races.
- After the fix, four runs with `-n auto`: 2 failures (the two races, fixed next), 0, then at
  the final commit 0 and 1 (8,274 passed, 266 skipped): the one is
  `test_choosing_a_job_never_reads_a_slow_share_on_the_event_loop`, whose longest event-loop
  pause was 0.35 s against its 0.3 s limit under load; its real guard (no `stat` on the event
  loop) passed. It is listed with the known load-sensitive tests in
  `docs/simplify/plan.md`.
- So item 5 stays: the Windows CI job runs with `-n auto`; `-n 0` remains the fallback.

## Plan changes

- `docs/plan/09-quality-and-release.md` Q-2: a note on parallel runs.
- `CLAUDE.md` Commands: parallel by default, `-n 0`, the benchmark command.
- `.github/workflows/ci.yml`: the benchmark job passes `-n 0`.
- `docs/simplify/plan.md`: how the Q-6 packages run the tests.
