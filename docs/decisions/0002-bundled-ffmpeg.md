# 0002 — The bundled FFmpeg, MKVToolNix and MediaInfo

- Status: accepted
- Date: 2026-11-12
- Steps: D-7, C-1, C-4

## Context

02 §Bundled FFmpeg: every package ships the FFmpeg pinned in `tools/ffmpeg.toml`, a GPL build
from an upstream release branch with libx264, libx265, libsvtav1, libopus, libplacebo + Vulkan,
libvpl (QSV), NVENC, AMF (Windows) and VAAPI (Linux), shared libraries, and it must run on the
oldest supported distro (Ubuntu 22.04, [0072](0072-m10-bundling-packaging-smoke-tests.md)
Decision 2). The first candidate is BtbN's release-branch `gpl-shared` build; D-7 confirms the
choice and tests it on the hosts that are available. 07 §Tool bundling also bundles
MKVToolNix (`mkvpropedit.exe`) and MediaInfo CLI on Windows, in the layout of
[0005](0005-tool-discovery-details.md) item 2.

The Windows build of the pin, BtbN n9.0.2 win64, crashes now and then with `0xC0000005` when
`fieldmatch` (Detelecine) runs before other filters ([0070](0070-windows-testing-phase.md)
"The desktop part": 2 of 40 runs). The owner's choice (0072, answer 2): try another Windows
build and switch the `windows-x64` pin only if it is clean and meets 02's requirements.

## Decision

1. **FFmpeg stays BtbN `autobuild-2026-09-30-13-08`, n9.0.2-17-g2a571b6068, `gpl-shared`, on
   both platforms.** No candidate is free of the crash (below), so the Windows pin does not
   change, the manifest keeps one `version` per build, and the crash stays a known limit.
   Retention (BtbN's README, checked 2026-11-12): the last build of each month stays for two
   years, so the pin should stay downloadable until about 2028-09. BtbN's repository moved to
   the organisation `FFmpeg-Builds/FFmpeg-Builds`; the pinned `github.com/BtbN/…` URLs
   redirect there (both checked 2026-11-12). The next re-pin should use the new URLs.
2. **MKVToolNix 103.0 and MediaInfo CLI 26.10 are pinned in `tools/bundled-tools.toml`**
   (Windows only; Linux packages use the distro's, `Recommends: mkvtoolnix, mediainfo`):
   - MKVToolNix: the portable `mkvtoolnix-64-bit-103.0.zip` (the site also offers a `.7z`;
     the `.zip` needs no extractor beyond Python's, so the Windows layout builds on Linux and
     Windows alike). SHA-256 `c860a10c…0417`, equal to the site's `<archive>.sha256`. Only
     `mkvpropedit.exe` (static, 22.5 MB; runs alone, checked on the VM), `doc/COPYING.txt`
     (GPL-2.0) and `doc/README.txt` (the third-party licences) are kept, not the 300-file
     archive.
   - MediaInfo: `MediaInfo_CLI_26.10_Windows_x64.zip`, SHA-256 `4cc94bd2…8a29`. MediaArea
     publishes no checksum: two downloads, on the VM on 2026-11-04 and on the host on
     2026-11-12, were equal. The archive has no top folder (`reframe.tools.fetch` now
     extracts such a zip). Kept: `MediaInfo.exe`, `LICENSE` (BSD-2-Clause) and
     `License.html`; not `LIBCURL.DLL` (MediaInfo reads local files without it; checked on
     the VM).
   - Both sites still list every release since their first, so the pins stay downloadable.
3. **`scripts/bundle-tools.py` is the CI step**: `uv run python scripts/bundle-tools.py
   --platform linux-x64|windows-x64 [--dest DIR]` lays out `ffmpeg/` (and on Windows
   `mkvtoolnix/`, `mediainfo/`) in `desktop/src-tauri/resources/tools/`, which the app ships
   as `<resources>/tools/`. One layout is for one build platform: the plan's
   `resources/tools/<os>/` is wrong (one build makes one platform's package), so there is no
   sub-folder per OS. Size and SHA-256 are checked before anything is extracted; a rerun keeps
   a folder whose files still match the hashes recorded at layout time (and the same list of
   kept files); another platform's folders are removed; a destination with files the script
   did not make is refused. On the platform it lays out, it runs tool discovery and requires
   each tool as `bundled` with its pinned version (so the Docker build of the oldest distro
   checks that FFmpeg runs there). The FFmpeg folder is the whole archive root, as `reframe
   tools fetch` installs it (234 MB on Linux, of which `ffplay`, `doc/`, `man/` and `include/`
   are about 42 MB): the tests run against the same layout that ships.
4. **`LIBVA_DRIVERS_PATH`** (the D-7 question of `status.md`): the core keeps setting the first
   distro driver folder that exists for the bundled FFmpeg on Linux. The BtbN build does not
   carry its own libva: it loads the system's `libva.so.2` at run time (implib-gen stubs), and
   that libva already looks in its distro's folder. On this host the encode works with and
   without the variable; in the Ubuntu 24.04 and Debian 13 containers too. So the variable is
   not needed on the tested distros and does no harm; it stays for distros whose libva looks
   elsewhere (not seen).
5. **New capability reasons** (`reframe/capabilities/reasons.py`) for what the host tests
   found reported as `error`:
   - libplacebo without a Vulkan loader (the Windows VM has no `vulkan-1.dll`; a container
     without `libvulkan1`): "No Vulkan runtime, or one too old for libplacebo (Vulkan 1.0.0,
     needs 1.2.0)", state `unavailable`. The same rule for the device API text.
   - The system's libva too old for the build (the stub aborts with SIGABRT): "The system's
     libva.so.2 is too old for this FFmpeg build (it has no vaMapBuffer2)".
   - A system library the build loads is missing (QSV without `libva-drm2`): "The system
     library libva-drm.so.2 is not installed".

### The Windows build: the crash runs

The VM `win10` (Windows 10 Pro 22H2, 6 processors of a Ryzen 5 5600, no GPU), the command of
`test_every_filter_on_an_untagged_interlaced_source` with Detelecine (`fieldmatch,decimate,
idet,bwdif,…` on `interlaced.mkv`, libx264 ultrafast), run one after another from Git Bash
(which shows `0xC0000005` as exit 139). Every candidate's `-buildconf` has `--enable-gpl
--enable-version3 --enable-shared`, libx264, libx265, libsvtav1, libopus, libplacebo, Vulkan,
libvpl, AMF and ffnvcodec (NVENC); every archive's SHA-256 matched its publisher's.

| Build | Crashes |
|-------|---------|
| BtbN `autobuild-2026-09-30-13-08`, n9.0.2-17 (the pin; baseline) | 2 of 400 |
| BtbN `autobuild-2026-10-31-12-59`, n9.0.2-39 (the newest month-end build of `release/9.0`) | 5 of 400 |
| gyan.dev 9.0.2 `full_build-shared` (GitHub `GyanD/codexffmpeg` release `9.0.2`) | 4 of 400 |
| The pin with `-filter_threads 1` | 0 of 400 |
| The pin, the chain without `decimate` (crashes more often, 0070) | 11 of 400 |
| The pin, the chain without `decimate`, with `-filter_threads 1` | 16 of 400 |
| The pin's Linux build on the host (same CPU) | 0 of 400 |

Two builds from different build systems crash alike, and the Linux build does not: the defect
is in FFmpeg's Windows code path, not in one build. One filter thread is no workaround: the
chain without `decimate` crashes as often with it. Not tried: an MSVC build
(none found that is GPL, shared and has all of 02's libraries).

## Host tests

Each host: the bundled layout by `scripts/bundle-tools.py`, Reframe from this branch with
private config, data and cache folders (`REFRAME_DATA_DIR/tools` holding the layout, so
discovery finds it as `bundled`), `uv run python -m reframe.tools`, `uv run reframe encoders
--json`, and real encodes through the queue (`reframe encode --in-process`) of
`multitrack.mkv` (1 video, 3 audio, 3 subtitle tracks) with a user preset per encoder: MKV,
640×360 at most, Opus audio. Each output probed with the bundled ffprobe.

**This host: CachyOS (Arch), kernel 7.3.1, AMD RX 7600, Mesa 26.2.5, libva 2.24.1,
`amf-amdgpu-pro` 25.10** (2026-11-12). Discovery: ffmpeg and ffprobe `bundled`
n9.0.2-17-g2a571b6068-20260930, mkvpropedit from `PATH` (103.0), MediaInfo missing (not
installed). Detection: every software encoder, `h264/hevc/av1_vaapi`, `h264/hevc/av1_amf`
available; NVENC "NVIDIA driver not found", QSV "No Intel QSV device (needs an Intel GPU with
its media driver)"; libplacebo works. Encodes: libx264, libx265, libsvtav1, h264/hevc/av1_vaapi
and h264/hevc/av1_amf all done, each with three Opus tracks (av1_amf pads 320×180 to 320×192,
the known limit of [0010](0010-definitions-filters-and-containers.md)).

**Debian 13 container with `/dev/dri`** (Docker, `--device /dev/dri --group-add render`;
`mesa-va-drivers` 25.0.7, libva 2.22.0, `libvulkan1` and `mesa-vulkan-drivers`; glibc 2.41).
Discovery: ffmpeg and ffprobe `bundled`. Detection: software and `h264/hevc/av1_vaapi`
available; AMF "AMD AMF runtime not found (libamfrt64.so.1)"; NVENC and QSV as above;
libplacebo works. Encodes: libx264, libx265, libsvtav1, h264/hevc/av1_vaapi done.

**Ubuntu 24.04 container with `/dev/dri`** (`mesa-va-drivers` 25.2.8, libva 2.20.0, glibc
2.39). Discovery: `bundled`. Detection: software available; **VAAPI unavailable: "The system's
libva.so.2 is too old for this FFmpeg build (it has no vaMapBuffer2)"** (before this record:
`error`, "FFmpeg crashed during the test encode (signal 6)"); AMF "AMD AMF runtime not found
(libamfrt64.so.1)"; libplacebo "No Vulkan runtime, or one too old for libplacebo (Vulkan 1.0.0,
needs 1.2.0)" (no `libvulkan1` installed). Encodes: libx264, libx265, libsvtav1 done; an
h264_vaapi job is refused by validation with the libx264 fix.

**Ubuntu 22.04 container** (no `/dev/dri`, glibc 2.35, the oldest supported distro).
Discovery: `bundled`. Encodes: libx264, libx265, libsvtav1 done. VAAPI "No VAAPI device (no
render node in /dev/dri)". QSV without `libva-drm2`: "The system library libva-drm.so.2 is not
installed" (before: "FFmpeg crashed", signal 6). With `/dev/dri` and libva 2.14 the VAAPI test
aborts the same way as on 24.04 (checked with the FFmpeg command alone).

**The Windows VM** (`win10`, Windows 10 Pro 22H2 19045, no GPU, no Vulkan loader; Python 3.14,
over SSH). The layout built on the VM by the script (FFmpeg, MKVToolNix, MediaInfo; the
MediaInfo download needed `SSL_CERT_FILE`, see Consequences). Discovery: all four tools
`bundled` (ffmpeg/ffprobe n9.0.2-17-g2a571b6068-20260930, mkvpropedit 103.0, mediainfo 26.10),
also with MKVToolNix and MediaInfo installed on `PATH`. Detection: software encoders available;
NVENC "NVIDIA driver not found", QSV "No Intel QSV device (needs an Intel GPU with its media
driver)", AMF "AMD AMF runtime not found (amfrt64.dll)", VAAPI "Not available on Windows";
libplacebo "No Vulkan runtime, or one too old for libplacebo (Vulkan 1.0.0, needs 1.2.0)"
(before: `error`); no crash, no hang. Encodes: libx264, libx265, libsvtav1 with Opus done;
h264_nvenc, hevc_amf and av1_qsv jobs refused by validation with a software fix.
`capabilities/test_real.py::test_libplacebo_without_a_vulkan_driver` passes there.

**Not verified**: Intel (VAAPI with the iHD driver, QSV), NVIDIA (NVENC, on Linux and
Windows), Windows with a GPU (AMF, NVENC, QSV, libplacebo), Fedora (the plan's second Linux
family; Arch stands in), a real install of the packages (D-8), the GitHub runners.

## Consequences

- **VAAPI does not work with the bundled build on Ubuntu 22.04 and 24.04 LTS and Debian 12**
  (libva 2.14, 2.20, 2.17; each checked in a container with `/dev/dri`): the build calls
  `vaMapBuffer2`, which those lack and libva 2.22 (Debian 13) has. Settings shows the
  reason; software encoders, NVENC and AMF are not affected. The plan's remedy (07, risk
  table: point the override to the distro FFmpeg) does not help there: those distros' FFmpeg
  (4.4.2, 6.1.1, 5.1.9; `apt-cache policy ffmpeg`) is below Reframe's minimum 7.0. A fix needs
  a build that checks the libva version at run time (to report upstream to BtbN / FFmpeg) or
  a newer libva on the host. Known limit.
- The Windows Detelecine crash stays a known limit ([0070](0070-windows-testing-phase.md)):
  2 of 400 runs here. A job fails as "ffmpeg crashed"; a retry usually works.
- On a Windows that has not yet fetched the SSL.com / SecureTrust root (Windows fetches roots
  on demand, Python does not trigger it), the MediaInfo download fails with
  `CERTIFICATE_VERIFY_FAILED`; `SSL_CERT_FILE` set to certifi's bundle (`uv run python -m
  certifi`) fixes it. The GitHub runner's store is not checked.
- The `.deb` / `.rpm` put `bundle.resources` in `/usr/lib/Reframe/` (Tauri's `productName`,
  `testdata/README.md` "The sidecar build and its packages"), so the bundled FFmpeg is in
  `/usr/lib/Reframe/tools/ffmpeg/`; the core finds it next to the sidecar
  (`<exe dir>/../tools`). The plan's `/usr/lib/reframe/tools/ffmpeg/` is corrected.

## Plan changes

- `docs/plan/07-desktop-app.md` §Tool bundling (the `.deb`/`.rpm` folder) and §D-7 (bullet 1
  done; bullet 2: `resources/tools/` per build platform, not `resources/tools/<os>/`).
- `docs/plan/02-architecture.md` §Bundled FFmpeg: the `.deb`/`.rpm` install location; the build
  choice is confirmed here.
