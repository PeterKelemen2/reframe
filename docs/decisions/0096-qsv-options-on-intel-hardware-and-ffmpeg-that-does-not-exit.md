# 0096 — QSV options on Intel hardware, and FFmpeg that does not exit

- Status: accepted
- Date: 2026-11-18
- Steps: C-6, C-8, C-11

## Context

After [0095](0095-qsv-takes-software-frames.md) the QSV encoders were checked option by option
on the same laptop (Intel UHD 620, Windows 11, driver 31.0.101.2140), with the pinned n9.0.2
and the `override-test` n8.1.3 build: every preset, profile, quality point, bitrate and every
value of every QSV option, read back from FFmpeg's `-v verbose` parameter dump, then jobs
through `reframe plan` / `reframe encode` (`testdata/README.md` §QSV on an Intel GPU). The two
builds gave the same results. What did not work:

1. **Refused (the encode fails):** `low_power` on H.265, and on H.264 at a constant quality
   (`Invalid FrameType:0`, once `Error during encoding: GPU Hang (-21)`); `tile_cols` /
   `tile_rows` above 1 (`Error querying encoder params: unsupported (-3)`); H.264 `g=1` with
   B-frames (`Error flushing encoder: Internal bug`; with `-bf 0` it works).
2. **Ignored (no change in the dump):** `adaptive_i`, `adaptive_b`, H.265 `rdo` and
   `transform_skip`, `look_ahead_downsampling=4x` (stays 2×); `extbrc` at a constant quality
   (it works at a bitrate, and the H.265 look-ahead depth with it); `p_strategy=2` with
   B-frames (FFmpeg: "Please set max_b_frames(-bf) to 0 to enable P-pyramid").
3. **FFmpeg did not exit.** After the H.264 low-power error FFmpeg sometimes writes the output,
   prints `progress=end` and then spins on one core: once in a queued job (n9.0.2, more than
   10 minutes) and in direct runs on n8.1.3. The stall watchdog (05 §C-11, 0016) counts CPU
   use as activity, so the job never ended.

The plan's rule for AMF and VAAPI ("options the driver refuses are not offered") fits one GPU
generation per vendor there. Tiles, low power and transform skip are features of newer Intel
generations, so removing them for a UHD 620 would take them from GPUs that have them.

## Decision

1. **The QSV options stay offered**; the help of each one a UHD 620 refuses or ignores says so.
   Advanced options get no dry run, so a refused value fails the job with FFmpeg's error.
2. **Validation rules** (recorded behaviour, not GPU-specific): extended rate control and the
   H.265 / AV1 look-ahead depth `require` the bitrate mode (`encoder.option_inactive`);
   `p_strategy=2` without `bf` 0 is `encoder.option_ignored`; H.264 QSV with `g` 1 and B-frames
   is `encoder.option_conflict` (an error; every frame a keyframe leaves nothing for
   B-frames), with the fix "Set B-frames to 0".
3. **An FFmpeg step still running 60 s of active time after its last progress block is
   stopped** (`EXIT_GRACE`, verdict `no_exit`), busy or not. The job fails with "FFmpeg finished
   writing but did not exit within 1 minute and was stopped" and FFmpeg's error lines. FFmpeg
   writes the trailer before its last progress block, so a correct run never waits there: the
   `total_size` of the `progress=end` block is the finished file's size, for Matroska and for
   MP4 with `+faststart` (n9.0.2, 20 s of 640×360 libx264).

## Consequences

- A hung QSV job ends after a minute; on the laptop three low-power jobs ended in 8 s, 68 s
  (stopped) and 2 s, and the GPU encoded normally afterwards.
- A job whose FFmpeg finished correctly but hung while it closed fails instead of being kept;
  none was seen.
- Not checked: QSV on Linux and on Arc or newer Intel GPUs, AV1 on QSV, the desktop app's
  windows with QSV (the encoder list and presets come from the same API as the CLI checks).

## Plan changes

- `05-core.md` §C-11 (Time limits: the limit after the last progress block).
