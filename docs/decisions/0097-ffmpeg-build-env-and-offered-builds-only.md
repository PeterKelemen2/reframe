# 0097 — REFRAME_FFMPEG_BUILD also replaces an unusable PATH FFmpeg; the API takes offered builds only

- Status: accepted
- Date: 2026-11-19
- Steps: S-8; supersedes item 3 of [0094](0094-docker-image-without-ffmpeg.md) and refines item 3
  of [0093](0093-ffmpeg-download-and-build-choice.md) for the API

## Context

Review R2 of S-8 (2026-11-18) found:

- `REFRAME_FFMPEG_BUILD` was skipped without a word when the FFmpeg in use came from `PATH` and
  was too old or broken (Debian 12 has FFmpeg 5.1, Ubuntu 24.04 has 6.1; Reframe needs 7.0),
  and when the process did not own the data folder. The start-up warning then told the admin
  to set the variable that was already set.
- `POST /api/system/tools/fetch` and `/tools/install-file` accepted any manifest build
  (`override-test` started a download), although 0093 item 3 offers only the `offered` builds.

## Decision

1. `REFRAME_FFMPEG_BUILD` downloads when discovery finds no **usable** FFmpeg at server start:
   none, or one from `PATH` that is too old or does not run (a downloaded build ranks above
   `PATH`). It never replaces an environment or Settings path, usable or not. A server that
   does not own the data folder downloads nothing.
2. Every skip is one log line with the reason and a `tools.fetch_skipped` problem; a wrong name
   is `tools.build_unknown`; a failed download is one line that points to the download's own
   error line. The start-up warning does not suggest the variable when it is set. With the
   variable set and a usable FFmpeg, one INFO line says that nothing is downloaded.
3. The API refuses a build that is not offered: 422 `tools.build_not_offered`. The CLI
   (`reframe tools fetch --build`) still takes every manifest build, for CI and development.

## Consequences

A Debian 12 or Ubuntu 24.04 bare-metal server with the distro's FFmpeg on `PATH` gets the pinned
build with the variable set. Built by the R2 fix round (merge 7e6e38cf).

## Plan changes

`06-web-app.md` S-8 (the `REFRAME_FFMPEG_BUILD` item, done in the fix round; the `install-file`
and `tools/fetch` items now name the 422); `docs/deployment.md` step 5.
