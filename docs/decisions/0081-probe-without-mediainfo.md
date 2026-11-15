# 0081 — The probe works without MediaInfo

- Status: accepted
- Date: 2026-11-15
- Steps: C-19 (new); also C-1, C-3, D-7, D-8, S-6, F-10, F-15, Q-5

## Context

The probe (C-3) uses MediaInfo when it is available: `pymediainfo` with its bundled
`libmediainfo` (the `[mediainfo]` extra, in every frozen build), `probe/mediainfo.py`. It fills
three gaps that ffprobe leaves:

1. a **bit rate** for a video or audio stream when ffprobe's stream `bit_rate` and the Matroska
   statistics tags give none (or the tags look stale);
2. **CFR or VFR** for a video stream that ffprobe's output cannot decide;
3. a **BCP 47 language**. For Matroska, Reframe's own track reader gives `LanguageIETF` since
   the core-complete review (R4-3), with MediaInfo on or off.

What MediaInfo costs:

- the `pymediainfo` wheel (about 15 MB with `libmediainfo`) in every build, and the MediaInfo
  CLI that the Windows package bundles (`tools/bundled-tools.toml`);
- `Recommends: mediainfo` in the .deb / .rpm, the `mediainfo` package and the `[mediainfo]`
  extra in the Docker image;
- in the AppImage and on Fedora 45 the system `mediainfo` is `broken` (the D-8 open item: the
  sidecar's `LD_LIBRARY_PATH` reaches it);
- one of the four licence-text groups still open for v1 (MediaInfoLib's internal code,
  [0079](0079-q5-release-process.md));
- a tool in discovery, Settings → Tools, the settings field `tools.mediainfo`, and the bit-rate
  source `mediainfo` in `MediaSource`.

### The check (2026-11-15)

33 real files from the owner's SMB shares (one per release folder: 31 MKV, 2 MP4; BD remuxes,
web releases, anime encodes, HandBrake 0.10 to 1.10 output, FFmpeg output) and the 13
generated fixtures. For each file: Reframe's probe with MediaInfo off and on, MediaInfo's raw
fields (`pymediainfo` 7.0.1), and the **exact** bytes per track from a scan of every Matroska
block header (a scratch script). The scan agrees with mkvmerge's statistics tags to within
1 bit/s on all 17 video tracks that have them, and with ffprobe's MP4 stream rate for the same
stream (`vfr.mkv` and `vfr.mp4`: 489085). Ffprobe 9.0.2, MKVToolNix 103.0 for `mkvinfo`.

| Muxer of the file | Files | Files with a stream that has no rate without MediaInfo | Such streams | MediaInfo gave a rate |
|-------------------|-------|-------|---------|-----|
| mkvmerge | 19 | 5 | 12 | 10 |
| HandBrake 0.10 | 3 | 3 | 3 | 3 |
| HandBrake 1.7, 1.8, 1.9, 1.10 | 7 | 7 | 17 | 2 |
| FFmpeg (`Lavf61`) | 1 | 1 | 2 | 0 |
| MP4 (GPAC, `Lavf61`) | 2 | 0 | 0 | — |
| no writing application | 1 | 0 | 0 | — |

- **Where MediaInfo gives a rate it is close**: 15 of the 34 streams, median error 0.04 %,
  worst 2.2 % (HandBrake 1.8, HEVC).
- **Where it matters most it gives nothing**: modern HandBrake output (1.7 to 1.10 with AAC
  audio, the owner's own encodes) and plain FFmpeg output carry no rate for any stream, and
  MediaInfo gives none either (17 of the 19 streams it misses). On the fixtures it gives a rate
  only when exactly one stream lacks one.
- **Two of its "rescues" hide a Reframe bug.** In 2 of the 19 mkvmerge files (mkvmerge 15 and
  93) the statistics tags are right (video equal to the exact scan to 1 bit/s), but
  `check_stats_tags` calls every tag stale: the tracks' `NUMBER_OF_BYTES` add up to more than the
  file size (550,630,437 > 548,171,435 bytes; 29,943,201,280 > 29,929,897,720). mkvmerge
  zlib-compresses PGS subtitle tracks (`ContentCompression` in their `TrackEntry`), and
  `NUMBER_OF_BYTES` counts the bytes before compression. MediaInfo then repeats the tags.
- **VFR**: on every file and fixture the verdict is the same with and without MediaInfo.
  Reframe's own fallback (the timestamps of the first 120 packets) decides it.
- **MP4**: ffprobe gives every stream's rate; MediaInfo adds nothing.

**A sampled estimate.** The same script read 32 clusters at evenly spaced offsets (2 % to 98 %
of the file), and for each the next cluster's timestamp, so it knows the time each sampled
cluster covers. Per track it summed the block bytes. Four ways to turn that into rates were
compared on the 34 streams:

| Estimate | Answers | Median error | Worst | Within 5 % |
|----------|---------|--------------|-------|------------|
| MediaInfo | 15 / 34 | 0.04 % | 2.2 % | 15 |
| File size minus the known streams (one unknown stream only) | 5 / 34 | 0.08 % | 2.1 % | 5 |
| Share of the sampled bytes × file size | 34 / 34 | 4.1 % | 39.5 % | 19 |
| Bytes per sampled second, every track | 34 / 34 | 3.9 % | 85.5 % | 18 |
| **Audio: bytes per sampled second; one unknown video stream: the file's rate minus every other stream** | **34 / 34** | **0.47 %** | **9.9 %** | **31** |

With 64 clusters the last row is 0.41 % median, 10.2 % worst, 31 within 5 %: more samples do
not help, because the error left is the audio's own variation: the streams outside 5 % are
audio tracks (FLAC and two AAC with 32 clusters, three DTS with 64; 5.1 % to 10.2 %). Video is
within 2.1 % in every file. Reading 32 clusters took a
median of 16 MB and 0.7 s per file over SMB; the full block scan takes about 9 s per GB there,
so it is a check, not a probe step.

Not checked: M2TS, MPEG-TS and AVI (no such files on the shares), Matroska files with a
`TimestampScale` other than 1 ms (the script assumed 1 ms), and files with more than one video
stream.

## Decision

1. **MediaInfo leaves the product.** No `pymediainfo`, no `libmediainfo`, no bundled MediaInfo
   CLI, no `mediainfo` package or recommendation, no Settings → Tools row, no
   `REFRAME_MEDIAINFO`, no settings field `tools.mediainfo`. It is not kept as a development
   tool either: the tests' oracle for bit rates is the exact block scan and mkvmerge's
   statistics tags.
2. **Fix the stale-tag check.** A track whose `TrackEntry` has `ContentEncodings` with
   compression is left out of the `NUMBER_OF_BYTES` sum, and its own tags are trusted only by the
   other checks (`BPS` against the file's rate, `DURATION` against the file's). Reframe's
   Matroska reader reads `ContentEncodings`. The two files above must keep their tags.
3. **A sampled estimate for Matroska and WebM.** When a video or audio stream still has no rate
   after ffprobe and the tags, the probe reads 32 clusters at evenly spaced offsets (2 % to
   98 %), each with the next cluster's timestamp, using the file's `TimestampScale`:
   - an audio stream gets its bytes per sampled second;
   - a single video stream without a rate gets the file's rate minus every other stream's;
   - more than one video stream without a rate: each gets its bytes per sampled second.

   The reads are bounded (256 KB windows, a cluster of at most 64 MB, the reader's `MAX_*`
   limits), run in the probe's worker thread with a time limit and cancel, and a file the
   reader cannot sample keeps `unknown`. Other containers keep `unknown`.
4. **A new bit-rate source `estimated`** replaces `mediainfo`. The UI shows it as an estimate
   ("≈", with "estimated from 32 samples") and offers the existing **Measure** scan for the
   exact value. `BitrateSource` changes in a persisted document (`MediaSource`): a
   `schema_version` bump, a migration (`mediainfo` → `estimated`) and a down-level note. Probe
   cache entries made with MediaInfo are probed again (the cache key changes).
5. **VFR** is decided by ffprobe's output and Reframe's 120-packet fallback alone.
6. **BCP 47** comes from Reframe's Matroska reader (as now) and, for other containers, from the
   ISO 639 code through `reframe.languages`.
7. **When**: in M10, before the release checklist (step C-19).

## Consequences

- Every build loses about 15 MB, Windows also the MediaInfo CLI. The `mediainfo` half of the
  D-8 open item goes away, and with 0080 the whole of it. One of the four open licence-text
  groups for v1 goes away.
- More streams get a rate: 34 of 34 in the check, not 15. On the streams where MediaInfo had
  one, the estimate is as close for video and up to 10 % off for some audio (FLAC, DTS, AAC),
  where MediaInfo was within 0.3 %. The UI says it is an estimate, and Measure gives the exact
  value.
- A probe of an MKV without trusted rates reads about 16 MB more: about 0.7 s over a network
  share. Q-3's probe budgets (local files) must still pass.
- Two mkvmerge files out of 19 were probed with stale-looking tags. The fix in item 2 matters
  without MediaInfo too, because it decides which rate the batch rules and the commentary
  heuristic see.
- To revisit: M2TS / MPEG-TS sources, if ffprobe gives no rate there, need their own sampling
  or stay `unknown` until measured.

## Plan changes

- `05-core.md`: new section **C-19 Probe without MediaInfo**; C-1 (discovery), C-3 (the probe),
  the core's optional extras.
- `02-architecture.md`: the tool diagram and the `mediainfo` line of the encoding backend, the
  bundled-tools folders, the path-override table.
- `03-features.md`: §Settings (Tools); the bit-rate sources in the track table; the codec
  name line, which named MediaInfo as a fallback for commercial names that the code never
  used (`probe/names.py` reads ffprobe only).
- `06-web-app.md`: the Docker image's runtime packages.
- `07-desktop-app.md`: the bundled-tools table and D-7's notes.
- `08-roadmap.md`: C-19 in M10.
- `09-quality-and-release.md`: the MediaInfo licensing row.

## Built

### Wave 0 (the lead, 2026-11-15)

`BitrateSource.estimated` replaces `mediainfo`; `BitrateInfo.samples` (the number of clusters
an estimate was made from, so the UI says "estimated from N samples" and not always 32: a short
file has fewer clusters); `media_source` schema 2 with the migration `mediainfo` → `estimated`;
`tools.mediainfo` removed from the settings (`settings` schema 2).

### Built: E (the probe)

*Placeholder.*

### Built: P (MediaInfo leaves the product)

*Placeholder.*

### Built: U (the track table)

*Placeholder.*

### The real-file check

*Placeholder.*

## Review

*Placeholder.*
