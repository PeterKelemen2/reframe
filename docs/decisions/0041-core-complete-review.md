# 0041 — The core-complete review: findings and what was done with each

- Status: accepted
- Date: 2026-10-16
- Steps: C-3, C-6, C-8, C-10, C-11, C-12, C-13, C-14, C-15

## Context

[0029](0029-core-before-the-ui-milestones.md) merges `core-complete` into `main` only after a
fresh review's findings are fixed. `git diff main...core-complete` is about 53 000 added lines
(224 files) after the batch engine (2a, [0040](0040-batch-engine-and-reframe-batch.md)) was
merged, too much for one reviewer. Five fresh reviewers (`xhigh`) each took one area, on
`core-complete` at 3cde317:

| Reviewer | Area |
|----------|------|
| R1 | C-12 M6: the selection stage, `explain`, the defaults lint, `JobService.draft` / `explain` |
| R2 | C-12 M7 and C-15 `batch`: descriptors, grouping, rules, derive / merge, overrides, resolution, `Reframe.batch`, `reframe batch` |
| R3 | C-10: the scans, frames, crop detection, preview clips, the frame cache |
| R4 | C-13, C-11 (core-complete parts), C-14: in-place edits, the queue's keys, the Matroska reader, when-done, power actions |
| R5 | C-6 option sets and C-8 option rules, the dry run, C-15 `tools` / `presets`, the 1i small fixes |

Each finding came with a reproduction (a failing test or a command with its real output). The
lead ran the reproduction of every blocker and major again on 3cde317 before deciding.

Severities: **blocker**: a wrong output file, a source or user file damaged or removed, a hang,
a crash on valid input, a power action reachable from a test, a security hole. **Major**: a
"Done when" line not met, a broken contract or `CLAUDE.md` rule, a wrong result the user sees.
**Minor**: the rest.

## Decision

Every blocker and major is fixed; each minor that is cheap is fixed too. One fix agent per
group of steps; every fix has a test that fails before it and passes after it, and a dated
"Follow-up (core-complete review, 2026-10-16)" section in its step's decision record.

### Findings

`file:line` is on 3cde317. "Group" names the fix agent: **A** C-12 selection stage (0031), **B**
C-12 batch engine and C-15 `reframe batch` / `plan` (0040, 0038), **C** C-10 (0032, 0033),
**D** C-13 / C-11 / C-3 (0034, 0016, 0007), **E** C-6 / C-8 / C-15 `tools` / `presets` (0035,
0014, 0038). Duplicates were merged: R2-8 into R1-5 (the same stale feature row); R1-4 and R2-5
(both at `jobs.py:334`) go to one agent.

**Blockers (4)** — the first three reproduced by the lead on 3cde317, the fourth measured by fix agent D:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-1 | C-12 | `batch/selection.py:386` | "No listed language found" counts commentary / description tracks: a listed language with only an extra track never triggers `no_match`, and with `commentary="drop"` the draft has **no audio track and no issue** (the encode writes a file without audio). Reproduced: French film + English audio description, *H.265 MKV 1080p*, preferred audio `en` → `audio outputs: []`, `issues: []` | Fix (A): count main tracks only; 0031 §3 corrected |
| R2-1 | C-15 | `cli.py` `run_batch`, `batch/service.py` `_collisions` | Name collisions are checked per group only. With the collision setting *overwrite*, a job of one group **overwrites a source file of another group of the same run**; two outputs with one name lose the first. Reproduced: E01 of `anime-s01` and `multitrack.mkv` copied as `Anime.Show.S01E01.Pilot.mkv` → the second source's SHA-256 changed | Fix (B): the batch-level checks run over every group; `reframe encode` of several files checked for the same hole |
| R5-1 | C-6 / C-15 | `command/video.py:155-167`, `validation/dryrun.py:449`, `cli.py` plan | Custom parameters that make the encoder write a file (x265 `analysis-save`, `csv`; FFmpeg's `vstats_file` through the own-option path) pass validation, and `reframe plan` dry-runs every user preset with custom parameters: importing a shared preset and only **planning** with it overwrites any file the user can write. Reproduced: `victim.txt` became a 5984-byte x265 analysis file | Fix (E): a validation error for keys that name files, the dry run refuses them and runs in a temporary working folder |
| R4-7 | C-13 / C-11 | `queue/runner.py` (`run_streaming(cancel=…)` of the in-place step) | Found while checking a suspected item of R4: Reframe's own cancel, `close()` and the 5-minute step limit kill mkvpropedit while it edits the source in place. A kill late in the edit (after mkvpropedit voided the old `Tracks`, before the new one and its `SeekHead` entry were written) **destroyed the source's track headers in 3 of 900 runs** (ffprobe shows no streams); random kills (150 runs) had hit only the time before the first write | Fix (D, second round): a running in-place edit is never killed by a cancel or `close()`; the job's end state says whether the edit was written |

**Majors (12)** — all reproduced by the lead on 3cde317:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-2 | C-12 | `batch/explain.py:211` | `no_match="none"` with `other_languages` keep: tracks are taken, but the error `defaults.no_listed_language` keeps the job out of the queue | Fix (A) |
| R1-3 | C-12 | `batch/explain.py:138, 471, 497` | The default audio track, the foreign-audio burn-in target and the default subtitle track can be a kept commentary track (a commentary subtitle is burned in) | Fix (A) |
| R2-2 | C-12 | `batch/descriptors.py:220`, `derive.py:144`, `selectors.py:151` | Heuristic roles (event share, bit rate) are in fingerprints and derived selectors: one release splits, a derived rule is ✗ in the next episode | Fix (B): only flag / title evidence |
| R3-1 | C-10 | `analysis/bitrate.py:205`, `subtitles.py:391`, `service.py` `store` | Two scans of one file at once: the second store discards the first one's measured value | Fix (C) |
| R3-2 | C-10 | `analysis/subtitles.py:255-261` | MP4 `mov_text`: FFmpeg writes an empty sample for every gap, so the event count is about doubled (3 cues → 6) | Fix (C) |
| R4-1 | C-11 / C-13 | `queue/service.py:131-162` | The queue's job keys do not resolve links: an encode reads a source through a link while it is edited in place, two edits of one file run at once (20 of 100 real runs lost an edit), two outputs through a linked folder | Fix (D): keys on file identity |
| R4-2 | C-13 | `probe/matroska.py:275-281, 210-212` | A SeekHead position ≥ 2^63 raises `ValueError` out of `Reframe.sources.probe` ("unexpected error"); ffprobe reads the file | Fix (D) |
| R4-3 | C-13 / C-3 | `probe/prober.py:436-439, 484-487` | With MediaInfo, `language_ietf` holds MediaInfo's derived tag for tracks that have no `LanguageIETF` element (the lead saw it in demo 3: `en` where `mkvmerge -J` and `mkvinfo` show none). The re-probe check is not fooled | Fix (D): the Matroska reader's value wins, also `None` |
| R4-4 | C-13 | `probe/prober.py:484-487` | An invalid `LanguageIETF` in the file is stored unchecked; `reframe plan` then crashes with a `ValidationError` (reproduced) | Fix (D): only valid tags, else a probe warning |
| R5-2 | C-15 / C-6 | `jobs.py:485-487`, `cli.py:1220-1225` | `plan(dry_run=True)` drops the dry run's warnings (`dry_run_skipped`, `dry_run_warning`) and `reframe plan` says the parameters were checked when they were not | Fix (B) |
| R5-3 | C-6 | `validation/dryrun.py:186-206` | libvpx refuses a value through a codec control (`Failed to set VP8E_SET_ARNR_MAXFRAMES codec control`), FFmpeg exits 0: the dry run passes (reproduced with the pinned n9.0.2) | Fix (E) |
| R5-4 | C-8 | `validation/levels.py:50-52, 96-99` | `encoder.level_too_low` pads by preset, not by the `min-cu-size` option: validation passes a job x265 refuses and refuses one it accepts (checked with x265) | Fix (E) |

**Minors (22)**:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-4 | C-12 / C-15 | `jobs.py:334` | A codec the container cannot hold is reported twice in a draft | Fix (B) |
| R1-5 | docs | `status.md` C-12 row and feature row, 0031 | Stale "Open" / "Missing" text (also R2-8) | Fix (A, B) |
| R1-6 | C-12 / C-3 | `batch/explain.py:327-335`, `probe/roles.py:295` | A subtitle track with 0 events counts as "few events" (forced) | Fix (A) |
| R2-3 | C-12 | `batch/report.py:111-118` | An override that removes a rule shifts the row's cells under the wrong columns | Fix (B) |
| R2-4 | C-12 | `batch/grouping.py:160-172` | The loose level counts a changed track twice | Fix (B) |
| R2-5 | C-15 | `jobs.py:334` | `plan` / `encode` with a group preset drop the `batch.track_relaxed` / `ambiguous` / `skipped` warnings | Fix (B) |
| R2-6 | C-15 | `cli.py`, `batch/report.py:116` | Row labels without the season in a group that spans seasons | Fix (B) |
| R2-7 | C-15 | 0040 §6 | A re-run queues the earlier outputs again as a group of their own; §6 said it does not | Fix (B): outputs of the batch's own files are left out |
| R3-3 | C-10 | `preview/clip.py:165-170` | The clip id ignores the plan's files (renamed chapters give the stale clip) | Fix (C) |
| R3-4 | C-10 | `preview/frames.py:139-147` | A failing output chain loses the source frames too | Fix (C) |
| R3-5 | C-10 | `preview/frames.py:91`, 0033 §3 | The tone mapper (and the cache key) changes when detection ends, on every start (the notes are right) | Doc only (C): waiting for detection would delay the first frames |
| R3-6 | C-10 | `preview/common.py:171-184` | A timestamp ≥ 10^9 s fails with a traceback, not a message | Fix (C) |
| R3-7 | C-10 | `preview/clip.py:195-201` | Two identical clips at once share one temporary file | Fix (C) |
| R3-8 | docs | `testdata/README.md`, 0033 §1 | The cropdetect rounding example and a stale sentence | Fix (C) |
| R4-5 | C-13 | `probe/matroska.py:271-273, 294-309` | SeekHead entries are not bounded (67 MB crafted file: 17.7 s, 663 MB) | Fix (D) |
| R4-6 | C-13 | `tests/metadata/test_metadata_edit_real.py:154` | The demo-3 test does not assert the job type and the time | Fix (D) |
| R5-5 | C-15 | `tools/fetch.py:780-786` | A cancel during discovery after the swap says "Nothing was installed" although it was | Fix (E) |
| R5-6 | C-15 (test) | `tests/tools/test_fetch.py:343-352` | The test asserts step messages that coalescing can drop (the load-sensitive failure of the 2a merge); the progress never goes backwards | Fix (E) |
| R5-7 | C-8 | `validation/video.py:944` | `vbv-maxrate` without `vbv-bufsize` (or the reverse) is dropped by the encoder without a warning | Fix (E) |
| R5-8 | C-6 / C-8 | `validation/video.py:373` | Malformed `master-display` / `max-cll` text is accepted (x265 ignores it, no HDR SEI) | Fix (E) |
| R5-9 | C-15 | `cli.py` presets output | Control characters of imported preset names reach the terminal | Fix (E) |
| R5-10 | docs | `validation/dryrun.py:15` | A reference to a test file that does not exist | Fix (E) |

**Suspected** (no reproduction; each fix agent checks the ones of its area and fixes those that
turn out real and cheap): `batch/metadata.py:35` an invalid `language_ietf` preferred (A); a
hand-picked stream not claimed against relaxed rules, `first_of_language` for a second rule on
one track, an audio rule with subtitle settings shown ✓, `episode_key` on the event loop (B);
the scans do not pass the tool's environment (C, fixed); a cache hit checks only the PNG header,
M2TS PGS segments (C, not checked); stale `.fetch-*` folders after a crash, a slow download
outlasting the cancel wait, the lexical tar link check, no size cap on `presets import`,
dry-run attribution of short keys (E); mkvpropedit killed while it writes the source by
Reframe's own cancel, `close()` or the 5-minute limit — 150 random kills damaged nothing, but
D's kills late in the edit did: it became the blocker R4-7 above.

### Outcome

Every finding is closed: fixed with a test, fixed in the docs, or a known limit. Test paths are
under `packages/reframe/tests/`; each fix test failed before its fix (the agents' follow-up
sections name the exceptions: R4-6 and the guards of R4-7 passed before too). The fix commits
were merged into `core-complete` with `--no-ff`:

| Group | Fix commits | Merge |
|-------|-------------|-------|
| A | ff110e7 | 9956b02 |
| D | 347ff84 (R4-1), fee150b (R4-2 … R4-6) | 6dd7232 |
| D, second round | 870717e (R4-7); 80ef8a0 (the `cancel()` / `close()` docstrings, committed on `core-complete` after the merge) | 2557ed2 |
| C | f3091f5 | df4f19e |
| B | 2d3390f; cac17d5 (the lead's `BatchGrouping.issues` docstring, committed on `core-complete` after the merge) | 09fa76f |
| E | a0529f9, cf894d6, 71640fe | 7f53682 |

| ID | Fix commit | Test(s) | Result |
|----|------------|---------|--------|
| R1-1 | ff110e7 | `batch/test_main_tracks.py`: the 6 R1-1 tests (`test_a_listed_audio_description_is_not_a_listed_language_found`, `test_no_listed_language_counts_main_tracks_only`, `test_the_kept_commentary_comes_after_the_no_match_track`, `test_a_listed_commentary_subtitle_does_not_count_as_found`, `test_take_none_with_only_a_listed_commentary_is_an_error`, and `test_no_listed_language_through_the_facade` through the facade); `batch/test_selection.py::test_a_listed_commentary_does_not_count_as_found` | Fixed: only main tracks count, for audio and subtitles. Known limit (0031): a source whose every audio track is an extra still gets no audio track with `commentary = drop` |
| R1-2 | ff110e7 | `test_main_tracks.py::test_take_none_is_an_error_only_when_no_main_track_is_taken`, `::test_no_listed_language_through_the_facade`; `batch/test_explain.py::test_no_listed_language_take_none_is_an_error_with_fixes` | Fixed |
| R1-3 | ff110e7 | `test_main_tracks.py`: the 4 R1-3 tests (`test_a_kept_commentary_is_never_the_first_language_default_audio`, `test_a_commentary_subtitle_is_never_burned_in_for_foreign_audio`, `test_foreign_audio_burn_in_takes_the_main_subtitle`, `test_a_commentary_subtitle_is_never_the_first_language_default`) | Fixed |
| R1-4 | 2d3390f | `jobs/test_service.py::test_a_codec_the_container_cannot_hold_is_one_issue` | Fixed |
| R1-5 | ff110e7 (0031, the C-12 row), 2d3390f (the C-12 and feature rows) | none (docs) | Fixed |
| R1-6 | ff110e7 | `batch/test_explain.py::test_an_empty_subtitle_track_is_not_the_forced_track`; `probe/test_roles_empty_subtitles.py::test_an_empty_subtitle_track_is_not_forced` (real FFmpeg and mkvpropedit) | Fixed in C-12 and C-3 (0006 follow-up) |
| R2-1 | 2d3390f | `jobs/test_cli_output_names.py`: `test_batch_never_writes_a_file_of_another_group`, `test_batch_two_outputs_with_one_name_in_two_groups`, `test_resolve_batch_checks_every_group`, `test_encode_never_writes_another_file_of_the_command`, `test_encode_two_outputs_with_one_name`, `test_batch_never_overwrites_a_file_named_as_an_output_with_the_real_queue` | Fixed; fixed again in the final review: **RA-1** (the checks compared spellings, not files) |
| R2-2 | 2d3390f | `batch/test_descriptors.py::test_heuristic_roles_neither_split_a_season_nor_break_a_derived_rule`, `::test_descriptor_roles_have_flag_or_title_evidence` | Fixed. Known limit (0040): an untitled, unflagged signs track is told from the full track only by its order |
| R2-3 | 2d3390f | `batch/test_resolve.py::test_an_override_that_changes_the_rule_lists_is_invalid` | Fixed for explicit rules; fixed again in the final review: **RA-3** (the rules the defaults compile to) |
| R2-4 | 2d3390f | `batch/test_grouping.py::test_a_changed_track_counts_once_at_every_level`, `::test_loose_pairs_changed_tracks_by_kind` | Fixed |
| R2-5 | 2d3390f | `jobs/test_cli_output_names.py::test_plan_with_a_group_preset_shows_the_track_rule_warnings` | Fixed |
| R2-6 | 2d3390f | `batch/test_anime_season.py::test_matrix_labels_name_the_season_when_a_group_spans_seasons`; `batch/test_grouping.py::test_episode_labels`; `jobs/test_cli_output_names.py::test_a_group_of_two_seasons_names_the_season` | Fixed (RA-5 of the final review: a file-name label is shown once) |
| R2-7 | 2d3390f, cac17d5 | `jobs/test_cli_output_names.py::test_a_rerun_queues_only_the_episodes_not_done_yet` | Fixed as 0040 §6 says (`batch.already_encoded`); the deviation from the lead's instruction is in 0040 |
| R2-8 | (R1-5) | none | Merged into R1-5 |
| R3-1 | f3091f5 | `analysis/test_analysis_facade.py::test_two_bitrate_scans_keep_both_measurements`, `::test_subtitle_scan_and_bitrate_scan_keep_both`, `::test_concurrent_updates_are_serialised`, `::test_update_after_the_file_changed_stores_nothing` | Fixed (`SourceAccess.update`, added to the contract in c2b71b2) |
| R3-2 | f3091f5 | `test_analysis_facade.py::test_mov_text_event_count` (MP4 and MOV), `::test_mov_text_cues_without_text_are_not_events` | Fixed |
| R3-3 | f3091f5 | `preview/test_clip.py::test_renamed_chapters_give_a_new_clip` | Fixed |
| R3-4 | f3091f5 | `preview/test_frames.py::test_a_bad_custom_filter_keeps_the_source_frames` | Fixed |
| R3-5 | f3091f5 (0033 §3) | none (wording) | Doc only, as decided |
| R3-6 | f3091f5 | `preview/test_common.py::test_a_time_a_frame_key_cannot_hold`, `::test_the_last_time_a_frame_key_holds`; `preview/test_frames.py::test_a_time_far_after_the_end` | Fixed |
| R3-7 | f3091f5 | `preview/test_clip.py::test_two_identical_clips_at_once`, `::test_a_clip_made_meanwhile_by_another_run` | Fixed |
| R3-8 | f3091f5 (`testdata/README.md`, 0033 §1) | `preview/test_cropdetect.py::test_cropdetect_rounding_example` (tool behaviour) | Fixed |
| R4-1 | 347ff84 | `queue/test_job_keys.py` (8 of its tests: symbolic link, hard link, linked output folder, case, a mocked `os.stat` identity, two runs of the queue with the fake tools) | Fixed; fixed again in the final review: **RB-1** (the keys read the disk on the event loop), **RB-2** (a NUL path broke the scheduler), and `st_ino` 0 |
| R4-2 | fee150b | `probe/test_matroska_limits_and_ietf.py` (`test_a_seek_position_past_2_63_is_skipped_and_the_next_entry_used`, `test_probe_of_a_file_with_a_seek_position_past_2_63` and 3 more); `metadata/test_metadata_unusual_files.py::test_an_in_place_edit_of_a_file_with_a_seek_position_past_2_63_ends_as_data` | Fixed |
| R4-3 | fee150b | `test_matroska_limits_and_ietf.py::test_matched_tracks_get_the_files_value_or_none`, `::test_probe_with_mediainfo_on_keeps_only_the_files_bcp47_tags`, `::test_real_mediainfo_derives_a_bcp47_tag_from_the_legacy_language`; `test_metadata_unusual_files.py::test_with_mediainfo_on_the_reprobe_shows_only_the_files_bcp47_tags` | Fixed; the docstring in 2f43fe9, and RB-6 / RB-7 of the final review |
| R4-4 | fee150b | `test_matroska_limits_and_ietf.py::test_a_value_that_is_not_a_language_tag_is_not_used`, `::test_mediainfo_languages_that_are_too_long_are_not_used`, `::test_probe_of_an_invalid_language_ietf`; `test_metadata_unusual_files.py::test_a_file_with_an_invalid_language_ietf_can_be_drafted_and_planned` | Fixed |
| R4-5 | fee150b | `test_matroska_limits_and_ietf.py`: the 7 bound tests (`test_many_seek_heads_full_of_entries_are_bounded` … `test_a_seek_head_over_its_limit_is_skipped`) | Fixed: a 16 MB `Tracks` of 8 million entries took 14.8 s and 1.75 GB, now 0.011 s |
| R4-6 | fee150b | `metadata/test_metadata_edit_real.py::test_languages_names_and_flags_the_reprobe_shows_them_all` | Fixed (a test gap) |
| R4-7 | 870717e, 80ef8a0 | `queue/test_in_place_stop.py` (8 tests: 6 failed before, 2 guards); `metadata/test_metadata_edit_real.py::test_cancelling_an_in_place_edit_lets_mkvpropedit_finish` | Fixed: 300 random cancels through the real queue, 0 damaged files (before: 2), every end matches its file. Fixed again in the final review: **RB-3** (a late step limit), **RB-4** (an event loop that shuts down), **RB-5** (a paused edit that a stop resumes) |
| R5-1 | a0529f9 | `validation/test_custom_params_rules.py`, `validation/test_custom_params_ffmpeg.py`, `validation/test_dryrun_ffmpeg.py` (the 4 R5-1 tests: `test_a_refused_parameter_never_starts_ffmpeg`, `test_ffmpeg_runs_in_a_temporary_folder_that_is_removed`, `test_a_relative_source_is_given_to_ffmpeg_as_an_absolute_path`, `test_planning_with_a_shared_preset_leaves_the_users_file_alone`), `validation/cases_options.py`, `definitions/test_custom_params.py` | Fixed (`encoder.custom_param_file`, `encoder.custom_param_unknown`; the dry run never starts FFmpeg with them and runs in a temporary folder); fixed again in the final review: **RC-1** (x264 `cqm=<path>`) |
| R5-2 | 2d3390f | `jobs/test_cli_plan_dry_run.py::test_plan_shows_a_skipped_dry_run`, `::test_plan_shows_the_dry_runs_warnings` | Fixed |
| R5-3 | a0529f9 | `test_dryrun_ffmpeg.py::test_a_value_libvpx_refuses_through_a_codec_control_is_an_error`, `::test_a_control_that_names_no_parameter`, `::test_the_real_libvpx_codec_control_refusals` | Fixed |
| R5-4 | a0529f9 | `validation/test_option_values.py::test_x265_level_with_min_cu_size_16_at_medium`, `::test_x265_level_with_min_cu_size_8_at_ultrafast`; `validation/test_levels_ffmpeg.py::test_the_padding_follows_min_cu_size` | Fixed |
| R5-5 | 71640fe | the 3 R5-5 tests: `tools/test_fetch.py::test_a_cancel_after_the_swap_finishes_and_says_so`, `tools/test_fetch_cli.py::test_the_cli_says_what_was_installed_after_an_interrupt`, and the cancel before the swap, now in `tools/test_fetch_cli.py::test_ctrl_c_stops_the_download` | Fixed |
| R5-6 | 71640fe | `tools/test_fetch.py::test_the_fetch_helper_sees_every_step_message` | Fixed (the test helper records every event) |
| R5-7 | a0529f9 | `validation/test_option_values.py::test_vbv_maxrate_without_a_buffer_is_inactive`, `::test_a_vbv_buffer_without_a_maximum_rate`; `validation/test_option_formats_ffmpeg.py::test_vbv_with_the_encoders` | Fixed |
| R5-8 | a0529f9 | `validation/test_option_values.py::test_the_hdr_text_options_are_checked`, `::test_copy_hdr_metadata_writes_valid_text`; `test_option_formats_ffmpeg.py::test_what_the_encoders_write_for_the_hdr_texts`, `::test_svt_av1_never_ends_with_text_after_the_tags` | Fixed; fixed again in the final review: **RC-2** (signs and white space) |
| R5-9 | cf894d6 | `jobs/test_cli_control_characters.py::test_printable_replaces_control_characters`, `::test_names_from_an_imported_file_reach_the_terminal_without_escapes` | Fixed for the preset output; completed in the final review: **RA-2** (the other human lines) |
| R5-10 | a0529f9 | none (references) | Fixed |

The suspected items:

| Item | Group | Fix commit | Test(s) | Result |
|------|-------|------------|---------|--------|
| `batch/metadata.py:35` prefers an invalid `language_ietf` | A | ff110e7 | `batch/test_explain.py::test_an_invalid_language_ietf_falls_back_to_the_language` | Real, fixed |
| A hand-picked stream is not claimed against relaxed rules | B | 2d3390f | `batch/test_rules.py::test_a_hand_pick_counts_as_an_exact_match` | Real, fixed |
| `first_of_language` for a second rule on one track | B | 2d3390f | `batch/test_rules.py::test_a_track_that_two_rules_take_is_the_first_of_its_language_for_both` | Real, fixed |
| An audio rule with subtitle settings shown ✓ | B | 2d3390f | `batch/test_rules.py::test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell` | Real, fixed |
| `episode_key` on the event loop | B | 2d3390f | `jobs/test_cli_output_names.py::test_the_row_order_is_computed_off_the_event_loop` | Real, fixed |
| The scans do not pass the tool's environment | C | f3091f5 | `analysis/test_analysis_tasks.py::test_the_scans_run_their_tools_with_the_tool_environment` | Real, fixed |
| A cache hit checks only the PNG header; M2TS PGS segments | C | none | none | Not checked; listed in `docs/status.md` |
| Stale `.fetch-*` folders after a crash | E | 71640fe | `tools/test_fetch.py::test_a_killed_fetchs_work_folder_is_removed_by_the_next_fetch` | Real, fixed |
| A slow download outlasts the cancel wait | E | 71640fe | `tools/test_fetch.py::test_a_cancel_stops_a_slow_download_at_once` | Real, fixed |
| The lexical tar link check | E | 71640fe | `tools/test_fetch.py::test_a_link_chain_that_leaves_the_build_folder_is_refused`, `::test_a_member_inside_a_linked_folder_is_refused`, `::test_links_inside_the_build_folder_are_kept` | Real, fixed |
| No size cap on `presets import` | E | cf894d6 | `jobs/test_cli_presets.py::test_import_refuses_a_file_larger_than_the_cap`, `::test_import_never_reads_a_device_or_a_fifo`, `::test_import_from_stdin_is_capped` | Real, fixed |
| Dry-run attribution of short keys | E | a0529f9 | `validation/test_dryrun_ffmpeg.py::test_a_warning_goes_to_the_key_it_names_not_to_a_short_key_in_its_text`, `::test_the_real_rd_refine_warning` | Real, fixed |
| mkvpropedit killed by Reframe's own cancel, `close()` or the 5-minute limit | D | 870717e | (R4-7) | Became the blocker R4-7 |

## Final review (2026-10-17)

### Context

The fix rounds above changed many files again (selection, batch, scans, queue keys, the
Matroska reader, the in-place stop path, custom parameters, fetch). Before the merge into
`main`, three fresh reviewers (`xhigh`) on `core-complete` at 5dbf152 reviewed
`git diff 3cde317..core-complete`, the fix rounds only:

| Reviewer | Area |
|----------|------|
| R-A | C-12 / C-15: the batch engine, `reframe batch`, `plan`, `encode` |
| R-B | C-13 / C-11 / C-14 / C-3: the queue, the Matroska reader, in-place edits, with a stress test on the real mkvpropedit |
| R-C | C-6 / C-8 / C-10 / C-15 `tools` |

The lead ran every blocker and major reproduction again. The severities are those of the first
review. One fix agent per reviewer (RA, RB, RC), each with a dated "Follow-up (final review,
2026-10-17)" section in its steps' records (0040, 0038, 0016, 0034, 0007, 0035).

### Findings

Test paths are under `packages/reframe/tests/`; each fix test failed on 5dbf152 (RN's two guards
passed before too).

| ID | Severity | Step | What | Decision | Commit | Test(s) |
|----|----------|------|------|----------|--------|---------|
| RA-1 | blocker | C-15 / C-12 | R2-1's name checks compared spellings (`normcase(abspath(…))`), not files. With *overwrite*, `reframe encode real/E01.mkv link/Anime.Show.S01E01.Pilot.mkv` (`link` → `real`; the second file a user file named as E01's output) replaced the user file (real FFmpeg and queue: its SHA-256 changed); `reframe batch` did the same; `reframe batch real link --dry-run` listed every episode twice | Fix: one key per file, `reframe.jobs.file_key` (the file's identity, `st_dev` and `st_ino`, when it exists; else the path with links resolved, case-folded; it never raises), computed off the event loop; a file given through two spellings is taken once ([0040](0040-batch-engine-and-reframe-batch.md) follow-up) | ef2fdb6 | `jobs/test_cli_file_identity.py`: its 9 tests (among them the reviewer's `test_encode_never_writes_a_source_given_through_a_linked_folder` and `test_batch_never_writes_a_source_given_through_a_linked_folder`, and `test_a_user_file_reached_through_a_link_is_never_overwritten_by_the_real_queue`); `batch/test_file_identity.py`: its 8 tests other than `test_an_override_is_found_through_a_linked_folder` (among them `test_file_key_on_windows_mocked`) |
| RA-2 | minor | C-15 | R5-9 was incomplete: the `Preset:` line of `encode` / `batch`, the differences and labels of group members, the matrix lines, `reframe probe` and `reframe encoders` printed control characters | Fix: every such line goes through `printable` ([0038](0038-cli-tools-presets-and-when-done.md) follow-up) | ef2fdb6 | `jobs/test_cli_control_characters.py::test_preset_line_of_batch_and_encode_has_no_control_characters`, `::test_titles_and_file_names_in_the_batch_output_are_printable`, `::test_reframe_probe_prints_titles_without_control_characters` |
| RA-3 | minor | C-12 | A per-file override of the defaults that changes the rules they compile to put a file's cells under other columns (R2-3 covered explicit rules only) | Fix: such an override is `batch.override_invalid` (`compiled_rules_moved`) | ef2fdb6 | `batch/test_resolve.py::test_an_override_that_changes_the_compiled_rules_is_invalid`, `::test_an_override_inside_the_compiled_rules_is_applied`, `::test_another_number_of_preferred_languages_is_an_invalid_override`; `batch/test_file_identity.py::test_an_override_is_found_through_a_linked_folder` |
| RA-4 | minor | C-15 | `reframe encode` showed C-8's `output.overwrite` ("will be replaced") next to `batch.output_is_source` ("never overwritten") | Fix: `output.overwrite` is left out for that job | ef2fdb6 | `jobs/test_cli_output_names.py::test_encode_does_not_say_will_be_replaced_next_to_never_overwritten`, `::test_encode_keeps_the_overwrite_warning_of_a_file_outside_the_command` |
| RA-5 | minor | C-15 | A group member labelled by its file name showed the name twice | Fix | ef2fdb6 | `jobs/test_cli_output_names.py::test_a_member_labelled_by_its_file_name_shows_the_name_once` |
| RB-1 | major | C-11 | R4-1's keys did file-system calls (`realpath`, `samefile`) on the event loop: with each `stat` of a slow share at 0.3 s, `start()` blocked the loop for 7.5 s | Fix: `files.file_key` is read in a worker thread when a job is added, retried or restored, and kept with the job; `files.same_key` compares without I/O ([0016](0016-queue-and-job-runner.md) follow-up) | e6a8013 | `queue/test_job_keys.py::test_choosing_a_job_never_reads_a_slow_share_on_the_event_loop`, `::test_a_restored_job_gets_its_keys_off_the_event_loop`, `::test_the_keys_are_what_the_rule_compares` |
| RB-2 | major | C-11 | A path with a NUL character: `realpath` raises `ValueError`; after a `retry()`, every `add()`, `start()` and job end raised, and no job started | Fix: no key function raises; such a job fails with `queue.path_unusable` and the queue goes on | e6a8013 | `queue/test_job_keys.py::test_a_nul_in_a_path_fails_its_job_and_the_queue_goes_on`, `::test_a_nul_in_the_source_path_is_a_clean_failure`, `::test_a_restored_job_with_a_nul_in_its_path`, `::test_no_key_function_raises_for_a_path_with_a_nul`, `::test_the_conflict_rule_takes_a_nul_path`, `::test_python_facts_behind_the_rule` |
| RB-3 | minor | C-13 | A late step time limit of an in-place edit ended a finished edit `cancelled` although no cancel was sent (22 of 200 real runs with a short limit) | Fix: the limit cancels only the step; an exit code 0 is a finished edit and is checked ([0034](0034-metadata-edit-in-place.md) follow-up) | e6a8013 | `queue/test_in_place_stop.py::test_a_time_limit_after_the_edit_ended_does_not_cancel_the_job`, `::test_an_exit_0_that_came_with_the_time_limit_is_a_finished_edit`, `::test_a_time_limit_is_never_reported_as_a_cancel` |
| RB-4 | minor | C-13 | An event loop that shuts down (`asyncio.run` after a second Ctrl+C) kills mkvpropedit, and the log said it was let finish | Not prevented; the log and the `interrupted` end say the file may be damaged, so does a restored in-place job that was running; R4-7's item 2 in 0034 corrected | e6a8013 | `queue/test_in_place_stop.py::test_an_event_loop_that_shuts_down_says_the_file_may_be_damaged`, `::test_a_restored_in_place_job_that_was_running_may_be_damaged` |
| RB-5 | minor | C-11 | A paused in-place edit that a cancel or `close()` resumes was shown `paused`, without its sleep inhibit | Fix: shown `running`, the inhibit taken again | e6a8013 | `queue/test_in_place_stop.py::test_a_paused_edit_that_a_stop_resumes_is_shown_running` |
| RB-6 | minor | C-2 / C-3 | The `language_ietf` docstring (and the JSON Schema) left out that MediaInfo's value stays when the reader cannot read or match the tracks | Fix: the docstring and the schema snapshot ([0007](0007-probe-mediainfo-library-and-delay.md) follow-up) | 9c91444 | the `AudioStream`, `SubtitleStream`, `VideoStream` snapshots of `models/test_schema.py` |
| RB-7 | minor | C-3 | The probe cache's parser fingerprint did not cover `matroska.py` | Fix | 9c91444 | `probe/test_cache_fingerprint.py::test_a_change_to_a_reader_changes_the_fingerprint` |
| `st_ino` 0 | suspected (Windows) | C-11 / C-15 | On a volume without file indexes Windows reports `st_ino` 0 for every file, so any two files there were one file | Fix: `st_ino` 0 is no identity; the path decides (the queue's keys and `reframe.jobs.file_key`) | e6a8013, ef2fdb6 | `queue/test_job_keys.py::test_a_zero_file_index_is_no_identity`, `batch/test_file_identity.py::test_file_key_on_windows_mocked` (both mocked) |
| RC-1 | major (the reviewer: blocker) | C-6 / C-15 | x264 reads every `cqm` value as a file name unless it contains `flat` or `jvt`: `cqm=<path>` passed validation, `reframe plan` dry-ran it and `reframe encode` read the file | Fix: `cqm` is an x264 file key with the names `flat` / `jvt`; names are compared as the libraries compare them, never through a `no` prefix ([0035](0035-advanced-option-sets-and-dry-run.md) follow-up). Classified major by the lead: no file is written or damaged, and x264 applies only a file that parses as a CQM matrix | 0b93f2d | `validation/test_custom_params_ffmpeg.py::test_x264_reads_and_applies_the_file_a_cqm_value_names`, `::test_a_value_that_is_a_name_or_a_file_name`; `validation/test_custom_params_cqm.py` (3 tests); `validation/test_custom_params_rules.py`; `definitions/test_custom_params.py` |
| RC-2 | minor | C-6 / C-8 | The HDR text checks refused a leading `+` (x265 and SVT-AV1 accept it) and accepted a no-break space, digits of other scripts and a vertical tab before the text (they do not) | Fix: `+N` and `-0` accepted, other negative numbers refused; C white space, ASCII digits, the text stripped as FFmpeg strips it | 0b93f2d | `validation/test_option_values.py::test_signs_and_spaces_as_the_encoders_read_them`, `validation/test_option_formats_ffmpeg.py::test_signs_and_spaces_with_the_encoders` |
| RN | minor (two, found by fix agent RB outside its files) | C-8 / C-15 | NUL paths outside the queue: `Reframe.jobs.validate` / `plan` showed `validation.rule_failed`, and `Reframe.sources.probe` raised | Fix: `LocalFileSystem` never raises for such a path; a NUL output path is `output.not_writable`, a given NUL source `source.path_unusable`; the dry run is skipped; the probe gives `ProbeError` `not_found` (0016 follow-up "RN") | 11a094f | `validation/test_nul_paths.py`, `test_service_nul_paths.py` |
| RC-3 | minor (found by fix agent RC) | C-6 | x265 4.3 with deblocking off never finishes a small picture (below) | Known limit, not fixed ([0035](0035-advanced-option-sets-and-dry-run.md#follow-up-final-review-2026-10-17)) | none | none |

The merges into `core-complete`: RA (ef2fdb6) 0a78913, RC (0b93f2d) 47792db, RB (e6a8013,
9c91444) 5d82057, RN (11a094f) 4a94c7c.

**RC-3.** x265 4.3 with the deblocking filter off (`no-deblock=1`, `deblock=false`, or a
`deblock` value that x265 cannot read) never finishes a picture narrower than about 256 pixels
(192×108 to 224×126 checked). FFmpeg sits at 0 % CPU and ignores SIGTERM. The lead checked it
in Reframe: the dry run gives the warning `encoder.dry_run_skipped` ("did not finish within
30 s") after 30.0 s; a queued encode fails with "FFmpeg made no progress … (no output, no CPU
use) and was stopped" at the stall limit (600 s by default; 20 s in the lead's reproduction),
and the process is killed. Not cheap to fix: a validation rule needs x265's exact condition.
RC's first note (in 0035 and `testdata/README.md`) blamed the text `deblock=abc`; both notes
are corrected.

### Stress test (R-B, real mkvpropedit)

R-B ran 1080 stop runs of real in-place edits (cancel, cancel-all, close, pause + cancel,
pause + close; early, late and random): 0 damaged files and 0 end states that disagree with
the file. With a short step limit, 22 of 200 runs ended `cancelled` with no cancel sent (RB-3).
After RB's fixes (re-run by RB, recorded in 0034 and `testdata/README.md` "Metadata edit
(C-13)"): 60 late stops of each kind (300 runs), 0 damaged, every end matches its file; the
step limit at 0.3 to 1.3 times mkvpropedit's median run time, 100 runs: 93 `done` after the
check, 7 `failed` "the file may be damaged" (every file intact), 0 `cancelled`.

### The lead's checks

After the last code merge (4a94c7c), the full suite run alone in four chunks: 2673 + 1010 +
2611 + 203 = **6497 passed, 2 skipped**; `needs_gpu` **26 passed**; ruff, format, mypy (Linux
and `--platform win32`) green. After the RA / RC / RB merges (5d82057): 2660 + 1010 + 2604 +
203 = 6477 passed, 2 skipped; `needs_gpu` 26 passed.

### Demos

All 8 demos of [core-breakdown.md](../core-breakdown.md#demos-run-for-real-by-the-lead-after-wave-3-output-in-the-final-report)
pass, run for real on 4a94c7c (the output is in the lead's final report):

1. **M6.1**: the DTS-HD MA bit rate is measured, 2 140 063 b/s, stored as `measured`.
2. **M6.2**: the commentary track has its role, with the evidence "disposition comment".
3. **M6.3/4**: `metadata_edit` in 0.079 s (limit 1 s; repeat runs 0.071–0.074 s); the
   re-probe and `mkvmerge -J` show `hu`, `pt-BR`, the names and the flags.
4. **M6.5**: `explain`: DTS-HD MA → AC-3 320; AC-3 224 passed through; the stereo track
   falls to the next rule; a reason on each row.
5. **M7**: one group, 12 of 12 files, the E05 / E11 warnings; the group saved as a preset;
   the second season 3 of 3 ✓.
6. **M8**: 4K HDR frames at most 0.953 s each (limit 2 s); automatic crop 22/24/0/0, conservative
   0/0/0/0; a 3 s HEVC Main 10 preview clip; a cancelled scan → ffmpeg gone in 0.020 s
   (limit 1 s).
7. **M9 (core part)**: the search "psy" finds psy-rd and psy-rdoq; the HDR10 patch operations
   fill master-display and max-cll; an unknown x265 key → `encoder.custom_param_rejected`,
   exit 1.
8. `reframe tools status`, `reframe presets list`, and an export → import → export round trip
   with an empty diff.

## Consequences

- Every blocker and major has a test that failed on 3cde317 and passes after its fix; every
  blocker and major of the final review has one that failed on 5dbf152.
- What is left (won't fix, a known limit, or a suspected item not checked) is listed in
  `docs/status.md` ("Known limits left from the core-complete reviews").
- With the findings fixed and the demos passing, `core-complete` merges into `main`
  ([0029](0029-core-before-the-ui-milestones.md) item 3).
- The review's repro files stay uncommitted in the reviewers' worktrees, which are removed after
  the merge into `main`; the fix agents turned the useful ones into tests.

## Plan changes

None in this record; the fix agents record plan changes in their steps' records.
