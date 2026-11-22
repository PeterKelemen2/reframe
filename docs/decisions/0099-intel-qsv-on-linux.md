# 0099 — Intel QSV on Linux

- Status: accepted
- Date: 2026-11-19
- Steps: C-4, C-6, S-6

## Context

[0095](0095-qsv-takes-software-frames.md) and
[0096](0096-qsv-options-on-intel-hardware-and-ffmpeg-that-does-not-exit.md) checked QSV under
Windows only. The same laptop now also boots Linux, so the checks were repeated there, and the
Docker image's "Intel QSV not verified" item (06 §S-6) was checked as well.

| Item | Version |
|------|---------|
| Machine | i5-8250U, Intel UHD 620 (Kaby Lake R, gen 9.5, PCI `8086:5917`), 8 threads, 11 GB |
| OS | CachyOS, kernel 7.3.3-1-cachyos |
| VA driver | intel-media-driver 26.3.5 (iHD, the full build: H.264 `EncSlice` and `EncSliceLP`, HEVC Main/Main10 `EncSlice`) |
| QSV runtime | intel-media-sdk 23.2.2 (`libmfxhw64.so.1.35`), libmfx 23.2.2, libvpl 2.17.0; no vpl-gpu-rt (`libmfx-gen`) |
| libva | 2.24.1 (libva-utils 2.24.0) |
| FFmpeg | pinned n9.0.2-17-g2a571b6068-20260930, `override-test` n8.1.3-9-g29e619e767-20260930, Arch n9.0.2 (comparison) |
| Docker | Docker 29.9.3, Compose 5.7.0, no buildx (the classic builder) |
| Python / uv / Node | CPython 3.14.9, uv 0.13.5, Node 26.13.0 |

The results are in `testdata/README.md` §QSV on Linux. In short:

1. **The runtime.** The BtbN builds link the oneVPL dispatcher in and load libva, the iHD
   driver and the QSV runtime from the system. On gen 9.5 the dispatcher loads the Media SDK
   runtime `libmfxhw64.so.1.35` (implementation 1.35, as on Windows). All three builds give
   the same results.
2. **Software frames work** (`h264_qsv` 8-bit, `hevc_qsv` 8- and 10-bit, HDR10 kept). The
   old setup of the plan (`-init_hw_device qsv=hw`, `hwupload=extra_hw_frames=64`) also works
   on Linux: the texture error of 0095 is a D3D11 one. `av1_qsv` fails with `This version of
   runtime doesn't support AV1 encoding`, as on Windows.
3. **Detection** gives the same states and reasons as on Windows. But when the GPU and the
   media driver are there and the QSV runtime package is not, FFmpeg prints the same `Error
   creating a MFX session: -9.` as on a machine without an Intel GPU, so Reframe said "No
   Intel QSV device (needs an Intel GPU with its media driver)" while VAAPI on the same GPU
   worked.
4. **Options**: the same as Windows (0096's table), except:
   - H.264 low power fails when the encoder opens, at a constant quality and at a bitrate
     (`Selected ratecontrol mode is unsupported`, exit 218). Only CQP works, and Reframe
     offers no CQP for QSV. On Windows it worked at a bitrate.
   - The H.265 look-ahead depth with extended rate control stays `LookAheadDepth: 0` (on
     Windows: the value).
   - H.264 `g=1` with B-frames prints `Error during encoding: undefined behavior (-16)`
     before the same flush error.
5. **FFmpeg that does not exit** (0096) did not happen: H.264 low power fails at open on
   Linux (four runs), so the 60 s exit limit was not reached.
6. **The Docker image** (built from `docker/Dockerfile`): QSV unavailable, "No Intel QSV
   device". The image's only QSV runtime is `libmfx-gen1.2` 25.1.4 (the oneVPL GPU runtime).
   The dispatcher loads it, it does not take the gen 9.5 GPU, and the session fails (-9).
   The Media SDK runtime (`libmfx1`) is not in Debian 13 (main, contrib, non-free), its
   backports or sid; Debian 12 has `libmfx1 22.5.4-1`, whose dependencies Debian 13 meets.
   With it added, QSV works in the container. VAAPI worked in both.
7. **The GPU tests** found that VAAPI on the iHD driver refuses values that the AMD GPU takes:
   H.264 levels 6.0, 6.1 and 6.2, and H.265 quality levels (`compression_level`) other than
   1, 4 and 7. They fail at the first frame (`Failed to end picture encode issue: 24
   (internal encoding error)`).

## Decision

1. **The QSV session reason** is "No Intel QSV device or runtime (needs an Intel GPU, its media
   driver and its QSV runtime)". The rule (`Error creating / initializing / querying a MFX
   session`) does not change.
2. **The amd64 Docker image installs `libmfx1=22.5.4-1` from Debian 12** next to
   `libmfx-gen1.2`: in the same `RUN`, a `bookworm` source and a pin of priority 100 (so no
   other package comes from it), both removed after the install. `debian-packages.sh` lists the
   package and its copyright file like the others. With both runtimes, the dispatcher loads
   both and uses the one that takes the GPU.
3. **No change to 0095's setup.** The QSV encoders take software frames on Linux too: one
   setup for both systems, and no fixed frame pool.
4. **The help of the QSV low-power and H.265 look-ahead-depth options** says what the UHD 620
   does on Linux. **The VAAPI values that the UHD 620 refuses stay offered**, with help (the
   rule of 0096 for QSV: they are features of the GPU generation, and the AMD GPU takes them):
   the H.264 levels 6.x, and the quality level ("an Intel UHD 620 takes only 1, 4 and 7 for
   H.265"). `test_hardware_choices_rate_control_and_options_encode` accepts these failures
   when the render node is an Intel GPU only.
5. **A Linux test with an Intel GPU** (`test_qsv_and_vaapi_on_an_intel_gpu`): `h264_qsv`
   (8-bit), `hevc_qsv` (10-bit), `h264_vaapi` and `hevc_vaapi` available, and `av1_qsv`, when
   unavailable, with the AV1 reason.

`reframe encode` does not run the one-frame dry run of custom parameters; `reframe plan`
does ([0035](0035-advanced-option-sets-and-dry-run.md)). A custom `low_power=1` is therefore
caught by `plan`, and with `encode` the job fails with FFmpeg's error. That is the design, not
a bug.

## Consequences

- QSV works in the Docker image on Intel GPUs before Tiger Lake. The image grows by about
  36 MB on disk (699 → 735 MB).
- The image build reads Debian 12 from `deb.debian.org`. When Debian 12 moves to
  `archive.debian.org`, the build fails and the source line must change (or the package must
  come from snapshot.debian.org). The Media SDK is end-of-life upstream; 22.5.4 is its last
  Debian version.
- On bare metal the QSV runtime is a system package, like the VAAPI driver: the Media SDK
  runtime (for example `intel-media-sdk` on Arch) for GPUs before Tiger Lake, the oneVPL GPU
  runtime (`vpl-gpu-rt`) for newer ones. `docs/deployment.md` says so; the reason says
  "runtime".
- Not checked: Tiger Lake and newer Intel GPUs (`libmfx-gen`) in Docker and on bare metal, so
  also whether the dispatcher picks `libmfx-gen` there when both runtimes are installed (Intel's
  dispatcher documentation says it does); Arc; AV1 on QSV hardware; the 60 s exit limit on
  Linux; the web UI's encoder list in a browser on the laptop (the same API,
  `GET /api/system/encoders`, was checked in the container).
- On Arch, `/usr/lib64` is a link to `/usr/lib`, so discovery gives the bundled FFmpeg
  `LIBVA_DRIVERS_PATH=/usr/lib64/dri:/usr/lib/dri`, the same folder twice. Harmless; not
  changed.

## Plan changes

- `06-web-app.md` §S-6: the runtime packages (the Media SDK runtime for older Intel GPUs) and
  Intel QSV in Docker verified.
- `05-core.md` §C-4: the QSV reason text (committed with the fix, `e5b2c965`).
