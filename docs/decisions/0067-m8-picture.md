# 0067 — M8, picture: the preview panel, crop, filters and the preview clip

- Status: accepted
- Date: 2026-11-02
- Steps: F-7, F-8, F-15 (Preview), F-17 (flow 4), S-2 (one route), C-12 (the preset diff)

## Context

M8 ([08 §M8](../plan/08-roadmap.md#m8--picture-preview-crop-filters)) builds the picture UI of
[03 §Dimensions](../plan/03-features.md#dimensions), [§Filters](../plan/03-features.md#filters)
and [§Preview](../plan/03-features.md#preview) on the core of
[0033](0033-preview-frames-crop-and-clips.md) and the preview routes of
[0049](0049-s2-system-fs-settings-sources-preview.md). Its tasks and waves are in
[m8-breakdown.md](../m8-breakdown.md). Before any agent, the lead checked the API (2026-11-02,
on `m7-batch-season` d3c2467, a real `reframe-server` from `scripts/dev-server.py` with the
pinned FFmpeg n9.0.2 and the fixtures `letterbox`, `hdr10`, `hdr10-4k`, `multitrack`,
`anamorphic`; scripts in the lead's scratchpad `lead/api_check.py`, `clip_check.py`,
`clipframes_check.py`, `play_check.mjs`):

- **There**: `preview/frames` (10 frames of `letterbox` in 0.16 s; of `hdr10-4k` in 3.7 s,
  with the note "The source is HDR10: a PNG cannot hold HDR, so the frames are tone mapped to
  SDR for display with zscale + tonemap."), the signed PNG URLs (`ETag` = the key),
  `preview/render` (the source and the output frame; 4K: 0.76 s), `preview/cropdetect` (a task;
  `letterbox`: samples 0.2–1.8 s `22 / 24 / 0 / 0`, 2.2–3.8 s `0 / 0 / 40 / 40`, automatic
  `22 / 24 / 0 / 0` on 5 of 10 frames, conservative `0 / 0 / 0 / 0`, the note "The frames
  disagree: …"; `hdr10-4k`: 3.0 s), `preview/clip` (a task; H.264 in MP4 and MKV, HEVC and AV1
  clips made from the built-in presets), the clip link (`206` for `bytes=0-99`,
  `video/x-matroska`), `preview/cache` and Settings → Preview (`sample_frames` 10,
  `cache_size_mb` 1024). `jobs/geometry` gives the pipeline header and the source's chroma grid.
  The source colour box has its data in the probe (`VideoStream.color`, `bit_depth`, `hdr` with
  the mastering display and MaxCLL). Colorspace BT.709 on `hdr10` without tone mapping gives the
  warning `filter.hdr_without_tonemap` with the fix *Enable tone mapping*.
- **Fixtures**: `letterbox.mkv` (2 s of 2.39:1 letterbox, then 2 s of 4:3 pillarbox) is the
  fixture with changing aspect ratios of demo point 2: automatic and conservative differ.
  `hdr10.mkv` (BT.2020 PQ, HDR10 metadata) is the HDR source of demo point 3.
- **Playback in the browsers Playwright runs** (headless, `play_check.mjs`, each clip 2 s of
  `letterbox`, `loadeddata` then 0.7 s of `play()`):

  | Clip | Chromium 156.0.8078.4 | Firefox 157.0 |
  |------|------|------|
  | H.264 in MP4 (`very-fast-1080p30`) | plays | plays |
  | H.264 in MKV (`h264-mkv-1080p`) | plays | plays |
  | HEVC in MKV (`h265-mkv-1080p`) | `MEDIA_ERR_SRC_NOT_SUPPORTED` (`DEMUXER_ERROR_NO_SUPPORTED_STREAMS`) | plays |
  | AV1 in MKV (`av1-mkv-2160p-4k`) | plays | plays |

  `canPlayType('video/mp4; codecs="hvc1…"')` is `""` in Chromium, `"probably"` in Firefox.
- **Missing**: (1) frames of a clip: the encoded frame compare
  ([03 §Preview](../plan/03-features.md#preview)) decodes the clip, and no route did that
  (`preview/frames` takes a source id); (2) nothing writes a detected crop into a job: a job in
  automatic mode without `rect` is encoded uncropped with the info issue
  `dimensions.crop_not_detected`; (3) a detected `rect` would mark the job *modified* against
  its preset (`presets/diff` compared `dimensions.crop.rect`).

## Decision

1. **Frames of a clip** (S-2, the lead in wave 0): `POST /api/preview/clips/{id}/frames
   {timestamps}` decodes frames of a cached clip and answers as `preview/frames` does (it waits;
   a client that goes away cancels the task; `404 preview.unknown_clip` when the clip is not in
   the cache). The clip's frame at `t` is the source frame at `start + t` (0033 §6); the frames
   say `kind: "source"` (they are the clip file's). Checked on the real server: an HEVC clip of
   `letterbox` decoded in 0.06 s. Tests: `test_preview.py::test_frames_of_a_clip_are_decoded_from_the_clip`
   (a cropped clip gives 320×134 frames), `::test_frames_of_a_clip_not_in_the_cache_is_404`.
2. **A detected crop is not a change against the preset** (C-12, the lead in wave 0):
   `presets.diff` leaves out `dimensions.crop.rect` when the template's and the preset's crop
   modes are the same automatic or conservative mode: the rectangle is a detection result, not a
   setting. A manual rectangle still counts. Tests: `test_diff.py::test_a_detected_crop_is_not_a_change`,
   `::test_a_manual_crop_is_a_change`.
3. **How a detected crop enters a job.** The crop store (task B) runs crop detection on the
   shown file once per page (the strip's sample times, Settings → Preview's count) and, for a
   single job in automatic or conservative mode without a `rect`, writes the mode's rectangle
   with `editor.amend` (new, the lead in wave 0): applied without an undo step, so an undo never
   takes it out and the steps around it still apply (the history holds patches); it ends a
   coalescing run. This happens whichever tab is shown (the workspace starts the crop store).
   A switch between automatic and conservative is one undo step that carries the other
   rectangle. In a group the shown file's detection is shown, not written: a group's template
   detects the crop per file (`crop_policy`). Tests: `editor.test.ts` "amends the job without an
   undo step…", "ends the coalescing run at an amend…", `editor.group.test.ts` "amends nothing in
   a group…".
4. **Playback decides, not the codec name.** The preview clip plays in a `<video>`; when the
   element reports an error, the panel shows the encoded frame compare instead. *Compare frames*
   is offered for every clip. *Open in external player* opens the signed clip URL through
   `platform.openExternal`.
5. **The preview panel follows the tab.** On Dimensions it shows the source frame with the crop
   overlay; on Filters, the split before / after; on the other tabs it keeps the user's view
   mode. It is shown by default now (it was collapsed while it was a placeholder).
6. **`←` / `→` move through the frames while the focus is in the preview panel** (not in a text
   field, not on a crop handle, where the arrows move the edge). Not a global shortcut: tabs,
   sliders and segmented controls use the arrow keys.
7. **Which frames are asked for.** The strip of the shown file is asked for on any tab (crop
   detection and the magnifier use its frames); the output frame only while the panel is open
   and its view mode needs one, 250 ms after the last edit, the newest answer only (an older
   request is aborted, which cancels its task on the server).
8. **The magnifier's place.** The main frame with the crop lines, the drag handles and the loupe
   is the preview panel's; the four edge strips, the zoom, the frame navigation and *Check crop
   on all frames* are in the Dimensions tab under the crop inputs (manual mode).

## Consequences

- The routes, the preview store (`stores/preview.ts`) and the crop store (`stores/crop.ts`) are
  the contracts of [m8-breakdown.md](../m8-breakdown.md).
- A job that is never shown in the editor (another file of *Add all*, the files of a group) is
  queued without crop detection: automatic crop gives no crop and the info issue
  `dimensions.crop_not_detected` (as the CLI; 0024's follow-up). Recorded in "Where M8 ended".

## Plan changes

- [06 §S-2](../plan/06-web-app.md#s-2-rest-api), Preview: the row of
  `POST /api/preview/clips/{id}/frames`.

## Task A — F-7 the preview panel, `FrameViewer`, `SplitCompare`

- **Store members added** (the contract's members are as the skeleton has them): `sought` (the
  frame of the last seek), `seeking`, `seekNote` (why a seek shows no frame: the server's note or
  the problem's title), `renderNotes` (the render's notes), `panelOpen` (set by `PreviewPanel`
  from its `collapsed` model; `false` when it unmounts) and `imageFailed(frame): boolean`.
- **When the output frame is out of date.** Its key is the current frame's key and the job's
  `source`, `dimensions`, `filters`, `video` and `subtitles` (what the server's output graph
  reads); an audio, chapter or naming edit keeps the frame. A new frame, view mode, opened panel
  or job asks at once; an edit 250 ms after the last one.
- **An image that does not load** (a link expires after 300 s) asks again once per frame shown:
  a strip image reloads the strip (one request for all thumbnails), the seek frame is asked for
  again, the output frame is rendered again. A second failure of the same frame shows "The frame
  could not be loaded."; choosing another frame or seeking allows a new attempt, so a link that
  never loads cannot ask in a loop.
- **The tab and the view mode.** `PreviewPanel` keeps the view the user chose on a tab without
  its own view (item 5) and shows it again there; a view chosen on Dimensions or Filters is not
  remembered.
- **The arrow keys** (item 6) are left alone when another handler took them (`defaultPrevented`),
  with a modifier key, in a text field, on a slider (`role="slider"`, `input[type=range]`, the
  split slider) and on or inside an element with `data-crop-handle` (task B's handles).
- **Sizes.** *Fit* is the panel's width, at most 60 % of the window's height; 100 % and 200 %
  are 1 and 2 CSS pixels per picture pixel (output pixels in the Output, Split and Side views).
  The overlay layer is the picture box itself (`aspect-ratio` of the frame), so a percentage of
  the layer is the same percentage of the source picture; `preview.pointer` is the pointer in
  source pixels.
- **`SplitCompare`** draws `before` in an SVG whose view box is the cropped and turned source
  (the crop from `geometry.crop`, then `filter_rotation` clockwise, then the horizontal flip),
  stretched to the output's box, so both halves show the same picture area. Without a geometry
  (the crop store's stub) the source is shown whole. The split is a native range input over the
  picture (arrow keys, Home, End). An image that fails emits `failed`.
- **Checked on the real server** (pinned FFmpeg n9.0.2, `scripts/dev-server.py`): 10 `letterbox`
  frames without a `count` in the request; a seek to 99 s on `letterbox` is a `422` with the title
  "No frame of letterbox.mkv could be made: FFmpeg gave no picture at this time (after the last
  frame?)" (a single timestamp without a picture fails the task; 0033 §2), shown under the seek
  field; a custom filter FFmpeg cannot use gives no output frame and its reason; a render of
  `hdr10-4k` without tone mapping repeats the source's HDR note and adds "The output stays HDR:
  …" (shown once each); an aborted strip request of `hdr10-4k` (cold cache) is cancelled on the
  server (`GET /api/tasks` lists the `frames` task as `cancelled`).
- **Not built**: a time field in `h:mm:ss` (the seek field takes seconds), previous / next
  buttons (the strip and the arrow keys do it), wheel or pinch zoom.
- **Plan box**: 06 §F-7's `FrameViewer` box needs task B's drag handles in the overlay layer; it
  is left for the lead.

## Task B — F-7 the Dimensions tab, the crop store, the crop overlay

Built: `stores/crop.ts`, `components/editor/tabs/DimensionsTab.vue`, `components/dimensions/`
(`PipelineHeader`, `CropSection`, `SizeSection`, `CropOverlay`, the pure `grid.ts` and
`header.ts`), `i18n/messages/en/dimensions.json`. Choices where the plan leaves one:

1. **The client applies the core's crop rules.** `grid.ts` `appliedCrop` is `_crop` of
   `reframe.dimensions` (snap down, the right or bottom edge grown on an off-grid frame, no crop
   on an axis that is removed or left with less than one step; interlaced doubles the vertical
   step; a 90° / 270° display matrix swaps the sides and the steps), tested with the core's own
   cases. `crop.rect` is that crop of the job's rectangle (or, in a detected mode without one,
   of the shown file's detection).
2. **A manual crop is stored as the server applies it.** `setRect` first keeps each axis at
   least one grid step wide (the edge that moved gives way, so a dragged edge stops at the other
   one), then applies the rules above and stores the result. The server never changes it (no
   `dimensions.crop_snapped`; checked against the real server). `snapNote` names each moved
   value and why: `Top 141 → 140 (4:2:0 chroma grid)`, `… (interlaced 4:2:0 chroma grid)`,
   `Right 0 → 1 (the width must be a multiple of 2)`, `Bottom 500 → 172 (kept inside the
   picture)`.
3. **Modes.** None stores `{mode: "none", rect: null}`; Manual starts from `crop.rect` (zeros
   without one). In a group Manual also starts from what is shown, the shown file's detection
   included: it is the user's manual crop for the group from then on. Automatic and conservative
   in a group store the mode with `rect: null` (item 3 of this record).
4. **The pipeline header** is 03's line from `pipelineOf` (the Summary's): `Source W×H (ratio,
   square | pixel aspect n:m) → Crop W×H → Rotate N°, Flip → Output W×H · aspect · square
   pixels | pixel aspect n:m`. The crop step is left out when nothing is cropped (as on the
   Summary); the rotation is the total one, as on the Summary. A ratio is named (`16:9`) when it
   is one of the common ones, else written as `2.39:1`. Amber when `upscaled`; red when
   `jobs/geometry` fails or a `dimensions.*` issue is an error; a sentence under the line says
   which, so colour is not the only cue.
5. **The detection line**: Automatic `Detected 22 / 24 / 0 / 0 on 5 of 10 frames`;
   Conservative `Black on every frame: 0 / 0 / 0 / 0 (10 frames)`; then the detection's notes.
   A failed detection shows its reason with *Detect again* (`crop.detect()`); in a group a line
   says that each file detects its own crop when it is queued.
6. **Inputs.** The edge inputs commit on `change` (Enter, Tab, leaving the field, the arrow
   keys of the number input, whose step is the chroma step); a run of edits of one edge is one
   undo step. Exact width and exact height start from the current output size; Custom PAR starts
   at 1:1; the advanced part opens when one of its fields is revealed.
7. **Fit within boxes** are 16:9 like the names' usual frames: 2160p 3840×2160, 1440p
   2560×1440, 1080p 1920×1080, 720p 1280×720, 576p 1024×576, 480p 854×480 (HandBrake's
   resolution limits use 720×576 and 720×480; with square pixels those boxes give a 16:9 film
   404 lines, which is not "576p"). Any other box is *Custom W×H*.
8. **The handles** (`CropOverlay`, in A's overlay layer, positioned in percent of
   `crop.sourceSize`): one `role="slider"` per edge with `tabindex="0"`, `data-crop-handle="top"`
   (`bottom`, `left`, `right`), an accessible name (`Top crop edge`) and value. The arrow keys
   move the edge in the arrow's direction, one chroma step per press, 8 steps with Shift; every
   arrow key on a handle is stopped there (`preventDefault`, `stopPropagation`), so the panel's
   `←` / `→` never also step the frame. A drag is one undo step (a coalesce key per drag,
   `editor.endCoalescing()` when the pointer is let go); a run of key presses on one handle is
   one (a key per edge, ended when the handle loses the focus).

Tests: `stores/crop.test.ts` (17), `components/dimensions/grid.test.ts` (16),
`header.test.ts` (4), `CropOverlay.test.ts` (4), `components/editor/tabs/DimensionsTab.test.ts`
(7), and the real-server `components/dimensions/dimensions.server.test.ts` (7: the detection of
`letterbox` and its amend without an undo step and without *modified*; the header against
`jobs/plan` for a manual crop, a rotation, a flip, an exact width, an upscaled exact height with
a 270° turn and a custom pixel aspect).

## Task C — F-7 `CropMagnifier`, the loupe, `CropCheckGrid`

(Task C writes this section.)

## Task D — F-8 the Filters tab

(Task D writes this section.)

## Task E — F-15 Settings → Preview, the preview clip

(Task E writes this section.)

## Task F — F-17 flow 4

(Task F writes this section.)
