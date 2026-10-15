# 0033 — Preview frames, crop detection and preview clips (C-10 picture)

- Status: accepted
- Date: 2026-10-15
- Steps: C-10, Q-3 (and F-7, F-8, S-2, which use the results)

## Context

[05 §C-10](../plan/05-core.md#c-10-preview-and-analysis-tasks) asks for frames ("N evenly
spaced timestamps … fast seek … a PNG of the source frame, and of the output frame with the
job's filter graph applied … cache key: source fingerprint + timestamp + settings hash … LRU
with a size limit"), crop detection ("`cropdetect` on each sample (round=2, a limit that suits
HDR/PQ black levels)") and a preview clip ("encode N seconds from timestamp T with the full
plan"). [03 §Preview](../plan/03-features.md#preview) and [03 §Dimensions → Crop](../plan/03-features.md#3-crop)
add the frame strip, the Source / Output views, the encoded frame compare and the crop
magnifier (full-resolution source pixels). The plan does not say what the settings hash
covers, how frames and clips share the cache, how an HDR picture becomes a PNG, which
`cropdetect` limit, what a missing frame does, or how a 2-pass job makes a clip.

FFmpeg n9.0.2 facts this record relies on are in `testdata/README.md` ("Preview frames, crop
detection and clips (C-10)") and in the tests of `packages/reframe/tests/preview/`.

## Decision

### 1. Cache keys and the LRU

- **Frame key** = `<source>-<milliseconds>-<settings>` (also the file name,
  `<cache dir>/frames/<key>.png`): `source` = 16 hex digits of a hash of the absolute path,
  the size and the modification time in nanoseconds; the timestamp in whole milliseconds (the
  frame is taken at exactly that time); `settings` = 16 hex digits of a hash of the **frame
  recipe** (kind, the colour tagging, the whole filter chain, the PNG options) and the
  **FFmpeg build** (path, version, library versions), plus a key format number. Hashing the
  chain instead of job fields covers everything that changes the picture (crop, size, pixel
  aspect, filters and their implementation, the encoder's pixel format, libplacebo or
  zscale) and nothing that does not (audio, names, rate control): two jobs with the same
  picture share their output frames. Not covered: a changed shared library (libplacebo,
  libzimg) under the same FFmpeg version.
- A key from a URL is accepted only in exactly this form, so it can never name another file.
- **One budget for frames and clips**: Settings → Preview has one "cache size limit"
  (`cache_size_mb`, 1 MB = 2**20 bytes). The least recently used files of both folders go
  first. A file's modification time is its last use: every hit (`frame_path`, `clip_path`, a
  task that finds the file) sets it to now.
- The LRU runs after each task. It never removes the files that task made or used, nor a file
  used in the last 30 s (another task's fresh result that its client has not fetched yet). So
  `cache_size_mb = 0` keeps only the latest results. Temporary files are removed after an
  hour (a crash left them).
- `reframe.preview.clear_cache(ctx)` and `cache_size(ctx)` are for Settings → Preview
  ("clear cache"); the facade does not expose them yet (reported to the lead).

### 2. How a frame is made

- **One FFmpeg run per timestamp** makes every kind that is not cached: `-ss T` before `-i`
  (fast seek; FFmpeg still decodes from the keyframe before T and gives the first frame at or
  after T, pixel-identical to decoding everything), a `split` when the source and the output
  frame are both made (one decode: 0.65–0.75 s for both 4K frames instead of 1.17–1.28 s in
  two runs), one `-frames:v 1` PNG per kind, written under a temporary name and renamed when
  complete. FFmpeg negotiates the pixel format across a `split`: a branch that ends in a bare
  `format=rgb24` made it convert to RGB before the split, and the other branch's crop and scale
  then ran on RGB. Each branch therefore converts with its own `scale`, and a test checks that
  both pictures of one run equal one-kind runs (crop, denoise, sharpen, Bob, HDR kept, tone
  mapping). An output chain whose first filter takes only RGB (a custom `lutrgb`) would still
  move the conversion before the split. **Two timestamps at a time** per task (10 frames of the 4K HDR
  fixture: 5.0 s one at a time, 4.0 s two, 3.7 s three).
- **Full resolution**, the picture as FFmpeg decodes it (display matrix applied, decision
  [0009](0009-dimension-maths-conventions.md)); an anamorphic source keeps its stored pixels
  (720x480, the PNG carries the SAR).
- **Colour**: a source that does not say its colour gets C-7's assumed colour first
  (`setparams`, the same values as the graph: BT.709 for HD), and the RGB conversion is an
  explicit `scale` (`flags=bicubic+accurate_rnd+full_chroma_int`, then `format=rgb24`).
  FFmpeg converts an untagged frame with BT.601, and after an input seek it converted the
  frame **before** a `setparams` that came first in the chain, so only an explicit `scale`
  gives the colours a player shows.
- **PNG**: 8-bit RGB, compression level 3 with the default Paeth prediction (a grainy 4K
  picture: 0.45 s and 8.9 MB; level 6: 0.94 s and 8.5 MB; level 1: 0.34 s and 13.9 MB).
- **A timestamp without a picture** (after the last frame: FFmpeg exits 0 and writes nothing;
  a decoding error) is left out with a note (`No frame at 99.000 s: …`). The task fails only
  when no source frame at all could be made.

### 3. HDR for display

A PNG cannot hold PQ or HLG. An HDR source frame is tone mapped with the filters of the Tone
mapping filter's default preset (`tonemap_filters`, new in `command/filtergraph.py`, the same
function C-7's graph uses): `libplacebo` (BT.2390, peak detection) when its run test passed
(decision [0021](0021-libplacebo-run-test.md)), else `zscale` + `tonemap` (Hable). The output
frame of a job whose output stays HDR (no Tone mapping or Colorspace filter) is mapped the
same way. `FrameSet.notes` says which. A build with neither shows the HDR signal unmapped
(pale), with a note. Dolby Vision profile 5 has no HDR10 base layer: without libplacebo
(which applies the RPU) its colours are wrong, and the note says so (not verified: there is
no profile 5 fixture). Frames do not wait for the encoder detection: before its first result
the capability snapshot has no libplacebo, so the first frames of a first start use zscale;
the key changes with the chain, so later frames use libplacebo.

### 4. Output frames

- The job's video filter graph is made by the functions C-7's builder uses
  (`source_geometry`, `compute_geometry`, `build_video_graph`, `filter_available`) with the
  encoder's **software** pixel format as the format stage (a hardware encoder's
  `format=nv12,hwupload` becomes `format=nv12`); a test compares it with the plan's
  `-filter:v:0` for 24 jobs (crop, size, pixel aspect, rotation, flip, deinterlace, detelecine,
  denoise, deblock, sharpen, chroma smooth, grayscale, custom, colorspace, tone mapping, both
  tone mappers), and another with a lossless clip of the job: the encoded frame is the output
  frame, pixel for pixel.
- **Burned-in subtitles are not drawn** on output frames (a note says so): the `subtitles`
  filter reads the whole source file for every frame (a 30 GB remux would take minutes per
  frame), and a bitmap subtitle that started before the seek point would be missing. A
  preview clip shows them (it runs the full plan).
- A copied video (passthrough): the output frames are the source frames (same key, a note).
- A job that cannot be planned (an unknown encoder, a filter this build cannot run): the source
  frames are made, the output frames are left out with a note. A job for another file fails
  the task.

### 5. Crop detection

- One decoded frame per sample, the timestamps of the frame strip (same count, same
  function), `cropdetect=limit=0.094118:round=2:skip=0`:
  - `skip=0`: the default skips the first two frames, so one frame gave no result;
  - `limit=0.094118` (24/255) is a **fraction of the full range**, which FFmpeg scales by the
    bit depth (24 at 8-bit, 96.3 at 10-bit). Measured black: SDR bars 16 (8-bit), PQ bars 64
    (10-bit, YAVG 63.9, ringing up to 91 next to the picture); limited-range black is the same
    fraction of the range in both, so the limit is the same distance above black (in PQ about
    0.03 cd/m²). An absolute `limit=24` found no bars at all in the 10-bit PQ letterbox. The
    value is written explicitly so a changed FFmpeg default cannot change it (n8.1.3 and
    n9.0.2 both default to 0.094118).
  - `round=2`: `cropdetect` rounds x and y up to even and the size down to even (an odd
    `round` is doubled, `round=1` means 16); C-5's `compute_geometry` snaps to the source's
    grid.
- The first `crop=w:h:x:y` line is the sample frame (`-frames:v 1` lets a second frame through
  the filter); it becomes top `y`, left `x`, right `W − x − w`, bottom `H − y − h` on the
  picture as decoded (90°/270° display matrices swap W and H). A black frame (negative `w` /
  `h`) or a sample that could not be decoded is `None` and does not vote; notes count them.
  When every sample fails, the task fails.
- `detect_crop_consensus` (C-5) gives `auto` and `conservative`; `auto_frames` counts the
  samples equal to `auto`. On `letterbox.mkv` (5 letterbox and 5 pillarbox samples) the tie
  goes to the letterbox (fewer edge pixels): automatic 22 / 24 / 0 / 0 on 5 of 10 frames,
  conservative no crop.

### 6. Preview clip

- A copy of the job with the range `start … start + seconds` (to the end when that is past
  it), the output `<cache dir>/clips/<id>.<ext>` in the job's container, and **no in-place
  edit** (a preview never writes the source; a plan that would write outside the cache is
  refused). Validation first, with the queue's rule: an `encoder.checking` issue waits for
  the detection; any error fails the task with the first message.
- C-7's plan runs step by step through `run_streaming` with the task's cancel token: the
  loudness analyse steps, **both passes of a 2-pass job** (the clip shows the job's rate
  control; a 1-pass ABR clip would spend bits differently), mkvpropedit, the rename. Progress
  is the queue's weighted `ProgressTracker`. Plan files, statistics files and the partial
  output are removed afterwards, also after a failure or a cancel.
- **The id** is 32 hex digits of a hash of the source file version, the plan steps (with a
  placeholder output name) and the tool builds: the same request returns the cached clip at
  once. The clip's timeline starts at 0: its frame at `t` is the source frame at `start + t`
  (the encoded frame compare: `Reframe.sources.frames(clip.path, timestamps=[t])`).

### 7. The Q-3 budget on long GOPs

Measured in `tests/preview/test_benchmark.py` (through the facade, libplacebo, one frame per
task, 11 timestamps; 12 threads): load average 3.4–4.2 (other agents' test runs): cold
678–844 ms, mean 742 ms (budget 2 s); cached 1.4 ms mean, 3.8 ms max (budget 50 ms);
`frame(key)` 38 µs. Load average 12–13: cold 699–920 ms. Load average 19: cold up to 2.4 s,
over the budget; the test then reports the run as skipped ("the machine is busy"), because a
budget measured on an overloaded machine says nothing about a normal desktop. The cold time grows with the distance from the keyframe
before T: `hdr10-4k` (keyint 48) decodes at about 165 frames/s (120 frames in 0.73 s), so its
worst case (47 frames) is about 0.3 s of decoding. A source with a 250-frame GOP (x265's
default keyint at 24 fps, 10 s) needs up to about 1.5 s more and is close to the 2 s budget; a
source with longer GOPs (keyint 500 or "infinite") is over it. The budget holds for typical
disc and streaming sources (GOPs of 1–10 s at 24 fps), not for every file.

## Consequences

- S-2 maps `POST /api/preview/frames` to `sources.frames(path, count | timestamps)`,
  `GET /api/preview/frames/{key}.png` to `sources.frame(key)` (the key is content-addressed:
  it can be the ETag), `POST /api/preview/render {job, timestamp}` to
  `sources.frames(job.source.path, timestamps=[t], job=job)` (the `output` frame),
  `POST /api/preview/cropdetect` and `/clip` to the tasks, `GET /api/preview/clips/{id}` to
  `jobs.preview_clip_path(id)`.
- F-7's crop magnifier gets full-resolution 8-bit RGB PNGs of the decoded picture; F-8's
  split view gets output frames rendered by the same graph as the encode.
- Revisit: subtitle burn-in on output frames (an extracted subtitle stream would make it
  cheap); a separate budget for clips if users keep many 4K clips; frame workers per CPU.

## Plan changes

None: the plan's bullets are built as written; this record settles what they leave open.
