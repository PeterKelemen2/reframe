# Changelog

All notable changes to Reframe. A version is the core's `__version__`, and its tag is `v` and
that version. From the second release on, each section is made by git-cliff from conventional
commits ([docs/release.md](docs/release.md)).

## [Unreleased]

## [0.10.0] - 2026-11-24

### Added

- A preview clip is kept for each frame, clip length and set of job settings: another frame or
  a changed setting hides it, and going back shows it again, for an easy comparison. The frames
  of *Compare frames* are decoded once per clip.
- The web app shows the preview large in a modal (the desktop app opens it in its own window).
- Audio and subtitle defaults applied to a job stay with it while it is open: the preset shows
  *modified*, the dialog opens with them again, and *Save as new preset* keeps them.
- The Summary's Output card shows the output name, folder and path first, then the container
  and its options, then the naming; the variables and the parsed name start folded.
- The Summary's top row gives Source, Job type and Picture pipeline (with Video under it) parts
  of 3, 2 and 1 on a wide screen, and the source picture takes the card's width.
- `docker/compose.nvidia.yml`: the published image on an NVIDIA host, with the drives under one
  folder read and written in place.
- The Docker image carries the app icon for log viewers such as Dozzle.

### Fixed

- Encoding progress stayed at 0 % with the `compat` FFmpeg build when a subtitle track started
  late; it now counts the frames when FFmpeg reports no position.
- A changed output folder in Settings did not reach an open file, which also called the old
  folder "chosen for this file". The file now offers the new folder.
- The defaults dialog's preview lists the tracks in the order they are written.
- The web app had no favicon.
- The Docker image's health checks no longer fill the server's console.
- A track row's number, buttons, drag handle and check box are centred on its source field.
- The web app's clip button says that it opens the clip in a new tab.
- The preview column fits the clip lengths and *Encode preview* on one row.
- The highlight of a field reached through a link fades in and out instead of vanishing.
- The corners of button groups are concentric with their selected button.

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
