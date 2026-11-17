# Area naming-preview-service: `packages/reframe/tests/naming/`, `packages/reframe/tests/preview/`, `tests/test_service.py`, `tests/test_service_nul_paths.py`, `tests/test_package.py`

Baseline: 26 files, 688 tests, 4,722 test code lines, 66 s of test time.

## Summary

5 findings. Tier A: 3 findings, -3 tests, about -20 code lines, about 0.6 s. Tier A+B: 5 findings,
-4 tests, about -47 code lines, about 2.3 s of test time.

Two earlier trims already went through this area: `docs/test-trim-reports/N.md` (naming: 769 to
632 tests, with mutation checks) and `R.md` (preview), plus `Q.md` for `test_service.py` and
`test_package.py`. Q-6 NDP-05 moved the facade `app` fixture and `FakeFs`. Most tests that are left
pin verified FFmpeg or guessit behaviour (`testdata/README.md` "Preview frames, crop detection and
clips (C-10)", `test_guessit_quirks.py`), decision-named guards (0033, 0041 R3-6), the C-16 naming
regressions, or NUL handling (VAL-14, Tier C). So there is not much left to cut.

The best three:
- TNP-04: `preview/test_facade.py::test_a_preview_clip_and_its_frames` (1.66 s) repeats what the
  server's clip route tests do through the same facade methods, and their assertions are stricter.
- TNP-01: `test_clip.py::test_the_clip_cache_is_read_off_the_event_loop` makes the same two clips
  as `test_the_same_request_gives_the_cached_clip`. Merge it into that test.
- TNP-02: `test_frames.py::test_the_default_count_comes_from_the_settings` becomes one setting and
  one assert in `test_the_cache_keeps_its_size_limit`.

## Findings

### TNP-01 The clip off-loop test makes the same two clips as the cached-clip test
- Kind: near-copy
- Where: `packages/reframe/tests/preview/test_clip.py::test_the_clip_cache_is_read_off_the_event_loop` (210), `::test_the_same_request_gives_the_cached_clip` (128)
- Now: both make `lossless(src)` of `letterbox` with `start=0.5, seconds=1.0` twice in one
  `make_env(tmp_path / "cache")` and assert `again == first`. The off-loop test also records the
  file reads on the event-loop thread (`file_reads_on_this_thread`) and asserts there are none. The
  cached-clip test also patches `run_streaming` to raise on the second call (no new encode), then
  asserts that another crop gives a new id. Coverage: the same 3043 lines.
- Change: merge into `test_clip.py::test_the_same_request_gives_the_cached_clip`. Add
  `on_loop = file_reads_on_this_thread(monkeypatch, tmp_path / "cache")` before the first `clip(...)`,
  and add `assert on_loop == [], on_loop` right after `assert again == first`, before
  `monkeypatch.undo()`. The undo also removes the recorder, but the list keeps what it recorded,
  so the assert covers both runs. Delete the off-loop test, and keep its docstring line ("The cache
  folder may be slow ...") as a comment.
- Saved: 1 test, about 6 code lines (8 out, 2 in), 0.27 s, one lossless clip encode.
- Guarantee kept by: the merged `test_the_same_request_gives_the_cached_clip`. Same input (two
  identical `lossless(src)` clips at 0.5 s / 1.0 s, fresh cache) and the same assertions
  (`again == first`, no cache-file read on the loop thread), plus its own assertions.
- Why nothing is lost: the input is identical. Both assertions of the off-loop test move over
  unchanged. The `no_encode` patch changes nothing for the second run of the off-loop test,
  because that run is a cache hit and does not encode in either test.
- Docs and history: `grep -rn test_the_clip_cache_is_read_off_the_event_loop docs/` finds nothing.
  `git log -S` gives cc2b510 "preview: read the frame and clip cache off the event loop" (a fix,
  with no review ID or decision). The merge keeps its exact input and assertion.
  `test_the_same_request_gives_the_cached_clip` comes from 181a7ec (C-10) and is named nowhere in
  docs/.
- Risk: low (the only subtle point is the `monkeypatch.undo()` order, explained above).
- Proposed tier: A
- Confidence: high

Verdict: ADJUSTED — the merge is sound and keeps every guarantee (same input, both asserts; the recorder is set before the first `clip(...)` and its list survives `monkeypatch.undo()`; the third clip after undo is simply not recorded, which the off-loop test never had either). Correction of the numbers only: the deleted test has 10 code lines (3 signature + 7 body), the merge adds 2, so **-1 test, -8 code lines** (not -6). Tier A stays. Not named in docs/ or testdata/; cc2b510 is a fix with no review ID, and its exact input and assertion move over.
Checked: applied the merge; `runtests.sh packages/reframe/tests/preview/test_clip.py …` (with the other changed files) → all passed, light load. Mutation: `cached = _cached_clip(cache, clip_id)` (the cache lookup on the event loop, `preview/clip.py:177`) → the merged `test_the_same_request_gives_the_cached_clip` FAILS (`-n 0`, 1.2 s), so the off-loop guard is kept.

Orchestrator: Tier A, package Q-7.5.

### TNP-02 The settings default count of the frames task: one assert in a test that already sets the preview settings
- Kind: near-copy
- Where: `packages/reframe/tests/preview/test_frames.py::test_the_default_count_comes_from_the_settings` (101), `::test_the_cache_keeps_its_size_limit` (221)
- Now: the first test runs a real frames task on `letterbox` with
  `AppSettings(preview=PreviewSettings(sample_frames=4))` and `count=None`, and asserts 4 frames.
  The second already builds `AppSettings(preview=PreviewSettings(cache_size_mb=0))` and runs a
  frames task with `count=2`. Coverage: the first test's lines are a subset of 8 other tests' lines
  (the subset list in covmap).
- Change: merge into `test_frames.py::test_the_cache_keeps_its_size_limit`. Use
  `PreviewSettings(cache_size_mb=0, sample_frames=2)`, change `count=2` to `count=None`, and add
  `assert len(fs.frames) == 2`. Delete `test_the_default_count_comes_from_the_settings`.
- Saved: 1 test, about 10 code lines, 0.36 s, one frames task (4 FFmpeg frame runs).
- Guarantee kept by: the merged `test_the_cache_keeps_its_size_limit`. With `count=None`, the frame
  count comes from `preview.sample_frames` (a value other than the default 10), and the test asserts
  that count. Its own guarantees stay: an old frame is trimmed over the limit, and the task's own
  frames stay.
- Why nothing is lost: the input class is the same (a value of `sample_frames` that is not the
  default, with no `count`). 2 instead of 4 does not take another path. The explicit `count` path
  that the size-limit test used is covered by about 15 other tests in `test_frames.py`. The
  trimming does not depend on how the count was chosen. `cropdetect::test_the_samples_are_the_frames_of_the_strip`
  is not a guard here: it only compares two tasks that both read the setting.
- Docs and history: `grep -rn test_the_default_count_comes_from_the_settings docs/` finds nothing.
  `git log -S` gives only 181a7ec (C-10, first version). `test_the_cache_keeps_its_size_limit` is
  named in `docs/test-trim-reports/R.md` as the guard of `trim()` with the real clock. That guard
  stays, because the merge only adds to it.
- Risk: low. A `PreviewSettings` value from 1 to 60 is valid, so `sample_frames=2` is fine.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — `sample_frames=2` is valid (1..60, default 10, `models/settings.py:78`), `count=None` takes `settings.preview.sample_frames` (`preview/frames.py:81`), and the merged test keeps its R.md guard role (R.md mutation 10). Numbers: -1 test, -10 code lines (13 out, 3 in, two of them changed lines). Tier A.
Checked: applied the merge; `runtests.sh … preview/test_frames.py …` → passed. R.md mutation 10 (`trim()` uses clock 0 when `now` is None) → merged `test_the_cache_keeps_its_size_limit` FAILS. Mutation `count=10 if count is None else count` (setting ignored) → merged test FAILS. Both `-n 0`, about 1.4 s, light load.

Orchestrator: Tier A, package Q-7.5.

### TNP-03 `test_multibyte_characters_are_never_split` is covered by a stricter example and by the property test
- Kind: property-covers
- Where: `packages/reframe/tests/naming/test_sanitize.py::test_multibyte_characters_are_never_split` (281)
- Now: the file part `"日本語" * 40` (3-byte characters, `mkv`). It asserts that the part is at
  most 250 bytes and that `part.encode().decode("utf-8")` does not raise (no lone surrogate, which
  means no half character).
- Change: delete.
- Saved: 1 test, 4 code lines, about 0 s.
- Guarantee kept by:
  - `test_sanitize.py::test_bytes_that_are_not_utf8_become_the_replacement_character` (189):
    `_one("\udcff" * 100)` gives a file part of 3-byte characters (`"�"`) cut at the limit, and
    the test asserts the exact result `"�" * 82 + ".mkv"`. That is the same class (a cut through
    3-byte characters in a file part, `mkv`) with a stricter, exact assertion.
  - `test_every_part_is_safe_and_fits` (168, Hypothesis): `"日本語" * 30` and `"é" * 70` are in its
    sampled text. It asserts `len(fsencode(file + ".part")) <= 255` (the same as `<= 250`) and no
    character in `0xD800..0xDFFF`.
  - `test_folder_parts_have_the_full_255_bytes` and `test_a_long_reserved_name_stays_in_the_byte_limit`
    pin "never half a character" with exact results for 2-byte characters.
- Why nothing is lost: the two assertions of the deleted test are the property test's assertions.
  An exact deterministic case of the same class (3-byte characters cut in a file part) stays.
  Coverage: its 53 lines are all covered by `test_bytes_that_are_not_utf8_…` (covquery: only A 0
  lines).
- Docs and history: `grep -rn test_multibyte_characters_are_never_split docs/` finds nothing.
  `git log -S` gives only e585527 (C-16, first version, no bug named).
- Risk: low
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — the deleted test's cut is at an aligned boundary (246 bytes = 82 three-byte characters), so it never actually forces a split of a character; the `\udcff` * 100 case in `test_bytes_that_are_not_utf8_…` is the same aligned 3-byte cut with an exact result, and the 2-byte folder case (`test_folder_parts_have_the_full_255_bytes`, 255 bytes → 127 characters, not aligned) is the test that really pins "never half a character". Not named in docs/ or N.md (N.md names no sanitize guard). -1 test, -4 code lines. Tier A.
Checked: deleted it; `runtests.sh … naming/test_sanitize.py …` → passed. Mutations of `_cut` (`naming/sanitize.py:108`) with the multibyte test already deleted: `errors="replace"` (a split character becomes a 3-byte "\ufffd") → `test_a_long_reserved_name_stays_in_the_byte_limit[mkv,m4v,""]` and the property test FAIL; `errors="surrogateescape"` → the same plus `test_folder_parts_have_the_full_255_bytes` FAIL (`-n 0`, 0.7 s; it waited for a slot). Source restored.

Orchestrator: Tier A, package Q-7.5.

### TNP-04 The facade clip test repeats the server's clip-route tests
- Kind: layer-duplicate
- Where: `packages/reframe/tests/preview/test_facade.py::test_a_preview_clip_and_its_frames` (57)
- Now: through the facade (`app` fixture, real FFmpeg), it runs `app.jobs.preview_clip(job_for(letterbox), start=1.0, seconds=1.0)`
  and asserts DONE and a `PreviewClip`. Then `preview_clip_path(clip.id) == clip.path`,
  `preview_clip_path("0" * 32) is None`, and `app.sources.frames(clip.path, timestamps=[0.5])`
  gives one frame.
- Change: delete. The server layer keeps the facade-wiring check: its routes are the only
  production callers of `jobs.preview_clip` and `jobs.preview_clip_path` (no CLI caller; checked
  with grep), and they go through the real facade with stricter assertions. The core module layer
  keeps the clip and frame behaviour.
- Saved: 1 test, 15 code lines, 1.66 s (one clip encode, one frames task).
- Guarantee kept by:
  - `packages/reframe-server/tests/test_preview.py::test_frames_of_a_clip_are_decoded_from_the_clip`
    (228). Real FFmpeg, `letterbox`. `POST /api/preview/clip` calls the real
    `reframe.jobs.preview_clip`, and the task is DONE with a `PreviewClip` result.
    `POST /api/preview/clips/{id}/frames` calls the real `jobs.preview_clip_path(id)` and then
    `sources.frames(path, timestamps=[0.0, 0.5])`. It asserts two frames of 320x134, which proves
    that the path is the clip and not the source (stricter than one frame).
  - `test_preview.py::test_frames_of_a_clip_not_in_the_cache_is_404` (258) and
    `::test_the_link_of_a_clip_not_in_the_cache_is_404` (264): `preview_clip_path` of an unknown
    id is `None`, which the route turns into a 404.
  - `test_preview.py::test_a_clip_task_result_leads_to_a_playable_url` (208): the link route calls
    `preview_clip_path` for a real clip.
  - `preview/test_clip.py::test_a_clip_with_the_jobs_plan` (`clip_path` of the id and of `../`+id),
    `::test_the_encoded_frames_are_the_output_frames` (frames of a clip file).
- Why nothing is lost: every input of the facade test (a real clip of `letterbox`, its id, an
  unknown id, frames of the clip file) is sent to the same facade methods by a server test, with
  the same or stricter assertions. The only difference is the layer: the core package alone would
  no longer run `jobs.preview_clip` end to end. CI runs both packages together, and
  `test_the_cache_lookups_read_no_file_on_the_event_loop` still calls `preview_clip_path` directly
  in the core.
- Docs and history: `grep -rn test_a_preview_clip_and_its_frames docs/` finds nothing. `git log -S`
  gives only 181a7ec (C-10, first version). `test_facade.py` is not named in docs/.
- Risk: medium. It is a cross-package dependency: a run of only `packages/reframe/tests` loses this
  facade path.
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED (Tier B, medium risk as stated) — on whether the server path is the same: yes, for every assertion the facade test makes. The server's app holds the real `Reframe`, made by the same `Reframe.create(config, data, cache_dir)`; the routes call exactly `reframe.jobs.preview_clip(job, start=, seconds=)` (`routers/preview.py:168`), `reframe.jobs.preview_clip_path(id)` (`:174`, `:186`, `routers/media.py:65`) and `reframe.sources.frames(path, timestamps=…)` (`:188`). Same fixture (`letterbox`, copied into the media root by `api.add_fixture`), real FFmpeg. Differences, none of which the facade test asserted: (1) in the server tests FFmpeg runs **behind the fake-tools launcher** (`use_real_tools` → `exec_program` → `subprocess.call` of the real binary), so the core's own process tree (Job Object on Windows) holds a Python launcher with FFmpeg below it; that matters only for cancel/kill, which the facade test does not do; (2) the server settings turn `hardware_tests` off, so the "only A" coverage is capability detection/hwtest and naming lines from `job_for`, nothing clip-specific; (3) `preview/clip.py:86-87` (wait for an encoder still being checked) is only-A by a race, and it is pinned on purpose by `test_clip.py::test_validation_waits_for_an_encoder_being_checked`. Windows: `packages/reframe-server/tests/test_preview.py` has no Windows skip (module or conftest), and the CI Python job runs `uv run pytest -m "not needs_gpu and not benchmark"` over all testpaths (both packages) on ubuntu-latest and windows-latest with `REFRAME_REQUIRE_FFMPEG=1`, so the keepers fail rather than skip wherever the deleted test ran; the Linux pinned-FFmpeg job also runs both packages. The auditor missed a better core keeper for the two path asserts: `preview/test_facade.py::test_the_cache_lookups_read_no_file_on_the_event_loop` already asserts `app.jobs.preview_clip_path(known) == mkv` and `(unknown) is None` through the core facade. What a core-only run loses is just an end-to-end run of the one-line `JobService.preview_clip` (`jobs.py:711`). Not named in docs/; history only 181a7ec. -1 test, -15 code lines, 1.66 s.
Checked: deleted it; `runtests.sh … preview/test_facade.py packages/reframe-server/tests/test_preview.py …` → passed. covquery A vs `test_frames_of_a_clip_are_decoded_from_the_clip` → only-A 276 lines: capability detection/hwtest, naming, `clip.py:86-87` (covered by the dedicated test above). Coverage DB for `jobs.py:711` → only the facade test and the two server clip tests.

Orchestrator: Tier B, package Q-7.10.

### TNP-05 The `env` fixture (and the fake-tools `fake` fixture) copied between the facade test files
- Kind: shared-setup
- Where: `packages/reframe/tests/test_service.py::env` (60) and `::fake` (70);
  `packages/reframe/tests/test_service_nul_paths.py::env` (31) and `::fake` (41). Cross-area: the
  same `env` body, character for character, is in `test_service_settings.py:36`. Variants with
  extra lines are in `tools/test_fetch_cli.py:64`, `queue/test_facade.py:32`,
  `capabilities/test_service.py:~100`, `test_cli.py:~183`, `jobs/conftest.py:~171` and 9 more
  (grep `REFRAME_{name.upper()}_DIR`).
- Now: `env` (clear `ENV_VARS`, set `REFRAME_CONFIG/DATA/CACHE_DIR` under `tmp_path`, 7 code lines)
  is written out 3 times. `fake` (point `REFRAME_FFMPEG`/`REFRAME_FFPROBE` at `fake_tools` with the
  multitrack probe rule, 5 to 9 code lines) is written out twice, with the same behaviour.
  SRV-05 did not cover these (it moved the wait loops and the server helpers only).
- Change: move `env` and `fake` (with `MULTITRACK`) to `packages/reframe/tests/conftest.py`, which
  already exists and holds `anyio_backend` and `fifo_read`. A module that defines its own `env` or
  `fake` still overrides them, so `tools/test_fetch_cli.py` and the variants are not touched.
  Delete the copies in `test_service.py` and `test_service_nul_paths.py` (and in
  `test_service_settings.py`, if that area agrees). `test_service.py` keeps its `probe_rule` and
  `stdout_file` helpers for the other tests.
- Saved: 0 tests, about 12 code lines in this area (about 26 out, about 14 into conftest), about
  19 with `test_service_settings.py`, 0 s.
- Guarantee kept by: the same fixtures, with the same bodies, from the conftest.
- Why nothing is lost: helpers move, no test changes. A fixture in a directory conftest has a
  wider scope than a module fixture of the same name, so the module copies elsewhere still win.
- Docs and history: none (fixtures, not tests).
- Risk: low. Check with `uv run pytest --collect-only -q packages/reframe/tests` that no test
  starts to get the conftest `env` when it expected none (a test that asks for `env` now has a
  module copy, so nothing changes for it).
- Proposed tier: B (helps more as a cross-area change, so it needs the other areas to agree)
- Confidence: high

Verdict: ADJUSTED — the move works (no test changes; no module picks up the conftest `env`/`fake` unexpectedly: 7 files in `packages/reframe/tests` define their own `env`, and the 3 module-level `fake` fixtures win). But the line count is lower: with the imports (`ENV_VARS`, `ft`) and a `MULTITRACK` constant that ruff wraps, conftest gains 21 code lines while 30 go out of the two files (13 net from `test_service.py`, 17 from `test_service_nul_paths.py`), so **0 tests, about -9 code lines** in this area (not -12). `test_service.py` keeps its own `MULTITRACK`, `probe_rule` and `stdout_file` (used by other tests). Tier B (pays off only with the cross-area copies).
Checked: applied it; `uv run ruff check packages/reframe/tests` → clean after `--fix`; `uv run mypy` → no issues (598 files); collection with all five findings applied: area 688 → 684 (naming 482→481, preview 176→173, test_service.py 23, nul 6, package 1); `runtests.sh` of `test_service.py test_service_nul_paths.py test_service_settings.py tools/test_fetch_cli.py` with the changed preview files, `naming/test_sanitize.py` and server `test_preview.py` → 183 passed in 40 s, light load.

Orchestrator: Tier B, package Q-7.10.

## Looked at and kept

- `naming/test_corpus.py` (146 cases, 68 line sets; `test_corpus_ignores_guessit_user_config[2]`
  runs all of them again): this is committed test data, and status.md names the user-config test
  as the 0012 guard (N.md).
- `naming/test_template.py::test_a_huge_width_or_precision_is_an_issue` (39 cases, 2 line sets:
  season + quality_bitrate share one): it is a C-16 MemoryError regression (cd0b060). N.md tried to
  drop `quality_bitrate`, and the float mutation then survived, so they put it back and said
  "stays whole". A rotating trim of the 13 specs over the 3 variables would save about 26 cases
  of about 1 ms each. That is not worth going against that recorded decision (Tier C).
- `naming/test_resolve.py::test_number_overrides_take_only_ascii_digits` (11 cases, 1 line set):
  N already trimmed it from a Cartesian product. Each case is a separate input class (superscript,
  three Unicode digit sets, 10 digits, 5000 digits, sign, decimal, two numbers) of the
  `[0-9]{1,9}` rule (0012 follow-up, cd0b060).
- `naming/test_source.py::test_generic_folders` (15 cases, 1 line set),
  `test_sanitize.py::test_reserved_names` (10, 1), `::test_not_reserved` (5, 1),
  `::test_forbidden_characters` (10, 3), `test_variables.py::test_hb_encoder` (7, 1),
  `::test_resolution` (15, 3), `::test_audio_channels_label`, `test_clean.py::test_convert_separator`,
  `::test_title_case_is_handbrakes`, `test_parse.py::test_detect_separator`, `::test_clean_text`,
  `test_source.py::test_split_extension`, `test_template.py::test_suggestions`: these share line
  sets because each case is one regex alternative or one data-table entry. N trimmed them with
  mutation checks, and had to put cases back in `specials?` and `convert_separator`. In
  `test_reserved_names`, CON, PRN, AUX and NUL each pin one member of `RESERVED_NAMES`.
- `naming/test_guessit_quirks.py` (all 14) and `test_parse.py::test_guessit_reads_user_config_files_without_the_option`:
  they pin guessit's own output (library behaviour, CLAUDE.md), each next to the workaround.
  `test_quirk_bare_absolute_numbers_…` has the same lines as
  `test_parse.py::test_absolute_numbers_in_other_digits[Bleach - 001]`, but the inputs differ
  (raw guessit spans and One Piece compared with Reframe's Unicode digits).
- `naming/test_resolve.py::test_demo_hacksaw_ridge` and `::test_result_round_trips` (same lines,
  same input): a merge would save 1 test and about 3 lines. But the first is an M2 demo test
  ("kept by rule", N.md), and N.md names the second as the guard of a deleted round-trip test.
  Kept as they are.
- `naming/test_template.py::test_suggestions[maintitle]`, `::test_field_and_target_of_the_fix`,
  `::test_unknown_variable_keeps_its_spec_in_the_fix` (same lines): each asserts a different part
  of the fix (label, path and target, spec).
- `naming/test_sanitize.py::test_255_byte_limit_cuts_at_last`, `::test_folder_parts_have_the_full_255_bytes`
  (same lines as the deleted multibyte test): they have exact byte counts and notes, which the
  property test does not check.
- `naming/test_sanitize.py::test_every_windows_forbidden_character_is_replaced`: unlike the
  property test, it calls `replace_forbidden` directly and asserts `changes`.
- `naming/test_naming_models.py` (3): persistence. A stored job without `field_overrides` still
  loads, and unknown fields survive.
- `preview/test_common.py::test_a_time_a_frame_key_cannot_hold` (4 cases, 1 line set),
  `::test_the_last_time_a_frame_key_holds`, `test_frames.py::test_a_time_far_after_the_end`: R3-6
  guards, named in decisions 0033:227-229 and 0041:146.
- `preview/test_common.py::test_a_time_that_is_not_in_the_source` (3, 1), `::test_a_count_out_of_range` (2, 1),
  `test_cache.py::test_timestamp_ms` (4, 1), `test_clip.py::test_bad_ranges` (4, 3): R.md trimmed
  them already. Each case left is a boundary or a separate "just outside" value.
- `preview/test_cache.py::test_not_a_frame_key` (9 cases, 1 line set): each is a separate way to
  get out of the cache folder or a separate key shape (path traversal, upper case, newline,
  13-digit time). This is a security boundary.
- `preview/test_frames.py::test_the_frame_cache_is_read_off_the_event_loop` (subset of nothing, but
  `test_output_frames_follow_the_job` is a subset of it): a merge into `test_output_frames_follow_the_job`
  would lose the off-loop check of the path where both kinds are made in one run (that test always
  has the source frames cached first). Kept.
- `preview/test_frames.py::test_two_tasks_make_the_same_frames` and the other members of the
  1382-line subset chain: each asserts something different (concurrency, cache hit, copied video,
  unplannable job, clear).
- `preview/test_frames.py::test_fast_seek_gives_the_frame_of_a_slow_seek` (a subset of
  `test_clip::test_the_encoded_frames_are_the_output_frames`): a verified FFmpeg behaviour (README
  "Fast seek gives the frame of a slow seek").
- `preview/test_frames.py::test_one_run_for_both_kinds_…` (4), `::test_an_untagged_hd_source_is_shown_with_bt709`,
  `test_cropdetect.py::test_cropdetect_rounding_example`, `::test_a_single_frame_needs_skip_0`,
  `::test_an_absolute_limit_finds_no_bars_in_10_bit`, `::test_black_levels`, `test_cancel.py` (3),
  `test_benchmark.py`: verified tool behaviour (README C-10 section) and the C-10 "Done when"
  (cancel within 1 s, 4K HDR budget).
- `preview/test_clip.py::test_loudness_and_the_bcp47_language_header_edit` (a subset of
  `::test_the_clip_has_the_bcp47_language`): the second is a `needs_mkvtoolnix` oracle and skips
  where MKVToolNix is missing. The first asserts the step sequence and the `.part` target of the
  header edit with a fake writer.
- `preview/test_clip.py::test_a_cancel_*` (3): defect regressions (docstrings say "Defect:").
- `preview/test_clip.py::test_a_clip_with_the_jobs_plan` and `::test_the_encoded_frames_are_the_output_frames`:
  both make a lossless letterbox clip, but at 1.0 s and at 0.0 s. Sharing one clip would change
  the pixel comparison to a seek offset (some risk, about 0.3 s saved).
- `preview/test_facade.py::test_frames_and_a_frame_by_key`: it is the only check that the
  facade's frames go into `cache_dir/frames`, and the only facade-level check that a job's output
  frame is cropped. The server tests only check kinds and URLs.
- `preview/test_facade.py::test_crop_detection`: the only test that runs the real
  `Reframe.sources.cropdetect` (the server test monkeypatches it), and the only one that checks
  `done.result == result.model_dump(mode="json")` for crop detection.
- `preview/test_facade.py::test_the_cache_lookups_read_no_file_on_the_event_loop`: a fix (07fef91);
  no other test covers the facade lookups off the loop.
- The `tone.mka` "no video stream" tests in `test_frames.py`, `test_cropdetect.py` and `test_clip.py`:
  each task has its own check (`frames.py:73`, `crop.py:63`, `clip.py:122`). The shared setup is
  one line in each file.
- The rotated-MP4 setup in `test_frames.py` (fixture) and `test_cropdetect.py` (inline): a shared
  `preview/conftest.py` would cost about as many import lines as it saves.
- `test_service.py::test_probe_errors_are_values`: the only facade test of a missing file with a
  usable ffprobe (`service.py:275,597`; covquery against the NUL and `async with` tests). The
  FAILED half overlaps `probe/test_prober.py::test_unreadable_file`, which is stricter, but the
  test stays for the missing-file half.
- `test_service.py::test_a_cancelled_probe_many_kills_every_ffprobe` and
  `::test_cancelling_the_probe_many_task_reaps_every_ffprobe` and
  `::test_probe_many_starts_no_probe_after_a_cancel`: the first two differ in the path (token
  cancel or task cancel). The third has a stub and progress counts (the SRV-01 port).
- `test_service.py::test_folders_default_to_paths_and_can_be_given` (a subset of 2 others): it is
  the only check of the folder defaults and of the given folders.
- `test_service_nul_paths.py` (6): VAL-14 is Tier C (NUL handling in every layer stays). Decision
  0016.
- `test_package.py::test_version_is_pep440`: the only check of the core package's version form
  (Q.md removed its neighbour already).

## Speed notes

- `preview/test_clip.py::test_two_identical_clips_at_once` (4.64 s): it runs two 3 s libx265
  encodes of `hdr10-4k`. Both tasks start, and look in the cache, before either one finishes, so
  a 1 s `letterbox` clip may keep the same race at a fraction of the time. Check that the two runs
  still overlap at the rename.
- `preview/test_cancel.py::test_cancel_frames` (7.31 s): the cancel happens about 0.3 s after
  FFmpeg starts. Most of the time is probably the first `fixture_media("hdr10-4k")` generation or
  the probe and plan of the 4K file in that worker. This is not measured here.
- `test_service.py::test_create_returns_at_once_while_discovery_is_slow` (1.75 s): the fake
  `-version` sleeps 1.5 s. A 1.0 s sleep (assert `create() < 0.5` s and the probe `>= 0.9` s) would
  keep the margin and save about 0.5 s.

## Verifier notes

- Corrected totals. Tier A (TNP-01, -02, -03): **-3 tests, -22 code lines** (8 + 10 + 4; the
  auditor said about 20), about 0.6 s. Tier A+B (adds TNP-04, -05): **-4 tests, -46 code lines**
  (22 + 15 + 9; the auditor said about 47), about 2.3 s. Area count with all five applied:
  688 → 684 tests.
- Verdicts: 3 confirmed (TNP-02, TNP-03, TNP-04), 2 adjusted (TNP-01 and TNP-05: line counts only),
  0 rejected.
- TNP-04: the better core keeper for `preview_clip_path` (known id and unknown id through
  `app.jobs`) is `preview/test_facade.py::test_the_cache_lookups_read_no_file_on_the_event_loop`,
  which stays in the core package. After the deletion, a core-only run (`uv run pytest
  packages/reframe/tests`, as some Q-6 "Done when" lines use) no longer runs
  `JobService.preview_clip` (`jobs.py:711`). It is one line that calls `preview.start_preview_clip`,
  and `preview/test_clip.py` tests that function in depth. The full run and CI (both OSes) still run it
  through the two server clip tests. If the owner wants the core package to stand alone, keep the
  test. Otherwise Tier B is right.
- TNP-04, process tree: the server keepers run FFmpeg through the fake-tools launcher (a Python
  child that runs the real binary). The facade test was the only core test where the *facade*
  starts a clip encode that is the real FFmpeg as its direct child. It never cancelled, so no assertion
  depended on that. Clip cancel and kill of the real tree stay in `preview/test_clip.py::test_a_cancel_*`
  and `test_cancel.py`.
- TNP-03: the deleted test and the `\udcff` case both cut at a 3-byte-aligned limit (246 = 3 × 82),
  so neither forces a split of a 3-byte character. Only the 2-byte folder case and the reserved-name
  case catch a `_cut` that splits a character. Consider making the kept exact 3-byte case
  non-aligned (for example a 1-byte prefix) if the owner wants a 3-byte split pinned exactly. This is not
  needed for the deletion.
- TNP-05: the conftest `fake` copies the `test_service_nul_paths.py` body (an inline `ft.Rule`), so the
  conftest does not need `probe_rule` or `stdout_file`. `test_service.py` keeps those two helpers.
- Speed note on `test_two_identical_clips_at_once`: not checked here. The 4K HDR clip may be there
  on purpose (a long encode so that both runs overlap). Check that the runs still overlap before you
  shrink it, as the auditor says.
