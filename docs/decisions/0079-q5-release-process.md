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

(Filled by A.)

## Task W: the release workflow

(Filled by W.)

## Review and fix round

(Filled by the lead.)
