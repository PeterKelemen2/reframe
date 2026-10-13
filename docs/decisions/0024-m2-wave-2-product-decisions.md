# 0024 — M2 wave 2: default preset, crop note until M8, audio values snapped, video default flag

- Status: accepted
- Date: 2026-10-13
- Steps: C-7, C-8, C-9, C-15
- Supersedes in part: [0015](0015-presets-and-settings-stores.md) (the default preset),
  [0014](0014-validation-rules-and-severities.md) (the severities of `dimensions.crop_not_detected`
  and of the audio range rules)

## Context

The wave-2 steps of M2 left product questions that the plan does not answer. The user decided
the first four on 2026-10-13; the fifth is the lead's choice.

1. **Default preset** (0015): HandBrake's default, *Fast 1080p30* (x264, MP4, AAC stereo), or
   *H.265 MKV 1080p*.
2. **Frame rate of the Matroska presets** (0015): keep the source frame rate (names without
   fps), or HandBrake's peak 30/60 cap and names.
3. **Crop not detected** (0014): crop detection is C-10 (M8). Until then every job with
   automatic crop (the default) encodes uncropped, and 0014 made that a warning on every job.
4. **Audio values the encoder cannot do** (0014): AC-3 at 700 kb/s, AC-3 7.1, AC-3 at 96 kHz.
   0014 made them errors with a "snap" fix, which blocks the queue.
5. **The video track's default flag** (C-7's question): `VideoSettings.metadata` has every flag
   off, and FFmpeg-written sources often have `default=0` on their only video stream
   (`testdata/README.md`, "no default flag on single streams"), so a drafted job writes
   `FlagDefault=0` on the video.

## Decision

1. The default preset is **H.265 MKV 1080p** (`h265-mkv-1080p`).
2. The Matroska presets keep the **source frame rate** and their names without fps
   (0015 stays).
3. `dimensions.crop_not_detected` is **info** until crop detection exists (M8); it becomes a
   warning again with C-10.
4. An audio bitrate, mixdown or sample rate the encoder cannot do is **snapped by the command
   builder** to the nearest allowed value (C-6's `snap`, the encoder's mixdowns and sample
   rates), and validation shows an **info** issue that says what will change. It never blocks
   the queue.
5. A drafted job's video track gets the **default flag** (what mkvmerge writes); the other video
   metadata comes from the source track.

## Consequences

- `reframe encode FILE` without `--preset` (C-15) and the UI start from an x265 MKV encode.
- M2 CLI jobs show one info line about the crop instead of a warning.
- A user who types an impossible audio value gets the nearest one, with a note; the job still
  runs.

## Plan changes

- [03 §Presets](../plan/03-features.md#presets): the default preset.
- [05 §C-7](../plan/05-core.md#c-7-command-builder): audio values are snapped.
- [05 §C-8](../plan/05-core.md#c-8-validation): the crop note and the audio snap are info.
