# 0032 — Analysis scans (C-10): PGS forced flags, covered time, the DTS-HD MA and PGS fixtures

- Status: accepted
- Date: 2026-10-15
- Steps: C-10 (bitrate scan, subtitle scans, loudness measure), Q-2.1 (test media)

## Context

[05 §C-10](../plan/05-core.md#c-10-preview-and-analysis-tasks) lists three analysis tasks:
"Bitrate scan: packet sizes for one stream (`-show_entries packet=size`) → average bitrate",
"Subtitle scans: event counts. PGS forced-flag count (decode with `forced_subs_only`)" and
"Loudness measure (`loudnorm` print_format=json)". [09 §Test media](../plan/09-quality-and-release.md#test-media)
says "PGS comes from recorded probe JSON only (FFmpeg has no PGS encoder)", and
[08 §M6](../plan/08-roadmap.md#m6--tracks-and-metadata) demo 1 needs "A DTS-HD MA track with
no bitrate in the file", which FFmpeg cannot make either (its `dca` encoder writes a DTS core
only). The facts below were checked on 2026-10-15 with FFmpeg n9.0.2 (Arch package and the
pinned BtbN build; the DTS-HD MA fixture also with n8.1.3) and are recorded in
`testdata/README.md` "Analysis scans".

## Decision

### 1. PGS forced events: read the forced flag, do not decode

A decode with `forced_subs_only` **cannot** count the forced events of a PGS track. FFmpeg's
`pgssubdec` still returns every display set and only leaves the palette of a non-forced
composition object empty (`display_end_segment`). On the PGS fixture (6 events, 2 forced):

```
$ ffprobe -v error -select_streams 1 -show_entries subtitle=pts_time,num_rects -of csv=p=0 pgs.mkv
$ ffprobe -v error -forced_subs_only 1 -select_streams 1 -show_entries subtitle=pts_time,num_rects -of csv=p=0 pgs.mkv
```

both print the same 12 lines (`num_rects` 1, 0, 1, 0, …: show, clear). VobSub is different:
`dvdsubdec` drops every subpicture that does not start with the forced command (`0x00`), so
there the plan's decode works (3 subpictures, 2 forced: 3 lines without the option, 2 with it).

So the subtitle scan:

- **PGS**: one ffmpeg copies every requested PGS track to a `.sup` file
  (`-map 0:<index> -c copy -f sup`) in a temporary folder under `<cache dir>/scans`, removed
  when the task ends (also on cancel: the reader thread stops on the cancel token first, so
  Windows can remove the file); `reframe.analysis.subtitles.read_display_sets` reads the
  segment headers and the presentation compositions only. A display set is **forced** when its
  PCS has a composition object with the flag `0x40`, the bit the decoder checks.
- **VobSub**: the decode as planned, one ffprobe per track:
  `ffprobe -v error -forced_subs_only 1 -select_streams <i> -show_entries subtitle=pts_time -of compact=p=0`.
- **Other tracks** (text, DVB): no forced count (`forced_event_count = None`).

### 2. What an event is

- Every track but PGS: one **packet** is one event, counted for all requested tracks by one
  ffprobe (`-select_streams s -show_entries packet=stream_index,pts_time`). That is what
  mkvmerge's `NUMBER_OF_FRAMES` counts, so a measured count and a statistics-tag count of the
  same track agree.
- PGS: one **display set** is one event. In Matroska that is one block (FFmpeg's muxer merges
  the segments with `pgs_frame_merge`), the same as the packet count and `NUMBER_OF_FRAMES`; in
  M2TS every segment is a packet, so a packet count would count each event about four times.
  A PGS subtitle is two display sets (show, then clear), so the event count of a PGS track is
  about twice its number of subtitles; the forced count counts the forced *show* display sets.

### 3. Bit rate: the covered time

Bit rate = 8 × the bytes of the stream's packets / the time the packets cover:

1. the earliest packet time (`pts_time`, else `dts_time`) to the latest packet end
   (time + `duration_time`) — right for decode order (B-frames) and for a stream that starts
   late or ends early;
2. no packet durations: the span of the packet times plus one average interval;
3. fewer than two packet times: the stream's (else the container's) duration from the probe.

Not the sum of the packet durations: Matroska stores whole milliseconds, so the 10.667 ms
frames of the DTS fixture are `duration_time=0.010000` and their sum is 3.75 s for a 4 s
track. The latest end is off by at most a millisecond: the fixture measures 2 140 063 b/s for
an exact 2 139 528 b/s (0.03 %).

The packet listing is read line by line (`run_streaming`, `-of compact=p=0`), never as one JSON
document. Video streams can be measured too; any other stream type fails the task.

### 4. Measured values and roles

When a bitrate or subtitle scan is done, a copy of the source gets the values
(`BitrateSource.MEASURED`; `event_count_source="measured"` and `forced_event_count`) and goes
to `ctx.sources.store`. C-3's role heuristics are worked out again on that copy
(`reframe.probe.roles.assign_audio_roles` / `assign_subtitle_roles`, as the MediaInfo step of
the prober already does for bit rates), because they use these values: a measured 128 kb/s
untitled stereo track after a 5.1 track becomes a commentary candidate, a track with ≤ 25 % of
the events of another track in its language a forced candidate. A failed or cancelled scan
stores nothing. The loudness measurement is only the task's result: `MediaSource` has no
field for it.

### 5. Loudness

`ffmpeg -hide_banner -nostdin -nostats -progress pipe:1 [-ss S] -i FILE [-t D] -map 0:<i>
-filter:a loudnorm=print_format=json -f null -` (fast seek, the same chain end as the
`analyse` step of a job), the last JSON block parsed with C-11's
`reframe.queue.loudnorm.parse_blocks`. `-inf`, `inf` and `nan` are `None` (a silent track:
`input_i` and `input_tp` are `-inf`, `input_lra` 0, `input_thresh` -70). A `start` after the
end decodes nothing, and ffmpeg still exits 0 and prints the values of silence ("Output file is
empty"); the task fails instead ("has no audio in the part to measure"), found by no
`-progress` block with an `out_time` above 0. The JSON block is printed at log level `info`,
so the command must not have `-v error`.

### 6. The DTS-HD MA fixture: a real DTS-HD MA stream without a core

`testing/reframe_testing/dts.py` writes a real DTS-HD MA bitstream in Python: extension
substream (EXSS, sync `0x64582025`) frames with one asset whose only coding component is an
XLL (lossless) frame (sync `0x41A29547`); 5.1, 48 kHz, 24-bit, 512 samples per frame, fixed
prediction with Rice and hybrid Rice codes, every CRC-16 (common header, channel-set header,
NAVI, EXSS header) correct. ETSI TS 102 114 and FFmpeg's `dca_exss.c`, `dca_xll.c`,
`dcadec.c`, `dca_parser.c` and `dtsdec.c` (n9.0.2) were the references. FFmpeg decodes it with
`-err_detect crccheck+explode` and gives back exactly the samples written, and ffprobe reports
`profile: "DTS-HD MA"`, `sample_fmt: s32p`, `bits_per_raw_sample: 24`, `5.1(side)` and **no
`bit_rate`** (the XLL decoder sets it to 0; the Matroska muxer writes no statistics tags).
Reframe's probe shows "DTS-HD MA", lossless, bit rate unknown (`— (unknown)` in `reframe
probe`). Same result with the pinned n9.0.2 and the n8.1.3 builds.

**What is different from a Blu-ray track:** there is no lossy DTS core before each EXSS frame
(the asset descriptor says "XLL only", `bBcCorePresent = 0`); DTS-HD allows that. FFmpeg's
core frames cannot be used: the fixture recipes are "write files, then run ffmpeg", and
splicing the EXSS frames between FFmpeg's core frames needs a Python step between two ffmpeg
steps, which is a change to the generator (`media.py` outside the new recipes), and a Python
DTS core encoder is much more work than the lossless part. Consequences: a "DTS core only"
decoder (`-core_only 1`, the `dca_core` bitstream filter, a player without DTS-HD) finds nothing
to play; nothing in Reframe uses the core today. The TrueHD fallback of the task description
was not needed.

The fixture `dts-hd-ma` also has two AC-3 tracks with a bit rate in their headers (`eng` 5.1
224 kb/s, `eng` stereo 192 kb/s), and the DTS-HD MA track is `hun`: with these, M6 demo 5
("Hungarian 5.1 or more → AC-3 5.1, max 320", "English 5.1 or more → AC-3 5.1, max 384")
can run on the same file.

### 7. The PGS fixture

`testing/reframe_testing/pgs.py` writes `.sup` files (PCS, WDS, PDS, ODS with run-length coded
bitmaps, END; one show and one clear display set per event, the forced flag on the composition
object of forced events). FFmpeg copies them into Matroska (`-c:s copy`; `-copyts` keeps the
event times, because the `sup` demuxer starts at the first event). The fixture `pgs`
(720×480) has an `eng` track with 6 events, 2 of them forced, and an `eng` track with the forced
disposition and 2 forced events. ffprobe reads both as `hdmv_pgs_subtitle`, 12 and 4 packets.

## Open product questions (defaults chosen, easy to change)

1. **PGS event count** = display sets, including the "clear" ones (§2), so that a measured
   count and a `NUMBER_OF_FRAMES` tag agree. The UI could show "about N subtitles" (half) for
   PGS; changing the count itself is one line in `subtitles.scan`.
2. **Roles are recomputed** after a scan (§4). The alternative is to keep the probe's roles
   until the next probe.
3. **No loudness in the source**: the measurement is not stored (no field; a new persisted
   field needs a `schema_version` bump). The analyse step of a job measures again.
4. **The fixture's DTS-HD MA track has no core** (§6).

## Consequences

- The Measure button (03 §Audio), the Events column and the forced suggestion (03 §Subtitles)
  have their core: `Reframe.sources.bitrate_scan / subtitle_scan / loudness_scan`.
- Cancelling a scan stops its process within 1 s (measured: 6 to 25 ms on a 2-hour file;
  `tests/analysis/test_analysis_cancel.py`).
- A PGS scan needs ffmpeg as well as ffprobe and writes a temporary copy of the PGS tracks
  (tens of MB for a film) under `<cache dir>/scans`.
- The PGS and DTS-HD MA probes in `testdata/probes/` stay synthesised (0006), but there are now
  generated files with the same properties to test against FFmpeg itself.

## Plan changes

- [05 §C-10](../plan/05-core.md#c-10-preview-and-analysis-tasks): the subtitle scans bullet
  (PGS forced flags from the stream, VobSub with `forced_subs_only`).
- [03 §Subtitles](../plan/03-features.md#subtitles): foreign audio search uses the forced flags
  found in a scan of the stream (not a decode).
- [09 §Test media](../plan/09-quality-and-release.md#test-media): the PGS fixture is generated;
  a new row for the DTS-HD MA track.
