# Test trim, area T (tools runner, discovery, fetch, versions; platform childproc, sleep, power, notify)

Branch `test-trim-T` (`test-trim/T` cannot exist: the branch `test-trim` already exists, so git
cannot create a ref below it). No production code, conftest.py or `testing/` file was changed.

## Numbers

| | Tests | Wall time (with `--cov --cov-branch`) |
|---|---|---|
| Before | 441 | 87.4 s, 86.5 s (two runs) |
| After | 423 (-18, -4.1 %) | 77.0 s to 89.3 s (five runs; other agents shared the machine) |

Without coverage, after: 423 passed in 72.8 s.

The area is lean, so the reduction is small. Most files are explicit KEEP categories (tree kill,
cancel, timeout, output limit, Job Objects, SetThreadExecutionState, power safety, fetch
security checks, golden D-Bus bytes, recorded version outputs).

## Coverage gate

`covcmp.py before.json after.json` (one run each):

```
LOST packages/reframe/src/reframe/platform/power.py: lines [495] branches []
TOTAL LOST: 1
```

`PowerService.countdown` was covered only by `test_defaults`, so that test was restored (Q-7.6 later merged it into `test_the_deadline_uses_the_wall_clock`).

After that the gate showed losses only in `capabilities/` (detect.py, parse.py, service.py:357).
The background capability detection that `Reframe.create` starts in the facade and CLI fetch
tests is cancelled at a different point in each run, so these lines change from run to run.
None of the tests that run that detection were changed. Evidence:

Unmodified tree against an unmodified-tree rerun (`before.json` against `b3.json`) also loses lines:

```
LOST packages/reframe/src/reframe/capabilities/parse.py: lines [143, 144, 155, 156, 157] branches [(142, 143), (154, 155), (155, 156)]
LOST packages/reframe/src/reframe/capabilities/service.py: lines [357] branches []
LOST packages/reframe/src/reframe/cli.py: lines [] branches [(2021, 2030)]
LOST packages/reframe/src/reframe/tools/runner.py: lines [] branches [(376, 374)]
TOTAL LOST: 11
```

Trimmed tree, union of three runs, against `before.json`. Only lines that the unmodified rerun
also loses are left:

```
LOST packages/reframe/src/reframe/capabilities/parse.py: lines [143, 144, 155, 156, 157] branches [(142, 143), (154, 155), (155, 156)]
LOST packages/reframe/src/reframe/capabilities/service.py: lines [357] branches []
TOTAL LOST: 9
```

Trimmed tree, union of three runs, against the unmodified-tree rerun (`b3.json`):

```
TOTAL LOST: 0
```

A per-test context run (`COVERAGE_CORE=ctrace --cov-context=test`) showed that service.py:357
came from `test_fetch_cli.py::test_fetch_installs_the_build_that_discovery_then_uses`. That
test was not changed. In one unmodified-tree run the line was not covered at all.

Flaky, not changed: `tools/test_fetch.py::test_fetch_installs_the_build_and_skips_an_intact_install`.
It fails often under `--cov` on a loaded machine, before and after the trim, with
`'Reading the manifest' in fetch.messages`: progress messages of one task coalesce in the event
queue, so a short step can be lost. It passes without coverage. Report it to the owner of C-15.

## Deleted tests (18)

### Duplicate of another test (same code path, same or weaker assertions)

- `tools/test_runner.py::test_missing_binary_on_path_is_a_result`: the same `except OSError`
  branch as `test_missing_binary_is_a_result_not_an_exception`, with weaker assertions.
- `tools/test_runner.py::test_process_that_finishes_in_time_is_not_timed_out`: every ok-path
  run with a timeout covers it (cancel-after-exit, the streaming tests, on_start).
- `tools/test_discovery.py::test_discover_tools_sync`: `test_path_is_used_without_a_bundled_build`
  uses `discover_tools_sync`, and `test_bundled_wins_over_path` covers the bundled result.
- `platform/test_sleep_real.py::test_no_bus_at_all_gives_the_one_warning`: the same address and
  backends as `test_sleep_failures.py::test_unusable_bus_address_is_unavailable_never_an_exception[no-such-socket]`,
  which also checks for leaked sockets.
- `platform/test_sleep_failures.py::test_default_inhibitor_with_malformed_environment`: 8 cases
  cut to 4 (`bad-escape`, `escape-not-utf8`, `nul-in-path`, `no-transport`). The environment
  is read the same way for every address. The explicit-address test keeps all 8 addresses. The
  regression test stays (see the mutation checks).

### Parametrized cases that add no branch

- `tools/test_versions.py::test_lib_major_to_series[59-5]`: the same fallback as 58 and 64.
- `tools/test_versions.py::test_lib_major_to_series[60-6]`: pinned by
  `test_master_build_series_comes_from_the_library_majors`.
- `tools/test_versions.py::test_lib_major_to_series[63-9]`: pinned by
  `test_real_version_outputs[ffmpeg-btbn-master-N-127032.txt]`.
- `tools/test_versions.py::test_not_ffmpeg_output[hello world\n]`: a generic non-match. The
  near-match (`ffprobe: command not found`), the other tool's output, the empty case and the
  blank-line case stay.

### Constants, defaults, or no real assertion

- `tools/test_versions.py::test_minimum_is_7_0`: a constant. The 7.0 boundary is tested through
  behaviour (`7.0.2-static` meets it; 6.1.2 does not).
- `tools/test_runner.py::test_run_result_defaults`: dataclass defaults. `ok` and `started` are
  checked in every run test.
- `tools/test_runner.py::test_version_of_the_fake_is_ok`: tests the fake tool, not Reframe.
- `platform/test_sleep.py::test_lock_parameters`: constants (`WHAT`, `WHO`, `MODE`,
  `PORTAL_INHIBIT_SUSPEND`). The backend call-argument tests and the golden D-Bus bytes pin each
  value.
- `platform/test_childproc.py::test_real_prctl_is_loaded`: only `callable(preexec)`. The real
  PDEATHSIG test (`test_children_die_when_reframe_is_killed`) proves it.
- `platform/test_childproc.py::test_posix_after_spawn_is_a_no_op`: no assertion. Every real run
  calls `after_spawn` on POSIX.

## Restored after a check

- `platform/test_power.py::test_the_deadline_uses_the_wall_clock`: the coverage gate (`PowerService.countdown` getter).
- `tools/test_fetch.py::test_a_bad_manifest_is_refused[ftp://…]`: two mutations were caught by
  no other test (see below).
- `platform/test_sleep_backends.py::test_windows_backend_accepts_a_mock_kernel32`: it is the
  only test of a second `free()` that runs on Windows (`test_windows_backend_without_kernel32_is_unavailable`
  is skipped there). Windows mock tests are a KEEP category.

## Mutation checks

Each mutation was reverted with `git checkout -- <file>`. `git status` showed no production
change after each check.

| Mutation | Guards the deleted test | Remaining test that failed |
|---|---|---|
| `MIN_FFMPEG = (7, 1)` | `test_minimum_is_7_0` | `test_version_tokens[7.0.2-static …]` |
| `_VERIFIED_LIB_MAJORS[60] = 7` | `lib_major_to_series[60-6]` | `test_master_build_series_comes_from_the_library_majors` |
| `_VERIFIED_LIB_MAJORS[63] = 8` | `lib_major_to_series[63-9]` | `test_real_version_outputs[ffmpeg-btbn-master-N-127032.txt]` |
| fallback `major - 53` | `lib_major_to_series[59-5]` | `test_lib_major_to_series[58-4]` |
| `_check_url` also accepts `ftp` on loopback | ftp case | **none**: the ftp case was restored |
| `_check_url` accepts any non-http scheme | ftp case | **none**: the ftp case was restored; after that `test_a_bad_manifest_is_refused[…-https://1]` failed |
| runner deadline `min(timeout, 0.1)` | `test_process_that_finishes_in_time_is_not_timed_out` | `test_crash_is_a_normal_result` (and others) |
| runner `except OSError` becomes `except FileNotFoundError` | `test_missing_binary_on_path_is_a_result` | `test_not_executable_file_is_a_result` |
| `RunResult.started` always True | `test_run_result_defaults` | `test_missing_binary_is_a_result_not_an_exception` |
| `discover_tools_sync` ignores `bundled_roots` | `test_discover_tools_sync` | `test_main_reports_and_checks_the_origin` |
| `_prctl = None` (no PDEATHSIG) | `test_real_prctl_is_loaded` | `test_children_die_when_reframe_is_killed` |
| `after_spawn` calls the Windows job on every platform | `test_posix_after_spawn_is_a_no_op` | none fails, and the deleted test would not fail either: on Linux `windows_job()` raises OSError, which `after_spawn` suppresses (checked directly) |
| `WHAT = "sleep"` / `MODE = "delay"` / `WHO = "reframe"` | `test_lock_parameters` | `test_logind_holds_the_returned_fd_and_closes_it_on_free` |
| `PORTAL_INHIBIT_SUSPEND = 8` | `test_lock_parameters` | `test_session_falls_back_to_the_portal_with_the_suspend_flag` |
| warn-once check removed (`if self._warned` becomes `if False`) | `test_no_bus_at_all_gives_the_one_warning` | `test_sleep.py::test_no_backend_works_one_warning_and_goes_on` |
| events publish without a bus check | (control) | `test_sleep.py::test_no_events_bus_is_fine` |
| session `except Exception` and inhibitor `except Exception` become `except TypeError` (the M2 review regression) | env-malformed cases | `test_default_inhibitor_with_malformed_environment[bad-escape]` |
| Windows `free()` without the `thread is None` guard | `test_windows_backend_accepts_a_mock_kernel32` | Linux: `test_windows_backend_without_kernel32_is_unavailable`. That test is skipped on Windows, so the deleted test was restored |

A gap that already existed (no deleted test covered it): if `RunResult.ok` ignores `cancelled`,
no test in this area fails. The cancel tests check `result.cancelled` but not `not result.ok`.

## Uncertain, kept

- `platform/test_power.py::test_quit_has_nothing_to_wait_for`: it overlaps
  `test_quit_only_publishes_executing`, but it came with the "an executing power action runs
  to its end" change (f1b33bd). It is the only test that checks that `close()` does not wait
  after `quit`.
- `tools/test_runner.py::test_directory_is_a_result`: the same `except OSError` branch as the
  other start errors, but on Windows a directory gives a different error class.
- `tools/test_discovery.py::test_broken_override_crash`: the same `returncode != 0` branch as
  the exit-code test, but it is the only test with a negative return code (it would catch a
  `> 0` mutation).
- `platform/test_power_executors.py::test_systemctl_path_can_be_given`: it overlaps the
  `systemctl_argv` assertions, but it is the only test of the executor's `systemctl=` argument.
- `tools/test_fetch_cli.py::test_status_help` / `test_fetch_help`: help-text checks, kept
  because they check the documented exit codes.
- `tools/test_versions.py::test_version_tokens`: all 7 real-world version strings were kept
  (the Debian, static, gyan, Ubuntu, `n10.0`, dated-git and master formats).

## Unused fixtures or helpers

None. No fixture in conftest.py or `testing/` became unused. Unused imports in the edited files
were removed (`RunResult` in test_runner.py, `versions` in test_versions.py).
