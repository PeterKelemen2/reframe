# Releasing Reframe

A release is a `v*` tag on `main`. The tag starts `.github/workflows/release.yml`, which builds
every package, publishes the Docker image, writes the updater's `latest.json` and makes the
GitHub release. This file is the procedure. The reasons are in
[decision 0079](decisions/0079-q5-release-process.md) (the release process) and
[decision 0073](decisions/0073-gpl-corresponding-source-per-tool-pin.md) (the sources release).
The workflow's decisions (which release is complete, which is the latest, the notes, the
signature) are in `scripts/release-workflow.py`.

## Once, before the first release

### The secrets and variables

Set them in the repository: *Settings → Secrets and variables → Actions*.

| Name | Kind | Required | What it is |
|------|------|----------|------------|
| `TAURI_SIGNING_PRIVATE_KEY` | secret | yes | The updater's private key: the **content** of the key file that `tauri signer generate` writes (one base64 line), not its path. |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | secret | if the key has a password | The key's password. |
| `RELEASE_GPG_PRIVATE_KEY` | secret | yes | The release key that signs `SHA256SUMS`: the armored secret key (below). |
| `RELEASE_GPG_PASSPHRASE` | secret | if the key has a passphrase | The release key's passphrase. |
| `WINDOWS_CERTIFICATE` | secret | no | The code-signing certificate with its private key, as a PFX file in base64 (`base64 -w0 cert.pfx`). Without it the Windows installers are not signed and the release notes say so. |
| `WINDOWS_CERTIFICATE_PASSWORD` | secret | with the certificate | The PFX file's password. |
| `WINDOWS_TIMESTAMP_URL` | variable | with the certificate | The certification authority's RFC 3161 timestamp server. With a timestamp a signature stays valid after the certificate expires. |

The first job checks them before anything is built: a required secret that is not set, a
certificate without its password or timestamp server, and a release key that cannot sign or that
is not the key in this file each stop the run there.

The workflow needs no other token. `GITHUB_TOKEN` gets `contents: write` in the jobs that make
releases and `packages: write` in the jobs that push the image; every other job reads only.

A certificate from a certification authority is necessary for a real release. A self-signed
certificate is trusted only on a machine where its root was imported
([decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md), task W). A cloud key
(for example Azure Trusted Signing) needs a `signCommand` in place of the PFX import: change
the workflow's signing step.

### The updater's key

The committed `plugins.updater.pubkey` in `desktop/src-tauri/tauri.conf.json` is the **release
key** (key id `F2212B5119791A8F`, made 2026-11-20); the test key of decision 0072
(`80B98CB268A32743`) is no longer trusted. It was made as follows:

```sh
cd desktop
npx tauri signer generate -w ~/.tauri/reframe-release.key   # asks for a password
```

1. Put the content of `~/.tauri/reframe-release.key.pub` into `plugins.updater.pubkey` and commit
   it (`build(Q-5): the updater's release key`).
2. Put the content of `~/.tauri/reframe-release.key` into the secret
   `TAURI_SIGNING_PRIVATE_KEY`, and its password into `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
3. Keep a copy of the key file and the password outside GitHub. **If the key is lost, the
   installed apps cannot be updated again:** a new key needs a new public key in the app, which
   only a manual install brings.

`scripts/updater-manifest.py` refuses a signature made with a key other than the committed
public key, so a release with the wrong key stops before it is published.

### The signing key of SHA256SUMS

Each release has `SHA256SUMS` (the SHA-256 of every file of the release) and `SHA256SUMS.asc`,
its detached GPG signature. That signature is what makes the AppImage, `.deb` and `.rpm` signed
downloads; users check it with the public key below ("Check a download").

1. Make the key (GnuPG asks for a passphrase):

   ```sh
   gpg --quick-gen-key 'Reframe releases' ed25519 sign never
   gpg --list-keys --with-fingerprint 'Reframe releases'
   ```

2. Put the public key into the block below, in place of the line in it, and its fingerprint
   above the block, then commit (`docs(release): the release key`):

   ```sh
   gpg --armor --export FINGERPRINT
   ```

3. Put the secret key into the secret `RELEASE_GPG_PRIVATE_KEY` and the passphrase into
   `RELEASE_GPG_PASSPHRASE`:

   ```sh
   gpg --armor --export-secret-keys FINGERPRINT
   ```

4. Keep a copy of the secret key and the passphrase outside GitHub. A new key later means a new
   block here; the signatures of older releases stay checkable with the old public key, so keep
   it in this file's history.

The workflow reads the first public key block of this file: its first job signs a test file
with the secret and checks the signature with that block, and the release job does the same with
the real `SHA256SUMS`. Until the block holds a key, no release can be made.

The release key (fingerprint: `72D5 8F6B A476 19BF 9E1C  91A5 DE34 47FC 73F7 8AB9`, made
2026-11-20):

```text
-----BEGIN PGP PUBLIC KEY BLOCK-----

mDMEawBhWBYJKwYBBAHaRw8BAQdAQFcPdNNxMBOemQPCnC1Daud9GU24jeJ+DrsQ
U7IM4+i0EFJlZnJhbWUgcmVsZWFzZXOIkAQTFgoAOBYhBHLVj2ukdhm/nhyRpd40
R/xz94q5BQJrAGFYAhsDBQsJCAcCBhUKCQgLAgQWAgMBAh4BAheAAAoJEN40R/xz
94q56+kA/1F6hbA8pM1EIBzubI5yyTFSLvaemX56Gqk85gfoshZYAP9v5g2+Agym
GjI57qBMnKSI1mGTKoal/aocH2wrIg9LCg==
=VCKE
-----END PGP PUBLIC KEY BLOCK-----
```

### Visibility

- The workflow refuses to run while the repository is private (its first job): make the
  repository public before the first release.
- The updater reads `https://github.com/PeterKelemen2/reframe/releases/latest/download/latest.json`.
  It finds nothing while the repository is private: every update check fails quietly.
- The sources release must be as easy to reach as the packages (0073): in the same repository,
  with the same visibility.
- A new GHCR package is private. After the first run, set `ghcr.io/peterkelemen2/reframe` to
  public (*Packages → reframe → Package settings*).

## Each release

The version is `X.Y.Z` (the same in PEP 440 and SemVer). The tag is `v` and that version
(`v1.1.0`).

1. **Start from `main`** with every CI job green.
2. **Set the version** in every version field:

   ```sh
   uv run --no-project python scripts/stamp-version.py --set 1.1.0
   uv run --no-project python scripts/stamp-version.py --check
   ```

3. **Write the changelog.**
   - The first release (`v1.0.0`): write its section in `CHANGELOG.md` by hand from
     `docs/status.md`, in place of the comment under `## [Unreleased]`. The commits before it
     are not conventional commits.
   - Every later release: let git-cliff write the section from the commits since the last `v*`
     tag, then read it and correct it:

     ```sh
     uv tool run git-cliff==2.14.2 --unreleased --tag v1.1.0 --prepend CHANGELOG.md
     ```

   Check the section that the release notes and `latest.json` will use:

   ```sh
   uv run --no-project python scripts/release-notes.py 1.1.0
   ```

4. **Commit** the version fields and the changelog: `chore(release): v1.1.0`.
5. **Tag and push** the commit and the tag:

   ```sh
   git tag -a v1.1.0 -m "Reframe 1.1.0"
   git push origin main v1.1.0
   ```

   Push one `v*` tag at a time. The workflow runs one release at a time and GitHub keeps only
   one run waiting: when a third tag's run arrives while the first runs, GitHub cancels the
   waiting second one. Start a cancelled run again with *Re-run all jobs* once the running one
   has finished.
6. **Watch the workflow** (*Actions → Release*). The sources job takes longer when it makes a
   new sources release (it downloads every source archive; it stops after five hours); the
   Linux and Windows builds stop after two hours.
7. **Check the release** (below).

**Pre-releases are not supported in v1.** The workflow refuses a tag whose version has a
pre-release part (`1.1.0rc1`, `1.1.0b2`, `0.1.0.dev0`). Its SemVer spelling (`1.1.0-rc.1`)
cannot build the MSI (WiX accepts only a numeric pre-release), and dpkg sorts `1.1.0-rc.1`
after `1.1.0`, so apt would not upgrade an rc to its release (0079, task V). The MSI also limits
the version to 255.255.65535.

**The latest release.** A release becomes GitHub's "Latest" (which the updater reads) and the
image tag `latest` only when its version is the highest `vX.Y.Z` tag. A patch of an older line
(`v1.0.5` after `v1.1.0`) is published without moving them.

## What the workflow does

| Job | What |
|-----|------|
| Version, secrets and visibility | `stamp-version.py --check`, then `release-workflow.py preflight`: the tag is `v` and the stamped version, the version is `X.Y.Z` within the MSI's limits, the secrets are set (the certificate with its password and timestamp server), the repository is public; and whether the version is the highest `vX.Y.Z` tag (the latest). `release-notes.py` finds the version's section in `CHANGELOG.md`. `release-workflow.py sums` signs a test file with the release key and checks it with the key in this file. |
| Sources release | `desktop/packaging/linux/appimage-libs.sh` reads the distro packages that the AppImage will carry (dpkg in the Linux build image); `sources-manifest.py` writes the source manifest and gives its tag `sources-<12 hex>`: the libva source, the AppImage runtime's tree and the libraries it links, and the Ubuntu source packages of the AppImage's distro packages. No package conveys FFmpeg, so its sources are not in it ([decision 0094](decisions/0094-docker-image-without-ffmpeg.md)). `release-workflow.py sources-find` looks for a release with that tag: a published one is used only when it has the manifest, `SHA256SUMS`, `licence-texts.json` and every archive with the expected SHA-256; a draft (an interrupted upload) is deleted. Otherwise `sources-fetch.py` downloads and checks one archive per entry in the image of `desktop/packaging/sources/Dockerfile` (Ubuntu 26.04), it also writes `licence-texts.json`, the licence files of each archive (the Ubuntu source packages' come from the Linux build image's `/usr/share/doc` instead), and `release-workflow.py sources-publish` uploads the manifest, the archives, `licence-texts.json` and `SHA256SUMS` to a draft and publishes it when GitHub has every file: never "latest", with no `v` in its tag. The other jobs get its URL, the manifest, `SHA256SUMS`, `licence-texts.json` and the AppImage package list. |
| Linux packages | `desktop/packaging/linux/build.sh` builds the AppImage, `.deb` and `.rpm` in the Ubuntu 22.04 build image, with notices that name the sources release, and checks that the AppImage carries exactly the distro packages the manifest lists. `install-test.sh` installs, runs and removes them in Ubuntu 22.04, Debian 12 and Fedora. |
| Windows installers | The tools layout, the frozen sidecar, the notices, then `tauri build` (NSIS and MSI), signed with the certificate when it is set. `desktop/packaging/windows/no-ffmpeg-check.py` fails the job when the layout, or an installer's contents (7-Zip for NSIS, `msiexec /a` for the MSI), has `ffmpeg.exe`, `ffprobe.exe` or an FFmpeg DLL. `tauri signer sign --app-version` signs the NSIS installer for the updater. |
| Docker image | One build per platform, each on a runner of that architecture (`ubuntu-24.04`, `ubuntu-24.04-arm`) and with its own `docker/notices/THIRD_PARTY_NOTICES`. Each is pushed to GHCR by digest only, without a tag. |
| Docker image tags | After the Linux and Windows jobs have passed: one multi-platform image tagged with the version, and with `latest` when the version is the latest. |
| GitHub release | `latest.json` from `updater-manifest.py` (the NSIS installer only); the notes from `release-workflow.py notes` (the changelog section, a line when the installers are not signed, how to check a download, the sources release's URL and its `SHA256SUMS`); `SHA256SUMS` of every file and `SHA256SUMS.asc` (`release-workflow.py sums`); then `release-workflow.py publish`: a leftover draft of the tag is deleted, the files go to a draft, and the draft is published (as "Latest" only for the latest version) when GitHub has every file with its SHA-256. A release that is published already is never replaced. |

`latest.json` has only the Windows NSIS installer. The AppImage and `.deb` entries are added
once their update path is verified (not done: [decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md),
task W); until then Linux installs get no update offer. The MSI and the `.rpm` are never
updated by the app.

Each package's `THIRD_PARTY_NOTICES` names the sources release, lists the SHA-256 of the
archives of the parts that this platform bundles and carries their licence texts; the release
notes list them all. A part without a licence text stops the notices: a new npm or PyPI package
that ships none needs its text in `tools/licence-texts.toml`, a new source archive with no
licence file at its top a look at `select_licence_files` in `scripts/sources-fetch.py`.

## When a run fails

Fix the cause, then use *Re-run failed jobs*. What a failed run leaves:

- **A sources release** that was published stays and is used again by the next run with the
  same manifest.
- **A draft sources release or a draft release** (a cancelled, timed-out or failed upload): the
  next run deletes it and uploads again. Nobody but the repository's maintainers sees a draft.
- **A published sources release without all its files** (made by hand or by an older
  workflow): the sources job stops and names the missing files. If no Reframe release names it,
  delete it (`gh release delete sources-… --cleanup-tag`) and re-run.
- **The Linux job fails when apt moved**: an Ubuntu package of the AppImage got a new version
  between the sources job and the Linux build, so the AppImage would not match the manifest.
  Re-run the whole workflow (*Re-run all jobs*): it makes a new manifest, so a new sources
  release.
- **The sources job fails during the fetch**: github.com and the Ubuntu archive sometimes
  refuse connections after many clones (each clone and download is tried 3 times). Re-run it:
  the fetch starts again from the beginning on a new runner.
- **Docker image digests without a tag** in GHCR. They are not visible to `docker pull` by tag.
  Delete them in the package's settings if you like.
- **"The release v1.1.0 is published already"**: a re-run after the release was published. The
  release is not changed. To replace a release, delete it first (only if nobody should have
  downloaded it).

If the commit itself is wrong, delete the tag (`git push origin :refs/tags/v1.1.0`,
`git tag -d v1.1.0`), fix, commit, and tag again. Never move a tag that was published as a
release.

## Check the release

The first release also checks the workflow itself: it has never run on GitHub (0079).

- The release has the AppImage, `.deb`, `.rpm`, the NSIS installer and its `.sig`, the MSI,
  `latest.json`, `SHA256SUMS` and `SHA256SUMS.asc`. `latest.json` names the version and the NSIS
  installer's URL.
- The checks of "Check a download" pass with the key in this file.
- The notes have the changelog section, how to check a download, the sources link and the
  sources' `SHA256SUMS`; and the "not code-signed" line only when the certificate was not set.
- The release is "Latest", and the image has the tag `latest`, only when its version is the
  highest `vX.Y.Z` tag.
- An app of the previous version on Windows offers the update, installs it and starts the new
  version ([decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md), task W, "The
  updater").
- `notices/THIRD_PARTY_NOTICES` in a package and `/opt/reframe/notices/THIRD_PARTY_NOTICES` in
  the image name the same sources release as the notes.
- The sources release has one archive per manifest entry and `licence-texts.json`, and
  `sha256sum -c SHA256SUMS` passes in a folder with them. The first time, record its total
  size (more than 1 GB was measured while it held FFmpeg's sources: 0079, task S). GitHub's
  limit is 2 GiB per file; the largest archive measured then was about 263 MB.
- `docker pull ghcr.io/peterkelemen2/reframe:1.1.0` on amd64 and on arm64; the server starts and
  answers (`docs/deployment.md`). arm64 has software encoders only.
- The AppImage on a desktop: `desktop/packaging/linux/appimage-test.sh` (it needs KWin, so it
  runs on a developer machine, not in the workflow).
- The Windows installers' signatures (signed releases): `Get-AuthenticodeSignature` says
  `Valid`; the SmartScreen prompt names the publisher.
- The first runs only: the free disk space that the sources and Linux jobs print or need (the
  sources job holds the Linux build image, the fetch image and the archives;
  locally the Linux build image and its cache volumes take about 8 GB), and each job's time.
- The arm64 image job runs on `ubuntu-24.04-arm`. If that runner is not available to the
  repository, change the job to `ubuntu-24.04` with `docker/setup-qemu-action`.

## Check a download

Each release has `SHA256SUMS` and its signature `SHA256SUMS.asc`. Save the key block of "The
signing key of SHA256SUMS" (above, in this file on GitHub) as `reframe-release-key.asc`, put the
downloads, `SHA256SUMS` and `SHA256SUMS.asc` in one folder, then:

```sh
gpg --import reframe-release-key.asc
gpg --verify SHA256SUMS.asc SHA256SUMS          # "Good signature", and the fingerprint above
sha256sum --check --ignore-missing SHA256SUMS   # "OK" for each download
```

GnuPG warns that the key is not certified with a trusted signature; the fingerprint that
`gpg --verify` prints must be the one above. On Windows, `Get-FileHash FILE` prints the SHA-256
to compare with the file's line in `SHA256SUMS`; the installers of a signed release also carry
an Authenticode signature (*Properties → Digital Signatures*).

## Keep or delete old releases

- An app release can be deleted when nobody should download it any more.
- **A sources release stays as long as any app release or image that names it can be
  downloaded** (0073 item 5). Before you delete an app release, look up which sources release
  its notes name. Delete a sources release only when no remaining app release or image tag
  names it.
- Never mark a sources release as "latest" and never give it a `v` tag: the updater reads the
  latest release, and a `v*` tag starts the release workflow.

## Installers from a development tree

The committed version between releases is a development version (`0.1.0.dev0`, SemVer
`0.1.0-dev.0`). Tauri's MSI takes only a numeric pre-release, so on Windows `npx tauri build`
builds the NSIS installer and then stops at the MSI ("optional pre-release identifier in app
version must be numeric-only … for msi target"). From a development tree, build the NSIS
installer only:

```sh
npx tauri build --bundles nsis
```

On Linux, `desktop/packaging/linux/build.sh` builds the .deb, the .rpm and the AppImage, and
Tauri's rpm bundler refuses a `-` in the version ("invalid version \"0.1.0-dev.0\": contains
invalid character"), so a full Linux build from a development tree fails at the rpm.

For an MSI, a Linux build (or an update test that needs two versions), stamp a final version
into the working tree first and do not commit it:

```sh
uv run --no-project python scripts/stamp-version.py --set 0.1.3
```

## Not part of a release

- No `reframe` wheel on PyPI for v1 (0079 item 8).
- No package signature inside the `.deb` and `.rpm` (no apt or dnf repository): the signed
  `SHA256SUMS` covers them.
- No macOS build.
