# 0002 — Bundled FFmpeg: the BtbN build, a shipped libva on Linux, mkvpropedit on Windows

- Status: accepted
- Date: 2026-11-10
- Steps: D-7, C-1, C-4

## Context

02 §Bundled FFmpeg names the BtbN release-branch GPL build (shared libraries) as the first
candidate and lists what the build must have. 07 D-7 asks for this choice to be confirmed on the
available hosts and recorded here, with the untested hosts listed as not verified. 05 C-1 sets
`LIBVA_DRIVERS_PATH` for the bundled FFmpeg on Linux, "only if D-7 shows that it is needed".
0005 puts bundled MKVToolNix and MediaInfo in `tools/mkvtoolnix/` and `tools/mediainfo/`.

The pinned build is `n9.0.2-17-g2a571b6068-20260930` (BtbN `autobuild-2026-09-30-13-08`,
`gpl-shared`, `tools/ffmpeg.toml`).

### What the build has

`ffmpeg -buildconf` of the Linux build has every library the plan requires: `libx264`,
`libx265`, `libsvtav1`, `libopus`, `libplacebo`, `vulkan`, `libvpl`, `ffnvcodec` (NVENC),
`amf` and `vaapi`. Its binaries need glibc 2.28 or newer (`objdump -T`: the highest version is
`GLIBC_2.28`).

### How it loads libva (found with this decision)

The build does not contain libva. It loads the **system's** `libva.so.2`, `libva-drm.so.2` and
`libdrm.so.2` at run time through generated stubs (implib-gen). When a library or one of its
functions is missing, FFmpeg **aborts** (SIGABRT, exit code 134), it does not fail:

```
implib-gen: libva.so.2: failed to resolve symbol 'vaMapBuffer2' via dlsym: /lib/x86_64-linux-gnu/libva.so.2: undefined symbol: vaMapBuffer2
ffmpeg: libva.so.2.init.c:290: _libva_so_2_tramp_resolve: Assertion `0 && "Assertion in generated code"' failed.
```

The bundled FFmpeg was run in containers with the laptop's Intel GPU passed in (`--device
/dev/dri`), with the distro's Intel media driver installed:

| Distro (glibc) | System libva | VAAPI with the system libva |
|----------------|--------------|-----------------------------|
| Ubuntu 22.04 (2.35) | 2.14 | aborts (no `vaMapBuffer2`) |
| Ubuntu 24.04 (2.39) | 2.20 | aborts (no `vaMapBuffer2`) |
| Debian 12 (2.36) | 2.17 | aborts (no `vaMapBuffer2`) |
| Debian 13 (2.41) | 2.22 | works |
| Fedora 45 (2.44) | 2.24.1 | works |
| CachyOS (Arch), the host | 2.24.1 | works |

So with the system libva, VAAPI (and QSV, which uses libva on Linux) is lost on both current
Ubuntu LTS releases and on Debian 12. Setting `LIBVA_DRIVERS_PATH` does not help: the abort
comes before any driver is loaded. It also harms: it replaces libva's own list of driver
folders, and Fedora's libva looks in `/usr/lib64/dri-nonfree` first, where RPM Fusion's full
Intel driver is (the free driver in `/usr/lib64/dri` has no encoders).

## Decision

1. **The build is confirmed**: BtbN release-branch `gpl-shared`, as pinned in
   `tools/ffmpeg.toml`.
2. **Linux: a libva ships next to FFmpeg, as a fallback.** `tools/libva.toml` pins the libva
   source (2.24.1, SHA-256). `scripts/bundle-tools.py` builds it in `ubuntu:22.04`, the oldest
   supported distro, so it loads on every newer one, with DRM only and the driver folders
   `/usr/lib/x86_64-linux-gnu/dri`, `/usr/lib64/dri-nonfree`, `/usr/lib64/dri-freeworld`,
   `/usr/lib64/dri`, `/usr/lib/dri`. It goes to `tools/ffmpeg/libva/` (`libva.so.2`,
   `libva-drm.so.2`, `COPYING`).
3. **Discovery uses the system's libva when it can, the shipped one otherwise.**
   `reframe.platform.libva.system_libva_usable()` loads the system's `libva.so.2` and
   `libva-drm.so.2` and checks for the newer functions that the build calls (`vaMapBuffer2`,
   `vaSyncBuffer`, `vaSyncSurface2`, `vaCopy`). Only when it fails, and only for a bundled
   FFmpeg that has `libva/`, is `LD_LIBRARY_PATH` set to that folder for FFmpeg and ffprobe.
   A new enough system libva is better, because it knows the distro's own driver folders. The
   `LIBVA_DRIVERS_PATH` logic of C-1 is removed.
4. **Reasons for the abort.** The loader texts are known reasons: "The system's libva.so.2 is
   too old for this FFmpeg (it has no vaMapBuffer2)", "libva-drm.so.2 is not installed
   (hardware encoding needs it)". This matters for `reframe tools fetch` and for the Docker image,
   which have no shipped libva (the Docker image is Debian 13: its libva works).
5. **The shipped folder** is `desktop/src-tauri/resources/tools/` (git-ignored apart from a
   README), built for the host platform by `scripts/bundle-tools.py` and mapped to `tools/`
   in the app (`tauri.conf.json`), one folder above the sidecar, where `bundled_tool_roots`
   already looks. It holds only what Reframe runs: `ffmpeg` and `ffprobe`, the libraries (on
   Linux each under its soname only, because an installer may not keep links), and the licence
   files. Not 07's `resources/tools/<os>/`: one platform is built per run, so a folder per OS
   adds a mapping and nothing else.
6. **MKVToolNix ships on Windows only** (`tools/mkvtoolnix.toml`: the portable 103.0 zip,
   SHA-256; only `mkvpropedit.exe`, which needs only Windows' own DLLs, and `COPYING.txt`). On
   Linux it comes from the distro, as 0005 allows.
7. **MediaInfo is not bundled as a program.** The sidecar already ships pymediainfo with its
   own `libmediainfo` (0069 item 9), which is what Reframe reads; the `mediainfo` program stays
   optional.
8. **"Use bundled FFmpeg" downloads only when there is no bundled build.** `ToolInfo.bundled_dir`
   says where the bundled build of a tool's family is, also when an override is used. Settings
   and the first-run screen then only remove the Settings paths, instead of downloading the
   pinned build into the data folder when the app already ships it.
9. **Oldest supported distro: Ubuntu 22.04 LTS** (glibc 2.35, WebKitGTK 4.1 for Tauri 2). The
   plan named no distro; D-8 builds the AppImage on it.

## Results

Reframe's own discovery and encoder detection (`reframe encoders`, run from the source tree with
uv in each container) against the output of `bundle-tools.py`, on the Intel UHD Graphics 620
(Kaby Lake) of this laptop:

| Distro | libva used | VAAPI H.264 / H.265 | QSV H.264 / H.265 | AV1 |
|--------|-----------|---------------------|-------------------|-----|
| Ubuntu 22.04, `intel-media-va-driver-non-free` 22.3 | shipped | available | unavailable: "The Intel media driver is too old for QSV (needs VA-API 1.15.0)" | unavailable (no AV1 encoder on this GPU) |
| Ubuntu 24.04, non-free 24.1, `libmfx1` | shipped | available | available | unavailable |
| Debian 12, non-free 23.1, `libmfx1` | shipped | available | available | unavailable |
| Debian 13, non-free 25.2 | system | available | unavailable (no QSV runtime for this GPU is packaged) | unavailable |
| Fedora 45, RPM Fusion `intel-media-driver` 26.3 | system | available | unavailable (no QSV runtime installed) | unavailable |
| CachyOS (Arch), host, the frozen sidecar | system | available; a real encode of `hdr10.mkv` with "H.265 VAAPI 1080p" | available; a real encode with "H.265 QSV 1080p" | unavailable |

With the distros' free Intel drivers, Debian and Ubuntu lack H.265 encoding on this GPU and
Fedora's lacks every encoder; detection names the cause ("The VAAPI driver cannot encode H.265
on this GPU"). Two reasons were wrong on this GPU before this work and are fixed: AV1 showed as
an error with QSV's CQP notice as the reason, and a QSV runtime that is missing said "No Intel
QSV device" only.

Earlier on the AMD desktop (Radeon RX 7600, CachyOS), the same pinned build passed the C-4
captures: VAAPI and AMF encode (`testdata/README.md`, "Hardware encoder failures").

Windows 10 VM (no GPU): `scripts/bundle-tools.py --platform windows-x64` output copied next to
the release build (`target/release/tools/`). The frozen `reframe tools status` finds `ffmpeg`,
`ffprobe` and `mkvpropedit` as `bundled` in that folder, and a real encode of `chapters.mkv`
("Fast 720p30") works.

### Not verified

- **NVIDIA (NVENC)**: no NVIDIA host, on Linux or Windows.
- **Intel QSV and AMD AMF on Windows**: the VM has no GPU.
- **Intel GPUs newer than Kaby Lake** (the oneVPL runtime `libmfx-gen`, AV1 on Arc).
- **AMD on Linux with the shipped libva**: the AMD desktop runs Arch, whose libva is used; the
  fallback is checked only with Intel's driver.
- **openSUSE, RHEL and other distros**; real installs of the packages (D-8) instead of the
  source tree in a container.

## Consequences

- The Linux packages carry about 0.3 MB more (libva); the bundle is 194 MB on Linux and
  204 MB on Windows, before installer compression.
- The libva build needs Docker (or an `ubuntu:22.04` job with the build tools) wherever the
  packages are built. CI's desktop job runs it.
- A pin update of FFmpeg can need newer libva functions: re-check `NEEDED_FUNCTIONS` against the
  new build (`test_the_checked_libva_functions_are_called_by_the_pinned_build` only checks
  that each listed function is still called).
- `reframe tools fetch` installs no libva: on Ubuntu 24.04 or Debian 12 its FFmpeg has no
  VAAPI, and detection says why.

## Plan changes

- `docs/plan/05-core.md` C-1: the `LIBVA_DRIVERS_PATH` bullet replaced by the libva fallback.
- `docs/plan/02-architecture.md` §Bundled FFmpeg: the build confirmed, the shipped libva, what
  is bundled where.
- `docs/plan/07-desktop-app.md` D-7: the shipped folder, the done items.
