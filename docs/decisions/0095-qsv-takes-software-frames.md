# 0095 — QSV encoders take software frames

- Status: accepted
- Date: 2026-11-18
- Steps: C-6, C-4

## Context

The plan (05 §C-6) gives the QSV encoders a hardware setup: `-init_hw_device qsv=hw
-filter_hw_device hw` and the filter tail `hwupload=extra_hw_frames=64,format=qsv`. It was
never run on an Intel GPU ([0008](0008-encoder-detection-reasons-and-filters.md),
`testdata/README.md` §Hardware setup).

The first Intel machine is a laptop: Intel UHD 620 (i5-8250U, Kaby Lake R), Windows 11 25H2,
Intel driver 31.0.101.2140, the pinned build n9.0.2-17-g2a571b6068-20260930. `reframe encoders`
reported every QSV encoder as an error:

```console
av1_qsv — error: The test encode failed: Could not create the texture (80070057)
h264_qsv — error: The test encode failed: Could not create the texture (80070057)
hevc_qsv — error: The test encode failed: Could not create the texture (80070057)
```

80070057 is E_INVALIDARG from Direct3D 11. The QSV device itself starts (`Initialize MFX
session: implementation version is 1.35`); creating the frame pool for `hwupload` fails:

```console
[D3D11VA @ …] Using device 8086:5917 (Intel(R) UHD Graphics 620).
[AVHWFramesContext @ …] Could not create the texture (80070057)
[AVHWFramesContext @ …] Error initializing a child frames context
[AVHWFramesContext @ …] Error creating an internal frame pool
```

Test encodes over SSH, testsrc2, `-f null -` (all in `testdata/README.md` §QSV on an Intel GPU):

| Setup | n9.0.2 | n8.1.3 |
|-------|--------|--------|
| `hwupload=extra_hw_frames=N`, N = 8, 16 … 64 | texture error | texture error (N = 64) |
| `hwupload` without `extra_hw_frames` | works | `hevc_qsv` 1080p works; `h264_qsv` 720p fails after it starts ("Cannot allocate memory") |
| software frames (`-pix_fmt nv12` / `p010le`, no device, no upload) | works | works |

Software frames encoded 600 frames of 1080p on both builds: `h264_qsv` with `-look_ahead 1`,
`hevc_qsv` 10-bit with `-bf 3 -refs 4`. A D3D11 device made first and the QSV device derived
from it fails the same way; the DXVA2 child device cannot be created.

## Decision

1. The QSV encoders have no hardware setup: they take software frames (`-pix_fmt <sw_pix_fmt>`),
   as NVENC and AMF do. The encoder opens its own session and uploads the frames.
2. Detection maps `This version of runtime doesn't support AV1 encoding` (the UHD 620's
   runtime) to `unavailable`, "This Intel GPU cannot encode AV1".
3. The GPU encode test (`test_hardware_encode`) covers `h264_qsv` (8-bit) and `hevc_qsv` (10-bit,
   HDR10).

## Consequences

- No fixed frame pool, so the setup does not depend on the driver accepting a texture array,
  and it works on the 8.1 build, which the upload without a pool does not.
- Reframe's filter chain runs on the CPU anyway, so no QSV filter needs frames on the GPU. A
  later GPU filter chain (`vpp_qsv`, `scale_qsv`) would need a device and an upload again.
- Detection without an Intel GPU now fails at `Error creating a MFX session` (the encoder's own
  session); the reason stays "No Intel QSV device". The QSV case of the device-creation rule
  (a failed `-init_hw_device qsv=hw`) is gone with the setup.
- Verified only on one Intel GPU under Windows. QSV on Linux (VAAPI below oneVPL) and Arc are
  not checked; the QSV advanced options are still not verified on hardware.

## Plan changes

- `05-core.md` §C-6 (the QSV setup in the video encoder list) and §C-4 (the QSV reason texts).
