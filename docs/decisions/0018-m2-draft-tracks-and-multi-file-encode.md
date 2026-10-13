# 0018 — M2 drafts use the audio codec rules without track selection; `encode` takes many files

- Status: accepted
- Date: 2026-10-13
- Steps: C-12, C-15

## Context

**Output tracks of a drafted job.** M2's demo runs `reframe plan movie.mkv --preset "H.265 MKV
1080p"` and `reframe encode …`: the CLI turns a preset into a job. A preset stores audio and
subtitle *defaults* ([03 §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset)),
and "when a source opens, Reframe applies the preset's audio defaults". The engine that
applies them (C-12 "Audio and subtitle defaults": a selection stage, a codec-rule stage and
`explain`) is scheduled for M6 ([08 §M6](../plan/08-roadmap.md#m6--tracks-and-metadata)). So the
plan gives M2 no way to choose the output tracks of a job.

**Season encode.** C-15's "Done when" is "the CLI can encode a season folder end to end with no
UI", but M2's CLI scope is `encoders`, `plan`, `encode` and `name`
([08 §M2](../plan/08-roadmap.md#m2--encode-from-the-cli)), and `reframe encode` takes one
`FILE`. `reframe batch` (grouping and track rules, C-12) is M7.

The user decided both points on 2026-10-13.

## Decision

1. **M2 builds the codec-rule stage of C-12** (as its own step in M2 wave 2), not the
   selection stage. A job drafted from a preset in M2 gets:
   - **every** source audio track, in source order (no language filter, no commentary drop,
     no `und` handling: that is the selection stage, M6). Each track is encoded by the first
     matching rule of the preset's `audio_defaults.codec_rules`, with the bitrate-cap rules of
     03 (never bigger than the source; passthru when the source fits; snap to the encoder's
     allowed values; an unknown bitrate counts as above the max), the passthru policy and its
     fallback encoder, and the rule's mixdown and extras. Each track gets a reason string, as
     `explain` will give in M6.
   - **every** source subtitle track with action `copy` (container rules, such as text to
     `mov_text` in MP4 or no bitmap subtitles in MP4, are applied by the builder and by
     validation as 03 §Subtitles says).
   - the source track's language, title and flags as its metadata.
2. **`reframe encode` takes several files and folders**:
   `reframe encode FILE|DIR… --preset NAME [-o OUT]`. It adds one job per media file (folders
   are searched for media files), all with the same preset, to the queue, names each output
   with the naming template, and runs them with the queue's parallel setting. `-o` is allowed
   only with a single file. There is no grouping and there are no track rules: that stays
   `reframe batch` (M7).

## Consequences

- M6 adds the selection stage, `explain` for the selection, the defaults lint and the UI on
  top of the codec-rule stage built here, which it reuses unchanged.
- Until M6, a drafted job keeps commentary tracks and every language. A user who wants fewer
  tracks must edit the job (no CLI option for that in M2).
- A file whose drafted job has validation errors (for example a PGS track and an MP4 preset)
  is reported and not queued; the other files are still encoded.
- C-15's season criterion is met with `reframe encode SEASON_DIR --preset …`.

## Plan changes

- [08-roadmap.md §M2](../plan/08-roadmap.md#m2--encode-from-the-cli): the steps list `C-12`
  (codec-rule stage of the audio defaults only).
- [05-core.md §C-12](../plan/05-core.md#c-12-batch-engine): the codec-rule stage is built in M2.
- [05-core.md §C-15](../plan/05-core.md#c-15-service-facade-and-cli): `reframe encode FILE|DIR…
  --preset NAME [-o OUT]`.
