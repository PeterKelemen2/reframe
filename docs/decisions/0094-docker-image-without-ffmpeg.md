# 0094 — The Docker image contains no FFmpeg either

- Status: accepted
- Date: 2026-11-18
- Steps: S-6 (reopened), S-8, D-10; supersedes item 1's Docker part of
  [0093](0093-ffmpeg-download-and-build-choice.md)

## Context

[0093](0093-ffmpeg-download-and-build-choice.md) item 1 took FFmpeg out of the desktop packages
and kept the `default` build inside the Docker image (`docker/Dockerfile`'s `tools` stage,
`/opt/reframe/tools/ffmpeg/`). The owner (2026-11-18): the image should not contain FFmpeg
either, since it is downloaded anyway; the download goes to a bind-mounted folder.

The image already has one: `REFRAME_DATA_DIR=/data`, and the compose example mounts
`/srv/reframe/data:/data`. `reframe tools fetch` (and the first-run screen's download) installs
into `<data dir>/tools/ffmpeg/`, which is `/data/tools/ffmpeg/`: it survives a new container.
VAAPI in the container used the image's Debian 13 libva and Mesa / Intel drivers with the same
BtbN binary (audit D-16a, 2026-11-18), so a downloaded build needs no libva copy there.

## Decision

1. The image contains no FFmpeg: the `tools` stage goes, and nothing is installed in
   `/opt/reframe/tools/`. The GPU runtime packages (VA drivers, oneVPL GPU runtime) stay.
2. The first start with an empty `/data` shows the web app's first-run screen: *Download* an
   offered build into `/data/tools/ffmpeg/`, *Install from file* (an archive in a media root),
   or the existing override (`REFRAME_FFMPEG` / `REFRAME_FFPROBE` with a mounted build).
3. `REFRAME_FFMPEG_BUILD` (optional, not set by default): when set to an offered build's name and
   discovery finds no FFmpeg at server start, the server starts the download of that build (the
   same task as *Download*). For a server that should work without a first visit to the UI. A
   wrong name or a failed download is logged and shown on the first-run screen; the server
   starts anyway.
4. Licensing: no artefact of Reframe conveys FFmpeg any more. The image's notices drop it; the
   sources release of [0073](0073-gpl-corresponding-source-per-tool-pin.md) keeps the parts that
   are still conveyed (the AppImage's libraries, the image's Debian packages).

## Consequences

- The image is about 230 MB smaller. A first start needs the download (or a file, or a mounted
  build) before the first encode.
- A deleted or empty `/data` means a new download; the compose example says so.
- `/opt/reframe/tools/` stays a bundled root in discovery, so a user who mounts a build there
  still gets it as `bundled`.

## Plan changes

- `01-scope.md` §Constraints; `02-architecture.md` §Bundled FFmpeg (who bundles, install
  location); `06-web-app.md` S-6 (the image stages, reopened) and S-8 (`REFRAME_FFMPEG_BUILD`);
  `09-quality-and-release.md` §Licensing (the FFmpeg row); `08-roadmap.md` (the sources item);
  `README.md` (plan); [0093](0093-ffmpeg-download-and-build-choice.md) status line.
