# 0068 — M9, advanced encoder options: the advanced panel

- Status: accepted
- Date: 2026-11-02
- Steps: F-9 (the advanced panel)

## Context

M9 ([08 §M9](../plan/08-roadmap.md#m9--advanced-encoder-options)) builds the advanced panel of
[03 §Advanced encoder options](../plan/03-features.md#advanced-encoder-options), the one unchecked
box of [06 §F-9](../plan/06-web-app.md#f-9-video-tab-and-advanced-options), on the core of C-6
([0035](0035-advanced-option-sets-and-dry-run.md)). Its tasks and waves are in
[m9-breakdown.md](../m9-breakdown.md). Before any agent, the lead checked the API (2026-11-02, on
`main` 7fbda7c, a real `reframe-server` from `scripts/dev-server.py` with the pinned FFmpeg n9.0.2
and the fixtures `hdr10`, `multitrack`; scripts in the lead's scratchpad `lead/api_check.py`,
`api_check2.py`):

- **The option schema** is in the definitions (`video_encoders[id].options`, definition order).
  Options per encoder: `libx264` 52, `libx265` 81, `libsvtav1` 38, `libvpx-vp9` 17, `h264_nvenc`
  24, `hevc_nvenc` 26, `av1_nvenc` 24, `h264_qsv` 17, `hevc_qsv` 19, `av1_qsv` 12, `h264_amf` 28,
  `hevc_amf` 24, `av1_amf` 25, `h264_vaapi` 8, `hevc_vaapi` 8, `av1_vaapi` 7. x265 by category:
  Motion / analysis 24, Rate control 17, Frame types / GOP 13, HDR / colour 10, Loop filters 7,
  Performance 6, Psycho-visual 4 (no *Basic* option); by type: bool 29, int 27, enum 15, float 7,
  string 3; by default: `preset` 45, `fixed` 25, `encoder` 11. x265 `bframes`: int 0–16, unit
  `frames`, default `{kind: preset, values: {ultrafast: 3, …, slow: 4, slower: 8, …}, tunes:
  [animation, zerolatency]}`. The category order is the core's `OPTION_CATEGORIES` (Basic, Rate
  control, Frame types / GOP, Motion / analysis, Psycho-visual, Loop filters, HDR / colour,
  Performance); the frontend does not receive it.
- **The search** (`GET /api/definitions/encoders/libx265/options?q=`): `psy` → `psy-rd`,
  `psy-rdoq`, `nr-intra`, `nr-inter` (the last two by their help text); `rd` → `rd`,
  `rdoq-level`, `rd-refine`, `psy-rd`, `psy-rdoq`, `dynamic-rd`, `hrd`, `rskip`; `deblock` →
  `deblock-tc`, `deblock-beta`, `sao-non-deblock`.
- **Copy HDR metadata** (`POST /api/jobs/hdr-metadata`) on `hdr10` with `h265-mkv-1080p`
  (libx265, preset `faster`, 10-bit): `[{op: add, path: /video/advanced/master-display, value:
  "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"}, {op: add, path:
  /video/advanced/max-cll, value: "1000,400"}]`. The plan's command already carries the source's
  HDR10 metadata without the copy (`-x265-params colorprim=bt2020:…:master-display=…:max-cll=…`):
  the copy makes the values visible and editable in the panel.
- **The command**: `advanced: {bframes: 6}` adds `:bframes=6` at the end of `-x265-params`.
- **The dry run** (`POST /api/jobs/dry-run`, 0.06–0.07 s on `hdr10`): `nosuchparam=1` → `error
  encoder.custom_param_rejected` at `video.custom_params` ("FFmpeg refused 'nosuchparam': Unknown
  option: nosuchparam.", fix *Remove nosuchparam=1 from the custom parameters*); `bframes=abc` →
  the same code ("Invalid value for bframes: abc."); `psy-rd=2.0` → `[]`; `csv=out.csv` → `error
  encoder.custom_param_file` (no FFmpeg run). `jobs/validate` gives `encoder.custom_param_file`
  but not `custom_param_rejected`: it does not dry-run, and neither does adding to the queue.
- **Validation of options** (`jobs/validate`): `{amp: true, rect: false}` → `warning
  encoder.option_inactive` at `video.advanced.amp`; `{bframes: 99}` → `error encoder.option_invalid`
  at `video.advanced.bframes` and `error encoder.lookahead_too_short` at
  `video.advanced.rc-lookahead`; `{psy-rd: "x"}` → `encoder.option_invalid`; `{nosuch: 1}` →
  `error encoder.option_unknown` at `video.advanced.nosuch`.
- **Missing**: nothing on the server. The UI had the custom parameters read-only (M4).

## Decision

1. **The panel's place.** *Advanced options* is a collapsible section of the Video tab, after
   *Encoder settings*; its toggle is 03's "**Advanced…**". Not a dialog: the command drawer,
   sticky at the tab's foot, stays in view while an option changes (the demo's "the command
   preview updates at once"), and a validation issue's reveal reaches the option. Whether it is
   open is page state (`ui.advancedOpen`, `false` at start); `ui.reveal` of
   `video.advanced.<key>` or `video.custom_params` opens it. Inside it, the layout of 03: the
   search, *Show only changed* and the categories with their counts beside (or, in a narrow
   column, above) the shown category's options.
2. **Changed means stored.** The job keeps only changed options (`VideoSettings.advanced`). An
   option is changed while its key is in `video.advanced`, whatever its value: a value typed
   equal to today's default stays (it pins the option when the speed preset changes). ↺ and
   clearing a field remove the key. The category count is the number of the category's keys in
   `video.advanced`.
3. **"At once"** is the drawer's next answer: `jobs/plan` 250 ms after the last edit
   (`EDIT_DEBOUNCE`, M4), with no other action; each control writes its value into the job as
   soon as it is committed (a step, a choice, a typed number).
4. **The search** is the server's (`GET /api/definitions/encoders/{id}/options?q=`: the core's
   ranking over label, key, CLI name and help), asked for after a short pause in the typing, the
   newest answer only. The matches show in its order across the categories, each with its
   category; an empty query brings the category view back.
5. **Categories**: the core's order (above), then *Custom parameters*. A category without an
   option for the encoder is not listed. The names are the frontend's i18n keys; a category the
   frontend does not know is shown by its name, after the known ones.
6. **The default as placeholder text** (an empty field shows it; a switch or a choice names it
   beside the control): `fixed` → its value; `preset` → the value for the job's speed preset (the
   encoder's default preset when the job has none), naming the preset, and that the preset decides
   ("4 (preset slow)"); a preset missing from `values` → the option is not used at that preset;
   when the job's tune is one of the option's `tunes`, the text says the tune changes it;
   `encoder` → the encoder decides (with its note).
7. **A key the encoder does not define** (from an imported preset or job) is shown after the
   categories as a row with its value and ↺, so that its `encoder.option_unknown` error has a
   field.
8. **Custom parameters** are edited in the panel (no longer read-only): a typing run is one undo
   step; the text is checked with `POST /api/jobs/dry-run` 500 ms after the typing stops (as the
   Filters tab's custom filter, M8), and when the field opens with a text; only the newest text's
   answer counts. The dry run's errors show at the field with validation's issues at
   `video.custom_params`.
9. **Copy HDR metadata from source** applies the server's patch as one undo step (in a group, at
   the page's scope, like any edit). An empty patch says why: the source has no HDR metadata, or
   the encoder takes it from the frames (it has no such options).

## Consequences

- The skeleton (`ui.advancedOpen`, the section and the stubs) and the contracts are in
  [m9-breakdown.md](../m9-breakdown.md).
- A custom parameter FFmpeg refuses is shown at the field and in the dry run only: `jobs/validate`
  and *Add to queue* do not dry-run, so such a job can be queued and fails at the encode (as the
  custom filter, M8's L2). Recorded; an owner question.

## Plan changes

None yet.

## Task A — F-9 the advanced panel

(Task A writes this section.)

## Task B — F-9 custom parameters and Copy HDR metadata

(Task B writes this section.)
