# Test trim, area P (probe/ and definitions/)

Branch `test-trim-P`. `test-trim/P` was not possible: the branch `test-trim` exists, so git
cannot create a ref under `refs/heads/test-trim/`.

## Numbers

| | Before | After |
|---|---|---|
| Tests (the 23 files of the area) | 794 (793 passed, 1 skipped) | 766 (765 passed, 1 skipped) |
| Removed | | 28 (3.5 %) |
| Wall time (pytest with `--cov --cov-branch`) | 82 s | 65 s and 117 s (two runs) |

The wall times are not a fair comparison. Other agents shared the machine, so the same run took
65 s once and 117 s the next time. The deleted tests are all fast. The only slow one was
`test_json_loads_raises_recursion_error_far_beyond_the_limit` (200 000 levels of JSON).

The area is already lean, so little was deleted. Most of its tests are one of these:

- real-tool tests (`test_tools.py`, `test_options_values.py`, `test_live.py`, `test_matroska.py`)
- recorded-probe and snapshot tests
- fault-injection tests (`test_prober.py`, `test_folder.py`)
- data tables where each row is one map entry or one keyword (`test_names.py`, `test_roles.py`)

All of those were kept.

## Coverage gate

```
before 37.187% 1332/6918 branches 9383/21896 lines
after 37.187% 1332/6918 branches 9383/21896 lines
TOTAL LOST: 0
```

## Deleted tests

### Same branch as a row that stays

- `probe/test_names.py::test_audio_names[pcm_s24le]` and `[pcm_dvd]`: the same `pcm_` prefix
  branch as `pcm_s16le` and `pcm_bluray`.
- `probe/test_parse.py::test_parse_rational[abc]`: the same `len(parts) != 2` branch as
  `1/2/3`.
- `probe/test_bitrate.py::test_stream_bitrate[{"bit_rate": "N/A"}]`: the same path as `{}` and
  `positive_int("x")`. The README notes that ffprobe JSON has no `"N/A"` bit rate.
- `probe/test_bitrate.py::test_parse_duration_tag[""]`: the same `not value` branch as `None`.
- `probe/test_cache.py::test_corrupt_entry_is_ignored_and_rewritten["\x00\x01"]`: the same
  JSON-decode branch as `{not json`.
- `probe/test_cache.py::test_corrupt_entry_is_ignored_and_rewritten[{"format": 99, "parser": 1}]`:
  the same as `{"format": 1}`.
- `probe/test_cache_nesting.py::test_a_deep_entry_is_a_miss_and_is_rewritten[1000]`: the same
  `too_deep` branch as 65 and 300 (300 stays for its Pydantic note, 200 000 for `RecursionError`).
- `probe/test_mediainfo.py::test_an_ascii_stream_order_is_matched[3]`: the same as `0`, `12`
  and `007`.
- `probe/test_prober.py::test_garbage_output['{"streams": [']`: the same `JSONDecodeError` path
  and message as `this is not json`.
- `definitions/test_snap.py::test_snap_mixdown`, five rows:
  - `aac stereo 6`: the same branch as `aac 5.1 8`
  - `libmp3lame 7.1 8`: the same as `libmp3lame 5.1 6`
  - `aac dpl2 1`: the upmix branch, already taken by `aac 5.1 2`; the dpl2 boundary stays
    as `aac dpl2 2`
  - `ac3 None 3` and `flac None 8`: the same keep branch as `ac3 None 6` and `aac None 8`
- `definitions/test_snap.py::test_snap_samplerate`, two rows:
  - `libmp3lame 96000`: the same as `ac3 96000`
  - `libopus None 22050`: the same as `libopus None 44100`
- `definitions/test_snap.py::test_channels_mixdown[8]`: the same branch as 7.

### Exact duplicates

- `probe/test_roles.py::test_audio_title_keywords[Kommentar]`: the same input and assertion as
  `test_german_compounds_and_described[Kommentar]`.
- `probe/test_cache.py::test_entry_of_another_parser_source_is_a_miss`: the same code path as
  `test_another_parser_version_is_a_miss` (both patch `parser_fingerprint`, and both expect a
  miss).
- `probe/test_mediainfo.py::test_a_stream_order_that_is_not_ascii_digits_is_not_matched[0-1]`
  and `test_a_bit_rate_is_read_from_ascii_digits[2104000 / 1509000]`: both cases are rows of
  `probe/test_bitrate.py::test_track_data`.

### Tests of Python, not of Reframe

- `probe/test_mediainfo.py::test_python_facts`: it asserts what `str.isdigit`, `int` and `re`'s
  `\d` accept. The regression tests that stay check Reframe's own `[0-9]+` match against those
  characters.
- `probe/test_cache_nesting.py::test_json_loads_raises_recursion_error_far_beyond_the_limit`: it
  asserts that `json.loads` raises `RecursionError`. The 200 000-level case of
  `test_a_deep_entry_is_a_miss_and_is_rewritten` runs the code that catches it.

### Contained in another test

- `definitions/test_lint.py::test_every_fallback_chain_ends_in_software`: each of its asserts is
  also in `definitions/test_contract.py::test_fallback_chains_name_known_encoders_and_end_in_software`,
  and the linter's clean-data test (the "Done when" test) checks it again.

### Getters, caching, constants

- `definitions/test_models.py::test_video_encoder_option_lookup`: a trivial `next(...)`
  getter, used by `effective_option` and `hdr_options` tests.
- `definitions/test_quality_support_loader.py::test_load_definitions_is_cached`: it only checks
  that `@cache` is there, which is an implementation detail.
- `definitions/test_contract.py::test_audio_encoders_have_labels`: constants (`label == "AC-3"`).
  The `snap`, `lint` and tool tests use every one of these encoders by id.

## Mutation checks

Each mutation was run against the remaining tests of the area, except the two real-encode
files, `test_tools.py` and `test_options_values.py`. Each file was reverted with
`git checkout`, and after every run `git status` showed no change in `packages/reframe/src`.

| # | Mutation (guarded by a deleted test) | Result: the remaining test that failed |
|---|---|---|
| 0 | `pcm_` prefix narrowed to `pcm_s` (pcm_dvd, pcm_s24le) | `test_audio_names[pcm_bluray]` |
| 1 | `kommentar` no longer a substring (Kommentar row) | `test_german_compounds_and_described[Audiokommentar]` |
| 2 | `parse_rational` part-count check removed (`abc`) | `test_parse_rational[1/2/3]` |
| 3 | only `yuv420p` is 8-bit (the `nv12` row) | **survived**: the `nv12` row was restored; with it the mutation is caught |
| 4 | `positive_int` does not catch `ValueError` (`N/A`) | `test_stream_bitrate[stream8]` |
| 5 | cache `_read` catches `OSError` only (`\x00\x01`) | `test_corrupt_entry_is_ignored_and_rewritten[{not json]` |
| 6 | parser fingerprint not compared (parser-source miss) | `test_another_parser_version_is_a_miss` |
| 7 | `too_deep` check removed from `_read` (1000 levels) | `test_a_deep_entry_is_a_miss_and_is_rewritten[65]` |
| 8 | `except RecursionError` removed (stdlib json test) | `test_a_deep_entry_is_a_miss_and_is_rewritten[200000]` |
| 9 | stream order `[0-9]+` → `\d+` (`test_python_facts`) | `test_a_stream_order_that_is_not_ascii_digits_is_not_matched[٣]` |
| 10 | `fullmatch` → `match` (`0-1` param) | `test_bitrate.py::test_track_data` |
| 11 | dpl2 `<=` → `<` (`aac dpl2 1`) | `test_snap_mixdown[aac-dpl2-2-None]` |
| 12 | keep layout only when source == max (`ac3 None 3`, `flac None 8`) | `test_snap_mixdown[aac-5.1-2-None]` |
| 13 | `snap_samplerate` returns the max rate (two rows) | `test_snap_samplerate[ac3-None-22050-32000]` |
| 14 | `option()` returns the first option for an unknown key | `test_options_search_hdr.py::test_option_defaults_and_context` |
| 15 | data: `hevc_nvenc` fallback ends in hardware (lint fallback test) | `test_lint.py::test_the_packaged_definitions_are_clean` |

Not mutation-checked, because no remaining test can or should catch it:

- Removing `@cache` from `load_definitions` (`test_load_definitions_is_cached`) makes tests
  slower, and nothing fails.
- Changing the `ac3` label (`test_audio_encoders_have_labels`): the labels are display data.

## Uncertain, kept

- `definitions/test_contract.py::test_loader_reads_the_packaged_encoders`: constants of libx265
  (codec, `handbrake_key`, the 10-bit `pix_fmt`). Kept as the M2 contract smoke test.
- `definitions/test_models.py::test_passthru_and_mixdowns`: mostly data assertions that C-12
  relies on.
- `probe/test_cache.py::test_invalidation[path]`: the same "different entry file" path as the
  size and mtime cases. Kept because the cache key (path + size + mtime) is the C-3 spec.
- `probe/test_names.py` container rows `a.MTS` / `a.m2ts` and subtitle rows `subrip` / `srt`:
  each row is its own map entry.
- `probe/test_mediainfo.py` stream-order rows `" 1"`, `"1 "`, `"1\n"`, `"+1"`, `"-1"`: each one
  guards a different wrong implementation (strip, `int()`, `$` against `\Z`). They are from an
  M2 review fix.
- `definitions/test_lint.py::test_every_option_has_help_and_a_mapping`: the linter test also
  checks this, but this test states the "Done when" criterion directly.

## Unused fixtures

None. No fixture or helper in `conftest.py` or `testing/` lost its last user. In
`test_cache_nesting.py`, `PARSER_DEPTH` is still used.
