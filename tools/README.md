# tools

Pinned third-party tool builds. Plan: [02 §Bundled FFmpeg](../docs/plan/02-architecture.md#bundled-ffmpeg),
`Q-1.2` in [09](../docs/plan/09-quality-and-release.md), `D-7` in [07](../docs/plan/07-desktop-app.md).

| File | Content |
|------|---------|
| `ffmpeg.toml` | The FFmpeg build that ships (`default`) and a second build for the CI job that tests the path override (`override-test`). For each platform: URL, SHA-256, size, archive layout. Also the exact version string, licence and the source commits (GPL source obligations). |
| `libva.toml` | Linux: the libva source that `scripts/bundle-tools.py` builds in Ubuntu 22.04 and ships in `tools/ffmpeg/libva/`, for distros whose own libva is too old for the FFmpeg build ([decision 0002](../docs/decisions/0002-bundled-ffmpeg.md)). URL, SHA-256, size, the driver folders it searches. |
| `mkvtoolnix.toml` | Windows: the MKVToolNix portable zip; only `mkvpropedit.exe` and the licence ship. URL, SHA-256, size, the source archive. |

MediaInfo ships inside the sidecar (pymediainfo's library), so it has no pin here.

## Bundle the tools for the desktop app

```sh
uv run --no-project python scripts/bundle-tools.py                          # host platform
uv run --no-project python scripts/bundle-tools.py --platform windows-x64   # from Linux too
```

It writes `desktop/src-tauri/resources/tools/` (the app maps it to `tools/`, one folder above
the sidecar): `ffmpeg/` with only `ffmpeg`, `ffprobe`, the libraries (on Linux each under its
soname, without links) and `LICENSE.txt`; on Linux `ffmpeg/libva/`; on Windows `mkvtoolnix/`;
and `bundle.json` with the versions. Downloads are kept in `.tools/` and checked against their
SHA-256 on every run. On Linux the libva build runs in Docker (`--libva-build native` inside an
`ubuntu:22.04` job with meson, ninja, gcc and libdrm-dev; `skip` leaves it out).

## Fetch a build

```sh
uv run python scripts/fetch-tools.py                          # default build, host platform
uv run python scripts/fetch-tools.py --build override-test
uv run python scripts/fetch-tools.py --platform windows-x64   # download + verify only
```

The script downloads the archive into `.tools/` (git-ignored), checks the size and SHA-256
**before** it extracts, extracts safely, runs `ffmpeg -version` and `ffprobe -version` to check
the pinned version (host platform only), and prints the absolute `bin` folder on stdout. A second
run only re-hashes the extracted files and skips the download. It uses only the standard library.

Layout: `.tools/ffmpeg/<build>-<platform>/<archive root>/bin/`. Keep the archive layout: on
Linux the binaries load the shared libraries from `../lib` (RPATH `$ORIGIN/../lib`); on Windows
the DLLs are next to the `.exe` files.

## Where the builds come from

[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), release-branch `gpl-shared`
variant, confirmed in [decision 0002](../docs/decisions/0002-bundled-ffmpeg.md), which lists
the hosts it was tested on.

**Retention.** BtbN keeps the last build of each month for two years and only the last 14 daily
builds. The `latest` release floats. So:

- Pin only a **month-end** `autobuild-YYYY-MM-DD-HH-MM` release (the last build of a month).
  Never pin `latest` or a mid-month daily build: it is deleted after 14 days and CI breaks.
- The current pin, `autobuild-2026-09-30-13-08`, should stay available until about 2028-09.
  Re-pin before then, or mirror the archives (for example as release assets of this repository)
  and change the URLs. The SHA-256 values do not change when the URL changes.

## Update a pin

1. List the releases: `curl -s "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases?per_page=100"`.
   Choose the newest month-end `autobuild-…` release.
2. In that release, find the `ffmpeg-n<X.Y.Z>-…-linux64-gpl-shared-<X.Y>.tar.xz` and
   `…-win64-gpl-shared-<X.Y>.zip` assets. Download both and compute the SHA-256 yourself.
   Compare with the release's `checksums.sha256` (and the `digest` field of the API).
3. Update `url`, `sha256`, `size` and `root` (the top folder of the archive) for each platform.
4. Update `version` (the exact string after `ffmpeg version ` in `ffmpeg -version`, including
   the `-YYYYMMDD` suffix), `release_version`, `release_tag`, `release_url`, `checksums_url`,
   `source_commit` (the full FFmpeg commit from the `-g<hash>` part of the version) and
   `build_scripts_commit` (the BtbN commit that the release tag points to).
5. Copy the file to `packages/reframe/src/reframe/tools/ffmpeg.toml`: the installed package
   reads that copy for `reframe tools fetch` (decision 0038), and a test fails while the two
   differ.
6. Run `uv run python scripts/fetch-tools.py` for both builds, and `uv run pytest`.
   The CI caches of `.tools/` and `testdata/media/` are keyed on this file, so they refresh.

## Licence

The builds use `--enable-gpl --enable-version3`: **GPL-3.0-or-later**. Each archive contains
`LICENSE.txt`. Every artefact that bundles a build must ship that licence and the corresponding
source (or a written offer) for the exact build: the FFmpeg commit in `source_commit` and the
BtbN build scripts at `build_scripts_commit`, which pin the source of every dependency
(see [09 §Licensing](../docs/plan/09-quality-and-release.md#licensing)).
