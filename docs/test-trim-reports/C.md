# Test trim report: area C

Branch `test-trim-C`. The name `test-trim/C` cannot be used because a branch `test-trim`
exists, and git cannot make `refs/heads/test-trim/C` next to it.

Files: `packages/reframe/tests/{presets/test_builtin,presets/test_store,presets/test_diff,
command/test_tracks,command/test_snapshots,command/test_filtergraph,command/test_integration,
command/test_metadata_edit,command/test_quoting,command/test_video,command/test_builder,
dimensions/test_source,dimensions/test_geometry,dimensions/test_ffmpeg,dimensions/test_crop,
dimensions/test_properties}.py`

## Numbers

| | before | after |
|---|---|---|
| tests | 724 | 694 (-30, -4 %) |
| wall time (pytest, with branch coverage) | 72.3 s | 40.5 s |

The wall times are not a fair comparison. Other agents shared the machine, and the same tree
gave 62 s and 40 s in two runs. All 30 deleted tests are pure unit tests that run in
milliseconds, so the real time saving is very small. Nearly all of the time is in the real-FFmpeg
integration tests, the hypothesis properties and the snapshots, which this trim keeps.

The area is already lean. Most of its tests are in categories that must be kept: plan "Done
when" (C-5 properties and table tests, C-7 ≥ 40 snapshots and the integration run, C-9
migration / export-import / corrupt file), real tool behaviour (`test_ffmpeg.py`,
`test_integration.py`, the awkward subtitle file names, the shell paste test, HandBrake
parameter strings in FFmpeg), regression tests from the M2 review fixes (`415929c`,
`872dfcc`, `d533aa8`, `6badb76`, `8bd8e52`, `f1c4a9c`) and persistence tests. So only redundant
rows of the parametrized tables were removed.

## Coverage gate

```
before 44.530% 1863/6918 branches 10968/21896 lines
after 44.530% 1863/6918 branches 10968/21896 lines
TOTAL LOST: 0
```

## Deleted tests

### Equivalent pixel formats in `dimensions/test_source.py::test_chroma_steps` (14)

Each one goes through the same branch of `chroma_steps` as a case that stays (same regex
alternative, same `_NV_STEPS` path, same prefix-tuple path). Each is also an swscale output
format of the build (`ffmpeg -pix_fmts`, flag `O`), so
`test_ffmpeg.py::test_chroma_steps_match_ffmpeg_crop_for_every_pixel_format` still checks it
against FFmpeg's `crop`:

- `yuvj420p`, `yuv420p10le`, `yuva420p16be`: family regex `420`, like `yuv420p`
- `nv21`: `_NV_STEPS`, like `nv12`
- `p016be`: `_P_FORMAT_RE` group `0`, like `p010le`
- `yuv422p10le`: family `422`. `test_4_2_2_ten_bit` still checks the same format through
  `source_geometry`
- `yuyv422`, `uyvy422`: family `422`, like `yuv422p`
- `nv20le`: `_NV_STEPS` 4:2:2, like `nv16`
- `yuv444p12le`: family `444`, like `yuv444p`
- `bgr0`, `gbrp10le`, `gray10le`, `ya8`: the no-subsampling prefix tuple, like `rgb24`,
  `x2rgb10le` and `gray`

### Same branch in `dimensions/test_source.py` (5)

- `test_unknown_pixel_formats[cuda]`, `[unknown]`: the same final `return None` as `vaapi`
  and `bayer_rggb8`
- `test_rotation_from_the_display_matrix[0]`, `[180]`, `[270]`: a plain pass-through (one
  case stays, 90). Rotation handling is covered by the property
  `test_rotation_flip_and_pixel_aspect_pass_through` and by the real-FFmpeg
  `test_rotation_chain`.

### Repeated rows in `command/test_tracks.py` (11)

- `test_mixdown_is_snapped`:
  - `eac3 8ch 7.1→5.1`: the same rule-4 branch as `ac3 8ch 7.1→5.1`
  - `aac 2ch 7.1→keep`: the same no-upmix branch as `aac 2ch 5.1→keep`
  - `libmp3lame 8ch None→stereo`: the same "keep, more channels than the encoder" branch as
    `ac3 8ch None→5.1`
  - `aac 1ch dpl2→keep (mono)`: the dpl2 ≤ 2 channels rule stays at its boundary (2 ch) and at
    6 ch. The mono table for 1 channel is in `libopus 1ch stereo→mono`.
- `test_bitrate_is_snapped_for_the_effective_mixdown`:
  - `eac3 7000→6144`: above the maximum, like `ac3 700→640`
  - `aac 2ch 700→512`: implied by `aac 2ch mixdown 5.1 700→512`, which stays
  - `libopus 6ch 20→36`: below the minimum, like `ac3 100→224`. The free-range clamp is also
    checked by `test_every_written_value_is_one_the_encoder_can_do`.
- `test_output_layout`:
  - `libopus 6ch 5.1(side)` and `libopus 3ch 2.1`: exact repeats of rows of
    `test_opus_gets_a_layout_it_accepts`, which checks the same filter
  - `aac 5ch 5.0, None → no filter`: the same branch as `aac 6ch 5.1, None → no filter`
  - `libmp3lame 6ch 5.1(side) mixdown 5.1 → stereo`: the same snap as the `None` request row,
    which stays. The 5.1 request to libmp3lame is in `test_mixdown_is_snapped`.

### Restored after the mutation check

- `test_chroma_steps[uyyvyy411]`. It is not an swscale output format (`I....`), so the
  real-FFmpeg test does not see it. It is the only test of the unanchored family search (see
  M14 below).

## Mutation checks

After each mutation I ran all remaining tests of the area (`tests/command`,
`tests/dimensions`, `tests/presets`, real FFmpeg on PATH). Then I reverted the file and
confirmed with `git status` that no production file was changed.

| # | Mutation (production code) | Guards the deleted | Remaining test that failed |
|---|---|---|---|
| M1 | drop `nv21` from `_NV_STEPS` | `nv21` | `test_ffmpeg::test_chroma_steps_match_ffmpeg_crop_for_every_pixel_format` |
| M2 | `_P_FORMAT_RE` `p[024]1[0-9]` → `p[024]10` | `p016be` | same real-FFmpeg test |
| M3 | drop the `bgr` prefix | `bgr0` | same real-FFmpeg test |
| M4 | drop the `ya` prefix | `ya8` | same real-FFmpeg test |
| M5 | `rotation=stream.rotation % 180` | rotation 180/270 | `test_ffmpeg::test_rotation_chain[270-0-False]` and 2 more |
| M6 | bitrate snap without the minimum clamp | `libopus 20→36` | `test_tracks::test_every_written_value_is_one_the_encoder_can_do` |
| M7 | dpl2 allowed from 2 channels (`<=` → `<`) | `aac 1ch dpl2` | `test_mixdown_is_snapped[aac-2-dpl2-None-stereo]`, a snapshot |
| M8 | libopus downmix takes the smallest fit (`fits[-1]` → `fits[0]`) | `libopus 2.1` | `test_opus_gets_a_layout_it_accepts[4.0…]`, integration |
| M9 | skip the side → back relabel loop for libopus | `libopus 5.1(side)` | none: an **equivalent mutant**. The fallback "largest accepted subset" also gives `5.1` for `5.1(side)`, so the deleted row could not catch it either |
| M10 | other encoders are always remixed to the table layout | `aac 5.0` | integration `test_71_source…`, a snapshot, `test_opus…` |
| M11 | bitrate snap without the maximum clamp | `eac3 7000`, `aac 700` | `test_bitrate_is_snapped…[aac-2-settings5-512]`, a snapshot, integration |
| M12 | an unknown pixel format gives (2, 2) | `cuda`, `unknown` | `test_unknown_pixel_formats[vaapi]`, `[bayer_rggb8]` |
| M13 | no-upmix rule only up to 6 channels | `aac 2ch 7.1` | `test_mixdown_is_snapped[ac3-6-7.1-None-5.1]` and 2 more |
| M14 | `_FAMILY_RE` anchored at the start (`^[a-z]{3,4}(420…)`) | `uyyvyy411`, `yuyv422` | **none at first**, so I restored `uyyvyy411`. Then `test_chroma_steps[uyyvyy411]` failed |

## Uncertain, kept

- `command/test_filtergraph.py::test_setparams_only_for_an_untagged_source` and
  `test_colour_params_is_the_graphs_setparams` overlap. Only the first checks that a tagged
  source gets no `setparams` in the graph. (Q-7.11 merged the second into the first; that
  assertion stays.)
- `command/test_filtergraph.py::test_subtitles_filter_opens_awkward_file_names`: the
  `all ' : , ; [ ] \ " $ & mixed` name includes most of the single-character names. I kept them
  all because they are real-tool tests, and Windows may treat names with `:` / `"` differently.
- `command/test_quoting.py::test_quote_windows`: the rows `x&y`, `100%`, `caret^`, `(group)`
  each check one member of the same cmd metacharacter set.
- `dimensions/test_geometry.py`: the "Custom pixel aspect missing" and "… 0/1 is not valid"
  rows are the two halves of one `or`. Auto and manual crop with a rect follow the same path.
  These are C-5 "Done when" table tests, so I kept them.
- `presets/test_builtin.py`: the four per-preset parametrized checks (26 presets × 4) all
  follow the same code path, but each validates a different data item, so I kept them.
- `command/test_tracks.py::test_every_written_value_is_one_the_encoder_can_do`: one test over
  a 9 900-case Cartesian product. It is fast and is the only test that catches M6, so I kept it
  whole.

## Unused fixtures

None. No fixture or helper became unused.
