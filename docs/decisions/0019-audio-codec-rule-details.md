# 0019 — Audio codec rules: the corrected example, lossless sources, no upmix, what "fits" means

- Status: accepted. Item 1 (the example corrected to AAC 160) is superseded by
  [0023](0023-lossy-passthru-above-the-max.md); item 2 was confirmed by the user; items 3 to 7
  were accepted by the M2 lead without asking (each is one small function in
  `reframe/batch/audio_rules.py` and easy to change)
- Date: 2026-10-13
- Steps: C-12 (codec-rule stage, M2, [0018](0018-m2-draft-tracks-and-multi-file-encode.md))

## Context

C-12's codec-rule stage follows [03 §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset)
part 2 ("Max bitrate rules" and the worked example) and part 3 (passthru and fallback).
Building it showed one contradiction in the plan and several points the plan leaves open.

1. **The example's last row contradicts the rules.** Rule 3 is `Any · Stereo or less → AAC ·
   Stereo · 160 kb/s · Passthru`. The example says the source `eng · AC-3 2.0 · 192 kb/s` gets
   "Passthru: Rule 3 matches, and the source fits". But the rules table says the source fits
   only when "its bitrate is at or below the max", and 192 > 160. 05 §C-12's "Done when" calls
   the row "stereo fallback", which agrees with the rules, not with the example.
2. **Lossless sources with a known bit rate.** The table's first row says "Lossless (TrueHD,
   DTS-HD MA, FLAC, PCM) → encode at the max". When a lossless track's bit rate is known and
   below the max (the real `ass-fonts` probe has a FLAC 2.0 track at 133.7 kb/s; the default
   rule is AAC at 256 kb/s), encoding at the max makes the track bigger than its source, which
   the same section forbids ("Reframe never makes a track bigger than its source").
3. **Upmix.** The Mixdown column lists `Up to 5.1 (only downmixes 7.1)` and `5.1`, but does
   not say what `5.1` (or `Stereo`) does with a source that has fewer channels. FFmpeg n9.0.2
   upmixes with `-ac 6`, but the new channels are silent (testdata/README.md "Audio codec
   rules (C-12)": FL and FR at −21 dB RMS, the other four at −118 dB or less). HandBrake never
   upmixes.
4. **Rule settings that need a decode.** A rule's gain, DRC, loudness normalisation or sample
   rate cannot be applied to a passed-through track.
5. **A rule without a max on a lossy encoder.** `max_bitrate = None` is meant for lossless
   encoders (FLAC), but a passthru rule's fallback encoder (AAC) or a lossy rule saved without
   a max still needs a bit rate.
6. **Extra outputs** ("also add an AAC stereo track for compatibility"): the plan does not say
   whether they can pass through, which flags they get, or whether the rule's sample rate,
   gain, DRC and loudness apply to them.
7. **"Only for the first track of this language"** needs the selection stage (M6).

## Decision

1. **The rules table wins; the example is corrected.** Row 4 is `eng · AC-3 2.0 · 192 kb/s →
   rule 3 → AAC Stereo · 160 kb/s` ("Rule 2 needs 5.1 or more. Rule 3 matches. 192 > 160 →
   encode at the max"). A fifth row, `eng · AC-3 2.0 · 128 kb/s → rule 3 → Passthru` ("Rule 2
   needs 5.1 or more. Rule 3 matches, and the source fits"), keeps the passthru that the row
   was meant to show. The "Why" column now shows the reason strings that Reframe produces
   (row 3: "Downmix 7.1 → 5.1. Lossless source → encode at the max").
2. **A lossless source is "above the max" only when its bit rate is above the max or
   unknown** (reason "Lossless source → encode at the max"). With a known bit rate at or below
   the max it is treated like any other source: it can fit (a FLAC track passes through) or it
   is encoded at the smallest allowed value at or above its bit rate.
3. **A mixdown never upmixes.** A source with fewer channels than the rule's mixdown keeps its
   layout (with a note "2.0 source: no upmix to 5.1"); a source with as many channels gets the
   layout by name (`5.1`, `stereo`, `mono`; `dpl2` and `up_to_5.1` keep it). So `5.1` and
   `Up to 5.1` give the same output. An encoder that cannot make the layout (AC-3, E-AC-3:
   no 7.1; MP3: no 5.1) gets its largest layout below it, with a note.
4. **The source fits only if the rule changes nothing that needs a decode**: no gain, no DRC,
   no loudness normalisation, and no sample rate other than the source's.
5. **No max on a lossy encoder = the encoder's default bit rate for the layout** (AAC 5.1:
   384 kb/s), with the same "never bigger than the source" rules ("… → encode at the default").
6. **Extra outputs** are always encoded with their codec at their bit rate (as the max, with
   the same rules), unless their codec is `passthru` (then as a passthru rule with no max). The
   rule's sample rate, gain, DRC, loudness and name template apply to them. They are never
   the default track. Their outcome is listed in the decision's notes.
7. **`first_track_of_language_only` in M2** = the first track of that language in source
   order (every track is selected in M2). `apply_codec_rules` takes it as a keyword
   (`first_of_language`); M6 passes the selection stage's answer. A track that a limited rule
   does not take goes on to the next rule ("Rule 1 is only for the first track of a
   language"). If no rule is left (only when the catch-all itself is limited), the track gets
   no output and the decision says why.

Smaller points, recorded so they are not asked again:

- The source bit rate is rounded **up** to whole kb/s for "the smallest allowed value at or
  above the source bitrate" (128.453 kb/s → 129), and that value is capped by the snapped max.
- "On the passthru list" means any codec of `PassthruPolicy.allowed` (HandBrake's auto
  passthru), not only the rule's codec: the example's row 5 passes AC-3 through an AAC rule.
  A DTS-HD source matches only `dtshd`; Reframe does not extract the DTS core when only `dts`
  is allowed (FFmpeg has the `dca_core` bitstream filter for it; not in the plan).
- An unknown channel count (0) matches only an `Any` channel condition and gets the rule's
  layout.
- A passthru output keeps `encoder` = the rule's codec (or the policy's fallback encoder for a
  `passthru` rule), as `AudioOutputTrack.encoder` documents for auto passthru.
- Name template variables: `{lang}`, `{lang_name}`, `{lang_native}`, `{channels}` (output
  layout: `5.1`, `2.0`), `{codec}` (output codec; the source codec for passthru), `{bitrate}`,
  `{title}`, `{source_codec}`, with the naming template syntax (`<…>` groups, format specs).

## Consequences

- The live preview and `explain` (M6) show these reasons; M6 reuses `apply_codec_rules`
  unchanged.
- A user who wants "pass through anything that fits, whatever its bit rate" sets no max on a
  `passthru` rule.
- If the user wants upmixing (item 3), `requested_mixdown` changes and `5.1` then differs from
  `Up to 5.1`.
- C-8 validation of rules (a codec the container cannot hold, a max outside the encoder's
  range, track name templates with unknown variables) is not part of this step: the draft
  names the encoder anyway and puts a note on the decision.

## Plan changes

- [03-features.md §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset):
  the Mixdown row (no upmix), the "Max bitrate rules" table (lossless with a known bit rate,
  rule settings that need a decode, no max), the worked example (row 4 corrected, row 5 added,
  the reason strings).
