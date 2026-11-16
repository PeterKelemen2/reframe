# 0084 — Parallel test runs with pytest-xdist

- Status: accepted
- Date: 2026-11-16
- Steps: Q-2, Q-6

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

1. `pytest-xdist` is a dev dependency. A local full run is
   `uv run pytest -m "not needs_gpu" -n auto`. Without `-n` the suite still runs in one process,
   as before; `-n` is not in `addopts`, so running one file or one test has no worker start-up.
2. The `reframe_testing` pytest plugin escapes lone surrogates in a report's captured sections
   (`backslashreplace`) before the report is sent. Only the text shown for captured output
   changes; no test result does.
3. `test_template_and_preset` runs its command with a 1,000-column terminal, so its file path
   never wraps.
4. CI keeps one process for now: xdist was tried only on Linux. Turning on `-n auto` in
   `.github/workflows/` waits for a Windows run (the Windows test VM of decision 0070).

## Consequences

- A full local run takes about 6 minutes instead of about 35.
- Tests that depend on the length of the temporary path or on running alone in the process can
  fail under xdist and pass alone. Fix the test (as in item 3), or mark it to run in one
  worker with `@pytest.mark.xdist_group` and `--dist loadgroup`.
- Timing budgets (`tests/probe/test_live.py::test_probe_budgets`) run with all cores busy and
  can miss their budget under xdist, as they already did when several suites ran at once.
  Rerun such a test alone before treating it as a regression.
- A later test-speed audit (fewer slow waits, fixture scopes, redundant tests) can start from
  this baseline.

## Plan changes

- `docs/plan/09-quality-and-release.md` Q-2: a note on local parallel runs.
- `CLAUDE.md` Commands: the `-n auto` command.
- `docs/simplify/plan.md`: how the Q-6 packages run the tests.
