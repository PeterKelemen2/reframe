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

(Filled by A.)

## Task W: the release workflow

Built 2026-11-14 on the AMD desktop. Nothing ran on GitHub (nothing is pushed).

**`.github/workflows/release.yml`** (on `v*`; workflow `permissions: contents: read`, one
`concurrency` group without cancelling, `UV_FROZEN=1`, every action pinned by commit SHA):

1. `version`: `stamp-version.py --check` prints the version and the tag must be `v` and it;
   `--print-semver` gives the SemVer spelling; a SemVer with `-` is a pre-release.
   `release-notes.py VERSION` must find a section. `TAURI_SIGNING_PRIVATE_KEY` must be set: the
   run stops here, before anything is published.
2. `sources` (`contents: write`): the AppImage library list, `sources-manifest.py --out …
   --appimage-libs …` → the tag; `gh release view TAG` or else `sources-fetch.py` and
   `gh release create TAG --latest=false --target $GITHUB_SHA` with the manifest, the archives
   and `SHA256SUMS`. Outputs: the tag and its URL; `SHA256SUMS` as the artifact `sources-sums`.
3. In parallel:
   - `linux`: `build.sh dist/linux` with `REFRAME_SOURCES_URL` and `REFRAME_SOURCES_SUMS`
     (a path in the working tree: `build.sh` carries untracked files into the container), then
     the multitrack fixture and `install-test.sh dist/linux` (0072 task L's release-job
     commands; `appimage-test.sh` needs KWin and is a manual check in `docs/release.md`).
   - `windows` (0072 task W's job list): `bundle-tools.py --platform windows-x64`, the sidecar,
     `cargo install --locked cargo-about@0.9.3 --features cli`, the notices with
     `PYTHONUTF8=1` and `--sources-url/--sources-sums`; when the secret `WINDOWS_CERTIFICATE` is
     set, the PFX goes into `Cert:\CurrentUser\My` and an overlay with its thumbprint,
     `digestAlgorithm` `sha256`, `timestampUrl` (variable `WINDOWS_TIMESTAMP_URL`, required
     with the certificate) and `tsp` true is passed to `tauri build --config`, then
     `Get-AuthenticodeSignature` must say `Valid` for both installers; output `signed`. Then
     `tauri signer sign --app-version SEMVER` of the NSIS installer (key and password from the
     secrets, in that step's environment only). `createUpdaterArtifacts` stays off, as 0072
     chose.
   - `docker` (`packages: write`), one job per platform: the notices for
     `docker-linux-x64|arm64` into `docker/notices/THIRD_PARTY_NOTICES` (one file per build
     context, so one build per platform: task A's Dockerfile checks the file's platform), QEMU
     for arm64, `docker buildx build --platform linux/ARCH` pushed **by digest only**
     (`push-by-digest=true`), the digest as an artifact.
4. `docker-tags`, after `docker`, `linux` and `windows`: `docker buildx imagetools create` with
   the version tag, plus `latest` for a non-pre-release. No tag is published unless every
   package built.
5. `release` (`contents: write`): `release-notes.py` → `updater-manifest.py` (the NSIS installer
   only) → the notes (the changelog section, a "not code-signed" line when `signed` is not
   true, the sources URL and its `SHA256SUMS`) → `gh release create --verify-tag --draft` with
   the AppImage, `.deb`, `.rpm`, NSIS + `.sig`, MSI and `latest.json`, then `gh release edit
   --draft=false --latest` (or `--prerelease --latest=false`). The draft keeps
   `releases/latest/download/latest.json` from pointing at a release whose files are not all up.

Choices beyond the spec's words, each small: a pre-release version becomes a GitHub
pre-release, never "latest" (the updater would offer an rc to everyone) and gets no Docker
`latest`; the Linux install test runs before anything is published; `latest.json` has no Linux
entries (0072 task W: the AppImage/deb update is not checked).

**`scripts/updater-manifest.py`** (the contract, plus `--tauri-config`, default the committed
`tauri.conf.json`): one platform entry per artefact, `{"signature": <the .sig file>, "url":
<base-url>/<name>}`, `version`, `notes`, `pub_date` (RFC 3339, UTC). It refuses what the app
would refuse after download: a `.sig` without `version:` or with another version (the app has
`requireSignedVersion`), with another `file:`, or by a key whose id is not the committed
`pubkey`'s; a version that is not SemVer (PEP 440 `1.1.0rc1`); an artefact the app never
updates (MSI, rpm); two artefacts for one target; a non-https URL.

**Checked against the real tools** (not memory):

- `tauri-plugin-updater` 2.14.1 (its source in the cargo registry): the static format
  (`version` parsed as SemVer after stripping `v`, optional `notes`, `pub_date` RFC 3339,
  `platforms.<target>.{url, signature}`); the target is `{os}-{arch}-{installer}` then
  `{os}-{arch}` (`windows-x86_64-nsis`, `linux-x86_64-appimage`, `linux-x86_64-deb`); the
  signature field is base64 of the minisign signature text; the version check reads `version:`
  from the trusted comment.
- `tauri signer` (tauri-cli 2.12.4), with a throwaway key in the scratch folder: `.sig` = base64
  of `untrusted comment…`, a 74-byte signature line (`ED` + 8-byte key id + 64), `trusted
  comment: timestamp:…<TAB>file:<basename><TAB>version:<v>`; the public key's line is `Ed` +
  the same key id + 32 bytes, so the key id check needs no cryptography; the key's content in
  `TAURI_SIGNING_PRIVATE_KEY` signs as `-f` does. The committed `pubkey`'s key id is
  `80B98CB268A32743` (0072's test key). The test uses a real signature and public key from this
  run.
- `config.schema.json` of tauri-cli 2.12.4: `bundle.windows.certificateThumbprint`,
  `digestAlgorithm`, `timestampUrl`, `tsp`.
- The signing step's overlay and `GITHUB_OUTPUT` line in PowerShell 7.4 (the
  `mcr.microsoft.com/powershell` image, removed after): valid JSON without a BOM.
- The `run:` blocks of the `version` job (on V's stamped tree: a matching tag passes, `v0.1.0`
  against `0.1.0.dev0` fails), `windows` (the `--config` array with and without signing; the
  signer command), `docker-tags` and `release` (with `gh`/`docker`/`npx` stubs that print their
  arguments, the real `updater-manifest.py` and a real signature) under `bash -eo pipefail`.
- The action SHAs from `gh api` (`upload-artifact` v7.0.2, `download-artifact` v8.0.2,
  `setup-qemu-action` v4.4.0, `setup-buildx-action` v4.4.1) and their inputs from their
  `action.yml`.
- actionlint 1.7.12 (`uv tool run --from actionlint-py==1.7.12.25 --with
  shellcheck-py==0.11.0.1 actionlint`, so its shellcheck rule runs): no findings.

**Not verified** (needs GitHub, a certificate or buildx): any job on a runner; the classic
builder (`DOCKER_BUILDKIT=0`) and the disk space of `ubuntu-latest` for `build.sh` (locally
about 8 GB of image and cache volumes); buildx's `containerimage.digest` metadata key and
`imagetools create --annotation`; the arm64 build under QEMU (time); signing with a CA
certificate and an RFC 3161 server; `gh release` against the real repository; the updater
reading a `latest.json` from a real release.

**Interfaces this workflow assumes from other tasks** (the lead reconciles):

- The AppImage library list for `sources-manifest.py --appimage-libs` is written in the Linux
  build image by `uv run --no-project python scripts/appimage-libs.py resolve --out FILE`
  (task S's interface as its unfinished tree showed it; the `sources` job builds the image and
  runs that). The `linux` job builds the image again on another runner: an Ubuntu package
  updated in between makes the AppImage differ from the manifest (S's `check` would find it).
- `build.sh` passes `REFRAME_SOURCES_URL` and `REFRAME_SOURCES_SUMS` into the container, and
  `build-in-container.sh` gives them to `third-party-notices.py` as `--sources-url` and
  `--sources-sums` (neither file is task W's).
- `third-party-notices.py --platform docker-linux-*` runs with `uv sync` and `npm ci` in
  `frontend/` done, and needs no frozen sidecar or cargo-about.
- `sources-fetch.py --out DIR` writes only the archives and `SHA256SUMS` into `DIR` (the
  manifest is uploaded from outside it; a second `manifest.json` in `DIR` would collide).

## Review and fix round

(Filled by the lead.)
