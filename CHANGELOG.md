# Changelog

All notable changes to Reframe. A version is the core's `__version__`, and its tag is `v` and
that version. From the second release on, each section is made by git-cliff from conventional
commits ([docs/release.md](docs/release.md)).

## [Unreleased]

## [0.9.0] - 2026-11-24

The first release, a rehearsal of the release before v1.0.0. The Windows installers are not
signed.

### Added

- Source information: commercial codec names, bitrates with their source, track roles such as
  commentary, SDH and signs with the evidence for each, and HDR10, HDR10+, HLG and Dolby
  Vision detection.
- Encoding with x264, x265, SVT-AV1 and the NVIDIA NVENC, Intel QSV, AMD AMF and VAAPI
  hardware encoders. Encoder detection runs in the background, and an unavailable encoder is
  explained and offers a fallback.
- Advanced options for x264, x265 and SVT-AV1, with search, help, a command preview and a dry
  run that checks custom parameters.
- Built-in presets modelled on HandBrake's, user presets, and preset import and export.
- A Range selector, dimensions and crop (automatic, conservative and manual, with a magnifier
  and a check on many frames), filters with a before and after preview, HDR to SDR tone
  mapping and a live preview clip.
- Audio and subtitle defaults with per-language codec and maximum bitrate rules, track names
  with templates, languages and flags, external subtitles, chapters and tags.
- Metadata changes written in place, and remux-only jobs, with Reframe's own Matroska header
  writer.
- Batch and season mode: groups of files, track rules, *Apply to group*, a per-file matrix and
  crop detection for each file.
- Output naming with every HandBrake variable and release-name parsing.
- A persistent queue with parallel jobs, pause, retry, logs, when-done actions and sleep
  inhibit while encoding.
- The `reframe` command line: `probe`, `plan`, `encode`, `batch`, `name`, `presets`, `queue`
  and `tools`.
- The web app for one user, with a login, and a Docker image.
- The desktop app for Linux (AppImage, deb, rpm) and Windows (NSIS installer and MSI), with
  an updater.
- FFmpeg is downloaded at the first start, with a choice of builds and a warning when a build
  does not suit the GPU driver.
- Keyboard navigation, and an accessibility check of each screen in Chromium, Firefox and
  WebKit.
