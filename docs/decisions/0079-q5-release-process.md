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
   MediaInfo for Windows (MKVToolNix too until item 11); libva; the Debian/Ubuntu source package and version of
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
     licences in the Windows notices (0073's table missed them). (2026-11-14, item 11: no installer bundles MKVToolNix any more; "Fix round — FL".)
   - **The AppImage runtime** (type2-runtime, static: libfuse LGPL-2.1, squashfuse, musl, zstd,
     zlib) is pinned and its sources go into the manifest for `linux-x64` (0079 "Task S" called
     it MIT only).
   - **The arm64 image builds on GitHub's native `ubuntu-24.04-arm` runner**; the repository
     is made public before the first release (the sources release must be as reachable as the
     binaries anyway), and the workflow refuses to run while it is private.
   - **Linux packages:** the release attaches a `SHA256SUMS` of every artefact and a detached
     GPG signature of it (the key from a repository secret; the public key in
     `docs/release.md`). That is the "signed" of 09 §Q-5 for the AppImage, .deb and .rpm.

11. **The owner's answers to the fix round's questions (2026-11-14).**
   - **The Windows installers stop bundling `mkvpropedit.exe`.** The upstream binary links
     OpenSSL 4 (Apache-2.0) into a GPL-2.0-only program, and Apache-2.0 is generally held to be
     incompatible with GPL-2.0-only (task FS). Windows users install MKVToolNix themselves;
     Settings → Tools and the first-run check already report a missing tool with its reason.
     The MXE sources leave the manifest with it; MediaInfo stays bundled.
   - **Boost's source is not in the sources release** (moot once mkvpropedit goes).
   - **The notices carry the full licence text** (with its copyright lines) of every bundled
     third-party part, not only its name and source link: the BSD/MIT/ISC/zlib-style licences ask
     for the text in a binary distribution.

12. **The owner's answers to fix FL's questions (2026-11-14).**
   - **The four groups FL left without full texts stay open items for v1** ("Fix round — FL",
     "Not covered"): CPython's own libraries (python-build-standalone's `full` archives),
     MediaInfoLib's internal third-party code, the AppImage's `AppRun` and the GTK plugin hook,
     and the Windows-only parts. Each still has its name and source link in the notices. They
     are on the release checklist; the Windows group is checked in the Windows testing phase.
   - **The Docker image keeps every installed Debian package's copyright file** (3.6 MB, most of
     it Boost's, which Debian's `mkvtoolnix` pulls in); no deduplication.

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
  `source_url` with a `source_sha256`, libva's pinned tarball, and each library a static build
  links: "Fix round — FS"), `repository` (the tree a static build was built from),
  `ubuntu-source` (one per source package and version of the AppImage list). (Since "Fix round — FL" no
  MKVToolNix entry, and `repository` is the AppImage runtime's only.) JSON with sorted keys, entries sorted by archive
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
- 0073's open question: the build image stays pinned by digest, and its apt packages come from
  one `snapshot.ubuntu.com` timestamp ("Fix round — FS", m5), so the sources job and the Linux
  build resolve the same versions until the timestamp moves; the check stays.
- Not in the manifest: linuxdeploy's `AppRun` (MIT, from Tauri's `apprun-old` release). The
  AppImage runtime is pinned and in the manifest with what it links ("Fix round — FS", B2).

### The notices (`scripts/third-party-notices.py`)

- `--sources-url` and `--sources-sums` put the sources release and the archives' SHA-256 after
  the introduction (with `--sources-manifest`, only the platform's part: "Fix — N" below).
- `docker-linux-x64` and `docker-linux-arm64`: FFmpeg with the pin of `linux-x64` or
  `linux-arm64` (its licence from the `--tools` folder that holds `fetch-tools.py`'s `ffmpeg`
  folder, required for these platforms since "Fix round — FS"; no libva: the image uses
  Debian's), CPython (the script refuses an interpreter other than the image's
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
`windows-x64`; libva: `linux-x64`), `repository` and `ubuntu-source` (`linux-x64`) list
desktop package platforms, so the image, which bundles only FFmpeg, gets none of them. An unknown kind, an
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
least one. (2026-11-14, "Fix round — FL": Windows lists MediaInfo, not MKVToolNix.) The workflow passes the manifest it fetched with (task W).

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

Review R1 (xhigh, a fresh agent, 2026-11-14) read every task's code and ran its tests and
mutations. The lead reproduced each blocker and major before the fix round; the owner answered
the questions they raised (items 10, 11 and 12). Three fix agents: FW (the workflow), FS
(sources and licences), then FL (the owner's item 11). The lead broke each merged fix once
(a mutation) and the tests caught it.

| Finding | What | Outcome |
|---------|------|---------|
| B1 (blocker) | The Windows `mkvpropedit.exe` is an MXE static build (Qt, GNU MP, Boost) whose sources were not in the manifest | FS added the MXE tree and parts; then the owner removed `mkvpropedit.exe` from the Windows installers (item 11; FL), and its sources left with it. Windows users install MKVToolNix: discovery also searches its install folder, and every message names it |
| B2 (blocker) | The AppImage runtime was fetched unpinned at build time and not in the manifest | Fixed (FS): pinned (URL + SHA-256), handed to the bundler (`LDAI_RUNTIME_FILE`), checked in the built AppImage (`appimage-libs.py check-runtime`); type2-runtime and what it links statically are in the manifest |
| M1 (major) | A draft or partial sources release counted as found; a gh error counted as "not found" | Fixed (FW): `release-workflow.py sources-find` deletes drafts and accepts only a published release whose every asset matches `SHA256SUMS`; any gh error stops the step; the release job does the same for its own draft |
| m1 | A test pinned the version string | Fixed by the lead (2a8f24c) |
| m2 | The sidecar's Ubuntu `libstdc++`, `libgcc_s`, `libz` were neither listed nor checked | Fixed (FS): mapped to their Ubuntu packages in every Linux package |
| m3 | The documented Docker notices command failed, and without `--tools` the notices lacked FFmpeg | Fixed (FS): `--tools` with an `ffmpeg/` folder required for `docker-*`; the doc corrected |
| m4 | The manifest's hash depended on the caller's `SCRIPT_*` variables | Fixed (FS): evaluated in a clean environment |
| m5 | The Linux build image's apt was unpinned | Fixed (FS): `snapshot.ubuntu.com` at a pinned time |
| m6 | `latest` always moved, also for a patch on an older line | Fixed (FW): only for the highest `vX.Y.Z` tag |
| m7 | Nothing stopped a run on a private repository | Fixed (FW): `preflight` refuses it (the owner makes the repository public, item 10) |
| m8 | Test holes in both halves | Fixed: FW moved the workflow's logic into `scripts/release-workflow.py` with tests; FS added the named tests |
| m9 | The Linux packages were not "signed" | Fixed (FW): a GPG-signed `SHA256SUMS` of every file; the key is required like the Tauri key |
| m10 | A dev version (`0.1.0-dev.0`) breaks the MSI | Documented (FW): dev builds use `--bundles nsis` or stamp a final version locally; the rpm has the same limit (FS; `docs/release.md`) |
| Nits | Windows signing secrets, `to_semver` edge cases, concurrency note; survived mutations SF3, SF15, SF12, AL3, AL5, TN6 | Fixed, each with a test |

**Owner answers that changed the scope:** no `mkvpropedit.exe` on Windows; Boost's source not
needed; the full licence texts of every bundled part in the notices (FL: 38 mutations caught),
with four groups left as open items (item 12).

**Not run** (needs GitHub or Windows): the release workflow itself (every job), the sources
release upload, the multi-arch image push, Windows signing with a real certificate, the GPG key,
and the Windows discovery of an installed MKVToolNix (the registry read is mocked).

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

### Fix round — FS

Done 2026-11-14 on the AMD desktop, for review R1's findings B1, B2, m2, m3, m4, m5, the FS
test holes of m8 and the FS nits. Each finding was reproduced first.

**B1: the sources of mkvpropedit.exe's MXE build.** (2026-11-14, item 11: no installer bundles MKVToolNix any more; "Fix round — FL".)

- Reproduced in the review's copy of `mkvpropedit.exe` (from the pinned zip): the strings name
  `Qt 6.12.0 (… static release build; by GCC 16.2.0)`, `GNU MP`, the prefix
  `/opt/mxe/usr-master-20261004-a9135e507-qt-12-0/`, `mingw-w64-v14.0.0`, the source path
  `libdvdread-6.1.3/src/ifo_read.c`, 318 OpenSSL `crypto/…/*.c` paths, `deflate 1.3.2`,
  libiconv's alias table, `10.49 2026-09-28` (PCRE2) and zstd's error texts.
- Which MXE: `packaging/windows/setup_cross_compilation_env.sh` of MKVToolNix at `release-103.0`
  (Codeberg) clones `codeberg.org/mbunkus/mxe`. That fork has the branch
  `master-20261004-a9135e507-qt-12-0` (head `02b82ecfdc5a63decc4e64e06ca2dc8f0b7158f1`): MXE
  `a9135e507` (on GitHub's `mxe/mxe` too) and 15 MKVToolNix commits (libdvdread 6.1.3, libdvdcss
  1.4.3, Qt without databases, FFmpeg and WebView, gcc 16 fixes, …). Its `build.sh` installs into
  `usr-<branch>` with `plugins/gcc16`: the binary's prefix and GCC 16.2.0. Upstream `a9135e507`
  alone has libdvdread 6.0.1 and GCC 11.5.0, so the branch, not the upstream commit, is the
  source. Its `MKVTOOLNIX_DEPENDENCIES`: gettext, libiconv, zlib, boost, flac, ogg, pthreads,
  vorbis, cmark, libdvdread, gmp, qt6, qt6-qtmultimedia.
- Which packages are in the executable: the `Rakefile` at the tag links mkvpropedit with
  `$common_libs` (boost_filesystem, flac, z, pugixml, intl, iconv, fmt, qt_non_gui = Qt Core,
  gmp, cmark, dvdread; libebml, libmatroska, fmt and pugixml are in MKVToolNix's own tarball). A
  static link keeps only the objects it uses, so the binary decides: markers found for Boost,
  gettext (libintl), GNU MP, libdvdcss (its `DVDCSS_*` variables), libdvdread, libiconv,
  mingw-w64 (the C runtime and winpthreads), OpenSSL (libcrypto), PCRE2, Qt Base, zlib, zstd;
  none for FLAC, Ogg, Vorbis, cmark, Brotli (only OpenSSL's names for it), FreeType, HarfBuzz,
  libpng, JPEG, GLib, ICU, D-Bus, SQLite, Dr. MinGW. The GCC runtime is under the GCC Runtime
  Library Exception and stays out, as for the BtbN builds.
- **`tools/static-builds.toml`** (new) `[binaries.mkvpropedit]`: the tree (repository, commit)
  and the 12 parts, each with the URL and SHA-256 that MXE's `src/*.mk` (and `mxe.github.mk`
  for zlib and zstd) give at that commit. All 12 were downloaded here and matched: 342 MB
  (Boost 199 MB, OpenSSL 55 MB, Qt Base 51 MB). mingw-w64's licence was read in its COPYING
  files; the others are the projects' stated licences.
- `sources-manifest.py` makes a `repository` entry for the tree (archive
  `<repository name>-<12 hex>.tar.xz`, fetched by commit like `git`) and a `url` entry per part
  (an `archive` field names files such as GitHub's `v1.5.7.tar.gz`), for the binary's
  `platforms`. A tarball that two pins name is one entry with both platforms; two different
  files with one name are an error. `sources-fetch.py` fetched the MXE tree by commit from
  Codeberg (depth 1 by hash works there), with `type2-runtime`, squashfuse, zstd 1.5.6 and
  libdvdcss, into checked archives.
- `third-party-notices.py`: a `repository` entry goes to the packages of its platforms (not to
  the image), and the desktop notices get a section "Statically linked libraries": per binary,
  its tree and commit, then each part with its version, licence and source archive.

**B2: the AppImage runtime.**

- Tauri 2.12.4 (`crates/tauri-bundler/src/bundle/linux/appimage/linuxdeploy.rs` at
  `tauri-cli-v2.12.4`) downloads linuxdeploy from `tauri-apps/binary-releases`
  (`linuxdeploy-07333c6`), `AppRun` (`apprun-old`) and `linuxdeploy-plugin-appimage` from that
  plugin's floating `continuous` release into `~/.cache/tauri` once. The plugin's appimagetool
  downloads `type2-runtime/releases/download/continuous/runtime-x86_64` at every build unless
  it gets `--runtime-file`; the plugin passes `LDAI_RUNTIME_FILE` as `--runtime-file` (strings
  of the cached plugin). A run in the build image **without network**: Tauri's
  `linuxdeploy-07333c6` and the cached plugin on a small AppDir ran
  `appimagetool … --runtime-file /rt/runtime-x86_64` and wrote the AppImage with
  `LDAI_RUNTIME_FILE`; without it, "Downloading runtime file from …/continuous/runtime-x86_64"
  failed. The AppImage's first 944 632 bytes equal the runtime file apart from `.digest_md5`.
- The pin: type2-runtime's tagged release `20251108` (tag commit
  `dd6cebedcbddde9c82f89b011e8e1d40b6e43868`); `runtime-x86_64` SHA-256 `2fca8b44…260d` equals
  the release asset's digest and a download. (The 2026-11-12 AppImage had `continuous`,
  `fedfad5`, which GitHub replaces on every push.) Its build at the tag: `alpine:3.21` with
  `zstd-static`, `zlib-static`, `musl-dev`, `mimalloc-dev`; libfuse 3.15.0 (SHA-256 in its
  script) with `patches/libfuse/mount.c.diff`; squashfuse 0.5.2 (SHA-256 in its script); a
  `static-pie` link of `-lsquashfuse -lsquashfuse_ll -lzstd -lz -lfuse3 -lmimalloc`. Its strings
  say squashfuse 0.5.2, zstd 1.5.6, zlib 1.3.1, FUSE 3.15.0, commit `dd6cebe`. The Alpine 3.21
  packages of the release date (aports `3.21-stable`, the last APKBUILD change before
  2025-12-08): musl 1.2.5-r9, zstd 1.5.6-r2, zlib 1.3.1-r2, mimalloc2 2.1.7-r0; each upstream
  tarball's SHA-512 equals its APKBUILD's, and the pin holds its SHA-256. Alpine's own patches
  (musl has 9) live in aports and are not in the manifest: those parts are MIT, BSD or Zlib;
  the LGPL part, libfuse, is complete with its patch in the type2-runtime tree.
- `desktop/packaging/linux/appimage-runtime.sh` downloads the pinned file into the cache volume
  and checks its SHA-256 at every use; `build-in-container.sh` exports `LDAI_RUNTIME_FILE`
  before `tauri build` and runs `appimage-libs.py check-runtime` after it, which fails unless
  the AppImage starts with the pinned runtime outside the four sections appimagetool writes
  (`.digest_md5`, `.upd_info`, `.sha256_sig`, `.sig_key`). Checked on the small AppImage above
  (match) and on the review's runtime from the 2026-11-12 AppImage (no match).
- **A whole `build.sh` run here** (the snapshot image of m5, an empty Tauri cache, the version
  stamped to `0.1.0` in the build's copy, `REFRAME_APPIMAGE_LIBS` from the snapshot image): the
  bundler downloaded the `continuous` plugin (appimagetool "build 295", 2025-12-04), which ran
  `appimagetool … --runtime-file /root/.cache/reframe/appimage-runtime-2fca8b44…`;
  `check-runtime` passed, the library check passed (138 packages, with the sidecar's), the
  notices have the runtime's section, and `glibc.txt` still ends at GLIBC_2.35. The plugin that
  `linuxdeploy-07333c6` carries for a failed download reads `LDAI_RUNTIME_FILE` too (strings).
- The tree and its 6 parts (11 MB) are `linux-x64` entries; the linux notices list them.

**m2: the sidecar's system libraries.** In the 2026-11-12 build, `_internal/libgcc_s.so.1`,
`libstdc++.so.6` and `libz.so.1` of the frozen sidecar are byte-equal to the build image's files
of `libgcc-s1`, `libstdc++6` and `zlib1g` in the `.deb` (the review's) and the `.rpm` (read with
`bsdtar`), and changed by linuxdeploy in the AppDir. The old `check` passed that AppDir
without them. `check` now maps a file at the top of `_internal/` to the package that owns a
library of that name under `/lib` or `/usr/lib`, and skips the others (Python's own library,
wheel libraries); the list has the three packages. Run against that AppDir in its image: the
old list fails with the three named; the new list (138 packages, 98 source packages: `zlib`
added, `gcc-12` was there) matches. The `.deb` and `.rpm` carry the same sidecar and the same
`linux-x64` notices, so these sources cover them; the check runs on the AppDir only (the build
image cannot open the `.rpm`).

**m3: the Docker notices.** Reproduced: the earlier script with the documented command wrote
notices with no bundled tool (no FFmpeg) and exit 0. Now `--tools` is required for `docker-*`
(exit 2 without it) and must hold an `ffmpeg` folder (exit 1, naming the `fetch-tools.py`
command). `docs/deployment.md` gives `fetch-tools.py --install-dir`, `npm ci` and
`uv run --python 3.14.8 … --tools`; run here as written: 1 tool, CPython 3.14.8, 38 Python
and 105 JavaScript packages.

**m4: the caller's environment.** Reproduced on the real BtbN scripts (`6c9aec5`): with
`SCRIPT_LEAK=1` and `GITHUB_REPOSITORY` set, the earlier script put the variable into all 117
stage entries and the tag changed (`sources-c55552c2a535` against `sources-783c16dc5132`).
`generate.sh` and the stage evaluation now get only `PATH` and `LC_ALL=C`: the same tag with
and without them, and the 220 entries of the earlier script's clean run are unchanged.

**m5: the build image's apt.** `desktop/packaging/linux/Dockerfile` writes
`/etc/apt/sources.list` for `https://snapshot.ubuntu.com/ubuntu/<APT_SNAPSHOT>/` (`jammy`,
`jammy-updates`, `jammy-security`, all components; `20261114T000000Z`, the fetch image's). The
snapshot answers HTTP with a redirect to HTTPS and the base image has no CA certificates, so
the first `update` and the `ca-certificates` install run with `Acquire::https::Verify-Peer=false`
(apt still checks the signed indexes, as with the image's default `http://` archive). Built
here: `appimage-libs.py resolve` gave 138 packages with the same versions as the 2026-11-12
image. When the timestamp moves, the AppImage list is resolved again (a new sources release).

**The manifest at these pins** (the real BtbN scripts, the snapshot image's list): 240 entries
(2 `git`, 117 `btbn-stage`, 2 `repository`, 21 `url`, 98 `ubuntu-source`), tag
`sources-a2cf246f4653` (before "Fix round — FL", which took MKVToolNix, the MXE tree and its 12
parts out). `linux-x64` lists 223 archives, `windows-x64` 113, the images 117 and
114 as before; every archive is in at least one. A sources release grows by about 345 MB for
Windows and 11 MB for Linux.

**Tests** (each named defect fails its test; mutation in brackets, all caught):
`test_sources_manifest.py` the environment [FM1], the static builds' entries [FM2–FM4], a
shared and a clashing tarball [FM5, FM6], the committed pins name Qt, GNU MP, libfuse and the
rest [TB1]; `test_sources_fetch.py` a tree by commit [FR1], SVN pins [SF13], mirror pins
[SF14], archive times and owners [SF3, SF15], the `.dsc` path guard [SF12];
`test_appimage_libs.py` the sidecar's libraries, only libraries, only the top folder
[AL-m2, AL-m2b, AL-m2c], two owners [AL3], the distribution [AL5], `check-runtime` [RT1–RT4], the list [PK1];
`test_third_party_notices.py` the kinds per platform [TN-repo, TN-repo2], the section and the
licences [TN-static, TN-static2], `--tools` and the `ffmpeg` folder [TN-m3a, TN-m3b], no libva
in the image [TN6]; `test_linux_packaging.py` the library check run, a failed check and a
missing list [BS1–BS3], the runtime download, its checksum and the cached copy [RS1, RS2], the
runtime handed to the bundler and checked [RS3, RS4]; `test_docker_image.py` the notices
stage [DK2].

**Owner questions.**

1. The notices name each static part's licence and point to its source archive; they do not
   carry the licence texts with the copyright lines. BSD, MIT, ISC and ZPL ask for those in
   binary distributions (mingw-w64's `COPYING.MinGW-w64-runtime.txt` says so for every program
   linked with it), and the same holds for FFmpeg's BtbN dependencies. Should the notices carry
   them (for example taken from the archives when the sources release is made)?
2. Boost (BSL-1.0) needs no source and is 199 MB of the 345 MB. Keep it (item 10 says every
   linked MXE package) or leave it out?
3. `mkvpropedit.exe` links OpenSSL 4 (Apache-2.0). `tools/bundled-tools.toml` says MKVToolNix
   is `GPL-2.0-only` (its README: "GPL v2"); Apache-2.0 code cannot join GPL-2.0-only code
   (GPL-2.0-or-later can, under GPL-3.0). Worth a look at MKVToolNix's terms before v1 ships
   the executable; it is upstream's build, not Reframe's.

**For the lead and FW.** No new workflow input: `build.sh` fetches the runtime itself from the
pin (a GitHub release download in the `linux` job). The `sources` job's fetch now also reaches
codeberg.org, gmplib.org, ftp.gnu.org, download.videolan.org, download.qt.io,
archives.boost.io, downloads.sourceforge.net, musl.libc.org and zlib.net. A Linux build from a
dev tree (version `0.1.0-dev.0`) fails at the rpm: Tauri's rpm bundler refuses `-` in the
version ("invalid version \"0.1.0-dev.0\": contains invalid character"), the rpm counterpart of
review finding m10; the full build here ran with the version stamped to `0.1.0` in its copy.

### Fix round — FL

Done 2026-11-14 on the AMD desktop, for the owner's answers in item 11. Two parts, each
committed on its own.

**Part 1: the Windows installers bundle no `mkvpropedit.exe`.**

- **The pins.** `[tools.mkvtoolnix]` left `tools/bundled-tools.toml`; `[binaries.mkvpropedit]`
  with the MXE tree and its 12 parts left `tools/static-builds.toml` (the AppImage runtime
  stays, so the `repository` kind stays: it is now the runtime's tree only). The manifest and the
  notices read the pins, so `sources-manifest.py` and `third-party-notices.py` needed no code
  change. The real manifest at these pins without the AppImage list: 128 entries (2 `git`, 117
  `btbn-stage`, 1 `repository`, 8 `url`); `windows-x64` 99 (2 `git`, 96 stages, MediaInfo),
  `linux-x64` 125 before its 98 Ubuntu sources.
- **`bundle-tools.py`.** `mkvtoolnix` is no tool folder any more. The bundler ships every folder
  of `resources/tools/`, so a `mkvtoolnix/` that an earlier Windows layout left would put
  `mkvpropedit.exe` back into the installers: a folder with the layout's marker that the
  platform does not want is removed; one without a marker is refused as before.
- **Checked, nothing to change:** `desktop/packaging/windows/**` (only the test certificate),
  `desktop/src-tauri` (the resource map is the whole `resources/tools/`), the smoke tests (they
  check FFmpeg), `scripts/windows-setup.ps1` (it installs MKVToolNix on the test machine's `PATH`
  as a development tool and says nothing of a bundled one). The release workflow's step name, the
  READMEs, 07 §Tool bundling and §D-7, 02 §Bundled FFmpeg, 09 §Licensing and the earlier
  sentences of 0002, 0072, 0073 and this record (dated notes) said it was bundled.

**A Windows user without MKVToolNix, checked in the code and the tests that simulate a missing
tool:**

- Discovery's reason was "mkvpropedit was not found (optional: install it, or set
  REFRAME_MKVPROPEDIT to its path)" on every platform: it did not say that mkvpropedit is part
  of MKVToolNix. Settings → Tools showed that reason and, with no bundled build, no *Use bundled*
  (*Remove override* for a Settings path); the first-run screen the same reason. The in-place
  edit's error (`tool.mkvpropedit_missing`) ended with the reason; the BCP 47 warning
  (`metadata.language_tag_lost`) and the post-mux flag warning said only "mkvpropedit was not
  found". Nothing is dropped silently: the post-mux step is planned only when mkvpropedit is
  found, and each loss is a warning (the in-place job an error).
- **MKVToolNix's installer does not put itself on `PATH`.** Read in
  `packaging/windows/installer/mkvtoolnix.nsi` at `release-103.0` (Codeberg): it installs into
  `$PROGRAMFILES64\MKVToolNix` (`RequestExecutionLevel admin`), writes
  `HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\mkvtoolnix-gui.exe` (default value
  `$INSTDIR\mkvtoolnix-gui.exe`, also its `InstallDirRegKey`) and the uninstall key, and has no
  `PATH` code. So a user who installed it as told would still have seen mkvpropedit missing.
- **Fixed:**
  - The reason names MKVToolNix and where to get it: on Windows "mkvpropedit was not found. It is
    part of MKVToolNix: install MKVToolNix from https://mkvtoolnix.download/, or set
    REFRAME_MKVPROPEDIT to its path."; elsewhere "… install your distribution's mkvtoolnix
    package …"; MediaInfo likewise (the MediaInfo site, or the `mediainfo` package).
  - On Windows discovery finds mkvpropedit after `PATH` in MKVToolNix's folder: the App Paths
    value (64-bit registry view, then 32-bit: the installer is an `amd64-unicode` NSIS build
    without `SetRegView`, and which view it writes was not checked on Windows), then
    `%ProgramW6432%` / `%ProgramFiles%\MKVToolNix`. Its origin is the new `ToolOrigin.installed`
    ("Where its installer put it"; not persisted, so no schema version; the OpenAPI types
    regenerated). 02 §Path override has the row, 05's discovery bullet the origin. The registry
    read is mocked in the tests and type-checked by `mypy --platform win32`; it did not run on
    Windows (no VM work in Q-5).
  - The three issues end with discovery's reason, so each names the missing tool and how to get
    it.
  - Settings → Tools and the first-run screen show, for mkvpropedit or MediaInfo found nowhere,
    a translated instruction in place of the server's English reason: "mkvpropedit is part of
    MKVToolNix, which Reframe needs to edit MKV files in place and to write BCP 47 languages.
    Install MKVToolNix from mkvtoolnix.download, then choose Check again." (Linux: the
    distribution's package). A tool that is found but fails keeps the server's reason.
- **Tests** (each fails on the defect; mutation in brackets, all caught):
  `test_bundle_tools.py` an earlier layout's `mkvtoolnix/` is removed [the marker not
  accepted], an unmarked one refused [any folder accepted], the real pins keep MediaInfo only
  [the pin put back]; `test_sources_manifest.py` the repository's static builds have nothing for
  Windows [the MXE build put back], the Windows tool sources are MediaInfo's only [the pin put
  back]; `test_third_party_notices.py` a laid-out `mkvtoolnix/` stops the notices, the Windows
  notices name no static build; `packages/reframe/tests/tools/test_discovery.py` the reason per
  platform [the old text; the Linux text on Windows], MKVToolNix's folder from the registry
  [no lookup; a quoted value], its default folder [`ProgramFiles` not read], `PATH` first, not
  on Linux; `packages/reframe/tests/validation/test_missing_mkvpropedit.py` the in-place, BCP 47
  and flag issues say what to install [each message without the reason; the shared helper
  empty]; `ToolsSection.test.ts` the Windows and Linux instruction, no *Use bundled*, the
  server's reason for a broken tool, the `installed` origin [no hint; the hint for a broken
  tool; the Linux hint on Windows; no label]; `FirstRunScreen.test.ts` the instruction on the
  welcome screen [the server's reason shown]. 18 mutations.
- For the lead (`docs/status.md` is yours): the D-7 row ("`tools/bundled-tools.toml` pins
  MKVToolNix 103.0 (`mkvpropedit.exe`) and MediaInfo CLI 26.10 for Windows", "bundled mkvpropedit
  and MediaInfo are not verified (Windows)"), the D-8 row (Windows install: "all four tools
  `bundled`"), the M10 row ("D-7 done (bundled FFmpeg, MKVToolNix, MediaInfo …)") and the "Tool
  paths and bundled FFmpeg" row ("ship FFmpeg, MKVToolNix and MediaInfo") now say too much;
  `docs/m10-breakdown.md` (T's task, contracts and file list) is history.

**Part 2: the full licence texts in the notices.**

What the notices carried before, per part (checked with the real `docker-linux-x64` notices of
the old script and `scripts/third-party-notices.py`'s code):

| Part | Text before | Where the text comes from now |
|---|---|---|
| Python packages (pip-licenses) | yes, all 37 of the image and 43 of the sidecar | unchanged; a package without one stops the run unless `tools/licence-texts.toml` `[pypi]` has its text |
| JavaScript packages (license-checker) | 102 of 105: none for `rfc6902` 5.3.0 (no licence file; its README points to an MIT text), `@vue/devtools-api` 6.6.4 (the nested copy has none), `@rolldown/binding-linux-x64-gnu` | the three texts read upstream at those versions, in `[npm]` (the rolldown binding by the glob `@rolldown/binding-*`, one name per platform); a new package without one stops the run |
| Rust crates (cargo about) | yes (a crate without a licence file gets the SPDX text) | unchanged |
| FFmpeg, libva, MediaInfo CLI (the tool folders) | the licence file of each | unchanged |
| The BtbN stages linked into FFmpeg (115 for `linux64`, 96 `win64`, 112 `linuxarm64`), FFmpeg's and the BtbN scripts' trees | **no** | the sources release's `licence-texts.json` |
| The AppImage runtime (type2-runtime, libfuse, squashfuse, musl, zstd, zlib, mimalloc); MediaInfo's source (MediaInfo, MediaInfoLib, ZenLib) | **no** (names only) | `licence-texts.json` |
| The AppImage's Ubuntu libraries (98 source packages), the sidecar's `libgcc_s`, `libstdc++`, `libz` (in that list since "Fix round — FS") | **no** (linuxdeploy copies the copyright files into the AppImage, the `.deb` and `.rpm` had none) | `/usr/share/doc/<package>/copyright` of each binary package, read in the Linux build image where the notices run |
| The Docker image's Debian packages | **no** (a list with source links) | `docker/debian-packages.sh` appends each installed package's copyright file to the image's `THIRD_PARTY_NOTICES` |

**How a release produces them.**

- `sources-fetch.py` reads, after the fetch, the licence files of every archive but the Ubuntu
  source packages and writes `licence-texts.json` (archive → path and text), listed in
  `SHA256SUMS`. A licence file is a file at the archive's top whose name is a licence's
  (`LICENSE*`, `COPYING*`, `COPYRIGHT*`, `NOTICE*`, `PATENTS`, `GPL2.txt`, …; not code or build
  files such as `license.c`, `COPYING.in`), a file in a licence folder there (`LICENSES/`,
  mingw-w64's `COPYING.MinGW-w64-runtime/`), or the same one level into a folder of vendored
  components (`vendor/`, `third_party/`, `subprojects/`, …: librsvg's vendored crates, libjxl's
  highway, GLib's proxy-libintl). A stage that checks its sources out into sub-folders gets the
  licence files one folder down. Latin-1 files are read as such, CRLF becomes LF, a link gets its
  target's text. An archive with no licence file stops the fetch (its archive kept for the rerun)
  unless `tools/licence-texts.toml` `[sources]` has its text.
- `release-workflow.py`: `sources-find` requires `licence-texts.json` in a published release's
  `SHA256SUMS`, downloads it and checks its bytes against that line (the API's digest may be
  null), and writes it to `--texts-out` (default: next to `--sums-out`); `sources-publish`
  uploads it with the archives. So a release that reuses the sources release gets the texts too.
- `release.yml`: the `sources` job passes `--texts-out`, copies the fetched file, and puts it into
  the `sources` artifact; the Linux job sets `REFRAME_SOURCES_TEXTS` (`build.sh` mounts it at
  `/sources/licence-texts.json`; the four variables together or none); the Windows and Docker
  notices get `--sources-texts`. actionlint 1.7.12 with shellcheck: clean.
- `third-party-notices.py --sources-texts FILE` (with `--sources-url`, `--sources-sums` and
  `--sources-manifest`: all four or none) adds a last section, "Licence texts of the parts in the
  sources release": one entry per archive the platform bundles, each licence file's text, a text
  seen before named instead of repeated. An Ubuntu source package's entry has the `copyright`
  file of each of its binary packages from `/usr/share/doc` (the manifest's `binary_packages`);
  outside the build image the files are missing and the run stops. An archive without a text and
  without a committed one stops the run.
- **Licences only in file headers**, found by checking every real stage (below):
  nv-codec-headers (each header: "This copyright notice applies to this header file only", MIT,
  NVIDIA or 2016) and libglvnd (the licence section at the end of its `README.md`, with X.Org,
  Mesa, uthash, buildconf and ax-pthread): their texts, read at the pinned commits, are in
  `[sources]`.

**Checked against the real sources (no full fetch).**

- Every one of the 117 BtbN stages of the current manifest: a tree-only fetch (`git fetch
  --depth=1 --filter=blob:none`) of each repository it pins, placed where its commands check it
  out, the rule applied to the tree and the chosen files' blobs read. Each stage has licence
  files but nv-codec-headers and libglvnd (now committed texts); LAME and Xvid (SVN) list
  `COPYING`, `LICENSE` and `LICENSE` at their pinned revisions over HTTPS. This check does not
  see submodules, `cargo vendor` and generated files; the real archives have them.
- A real fetch with `sources-fetch.py` of 18 entries (the 2 git trees, 7 stages: xorgproto,
  zlib, xz, OpenCL (two checkouts), dav1d, nv-codec-headers (three), libass; the 8 tarballs; the
  type2-runtime tree; 34.6 MB), on this host with stub `svn` and `meson` (no stage of the subset
  calls them). First run: it stopped at nv-codec-headers, as it should; with the committed text,
  `licence-texts.json` 373 KB, every archive with its files (xorgproto 37 `COPYING-*`, xz 5,
  FFmpeg 5, fuse `GPL2.txt`, `LGPL2.txt`, `LICENSE`, MediaInfo's source 5 one folder down).
  A rerun skipped the 18 archives and wrote the same texts.
- `docker/debian-packages.sh` in the pinned `debian:trixie-…-slim` with the runtime stage's
  `apt-get install` (same pins): 159 packages, 159 copyright files (the slim image keeps them:
  `path-include /usr/share/doc/*/copyright`; `libgcc-s1` is a link to `gcc-14-base`), 44 texts
  named as repeats, 3.6 MB appended (Boost's copyright file alone 2.2 MB: `mkvtoolnix` pulls
  `libboost-filesystem1.83.0`).

**Real runs of the notices and their size** (2026-11-14):

| Platform | Before | Now | Of which the source texts |
|---|---|---|---|
| `linux-x64` (the build image `reframe-l`, Ubuntu 22.04: `uv sync`, `bundle-tools.py`, the frozen sidecar, `npm ci`, `cargo about`, as `build-in-container.sh`) | 1.07 MB | **3.73 MB** | 2.64 MB: 223 archives (2 git, 115 stages, 7 tarballs, the runtime tree, 98 Ubuntu source packages with 138 binary packages' copyright files) |
| `docker-linux-x64` (this host, `uv run --python 3.14.8`) | 0.45 MB | **1.89 MB**, plus 3.6 MB of Debian copyright files that the image build appends: 5.5 MB in the image | 1.42 MB: 117 archives |
| `windows-x64` (not runnable here: the Windows sidecar and crates; the section alone, computed with the script's functions) | about 1 MB (0072 "Task W") | about 2.2 MB | 1.23 MB: 99 archives |
| `docker-linux-arm64` (the section alone) | about 0.45 MB | about 1.85 MB, plus the Debian files (fewer: no GPU drivers; not measured) | 1.40 MB: 114 archives |

The full runs used the full manifest (226 entries, tag `sources-b769054396f7`) with a texts file
made of the 18 fetched archives and, for the other stages, the texts of the tree-only check, and
`SHA256SUMS` with stand-in lines (the SHA-256 of each name) for the archives not fetched; the
subset runs used only real files: `linux-x64` 1.37 MB, `docker-linux-x64` 0.72 MB.

**Not covered** (each still has its name and source link, not its full text):

1. **CPython's own libraries.** The sidecar and the image use python-build-standalone 3.14.8
   (release `20261013`); its `install_only` build has CPython's `LICENSE.txt` only, not the
   texts of OpenSSL, libffi, SQLite, xz, bzip2, zlib, ncurses/libedit, mpdecimal, expat (and on
   Windows Tcl/Tk and the VC++ runtime DLLs). The release's `full` archives (113 MB for
   `x86_64-unknown-linux-gnu`) hold them in `python/licenses/`; a pin of those per platform and
   an extraction would close it.
2. **MediaInfoLib's own third-party code** in pymediainfo's `libmediainfo` (every platform: the
   strings show ZenLib, TinyXML-2, Brian Gladman's AES and SHA-256) and in `MediaInfo.exe`:
   their licences are in the headers of `Source/ThirdParty/*` (no licence files); Gladman's asks
   for its notice in a binary's documentation. Committed texts would close it.
3. **The AppImage's `AppRun` and linuxdeploy-plugin-gtk's hook** (MIT): not pinned, no text.
4. **Windows only, not checked here:** WebView2Loader inside `Reframe.exe` (webview2-com), the
   NSIS stub and plugins inside the NSIS installer, WiX's custom actions inside the MSI, the
   sidecar's DLLs; and license-checker's tree on Windows (another rolldown binding: covered by
   the glob; other native packages: not seen).

**Tests** (each fails on the defect; mutation in brackets; 38 mutations, all caught):
`test_sources_fetch.py` the files at the top [no `GPL2.txt` names; no licence folders; CRLF
kept], sub-folders [no fallback], vendored components [none], code files not taken [the filter
off], Latin-1 and links [UTF-8 with replacement; links not followed], an archive without one
stops the fetch [accepted], a committed text lets it pass [ignored], the real nv-codec-headers
pattern, the texts in `SHA256SUMS` [left out], Ubuntu archives not read [read];
`test_release_workflow.py` a reused release gives its texts [not allowed in the sums; not
written], sums without the texts, bytes not the sums' [not checked], `--texts-out` [ignored],
uploaded with the archives [not uploaded], texts written after the sums not uploaded, every
package job gets the texts from `release.yml` [the Windows option removed];
`test_third_party_notices.py` the texts per platform [every archive on every platform; no
section; the `:amd64` suffix kept], a text named once [no dedupe], a missing archive text, a
missing copyright file [each skipped], the four options together [`--sources-texts` optional],
the texts file's format [any schema], committed npm/PyPI texts with globs [exact names], none
at all [accepted], committed source texts [ignored], `javascript_entries` uses them [not],
the scripts agree on the file name, each committed text has a source and a copyright line;
`test_linux_packaging.py` the texts mounted [not], the four variables [three],
`build-in-container.sh` passes them [not]; `test_docker_image.py` each installed package's
copyright file once [no dedupe; removed packages included], a missing one stops the build
[skipped], the Dockerfile passes the notices [not].

**For the lead and W.** New input of the release: the sources release's `licence-texts.json`
(no secret). The `linux` job's `build.sh` needs `REFRAME_SOURCES_TEXTS` with the other three.
A sources release published without `licence-texts.json` (none exists yet) is "incomplete" for
`sources-find`: delete it and re-run (`docs/release.md`). A release whose new npm or PyPI
package has no licence file, or whose new source archive has none at its top, stops in the
package jobs or the sources job with the name; its text goes into `tools/licence-texts.toml`.
