# 0104 — Faster CI test runs: a worker per vCPU, three parts, a smaller 3.13 run

- Status: accepted
- Date: 2026-11-23
- Steps: Q-1.1

## Context

Q-1.1 runs `pytest -m "not needs_gpu"` in one job per platform and Python version. The first
GitHub runs (2026-11-23) took 907 s (Linux, 3.13), 1,035 s (Linux, 3.14) and 969 s (Windows,
3.14) in the pytest step alone; the owner's machine runs the same tests in about 280 s. Every
job's log says `created: 2/2 workers`: `-n auto` counts physical cores, and the standard
runners of a public repository have 4 vCPUs on 2 cores.

The number of tests is not what costs the time. The Q-7 audit
([0091](0091-test-trimming-step.md)) found little left to remove, and most of the time goes to
the 1,008 tests that run real FFmpeg and to the server tests, which are the coverage that
matters most for a transcoder.

## Decision

1. **A worker per vCPU.** CI's test step passes `-n logical` (4 workers), not `-n auto`.
   Most tests wait on FFmpeg or other child processes, so they gain from the extra workers.
   Local runs keep `-n auto`.
2. **Three parts per platform.** The Python 3.14 suite runs on Linux and on Windows as three
   jobs each (`--splits 3 --group N`, pytest-split's `duration_based_chunks`, which keeps a
   module's tests together). The parts come from the per-test times in `.test_durations`,
   committed and refreshed with
   `uv run pytest -m "not needs_gpu and not benchmark" --store-durations --clean-durations`.
3. **Python 3.13 without the real-FFmpeg tests.** The Linux 3.13 job runs
   `-m "not needs_ffmpeg and not needs_gpu and not benchmark"` (7,491 of 8,439 tests). The full
   suite runs on 3.14 because everything that ships uses `.python-version` (3.14): the sidecar,
   the Docker image and the release workflow. The proposal was the other way round (the full
   suite on 3.13); it would skip the real-FFmpeg tests on the Python that ships.

## Consequences

- Seven Python jobs instead of three; with the other jobs of `ci.yml`, 19 run at the same time,
  under the 20 that GitHub runs at once for a free account.
- A test that is not in `.test_durations` is counted at the average time; the parts drift
  apart until the file is refreshed. A missing or stale entry never drops a test.
- A real-FFmpeg test that fails only on Python 3.13 is not caught in CI. Both
  version-specific failures of the first runs (`Process.wait()` on 3.14.4, CPython gh-119710;
  the JSON parser's stack-based depth limit) were found by tests without `needs_ffmpeg`.
- The lint and type-check steps run in each part: a few seconds each.

## Plan changes

- `09-quality-and-release.md` §Q-1.1: the Python test command in CI.
