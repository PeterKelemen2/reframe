# 0105 — A v0.9.0 release rehearses the pipeline; v1's Windows installers are unsigned

- Status: accepted
- Date: 2026-11-24
- Steps: Q-5, D-8

## Context

[Decision 0103](0103-owner-decisions-before-v1.md) ("Order") and the roadmap (§Owner decisions
before the release checklist) have a `v1.0.0-rc.1` tag try the release pipeline before the
user docs. The release workflow cannot release it: since Q-5
([0079](0079-q5-release-process.md), `docs/release.md` §Pre-releases) it refuses a version with
a pre-release part, because WiX builds no MSI for a non-numeric pre-release and dpkg sorts
`1.0.0-rc.1` after `1.0.0`. `scripts/release-workflow.py preflight` says
`'1.0.0rc1' is not X.Y.Z: pre-releases are not released`.

The release checklist asks for a signed Windows installer. No code-signing certificate is set
(`WINDOWS_CERTIFICATE`); the workflow then releases unsigned installers and says so in the
release notes.

## Decision

1. **A rehearsal release `v0.9.0`** (the owner's choice, 2026-11-24): a real, public release
   with a plain version. It runs every job of the release workflow on GitHub for the first
   time. Its `CHANGELOG.md` section is the hand-written first one. `v1.0.0` follows after the
   user docs and the release checklist, and checks the updater from an installed 0.9.0.
2. **Unsigned Windows installers in v1** (the owner's choice): no certificate. SmartScreen
   warns at the first install; the release notes say that the installers are not signed. A
   certificate can be added later without a code change (`docs/release.md`, "Once, before the
   first release").

## Consequences

- `v0.9.0` is GitHub's "Latest" release, and the updater offers it, until `v1.0.0`.
- A failure of the release workflow is fixed and released as `v0.9.1`; a published release is
  never replaced.
- From `v1.0.0` on, git-cliff writes each section from the commits since the last `v*` tag.
- The checklist item "Windows installer (signed)" becomes "unsigned, said in the notes".

## Plan changes

- `08-roadmap.md`: §Owner decisions before the release checklist (the rehearsal release), the
  release checklist (unsigned Windows installers; the updater from 0.9.0 to 1.0.0).
- `09-quality-and-release.md` §Q-5: the installers of v1 are unsigned.
- `01-scope.md`, open question 6: the answer on signing.
- `docs/release.md`: the first release is `v0.9.0`.
