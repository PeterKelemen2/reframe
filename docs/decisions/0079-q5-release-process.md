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

Built (2026-11-14, on Linux):

- **`scripts/stamp-version.py`** (stdlib only: `uv run --no-project python scripts/stamp-version.py`).
  It reads `__version__` from `packages/reframe/src/reframe/__init__.py` and stamps its SemVer
  spelling into `frontend/package.json`, `desktop/package.json`, the root `version` and
  `packages[""].version` of both `package-lock.json` files (as `npm version` does),
  `desktop/src-tauri/tauri.conf.json`, the `[package]` of `Cargo.toml` and the
  `reframe-desktop` entry of `Cargo.lock`. Each edit changes only the value in place (CRLF
  checkouts keep their line ends); `--check` prints the version or names each field that
  differs (exit 1); a version it cannot spell exits 2 and writes nothing. Contract as given,
  plus a hidden `--root` for the tests.
- **The spelling.** Accepted: `X.Y.Z`, `X.Y.ZaN` → `X.Y.Z-alpha.N`, `X.Y.ZbN` → `-beta.N`,
  `X.Y.ZrcN` → `-rc.N`, `X.Y.Z.devN` → `-dev.N`. Refused: post, local, epoch, combined
  (`rc1.dev2`) and leading zeros, because SemVer cannot keep PEP 440's order for them. The dot
  before the number keeps `rc.2` before `rc.10`. `.devN` sorts after the betas in SemVer
  (PEP 440 puts it first): a dev version is never tagged.
- **`reframe-server`** has no version of its own: `[tool.hatch.version] path` is the core's
  `__init__.py`, and `reframe_server.__version__` is imported from `reframe`.
  `uv build --package reframe-server` (sdist, then the wheel from it) gives
  `reframe_server-0.1.0.dev0`. The Docker image copies the core's `src` before its
  non-editable `uv sync`, so it builds too.
- **The version now:** `0.1.0.dev0` kept (SemVer `0.1.0-dev.0` in every field; the frontend
  was `0.0.0`, the desktop `0.1.0`). The first release sets its own with `--set`.
- **The frontend** gets `__REFRAME_VERSION__` from `frontend/package.json` through Vite's
  `define`; the Diagnostics copy's client part has a `version:` line (seen in a real
  `build:web` bundle).
- **CI:** `stamp-version.py --check` in the `python` job (Linux and Windows), before `uv sync`.
- **git-cliff 2.14.2** (2026-09-18), run as `uv tool run git-cliff==2.14.2`: the PyPI package
  has wheels for Linux x64/arm64, macOS and Windows, so it runs on every runner with
  `setup-uv` and needs no action. (npm `git-cliff@2.14.2` also exists.) `cliff.toml`'s first
  comment names the pin, and the test runs that pin.
- **`CHANGELOG.md`** is the frame: the header, `## [Unreleased]`, and a comment on the first
  release's section, written by hand from `docs/status.md`. `scripts/release-notes.py VERSION`
  (a leading `v` is ignored) prints a section without its heading; exit 1 for none or an
  empty one.

Checked against the real tools:

| Tool | `1.1.0rc1`, `0.1.0.dev0` (PEP 440) | `1.1.0-rc.1`, `0.1.0-dev.0` |
|---|---|---|
| Tauri CLI 2.12.4 (`tauri inspect wix-upgrade-code` parses the config) | refused: "`tauri.conf.json > version` must be a semver string" | taken |
| cargo 1.99.1 (`cargo metadata`) | refused: "unexpected character 'r' after patch version number" | taken |
| npm's `semver` (frontend `node_modules`) | `valid()` is null | valid; `alpha.1 < alpha.2 < beta.1 < rc.2 < rc.10 < release` |

- `cargo metadata --locked` with `Cargo.toml` stamped and `Cargo.lock` not: "cannot update the
  lock file … because --locked was passed". This is why the lock is stamped.
- **Pre-releases and the installers** (the bundler source at tag `tauri-cli-v2.12.4`):
  - **MSI** (`crates/tauri-bundler/src/bundle/windows/msi/mod.rs`, `convert_version`): a
    pre-release must be numeric (`1.1.0-4` → `1.1.0.4`). `1.1.0-rc.1` fails the build:
    "optional pre-release identifier in app version must be numeric-only and cannot be
    greater than 65535 for msi target". Only `bundle.windows.wix.version` overrides it. WiX
    limits: major ≤ 255, minor ≤ 255, patch ≤ 65535.
  - **NSIS** (`nsis/mod.rs`): takes any SemVer. `VIProductVersion` is `X.Y.Z.0`.
  - **deb** (`linux/debian.rs`): `Version:` is the SemVer string, unchanged. dpkg 1.21.1
    (`ubuntu:22.04`): `1.1.0-rc.1` is **greater** than `1.1.0`, so apt does not upgrade an rc
    to its release. (`1.1.0~rc.1` sorts before it.)
  - **rpm** (`linux/rpm.rs`): the RPM `Version` is the SemVer string, unchanged. rpm does not
    allow `-` in a version. This was not checked with a real rpm here (no rpm on this host).
  - So with this release process, a pre-release tag cannot build the MSI, and its deb and rpm
    would be ordered wrongly. A question for the lead or the owner: should v1 tag only final
    versions (`X.Y.Z`)? If pre-releases come later, they could build only NSIS and the
    AppImage.
- **git-cliff** (2.14.2, run on a throwaway repository: the old-style commits, then a `v0.9.0`
  tag, then `feat`/`fix`/`perf` with scopes, `docs`/`test`/`ci`/`chore`/`build`/`refactor`/
  `revert`, `feat(S-2)!:`, a `BREAKING CHANGE:` footer, one non-conventional commit, and a
  `--no-ff` merge of a branch with a `fix`):
  - The groups are Breaking, Added, Fixed and Performance, in that order. Each line is
    `- <scope>: <subject>`. A breaking commit with a footer shows the footer's text. The
    other types, the merge commit and the non-conventional commit are left out. The `fix`
    from the merged branch is kept.
  - `--prepend CHANGELOG.md` removes the configured `header` from the start of the file, then
    writes the header and the new section above the rest. Because the header ends with
    `## [Unreleased]`, that heading stays at the top, with nothing under it. If the file does
    not start with exactly that header, the frame is written twice (a test checks this).
  - With `--tag`, the section's date is the date of the run.
  - `tag_pattern = "^v[0-9]"`: the `sources-…` tags of 0073 are not releases.
  - Since the last `v*` tag: the section of a final release that follows an rc lists only
    the commits made after that rc.
- **The procedure** (for `docs/release.md`, task W):
  1. `uv run --no-project python scripts/stamp-version.py --set X.Y.Z`.
  2. The changelog. For the first release, replace the comment in `CHANGELOG.md` with the
     section `## [X.Y.Z] - YYYY-MM-DD` and write it by hand. For later releases, run
     `uv tool run git-cliff==2.14.2 --unreleased --tag vX.Y.Z --prepend CHANGELOG.md`, then
     read the result.
  3. Commit (`chore(release): vX.Y.Z`), then tag `vX.Y.Z`.
  4. The workflow checks the tag with
     `test "$GITHUB_REF_NAME" = "v$(uv run --no-project python scripts/stamp-version.py --check)"`,
     and gets the notes with `scripts/release-notes.py "$GITHUB_REF_NAME"`.

## Task S: the source manifest and the sources release

### What the BtbN scripts pin (checked 2026-11-14)

Read in a depth-1 clone of `github.com/BtbN/FFmpeg-Builds` at `build_scripts_commit`
(6c9aec5), and by running its own `generate.sh` for `linux64`, `win64` and `linuxarm64`
(`gpl-shared`, addin `9.0`).

- **Per stage**, `scripts.d/**/NN-name.sh` sets `SCRIPT_REPO` and `SCRIPT_COMMIT` (and `…2`,
  `…3`, `SCRIPT_MIRROR`, `SCRIPT_REV`, `SCRIPT_BRANCH`); `ffbuild_dockerdl` prints the stage's
  download commands. The default is `git-mini-clone REPO COMMIT .` (`images/base/git-mini-clone.sh`:
  `git init`, `git fetch --depth=1 origin REF`, `git checkout FETCH_HEAD`). At this commit no
  stage pins a tarball and a checksum. What the pins are:
  - a full commit hash: nearly every stage;
  - a tag name only: OpenSSL `openssl-3.6.4`, Mbed TLS `v4.2.0`, Vulkan-Headers `v1.4.363`;
  - an SVN revision: LAME `trunk/lame@6835`, Xvid `trunk/xvidcore@2204`;
  - commands that fetch more than the pinned tree: `git submodule update --init --recursive`
    (OpenSSL, nghttp3, libjxl, libplacebo, Mbed TLS, GLib, zimg), `meson subprojects download`
    (GLib), `./utils/git-sync-deps` (shaderc, commits in its `DEPS`), `./autogen.sh` (Opus,
    downloads its model data), `cargo vendor --versioned-dirs` (librsvg, its `Cargo.lock`),
    `autoreconf -i` (LAME). libiconv deletes gnulib's `.git`; AMF deletes `.git` and
    `Thirdparty`.
- **Which stages a build uses**: `generate.sh TARGET VARIANT ADDIN` follows the dependencies of
  `zz-final.sh`, keeps the scripts whose `ffbuild_enabled` passes, and mounts for each stage
  `.cache/downloads/<stage>_<SHA-256 of its download commands and a newline>.tar.xz`, which
  `download.sh` makes by running the commands in BtbN's base image and packing the folder.
  Counts: `linux64` 115 download archives, `win64` 96, `linuxarm64` 112. Two stages (aom,
  libaribb24) also mount `patches/<name>` of the scripts. `linuxarm64` needs no archive that
  `linux64` does not have (davs2, xavs2 and onevpl are `linux64` only), so the arm64 pin adds
  only platform names to the manifest.
- **FFmpeg itself**: `build.sh` clones the head of `release/9.0` when it builds; the pin's
  `source_commit` is that commit (from the version string).
- **Toolchain**: crosstool-ng, cloned from its default branch when BtbN builds its base images
  (not pinned). The binaries link libgcc and libstdc++ statically (GCC Runtime Library
  Exception) and glibc dynamically (a system library); the win64 mingw-w64 runtime is the
  stage `10-mingw`, so it is in the manifest. The toolchain itself is not.

### The manifest (`scripts/sources-manifest.py`)

- The FFmpeg platforms are the `[builds.default.platforms]` of `tools/ffmpeg.toml`; the BtbN
  target of each comes from its archive's name (`…-linux64-gpl-shared-9.0.tar.xz`), the addin
  from `source_branch`. The script checks out the BtbN scripts at `build_scripts_commit`, runs
  their `generate.sh` per platform, reads every `run_stage` line's mounts, evaluates each
  stage's download commands as the build does (`util/vars.sh`, `util/dl_functions.sh`, the
  script, `ffbuild_dockerdl`) and refuses a stage whose commands do not hash to the archive name
  the build mounts. `bash` and `git` must be on `PATH`.
- Entry kinds: `git` (FFmpeg at `source_commit`, the BtbN scripts at `build_scripts_commit`),
  `btbn-stage` (one per download archive, with the platforms that use it, its commands, its
  `SCRIPT_*` variables and the patches it mounts), `url` (the MKVToolNix and MediaInfo
  `source_url` with a `source_sha256`, libva's pinned tarball), `ubuntu-source` (one per source
  package and version of the AppImage list). JSON with sorted keys, entries sorted by archive
  name; archive names keep only `[A-Za-z0-9._-]` (what GitHub keeps in an asset name;
  `gtk+3.0` becomes `gtk_3.0`). The tag is `sources-` and 12 hex digits of the file's SHA-256.
- Run here at the current pins (with the `source_sha256` values below): 219 entries (2 `git`,
  117 `btbn-stage`, 3 `url`, 97 `ubuntu-source`), tag `sources-7774ae0b8228`. The tag also
  changes when the build image's apt gives other versions.
- `tools/bundled-tools.toml` has no checksum for the MKVToolNix and MediaInfo source tarballs;
  the manifest needs `source_sha256` (the lead adds it: the MKVToolNix value equals the site's
  `mkvtoolnix-103.0.tar.xz.sha256`; MediaArea publishes none, the value is one download's).

### The fetch (`scripts/sources-fetch.py`)

- `git`: fetched by commit (git checks every object against its hash). `btbn-stage`: the
  commands must hash to the entry's `download_hash`; they run as `download.sh` runs them, with
  `git-mini-clone` and `retry-tool` from the BtbN scripts at the pinned commit; then every git or
  SVN checkout whose origin is a pinned repository must be at one of its pinned commits or
  revisions (nv-codec-headers is pinned three times in one stage). Not checked: the tag-pinned
  stages beyond "the tag was fetched", checkouts whose `.git` the commands delete, and
  submodules, vendored crates and other second-level downloads (their parent's tree or lock
  pins them, BtbN does not). `url`: the pinned SHA-256. `ubuntu-source`: the `.dsc` from
  `launchpad.net/ubuntu/+archive/primary/+sourcefiles/<source>/<version>/` must name the pinned
  source and version, and each file it lists must have its size and SHA-256 (checked against
  the real gtk+3.0 `.dsc`).
- Archives: `.tar.xz` of the tree with the entry's name as top folder, without `.git` and
  `.svn`, in name order with owner 0 and time 0 (the same tree gives the same bytes); an Ubuntu
  source package is a `.tar` of the `.dsc` and its files. An archive gets its name only after
  its check, so a rerun skips it (a `url` archive is hashed again). A folder holding a file of
  no entry is refused. Clones and stage commands get 3 attempts, 30 s apart: on this host
  github.com and archive.ubuntu.com answered "No route to host" for a minute several times
  during the long runs.
- **The environment matters**: the download commands assume BtbN's base image. On Ubuntu 22.04
  LAME's `autoreconf -i` failed ("Autoconf version 2.73 or higher is required") and libplacebo's
  `git submodule update --filter=blob:none` failed (git 2.34). They ran in `ubuntu:26.04` with
  git 2.53, subversion, cargo, meson, python3, automake, libtool and `autoconf_2.73-2_all.deb`
  from the Ubuntu pool, as BtbN's `images/base/Dockerfile` installs it. The release workflow
  runs `sources-fetch.py` in such a container (Ubuntu 26.04 by digest).
- Measured (real fetch of the `linux-x64` entries, 2026-11-14): 162 of the 215 archives,
  1040 MB. The 100 entries that are not BtbN stages, all of them: 452.5 MB (97 Ubuntu source
  packages 440 MB, the largest gcc-12 92 MB for `libatomic1`, webkit2gtk 45 MB; FFmpeg 11.8 MB;
  libva 0.6 MB); their `SHA256SUMS` checked with `sha256sum -c`, and a rerun skipped all 100.
  62 of the 115 BtbN stages: 587.5 MB (Opus 263 MB with its model data, OpenSSL 138 MB with
  its submodules). The other 53 stages were not fetched: github.com refused connections from
  this host for longer than the retries after a few hundred clones. So a sources release is
  more than 1 GB; the arm64 pin adds no archive, Windows adds the two mingw-w64 stages,
  MKVToolNix (11.2 MB) and MediaInfo (6.7 MB).

### The AppImage's distro libraries

- The notices name the manifest's hash and go into the AppImage, so the AppImage's library set
  must be known before `tauri build`. It is a committed list of 135 Ubuntu binary packages,
  `desktop/packaging/linux/appimage-packages.txt`, taken from a real AppDir (the 2026-11-12
  build in the `reframe-l` build volume: 403 files outside `usr/lib/Reframe`: the libraries in
  `usr/lib`, the GTK plugin's modules, typelibs and schemas, and each package's copyright file).
- `scripts/appimage-libs.py resolve` (in the build image; `desktop/packaging/linux/appimage-libs.sh`
  builds the image and runs it) gives each package's version, source package and source version
  from `dpkg-query`: 97 source packages. `appimage-libs.py check APPDIR --expected FILE` maps
  every distro file of the built AppDir to the one package that owns it (`/var/lib/dpkg/info/*.list`:
  the same path, else a path that ends like it, else a symlinked doc folder) and fails unless the
  packages and versions equal FILE's. Run here against that real AppDir: every file mapped, and
  it matched; an edited version and a removed package were reported. `build.sh` runs it after the
  build when `REFRAME_APPIMAGE_LIBS` names the file the manifest was made from.
- 0073's open question: the build image stays pinned by digest; its apt packages are not
  pinned. If apt gives another version between the sources job and the Linux build, the check
  fails and the release is run again (a new sources release follows).
- Not in the manifest: linuxdeploy's `AppRun` and the AppImage runtime (MIT, not distro files).

### The notices (`scripts/third-party-notices.py`)

- `--sources-url` and `--sources-sums` (both or neither) put the sources release and every
  archive's SHA-256 (the whole release, not only the platform's part) after the introduction.
- `docker-linux-x64` and `docker-linux-arm64`: FFmpeg with the pin of `linux-x64` or
  `linux-arm64` (its licence from the `--tools` folder, e.g. `fetch-tools.py`'s; no libva: the
  image uses Debian's), CPython (the script refuses an interpreter other than the image's
  `uv python install` version), the server's packages from `uv export` with the selection of
  the image's `uv sync` (a test compares it with the Dockerfile) and the markers evaluated for
  the platform's machine, the MediaInfo library of the pymediainfo wheel, the frontend's
  packages, and a sentence that points to the Debian package list next to the file. Run here
  for `docker-linux-x64`: 1 tool, CPython 3.14.8, 38 Python packages and MediaInfoLib 24.12, 105
  JavaScript packages.

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
