# XXXX — Synthesised probe recordings; probe details (HDR10+ frame read, roles, MediaInfo)

- Status: accepted
- Date: 2026-10-11
- Steps: C-3, Q-2.2

## Context

**Recorded probes.** Q-2.2 asks for "recorded real-world ffprobe JSON … for codecs that cannot
be generated (TrueHD Atmos, DTS:X, PGS, DV)", and C-3's "Done when" lists nine of them. There
are no such files on the development machine, and personal media must not be used. FFmpeg
cannot make them either:

```console
$ ffmpeg -h encoder=truehd | grep layouts      # no Atmos substream, at most 5.1
    Supported channel layouts: mono stereo 2.1 3.0 3.1 4.0 4.1 5.0(side) 5.1(side)
$ ffmpeg … -c:v libx265 -dolbyvision 1 … dv.mkv
[libx265 @ …] Dolby Vision enabled, but received frame without AV_FRAME_DATA_DOVI_METADATA
```

The `dca` encoder writes a DTS core only, and there is no PGS encoder.

**HDR10+.** C-3 says: read the first frame's side data "if it [stream side data] is missing".
HDR10+ dynamic metadata never is stream side data; ffprobe shows it only as frame side data
(`HDR Dynamic Metadata SMPTE2094-40 (HDR10+)`), so with that rule HDR10+ is never detected.

**Roles.** C-12 selectors use `roles=[main]` (04 §Deriving rules: "E01 track #2: eng · DTS-HD
MA · 5.1 · role=main"), so "main" must mean "a regular track", not "the first track". The
keyword `AD` matched case-insensitively also matches the word "Ad" in titles such as
"Ad Astra".

**MediaInfo.** 03 §Audio names MediaInfo as a fallback for the commercial codec name too. The
MediaInfo strings for that (Format / AdditionalFeatures) could not be checked against a real
file here (no such files), and C-3 lists MediaInfo only in the bitrate chain.

## Decision

1. The recorded probes in `testdata/probes/` are **synthesised from real output**: the closest
   file FFmpeg can make, real `mkvpropedit --add-track-statistics-tags` tags, the real ffprobe
   JSON of the pinned build, and then only the fields FFmpeg cannot generate edited (profiles,
   PGS codec names and canvas, the DOVI configuration record). Each edit is listed with its
   reason in `testdata/probes/index.json` and `README.md`, with the source evidence (strings
   confirmed by a byte search in the build, FFmpeg source for the decoder behaviour).
   `testdata/probes/record_probes.py` makes them. They are replaced by true recordings when
   such files are available (Q-2.4's local samples suite is the natural source).
2. The first frame is read for **every PQ stream** (HDR10+ detection), and for HLG or
   10-bit BT.2020 streams without static metadata (the "missing" fallback, including
   one-pass x265 files whose transfer is not tagged).
3. Every audio and subtitle track without a commentary / description / music (audio) or
   forced / SDH / signs / commentary / description (subtitles) role gets `main` (evidence
   `flag` when it has the `default` disposition, else `heuristic`).
4. Title keywords match as whole words, case-insensitive, except the two-letter acronyms `AD`
   and `CC`, which must be upper case.
5. MediaInfo is used for bit rates only (C-3). The commercial name comes from the ffprobe
   profile.

## Consequences

- The snapshot tests cover the parser for these codecs, but a field that real files have and
  the synthesised ones lack would not be noticed. Replace the synthesised files first when real
  samples are available.
- One more ffprobe run (one decoded frame) per PQ file; measured probe time stays far below the
  Q-3 budget (multi-track fixture 30–55 ms, 24-file folder 0.2–0.4 s on the reference machine).
- 03's "MediaInfo as a fallback" for codec names is not done; revisit with real files.

## Plan changes

- `docs/plan/09-quality-and-release.md` Q-2.2: synthesised-from-real-output recordings are
  allowed until real ones exist.
- `docs/plan/05-core.md` C-3: the HDR bullet (first frame also for HDR10+), the role bullet
  (`main`, acronyms).
