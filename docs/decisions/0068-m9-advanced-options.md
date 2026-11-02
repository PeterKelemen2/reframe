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

- **Files**: `AdvancedOptions.vue` (the panel), `OptionRow.vue` (one option), `options.ts` (the
  category order, the default text, the JSON pointer of a key), `useOptionSearch.ts` (the search
  request, so that the real-server test can run it), in `components/video/advanced/`. The Video
  tab needed nothing more: the panel reads passthrough from the job itself.
- **Layout** (item 1): the search, *Show only changed* and the category list on the left, the
  shown category's options on the right; in a column narrower than 40rem the categories go above
  the options (side by side, wrapping), and in one narrower than 30rem a row's label goes above
  its control. The category with the selection has `aria-current`; a count shows only when it is
  above 0 (`data-count` always; the screen-reader text says "2 changed options").
- **Show only changed** filters the shown category's options (and the search's matches); the
  category list and its counts stay, so the counts say where to look. A category without a
  changed option says so. Custom parameters count as changed while the text is not empty (they
  stay shown); their category has no count.
- **Controls by type**: int and float are an `InputNumber` that writes on commit (Enter, Tab,
  blur, an arrow-key step), each commit one undo step; float digits are the step's (0.05 → 2).
  A bool is a switch that shows the default's value while the option is not set (off when the
  encoder decides) and writes the other value. An enum is `ChoiceSelect` with "Default: …" as its
  first entry (choosing it removes the key). A string is a text field that writes while typing,
  one undo step per typing run. Emptying a field removes the key (item 2). ↺ shows on a changed
  option only (03's mock-up), then the focus goes to the option's control.
- **The default text** (item 6) is the placeholder of a number or text field and the "Default:"
  entry of a choice; a switch, and every changed option, has it beside the control
  ("default: 4 frames (preset Slow)"). The preset is named by its label (the speed slider's
  "Slow"), values carry their unit, enum values their choice label, bools "on"/"off"; an
  `encoder` default reads "the encoder decides (auto, from the frame rate)".
- **Help**: ⓘ shows the option's help and its command-line name ("Command line: rc-lookahead"),
  so that a search by CLI name shows why it matched.
- **The search** (item 4) is asked 200 ms after the last key press; while it is on its way the
  status says "Searching…", then how many match. Choosing a category leaves the search. An
  encoder without options (one the definitions do not know) matches nothing without asking.
- **A reveal** of `video.advanced.<key>` selects the option's category, turns *Show only
  changed* off when the option is not changed, and clears a search whose matches do not hold it;
  `video.custom_params` selects *Custom parameters* the same way. A key the encoder does not
  define (item 7) is in the "Not options of <encoder>" group under the shown options, in every
  view, so its reveal needs nothing more.
- **Checked on the real server** (pinned FFmpeg n9.0.2, `hdr10`, preset `h265-mkv-1080p`:
  libx265 at `slow`): "psy" → psy-rd, psy-rdoq, nr-intra, nr-inter; "rc-lookahead" →
  rc-lookahead; "consecutive" (bframes' help) → bframes; B-frames 6 → `:bframes=6` in the
  drawer's command; `{rect: false, amp: true}` → the `encoder.option_inactive` warning at the amp
  row and in Summary, whose link opens the panel at amp; the `h265-nvenc-1080p` preset on this
  machine (no NVIDIA device) still shows `hevc_nvenc`'s schema (Basic first; one changed option
  from the preset in Rate control).
- **Not built**: a count on *Custom parameters*; a changed-option count in the collapsed
  section's header; a way to type a value outside an option's min/max (the field clamps it, so
  `encoder.option_invalid` comes only from an imported job).
- **Known, not mine**: the Video tab is wider than its column at 1280 px (5 px: the frame-rate
  mode buttons) and at 1024 px (the column is 228 px; the encoder settings' inline fields), with
  the panel closed too; the panel itself fits at 1920, 1440, 1280 and 1024 px.
- **Plan box**: 06 §F-9's `AdvancedOptions` box waits for task B's components in the panel.

## Task B — F-9 custom parameters and Copy HDR metadata

(Task B writes this section.)
