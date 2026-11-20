# 0102 — NVIDIA NVENC on Linux

- Status: accepted
- Date: 2026-11-20
- Steps: C-4, C-6, C-7, C-8, C-11, S-6

## Context

NVENC had been checked on the Windows VM only ([0093](0093-ffmpeg-download-and-build-choice.md)),
and status.md listed "NVENC on Linux" and "NVIDIA NVENC in Docker" as not verified. This round
checked both on a Linux host, after [0101](0101-nvenc-session-limit-and-older-build-hint.md).
The tool behaviour is recorded in `testdata/README.md` §NVENC on Linux.

| Item | Version |
|------|---------|
| Machine | Debian 13, kernel 6.12.117+deb13-amd64, 20 threads, 7.6 GB; a home server (Jellyfin also uses the GPU) |
| GPU / driver | GeForce GTX 1050 Ti (Pascal, GP107), NVIDIA 580.159.04 (`.run`, DKMS; Debian's 550 cannot run either offered build) |
| FFmpeg | `compat` n8.1.3-9-g29e619e767-20260930 (NVENC works), `default` n9.0.2-17-g2a571b6068-20260930 (needs driver 610) |
| Docker | 29.10.0, Compose 5.8.0, buildx 0.39.0, NVIDIA Container Toolkit 1.20.2 with CDI |

Three parts ran: the lead (detection, the option matrix, levels, the GPU tests), agent E
(real encodes through the CLI and the core API) and agent D (the Docker image).

## Results

1. **Full test suite on Debian 13** with the pinned build on `PATH` (as CI): 8046 passed, one
   timing failure under load (`test_a_node_script_that_ignores_sigterm_is_killed_when_the_check_stops_it`,
   3 of 3 pass alone). Without FFmpeg on `PATH` 65 tests fail: the tests isolate the data
   folder, so they do not see the bundled build (CI puts the pinned build on `PATH`).
2. **What works** (agent E): both built-in NVENC presets; CQ (sizes fall with the value),
   average bitrate (+3 % of the target), 2-pass turbo and full (`-multipass`); H.265 10-bit
   from 8- and 10-bit sources; HDR10 kept (BT.2020/PQ, mastering display and content light
   level in the container and the bitstream); tone mapping to SDR (libplacebo: Vulkan works
   with the NVIDIA ICD; zscale too); the accepted advanced options visible in the stream
   (`trace_headers`); queue order, progress, `reframe queue cancel`, Ctrl-C, three jobs in
   parallel (NVENC at 100 %), a 12-episode season batch; preview clip, frames and crop
   detection through the core API; the busy GPU of 0101 in a real job.
3. **Docker** (agent D): the compose `deploy` reservation, `--gpus all`, CDI
   (`--device nvidia.com/gpu=all`) and `--runtime nvidia` all mount `nvidia-smi`,
   `libnvidia-encode` and `libcuda`. `default` → every NVENC encoder "NVIDIA driver too old:
   NVENC needs driver 610.00 or newer" (build mismatch); `compat` → H.264 (8-bit) and H.265
   (10-bit) available, AV1 not (Pascal). H.264 8-bit and H.265 Main 10 4K HDR10 encoded with
   the metadata kept. Image 522 MB, built in 72 s. With CDI the toolkit mounts all driver
   libraries whatever `NVIDIA_DRIVER_CAPABILITIES` says.
4. **Web UI** (lead, headless Chromium through an SSH tunnel to `scripts/dev-server.py` on the
   host, a fresh home without FFmpeg, hardware tests on): the first-run screen offers
   `default` and `compat` (with the 570–609 text); `default` installs in 10 s, every NVENC
   encoder is unavailable with the build mismatch; with the "H.265 NVENC 1080p" preset the
   Summary issue names other builds, the Video banner says "NVIDIA driver too old", its
   **Use another FFmpeg…** opens Settings → Tools with the notice; installing `compat` there
   makes H.264 and H.265 NVENC available (AV1 not), the notice and the job's issue go away,
   and the queued job ends `done` (H.265 NVENC, PQ kept).
5. **Defects found:**
   - a. **NVENC refuses an explicit level at run time** ("InitializeEncoder failed: invalid
     param (8): Invalid Level."): (i) when the picture size or frame rate exceeds the level
     (as x265, which validation already checked), (ii) in bitrate mode when the bitrate is
     above what the level allows: FFmpeg gives NVENC a buffer of twice the bitrate, and NVENC
     checks the buffer and the bitrate against the level's NAL limits. Measured for every
     level: H.264 min(MaxBR, MaxCPB / 2) × 1.2 (Baseline, Main) or × 1.5 (High); H.265
     the same × 1.1 per tier; Main 10 as Main; the High tier below level 4 has no limit.
   - b. **FFmpeg 8.1 writes H.264 Main when no `-profile` is given** (9.0 writes High), while
     Reframe's definition and the Video tab say the default is High. `compat` users got Main.
   - c. **Pascal refuses some advanced options at run time** that validation lets through:
     `refs` > 1, `tf_level`, `lookahead_level` other than automatic, and in H.265 B-frames,
     `b_ref_mode`, temporal AQ and `unidir_b`, tune `uhq`. In H.264, `b_ref_mode` and temporal
     AQ work. Any NVIDIA GPU: `weighted_pred` with B-frames ("Weighted Prediction not
     supported with B-frames"), and a keyframe interval not larger than the B-frames + 1.
   - d. **Job errors**: a refused option ended with FFmpeg's guess "Error while opening encoder -
     maybe incorrect parameters such as bit_rate, rate, width or height", and the H.265 B-frame
     refusal ("Max B-frames 2 exceed 0") showed only that guess.
   - e. **The 10-bit reason of `h264_nvenc`** was "No NVIDIA GPU that can encode H.264" (the
     rule order of 0101 again: "No capable devices found" won over "10 bit encode not
     supported").
   - f. **A job with the `default` build** said "NVIDIA driver too old …" and offered only
     libx265; the way out (another build) was only in `reframe encoders`.
   - g. **The server console** never named the build mismatch (Docker users read only it), and a
     running server does not see a build that `reframe tools fetch` installed (until **Check
     again** or a restart).
   - h. **NVENC caps a constant quality at the level it picks.** With no level, NVENC picks the
     lowest level that fits the picture and keeps the bitrate under that level's maximum, in
     CQ mode too: H.265 1080p25 is held at about 12 Mbit/s (level 4.0) and H.264 at about
     24 Mbit/s, so on grainy content CQ 10 and CQ 20 give the same file. An explicit higher
     level or a large `-maxrate` lifts the cap. Reframe's CQ arguments are HandBrake's.
   - i. The built-in "H.265 NVENC 2160p 4K" preset is 8-bit, unlike the other 4K presets.

## Decision

1. **Validation** (C-8): `encoder.level_too_low` also covers `h264_nvenc` (H.264 table A-1,
   MaxFS and MaxMBPS) and `hevc_nvenc` (the x265 table). A new rule
   `encoder.level_bitrate_too_high` (jobs and presets) refuses an NVENC level whose measured
   bitrate limit the average bitrate exceeds, with the fixes "Use N kb/s" and "Let the encoder
   choose the level". It is skipped when the custom parameters set `maxrate` or `bufsize`, and
   for H.264 High 10 (not measured: no GPU at hand encodes 10-bit H.264).
2. **Definitions** (C-6, C-7): `ChoiceSetting.write_default` makes the command builder write
   the default when the job sets none; `h264_nvenc` profiles use it, so every build writes
   High (High 10 at 10-bit).
3. **Options** (C-6): the help texts name the Pascal limits; `weighted_pred` requires
   B-frames set to 0 (else it is inactive, `encoder.option_inactive`). As in
   [0096](0096-qsv-options-on-intel-hardware-and-ffmpeg-that-does-not-exit.md), features of a
   GPU generation stay offered.
4. **Job errors** (C-11): FFmpeg's "maybe incorrect parameters", "Error sending frames to
   consumers" and "No capable devices found" are used only when nothing else says why; an
   NVENC line counts as a cause without an error word; "Max B-frames N exceed 0" reads "This
   GPU has no B-frames for this codec: set B-frames to 0."
5. **Reasons** (C-4): "10 bit encode not supported" comes before "No capable devices found".
   An unavailable encoder with a build mismatch says "Another FFmpeg build may work with this
   computer (Settings → Tools, or reframe tools fetch --build)". Detection logs one INFO line
   per mismatch cause for the server console (INFO, so the CLI does not print it twice).
6. **Docs**: `docs/deployment.md` (agent D: the driver → build table, the `reframe-nvidia`
   profile needs its name in each compose command, the capabilities note); `docs/user/ffmpeg.md`
   (a CLI fetch needs **Check again**).
7. **GPU tests** cover NVENC: the choices, rate controls and options of `h264_nvenc` and
   `hevc_nvenc` (Pascal refusals accepted only with FFmpeg's "not supported" text, levels too
   low for the test picture expected to fail), the quality range ends, every entry of the
   bitrate table (the limit passes, one more kb/s fails) and the picture-size limits.
8. **Not changed, the owner decides:** the CQ cap (5h; options: leave it, give CQ a generous
   `-maxrate`/`-bufsize`, or set a level; each changes the level a player sees), the 8-bit 4K
   NVENC preset (5i). The GPU test marks the CQ range end of NVENC as an expected failure
   until then.

## Consequences

- A level that NVENC would refuse is a validation error with a fix before the job starts. The
  bitrate table was measured on Pascal with driver 580; newer GPUs follow the same level
  limits (they are the codec's), but that is not checked.
- H.264 NVENC outputs are High profile with the `compat` build as with `default`.
- Not verified: AV1 NVENC (Pascal has none), H.264 10-bit, Turing and newer GPUs, the `default`
  build with a driver ≥ 610, the toolkit's legacy (non-CDI) mode, Windows (the session limit
  text of 0101).
- Agent E also found that a hard-linked second source is dropped from a CLI run without a
  message (by design, `file_key`), and the job header names the output before the collision
  rename. Not NVENC; listed in status.md.

## Plan changes

`05-core.md` §C-8: the level rule names NVENC and the bitrate rule.
