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
  `hdr10-4k`; 0.1 s when everything is up to date. About 13 MB in total (6 MB of it is
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
build; x264 core 165, x265 4.1, SVT-AV1 v4.2.0) and, for AMF and VAAPI, an AMD RX 7600. The
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
  uses (C-3).

### Audio and subtitle defaults (C-12, selection stage)

(core-complete wave 1a: what the selection stage relies on.)

### Analysis scans (C-10: bitrate, subtitles, loudness)

(core-complete wave 1b: packet sizes, event counts, `forced_subs_only`, `loudnorm`, the new
fixtures.)

### Preview frames, crop detection and clips (C-10)

(core-complete wave 1c: fast seek, HDR frames for display, `cropdetect` limits, timing.)

### Metadata edit (C-13)

(core-complete wave 1d: mkvpropedit in place, what FFmpeg does not write, the re-probe.)

### Advanced encoder options (C-6, complete option sets)

(core-complete wave 1e: option names and ranges checked with the encoders, the dry run.)

### Power actions (C-14)

(core-complete wave 1f: the commands and what they do; checked without running them.)

### When-done actions (C-11)

Nothing to record: the queue's when-done actions run no tool. They call C-14's power service
(its OS calls are under "Power actions (C-14)") and the notification hook
([decision 0037](../docs/decisions/0037-when-done-power-actions-and-job-notifications.md)).

### Tools fetch and the CLI (C-15)

(core-complete wave 1h.)

### Batch engine (C-12, M7)

(core-complete wave 2: the season fixture of 04 §Example.)
