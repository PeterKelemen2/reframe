# 0025 — An audio bitrate the encoder cannot do snaps down, as in HandBrake

- Status: accepted
- Date: 2026-10-14
- Steps: C-7, C-8, C-12 (shared helper of C-6)
- Supersedes in part: [0024](0024-m2-wave-2-product-decisions.md) item 4 (the word "nearest"
  for the bitrate only)

## Context

[0024](0024-m2-wave-2-product-decisions.md) item 4 says that an audio bitrate, mixdown or sample
rate the encoder cannot do is snapped by the command builder "to the nearest allowed value
(C-6's `snap`, …)". C-6's `AudioBitrateDef.snap` has two directions, `down` (the default) and
`up`; it has no "nearest". For a bitrate between two allowed steps the two readings differ:
AC-3 stereo at 150 kb/s is 128 (down) or 160 (nearest). FFmpeg's own `ac3` encoder writes 160.

The C-7 follow-up (wave 2b) built `down`, the same direction as C-8's snap fix and as the max
bitrate of C-12's codec rules, and asked the lead to decide.

HandBrake 1.11.2, `libhb/common.c`, checked in its source (`hb_audio_bitrate_get_best` and
`hb_audio_bitrate_find_closest`): the bitrate is clamped to the encoder's range for the codec,
sample rate and mixdown, then the largest allowed bitrate at or below it is taken (the source
comment: "bitrates are sanitized downwards"). A value below the smallest step becomes the
smallest step.

## Decision

- A **bitrate** the encoder cannot do is clamped to the encoder's range for the effective
  mixdown, then goes **down** to the next allowed step (`AudioBitrateDef.snap` with its
  default direction). This is HandBrake's rule. The builder (C-7), the validation note and fix
  (C-8) and the codec rules (C-12) all use it.
- The **mixdown** and the **sample rate** stay as 0024 and the shared helpers say: the
  encoder's largest layout below, never an upmix (`snap_mixdown`); the nearest listed rate, the
  higher one on a tie (`snap_samplerate`).
- A codec rule that asks for "the smallest allowed bitrate at or above the source bitrate"
  (03 §Audio defaults) still uses `up`. That is a different question (a floor, not a typed
  value).

## Consequences

- A typed bitrate never gives a bigger track than the user asked for (AC-3 stereo 150 → 128,
  AC-3 700 → 640). A value below the range goes up to the minimum (AC-3 5.1 at 100 → 224).
- Where FFmpeg would round a free value up by itself (AC-3 150 → 160), Reframe writes the
  lower step. The validation note says which value is written.
- If the user prefers "nearest", it is one `direction` argument in `reframe.command.audio` and
  in the C-8 rule, and a new record.

## Plan changes

- None in this commit. The C-7 follow-up commit already changed
  [05 §C-7](../plan/05-core.md#c-7-command-builder) (the audio bullet: "goes down to the next
  allowed step (as HandBrake does)"); this record confirms that wording against HandBrake's
  source.
