# Recorded ffprobe JSON (Q-2.2, C-3)

The input of the `MediaSource` snapshot tests (`packages/reframe/tests/probe/test_snapshots.py`).
Everything here is made by one script with the **pinned build**
(`ffprobe version n9.0.2-17-g2a571b6068-20260930`, `tools/ffmpeg.toml`) and
`mkvpropedit v101.0`:

```sh
BIN=$(uv run --no-project python scripts/fetch-tools.py --platform linux-x64 | tail -n 1)
uv run python testdata/probes/record_probes.py --bin "$BIN"              # everything
uv run python testdata/probes/record_probes.py --bin "$BIN" --only pgs   # one recorded probe
uv run python testdata/probes/record_probes.py --bin "$BIN" --fixtures   # fixtures/ only
uv run python testdata/probes/record_probes.py --bin "$BIN" --strings    # confirmed_strings.json only
uv run pytest packages/reframe/tests/probe/test_snapshots.py --snapshot-update   # then review
```

| Path | What |
|------|------|
| `<name>.json` | ffprobe output of Reframe's probe command (`reframe.probe.probe_argv`: `-v error -of json -show_format -show_streams -show_chapters -show_programs`) |
| `<name>.frames.json` | The first frames of the main video stream (`reframe.probe.frames_argv`), recorded when Reframe would read them (HDR). The files recorded before the M1 review fix used `-read_intervals %+#1` (one packet); the command now reads `%+#5`, of which one frame is a subset, so the snapshots are unchanged |
| `fixtures/<file>.json` | The same for every generated fixture file (`reframe_testing.media`), so the snapshots do not depend on the FFmpeg that runs the tests |
| `index.json` | For each recorded probe: file name, description, the exact FFmpeg / mkvpropedit commands, `synthesised`, and **every edit** (stream, field, old value, new value, why) |
| `confirmed_strings.json` | Byte search: every ffprobe string that `reframe.probe` matches on, and the files of the pinned build and of this machine's FFmpeg that contain it |
| `record_probes.py` | The script |
| `real/<name>.json`, `real/<name>.tracks.mkv` | Two real mkvmerge files, anonymised (below): ffprobe's JSON and a Matroska file of the track headers only. The snapshot tests parse the JSON with those headers, as the prober does |
| `real/record_real.py` | The script for them |

## Real files: `real/`

Recorded on 2026-11-15 from two of the owner's files (read only) with the pinned ffprobe and
`real/record_real.py`. They are the two mkvmerge files of decision 0081 whose tracks'
`NUMBER_OF_BYTES` add up to more than the file, because mkvmerge counts its zlib-compressed PGS
tracks before compression (`testdata/README.md`, "Sampled bit rates").

| Name | Writing application | Layout |
|------|---------------------|--------|
| `mkvmerge15-episode-pgs` | mkvmerge v15.0.0 | HEVC Main 10 1080p; 2 × AAC 2.0; 2 × PGS (compressed); 24 min |
| `mkvmerge93-remux-pgs` | mkvmerge v93.0 | H.264 High 1080p; AC-3 5.1, DTS-HD MA 5.1, AC-3 5.1; SRT; PGS (compressed); 100 min |

Anonymised: `format.filename` is the name above; every `title`, `comment`, `description`,
`filename` and `handler_name` tag is removed; `creation_time` and
`_STATISTICS_WRITING_DATE_UTC` are a neutral date; chapter IDs are 1, 2, … and chapter titles
`Chapter NN`. The `.tracks.mkv` holds the EBML header, a Segment of unknown size, `Info` with
`TimestampScale`, `Duration`, `MuxingApp` and `WritingApp` only, and `Tracks` with the
elements the probe reads (no `Name`, no `CodecPrivate`; the track UIDs are 1, 2, …). The numbers
(sizes, durations, statistics tags) are the real ones.

```sh
uv run python testdata/probes/real/record_real.py --ffprobe "$BIN/ffprobe" NAME FILE
```

The JSON is written with `json.dumps(indent=4)` (ffprobe's own layout differs only in
whitespace). File names are anonymised: each file is generated under a neutral name and probed
by that relative name, so `format.filename` is for example `movie-truehd-atmos.mkv` and no
local path is recorded.

## Real-world probes: synthesised from real output

There are no real TrueHD Atmos, DTS:X, PGS or Dolby Vision files on the development machine,
and personal media must not be used. So each "real-world" probe is the **real ffprobe output
of the closest file that FFmpeg can make**, in the layout of a typical release, with real
mkvmerge statistics tags (`mkvpropedit --add-track-statistics-tags`: `BPS`, `DURATION`,
`NUMBER_OF_FRAMES`, `NUMBER_OF_BYTES`, `_STATISTICS_*`). Only the fields that FFmpeg cannot
generate were then edited. Files with edits are **synthesised from real output**
(`"synthesised": true` in `index.json`). Replace them with true recordings when such files are
available (keep the name; the snapshot diff then shows what changed).

| Probe | File | Layout | Synthesised | Edits (all in `index.json`) |
|-------|------|--------|-------------|-------------------------------|
| `truehd-atmos` | `movie-truehd-atmos.mkv` | H.264 1080p; TrueHD 5.1(side) 24-bit (default); AC-3 5.1 640k; AC-3 2.0 192k "Director's Commentary" (title, no flag) | yes | stream 1 `profile` added: `Dolby TrueHD + Dolby Atmos` |
| `dts-hd-ma` | `movie-dts-hd-ma.mkv` | H.264 1080p; DTS 5.1 (default); AC-3 2.0 192k eng without title or flag; SRT | yes | stream 1: `profile` `DTS` → `DTS-HD MA`, `sample_fmt` `fltp` → `s32p`, `bits_per_raw_sample` `24` added, `bit_rate` `1411200` removed |
| `dts-x` | `movie-dts-x.mkv` | H.264 1080p; DTS 5.1 eng (default); AC-3 5.1 ger | yes | as `dts-hd-ma`, `profile` → `DTS-HD MA + DTS:X` |
| `eac3-atmos` | `show-eac3-atmos.mkv` | H.264 1080p; E-AC-3 5.1 640k; SRT "English", "English [SDH]", "English [Forced]" | yes | stream 1 `profile` added: `Dolby Digital Plus + Dolby Atmos` |
| `pgs` | `movie-pgs.mkv` | H.264 1080p; AC-3 5.1; four bitmap tracks: eng "English" default (8 events), eng untitled (1 event), eng "English SDH" `hearing_impaired` (9), hun (8) | yes | streams 2–5: `codec_name` `dvd_subtitle` → `hdmv_pgs_subtitle`, `codec_long_name` `DVD subtitles` → `HDMV Presentation Graphic Stream subtitles`, `width`/`height` 720×480 → 1920×1080, `extradata_size` removed |
| `ass-fonts` | `anime-ass-fonts.mkv` | H.264 1080p; FLAC 2.0 jpn (default); AAC 2.0 eng; ASS "Signs & Songs" (2 events, no flags); ASS "Full Subtitles" (8, default); attachments `ReframeBox.ttf` (`application/x-truetype-font`) and `ReframeBox-Alt.ttf` (`font/ttf`); 2 chapters | no | — |
| `vfr` | `phone-vfr.mkv` | 1 s each at 24, 30, 60 fps (H.264 720p), AAC | no | — |
| `dvd-interlaced` | `dvd-title-interlaced.mkv` | MPEG-2 720×480 29.97i TFF, SAR 32:27; AC-3 2.0 eng + fre; VobSub eng + fre; 2 chapters | no | — |
| `dvd-interlaced-vob` | `dvd-title-interlaced.vob` | The same title as MPEG-PS (`-f vob`): stream ids and start offsets, no tags | no | — |
| `hdr10` | `movie-hdr10-2160p.mkv` | HEVC Main 10 3840×2160 BT.2020/PQ, mastering display + MaxCLL/MaxFALL as stream side data (two libx265 passes, as the `hdr10` fixture); E-AC-3 5.1 | no | — |
| `hdr10-sei-only` | `movie-hdr10-sei.mkv` | One libx265 pass: PQ colour tags, HDR10 metadata only in SEI (frame side data) | no | — |
| `dv-p8` | `movie-dv-p8.mkv` | The HDR10 stream (1080p) + a DOVI configuration record, profile 8.1 | yes | stream 0 `side_data_list`: `DOVI configuration record` appended (`dv_profile` 8, `dv_level` 4, `rpu_present_flag` 1, `el_present_flag` 0, `bl_present_flag` 1, `dv_bl_signal_compatibility_id` 1, `dv_md_compression` 0) |
| `hlg` | `broadcast-hlg.mkv` | HEVC Main 10 1080p50 BT.2020 / `arib-std-b67`, AAC | no | — |
| `cover-art` | `song-cover.m4a` | AAC + PNG cover (`attached_pic`) | no | — |
| `mkvmerge-vfr` | `phone-vfr-mkvmerge.mkv` | The VFR clip (24 / 30 / 60 fps) as MP4, remuxed by **mkvmerge** (`mkvmerge -o … source.mp4`): `r_frame_rate = avg_frame_rate = 29999/500` from `DefaultDuration`; mkvmerge's own statistics tags (114 frames, 3.01 s) | no | — |
| `stale-stats` | `movie-stale-stats.mkv` | A 29.97 fps clip muxed by mkvmerge, then re-encoded by FFmpeg at 200 kb/s: the **stale** statistics tags of the source stay (`BPS` 9582197, `NUMBER_OF_BYTES` 2397945 in an 85 344-byte file) | no | — |
| `phone-rotated` | `phone-rotated.mov` | H.264 1280×720 with a display matrix (`-display_rotation -90`, i.e. 90° clockwise), AAC, QuickTime timecode (`tmcd`) data stream, `creation_time` | no | — |

### Why each edit is what a real file would show

- **TrueHD Atmos.** FFmpeg's `truehd` encoder (experimental, `-strict -2`) writes at most 5.1
  and no 16-channel Atmos substream. FFmpeg's `mlpdec.c` `read_major_sync()` sets
  `AV_PROFILE_TRUEHD_ATMOS` when there are 4 substreams and the top bit of `substream_info` is
  set, and changes nothing else (TrueHD has no `bit_rate`, so the stats tag gives it).
  Profile string confirmed in `libavcodec`.
- **DTS-HD MA / DTS:X.** The `dca` encoder writes a DTS core only (ffprobe: `profile` `DTS`,
  `fltp`, `bit_rate` 1411200). For a lossless (XLL) stream FFmpeg's `dca_xll.c`
  `ff_dca_xll_filter_frame()` sets the profile (`AV_PROFILE_DTS_HD_MA`, `…_MA_X`,
  `…_MA_X_IMAX`), `sample_fmt` `S32P` for 24-bit storage, `bits_per_raw_sample =
  storage_bit_res` (24) and `bit_rate = 0`, which ffprobe leaves out of JSON (checked in the
  FFmpeg n8.1 source). The `BPS` tag is the real value of the generated core.
- **E-AC-3 Atmos.** The `eac3` encoder cannot write JOC metadata; `ac3dec.c` sets
  `AV_PROFILE_EAC3_DDP_ATMOS` for a JOC stream. Nothing else changes.
- **PGS.** FFmpeg has no PGS encoder (and cannot convert text to bitmap subtitles,
  testdata/README.md). The tracks are VobSub bitmaps (`reframe_testing.vobsub`, encoded with
  `dvdsub`) re-labelled with the PGS decoder's names (both confirmed in `libavcodec`), the
  Blu-ray canvas, and no `extradata_size` (Matroska `S_HDMV/PGS` has no CodecPrivate; VobSub
  keeps its palette there). Event counts and `BPS` are the real values of the generated tracks.
- **Dolby Vision 8.1.** libx265 with `-dolbyvision 1` needs Dolby Vision metadata on every
  input frame (`Dolby Vision enabled, but received frame without AV_FRAME_DATA_DOVI_METADATA`),
  so a DV stream cannot be made from scratch. The appended entry has the side-data type from
  `libavcodec` and the field names in the order they appear in `bin/ffprobe`
  (`dv_version_major` … `dv_md_compression`).

## Facts found while recording

Checked with the pinned build on 2026-10-11 (most are asserted in
`packages/reframe/tests/probe/test_recorded_probes.py`):

- **MPEG-2 field order differs by container.** The same interlaced TFF MPEG-2 stream is
  `field_order=tb` in Matroska and `tt` in MPEG-PS.
- **VOB start offsets.** In the MPEG-PS file, video starts at 0.533367 s and audio at
  0.528033 s (`format.start_time` 0.528033): real stream start offsets for the audio delay.
- **`font/ttf` attachments get no `codec_name`.** ffprobe maps the Matroska attachment
  `application/x-truetype-font` to `ttf`, but prints no `codec_name` for `font/ttf`.
- **mkvpropedit v101.0 writes the statistics tags without a language suffix** (`BPS`, not
  `BPS-eng`), and replaces FFmpeg's `DURATION` tag with its own value.
- **Display matrix sign.** `-display_rotation -90` gives `"rotation": -90` in ffprobe: the
  value is counter-clockwise, so the picture must be turned 90° clockwise. `-noautorotate` is
  needed, otherwise FFmpeg rotates the pixels and writes no matrix.
- **`-dolbyvision 1` in libx265 also needs VBV** (`Dolby Vision requires VBV settings to
  enable HRD`), before it fails on the missing frame metadata.
- **mkvmerge and VFR.** For a Matroska file written by mkvmerge, ffprobe takes both
  `r_frame_rate` and `avg_frame_rate` from `DefaultDuration`, so a VFR source looks CFR
  (`29999/500`). The statistics tags (`NUMBER_OF_FRAMES` / `DURATION`) or MediaInfo
  (`FrameRate_Mode` VFR, 37.886 fps) show the truth. mkvmerge also starts the video at
  0.021 s here (audio delay −21 ms).
- **FFmpeg keeps stale statistics tags.** Re-encoding with FFmpeg copies the stream tags,
  `BPS` and `NUMBER_OF_BYTES` included, and replaces only `DURATION`.
- **The container `ENCODER` tag does not name the writer.** mkvmerge copies a source's global
  `ENCODER=Lavf…` tag (seen in the review's `mm-cfr.mkv`), so it cannot tell an FFmpeg file
  from an mkvmerge file.
- **Inherited `default` flags.** Each `.idx` input brings a `default` disposition into the
  output unless `-disposition:s:N 0` clears it.

## Confirmed strings

`confirmed_strings.json` lists, for each string, where it is a NUL-terminated C string
(`standalone`, or `suffix`: the tail of a longer string after linker string merging). Searched
files: the pinned build's `lib/libavcodec.so.63.1.102`, `lib/libavutil.so.61.1.102`,
`bin/ffprobe`, and this machine's (Arch Linux n9.0.2) `/usr/lib/libavcodec.so.63.1.102`,
`/usr/lib/libavutil.so.61.1.102`, `/usr/bin/ffprobe`. Every string was found in both.

| Group | Strings |
|-------|---------|
| AAC profiles | `LC`, `HE-AAC`, `HE-AACv2`, `LD`, `ELD`, `Main`, `SSR`, `LTP`, `xHE-AAC` |
| DTS profiles | `DTS`, `DTS-ES`, `DTS 96/24`, `DTS-HD HRA`, `DTS-HD MA`, `DTS-HD MA + DTS:X`, `DTS-HD MA + DTS:X IMAX`, `DTS Express` |
| E-AC-3 / TrueHD | `Dolby Digital Plus + Dolby Atmos`, `Dolby TrueHD + Dolby Atmos` |
| Video profiles | `Constrained Baseline`, `Baseline`, `Main`, `High`, `High 10`, `High 4:2:2`, `High 4:4:4 Predictive`, `Main 10`, `Main Still Picture`, `Rext`, `Professional`, `Profile 0`, `Profile 2`, `Simple`, `4:2:2`, `HQ` |
| Codec names | `hdmv_pgs_subtitle`, `dvd_subtitle`, `dvb_subtitle`, `subrip`, `ass`, `webvtt`, `mov_text`, `truehd`, `eac3`, `ac3`, `dts`, `aac`, `flac`, `opus`, `pcm_s24le`, `pcm_bluray`, `h264`, `hevc`, `av1`, `vp9`, `mpeg2video`, `ttf`, `otf` |
| Long names | `HDMV Presentation Graphic Stream subtitles`, `DVD subtitles` |
| Side data | `Mastering display metadata`, `Content light level metadata`, `DOVI configuration record`, `HDR Dynamic Metadata SMPTE2094-40 (HDR10+)` (frame, libavutil), `HDR10+ Dynamic Metadata (SMPTE 2094-40)` (packet, libavcodec), `Display Matrix` |
| ffprobe fields | `side_data_type`, `red_x`, `white_point_x`, `min_luminance`, `max_luminance`, `max_content`, `max_average`, `dv_version_major`, `dv_version_minor`, `dv_profile`, `dv_level`, `rpu_present_flag`, `el_present_flag`, `bl_present_flag`, `dv_bl_signal_compatibility_id`, `dv_md_compression`, `rotation`, `field_order`, `closed_captions` |

Not found anywhere (so Reframe does not match on them): `E-AC-3 JOC` and `Dolby Digital Plus`
alone are not ffprobe profile strings. Reframe shows `E-AC-3 Atmos` (05 C-3).
