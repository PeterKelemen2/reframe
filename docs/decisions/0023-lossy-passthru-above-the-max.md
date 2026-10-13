# 0023 — A lossy source that fits is passed through at any bitrate

- Status: accepted
- Date: 2026-10-13
- Steps: C-12
- Supersedes in part: [0019](0019-audio-codec-rule-details.md) (item 1: the rules table wins and
  the example is corrected)

## Context

03 §Audio defaults defined "the source **fits**" with five conditions, one of them "its
bitrate is at or below the max". Its own worked example contradicted that: rule 3 (Any /
Stereo or less → AAC Stereo, max 160 kb/s, passthru if it fits) passes through an `eng · AC-3
2.0 · 192 kb/s` track. C-12 followed the definition and corrected the example to "AAC Stereo
· 160 kb/s" ([0019](0019-audio-codec-rule-details.md) item 1).

The user decided on 2026-10-13 that the example is what was meant: re-encoding a lossy track
to another lossy codec costs quality (a generation loss) for a small saving.

## Decision

- A **lossy** source fits when its codec is on the passthru list (`PassthruPolicy.allowed`),
  the container can hold it, its channels are within the rule's mixdown, and the rule changes
  nothing that needs a decode (0019 item 4). Its bitrate does not matter, also when it is
  unknown. The max bitrate applies only when the track is encoded.
- A **lossless** source fits only when, in addition, its known bitrate is at or below the max
  (0019 item 2, confirmed by the user). A lossless source above the max, or with an unknown
  bitrate, is encoded at the max.
- `if_fits = "reencode"` still re-encodes a source that fits, with the bitrate rules for
  encoding (never above the max, never bigger than the source).
- The example of 03 is restored: row 4 is a passthru again.

## Consequences

- With the default catch-all rule (AAC, up to 5.1, max 256), every AAC, AC-3, E-AC-3, DTS,
  MP3 or Opus track that the container can hold is passed through, whatever its bitrate. A
  user who wants smaller files sets the rule's "if it fits" to "Re-encode".
- An unknown bitrate only matters for lossless sources and for sources that do not fit, so
  **Measure** is offered less often.

## Plan changes

- [03 §Audio defaults](../plan/03-features.md#2-codec-rules-how-each-selected-track-is-encoded):
  the max-bitrate rules table and the worked example.
