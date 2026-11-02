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

(Task C writes this section.)

## Task D — F-8 the Filters tab

(Task D writes this section.)

## Task E — F-15 Settings → Preview, the preview clip

(Task E writes this section.)

## Task F — F-17 flow 4

(Task F writes this section.)
