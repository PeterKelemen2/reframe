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

(Task A writes this section.)

## Task B — F-7 the Dimensions tab, the crop store, the crop overlay

(Task B writes this section.)

## Task C — F-7 `CropMagnifier`, the loupe, `CropCheckGrid`

Built in `components/crop/` (phase 1: unit tests against the store stubs; the browser checks
come after tasks A and B are merged).

- **The edge strips.** Each strip is a canvas of 384 × 96 CSS pixels (top, bottom) or 96 × 384
  (left, right): the crop line in the middle of its depth, 48 / *zoom* source pixels on each
  side (24, 12 or 6 at 2×, 4×, 8×), and along the line as many source pixels as fit (192, 96,
  48; the whole picture when it is shorter). Along the line the strip is centred on the pointer
  over the panel's picture (`preview.pointer`), else on the middle, and kept inside the picture.
  The pixels are drawn with `imageSmoothingEnabled = false`; everything outside the kept
  rectangle is tinted; the crop line is a 2-pixel stroke centred on the boundary between the
  last removed and the first kept pixel (so one canvas pixel on each side of it); the pixel grid
  is a 1-pixel line at every source pixel boundary. The label gives the source rows (top,
  bottom) or columns (left, right) shown, from 0 and inclusive (`Rows 10–33`). The strips and
  the loupe draw once per `requestAnimationFrame`, from the last pointer position.
- **The loupe** is a 160-pixel round canvas at a fixed 4× (40 × 40 source pixels around the
  pixel under the pointer) with the same tint and lines, placed in percent of `crop.sourceSize`
  in A's overlay layer, `pointer-events: none`. It loads the frame only on the Dimensions tab in
  manual crop. It does not follow the magnifier's zoom control (that is in the tab, the loupe in
  the panel; no shared state was added for it).
- **The frame loader** (`frames.ts`) fetches the signed PNG URL against the server's base URL
  (the desktop app's page is not on the server's origin) and decodes it with
  `createImageBitmap(blob, { colorSpaceConversion: "none" })`. One bitmap per frame **key**,
  shared by its users (the magnifier and the loupe show the same frame) and closed when the last
  one lets go: new links to the same frame after `preview.reload()` keep the decoded pixels. A
  failed fetch asks `preview.reload()` once; a second failure in a row shows *The frame could
  not be loaded.*
- **The check of all frames** fetches each strip frame's PNG once, shows it through an object
  URL and posts the same `Blob` to a module worker (`cropCheck.worker.ts`), which decodes it,
  reads each removed band through an `OffscreenCanvas` and answers the bands' luma variance and
  whether the frame loses content. The grid does not hold ten decoded bitmaps: at 4K that would
  be about 330 MB. The bands are the removed parts without overlaps (top and bottom full width,
  left and right between them). Luma is BT.709 from the PNG's RGB (`0.2126 R + 0.7152 G +
  0.0722 B`, 0–255). A frame loses content when **any** band's variance is **above 4**. Each
  frame shows the crop (tint and line) and the bars that crop detection found at its timestamp
  (`detection.samples`, matched by the exact timestamp: both come from `sample_times`), hatched,
  with the numbers in text; the badge says *Removes picture* with an icon. A click on a frame
  selects it in the panel (`preview.select`) and closes the dialog. Closing terminates the
  worker and revokes the object URLs; another crop or strip runs the check again.
- **Threshold calibration** (2026-11-02, the pinned FFmpeg n9.0.2, `ffmpeg -ss t -i
  letterbox.mkv -frames:v 1 -vf format=rgb24` for the ten strip times, the same formula in
  Python; to be confirmed on the server's PNGs in the browser):

  | Crop | Band | 0.2–1.8 s (letterbox) | 2.2–3.8 s (4:3) |
  |------|------|------|------|
  | 22 / 24 / 0 / 0 | top | 0.34–0.44 | 6 138–6 355 |
  | 22 / 24 / 0 / 0 | bottom | 0.33–0.46 | 6 598–8 610 |
  | 0 / 0 / 40 / 40 | left | 802–3 544 | 0.00 |
  | 0 / 0 / 40 / 40 | right | 7 475–7 910 | 0.00 |
  | 24 / 24 / 0 / 0 (2 rows into the picture) | top | 1 720–1 724 | 6 115–6 341 |

  The bars' noise stays under 0.5 and two picture rows in a 24-row band give 1 720, so 4 (a
  standard deviation of 2 luma steps) leaves a wide margin on both sides. Known limit: a band
  of flat picture (one colour) or of a very dark scene has a low variance and is not flagged.

## Task D — F-8 the Filters tab

(Task D writes this section.)

## Task E — F-15 Settings → Preview, the preview clip

(Task E writes this section.)

## Task F — F-17 flow 4

(Task F writes this section.)
