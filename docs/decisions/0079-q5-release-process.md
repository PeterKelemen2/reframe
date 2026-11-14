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
   against the stamped version → the sources release (made unless a published release with
   its tag has every file of the manifest, never "latest", no `v`) → in parallel: the Linux
   packages, the Windows installers, the Docker image (both platforms, to GHCR) — each with the notices that name the sources release → the
   updater's `latest.json` → a GitHub release with the packages, `latest.json`, the changelog
   section and the sources link. Windows code signing runs when the certificate secrets are
   set; without them the installers are unsigned and the release notes say so. The updater
   signature (the Tauri key secret) is required: the workflow fails without it. A release
   procedure (`docs/release.md`) lists the steps and the secrets.
8. **No PyPI wheel for v1.** The core's Python API is not promised as stable.

9. **The owner's answers to the wave-1 questions (2026-11-14).** The version stays
   `0.1.0.dev0` until the owner sets the first release's number. **No pre-releases**: a
   pre-release SemVer cannot build the MSI (Tauri's WiX version needs a numeric pre-release) and
   dpkg sorts `1.1.0-rc.1` after `1.1.0` (task V), so the workflow refuses a pre-release tag.
   `latest.json` lists Windows only; the Linux AppImage/deb entries are added once the Linux
   update path is checked (0072 "Task W"). Each artefact's notices list **only the part of the
   sources release its platform bundles** (task N). RFC 3161 timestamps for Windows signing.

10. **The owner's answers to review R1 (2026-11-14).**
   - **The Windows `mkvpropedit.exe` is an MXE static build** that contains Qt 6.12.0 and GNU
     MP (and Boost and others); review R1 found it, the lead confirmed it with `strings`. Its
     corresponding source is the MXE commit it was built with and the source of every MXE
     package linked into it: they go into the source manifest for `windows-x64`, with their
     licences in the Windows notices (0073's table missed them).
   - **The AppImage runtime** (type2-runtime, static: libfuse LGPL-2.1, squashfuse, musl, zstd,
     zlib) is pinned and its sources go into the manifest for `linux-x64` (0079 "Task S" called
     it MIT only).
   - **The arm64 image builds on GitHub's native `ubuntu-24.04-arm` runner**; the repository
     is made public before the first release (the sources release must be as reachable as the
     binaries anyway), and the workflow refuses to run while it is private.
   - **Linux packages:** the release attaches a `SHA256SUMS` of every artefact and a detached
     GPG signature of it (the key from a repository secret; the public key in
     `docs/release.md`). That is the "signed" of 09 §Q-5 for the AppImage, .deb and .rpm.

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
  4. The workflow checks the tag against `stamp-version.py --check`'s output
     (`release-workflow.py preflight` since "Fix round — FW"), and gets the notes with
     `scripts/release-notes.py "$GITHUB_REF_NAME"`.

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

- `--sources-url` and `--sources-sums` put the sources release and the archives' SHA-256 after
  the introduction (with `--sources-manifest`, only the platform's part: "Fix — N" below).
- `docker-linux-x64` and `docker-linux-arm64`: FFmpeg with the pin of `linux-x64` or
  `linux-arm64` (its licence from the `--tools` folder, e.g. `fetch-tools.py`'s; no libva: the
  image uses Debian's), CPython (the script refuses an interpreter other than the image's
  `uv python install` version), the server's packages from `uv export` with the selection of
  the image's `uv sync` (a test compares it with the Dockerfile) and the markers evaluated for
  the platform's machine, the MediaInfo library of the pymediainfo wheel, the frontend's
  packages, and a sentence that points to the Debian package list next to the file. Run here
  for `docker-linux-x64`: 1 tool, CPython 3.14.8, 38 Python packages and MediaInfoLib 24.12, 105
  JavaScript packages.

**Fix — N (notices per platform), 2026-11-14.** The owner's answer (item 9): each package's
notices list only the archives its platform bundles. `third-party-notices.py` takes
`--sources-manifest FILE` with `--sources-url` and `--sources-sums` (all three or none: exit 2).
The manifest needed no new field (its tag is unchanged): an entry's `kind` says what its
`platforms` mean. `git` and `btbn-stage` list FFmpeg platforms, so they go to every package of
that FFmpeg platform (`linux-x64` → the desktop Linux packages and `docker-linux-x64`,
`linux-arm64` → `docker-linux-arm64`, `windows-x64` → Windows). `url` (MKVToolNix, MediaInfo:
`windows-x64`; libva: `linux-x64`) and `ubuntu-source` (`linux-x64`) list desktop package
platforms, so the image, which bundles only FFmpeg, gets none of them. An unknown kind, an
archive in the sums that no entry names, a bundled entry without a sum, and a platform with no
entry (a manifest made without its FFmpeg pin) are errors. The notices text says the release
holds the sources of every package and lists this package's archives. `build.sh` takes
`REFRAME_SOURCES_MANIFEST` (realpath'd, mounted read-only at `/sources/manifest.json`; the three
variables together or none, and each file must exist, before any `docker` call), and
`build-in-container.sh` passes `--sources-manifest /sources/manifest.json`. Run here: the real
`sources-manifest.py` (with the task S AppImage list) gave 219 entries, tag
`sources-baff46a3d47a` (the same bytes as task S's last run); with a sums file made from it,
`linux-x64` lists 215 archives (2 git, 115 stages, libva, 97 Ubuntu sources), `windows-x64` 100
(2 git, 96 stages, MKVToolNix, MediaInfo), `docker-linux-x64` 117 (2 git, 115 stages),
`docker-linux-arm64` 114 (2 git, 112 stages; no davs2, xavs2, onevpl); every archive is in at
least one. The workflow passes the manifest it fetched with (task W).

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

Built 2026-11-14 on the AMD desktop, then reconciled with what V, S and A delivered (phase 2,
the same day). Nothing ran on GitHub (nothing is pushed).

**`.github/workflows/release.yml`** (on `v*`; workflow `permissions: contents: read`, one
`concurrency` group without cancelling, `UV_FROZEN=1`, every action pinned by commit SHA):

1. `version` (since "Fix round — FW": `release-workflow.py preflight` makes these checks, and
   more): `stamp-version.py --check` prints the version; the tag must be `v` and it, and
   the version must be `X.Y.Z` (no pre-releases in v1: task V found that a SemVer pre-release
   cannot build the MSI and that dpkg sorts `1.1.0-rc.1` after `1.1.0`; the lead's decision).
   A final version is spelled the same in PEP 440 and SemVer, so the workflow has one version.
   `release-notes.py VERSION` must find a section. `TAURI_SIGNING_PRIVATE_KEY` must be set: the
   run stops here, before anything is published.
2. `sources` (`contents: write`, 5 h): `appimage-libs.sh` (task S: builds the Linux build image
   and resolves the AppImage's packages in it) → `sources-manifest.py --out … --appimage-libs …`
   (stdout: the tag) → `gh release view TAG` (replaced by `release-workflow.py sources-find`
   and `sources-publish`: "Fix round — FW"): if found, its `SHA256SUMS` is downloaded; else the
   fetch image (`desktop/packaging/sources/Dockerfile`, below) is built and
   `sources-fetch.py --manifest /sources/manifest.json --out /sources/files` runs in it (the
   repository mounted read-only, uv's environment in the image), then `gh release create TAG
   --latest=false --target $GITHUB_SHA` with the manifest and `files/*`. `df -h` and `du -sh`
   go to the log (the size of a new sources release). The artifact `sources` carries the
   manifest, `SHA256SUMS` and `appimage-libs.json` to the other jobs.
3. In parallel:
   - `linux`: `build.sh dist/linux` with `REFRAME_SOURCES_URL`, `REFRAME_SOURCES_SUMS`,
     `REFRAME_SOURCES_MANIFEST` and `REFRAME_APPIMAGE_LIBS` (paths; `build.sh` mounts them and
     checks the built AppImage's packages against the list: if apt moved since the `sources`
     job, it fails and the release is run again, `docs/release.md`), then the multitrack fixture
     and `install-test.sh dist/linux`. `appimage-test.sh` needs KWin and is a manual check.
   - `windows` (0072 task W's job list): `bundle-tools.py --platform windows-x64`, the sidecar,
     `cargo install --locked cargo-about@0.9.3 --features cli`, the notices with `PYTHONUTF8=1`,
     `--sources-url`, `--sources-sums` and `--sources-manifest`; when the secret
     `WINDOWS_CERTIFICATE` is set, the PFX goes into `Cert:\CurrentUser\My` and an overlay with
     its thumbprint, `digestAlgorithm` `sha256`, `timestampUrl` (variable
     `WINDOWS_TIMESTAMP_URL`, required with the certificate) and `tsp` true (RFC 3161, the
     owner's answer) is passed to `tauri build --config`, then `Get-AuthenticodeSignature` must
     say `Valid` for both installers; output `signed`. Then `tauri signer sign --app-version
     VERSION` of the NSIS installer (key and password from the secrets, in that step's
     environment only). `createUpdaterArtifacts` stays off, as 0072 chose.
   - `docker` (`packages: write`), one job per platform, each on a runner of its architecture
     (`ubuntu-24.04`, `ubuntu-24.04-arm`): `fetch-tools.py --platform linux-x64|linux-arm64
     --install-dir $RUNNER_TEMP/tools/ffmpeg` (FFmpeg's licence for the notices), the notices
     with `uv run --python 3.14.8 --with pip-licenses==5.5.5 … --platform docker-linux-x64|arm64
     --tools … --sources-url/-sums/-manifest … --out docker/notices/THIRD_PARTY_NOTICES` after
     `npm ci` in `frontend/`, then `docker buildx build --platform linux/ARCH` pushed **by digest
     only** (`push-by-digest=true`), the digest as an artifact. One build per platform because
     the notices differ per platform and the Dockerfile refuses another platform's (task A).
     The arm64 runner instead of QEMU: no emulation (the image build runs `ffmpeg -version` of
     the arm64 build natively, as A's `fetch-tools.py` check does on an aarch64 host), no
     third-party binfmt image, and a build time like amd64's. It needs `ubuntu-24.04-arm` to be
     available to the repository (`docs/release.md` says what to change if it is not).
4. `docker-tags`, after `docker`, `linux` and `windows`: `docker buildx imagetools create` with
   the version and `latest` (`latest` only for the highest version since "Fix round — FW"). No
   tag is published unless every package built.
5. `release` (`contents: write`): `release-notes.py` → `updater-manifest.py` (the NSIS installer
   only: Linux entries come once the Linux update path is verified, the owner's answer) → the
   notes (the changelog section, a "not code-signed" line when `signed` is not true, the
   sources URL and the whole release's `SHA256SUMS`) → `gh release create --verify-tag --draft`
   with the AppImage, `.deb`, `.rpm`, NSIS + `.sig`, MSI and `latest.json`, then `gh release
   edit --draft=false --latest`. The draft keeps `releases/latest/download/latest.json` from
   pointing at a release whose files are not all up. (Since "Fix round — FW": the signed
   `SHA256SUMS`, then `release-workflow.py publish`.)

**`desktop/packaging/sources/Dockerfile`** (the fetch image): `ubuntu:26.04` by digest (the
digest S used), uv 0.13.5 by digest with CPython 3.14.8, and BtbN's tools for the download
commands: `git` 2.53, `subversion`, `cargo`, `meson`, `python3`, `automake`, `libtool`,
`pkgconf`, `xz-utils`, `curl`, each at an exact version, installed from
`snapshot.ubuntu.com` at `20261114T000000Z` (`apt-get update --snapshot`, checked in the
image: it needs `ca-certificates` first, which is the only unpinned package), so a newer
archive does not break the pins; and `autoconf_2.73-2_all.deb` (Ubuntu 26.04 has 2.72) from
the same snapshot's pool with its SHA-256 (`7708a595…3270`, equal to the
`archive.ubuntu.com` pool's file), installed by apt with the others. Built here with the
classic builder; `sources-fetch.py` ran in it, exactly as the workflow calls it, on a subset
manifest of four entries chosen for the tools (LAME: `autoreconf` with autoconf 2.73; libplacebo:
`git submodule update --filter=blob:none`; Xvid: SVN; libva: a tarball): all four fetched and
checked, 7.2 MB, `SHA256SUMS` written, in 2 min 35 s.

**`scripts/updater-manifest.py`** (the contract, plus `--tauri-config`, default the committed
`tauri.conf.json`): one platform entry per artefact, `{"signature": <the .sig file>, "url":
<base-url>/<name>}`, `version`, `notes`, `pub_date` (RFC 3339, UTC). It refuses what the app
would refuse after download: a `.sig` without `version:` or with another version (the app has
`requireSignedVersion`), with another `file:`, or by a key whose id is not the committed
`pubkey`'s; a version that is not SemVer; an artefact the app never updates (MSI, rpm); two
artefacts for one target; a non-https URL.

**Checked against the real tools** (not memory):

- `tauri-plugin-updater` 2.14.1 (its source in the cargo registry): the static format
  (`version` parsed as SemVer after stripping `v`, optional `notes`, `pub_date` RFC 3339,
  `platforms.<target>.{url, signature}`); the target is `{os}-{arch}-{installer}` then
  `{os}-{arch}` (`windows-x86_64-nsis`, `linux-x86_64-appimage`, `linux-x86_64-deb`); the
  signature field is base64 of the minisign signature text; the version check reads `version:`
  from the trusted comment.
- `tauri signer` (tauri-cli 2.12.4), with throwaway keys (deleted): `.sig` = base64 of
  `untrusted comment…`, a 74-byte signature line (`ED` + 8-byte key id + 64), `trusted
  comment: timestamp:…<TAB>file:<basename><TAB>version:<v>`; the public key's line is `Ed` +
  the same key id + 32 bytes, so the key id check needs no cryptography; the key's content in
  `TAURI_SIGNING_PRIVATE_KEY` signs as `-f` does. The committed `pubkey`'s key id is
  `80B98CB268A32743` (0072's test key). The test uses a real signature and public key.
- `config.schema.json` of tauri-cli 2.12.4: `bundle.windows.certificateThumbprint`,
  `digestAlgorithm`, `timestampUrl`, `tsp`.
- The signing step's overlay and `GITHUB_OUTPUT` line in PowerShell 7.4 (the
  `mcr.microsoft.com/powershell` image, removed after): valid JSON without a BOM.
- The `run:` blocks under `bash -eo pipefail` (as they were before "Fix round — FW", which
  ran its own): `version` on an exported tree (`0.1.0.dev0` and
  `1.2.0rc1` refused as pre-releases, `v1.2.1` against `1.2.0` refused, `v1.2.0` passes);
  `windows` (the `--config` array with and without signing; the signer command), `docker-tags`
  and `release` (with `gh`/`docker`/`npx` stubs that print their arguments, the real
  `release-notes.py` and `updater-manifest.py` and a real 1.1.0 signature).
- The Docker notices command for `docker-linux-arm64` with a `fetch-tools.py --platform
  linux-arm64 --install-dir` folder and a real `SHA256SUMS` (before `--sources-manifest`
  existed: it is task N's): 1 tool, CPython 3.14.8, 38 Python and 105 JavaScript packages.
- The action SHAs from `gh api` (`upload-artifact` v7.0.2, `download-artifact` v8.0.2,
  `setup-buildx-action` v4.4.1) and their inputs from their `action.yml`.
- actionlint 1.7.12 (`uv tool run --from actionlint-py==1.7.12.25 --with
  shellcheck-py==0.11.0.1 actionlint`, so its shellcheck rule runs): no findings.

**Not verified** (needs GitHub, a certificate or an arm64 host): any job on a runner; whether
`ubuntu-24.04-arm` is available to this repository; the classic builder (`DOCKER_BUILDKIT=0`)
and the free disk of `ubuntu-latest` for the `sources` job (two images and more than 1 GB of
archives) and the Linux build (locally about 8 GB of image and cache volumes); a whole sources
fetch (S fetched 162 of 215 `linux-x64` archives before github.com refused this host; a runner
has another address); buildx's `containerimage.digest` metadata key and `imagetools create
--annotation`; signing with a CA certificate and an RFC 3161 server; `gh release` against the
real repository; the updater reading a `latest.json` from a real release.

**Phase 2 changes** (after V, S, A and the lead's fcda364 merged): only final `X.Y.Z` tags (the
`prerelease` output, `--prerelease` and the no-`latest` branches went; one version output
instead of `version` and `semver`); the `sources` job calls `appimage-libs.sh` and fetches in
the new fetch image; the artifact `sources` (manifest, sums, package list) replaces
`sources-sums`; the Linux job passes the four `REFRAME_*` paths instead of an untracked file in
the tree; every notices call gets `--sources-manifest` (the notices list only the platform's
archives: the owner's answer, task N builds it); the Docker notices get `--tools` and
`--python 3.14.8`; arm64 builds on `ubuntu-24.04-arm` instead of QEMU (`setup-qemu-action`
removed).

## Review and fix round

(Filled by the lead.)

### Fix round — FW (the workflow), 2026-11-14

Each finding was reproduced first; each fix has a test that fails on it (the mutation is named;
all 39 were caught). The workflow's logic moved into **`scripts/release-workflow.py`** (stdlib
only, one subcommand per step: `preflight`, `sources-find`, `sources-publish`, `notes`, `sums`,
`publish`), tested in `testing/tests/test_release_workflow.py` against a fake GitHub that keeps
releases, drafts, assets and tags as the API reports them. `gh` is its only way to GitHub, and
any non-zero exit of `gh` stops the step.

**M1: a draft or partial sources release was reused.** Reproduced in gh 2.102.1's source
(`pkg/cmd/release/shared/fetch.go`, `create/create.go`, `create/http.go` at `v2.102.1`):
`gh release view TAG` looks the tag up as a published release and, at the same time, as a
draft (GraphQL `release(tagName:)`, then REST by id), so it succeeds for a draft; `gh release
create` with files and without `--draft` creates a draft, uploads, then publishes, and deletes
the draft only when an upload returns an error (a cancelled or timed-out job leaves it). The
old step with a stub `gh`: a draft gave `found=true`, an HTTP 502 `found=false`. The release job
had the same shape (`gh release create --draft` beside a leftover draft, then `gh release edit`
by tag). Now:

- `sources-find` lists the releases (`gh api --paginate --slurp
  'repos/R/releases?per_page=100'`: the by-tag endpoint finds published releases only, the list
  has drafts for a token with push access — REST docs; real call: a list of pages), deletes each
  draft with the tag (`DELETE /releases/{id}`), and counts a published one as found only when it
  has `manifest.json` with the local manifest's SHA-256 and size, `SHA256SUMS` (downloaded by
  asset id with `Accept: application/octet-stream`; a real public asset's bytes hash to its
  `digest`) listing exactly the manifest's archives, and each archive, every asset `state
  uploaded` with the `digest` of its line, nothing else. Otherwise it stops and says what to do.
  A draft with the tag can only be an interrupted run's: the concurrency group runs one release
  at a time.
- `sources-publish` and `publish` (the release job): a published release with the tag stops the
  step (never replaced); drafts are deleted; `gh release create TAG --draft …` uploads (gh does
  not publish a `--draft`); then exactly one draft must have exactly the local files (state,
  size, digest); only then `PATCH /releases/{id}` with `draft=false` and `make_latest`. A failed
  upload leaves the draft for the next run to delete.
- Tests (mutations): drafts deleted, not reused (RW1); a release on a later page (RW2); a
  published release with an unfinished, short, changed, missing or extra file, another
  manifest, or `SHA256SUMS` that lists other archives stops the run (RW3–RW8, RW34); a published
  version is never replaced (RW9); an incomplete draft is not published (RW10); a second draft
  during the upload (RW32); local sums that do not match the archives (RW14); a gh failure is not
  "not found" (RW27); `found` reaches `$GITHUB_OUTPUT` (RW28).

**m6: `latest` always moved.** `preflight` sets `latest` when no `vX.Y.Z` tag is numerically
higher (`gh api --paginate --slurp repos/R/git/matching-refs/tags/v`; real calls: `refs/tags/v…`
entries, `[]` for this repository today); tags with a pre-release part are not versions. The
image gets `:latest` and the release `make_latest=true` only then (REST: `make_latest` "Defaults
to true for newly published releases", so it is always sent). Tests: RW21 (string order), RW22,
RW11.

**m7: a private repository.** `preflight` refuses when `gh api repos/R` says `private` (real:
`true` today). Test RW20.

**m8 (FW): test holes.** CL1: the git-cliff test repository gets a `sources-0123456789ab` tag
between conventional commits; without `tag_pattern` the release's section loses the commits
before it (caught). The run blocks' logic is in the script now: the tag (RW15), pre-releases and
non-ASCII digits (RW16), the MSI's limits (RW17), found/not found (RW1, RW28), the notes (RW24,
RW36), the private repository (RW20), latest (RW21, RW22). What stays in the workflow is calls,
plus three lines of shell for the image tags (run by the harness below).

**m9: the Linux packages "signed".** The release job writes `SHA256SUMS` of every file of the
release (`sha256sum` format, name order) and `SHA256SUMS.asc` (armored, detached) with
`RELEASE_GPG_PRIVATE_KEY` and `RELEASE_GPG_PASSPHRASE` in a new GnuPG home, then verifies it in
a second home that holds only the first public key block of `docs/release.md`, so a signature
users could not check stops the job. The version job runs the same on `CHANGELOG.md`: a missing
secret, a wrong passphrase, another key or no key in the doc stop the run before anything is
built (`preflight` names a missing secret first). Checked with GnuPG 2.4.9: a protected secret
key imports in batch without its passphrase; a wrong passphrase fails ("Bad passphrase") in a
new home, but signs in a home whose agent cached the right one (hence a new home per run); `gpg
--verify` exits 0 for a good signature by an untrusted key and 1 for a changed file; a key
without a passphrase signs with an empty `--passphrase-fd 0`; the doc's `gpg --quick-gen-key
'Reframe releases' ed25519 sign never` works without an e-mail address. Tests: the signature
verifies as a user checks it and fails on a changed `SHA256SUMS` (RW26); a wrong passphrase,
another key in the doc (RW25), no key in the doc (RW35), no secret. `docs/release.md`: the key's
procedure, the key block (empty until the owner makes the key: until then no release can be
made) and "Check a download". The `.deb` and `.rpm` carry no package signature of their own.

**m10: `tauri build` from a development tree.** Read in the bundler at `tauri-cli-v2.12.4`
(`crates/tauri-bundler/src/bundle/windows/msi/mod.rs`, `bundle.rs`, `settings.rs`): the MSI's
version is `bundle.windows.wix.version` when set, else `convert_version(version)`, which refuses
a pre-release that is not a number ("optional pre-release identifier in app version must be
numeric-only and cannot be greater than 65535 for msi target"); `validate_wix_version` allows at
most 255.255.65535. The bundles are made in `targets` order (`nsis`, `msi`), so a dev `tauri
build` writes the NSIS installer and then fails. Chosen: no config change (a committed
`wix.version` would apply to releases too and need stamping); `docs/release.md` "Installers from
a development tree": `npx tauri build --bundles nsis`, or a local, uncommitted
`stamp-version.py --set X.Y.Z` for an MSI (as 0072's updater tests used 0.1.0 and 0.1.1). The
release path is unchanged; `preflight` also refuses a version beyond WiX's limits (RW17). Not run
on Windows (no VM work in Q-5). For the lead: 0072's VM procedure and `docs/m10-breakdown.md`
("Machines and commands") still say plain `npx tauri build`.

**Nits.** The version job requires `WINDOWS_CERTIFICATE_PASSWORD` and `WINDOWS_TIMESTAMP_URL`
when `WINDOWS_CERTIFICATE` is set (RW18, RW19; `ConvertTo-SecureString` cannot take an empty
password); the secrets reach the script only as `${{ secrets.X != '' }}`. `to_semver`: `[0-9]`
and `fullmatch` (SV-N1, SV-N2; `'1.1.0\n'`, `'١.1.0'`, `'1.1.0rc٣'` were stamped before).
Concurrency: GitHub's docs (read 2026-11-14) keep one running and one pending run per group, and
a newer run cancels the pending one. `queue: max` would keep up to 100, but actionlint 1.7.12 (the
newest `actionlint-py`, 1.7.12.25) refuses the key (`unexpected key "queue" for "concurrency"
section`), so `docs/release.md` says to push one tag at a time and re-run a cancelled run.

**Run locally** (nothing runs on GitHub): every changed run block under `bash -eo pipefail`, with
`gh` being the tests' fake GitHub as an executable (its state in a JSON file), `docker` stubbed, a
tree stamped 1.1.0, a throwaway GPG key pasted into a copy of `docs/release.md` and a throwaway
updater key: `preflight` (1.1.0 the highest tag: `version=1.1.0`, `latest=true`; a private
repository, no GPG secret and a certificate without its URL: three `::error::` lines; tag
`v1.1.1` for 1.1.0: refused); the signing check (passes; a wrong passphrase and the committed
doc without a key fail); sources (a leftover draft deleted, `found=false`; an upload cut after
two files leaves a draft; the next run deletes it, uploads all five files and publishes with
`make_latest=false` and the target; a third run: `found=true`, the downloaded `SHA256SUMS` equals
the fetched one); the image tags with `latest` true and false; the release (latest.json with a
real updater signature, the notes, the signed sums, a leftover draft deleted, nine assets,
`make_latest=true`; the same step again is refused); then a user's check with the doc's
commands ("Good signature", `sha256sum --check --ignore-missing` OK). actionlint 1.7.12 with
shellcheck 0.11.0: clean.

**Not verified** (needs GitHub): gh's writes (draft, upload, `DELETE`, `PATCH`) against the real
API; whether a draft's assets have a `digest` right after the upload (documented "string or
null"; null skips only the digest comparison); `${{ secrets.X != '' }}` as `true`/`false` in a
step's environment (the documented coercion).
