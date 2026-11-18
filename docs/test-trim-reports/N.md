# Test trim, area N: languages and naming

Files: `packages/reframe/tests/test_languages.py` and `packages/reframe/tests/naming/`
(`test_corpus`, `test_template`, `test_resolve`, `test_variables`, `test_source`,
`test_sanitize`, `test_parse`, `test_clean`, `test_guessit_quirks`, `test_value`,
`test_naming_models`). Branch `test-trim-N`. The name `test-trim/N` cannot exist, because the
branch `test-trim` exists.

## Numbers

| | Before | After |
|---|---|---|
| Tests | 769 | 632 (-137, -17.8 %) |
| Wall time, no coverage (2 runs) | 23.7 s / 19.9 s | 18.3 s / 18.3 s |
| Wall time, with `--cov --cov-branch` | 34.4 s | 20.2 s / 31.2 s (noisy machine) |

Per file:

| File | Before | After |
|---|---|---|
| test_languages.py | 233 | 150 |
| naming/test_corpus.py | 150 | 150 |
| naming/test_template.py | 81 | 78 |
| naming/test_resolve.py | 63 | 41 |
| naming/test_variables.py | 58 | 53 |
| naming/test_source.py | 50 | 42 |
| naming/test_sanitize.py | 47 | 43 |
| naming/test_parse.py | 36 | 31 |
| naming/test_clean.py | 25 | 20 |
| naming/test_guessit_quirks.py | 14 | 14 |
| naming/test_value.py | 7 | 7 |
| naming/test_naming_models.py | 5 | 3 |

Most of the remaining time is in the corpus (146 cases, which run again under the two hostile
guessit configs) and in the `needs_ffmpeg` / mkvpropedit tool tests. All of these stay.

## Coverage gate

`uv run pytest <area files> --cov=reframe --cov-branch` before and after, compared with
`covcmp.py`:

```
before 30.450% 627/6918 branches 8147/21896 lines
after 30.450% 627/6918 branches 8147/21896 lines
TOTAL LOST: 0
```

## Deleted tests, by reason

### Table cases that repeat a code path already in the same table or in another table

- `test_bibliographic_and_terminology_pairs`: 20 pairs reduced to 3 (`chi`, `fre`, `ger`).
  All pairs go through the same code. `test_exactly_twenty_codes_differ_between_b_and_t`
  still pins the set of 20, `test_every_iso639_2_code_keeps_its_meaning` checks every /T and
  /B code, and `test_container_codes_round_trip_for_every_entry` checks
  `normalize(legacy(tag))` for every entry.
- `test_normalize`: 52 cases reduced to 24. Removed:
  - plain codes: `de`, `eng`, `jpn`;
  - forms that `test_container_codes` checks through `to_matroska_ietf` (which is
    `normalize(x) or "und"`): `pt-BR`, `es-419`, `zh-Hans`, `sr-Latn`, `yue`, `qaa`, `sgn`,
    `iw`, `in`, `jw`, `mo`, `tl`, `tgl`, `sh`;
  - one of two equal forms: `pt_BR` (`pt_br` stays);
  - names that `test_every_name_in_the_list_normalizes` checks for every entry (also in upper
    case): `German`, `Deutsch`, `Hungarian`, `magyar`, `Magyar`, `Français`,
    `Portuguese (Brazil)`, `Chinese (Simplified)`, `Undetermined`, `Tagalog`.

  Kept: case, `_`, whitespace, extlang, `TGL`, `tgl-PH`, `hbs`, `fil`, `ji`, `scc`, `scr`,
  `cmn`, `tlh`, accent folding (`francais`), and every `Language.find` path (`Cantonese`,
  `Brazilian Portuguese`, `Serbo-Croatian`, `allemand`).
- `test_invalid`: `""` (the same branch as `"   "`), `"123"` and `"en-" + "a" * 70` (shape
  failures that `en--US`, `-en` and `toolongcode-x` already cover).
- `test_container_codes`: `en`, `pt-PT`, `zh-Hant`, `sr-Cyrl`, `en-GB` (the same as `hu`,
  `pt-BR`, `zh-Hans`, `sr-Latn`); `cmn`, `swh` (macrolanguage fallback: `yue`, `arb` and
  `zsm` stay); `art` (collective: `sgn` stays).
- `test_names`: `fr`, `ja`, `zh-Hant`, `sr-Latn`, `es-419`. CLDR display data on the same
  path as `hu`, `pt-BR`, `zh-Hans`. `ja` stays in the capitalised-name test.
- `test_search_ranking`: `hu`, `hun`, `Hungarian`, `ger`, `deu`, `zh-Hans`, `und`,
  `Undetermined`, `es-419`. `test_search_finds_every_entry_first` checks the tag, every ISO
  code and the English name of every entry.
- `test_same_language`: `deu`/`German`, `pt-BR`/`pt` (`pt-BR`/`pt-PT` stays), `arb`/`ar`
  (`cmn`/`zh` stays), `en`/`de` (`und`/`en` stays).
- `test_matches`: `pt`/`pt`, `ger`/`de` (`de`/`ger` stays), `sr-Latn`/`sr` (the script check:
  `zh-Hans`/`zh-Hant` stays), `und`/`und`, `en`/`x?` (an invalid track: `en`/`None` stays),
  `None`/`en` (an invalid rule: `garbage!`/`en` stays).
- `test_number_overrides_take_only_ascii_digits` (naming): the 11 values x 3 keys Cartesian
  product is now 11 `(key, value)` pairs. The keys take turns, so each key has 3 or 4 of the
  values. `season`, `episode` and `year` share one code path (`_NUMBER_OVERRIDES`).
- `test_suggestions`: `show` (alias, like `episode_title`) and `resolutoin` (difflib, like
  `maintitle`).
- `test_resolution`: `3840x1600`, `1280x536` (cropped scope: `1920x800` stays), `720x480`
  (the height branch: `640x480` and `720x576` stay).
- `test_audio_channels_label`: `stereo` (a named layout, like `mono` and `quad`), `7.1` (the
  same branch as `5.1(side)`).
- `test_generic_folders`: `Season 3`, `s1`, `cd 2`, `video_ts` (separator and case variants
  of kept cases).
- `test_not_generic`: `The Sopranos` (trivial; `SOPRANOS_DIR` and `Season of the Witch`
  stay).
- `test_split_extension`: `movie.mkv` (`movie.MKV` stays), `00800.m2ts`, `Movie.2016.1080p`
  (an unknown extension, like the Sopranos folder name).
- `test_reserved_names`: `con` (`com9` covers the case), `COM1`, `LPT1` (`COM0`, `com9` and
  `LPT9` are the limits).
- `test_not_reserved`: `Concord` (like `CONSOLE`).
- `test_clean_text`: `.A.Scandal.in.Belgravia` (strip, like `" - Rose "`), `""`.
- `test_detect_separator`: `hacksawridge` (`None`, like `WALL-E`).
- `test_convert_separator`: `.` to `_` (the same as `.` to space), `the-sopranos` (the non-dot
  branch, like `The_Office_US`), `Chernobyl...1.23.45` (numbers, like `12.00.AM-1.00.AM`),
  `Spider-Man...`.
- `test_title_case_is_handbrakes`: `the sopranos` (`THE SOPRANOS` covers the lower-casing as
  well).

### Property tests that an exhaustive test in the same file includes

- `test_property_container_codes_round_trip`: `test_container_codes_round_trip_for_every_entry`
  checks every entry. The extra assertion `(iso639_2b, iso639_2t) == (legacy, mp4)` is a
  tautology of `_make_entry`.
- `test_property_search_finds_entry_first`: the same assertion as
  `test_search_finds_every_entry_first`, on a sample.

### Duplicate tests

- `test_search_entries_include_display_data`: `search("hu")[0]` fields. Entry fields are
  pinned by `test_language_entry_fields`.
- `test_render_with_a_bad_spec_uses_the_default_format`: the `except ValueError` fallback of
  `render`. `test_a_huge_width_or_precision_is_an_issue` also checks the rendered fallback.
- `test_naming_ignores_guessit_user_config` (2 cases): the same regression (0012 follow-up) is
  checked by `test_corpus_ignores_guessit_user_config`. That test is the one status.md names,
  and it runs every corpus case, Sopranos and Hacksaw Ridge included, under the same hostile
  configs. `test_guessit_reads_user_config_files_without_the_option` also checks
  `GUESSIT_OPTIONS`.
- `test_name_result_round_trip` (naming models): a pydantic round trip of a hand-built
  `NameResult`. `test_resolve.test_result_round_trips` round-trips a real one, and
  `tests/models/test_roundtrip.py` round-trips every public model.
- `test_variables_are_models`: `isinstance` and a round trip of `NamingVariable` (mypy and
  `tests/models` cover these).

## Mutation checks

Each mutation was run against the remaining area tests (`-m "not needs_ffmpeg"`). The
production code was reverted after each run, and `git status` showed no change in `src/`.

| Mutation | Guards the deletion of | Failing remaining test |
|---|---|---|
| `render`: `except ValueError` → `except KeyError` | render bad-spec test | `test_a_huge_width_or_precision_is_an_issue[season-1e12]` |
| number override checked only for `season` | override Cartesian product | `test_bad_field_overrides` (and the paired `episode`/`year` cases) |
| float values skip `_check_spec_size` | (dropping `quality_bitrate` from the huge-width test) | **none at first: restored** `quality_bitrate`; then `test_a_huge_width_or_precision_is_an_issue[quality_bitrate-1e12]` |
| `no_user_config: False` | `test_naming_ignores_guessit_user_config` | `test_corpus_ignores_guessit_user_config[type-movie]` |
| `same_language` without `prefer_macrolanguage` | `arb`/`ar` | `test_same_language[cmn-zh-True]` |
| `matches` without the script check | `sr-Latn`/`sr` | `test_matches[zh-Hans-zh-Hant-False]` |
| `validate`: only `None` is "no language" | `""` in `test_invalid` | `test_invalid[   -No language given]` |
| `Language.get(text, normalize=False)` (no CLDR) | deprecated codes in `test_normalize` | `test_bibliographic_and_terminology_pairs[chi-zho-zh]` (first failure; `-x`) |
| `split_extension` case-sensitive | `movie.mkv` | `test_split_extension[movie.MKV-movie-mkv]` |
| regex `specials?` → `specials` | `Special` | **none at first: restored** `Special` and `Extras`; then `test_generic_folders[Special]` |
| `convert_separator`: non-dot branch only for space | `the-sopranos`, `The_Office_US` | **none at first: restored** `The_Office_US`; then `test_convert_separator[The_Office_US-…]` |
| `is_reserved` without `.upper()` | `con` | `test_reserved_names[com9]` |
| no macrolanguage fallback in `_iso639_2` | `cmn`, `swh` | `test_container_codes[yue-chi-zho-yue]` |
| `resolution_label`: width test only | `720x480` and others | `test_resolution[size4-1080p]` |
| `title_case` without `.lower()` | `the sopranos` | `test_title_case_is_handbrakes[THE SOPRANOS-…]` |
| search without the ISO-code rank | `hun`, `ger`, `deu` | `test_search_ranking[pt-first4]` |

These mutations survive the remaining tests and also the **original** suite (checked against
the `test-trim` versions of the files), so the trim lost nothing here:

- `_looks_like_name` without the 100-character limit (`Language.find` fails on `"G" * 101`
  anyway).
- `audio_channels_label` without the dotted-layout branch (the channel count gives the same
  label).
- `normalize` passes the unstripped value to the name lookup.
- `search` without the exact-native-name rank (the prefix rank still puts the entry first).

## Uncertain, kept

- `test_property_normalize_variants_of_an_entry`: mostly covered by the exhaustive
  every-entry tests, but it is the only test of upper-case and `_` forms of every tag. (Q-7.11
  replaced it with a loop over every entry and form in
  `test_languages.py::test_container_codes_round_trip_for_every_entry`.)
- `test_any_field_overrides_round_trip`: a generic pydantic round trip, but of a persisted
  job document.
- `test_hb_encoder` (7 cases): HandBrake key data per encoder family. It is the only test of
  these keys.
- `test_forbidden_characters` (10 cases): one case per Windows replacement. Windows rules are
  a C-16 "Done when" item.
- `test_a_huge_width_or_precision_is_an_issue` (39 cases): a regression test. Its variable
  dimension is not independent (see the float mutation above), so it stays whole.
- The `needs_ffmpeg` / mkvpropedit tests, `test_guessit_quirks.py`, the corpus,
  `test_examples_of_03`, the M2 demo tests, the 0012 follow-up regression tests and every
  HandBrake-variable test: kept by rule.

## Unused fixtures

None. `naming/conftest.py` fixtures (`fake_fs`, `empty_fs`, `now`, `guessit_user_config`) are
all still used.
