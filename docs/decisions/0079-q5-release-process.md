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

(Filled by S.)

## Task A: the arm64 pin and the Docker image

(Filled by A.)

## Task W: the release workflow

(Filled by W.)

## Review and fix round

(Filled by the lead.)
