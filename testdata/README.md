# testdata

Test data for Reframe. Nothing in `media/` is committed: it is generated.

| Path | Committed | What |
|------|-----------|------|
| `media/` | no (git-ignored) | Generated fixture media (`scripts/make-testdata.py`) |
| `names.toml` | yes (later, `C-16`) | File-name corpus for guessit / output naming |
| `probes/` | yes | Recorded ffprobe JSON (`Q-2.2`, synthesised from real output; see `probes/README.md`) and the JSON of every generated fixture |

## Generated media

```sh
uv run python scripts/make-testdata.py                 # all fixtures into testdata/media/
uv run python scripts/make-testdata.py --only vobsub   # one fixture
uv run python scripts/make-testdata.py --force         # regenerate even if up to date
uv run python scripts/make-testdata.py --list          # names and descriptions
```

- FFmpeg and ffprobe come from Reframe's own tool discovery (`reframe.tools`, step C-1):
  `$REFRAME_FFMPEG` / `$REFRAME_FFPROBE` → the bundled build (in CI:
  `$REFRAME_DATA_DIR/tools/ffmpeg`, installed with `scripts/fetch-tools.py --install-dir`) →
  `PATH`. `uv run python -m reframe.tools` shows which binaries it picks and why.
- Incremental: `media/manifest.json` stores a hash of each recipe (files written, FFmpeg
  arguments, generator version, first line of `ffmpeg -version`). A fixture whose outputs exist
  and whose hash did not change is skipped. Each fixture is built in a temporary folder
  (`media/.tmp-*`) and moved into place only on success.
- Time on the reference machine (Arch Linux, 12 threads, FFmpeg n9.0.2): about 0.9 s for all
  fixtures but `hdr10-4k` (cold, idle machine; 3.3 s under heavy load), plus about 4 s for
  `hdr10-4k`; 0.1 s when everything is up to date. About 15 MB in total (6 MB of it is
  `hdr10-4k`).
- Tests get a fixture with the `fixture_media` pytest fixture (`fixture_media("multitrack")`),
  which generates it on demand and skips the test when there is no usable ffmpeg. The code is
  in `testing/reframe_testing/media.py`.
- `needs_ffmpeg` tests and `fixture_media` **skip** when ffmpeg or ffprobe is missing or its
  `-version` fails. With `REFRAME_REQUIRE_FFMPEG=1` (CI sets it) they **fail** instead, with
  the reason (for example `REFRAME_FFMPEG=/x/ffmpeg is not a file`). So a broken tool path
  cannot make a CI job green by skipping every real-tool test.
- Several threads can generate fixtures at the same time: every read and write of
  `manifest.json` holds one lock, and a rename that fails with `PermissionError` (Windows: the
  file is open in another thread or process) is tried again for about 5 s.

| Name | File(s) | What it has |
|------|---------|-------------|
| `multitrack` | `multitrack.mkv` | H.264 320×180, 4 s. Audio: `jpn` AC-3 5.1(side) "Japanese 5.1" **default** (440 Hz), `eng` AAC stereo "English Stereo" (660 Hz), `eng` AAC stereo 64k "Director's Commentary" **comment** (880 Hz). Subtitles (SRT): `eng` "English" **default**, `eng` "English SDH" **hearing_impaired**, `eng` "Signs & Songs" **forced** |
| `text-subs` | `text-subs.mkv`, `text-subs.en.srt`, `text-subs.en.ass` | SRT and ASS tracks (UTF-8 text with Hungarian accents, ASS override tags, a positioned sign) plus the same files as sidecars. The ASS styles use `Fontname` "Reframe Box"; `ReframeBox.ttf` is attached (see below) |
| `vobsub` | `vobsub.mkv` | 720×480. Two `dvd_subtitle` tracks: `eng` default (2 events), `fre` forced (1 event) |
| `letterbox` | `letterbox.mkv` | 320×180: 2 s of 2.39:1 letterbox (`crop=320:134:0:22`), then 2 s of 4:3 pillarbox (`crop=240:180:40:0`) |
| `anamorphic` | `anamorphic.mkv` | 720×480, SAR 32:27, DAR 16:9 |
| `interlaced` | `interlaced.mkv` | 320×240 H.264 29.97i, `interlace=scan=tff,setfield=tff`, `-flags +ildct+ilme`; `field_order=tb` |
| `vfr` | `vfr.mp4` | 1 s each at 24, 30 and 60 fps; `r_frame_rate=120/1`, `avg_frame_rate=38/1` |
| `vfr-mkv` | `vfr.mkv` | The same clip in Matroska; `avg_frame_rate=0/0` (see below) |
| `hdr10` | `hdr10.mkv` | HEVC Main 10, BT.2020 / PQ, mastering display (G 0.265,0.69 … L 0.0001–1000 cd/m²), MaxCLL 1000 / MaxFALL 400, as stream **and** frame side data |
| `hdr10-4k` | `hdr10-4k.mkv` | 3840×2160 HEVC Main 10, BT.2020 / PQ, HDR10 metadata as SEI only (one libx265 pass), 5 s at 23.976 fps, keyint 48 (2 s). The 4K source of the C-10 frame budget (Q-3; the one fixture that is not low resolution, decision 0030); about 6 MB and 4 s to generate |
| `chapters` | `chapters.mkv` | 5 s, 4 chapters (Opening, Part One, Part Two, Credits) and a title, from an FFMETADATA file |
| `season` | `season/Show.S01E01.Title.mkv` … `E12` | 12 copies of the multi-track layout (title `Show - S01Enn`). **E05** has an extra `eng` AC-3 2.0 "Commentary" (comment) as the 4th audio track. **E09** has no second audio track ("English Stereo") |
| `dts-hd-ma` | `dts-hd-ma.mkv` | H.264 320×180, 4 s. Audio: `hun` **DTS-HD MA** 5.1(side) 24-bit 48 kHz "DTS-HD MA 5.1" **default**, a real lossless (XLL) stream written by `reframe_testing/dts.py` with **no bit rate in the file** (ffprobe: `profile` `DTS-HD MA`, no `bit_rate`; 375 frames, 1 069 764 bytes = 2 139 528 b/s); `eng` AC-3 5.1 224 kb/s "English AC-3 5.1"; `eng` AC-3 stereo 192 kb/s "English Stereo". M6 demo 1 (Measure) and the audio-defaults demo |
| `pgs` | `pgs.mkv` | H.264 720×480, 4 s. Two PGS (`hdmv_pgs_subtitle`) tracks written by `reframe_testing/pgs.py`: `eng` "English" **default**, 6 events (2 with the forced flag, at 0.2 s and 2.1 s), 12 display sets; `eng` "English (forced)" **forced**, 2 forced events, 4 display sets |
| `anime-s01` | `Anime.Show.S01.BluRay.x264-GRP/Anime.Show.S01E01.Pilot.BluRay.x264-GRP.mkv` … `E12` | The 04 §Example season (batch mode, C-12 M7; decision 0040): H.264 320×180, 2 s. Audio: `jpn` **TrueHD** 5.1(side) 24-bit "Japanese" **default** (FFmpeg's experimental `truehd` encoder; no bit rate in the file), `eng` **DTS-HD MA** 5.1 "English Dub" (`reframe_testing/dts.py`, no bit rate). Subtitles (ASS): `eng` "Signs & Songs" **forced**, `eng` "Full" **default**. **E05** also has `eng` AC-3 2.0 96 kb/s "Commentary" (**comment**) after the dub; **E11** has no dub, and its signs track is titled "Signs". Each episode is a stream copy of one master, with the container title `Anime Show - S01Enn - Title`; about 770 KB each |
| `anime-s02` | `Anime.Show.S02.BluRay.x264-GRP/Anime.Show.S02E01.Return.BluRay.x264-GRP.mkv` … `E03` | Season 2 of the same release: three episodes with E01's layout (the M7 demo applies season 1's group preset to it) |

`testing/tests/test_media_fixtures.py` checks every row with ffprobe.

### How the special fixtures are made

- **Bitmap subtitles.** FFmpeg cannot encode text subtitles to bitmap subtitles (see below).
  So `reframe_testing/vobsub.py` writes a VobSub `.idx` + `.sub` pair in plain Python (DVD
  subpicture units in an MPEG-2 program stream; each event is a white bar with a black outline
  and gaps). FFmpeg reads it, decodes it and encodes it again with the `dvdsub` encoder.
- **HDR10.** Two libx265 passes. The first gets the HDR10 parameters in `-x265-params` and the
  colour properties through `setparams`. The second decodes the first and encodes it again with
  the same parameters, so the encoder receives the HDR metadata as frame side data and the
  Matroska muxer writes it at stream level (see below).
- **Font.** The ASS fixture always attaches **Reframe Box** (`ReframeBox.ttf`, 1672 bytes), a
  tiny TrueType font that `reframe_testing/boxfont.py` generates: every character is a filled
  box. It is generated by this project and is public domain (CC0). No system font is used, so
  `text-subs.mkv` (attachment name and size, ASS `Fontname`) is the same on every OS and
  runner image, and `C-3` snapshots do not depend on the machine. The attachment has
  `mimetype=application/x-truetype-font`. A test renders the ASS text with libass and checks
  that the glyphs are solid boxes (a fallback font fills about 30 % of the text's bounding box,
  Reframe Box about 83 %), so libass really uses the attached font.
- **DTS-HD MA.** FFmpeg's `dca` encoder writes a DTS core only (`-strict -2`), so
  `reframe_testing/dts.py` writes the DTS-HD MA stream in Python: extension substream (EXSS)
  frames with one asset whose only component is an XLL (lossless) frame: 5.1, 48 kHz,
  24-bit, 512 samples per frame, fixed prediction with Rice codes, every CRC-16 correct
  (references: ETSI TS 102 114 and FFmpeg's `dca_exss.c` / `dca_xll.c` / `dcadec.c`).
  There is **no DTS core** (decision 0032). Each channel is a steady tone whose frequency is
  a whole number of periods per frame (93.75 Hz steps), so the frames of one second are the
  same; the level changes every second (0, -6, -12, -3 dB), so the frame size varies. FFmpeg
  copies the `.dtshd` file (`-f dts`) into Matroska. A test decodes it with
  `-err_detect crccheck+explode` and compares every sample with what was written (lossless).
- **PGS.** FFmpeg has no PGS encoder either. `reframe_testing/pgs.py` writes `.sup` files
  (PCS, WDS, PDS, ODS with run-length coded bitmaps, END): one show and one clear display
  set per event, the bars of the VobSub fixture as bitmaps, the forced flag (`0x40`) on the
  composition object of a forced event. FFmpeg copies them into Matroska with `-copyts`.

## Fake FFmpeg (fault injection)

`reframe_testing.fake_tools.make_fake_tools(dir, Scenario([...]))` (or the `fake_tools`
pytest fixture) writes fake `ffmpeg` / `ffprobe` launchers that sleep, hang, crash, flood,
print captured driver errors or `-progress` blocks. The texts come from the pinned build
(`testing/reframe_testing/fake_data/`, refreshed by `capture_fake_data.py`, see below).

| Environment variable | What |
|----------------------|------|
| `REFRAME_FAKE_FFMPEG_SCENARIO` | Path of the scenario JSON (the launchers set a default) |
| `REFRAME_FAKE_FFMPEG_LOG` | Folder for the call log: one `<pid>-<random>.json` file per process (written under a `.tmp` name, then renamed), sorted by a `monotonic_ns` timestamp. No shared append-only file: `O_APPEND` is not atomic between processes on Windows |
| `REFRAME_FAKE_FFMPEG_MAX_LIFETIME` | Seconds (default 120) after which `hang` (exit code 124) and the grandchild exit by themselves, so a failed test cannot leave processes behind |

- The fake runs with the base interpreter (`sys._base_executable`), not the venv `python`: on
  Windows that is a launcher process. So the tree is `fake` (POSIX) or `cmd.exe -> fake`
  (Windows `.cmd` launcher).
- `crash()` on Windows exits with `0xC0000005` (passed to `os._exit` as the signed value
  `-1073741819`; the unsigned value raises `OverflowError`).
- The `fake_tools` fixture kills every logged process that still runs in its teardown
  (`FakeTools.kill_leftovers()`; a pid that the OS gave to a newer process is left alone).
- The `exec` action (`fake_tools.exec_program(path)`, C-11) passes a call to a real program with
  the same arguments, stdin, stdout and stderr, and exits with its exit code. A rule with no
  conditions and this action, put last, makes the fake a real ffmpeg except for the calls that
  the other rules catch (one failing job among real encodes).

## Verified tool behaviour

FFmpeg **n9.0.2**, checked on 2026-10-11 with two builds: the Arch Linux package and the pinned
BtbN build `n9.0.2-17-g2a571b6068-20260930` (`tools/ffmpeg.toml`). Most of these are also
asserted in `testing/tests/test_media_fixtures.py`, which passes with both builds, so a
different FFmpeg shows up as a test failure.

### Matroska muxer: dispositions

Command (per disposition; subtitle dispositions on an SRT track):

```sh
ffmpeg -v error -y -f lavfi -i sine=duration=0.5 -c:a aac -disposition:a:0 <disposition> t.mkv
ffprobe -v error -of json -show_streams t.mkv      # read back "disposition"
```

| Disposition | Written and read back | Note |
|-------------|----------------------|------|
| `default`, `forced`, `comment`, `hearing_impaired`, `visual_impaired`, `original` | yes | Matroska `FlagDefault`, `FlagForced`, `FlagCommentary`, `FlagHearingImpaired`, `FlagVisualImpaired`, `FlagOriginal` |
| `dub` | yes | stored as `FlagOriginal=0`; ffprobe reads it back as `dub` |
| `descriptions` | yes on a subtitle track, **no** on an audio track | `FlagTextDescriptions` |
| `captions`, `lyrics`, `karaoke`, `metadata`, `dependent`, `still_image` | **no** (read back as no flags) | |

So all three dispositions of the plan's multi-track row (`default`, `comment`,
`hearing_impaired`) work with FFmpeg alone.

### Matroska muxer: no default flag on single streams

Without any `-disposition`, FFmpeg marks a stream `default` only when its type has two or more
streams. A file with one video and one audio stream gets `FlagDefault=0` on both (mkvmerge
writes 1):

```
$ ffmpeg -v error -y -f lavfi -i testsrc2=size=64x64:duration=0.2 -f lavfi -i sine=duration=0.2 -c:v libx264 -c:a aac single.mkv
$ ffprobe -v error -show_entries stream=index:stream_disposition=default -of compact single.mkv
stream|index=0|disposition:default=0
stream|index=1|disposition:default=0
```

The fixtures set `-disposition:v:0 default` (and `a:0`) explicitly. The command builder (`C-7`)
should do the same.

### Matroska muxer: no statistics tags, few stream bit rates

FFmpeg writes only `DURATION` and `ENCODER` tags per track. It does **not** write the
mkvmerge statistics tags `BPS`, `NUMBER_OF_FRAMES`, `NUMBER_OF_BYTES`, `_STATISTICS_TAGS`. So
the generated fixtures cannot exercise `C-3`'s bitrate chain step "Matroska statistics tags" or
the subtitle event counts from `NUMBER_OF_FRAMES`; those need recorded probes (`Q-2.2`) or a
file processed with `mkvpropedit --add-track-statistics-tags`. ffprobe reports a stream
`bit_rate` only for AC-3 here (from the bitstream header), not for H.264, AAC or SRT:

```
$ ffprobe -v error -show_entries stream=index,bit_rate:stream_tags -of compact multitrack.mkv
stream|index=0|bit_rate=N/A|tag:ENCODER=Lavc63.1.102 libx264|tag:DURATION=00:00:04.000000000
stream|index=1|bit_rate=192000|tag:language=jpn|tag:title=Japanese 5.1|tag:ENCODER=Lavc63.1.102 ac3|tag:DURATION=00:00:04.000000000
stream|index=2|bit_rate=N/A|tag:language=eng|tag:title=English Stereo|tag:ENCODER=Lavc63.1.102 aac|tag:DURATION=00:00:04.021000000
...
```

(In `-of json` output a missing bit rate is a missing `bit_rate` key, not `"N/A"`.)

### HDR10 with libx265: one pass gives SEI only; `-color_trc` is not enough

`-color_primaries` / `-color_trc` as output options did not reach the file when the frames
carry "unspecified" (lavfi sources); `-colorspace` did. And `master-display` / `max-cll` in
`-x265-params` end up only in the bitstream (SEI, visible as frame side data), not in the
Matroska `Colour` / `MasteringMetadata` elements (stream side data):

```
$ ffmpeg -v error -y -f lavfi -i testsrc2=size=320x180:rate=25:duration=2 -vf format=yuv420p10le -c:v libx265 -preset ultrafast -x265-params log-level=error:hdr10=1:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400 -color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc one-pass.mkv
$ ffprobe -v error -select_streams v:0 -show_entries stream=color_space,color_transfer,color_primaries:stream_side_data=side_data_type -of compact one-pass.mkv
stream|color_space=bt2020nc|color_transfer=unknown|color_primaries=unknown
$ ffprobe -v error -select_streams v:0 -read_intervals %+#1 -show_entries frame_side_data=side_data_type -of compact one-pass.mkv
frame|...|side_datum/mastering_display_metadata:side_data_type=Mastering display metadata|side_datum/content_light_level_metadata:side_data_type=Content light level metadata
```

With `setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc` in the filter
chain the colour properties are written. When the encoder input is decoded HDR10 video (the
normal transcode case, and pass 2 of the fixture), the Matroska muxer also writes the stream
side data:

```
$ ffprobe -v error -select_streams v:0 -show_entries stream=color_space,color_transfer,color_primaries:stream_side_data=side_data_type,max_luminance,max_content -of compact hdr10.mkv
stream|color_space=bt2020nc|color_transfer=smpte2084|color_primaries=bt2020|side_datum/content_light_level_metadata:side_data_type=Content light level metadata|side_datum/content_light_level_metadata:max_content=1000|side_datum/mastering_display_metadata:side_data_type=Mastering display metadata|side_datum/mastering_display_metadata:max_luminance=1000/1
```

This confirms `C-3`'s fallback to the first frame's side data, and is relevant to `C-7`
(colour tags for HDR encodes: set them in the filter chain, not only as output options).

### VFR in Matroska: `avg_frame_rate` is `0/0`

```
$ ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate,avg_frame_rate,nb_frames -of compact vfr.mkv
stream|r_frame_rate=120/1|avg_frame_rate=0/0|nb_frames=N/A
$ ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate,avg_frame_rate,nb_frames -of compact vfr.mp4
stream|r_frame_rate=120/1|avg_frame_rate=38/1|nb_frames=114
```

`r_frame_rate ≠ avg_frame_rate` holds for both, but in Matroska written by FFmpeg the average is
unknown (`0/0`), not a real average. `C-3` must treat `0/0` as "unknown", not as a frame rate.
Matroska packets also have no duration (`duration_time=N/A`); the tests use timestamp deltas.

### Interlaced: FFmpeg writes `field_order=tb` for top-field-first

```
$ ffprobe -v error -select_streams v:0 -show_entries stream=field_order -of compact interlaced.mkv
stream|field_order=tb
```

The `ffmpeg` CLI sets `tb` (not `tt`) on encoders for interlaced TFF frames (it uses `tt`/`bb`
only for MJPEG). DVD rips from other tools often show `tt`. `C-3` must treat `tt` and `tb` as
top field first (and `bb` / `bt` as bottom field first).

### No text-to-bitmap subtitle conversion

```
$ ffmpeg -hide_banner -y -i a.srt -c:s dvdsub out.mkv
...
[sost#0:0/dvdsub @ 0x557b10a00a40] Subtitle encoding currently only possible from text to text or bitmap to bitmap
Error opening output file out.mkv.
Error opening output files: Invalid argument
(exit 234)
```

Relevant to `C-7`/`C-8`: "convert" from text to VobSub/PGS is impossible with FFmpeg.

### FFmpeg 8.1 and later print "Exiting with exit code 0" on stdout

After `ffmpeg -version` and `ffmpeg -h …` (also `-h encoder=<name>`), FFmpeg n8.1.3 and n9.0.2
print an empty line and `Exiting with exit code 0` **to stdout**, even with `-v quiet`. n7.1
and n6.1.2 do not (the recorded `-version` outputs in `packages/reframe/tests/tools/data/`).
`-encoders`, `-filters`, `-hwaccels` and `ffprobe -version` do not (both builds; see the files
in `testing/reframe_testing/fake_data/`). After an encode the line goes to stderr, and only at
`-v verbose` or above:

```
$ ffmpeg -hide_banner -h encoder=reframe_nonexistent
Codec 'reframe_nonexistent' is not recognized by FFmpeg.

Exiting with exit code 0
```

Parsers of `-version` and `-h encoder=` output (`C-1`, `C-4`) must ignore it.
`-h encoder=<unknown>` exits with 0, so "unknown encoder" is detected from the text.

### `-progress` output

Real runs of the pinned build with `-progress pipe:1 -nostats -stats_period 0.1` are in
`fake_data/progress_null_long.stdout.txt` (libx264 to `-f null`, 18 blocks) and
`fake_data/progress_mkv_long.stdout.txt` (libx264 + AAC into a Matroska file, 20 blocks); the
commands are in `captures.json`. `-readrate 2` makes each run take about 2 s, so there are
many blocks on a fast machine too. What `C-11`'s parser must handle:

- Every block has the same 12 keys in the same order (`frame` … `speed`, `progress`), and only
  the last block has `progress=end`.
- **`N/A` values.** Before the encoder returns its first packet, blocks have
  `out_time_us=N/A`, `out_time_ms=N/A`, `out_time=N/A`, `speed=N/A`, `bitrate=N/A`, `frame=0`
  and `total_size=0`. With `-f null`, `bitrate=N/A` and `total_size=N/A` stay in every later
  block. `fps=0.00` for about the first second.
- **Padded values.** `bitrate` is `%6.1fkbits/s` and `speed` is `%4.3gx` (fftools
  `print_report()`), so they can start with spaces: `bitrate=  43.8kbits/s`, `speed= 4.3x`.
- In a Matroska output `total_size` moves in steps (the muxer writes whole clusters). In this
  short run it is `total_size=762` (the header) in all blocks but the last one, so `bitrate`
  falls from `43.8` to `1.6kbits/s` and only the last block has the real `782.4kbits/s`.
  Do not use `total_size` or `bitrate` for an ETA.
- With an audio stream, `out_time` can start above 0 before the first video frame
  (`frame=0`, `out_time=00:00:00.139320`).
- `out_time_ms` has the same value as `out_time_us` (microseconds, not milliseconds).

The fake's `progress(na_blocks=N, na_fields=[...])` action prints the same start-up blocks and
`N/A` fields (`reframe_testing.fake_tools.progress`).

### Hardware encoder failures (stderr and exit codes)

Captured with the **pinned build** (`n9.0.2-17-g2a571b6068-20260930`, BtbN gpl-shared,
linux-x64) on this machine: AMD Radeon RX 7600, VAAPI at `/dev/dri/renderD128`, AMF runtime
installed, no NVIDIA driver, no Intel GPU. The `C-4` test command is
`ffmpeg -hide_banner -nostdin -f lavfi -i color=size=640x360 -frames:v 3 -c:v <encoder> -f null -`.
Full texts are in `testing/reframe_testing/fake_data/` (`hw_*.stderr.txt`, also with
`-v error`); `captures.json` has, for each capture, the exact command, extra environment
variables, the exit code, the build (`build`) and the machine (`machine`). An earlier set of
captures made with the Arch Linux n9.0.2 package had the same key lines and exit codes.

| Capture | Case | Exit code | Key stderr line |
|---------|------|-----------|-----------------|
| `hw_hevc_nvenc_no_driver`, `hw_h264_nvenc_no_driver` | NVENC, no NVIDIA driver | 255 | `[hevc_nvenc @ 0x…] Cannot load libcuda.so.1` |
| `hw_hevc_qsv_no_device` | `hevc_qsv`, no Intel GPU | 171 | `[hevc_qsv @ 0x…] Error creating a MFX session: -9.` |
| `hw_qsv_init_failed` | `-init_hw_device qsv=hw`, no Intel GPU | 187 | `Device creation failed: -542398533.` / `Failed to set value 'qsv=hw' for option 'init_hw_device': Generic error in an external library` |
| `hw_h264_vaapi_bad_device` | `-vaapi_device /dev/dri/renderD999` | 234 | `[VAAPI @ 0x…] No VA display found for device /dev/dri/renderD999.` |
| `hw_h264_vaapi_init_failed` | real render node, `LIBVA_DRIVER_NAME=reframe_nonexistent` (no VA driver) | 251 | `[VAAPI @ 0x…] Failed to initialise VAAPI connection: -1 (unknown libva error).` |
| `hw_h264_vaapi_not_drm` | `-vaapi_device /dev/null` | 187 | `Device creation failed: -542398533.` (no `[VAAPI]` line at all) |
| `hw_h264_vaapi_no_hwupload` | `h264_vaapi` without device and `hwupload` | 218 | `Error reinitializing filters!` (format negotiation) |
| `hw_h264_vaapi_ok` | `h264_vaapi` with `/dev/dri/renderD128` | 0 | success |
| `hw_hevc_amf_ok` | `hevc_amf` | 0 | success: AMF works on Linux here. stderr has a Mesa line `radv: RADV_PERFTEST=video_decode is deprecated …` (the AMF runtime sets that variable; it is not in our environment) and an AMF warning line |

Facts for `C-4`'s reason mapping:

- `Cannot load libcuda`, `No VA display found` and `Failed to initialise VAAPI` appear as the
  plan expects (all three provoked above).
- **`MFX_ERR_UNSUPPORTED` does not appear in real ffmpeg output**, and the string is not in
  the build at all (table below). oneVPL errors print a number: `Error creating a MFX session:
  -9.` (-9 is `MFX_ERR_NOT_FOUND`). Map the text `Error creating a MFX session` instead.
- **The last stderr line is not a useful reason.** When the encoder cannot open, the last line
  is the generic `Conversion failed!` (default log level) or `Nothing was written into output
  file, because at least one of its streams received no packets.` (`-v error`). When a
  `-init_hw_device` / `-vaapi_device` option fails, it is `Error parsing global options:
  <strerror>`. So "unknown patterns keep the last stderr line" gives no information; the first
  line that names the encoder or the device (`[hevc_nvenc @ …]`, `[VAAPI @ …]`) is the useful
  one.

#### Error texts confirmed in the pinned build

Errors that cannot be provoked on this machine (old NVIDIA driver, NVIDIA GPU without NVENC,
Intel GPU without support) were confirmed by a byte search for the exact text in the pinned
build's files. `capture_fake_data.py` does this and writes
`testing/reframe_testing/fake_data/library_strings.json` (asserted in
`test_fake_ffmpeg.py::test_library_strings_confirm_the_hardware_error_texts`). Command:

```sh
BIN=$(uv run --no-project python scripts/fetch-tools.py --platform linux-x64 | tail -n 1)
uv run python testing/reframe_testing/capture_fake_data.py --ffmpeg "$BIN/ffmpeg" --ffprobe "$BIN/ffprobe"
```

(The search: printable runs of ≥ 5 bytes, like `strings(1)`, in `bin/ffmpeg` and
`lib/libav*.so.*.*.*`.) `%d` / `%s` are filled in at run time.

| Text in the build | File | Use |
|-------------------|------|-----|
| `Driver does not support the required nvenc API version. Required: %d.%d Found: %d.%d\n` | `lib/libavcodec.so.63.1.102` | NVIDIA driver too old |
| `The minimum required Nvidia driver for nvenc is %s or newer\n` | `lib/libavcodec.so.63.1.102` | printed after the line above |
| `Cannot load %s\n` (with `libcuda.so.1`) | `lib/libavcodec.so.63.1.102`, `lib/libavutil.so.61.1.102` | NVIDIA driver not found. The library name is a separate string, so the output is `Cannot load libcuda.so.1` on Linux (`nvcuda.dll` on Windows, not checked: it is not in the Linux build) |
| `No capable devices found\n` | `lib/libavcodec.so.63.1.102` | NVENC: no GPU that can encode. **`No NVENC capable devices found` is not in the build** |
| `No CUDA capable devices found\n` | `lib/libavcodec.so.63.1.102` | NVENC: CUDA finds no GPU |
| `OpenEncodeSessionEx failed` | `lib/libavcodec.so.63.1.102` | NVENC session error (followed by the NVENC status text) |
| `Error creating a MFX session: %d.\n` | `lib/libavcodec.so.63.1.102`, `lib/libavutil.so.61.1.102` (and without `: %d.` in `lib/libavfilter.so.12.1.102`) | QSV: no Intel GPU / no runtime (provoked above, `-9`) |
| `Error initializing an MFX session\n` | `lib/libavcodec.so.63.1.102` | QSV session init |
| `Error querying a MFX session: %d.\n` | `lib/libavutil.so.61.1.102` | QSV device query |
| `No VA display found for device %s.\n` | `lib/libavutil.so.61.1.102` | VAAPI: device path does not open (provoked) |
| `No VA display found for any default device.\n` | `lib/libavutil.so.61.1.102` | VAAPI: no device given and none found |
| `Failed to initialise VAAPI connection: %d (%s).\n` | `lib/libavutil.so.61.1.102` | VAAPI: `vaInitialize` failed (provoked) |
| `Failed to create a VAAPI device.\n` | `lib/libavcodec.so.63.1.102` | VAAPI device creation |
| `Failed to create  hardware device context (AMF) : %s\n` (two spaces) | `lib/libavcodec.so.63.1.102`, `lib/libavfilter.so.12.1.102` | AMF runtime missing |
| `Device creation failed: %d.\n` | `bin/ffmpeg` | any `-init_hw_device` failure (provoked) |
| `Error while opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.\n` | `bin/ffmpeg` | any encoder that cannot open |
| `Conversion failed!\n` | `bin/ffmpeg` | generic last line |
| `MFX_ERR_UNSUPPORTED` | **not found** | the plan's pattern; never printed |

### Language tags (FFmpeg n9.0.2, MKVToolNix v101.0)

Checked in `C-6` (`packages/reframe/tests/test_languages.py`, `needs_ffmpeg` tests):

```sh
ffmpeg -v error -y -f lavfi -i sine=d=0.2 -c:a aac -metadata:s:a:0 language=X out.mkv   # and out.mp4
ffprobe -v error -show_entries stream_tags -of compact out.mkv
mkvpropedit out.mkv --edit track:a1 --set language-ietf=pt-BR ; mkvmerge -J out.mkv
```

- **Matroska, FFmpeg:** writes the value **verbatim** into the legacy `Language` element and
  never writes `LanguageIETF` (`de` → `de`, `pt-BR` → `pt-BR`). ffprobe reads it back verbatim;
  `und` reads back as no tag. So the command builder must pass ISO 639-2/B
  (`reframe.languages.to_matroska_legacy`).
- **MP4, FFmpeg:** keeps 3-letter codes (`deu`, `ger`) and **silently drops** 2-letter codes and
  BCP 47 tags (`de`, `pt-BR` → no language). The builder must pass ISO 639-2/T (`to_mp4`).
- **mkvpropedit:** `--set language=X` writes both elements (`pt-BR` → `por` + `pt-BR`);
  `--set language-ietf=X` alone changes only `LanguageIETF` and can leave the track
  inconsistent.
- **ffprobe never shows `LanguageIETF`.** After `language-ietf=pt-BR` it still reports
  `language=por`. Reading region/script subtags back needs `mkvmerge -J` (`language_ietf`) or
  MediaInfo. This matters for `C-3` (source language) and `C-13` (re-probe after a metadata
  edit); it is decided with `C-13`.


### Hardware setup of the encoder definitions (M2 contract)

Checked on 2026-10-13 with `/usr/bin/ffmpeg` (Arch n9.0.2) on the machine above (AMD RX 7600,
no NVIDIA, no Intel GPU), encoding 3 frames to `-f null -`:

```sh
ffmpeg -hide_banner -nostdin -v error -init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va \
  -f lavfi -i color=size=640x360 -frames:v 3 -vf format=p010le,hwupload -c:v hevc_vaapi -profile:v main10 -f null -
ffmpeg -hide_banner -nostdin -v error -f lavfi -i color=size=640x360 -frames:v 3 -pix_fmt p010le -c:v hevc_amf -f null -
```

| Encoder | Setup | 8-bit | 10-bit |
|---------|-------|-------|--------|
| `h264_vaapi`, `hevc_vaapi`, `av1_vaapi` | `-init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va`, `-vf format=nv12\|p010le,hwupload` | exit 0 | exit 0 (`hevc`, `av1`) |
| `hevc_amf`, `av1_amf` | none, software frames (`-pix_fmt yuv420p` / `p010le`) | exit 0 | exit 0 |
| `h264_amf` | none | exit 0 | exit 183: `10-bit input video is not supported by AMF H264 encoder` |
| `hevc_nvenc` | none | exit 255: `Cannot load libcuda.so.1` | not run |
| `hevc_qsv` | `-init_hw_device qsv=hw -filter_hw_device hw`, `-vf hwupload=extra_hw_frames=64,format=qsv` | exit 187: `Device creation failed: -542398533.` | not run |
| `libsvtav1`, `libvpx-vp9` | software, `-pix_fmt yuv420p10le` | exit 0 | exit 0 |

`libsvtav1` prints `Svt[info]: …` lines on stderr even with `-v error` (the SVT library logs on
its own). The QSV setup is the plan's; it is not verified on an Intel GPU.

### Encoder detection (C-4)

Checked on 2026-10-13 with the pinned build (and the Arch n9.0.2 package where noted) on the
machine above (AMD RX 7600, no NVIDIA driver, no Intel GPU). Decision
[0008](../docs/decisions/0008-encoder-detection-reasons-and-filters.md) is based on these.

**The test encode** that C-4 runs is built from the hardware setup of the definitions
(`reframe.capabilities.hardware_test_argv`):

```sh
# VAAPI (10-bit: format=p010le); QSV: -init_hw_device qsv=hw -filter_hw_device hw and
# -vf format=nv12,hwupload=extra_hw_frames=64,format=qsv
ffmpeg -hide_banner -nostdin -init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va \
  -f lavfi -i color=size=640x360 -frames:v 3 -vf format=nv12,hwupload -c:v h264_vaapi -f null -
# NVENC and AMF take software frames (10-bit: -pix_fmt p010le)
ffmpeg -hide_banner -nostdin -f lavfi -i color=size=640x360 -frames:v 3 -pix_fmt nv12 \
  -c:v hevc_amf -f null -
```

The `detect_*` captures in `fake_data/` are exactly these commands
(`capture_fake_data.py --only detect_…`; `test_hwtest.py` fails when the definitions change the
command and the captures were not made again):

| Capture | Exit code | Key stderr line | C-4 reason (state) |
|---------|-----------|-----------------|--------------------|
| `detect_h264_vaapi_ok`, `detect_hevc_vaapi_10bit_ok`, `detect_hevc_amf_ok`, `detect_hevc_amf_10bit_ok` | 0 | — | available |
| `detect_hevc_nvenc_no_driver` | 255 | `[hevc_nvenc @ 0x…] Cannot load libcuda.so.1` | NVIDIA driver not found |
| `detect_hevc_qsv_no_device` | 187 | `Failed to set value 'qsv=hw' for option 'init_hw_device': Generic error in an external library` (no device line) | No Intel QSV device (needs an Intel GPU with its media driver) |
| `detect_h264_vaapi_bad_device` (`renderD999`) | 234 | `[VAAPI @ 0x…] No VA display found for device /dev/dri/renderD999.` | No VAAPI device (/dev/dri/renderD999) |
| `detect_h264_vaapi_no_driver` (`LIBVA_DRIVER_NAME=reframe_nonexistent`) | 251 | `[VAAPI @ 0x…] Failed to initialise VAAPI connection: -1 (unknown libva error).` | VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error) |
| `detect_hevc_amf_no_runtime` | 171 | `[AMF @ 0x…] DLL libamfrt64.so.1 failed to open`, then `[hevc_amf @ 0x…] Failed to create  hardware device context (AMF) : Unknown error occurred` | AMD AMF runtime not found (libamfrt64.so.1) |
| `detect_h264_amf_10bit` (`-pix_fmt p010le -c:v h264_amf`) | 183 | `[h264_amf @ 0x…] 10-bit input video is not supported by AMF H264 encoder` | 10-bit is not supported by this encoder |

- **A missing AMF runtime can be provoked without root**: `LD_LIBRARY_PATH` pointing at a
  folder with an empty `libamfrt64.so.1` makes `dlopen` fail (the capture records the folder
  as a placeholder).
- **`-h encoder=` pixel formats do not tell 10-bit support for hardware encoders**: `h264_amf`
  lists `p010le` and still refuses 10-bit. Only the test encode decides. (For software
  encoders the list is right: `libx265` lists `yuv420p10le`.)
- **QSV at `-v verbose`** says why the device fails here (`[VAAPI @ …] Ignoring device 0 with
  non-matching vendor id (0x8086).` … `Cannot open a VA display from DRM device (null).`); at
  the default level, which C-4 uses, only the fftools lines above are printed.
- **Presets in `-h encoder=`**: `libx264` / `libx265` have `-preset <string>`, so FFmpeg does
  not list them; `libsvtav1` has `-preset <int> … (from -2 to 13)` without names; NVENC lists
  `slow`, `medium`, `fast`, `p1` … `p7`; QSV `veryfast` … `veryslow`; AMF `quality`,
  `balanced`, `speed`, `high_quality` (under `-preset` and `-quality`); VAAPI has no `-preset`
  and lists only the pixel format `vaapi`.
- **`-filters`**: FFmpeg 9 prints two flag columns (`T.`, `.S`), FFmpeg 7 printed three
  (`TSC`). The pinned build has 562 filters, `libplacebo` and `zscale` among them.
- **`libplacebo` needs a working Vulkan device.** `-filters` lists it whether Vulkan works or
  not, so detection runs one frame through it (checked 2026-10-13, both builds; the commands
  are the `detect_libplacebo_*` captures):

  ```sh
  ffmpeg -hide_banner -nostdin -f lavfi -i color=size=640x360 -frames:v 1 -vf libplacebo -f null -
  ```

  With RADV (Mesa) on the RX 7600: exit 0 in about 0.18 s (Vulkan start-up). With
  `VK_ICD_FILENAMES=/nonexistent/icd.json` (no Vulkan driver): exit 187 and

  ```
  [libplacebo @ 0x…] Failed creating instance: VK_ERROR_INCOMPATIBLE_DRIVER
  [libplacebo @ 0x…] Failed initializing vulkan instance
  [libplacebo @ 0x…] Failed initializing vulkan device
  [Parsed_libplacebo_0 @ 0x…] Failed creating Vulkan device!
  [AVFilterGraph @ 0x…] Error initializing filters
  Error opening output file -.
  Error opening output files: Generic error in an external library
  ```

  → "No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)". libplacebo is linked into
  `libavfilter` and loads `libvulkan.so.1` at run time; its other device errors (`Found no
  suitable device, giving up.`, `Vulkan device does not support all required features!`,
  `Failed creating logical device!`) are confirmed in `lib/libavfilter.so.12.1.102` only
  (`library_strings.json`).
- **Render nodes** (decision 0020): this machine has one, `/dev/dri/renderD128` (plus
  `card1` and `by-path/`). Detection lists `/dev/dri/renderD*` sorted by number and tests each
  VAAPI encoder on them in turn; the multi-node logic is proved with the fake ffmpeg
  (`test_detect.py`: two nodes, the first fails with the real "no VA driver" text).
- **Timing**: `-encoders`, `-filters` and each `-h encoder=` take about 10 ms, a test encode
  about 30 ms, the libplacebo test about 0.18 s. A full detection (23 encoders of the
  definitions, 12 hardware tests plus the 10-bit tests, the libplacebo test): **0.36 s** with
  the pinned build, 0.69 s with the Arch package (0.20 – 0.40 s before the libplacebo test).

Real result with the pinned build (`detect_capabilities`, hardware tests on; `libplacebo`
usable):

| Encoder | State | 10-bit | Device | Reason |
|---------|-------|--------|--------|--------|
| `libx264`, `libx265`, `libsvtav1`, `libvpx-vp9` | available | yes | – | |
| `h264_nvenc`, `hevc_nvenc`, `av1_nvenc` | unavailable | – | – | NVIDIA driver not found |
| `h264_qsv`, `hevc_qsv`, `av1_qsv` | unavailable | – | – | No Intel QSV device (needs an Intel GPU with its media driver) |
| `h264_amf` | available | no (no 10-bit format in the definition) | – | |
| `hevc_amf`, `av1_amf` | available | yes | – | |
| `h264_vaapi` | available | no (no 10-bit format in the definition) | `/dev/dri/renderD128` | |
| `hevc_vaapi`, `av1_vaapi` | available | yes | `/dev/dri/renderD128` | |
| `aac`, `ac3`, `eac3`, `libopus`, `flac`, `libmp3lame` | available | – | – | |
| `libfdk_aac` | unavailable | – | – | Not in this FFmpeg build |

### Encoder definitions (C-6)

Checked on 2026-10-13 with both n9.0.2 builds (Arch `/usr/bin/ffmpeg` and the pinned BtbN
build; x264 core 165, x265 4.3, SVT-AV1 v4.2.0, libvpx 1.17.0) and, for AMF and VAAPI, an
AMD RX 7600. Checked again on 2026-10-15 (the HEVC encoder's own log line "HEVC encoder
version"): Arch n9.0.2 has x265 4.3, x264 core 165 r3222, SVT-AV1 v4.2.0; both BtbN builds
(n9.0.2 and n8.1.3) have x265 4.3+49-020d7054, x264 core 165, SVT-AV1 v4.2.0-151-g5ed9ffbcb;
all three libvpx v1.17.0. (This section said x265 4.1 before: no build here has it.) The
M2 review fixes (2026-10-14) were checked with these and with the CI override build n8.1.3
(BtbN `n8.1.3-9-g29e619e767`). `packages/reframe/tests/definitions/test_tools.py` repeats
every check (`needs_ffmpeg`; the AMF / VAAPI encodes are `needs_gpu`); where n8.1.3 differs,
the test asserts what each version does:

```sh
uv run pytest packages/reframe/tests/definitions/test_tools.py           # the active build
REFRAME_FFMPEG=…/bin/ffmpeg REFRAME_FFPROBE=…/bin/ffprobe uv run pytest …  # another build
```

HandBrake values (encoder keys, filter presets, audio bitrates, quality ranges, presets) come
from HandBrake **1.11.2** (`libhb/common.c`, `libhb/param.c`, `libhb/encavcodec.c`,
`preset/preset_builtin.json`). The `handbrake_key` values of the M2 contract match
`hb_video_encoders` (`x264`, `x265`, `svt_av1`, `VP9`, `nvenc_h264` … `vce_av1`); HandBrake has
no VAAPI encoders, so the `vaapi_*` keys are Reframe's own.

**Encoder options.** Every private option, preset, tune, profile and level that the definitions
write exists in `ffmpeg -h encoder=<id>` (named constants included), for all 16 video encoders;
help works without the hardware. x264 and x265 take free text and print their own lists for a
bad value:

```
$ ffmpeg -f lavfi -i testsrc2 -c:v libx264 -preset bogus -f null -
[libx264 @ …] Possible presets: ultrafast superfast veryfast faster fast medium slow slower veryslow placebo
[libx264 @ …] Possible tunes: film animation grain stillimage psnr ssim fastdecode zerolatency
$ … -c:v libx265 -profile:v bogus …
[libx265 @ …] Possible profiles: main main10 mainstillpicture msp main-intra main10-intra main444-8 …
```

**x264 / x265 per-preset defaults** are read from the settings both libraries write into the
stream (`x264 - core 165 … options: cabac=1 ref=3 …`, `x265 … options: … bframes=4 b-adapt=2
…`) after a 3-frame encode per preset. The tables are in `definitions/data/options/x26*.toml`;
a summary:

| Preset | x264 bframes / ref / subme / rc-lookahead / me | x265 bframes / ref / rd / rc-lookahead / ctu |
|--------|-----|-----|
| ultrafast | 0 / 1 / 0 / – / dia | 3 / 1 / 2 / 5 / 32 |
| veryfast | 3 / 1 / 2 / 10 / hex | 4 / 2 / 2 / 15 / 64 |
| medium | 3 / 3 / 7 / 40 / hex | 4 / 3 / 3 / 20 / 64 |
| slow | 3 / 5 / 8 / 50 / hex | 4 / 4 / 4 / 25 / 64 |
| veryslow | 8 / 16 / 10 / 60 / umh | 8 / 5 / 6 / 40 / 64 |
| placebo | 16 / 16 / 11 / 60 / tesa | 8 / 5 / 6 / 60 / 64 |

**Bad parameters do not fail.** `-x264-params bogus=1` logs `Error parsing option 'bogus = 1'.`,
`-x265-params bogus=1` logs `Unknown option: bogus.`, `-svtav1-params bogus=1` logs `Error
parsing option bogus: 1.`, and all three encode on with exit code 0. A dry run of custom
parameters (C-8) must read the log, not only the exit code. Other library behaviour:

- x265 turns SAO back on for `selective-sao=N` (N > 0) even with `sao=0`; `hdr10-opt=1` is
  dropped unless the output is tagged BT.2020 ("Recommended Settings for HDR10-opt: colour
  primaries should be BT.2020, Disabling hdr10-opt."). `level-idc=4.1` is written as 41.
- FFmpeg's libx265 wrapper sets `repeat-headers` when the muxer has no global headers.
- libx264's `fastfirstpass` is on by default: a full first pass needs `-fastfirstpass 0`.
- SVT-AV1 v4.2: default preset 8 and tune 1 (PSNR) (log: `preset / tune / pred struct : 8 /
  PSNR`); presets 12 and 13 are mapped to 11; tune 3 (IQ) fails for normal (random access)
  encodes; `level=4.1` is rejected, `level=41` works.
- libvpx-vp9: `-crf N` alone gives the same file as `-crf N -b:v 0`.

**Range ends (M2 review, 2026-10-14, all three builds: both n9.0.2 and n8.1.3).** Each end of
every quality range and every number option must have its own effect
(`test_quality_range_ends_are_honoured`, `test_option_range_ends_encode`,
`test_recorded_cross_option_rules`, and `test_hardware_quality_range_ends_are_honoured` on the
RX 7600):

| Encoder | What the tools do | Range in the definitions |
|---------|-------------------|--------------------------|
| `libsvtav1` | `-crf 0` is "not set": the log says `CRF / 35.00` and the file is the same as with no `-crf` | quality 1–63 |
| `h264_vaapi`, `hevc_vaapi`, `av1_vaapi` | `-global_quality 0` is "not set": the driver's QP (h264 20, hevc 25, av1 25), the same file as no value. 52 gives the same file as 51 (av1: 256 as 255) | 1–51 (av1 1–255) |
| `av1_amf` | QP 0: `AMF_OUT_OF_RANGE: SetPropertyInternal() Av1QIndex_Intra failed`, exit 0, the same file as no QP. 256: "Value 256 … out of range [-1 - 255]" | 1–255 |
| `h264_amf`, `hevc_amf` | QP 0 works (a larger file than 1); 52: "out of range [-1 - 51]" | 0–51 |
| `libx265` | `ref` 9 and more with B-frames: "NumPocTotalCurr (total references) is non-compliant", encoder not opened (works with `bframes=0`). `merange=32768`: "Search Range must be less than 32768". `rc-lookahead` at or below `bframes`: "Lookahead depth must be greater than the max consecutive bframe count" (0 works with `bframes=0`) | `ref` 1–8, `merange` 0–32767; the look-ahead rule is for validation (C-8) |
| `libx264` | `subme` 10 and 11 need `trellis=2`: with 0 or 1 the stream says `subme=9`, no message | a note in the help; the rule is for validation (C-8) |
| `libsvtav1` | `lookahead=-1`: "Error parsing option lookahead: -1.", exit 0. 121: "The lookahead distance must be [0 - 120]" | 0–120, default "encoder decides" |
| `av1_nvenc` | `ffmpeg -h`: `-cq` 0–63, `-init_qpI/P/B` 0–255 (`hevc_nvenc`: both 0–51) | initial QPs = CQ × 255/63 ∓ 8 (not checked on NVIDIA hardware) |

A quality value converted between encoders (`convert_quality`) is rounded half up: x264 RF 23
is 26.5 on the QSV, AMF and VAAPI scales and becomes 27 on all three.

**n8.1.3 against n9.0.2.** `h264_amf` and `hevc_amf` have no `high_quality` constant for
`-quality` / `-preset` in n8.1.3 (only `speed`, `balanced`, `quality`); C-4 reads the build's
presets, so `supported_presets` does not offer it there. Every other private option, constant
and range that the definitions use is the same.

**av1_amf pads the picture (RX 7600, VCN 4; all three builds).** 1920x1080 is written as
1920x1082, 640x360 as 640x362 and 720x480 as 768x480 (ffprobe `width` / `height`; the width
goes up to a multiple of 64, a height that is not a multiple of 16 gets 2 more lines). The
extra lines repeat the picture's edge. 1280x720 and 3840x2160 stay as they are. `av1_vaapi` on
the same GPU writes 1920x1080; `hevc_amf` keeps the display size and pads only the coded size
(`coded_height` 1088). `test_av1_amf_pads_the_picture` records it.

**Hardware rate control (AMF, VAAPI on radeonsi).** Every preset, profile, level, the quality
mode at min / default / max, average bitrate and every option encode:

| Encoder | Quality mode (as in the definitions) | Notes |
|---------|------------------|-------|
| `h264_amf`, `av1_amf` | `-rc cqp -qp_i Q -qp_p Q+2 -qp_b Q+4` (AV1: +8 / +16, range 1–255) | HandBrake's offsets. `hevc_amf` has no `-qp_b` |
| `h264_vaapi`, `hevc_vaapi`, `av1_vaapi` | `-rc_mode CQP -global_quality Q` | ICQ fails: "Driver does not support ICQ RC mode (supported modes: CQP, CBR, VBR, QVBR)". `av1_vaapi` has no `-qp`. With no quality option h264 uses QP 20 and hevc QP 25 (same files as `-qp 20` / `-qp 25`) |

`-bf 2` gives B-frames on `h264_amf` (ffprobe `has_b_frames=2`); `h264_vaapi` uses B-frames
by default and `-bf 0` turns them off; `hevc_vaapi` and `av1_amf` encode without B-frames
whatever `-bf` says ("The current GPU in use does not support AV1 B-frame encoding"). With no
profile set, `h264_vaapi` writes High and `h264_amf` Main.

**Audio encoders.** Each mixdown at its minimum, default and maximum bitrate (and every value of
the fixed-step lists), every listed sample rate and the VBR quality range encode. Behaviour
behind the data:

| Encoder | What FFmpeg does |
|---------|------------------|
| `ac3` | Snaps silently to the AC-3 rates: `-b:a 150k` → 160 kb/s, 24k → 32k, 700k → 640k. 5.1 below 40k fails. 7.1 input is negotiated down to 5.1(side). Default without `-b:a`: 96 / 192 / 448 kb/s (mono / stereo / 5.1) |
| `eac3` | Takes any value from 24k to 6144k (7000k fails); 5.1 maximum (7.1 → 5.1(side)) |
| `aac` | Above 6144 bits per frame per channel: "Too many bits … clamping to max" (stereo 600k) |
| `libopus` | 0.5 kb/s to 256 kb/s per channel: "The bit rate 600000 bps is unsupported. Please choose a value between 500 and 512000." 7.1 works (2048k maximum) |
| `libmp3lame` | Snaps to the MPEG-1 Layer III rates (150k → 160k, 8k → 32k at 48 kHz); mono and stereo only |
| all | An unlisted output rate fails: "Specified sample rate 44100 is not supported by the libopus encoder" (`ac3` at 96000 too). Without `-ar` FFmpeg picks a supported rate itself |

**Containers** (`-c copy` from Matroska sources, read back with ffprobe):

| Codec | MKV | MP4 | WebM |
|-------|-----|-----|------|
| h264, hevc | yes | yes (`avc1`, `hev1`; `-tag:v hvc1` works) | no ("Could not write header") |
| av1, vp9 | yes | yes | yes |
| vp8 | yes | no ("Could not find tag for codec vp8") | yes |
| mpeg1video, mpeg2video, mpeg4, mjpeg | yes | yes | no |
| prores, wmv2, msmpeg4v3, theora | yes | no | no |
| aac, ac3, eac3, mp3, opus, flac, alac, pcm_s16le/s24le/s32le | yes | yes | opus only |
| truehd | yes | only with `-strict -2` ("truehd in MP4 support is experimental") | no |
| dts | yes | yes (tag `mp4a`) | no |
| vorbis | yes | yes (tag `mp4a`; HandBrake does not allow it) | yes |
| subrip, ass, webvtt | yes | no (only mov_text) | webvtt only |
| mov_text | no ("Subtitle codec mov_text … is not supported") | yes | no |
| dvd_subtitle (VobSub) | yes | **yes** (tag `mp4s`) | no |
| hdmv_pgs_subtitle | yes (from libavformat/matroskaenc.c: FFmpeg has no PGS encoder to test) | no (no tag in libavformat/movenc.c `codec_mp4_tags`) | no |
| ttf attachment | yes | no ("Could not find tag for codec ttf") | dropped without an error |

**Matroska `copy_except` (M2 review, all three builds).** MKV takes `copy = ["*"]` for audio
and video, but the muxer refuses some codecs. A stream of every audio encoder and every
software video encoder in the build was `-c copy`-muxed into Matroska
(`test_mkv_copy_except_matches_the_muxer` repeats it for the denied codecs and a set of
allowed ones):

| Result | Codecs |
|--------|--------|
| refused: "No wav codec tag found for codec …", exit 234 | pcm_bluray, pcm_dvd, s302m, pcm_s24daud, pcm_vidc, pcm_s8, pcm_s8_planar, pcm_s16le/s16be/s24le/s32le_planar, pcm_s64be, pcm_u16le/u16be/u24le/u24be/u32le/u32be, pcm_f32be, pcm_f64be, dsd_lsbf_planar and dsd_msbf_planar (from a hand-made DSF file), adpcm_adx, adpcm_argo, adpcm_g726le, adpcm_ima_alp/amv/apm/qt/ssi/ws, aptx, aptx_hd, comfortnoise, gsm, nellymoser, roq_dpcm, sbc |
| refused: "Raw RGB is not supported Natively in Matroska" | rawvideo with an RGB pixel format (YUV rawvideo works) |
| exit 0, but the file cannot be read back ("unknown codec", "Duplicate element") | dfpwm, dirac (vc2), gif, qtrle, rpza; svq1 in n9.0.2 only (n8.1.3 reads it back) |
| copied and read back | pcm_s16le/s16be/s24le/s24be/s32le/s32be/s64le, pcm_u8, pcm_f32le, pcm_f64le, pcm_alaw, pcm_mulaw, adpcm_ms, adpcm_ima_wav, adpcm_g722, adpcm_g726, adpcm_swf, adpcm_yamaha, mp2, wavpack, alac, tta, mlp, truehd, ffv1, prores, png, mjpeg … |

Not verified (FFmpeg has no encoder, and no hand-made source worked): pcm_f16le, pcm_f24le,
pcm_lxf, pcm_sga, dsd_lsbf, dsd_msbf. They are denied too, so they are encoded instead of a
mux that may fail. Decode-only game and telephony ADPCM variants are not in the list.

Chapters: all three keep the 4 chapters of the `chapters` fixture.

Dispositions (two AAC / Opus tracks, `-disposition:a:0 X -disposition:a:1 0`, read back):

| Disposition | MP4 | WebM |
|-------------|-----|------|
| `default`, `forced` | yes | yes |
| `comment` | yes | no |
| `hearing_impaired` | yes (ffprobe also shows `captions`) | no |
| `visual_impaired` | yes (ffprobe also shows `descriptions`) | no |
| `original` | no | no |

With no default track of a type, the MP4 muxer marks the first one default (`[1, 0]` for
`-disposition 0` on both); Matroska and WebM write `[0, 0]`. Matroska writes all six flags
(see above). mkvpropedit's names are `flag-default`, `flag-forced`, `flag-commentary`,
`flag-hearing-impaired`, `flag-visual-impaired`, `flag-original` (`mkvpropedit
--list-property-names`, v101.0).

**Filters.** Both builds have every filter the definitions use: `fieldmatch`, `decimate`,
`idet`, `bwdif`, `yadif`, `nlmeans`, `hqdn3d`, `deblock`, `unsharp`, `cas`, `hue`, `zscale`,
`tonemap`, `libplacebo`, `colorspace`. Every preset and tune chain runs (`-frames:v 2 -f null
-`; colour filters on the `hdr10` fixture). Behaviour behind the data:

- `zscale` fails on an untagged source (`testsrc2`): "no path between colorspaces". After
  `setparams=color_primaries=…:color_trc=…:colorspace=…` it works.
- `libplacebo` needs a Vulkan driver: with `VK_ICD_FILENAMES=/nonexistent.json` it fails
  ("Error initializing filters", "Generic error in an external library") although
  `ffmpeg -filters` lists it.
- `idet` sets the interlaced flag on the frames it detects
  (`setfield=prog,idet,showinfo` on the `interlaced` fixture shows `i:T`), so
  `bwdif` / `yadif` `deint=interlaced` processes only those.
- `colorspace=all=bt709` fails on the 10-bit HDR fixture; the definitions use `zscale`.

### Sleep inhibit (C-14)

Checked on 2026-10-13 on Arch Linux, systemd 262, KDE Plasma 6 (Wayland, PowerDevil),
dbus on `/run/dbus/system_bus_socket`, session bus `unix:path=/run/user/1000/bus`.
Decisions [0011](../docs/decisions/0011-sleep-inhibit.md) (client, Windows thread) and
[0020](../docs/decisions/0020-m2-wave-1-product-decisions.md) (only automatic sleep). Code:
`reframe/platform/sleep.py`, `reframe/platform/dbus.py`. Tests:
`packages/reframe/tests/platform/test_sleep_real.py` (skipped without the bus or service).
Other programs hold inhibits too (here a playing Jellyfin client: KDE lists `"idle"
"jellyfin-desktop" "playing"`, which sets both PolicyAgent flags; parallel test runs), so each
real test finds only its own inhibit by a unique reason in logind `ListInhibitors` and KDE
`ActiveInhibitions` (`busctl --json=short`). Global flags (`HasInhibit`, the PolicyAgent's
`HasInhibition`) are only printed: "it was false before" did not prove that nothing else
changed it (M2 review, 2026-10-14: `systemd-inhibit --what=idle sleep 45` started just before
the session test sets KDE's "screen" flag about 5 s later, during the test). `CanSuspend` is
asserted only while no other program holds a logind `sleep` block lock. Every lock and
connection is freed in a `finally`, so a failing check leaks no socket into a later test
(before, it failed `tests/probe/test_live.py` with `PytestUnraisableExceptionWarning …
finalizing socket … /run/user/1000/bus`). Checked on 2026-10-14: the platform tests pass
while `systemd-inhibit --what=idle sleep 120` runs, and a deliberately failing check in the
session test fails only that test.

**Timing on KDE.** PowerDevil makes every inhibition active about **5 s** after it is
requested, also the ones it mirrors from logind (polled every second: `false` at 0–4 s,
`true` from 5 s). An earlier check in this section looked after 1 s and wrongly found that
KDE ignores logind locks (0011's context and 0020's context repeat that); it does not.

What each lock does on KDE, measured 6–7 s after it was taken. `suspend` / `screen` are
PowerDevil's `PolicyAgent.HasInhibition(1)` (InterruptSession: the automatic suspend on idle)
and `HasInhibition(4)` (ChangeScreenSettings: dimming, screen off, lock).

| Lock | `CanSuspend` (logind) | KDE `ActiveInhibitions` | suspend | screen |
|------|-----------------------|-------------------------|---------|--------|
| none | `yes` | – | `false` | `false` |
| logind `sleep` block | `inhibited` | `"sleep" … "block"` | `true` | `false` |
| logind `idle` block | `yes` | `"idle" … "block"` | `true` | **`true`** |
| `org.freedesktop.PowerManagement.Inhibit.Inhibit("Reframe", why)` | `yes` | `"sleep" "Reframe" why "block"` | `true` | `false` |
| portal `Inhibit("", 4 /*suspend*/, {reason})` | `yes` | `"sleep" "com.microsoft.VSCode" why "block"` | `true` | `false` |
| portal `Inhibit("", 8 /*idle*/, {reason})` | `yes` | `"idle" … "block"` | `true` | **`true`** |

So, for "stop only automatic sleep, the screen may still lock" (0020), the right lock on
KDE is the PowerManagement inhibit (or the portal with flag 4). A logind `sleep` lock refuses
the user's own suspend (`inhibited`); a logind `idle` lock and the portal's idle flag also
keep the screen on. The portal names the app from the caller's cgroup (here the terminal's
VS Code scope), PowerManagement shows "Reframe". `CanSuspend` stays `yes` with every lock
but the logind `sleep` one. Not checked: an actual suspend (this machine was never
suspended), KDE's handling of the power button and lid during an inhibit.

Reframe's Linux hold (the default inhibitor, `create_sleep_inhibitor()`):

1. The session inhibit: PowerManagement, else the portal with flag 4. It lasts while the
   connection is open. Release calls `UnInhibit(cookie)` / `Request.Close()` and then closes
   the connection. Each of these alone ends it (checked: `UnInhibit` with the connection
   open; `Request.Close()` with the connection open; closing the connection without either).
   No session bus → skipped (nothing on a headless machine suspends on the desktop's idle).
2. The logind `idle` lock, only where needed: when the session inhibit is not held, or when
   logind's `IdleAction` is not `ignore` (here: `ignore`, `IdleActionUSec` 30 min).
3. `systemd-inhibit` is not used: with `--what=idle` it reaches the same logind with the same
   polkit rule (`inhibit-block-idle` is `yes` for every caller) as the direct call, so it
   adds a long-running process and no coverage, and it cannot take the session inhibit.

Session-bus services on this desktop (`busctl --user list`, trimmed):

```text
org.freedesktop.PowerManagement          1766 org_kde_powerde
org.freedesktop.PowerManagement.Inhibit  1766 org_kde_powerde
org.freedesktop.ScreenSaver              1610 kwin_wayland
org.freedesktop.portal.Desktop           2047 xdg-desktop-por
org.freedesktop.impl.portal.desktop.kde  2101 xdg-desktop-por
org.kde.Solid.PowerManagement.PolicyAgent 1766 org_kde_powerde
```

```console
$ busctl --user introspect org.freedesktop.PowerManagement.Inhibit /org/freedesktop/PowerManagement/Inhibit org.freedesktop.PowerManagement.Inhibit
NAME               TYPE   SIGNATURE RESULT/VALUE FLAGS
.HasInhibit        method -         b            -
.Inhibit           method ss        u            -
.UnInhibit         method u         -            -
.HasInhibitChanged signal b         -            -
$ busctl --user introspect org.freedesktop.portal.Desktop /org/freedesktop/portal/desktop org.freedesktop.portal.Inhibit
NAME              TYPE     SIGNATURE RESULT/VALUE FLAGS
.CreateMonitor    method   sa{sv}    o            -
.Inhibit          method   sua{sv}   o            -
.QueryEndResponse method   o         -            -
.version          property u         3            emits-change
.StateChanged     signal   oa{sv}    -            -
$ busctl introspect org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager | grep -i inhibit
.Inhibit                          method   ssss                h                                                                            -
...
$ busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager IdleAction IdleActionUSec IdleHint
s "ignore"
t 1800000000
b false
```

The PowerManagement inhibit with a held connection, polled every second (KDE's
`RequestedInhibitions` / `ActiveInhibitions`), then the connection closed without
`UnInhibit`:

```text
 0.0s suspend=b false requested=a(ssssu) 0 active=a(ssssu) 0
 4.0s suspend=b false requested=a(ssssu) 0 active=a(ssssu) 0
 5.0s suspend=b true requested=a(ssssu) 1 "sleep" "Reframe" "probe pm" "block" 3 active=a(ssssu) 1 "sleep" "Reframe" "probe pm" "block" 3
closed+1.0s suspend=b false requested=a(ssssu) 0 active=a(ssssu) 0
```

The real tests (`uv run pytest -s packages/reframe/tests/platform/test_sleep_real.py`):

```text
logind during: ['Reframe 1000 peti 748992 pytest idle Reframe test ff1140ad block']; CanSuspend before=yes during=yes
logind after: []
desktop before: PowerManagement HasInhibit=0; KDE PolicyAgent suspend=0 screen=0; ActiveInhibitions: a(ssssu) 0
desktop during: PowerManagement HasInhibit=1; KDE PolicyAgent suspend=1 screen=0; ActiveInhibitions: a(ssssu) 1 "sleep" "Reframe" "Reframe session test" "block" 3
desktop after: PowerManagement HasInhibit=0; KDE PolicyAgent suspend=0 screen=0; ActiveInhibitions: a(ssssu) 0
default: backends=('session',) IdleAction=ignore
default during: logind []; PowerManagement HasInhibit=1; KDE PolicyAgent suspend=1 screen=0; ActiveInhibitions: a(ssssu) 1 "sleep" "Reframe" "Reframe default 14a58319" "block" 3; CanSuspend yes
headless: backends=('logind',) during=['Reframe 1000 peti 748992 pytest idle Reframe headless d1e0ab3f block']
portal during: PowerManagement HasInhibit=1; KDE PolicyAgent suspend=1 screen=0; ActiveInhibitions: a(ssssu) 1 "sleep" "com.microsoft.VSCode" "Reframe portal test" "block" 3
portal after Request.Close (connection open): PowerManagement HasInhibit=0; KDE PolicyAgent suspend=0 screen=0; ActiveInhibitions: a(ssssu) 0
PowerManagement after the connection closed: PowerManagement HasInhibit=0; KDE PolicyAgent suspend=0 screen=0; ActiveInhibitions: a(ssssu) 0
logind idle lock only, KDE during: PowerManagement HasInhibit=1; KDE PolicyAgent suspend=1 screen=1; ActiveInhibitions: a(ssssu) 1 "idle" "Reframe" "Reframe KDE mirror test" "block" 3
```

Without any bus, the one warning event:

```json
{
  "type": "app.warning",
  "code": "sleep_inhibit.unavailable",
  "message": "Sleep inhibit is not available: the computer may go to sleep on its own while the queue runs.",
  "detail": "logind: no system bus: FileNotFoundError: [Errno 2] No such file or directory; session: no session bus: FileNotFoundError: [Errno 2] No such file or directory"
}
```

polkit defaults (`/usr/share/polkit-1/actions/org.freedesktop.login1.policy`):
`inhibit-block-idle` is `yes` for any, inactive and active callers; `inhibit-block-sleep` is
`auth_admin_keep` for any other caller (not used any more). No call sets
`ALLOW_INTERACTIVE_AUTHORIZATION`, and none of the session calls asked for anything.

The client's bytes for the three calls are identical to jeepney 0.9.0's
`new_method_call(…).serialise(serial=2)` (logind `Inhibit` `ssss`, PowerManagement `Inhibit`
`ss`, portal `Inhibit` `sua{sv}`; kept as golden values in `test_sleep_dbus.py`). A logind
error reaches it as `org.freedesktop.DBus.Error.InvalidArgs: Invalid what specification
bogus`.

**GNOME (not tested, no GNOME here).** GNOME has no `org.freedesktop.PowerManagement`
service, so Reframe uses the portal there. The portal documentation
(<https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Inhibit.html>)
gives the flags (1 logout, 2 user switch, 4 suspend, 8 idle) and ends an inhibition with
`Request.Close()`; it does not say what happens when the caller disconnects, which is why
release calls `Close()` first. Whether GNOME's automatic suspend honours a suspend inhibit
and still lets the user suspend from the menu is not verified.

**Failures that are not D-Bus errors** (`test_sleep_failures.py`, checked 2026-10-14).
Sleep inhibit never raises (0011 item 7): each one makes that backend unavailable, its
socket is closed, and the queue goes on (one `sleep_inhibit.unavailable` warning when
nothing holds). The `last_error` texts, with both bus addresses set to the same value:

| `DBUS_*_BUS_ADDRESS` or peer | what the backend says |
|------------------------------|-----------------------|
| `unix:path=%zz`, `unix:abstract=%0` | `ValueError: malformed D-Bus address …: bad escape '%zz'` |
| `unix:path=/tmp/%ff%fe` | `ValueError: malformed D-Bus address …: an escaped value is not UTF-8` |
| `unix:path=/tmp/reframe%00bus` | `ValueError: malformed D-Bus address …: a path cannot contain NUL` |
| `unix:path=` | `OSError: [Errno 22] Invalid argument` (skipped: no session bus) |
| `unix:path=/xxx…` (300 characters) | `OSError: AF_UNIX path too long` |
| a peer that closes at once / after `AUTH` / during `NEGOTIATE_UNIX_FD` | `ConnectionResetError` or `ConnectionError: the bus closed the connection` |
| a peer that sends 20 000 bytes without `\r\n` | `authentication line too long` |
| a reply whose `REPLY_SERIAL` or `UNIX_FDS` field is a string | `DBusProtocolError: header field 5 has type 's', not 'u'` |

Before this, a malformed address raised `ValueError` out of `acquire()` (every queued job
failed with "Internal error: ValueError"), and a garbage header field leaked the session
socket.

Windows (`SetThreadExecutionState`) is not checked on a real machine: the values and the
"return value is NULL on failure" rule are from
<https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate>
(`ES_CONTINUOUS` 0x80000000, `ES_SYSTEM_REQUIRED` 0x00000001; "cannot be used to prevent the
user from putting the computer to sleep").

### Command builder (C-7)

Checked on 2026-10-13 with both n9.0.2 builds (Arch `/usr/bin/ffmpeg` and the pinned BtbN
build) on the machine above (AMD RX 7600: VAAPI, AMF and libplacebo work). Decision
[0013](../docs/decisions/0013-command-builder-details.md) is based on these.
`packages/reframe/tests/command/test_integration.py` runs the builder's plans on the fixtures
and probes the results again (both builds pass; the VAAPI / AMF cases are `needs_gpu`):

```sh
uv run pytest packages/reframe/tests/command/test_integration.py
REFRAME_FFMPEG=$BIN/ffmpeg REFRAME_FFPROBE=$BIN/ffprobe uv run pytest packages/reframe/tests/command
```

**Stream tags and dispositions are copied from the source.** Without options, the source's
stream tags (also mkvmerge statistics: the recorded `stale-stats` probe) and dispositions go
into the output. `-map_metadata:s -1` drops the stream tags; then the attachments need their
own map, or the Matroska muxer fails. An empty value removes a tag:

```console
$ ffmpeg -i multitrack.mkv -map 0:0 -map 0:1 -map 0:4 -c copy -metadata:s:a:0 title= t2.mkv
stream|index=1|codec_name=ac3|disposition:default=1|…|tag:language=jpn|tag:ENCODER=Lavc63.1.102 ac3|tag:DURATION=…
$ ffmpeg -i text-subs.mkv -map 0:v -map 0:s -map 0:t? -c copy -map_metadata:s -1 t4.mkv
[matroska @ 0x…] Attachment stream 3 has no filename tag.
[out#0/matroska @ 0x…] Could not write header (incorrect codec parameters ?): Invalid argument   (exit 234)
$ ffmpeg … -map_metadata:s -1 -map_metadata:s:t:0 0:s:t:0 t5.mkv          # exit 0
stream|index=3|codec_name=ttf|codec_type=attachment|tag:filename=ReframeBox.ttf|tag:mimetype=application/x-truetype-font
```

`-map_metadata -1` would also drop the chapter titles (they are "chapter metadata"), so the
builder uses `-map_metadata:s -1` and `-map_metadata:g -1` separately.

**MP4.** `deu` (ISO 639-2/T), `-tag:v hvc1`, `mov_text` and the six flags as in the C-6
table. A track title is written as the `udta` name and **read back as `name`, not `title`**
(C-3's probe reads only `title`):

```console
$ ffmpeg … -metadata:s:a:0 language=deu -metadata:s:a:0 "title=English Stereo" … -movflags +faststart -f mp4 m1.part.m4v
stream|index=1|codec_name=aac|codec_tag_string=mp4a|disposition:default=1|…|tag:language=deu|tag:handler_name=SoundHandler|tag:name=English Stereo
```

Without `-f`, a `.m4v` name selects the `ipod` muxer: `[ipod @ 0x…] Could not find tag for
codec opus in stream #1, codec not currently supported in container` (exit 234); with
`-f mp4` the same command works. TrueHD in MP4 needs a plain `-strict -2`: with
`-strict:a:0 -2` the muxer still says `truehd in MP4 support is experimental, add '-strict -2'
if you want to use it.` (exit 88).

**Chapters and the range.** With an input `-t`, copied chapters are shifted by the seek but
not cut; an output `-t` cuts them (`test_time_range_cuts_the_copied_chapters`):

```console
$ ffmpeg -ss 1.2 -t 2 -i chapters.mkv -map 0:v -c:v libx264 -map_chapters 0 c1.mkv
chapter|start_time=0.000000|end_time=1.300000|tag:title=Part One
chapter|start_time=1.300000|end_time=2.800000|tag:title=Part Two
chapter|start_time=2.800000|end_time=3.800000|tag:title=Credits
format|duration=2.000000
```

A chapter edge exactly on the range start or end leaves an **empty chapter** (checked on
2026-10-14 with both n9.0.2 builds; `-c:v libx264 -map_chapters 0` on the `chapters` fixture,
whose chapters are 0–1, 1–2.5, 2.5–4 and 4–5 s): FFmpeg skips a chapter only when it ends
before the seek point and stops only at one that starts after the range end. So the builder
writes such chapters as FFMETADATA (decision 0013, chapter follow-up;
`test_chapter_range_end_after_the_last_chapter_is_clamped`):

| Options | Chapters read back |
|---------|--------------------|
| `-ss 2.5` | `Part One 0.0–0.0`, `Part Two 0.0–1.5`, `Credits 1.5–2.5` |
| `-ss 1 … -t 3` | `Opening 0.0–0.0`, `Part One 0.0–1.5`, `Part Two 1.5–3.0`, `Credits 3.0–3.0` |
| `-ss 4 … -t 1` | `Part Two 0.0–0.0`, `Credits 0.0–1.0` |
| `-ss 1.2 … -t 2` | `Part One 0.0–1.3`, `Part Two 1.3–2.0` (no edge on the range: no empty chapter) |

An FFMETADATA input (`-f ffmetadata -i x.txt -map_chapters 1`) is not shifted by the source's
`-ss`; `\=`, `\;`, `\#` escape those characters in titles (`title=First \= one\; \#x` reads
back as `First = one; #x`).

**Two-pass `loudnorm`.** Two `loudnorm` filters in one run (`-filter:a:0 …loudnorm=I=-23…`,
`-filter:a:1 loudnorm=I=-16…`) print their blocks **in reverse output order** (the −16 block,
`"output_i" : "-16.00"`, came first), and both are prefixed `[Parsed_loudnorm_0 @ 0x…]`
(the index is local to each graph). So each normalised track gets its own analyse run. Other
facts: the JSON keys are `input_i`, `input_tp`, `input_lra`, `input_thresh`, `output_*`,
`normalization_type`, `target_offset`; `LRA` takes 1 to 50; a silent track measures
`"input_i" : "-inf"` and `"target_offset" : "inf"`, and the second pass refuses that
(`Value -inf for parameter 'measured_I' out of range [-99 - 0]`, exit 222); without `-ar` the
`loudnorm` output (192 kHz) reaches the AAC encoder as 96 kHz. `aresample` in n9.0.2 has no
`ocl` alias (`Error applying option 'ocl' to filter 'aresample': Option not found`): the
option is `out_chlayout`.

**Two-pass statistics files** (encoder library default names, killed half-way to see the
temporary ones):

| Encoder | Option | Files |
|---------|--------|-------|
| `libx264` | `-passlogfile P` | `P-0.log`, `P-0.log.mbtree` (not with `ultrafast`); while pass 1 runs `P-0.log.temp`, `P-0.log.mbtree.temp` |
| `libx265` | `-x265-params stats=P` | `P`, `P.cutree`; while pass 1 runs `P.temp`, `P.cutree.temp` |
| `libsvtav1`, `libvpx-vp9` | `-passlogfile P` | `P-0.log` |

The `-0` is the output stream index, so the video is mapped first. The `stats=` value goes
through FFmpeg's dictionary parser: `stats=/x/a\:b\'c d.passlog` writes `a:b'c d.passlog`.

**`subtitles=` file names.** The documented form (option-parser escapes inside graph-level
quotes, `subtitles=filename='…\:…'`) opens every awkward name: spaces, `:`, `'`, `,;[]`,
`\`, `%`, `=`, `"`, `$`, `&`, non-ASCII, in a folder named `dir, ;'[x]`
(`test_subtitles_filter_opens_awkward_file_names`). The filter reads its file from time 0
while `-ss` starts the frames at 0, so a ranged burn-in shifts the frame times around it
(`setpts=PTS+S/TB,subtitles=…,setpts=PTS-S/TB`); the ranged output's frames then equal the
full burn-in's frames shifted by S (lossless x264, `test_burn_in_text_subtitles_with_a_range`).

**External subtitle files and the range** (corrected 2026-10-14, M2 review; both n9.0.2
builds). The source's `-ss` does not move another input: an `.srt` input without its own
`-ss` keeps its times (`00:00:00,500` stays). With `-itsoffset X -ss S -i file.srt` an event
at `t` lands at `t + X − S`, **but an event that is on screen at S (or that a negative `X`
moves before 0) comes out with a negative time**, and the muxers do not drop it. The
`chapters` fixture with `text-subs.en.srt` (events 0.5–1.8 s and 2.0–3.6 s), `-ss 1.2 … -t
2.5`, video encoded:

| Output | Without an output `-ss` | With `-ss 0` as an output option |
|--------|-------------------------|----------------------------------|
| MKV, SRT copied | video and audio start at 0.7 s (the muxer moves every stream so that the −0.7 s event is at 0); the chapters do not move, so they are 0.7 s early | video and audio at 0; one event, 0.8–2.4 s (the event on screen at 1.2 s is dropped) |
| MP4, `mov_text` | `mov_text` samples at −1.5 s and 0.0–2.3 s: wrong event times | an empty sample 0.0–0.8 s, then the event 0.8–2.4 s |
| MKV, `-copypriorss:s:0 0` (no output `-ss`) | | the same as `-ss 0` for a copied track; no effect on a converted one (`mov_text`) |

An output `-ss 0` also drops what a **copied** stream has before 0: the encode of the
`multitrack` fixture with `-ss 1.2 -t 2.5` and the AC-3 track copied gave, without it, an
MKV whose audio started 1.17 s before the video (115 AC-3 packets: the copy starts at the
demuxer's seek point, the fixture's only keyframe at 0); with it, 78 packets and both
streams at 0. But it drops the first packets of a **copied video** too (its keyframe before
the seek point, or a packet with a negative decoding time: the `hdr10` copy became
unreadable, the MP4 remux lost its video stream), and, even without a range, the first
packet of each copied audio track of the `multitrack` fixture (AC-3 125 → 124 packets, AAC
189 → 188: the AAC priming packet has a negative time). So the builder writes `-ss 0` only
when the video is encoded (a copied audio track may then lose up to one frame at the start),
and a remux keeps FFmpeg's behaviour (it starts at the keyframe before the range, every
stream moved by the same amount). There is no FFmpeg option that cuts an event short:
an event that is on screen at the range start is dropped, not shortened
(`test_external_subtitle_with_a_range_starts_at_zero`,
`test_external_subtitle_with_a_negative_offset_starts_at_zero`,
`test_remux_with_a_negative_subtitle_offset_starts_at_zero`).

**Bitmap burn-in.** `-filter_complex "[0:0][0:1]overlay=eof_action=pass[v]"` burns the
`vobsub` fixture's track in (36 of the first 50 frames differ from a plain encode);
`-forced_subs_only:2 1` is accepted as an input option for the stream. `-map "[v]"` may come
before `-filter_complex`. `overlay` works in **8-bit 4:2:0** unless `format=` says otherwise
(`-h filter=overlay`: `yuv420` default, `yuv420p10`, `yuv422`, `yuv422p10`, `yuv444`,
`yuv444p10`, `rgb`, `gbrp`, `auto`). The `hdr10` fixture's video with the `vobsub` track
(25 frames, luma compared with the plain decode, checked with both builds on 2026-10-14):

| `overlay` format | Luma samples equal to the plain decode | Frame 0: samples with the two low bits set |
|------------------|----------------------------------------|--------------------------------------------|
| default | 289 551 of 1 440 000 | 0 |
| `format=auto` | 42 585 (it negotiates `bgra`: 8-bit RGB for the whole picture) | 47 532 (rounding noise) |
| `format=yuv420p10` | 1 427 776 (all but the subtitles) | 34 230 (= the plain decode) |

So a source of more than 8 bits gets `format=yuv420p10` (`yuv422p10` / `yuv444p10` for those
chroma formats; `test_bitmap_burn_in_keeps_10_bits`, a lossless x265 encode).

**DRC.** `-drc_scale:1 <n>` is accepted as an input option for stream 1. The AC-3 decoder's
default is 1 (`-drc_scale <float> … (from 0 to 6) (default 1)`). FFmpeg's AC-3 encoder writes
no dynamic range data, so the four decodes of the fixture (default, 0, 1, 4) are identical:
the effect is not visible with generated media.

**Global tags.** `title`, `artist`, `album_artist`, `date`, `comment`, `genre`,
`description`, `synopsis` are written and read back by the Matroska, MP4 and WebM muxers (MKV
upper-cases them: `ARTIST`, `ALBUM_ARTIST`, `SYNOPSIS`). MP4 drops `director`
(`-metadata director=D` → no tag); Matroska writes `DIRECTOR`.

**HDR.**

- x265 10-bit from the `hdr10` fixture keeps the colour and the HDR10 metadata (stream and
  frame side data) without any `-x265-params`, also after `scale`; the explicit params give
  the same result. SVT-AV1 the same, with `-svtav1-params color-primaries=bt2020:
  transfer-characteristics=smpte2084:matrix-coefficients=bt2020-ncl:mastering-display=
  G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001):content-light=1000,400`
  (no "Error parsing option" line). `hevc_vaapi` with `format=p010le,hwupload` and no
  `-profile` writes Main 10 with the HDR10 side data; `av1_amf` 10-bit too.
- **Tone mapping leaves the HDR10 metadata in.** After `zscale…tonemap…` or `libplacebo`
  (colour tags `bt709` everywhere) the output still has the mastering display and content
  light level, in the container and as SEI written by x264 / x265:

  ```console
  $ ffmpeg -i hdr10.mkv -vf "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p" -c:v libx264 t1.mkv
  stream|pix_fmt=yuv420p|color_space=bt709|color_transfer=bt709|color_primaries=bt709|side_datum/content_light_level_metadata:…|side_datum/mastering_display_metadata:…
  frame|color_space=bt709|color_transfer=bt709|…|side_datum/mastering_display_metadata:…|side_datum/content_light_level_metadata:…
  $ ffmpeg … -vf "…,sidedata=mode=delete:type=MASTERING_DISPLAY_METADATA,sidedata=mode=delete:type=CONTENT_LIGHT_LEVEL,format=yuv420p" … r1.mkv
  stream|color_space=bt709|color_transfer=bt709|color_primaries=bt709
  ```

  The `sidedata` filter's types include `DYNAMIC_HDR_PLUS`, `DOVI_RPU_BUFFER`,
  `DOVI_METADATA` and `DYNAMIC_HDR_VIVID` too; the builder removes all six.

**Frame rate** (the `vfr.mp4` fixture: 59 frames of 1/60 s, 30 of 1/30 s, 24 of 1/24 s):

| Options | Result |
|---------|--------|
| `-fpsmax:v:0 30` | `r_frame_rate=30/1`, 92 frames, all 1/30 s: constant 30, not a capped VFR |
| `-r:v:0 30 -fps_mode:v:0 cfr` | the same |
| `-fps_mode:v:0 cfr` (no `-r`) | `120/1`, 360 frames (the source's `r_frame_rate`) |
| `-fps_mode:v:0 vfr -fpsmax:v:0 30` or `… vfr -r:v:0 30` | refused: `One of -r/-fpsmax was specified together a non-CFR -vsync/-fps_mode. This is contradictory.` (exit 234) |

Bob deinterlacing (`bwdif=mode=send_field`) of the `interlaced` fixture (60 frames at
30000/1001) makes 120 frames; with `-r:v:0 30000/1001 -fps_mode:v:0 cfr` (constant, "same as
source" before the M2 review) the output had 60 frames again, every second field dropped. The
builder doubles the rate after a deinterlacer that sends fields (`mode=send_field`, `1`,
`send_field_nospatial`, `3`): an MP4 output reads back `avg_frame_rate=60000/1001`, 120
frames (`test_bob_with_a_constant_same_as_source_rate_keeps_every_field`; Matroska's 1 ms
time base reads back as `19001/317`).

Detelecine (`fieldmatch,decimate`; checked on 2026-10-14 with both builds) of a 2:3 telecined
clip (`testsrc2` at 24000/1001, 48 frames, through `telecine=pattern=23`: 60 frames at
30000/1001, lossless x264):

| Rate options | MKV and MP4 read back |
|--------------|-----------------------|
| `-r:v:0 30000/1001 -fps_mode:v:0 cfr` (constant "same as source" before the second review round) | 60 frames at 30000/1001: the 12 frames `decimate` dropped are duplicated back |
| `-r:v:0 24000/1001 -fps_mode:v:0 cfr` | 48 frames, `r_frame_rate` and `avg_frame_rate` 24000/1001 |
| no `-r` | the same 48 frames at 24000/1001 |

So the builder's constant "same as source" rate is the rate after the filters
(`decimate`: × (cycle − 1) / cycle;
`test_detelecine_with_a_constant_same_as_source_rate_keeps_the_film_rate[mkv|mp4]`).

**Command display** (`EncodePlan.display`, POSIX style). Pasted into `bash` 5, `zsh` and
`fish` (`/usr/bin/fish` on the development machine) with every awkward character of
`test_posix_display_pastes_into_bash_zsh_and_fish`: `shlex.quote` output fails in fish for
`'`, `\` (inside single quotes fish reads `\\` and `\'` as escapes) and a leading `%`
(`%self` is fish's process expansion), and in zsh for a leading `=` (`=ls` expands to
`/usr/bin/ls`). The builder quotes these too. The Windows style is for `cmd.exe`; no
PowerShell was available to check it.

**Audio layouts.** Encoding the 7.1 test source: `ac3` and `eac3` give `5.1(side)` by
themselves, `libmp3lame` `stereo`, `aac` and `libopus` keep `7.1`; with `-ac:a:0 6` AAC and
Opus give `5.1`. But libopus refuses the `5.1(side)` layout of the AC-3 fixture track:

```console
$ ffmpeg -i multitrack.mkv -map 0:1 -c:a libopus o.webm
[libopus @ 0x…] Invalid channel layout 5.1(side) for specified mapping family -1.
$ ffmpeg -i multitrack.mkv -map 0:1 -filter:a:0 aresample=out_chlayout=5.1 -c:a:0 libopus o.mkv    # exit 0, layout 5.1
```

`5.1` is `FL+FR+FC+LFE+BL+BR` and `5.1(side)` is `FL+FR+FC+LFE+SL+SR` (`ffmpeg -layouts`); the
conversion is a relabel (the PCM of both decodes has the same MD5). A 5.0 source encodes to
Opus and AC-3 unchanged. `aresample=matrix_encoding=dplii:out_chlayout=stereo` gives a stereo
Dolby Pro Logic II downmix. libopus picks 48 kHz for a 44.1 kHz input when no `-ar` is given.

**Which layouts each encoder takes** (M2 review; both builds, 2026-10-14; a PCM source of each
named layout encoded with `-c:a <encoder>` and no filter, `test_layout_tables_match_ffmpeg`):

- `ffmpeg -h encoder=…` lists layouts only for `ac3` / `eac3` (mono … `5.1(side)`, `5.1`) and
  `libmp3lame` (mono, stereo); FFmpeg converts any other layout for them by itself (`6.0` →
  `5.0(side)`, `7.1(wide)` → `5.1(side)`, everything → stereo for MP3).
- `aac` and `flac` list none and take every layout as it is (`6.0`, `7.1(wide)`, `octagonal`).
- `libopus` lists none and takes **only** `mono`, `stereo`, `3.0`, `quad`, `5.0`, `5.1`, `6.1`
  and `7.1` (the Vorbis orders of mapping family -1). Every other layout fails with exit 234:
  `Invalid channel layout 5.0(side) for specified mapping family -1` (also `2.1`,
  `3.0(back)`, `4.0`, `quad(side)`, `3.1`, `4.1`, `5.1(side)`, `6.0`, `6.0(front)`,
  `hexagonal`, `6.1(back)`, `6.1(front)`, `7.0`, `7.0(front)`, `7.1(wide)`,
  `7.1(wide-side)`, `octagonal`). So the builder relabels side to back for libopus
  (`5.0(side)` → `5.0`, `quad(side)` → `quad`) and otherwise downmixes to the largest layout
  it takes that is made of the source's channels (`2.1` and `3.0(back)` → stereo, `4.0` →
  `3.0`, `6.0` → `5.0`, `7.1(wide)` → `5.1`), and re-probing gives exactly these
  (`test_opus_gets_a_layout_it_accepts`). For the other encoders a remix to the bitrate
  table's layout (`6.0` → `5.1`) would lose channels, so only the lossless `5.1(side)` →
  `5.1` relabel is written.

**Ranges.** `-ss 0.4 … -t 2` on the 25 fps fixture gives exactly 50 frames, and the first one
is source frame 10 (same MD5). With `-c copy` the cut starts at the keyframe before the seek
(75 frames for `-ss 1.0 -t 2` on the fixture, whose only keyframe is at 0).

**mkvpropedit** `--edit track:a2 --set language=pt-BR` on an FFmpeg-written MKV: `mkvmerge -J`
then shows `language: por`, `language_ietf: pt-BR` for that track.

**Audio values the encoder cannot do** (decision
[0024](../docs/decisions/0024-m2-wave-2-product-decisions.md) item 4; checked on 2026-10-14
with both n9.0.2 builds, same results). Sources: a FLAC 7.1 file (eight `sine` inputs joined
with `join=inputs=8:channel_layout=7.1`) and a FLAC stereo file at 44.1 kHz. Unsnapped, FFmpeg
refuses some values and silently changes others, so the builder snaps them itself
(`test_impossible_audio_values_are_snapped`, `test_71_source_gets_the_layout_the_encoder_can_make`):

| Arguments | Result |
|-----------|--------|
| `-c:a ac3 -ar:a:0 96000` | `Specified sample rate 96000 is not supported by the ac3 encoder` (exit 234) |
| `-c:a libopus -ar:a:0 44100` | `Specified sample rate 44100 is not supported by the libopus encoder` (exit 234) |
| `-c:a libopus -b:a:0 600k` (stereo) | `The bit rate 600000 bps is unsupported. Please choose a value between 500 and 512000.` (exit 234) |
| `-c:a aac -b:a:0 700k` (stereo) | accepted (the encoder clamps by itself) |
| `-c:a ac3 -b:a:0 700k` (5.1) | 640 kb/s |
| 7.1 → `-c:a ac3 -ac:a:0 8` | `Specified channel layout '7.1' is not supported by the ac3 encoder` (exit 234) |
| 7.1 → `-filter:a:0 aresample=out_chlayout=7.1 -c:a:0 ac3` | 6 channels at FFmpeg's default 448 kb/s: FFmpeg converts the filter's 7.1 to the encoder's layout by itself (what the builder wrote before the snap) |
| 7.1 → `-filter:a:0 aresample=out_chlayout=5.1 -c:a:0 ac3 -b:a:0 640k` | 6 channels, 640 kb/s (`eac3` with the same filter: 6 channels); FFmpeg's AC-3 and E-AC-3 decoders always read the layout back as `5.1(side)` |
| 7.1 → `aresample=out_chlayout=stereo -c:a libmp3lame` | 2 channels |
| stereo → `aresample=matrix_encoding=dplii:out_chlayout=stereo` | the same PCM (MD5 of the decoded `s16le`) as without the filter: nothing to matrix-encode, so the builder keeps the source layout |

E-AC-3 at 44.1 kHz with `-b:a 1536k` reads back as 1 535 231 b/s (whole frames).

### Validation (C-8)

**Forced-only subtitles** (`subtitle.forced_only_unsupported`). `forced_subs_only` is a
*decoder* option. Checked on 2026-10-13 with `/usr/bin/ffmpeg` n9.0.2 (Arch), the pinned
build `n9.0.2-17-g2a571b6068-20260930` and the CI override build `n8.1.3-9-g29e619e767`;
`packages/reframe/tests/validation/test_ffmpeg.py` repeats it.

- Only two decoders have it: `ffmpeg -h decoder=pgssub` and `-h decoder=dvdsub` list
  `-forced_subs_only <boolean> .D...S..... Only show forced subtitles (default false)`;
  `dvbsub`, `subrip` and `ass` do not. So it works for PGS **and VobSub**, not only PGS as
  03 §Subtitles said.
- A stream copy does not decode, so the option changes nothing: `ffmpeg -forced_subs_only 1
  -i vobsub.mkv -map 0:s:0 -c copy copy.mkv` keeps both events of the fixture (2 packets in,
  2 out).
- Decoded, it works: the same input with `-c:s dvdsub` (the fixture has no forced events)
  writes nothing: `Output file is empty, nothing was encoded`. A burn-in decodes the track,
  so forced-only works for a burned-in PGS or VobSub track.
- On a text track FFmpeg warns `… it is a private option of some decoder which was not
  actually used for any stream` and keeps every event (`text-subs.mkv`, SRT → ASS: 2 events
  in, 2 out).

**HDR source encoded to 8-bit without tone mapping** (`filter.hdr_8bit`). Checked on
2026-10-14 with `/usr/bin/ffmpeg` n9.0.2 (Arch) and the pinned build
`n9.0.2-17-g2a571b6068`; `packages/reframe/tests/validation/test_hdr_ffmpeg.py` repeats it
for x264.

- Without tone mapping or a Colorspace conversion the command builder's plan only changes the
  pixel format: `-filter:v:0 scale=320:180:flags=lanczos,setsar=1/1,format=yuv420p -c:v:0
  libx264 -crf:v:0 22` on the `hdr10` fixture (HEVC 10-bit, BT.2020 PQ, mastering display
  and content light level). No `setparams`, no `sidedata=mode=delete`, no HDR params
  (`keeps_hdr` is false at 8 bits).
- FFmpeg keeps the colour tags and the HDR10 side data. ffprobe of the outputs, the same with
  both builds:

  | Encoder (8-bit) | pix_fmt | primaries / transfer / matrix | Stream side data | First frame side data |
  |-----------------|---------|-------------------------------|------------------|-----------------------|
  | libx264 | yuv420p | bt2020 / smpte2084 / bt2020nc | CLL, mastering display | SEI, mastering display, CLL |
  | libx265 (Main) | yuv420p | bt2020 / smpte2084 / bt2020nc | CLL, mastering display | SEI, mastering display, CLL |
  | libsvtav1 | yuv420p | bt2020 / smpte2084 / bt2020nc | CLL, mastering display | mastering display, CLL |
  | libvpx-vp9 (Profile 0) | yuv420p | bt2020 / smpte2084 / bt2020nc | CLL, mastering display | mastering display, CLL |

  So the output is an 8-bit HDR10 file (C-3 probes it as HDR10 with the source's values):
  not washed out, as an SDR-tagged conversion is (`filter.hdr_without_tonemap`), but HDR in
  8 bits, which bands. With libx265 at 10 bits the same plan gives `yuv420p10le`, Main 10,
  the same tags.
- The warning's fixes: tone mapping (`zscale` + `tonemap`) gives 8-bit BT.709 with no HDR
  metadata; 10-bit x264 gives `yuv420p10le` BT.2020 PQ, still HDR10.

**x265 level limits** (`encoder.level_too_low`). Checked on 2026-10-14 with both builds
(`/usr/bin/ffmpeg` n9.0.2 and the pinned `n9.0.2-17-g2a571b6068`, the same results);
`packages/reframe/tests/validation/test_levels_ffmpeg.py` repeats the boundaries.
`ffmpeg -f lavfi -i testsrc2=size=WxH:rate=R -c:v libx265 -preset P -x265-params
level-idc=L -f null -` exits with 183 and one of:

- `x265 [error]: picture dimensions are out of range for specified level`: more luma
  samples than the level's MaxLumaPs (H.265 table A.8), or a side longer than
  `sqrt(8 × MaxLumaPs)`. 1920x1080 needs level 4 (fails at 3.1); 2560x1440 and 4K need 5;
  8K needs 6. At level 3.1 the widest picture is 2800 (2808 fails), at level 4 4216 with
  `medium` but 4208 with `ultrafast`.
- `x265 [error]: frame rate is out of range for specified level`: samples × frame rate above
  MaxLumaSr. 1080p at level 4: 32 fps passes, 33 fails; level 4.1: 60 passes, 65 fails; 4K
  60 fps needs 5.1.
- The size is the picture padded to the minimum coding unit: 16 for `ultrafast`, 8 for
  `superfast` to `veryslow` (level 4: 1920x1160 passes with `medium`, `superfast`,
  `veryfast`, `faster`, `veryslow` and fails with `ultrafast`, which counts 1920x1168).
- Level 1 refuses even 320x180; with CRF and a level x265 only warns ("Specifying a decoder
  level with constant rate factor rate-control requires …").

**x265 lookahead and x264 subme** (`encoder.lookahead_too_short`,
`encoder.subme_needs_trellis`). Checked on 2026-10-14 with both builds;
`packages/reframe/tests/validation/test_x26x_ffmpeg.py` repeats it.

- x265 exits with 183 and `x265 [error]: Lookahead depth must be greater than the max
  consecutive bframe count` when `rc-lookahead` ≤ `bframes`: `rc-lookahead=4:bframes=4`
  and `rc-lookahead=0:bframes=4` stop, `5:4` and `0:0` run. The preset defaults count:
  `ultrafast` (lookahead 5, 3 B-frames) stops with `bframes=5`, `medium` (20, 4) with
  `rc-lookahead=4`. `-tune animation` adds 2 B-frames (`medium`: 5 stops, 7 runs;
  `slower`: 6 stops, 11 runs), `-tune zerolatency` sets both to 0 (`bframes=3` stops);
  `-x265-params` values win over the tune (`animation` with `rc-lookahead=5:bframes=4`
  runs).
- x264 writes the `subme` it uses into its settings SEI: `subme=10:trellis=1` → `subme=9`,
  `subme=11:trellis=0` → 9, `subme=10:trellis=2` → 10; `veryslow` (10, trellis 2) with
  `trellis=1` → 9, `placebo` with `trellis=0` → 9. No message. `aq-mode=0` leaves 10.

### Audio codec rules (C-12)

The codec rules are pure; the encoder and container facts they use (bitrate steps, which
codecs a container can copy, no 7.1 in AC-3 / E-AC-3 / MP3) are C-6's, above. Two more facts
were checked with `/usr/bin/ffmpeg` n9.0.2 for decision
[0019](../docs/decisions/0019-audio-codec-rule-details.md):

- **FFmpeg's upmix adds silent channels.** A stereo AC-3 file (two sine tones) encoded with
  `ffmpeg -i st.mka -ac 6 -c:a ac3 -b:a 448k up.mka` is `5.1(side)` at 448 kb/s; `-af
  astats=measure_overall=none:measure_perchannel=RMS_level` reads −21.07 dB RMS on channels 1
  and 2 and −118.6 dB, −inf, −118.6 dB, −118.6 dB on channels 3 to 6. So a codec rule never
  upmixes: a source with fewer channels than the rule's mixdown keeps its layout.
- **DTS core extraction exists but is not used.** `ffmpeg -bsfs` lists `dca_core` (it keeps
  the DTS core of a DTS-HD stream). Reframe matches a DTS-HD source only to the `dtshd`
  passthru codec, as the definitions do; passing only the core through is not in the plan.
- **A source sample rate the encoder lacks is snapped by Reframe, not left to FFmpeg**
  (decision [0024](../docs/decisions/0024-m2-wave-2-product-decisions.md) item 4; both n9.0.2
  builds, a `sine=sample_rate=N` source written to `.mka`). Without `-ar`, FFmpeg picks its
  own rate, which is not always the nearest: `libopus` writes 48000 Hz from 44100, 22050 and
  11025 Hz; `ac3` keeps 44100 and writes 32000 Hz from 22050 and 11025 Hz. With an explicit
  rate the encoder lacks, the encode fails (`ac3 -ar 22050`: "Specified sample rate 22050 is
  not supported by the ac3 encoder", exit code 234). So the codec rules put the snapped rate
  of C-6's `snap_samplerate` into the track (Opus from 22050 Hz: 24000 Hz, with a note), which
  is the rate the command builder writes with `-ar`. ffprobe reports 48000 Hz for every Opus
  track in Matroska, whatever `-ar` was (the decoder's output rate), so a test cannot read
  the Opus rate back from the file.

### Queue and job runner (C-11)

Checked on 2026-10-14 with both n9.0.2 builds (`/usr/bin/ffmpeg` and the pinned BtbN build),
psutil 7.2.2 and SQLite 3.53.4, for decision
[0016](../docs/decisions/0016-queue-and-job-runner.md). The real-FFmpeg parts are repeated by
`packages/reframe/tests/queue/test_integration.py` (run it with `REFRAME_FFMPEG` /
`REFRAME_FFPROBE` set to either build).

**`-progress` after a pause.** An x264 encode with `-readrate 1 -progress pipe:1 -nostats`,
suspended with psutil `Process.suspend()` (`SIGSTOP`) after 2 s and resumed 3 s later
(`SIGCONT`). No block is printed while it is stopped; the next one comes at once after the
resume. FFmpeg's `speed` and `fps` are averages since the start on a clock that ran on:

| Seconds | 0.5 | 1.0 | 1.5 | (stopped 2–5) | 5.0 | 5.5 | 6.0 | 8.2 (end) |
|---------|-----|-----|-----|---------------|-----|-----|-----|-----------|
| `speed` | 1.44x | 1.24x | 1.15x–1.17x | — | 0.444x–0.449x | 0.51x | 0.56x | 0.73x |
| `fps` (pinned) | 0.00 | 31.00 | 29.33 | — | 11.22 | 12.93 | 14.02 | 18.22 |

So the queue computes speed, fps and the ETA from the change between blocks over active time.
Blocks also come before the first packet (`frame=0`, `out_time_us=N/A`, see "`-progress`
output" above): a live FFmpeg is never silent for longer than `-stats_period`.
`Process.status()` still says `running` right after `suspend()` returns and `stopped` a moment
later (the signal is delivered asynchronously): tests poll for it.

**loudnorm ranges** (`ffmpeg -h filter=loudnorm`, the same in both builds): `I` −70…−5, `LRA`
1…50, `TP` −9…0, `measured_I` −99…0, `measured_LRA` 0…99, `measured_TP` −99…99,
`measured_thresh` −99…0, `offset` −99…99.

**Silent and near-silent tracks.** The analyse pass (`loudnorm=I=-23:TP=-1:LRA=20:print_format=json`)
of digital silence (`anullsrc`) prints `"input_i" : "-inf"`, `"input_tp" : "-inf"`,
`"input_lra" : "0.00"`, `"input_thresh" : "-70.00"`, `"target_offset" : "inf"`. Pink noise
at −84 dBTP (`anoisesrc=c=pink:a=0.0001`, mean −90.3 dB) gives `"input_i" : "-inf"` and
`"target_offset" : "inf"` with `"input_tp" : "-84.39"` (all of it is below the −70 LUFS
gate). The second pass with `measured_I=-99:measured_TP=-84.39:measured_LRA=0:measured_thresh=-70`
on that noise (4 s, dynamic mode):

| `offset` | Output (volumedetect) | Output integrated |
|----------|-----------------------|-------------------|
| `99` | mean −12.4 dB, max 0.0 dB | −9.6 LUFS: full-scale noise |
| `0` | mean −90.3 dB, max −84.3 dB | unchanged |
| `-99` | mean −91.0 dB | lower |

So a non-finite `target_offset` becomes 0, not the range end. Digital silence (5 s) passes
the second pass with any offset and stays silent.

**A silent input shorter than 3 s fails the second pass**, whatever the measured values:
2 s of `anullsrc` with `measured_I=-99:measured_TP=-99:…:offset=0:linear=true` gives
"Normalization Type: Linear", `[aac] Input contains (near) NaN/+-Inf` (flac: "invalid block
size"), "Conversion failed!", exit code 234 (both builds). loudnorm's first-frame path (input
shorter than 3 s) computes its own gain from the input's −inf loudness. A 2 s **output range**
(`-t 2`) of a 5 s silent source works (exit 0): loudnorm reads 3 s of input first.

**MP4 chapters are a data stream.** An x264 + AAC MP4 with `-map_chapters 0` lists
`video`, `audio` and `data` (`bin_data`, the QuickTime chapter text track) in ffprobe. The
output check compares video, audio and subtitle streams only.

**File names.** POSIX `os.rename` replaces an existing target; `os.link(src, dst)` raises
`FileExistsError` when `dst` exists (both checked by `tests/queue/test_units.py`), so the
final rename that must not replace uses a hard link plus an unlink, with a check-then-rename
fallback when the file system has no hard links (`EPERM`, `EXDEV`, `EMLINK`, `ENOSYS`,
`EOPNOTSUPP`). On Windows `os.rename` refuses an existing target and `os.replace` onto a file
that another process has open raises `PermissionError` (Python documentation; mock-tested on
Linux only, not run on Windows yet).

**The owner lock** (decision 0027, `reframe.queue.lock`). On Linux an `fcntl.flock(LOCK_EX |
LOCK_NB)` on `queue.lock` conflicts with a lock of another open file description, also in the
same process (two `QueueService` objects on one data folder behave like two processes), and
the kernel frees it when the owner is killed with `SIGKILL` (`tests/queue/test_owner.py`, real
processes). The descriptor is not inherited by children (PEP 446), so an FFmpeg that outlives
Reframe cannot keep it. Windows (`msvcrt.locking`, mandatory byte-range locks) is mock-tested
only.

**File names that are not UTF-8.** On Linux a name with the byte 0xFF is the Python string
`bad\udcffname.mkv` (PEP 383). Pydantic's `model_dump_json()` refuses it ("surrogates not
allowed"), and so does SQLite for a text value; `model_dump(mode="json")` keeps it, and
`json.dumps(…, ensure_ascii=True)` writes `\udcff`, which `json.loads` restores. FFmpeg gets
the original bytes through `subprocess` (`os.fsencode`).

**SQLite.** `PRAGMA journal_mode = WAL` rewrites the file header (bytes 18 and 19, the file
format versions, go from 1 to 2), so the store reads `PRAGMA user_version` on a plain
connection first and leaves a newer file untouched. A file that is not a database opens
without an error; the first statement raises `sqlite3.DatabaseError: file is not a
database`.

### Output naming (C-16)

Checked on 2026-10-14 with guessit 4.4.0 and CPython 3.14.7 on Linux (glibc), for the M2
review follow-up of decision [0012](../docs/decisions/0012-output-naming-rules.md):

- **guessit's user config files.** Without `no_user_config`, guessit reads
  `guessit.options.json` in the working folder, `~/.guessit/options.json` and
  `~/.config/guessit/options.json` (`.yml` / `.yaml` too when PyYAML is installed; it is
  not). It does not read `$XDG_CONFIG_HOME/guessit`. A file `{"type": "movie"}` in any of the
  three places turns the episode title of `The.Sopranos.S03E02.Proshai.Livushka…` into
  `alternative_title`; with `no_user_config: True` none of them is read. guessit loads the
  files on the first call and keeps them in `guessit.api.default_api` until the options
  `config`, `no_user_config` or `no_default_config` change (tests call
  `default_api.reset()`). Asserted in `tests/naming/test_parse.py`.
- **guessit and other digits.** `Bleach - ٠٠١ - Title` (Arabic-Indic) and
  `Bleach - ００１ - Title` (full-width) give season 0, episode 1, the same as `001`;
  `Bleach - ²²³ - Title` gives no episode (`²²³` is an `alternative_title`).
- **Python's format specs read every decimal digit.** `format(3, "٥")` and
  `format(3, "５")` give `'    3'` (width 5); `format(3, "²")` raises `ValueError`. A width
  of 999999999999 raises `MemoryError`; more than `sys.maxsize` raises `ValueError` ("Too
  many decimal digits"). `format(123456789, "c")` raises `OverflowError`.
- **`strftime` limits its own output.** `datetime.strftime("%1000Y")` gives 1000 characters
  (glibc field widths), `"%100000Y"` and `"%999999999999Y"` give an empty string at once.
- **A POSIX name that is not UTF-8.** `os.fsdecode(b"bad\xffname.mkv")` is
  `'bad\udcffname.mkv'`; `str.encode("utf-8")` of it raises `UnicodeEncodeError`
  ("surrogates not allowed"), and so do `print`, pydantic's `model_dump_json` and
  `model_validate_json` (a `\udcff` escape in JSON is "lone leading surrogate"). Pydantic's
  `model_dump(mode="json")` and `model_validate` (Python objects) keep the surrogate, and
  `json.dumps(…, ensure_ascii=True)` / `json.loads` give it back exactly, which the probe cache
  uses (C-3). JavaScript (node v26.10.0): `JSON.parse('"\\udcff"')` is one UTF-16 unit,
  U+DCFF, and `JSON.stringify` writes it back as `"\udcff"` (`reframe.models.json_text`,
  0044). The float spellings differ: `json.dumps(1e-05)` is `1e-05`, pydantic-core 2.50.0's
  `to_json(1e-05)` is `0.00001` (the same value); `1e+16`, `1.5e+300`, `5e-324` and
  `23.976023976023978` are spelled the same.

### Audio and subtitle defaults (C-12, selection stage)

Checked on 2026-10-15 with MKVToolNix 101.0 (`/usr/bin/mkvmerge`) and ffprobe n9.0.2
(`/usr/bin/ffprobe`), for decision
[0031](../docs/decisions/0031-audio-and-subtitle-selection-stage.md). The selection itself is
pure; it relies on what the probe reads from an mkvmerge-made file: the forced flag and the
event count of a subtitle track (the foreign audio search), and the default flags (at most one
default track per kind is kept). `tests/batch/test_explain_media.py` repeats this on the
`multitrack` fixture (`needs_ffmpeg`; skipped without mkvmerge).

```
$ printf '1\n00:00:01,000 --> 00:00:02,000\nElvish: Hello\n' > forced.srt
$ mkvmerge -q -o fas.mkv multitrack.mkv --language 0:eng --track-name 0:Forced \
    --forced-display-flag 0:1 forced.srt
$ ffprobe -v error -show_entries stream=index,codec_type,codec_name:stream_disposition=default,forced,comment:stream_tags=language,title,NUMBER_OF_FRAMES -of compact fas.mkv
...
stream|index=4|codec_name=subrip|codec_type=subtitle|disposition:default=1|disposition:comment=0|disposition:forced=0|tag:language=eng|tag:title=English|tag:NUMBER_OF_FRAMES=2
stream|index=5|codec_name=subrip|codec_type=subtitle|disposition:default=0|disposition:comment=0|disposition:forced=0|tag:language=eng|tag:title=English SDH|tag:NUMBER_OF_FRAMES=3
stream|index=6|codec_name=subrip|codec_type=subtitle|disposition:default=0|disposition:comment=0|disposition:forced=1|tag:language=eng|tag:title=Signs & Songs|tag:NUMBER_OF_FRAMES=1
stream|index=7|codec_name=subrip|codec_type=subtitle|disposition:default=1|disposition:comment=0|disposition:forced=1|tag:language=eng|tag:title=Forced|tag:NUMBER_OF_FRAMES=1
```

- `--forced-display-flag` is ffprobe's `disposition:forced=1`; mkvmerge's statistics tag
  `NUMBER_OF_FRAMES` is the event count of a subtitle track (C-3 reads it as
  `event_count`, source `stats_tag`).
- **mkvmerge marks an added track default** (`FlagDefault=1`) unless it is told otherwise
  (`--default-track-flag 0:0`): the file above has two default subtitle tracks (4 and 7). So a
  draft that keeps every track (no language set) keeps the default flag only on the first of
  them (03 §Track metadata: one default track per type).
- HandBrake's subtitle defaults were read in its source, not run: see decision 0031
  ("Context").

### Analysis scans (C-10: bitrate, subtitles, loudness)

Checked on 2026-10-15 with FFmpeg n9.0.2 (Arch package and the pinned BtbN build
`n9.0.2-17-g2a571b6068-20260930`; the DTS-HD MA rows also with the n8.1.3 override build).
Decision [0032](../docs/decisions/0032-analysis-scans-and-their-fixtures.md) uses these.

**Packet listing** (the bitrate scan; `-of compact=p=0`, one line per packet, keys in the
order ffprobe prints them, not the order of `-show_entries`):

```
$ ffprobe -v error -select_streams 1 -show_entries packet=pts_time,dts_time,duration_time,size \
      -of compact=p=0 -i dts-hd-ma.mkv
pts_time=0.000000|dts_time=0.000000|duration_time=0.010000|size=3140
pts_time=0.011000|dts_time=0.011000|duration_time=0.010000|size=3140
…
pts_time=3.989000|dts_time=3.989000|duration_time=0.010000|size=2964
```

- Matroska stores times in whole milliseconds: a 512-sample DTS frame (10.667 ms) has
  `duration_time=0.010000`, so the 375 durations add up to 3.75 s for a 4 s track. The scan
  uses the first packet time to the last packet end (3.999 s): 2 140 063 b/s measured, 2 139 528
  b/s exact (0.03 %).
- An ffprobe packet listing of 225 000 AC-3 packets (2 hours) takes about 2.3 s through the
  scan's line reader (load average about 7).

**Subtitle packets** of all subtitle streams in one pass:
`ffprobe -v error -select_streams s -show_entries packet=stream_index,pts_time,size -of compact=p=0`
prints `stream_index=1|pts_time=0.200000|size=12`. One SRT cue, one ASS `Dialogue` line or one
VobSub subpicture is one packet (`multitrack`: 2, 3, 1; `text-subs`: 2, 3; `vobsub`: 2, 1).

**MP4 / MOV text (`mov_text`)** (checked 2026-10-16 with the pinned n9.0.2 and the n8.1.3
override build, the same results; core-complete review R3-2). A sample is a 16-bit text
length, the text, then style boxes. The MP4 and MOV muxers fill the time before the first cue
and every gap between two cues with an **empty sample**, `00 00` (2 bytes). 3 SRT cues
(1–2 s, 3–4 s, 5–6.5 s) with `-c:s mov_text` (MP4: codec tag `tx3g`; MOV: `text`):

```
$ ffprobe -v error -select_streams s -show_entries packet=stream_index,pts_time,duration_time,size \
      -of compact=p=0 three.mp4
stream_index=1|pts_time=0.000000|duration_time=1.000000|size=2
stream_index=1|pts_time=1.000000|duration_time=1.000000|size=7
stream_index=1|pts_time=2.000000|duration_time=1.000000|size=2
stream_index=1|pts_time=3.000000|duration_time=1.000000|size=7
stream_index=1|pts_time=4.000000|duration_time=1.000000|size=2
stream_index=1|pts_time=5.000000|duration_time=1.500000|size=9
```

- Back-to-back cues (0–1, 1–2, 2–3 s, one letter each) give 3 samples of 3 bytes, no empty
  sample.
- An ASS file with `Hello` (1–2 s), an empty `Dialogue` (2–3 s), one with override tags only
  (`{\b1}{\b0}`, 3–4 s) and `{\i1}Styled{\i0}` (5–6 s) gives 4 samples: 2 bytes at 0 s, 7
  at 1 s, **2 bytes at 2 s lasting 3 s** (the two cues without text get no sample of their
  own), 30 bytes at 5 s (`0006 "Styled"` and a 22-byte `styl` box). In Matroska (`-c:s ass`)
  the same file has 4 packets: the ASS decoder keeps the empty events, the `mov_text` encoder
  drops them.
- So the subtitle scan does not count a `mov_text` packet of 2 bytes or less: 3 events, not 6,
  for the 3 cues (`tests/analysis/test_analysis_facade.py`).

**PGS in Matroska.** The `sup` demuxer returns one packet per *segment*; the Matroska muxer
merges the segments of a display set into one block (`pgs_frame_merge`, added by
`matroskaenc`), so `pgs.mkv` has 12 and 4 packets for 6 and 2 events (show + clear each).
Without `-copyts` ffmpeg moves the first event of a `.sup` input to 0 s (the demuxer's start
time is the first event); with it the tracks start at `0.200000`. `ffmpeg -i pgs.mkv -map 0:1
-c copy -f sup out.sup` writes the segments again (8 388 bytes, the size of the written file;
only the PTS differ).

**`forced_subs_only`** (decoder option; ffprobe passes it to the decoder when it is given
before the input; `-show_entries subtitle=…` alone shows the decoded subtitles):

```
$ ffprobe -v error -select_streams 1 -show_entries subtitle=pts_time,num_rects -of csv=p=0 pgs.mkv
0.200000,1
0.800000,0
…                                   (12 lines: show 1 rect, clear 0 rects)
$ ffprobe -v error -forced_subs_only 1 -select_streams 1 \
      -show_entries subtitle=pts_time,num_rects -of csv=p=0 pgs.mkv
(the same 12 lines)
```

- **PGS**: `pgssubdec` returns every display set and leaves the palette of a non-forced object
  empty; the event count does not change. `rect->flags` (`AV_SUBTITLE_FLAG_FORCED`) is not in
  ffprobe's output. So the scan reads the forced flag (`0x40` of the composition object in the
  PCS) from a `.sup` copy.
- **VobSub**: `dvdsubdec` drops every subpicture that does not start with the forced start
  command `0x00`: a track with 3 subpictures, 2 of them forced, gives 3 lines without the
  option and 2 with it. The `vobsub` fixture has no forced subpictures (its `fre` track only has
  the forced *disposition*): 0 lines with the option.

**`loudnorm`** prints its JSON block at log level `info` (nothing with `-v error`):

| Input | `input_i` | `input_tp` | `input_lra` | `input_thresh` | exit |
|-------|-----------|------------|-------------|----------------|------|
| `multitrack` stream 2 (AAC stereo, 660 Hz sine, mono at -18 dBFS upmixed) | -21.66 | -20.63 | 0.00 | -31.66 | 0 |
| `multitrack` stream 1 (AC-3 5.1, 440 Hz) | -21.75 | -18.06 | 0.00 | -31.75 | 0 |
| 2 s of `anullsrc` (digital silence) | `-inf` | `-inf` | 0.00 | -70.00 | 0 |
| `-ss 100` on the 4 s `multitrack` (nothing decoded) | `-inf` | `-inf` | 0.00 | -70.00 | 0, plus "Output file is empty, nothing was encoded" and one `-progress` block with `out_time_us=N/A` |

**DTS-HD MA without a core** (`dts-hd-ma.mkv`, all three builds):

```
$ ffprobe -v error -of compact=p=0 -show_entries stream=index,codec_name,profile,sample_fmt,bit_rate \
      -select_streams a:0 dts-hd-ma.mkv
index=1|codec_name=dts|profile=DTS-HD MA|sample_fmt=s32p|bit_rate=N/A
```

In `-of json` the stream has no `bit_rate` key, `bits_per_raw_sample` is `"24"`, the layout
`5.1(side)`, and the only tags are `language`, `title` and `DURATION`. `reframe probe` shows
`DTS-HD MA` · `lossless` · `5.1(side), 6 ch` · `48 kHz / 24-bit` · `— (unknown)`. The raw stream
is recognised without `-f dts` too (the `dts` probe counts EXSS headers whose size is a
multiple of 4 and whose CRC is right). `-err_detect crccheck+explode` decodes every frame.

**Cancel** (C-10 "Done when"): on a 2-hour file with an event every 25 ms (the file of
`tests/analysis/test_analysis_cancel.py`), cancelled 0.3 s after the process started, every
process was gone 6 to 25 ms after `TaskManager.cancel` (bitrate 12–18 ms, subtitle packet count
16–25 ms, PGS copy 6–9 ms, loudness 7–10 ms; load average about 7). Uncancelled, the passes take
2.3 s (bitrate), 3.4 s (subtitle packet count, 288 000 packets) and 3.0 s (PGS copy and read,
576 000 display sets, 7 200 forced).

### Preview frames, crop detection and clips (C-10)

Checked on 2026-10-15 with the Arch `/usr/bin/ffmpeg` n9.0.2 (the `cropdetect` defaults also
with the n8.1.3 override-test build), on the machine above (12 threads, AMD RX 7600:
libplacebo works). Decision [0033](../docs/decisions/0033-preview-frames-crop-and-clips.md) is
based on these. `packages/reframe/tests/preview/` asserts them (`test_frames.py`,
`test_cropdetect.py`, `test_clip.py`, `test_cancel.py`, the `benchmark` test).

**Fast seek gives the frame of a slow seek.** `-ss T` before `-i` decodes from the keyframe
before T and outputs the first frame at or after T: on `letterbox.mkv` at 0.2, 1.52, 2.0 and
3.96 s the PNG is pixel-identical to `-i … -ss T` (which decodes everything before T).

**Past the last frame FFmpeg writes nothing and exits 0**, with nothing on stderr at
`-loglevel error`:

```console
$ ffmpeg -v error -ss 3.99 -i letterbox.mkv -frames:v 1 -vf format=rgb24 -c:v png -f image2 -update 1 end.png
$ echo $?; ls end.png        # last frame at 3.96 s
0
ls: cannot access 'end.png': No such file or directory
```

**One PNG needs `-update 1`**, else the image2 muxer warns: `The specified filename '…/f.png'
does not contain an image sequence pattern … use the -update option (with -frames:v 1 if
needed) to write a single image.`

**RGB conversion and colour tags.** An untagged frame is converted to RGB with BT.601; after an
input seek, FFmpeg converts **before** a `setparams` that comes first in the chain (the
format negotiation puts the conversion at the decoder's link), so the tag has no effect. An
explicit `scale` after the tag converts with it. 1280x720 untagged H.264 of the colour
`0x3080C0`, first pixel of the PNG:

| Chain | without `-ss` | with `-ss 0.5` before `-i` |
|-------|---------------|---------------------------|
| `format=rgb24` | 47, 127, 191 (BT.601) | 47, 127, 191 |
| `setparams=…colorspace=bt709,format=rgb24` | 39, 123, 195 (BT.709) | **47, 127, 191** |
| `setparams=…colorspace=bt709,scale,format=rgb24` | 39, 123, 195 | 39, 123, 195 |
| `scale=in_color_matrix=bt709,format=rgb24` | 39, 123, 195 | 39, 123, 195 |

**`split` makes the source and the output frame from one decode**, but the pixel formats are
negotiated across the split: with `[0:0]split=2[x][y];[x]format=rgb24[src];[y]crop=…,scale=…,
format=yuv420p,format=rgb24[out]`, FFmpeg converted the decoded frame to RGB **before** the
split, so the output branch's crop and scale ran on RGB and its picture differed from a run
that makes only the output frame (also with `decimate`, `tmix`, `bwdif` Bob). The source frame
was the same. When each branch converts with its own `scale` (`…,scale=…,format=rgb24`), both
pictures are pixel-identical to one-kind runs (`test_one_run_for_both_kinds_…`: crop +
hqdn3d + sharpen, Bob, HDR kept with zscale display mapping, a tone-mapping job). 4K HDR,
zscale on both, crop + scale on one: 0.65–0.75 s in one run, 1.17–1.28 s in two.

**4K HDR frame times** (`hdr10-4k.mkv`, one frame per run, idle machine, load average 1.3):
decoding all 120 frames takes 0.73 s (about 165 frames/s). One PNG at 0.25 / 1.9 / 2.5 /
4.75 s (1.9 s is 45 frames after a keyframe), PNG compression level 1:

| Chain | times (s) | PNG size |
|-------|-----------|----------|
| `format=rgb24` (no tone mapping) | 0.34, 0.66, 0.38, 0.40 | 2.2 MB |
| zscale + tonemap (Hable) | 0.43, 0.57, 0.48, 0.43 | 1.6 MB |
| libplacebo (BT.2390, peak detection) | 0.56, 0.71, 0.60, 0.60 | 5.6 MB |
| decode only (`-f null`) | 0.26, 0.39, 0.31, 0.28 | |

Ten frames: zscale 5.0 s one at a time, 4.0 s two at a time, 3.7 s three at a time;
libplacebo 7.5 / 4.9 / 4.7 s. PNG compression of a grainy 4K picture (testsrc2 + noise,
`-pred` default `paeth`): level 1 0.34 s 13.9 MB, level 3 0.45 s 8.9 MB, level 6 0.94 s 8.5 MB.
An explicit `scale=flags=bicubic+accurate_rnd+full_chroma_int` before `format=rgb24` costs
nothing measurable at 4K.

**Display matrix and pixel aspect.** `ffmpeg -display_rotation:v:0 90 -i letterbox.mkv -c copy
rotated.mp4`: ffprobe shows `rotation=90`; the PNG of a frame is 180x320 and `cropdetect` says
`x1:22 x2:155 … w:134 h:320 x:22 y:0 crop=134:320:22:0` (the picture as decoded, decision
0009). `anamorphic.mkv` (720x480, SAR 32:27) gives a 720x480 PNG with
`sample_aspect_ratio=32:27`.

**`cropdetect`** (both builds):

```console
$ ffmpeg -h filter=cropdetect
   limit  <float>  Threshold below which the pixel is considered black (from 0 to 65535) (default 0.0941176)
   round  <int>    Value by which the width/height should be divisible (from 0 to INT_MAX) (default 16)
   skip   <int>    Number of initial frames to skip (from 0 to INT_MAX) (default 2)
$ ffmpeg -loglevel info -ss 1 -i letterbox.mkv -frames:v 1 -vf cropdetect=round=2 -f null -
(no cropdetect line: the first 2 frames are skipped)
$ ffmpeg -loglevel info -ss 1 -i letterbox.mkv -frames:v 1 -vf cropdetect=round=2:skip=0 -f null -
[Parsed_cropdetect_0 @ 0x…] x1:0 x2:319 y1:22 y2:155 w:320 h:134 x:0 y:22 pts:0 t:0.000000 limit:0.094118 crop=320:134:0:22
[Parsed_cropdetect_0 @ 0x…] x1:0 x2:319 y1:22 y2:155 w:320 h:134 x:0 y:22 pts:40 t:0.040000 limit:0.094118 crop=320:134:0:22
```

- `-frames:v 1` lets two frames through the filter; the first line is the sample frame.
- A limit below 1 is a fraction of the full range, scaled by the bit depth (24 at 8-bit, 96.3
  at 10-bit). On a 10-bit PQ letterbox (640x268 picture, 46-line bars, x265):
  `limit=0.094118` → `crop=640:268:0:46`; `limit=96` → the same; `limit=65` → `crop=640:270:0:44`
  (ringing); `limit=64` → `crop=640:280:0:38`; **`limit=24` → `crop=640:360:0:0`** (no bars: 24
  is below 10-bit black).
- Black levels (`signalstats`, YMIN / YLOW / YAVG / YMAX): SDR letterbox bar 14 / 16 / 16.1 / 18
  (8-bit); PQ letterbox bar 40 / 63 / 63.9 / 91 (10-bit; the extremes are x265 ringing next to
  the picture).
- A black frame: `x1:319 x2:0 y1:179 y2:0 w:-318 h:-178 x:320 y:180 … crop=-318:-178:320:180`.
- Rounding (checked 2026-10-16 with the pinned n9.0.2 and n8.1.3, the same results): x and y
  are rounded up to even, the size is recomputed to keep the right and bottom edges
  (`w = x2 − x + 1`), then cut down to a multiple of `round` (an odd `round` is doubled, and
  `round` 0 or 1 means 16), and x / y move by half the cut, rounded to even
  (`x += (cut / 2 + 1) & ~1`). A white 300x150 picture at 9,13 in a black 320x181 frame
  (`drawbox=x=9:y=13:w=300:h=150:color=white:t=fill`, 4:2:0): `x1:9 x2:308 y1:13 y2:162`,
  `round=2` → `crop=298:148:10:14`, `round=1` → `crop=288:144:16:16`. Made with
  `pad=320:181:9:13` instead, the picture is at **8,12** (`pad` puts it on the 4:2:0 chroma
  grid; at 9,13 only with a 4:4:4 input): `x1:8 x2:307 y1:12 y2:161`, `round=2` →
  `crop=300:150:8:12`, `round=1` → `crop=288:144:14:16`
  (`tests/preview/test_cropdetect.py::test_cropdetect_rounding_example`).

**The Q-3 frame budget** (`test_benchmark.py`: `hdr10-4k` through the facade, libplacebo, one
frame per task at the 10 sample times and at 2.0 s, 47 frames after a keyframe; the faster of
two cold runs): load average 3.4–4.2 on 12 threads: cold 678, 729, 726, 770, 678, 749, 787,
844, 688, 695, 820 ms (budget 2 s); cached mean 1.4 ms, max 3.8 ms (budget 50 ms);
`frame(key)` 38 µs. At load average 12–13: cold 699–920 ms; at load 19: up to 2.4 s.

**Cancel** (`test_cancel.py`, real FFmpeg; the time from `TaskManager.cancel` until the process
is gone, busy machine): a 4K output frame through `nlmeans=s=10:p=15:r=31` 15 ms; crop
detection on 60 samples of `hdr10-4k` 11 ms (no next sample starts); a 5 s 4K x265 `slow`
preview clip 25 ms (the partial clip is removed).

### Metadata edit (C-13)

Checked on 2026-10-15 with MKVToolNix **101.0** (`mkvpropedit`, `mkvmerge`, `mkvinfo`), FFmpeg
n9.0.2 (Arch) and n8.1.3 (BtbN), on copies of `multitrack.mkv`. Decision
[0034](../docs/decisions/0034-metadata-edit-in-place.md) uses these; the real-tool tests are
`packages/reframe/tests/metadata/test_metadata_edit_real.py` and
`packages/reframe/tests/probe/test_matroska.py`.

**Property names** (`mkvpropedit --list-property-names`): track headers `language`,
`language-ietf`, `name`, `flag-default`, `flag-forced`, `flag-commentary`,
`flag-hearing-impaired`, `flag-visual-impaired`, `flag-original` (also `flag-enabled`,
`flag-text-descriptions`); segment information (`--edit info`) `title`.

**An in-place edit takes about 25 ms** and writes both language elements:

```
$ time mkvpropedit e.mkv --edit track:a1 --set language=hun --set language-ietf=hu --set name="Magyar 5.1" \
    --set flag-default=1 --set flag-original=1 --edit track:a2 --set language=por --set language-ietf=pt-BR \
    --set flag-default=0 --edit track:a3 --set flag-commentary=1 --delete name --edit track:s2 \
    --set flag-hearing-impaired=1 --set flag-visual-impaired=1 --edit track:v1 --delete name
The file is being analyzed.
The changes are written to the file.
Done.
… 0,026 total
$ mkvmerge -J e.mkv     # track 1: language hun, language_ietf hu, track_name "Magyar 5.1", flag_original
                        # track 2: language por, language_ietf pt-BR; track 3: no track_name
```

`--delete name` on a track without a name, and `--edit info --delete title`, exit 0.

**Order of `language` and `language-ietf`.** `--set language=X` writes both elements
(`ger` → `ger` + `de`, `und` → `und` + `und`, `yue` → `chi` + `yue`); a later `--set
language=` overwrites an earlier `language-ietf`:

```
$ mkvpropedit f.mkv --edit track:a3 --set language-ietf=zh-Hant --set language=chi
$ mkvmerge -J f.mkv     # language chi, language_ietf zh   (zh-Hant is gone)
```

So Reframe always writes `--set language=<ISO 639-2/B> --set language-ietf=<BCP 47>`, in
that order (and its legacy code, which differs from MKVToolNix's for some tags: `test_languages.py`
`MKVTOOLNIX_DIFFERENT_LEGACY`).

**Track selectors.** `track:a2` is the second audio track in the order of the `TrackEntry`
elements, whatever their `TrackNumber`; attachments (a cover JPEG, fonts) are not tracks;
ffprobe lists the tracks in the same order and the attachments after them (a cover as a
`video` stream with `attached_pic`):

```
$ mkvmerge -o r.mkv --track-order 0:2,0:4,0:0,0:1 --attachment-mime-type image/jpeg \
    --attachment-name cover.jpg --attach-file cover.jpg m.mkv     # tracks: a, s, v, a, a, s, s
$ mkvpropedit r.mkv --edit track:1 --set track-number=9            # first entry is now number 9
$ mkvpropedit r.mkv --edit track:a1 --set name=FIRST-AUDIO --edit track:2 --set name=SECOND
$ mkvmerge -J r.mkv     # entry 1 (number 9, audio): FIRST-AUDIO; entry 2 (subtitles): SECOND
$ mkvpropedit r2.mkv --edit track:4 --set flag-original=1 --edit track:@5 --set flag-forced=1
                        # track:4 = 4th entry; track:@5 = TrackNumber 5
```

**Errors leave the file unchanged** (exit code 2):

```
$ mkvpropedit n.mkv
Error: Nothing to do.
$ mkvpropedit n.mkv --edit track:a9 --set name=x
Error: No track corresponding to the edit specification 'a9' was found. The file has not been modified.
$ chmod a-w n.mkv; mkvpropedit n.mkv --edit track:a1 --set name=x
Error: Updating the 'Tracks' element failed. Reason: The file could not be opened for writing. …
```

**A grown `Tracks` element moves to the end of the file.** FFmpeg leaves little room after
`Tracks`; adding `LanguageIETF` to two tracks and changing their flags made the file 700 bytes
larger (378787 → 379487): `mkvinfo -v -z` shows a `Void` where `Tracks` was and `Tracks` after
the `Cues`, found through the `SeekHead`. Reframe's Matroska reader follows the `SeekHead`
(`test_matroska.py` also checks it with 6000-character names).

**FFmpeg writes all six flags into Matroska; only `LanguageIETF` needs the fix-up.** Both
builds, the same output:

```
$ ffmpeg -v error -y -i m.mkv -map 0 -c copy -map_metadata:s -1 -metadata:s:a:0 language=hun \
    -metadata:s:a:0 title=X -disposition:a:0 default+original+visual_impaired -disposition:a:1 0 \
    -disposition:a:2 comment -disposition:s:0 forced+hearing_impaired -disposition:s:1 0 \
    -disposition:s:2 0 -disposition:v:0 0 out.mkv
$ mkvmerge -J out.mkv
  video default_track False · audio 1 default, flag_original, flag_visual_impaired, hun, "X"
  audio 2 default_track False · audio 3 flag_commentary · subtitles 1 forced, flag_hearing_impaired
  (no language_ietf on any track)
```

**MediaInfo and the re-probe.** With MediaInfo (the `pymediainfo` 7.0.1 wheel, libmediainfo
24.12) every track gets a BCP 47 `language`, derived from the legacy element when the track
has no `LanguageIETF` (`multitrack.mkv`: `ja` for `jpn`, `en` for `eng`, none for the `und`
video; `mkvmerge -J` shows no `language_ietf` on any track). The re-probe check compares
canonical BCP 47 tags on both sides, so it is not fooled. Since the core-complete review
(R4-3) the probe of a Matroska file takes `language_ietf` from Reframe's reader only, with
MediaInfo on or off: after the M6 demo edit the probe shows `hun`/`hu`, `por`/`pt-BR`,
`eng`/`None` (`test_metadata_unusual_files.py`, `test_matroska_limits_and_ietf.py`).

**An invalid `LanguageIETF`** (R4-4; mkvpropedit writes `language-ietf=en-US` on a1, then the
five bytes are replaced in the file): ffprobe reads the file (a1 `language=jpn`), `mkvmerge -J`
shows a1 as `jpn` with no `language_ietf`, MediaInfo shows the raw value (`en_US`, and
`j / a;x` for `j\na;x`). Reframe drops it with a probe warning.

**A `SeekHead` entry past the end of the file** (R4-2; the reviewer's `make_hostile.py`: long
names make mkvpropedit move `Tracks` behind the clusters, then a `Seek` `Tracks → 2^64 - 1` is
put in front of the real entry, in the `Void` after the `SeekHead`): ffprobe lists all seven
streams, `mkvmerge -J` all seven tracks; mkvpropedit refuses to edit the file:

```
$ mkvpropedit h.mkv --edit track:a2 --set language=por --set language-ietf=pt-BR
Error: Modification of properties in the section 'Track headers' was requested, but no
corresponding level 1 element was found in the file. The file has not been modified.   (exit 2)
```

In Python, `seek(2**63)` on a file raises `ValueError` ("cannot fit 'int' into an
offset-sized integer", CPython 3.14.7).

**Killing mkvpropedit during an edit** (R4-7 of the core-complete review; MKVToolNix 101.0,
copies of `multitrack.mkv`, an edit that grows `Tracks` so that it moves behind the clusters:
the language pair and a 200-character name on a1–a3 and s1–s3, about 27 ms). SIGKILL at a
random moment of the run: 150 runs, 146 killed while running, none damaged (the kill came
before the write; the file was unchanged). SIGKILL late in the run (60–120 % of its time):
900 runs, 3 damaged. mkvpropedit first overwrites the old `Tracks` with a `Void`, then writes
the new `Tracks` at the end of the file and points the `SeekHead` at it; a kill in between
leaves no reachable `Tracks` (`mkvinfo -v -z`: the `Void` of 685 bytes where `Tracks` was, and
either a `Tracks` after the `Cues` that the `SeekHead` does not name, or no `Tracks` at all).
ffprobe then shows no streams, `mkvmerge -J` recognises the file with 0 tracks, Reframe's
reader says "no Tracks element found".

mkvpropedit installs no signal handler: `SigCgt` and `SigIgn` in `/proc/<pid>/status`, read in
a tight loop during 20 such edits, are empty. So SIGTERM (and SIGINT) end it at once, as
SIGKILL does: SIGTERM late in the run, 600 runs, exit status -15 where it landed, 4 files
damaged in the same ways.

Through Reframe's queue (the real `Reframe` and mkvpropedit, the same edit, `queue.cancel()` at
a random moment up to 30 ms after mkvpropedit started, 300 runs): before R4-7, 2 damaged files
and 50 jobs that ended `cancelled` with no error although the file had the edit; with R4-7
(a cancel or `close()` lets a running in-place mkvpropedit finish; decision 0034, follow-up),
no damaged file, and all 300 ended `cancelled` with "The edit was already written …" and had
the edit. Only the step's 5-minute limit still kills a hung mkvpropedit.

After the final review's fixes (2026-10-17, decision 0034, RB-3 / RB-4; MKVToolNix 101.0, the
same edit on copies of five fixtures, the stop 0.6 to 1.2 times mkvpropedit's median run time
after it started): `cancel`, `close`, `pause` + `cancel`, `pause` + `close` and cancel-all, 60
runs each, no damaged file, and every job's end matched its file. With the step limit at 0.3 to
1.3 times the median run time (100 runs): 93 jobs `done` after the check, 7 `failed` "the file
may be damaged" with the file intact (killed before the write, or after it), none `cancelled`
(before RB-3: 22 of 200). A real `asyncio.run` stopped by two SIGINTs while the edit waits at
a gate: the shutdown cancels every task and so kills mkvpropedit; the stored job says so.

### Advanced encoder options (C-6, complete option sets)

Checked on 2026-10-15 with FFmpeg n9.0.2 (Arch `/usr/bin/ffmpeg`: x264 core 165, x265 4.3,
SVT-AV1 v4.2.0, libvpx 1.17.0), the pinned BtbN n9.0.2 build (x265 4.3+49, SVT-AV1
v4.2.0-151) and the BtbN n8.1.3 override build, and for AMF / VAAPI on an AMD RX 7600 (Mesa
26.2.4 radeonsi, amf-amdgpu-pro 25.10). Decision
[0035](../docs/decisions/0035-advanced-option-sets-and-dry-run.md). The tests repeat every
check (`needs_ffmpeg`; AMF / VAAPI `needs_gpu`):

```sh
uv run pytest packages/reframe/tests/definitions/test_tools.py packages/reframe/tests/definitions/test_options_values.py
uv run pytest packages/reframe/tests/validation/test_options_ffmpeg.py packages/reframe/tests/validation/test_options_facade.py
uv run pytest -m needs_gpu packages/reframe/tests/definitions   # every AMF / VAAPI option on the GPU
```

All three builds pass the non-GPU tests (`REFRAME_FFMPEG=…`). NVENC and QSV options come from
`ffmpeg -h encoder=<id>` only (named constants included): **not verified** on hardware. The
n8.1.3 help has every private option the sets use (it differs only in preset ranges and
NVENC's old `-cbr` / `-2pass` / `-spatial_aq` aliases).

**How each option was checked.** x264 / x265: a non-default value of every option reaches the
library's settings SEI (`test_every_x26x_option_reaches_the_library`); x264's colour tags are
not in its SEI and are read from the stream's VUI with ffprobe, as are x265's `range` and
`chromaloc` (its SEI has only flags for them); x265 `pools` from the log ("Thread pool created
using 2 threads"). The per-preset tables are the SEI of every preset and every tune
(`test_per_preset_defaults_match_the_library`); `lookahead-slices` from a 1280x720 encode.
SVT-AV1: the `SVT [config]` log lines and ffprobe (`test_svtav1_options_parse`,
`test_svtav1_option_defaults_in_the_log`). Every number option encodes at both range ends
(`test_option_range_ends_encode`, now with VP9) and every enum and bool value of the software
encoders encodes (`test_every_enum_and_bool_value_encodes`).

**Encoder facts behind the data:**

| Encoder | What the tool does | In the definitions |
|---------|-------------------|--------------------|
| x264 | `range=pc` / `tv` is overwritten by the input's range (FFmpeg's wrapper); `colorprim` / `transfer` / `colormatrix` / `chromaloc` win over the input's tags | `range` not offered |
| x264 | 8-bit `qpmax=81` → `qpmax=69`; 10-bit default 81 | 0–69, default "no limit" |
| x264 | `cqm=jvt` raises `qpmin` (a 10-bit encode with `qpmin=2` writes 9) | tested apart |
| x264 | `bluray-compat=1` with `bframes=5:weightp=2:b-pyramid=normal` writes 3 / 1 / strict, no message | `encoder.option_ignored` |
| x264 | `nal-hrd=vbr` without both VBV values: "NAL HRD parameters require VBV parameters", left out | `requires` → `encoder.option_inactive` |
| x264 | `pb_ratio` is in the SEI only with `mbtree=0` | fixed 1.3 |
| x265 | `qpmax=70`: the encoder does not open | 0–69 |
| x265 | `amp=1` with `rect=0` writes `amp=0`, no message | `requires` rect |
| x265 | `rd-refine` below RD 5: "--rd-refine disabled, requires RD level > 4 and adaptive quant"; `limit-tu` with `tu-inter-depth=1`: "limit-tu disabled, requires tu-inter-depth > 1"; `dynamic-rd` without VBV: "Dynamic-rd disabled, requires RD <= 4, VBV and aq-mode enabled"; `hrd` without VBV: "NAL HRD parameters require VBV parameters, ignored" | `requires` → `encoder.option_inactive` |
| x265 | `ctu=16:max-tu-size=32`: "Max TU size should be less than or equal to max CU size, setting max TU size = 16"; `qg-size` above the CTU likewise; `pmode=1` with `limit-refs=2`: "Limit reference options 2 and 3 are not supported with pmode. Disabling limit reference" | `encoder.option_ignored` |
| x265 | `ctu=16:min-cu-size=32`: "min CU size must be less than or equal to max CU size", exit 183 | `encoder.option_conflict` |
| x265 | `hdr10-opt=1` without BT.2020 tags: "Recommended Settings for HDR10-opt: colour primaries should be BT.2020, Disabling hdr10-opt." (exit 0) | help text |
| x265 | `rskip=2` is written to the SEI as `rskip=1 rskip-edge-threshold=0.050000`; `chromaloc` as a flag | tests read it so |
| x265 | below 720 lines: "Source height < 720p; disabling lookahead-slices"; at 720p the presets use 4 (ultrafast … slow) or 0 | per-preset table |
| SVT-AV1 | Ranges from its own errors: `aq-mode` 0–2, variance boost strength 1–4, octile 1–8, curve 0–2, `tf-strength` 0–4, `luminance-qp-bias` 0–100, `qp-scale-compress-strength` 0–3 (an integer: `1.5` is "Error parsing option"), `ac-bias` 0–8, `irefresh-type` 1–2, `hierarchical-levels` 0–5, `enable-dlf` 0–2, `min-qp` / `max-qp` 0–63, `tile-rows` 0–6, `tile-columns` 0–4 (5–6: "MaxTiles is 128 and MaxTileCols is 16"), `lp` 0–6 (7: "Setting maximum parallelism level") | ranges |
| SVT-AV1 | Defaults in the log: AQ mode 2, variance boost strength / octile / curve 2 / 5 / 0, sharpness 0, luminance QP bias 0, QP scale compress 0, "key frame" (irefresh-type 2), mini-GOP 32 at presets 0–8 and 16 at 10–11 | fixed / "from the preset" |
| SVT-AV1 | `aq-mode=0` turns CRF into constant QP (log "CQP") | help text |
| SVT-AV1 | `irefresh-type=1` with `hierarchical-levels=3`: "Fwd key frame is only supported for hierarchical levels 4 at this point. Hierarchical levels are set to 4" | `encoder.option_ignored` |
| SVT-AV1 | `min-qp` above `max-qp`: "MinQpAllowed must be smaller than or equal to MaxQpAllowed"; `qm-min` above `qm-max`: "Min quant matrix level must not greater than max quant matrix level" (exit 234) | `encoder.option_conflict` |
| SVT-AV1 | `matrix-coefficients=identity`: "Identity matrix … may be used only with 4:4:4" | not offered |
| SVT-AV1 | `mastering-display=G(0.265,0.69)…L(1000,0.0001)`, `content-light=1000,400` and the colour options win over the input's tags; ffprobe shows the side data in AV1 units (`44564/65536`, `256000/256`, `2/16384`) | Copy HDR metadata |
| libvpx-vp9 | No settings in the stream. 26 for `lag-in-frames` and 101 for `overshoot-pct`: "Failed to initialize encoder: Invalid parameter"; `arnr-maxframes=16` / `arnr-strength=7`: "Failed to set VP8E_SET_ARNR_… codec control" ("out of range [0..15]" / "[..6]"); `auto-alt-ref=7`, `sharpness=8`: "Error setting option … to value …" | ranges |
| libvpx-vp9 | Without a rate control FFmpeg uses CRF 32; a CQ value outside `qmin`…`qmax` fails ("CQ level 30 must be between minimum and maximum quantizer value (0-29)"), as does `qmin` above `qmax` | `encoder.option_conflict` |
| libvpx-vp9 | `qmin 0` / `qmax 63` and `sharpness 0` give the same file as no value (libvpx's defaults); undershoot / overshoot 0 or 100 give the same CQ file | fixed defaults; `requires` average bitrate |
| AMF (RX 7600) | Every pre-analysis option, `enforce_hrd`, `filler_data`, `preencode`, `async_depth`, `high_motion_quality_boost_enable`, `coder`, `me_half_pel` / `me_quarter_pel` (H.264), `me_quarter_pel` (H.265) encode | offered |
| AMF (RX 7600) | h264_amf with B-frames logs "AMF_INVALID_ARG: SetPropertyInternal() - BPicturesDeltaQP failed" (also for `bf_delta_qp` / `bf_ref_delta_qp`); hevc_amf `me_half_pel=0`: "Invalid settings: motionEstimationHalfPixel=0 and motionEstimationQuarterPixel=0", encoder not opened; av1_amf `-align 64x16` at 640x360: "Resolution incorrect for alignment mode", **exit code 0** and an empty output; `-align 1080p` / `none` keep 1920x1082 | not offered |
| VAAPI (radeonsi) | `idr_interval`, `async_depth`, `aud`, `tier` (H.265, AV1) encode; `low_power=1`: "Function not implemented"; h264 `b_depth=2`: "B-frame as L1 reference not supported"; `blbrc`: "Driver does not support BLBRC" | not offered |

**The dry run** (`-frames:v 1 -f null -`, video only): a refused custom parameter is in the
log, not the exit code, for three encoders:

| Encoder | `bogus=1` | Bad value | Exit code |
|---------|-----------|-----------|-----------|
| x264 | `Error parsing option 'bogus = 1'.` | `Error parsing option 'me = foo'.` (`bframes=99` is clamped silently) | 0 |
| x265 | `Unknown option: bogus.` | `Invalid value for me: foo.` | 0 |
| SVT-AV1 | `Error parsing option bogus: 1.` | `film-grain=99`: `Svt[error]: Film grain denoise strength is only supported for values between [0,50]` | 0 / 234 |
| libvpx-vp9 (own options) | `Unrecognized option 'bogus:v:0'.` | `Error setting option lag-in-frames to value abc.` | 8 / 234 |

x265 and SVT-AV1 print their own messages (`x265 [warning]: …`, `Svt[warn]: …`) whatever
FFmpeg's log level is.

**Level tags** (n9.0.2, the dry run's argv with `-loglevel +level+info`): FFmpeg tags each
line it logs after the line's contexts: `[libx264 @ 0x…] [warning] VBV maxrate specified, but
no bufsize, ignored`, `[info] Stream mapping:`, `[vost#0:0/libx265 @ 0x…] [enc:libx265 @ 0x…]
[error] …`. The second line of a message has no tag, and neither do x265's and SVT-AV1's own
lines. With the tags removed the log is the same as without the flag. `level+info` (no
leading `+`) resets the other flags: repeated lines are no longer folded into "Last message
repeated N times". Without the flag, x264's warnings through FFmpeg have no level word and
look like its info lines (`using SAR=1/1`). x264 logs `Error parsing option '…'` at the
warning level, and libvpx logs its configuration at the warning level when it cannot start.
`av1_vaapi` (radeonsi) `tile_groups=3`: `[warning] Invalid tile groups number 3, correct to 1.`

x264 warnings that name a parameter (custom parameters, dry-run argv): `VBV maxrate specified,
but no bufsize, ignored`, `VBV bufsize set but maxrate unspecified, ignored`, `NAL HRD
parameters require VBV parameters`, `b-pyramid normal + intra-refresh is not supported`,
`ref > 1 + intra-refresh is not supported`, `intra-refresh is not compatible with open-gop`,
`interlace + weightp is not implemented`, `subme=0 + direct=temporal is not supported`,
`ignoring unknown frame packing value`, `max bitrate less than average bitrate, assuming
CBR`, and the level limits (`frame MB size (20x12) > level limit (99)`, `DPB size …`, `MB rate
…`, `VBV bitrate …`, `VBV buffer …`). x264 clamps these without a word: `keyint=-5`,
`ref=0`, `crf=-20`, `crf=70`, `qp=100`, `b-adapt=5`, `bframes=20`, `rc-lookahead=300`,
`qpmin=60:qpmax=20`, `aq-mode=9`, `merange=2`, `keyint=10:min-keyint=20`, `threads=200`,
`qcomp=2`, `ipratio=0.5`, `nr=20000`, `deadzone-inter=40`, `slices=200`, `crf-max=10`.

#### Core-complete review (2026-10-16)

Checked with the same three builds (Arch n9.0.2, BtbN n9.0.2 and n8.1.3; the results are the
same in all three), each encode with the target in a temporary folder and a temporary working
folder. Tests: `tests/validation/test_custom_params_ffmpeg.py`, `test_dryrun_ffmpeg.py`,
`test_option_formats_ffmpeg.py`, `test_levels_ffmpeg.py`.

**Custom parameters that read or write files** (R5-1; the list is
`reframe/definitions/data/custom_params.toml`). Through the params argument the library reads
every key; keys are read with `_` as `-`, a leading `--`, and a `no` / `no-` prefix (which turns
the value into `true`):

| Encoder | Key | What happens (exit code 0 in every case) |
|---------|-----|-------------------------------------------|
| x265 | `csv=F`, `--csv=F` | F written (321 bytes for 5 frames) |
| x265 | `analysis-save=F`, `analysis_save=F` | F written (666 KB for 5 frames at 320x240; 5984 bytes for the reviewer's one frame) |
| x265 | `stats=F:pass=1`; `analysis-reuse-file=F:multi-pass-opt-analysis=1:pass=1` | F written |
| x265 | `pass=1` | `x265_2pass.log` and `x265_2pass.log.cutree` in the working folder |
| x265 | `no-csv=F` | "Invalid value for no-csv", and a file named `true` in the working folder |
| x265 | `analysis-load`, `scaling-list`, `lambda-file`, `dhdr10-info`, `nalu-file`, `film-grain`, `aom-film-grain`, `fovea-gaze-file` | read: "Error reading analysis data", "can't read matrix from F", "lambda file is incomplete", "Error reading (Aom) FilmGrain characteristics"; `nalu-file` and `film-grain` with a bad file crash FFmpeg (exit -11), Arch's `dhdr10-info` aborts (-6); BtbN: "--dhdr10-info disabled. Enable HDR10_PLUS in cmake" |
| x265 | `qpfile`, `zonefile`, `recon`, `recon-y4m-exec`, `dolby-vision-rpu`, `scenecut-qp-config`, `abr-ladder`, `input`, `output` | "Unknown option" (options of the x265 program only) |
| x264 | `dump-yuv=F`, `dump_yuv=F` | F written (576000 bytes for 5 frames) |
| x264 | `stats=F:pass=1` | F written; `pass=1` alone writes `x264_2pass.log` (+ `.mbtree`) in the working folder; `nostats=F:pass=1` writes `true` and `true.mbtree` there |
| x264 | `cqmfile=F` | read ("can't open file 'F'" when it is missing) |
| x264 | `opencl-clbin=F:opencl=1` | taken ("OpenCL: Unable to query installed platforms" here) |
| x264 | `qpfile`, `tcfile-in`, `tcfile-out`, `index`, `input`, `output` | "Error parsing option" |
| SVT-AV1 | `stat-file`, `fgs-table`, `recon`, `errlog`, `config`, `stats`, `qpfile`, `roi-map-file`, `input`, `output` | "Error parsing option" (options of SvtAv1EncApp); `pass=1` is taken and writes nothing |
| libvpx-vp9, as `-<name>:v:0` | `vstats_file`, `progress`, `stats_enc_pre` / `_post`, `stats_mux_pre`, `print_graphs_file` | F written: FFmpeg's own options take a stream specifier too |
| libvpx-vp9, as `-<name>:v:0` | `pass=1`; `report=1` | `ffmpeg2pass-0.log`; `ffmpeg-<date>.log` in the working folder |
| libvpx-vp9, as `-<name>:v:0` | `/filter=F`; `attach=F`; `fpre=F` | F read (FFmpeg reads an option's value from F when its name starts with `/`); `fpre` with a bad file crashes FFmpeg (-11) |

FFmpeg splits a params argument like `av_dict_parse_string`: `'csv'=F` and `c\sv=F` are the key
`csv`; `a=1:novalue:csv=F` is the keys `a` and `novalue:csv` ("Unknown option: novalue:csv.").
The private options of VP9, NVENC, QSV, AMF and VAAPI (`ffmpeg -h encoder=<id>`, the three
builds) and the 70 AVCodecContext options with the flags `E..V` (`ffmpeg -h full`, the same in
n8.1.3 and n9.0.2) name no file; `aspect`, `b` and `profile` are also FFmpeg's own options of
the same meaning.

**libvpx codec controls** (R5-3): a value out of a control's range is logged and dropped with
**exit code 0**: `arnr-maxframes=16` → "Failed to set VP8E_SET_ARNR_MAXFRAMES codec control:
Invalid parameter" and "Additional information: arnr_max_frames out of range [0..15]";
`arnr-strength=7` → `VP8E_SET_ARNR_STRENGTH` ("[..6]"); `min-gf-interval=40` →
`VP9E_SET_MIN_GF_INTERVAL` ("[0..(MAX_LAG_BUFFERS - 1)]"). Values out of an AVOption's range
(`tune-content=3`, `sharpness=8`, `cpu-used=12` …) stop FFmpeg instead ("Error setting option",
exit 222).

**x265 levels and `min-cu-size`** (R5-4): x265 pads the picture to the minimum CU before it
checks the level. 1920x1160 at level 4: `medium` exit 0; `medium` + `min-cu-size=16` or `32`
exit 183 ("picture dimensions are out of range for specified level"); `ultrafast` exit 183;
`ultrafast` + `min-cu-size=8` exit 0.

**VBV** (R5-7), x264 core 165 and x265 4.3:

| Parameters | CRF | Average bitrate |
|------------|-----|-----------------|
| `vbv-maxrate` only | dropped: x264 "VBV maxrate specified, but no bufsize, ignored" (the SEI says `rc=crf`, no VBV), x265 the same | dropped, the same message |
| `vbv-bufsize` only | dropped: "VBV bufsize set but maxrate unspecified, ignored" | used: "VBV maxrate unspecified, assuming CBR" (maximum = the bitrate; SEI `rc=cbr`) |
| both | used | used |

**HDR texts** (R5-8):

| Text | x265 `master-display` / `max-cll` | SVT-AV1 `mastering-display` / `content-light` |
|------|----------------------------------|-----------------------------------------------|
| `garbage` | "unable to parse mastering display color volume info", no mastering display; `max-cll`: "Invalid value", no light level | no mastering display, no message; `content-light`: "Invalid cll provided" |
| without `L(…)` | not parsed (as above) | no mastering display, no message |
| tags in another order | not parsed | taken |
| spaces before a number | taken | taken |
| text after the tags | ignored | **FFmpeg never ends** (killed after 15 s; also text before the tags) |
| a chromaticity above 65535 (x265) / 1 (SVT-AV1) | wraps: 70000 → 4464 | "Invalid mastering display info will be clipped to 0.0 to 1.0" |
| x265's whole numbers in SVT-AV1 | — | clipped, and `L(10000000,1)` overflows (maximum luminance −1734967296/256) |
| plain numbers in x265 | not parsed | — |
| `1000` (one light level) | "Invalid value for max-cll", but MaxCLL 1000, MaxFALL 0 written | "Invalid cll provided", nothing written |
| `1000,400,5` | taken (the rest ignored) | "Invalid cll provided" |
| `70000,400` | wraps to 4464 | clipped to 65535 |

#### Final review (2026-10-17)

Checked with the pinned BtbN n9.0.2 (x264 core 165, x265 4.3+49, SVT-AV1 v4.2.0); the tests
pass with Arch n9.0.2 and BtbN n8.1.3 too. Each encode ran in an empty temporary working
folder, with an `LD_PRELOAD` logger of every `open` / `fopen`. Tests:
`tests/validation/test_custom_params_ffmpeg.py`
(`test_x264_reads_and_applies_the_file_a_cqm_value_names`,
`test_a_value_that_is_a_name_or_a_file_name`), `test_custom_params_cqm.py`,
`test_option_formats_ffmpeg.py` (`test_signs_and_spaces_with_the_encoders`).

**A value that is a name or a file name** (RC-1). The library reads the value after FFmpeg's
quotes and escapes:

| Key | Taken as a name (no file is opened) | Opened as a file |
|-----|-------------------------------------|------------------|
| x264 `cqm` | a value that contains `flat` (the flat matrix, SEI `cqm=0`), else one that contains `jvt` (SEI `cqm=1`): `flat`, `jvt`, `'jvt '`, `./flat`, `/x/jvt/matrix.cfg`, `xflaty`, `flatjvt` | every other value, case-sensitive: `FLAT`, `Flat`, `JVT`, `fla`, `default`, `0`, `/x/matrix.cfg` ("can't open file 'F'", exit 187); a valid matrix file is read and applied (SEI `cqm=2`, the same as `cqmfile=F`) |
| x265 `scaling-list` | only `default` and `off` | every other value, case-sensitive: `DEFAULT`, `Off`, `./default`, `flat`, `0`, `default ` (an escaped or quoted space reaches x265) ("can't open scaling list file F", exit 183) |
| x264 `nocqm` / `no-cqm`, x265 `no-scaling-list` / `noscaling-list` | — | a file named `true` (`=flat`, `=0`, `=default`: "Error parsing option" / "Invalid value", then the file is opened) or `false` (`=1`) |

x264 does not read `CQM`, `--cqm` or `cqm_file` as `cqm` ("Error parsing option"); x265 reads
`--scaling-list` and `scaling_list` as `scaling-list`, but not `SCALING-LIST` ("Unknown
option").

**The extra search: every key that opens the file it is given.** Every token of 2 to 41
characters in `libavcodec.so.63` (68604) went to the library as a key: with an absolute path in
a missing folder, a relative name, and relative names with 12 file extensions (`.cfg`, `.txt`,
`.tbl`, `.json`, `.bin`, `.yuv`, `.y4m`, `.log`, `.csv`, `.stat`, `.dat`, `.xml`). Each key
that was not refused ("Error parsing option", "Unknown option", "Invalid value") then ran
alone, and with `pass=1`:

| Library | Keys that open the file they are given | A name or a file |
|---------|----------------------------------------|------------------|
| x264 | `cqm`, `cqmfile` (read), `dump-yuv` (written), `stats` (written with `pass=1`); `opencl-clbin` is taken (no OpenCL here) | `cqm` |
| x265 | `analysis-load`, `aom-film-grain`, `film-grain`, `lambda-file`, `nalu-file`, `scaling-list` (read), `analysis-save`, `csv`, `stats` with `pass=1` (written), also with `_` | `scaling-list` |
| SVT-AV1 | none: no key takes a path or a file name (`mastering-display` takes the relative name as text, and with a path FFmpeg never ends) | — |

Every key found is in `custom_params.toml`; keys that need another key or a build feature to
open their file (x265 `analysis-reuse-file`, `dhdr10-info`, `fovea-gaze-file`; x264
`opencl-clbin`) were there already.

**x265 with deblocking off never finishes a small picture** (RC-3, a known limit; decision
0041, final review). Found on the way, not a file key. An earlier note here blamed the text
`deblock=abc`; the cause is the picture width. x265 4.3 with the deblocking filter off
(`no-deblock=1`, `deblock=false`, or a `deblock` value that x265 cannot read) never finishes a
picture narrower than about 256 pixels (192×108 to 224×126 checked). FFmpeg sits at 0 % CPU and
ignores SIGTERM. In Reframe (checked by the lead): the dry run gives the warning
`encoder.dry_run_skipped` ("did not finish within 30 s") after 30.0 s; a queued encode fails
with "FFmpeg made no progress … (no output, no CPU use) and was stopped" at the stall limit
(600 s by default; 20 s in the lead's reproduction), and the process is killed. Checked again
with the Arch n9.0.2 build (x265 4.3), 0.2 s of `testsrc2`: 192×108 with `no-deblock=1` or
`lft=abc` had not finished after 12 s (killed); 320×180 with `no-deblock=1` or `deblock=abc`,
and 192×108 with deblocking on, finished.

**Signs and white space in the HDR texts** (RC-2); "the same" means the same side data in
the output:

| Text | x265 `master-display` / `max-cll` | SVT-AV1 `mastering-display` / `content-light` |
|------|----------------------------------|-----------------------------------------------|
| `+N` (also ` +N`, `\f+N`) | the same as `N` | the same as `N` (also `+.15`, `+1e+3`) |
| `-0` (`-00`, `-0.0`, `-.0`, `-0e-5`) | the same as `0` | the same as `0` |
| `-N` | wraps: `-1` → 65535, `-400` → 65136, `-13250` → 52286 (no primaries in the output); `L(…,-1)`: no luminance | changed: `-0.265` → 48169/65536 ("Invalid mastering display info will be clipped to 0.0 to 1.0", but not clipped), `L(1000,-0.0001)` → −2/16384; `content-light` as x265 |
| `++N`, `+ N` (x265 also `+-N`) | not parsed | no metadata |
| tab, `\v`, `\f` before a number | skipped | skipped |
| a no-break space before a number, Arabic-Indic digits | not parsed (`max-cll`: "Invalid value") | no metadata (`content-light`: "Invalid cll provided") |
| `\v` or `\f` before the text (FFmpeg drops only space, tab, CR and LF around a value) | not parsed | FFmpeg never ends |

### Power actions (C-14)

Checked on 2026-10-15 on Arch Linux (CachyOS kernel 7.2.8), systemd 262 (`262-1-arch`), polkit
127, KDE Plasma 6 (Wayland). **Read-only checks only: no power action was ever run, also not
`--dry-run`.** Decision [0036](../docs/decisions/0036-power-actions.md). Code:
`reframe/platform/power.py`. Tests: `packages/reframe/tests/platform/test_power*.py` (fake
executors, a fake command runner, mocked Windows DLLs; the shared pytest plugin makes the real
functions fail every test that reaches them).

- `systemctl --help` lists `poweroff`, `suspend`, `--no-ask-password` ("Do not prompt for
  password"), `--check-inhibitors=MODE` and `--dry-run` (which also covers `poweroff` and
  `suspend`; not used and not run).
- `man systemctl` (262): `poweroff` "is asynchronous; it will return after the power-off
  operation is enqueued, without waiting for it to complete"; `suspend` "will return after the
  suspend operation is successfully enqueued. It will not wait for the suspend/resume cycle to
  complete." `--check-inhibitors` defaults to `auto`: "logind will perform the check and
  respect active inhibitor locks, but systemctl will only do a client-side check for
  interactive invocations (i.e. from a TTY)". So Reframe (no TTY) gets logind's answer.
- `man org.freedesktop.login1` (262): `PowerOff(in b interactive)`, `Suspend(in b
  interactive)`; "The interactive boolean parameters can be used to control whether polkit
  should interactively ask the user for authentication credentials if required."
- `busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager
  CanPowerOff` → `s "yes"`; `… CanSuspend` → `s "yes"`; `… CanHibernate` → `s "yes"`.
- `pkaction --action-id … --verbose` (implicit any / inactive / active):
  `org.freedesktop.login1.power-off` `auth_admin_keep / auth_admin_keep / yes`;
  `power-off-multiple-sessions` the same; `suspend` the same;
  `power-off-ignore-inhibit` `auth_admin_keep` for all three. So the active desktop session
  may shut down and suspend without a password; a service outside the active session, another
  logged-in user or a `block` lock of someone else needs an administrator password, which
  `--no-ask-password` turns into an error (`power.failed`) instead of a dialog.
- `systemd-inhibit --list` on this desktop: only `delay` locks for `sleep` / `shutdown`
  (NetworkManager, UPower, rtkit, kwin, VS Code, Discord) and PowerDevil's `block` lock on the
  power / suspend / hibernate keys and the lid; nothing would refuse `poweroff` or `suspend`.

Windows (documentation only, nothing run; the code is mock-tested on Linux):

- `shutdown` (learn.microsoft.com, windows-commands/shutdown, updated 2025-12-01): `/s` "Shuts
  down the computer"; `/t <xxx>` "Sets the time-out period before shutdown to xxx seconds. The
  valid range is 0-315360000 (10 years), with a default of 30. If the timeout period is
  greater than 0, the /f parameter is implied."; `/f` "Forces running applications to close
  without warning users. Caution: Using the /f option might result in loss of unsaved data.";
  `/a` "Aborts a pending system shutdown … during the time-out period"; `/c <comment>` "a custom
  reason … You can use a maximum of 512 characters."
- `SetSuspendState` (learn.microsoft.com, powrprof.h, updated 2024-02-22): `BOOLEAN
  SetSuspendState(BOOLEAN bHibernate, BOOLEAN bForce, BOOLEAN bWakeupEventsDisabled)`;
  `bHibernate` FALSE: "the system is suspended"; `bForce` "This parameter has no effect";
  `bWakeupEventsDisabled` FALSE: "any system wake events remain enabled"; zero on failure
  (`GetLastError`); "The calling process must have the SE_SHUTDOWN_NAME privilege. To enable
  the SE_SHUTDOWN_NAME privilege, use the AdjustTokenPrivileges function." The page says
  nothing about Modern Standby (S0ix) machines or about the call returning only after resume:
  both are not verified.

### When-done actions (C-11)

Nothing to record: the queue's when-done actions run no tool. They call C-14's power service
(its OS calls are under "Power actions (C-14)") and the notification hook
([decision 0037](../docs/decisions/0037-when-done-power-actions-and-job-notifications.md)).

### Tools fetch and the CLI (C-15)

Checked on 2026-10-15 (Arch Linux, Python 3.14, the pinned BtbN n9.0.2 build of
`tools/ffmpeg.toml`). Tests: `packages/reframe/tests/tools/test_fetch*.py`,
`packages/reframe/tests/jobs/test_cli_{presets,when_done,plan_dry_run}.py`.

- **The version check.** The first line of `-version` of the pinned build is exactly
  `ffmpeg version n9.0.2-17-g2a571b6068-20260930 Copyright (c) 2000-2026 the FFmpeg developers`
  and `ffprobe version n9.0.2-17-g2a571b6068-20260930 Copyright (c) 2007-2026 the FFmpeg
  developers`: the third word is the manifest's `version`. The fake tools of
  `reframe_testing` print the same captured text, so a fake build in a test archive passes
  the check (and a scenario with `ft.version("n8.0")` fails it).
- **The real build through `reframe tools fetch`.** The extracted BtbN folder (234 MB:
  `bin/`, `lib/` with the `.so` links, `include/`, `doc/`, `man/`, `presets/`,
  `LICENSE.txt`), packed again as `tar.xz` (xz preset 0) and served by `http.server` on
  127.0.0.1 with a manifest of that archive's SHA-256 and size: downloaded, checked,
  extracted with the `data` filter (the `lib/*.so` symbolic links stay inside the folder and
  pass), `ffmpeg -version` / `ffprobe -version` of the extracted binaries print the pinned
  version (they load `lib/` through their RPATH from the temporary folder too), installed
  into `<data dir>/tools/ffmpeg` in 5.6 s, and tool discovery then reports both as `found ·
  bundled`, also over `/usr/bin/ffmpeg` on `PATH`. A second run hashes the files (about 1 s)
  and downloads nothing. The real download from GitHub was not run (no network in tests).
- **The marker** `.fetch-tools.json` has the format of `scripts/fetch-tools.py` with
  `layout: "bundled"` and the files relative to the install folder, so an install of
  `scripts/fetch-tools.py --install-dir <data dir>/tools/ffmpeg` (CI) counts as installed
  for `reframe tools fetch` and the other way round (test
  `test_the_script_and_the_core_recognise_each_others_install`).
- **Python 3.14 `asyncio.shield`.** When the outer future is cancelled and the shielded
  task then ends with an exception, asyncio calls the loop's exception handler ("exception
  in shielded future"; the anyio test runner turns it into a test error). The worker thread
  of a cancelled fetch ends with exactly such an exception, so the fetch waits with
  `asyncio.wait({future})` (a cancel of the wait leaves the future alone) instead of
  `shield`.
- **Progress events coalesce.** `task.progress` events of one task replace each other in a
  subscription's queue (`reframe.events`); a CLI that is busy for a moment shows only the
  latest step. The plain-line output of `tools fetch` therefore never relies on seeing every
  step, and the tests read the events while the task runs.

### Batch engine (C-12, M7)

Checked on 2026-10-15 with FFmpeg n9.0.2 (the Arch package; the fixture probes recorded with
the pinned BtbN build) and MKVToolNix 101.0.

- **FFmpeg's TrueHD encoder makes 5.1 at most.** `truehd` (`mlpenc`) is experimental
  (`-strict -2`) and lists the layouts mono … `5.1(side)`; `-ac 8` fails with "Specified
  channel layout '7.1' is not supported by the truehd encoder" (exit 234). `-ac 6` gives
  `5.1(side)`, 24-bit (`s32`, `bits_per_raw_sample` 24). ffprobe shows no `profile` (no Atmos)
  and, in Matroska, no `bit_rate`: Reframe's probe calls it "TrueHD", lossless, bit rate
  unknown. So the 04 §Example's "jpn TrueHD Atmos 7.1" is "jpn TrueHD 5.1" in `anime-s01`
  (decision 0040). Test: `testing/tests/test_media_fixtures.py::test_truehd_encoder_has_no_7_1`.
- **A stream copy keeps everything the batch engine reads.** `ffmpeg -i master.mkv -map 0
  -map -0:a:2 -c copy -metadata title=…` keeps each stream's language, title and
  dispositions (`default`, `forced`, `comment`) and the codec parameters; ffprobe of the
  copies shows the master's tracks minus the dropped ones, renumbered (E05: the commentary is
  #3 and the subtitles #4, #5; E11: the subtitles #2, #3). `-metadata:s:s:0 title=Signs` after
  `-map -0:a:1` titles the output's first subtitle stream (the signs track). Test:
  `test_media_fixtures.py::test_anime_seasons`.
- **The ASS tracks are `ass` with no statistics:** FFmpeg's Matroska muxer writes no
  `NUMBER_OF_FRAMES` tag, so `event_count` is unknown and C-3's "few events" heuristic does
  not run; the signs track's roles come from its flag (`forced`) and its title ("Signs").
- **The real encode of `reframe batch`** (`tests/jobs/test_cli_batch.py`, season 2 with the
  demo preset): TrueHD 5.1 → `libopus` 5.1 448 kb/s and DTS-HD MA 5.1 → `ac3` 5.1 640 kb/s;
  the re-probe shows `opus` 6 channels "Japanese 5.1" (default) and `ac3` 6 channels at
  640 000 b/s "English 5.1"; the ASS tracks are copied with `forced` on "Signs & Songs" and
  `default` on "Full".

### Filtergraph syntax and free filter text (S-1)

Checked on 2026-10-22 with the pinned build and the Arch Linux package (both n9.0.2). The real
ffmpeg writes the filters it parsed with `-print_graphs_file g.json -print_graphs_format json`
(FFmpeg 8 and later); `-v debug` shows each option value (`Setting 's' to value 'max(0,1)'`).

```sh
ffmpeg -v error -f lavfi -i nullsrc=s=64x64:d=0.04 -filter_complex "<graph>" \
  -print_graphs_file g.json -print_graphs_format json -f null -
```

| Graph | Filters FFmpeg makes |
|-------|----------------------|
| `hue=s='max(0,1)',hflip` | `hue` (`s` = `max(0,1)`), `hflip`: a quoted comma is not a split |
| `hue=s=max(0\,1),hflip` | `hue` (`s` = `max(0,1)`), `hflip`: nor is an escaped comma |
| ` eq =brightness=0.1 , hflip , ` | `eq`, `hflip`: spaces around names and separators go; a trailing `,` or `;` is accepted |
| `null@x,'hf'l\ip` | `null` (instance `x`), `hflip`: a name loses its quotes and escapes too |
| `[0:v]hflip [a];[a] vflip;` | `hflip`, `vflip`: labels, also after a space |
| `hflip, [a]vflip` | the label after `, ` is read (the run then fails: `[a]` has no source) |
| `metadata=mode=add:key=k:value='x,hflip` | `metadata` only, with `value` = `x,hflip`: a quote that is not closed takes the rest of the text, without an error |
| `hflip\` | error `No such filter: 'hflip\'`: a backslash at the end is kept |
| `,hflip`, `hflip,,vflip` | error `No such filter: ''` |
| `hue=s=1]` | error `Error parsing filterchain 'hue=s=1]' around: ]` |
| `sws_flags=bicubic;hflip` | `hflip`: a leading `sws_flags=…;` sets the scaler flags, it is not a filter |

`reframe_server.filtertext.parse_graph` follows these rules. It refuses a quote that is not
closed and a backslash at the end (FFmpeg reads them in a way the check cannot follow), and
reads a leading `sws_flags` as a filter (which is not allowed). Asserted by
`packages/reframe-server/tests/test_security_filtertext.py`.

`ffmpeg -h filter=<name>`: only options of type `<string>`, `<dictionary>` and `<binary>` can
hold a file name, a URL, a device or a plugin. In the pinned build, for example: `movie` /
`amovie` `filename`; `drawtext` `fontfile`, `textfile`; `libplacebo` `lut`, `shader_cache`,
`custom_shader_path`, `extra_opts`; `curves` `psfile`, `plot` (writes); `nnedi` `weights`;
`deshake` `filename` (writes); `subtitles` / `ass` `filename`, `fontsdir`; `lut3d` `file`;
`metadata` `file` (writes); `psnr` / `ssim` `stats_file` (writes); `vidstabdetect` `result`
(writes); `signature` `filename` (writes); `sendcmd` `filename`; `zmq` `bind_address`
(network); `frei0r` `filter_name` (a plugin); `lv2` `plugin`; `arnndn` `model`; `hwupload` /
`hwmap` `derive_device`. No filter of the allow-list (`ALLOWED_FILTERS`) has such an option,
in either build.

**Option values read from a file.** The ffmpeg tool (not libavfilter) reads an option's value
from a file when the option's name starts with `/`: `eq=/contrast=FILE` sets `contrast` to
the file's contents (`-vf` and `-filter_complex` alike; the file's text appears in the error
`Error when parsing the expression '…' for contrast`). Checked on 2026-10-22 with both builds
(n9.0.2), a file holding `SECRET-CONTENT-123`:

| Graph | Reads the file |
|-------|----------------|
| `eq=/contrast=F`, `lutyuv=/y=F`, `setpts=/expr=F`, `unsharp=/lx=F`, `hue=/s=F`, `drawbox=/color=F`, `scale=/w=F`, `scale=/sws_flags=F` (an option of a child object), `eq=/enable=F` (the timeline option) | yes: any option of any filter |
| `eq='/contrast'=F`, `eq='/'contrast=F`, `eq=\/contrast=F` | yes: the options lose one level of quoting and escaping first |
| `eq=brightness=0:/contrast=F`, `eq=1:/contrast=F` (after a value without a name), `eq= /contrast=F`, `eq=brightness=0: /contrast=F`, `eq=brightness=0:<tab>/contrast=F`, `eq=/contrast =F` | yes: spaces around the name are skipped |
| `eq=brightness='0:/contrast=F'`, `eq=brightness=0\:/contrast=F` | yes: that quote and escape are gone before the options are split at `:` |
| `eq@x=/contrast=F`, `eq=/contrast='F'`, `hflip,eq=/contrast=F` | yes |
| `eq=brightness='0\:/contrast=F'`, `eq=brightness=0\\:/contrast=F` | no: the second level escapes the `:`, so `brightness` is `0:/contrast=F` |
| `eq=\'/contrast\'=F` | no: a quote is not a name character, so the text is a value |
| `eq=//contrast=F` | no: `Error applying option '//contrast' to filter 'eq': Option not found` |
| `eq=contrast=/F`, `eq=enable=/F`, `eq=F` | no: a value that starts with `/` is a value |

So a name with a leading `/` can only start at the beginning of the options or after a `:`
(after the first level of unquoting), then spaces. `filtertext` refuses every `/` there, also
in the "no" rows of the second level and `eq=//contrast`, `eq=F` (when in doubt, refuse).
FFmpeg's expression evaluator has no function that reads a file (`man ffmpeg-utils`,
"Expression Evaluation"); the tool's other file syntax, `-/option FILE`, is a command-line
option, which free filter text cannot reach. Asserted by
`packages/reframe-server/tests/test_security_filtertext.py`.

### VAAPI device text (S-2, web-mode settings)

Checked on 2026-10-22 with the pinned build (n9.0.2, libva 1.24, Intel iHD driver) and
`LIBVA_MESSAGING_LEVEL=2`:

```sh
ffmpeg -hide_banner -v verbose -init_hw_device "vaapi=va:<device>" -f lavfi -i testsrc=d=0.1 -frames:v 1 -f null -
```

| `<device>` | What happens |
|------------|--------------|
| `/dev/dri/renderD128` | libva opens `/usr/lib/dri/iHD_drv_video.so`; the run works |
| `/dev/dri/renderD128,driver=../../../../../tmp/…/evil` | the text after the comma is a device option: `libva: User requested driver '…'`, `Trying to open /usr/lib/dri/../../../../../tmp/…/evil_drv_video.so`, so a library named by the client is loaded (here it does not exist: `Device creation failed: -5`) |
| `/dev/dri/renderD128,kernel_driver=i915` | accepted, the run works |
| `/etc/passwd`, a folder | `Failed to open … as DRM device node.`, `Cannot open X11 display …`: FFmpeg opens the path, then tries it as an X11 display name |
| `:0` | tried as an X11 display (`Cannot open X11 display :0.`) |
| `/dev/dri/card1` | `vaGetDriverNames() failed`: a primary node does not work for VAAPI here |

So web mode accepts only `/dev/dri/renderD<n>` (or empty: automatic). Asserted by
`packages/reframe-server/tests/test_settings.py::test_a_web_client_can_only_choose_a_vaapi_render_node`.

### uvicorn shutdown with a WebSocket client that does not read (S-3)

Checked on 2026-10-22 with uvicorn 0.54.0 (`ws="auto"`: websockets-sansio), websockets 17.3 and
Python 3.14 on Linux: a server whose event client paused reading after 200 messages of
128 KiB. At shutdown uvicorn gives the app `websocket.disconnect` (1012), writes a close frame
and calls `transport.close()`; the socket stays open while its write buffer is not empty (150 KB
here), so the connection stays in `server_state.connections` and uvicorn waits for it without
a limit. A second SIGINT does not help (`Server.wait_closed()` waits for every connection).
With `timeout_graceful_shutdown=2` uvicorn stops waiting after 2 s, logs `Cancel 0 running
task(s), timeout graceful shutdown exceeded` (ERROR) and runs the lifespan's shutdown; the
real `reframe-server` exited 2.5 s after SIGINT. Asserted by
`packages/reframe-server/tests/test_events.py::test_the_server_stops_while_a_client_does_not_read`.

A client socket given `SO_RCVBUF` 8192 before it connects keeps a 16 KB receive buffer; one
left alone grew from 128 KB to about 1 MB (Linux auto-tuning). The server's send buffer grew to
2.6 to 4 MB either way; the hub's send waited after 17 to 24 messages of 128 KiB.

### Request paths that reach the static files (S-4)

Checked on 2026-10-28 with uvicorn 0.54.0 (h11 0.16.0: httptools is not installed, so `http="auto"`
is h11), httpx 0.28.1, Starlette 1.9.0 and Python 3.14 on Linux, with raw request lines sent on
a socket:

| Request target | `scope["path"]` the app sees |
|----------------|------------------------------|
| `/../etc/passwd` | `/../etc/passwd` (dot segments are not removed) |
| `/%2e%2e/b` | `/../b` |
| `/x%2f..%2fy` | `/x/../y` (`%2f` becomes a separator) |
| `/a\..\b` | `/a\..\b` (unchanged; a separator only on Windows) |
| `/a%00b` | `/a\x00b`; `Path.resolve()` then raises `ValueError` |
| `/%5c%5chost%5cshare%5cx.js` | `/\\host\share\x.js` (`%5c` becomes `\`) |
| `/%5c/host/share/x.js` | `/\/host/share/x.js` |
| `/C:/Windows/win.ini` | `/C:/Windows/win.ini` |

On Windows such a path leaves the folder before any check (read in `ntpath.py` and `pathlib` of
Python 3.14.8 and checked with `PureWindowsPath` on Linux on 2026-10-28; not run on Windows):

- The join drops the folder: `PureWindowsPath("C:/srv/web") / "\\\\host\\share\\x.js"` is
  `\\host\share\x.js`; `\/host/share/x.js` gives the same UNC path, `C:/Windows/win.ini` gives
  `C:\Windows\win.ini`, and `\\.\pipe\name` stays a named pipe.
- `Path.resolve()` is `os.path.realpath`. On Windows that is `ntpath.realpath`, which calls
  `nt._getfinalpathname` (`ntpath.py` lines 674 and 709) and so opens the path: for a UNC path an
  SMB connection with the user's credentials. On Linux `ntpath.realpath` is only `abspath`.
- `posixpath.realpath` without `strict` ignores every `OSError`; `ntpath.realpath` raises a
  Windows error that is not in its list of expected ones (`_getfinalpathname_nonstrict`).
- `ntpath.isreserved` (Python 3.13+, pure string code on every OS) first removes the drive or UNC
  part (`splitroot`), then is true for a name with a control character (NUL among them),
  `"*:<>?|`, a trailing dot or space, or a DOS device name, also with an extension (`CON`,
  `nul.txt`, `COM1`, `CONIN$`). `aux-Ab12.js` is not reserved. So the drive and UNC forms are
  refused by their `:` and `\`, apart from it.

httpx removes literal dot segments from a URL before it sends it (`/a/../b` becomes `/b`), but
keeps `%2e%2e`. So a traversal test sends its request line on a socket to a live uvicorn
(`packages/reframe-server/tests/test_static.py::test_no_path_leaves_the_folder`).

Starlette's router calls `Router.default` only after no route matched (also not partly, which
would give 405) and no slash redirect applied. Inside an app it raises `HTTPException(404)`,
which the app's handler turns into the problem answer; for a WebSocket it closes the connection
(uvicorn answers 403).

`npm run build:web` (Vite 8.3.4) writes `dist/index.html` and `dist/assets/index-<hash>.js` /
`.css` only (the frontend has no `public/` folder). The real `reframe-server` with
`REFRAME_STATIC_DIR=frontend/dist` served it; the headless Chromium shell
(`chromium_headless_shell-1248`, `--dump-dom`) loaded `/queue` and the Vue app mounted under the
server's CSP with no refused resource.

### Local owner mode: uvicorn start-up failure, binds and addresses (S-7, task A)

Checked on 2026-10-28 with uvicorn 0.54.0, httpx and Python 3.14 on Linux, with the real
`reframe-server`:

- **A lifespan that fails at start-up ends the process with 3.** `uvicorn.Server.startup`
  runs `sys.exit(STARTUP_FAILURE)` (3) when the lifespan's start-up fails, and also when the
  bind fails. The `SystemExit` leaves the task of `server.serve()` and stops the event loop
  (`Task exception was never retrieved … exception=SystemExit(3)`), so code after
  `await server.serve()` does not run. Caught inside the coroutine that awaits
  `server.serve()`, it ends only that task, which is what `serve()` does. Asserted by
  `packages/reframe-server/tests/test_owner.py::test_owner_only_exits_75_against_a_held_lock_and_writes_nothing`
  and `test_app.py::test_a_server_whose_port_is_taken_exits_1`.
- **Starlette logs the whole traceback** of a lifespan that fails at start-up (uvicorn logs
  the `lifespan.startup.failed` message at ERROR): 121 lines for `StoreBusy`, because FastAPI
  nests the lifespan once for each of the 18 included routers.
- **Which address reaches which bind** (`--port 0`; the port from `server.json`; httpx):

  | `--host` | Listening sockets | `127.0.0.1` | `[::1]` | `localhost` |
  |---|---|---|---|---|
  | `127.0.0.1` | `127.0.0.1` | yes | refused | yes |
  | `::1` | `::1` | refused | yes | yes |
  | `localhost` | `::1` and `127.0.0.1` on two different ports | yes (the published port was the IPv4 socket's) | refused | yes |
  | `0.0.0.0` | `0.0.0.0` | yes | refused | yes |
  | `::` | `::` only (asyncio sets `IPV6_V6ONLY`) | refused | yes | yes |
  | `172.17.0.1` | `172.17.0.1` | refused | refused | refused |

  `localhost` resolves to `::1`, then `127.0.0.1` (`getent ahosts localhost`), and httpx tries
  both. Clients use `127.0.0.1` (decision 0056).
- **`mkstemp` makes the file `0600`**: `server.json` written through
  `reframe.settings.JsonDocumentFile` has mode `0o100600` with the default umask. Asserted by
  `test_owner.py::test_the_endpoint_file_names_the_listening_server_until_it_stops`.
- **The end of an idle exit** (`--mode desktop --idle-exit 1`, seconds after `server.json`
  appeared, polled every 2 ms): the port refuses at 1.081, `server.json` is gone at 1.181 and
  `queue.lock` is free at 1.181 (uvicorn closes the listener, sleeps 0.1 s and waits up to 2 s
  for open connections before the lifespan runs). An event client that had not authenticated
  when the idle exit came was closed after 1.08 s with code 1012, as an authenticated one is
  at SIGINT: uvicorn's shutdown closes every WebSocket before the lifespan closes the hub.
  Recorded in decision 0056 (follow-up) for C-17.
- **A `queue.lock` that is a folder** cannot be opened (`os.open` with `O_RDWR | O_CREAT`:
  `IsADirectoryError`, errno 21): the core's `queue.unreadable` path, used by
  `test_owner.py::test_owner_only_exits_1_when_the_lock_cannot_be_used`.

### uvicorn WebSocket ends (S-7 attachments)

Checked on 2026-10-28 with uvicorn 0.54.0 (`ws="auto"`: websockets-sansio), websockets 17.3 and
Python 3.14.8 on Linux: read in `uvicorn/protocols/websockets/websockets_sansio_impl.py`, and
the `websocket.disconnect` message that the hub's listener reads printed in the tests below.

| How the connection ends | The app's `websocket.disconnect` |
|-------------------------|----------------------------------|
| The client closes with a close handshake | the client's code (`{"code": 1000, "reason": ""}`) |
| The client's socket goes away (`transport.abort()`), also while the server's send waits | `{"code": 1005}` (`connection_lost` after the handshake) |
| uvicorn shuts down (`should_exit`) | `{"code": 1012}` (`shutdown()`); the client sees close code 1012 |

- `connection_lost` puts the disconnect in the app's queue before it wakes a send that waits
  for the transport; that send then raises `ClientDisconnected` (Starlette:
  `WebSocketDisconnect`). `handle_close` also queues the disconnect before it closes the
  transport. So when a send fails because the client left, a receive already has the
  disconnect.
- One connection's frames reach the app in the order they came: a text message sent before
  the close frame is received before the disconnect.

Asserted by `packages/reframe-server/tests/test_attach.py`
(`test_a_server_stop_leaves_the_attached_jobs_to_the_queue`: close code 1012 and the job not
cancelled; `test_a_detach_keeps_the_jobs_of_its_own_connection`: a `detach` and then the
close) and `packages/reframe-server/tests/test_events.py`
(`test_a_client_that_drops_while_the_hub_waits_to_send_has_its_jobs_cancelled`).

### The remote queue and `reframe queue` (C-17)

Checked on 2026-10-28 on Linux with Python 3.14.8, SQLite 3.54.0, websockets 17.3, httpx 0.28.1
and uvicorn 0.54.0 ([decision 0061](../docs/decisions/0061-c17-remote-queue-and-queue-commands.md)).

- **A client when the server is killed** (`kill -9` of a real `reframe-server`, a `websockets`
  client authenticated on `WS /api/events`): `recv` raises `ConnectionClosedError` with no
  close frame (`rcvd` and `sent` `None`), close code 1006, 5 ms after the kill. After uvicorn's
  shutdown the close code is 1012 (the S-7 section above). `RemoteQueue` reports the second
  as "the Reframe server stopped" and the first as "the connection to the Reframe server was
  lost".
- **SQLite in read-only mode on a WAL database** (`file:…?mode=ro`, the queue store with no
  open writer, then with a writer that holds the database open): both read. When no `-wal`
  and `-shm` files exist, the read-only connection makes them and leaves them. In a folder the
  user cannot write, `mode=ro` fails with "attempt to write a readonly database" and
  `mode=ro&immutable=1` reads the file. A missing file fails with "unable to open database
  file" (`read_saved_queue` checks first).
- **`flock` twice in one process**: a second `open` of `queue.lock` in the process that holds
  it, then `flock(LOCK_EX | LOCK_NB)`, raises `BlockingIOError` (the lock belongs to the open
  file description). The owner-search tests hold `queue.lock` or `server-start.lock` in the
  pytest process to play another process.
- **The CLI-started owner**: `python -m reframe_server --mode desktop --host 127.0.0.1 --port
  0 --owner-only --idle-exit 30` from `launch_detached` (new session, null stdio) writes
  `server.json`, takes the jobs of every client, and ended 30 s after its last client (seen
  with `ps` and `reframe queue list`, which then read the saved queue).
- **An encode for the real-process tests**: a 720p `testsrc2` video with a sine tone (x264
  ultrafast) is encoded with the default preset (H.265 MKV 1080p) at about 1.6 times real time
  here, under load and `nice -n 19`: 20 s of video in 12 s. The tests use 60 s for a job that
  must still run while the test acts, and 2–8 s for jobs that must end.

Asserted by `packages/reframe/tests/remote/test_shared_queue_real.py` (the kill of a server,
the owner and its idle start, the encodes), `test_cli_queue.py`
(`test_list_without_an_owner_reads_the_saved_queue_as_it_is`) and `test_owner_search.py` (the
locks held in the test process).

Checked on 2026-10-29 for the CLI's review fixes (Linux 7.3, Python 3.14.8, uvicorn 0.54.0,
websockets 17.3, rich 15.0.0, click 8.5.0, psutil 7.2.2):

- **A stopped client is dropped by uvicorn's keepalive.** A `websockets` client process,
  authenticated on `WS /api/events`, was stopped with SIGSTOP while the server's ping interval
  and ping timeout were 1 s each: the hub forgot the connection 2.03 s later and its listener
  read disconnect code 1005, the code of a client that is gone, so its attached jobs are
  cancelled. (In uvicorn's source: the pong time-out fails the connection with 1011 and closes
  the transport, and `connection_lost` queues 1005.) With the defaults (20 s and 20 s) the
  lead saw a job cancelled 29 s after the SIGSTOP of `reframe encode`.
- **SIGTSTP and an orphaned process group.** SIGTSTP with its default action stopped a child
  in a process group of its own (`process_group=0`, its parent in another group of the same
  session); a child in a new session (an orphaned group) went on running. The real-process
  Ctrl+Z test starts the CLI in a group of its own for this reason.
- **Python 3.14's `asyncio.shield`.** When the waiter of a shielded task is cancelled and the
  task then fails, the loop's exception handler gets "RemoteError exception in shielded
  future" (anyio's test runner turns that into a test error). The CLI waits for the add that
  is under way at Ctrl+C with `asyncio.wait`, which does not cancel the task and reports
  nothing.
- **rich's `Progress`** can be stopped and started again: the bars come back (the CLI takes
  them off the terminal while it is stopped).
- **Drafting in client mode does not hold the event loop**: with 120 files (fake tools) the
  longest gap of a 10 ms timer was 0.11 s, for `encode` (13.5 s in all) and for `batch`
  (6.5 s), measured under load with `nice -n 19`; the client's connection answers the
  keepalive pings in between.
- **click's truth values** (`click.BOOL`, also for an option's environment variable): `1`,
  `true`, `t`, `yes`, `y`, `on` and `0`, `false`, `f`, `no`, `n`, `off`, any case, spaces
  stripped; empty is false; another value (`2`, `garbage`) is a usage error (exit 2).

Asserted by `test_cli_client.py` (Ctrl+Z, a lost connection, the add under way at Ctrl+C,
`REFRAME_IN_PROCESS`) and `test_shared_queue_real.py`
(`test_ctrl_z_pauses_the_job_and_fg_resumes_it`).

### Docker image and deployment (S-6, task D)

Checked on 2026-10-28 on the owner's desktop (Docker 29.9.2 without buildx, Compose 5.6.1,
uv 0.13.5), with the image of `docker/Dockerfile` and no `/dev/dri` in any container:

- **No buildx.** `DOCKER_BUILDKIT=1 docker build` fails ("BuildKit is enabled but the buildx
  component is missing"). `docker compose build` falls back to the classic builder by itself
  (`Step 1/2 …`, `Successfully built`). The classic builder takes `ARG` before `FROM`, an
  image reference with a digest, and `COPY --from=<image>`. The whole build took 75 s.
- **Debian 13's Mesa** is built with `-Dvideo-codecs="all"` (`debian/rules` of mesa
  25.0.7-2+deb13u1, line 154), so `radeonsi_drv_video.so` in `mesa-va-drivers` has the H.264,
  HEVC and AV1 encoders. Debian's free `intel-media-va-driver` has only some encoders before
  Ice Lake (its package description); `intel-media-va-driver-non-free` has them all.
  `libmfx-gen1.2` (25.1.4) is the oneVPL GPU runtime. `tzdata` comes with these packages.
- **The BtbN shared build** needs only glibc and `libgcc_s` of the system (`ldd bin/ffmpeg`):
  libva is linked in, and finds Debian's drivers through `LIBVA_DRIVERS_PATH`, which tool
  discovery sets to `/usr/lib/x86_64-linux-gnu/dri`.
- **A clean stop ends with SIGTERM.** uvicorn raises the signal again after its shutdown, so
  `reframe-server` dies of SIGTERM: exit 143 in Docker (`tini` reports 128 + 15; the image
  maps it to 0 with `tini -e 143`) and in a shell. `docker compose stop` during an x265 encode
  took 0.3–0.4 s; the `.part` file was removed and the job was `interrupted` at the next start.
- **`docker exec` runs as root**, also when the main process dropped to `PUID`: the image
  links `reframe` and `reframe-server` to the entrypoint, so `--set-password` through
  `docker compose exec` writes `/config/auth.json` as `PUID:PGID`.
- **`setpriv`** (util-linux, in the slim image) changes the user without a passwd entry.
  Docker containers have `CAP_MKNOD`, so the entrypoint's group logic was checked with
  `mknod` stand-ins under `/dev/dri` (groups 987 and 44 added, a node of group 0 left out).
- **pydantic-settings reads list settings as JSON**: `REFRAME_MEDIA_ROOTS='["/media"]'` gives
  `media_roots == [Path("/media")]` in the real container (an output outside it is 403
  `path.outside_roots`). Asserted by `packages/reframe-server/tests/test_deploy.py`.
- **uvicorn 0.54 trusts `X-Forwarded-*` only from `FORWARDED_ALLOW_IPS`** (default
  `127.0.0.1,::1`; CIDR networks work). Through nginx 1.31.8 on a Docker network, with the
  proxy sending `X-Forwarded-Proto: https`: without the variable the session cookie had no
  `Secure`; with `FORWARDED_ALLOW_IPS=172.16.0.0/12` it had. Without `REFRAME_ALLOWED_HOSTS`
  the proxy's host name got 400 `request.host`; with it, `GET /`, the login and the
  `/api/events` WebSocket (`hello`, then a `heartbeat` within 20 s) worked through the proxy.
- **`uv tool install './packages/reframe[cli]' --with ./packages/reframe-server
  --with-executables-from reframe-server`** makes one tool environment (`reframe`) with both
  commands; `--with-executables-from` takes the package name of a path given with `--with`.
  `systemd-analyze --user verify` accepts the unit of `docs/deployment.md`.

Checked again on 2026-10-28 for the review of S-6 (same Docker and Compose, nginx
1.31.8-alpine-slim, util-linux 2.41.5 `setpriv` and Debian's `dash` in the image):

- **The client address that the container sees.** A connection from the host to a port
  published on `127.0.0.1` comes from the gateway of the container's network (`172.17.0.1`
  on the default bridge, `172.30.87.1` on a compose network with that fixed gateway). So does
  each connection that Docker's port forwarding passes on: nginx in a container saw
  `172.30.87.1` for requests from the host to its port on `127.0.0.1` and on `[::1]`. A
  container on the default bridge could not connect to a container of another bridge network
  (timed out). A port published on `127.0.0.1` refused the host's LAN address and `[::1]`.
- **`ip_range` without `gateway`**: Docker took the first address of the range as the gateway
  (`172.30.87.128` for `ip_range: 172.30.87.128/25`); with `gateway: 172.30.87.1` the first
  container got `172.30.87.128`.
- **uvicorn takes the last untrusted address of `X-Forwarded-For`**, so nginx's
  `$proxy_add_x_forwarded_for` (the client's header, then the address nginx saw) gives the
  real client. Through nginx with `FORWARDED_ALLOW_IPS` set to the proxy's one address, a
  client that sent a new `X-Forwarded-For` with each wrong password got 429 at the 6th try,
  and another client still logged in (200, `Secure` cookie). A direct client got 429 at the
  6th try too, and no `Secure` with `X-Forwarded-Proto: https` over plain HTTP. With
  `FORWARDED_ALLOW_IPS=172.16.0.0/12`, a client on the host through the published port got
  12 × 401 (never 429) and a `Secure` cookie over plain HTTP; without the variable five wrong
  passwords through a proxy on the host gave every client 429.
- **A missing host folder of a bind mount** is made by Docker as `root:root`. The entrypoint
  gives `/config` and `/data` to `PUID`; `/output` stays root's, and a job failed with
  `output.not_writable`. Docker's documentation says that published ports pass by ufw (not
  checked here: no root).
- **`setpriv` and `chown` read ids as decimal**: `--reuid=01000` and `chown 01000:010` give
  1000 and 10. `--reuid=00` stays root with every capability of the container (`CapEff:
  00000000a80425fb`). A rootful container's `/proc/self/uid_map` is `0 0 4294967295`;
  `unshare --user --map-root-user` gives `0 1000 1`. In `dash`, under `set -e`, an assignment
  from a command substitution that exits 2 ends the script with 2.
- **`docker run --user 4321:4321`** gives `HOME=/`. With `/config` and `/data` owned by
  another user (mode 0755) the server starts and is `healthy`, but logs "the jobs of this
  server are not saved" and cannot write its cache. `reframe-server --port 9000` as the
  command makes the container `unhealthy` (the `HEALTHCHECK` calls `REFRAME_PORT`);
  `REFRAME_PORT=9000` is `healthy`.
- **`cp -r dist target`** into an existing `target` copies into `target/dist/`; the files of
  the first copy stay in `target/`.

### Subtitle files, tags and chapter files (S-2 additions, M6 task S6)

Checked on 2026-11-01 with both FFmpeg n9.0.2 builds (Arch and the pinned BtbN
`n9.0.2-17-g2a571b6068-20260930`, the same results) and MKVToolNix v103.0. The routes that rely
on it are tested in `packages/reframe-server/tests/test_subtitles.py` and
`test_job_output.py`.

**ffprobe on external subtitle files** (`ffprobe -v error -of json -show_streams -show_format
-count_packets -i FILE`):

| File | `format_name` | `codec_name` | `nb_read_packets` |
|------|---------------|--------------|-------------------|
| `text-subs.en.srt` (UTF-8), the same with a UTF-8 BOM, with CRLF | `srt` | `subrip` | 2 |
| a Hungarian SRT in CP1250, a French one in Latin-1 | `srt` | `subrip` | 3, 2 (ffprobe does not decode the text) |
| a Hungarian SRT in UTF-16LE or UTF-16BE with a BOM | `srt` | `subrip` | 3 |
| `text-subs.en.ass`, and a `.ssa` (`ScriptType: v4.00`, `[V4 Styles]`) | `ass` | `ass` (never `ssa`) | 3 |
| a `.vtt` | `webvtt` | `webvtt` | 2 |
| the `ass` file named `.srt` | `ass` | `ass` | 3 (the demuxer goes by content) |
| `.sup` of the `pgs` fixture's tracks (`mkvextract` or `ffmpeg -c copy -f sup`) | `sup` | `hdmv_pgs_subtitle` | 48 and 16: one packet per *segment*; 12 and 4 display sets (the subtitle scan's count) |
| an empty `.srt`, a text file that is no subtitle file | exit 1, `Invalid data found when processing input` | | |

**Decoding the text** (`ffmpeg -i FILE -c:s srt -f srt -`):

- UTF-8, with or without a BOM, and `-sub_charenc UTF-8` on a BOM file: right.
- CP1250 or Latin-1 without `-sub_charenc`: exit 69, `Invalid UTF-8 in decoded subtitles text;
  maybe missing -sub_charenc option`. With `-sub_charenc CP1250` / `ISO-8859-1`: right
  (`Árvíztűrő tükörfúrógép.`, `Café à la crème.`).
- **UTF-16 with a BOM is read wrongly.** Without `-sub_charenc`, every event whose text starts
  with a letter that is not ASCII fails to decode (`Invalid UTF-8 …`, exit 0, the other events
  are written); copied into Matroska (`-c:s copy`), that first letter is U+FFFD as `mkvextract`
  writes it back (`Árvíztűrő` → `�rvíztűrő`, `Őszi` → `�szi`; `ű`, `ő` later in a line are
  kept). With `-sub_charenc UTF-16LE` or `UTF-16` every event fails (`Unable to recode subtitle
  event … from UTF-16LE to UTF-8`, exit 69). So `subtitles/inspect` names the encoding from the
  BOM and warns (`subtitle.utf16`: save the file as UTF-8); a detected `UTF-8` or `UTF-16*` is
  not a value for `-sub_charenc`.

**Tags as the builder writes them** (`-map_metadata:g -1 -metadata <key>=…` with the keys of
`reframe.command.metadata.TAG_KEYS`), read back with `ffprobe -show_format`: Matroska gives
`title` and `ARTIST`, `ALBUM_ARTIST`, `DATE`, `COMMENT`, `GENRE`, `DESCRIPTION`, `SYNOPSIS` (upper
case); MP4 gives the same keys in lower case. `jobs/tags` looks the source's values up without
case.

**Chapter files and mkvmerge.** `mkvmerge -o out.mkv --chapters FILE --no-chapters chapters.mkv`
reads the OGM and XML files that `jobs/chapters/export` writes (names such as
`Árvíztűrő, "tükör"`, `Part = 1; #2`, `<Two> & more`); `ffprobe -show_chapters` shows them. An
OGM file is read right as UTF-8 with and without a BOM, also under `LC_ALL=C`. OGM has no end
times: the last chapter ends at the end of the file (5.034 s), while the XML end times are kept
(5.000 s). `mkvextract FILE chapters out.xml` writes a UTF-8 BOM, a commented `<!DOCTYPE …>`,
`EditionFlagDefault` and `ChapterUID`; `mkvextract FILE chapters -s out.txt` writes OGM text;
`chapters/import` reads both.

**HandBrake's chapter CSV** (HandBrake itself was not run; read from its source on GitHub,
`master`, 2026-11-01): Windows (`ChaptersViewModel.Export`, `CsvHelper.Escape`) writes
`number,name` per line, the name in double quotes when it holds `,`, `"`, a line end or a tab,
`"` doubled, UTF-8 without a BOM, `Environment.NewLine`; its import (`CsvHelper.ParseFile`,
`ChapterImporterCsv`) parses RFC 4180, needs an integer first column and takes the second
column trimmed. macOS (`HBChapterTitlesController`) quotes for `,` and `"` only, writes LF and
no final line end, and its import needs the rows numbered 1 … n with as many rows as the movie
has chapters. Reframe writes RFC 4180 (Python's `csv`, minimal quoting, LF, a final line end),
which both import, and reads with Python's `csv`: the second column trimmed, a warning when the
numbers are not 1, 2, 3 ….

### Subtitle encodings, tag arguments and chapter files (M6 fix round, task FA)

Checked on 2026-11-01 with the pinned FFmpeg (BtbN `n9.0.2-17-g2a571b6068-20260930`), MKVToolNix
v103.0 and Linux 7.3 (x86-64). Tests: `reframe-server/tests/test_subtitles.py`,
`test_job_output.py`; `reframe/tests/validation/cases_metadata.py`, `test_chapters.py`,
`command/test_output_chapters.py`.

**An external SRT decoded with and without `-sub_charenc`** (`ffmpeg -i FILE -c:s srt -f srt -`,
three events: `Árvíztűrő tükörfúrógép`, `Őszi ünnep`, `plain ű`). Without `-sub_charenc` FFmpeg
copies a stream as it is (`-c:s copy`), so a file that is not UTF-8 reaches the output as invalid
UTF-8 (shown as U+FFFD, R1's finding); decoding it gives:

| File | none | `CP1250` | `UTF-8` | `UTF-16LE` / `UTF-16` | `CP1252` | `NOPE` |
|------|------|----------|---------|-----------------------|----------|--------|
| CP1250 | exit 69, `Invalid UTF-8 in decoded subtitles text` | right | exit 69, `Unable to recode … from UTF-8` | other characters (CJK), the last event lost, exit 0 | `Árvíztûrõ` (wrong letters), exit 0 | exit 234, `Unable to open iconv context` |
| UTF-8, with or without a BOM | right | events with letters that are not ASCII lost (`Unable to recode`), `plain Ĺ±`, exit 0 | right | other characters, events lost, exit 0 | events lost, `plain Å±`, exit 0 | exit 234 |
| UTF-16LE or UTF-16BE with a BOM | events that start with a letter that is not ASCII lost (`Invalid UTF-8`), exit 0 | `ĂrvĂ­ztĹ±rĹ‘` (mojibake), exit 0 | events that start with a letter that is not ASCII lost (`\xc3rvíztűrő`: that letter loses a byte), exit 0 | other characters, events lost, exit 0 | mojibake, exit 0 | exit 234 |
| UTF-32 with a BOM | exit 183, `Invalid data found when processing input` (also with every `-sub_charenc`) | | | | | |
| ASCII only | right, with every ASCII-based encoding | right | right | other characters | right | exit 234 |

So validation (`jobs/validate`, the queue) reports, at `subtitles[i].source.charset`, as errors:
`subtitle.charset_unknown` (no encoding chosen and the file is not UTF-8), `subtitle.utf16` (a
UTF-16 or UTF-32 file whatever is chosen, or a UTF-16 / UTF-32 / UCS encoding chosen), and
`subtitle.charset_mismatch` (UTF-8 chosen for a file that is not UTF-8, or another encoding
chosen for a UTF-8 file with letters that are not ASCII). An ASCII-only file passes with any
chosen encoding.

**ffprobe `-count_packets` and an empty subtitle file.** A file that ffprobe opens but that has no
event (`WEBVTT` with nothing after it, an `.ass` with only its header) gives its stream without
`nb_read_packets` (the key is left out at 0 packets); `subtitles/inspect` counts that as 0 events
(`subtitle.no_events`). An empty `.srt`, a BOM alone or blank lines: exit 1, as S6 found.

**One argument on Linux.** `ffmpeg … -metadata synopsis=<value>` (Python `subprocess`): an
argument of 131 071 bytes runs (FFmpeg writes the tag: 131 062 characters read back); 131 072
bytes fail before FFmpeg starts (`OSError: [Errno 7] Argument list too long`, the kernel's
`MAX_ARG_STRLEN` of 32 pages of 4096 bytes, NUL included); `ARG_MAX` is 2 097 152. A NUL character
in an argument: `ValueError: embedded null byte` from Python. So a tag is at most 3000 characters
(`metadata.tag_too_long`; at most 12 000 bytes in UTF-8) and a NUL in a tag or a track name is
`metadata.nul_character`. The longest command line of the builder's snapshot jobs
(`loudnorm_two_tracks_with_two_pass`) is 1 667 characters as `subprocess.list2cmdline` joins it
for Windows; with all eight tags at 3 000 characters it is 25 821, below Windows' 32 767 (the
`CreateProcess` limit from Microsoft's documentation; not checked on Windows yet, M10).

**mkvmerge v103 and OGM chapter files** (`mkvmerge -o out.mkv --chapters FILE --no-chapters …`,
read back with ffprobe): a line ends at CR LF, LF or a CR alone; U+2028, U+0085, `\x0b` and `\x1c`
stay in a name. The pairs are taken in the file's order, the numbers ignored: a repeated
`CHAPTER01` gives two chapters (`A` at 0, `B` at 2 s), `01, 03, 02` keeps that order (times 0,
1, 2), and `CHAPTER01= …` with `CHAPTER02NAME=X` names chapter 1 `X`. A name keeps its leading
spaces, its trailing white space is cut (`  lead and trail`); an empty name is written as
`Chapter 02`. mkvmerge refuses (exit 2, `Unknown chapter file format`) a file whose first line is
a name, a time without its name line, names only, and lower-case `chapter01=`; hours past 99
(`100:00:00.000`) are taken. A CP1252 file is read as UTF-8 (U+FFFD for each byte that is not
ASCII), and under `LC_ALL=C` each name is cut at its first such byte. `chapters/import` reads OGM
in the file's order the same way; it also takes a name before its time and a lone name (a
warning), and pairs a number's time and name where mkvmerge pairs by position. A file that is
not UTF-8 is read as Windows-1252 where every byte is defined there (curly quotes, dashes and
`€` come out right), else as Latin-1.

**mkvmerge and XML chapter names**: a `ChapterString` is kept as it is (`  spaced  `,
`\n  indented\n  `); CR LF becomes LF (XML's own line-end rule, which expat applies too).
`chapters/import` reads the names the same way, not trimmed.

**FFMETADATA chapters without a title.** A `[CHAPTER]` with no `title=` line, mapped with
`-map_chapters 1` into Matroska, gives a chapter with no title (ffprobe shows none). So after one
rename (names written through the FFMETADATA file) an untitled source chapter stays untitled in
the encoded file, as when the chapters are copied (a copy of `chapters.mkv` with two chapters,
`First` and an untitled one, names `["Renamed", ""]`: ffprobe `Renamed`, then no title).

### D-0 (4a)

Checked on 2026-10-23 on CachyOS (kernel 7.2, KDE Plasma on Wayland), Python 3.14.8,
PyInstaller 6.22.3 with pyinstaller-hooks-contrib 2026.9, Tauri 2.12.5 (CLI 2.12.4), tokio
1.54.1, util-linux 2.42.4. The spike and its scripts: `desktop/spike/README.md`.

- **`PR_SET_PDEATHSIG` follows the thread that forked**, not the process: a child forked by a
  thread that then ended got SIGTERM at once (return code -15) while the process lived on; a
  child forked by the main thread kept running. The spike shell forks on its main thread
  (tokio's `Command::spawn` forks on the calling thread; the shell logs `gettid()` = pid).
- **pidfd and a reused pid**: `pidfd_open` of a process that has ended and was reaped raises
  `ProcessLookupError`; a pidfd becomes readable when its process ends.
  `/proc/<pid>/stat` field 22 is the start time in clock ticks (100 per second here), the same
  unit for every process. Asserted by
  `packages/reframe-server/tests/test_parent.py::test_the_server_and_its_encode_stop_when_the_parent_is_killed`
  and `::test_a_process_younger_than_the_server_is_not_its_parent`.
- **uvicorn and SIGTERM**: uvicorn 0.54 handles SIGTERM like `should_exit`: the run of the spike
  with the death signal alone (no `--parent-pid`) ended with the job `interrupted` and its
  `.part` file removed.
- **PyInstaller onedir**: the bootloader runs Python in its own process (no child process;
  `/proc/<pid>/exe` is the frozen binary). The hooks of pydantic, uvicorn, websockets and
  langcodes collect what they need; babelfish, language_data, guessit, the `reframe` data and
  pymediainfo need options (the table in `desktop/spike/README.md`, each with its error). The
  pymediainfo hook's default library patterns miss the wheel's `libmediainfo.so.0`. Asserted by
  `packages/reframe-server/tests/test_frozen_sidecar.py` (skipped without the build).
- **guessit 4.4.0** reads `guessit/config/options.json` at its first call; without it every call
  raises (`FileNotFoundError`), and the core reads that as "no match".
- **Tauri**: `npx tauri build` runs `cargo build --bins --features tauri/custom-protocol
  --release`; without that feature tauri's `build.rs` sets `cfg(dev)` and the app loads
  `devUrl`. `generate_context!()` fails without `icons/icon.png` (`failed to open icon …`).
  The page's origin on Linux is `tauri://localhost` (in the server's desktop CORS list).
  `AppHandle::exit(0)` and a closed last window both reach `RunEvent::Exit`
  (`xdotool windowquit` under XWayland).
- **Page cache without root**: `posix_fadvise(POSIX_FADV_DONTNEED)` on every file of the onedir
  took its cached bytes from 38 MB to 0 (`fincore`). Pages that a running process maps stay
  (the `uv` binary of a running `uv run`, 17.9 MB). `fincore` 2.42 uses `cachestat`, which
  refuses files the user cannot write: `fincore: failed to do cachestat:
  /usr/lib/python3.14/os.py: Operation not permitted`.
- **psutil 7.2.2** `Process.kill()` checks the pid and the create time before it sends the
  signal (`_send_signal` calls `_raise_if_pid_reused`). The spike's cleanup script checks the
  start time itself (field 22 of `/proc/<pid>/stat`, as the server's parent watch does) before
  each SIGKILL of a process that is not its own child.
- **A child often starts in its parent's clock tick** (2026-10-27, kernel 7.3, `SC_CLK_TCK`
  100): a Python started through `timeout 60` had the start tick of `timeout` in 198 of 200 runs;
  through `timeout 60 timeout 60`, the outer `timeout`'s in 177 of 200; `uv run` and its Python
  in 4 of 20. A stand-in started just before the frozen server, not its ancestor, had the
  server's tick (`2272227` for both) and the server refused it (`the parent process … is not
  running`, exit 1). Asserted by
  `packages/reframe-server/tests/test_parent.py::test_a_process_of_the_servers_clock_tick_is_its_parent_only_when_it_is_an_ancestor`.
- **A process name with `)` and a space**: a Python started through a symlink named `a) b` has
  `comm` `a) b` and a stat line `381433 (a) b) S 381432 …`; only the last `)` ends the name.
  Asserted by `test_parent.py::test_a_process_younger_than_the_server_is_not_its_parent`.
- **MediaInfo in the frozen build** (`/usr/bin/ffprobe` n9.0.2): of the fixtures, the video
  bit rate of `anamorphic`, `hdr10-4k`, `hdr10`, `interlaced`, `letterbox`, `pgs`, `vobsub` and
  `vfr.mkv` comes from MediaInfo (`vfr.mkv`: 483043, source `mediainfo`); a build without
  `pymediainfo` and `libmediainfo` gives `unknown` for each, and no fixture gets a
  `language_ietf`. `vfr.mp4` has a stream bit rate from ffprobe (489085). Asserted by
  `test_frozen_sidecar.py::test_the_frozen_server_reads_bit_rates_with_its_bundled_mediainfo`.
- **Tauri's event permissions**: `core:event:default` is `allow-listen`, `allow-unlisten`,
  `allow-emit` and `allow-emit-to` (`src-tauri/gen/schemas/acl-manifests.json`, Tauri 2.12.5).
- **Tauri's `data_directory`** (Tauri 2.12.5, wry 0.57.0): `WebviewWindowBuilder::data_directory`
  becomes the key of wry's web context, which gives WebKitGTK a `WebsiteDataManager` with that
  folder as its base data and its base cache directory, and `cookies` in it
  (`wry/src/webkitgtk/web_context.rs`). Without it WebKitGTK uses its default, which here was
  `~/.local/share/org.reframe.spike/` (the app's identifier).

### D-0 (4b-i)

Checked on 2026-10-27 on CachyOS (kernel 7.3), KDE Plasma 6.8.1 on Wayland (KWin 6.8.1,
Xwayland 24.1.14), WebKitGTK `webkit2gtk-4.1` 2.54.2, GTK 3.24.52, Dolphin 26.08.2, systemd
262 (`busctl`), Playwright 1.64.1 (Chromium 156.0.8078.4, Firefox 157.0), the system Python
3.14.8 with PyGObject 3.58.1. The tools: `desktop/spike/README.md`, "WebKitGTK checks".

- **KWin scripts over D-Bus** (`qdbus6 org.kde.KWin /Scripting`): `loadScript(path, name)`
  then `start()` runs a plain JavaScript file; `unloadScript(name)` stops it and
  `isScriptLoaded(name)` is then `false`; a loaded script has an object `/Scripting/Script<N>`.
  `print()` reaches the user journal about 0.5 s late (`journalctl --user -f`); a
  `callDBus(name, path, interface, method, text)` to a name that nobody owns is seen at once by
  `busctl --user monitor --json=short` (the bus answers the call with an error). A
  `callDBus` to KWin's own name is not seen on the bus.
- **KWin placement**: KWin 6.8.1 has no `ActiveMouseScreen` setting (`strings
  /usr/lib/libkwin.so.6.8.1` has no such key; `kreadconfig6 --file kwinrc --group Windows`
  gives nothing for it, `Placement`, `FocusStealingPreventionLevel` or `SeparateScreenFocus`, so
  the defaults hold: centred placement, level 1 "Low"). A new window goes to
  `Workspace::activeOutput()`, centred in its work area. In KWin's 6.8 source,
  `PointerInputRedirection::updatePosition` sets the active output to the one under every
  pointer move, and `Workspace::setActiveWindow` sets it to the output of every activated
  window, also one that a script activates. The review's run fits it: its second app window was
  added on `DP-1` 2.3 s after the guard had given the keyboard back to the movie player there
  (where the cursor was then is not recorded). The scripting API reads it as `workspace.activeScreen` (read only) next to
  `workspace.cursorPos`. `workspace.windowAdded` comes before the window's
  first frame, so `opacity = 0` there hides it until it is moved. Setting `frameGeometry` to
  a new position alone takes effect at once; a new position together with a new size waits
  for the client, and twice in four tries with the Tauri window it did not take effect at all
  (the window stayed where KWin had put it, once on `DP-1`): move first, resize second.
  `getWindowInfo(uuid)` has `x`, `y`, `width`, `height` and `pid`, but no output. Before the
  spike's windows had `keepAbove = true` and overlapped, a drag from Dolphin never reached the
  app (it got no `wl_data_device.enter`); with both, every drag did.
- **Position requests**: under XWayland (`GDK_BACKEND=x11`) KWin honours the position that
  Tauri asks for (`WebviewWindowBuilder::position(100, 100)` → frame at 100,100); on native
  Wayland it is ignored (the window is centred on the output under the cursor). GTK under
  XWayland also maps a 1×1 helper window at -100,-100 (class empty) when the app starts; its
  normal window has the class `Reframe-spike`, on Wayland the app id is `reframe-spike`.
  Playwright's Chromium takes its Wayland app id from `CHROME_DESKTOP` when that is set (VS
  Code sets it to `com.microsoft.VSCode.desktop`); without it the class is `chromium-browser`.
  Playwright's Firefox window: `firefox-default`. Each browser window belongs to the pid that
  Playwright launched (`executablePath`).
- **KWin and focus**: setting `workspace.activeWindow` from a script activates that window
  (the scripts give the keyboard back that way); a new Tauri window is activated when it maps.
  In KWin 6.8's `Workspace::addWaylandWindow` a new window is activated when focus stealing
  prevention is "Low" or lower (the default here), and `windowAdded` is emitted after
  `activateWindow`; the scripting wrapper's signals (`windowAdded`, `windowActivated`,
  `windowRemoved`, `cursorPosChanged`, …) have nothing earlier and `activeScreen` has no
  setter. So a script first hears of a new window in `windowActivated`, when it already has the
  keyboard: each new spike window took it for 2 to 3 ms (the owner's `foreground_booster` log in
  the user journal), also on `HDMI-A-1`.
- **GTK 3 and an empty `XDG_CONFIG_HOME`** (`Gtk.Settings` in the system Python, no window):
  with the owner's config `gtk-font-name` is `Noto Sans 10`, the theme `Breeze`, dark preferred;
  with an empty one `Adwaita Sans 11`, `Adwaita`, light. A copy of `gtk-3.0/settings.ini` alone
  gives the dark preference only, a copy of `dconf/user` alone the font and theme only; with
  both the settings are the owner's.
- **`/dev/uinput` without root** (the user has an ACL on it): a device with `EV_ABS`
  (`ABS_X`, `ABS_Y`), `BTN_LEFT/RIGHT/MIDDLE` and bus `BUS_VIRTUAL`, set up with
  `UI_DEV_SETUP` and `UI_ABS_SETUP` and made with `UI_DEV_CREATE`, is listed by KWin as a
  pointer (`/org/kde/KWin/InputDevice/eventN`: `pointer` true, `touch` and `tabletTool` false,
  `outputName` empty, `mapToWorkspace` false). KWin maps its range onto the bounding box of all
  outputs: with `ABS_X` 0…3839 and `ABS_Y` 0…1079, value (x, y) puts the cursor at (x, y)
  (each move read back through `workspace.cursorPosChanged`, 235 of 235 per run, within 7 ms).
  KWin reports changes only: a move to where the cursor is gets no report. Wayland clients
  get real input from it: pointer events in WebKitGTK (`pointerType` `mouse`) and Dolphin's
  drag (`wl_data_device.start_drag` in `WAYLAND_DEBUG`). `UI_DEV_DESTROY` removes the device
  (gone from `/proc/bus/input/devices`).
- **Spectacle 6.8.1** `spectacle -b -n -u -S -o <file>` (window under the cursor) did not
  return within 20 s and was killed. In case it had left KWin waiting for a pick, the spike
  right-clicked once inside its own window afterwards. The spike takes no shot with Spectacle.
- **Dolphin 26.08.2** with new XDG folders (`XDG_CONFIG_HOME`, `XDG_STATE_HOME`,
  `XDG_CACHE_HOME`, `XDG_DATA_HOME`): `dolphin --new-window --select <paths>` starts a process
  of its own with the items selected; it writes `dolphinrc`, `dolphinstaterc`,
  `user-places.xbel` there and leaves `~/.config/dolphinrc` and `~/.local/state/dolphinstaterc`
  alone (mtimes before and after each run). With `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` AT-SPI
  gives each item's extents relative to the client area (below KWin's 28 px title bar); an
  item whose name is not UTF-8 is named with U+FFFD. Dolphin offers `text/uri-list`,
  `application/x-kde4-urilist`, `application/vnd.portal.filetransfer` and (not for the name
  that is not UTF-8) `application/x-kde-source-id`. Its `text/uri-list` is percent-encoded
  UTF-8, one URI per line with CRLF, in view order; for the file `bad\xffname.mkv` it sends
  `bad%EF%BF%BDname.mkv` (U+FFFD): the byte is lost in Dolphin, before any drop target. A drop
  of the selection onto its own item opened no menu (KWin added no window).
- **Tauri's drag-drop event (2.12.5, wry 0.57.0)**: wry turns each URI into a path by cutting
  `file://` and percent-decoding with `decode_utf8_lossy`; Tauri emits `tauri://drag-enter`
  (with paths) and `tauri://drag-drop` to the page, and the window event
  `WindowEvent::DragDrop` in Rust. The handler returns `true`, so WebKitGTK gets no DOM `drop`
  (the page sees `dragenter` and `dragleave`). Paths with spaces, `Ünnepi film – 2.mkv`,
  `日本語.mkv`, three files and a folder arrive byte for byte, on Wayland and XWayland alike.
- **WebKitGTK's DOM drop** (Tauri's handler off): `dataTransfer.types` is
  `["text/uri-list", "text/html"]`, `files` is empty, `getData("text/uri-list")` and
  `getData("text/plain")` are empty, `text/html` is one styled `<a>` with the URI of the first
  item only (also for three files).
- **WebKitGTK snapshot**: `webkit_web_view_get_snapshot` (`WebViewExt::snapshot`,
  `SnapshotRegion::Visible`) through Tauri's `with_webview` gives a cairo image surface of the
  CSS viewport at the device scale (1280×800 at scale 1), written with
  `ImageSurface::write_to_png`.
- **CSP in the app**: Tauri adds four `sha256-…` sources to `script-src` of the policy in
  `tauri.conf.json` and leaves `style-src 'self' 'unsafe-inline'` as it is; PrimeVue's styled
  mode works under it, `eval` is refused (`securitypolicyviolation`, `script-src`).
- **PrimeVue 4.5.5 `Tab`** is a `<button>` (`as` defaults to `BUTTON`) that takes the user
  agent's button font: WebKitGTK
  `600 13px Noto Sans`, Chromium `600 13.3333px Arial`, Firefox `600 13.3281px sans-serif`
  (headless) or `Noto Sans` (headed). Each tab, and so the tab bar, is 48 px high in
  Chromium and 51 px in WebKitGTK and Firefox.
  Headless Chromium hides scrollbars; headed Chromium draws classic 15 px ones, WebKitGTK and
  Firefox overlay ones (0 px).

### D-0 (4b-ii)

Checked on 2026-10-27 on the same set-up as 4b-i (KDE Plasma 6.8.1 on Wayland, WebKitGTK
2.54.2, Playwright 1.64.1: Chromium 156.0.8078.4, Firefox 157.0), with the frozen sidecar and
`/usr/bin/ffmpeg`. The magnifier check: `desktop/spike/MAGNIFIER.md`.

- **The preview frame route**: `POST /api/preview/frames` answers JSON with a signed URL
  (`/api/preview/frames/<key>.png?exp=…&sig=…`), not the bytes; the URL needs no token and gives
  401 without its signature. For `hdr10-4k.mkv` at 2.5 s the PNG is 3840×2160 `rgb24`
  (`ffprobe`), with `cICP` 01 01 00 01 (BT.709 primaries and transfer, full range), `cHRM` and
  `gAMA` chunks.
- **Which tone mapping a frame gets depends on timing**: with the same source and timestamp,
  six fresh sidecars used zscale + tonemap (1 169 110 bytes) and four used libplacebo
  (2 559 598 bytes), with different keys. `libplacebo` counts only after its Vulkan run test
  has passed (`CapabilitySnapshot.usable_filter`), so a frame request soon after the start
  gets zscale.
- **Frame clocks**: `performance.now()` and `requestAnimationFrame` timestamps step by 1 ms in
  WebKitGTK and Firefox and by 0.1 ms in Chromium (the smallest step in a busy loop). In the
  Tauri app on a 60 Hz output, WebKitGTK's frame callbacks come at 62.2 Hz (16.08 ms) with the
  real pointer (a full redraw on about 87 % of them) and when the page's own `setTimeout` events
  draw nothing; at 60.4 Hz only when those events lead to a redraw. Chromium, headed and
  headless, runs at 60.0 Hz. Headed Firefox misses single frames (33–34 ms) at about 0.5 %, also
  when the page draws nothing. Headless Firefox misses none.
- **The first frame interval of a run** (from the callback the run asked for to the next one)
  was 0.02 to 7 ms in 32 of 117 runs, all of them page-driven runs of Firefox or of WebKitGTK
  without the DMA-BUF renderer; why is not known. The statistics leave every run's first
  interval out.
- **`WEBKIT_DISABLE_DMABUF_RENDERER=1`** makes WebKitGTK draw the canvas on the CPU: 3.3 ms
  per redraw of the 4K bitmap scaled to 860×484 against 0.008 ms to queue (1.05 ms with a read
  back) with the default renderer. The page still holds 60 Hz.
- **Pointer events per second with the real pointer** (uinput moves at about 125 per second):
  WebKitGTK 53.7–55.0 per run with its default (DMA-BUF) renderer, fewer than its 62.2 frame
  callbacks per second (11.6 to 13.7 % of them come without a new position, so the page redraws
  53.7–55.0 times per second); 60.3–60.5 without the DMA-BUF renderer. Chromium 60.2–60.5 and
  Firefox 59.3–60.2, one per frame. Playwright's
  `page.mouse.move` reaches 60 per second in Chromium and Firefox, each call waiting for its
  frame. A `setTimeout` of 8 ms runs at about 12 ms in WebKitGTK (84 events per second).
- **Firefox fired no `pointermove` for the uinput move that brought the cursor into its
  window** (2 of 2 tries), only for later moves. WebKitGTK and Chromium fired one for that
  first move (5 of 5). Once, WebKitGTK fired none for a move 0.4 s after the entering one
  either (1 of 8 calibrations in the app), so the check tries up to four points.
- **Colour conversion in a canvas**: headless Chromium converts a PNG tagged `cICP` BT.709 to
  sRGB when it decodes it with `createImageBitmap` (a channel of 164 reads back as 159 with
  `getImageData`); with `{ colorSpaceConversion: "none" }`, or without the colour chunks, it
  reads 164. Firefox reads 164 in every case.
- **Playwright and `XDG_CACHE_HOME`**: Playwright looks for its browsers in
  `$XDG_CACHE_HOME/ms-playwright`; a temporary `XDG_CACHE_HOME` needs
  `PLAYWRIGHT_BROWSERS_PATH`. Playwright's headless Chromium is `chrome-headless-shell`
  (`chromium_headless_shell-1248`), not the headed binary.
- **Node keeps running while a timer is pending**: a Playwright script whose waits leave
  `setTimeout` timers behind does not exit until they fire, even after `browser.close()`.

### Preview frames: black bars after the display chain (M8 task C)

- The server's frames go through `scale=flags=bicubic+accurate_rnd+full_chroma_int,format=rgb24`.
  Its bicubic chroma upsampling rings into the black rows next to the picture. On `letterbox`
  (pinned FFmpeg n9.0.2) the BT.709 luma variance of the bars is up to 6.1 per band (22-row top,
  24-row bottom) and 2.0–4.1 for the 40-column pillarbox bars. A plain `format=rgb24` gives at
  most 0.46. `CropCheckGrid`'s threshold (64) is set from the first numbers (decision 0067
  "Task C").

### Custom parameters over advanced options (M9 fix round, task FC)

Pinned FFmpeg n9.0.2 (x264 core 165, x265 4.3+49), `testsrc2` 320×240, 3 frames, read back from
the stream's encoder settings SEI:

- The custom parameters come after the advanced options in the command, and the last value
  wins: `-x265-params psy-rd=1.5:psy-rd=0.75` writes `psy-rd=0.75`; `-g:v:0 10 … -g:v:0 50`
  (a generic option) writes `keyint=50`, `-aq-mode:v:0 1 … -aq-mode:v:0 2` (a private option)
  `aq=2:1.00`. So a custom parameter that sets an option overrides the panel's value
  (`encoder.custom_param_overrides`), with a params argument and without one.
- x265 reads `psy_rd=0.5` as `psy-rd=0.50` and `no-rect=1` as `no-rect`, the key forms
  `library_key_forms` gives.
- x264 reads `b-pyramid=0` as `b-pyramid=none` (`b_pyramid=0` in the SEI; `normal` is 2): it
  takes a choice's name or its index. The built-in *Social 25 MB* preset stores HandBrake's
  `b-pyramid=0` as the option's `none`.
- Every x264 and x265 built-in preset writes the same settings SEI with its options in
  `advanced` as with HandBrake's `VideoOptionExtra` string as custom parameters
  (`tests/presets/test_builtin.py`). SVT-AV1 writes no such SEI; its params argument is the same
  key by key. `keyint=10s` (seconds) stays a custom parameter: the keyint option is a number of
  frames.

### Windows: paths, processes and file behaviour (Q-1.4)

Windows 10 22H2 (VM), Python 3.14.10, FFmpeg n9.0.2 (BtbN win64, `reframe tools fetch`),
2026-11-04:

- `-x264-params` / `-x265-params` with a Windows path: FFmpeg's dictionary parser splits
  `key=C:\dir\f` at the drive colon, and the rest (`\dir\f`, also `/dir/f`) is a key without
  `=`, so FFmpeg refuses the whole argument (`Error setting option x265-params`) and nothing is
  written. `key=C\:\dir\f` gives the library `C:dirf` (each `\` removed): x265 `csv` and x264
  `dump-yuv` write that drive-relative name in the working folder. `key=C\:\\dir\\f`,
  `key='C:\dir\f'` and `key=C\:/dir/f` give the library `C:\dir\f`, and the file is written.
  Reframe refuses these keys by name, whatever the value.
- The builder's two-pass x265 plan (`stats=C\:/…/x.part.passlog`) encodes on Windows.
- Filter text `eq=/contrast=C:\dir\secret.txt` (also with `/`, or `C\:`) is a graph syntax
  error. Written as one graph token, `'C\:/dir/secret.txt'` (`quote_value`) or `C\\\:/dir/…`,
  the file is read: its text is in FFmpeg's error. The same holds for `eq='/contrast'=…`,
  `eq=brightness=0\: /contrast=…` and `unsharp=5:5:/lx=…`.
- The Windows build's `h264_qsv` has the private options `dual_gfx` and `vcm`, and `hevc_qsv`
  has `dual_gfx`; the Linux builds have neither.
- `os.stat()` on NTFS: `st_ctime_ns` is the creation time (equal to `st_birthtime_ns`). A
  rewrite of the same size followed by `os.utime` back to the old times changes no field but
  `st_atime`. `FILE_BASIC_INFO.ChangeTime` (`GetFileInformationByHandleEx`) moves on each write
  and on `os.utime`, but in clock ticks: writes less than one tick apart (1 ms on the VM, 15.6 ms
  by default) can share it. Reading it takes about as long as `os.stat` (16 µs and 23 µs).
- A path with a NUL: `os.path.realpath` and `Path.resolve` give it back (`ntpath` ignores the
  error unless `strict=True`, which raises `OSError`); `os.stat`, `open` and the others raise
  `ValueError` as on Linux.
- `os.stat` takes `..` out of a path before it looks at the folders: `C:\t\missing\..\a.mkv`
  is `C:\t\a.mkv` when `missing` does not exist.
- A file name `a:b` is the NTFS stream `b` of the file `a`: `shutil.copy` writes it and
  FFmpeg's `subtitles` filter reads it.
- `os.open` (and `open`) of a folder raises `PermissionError` (EACCES), not
  `IsADirectoryError`.
- `os.replace` cannot replace a symbolic link to a folder (`PermissionError`, WinError 5); the
  VM's account can create symbolic links.
- uv's `.venv\Scripts\python.exe` is a launcher: it starts the real interpreter as a child
  process (another pid), passes the exit code through (`SystemExit(75)` gives 75), and a kill of
  the launcher ends the child, also when it was started with `launch_detached`'s flags.
- A tool that crashes with an access violation exits with `0xC0000005` (positive, as an
  NTSTATUS code), not with a negative signal number. FFmpeg's own error exit is its negative
  `AVERROR` as an unsigned 32-bit code: an AAC encode of a silent track shorter than 3 s with
  loudness normalisation (`EINVAL`, -22) exits with `0xFFFFFFEA` (on Linux 234). FFmpeg's tag
  codes reach above `0xC0000000` too (`AVERROR_EOF` is `0xDFB9B0BB`), but none has the form of
  a system exception, `0xC000xxxx`.
- A just-renamed or just-deleted file can refuse to open for a moment (`PermissionError`): the
  fake tools' call log needed a retry when read while files came and went.
- FFmpeg's Matroska muxer, writing a seekable file, takes time quadratic in the number of
  subtitle packets on Windows (50 / 100 / 200 loops of the fixture: 0.34 / 3.6 / 16 s); with
  `-live 1`, or to a pipe or null output, it is linear (200 loops: 0.25 s). On Linux the 1800
  loops take 2.6 s.
- pydantic-core dumps at most 100 nested levels on Windows (256 on Linux).

### The sidecar build and its packages (M5 task A)

PyInstaller 6.22.3 (hooks-contrib 2026.9, Python 3.14.8), Tauri CLI 2.12.4 and tauri-build 2.7.4:

- A spec with two `Analysis` / `EXE(exclude_binaries=True)` and one `COLLECT` makes one onedir
  with both executables and one `_internal/`. Each executable is about 15.6–15.9 MB: it carries
  its own archive of pure-Python modules.
- The frozen executable started through a symbolic link gets the link's target as
  `sys.executable`: `reframe queue pause --all` run as `…/bin/reframe` → `…/sidecar/reframe`
  started `…/sidecar/reframe-server --mode desktop --host 127.0.0.1 --port 0 --owner-only
  --idle-exit 30`.
- tauri-build refuses a `bundle.resources` folder that does not exist (`resource path
  `resources/sidecar` doesn't exist`) and a glob that matches nothing; a folder that holds one
  file is fine. It copies the resources into `$CARGO_TARGET_DIR/<profile>/` and leaves them there.
- `bundle.linux.deb.files` copies the file a link points to: a link in the source tree whose
  target does not exist fails the bundle (`Failed to copy custom files: "linux/reframe-link"
  does not exist`). So a package cannot ship `/usr/bin/reframe` as a link; its install script
  makes it.
- The `.deb` and `.rpm` put `bundle.resources` in `/usr/lib/<productName>/` (here
  `/usr/lib/Reframe/sidecar/…`); the desktop entry is `/usr/share/applications/Reframe.desktop`
  with `StartupWMClass=reframe-desktop`; the package name is `reframe`.
  `postInstallScript` / `preRemoveScript` become the `.deb`'s `postinst` / `prerm` and the
  `.rpm`'s `POSTIN` / `PREUN` header tags.
