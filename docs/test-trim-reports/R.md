# Test trim report: area R (capabilities, preview, analysis)

Branch `test-trim-R` (the name `test-trim/R` cannot exist next to the branch `test-trim`: git
refuses `refs/heads/test-trim/R` while `refs/heads/test-trim` is a branch). Base: `test-trim`
(d0109b7).

Files: the 24 files of area R under `packages/reframe/tests/` (`capabilities/`, `preview/`,
`analysis/`).

## Numbers

| | Before | After |
|---|---|---|
| Tests (collected) | 456 | 433 (-23, -5 %) |
| Wall time, no coverage | 107 s (load about 4) | 115 s (load average 19: other agents ran at the same time) |
| Wall time, with coverage | 150 s | 178 s (same load; not comparable) |

The wall times are not comparable: the machine was shared with other agents during the second
runs. About 32 s of each run is the Q-3 benchmark (`test_4k_hdr_frame_budget`), which is kept.
The only slow test removed is the `subtitle-pgs` case of the cancel test (one more cancel on
the 2-hour file).

The area is already lean: most tests pin real FFmpeg behaviour (recorded `c4_*` / `hw_*`
captures, `library_strings.json`, the preview and scan tool behaviour in
`testdata/README.md`), plan "Done when" criteria (C-4 start < 1 s, timeouts and reason mapping
with the fake ffmpeg, `encoder.unavailable` with the closest-encoder fix; C-10 frame budget and
cancel within 1 s), M2-review regressions, cancel / timeout / kill tests and Windows mock
tests (registry fingerprint). So only 5 % were removed.

## Coverage gate

`uv run pytest <area files> --cov=reframe --cov-branch` before and after, compared with
`covcmp.py`:

```
before 55.060% 2455/6918 branches 13410/21896 lines
after 55.064% 2456/6918 branches 13410/21896 lines
TOTAL LOST: 0
```

(The one extra branch after is the benchmark's "busy machine" skip, taken because of the load.)

## Deleted tests

### Subsumed by other tests of the same code path

- `capabilities/test_service.py::test_wait_starts_a_detection`: `wait()` without `start()` is
  what `test_closest_available`, `test_every_render_node_is_tried`,
  `test_the_setting_forces_one_node` and `test_a_failing_cache_write_is_not_fatal` do, with
  stronger assertions.
- `capabilities/test_service.py::test_libplacebo_untested_with_hardware_tests_off`: the
  detection side is `test_detect.py::test_hardware_tests_off`
  (also asserts no libplacebo run); the setting reaching the detection is
  `test_service.py::test_hardware_tests_off`.
- `capabilities/test_devices.py::test_has_filter_keeps_its_meaning`: the same assertions
  (`has_filter` True, `usable_filter` False for a failed run test) are in
  `test_detect.py::test_libplacebo_without_vulkan` and the `test_usable_filter` table.
- `capabilities/test_cache.py::test_another_key_is_a_miss`: a miss for a missing entry is the
  first assertion of `test_round_trip`; a miss for an entry of another key is the
  `KEY_MISMATCH` case of `test_bad_entries_are_misses`; a changed setting that misses the cache
  end to end is `test_service.py::test_the_setting_and_the_nodes_are_in_the_cache_key`.
- `capabilities/test_issues.py::test_audio_encoder_without_anything_available`: the "no fix
  when nothing is available" branch of `encoder_issues` has no audio-specific code; it is
  `test_unavailable_without_anything_available`, and `libfdk_aac` without `aac` giving no
  closest encoder is in `test_closest_available_none`.
- `analysis/test_analysis_ffmpeg.py::test_bitrate_scan_of_a_subtitle_stream_fails`: the check
  runs before any tool; `test_analysis_tasks.py::test_bitrate_scan_of_a_wrong_stream_fails[3-…]`
  tests the same message with the fake context.
- `preview/test_cache.py::test_trim_with_the_real_clock`: `trim()` with the real clock runs in
  `test_frames.py::test_the_cache_keeps_its_size_limit` (an hour-old frame removed over the
  limit).

### Private helpers / implementation details

- `capabilities/test_reasons.py::test_normalise_line`: private helper; every `detail` of
  `test_real_failures` and `test_driver_errors_are_mapped` is a normalised line.
- `capabilities/test_hwtest.py::test_placeholders`: private `resolve_placeholders`; the
  unknown-placeholder error is `test_definition_errors`, the substitution is
  `test_the_hardware_captures_ran_the_current_command`.
- `capabilities/test_hwtest.py::test_uses_vaapi_device`: which encoders get a render node is
  asserted per encoder in `test_detect.py` (`test_hardware_tests_off_keeps_the_forced_vaapi_device`,
  `test_vaapi_uses_the_first_node_that_works`) and `test_service.py::test_every_render_node_is_tried`.

### Pydantic behaviour

- `capabilities/test_devices.py::test_vaapi_device_setting_defaults_to_automatic`: a model
  default and `model_validate` of one field. A wrong default fails
  `test_service.py::test_every_render_node_is_tried`.

### Parametrized cases that add no branch (merged)

- `preview/test_graph.py::test_the_output_graph_is_the_builders`: 12 jobs × libplacebo
  {False, True} → 12 jobs with libplacebo failed plus the 4 `hdr10` jobs with libplacebo
  usable (-8). libplacebo is only an implementation of the Tone mapping filter
  (`filters.toml`, the only `needs_vulkan` filter), so on the SDR jobs both runs build the same
  graph. Note for `docs/status.md` (C-10 notes say "an agreement test against `build_plan` for
  24 jobs"): it is now 16 cases of 12 jobs.
- `preview/test_common.py::test_a_count_out_of_range`: removed `-1` (the same lower-bound
  branch as `0`).
- `preview/test_cache.py::test_timestamp_ms`: removed `(0.0004, 0)` (round down, the same as
  `(2.0004, 2000)`).
- `preview/test_frames.py::test_bad_requests_fail_the_task` → `test_a_bad_request_fails_the_task`:
  removed the `count=0` case. Both cases are a `TaskFailed` of `sample_times` (all its messages
  are tested in `test_common.py`); one case keeps the task-level path.
- `analysis/test_analysis_cancel.py::test_cancel_stops_the_process_within_a_second[subtitle-pgs]`:
  `test_cancel_removes_the_temporary_pgs_copy` makes the same call through the same helper
  (`_cancel_stops_the_process`, same 1 s limit) and also checks the clean-up.

## Mutation checks

Each mutation was applied to the production code, the remaining tests of the named folder
were run (`-x`), and the file was restored with `git checkout` (`git status` showed no
production change before the commit).

| # | Mutation | Guards the deleted test | Remaining test that failed |
|---|----------|-------------------------|----------------------------|
| 1 | `CapabilityService.wait()` returns the snapshot instead of starting a detection | `test_wait_starts_a_detection` | `test_service.py::test_closest_available` |
| 2 | `untested_filters = []` in the detection | `test_libplacebo_untested_with_hardware_tests_off` | `test_detect.py::test_everything_works` (first with `-x`) |
| 3 | the service passes `hardware_tests=True` whatever the setting | same | `test_service.py::test_hardware_tests_off` |
| 4 | `EncoderSettings.vaapi_device` defaults to `/dev/dri/renderD128` | `test_vaapi_device_setting_defaults_to_automatic` | `test_service.py::test_every_render_node_is_tried` |
| 5 | `has_filter` is false for a filter whose run test failed | `test_has_filter_keeps_its_meaning` | `test_detect.py::test_libplacebo_without_vulkan` |
| 6 | `CapabilityCache.get` does not compare the stored key | `test_another_key_is_a_miss` | `test_cache.py::test_bad_entries_are_misses[KEY_MISMATCH]` |
| 7 | `normalise_line` keeps the `@ 0x…` address | `test_normalise_line` | `test_detect.py::test_driver_errors_are_mapped` |
| 8 | `uses_vaapi_device` false for `av1_vaapi` | `test_uses_vaapi_device` | `test_detect.py::test_hardware_tests_off_keeps_the_forced_vaapi_device` |
| 9 | an unknown placeholder becomes `''` instead of raising | `test_placeholders` | `test_hwtest.py::test_definition_errors` |
| 10 | `PreviewCache.trim` uses clock 0 when `now` is not given | `test_trim_with_the_real_clock` | `test_frames.py::test_the_cache_keeps_its_size_limit` |
| 11 | the bitrate scan accepts a subtitle stream | `test_bitrate_scan_of_a_subtitle_stream_fails` | `test_analysis_tasks.py::test_bitrate_scan_of_a_wrong_stream_fails[3-…]` |
| 12 | frame count range `0 <= count` | `count=0` / `-1` cases | `test_common.py::test_a_count_out_of_range[0]` |
| 13 | `timestamp_ms` rounds up (ceil) | `(0.0004, 0)` | `test_cache.py::test_timestamp_ms[2.0004-2000]` |
| 14 | the preview's output graph never uses libplacebo | the 8 SDR libplacebo agreement cases | `test_graph.py::test_the_output_graph_is_the_builders[hdr10.mkv-fields13-True]` |
| 15 | `encoder_issues` gives a fix when no encoder is available | `test_audio_encoder_without_anything_available` | `test_issues.py::test_unavailable_without_anything_available` |
| 16 | a negative timestamp is accepted | the merged frames-task test (the task-level path still fails) | `test_frames.py::test_a_bad_request_fails_the_task` |

## Uncertain, kept

- `capabilities/test_issues.py::test_audio_encoder_unavailable_with_a_fix` and
  `test_job_with_a_libfdk_aac_track` overlap (decision 0020, both apply to `libfdk_aac`); the
  first is the only one that checks the audio message with the audio encoder's label. (Q-7.11
  merged `test_job_with_a_libfdk_aac_track` into it; the message assertion stays.)
- `capabilities/test_service.py::test_definitions_property` and `test_close_without_start`:
  small, but they are the only checks of the snapshot before `start()` and of a second
  `close()`.
- `capabilities/test_hwtest.py::test_there_are_c4_captures`: a count of the captures; it keeps
  the capture-parametrized test from passing with no cases.
- `capabilities/test_reasons.py::test_informative_line_order` (private helper, but it is the
  plan's "most informative line" rule of C-4).
- `preview/test_common.py::test_tool_identity` and `preview/test_graph.py::test_the_identity_covers_the_png_options`:
  exact cache-key contents; no other test fails when a library version or the PNG options
  leave the key.
- `preview/test_frames.py::test_a_source_in_a_folder_with_special_characters`: the argv is a
  list, so the characters should not matter; kept as a cheap end-to-end guard.
- The `nan` / `inf` / negative cases of the timestamp, clip-range and loudness argument
  checks: `nan` and `inf` both go through `math.isfinite`, but each is a separate "just
  outside" value of the input.

## Unused fixtures

None. No fixture or helper in `conftest.py`, `testing/` or `preview/helpers.py` became unused.
