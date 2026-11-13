# 0073 — GPL corresponding source: one sources release per set of pinned builds

- Status: accepted
- Date: 2026-11-13
- Steps: Q-5, D-8, S-6

This is not legal advice. Review it before any public or commercial distribution.

## Context

[09 §Licensing](../plan/09-quality-and-release.md#licensing) says that every artefact that
bundles a GPL build must ship the licence and the corresponding source, or a written offer, for
the exact build that ships. It left open how. The M10 review found that no artefact does this
yet ([0072](0072-m10-bundling-packaging-smoke-tests.md) "Review and fix round", R1-5).
`THIRD_PARTY_NOTICES` gives only repository and commit links.

What the artefacts bundle, from the pins and the package builds of 0072:

| Part | Licence | Where | Pin |
|------|---------|-------|-----|
| FFmpeg, BtbN `gpl-shared` (`--enable-gpl --enable-version3`), and the libraries the build links | GPL-3.0-or-later | every artefact | `tools/ffmpeg.toml`: `source_commit`, `build_scripts_commit` (the BtbN scripts pin each dependency's source) |
| MKVToolNix 103.0 (`mkvpropedit.exe`) | GPL-2.0-only | Windows installers | `tools/bundled-tools.toml`: `source_url` |
| MediaInfo CLI 26.10 | BSD-2-Clause | Windows installers | `tools/bundled-tools.toml`: `source_url` |
| libva 2.24.1 | MIT | Linux packages | `tools/bundled-tools.toml` |
| WebKitGTK, GTK and the other libraries linuxdeploy copies from Ubuntu 22.04 | mostly LGPL-2.1+ | AppImage | none: the versions are whatever the build image's apt gives |

The owner chose between three ways (2026-11-13):

1. **Attach the source archives to every app release.** Simple to show, but each release
   uploads the same large archives again, although the pins change rarely.
2. **A written offer.** Least work. GPLv3 §6(b) ties a written offer to distribution in a
   physical product; for downloads §6(d) asks for equivalent access to the source. FFmpeg ships
   as GPL-3.0-or-later here, so an offer alone is the weakest choice.
3. **One sources release per set of pinned builds** (chosen). The archives go up once for each
   set of source versions, and every app release links to the set it was built from.

## Decision

1. **A source manifest.** The release workflow writes a manifest of every third-party part that
   an artefact bundles under GPL or LGPL: the FFmpeg commit and the BtbN build-scripts commit,
   each dependency source that those scripts pin, MKVToolNix, and the Debian source package and
   version of each distro library that linuxdeploy copies into the AppImage (from `dpkg -S` and
   `dpkg-query` in the build image). The Docker image's bundled FFmpeg comes from the same pin.
   The manifest also lists MediaInfo and libva: no licence requires their source, but their
   archives are small and are already downloaded.
2. **The manifest's hash names a sources release.** The sources release has the tag
   `sources-<first 12 hex digits of the manifest's SHA-256>`. It holds the manifest, one
   archive for each entry, and a `SHA256SUMS` file. If a release with that tag exists, the
   workflow uses it. If not, the workflow creates it before the app release.
3. **Each app release names its sources release.** `THIRD_PARTY_NOTICES` (from
   `scripts/third-party-notices.py`) and the release notes give the sources release's URL and
   the SHA-256 of each archive.
4. **A sources release is never GitHub's "latest" and never has a `v*` tag.** The updater reads
   `releases/latest/download/latest.json` (`desktop/src-tauri/tauri.conf.json`), and a `v*` tag
   starts the release workflow. So the workflow creates a sources release with
   `--latest=false` and with no `v` in front of its tag.
5. **Retention.** A sources release stays as long as any app release or image that links to it
   can be downloaded. Before you delete an old app release, check which sources release it
   names. Delete the sources release only when nothing else names it.
6. **No written offer.** The notices say where the source is, not that it can be asked for.

## Consequences

- Q-5's release workflow gets a job that writes the manifest, makes the sources release if it
  does not exist, and gives its URL to the notices. This job must run before the package builds
  put the notices into the packages.
- Before Q-5 relies on the BtbN scripts, check what they pin for each dependency (a git commit
  or a tarball and its checksum) and how to fetch exactly that source. Record the result in the
  Q-5 record. Do not use memory for this.
- The AppImage's distro libraries float with the build image. A rebuild that picks up a newer
  Ubuntu package makes a new manifest, so it makes a new sources release. Pinning the build
  image by digest makes this less frequent. Q-5 decides whether to pin it.
- The size of one sources release is not measured yet. It is expected to be hundreds of MB.
  Measure it when the first sources release is made.
- The repository is private now, so nothing is distributed yet. A sources release must be as
  easy to reach as the binaries: in the same repository, with the same visibility.
- The Docker image's base distro packages are not in the manifest. The image carries FFmpeg
  from the same pin, so it names the same sources release. Q-5 decides whether to add the base
  image's GPL and LGPL packages to the manifest or to name the base image's digest and its
  distro's source archive.

## Plan changes

- `09-quality-and-release.md` §Licensing: the corresponding-source bullet names this decision.
  §Q-5: a bullet for the sources release.
- `08-roadmap.md` §Release checklist: the corresponding-source item.
