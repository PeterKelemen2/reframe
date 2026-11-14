# Releasing Reframe

A release is a `v*` tag on `main`. The tag starts `.github/workflows/release.yml`, which builds
every package, publishes the Docker image, writes the updater's `latest.json` and makes the
GitHub release. This file is the procedure. The reasons are in
[decision 0079](decisions/0079-q5-release-process.md) (the release process) and
[decision 0073](decisions/0073-gpl-corresponding-source-per-tool-pin.md) (the sources release).

## Once, before the first release

### The secrets and variables

Set them in the repository: *Settings → Secrets and variables → Actions*.

| Name | Kind | Required | What it is |
|------|------|----------|------------|
| `TAURI_SIGNING_PRIVATE_KEY` | secret | yes | The updater's private key: the **content** of the key file that `tauri signer generate` writes (one base64 line), not its path. Without it the workflow stops in its first job, before it publishes anything. |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | secret | if the key has a password | The key's password. |
| `WINDOWS_CERTIFICATE` | secret | no | The code-signing certificate with its private key, as a PFX file in base64 (`base64 -w0 cert.pfx`). Without it the Windows installers are not signed and the release notes say so. |
| `WINDOWS_CERTIFICATE_PASSWORD` | secret | with the certificate | The PFX file's password. |
| `WINDOWS_TIMESTAMP_URL` | variable | with the certificate | The certification authority's RFC 3161 timestamp server. With a timestamp a signature stays valid after the certificate expires. |

The workflow needs no other token. `GITHUB_TOKEN` gets `contents: write` in the jobs that make
releases and `packages: write` in the jobs that push the image; every other job reads only.

A certificate from a certification authority is necessary for a real release. A self-signed
certificate is trusted only on a machine where its root was imported
([decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md), task W). A cloud key
(for example Azure Trusted Signing) needs a `signCommand` in place of the PFX import: change
the workflow's signing step.

### The updater's key

The committed `plugins.updater.pubkey` in `desktop/src-tauri/tauri.conf.json` is the **test key**
(key id `80B98CB268A32743`). Before the first release, replace it with the release key:

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

### Visibility

- The updater reads `https://github.com/PeterKelemen2/reframe/releases/latest/download/latest.json`.
  It finds nothing while the repository is private: every update check fails quietly.
- The sources release must be as easy to reach as the packages (0073): in the same repository,
  with the same visibility.
- A new GHCR package is private. After the first run, set `ghcr.io/peterkelemen2/reframe` to
  public (*Packages → reframe → Package settings*).

## Each release

The version is PEP 440 (`1.0.0`, `1.1.0rc1`). The tag is `v` and that version (`v1.1.0rc1`).

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

4. **Commit** the version fields and the changelog: `chore(release): 1.1.0`.
5. **Tag and push** the commit and the tag:

   ```sh
   git tag -a v1.1.0 -m "Reframe 1.1.0"
   git push origin main v1.1.0
   ```

6. **Watch the workflow** (*Actions → Release*). The Linux and Windows builds take the longest;
   each job stops after two hours.
7. **Check the release** (below).

A version with a pre-release part (`1.1.0rc1`, `1.1.0b2`) is published as a GitHub
pre-release. It is never "latest", so the updater does not offer it and the Docker image gets
no `latest` tag. Users who want it download it from the release page.

## What the workflow does

| Job | What |
|-----|------|
| Version and secrets | `stamp-version.py --check`: every version field agrees, and the tag is `v` and that version. `release-notes.py` finds the version's section in `CHANGELOG.md`. The updater's key secret is set. |
| Sources release | Reads the distro packages that the AppImage will carry (`appimage-libs.py resolve`, with dpkg in the Linux build image), writes the source manifest with `sources-manifest.py` and gets its tag `sources-<12 hex>`. If no release has that tag, `sources-fetch.py` downloads and checks one archive per entry, and the job makes the release: the manifest, the archives and `SHA256SUMS`, never "latest", with no `v` in its tag. The other jobs get its URL and `SHA256SUMS`. |
| Linux packages | `desktop/packaging/linux/build.sh` builds the AppImage, `.deb` and `.rpm` in the Ubuntu 22.04 build image, with notices that name the sources release. `install-test.sh` installs, runs and removes them in Ubuntu 22.04, Debian 12 and Fedora. |
| Windows installers | The tools layout, the frozen sidecar, the notices, then `tauri build` (NSIS and MSI), signed with the certificate when it is set. `tauri signer sign --app-version` signs the NSIS installer for the updater. |
| Docker image | One build per platform (`linux/amd64`, and `linux/arm64` under QEMU), each with its own `docker/notices/THIRD_PARTY_NOTICES`. Each is pushed to GHCR by digest only, without a tag. |
| Docker image tags | After the Linux and Windows jobs have passed: one multi-platform image tagged with the version, and `latest` for a release that is not a pre-release. |
| GitHub release | `latest.json` from `updater-manifest.py` (the NSIS installer only), the notes (the changelog section, a line when the installers are not signed, the sources release's URL and its `SHA256SUMS`), then the release as a draft with every file, published when the upload is complete. |

`latest.json` has only the Windows NSIS installer. The AppImage and `.deb` update path is not
checked yet ([decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md), task W), so
Linux installs get no update offer. The MSI and the `.rpm` are never updated by the app.

## When a run fails

Fix the cause, then use *Re-run failed jobs*. What a failed run leaves:

- **A sources release** stays and is used again by the next run with the same manifest.
- **Docker image digests without a tag** in GHCR. They are not visible to `docker pull` by tag.
  Delete them in the package's settings if you like.
- **A draft release**, if the last job failed during the upload. Delete the draft
  (`gh release delete v1.1.0`, which keeps the tag) and re-run the job.

If the commit itself is wrong, delete the tag (`git push origin :refs/tags/v1.1.0`,
`git tag -d v1.1.0`), fix, commit, and tag again. Never move a tag that was published as a
release.

## Check the release

The first release also checks the workflow itself: it has never run on GitHub (0079).

- The release has the AppImage, `.deb`, `.rpm`, the NSIS installer and its `.sig`, the MSI and
  `latest.json`. `latest.json` names the version and the NSIS installer's URL.
- The notes have the changelog section, the sources link and the `SHA256SUMS`; and the
  "not code-signed" line only when the certificate was not set.
- An app of the previous version on Windows offers the update, installs it and starts the new
  version ([decision 0072](decisions/0072-m10-bundling-packaging-smoke-tests.md), task W, "The
  updater").
- `notices/THIRD_PARTY_NOTICES` in a package and `/opt/reframe/notices/THIRD_PARTY_NOTICES` in
  the image name the same sources release as the notes.
- The sources release has one archive per manifest entry, and `sha256sum -c SHA256SUMS` passes
  in a folder with them. The first time, record its total size (0073 left it unmeasured).
- `docker pull ghcr.io/peterkelemen2/reframe:1.1.0` on amd64 and on arm64; the server starts and
  answers (`docs/deployment.md`). arm64 has software encoders only.
- The AppImage on a desktop: `desktop/packaging/linux/appimage-test.sh` (it needs KWin, so it
  runs on a developer machine, not in the workflow).
- The Windows installers' signatures (signed releases): `Get-AuthenticodeSignature` says
  `Valid`; the SmartScreen prompt names the publisher.
- The first runs only: the Linux job's free disk space on the runner (locally the build image and
  its cache volumes take about 8 GB, plus the container's copy of the tree) and its time.

## Keep or delete old releases

- An app release can be deleted when nobody should download it any more.
- **A sources release stays as long as any app release or image that names it can be
  downloaded** (0073 item 5). Before you delete an app release, look up which sources release
  its notes name. Delete a sources release only when no remaining app release or image tag
  names it.
- Never mark a sources release as "latest" and never give it a `v` tag: the updater reads the
  latest release, and a `v*` tag starts the release workflow.

## Not part of a release

- No `reframe` wheel on PyPI for v1 (0079 item 8).
- The Linux packages are not GPG-signed.
- No macOS build.
