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

The `c4_*` captures in `fake_data/` are exactly these commands
(`capture_fake_data.py --only c4_…`; `test_hwtest.py` fails when the definitions change the
command and the captures were not made again):

| Capture | Exit code | Key stderr line | C-4 reason (state) |
|---------|-----------|-----------------|--------------------|
| `c4_h264_vaapi_ok`, `c4_hevc_vaapi_10bit_ok`, `c4_hevc_amf_ok`, `c4_hevc_amf_10bit_ok` | 0 | — | available |
| `c4_hevc_nvenc_no_driver` | 255 | `[hevc_nvenc @ 0x…] Cannot load libcuda.so.1` | NVIDIA driver not found |
| `c4_hevc_qsv_no_device` | 187 | `Failed to set value 'qsv=hw' for option 'init_hw_device': Generic error in an external library` (no device line) | No Intel QSV device (needs an Intel GPU with its media driver) |
| `c4_h264_vaapi_bad_device` (`renderD999`) | 234 | `[VAAPI @ 0x…] No VA display found for device /dev/dri/renderD999.` | No VAAPI device (/dev/dri/renderD999) |
| `c4_h264_vaapi_no_driver` (`LIBVA_DRIVER_NAME=reframe_nonexistent`) | 251 | `[VAAPI @ 0x…] Failed to initialise VAAPI connection: -1 (unknown libva error).` | VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error) |
| `c4_hevc_amf_no_runtime` | 171 | `[AMF @ 0x…] DLL libamfrt64.so.1 failed to open`, then `[hevc_amf @ 0x…] Failed to create  hardware device context (AMF) : Unknown error occurred` | AMD AMF runtime not found (libamfrt64.so.1) |
| `c4_h264_amf_10bit` (`-pix_fmt p010le -c:v h264_amf`) | 183 | `[h264_amf @ 0x…] 10-bit input video is not supported by AMF H264 encoder` | 10-bit is not supported by this encoder |

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
  are the `c4_libplacebo_*` captures):

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
build; x264 core 165, x265 4.1, SVT-AV1 v4.2.0) and, for AMF and VAAPI, an AMD RX 7600.
`packages/reframe/tests/definitions/test_tools.py` repeats every check (`needs_ffmpeg`; the
AMF / VAAPI encodes are `needs_gpu`), so a different build shows up as a test failure:

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

**Hardware rate control (AMF, VAAPI on radeonsi).** Every preset, profile, level, the quality
mode at min / default / max, average bitrate and every option encode:

| Encoder | Quality mode (as in the definitions) | Notes |
|---------|------------------|-------|
| `h264_amf`, `av1_amf` | `-rc cqp -qp_i Q -qp_p Q+2 -qp_b Q+4` (AV1: +8 / +16, range 0–255) | HandBrake's offsets. `hevc_amf` has no `-qp_b` |
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
`ActiveInhibitions` (`busctl --json=short`), and checks a global flag only when it was false
before.

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

Windows (`SetThreadExecutionState`) is not checked on a real machine: the values and the
"return value is NULL on failure" rule are from
<https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate>
(`ES_CONTINUOUS` 0x80000000, `ES_SYSTEM_REQUIRED` 0x00000001; "cannot be used to prevent the
user from putting the computer to sleep").

### Command builder (C-7)

Nothing recorded yet.

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
