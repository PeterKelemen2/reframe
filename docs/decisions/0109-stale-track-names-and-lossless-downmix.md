# 0109 — A warning for track names that name the source's codec, a note for a lossless downmix

- Status: accepted
- Date: 2026-11-25
- Steps: C-8, F-10

## Context

03 §Track metadata: a track's name is text or a name template; `None` keeps the source
title. A preset's track rules write the source title when their `name_template` is `None`
(04 §Track rules), and the built-in presets set none. So a re-encoded track keeps a title
that describes the source track.

With the default preset "H.265 MKV 1080p" on `testdata/media/dts-hd-ma.mkv`, the drafted job
(`reframe.jobs.draft_from_preset`) has:

```text
source  #1 dts  DTS-HD MA  6 ch  title "DTS-HD MA 5.1"  (hun, default)
output  audio[0]  encode aac, mixdown stereo, 160 kb/s, name "DTS-HD MA 5.1", default
```

`multitrack.mkv` writes "Japanese 5.1" on an AAC stereo track, and the recorded
`truehd-atmos` probe writes "Dolby TrueHD Atmos 5.1" and "Dolby Digital 5.1" on AAC stereo
tracks. Validation found no issue, so the Summary said "No issues". A lossless 5.1 track mixed
down to lossy stereo got no note either: no single field shows both losses. This breaks
PRODUCT.md principle 2, "Never surprise the output". 05 §C-8 has no rule for either.

## Decision

1. **The default name stays the source title.** Reframe does not rename tracks on its own:
   a silent rename is a surprise too, and a title often carries more than the codec
   ("English Dub"). Validation says when the title is wrong and offers the new name.
2. **`metadata.name_stale`, a warning** at `audio[i].metadata.name` or
   `subtitles[i].metadata.name`, for a re-encoded track (an encoded audio track, a passthru
   that falls back to its encoder, a converted subtitle, a copied text subtitle that the
   container converts) whose written name (its own, else the source title) has a codec or
   layout word that the written track contradicts. A name with a template is not checked: it
   says what it was asked to (`{source_codec}`). A copied track keeps its source and is not
   checked.
   - **Codec words** come from the core's display names (`reframe.probe.names
     .audio_name_codecs()`): every commercial audio name, the parts of ffprobe's `A + B`
     profiles (`Dolby TrueHD`, `Dolby Atmos`, `Dolby Digital Plus`), and a feature word that
     several codecs' profile names share (`Atmos`). Each word maps to the codec an encoder
     writes under it; a profile no encoder writes (`DTS-HD MA`, `TrueHD Atmos`) maps to none,
     and any AAC profile name counts as AAC. The one name entered by hand is `Dolby Digital`
     (AC-3), the most common AC-3 title, which no ffprobe string contains. Subtitle words are
     the display names of the subtitle codecs the containers copy or encode (`SRT`, `ASS`,
     `WebVTT`, `PGS`, `VobSub`, `DVB`, `mov_text`).
   - **Layout words** are the mixdown labels of the definitions (`Mono`, `Stereo`, `Dolby Pro
     Logic II`, `5.1`, `7.1`) and any `N.M`, compared by channel count with the layout the
     command builder writes (snapped, never upmixed).
   - Words match whole and case-sensitively: not inside `DD5.1`, `7.1.4` or `DTS-HD`. A missed
     word is better than a warning on a correct name.
   - **The fix** renames the track (`add` at the name's path, which works when the client's
     job has no `name` member): the first stale codec word becomes the written codec's name
     (`AAC`), the first stale layout word becomes the written layout in the same style (`5.1`
     → `2.0`, `Mono` → `Stereo`), and later stale words are removed. `DTS-HD MA 5.1` →
     `AAC 2.0`; `English AC-3 5.1` → `English AAC 2.0`; `Dolby TrueHD Atmos 5.1` →
     `AAC 2.0`. The `N.M` style is the one of the `{channels}` template variable.
3. **`audio.lossless_downmix`, info** at `audio[i].mixdown`, when a lossless source track
   (`AudioStream.lossless`: TrueHD, DTS-HD MA, FLAC, PCM, …) is written by a lossy encoder
   with fewer channels. Info, not warning: the default preset asks for exactly that, and info
   is the severity of the other audio notes (0024). Fixes: pass the track through, when the
   container can copy the codec, and keep the source layout, when the encoder can write it.
4. The default flag is not changed: the track is still the main track of its language.
5. Both codes are new values of `ValidationIssue.code`, which is a free string, not a
   `Literal`. Issues are not persisted in a document with a schema version, so no migration.
6. The Summary's Tracks card shows a re-encoded track as source → output (`AC-3 5.1 → AAC
   Stereo`) and a renamed track as source title → name, in the muted text colour. A passthru
   track that the container cannot hold shows its fallback encoder, and a copied text
   subtitle that the container converts shows the format it gets.

## Consequences

- The default preset on a 5.1 source with a titled track shows a warning per track; on a
  lossless 5.1 source also a note. `reframe plan` and `reframe encode` print them.
- Titles in other spellings (`DD5.1`, `DTS-HD Master Audio`, `TrueHD7.1`) are not caught.
- To revisit: a preset option that names re-encoded tracks with a template by default.

## Plan changes

- `05-core.md` §C-8: the two rules.
- `03-features.md` §Track metadata (Name row) and §Audio (output tracks).
