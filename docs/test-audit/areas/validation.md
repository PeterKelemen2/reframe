# Area validation: `packages/reframe/tests/validation/` (all files, with `scenario.py` and `cases_*.py`)

Baseline: 33 files, 1,492 tests, 7,052 test code lines, 109 s of test time.

Read first: `docs/simplify/areas/validation.md` (Q-6), and the earlier trim reports
`docs/test-trim-reports/V1.md`, `V2.md` (validation), `C.md` (command, for TVL-11) and `B.md`
(batch, for TVL-07). Every file of the area was read in full, plus the cross-layer tests named
below (`tests/command/test_builder.py`, `test_video.py`, `test_tracks.py`,
`test_filtergraph.py`, `tests/batch/test_lint.py`, `tests/definitions/test_custom_params.py`,
`test_snap.py`, `tests/dimensions/test_properties.py`).

Most of the area is already trimmed (V1, V2) or is a real-tool oracle (9 of the 33 files run
FFmpeg). Those oracles are kept. The findings are about cases whose input is the clean
scenario, a property grid that the audio agreement matrix already runs with stricter checks,
copies of a case in a second file, and helpers copied from `scenario.py`.

## Summary

13 findings (Tier A 4, Tier B 8, Tier C 1).
- Tier A: -6 tests, about -55 code lines, about 0.1 s.
- Tier A+B: -273 tests, about -163 code lines, about 7 s (estimate; most small tests are
  below the per-test listing of `durations.txt`).

The best three:
- TVL-02: the mixdown and bitrate grids of `test_snap_notes.py` (244 cases) move into the
  stricter audio agreement matrix. That matrix already runs the same encoders, requests,
  channel counts and bitrate classes.
- TVL-01: 16 `test_negative` cases whose negative scenario is the clean job or template. The
  `test_clean_*_has_no_issues` tests already assert "no issues at all" for that scenario.
- TVL-11 (cross-area): `command/test_builder.py::test_refusals` repeats `PlanError` checks.
  `test_command_agreement.py::test_plan_errors_are_validation_errors` asserts the same raises
  for the same jobs, and it also checks the validation error.

## Verification summary (verifier)

13 findings: 12 CONFIRMED, 1 ADJUSTED (TVL-02), 0 REJECTED. No tier moves.
- Tier A (TVL-03, -05, -06, -08): −6 tests, about −55 code lines, about 0.1 s (unchanged).
- Tier A+B: **−267 tests** (not −273: TVL-02 adds 6 matrix cases, so it is −238 net), about
  **−159 code lines** (TVL-02 −36 instead of −40, TVL-11 −33 instead of −31), about **4 s**
  (TVL-02 about 0.85 s instead of 3 s, TVL-01 about 0.1 s instead of 0.3 s; TVL-10 3 s).

## Findings

### TVL-01 Negative cases that are the clean scenario
- Kind: param-trim
- Where: `test_rules.py::test_negative` (line 1509) for the cases whose negative is `nothing`
  or `ffmpeg_status(None)`: "ffmpeg missing" (334), "ffmpeg too old" (342), "ffmpeg broken"
  (350), "video encoder checking" (366), "source without video" (~684), "audio source
  missing" (~979), "subtitle source missing" (~1073), "PGS into MP4" (~1130), "no output
  path" (1280), "output is the source" (1281), "output is a folder" (1289), "collision,
  auto-rename" (1337), "folder not writable" (1362). Also `test_template.py::test_negative`
  (line 389) for "unknown video encoder" (132), "video encoder checking" (140) and "custom PAR
  missing" (291).
- Now: each of these 16 cases runs `sc.check(base())` (or `check_template(base())`) and
  asserts that one code is not found. `ffmpeg_status(None)` returns at once, so it does
  nothing, exactly like `nothing`.
- Change: in both files, parametrize `test_negative` over
  `[c for c in CASES if c.negative is not nothing]`. In the three tool cases of
  `test_rules.py`, replace `ffmpeg_status(None)` with `nothing`, and remove the `None` branch
  from `ffmpeg_status`. Add one comment: the clean test is the negative of these cases.
- Saved: 16 tests, about 0 code lines (the filter adds 2 lines and the `None` branch loses 2),
  about 0.3 s (estimate).
- Guarantee kept by: `test_rules.py::test_clean_job_has_no_issues` (1497) asserts
  `sc.base().validate() == []`. `test_template.py::test_clean_template_has_no_issues` (376)
  asserts `base().validate() == []`.
- Why nothing is lost: the input is the same scenario, `base()`. "No issues at all" is
  stricter than "this code is not at this path". Because there are no issues, `check` applies
  no fixes, and "no `validation.rule_failed`" is also implied. All 16 cases keep their
  positive test, so `test_every_code_has_a_case` and
  `test_every_template_rule_has_a_positive_case` do not change.
- Docs and history: `grep test_negative docs/` finds only `docs/test-trim-reports/`. Plan
  `05-core.md:436` (C-8 Done when) says "every rule has a positive and a negative test".
  Decision 0014 item 3 says the same. For these rules the negative test becomes the
  clean-scenario test, which is a negative for every code. The cases came with C-8 (eb4d950)
  and Q-6.16 (1d93460, template). None is a bug regression; its positive stays.
- Recorded keeps: V1 kept "the whole table" because each case is "a different branch, a
  different range kind, or came from a review round". V2 kept the template positive and
  negative tests as the C-8 Done when. This finding removes no case and no branch. It removes
  only negatives whose scenario is not a branch at all (the clean job). The Done-when
  guarantee stays through the clean tests.
- Risk: low. Because of the recorded keeps and the Done-when wording, the change still needs
  a review.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Tier B stays. All 16 negatives are `build(nothing)` = `sc.base()` / `base()`

(and `ffmpeg_status(None)` returns at once), so each runs exactly `sc.check(base())`. The clean
tests assert `validate() == []`; with no issues `check` applies no fix, so each negative is
implied. **Done-when wording:** `05-core.md:436` says "every **rule** has a positive and a
negative test" (per rule, not per case or per code); decision 0014 item 3 says "Every **code**
has a positive and a negative test"; `docs/status.md` C-8 says "each with a positive and a
negative test" / "each with a positive and a negative case". None of them asks for one negative
test *per case id*: after the change each of these codes keeps its `Case` object with
`negative=nothing`, and its negative test is the shared clean test (a negative for every code).
So the wording is still met, but only by that reading; the comment in the change must say it, and
the owner should accept it (hence Tier B, not A). **V1/V2:** V1 kept "the whole table" because
each case is "a different branch, a different range kind, or came from a review round"; this
change removes no case and no branch, only 16 runs of the identical clean scenario, so V1's reason
is untouched. V2 kept "the template positive / negative tests ("Done when" of C-8)": same answer —
the template cases stay, and their negative is `test_clean_template_has_no_issues`. Only
correction: time is about 0.12 s (16 × 7.6 ms average per negative), not 0.3 s.
Checked: applied the change (filter `NEGATIVE = [c for c in CASES if c.negative is not nothing]`
in both files, `ffmpeg_status(None)` → `nothing`, `None` branch removed) →
`uv run pytest --collect-only` test_negative 206 → 190 (−16; test_rules 180 → 167, test_template
26 → 23); `$SCRATCH/tools/runtests.sh test_rules.py test_template.py --junitxml` → 424 passed in 5.46 s, ruff and mypy
clean (2 slots, other agents' runs active); reverted.

Orchestrator: Tier B, package Q-7.8. Add the code comment the verifier asks for (the clean-job/template tests are the negative test of these codes, `05-core.md:436`); the owner may undo this choice (decisions-taken.md).

### TVL-02 The mixdown and bitrate "follow the helper" grids are inside the audio agreement matrix
- Kind: layer-duplicate (the same behaviour in two matrices)
- Where: `test_snap_notes.py::test_mixdown_issues_follow_the_helper` (241, 144 cases) and
  `::test_bitrate_issues_follow_the_helper` (270, 100 cases). Kept by
  `test_audio_agreement.py::test_codec_rules_builder_and_validation_agree` (382, 78 cases).
- Now: the grids run full validation for one track and compare the mixdown or bitrate note
  with `encoder.snap_mixdown` or `encoder.bitrate.snap`. Inputs:
  - mixdown grid: aac, ac3, libmp3lame, libopus × every request and None × channels
    0/1/2/3/6/8;
  - bitrate grid: aac, ac3, libmp3lame, libopus, flac × 8/100/250/700/5000 kb/s × channels
    1/2/6/8.

  The validation rules `mixdowns` and `bitrates` (`validation/audio.py:177-254`) do not call
  the helpers. They read `encoded_audio`, which is `planned_audio`, the builder's own plan,
  and `planned_audio` calls the helpers. The agreement test checks each note against the
  builder's real argv:
  - inputs: aac, ac3, eac3, libopus, flac, libmp3lame × 11 layouts (channels 0, 1, 2, 3, 4,
    6, 8) × every request × bitrate classes valid/between/above/below/vbr × 3 sample rates;
  - the note set must equal the expected set (one note per code, the code chosen between
    upmix and unsupported), and the message must name the written value;
  - each fix must keep the argv and remove its note.
- Change: delete the two grids, `REQUESTS`, and the imports that become unused
  (`itertools`, `get_args`, `channels_mixdown`). Keep `MIXDOWN_ENCODERS` and `VALUE_ENCODERS`
  only if `test_samplerate_issues_follow_the_helper` still needs them. In
  `test_audio_agreement.py::check_notes`, add the grid assertions it lacks:
  1. every note has `Severity.INFO`;
  2. a mixdown note that is not a libopus layout downmix has exactly one fix, a single
     `ReplaceOp`, whose value is not `"dpl2"` and is never an upmix
     (`DEFS.mixdowns[value].channels <= stream.channels` when both are known);
  3. add `"3.0": (3, "3.0")` to `LAYOUTS`. The grid's 3-channel source is `3.0`, which
     libopus keeps. The matrix has only `2.1` and `3.0(back)`, which libopus refuses.

  Keep `test_samplerate_issues_follow_the_helper`. Its rates (8000 to 192000 Hz) snap in both
  directions. The matrix has only 47000 Hz, and adding a rate would cost about 2.8 s.
- Saved: 244 tests, about 40 code lines (47 removed, about 7 added), about 3 s (estimate:
  `test_snap_notes.py` is below the 5.1 s per-file threshold with 302 tests; the 6 new
  agreement cases add about 0.6 s at 0.106 s each).
- Guarantee kept by: `test_audio_agreement.py::check_notes` (236-289), with the three
  additions above.
- Why nothing is lost:
  - Inputs: the encoders, requests and channel counts of the grids are a subset of the matrix
    once `3.0` is added. The bitrates 8 and 5000 are the "below" and "above" classes. 100,
    250 and 700 are "between", "valid" or clamped values, depending on the layout.
  - Assertions: "no note when the value is kept, one note otherwise" is `set(notes) ==
    expected`, which is stricter (it covers all five codes). "fix value == the snapped value"
    is "the fix keeps the argv", which is stricter (the real command). "message names the
    written value" is in both. Severity, the one fix, no `dpl2` and no upmix move into
    `check_notes`.
  - The helpers themselves stay covered by `definitions/test_snap.py` (`test_snap_mixdown`,
    `test_snap_mixdown_edge_cases`, "never an upmix" at :56).
  - The V1 mutations that only these grids caught: "upmix note info → warning" (now
    assertion 1), "drop the lossless-bitrate branch" (the matrix has flac with bitrates in
    every case). The text tests in the same file also catch both.
- Docs and history: `grep docs/`: only `docs/test-trim-reports/V1.md:35,38,75,77`. `git log
  -S`: both grids came with 1244f6a ("C-8: audio snaps … info …", decision 0024). Decision
  0024 names only `test_crop_note_says_what_happens` and the text tests, not the grids. The
  commit is a feature, not a bug fix.
- Recorded keeps: V1 trimmed these grids (encoders) and kept the rest as "oracle tests"
  against the helpers. V1 assumed that validation follows the helpers. It actually follows
  `planned_audio` (the builder), and the agreement matrix checks validation against the
  builder's real argv for a superset of the inputs. So the grids are a weaker copy, not a
  separate oracle. V1 itself relied on the agreement matrix to keep eac3 and libfdk_aac.
- Risk: medium. It moves many cases to another file, and the matrix runs only the
  encoder/container/audio rules (`_only_track_rules`). That is enough for these audio codes.
- Proposed tier: B
- Confidence: medium

Verdict: ADJUSTED — the move is sound, but `check_notes` needs a **fifth** check, and the numbers

are net of the 6 new matrix cases. Corrected change: delete the two grids, `REQUESTS`,
`itertools`, `get_args`, `channels_mixdown` (keep `MIXDOWN_ENCODERS`/`VALUE_ENCODERS`: the sample
rate test uses them); in `check_notes`, after `assert set(notes) == expected`, add (1) every note
`Severity.INFO`; for each mixdown note that is not a libopus layout downmix: (2) exactly one fix
with one `ReplaceOp`, (3) **`op.value == planned.mixdown`** (new), (4) `op.value != "dpl2"`,
(5) never an upmix; and add `"3.0": (3, "3.0")` to `LAYOUTS` (before the libopus-refused group:
libopus keeps 3.0). Corrected numbers: −244 grid tests +6 matrix cases = **−238 tests net**
(380 → 142 in the two files); about **−36 code lines** (−49 in `test_snap_notes.py`, +13 in
`test_audio_agreement.py`); about **−0.85 s** (the two grids are 1.35 s of test time by junit, the
6 new matrix cases about 0.5 s at 0.085 s each), not −3 s. Tier B stays, confidence medium → high
with the fifth check.

Superset check, case by case (codec × layout × channel count × bitrate):
- Mixdown grid (144 = aac, ac3, libmp3lame, libopus × None + 6 requests × channels 0/1/2/3/6/8):
  encoders ⊂ matrix ENCODERS; requests = matrix MIXDOWNS (the matrix asserts
  `set(MIXDOWNS) == {None, *get_args(Mixdown)}`); channels/layouts 0/None = "unknown",
  1 = "mono", 2 = "stereo", 6 = "5.1(side)", 8 = "7.1" are in the matrix. **Missing: channels 3
  with layout "3.0" — 28 cases (4 encoders × 7 requests)**; the matrix's 3-channel sources (2.1,
  3.0(back)) behave the same for aac/ac3/mp3 but libopus downmixes them, while it keeps 3.0
  (`ENCODER_LAYOUTS["libopus"]`), so the libopus × 3.0 behaviour (7 cases) was only in the grid.
  Fixed by the added LAYOUTS row. **Also not literally in the matrix:** every grid case asks for no
  bitrate and no quality (the encoder default); the matrix's tracks always carry a bitrate
  (valid/between/above/below) or a VBR quality. `snap_mixdown` and `_kept_layout` read neither, so
  no mixdown behaviour is lost.
- Bitrate grid (100 = aac, ac3, libmp3lame, libopus, flac × 8/100/250/700/5000 × channels
  1/2/6/8 = mono/stereo/5.1(side)/7.1, mixdown None): all encoders and layouts are in the matrix.
  The values 100/250/700 are not, so I classified each grid input by what the builder does
  (kept / step-down / clamp-above / clamp-below / lossless) and compared with the classes the
  matrix's own tracks with mixdown None reach for the same encoder and layout: **0 of the 20
  (encoder, layout) pairs has a grid class the matrix lacks** (script
  `$SCRATCH/vval/classes.py`).
- Source: the grids read the clean job's AC-3 640 kb/s 48 kHz stream with full `JOB_RULES`; the
  matrix reads PCM (lossless, no bitrate) at 44.1 kHz / none with `_only_track_rules`. The mixdown
  and bitrate paths of `planned_audio` (`command/audio.py:244-280`) read only the channels, the
  layout and the encoder; the `audio.*` codes come only from audio-area rules. No loss.

Mutations (product code in my worktree; old grids run from a copy of the HEAD file
`test_zz_oldgrid.py`, the old matrix from `test_zz_oldmatrix.py`, failures per test function):

| Mutation | old grids | old matrix | strengthened matrix | rest of test_snap_notes |
|---|---|---|---|---|
| M0 none | 0 | 0 | 0 | 0 (464 passed) |
| M1 `audio.mixdown_upmix` note info → warning | 40 | **0** | 60 | 3 (texts) |
| M2 `audio.mixdown_unsupported` note info → warning | 11 | **0** | 24 | 8 (texts, opus) |
| M3 helper `snap_mixdown`: `below = plain` (no channel limit) | 0 | 0 | 0 | 0 (equivalent: a fallback only runs when the request exceeds the encoder, so `max(plain)` is already ≤ limit) |
| M4 helper `snap_mixdown`: dpl2 allowed and preferred as fallback | 11 | **0** | 11 | 3 |
| M5 rule: the fix sets "stereo" instead of None on a stereo source (same argv) | 12 | **0** | **0 with the auditor's four checks; 12 with the fifth check** | 2 (texts) |
| M6 snapped-bitrate note info → warning | 0 | **0** | 70 | 3 |
| M7 drop the lossless-bitrate branch | 20 | 13 | 14 | 1 |

So the grids' "fix value == the snapped value" is **not** implied by "the fix keeps the argv"
(the auditor's claim): a fix that names a different mixdown with the same argv passes the matrix
(M5). The fifth check closes it. Every mutation the old grids catch, the strengthened matrix
catches.

V1's decision about these grids (`docs/test-trim-reports/V1.md`, "Parametrized cases that add no
new branch"): "The three oracle tests compare the validation notes with the C-6 helpers. All
encoders go through the same code; the encoders differ only in data, and the data of the removed
ones has the same shape as a kept one. `test_audio_agreement.py` (not in this area) still checks
C-8 against C-7 for aac, ac3, eac3, libopus, flac and libmp3lame." It trimmed the grids to one
encoder per kind and kept them as oracles; its mutation table names them as catchers of "upmix
note info → warning" and "drop the lossless-bitrate branch". **Does the reason still hold? No,
not as an oracle:** validation does not have its own snap logic; `validation/tracks.py:57-82`
`encoded_audio` calls `planned_audio`, which calls `snap_mixdown` / `bitrate.snap`. The grids'
oracle is therefore the same helper the code under test calls, so a helper bug is invisible to the
comparison (M3, M4: the grid caught M4 only through its dpl2 invariant, not through the oracle).
What the grids add is their invariant assertions; with the five checks those run in the matrix
on a superset of the inputs, and both V1 mutations are still caught (M1: 60, M7: 14). V1's own
note "check that the encoders removed here (eac3, libfdk_aac) stay covered there" is unaffected
(eac3 stays in the matrix; libfdk_aac was never in it).
Checked: applied the change → `uv run pytest --collect-only` 380 → 142 (58 + 84);
`$SCRATCH/tools/runtests.sh test_snap_notes.py test_audio_agreement.py -q` → 142 passed in 7.18 s (2 slots, other
agents running); ruff check/format and mypy clean; mutation runs via
`$SCRATCH/vval/mutate.py` → table above (`$SCRATCH/vval/mutations.txt`, `mutations2.txt`);
grid time `--junitxml` → 244 tests 1.35 s. All reverted.

Orchestrator: Tier B, package Q-7.8. With the verifier's fifth check `op.value == planned.mixdown` and the `3.0` layout row.

### TVL-03 Two option cases copy the R5 tests of `test_option_values.py`
- Kind: near-copy
- Where: `cases_options.py` case "x264 VBV maximum rate without a buffer" (85-92) and case
  "x265 mastering display that x265 cannot parse" (216-229), run as
  `test_rules.py::test_positive[...]` and `::test_negative[...]` (4 tests).
- Now: positive `video(encoder="libx264", advanced={"vbv-maxrate": 5000})`, negative the same
  with `vbv-bufsize: 6000`. Positive `libx265, bit_depth=10, master-display "garbage"`,
  negative the valid `X265_MD`. Each runs through `sc.check`.
- Change: delete the two cases.
- Saved: 4 tests, about 22 code lines, under 0.1 s.
- Guarantee kept by:
  - `test_option_values.py::test_vbv_maxrate_without_a_buffer_is_inactive[libx264]` (43). It
    runs the same positive input through `sc.check` (`_found`) and asserts `(option_inactive,
    video.advanced.vbv-maxrate, WARNING)`. It also runs CQ and ABR. With both values set, it
    asserts no issue at any `video.advanced.vbv*` path (stricter than the negative).
  - `test_option_values.py::test_the_hdr_text_options_are_checked[libx265-master-display-garbage-False]`
    and `[...-X265_MD-True]` (106). The same inputs through `sc.check`. They assert
    `(option_invalid, path, ERROR)` present or absent.
- Why nothing is lost: the inputs are identical. The assertions are the same or stricter. The
  one small difference is that `test_positive` asserts that every matching issue has the
  severity, while the kept test asserts that one does. `encoder.option_inactive` and
  `encoder.option_invalid` keep other positive and negative cases ("x265 amp …", "option out
  of range", "option not a choice"), so `test_every_code_has_a_case` still holds.
- Docs and history: `grep docs/` for the case ids: none. `git log -S`: both cases came in
  a0529f9 (review R5-7, R5-8), the same commit as the kept tests. 0041:162-163 and
  0035:229-243 name the kept `test_option_values.py` tests as the R5-7 and R5-8 guards, not
  the cases.
- Risk: low.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Tier A. Inputs are identical (`_found` sets the same fields as `video(...)`

on `sc.base()` and runs `sc.check`; `X265_MD` is byte-equal to the case's negative text). Kept
assertions: positive `(code, path, severity) in found` (one match with the severity, where
`test_positive` asserts all matches have it; a second, differently-graded match at the same path
is not a realistic loss); negative: no `vbv*` issue at all (stricter) and "ERROR tuple absent"
for master-display (marginally weaker than "code absent at path at any severity"; acceptable).
`encoder.option_inactive` / `option_invalid` keep other cases. No doc names the case ids
(grep docs/ testdata/ CLAUDE.md: none).

Orchestrator: Tier A, package Q-7.1.

### TVL-04 The x265 VBV buffer case copies `test_a_vbv_buffer_without_a_maximum_rate`
- Kind: near-copy
- Where: `cases_options.py` case "x265 VBV buffer without a maximum rate at a constant
  quality" (93-100): `test_rules.py::test_positive[...]` and `::test_negative[...]`.
- Now: positive libx265 with `vbv-bufsize 5000` (default CQ). Negative the same with
  `AverageBitrate()`.
- Change: delete the case.
- Saved: 2 tests, about 8 code lines.
- Guarantee kept by: `test_option_values.py::test_a_vbv_buffer_without_a_maximum_rate[libx265]`
  (55). The same positive input and the same `(code, path, WARNING)`. ABR at 2000 kb/s with
  no `vbv*` issue at all.
- Why nothing is lost: the positive input is identical. The negative input differs only in
  the ABR value (`AverageBitrate()` default against `kbps=2000`), and the rule does not read
  the value. The negative assertion of the kept test is stricter.
- Docs and history: none for the case id. Added in a0529f9 (R5-7) together with the kept test
  (named in 0041:162).
- Risk: low. It is Tier B only because the negative input is not literally the same.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Tier B. `_vbv_rules` (`validation/video.py:795`) checks only

`isinstance(video.rate_control, ConstantQuality)`, never the ABR value, so `AverageBitrate()` and
`AverageBitrate(kbps=2000)` take the same branch. Positive input identical. No doc names it.

Orchestrator: Tier B, package Q-7.8.

### TVL-05 `test_read_only_source_through_the_view` is the same scenario as two other tests
- Kind: near-copy
- Where: `test_inplace_fs.py::test_read_only_source_through_the_view` (156).
- Now: an in-place job, and `fs.writable_file = lambda path: False`. Asserts that
  `inplace.source_not_writable` is found.
- Change: delete.
- Saved: 1 test, 4 code lines.
- Guarantee kept by:
  - `test_inplace_fs.py::test_read_only_source_fix_writes_a_new_file_with_a_new_path` (142):
    the identical setup, `[issue] = …` (exactly one), and it checks the fix and the
    revalidation.
  - `test_rules.py::test_positive[inplace_read_only_source]` (`cases_inplace.py:50`):
    `both(in_place, read_only_source)`, code at `output.edit_in_place`, ERROR, and `sc.check`.
    Its negative, `[inplace_read_only_source]` with a writable source, also stays.
- Why nothing is lost: the input is identical and the assertions are stricter in both kept
  tests.
- Docs and history: `grep docs/`: `docs/simplify/areas/validation.md:100` (Q-6 VAL-04 cites it
  as the guard that `in_place_source` asks the view; the two tests above guard the same thing)
  and `V2.md:105`. `git log -S`: f7f6d48 (C-13 feature).
- Recorded keeps: V2 deleted it, then restored it only because its gate measured V2's own
  files. V2 wrote: "You can delete it if the gate is judged across the whole directory." Both
  kept tests are in this directory.
- Risk: low.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Tier A. (Line numbers at 38cf3eb: the test is `test_inplace_fs.py:106`, the

keeper `:92`; the report's 156/142 are stale.) Same `in_place()` helper, same
`writable_file = lambda path: False`; the keeper asserts exactly one issue and more. The Q-6 area
file (`docs/simplify/areas/validation.md:100`) cites it as the guard that `in_place_source` asks
the view; `test_read_only_source_fix_writes_a_new_file_with_a_new_path` (same file) and
`test_positive[inplace_read_only_source]` guard the same thing. V2's restore reason was its own
per-file gate only, as quoted.

Orchestrator: Tier A, package Q-7.1.

### TVL-06 The in-place default-track test is a rule case
- Kind: near-copy
- Where: `test_default_tracks.py::test_an_in_place_edit_with_two_default_tracks` (133).
- Now: `remux_job(edit_in_place=True)`, audio tracks 0 and 1 marked default. `sc.check`, one
  `metadata.several_defaults` issue at `audio[1].metadata.default`.
- Change: delete.
- Saved: 1 test, 6 code lines.
- Guarantee kept by: `test_rules.py::test_positive[inplace_two_default_audio_tracks]`
  (`cases_inplace.py:58`). The identical input (`both(in_place, default_audio(0, 1))`),
  `sc.check`, the same code and path, and WARNING. Also
  `test_default_tracks.py::test_validation_names_the_tracks_the_plan_marks_default[in-place
  edit]` (223).
- Why nothing is lost: the input, code and path are the same, and the kept test also checks
  the severity. The deleted test also asserts "exactly one issue of this code". The rule
  counts tracks the same way with or without in-place, and
  `test_one_warning_per_kind` (97) guards the count.
- Docs and history: `grep docs/`: none. `git log -S`: 59f55d0, the same commit as the rule
  case (a feature, not a fix).
- Risk: low.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Tier A. Identical input (`remux_job(..., edit_in_place=True)` + audio 0 and

1 default), same code/path, keeper adds the severity. The "exactly one" count is also pinned for
an in-place edit by `test_validation_names_the_tracks_the_plan_marks_default[in-place edit]`
(it compares the named tracks with the plan's), and in general by `test_one_warning_per_kind`.

Orchestrator: Tier A, package Q-7.1.

### TVL-07 Template default-track lint is tested in `batch/test_lint.py`; keep one wiring test
- Kind: layer-duplicate
- Where: `test_default_tracks.py::test_two_template_rules_that_mark_their_tracks_default`
  (265) and `::test_template_rules_with_one_default_per_kind_are_clean` (271).
- Now: `validate_template` calls `batch.lint.lint_track_rules`. These tests check two rule
  lists through `validate_template`. The lint itself, with messages, fixes and edge cases, is
  tested in `tests/batch/test_lint.py:437-520`.
- Change: delete both. Keep `test_a_template_rule_that_marks_every_track_default` (257) as
  the wiring test (`check_template`, so the fix target is checked too).
- Saved: 2 tests, about 10 code lines.
- Guarantee kept by:
  - `batch/test_lint.py::test_rules_of_one_kind_that_all_set_default` (subtitle rules
    `[True, None, True]×2` → `subtitle_rules[2]`, message and fix);
  - `batch/test_lint.py::test_audio_rules_with_one_default_track` ("one explicit default":
    `[True, False, None multiple]` → `[]`);
  - `test_default_tracks.py::test_a_template_rule_that_marks_every_track_default` (that
    validate_template passes the lint's issues on);
  - `test_template.py::test_clean_template_has_no_issues`.
- Why nothing is lost: the lint behaviour is pinned in batch with stricter assertions (the
  full messages and the applied fixes). The validation layer only has to prove that the lint
  is wired in, and the kept test does that. The inputs are not literally the same: two
  subtitle rules `[True, True]`, and the subtitle pair `[False, True]`.
- Docs and history: none in `docs/`. Added in 59f55d0 together with the batch tests. B.md
  does not mention them.
- Risk: low.
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED — Tier B. `validate_template` passes the whole template to

`lint_track_rules`, so the wiring is kind-agnostic; the kept audio wiring test plus
`batch/test_lint.py::test_rules_of_one_kind_that_all_set_default` (subtitles,
`[True, None, True]×2`) and `test_audio_rules_with_one_default_track` cover the behaviour. Note:
the two deleted tests are the only ones that run a *subtitle* rule pair through
`check_template` (fix applied and re-validated at the template layer); the lint test applies its
fixes itself. Acceptable at Tier B.

Orchestrator: Tier B, package Q-7.8.

### TVL-08 `_found_tools()` and `_source()` are copies of `scenario.make_tools()` / `make_source()`
- Kind: shared-setup
- Where: `test_dryrun_ffmpeg.py` `_found_tools` (59-66) and `_source` (69-71);
  `test_custom_params_cqm.py` `_found_tools` (58-65) and `_source` (68-70); `test_dryrun.py`
  `_source` (313-315) and the three `_tools(ToolStatus.FOUND, Path("/usr/bin/ffmpeg"))` calls.
- Now: `_found_tools()` builds `ToolSet(ffmpeg, ffprobe)` with `FOUND` and `/usr/bin/<name>`,
  which is exactly `sc.make_tools()` (`scenario.py:241-249`). `_source()` returns
  `sc.make_source()`.
- Change: call `sc.make_tools()` and `sc.make_source()`, and delete the helpers. Keep
  `test_dryrun.py::_tools` for the `MISSING` case.
- Saved: 0 tests, about 23 code lines.
- Guarantee kept by: the same objects are built.
- Why nothing is lost: identical values (the same names, status and paths).
- Docs and history: helpers from a0529f9 and 0b93f2d; no docs.
- Risk: low.
- Proposed tier: A
- Confidence: high

Verdict: CONFIRMED — Tier A, with one precision: `_found_tools()` (two files) is byte-equal to

`sc.make_tools()`, but `test_dryrun.py::_tools(FOUND, Path("/usr/bin/ffmpeg"))` gives **both**
tools the path `/usr/bin/ffmpeg`, while `sc.make_tools()` gives ffprobe `/usr/bin/ffprobe`. The dry
run reads only `tools.ffmpeg` (`validation/dryrun.py:466`), so nothing is lost. Lines: 23 code
lines confirmed (2 × 7 + 3 × 3), plus any import that becomes unused.

Orchestrator: Tier A, package Q-7.1.

### TVL-09 Two "the dry run never starts FFmpeg" tests are one test with two row lists
- Kind: near-copy
- Where: `test_custom_params_cqm.py::test_the_dry_run_never_starts_ffmpeg_with_a_cqm_file`
  (83, 5 cases) and `test_dryrun_ffmpeg.py::test_a_refused_parameter_never_starts_ffmpeg`
  (85, 5 cases).
- Now: both patch `dryrun.run` to fail, run `dry_run` and assert one ERROR at
  `video.custom_params`. The cqm test also asserts the exact code and the remaining text
  after the fix. The other test asserts that the code is one of two, and that there is one
  fix.
- Change: parametrize `test_a_refused_parameter_never_starts_ffmpeg` as `(job, code, rest)`
  with all 10 rows. Assert the exact code, one fix, and the custom parameters after the fix.
  Delete the cqm copy.
- Saved: 0 tests, about 12 code lines.
- Guarantee kept by: `test_dryrun_ffmpeg.py::test_a_refused_parameter_never_starts_ffmpeg`
  (merged).
- Why nothing is lost: all 10 inputs stay. Each row gets the union of the assertions (stricter
  for the 5 old rows).
- Docs and history: `test_a_refused_parameter_never_starts_ffmpeg` is named in 0035:204 and
  0041:156 (R5-1); the name stays. The cqm test came with 0b93f2d (final review RC-1). All its
  inputs stay.
- Risk: low.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Tier B. Neither test is `needs_ffmpeg` (both modules carry only

`pytest.mark.anyio`), so merging into `test_dryrun_ffmpeg.py` does not make the cqm rows skip
without FFmpeg. The rows need their own job builders (`cqm._job(custom)` is libx264,
`dryrun_ffmpeg._job` defaults to libx265): put the built job in the row, as the auditor says. The
kept name stays (named in 0035:204, 0041:156).

Orchestrator: Tier B, package Q-7.8.

### TVL-10 The facade's libvpx `arnr-maxframes=16` dry run repeats the R5-3 real-tool test
- Kind: near-copy (both real FFmpeg)
- Where: `test_options_facade.py::test_the_dry_run_of_each_software_encoder[libvpx-vp9-arnr-maxframes=16-encoder.custom_param_rejected]`
  (207).
- Now: a multitrack draft, VP9 with preset/tune/profile/level cleared, and the custom
  parameter `arnr-maxframes=16`. Asserts `[(custom_param_rejected, video.custom_params)]`,
  then that the dry run without custom parameters is clean. 2.98 s.
- Change: delete this row.
- Saved: 1 test, 1 code line, about 3 s.
- Guarantee kept by:
  `test_dryrun_ffmpeg.py::test_the_real_libvpx_codec_control_refusals[arnr-maxframes=16-…]`
  (251). The same draft, VP9 with the same fields cleared, and the same parameter. It asserts
  the same list and also the libvpx message "arnr_max_frames out of range [0..15]". "VP9 with
  no custom parameters dry-runs clean" stays in the rows `[libvpx-vp9-bogus=1]` and
  `[libvpx-vp9-lag-in-frames=26]`.
- Why nothing is lost: the assertion of the kept test is stricter. The only difference in the
  input is the rate control: the draft's value against `ConstantQuality(30)`. A codec-control
  refusal does not depend on it.
- Docs and history: `grep test_the_dry_run_of_each_software_encoder docs/`: none. The row came
  with a0529f9 (R5-3), the same commit as the kept test, which 0041:158 and 0035:222 name as
  the R5-3 guard. V2 kept `test_search_psy…` of this file, not this row.
- Risk: low. It is Tier B because both tests are review regressions and the inputs are not
  byte-identical.
- Proposed tier: B
- Confidence: medium

Verdict: CONFIRMED — Tier B. Inputs differ only as stated: the facade row keeps the draft's

`VideoSettings` and clears preset/tune/profile/level, the kept test replaces `job.video` with
`_vp9(...)` (CQ 30, same fields cleared). A libvpx codec-control refusal does not read the rate
control. "VP9 without custom parameters dry-runs clean" stays in the rows `bogus=1` and
`lag-in-frames=26`. 2.98 s confirmed in `durations.txt`. Both are needs_ffmpeg, so CI coverage is
unchanged.

Orchestrator: Tier B, package Q-7.8.

### TVL-11 (cross-area) `command/test_builder.py::test_refusals` repeats `PlanError` agreement rows
- Kind: layer-duplicate
- Where: `packages/reframe/tests/command/test_builder.py::test_refusals` (89-123).
- Now: 10 `build_plan` calls on multitrack drafts, each with `pytest.raises(PlanError,
  match=…)`: output path None, `libx266`, a WebM container, `h264_amf` at 10 bits, audio
  stream 9, audio without a source, an empty range, a source without video, passthrough into
  WebM, and a frame range without a frame rate.
- Change: delete it. To keep its stricter match, change the `REFUSALS` row "video passthrough
  the container cannot hold" (`test_command_agreement.py:259`) to `"h264 video cannot be
  copied into WebM"`.
- Saved: 1 test, about 31 code lines.
- Guarantee kept by: `test_command_agreement.py::test_plan_errors_are_validation_errors`
  (373). It has the same 10 jobs (rows at 255-278) and the same `build_plan` + `pytest.raises`
  with the same texts, and it also asserts the matching validation error.
  `test_every_plan_error_is_covered` (417) makes sure each `raise PlanError` keeps a row.
- Why nothing is lost: the inputs are the same multitrack drafts. The agreement rows set
  `video={"encoder": "libx264"}` where `test_refusals` uses the default draft for two cases.
  Those two refusals (no video stream, frame rate) do not depend on the encoder. The match
  texts are equal except for the passthrough row, which the change above makes equal.
- Docs and history: `grep test_refusals docs/`: none. `git log -S`: b9d7379 (C-7 feature). The
  agreement test came with 1244f6a (decision 0024). C.md lists `test_builder` in its scope
  but records no keep for `test_refusals`.
- Risk: low. It touches another area's file, so the command auditor must agree.
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Tier B, with a correction of "the same 10 jobs": **7 are identical**

(output path None, libx266, H.264 into WebM, h264_amf 10-bit, audio stream 9, audio without a
source, empty range: the same `draft(multitrack, video={"encoder": "libx264"})` + the same setattr).
**3 differ:** "no video stream" and "frame rate" use the draft's default encoder (libx265 in
`test_refusals`, libx264 in the agreement rows; the frame-rate row also drafts from the source
before its rate is removed); the WebM passthrough row in `test_refusals` keeps the draft's
subtitle tracks (`draft(src, container="webm", audio="passthru")`), while the agreement row clears
them (`subtitles()`) and sets libx264. None of these affects which `PlanError` is raised
(passthrough is checked on the video stream; default video is not passthrough). The one detail
lost: that the passthrough refusal wins over subtitle planning when the WebM job still has its
subtitles — an ordering detail, not a guarantee any doc names. Other assertions all equal or
stricter. Lines: −33 code lines (−31 in the function, plus 2 now-unused imports `PlanError`,
`AudioOutputTrack`).
Checked: deleted `test_refusals`, ruff --fix (2 F401), changed the REFUSALS match to
`"h264 video cannot be copied into WebM"` (99 chars, ruff clean) →
`$SCRATCH/tools/runtests.sh tests/command/test_builder.py tests/validation/test_command_agreement.py -k "plan_error or
builder"` → 50 passed in 5.57 s (includes `test_every_plan_error_is_covered`); reverted.

Orchestrator: Tier B, package Q-7.8. Delete `command/test_builder.py::test_refusals`, keep the agreement rows; tighten the passthrough row's match to "h264 video cannot be copied into WebM" (command verifier).

### TVL-12 The `split_custom_params` text test belongs in the definitions tests
- Kind: layer-duplicate
- Where: `test_dryrun.py::test_split_custom_params_keeps_the_typed_text` (52).
- Now: `split_custom_params(" ref=4 :bogus:path=C\\:/x::")` → names, values and raw text, and
  `""` → `[]`. The function lives in `reframe.definitions.custom_params`, and
  `definitions/test_custom_params.py` already has `test_the_split_keeps_the_typed_text` (29)
  plus a Hypothesis property that compares the split with the builder's.
- Change: move the input and its two assertions into
  `definitions/test_custom_params.py::test_the_split_keeps_the_typed_text`. Delete the
  validation copy.
- Saved: 1 test, about 4 code lines.
- Guarantee kept by: the merged definitions test. It keeps all inputs (a leading space
  dropped from `raw`, a trailing space kept, an escaped drive colon, an empty segment, `""`).
- Why nothing is lost: a move with every input and assertion kept.
- Docs and history: none in `docs/`. 13e6c2f (C-6 feature); the definitions test is from
  a0529f9.
- Risk: low (it touches another area's file).
- Proposed tier: B
- Confidence: high

Verdict: CONFIRMED — Tier B. The validation input adds what the definitions test lacks (a leading

space dropped from `raw`, a bare `bogus` → value "1", an escaped drive colon, two empty segments,
`""` → `[]`); moving it keeps all of them. No doc names it.

Orchestrator: Tier B, package Q-7.8.

### TVL-13 `test_no_odd_sizes` is a weaker copy of the dimensions properties
- Kind: property-covers
- Where: `test_engine.py::test_no_odd_sizes` (266-310, Hypothesis, 300 examples).
- Now: `compute_geometry(source_geometry(stream), dims)` for a yuv420p stream. It asserts that
  the scaled size is even and that an applied crop is on the chroma grid (4 lines for an
  interlaced source).
- Change: none proposed.
- Saved: (if it were dropped) 1 test, about 35 lines, about 1-2 s.
- Guarantee kept by: `dimensions/test_properties.py::test_the_result_is_a_multiple_of_the_modulus`
  (a multiple of the modulus ≥ 2 and of the chroma step, which is stricter) and the crop
  property at about line 305 (the cropped size is a multiple of the chroma step, ×2 when
  interlaced). The strategy covers every SAR, interlacing, modulus 2 to 16, fit boxes and
  manual crops. `dimensions/test_source.py` covers `source_geometry`.
- Why nothing would be lost: the dimensions properties assert the same, with stricter checks
  and wider inputs.
- Docs and history: decision 0014 "Decision" item 1 names
  `tests/validation/test_engine.py::test_no_odd_sizes` as the proof that no odd-size rule is
  needed. Added in eb4d950 (C-8).
- Risk: low technically, but a decision record names this test.
- Proposed tier: C (it could go only with an update of decision 0014 that points at the
  dimensions properties)
- Confidence: high

Verdict: CONFIRMED — Tier C, no change. Decision 0014 "Decision" item 1 names

`tests/validation/test_engine.py::test_no_odd_sizes`; it can go only with an update of 0014.

Orchestrator: Tier C, not planned: kept (see the verdict).

## Looked at and kept

- Every `*_ffmpeg.py` test and the needs_ffmpeg tests of `test_options_facade.py`,
  `test_dryrun_ffmpeg.py` and `test_custom_params_cqm.py`: real-tool oracles (V2 keep). This
  includes the equal-line groups of `test_option_formats_ffmpeg`, `test_custom_params_ffmpeg`
  (`test_the_recorded_private_options_cover_this_build`: 13 cases, 2 line sets, one encoder's
  real option list each), `test_levels_ffmpeg`, `test_x26x_ffmpeg` and `test_options_ffmpeg`.
  Each row is a different encoder behaviour.
- `test_option_values.py::test_x265_level_with_min_cu_size_16_at_medium` / `_8_at_ultrafast`:
  `test_levels_ffmpeg.py::test_the_padding_follows_min_cu_size` and the rule case "x265 level
  too low after the ultrafast padding" pin the same inputs. Both tests are named in 0014:255
  and 0041:159 (R5-4), and the ffmpeg test skips without FFmpeg.
- `test_option_values.py` signs, spaces and HDR text tables (28 + 26 cases on 10 + 11 line
  sets): each row is a different input class (sign, white space, Unicode digit, overflow),
  RC-2 / R5-8 (0041:163).
- `test_command_agreement.py::test_composite_parts_have_defaults` (66 cases, 4 line sets): V2
  keep (the data is per preset), and `UNREACHABLE` depends on it.
- `test_command_agreement.py::test_snapshot_jobs_validate_without_errors` (73 jobs) and
  `test_snapshot_jobs_are_imported`: V2 keep.
- `test_audio_agreement.py` equal-line groups (ac3/eac3, the `no-rate` pairs): data-driven per
  encoder table. V1 relies on it for eac3 and libfdk_aac. V2 already cut the no-rate rows.
- `test_snap_notes.py::test_samplerate_issues_follow_the_helper` (30): the only rates that
  snap downward. See TVL-02.
- `test_snap_notes.py::test_crop_note_says_what_happens`: decision 0024:69.
- `test_snap_notes.py` text and opus tests: V1 keep.
- `test_rules.py` positive table and the dedicated tests after it: C-8 Done when, V1 keep,
  review rounds. `test_template.py` positive cases and
  `test_every_template_rule_has_a_positive_case`: Q-6.16 Done when.
- `test_template.py::test_positive[video encoder unavailable]` against
  `test_an_unavailable_nvenc_preset_names_the_closest_encoder`: the inputs differ (rate
  control, preset), and the case feeds the per-rule positive check.
- `test_custom_params_rules.py::test_presets_get_the_check_too`: R5-1 "for jobs and
  presets". It uses a real built-in preset, while the template case uses a hand-made one.
- `test_custom_params_rules.py::test_presets_get_the_override_too`: the input is a built-in
  preset, not the template case's bare preset. It also asserts one issue with one fix.
- `test_default_tracks.py` job tests `test_two_default_audio_tracks`,
  `test_two_default_subtitle_tracks`, `test_one_warning_per_kind` (one line set): different
  inputs and messages. A merge would lose the one-kind inputs.
- `test_inplace_fs.py::test_every_view_answers_writable_file`: decision 0034:187.
- `test_engine.py::test_job_rule_decorator_registers`: V2 keep.
- `test_engine.py::test_source_without_video` against the "source without video" case: the
  input is a superset and it asserts the full code list, while the case asserts the path and
  severity. They are not equal.
- `test_paths.py` Windows-path tests and `test_local_*` (mocked Windows branches): never-drop
  list. `test_plan_and_statistics_files_are_the_source` (3 cases, 1 line set): each name is a
  separate data item of `written_paths` (0014 M2 review item 1).
- `test_nul_paths.py`: Q-6 VAL-14 (Tier C, kept).
- `test_text_charset.py`: Q-6 VAL-13.
- `test_same_file.py`: decision 0040:429. `test_local_same_file` overlaps
  `test_paths.py::test_local_file_system` in two asserts only.
- `test_no_mkvtoolnix.py`: an in-place edit with a BCP 47 language and every flag. These
  inputs differ from `test_inplace.py::test_a_clean_in_place_edit_has_no_issues`.
- `test_dryrun.py` log-parsing tests: each is a recorded log line (testdata/README, 0035).
- `scenario.py:FIXES_CHECKED` (written, never read): the Q-6 verifier already noted it, so it
  is not reported again.
- Other `command/` unit tests of `PlanError` (`test_video.py`, `test_tracks.py`,
  `test_filtergraph.py`): they call lower-level functions (`video_encoder_args`,
  `plan_subtitles`, `graph`) that the agreement test does not call directly. Those belong to
  the command auditor.

## Speed notes

- `test_option_formats_ffmpeg.py::_written` (183-201) waits 10 s for SVT-AV1 runs that never
  end. The row `[libsvtav1-mastering-display-\f…]` takes 10.3 s. Two frames take well under
  a second, and `test_svt_av1_never_ends_with_text_after_the_tags` uses 5 s for the same
  property, so `timeout=5` would save about 5 s.
- The same test encodes its `plain` reference again for each of its 28 rows, but there are
  only about 8 distinct references. `functools.cache` on `_written` would skip about 20 FFmpeg
  runs; the function returns plain data, so caching it is safe.

## Verifier notes

- TVL-02: the matrix's `check_notes` must get the fifth check `op.value == planned.mixdown`; with
  only the auditor's four, a fix that writes another mixdown with the same argv (M5) is caught by
  the old grids (12) and by 2 text cases, but not by the matrix. Once the grids go, only
  `test_texts_say_what_is_written` (stereo source, aac 5.1 / dpl2) would still catch it.
- TVL-02: the snapped-bitrate note's severity (M6) was not checked by the bitrate grid nor by the
  old matrix (only by 3 text cases); the strengthened matrix's INFO check is a real gain (70).
- TVL-02: M3 (`below = plain` in `snap_mixdown`) survives every test in both files, also before
  the change: the line's channel filter is unreachable with the current data (the fallback runs
  only for requests above what the encoder makes, and encoder mixdown lists are prefixes). Not
  caused by this trim; `definitions/test_snap.py` is the place for such a guard.
- TVL-05: the report's line numbers for `test_inplace_fs.py` (156, 142) do not match 38cf3eb
  (106, 92).
- The `testdata/media` symlink from the set-up is the only untracked item left in the worktree.
