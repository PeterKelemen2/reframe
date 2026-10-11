# testdata

Test data for Reframe. Nothing in `media/` is committed: it is generated.

| Path | Committed | What |
|------|-----------|------|
| `media/` | no (git-ignored) | Generated fixture media (`scripts/make-testdata.py`) |
| `names.toml` | yes (later, `C-16`) | File-name corpus for guessit / output naming |
| `probes/` | yes (later, `Q-2.2`) | Recorded real-world ffprobe JSON |

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
  fixtures (cold, idle machine; 3.3 s under heavy load), 0.1 s when everything is up to date.
  About 7 MB in total.
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
| `chapters` | `chapters.mkv` | 5 s, 4 chapters (Opening, Part One, Part Two, Credits) and a title, from an FFMETADATA file |
| `season` | `season/Show.S01E01.Title.mkv` … `E12` | 12 copies of the multi-track layout (title `Show - S01Enn`). **E05** has an extra `eng` AC-3 2.0 "Commentary" (comment) as the 4th audio track. **E09** has no second audio track ("English Stereo") |

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

### FFmpeg 9 prints "Exiting with exit code 0" on stdout

After `ffmpeg -version` and `ffmpeg -h …` (also `-h encoder=<name>`), FFmpeg n9.0.2 prints an
empty line and `Exiting with exit code 0` **to stdout**. `-encoders`, `-filters`,
`-hwaccels` and `ffprobe -version` do not (both builds; see the files in
`testing/reframe_testing/fake_data/`):

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
`test_fake_ffmpeg.py::test_library_strings_confirm_the_c4_texts`). Command:

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

