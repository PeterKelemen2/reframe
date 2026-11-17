# Area command-capabilities-dimensions: `packages/reframe/tests/command/` (with the 73 plan snapshots), `packages/reframe/tests/capabilities/`, `packages/reframe/tests/dimensions/`

Baseline: 28 files, 744 tests, 7,605 test code lines, 178 s of test time.

Read: every test file of the three folders, `command/conftest.py`, `capabilities/conftest.py`,
the snapshot file (structure, and the cases named below), `docs/simplify/areas/command.md`
(Q-6), and the earlier trim reports that touch this area: `docs/test-trim-reports/C.md`
(command, dimensions) and `docs/test-trim-reports/R.md` (capabilities). I also grepped
`Q.md`, `T.md`, `V2.md` and `N.md`. They only name source lines of this area, not tests.
Per-test times come from `junit.xml` of the baseline run (xdist, inflated).

## Summary

11 findings. Tier A: 6 findings, 9 tests, about 49 code lines, about 5.3 s. Tier A+B: 11
findings, 15 tests, about 102 code lines, about 6.7 s. The area is lean. Trims C and R already
took the parametrized duplicates, and most of what is left is real-FFmpeg oracle tests, M2
review regressions and plan "Done when" tables.

Main question, short answers:
- `dimensions/`: the example tables and the Hypothesis properties do not overlap. The examples
  pin exact sizes, crops and the note texts. The properties pin invariants only, which an
  implementation that never crops or always picks the smallest size would also pass. Neither
  replaces the other (see "Looked at and kept").
- Snapshots vs builder unit tests: no unit test builds the same job as a snapshot case. The
  closest pairs differ in one input that matters (see "Looked at and kept"). The two small
  findings in this area are merges inside the unit tests (TCD-09, TCD-10).
- `needs_ffmpeg` tests: all of them run FFmpeg or ffprobe as an oracle except
  `dimensions/test_ffmpeg.py::test_interlaced_fixture` (TCD-11).

Best three:
1. TCD-01: three hardware-tests-off detections and two default detections in `test_detect.py`
   become two merged tests (-2 tests, about 2.4 s).
2. TCD-05: `test_the_gpu_fingerprint_is_read_once` repeats the start, wait and rescan flow of
   `test_rescan_ignores_the_cache`. Merge them (-1 test, about 2.6 s).
3. TCD-02: three hand-written hardware and filter command tests in `test_hwtest.py` are pinned
   exactly by the capture-replay tests (-3 tests, 19 lines).

## Findings

### TCD-01 The hardware-tests-off and default detections in `test_detect.py` run the same detection two or three times
- Kind: near-copy
- Where: `capabilities/test_detect.py::test_hardware_tests_off` (187), `::test_libplacebo_untested_when_hardware_tests_are_off` (525), `::test_hardware_tests_off_keeps_the_forced_vaapi_device` (200, its second detection `automatic`, lines 210-211), `::test_everything_works` (54), `::test_libplacebo_works` (484)
- Now: `test_hardware_tests_off`, `test_libplacebo_untested_when_hardware_tests_are_off` and the
  `automatic` half of the forced-device test each call
  `detect_capabilities(fake_ffmpeg, DEFS, linux(hardware_tests=False))` with the default fake
  scenario, and each asserts a different part of the snapshot. `test_everything_works` and
  `test_libplacebo_works` both run `detect_capabilities(fake_ffmpeg, DEFS, LINUX)` with the
  default scenario. One real detection with the fake ffmpeg takes about 0.6 to 1.2 s.
- Change: merge `test_libplacebo_untested_when_hardware_tests_are_off` and the
  `automatic.status("hevc_vaapi").device is None` assertion into `test_hardware_tests_off`.
  The forced-device test keeps only its forced detection. Merge the four assertions of
  `test_libplacebo_works` (usable True, no failures or untested filters, exactly one
  libplacebo call equal to `filter_test_argv(...)[1:]`) into `test_everything_works`.
- Saved: 2 tests, about 7 code lines, about 2.4 s (0.58 + 1.16 + about half of the forced test's 1.43).
- Guarantee kept by: the merged `test_hardware_tests_off` and `test_everything_works`, with the same options, the same scenario and every assertion of the removed tests.
- Why nothing is lost: the inputs are identical: `linux(hardware_tests=False)` three times and
  `LINUX` twice, all with the default scenario. The assertions do not conflict. "No
  libplacebo call" is compatible with `encode_calls == []`, and "exactly one libplacebo call"
  is compatible with `test_everything_works`' count of `-c:v` and `-h` calls.
- Docs and history: `R.md` names `test_libplacebo_untested_when_hardware_tests_are_off` as the
  detection side it kept, `test_libplacebo_works` as the guard of its mutation 2, and
  `test_hardware_tests_off_keeps_the_forced_vaapi_device` as the guard of its mutation 8. The
  merge keeps each of those assertions, so the same mutations still fail a test. git:
  `dc1d384` (C-4), `c3edee1` (C-4, decision 0020), `75a0e50` (M2 review, decision 0008
  follow-up: "With hardware tests off, a forced VAAPI node is the status's device"). The
  forced-node part is unchanged.
- Risk: low. It is the same calls with more assertions per test.
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the inputs are identical (`linux(hardware_tests=False)` three times, `LINUX` twice, default scenario). I applied the merge: every assertion of the removed tests is kept, and both R.md mutations that these tests guard still fail a test. Measured: -2 tests, net -7 code lines (13 removed, +6 in the keepers), as stated.
Checked: merged `test_hardware_tests_off` + `test_everything_works`, then `runtests.sh capabilities/test_detect.py capabilities/test_service.py` → 57 passed (load: 5 pytest processes on the machine). R.md mutation 2 (`untested_filters=[]` in the snapshot) → `test_detect.py::test_hardware_tests_off` FAILED. A wrong extra untested filter → `test_hardware_tests_off`, `test_everything_works`, `test_libplacebo_not_in_the_build` FAILED.

Orchestrator: Tier A, package Q-7.4.

### TCD-02 Three hand-written test-encode commands are pinned exactly by the capture-replay tests
- Kind: other (a pure test duplicated by a recorded-data test)
- Where: `capabilities/test_hwtest.py::test_qsv_command` (50), `::test_filter_command` (76), `::test_software_frames_command` (38)
- Now: each test compares `hardware_test_argv` or `filter_test_argv` with a hand-written
  argv. `test_the_hardware_captures_ran_the_current_command` (84, 9 captures) and
  `test_the_filter_captures_ran_the_current_command` (71, 2 captures) assert that the
  recorded command of each committed capture (`fake_data/captures.json`) equals the builder's
  argv for the same encoder, bit depth and device.
- Change: delete the three tests.
- Saved: 3 tests, 19 code lines, about 0 s.
- Guarantee kept by: `test_the_hardware_captures_ran_the_current_command[detect_hevc_qsv_no_device]`, the full QSV argv: `-init_hw_device qsv=hw -filter_hw_device hw ... -vf format=nv12,hwupload=extra_hw_frames=64,format=qsv -c:v hevc_qsv`. `[detect_hevc_nvenc_no_driver]`, the full NVENC software-frames argv with `-pix_fmt yuv420p`. `[detect_hevc_amf_10bit_ok]`, the 10-bit software-frames path, `-pix_fmt p010le` taken from the definition. `test_the_filter_captures_ran_the_current_command[detect_libplacebo_ok]` and `[detect_libplacebo_no_vulkan]`, the full libplacebo argv. `test_there_are_hardware_and_filter_captures` stops the parametrized tests from passing with no cases.
- Why nothing is lost: the qsv test checks two slices of the argv that the capture test
  compares whole. The filter test compares the same list that both filter captures recorded.
  The software-frames test's `hevc_nvenc` assertion is the `detect_hevc_nvenc_no_driver`
  command. Its `av1_amf` 10-bit tail goes through the same code path as the
  `hevc_amf_10bit_ok` capture, with another definition row. That every 10-bit hardware test
  asks for p010le is also in `test_detect.py::test_everything_works` (`sorted(ten) == sorted(ten_bit)`).
- Docs and history: grep docs/ finds none of the three names. git: `dc1d384` (C-4) and
  `c3edee1` (decision 0020). Neither commit names a bug.
- Risk: low. A changed hardware setup fails the capture test and needs a recapture, as the
  capture test's docstring says. The hand-written argv only showed the same change a second time.
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the captures are real-tool records in `testing/reframe_testing/fake_data/captures.json`. Each one has the build line (`ffmpeg n9.0.2-17-g2a571b6068`), the machine (AMD RX 7600) and the exit code. `capture_fake_data.py::detect_captures` made the recorded `command` with `hardware_test_argv` / `filter_test_argv`, and FFmpeg ran exactly that argv. The capture test compares the whole recorded argv with the builder's output for the same encoder, bit depth and device. The three hand-written expectations are argv for argv equal to the captures: `detect_hevc_qsv_no_device` (QSV init, filter device and `-vf format=nv12,hwupload=extra_hw_frames=64,format=qsv`), `detect_hevc_nvenc_no_driver` (`-pix_fmt yuv420p`), `detect_libplacebo_ok`/`_no_vulkan` (the filter argv). The `av1_amf` 10-bit tail (`-pix_fmt p010le`) is not in a capture (the capture is `hevc_amf_10bit_ok`). A definition change that takes `p010le` away from `av1_amf` still fails `test_everything_works` (`sorted(ten) == sorted(ten_bit)` counts the calls with `p010le`). No doc names the three tests. 3 tests and 19 code lines, as stated (recounted).
Checked: deleted the three tests (and TCD-03), then `runtests.sh packages/reframe/tests/capabilities` → 223 passed (load: 5 pytest processes).

Orchestrator: Tier A, package Q-7.4.

### TCD-03 `test_vaapi_command` is also pinned by the VAAPI captures
- Kind: other (a pure test duplicated by a recorded-data test)
- Where: `capabilities/test_hwtest.py::test_vaapi_command` (27), and the constants `HEAD`, `SOURCE` (23-24), which nothing else uses after TCD-02
- Now: the test asserts the full `hevc_vaapi` 10-bit argv on renderD128, and that an
  `h264_vaapi` argv with `vaapi_device=/dev/dri/renderD129` contains `vaapi=va:/dev/dri/renderD129`.
- Change: delete the test and the two constants.
- Saved: 1 test, about 11 code lines, about 0 s.
- Guarantee kept by: `test_the_hardware_captures_ran_the_current_command[detect_hevc_vaapi_10bit_ok]`, the same full argv: renderD128, `format=p010le,hwupload`, `hevc_vaapi`. `[detect_h264_vaapi_bad_device]` passes `vaapi_device="/dev/dri/renderD999"` and asserts the full argv with `vaapi=va:/dev/dri/renderD999`, so the substitution of a given device is pinned with the whole argv.
- Why nothing is lost: the first assertion is identical to a capture case. The second is a
  weaker form (`in`) of the bad-device capture's equality, with another node number.
- Docs and history: `R.md` (line 79) names `test_vaapi_command` as the test that still checks
  the placeholder substitution after it deleted `test_placeholders`. That reason no longer
  needs this test: the capture test pins the substitution for a default and for a given
  device, and Q-6 CMD-04 has since replaced `resolve_placeholders`. git: `dc1d384` (C-4).
- Risk: low.
- Proposed tier: B (a trim report named it as a guard, so the verify step should run the R-report mutation "an unknown or wrong `{vaapi_device}` fill" against the capture test)
- Confidence: high
Verdict: CONFIRMED, tier B → A — I ran the mutation that R.md asks for, with `test_vaapi_command` (and TCD-02) deleted. (a) A given device is ignored (`values = {"vaapi_device": DEFAULT_VAAPI_DEVICE, …}`): `test_the_hardware_captures_ran_the_current_command[detect_h264_vaapi_bad_device]` fails, and so do 3 `test_detect.py` and 2 `test_service.py` node tests. (b) The device is filled wrongly (`vaapi_device + "x"`): all 4 VAAPI capture cases fail, and so do `test_detect.py` node tests and `test_real.py`. So the placeholder substitution that R.md named this test as the guard of is pinned with the whole argv. One guarantee is lost, and it does not matter: if the default of `hardware_test_argv`'s own `vaapi_device=` parameter changes to `renderD129`, the test suite still passes. That is because the capture test always passes the device it finds in the recorded argv (`renderD128` too). But no production code calls `hardware_test_argv` without a device: `run_hardware_test` always passes it, and its own default is guarded (`test_run_known_failure` asserts `renderD128` in the reason). The detection passes `device or DEFAULT_VAAPI_DEVICE`. 1 test and 11 code lines (9 + `HEAD` + `SOURCE`), as stated. Tier A: the reason for B was only the pending mutation check, and it passed.
Checked: mutation (a) → 6 failed, 217 passed. Mutation (b) → 8+ failed (4 VAAPI captures, `test_real.py::test_vaapi_and_amf_on_an_amd_gpu`, 3 detect tests). Default-parameter mutation (`vaapi_device: str = "/dev/dri/renderD129"` in `hardware_test_argv`) → 223 passed, so the mutation survives, but no production caller depends on that default. Every run: `runtests.sh packages/reframe/tests/capabilities`, 5 pytest processes on the machine.

Orchestrator: Tier A, package Q-7.4.

### TCD-04 `test_the_last_line_is_never_the_reason` repeats a `test_real_failures` row
- Kind: other (the same input, a weaker assertion)
- Where: `capabilities/test_reasons.py::test_the_last_line_is_never_the_reason` (138)
- Now: it takes the `detect_hevc_nvenc_no_driver` capture, checks that its last line is
  "Conversion failed!", and asserts that the reason does not contain "Conversion failed".
- Change: delete.
- Saved: 1 test, 4 code lines, about 0 s.
- Guarantee kept by: `test_reasons.py::test_real_failures[detect_hevc_nvenc_no_driver-…]` (124), the same stderr, reason `== "NVIDIA driver not found"`. `test_real_failures[hw_h264_vaapi_no_hwupload-…]` pins "the most informative line, never the generic last line" for an unknown text (state ERROR).
- Why nothing is lost: the reason equality implies "Conversion failed" is not in it.
  `returncode` is not given here and is 255 there, but `explain_failure` reads `returncode`
  only when no known text matches (`reasons.py:332-336`), and this text matches.
- Docs and history: grep docs/: none. git: `dc1d384` (C-4), not a fix.
- Risk: low.
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — `test_real_failures[detect_hevc_nvenc_no_driver-…]` has the same stderr and pins the reason with equality, and a known rule matches before the returncode or the last-line fallback is read (`reasons.py`, `explain_failure`). The removed test's check that the recorded last line is "Conversion failed!" is a precondition on the data, not a product guarantee. The generic-last-line rule stays pinned by the `hw_h264_vaapi_no_hwupload` row (ERROR, informative line). Added in `dc1d384`, not a fix. 1 test, 4 code lines.

Orchestrator: Tier A, package Q-7.4.

### TCD-05 `test_the_gpu_fingerprint_is_read_once` repeats the flow of `test_rescan_ignores_the_cache`
- Kind: near-copy
- Where: `capabilities/test_service.py::test_the_gpu_fingerprint_is_read_once` (387), `::test_rescan_ignores_the_cache` (287)
- Now: both start the service, wait, then `rescan()` with the default fake scenario. One counts
  the GPU fingerprint calls (`== 1`). The other checks that the rescan is not from the cache,
  that its first event is all CHECKING, and that the rescan ran test encodes. 2.58 s and 2.98 s.
- Change: merge into `test_rescan_ignores_the_cache`. Before `start()`, set
  `harness.service = harness.make(gpu_fingerprint=fingerprint)` with the counting function
  (it returns the same `GPU` string as the default), then add `assert calls == 1`.
- Saved: 1 test, about 7 code lines, about 2.6 s.
- Guarantee kept by: the merged `test_rescan_ignores_the_cache`, with the same flow (start, wait, rescan), the same fingerprint value and both sets of assertions.
- Why nothing is lost: the inputs are equal (the harness default is `lambda: GPU`). The
  fingerprint is read lazily in `_key` (`service.py:289-296`), so start plus rescan is exactly
  the path the counting test needs. The replaced service is never started and holds no task
  or subscription (`__init__` only stores fields).
- Docs and history: grep docs/: none for either name. git: both `dc1d384` (C-4), not a fix.
- Risk: low.
- Proposed tier: A
- Confidence: medium (the counting closure moves into a fixture-based test. Verify that it is still exactly 1)
Verdict: CONFIRMED — the merge works as proposed: replacing `harness.service` before `start()` gives exactly 1 fingerprint read across start, wait and rescan. The fixture closes the replacement service. No doc names the test. Measured: -1 test, net -7 code lines (14 removed, +7).
Checked: applied the merge → `runtests.sh capabilities/test_detect.py capabilities/test_service.py` 57 passed. Mutation `if self._gpu is None:` → `if True:` in `service._key` (the fingerprint is read on every key) → the merged `test_rescan_ignores_the_cache` FAILED (1 failed, 28 passed).

Orchestrator: Tier A, package Q-7.4.

### TCD-06 `test_a_10bit_test_with_another_pixel_format_fails` repeats the hwtest case one layer up
- Kind: layer-duplicate
- Where: `capabilities/test_detect.py::test_a_10bit_test_with_another_pixel_format_fails` (215) and its constant `AUTO_SELECTED` (45)
- Now: a full detection where the `hevc_amf` p010le test encode prints FFmpeg's
  "Incompatible pixel format 'p010le' … auto-selecting format 'nv12'" and exits 0. It asserts
  hevc_amf available, `supports_10bit` False, the `reason_10bit` text, and av1_amf 10-bit True. 1.41 s.
- Change: delete (with the constant).
- Saved: 1 test, about 23 code lines, about 1.4 s.
- Guarantee kept by: `capabilities/test_hwtest.py::test_run_10bit_with_another_pixel_format[nv12]` (164): the same encoder, the same stderr text and exit 0, and an exact `Failure(UNAVAILABLE, "hevc_amf does not take p010le in this FFmpeg build (it got nv12)", detail=…)`. The `[yuv420p10le]` case adds a 10-bit replacement format. How the detection turns a failed 10-bit test into "available, `supports_10bit=False`, `reason_10bit` = the failure's reason" is pinned by `test_detect.py::test_driver_errors_are_mapped` (av1_amf, lines 137-142) and `::test_timeouts_are_errors` (hevc_amf 10-bit hang, lines 168-173). The real FFmpeg behaviour is `test_real.py::test_a_replaced_pixel_format_fails_the_10bit_test`.
- Why nothing is lost: the detection-level lines it covers in addition to
  `test_driver_errors_are_mapped` are only `hwtest.py:133-137, 139` (covquery). The hwtest test
  covers those lines with the same input. The av1_amf `supports_10bit is True` assertion is
  what `test_everything_works` checks for every 10-bit hardware encoder without a rule.
- Docs and history: grep docs/: none. git: added in `75a0e50` "C-4: a stale cached status is
  checked again, not final (M2 review)", decision 0008 follow-up. The commit names this fix.
  The same commit added the hwtest test with the same input, so the rule "keep unless another
  test pins the exact same input" is met at the hwtest layer.
- Risk: medium. It is an M2 review regression test. The detection-level wiring stays covered
  by two other failure kinds.
- Proposed tier: B
- Confidence: medium
Verdict: REJECTED — keep it. The input is the same as `test_hwtest.py::test_run_10bit_with_another_pixel_format[nv12]`: `hevc_amf`, 10-bit, `p010le`, the identical "Incompatible pixel format 'p010le' for codec 'hevc_amf', auto-selecting format 'nv12'" text, exit 0. So the letter of the regression rule is met at the hwtest layer. But decision 0008, "Follow-up (M2 review, 2026-10-14)" item 2 ("The 10-bit test took exit code 0 as proof"), names its tests as "`test_real.py` (real FFmpeg), `test_hwtest.py`, `test_detect.py`". This is the only test in `test_detect.py` for that item, so the delete would make the decision record wrong. The auditor's "grep docs/: none" searched only for the test name. The test is also the only end-to-end check of the user-visible result for this M2 bug: the 8-bit test is clean, the 10-bit one is replaced, and the status is available with `supports_10bit=False` and that reason. The other detection-level failures go through non-zero exits (`test_driver_errors_are_mapped`) or a hang (`test_timeouts_are_errors`), not an exit-0 replacement. Saving 1 test and 1.4 s does not justify editing a decision record. If the owner still wants it gone, it goes with a decision 0008 edit in the same commit (tier C).
Checked: `git show 75a0e50` (both tests were added together, and the fix is in `hwtest.py`, `detect.py` only changes its docstring). `grep -n "test_detect.py" docs/decisions/0008-*.md` → line 176-177.

Orchestrator: Tier C, not planned: rejected in verify (decision 0008 follow-up item 2 names this file's test).

### TCD-07 The issue tests and their "apply the fix to a job" twins compute the same issue
- Kind: near-copy
- Where: `capabilities/test_issues.py::test_job_fix_applies` (248) and `::test_unavailable_with_a_fix` (168); `::test_job_with_a_libfdk_aac_track` (215) and `::test_audio_encoder_unavailable_with_a_fix` (200)
- Now: `test_unavailable_with_a_fix` and `test_job_fix_applies` both call
  `encoder_issues("hevc_nvenc", caps(**NO_HEVC_HARDWARE), DEFS)`. The first checks the issue
  and its fix, the second applies the fix to a job. `test_audio_encoder_unavailable_with_a_fix`
  and `test_job_with_a_libfdk_aac_track` both call
  `encoder_issues("libfdk_aac", caps(libfdk_aac=(UNAVAILABLE, "Not in this FFmpeg build")), DEFS, path="audio[1].encoder")`.
  The job test repeats the path and label assertions and then applies the patch.
- Change: merge each job test into its unit twin. Compute the issue once (for libfdk_aac,
  through the job's per-track comprehension, which also proves the ac3 track gives none), keep
  every assertion of both, then apply the patch.
- Saved: 2 tests, about 8 code lines, about 0 s.
- Guarantee kept by: the two merged tests, with the same snapshots and the same calls.
- Why nothing is lost: the inputs are identical. The job tests' path and label assertions
  repeat the unit tests' assertions. The patch-application assertions move unchanged.
- Docs and history: `R.md` "Uncertain, kept" names this pair: the audio test "is the only one
  that checks the audio message with the audio encoder's label" (decision 0020). The merge
  keeps that message assertion, so the reason for the keep holds. git: `dc1d384` (C-4),
  `fe5fed1` (C-4 audio fallback chain, decision 0020).
- Risk: low.
- Proposed tier: B (it goes against a recorded keep, though only as a merge)
- Confidence: high
Verdict: CONFIRMED — the inputs are identical, and R.md's keep reason (the audio message with the audio encoder's label) is kept by the merge. Applied: both merged tests pass with every assertion of the four tests. Measured: -2 tests, net about -10 code lines (41 removed, +7 in `test_unavailable_with_a_fix`, +24 in the audio test), a little more than the "about 8" in the report.
Checked: applied → part of the full three-folder run below (passed).

Orchestrator: Tier B, package Q-7.11.

### TCD-08 `test_colour_params_is_the_graphs_setparams` and `test_setparams_only_for_an_untagged_source` build the same graphs
- Kind: near-copy
- Where: `command/test_filtergraph.py::test_setparams_only_for_an_untagged_source` (277), `::test_colour_params_is_the_graphs_setparams` (392)
- Now: both build `graph(stream(), {"colorspace": FilterConfig(preset="bt2020")})`. One asserts
  the `setparams=…bt709,zscale=p=bt2020` substring and no `setparams` for a tagged stream. The
  other asserts `colour_params` of the untagged (exact) and tagged (None) streams and
  `,{setparams},zscale=` in the same graph. They are in the same coverage group.
- Change: one test, `test_setparams_only_for_an_untagged_source`:
  `setparams = colour_params(stream())`, its exact value, `f",{setparams},zscale=p=bt2020" in untagged`,
  `colour_params(tagged) is None`, `"setparams" not in graph(tagged, …)`.
- Saved: 1 test, about 6 code lines, about 0 s.
- Guarantee kept by: the merged test.
- Why nothing is lost: the inputs are identical. `f",{setparams},zscale=p=bt2020"` is stricter
  than both substring assertions. The tagged-graph assertion, the reason `C.md` kept the first
  test, stays.
- Docs and history: `C.md` "Uncertain, kept" names the pair ("Only the first checks that a
  tagged source gets no setparams in the graph"). The merge keeps that assertion. git:
  `b9d7379` (C-7), `181a7ec` (C-10).
- Risk: low.
- Proposed tier: B (it goes against a recorded keep, though only as a merge)
- Confidence: high
Verdict: CONFIRMED — the input is the same `graph(stream(), {"colorspace": FilterConfig(preset="bt2020")})`. The merged test keeps C.md's keep reason (no `setparams` in a tagged source's graph). `f",{setparams},zscale=p=bt2020"` together with the exact `setparams` value is stricter than both substring checks. Measured: -1 test, net -6 code lines.
Checked: applied → part of the full three-folder run below (passed).

Orchestrator: Tier B, package Q-7.11.

### TCD-09 `test_metadata_edit_plan_needs_no_tool` repeats the job of `test_metadata_edit_plan_edits_the_source`
- Kind: near-copy
- Where: `command/test_metadata_edit.py::test_metadata_edit_plan_needs_no_tool` (279), `::test_metadata_edit_plan_edits_the_source` (255)
- Now: both take `in_place()` with `audio[0]` set to `pt-BR` and call `build_plan`. One gets the
  tools found and checks the whole plan. The other gets ffmpeg and ffprobe MISSING and checks
  that the steps are `["header_edit"]`.
- Change: in `test_metadata_edit_plan_edits_the_source`, also build the plan with the missing
  tool set and assert `build_plan(job, src, caps(), none, shell="posix") == plan`.
- Saved: 1 test, about 3 code lines, about 0 s.
- Guarantee kept by: the merged test. Both inputs stay, and plan equality is stricter than the step-kind list.
- Why nothing is lost: same job, both tool sets, and a stronger assertion (the whole plan
  equal, not only the step kinds).
- Docs and history: grep docs/: none. git: `7247ae5` "feat(C-18): header_edit step runs
  Reframe's own Matroska writer" (decision 0080: the fix-up and the edit need no tool). The
  guarantee is kept and made stricter.
- Risk: low.
- Proposed tier: A
- Confidence: high
Verdict: CONFIRMED — the job is the same. With ffmpeg and ffprobe MISSING, the whole plan is equal to the plan with the tools found, which is stricter than the step-kind list. On Windows CI the removed test used the default shell. The merged one passes `shell="posix"`, and the steps do not depend on the shell. Measured: -1 test, net -3 code lines.
Checked: applied → part of the full three-folder run below (passed).

Orchestrator: Tier A, package Q-7.4.

### TCD-10 The MKV half of `test_a_header_edit_step_for_mkv_without_any_mkvtoolnix_but_not_for_webm` is in `test_metadata_edit.py`
- Kind: layer-duplicate (two files test the same builder rule)
- Where: `command/test_builder.py::test_a_header_edit_step_for_mkv_without_any_mkvtoolnix_but_not_for_webm` (191); targets `command/test_metadata_edit.py::test_an_mkv_output_gets_the_fixup_without_any_mkvtoolnix` (302) and `::test_no_fixup_without_a_tag_iso_639_2_cannot_say_or_outside_mkv` (322)
- Now: the builder test asserts that an MKV job with `pt-BR` on audio 1 has a `header_edit`
  step, and that a WebM job (libsvtav1, libopus, `pt-BR`) has none. The metadata-edit test
  asserts the exact steps `[encode, header_edit, finalize]`, the edit and the display for an
  MKV libx264 job with `pt-BR`. The other metadata-edit test checks "no fix-up" for an
  ISO 639-2 tag and for MP4.
- Change: move the WebM assertion (3 lines) into
  `test_no_fixup_without_a_tag_iso_639_2_cannot_say_or_outside_mkv`, then delete the builder test.
- Saved: 1 test, about 5 code lines, about 0 s.
- Guarantee kept by: `test_an_mkv_output_gets_the_fixup_without_any_mkvtoolnix` for the MKV fix-up, with a stricter assertion. The snapshot `test_plan_snapshot[languages_flags_and_ietf]` pins the same fix-up step, description and display with `pt-BR` on audio 1. The moved WebM assertion keeps the "Matroska-based but not MKV" case.
- Why nothing is lost: the MKV inputs differ only in the video encoder (the default vs
  libx264) and the `original` flag, and the fix-up reads neither. The covquery lines found only
  in the builder test (`audio.py:173-178`, `subtitles.py:130-131`, `video.py:66`) are the WebM
  job's, which moves.
- Docs and history: grep docs/: none. git: `7247ae5` (C-18, decision 0080), not a bug fix.
- Risk: low.
- Proposed tier: B (an assertion moves between files, and the MKV input is not identical)
- Confidence: medium
Verdict: CONFIRMED — the MKV fix-up is pinned more strictly by `test_an_mkv_output_gets_the_fixup_without_any_mkvtoolnix`. The only input differences (the default encoder and `original=True`) are fields that the fix-up does not read. The WebM case moves unchanged (it uses `build_plan(..., tools())` in place of `plan_of`, the same tools). Measured: -1 test, net -5 code lines. Tier B is fine (an assertion moves between files).
Checked: applied → part of the full three-folder run below (passed).

Orchestrator: Tier B, package Q-7.11.

### TCD-11 `dimensions/test_ffmpeg.py::test_interlaced_fixture` runs no FFmpeg filter. It only re-checks pure tests on a probed fixture
- Kind: layer-duplicate
- Where: `dimensions/test_ffmpeg.py::test_interlaced_fixture` (229)
- Now: it probes the `interlaced` fixture with the real ffprobe and asserts
  `source_geometry(...).interlaced`, chroma steps (2, 2), and that
  `compute_geometry` with a manual crop of top 6 gives crop top 4 and the note
  "Crop top 6 → 4 for interlaced 4:2:0.". No FFmpeg command runs on the result, unlike every
  other test in the file, which encodes and probes the output.
- Change: delete.
- Saved: 1 test, 9 code lines, about 0.26 s.
- Guarantee kept by: `probe/test_live.py::test_interlaced` (the real ffprobe on the same fixture: `field_order is TOP_FIRST`). `dimensions/test_source.py::test_interlacing_from_the_field_order[tff-True]` (TOP_FIRST becomes interlaced). `dimensions/test_source.py::test_chroma_steps[yuv420p-…]`. `dimensions/test_geometry.py::test_more_cases[DVD PAL 16:9 interlaced…]` (an interlaced 4:2:0 source with a manual crop of top 6 becomes 4, with exactly the note "Crop top 6 → 4 for interlaced 4:2:0."). The interlaced crop and height grid is also in the Hypothesis properties (`expect()` doubles `chroma_step_y` for interlaced). The real-FFmpeg grid rules are `test_x264_height_rules_for_4_2_0` and `test_chroma_steps_match_ffmpeg_crop_for_every_pixel_format`.
- Why nothing is lost: each step of the chain (ffprobe field order, then `interlaced`, then
  the crop grid and the note) is pinned with the same values. The fixture's 4:2:0 format is
  also in the recorded probe `testdata/probes/fixtures/interlaced.mkv.json`, which the
  snapshot `interlaced_all_filters` uses.
- Docs and history: grep docs/: none. Decision 0009 lists the FFmpeg behaviour items 1 to 5
  that `test_ffmpeg.py` records. This test records none of them. git: `789edae` (C-5), not a fix.
- Risk: low.
- Proposed tier: A
- Confidence: medium
Verdict: CONFIRMED — this is not the only real-tool check of the generated `interlaced` fixture. `probe/test_live.py::test_interlaced` (also `needs_ffmpeg`, so it runs in the same CI jobs) probes the same fixture with the real ffprobe and asserts `FieldOrder.TOP_FIRST`. That pins the "Interlaced: FFmpeg writes `field_order=tb`" behaviour in `testdata/README.md` as far as the removed test did: neither one tells `tb` from `tt`, because `parse.py` maps both to TOP_FIRST. `test_every_filter_on_an_untagged_interlaced_source` also encodes the fixture. Each later step is pinned with the same values: `test_interlacing_from_the_field_order[tff-True]`, `test_chroma_steps[yuv420p…]`, and the `test_more_cases` row "DVD PAL 16:9 interlaced" (manual top 6 → 4, the exact note "Crop top 6 → 4 for interlaced 4:2:0."). No doc names the test. 1 test, 9 code lines.
Checked: applied → the three folders collect 125 dimensions tests (was 126), and the run below passed.

Orchestrator: Tier A, package Q-7.4.

## Looked at and kept

- `dimensions/test_geometry.py::test_classic_cases` and `::test_more_cases` (9 + 38 rows) vs `test_properties.py`: the rows pin exact crop, size, SAR, aspect and note texts. The properties pin invariants (≤ requested crop, inside the box, multiple of the modulus, aspect error bound). Not covered either way. C.md also kept the rows as C-5 "Done when" tables. Coverage groups of 2 rows each (auto vs conservative before detection, custom PAR missing vs 0/1, 4:4:4 vs classic overscan) are distinct inputs with distinct notes.
- `dimensions/test_geometry.py::test_flip_and_rotation_are_reported_for_the_command_builder`: its first assertion is in `test_rotation_flip_and_pixel_aspect_pass_through`. Its size assertion (1080×1920 for SameAsSource after a 180° source and a 90° job rotation) is not in any row.
- `dimensions/test_geometry.py::test_crop_is_in_the_displayed_orientation`: the property allows any crop ≤ requested, so only this test pins that top 100 stays top 100 on a 90° source.
- `dimensions/test_geometry.py::test_negative_crop_values_are_clamped`: the property strategies never draw negative values (`model_construct` bypass).
- `dimensions/test_crop.py` examples vs `test_consensus_properties` and `test_rotate_crop_round_trips`: the properties check "auto is one of the samples with max agreement" and "conservative ≤ every sample". The examples pin tie-breaking, the exact conservative minimum, the agreement count and the clockwise direction. A round trip cannot tell clockwise from counter-clockwise. The coverage groups (tie pair, rotate pair) assert different things.
- `dimensions/test_properties.py`, the two coverage groups (3 and 2 properties with equal lines): different invariants of the same function. C-5 "Done when" names each.
- `dimensions/test_source.py::test_chroma_steps` (25 cases, 6 line sets): C.md already removed 14 equivalent formats. Each remaining case is a different output of a branch, or a trap (`p410le`/`y410le` "not 4:1:0", `uyyvyy411` restored after C's mutation M14, `YUV420P` case folding).
- `dimensions/test_source.py::test_unknown_pixel_formats`, `::test_interlacing_from_the_field_order`, `::test_unknown_sar_is_square`: one case per input class (None or empty vs unknown name, tff/bff/progressive/unknown, None/0/negative).
- `dimensions/test_ffmpeg.py` (other tests): each encodes or filters with FFmpeg and checks the output, the decision 0009 items 1 to 5 (oracles). `test_x264_height_rules_for_4_2_0` (4 cases, 1 line set): its work is in the subprocess, and each case is a boundary.
- `command/test_snapshots.py` (73 cases, 72 line sets, `h264_qsv` = `h264_vaapi` lines): each hardware case is the only argv check of that encoder's definition. CI has no GPU. C-7 "Done when" ≥ 40.
- Snapshots vs builder unit tests. No unit test builds a snapshot's job. `test_strict_is_written_once` duplicates the TrueHD track (the snapshot has one), so it tests the dedupe. `test_metadata_edit_plan_edits_the_source` is a language edit; the snapshots `metadata_edit_in_place` and `metadata_edit_windows_display` pin the same plan shape for other edits, and it documents the C-13/C-18 plan shape. `test_vaapi_device_default_and_from_the_status`: only the "from the status" half is like `hevc_vaapi_10bit_second_render_node` (another encoder); the "no device in the status" half is unique. `test_attachments_only_with_a_copied_ass_track_in_matroska`: the MP4 and "no subtitles" cases are in no snapshot. `test_argument_order` and `test_nothing_reaches_the_muxer_before_zero` (decision 0013 follow-ups, `415929c`) use jobs no snapshot has. The `metadata_edit` unit tests that are line subsets of `metadata_edit_in_place` (covmap) test other inputs ("unchanged value writes nothing", the source's IETF, name delete).
- `command/test_tracks.py` parametrizations (`test_mixdown_is_snapped` 15/10, `test_bitrate_…` 14/12, `test_samplerate_is_snapped` 7/2, `test_output_layout` 12/8, `test_opus_gets_a_layout_it_accepts` 30/14, `test_other_encoders_…` 6/5): C.md already removed 11 rows. Each remaining row is a different table outcome or boundary. `test_every_written_value_is_one_the_encoder_can_do` checks invariants, not the chosen value ("largest below", "down to a step"). The Opus rows are also the layouts that `test_layout_tables_match_ffmpeg` checks with the real FFmpeg.
- `command/test_filtergraph.py::test_subtitles_filter_opens_awkward_file_names` (10 real-FFmpeg cases, 1 line set): the two "all …" names contain most single characters, but C.md kept them all as real-tool and Windows-name cases. Kept.
- `command/test_filtergraph.py::test_escape_value` (5/1), `::test_filter_path` (5/2, Windows paths), `::test_a_deinterlacer_…` (8/7), `::test_detelecine_lowers_the_rate` (8/7), `::test_tonemap_filters_are_the_graphs` (4/3), `::test_bitmap_overlay_keeps_more_than_8_bits` (6/4, 0013 follow-up): each row is a distinct input class or expected value.
- `command/test_quoting.py::test_quote_windows` (14/6) vs the Hypothesis round trips: the rows pin the exact quoting of cmd.exe metacharacters, which a round trip does not need. C.md kept them. `test_posix_display_pastes_into_bash_zsh_and_fish` (4 shells, 1 set): a real-shell oracle, fish regression.
- `command/test_output_chapters.py::test_an_interval_that_makes_too_many_chapters_makes_none_at_once` (1e-7, 1e-300, 5e-324): small, tiny and subnormal (1/x = inf) boundaries (`14bd2ec`). `test_a_rename_leaves_…` (2/1): a short names list vs explicit empties. `test_the_limit_counts_…`: boundaries.
- `command/test_integration.py` (all): real-FFmpeg oracles or M2-review and decision 0026 regressions (`415929c`, `d533aa8`). `test_time_range_cuts_the_copied_chapters` is a line subset of `test_external_subtitle_with_a_range_starts_at_zero[mkv]`, but the range ends differ (3.2 vs 3.7) and only the first asserts the titles and the duration. `test_chapter_range_with_renamed_chapters` ⊂ `…_end_after_the_last_chapter_is_clamped`: different ranges, and the second is the `d533aa8` regression.
- `command/test_tracks.py::test_chapter_range_bounds` vs `test_builder.py::test_ranges`: the clamp results are partly implied by `expected_duration`, but the error cases and the start values are only in the first.
- `capabilities/test_service.py::test_hardware_tests_off` vs `test_detect.py::test_hardware_tests_off`: the service test pins that the setting reaches the detection (R.md mutation 3).
- `capabilities/test_service.py::test_the_setting_and_the_nodes_are_in_the_cache_key` (4.1 s) vs `test_cache.py::test_key_changes`: the service test pins the wiring of the setting and the nodes into the key. R.md also names it.
- `capabilities/test_service.py::test_unusable_ffmpeg` vs `test_detect.py::test_unusable_ffmpeg[...]`: two separate pre-checks. Q-6 "Looked at and kept".
- `capabilities/test_service.py::test_closing_on_the_final_event_keeps_the_cache` vs `::test_second_start_shows_the_cached_result_at_once`: the second half is similar, but the first pins the close-on-final-event race.
- `capabilities/test_service.py::test_libplacebo_result_is_in_the_snapshot`: its first two assertions are in `test_detect.py::test_libplacebo_without_vulkan`, but they are the precondition of its own rescan check.
- `capabilities/test_hwtest.py::test_run_10bit_with_another_pixel_format` (2/1): `yuv420p10le` is the "replaced by another 10-bit format" class.
- `capabilities/test_parse.py::test_every_captured_help_text_parses` (27/5): each case is a separate committed capture (data). Q-6 CMD-05 already trimmed this file.
- `capabilities/test_reasons.py` parametrizations (`test_real_failures` 10/9, `test_texts_confirmed_in_the_build` 12/10, the Vulkan and library rows): each row is a recorded text of a separate rule (0008, `testdata/README.md`).
- `capabilities/test_issues.py::test_preset_with_a_removed_encoder` (3/1): the H.264, H.265 and AV1 chains are separate definition data.
- `capabilities/test_detect.py::test_unusable_ffmpeg` (3/1), `capabilities/test_cache.py::test_bad_entries_are_misses` (5/4), `capabilities/test_devices.py::test_usable_filter` (5/4): one row per input class.
- `capabilities/test_fingerprint.py`, `test_detect.py::test_platforms`: Windows paths with fakes. Kept by rule.
- `capabilities/test_real.py`: real-FFmpeg oracles and `needs_gpu`.
- Q-6 CMD-10 (the `caps` helper copies): not reported again.

## Speed notes

- `command/test_integration.py::test_layout_tables_match_ffmpeg` (10.3 s) runs one libopus encode per layout, about 28, one after another. The runs are independent, so a thread pool (or `concurrent.futures`) would cut the wall time several-fold without changing the oracle.
- `capabilities/test_service.py::test_create_is_fast_while_detection_runs` (3.3 s) makes the fake `-encoders` sleep 2.0 s to prove that `create()` returns in under 1.0 s. A 1.3 s sleep with `>= 1.3` keeps the proof and saves about 0.7 s.
- `capabilities/test_service.py::test_second_start_shows_the_cached_result_at_once` (3.3 s) and `capabilities/test_recheck.py` (6.3 s) use 1.5 s listing sleeps (plus a 0.5 s probe delay) to hold the re-check open. These are timing windows, so shorten them only with care: about 1 s each.
- `capabilities/test_service.py::test_the_setting_and_the_nodes_are_in_the_cache_key` (4.1 s) runs four full starts with the fake ffmpeg. `hardware_tests=False` in its harness settings would make each start cheaper, if the key test does not need the encodes. Check that the setting is not itself part of the compared key change.

## Verifier notes

- Corrected totals. Tier A (TCD-01, 02, 03, 04, 05, 09, 11): 10 tests, about 60 code lines, about 5.3 s. Tier A+B (adds TCD-07, 08, 10; TCD-06 rejected): 14 tests, about 81 code lines (TCD-07 measured as 10, not 8), about 5.3 s. TCD-06 was the only time saving of B (1.4 s).
- All 11 findings applied together in the worktree: 744 → 729 collected (command 391 → 388, capabilities 227 → 216, dimensions 126 → 125). With TCD-06 kept, the result is 730.
  Checked: `runtests.sh packages/reframe/tests/command packages/reframe/tests/capabilities packages/reframe/tests/dimensions -q -m 'not benchmark'` with all 11 findings applied → 729 passed, 73 snapshots passed, 80.6 s (load: 3 other pytest runs). This is "the full three-folder run" that the verdicts refer to.
- TCD-02/03: the capture commands come from `hardware_test_argv` at capture time (`capture_fake_data.py::detect_captures`), so these tests guard the argv against drift since that capture. To fix a failure, you must capture again on real hardware (the docstring says how). This is the same pin as the hand-written lists, and it also has the real FFmpeg's stderr behind it.
- TVL-11 (validation report, cross-area): delete `command/test_builder.py::test_refusals` and keep `validation/test_command_agreement.py::test_plan_errors_are_validation_errors`, as the validation auditor proposes. The builder's unit-test file is the natural home of "the builder refuses X". But the agreement test is the strict superset: it has the same 10 multitrack jobs with the same `pytest.raises(PlanError, match=…)` texts, and it also asserts the matching validation code. `test_every_plan_error_is_covered` forces a row for each `raise PlanError`, so the builder refusals cannot quietly lose cases there. The reverse (keep `test_refusals`, drop the 10 rows) would lose the agreement check (decision 0024). Conditions: (1) tighten the passthrough row's match to `"h264 video cannot be copied into WebM"` as proposed. (2) A future `DISAGREE` entry (strict xfail) on one of these rows would hide a builder regression for that row: a strict xfail is satisfied whether the `PlanError` or the validation code is missing. `DISAGREE` is empty now. The note in `test_command_agreement.py` should say that a disagreement must not be on a row whose `PlanError` is the builder's only test. The differences I checked: the agreement uses `caps(libplacebo=False)` and `video={"encoder": "libx264"}` where `test_refusals` uses the default draft twice (no video stream, frame range without a rate), and neither refusal reads the encoder or libplacebo. My verdict: CONFIRMED, tier B, with condition (1).
- R.md's mutation 9 guard `test_hwtest.py::test_definition_errors` no longer exists (Q-6 CMD-04 replaced `resolve_placeholders`). I did not look for its replacement; it is outside this report's findings.
