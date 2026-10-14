# 0013 — Command builder: argument details, burn-in placement, HDR metadata, audio layouts, loudnorm, frame rate

- Status: accepted
- Date: 2026-10-13
- Steps: C-7 (affects C-8, C-11, C-15)

## Context

05 §C-7 gives the argument order, the filter graph builder, and what each track type writes.
Building it against FFmpeg n9.0.2 (the Arch package and the pinned BtbN build) showed places
where the plan's sketch does not produce correct files, or where it does not decide. Every
behaviour below is recorded with its command and output in `testdata/README.md` §Command
builder (C-7) and repeated by `packages/reframe/tests/command/test_integration.py`.

1. **Range end and chapters.** With `-t` as an input option, FFmpeg shifts the copied
   chapters by the seek but does not cut them: a 2 s output kept a chapter from 2.8 s to
   3.8 s. Only an output `-t` (the output's recording time) cuts them.
2. **Stream tags.** FFmpeg copies every source stream tag into the output, also into an
   encoded stream: the mkvmerge statistics (`BPS`, `NUMBER_OF_FRAMES`, …) of the source
   become false (the recorded `stale-stats` probe shows the result). It also copies the
   source's dispositions.
3. **HDR → SDR.** After `libplacebo` or `zscale,tonemap` the output is BT.709 SDR, but the
   source's mastering display and content light level stay in the frames' side data, and
   x264 / x265 write them into the SDR stream (SEI) and the container.
4. **Burn-in placement.** The plan's filter order has no place for burned subtitles.
   FFmpeg's `subtitles` filter reads its file from the start, while `-ss` starts the frames
   at 0, so a burn-in with a range is out of sync without a correction. A bitmap subtitle
   canvas covers the source picture; HandBrake moves each subtitle that falls outside the
   crop into the picture, which FFmpeg's `overlay` cannot do per event.
5. **Audio layouts.** libopus refuses `5.1(side)`, the layout that FFmpeg's AC-3, DTS and
   TrueHD decoders give ("Invalid channel layout 5.1(side) for specified mapping family
   -1"), so "keep the source layout" fails for the commonest surround sources. `loudnorm`
   outputs 192 kHz (an AAC track became 96 kHz without `-ar`).
6. **Two-pass loudnorm.** Several `loudnorm` filters in one run print their JSON blocks in
   no usable order (the second output's block came first) and the log prefix
   (`[Parsed_loudnorm_0 @ …]`) is local to each graph, so the blocks cannot be matched to
   tracks. The plan sets only the integrated loudness (−23 / −16 LUFS).
7. **Frame rate.** FFmpeg has no HandBrake-style peak frame rate: `-fpsmax R` with the
   default mode gives a constant R for a VFR source, and `-fps_mode vfr` with `-r` or
   `-fpsmax` is refused ("This is contradictory"). `-fps_mode cfr` without `-r` uses
   `r_frame_rate` (120 fps for the VFR fixture whose average is 38).
8. **Smaller points the plan does not settle**: the `.m4v` extension selects FFmpeg's `ipod`
   muxer (it refuses Opus); TrueHD in MP4 needs a plain `-strict -2` (`-strict:a:0 -2` does
   not reach the muxer); FFmpeg never writes Matroska `LanguageIETF`; a `FilterConfig()`
   says preset `default`, which Denoise, Deblock, Sharpen, Chroma smooth and Colorspace do
   not have (C-6 gives each implementation a `default_preset`); FFmpeg's AC-3 decoder
   applies DRC by default (`drc_scale` 1), HandBrake's DRC 0 means off; the 2-pass
   statistics files must be removed by somebody.

## Decision

### 1. Argument order additions

The order of 05 §C-7 stays, with these additions (`reframe/command/builder.py`):

- **Input options of the source**: decoder options before the seek, `-drc_scale:<index>`
  (DRC, below) and `-forced_subs_only:<index> 1` (bitmap burn-in, forced only).
- **The range**: `-ss` as an input option of the source (and of each external subtitle
  file, whose timestamps the source's seek does not move), the end as an **output** `-t`
  right after the maps. A frame range is converted to time with the source's average
  frame rate (frame-exact at CFR, checked).
- **Metadata section**: `-map_metadata:s -1` (no source stream tags), then
  `-map_metadata:s:t:N 0:s:t:N` for each copied attachment (the Matroska muxer needs their
  `filename`), then each track's `language`, `title` (when it has one) and **every**
  disposition (`0` for none).
- **Global tags**: `-map_metadata 0` (passthru) or `-map_metadata:g -1`, then the tags.
  `-map_metadata -1` is not used: it also drops the chapter titles.
- **Container flags**: `+faststart`, and the container's `copy_args` once, without a stream
  specifier (`-strict -2`).
- **Output**: `-f <muxer>` always (a `.part.m4v` output is MP4, not `ipod`).

### 2. Burn-in

- **Text** (`subtitles=`) is rendered last, after grayscale and before the format / upload
  stage: on the final picture, never cropped away, not denoised or sharpened, in SDR colours
  after tone mapping. With a range, `setpts=PTS+S/TB` before and `setpts=PTS-S/TB` after the
  filter keep the subtitle timing (`S` = range start − the external file's offset; checked:
  ranged frames equal the full burn-in's frames shifted by S, lossless).
- **Bitmap** (`overlay` in `-filter_complex`) right after the crop, before the rotation:
  the canvas covers the source picture. When the crop removes lines, the canvas is aligned
  with the **bottom** of the cropped picture (`overlay=x=-left:y=-(top+bottom)`): subtitles
  in a bottom letterbox bar move into the picture instead of being cropped away; subtitles in
  a top bar can be lost. A canvas of another size is scaled to the picture first.
- Filter argument escaping: the value is escaped for the option parser (`\` before
  `\ ' :`) and quoted for the graph parser (`'…'`), the documented form
  (`subtitles=filename='C\:/Movies/a.srt'`); Windows paths use forward slashes.

### 3. Colour and HDR

- **Colour tagging**: before an implementation that needs tagged input (`zscale`),
  `setparams` fills in what the source does not say (HDR: BT.2020 PQ or HLG; up to 480
  lines BT.601 NTSC; up to 576 lines BT.601 PAL; else BT.709).
- **HDR side data removed**: after tone mapping, or after a colour conversion of an HDR
  source, `sidedata=mode=delete` removes the mastering display, content light level,
  HDR10+, Dolby Vision RPU / metadata and HDR Vivid side data.
- **Tone mapping of an SDR source** is left out (it would only darken the picture).
- **HDR kept** (an HDR source, no tone mapping or colour conversion, 10-bit): the probe's
  colour and HDR10 metadata go into the params of x265 (`colorprim`, `transfer`,
  `colormatrix`, `master-display`, `max-cll`), SVT-AV1 (`color-primaries`,
  `transfer-characteristics`, `matrix-coefficients` in SVT's names, `mastering-display`,
  `content-light`) and x264 (colour only); an advanced option of the same name wins.
  Hardware encoders get the metadata from the frames (checked for VAAPI and AMF).
- A filter preset `default` that the implementation does not have means the
  implementation's `default_preset`.

### 4. Audio

- **Layout**: a chosen mixdown is written as `aresample=[matrix_encoding=dplii:]
  out_chlayout=<layout>` in the track's filter (so `loudnorm` measures what is encoded).
  Without a mixdown, the layout of the effective mixdown (source channels, limited by the
  encoder) is written when the source has more channels than it, or the same number with
  other labels (`5.1(side)` → `5.1`, a lossless relabel: the same PCM). A source with fewer
  channels is not upmixed (5.0 stays 5.0).
- **Sample rate** always (`-ar:a:N`): the track's or the source's rate, or the closest rate
  the encoder lists.
- **Bitrate**: the track's, else its VBR quality, else the definition's default for the
  effective mixdown (not FFmpeg's own default).
- **DRC** is the AC-3 / E-AC-3 decoder option `-drc_scale:<index>` with the track's value
  (0 = off, as in HandBrake), for each decoded AC-3 / E-AC-3 stream. FFmpeg has one decoder
  per input stream, so the first track that decodes a stream decides.
- **Passthru fallback**: a passthru track that the container cannot hold is encoded with its
  `encoder`, or AAC when it names none (HandBrake's default fallback).
- **Loudness**: one `analyse` step per normalised track, each measuring one block (its own
  `Measurement`). Targets: EBU R128 `I=-23`, Streaming `I=-16`, both `TP=-1`, `LRA=20`;
  the encode uses `linear=true` with the measured values. LRA 20 keeps most films in
  linear mode (loudnorm's default 7 makes it compress them dynamically).

### 5. Video

- **Frame rate**: same as source + variable: nothing. Constant: `-r R -fps_mode cfr`, with
  `R` the chosen rate or the source's **average** (`avg_frame_rate`, else frames ÷
  duration snapped to a standard rate within 0.2 %, else `r_frame_rate`). Peak, and a chosen
  rate with "variable": `-fpsmax R` (a slower CFR source keeps its rate; a faster or VFR
  source becomes CFR R).
- **2-pass**: pass 1 maps only the video and writes to `-f null -`. The statistics files
  (`<name>.part.passlog-0.log`, `.mbtree` for x264; `<name>.part.passlog`, `.cutree` for
  x265; and the `.temp` files that exist while a pass runs) are listed in the new
  `EncodePlan.temp_files`; the runner removes them when the job ends. The x265 `stats=` path
  is escaped for FFmpeg's dictionary parser.

### 6. Metadata, chapters, tags, job type

- Languages in the container's form (ISO 639-2/B for Matroska and WebM, /T for MP4). A BCP 47
  tag that ISO 639-2 cannot express (`pt-BR`, `zh-Hant`, `yue`) adds an `mkvpropedit` step
  (`--edit track:a2 --set language=pt-BR`, which writes both elements) when mkvpropedit is
  found; without it the legacy code is written alone (validation warns).
- Chapters: the source's (`-map_chapters 0`), none (`-1`), or an FFMETADATA file for renamed
  or generated chapters. `ChapterSettings.names` are the names of the source's chapters in
  order (with a chapter range, the names of the chapters in the range are used); an empty
  name keeps the source's. A generated last chapter shorter than a quarter of the interval
  is merged into the one before it.
- Tags use HandBrake's keys (Actors → `artist`, Director → `album_artist`, Release date →
  `date`, Plot → `synopsis`), written by all three muxers. Naming variables are rendered with
  C-16's template code without file-system reads; `{date}` / `{time}` need the new `now`
  argument of `build_plan`, `{modification-date}` stays empty.
- **remux**: video passthrough, every audio track copied, every subtitle track with the
  action `copy` (a text track converted to the container's text format still counts).
- `build_plan` takes two more keyword arguments: `naming` (the effective naming options, for
  tag values) and `now`. Step weights: analyse 0.05, pass 1 0.4, pass 2 0.6, encode 1,
  mkvpropedit 0.01, finalize 0. The display joins the steps with `&&` and shows the rename as
  `mv -f --` (POSIX) or `move /Y` (Windows).

## Consequences

- Outputs carry no stale or wrong stream metadata, and every flag is what the job says. A
  job whose video track has `default = false` writes `FlagDefault=0` on the video (the draft
  of C-15 should fill it from the source, or set it).
- HDR → SDR outputs are clean SDR. HDR outputs of x265 and SVT-AV1 carry the source's HDR10
  metadata even when the frames have none.
- Bitmap burn-in with a crop moves bottom subtitles up by the bottom crop; top subtitles in a
  cropped top bar are lost (HandBrake keeps them). Revisit if users burn in positioned
  bitmap subtitles on cropped sources.
- Text burn-in into an HDR output uses SDR white (libass is not PQ-aware): very bright on an
  HDR display.
- Loudness normalisation reads the source once more per normalised track. The runner (C-11)
  must turn `-inf` measurements (a silent track) into values `loudnorm` accepts
  (`measured_I` −99 … 0, `measured_TP` −99 … 99, `offset` −99 … 99): FFmpeg refuses `-inf`.
- Peak frame rate makes VFR sources CFR at the peak rate.
- C-8 must report what the builder refuses (`PlanError`): unknown encoders, filters,
  implementations, presets; codecs a container cannot hold; PGS into MP4; more than one
  burn-in; burn-in with video passthrough; a conversion from bitmap; an empty range; a frame
  range without a frame rate; an external subtitle of an unknown type; x265 with a tune and
  fast decode. It may warn about what the builder skips: advanced options of another encoder
  or not in this build, options whose `requires` does not hold, forced-only on a text track
  or a copy, DRC on a non-AC-3 source or with two values for one source stream, tone mapping
  of an SDR source.

## Plan changes

- `docs/plan/05-core.md` §C-7: the argument-order bullet (decoder options, range end as an
  output option, metadata details, `-f`), the filter-graph bullet (burn-in placement, HDR side
  data), the video bullet (HDR params, frame rate, `temp_files`), the audio bullet (layout,
  sample rate, DRC, one analyse step per track), the metadata bullet (no source stream tags,
  mkvpropedit for LanguageIETF).
- `docs/plan/05-core.md` §C-7: the `EncodePlan` sketch gets `files` and `temp_files`.
- `docs/plan/03-features.md` §Filters: the filter order names the burn-in positions and the
  HDR metadata removal; §Video: peak frame rate; §Subtitles → Output tracks: where the
  burn-in happens.

## Follow-up (M2 wave 2b), 2026-10-14: audio values snapped with the shared helpers

### Context

Decision [0024](0024-m2-wave-2-product-decisions.md) item 4 says the builder snaps an audio
bitrate, mixdown or sample rate that the encoder cannot do, and C-6 added the helpers that
C-7, C-8 and C-12 share (`AudioEncoderDef.snap_mixdown`, `AudioEncoderDef.snap_samplerate`,
`AudioBitrateDef.snap`, `channels_mixdown`). C-7 had its own copies (`effective_mixdown`,
`closest_samplerate`) that did not snap a chosen mixdown and wrote the track's bitrate as it
was: an AC-3 7.1 track became `aresample=out_chlayout=7.1` with no `-b:a` (FFmpeg converted
it to 5.1 by itself, at its default 448 kb/s), and a 5.1 mixdown on a stereo source was an
upmix with silent channels, against [0019](0019-audio-codec-rule-details.md) item 3. AC-3 at
96 kHz, Opus at 44.1 kHz and Opus stereo at 600 kb/s fail in FFmpeg (`testdata/README.md`,
"Audio values the encoder cannot do").

### Decision

Every encoded audio track (a passthru fallback too; a copied track is never snapped) goes
through one pure function, `reframe.command.planned_audio` (copy or encoder, the snapped
mixdown, the bitrate table, the bitrate or VBR quality, the sample rate). The builder writes
its values and nothing else, so C-8, C-12 and an agreement test can call it:

- **Mixdown**: `snap_mixdown(track.mixdown, source channels)`: never an upmix (a 5.1 or 7.1
  request on a stereo source keeps the stereo; Dolby Pro Logic II needs more than two
  channels), otherwise the encoder's largest layout below (AC-3 and E-AC-3 make 5.1 of 7.1,
  MP3 stereo of 5.1). §4 "Layout" applies to the snapped mixdown; when the source layout
  stays, only the relabel of §4 is written (`5.1(side)` → `5.1`).
- **Bitrate table**: the snapped mixdown, or `channels_mixdown(source channels)` when the
  source layout stays.
- **Bitrate**: `AudioBitrateDef.snap(track.bitrate, table)` with its default direction,
  **down**: clamped to the table's range, then the largest allowed step at or below (the rule
  C-6 documents as HandBrake's; C-8's fix and C-12's maximum use the same). With no bitrate
  and no VBR quality, the table's default.
- **Sample rate**: `snap_samplerate(track.samplerate, source rate)` (the nearest listed rate,
  the higher one on a tie).

0024 says "the nearest allowed value". For a bitrate between two steps the two differ: AC-3
stereo at 150 kb/s → 128 (down) or 160 (nearest; FFmpeg's `ac3` itself writes 160). The
builder writes 128, so that the builder, validation and the codec rules agree; changing it
means one `direction` argument here and in C-8.

### Consequences

- AC-3 and E-AC-3 7.1 tracks are written as 5.1 with the 5.1 bitrate (defaults 640 and
  1536 kb/s instead of FFmpeg's 448). A 5.1 mixdown on a stereo source keeps the stereo and
  the stereo default (AAC 160 kb/s, not 384). Dolby Pro Logic II on a stereo source writes no
  filter (the same PCM). AC-3 at 96 kHz, Opus at 44.1 kHz and Opus stereo at 600 kb/s encode.
- No existing plan snapshot changed (none of the 68 jobs had a value the encoder cannot do);
  two snapshots show the snapping.
- A source with an unknown channel count (0) still gets the requested layout (snapped to the
  encoder), which can be an upmix when the probe could not read the channels.

### Plan changes

- `docs/plan/05-core.md` §C-7, the audio bullet: how each value is snapped.

## Follow-up (M2 wave 2b), 2026-10-14: chapter range ends, chapters cut on a chapter edge

### Context

Decision [0026](0026-builder-and-validation-agree.md) makes the builder clamp the end of a
chapter range to the last chapter (§1 "The range": a time or frame range was already clamped
to the source). Re-probing such an encode showed a second problem that every chapter range
has: with `-map_chapters 0`, FFmpeg (fftools `copy_chapters`, both n9.0.2 builds) skips a
source chapter only when it ends *before* the seek point and stops only at one that starts
*after* the range end. A chapter that ends exactly at the range start, or starts exactly at
the range end, is written as an empty chapter (`-ss 2.5` on the `chapters` fixture gives
`Part One 0.0–0.0` before `Part Two`; `-ss 1 -t 3` gives `Opening 0.0–0.0` and
`Credits 3.0–3.0`; `testdata/README.md`). A chapter range always starts and ends on chapter
edges, so players showed the chapter before the range as a first, empty chapter.

### Decision

- `chapter_range` clamps the end to the last chapter. A range that starts after the last
  chapter, ends before it starts, or is used on a source without chapters stays a
  `PlanError` (validation: `range.outside`, the empty-range error).
- When the source's chapters are copied (no renamed chapters) and the range starts or ends
  within 1 ms of a chapter edge, the builder writes the source's chapters cut to the range
  as an FFMETADATA file instead of `-map_chapters 0` (the path of renamed chapters, with the
  source titles). A chapter shorter than 1 ms after the cut is left out. Other ranges keep
  `-map_chapters 0`.

### Consequences

- A chapter range encode has exactly the chapters of the range (chapters 3 to 9 of the
  4-chapter fixture: `Part Two 0–1.5`, `Credits 1.5–2.5`). Chapter tags other than the title
  are not kept in that case (FFMETADATA holds the title only).
- The plan snapshot `burn_ass_with_fonts_and_range` (range from 1.5 s, the source's chapter
  edge) now has an FFMETADATA file with `Part A` only, instead of `-map_chapters 0`.

### Plan changes

- `docs/plan/05-core.md` §C-7, the chapters bullet.

## Follow-up (M2 review), 2026-10-14: layouts for libopus, 10-bit burn-in, nothing before 0, Bob, display quoting

### Context

The M2 milestone review found these in the builder (each reproduced with both n9.0.2 builds
before the fix; `testdata/README.md` §Command builder has the commands and results):

1. **libopus refuses common layouts.** §4 relabelled only `5.1(side)`-like layouts with the
   table's channel count. libopus takes only the eight Vorbis layouts (mono, stereo, 3.0,
   quad, 5.0, 5.1, 6.1, 7.1) and FFmpeg does not convert for it (it lists no layouts), so an
   AC-3 3/2 source (`5.0(side)`), `quad(side)`, `3.0(back)`, `2.1`, `4.0` … failed with exit
   234. The same relabel was a lossy remix for `6.0` → `5.1` and `7.1(wide)` → `7.1`.
2. **Bitmap burn-in cut 10-bit sources to 8 bits.** `overlay` defaults to 8-bit 4:2:0.
3. **External subtitles reached the muxer with negative times.** §1 seeks each external
   file with the range start, but an event on screen at the range start (or moved before 0 by
   a negative offset) keeps a negative time; the Matroska muxer then moved every stream (the
   chapters did not move), and MP4 `mov_text` got wrong times. The same happened to copied
   streams of an encode with a range (a copied AC-3 track started 1.17 s before the video).
4. **Bob with a constant "same as source" frame rate** wrote the source's rate after a
   deinterlacer that doubles it, dropping every second frame.
5. **The POSIX display** (`shlex.quote`) did not paste into fish for `'` and `\`, nor for a
   leading `%`; zsh expands a leading `=`. The Windows display claimed PowerShell.

### Decision

1. `PlannedAudio` gets `layout` (the `aresample` `out_chlayout`, or `None`); the builder
   writes exactly it. With a mixdown, as before. Without one (the source layout stays):
   - for libopus (`ENCODER_LAYOUTS` in `reframe/command/audio.py`, checked against the real
     encoder by `test_layout_tables_match_ffmpeg`): the source layout if accepted, else the
     side → back relabel (`5.0(side)` → `5.0`, `quad(side)` → `quad`, `5.1(side)` → `5.1`),
     else the largest accepted layout made of the source's channels (`2.1` → stereo,
     `3.0(back)` → stereo, `4.0` → `3.0`, `6.0` → `5.0`, `7.1(wide)` → `5.1`);
   - for any other encoder: only a lossless relabel to the bitrate table's layout
     (`5.1(side)` → `5.1`); `6.0` and `7.1(wide)` reach the encoder as they are (AAC and FLAC
     take them; FFmpeg converts for AC-3, E-AC-3 and MP3 itself).
   The bitrate table is that of the **output** channels (`channels_mixdown`): a libopus
   downmix of `2.1` uses the stereo table (default 96 kb/s, was the 5.1 table's 320).
2. A source of more than 8 bits gets `overlay=…:format=yuv420p10` (`yuv422p10`,
   `yuv444p10` by its chroma format). Not `auto`: it negotiates 8-bit RGB.
3. When the video is encoded and something could start before 0 (a range start, a negative
   offset of an external subtitle that is not burned in), the output gets `-ss 0`: FFmpeg
   then drops every packet and subtitle event before 0. An event on screen at the range start
   is **dropped**, not shortened (no FFmpeg option cuts an event). A copied audio track can
   lose up to one frame at the start. With a copied video an output `-ss` would drop the
   video's own first packets, so a remux keeps FFmpeg's behaviour (it starts at the keyframe
   before the range and every stream keeps its relative time); a copied external track of a
   remux without a range drops its own events before 0 with `-copypriorss:s:N 0`. Not
   solved: a converted external track (`mov_text`) of a remux with a negative offset.
4. After a deinterlacer that sends fields (`bwdif` / `yadif` `mode=send_field`, `1`,
   `send_field_nospatial`, `3`), a constant "same as source" rate is twice the source's.
5. The POSIX display quotes for bash, zsh, fish and sh (tested with each): bare only for
   `[A-Za-z0-9_@%+=:,./-]` without a leading `=` or `%`, else single quotes with `'` as
   `"'"` and `\` as a backslash pair in double quotes. The Windows display is for `cmd.exe`
   only; PowerShell reads `,` and `;` outside quotes and `$` inside double quotes its own way
   (not checked: no PowerShell on the development machine).

### Consequences

- C-8 and C-12 read the layout from `planned_audio` (`PlannedAudio.layout`); a libopus
  downmix changes the bitrate table (`2.1`, `3.0(back)` → stereo; `6.1(back)`, `7.0`,
  `7.1(wide)` → 5.1). C-8 could note the libopus downmix like any other mixdown change.
- Seven plan snapshots with a range on an encoded video get `-ss 0`; nothing else in them
  changes.
- Detelecine (`decimate`) lowers the rate by 1/5 and a constant "same as source" rate then
  duplicates frames back; not changed (not in the review; open question).

### Plan changes

- `docs/plan/05-core.md` §C-7: the argument order (`-ss 0`), the filter graph (10-bit
  overlay), the video bullet (Bob) and the audio bullet (libopus layouts).
