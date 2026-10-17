# Test trim, area B (C-12 audio and subtitle defaults)

Files: `packages/reframe/tests/batch/` `test_audio_rules.py`, `test_lint.py`,
`test_selection.py`, `test_explain.py`, `test_draft.py`, `test_selection_properties.py`,
`test_explain_media.py`.

Branch: `test-trim-B`. (The name `test-trim/B` is not possible: the branch `test-trim` exists,
and git cannot have both `refs/heads/test-trim` and `refs/heads/test-trim/B`.)

## Numbers

| | Before | After |
|---|---|---|
| Tests | 582 | 476 (-106, -18 %) |
| Wall time (pytest, no coverage) | 8.9 s | 8.3 s |
| Wall time (with branch coverage) | 17.8 s | 9.5 s |

Per file: `test_audio_rules.py` 419 → 321, `test_lint.py` 57 → 56, `test_selection.py` 53 → 49,
`test_explain.py` 45 → 43, `test_draft.py` 6 → 5, `test_selection_properties.py` 1 → 1,
`test_explain_media.py` 1 → 1.

Most of the run time is the hypothesis test `test_defaults_properties` (about 5 s, kept as it
is). The time with coverage changes a lot from run to run.

## Coverage gate

The first "after" run lost one branch: `languages.py` line 677, the script check of
`matches`. Only the `(["zh-Hant"], "chi", "zh-Hans", False)` case of `test_language_identity`
covered it, so I put that case back. After that, two runs:

```
before 37.822% 1180/6918 branches 9720/21901 lines
after 37.958% 1187/6918 branches 9752/21901 lines
TOTAL LOST: 0

before 37.822% 1180/6918 branches 9720/21901 lines
after 37.833% 1180/6918 branches 9723/21901 lines
TOTAL LOST: 0
```

The "after" numbers are higher than "before" because the hypothesis test does not cover the
same lines in every run.

## Deleted tests and cases

### Repeated factor in a Cartesian product

- `test_audio_rules.py::test_the_output_agrees_with_the_shared_helpers`: encoders × channels ×
  mixdowns was 7 × 7 × 6 = 294 cases. It now uses one encoder of each kind, 5 × 7 × 6 = 210.
  `eac3` has the same mixdowns, sample rates and bit-rate table keys as `ac3`, and
  `libfdk_aac` has the same as `aac`. The test compares the output with the shared helpers'
  answer, so the table values do not matter, only their shape. No code in `planned_audio` or
  `audio_rules` treats them differently (`DRC_CODECS` applies only with DRC, which this test
  does not set). I kept all the channel counts (0, 1, 2, 3, 6, 7, 8) and all the mixdowns:
  each one is on a different side of a layout boundary. (-84)

### Parametrized cases that test no new branch

- `test_requested_mixdown`: `("keep", 2)` (keep returns `None` before it looks at the
  channels; `("keep", 8)` and `("keep", 0)` stay), `("up_to_5.1", 7)` (the same `>` branch as
  `("up_to_5.1", 8)`), `("5.1", 2)` (the same "fewer channels" branch as `("5.1", 5)`). (-3)
- `test_channels_match`: `("any", 8)` (`any` returns before the channels; `("any", 0)` stays),
  `("stereo_or_less", 1)` (the boundary `2` and the value just outside it, `3`, stay),
  `("5.1_or_more", 8)` (boundary `6` and `5` stay), `("5.1_or_more", 0)` (the same guard as
  `("mono", 0)`). (-4)
- `test_passthru_codec`: `("vorbis", None)` and `("alac", None)` (the same "no matching
  codec" path as `pcm_s24le`; the reason "Vorbis cannot be passed through" is still checked in
  `test_max_bitrate_rules`). Every DTS profile case stays: those cases record ffprobe's
  profile names. (-2)
- `test_language_matches`: `(["hun"], "hun")` (exact match; `(["hu"], "hun")` is the stronger
  case). (-1)
- `test_no_max_is_the_default_for_a_lossless_source`: the `FLAC 133.7` case (the boundary
  case `160 ≤ 160 (the default)` stays, and so does the 5.1 TrueHD case, which uses a
  different bit-rate table). (-1)
- `test_the_source_sample_rate_snaps_to_the_encoder`: `("libopus", 48000)` (the same "the
  encoder takes the rate" branch as `("aac", 44100)`), `("libopus", 22050)` (the same snap
  branch as `("libopus", 44100)`; the AC-3 22050 case, which records the FFmpeg failure,
  stays). (-2)
- `test_lint.py::test_shadowed`: `(["hu"] mono, ["en"] mono, False)` (the language-mismatch
  outcome; `["en"]` vs `["hu", "en"]` tests the stronger "all of the later languages" rule).
  (-1)
- `test_selection.py::test_language_identity`: `(["hun"], "hu")` (the same listed-language
  normalisation as `(["ger"], "de")`), `(["pt"], "por", None)` (the base-language case;
  `(["pt"], "por", "pt-BR")` stays), `(["en"], "eng")` (the same as `(["de"], "ger")`).
  `reframe.languages.matches` has its own table in `tests/test_languages.py::test_matches`.
  (-3)
- `test_selection.py::test_subtitle_selection`: `{"tracks_per_language": "none"}` (the same
  `select_tracks` branch as `test_tracks_per_language[none]`, which runs for audio). (-1)
- `test_explain.py::test_subtitle_default_track`: `(["de", "en"], "forced", 3)` (the
  `forced` policy does not read the languages; `(["hu", "en"], "forced", 3)` stays). (-1)

### Tests that other tests already cover

- `test_audio_rules.py::test_default_definitions_are_loaded`: `test_draft.py::test_multitrack`
  covers the default codec rules with `definitions=None` (with an exact reason). The second
  part only compared one call with the same call with `definitions=DEFS`. (-1)
- `test_explain.py::test_every_decision_has_a_kind`: `test_defaults_properties` checks the
  kind of every decision. `test_dropped_tracks_have_a_reason_and_no_output`,
  `test_example_of_03_row_by_row_through_draft_and_explain` and
  `test_foreign_audio_search_finds_the_forced_track` check it for audio and subtitles. (-1)
- `test_draft.py::test_empty_source`: `test_defaults_properties` draws sources with 0 audio
  and 0 subtitle tracks and checks that there are no decisions and no outputs. The empty
  selection is also checked in `test_selection.py::test_no_tracks`. (-1)

## Mutation checks

For each check: one change to production code, then a run of the remaining tests of
`packages/reframe/tests/batch/`, then the change reverted. `git status` showed no change to
production code before the commit.

| Mutation | Result: first failing test |
|---|---|
| `channels_match`: `channels <= 2` → `< 2` | caught: `test_example_of_03_row_by_row[eng AC-3 2.0 192]` |
| `channels_match`: `channels >= 6` → `> 6` | caught: `test_example_of_03_row_by_row[hun DTS-HD MA 5.1]` |
| `channels_match`: unknown-channels guard removed | **survived; it also survives with the original tests** (gap) |
| `requested_mixdown`: `source_channels > channels` → `>=` | caught: `test_requested_mixdown` |
| `requested_mixdown`: `keep` returns a layout for a known count | caught: `test_requested_mixdown[keep-0-None]` |
| `passthru_codec`: an unknown codec returns `"aac"` | caught: `test_passthru_codec` (pcm case) |
| `_samplerate`: a rate the encoder lacks is not snapped | caught: `test_sample_rate_snaps_to_the_encoder` |
| `_bitrate_state`: `value > max` → `>=` | caught: `test_no_max_is_the_default_for_a_lossless_source` (160 boundary) |
| `_output_mixdown`: the encoder's layouts are ignored | caught: `test_mixdown_in_the_output` |
| `language_matches`: string compare instead of `languages.matches` | caught: `test_language_matches[rule4-por-pt-BR-True]` |
| `rule_covers`: `all(` → `any(` | caught: `test_shadowed[earlier5-later5-False]` |
| `rule_covers`: the languages are ignored | caught: `test_example_of_03_row_by_row_through_draft_and_explain` |
| `effective_languages`: no normalisation | caught: `test_languages_from_settings` |
| Subtitle default `forced` with no forced track: first copy | **survived; it also survives with the original tests and `tests/integration`** (gap) |
| Default codec rule max 256 → 320 | caught: `test_multitrack` |
| Dropped subtitle decisions get `kind="audio"` | caught: `test_defaults_properties` |
| Keep-everything subtitle decisions get `kind="audio"` | caught: `test_defaults_properties` |

The two gaps were there before the trim, and none of the deleted cases would catch them.
`channels_match("stereo_or_less", 0)` would catch the first, and a `forced` subtitle policy on
a source with no forced track would catch the second. I added no tests, because the task was
to trim.

## Uncertain, kept

- `test_audio_rules.py::test_never_bigger_than_the_source`: its first half repeats the
  `fits, lossless at or below the max` row of `test_max_bitrate_rules`. Its second half (a
  free-range encoder rounds 128.453 up to 129) is checked nowhere else, so I kept the whole
  test.
- `test_the_output_agrees_with_the_shared_helpers`: channel counts 3 and 7 are "between"
  layouts. They are on different sides of the 5.1 boundary, so I kept both.
- `test_lint.py::test_builtin_presets_are_clean` (26 cases):
  `tests/integration/test_builtin_presets_validate.py` runs the same presets through
  `validate_template` (which includes `lint_defaults`), but it fails only on errors. This test
  also fails on lint warnings and info notes.
- The six evidence cases of `test_foreign_audio_search_finds_the_forced_track` and the seven
  cases of `test_burn_in`: each one tests a different evidence rank or burn-in branch.
- `test_m6_demo_item_5` and `test_m6_demo_item_5_through_the_facade`: both are demo
  criteria; the second runs through the `Reframe` facade with the Settings languages.
- The removed `kind` and empty-source checks now depend on the hypothesis test, which is
  random. Dropped subtitle tracks and empty sources occur in almost every run of 300
  examples, but no fixed test is left for them.

## Unused fixtures and helpers

None. `defaults_tracks.py` (a helper module, not my file) is still used by every file that
used it before.
