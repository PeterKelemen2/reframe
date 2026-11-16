# 0086 — `probe_hash` is no longer written

- Status: accepted
- Date: 2026-11-16
- Steps: C-2, C-3, Q-6.13

## Context

The job sketch in `05-core.md` (C-2) says a `SourceRef` holds "path + fingerprint (size, mtime,
probe hash)". The prober filled `SourceFingerprint.probe_hash` with `layout_hash`, a short hash
of the stream layout, on every probe. No code reads it: `rg probe_hash` over `packages/`,
`frontend/src` (except the generated `schema.d.ts` and test fixtures), `desktop/`, `scripts/`
and `testing/` finds only the writer, the model field and three test assertions. The service
compares fingerprints by `size` and `mtime` only. The simplification audit
([0083](0083-simplification-step-before-v1.md), findings X-09, PRB-11, MOD-07 (b); `simplify/
decisions-taken.md` D-4 and D-13) found this.

## Decision

1. `layout_hash` and its call in `parse_ffprobe` are deleted. The fingerprint that the prober
   gives is stored as it is.
2. `SourceFingerprint.probe_hash` stays declared and optional (default `None`); its description
   says that this version does not write it. No `schema_version` changes: a persisted job, a
   queue row or a probe cache entry that carries a value stays valid and keeps it, and an older
   version reads a missing optional field as `None`.
3. The field is removed only together with the next bump of `job_settings` and `media_source`
   (then with a migration and a down-level note).

## Consequences

- `reframe probe --json` and the source responses of the HTTP API show `"probe_hash": null`.
  No client reads it. The probe snapshots (61 values) and the schema description change.
- `probe/parse.py` is part of the probe cache's parser fingerprint, so each cached probe is read
  as stale and runs once more after the update.
- Two more user-visible changes come in the same package (Q-6.13):
  - Codec labels in the batch matrix, track labels and rule explanations come from
    `probe/names.py` (`codec_name`). A codec that the names table knows and the old batch
    table did not (`vp8`, `mpeg1video`, `vc1`, `ac4`, `wmav2`, …) shows its proper name
    instead of the raw codec name or "unknown codec".
  - (added after the Tier B review, RB-1) A codec that neither table knows (`jacosub`,
    `pcm_s16le`, …) now shows its raw ffprobe codec name, not "unknown codec": a `jacosub`
    subtitle is labelled `eng jacosub`, not `eng unknown codec`. Every subtitle label takes
    this path (subtitle descriptors have no profile); audio takes it only without a profile.
    "unknown codec" stays for a track without a codec.
  - A video stream whose `language_ietf` is not a valid tag but whose `language` is now gets
    the valid language, as audio and subtitle streams already did. This changes the video
    language in the encode command (`-metadata:s:v`) and `TrackDescriptor.language` of that
    track. A probed source cannot reach this case: the prober drops an invalid `LanguageIETF`
    with a warning.
- The probe cache has no memory layer any more (every hit reads its small file). With a cache
  folder that cannot be written, a second probe of the same file runs ffprobe again.

## Plan changes

- `docs/plan/05-core.md` C-2, the `JobSettings` sketch: `source` is "path + fingerprint (size,
  mtime)".
