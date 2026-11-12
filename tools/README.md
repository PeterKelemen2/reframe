# tools

Pinned third-party tool builds. Plan: [02 §Bundled FFmpeg](../docs/plan/02-architecture.md#bundled-ffmpeg),
`Q-1.2` in [09](../docs/plan/09-quality-and-release.md), `D-7` in [07](../docs/plan/07-desktop-app.md).

| File | Content |
|------|---------|
| `ffmpeg.toml` | The FFmpeg build that ships (`default`) and a second build for the CI job that tests the path override (`override-test`). For each platform: URL, SHA-256, size, archive layout. Also the exact version string, licence and the source commits (GPL source obligations). |
| `bundled-tools.toml` | The MKVToolNix (`mkvpropedit.exe`) and MediaInfo CLI builds that the Windows package ships (Linux packages use the distro's), and the libva source that the Linux layout builds into FFmpeg's `lib/`: URL, SHA-256, size, archive layout, the files kept, licence and source links. |

## Lay out the bundled tools of a package

```sh
uv run python scripts/bundle-tools.py --platform linux-x64     # or windows-x64
```

The script puts the `default` FFmpeg build (and, for `windows-x64`, MKVToolNix and MediaInfo)
into `desktop/src-tauri/resources/tools/` (`--dest DIR` for another folder): `ffmpeg/`,
`mkvtoolnix/`, `mediainfo/`, each with its licence file (decision 0005's layout). It checks each
archive's size and SHA-256 before it extracts anything, keeps a folder whose files still match
on a rerun, removes another platform's folders, and refuses to touch a destination that holds
files it did not make. On the platform it lays out, it then runs tool discovery and checks that
every tool is found as `bundled` with its pinned version. The Windows layout can be made on
Linux; the Linux layout needs a Linux host (the archive has symbolic links) with meson,
ninja, pkg-config, gcc and libdrm's headers (`apt install meson ninja-build pkg-config gcc
libdrm-dev`), because it builds libva from source (DRM only) into `ffmpeg/lib/`: the distros'
older libva lacks functions the FFmpeg build calls. Build the Linux layout on the oldest
supported distro (Ubuntu 22.04): the libva library needs that host's glibc.

Keep the libva pin at the newest libva release: libva does not load a VA driver built against
a newer VA-API than its own.

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

[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) (moved to
`github.com/FFmpeg-Builds/FFmpeg-Builds`; the old URLs redirect), release-branch `gpl-shared`
variant. [Decision 0002](../docs/decisions/0002-bundled-ffmpeg.md) confirms the choice, with
the host tests and the Windows builds that were tried instead.

**Retention.** BtbN keeps the last build of each month for two years and only the last 14 daily
builds. The `latest` release floats. So:

- Pin only a **month-end** `autobuild-YYYY-MM-DD-HH-MM` release (the last build of a month).
  Never pin `latest` or a mid-month daily build: it is deleted after 14 days and CI breaks.
- The current pin, `autobuild-2026-09-30-13-08`, should stay available until about 2028-09.
  Re-pin before then, or mirror the archives (for example as release assets of this repository)
  and change the URLs. The SHA-256 values do not change when the URL changes.

## Update a pin

FFmpeg (`ffmpeg.toml`):

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

MKVToolNix and MediaInfo (`bundled-tools.toml`):

1. Find the newest release: <https://mkvtoolnix.download/windows/releases/> (the portable
   `mkvtoolnix-64-bit-<version>.zip`) and <https://mediaarea.net/download/binary/mediainfo/>
   (`MediaInfo_CLI_<version>_Windows_x64.zip`).
2. Download the archive and compute the SHA-256 yourself. MKVToolNix publishes
   `<archive>.sha256` next to it: compare. MediaArea publishes no checksum: download it a second
   time on another day (or another machine) and compare.
3. Update `version` (what `mkvpropedit --version` / `mediainfo --Version` prints), the URLs,
   `sha256`, `size`, `root` and `files` (the binary, what it loads, the licence files), and the
   source links.
4. Run `uv run python scripts/bundle-tools.py --platform windows-x64` (on Windows it also checks
   the versions through tool discovery).

## Licence

FFmpeg: the builds use `--enable-gpl --enable-version3`: **GPL-3.0-or-later**. Each archive contains
`LICENSE.txt`. Every artefact that bundles a build must ship that licence and the corresponding
source (or a written offer) for the exact build: the FFmpeg commit in `source_commit` and the
BtbN build scripts at `build_scripts_commit`, which pin the source of every dependency
(see [09 §Licensing](../docs/plan/09-quality-and-release.md#licensing)).

libva (Linux layout) is MIT (`COPYING`, shipped as `ffmpeg/LICENSE-libva.txt`); its source is
the release tarball the pin names.

MKVToolNix is GPL-2.0-only (`doc/COPYING.txt`; `doc/README.txt` lists the licences of its
third-party parts); its source is the release tarball in `source_url`. MediaInfo is
BSD-2-Clause (`LICENSE`; `License.html` lists the third-party libraries built into it). The
bundle leaves out `LIBCURL.DLL`: MediaInfo needs it only to read URLs.
