# 0079 — Q-5: the release process

- Status: accepted
- Date: 2026-11-14
- Steps: Q-5 (D-7, D-8, S-6; 0073)

This is not legal advice. Review it before any public or commercial distribution.

## Context

[09 §Q-5](../plan/09-quality-and-release.md#q-5-release-process):

> - Semantic versioning. One version source (core `__version__`). The server, frontend and Tauri
>   versions are stamped from it at build time.
> - Changelog from conventional commits.
> - A release workflow on tag `v*` builds: the Docker image → GHCR (`linux/amd64`, `linux/arm64`
>   without HW encoders); Windows NSIS (+ MSI) and Linux AppImage/deb/rpm → GitHub Release,
>   signed; the updater manifest `latest.json`; the sources release of
>   [0073](0073-gpl-corresponding-source-per-tool-pin.md); optional: the `reframe` wheel to PyPI.

What exists (2026-11-14, `m10-hardening` at fdd9702):

- Versions: `reframe.__version__ = "0.1.0.dev0"` (hatch reads it for the `reframe` wheel);
  `reframe-server` has its own hatch version source; `frontend/package.json` is `0.0.0`;
  `desktop/package.json`, `desktop/src-tauri/tauri.conf.json` and `Cargo.toml` are `0.1.0`.
  Nothing ties them together.
- Commits name the plan step first (`F-17: …`, `docs: …`, merges); they are not conventional
  commits, so no tool can make a changelog from them as they are.
- Builds: the Linux packages (`desktop/packaging/linux/build.sh`, in a digest-pinned Ubuntu
  22.04 image), the Windows installers (NSIS per-user, MSI per-machine, test-signed on the VM),
  the updater (checked against a test release: 0072 "Task W"), the Docker image
  (`docker/Dockerfile`, digest-pinned Debian trixie; S-6), `scripts/third-party-notices.py`
  (in the desktop packages, not in the Docker image). No workflow builds any of them.
- FFmpeg pins: `linux-x64` and `windows-x64` only (`tools/ffmpeg.toml`).
- 0073 left to Q-5: what the BtbN scripts pin for each dependency, whether to pin the AppImage's
  build image (it is pinned by digest already), and how the Docker image's distro packages are
  covered.
- Nothing is pushed, so no workflow has run on GitHub (Q-1.1 "Done, never run").

## Decision

The owner's answers (2026-11-14): conventional commits from now on; Windows code signing when
the certificate secrets are set; an arm64 FFmpeg pin; no PyPI for v1.

1. **One version source.** `reframe.__version__` (PEP 440, e.g. `1.0.0`, `1.1.0rc1`). A script
   stamps it into `reframe-server`'s version, `frontend/package.json`, `desktop/package.json`,
   `tauri.conf.json` and `Cargo.toml`/`Cargo.lock` (SemVer spellings where a tool needs them:
   `1.1.0rc1` → `1.1.0-rc.1`), and checks that they agree (`--check`, run in CI). The release
   workflow refuses a tag `vX` that is not the stamped version. The frontend gets the version
   at build time (Vite `define`), so the UI and the diagnostics report show the same one.
2. **Conventional commits, with the step ID as scope.** From now on a commit subject is
   `type(scope): subject`, `type` one of `feat`, `fix`, `perf`, `refactor`, `test`, `docs`,
   `build`, `ci`, `chore`, `revert`; the scope is the plan step when there is one
   (`fix(F-17): …`, `feat(Q-5): …`), else an area (`docs(status): …`). `CLAUDE.md`'s commit rule
   says so. Merge commits stay as git writes them. The older history is not rewritten.
3. **The changelog** is made by git-cliff (a pinned version) from the commits since the last
   `v*` tag: `feat` → Added, `fix` → Fixed, `perf` → Performance, a `!` or `BREAKING CHANGE:`
   footer → Breaking; `docs`, `test`, `ci`, `chore`, `build`, `refactor` and merges are left
   out. Before the first `v*` tag the older commits are not conventional: the first release's
   section is written by hand from `docs/status.md`. `CHANGELOG.md` is committed; the release
   notes are that version's section.
4. **The sources release (0073)** is built by two scripts: one writes the source manifest (the
   FFmpeg commit and each dependency the BtbN scripts pin, for every FFmpeg platform that ships;
   MKVToolNix and MediaInfo for Windows; libva; the Debian/Ubuntu source package and version of
   each library linuxdeploy copies into the AppImage, read with `dpkg` in the build image), the
   other fetches one archive per entry, checks each against the pin, and writes `SHA256SUMS`.
   What the BtbN scripts pin and how to fetch exactly that source is checked against the real
   repository and recorded here (task S).
5. **The Docker image's distro packages** are not re-hosted. The image carries
   `THIRD_PARTY_NOTICES` (as the desktop packages do), which names the sources release (for the
   bundled FFmpeg) and lists each Debian package installed in the runtime image with its source
   package, version and its `snapshot.debian.org` source link; the base image is pinned by
   digest. (Debian keeps every source version on snapshot.debian.org.)
6. **arm64.** `tools/ffmpeg.toml` gets BtbN's `linuxarm64` `gpl-shared` build of the same
   source commit. The Docker image is built for `linux/amd64` and `linux/arm64` with buildx;
   arm64 has software encoders only (no VAAPI/QSV/NVENC claimed). Its sources are in the
   manifest.
7. **The release workflow** (`.github/workflows/release.yml`, on a `v*` tag): check the tag
   against the stamped version → the sources release (made if its tag does not exist, never
   "latest", no `v`) → in parallel: the Linux packages, the Windows installers, the Docker image
   (both platforms, to GHCR) — each with the notices that name the sources release → the
   updater's `latest.json` → a GitHub release with the packages, `latest.json`, the changelog
   section and the sources link. Windows code signing runs when the certificate secrets are
   set; without them the installers are unsigned and the release notes say so. The updater
   signature (the Tauri key secret) is required: the workflow fails without it. A release
   procedure (`docs/release.md`) lists the steps and the secrets.
8. **No PyPI wheel for v1.** The core's Python API is not promised as stable.

## Consequences

- Nothing in this step can run on GitHub before a push: the workflow is checked with
  actionlint and each script it calls is tested locally; the first real run is part of the
  release checklist.
- Each release with new FFmpeg/tool pins or a new AppImage library set makes a new sources
  release (hundreds of MB, measured when first made).
- Commit messages change style mid-project; tools that read the history (the changelog) start
  at the first `v*` tag.

## Plan changes

- 09 §Q-5: the changelog bullet names conventional commits with the step ID as scope; the PyPI
  bullet says not for v1; the bullets link here.
- `CLAUDE.md`: the commit rule (item 2).

## Task V: the version and the changelog

(Filled by V.)

## Task S: the source manifest and the sources release

(Filled by S.)

## Task A: the arm64 pin and the Docker image

**The pin** (`tools/ffmpeg.toml`, `[builds.default.platforms.linux-arm64]`, copied into the
package): BtbN's `ffmpeg-n9.0.2-17-g2a571b6068-linuxarm64-gpl-shared-9.0.tar.xz` of the same
release `autobuild-2026-09-30-13-08`. Checked on 2026-11-14: the SHA-256 in the release's
`checksums.sha256`, the asset digest in the GitHub API and a real download agree
(`706ccdbc…730a`, 57 679 524 bytes); one root folder; `bin/ffmpeg` and `bin/ffprobe` are
`ELF 64-bit LSB pie executable, ARM aarch64`, RPATH `$ORIGIN/../lib`, needing only glibc
libraries (`libc`, `libm`, `libdl`, `libpthread`, `librt`, `libgcc_s`); `bin/ffmpeg` and
`lib/libavutil.so.61` carry `n9.0.2-17-g2a571b6068-20260930`, the `default` build's version (so
the same source commit); the embedded configure line is BtbN's cross build
(`--arch=aarch64 … --enable-gpl --enable-version3 … --extra-version=20260930`). The release's
other `linuxarm64` assets are the 8.1 builds and master builds (`ffmpeg-N-127032-…`, another
source): a test checks that every platform's archive is named after the build's
`git describe` and variant and lies under its release tag. `scripts/fetch-tools.py
--platform linux-arm64` downloaded, verified and extracted it here (version check skipped: no
aarch64 host). The arm64 binaries were not run (no aarch64 host, no emulation).

The build itself has `--enable-vaapi`, `--enable-ffnvcodec` and `--enable-amf`; the arm64
image installs no GPU driver and claims software encoders only (item 6).

- The platform key is `linux-arm64`. `fetch-tools.py` and `reframe.tools.fetch` accept it and
  detect it on Linux `aarch64`/`arm64` (so `reframe tools fetch` on an arm64 Linux host fetches
  it, and the `-version` check runs in an arm64 image build). `bundle-tools.py` keeps its own
  x64 list: the desktop packages are x64, and libva has no arm64 pin.
- No `override-test` arm64 pin: the override job runs on x64 runners only. The tests now expect
  the `default` build to have one platform more than `override-test`.

**The image** (`docker/Dockerfile`):

- `TARGETARCH`: the Dockerfile reference ("Automatic platform ARGs in the global scope",
  read 2026-11-14) says these ARGs are set by BuildKit only and reach a stage only when it
  redeclares them **without a value**. Each stage that needs it has `ARG TARGETARCH` and uses
  `${TARGETARCH:-$(dpkg --print-architecture)}`: the classic builder (no `TARGETARCH`) builds
  for the architecture it runs on. `amd64` → FFmpeg `linux-x64`, `arm64` → `linux-arm64`,
  anything else stops the build.
- The three base images are pinned by the digest of a multi-platform OCI index; each index
  has `linux/amd64` and `linux/arm64` (registry API, 2026-11-14). uv lists
  `cpython-3.14.8-linux-aarch64-gnu`, and every package of the image's `uv sync` has a
  cp314/abi3 `manylinux` aarch64 wheel or a pure wheel in `uv.lock`.
- Debian packages on arm64: `mediainfo 25.04-1`, `tini 0.19.0-3+b8` (trixie main) and
  `mkvtoolnix 92.0-1+deb13u1` (trixie-security) exist for arm64 at the pinned versions
  (the archive's `Packages` indexes); `intel-media-va-driver-non-free` and `libmfx-gen1.2` are
  amd64 only. The arm64 image installs `mediainfo`, `mkvtoolnix` and `tini` only.
- The notices: a `notices` stage copies `docker/notices/` (committed: only its `.gitignore`;
  `.dockerignore` lets the folder in) and stops the build when `THIRD_PARTY_NOTICES` is
  missing or empty, or when its first line does not name the image's platform
  (`(docker-linux-x64)` / `(docker-linux-arm64)`, the header `third-party-notices.py`
  writes). The runtime image has it in `/opt/reframe/notices/`.
- The Debian package list: `docker/debian-packages.sh` runs after the last `apt-get` and
  writes `/opt/reframe/notices/DEBIAN_PACKAGES`: per installed package (`ii`), its
  `${binary:Package}`, version, `${source:Package}` and `${source:Version}`, and
  `https://snapshot.debian.org/package/<source>/<source version>/` (`:` and `+` percent-encoded;
  both spellings return the same page). Real behaviour: dpkg-query fills the source fields with
  the binary's own name and version when there is no `Source` field; a binNMU (`tini
  0.19.0-3+b8`) has the source version `0.19.0-3`, the one snapshot has; `Multi-Arch: same`
  packages print as `name:amd64`; the image's `awk` is mawk.

**Built here** (classic builder, Docker 29.9.2, 2026-11-14): the amd64 image with a
placeholder `docker-linux-x64` notices file: built; `/opt/reframe/notices/` holds the notices
and `DEBIAN_PACKAGES` (159 packages, as many as `dpkg-query -W`; 115 source versions);
`reframe tools status` in it finds ffmpeg/ffprobe `bundled` (n9.0.2) and mkvpropedit 92.0,
mediainfo 25.04. Without the notices, and with the arm64 notices in an amd64 build, the build
stops at the `notices` stage with the message. The snapshot links: 30 of the 115 returned
200 (with epochs, `+` and `~` in the version; `mesa`, `onevpl-intel-gpu`, `mediainfo`; by
hand before: `mkvtoolnix`, `shadow`); the other 85 failed to
connect (this network dropped connections during the run, also to GitHub); none returned 404.
The arm64 branch was run as far as it can be on amd64: a classic build with
`--build-arg TARGETARCH=arm64` (and arm64 notices) fetched the `linux-arm64` FFmpeg (its
`bin/ffmpeg` has the archive's hash), installed no GPU package and wrote the list. Every image,
stage image and pulled base image was removed afterwards.

**Not verified here:** a real `linux/arm64` build and run (no buildx: using a downloaded
buildx plugin was refused by this session's permissions; no qemu binfmt), buildx itself, the
push to GHCR.

**Plan problem (for W and the lead): one notices file per build context.** The contract copies
`docker/notices/THIRD_PARTY_NOTICES`, and the notices differ per platform (the FFmpeg archive
and its SHA-256). One `docker buildx build --platform linux/amd64,linux/arm64` sees one build
context, so it cannot give each platform its own notices: the build refuses it at the
`notices` stage. The workflow builds one platform per job (own notices each; an
`ubuntu-24.04-arm` runner builds arm64 natively, without qemu), pushes each by digest and joins
them with `docker buildx imagetools create`. A single multi-platform build would need notices
that cover both platforms instead.

## Task W: the release workflow

(Filled by W.)

## Review and fix round

(Filled by the lead.)
