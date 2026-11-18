# 0093 — The desktop app downloads FFmpeg; a build picker and a build-mismatch warning

- Status: accepted; item 1's Docker part (the image keeps FFmpeg) is superseded by [0094](0094-docker-image-without-ffmpeg.md)
- Date: 2026-11-18
- Steps: C-21, S-8, F-20, D-10 (new); supersedes the "every artefact bundles FFmpeg" part of
  [0002](0002-bundled-ffmpeg.md) and [02 §Bundled FFmpeg](../plan/02-architecture.md#bundled-ffmpeg)

## Context

[02 §Bundled FFmpeg](../plan/02-architecture.md#bundled-ffmpeg) and
[01 §Constraints](../plan/01-scope.md#constraints) say that every artefact (the Docker image, the
Linux packages, the Windows installers) bundles the same pinned FFmpeg, the `default` build of
`tools/ffmpeg.toml` (BtbN, release/9.0, n9.0.2).

On 2026-11-18 the owner tested Reframe on a Windows 10 VM with an NVIDIA GeForce GTX 1050 Ti
(Pascal) and driver 582.78 (dockur/windows, GPU passthrough):

- `reframe encoders` with the pinned build: `hevc_nvenc — unavailable: NVIDIA driver too old:
  NVENC needs driver 610.00 or newer` (the same for `h264_nvenc` and `av1_nvenc`). FFmpeg's own
  text: `Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0`,
  `The minimum required Nvidia driver for nvenc is 610.00 or newer`.
- To our knowledge NVIDIA's 580 driver branch is the last one for GeForce 10 (Pascal) and older
  cards, so such a card never gets driver 610: with the bundled build it has no NVENC at all.
- The `override-test` build of the same manifest (BtbN, release/8.1, n8.1.3, the same
  autobuild) works with that driver: real encodes through Reframe's queue gave `h264_nvenc`,
  `hevc_nvenc` (also 10-bit Main 10, and 4K HDR10 with the mastering display and light level
  kept), 2-pass, the tunes `ll` / `ull` / `lossless`, and HDR → SDR tone mapping with
  libplacebo and with `zscale`. `reframe encoders` with it: `h264_nvenc — available (8-bit
  only)`, `hevc_nvenc — available`, `av1_nvenc — unavailable: No NVIDIA GPU that can encode AV1`.

The owner's answers (2026-11-18): a user whose system does not fit the pinned build must be told
so, and must be able to choose their own build. Instead of bundling, Reframe offers a choice of
builds and downloads the chosen one at the first run. Internet is not required: without a
connection Reframe says so and suggests the user's own build. The warning applies only when an
encoder is wholly unavailable: a 10-bit-only limit leaves the encoder usable in 8-bit and is not
a build mismatch.

Facts that the design must keep:

- `reframe tools fetch --build NAME` already downloads a pinned build, checks its size and
  SHA-256 before it extracts anything, checks `ffmpeg -version`, and installs it as the
  `bundled` build in `<data dir>/tools/ffmpeg/`; the server has `POST /api/system/tools/fetch`
  and the first-run screen already offers this download when no FFmpeg is found.
- On Linux, the BtbN build's VAAPI needs a newer libva than Ubuntu 22.04 / 24.04 and Debian 12
  have. Today `scripts/bundle-tools.py` builds libva from its pin into the bundled FFmpeg's
  `lib/`; `reframe tools fetch` does not, so a downloaded build has no VAAPI on those distros.
- BtbN keeps a month-end build for two years (`tools/ffmpeg.toml` header), so a pin must be
  renewed (or mirrored) before then.

## Decision

1. **The desktop packages contain no FFmpeg.** The AppImage, .deb, .rpm, NSIS and MSI installers
   ship without it. The first run offers the builds to download (item 3) or the user's own
   FFmpeg (Settings → Tools path). **The Docker image keeps the `default` build** inside: a
   server image is pulled from the network anyway, has no screen to choose a path on, and its
   GPU documentation relies on the known build. A bare-metal server is unchanged (`reframe tools
   fetch`, or `REFRAME_FFMPEG`).
2. **The Linux packages keep libva** (built from its pin, MIT). When a build is downloaded on
   Linux and the app has a packaged libva, the libva libraries are copied into the installed
   build's `lib/`, the layout that the packages use today. A build installed without it (the
   CLI from source, a bare-metal server) works as today: VAAPI then depends on the system's
   libva, and a too-old one is a build mismatch (item 6).
3. **Offered builds.** `tools/ffmpeg.toml` marks the builds that users may choose and gives each a
   label and a one-line summary of who it is for:
   - `default`: the build Reframe is tested with (release/9.0). Its summary says that NVENC needs
     NVIDIA driver 610 or newer.
   - `compat`: release/8.1 from the same autobuild, for NVIDIA drivers older than 610 (GeForce 10
     and older). It is the pin that `override-test` uses today; the override-path tests may keep
     using it under either name. Only what was checked is claimed: driver 582.78 on a GTX 1050 Ti.
   No other version is offered: Reframe's encoder and filter definitions are tested against the
   pinned builds. Any other FFmpeg stays possible through the path override.
4. **Download, from a file, or your own.** The first-run screen and Settings → Tools offer:
   *Download* an offered build; *Install from file* (an archive downloaded on another computer:
   the same size and SHA-256 checks against the manifest); and, on the desktop, *Choose path*
   (web mode: the existing note that the server's environment or settings file sets it). A
   download that cannot reach the server is reported as such (`tools.fetch_offline`: no network
   or name resolution, refused or timed-out connection), with these alternatives; other failures
   keep their reasons (checksum, size, archive, version).
5. **A downloaded build that is not this release's pin.** After an app update whose manifest pins
   another build, the installed downloaded build is reported as `outdated` (its version is not
   the pinned version of the build it was installed as). Settings → Tools and the first-run check
   show a notice with *Download* for the pinned build. It does not block: the old build keeps
   working until the user acts.
6. **The build-mismatch warning.** `EncoderStatus` gets `build_mismatch: bool` (default `false`):
   `true` when the encoder is unavailable because this FFmpeg build needs newer system software
   than the computer has, so another build or a system update can make it available. It is set
   from the reason mapping for: the NVENC API / driver version (`nvenc API version`, `minimum
   required Nvidia driver`), and a system library too old or missing for the build (the
   `implib-gen` stubs). Never for a 10-bit-only limit (`reason_10bit`, AMD's 10-bit driver
   message), and never for filters (libplacebo falls back to `zscale`). Where it shows:
   - the encoder's reason text, unchanged, plus a hint in the UI and the CLI;
   - the missing-encoder banner on the Video tab and the Summary issue: a *Use another FFmpeg…*
     action that opens Settings → Tools. It is a UI action next to *Check again*, not a `Fix`:
     a new `FixTarget` would change a persisted model (queue issues);
   - Settings → Tools: a notice that names each such encoder with its reason and offers the other
     offered builds, *Install from file* and the path;
   - CLI: `reframe encoders` and `reframe tools status` print one hint line after the list, e.g.
     `hint: hevc_nvenc needs newer system software than this FFmpeg build expects: update the
     driver, or use another build (reframe tools fetch --build compat, or REFRAME_FFMPEG /
     tools.ffmpeg).`
   No start-up toast (the owner's choice).
7. **Licensing.** The desktop packages no longer convey FFmpeg, so their notices drop it and the
   GPL corresponding-source release of [0073](0073-gpl-corresponding-source-per-tool-pin.md) is
   needed for the Docker image's build only. The build picker shows each build's licence
   (`GPL-3.0-or-later`) and its source links from the manifest before the download.
8. **Tests and CI.** Tests keep using the pinned build from `.tools/` (`scripts/fetch-tools.py`).
   The package builds stop putting FFmpeg into `resources/tools/` (libva stays on Linux). The
   desktop smoke test (D-9) starts with no FFmpeg, sees the first-run screen offer the builds,
   and installs the `default` build from a local archive (*Install from file*, from the CI cache)
   so that it does not depend on GitHub's download servers.

## Consequences

- Installers lose about 200 MB. The first run needs a download (or a file, or a path) before the
  first encode; until then the app is usable for presets and settings, as on the repair screen.
- A GeForce 10 user can use NVENC with the `compat` build, and every user whose system does not
  fit a build is told what to do instead of seeing only a reason.
- Reframe now depends on BtbN's release assets staying online for a fresh install (two years for
  a month-end build): re-pin before then, or mirror the archives with each Reframe release.
- The D-7 and D-8 items that bundled FFmpeg into the packages are replaced by D-10; the M10
  release checklist's GPL-sources item applies to the Docker image only.
- Not decided here: mirroring the archives; offering more builds (a new `compat` when `default`
  moves on).

## Plan changes

- `01-scope.md`: §Constraints (the bundling bullet); open question 2's default text.
- `02-architecture.md`: §Bundled FFmpeg (who bundles, install location, the download, the
  path-override table's row 3).
- `03-features.md`: §Video "Missing encoder behaviour" (a row for a build mismatch); §Settings
  (the Tools row).
- `05-core.md`: new step C-21.
- `06-web-app.md`: new step S-8 (Part A) and F-20 (Part B); the `tools/fetch` route row.
- `07-desktop-app.md`: §Tool bundling; new step D-10.
- `08-roadmap.md`: M10's steps.
- `09-quality-and-release.md`: §Licensing (the FFmpeg row).
- `README.md` (plan): the FFmpeg distribution line.
- [0002](0002-bundled-ffmpeg.md): status line (superseded in part).
