# 0110 — The crop review works in every crop mode

- Status: accepted
- Date: 2026-11-25
- Steps: F-7, C-10

## Context

`03-features.md` (Dimensions, 3. Crop) puts the crop magnifier and *Check crop on all frames*
under "manual mode", and the step's "Done when" says "Manual crop shows the magnifier". The
build followed it: `CropSection` mounted `CropMagnifier` (with the check) only in Manual.

The design critique of the Workspace (2026-11-25, P1 "Output truth") found the result in the
running app with `letterbox.mkv` (2 s of 2.39:1 letterbox, then 2 s of 4:3):

- Automatic, the default, crops `22 / 24 / 0 / 0`. The magnifier and the check, which show that
  this crop removes picture on the five 4:3 frames, were not there. To look, the user had to
  choose Manual, and that marks the preset *modified*.
- The crop detection's note "The frames disagree: automatic 22 / 24 / 0 / 0, conservative
  0 / 0 / 0 / 0 (top / bottom / left / right)." was a muted bullet. The status bar said
  "No issues".
- The crop values had no edge names: "22 / 24 / 0 / 0".

The crop overlay on the preview was already drawn in Automatic and Conservative (read-only,
`CropOverlay` shows it whenever the job changes the picture). On a letterboxed frame its tint
falls on the black bars, so it is easy to miss; on the 4:3 frames it covers picture.

Positioning point 4 in `PRODUCT.md` is "A crop preview you can trust".

## Decision

1. **The magnifier and *Check crop on all frames* show in Automatic, Conservative and Manual**
   (not in None, and not before the detected crop is known). Outside Manual they are read-only:
   a note says "Choose Manual to move the edges." Manual adds only the inputs and the handles.
   Looking (zoom, pixel grid, frame steps, the check) never changes the job, so it never marks
   the preset *modified*.
2. **Frames that disagree are a warning issue**, made by the client:
   `dimensions.crop_frames_disagree` at `dimensions.crop`, when the job is a single file in
   Automatic and its crop removes more on some edge than the conservative crop (what is black
   on every sample frame). The message names both crops; the fix *Use Conservative* replaces
   the crop with the conservative one (one undo step); the issue list adds *Check crop on all
   frames*, which goes to the Dimensions tab and opens the check. The Summary's Issues card,
   the status bar's count and the crop mode field show it like a server issue.
   - It is a client issue because the server's job does not hold the detection: `CropSettings`
     has the mode and the rectangle only, and `jobs/validate` does no I/O. Adding the detection
     to the persisted job settings only to warn would put per-file measurements into presets
     and queue documents. The validation store keeps the server's issues and the issues that
     client stores add (`addLocal`) side by side; the server's answer replaces only its own.
   - Conservative gets no warning: its crop is black on every frame. It shows a plain line
     instead: "Some frames have more black bars: T 22 · B 24 · L 0 · R 0 on 5 of 10 frames."
   - A group gets no such issue in the editor: its files are detected when the group is queued.
3. **The core's crop detection no longer writes the "frames disagree" note.** The client tells
   it from `auto` and `conservative`, in the user's language and with the edge names; the note
   would repeat the warning beside it. No other code reads `CropDetection.notes`, and crop
   detections are not stored.
4. **Crop values always name their edges**, in one order, top, bottom, left, right (the order
   of the inputs, `CropRect` and the plan): `T 22 · B 24 · L 0 · R 0`, one i18n string
   (`dimensions.crop.rect`) with a no-break space between each letter and its value. The
   detection lines, the check's per-frame bars and the warning use it.

## Consequences

- The crop review is reachable without changing the job. Manual is for changing the crop only.
- A frame disagreement is counted in the status bar and the Summary, and it does not block the
  queue (a warning).
- A season group's files can still disagree at queue time without a warning; the batch crop
  run (`batch/service.py`) could raise one per row. Not done here.
- No persisted document changes: no schema version, no migration.

## Plan changes

- `docs/plan/03-features.md`, Dimensions → 3. Crop: the detection example with edge names, the
  magnifier and the check in every crop mode (read-only outside Manual), the disagreement
  warning, and the "Done when" line.
- `docs/plan/06-web-app.md`, F-7: the crop overlay in every crop mode with handles in Manual,
  the magnifier and the check in every crop mode.
