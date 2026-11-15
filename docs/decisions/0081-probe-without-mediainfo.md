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

`probe/mediainfo.py` and `use_mediainfo` are gone; nothing in `reframe` imports `pymediainfo`
(a test runs `import reframe` and a probe with its import blocked). The real-file and fixture
results are in `testdata/README.md`, "Sampled bit rates": every video and audio stream of the
31 Matroska files and of every Matroska fixture has a rate; estimated video within 1.44 %,
audio within 9.86 % (FLAC) of the block scan.

- **Reader** (`probe/matroska.py`): `MatroskaTrack.compressed` (a `ContentEncoding` of type 0,
  or with `ContentCompression`); `MatroskaFile.timestamp_scale`, `duration` (seconds),
  `segment`, `segment_size`. Every existing name and signature is kept.
- **Stale tags**: the reader now runs before ffprobe's output is parsed, and
  `parse_ffprobe(…, matroska=)` / `vfr_undecided(…, matroska=)` pass the compressed tracks'
  stream indexes to `check_stats_tags(…, compressed=)`: they leave the `NUMBER_OF_BYTES` sum, and
  the size check does not apply to their own tags (the `BPS` and `DURATION` checks do).
- **Sample** (`probe/sampling.py`): as item 3, with these choices the item does not settle:
  - a segment no larger than the windows together (32 × 256 KB) is read whole, cluster by
    cluster; a file whose windows find no cluster is read from the first cluster, at most 32.
    The fixtures are single-cluster files of 2 to 5 s, where no window lands before the cluster
    and the header share made "the file's rate minus the others" 8 % off (`hdr10.mkv`);
  - the last cluster ends at the segment's `Duration`; a span outside 0 to 60 s is not used;
  - when the sample holds every cluster, a single video stream also gets its bytes per sampled
    second (the exact value); a subtraction at or below zero, or no file rate, falls back to the
    same;
  - "every other stream" includes subtitle tracks and tracks ffprobe does not map, at their
    sampled rate;
  - a window without a cluster start gives no sample at that offset, as in the check: the real
    files gave 1 to 12 clusters, not 32. `BitrateInfo.samples` is the number read;
  - limits: 256 MB read in all (`MAX_SAMPLE_READ`; the clusters read so far are the sample),
    `MAX_ELEMENTS` per cluster, 30 s (`prober.SAMPLE_TIMEOUT`; after it the rates stay
    `unknown`, logged, no warning). Cancel and the time limit stop the worker before its next
    read.
- **Cache**: `PARSER_VERSION` 2, `sampling.py` in `_PARSER_MODULES` and `mediainfo.py` out,
  `cache_options()` is `{"matroska": 3}`.
- **BCP 47** for other containers: `parse_ffprobe` sets `language_ietf` to
  `languages.normalize` of the ISO 639 code (`und` and codes without a tag: `None`).
- **Recorded probes**: `testdata/probes/real/` holds the mkvmerge 15 and 93 files of the check,
  anonymised (`record_real.py`): ffprobe's JSON and a header-only Matroska file. Through the
  prober both keep their statistics tags (`stats_tag`, video equal to the block scan to 1 bit/s).
- **Oracle**: `testing/reframe_testing/blockscan.py`, the exact block scan.

#### Review fixes (FE, 2026-11-15)

Fixes of R2's findings, each with a test that failed before the fix.

1. **A huge `TimestampScale`.** The reader read an unsigned integer of any length, so a
   `TimestampScale` of 130 bytes in an `Info` without `Duration` passed, the sample's span
   raised `OverflowError` and `probe_folder` failed with an `ExceptionGroup`. Now an unsigned
   integer element over 8 bytes (the specification's limit) is damaged: `MatroskaError`, so the
   track headers are not used and the rates stay `unknown`. Checked with ffprobe n9.0.2 on R2's
   file: libavformat also rejects it ("Invalid length 0x82 > 0x8 for element with ID
   0x2AD7B1") and reads the rest. A `Duration` whose seconds overflow a float is no duration.
   The prober also catches `ArithmeticError` and `ValueError` from the sample (the file keeps
   `unknown`, no exception: "Done when" 3).
2. **Attachments counted as video.** The single video stream got the rate of the whole file
   minus the other streams, so the `Attachments` element went to the video (R2's 60 s 2 Mb/s
   file with a 4 MB font: +26.8 %). `MatroskaFile.other_bytes` is now the size of the top-level
   elements that hold no blocks: those the reader reads before `Tracks` and `Info` are found,
   and the `Attachments`, `Chapters`, `Tags` and `Cues` that the `SeekHead` lists (one 12-byte
   header read each; ffmpeg n9.0.2 and mkvmerge 103 both list them, checked with `mkvinfo`). The
   file's rate leaves them out. Chosen over the sizes in `source.attachments`: those come from
   ffprobe, do not cover cover art, cues and tags, and are not the element's bytes. An entry
   that does not point at its element is left out. R2's file after the fix: video 2,003,430
   vs 2,000,281 b/s (+0.16 %). Tests: a generated ffmpeg (`-attach`) and mkvmerge
   (`--attach-file`) file with 4 MB of random bytes, each within 3 % of the block scan; the
   reader's sizes on a synthetic file. `cache_options()` is `{"matroska": 4}`.
3. **A timed-out sample was cached.** A sample or a Matroska header read that times out or
   fails with `OSError` (a slow or unreachable share, not the file) now leaves the probe out of
   the cache, so the next probe reads again. A file without a usable cluster, or with damaged
   headers, is still cached. The header read is included because it has the same problem.
4. **Fingerprint.** `parser_fingerprint` hashes `languages.py` and the three language tables
   too (`parse.py` uses `languages.normalize`); the list is `_PARSER_FILES`, relative to the
   `reframe` package.
5. **Docstring.** `tracks_by_kind` explains the order without mkvpropedit.

Not changed (outside this task): the accuracy of few samples on variable audio (R2's
`vbr-flac.mkv`: audio −30 %, video +9 %), and the per-track estimate when a file has two video
streams (R2's `mkvmerge-nostats.mkv`: first video −4.4 %).

### Built: P (MediaInfo leaves the product)

1. **The core and server**: as 0080's P items 1 and 2 (`mediainfo` leaves `ToolName`,
   `ToolSet`, discovery, `REFRAME_MEDIAINFO`, the bundled `mediainfo/` folder and
   `parse_mediainfo_version`). The `language_ietf` description no longer names MediaInfo.
2. **Python packages**: the `[mediainfo]` extra of `reframe` and `pymediainfo` are gone (the
   dev group installs `reframe[cli]`; `uv.lock` without pymediainfo). The sidecar spec has no
   `pymediainfo` hidden import and no libmediainfo binaries.
3. **The Windows layout** is FFmpeg only: `tools/bundled-tools.toml` pins no MediaInfo CLI,
   and `scripts/bundle-tools.py` loses its tool-archive path (the kept-files list, archives
   without a top folder); the libva pin stays. A `mediainfo/` folder of an earlier layout is
   removed. The sources manifest names no MediaInfo source, so the Windows installers'
   sources are FFmpeg's only. `reframe.tools.fetch` keeps its generic zip-without-a-top-folder
   support (now unused by any pin).
4. **Docker**: no `mediainfo` package, no `--extra mediainfo`; the notices' `uv export` has
   no `mediainfo` extra.
5. **Notices**: the MediaInfoLib entry (read from pymediainfo's library) is gone. One of
   0079 item 12's open licence-text groups (MediaInfoLib's internal code) goes away.
6. **Checked on this host (2026-11-15)**:
   - the frozen sidecar (`desktop/sidecar/build.py`): no `pymediainfo` module or folder and no
     file named like `*mediainfo*`; the frozen server probes `vfr.mkv` (pinned ffprobe
     n9.0.2) with a video rate of 489048, source `estimated`, 1 sample
     (`test_the_frozen_server_estimates_the_bit_rates_that_ffprobe_does_not_give`);
   - the Docker image (classic builder, linux/amd64, built and removed): `dpkg-query` lists
     no `mediainfo`, `libmediainfo*`, `libzen*`, `mkvtoolnix`, `libebml*` or `libmatroska*`;
     its `DEBIAN_PACKAGES` names none; its venv has no pymediainfo; `reframe tools status`
     lists the bundled ffmpeg and ffprobe only;
   - deb/rpm: the Tauri config has no `recommends`; the packages were not built (the build
     needs the Ubuntu 22.04 build image and a final version), the container install test
     checks it when they are.
7. **The D-8 open item** (the system `mediainfo` `broken` under the AppImage's
   `LD_LIBRARY_PATH`) goes away.

### Built: U (the track table)

- **The cell** of an `estimated` rate (`TrackTable.vue`): `≈ 2,140 kb/s` (the message
  `tracks.units.kbpsEstimated`), **Measure** next to it on the same line (the existing bit-rate
  scan, the same button as for an unknown rate), and under it "estimated from one sample" /
  "estimated from N samples" (vue-i18n plural from `bitrate.samples`). Measure is on the value's
  line, not the label's: beside the longer label it fell outside the table's scroll width.
- An `estimated` rate without `samples` (a cached document migrated from `mediainfo`) says only
  "estimated". The details row shows `≈ value · Estimated from a sample of the file's
  clusters`. A measured, `stream` or `stats_tag` rate offers no Measure, as before.
- Checked headless against the real server: `dts-hd-ma.mkv` shows "≈ 2,140 kb/s, Measure,
  estimated from one sample"; Measure replaces it with "2,140 kb/s measured" and announces it.
- The real server now estimates rates the frontend's server tests expected as `unknown`: the
  scans tests now start from `estimated` (`dts-hd-ma` 1 sample, `commentary` 32 samples; the
  commentary role comes from the estimate, so a measure no longer changes it), and the audio
  defaults preview offers no Measure for the DTS-HD MA track (`measure` is set only for an
  unknown rate in `batch/audio_rules.py`).
- Settings → Tools and the first-run screen list ffmpeg and ffprobe only (`TOOL_NAMES`); the
  MediaInfo install hints are gone.

### The real-file check

*Placeholder.*

## Review

*Placeholder.*
