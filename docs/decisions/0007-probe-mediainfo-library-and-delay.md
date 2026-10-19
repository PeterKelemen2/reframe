# 0007 — Probing uses the pymediainfo library; delay, LanguageIETF, VFR in Matroska

- Status: accepted
- Date: 2026-10-11
- Steps: C-3, C-12, D-7

## Context

The M1 review found these gaps in C-3:

1. **MediaInfo.** The probe calls MediaInfo through `pymediainfo`. The `pymediainfo` 7 wheels
   bundle `libmediainfo` (`.venv/…/pymediainfo/libmediainfo.so.0`), so
   `MediaInfo.can_parse()` is true even when no MediaInfo is installed. The `mediainfo` tool
   that discovery finds (`REFRAME_MEDIAINFO`, Settings → Tools, the bundled MediaInfo CLI of
   07 §Tool bundling) has no effect on probing. 05 C-3 says "MediaInfo (if installed)".
2. **LanguageIETF.** ffprobe does not show the Matroska `LanguageIETF` element:

   ```console
   $ mkvpropedit pt.mkv --edit track:a1 --set language=pt-BR
   $ ffprobe -v error -show_entries stream_tags=language -of compact pt.mkv   # → language=por
   $ python -c '…MediaInfo.parse("pt.mkv")…'                                # → Audio language pt-BR
   ```

   So C-12 region and script rules (`pt-BR`, `zh-Hant`) can never match a Matroska track.
3. **Delay.** C-3 says "stream start offsets (shown as audio delay)". ffprobe's `start_time` is
   the absolute timestamp of the first packet. Shown as the delay, an M2TS that starts at
   1.4 s shows "+1400 ms", and the recorded DVD VOB shows "+528 ms" (video 0.533367, audio
   0.528033: the audio really starts 5 ms *before* the video).
4. **VFR in Matroska.** FFmpeg's Matroska demuxer sets `r_frame_rate` = `avg_frame_rate` from
   `DefaultDuration`, and mkvmerge always writes `DefaultDuration`. A VFR file remuxed by
   mkvmerge shows `r = avg = 29999/500` (ffprobe), while MediaInfo says VFR, 37.886 fps.
   (`testdata/probes/mkvmerge-vfr.json` is a real recording of this.) The container `ENCODER`
   tag cannot show who wrote the file: mkvmerge copies a source's `ENCODER=Lavf…` tag.
5. **Stale statistics tags.** FFmpeg copies stream tags when it re-encodes. An 85 kB re-encode
   of an mkvmerge file keeps `BPS=9582197` and `NUMBER_OF_BYTES=2397945`
   (`testdata/probes/stale-stats.json`, real).

## Decision

1. Probing uses the **pymediainfo library** (bundled in the wheel, or a system
   `libmediainfo`). The discovered `mediainfo` tool is for diagnostics only. Calling the
   MediaInfo CLI with `--Output=JSON` would add a subprocess for every probe and a second
   parser for nothing that the library cannot give. The MediaInfo version (pymediainfo +
   libmediainfo) is part of the probe cache identity.
2. `language_ietf: LanguageTag | None` on every stream: the BCP 47 tag that MediaInfo reports
   (the Matroska `LanguageIETF` element when present). It is `None` without MediaInfo. The
   **effective language** for C-12 is `language_ietf` if set, else `language`.
3. `start_time` stays the raw ffprobe value. A new `delay` (seconds, may be negative) is
   relative to the main video stream's `start_time`, or to the container's `start_time` when
   there is no video. This is what mkvmerge and HandBrake show. The CLI and the UI show `delay`.
4. VFR in Matroska: if `avg_frame_rate` is known, compare it with `NUMBER_OF_FRAMES` /
   `DURATION` from the statistics tags (if they pass the checks in 5); VFR if they differ by
   more than 1 %. Without such tags, use MediaInfo's `FrameRate_Mode`. Without MediaInfo,
   sample the timestamps of the first 120 packets (`-show_entries packet=pts_time
   -read_intervals %+#120`).
5. Statistics tags are used (bit rate, frame count, event count, VFR) only when they pass these
   checks: the sum of the tracks' `NUMBER_OF_BYTES` ≤ the file size, `BPS` ≤ 1.05 × the
   container bit rate, and `DURATION` ≤ 1.05 × the container duration + 1 s. A failed check is
   a warning, and the chain falls through to MediaInfo / unknown.

## Consequences

- MediaInfo runs on every probe when it is available (it is needed for `language_ietf`). The
  multi-track fixture probe takes about 30–55 ms in total.
- When MediaInfo is not available, a Matroska file without statistics tags costs one more short
  ffprobe run (the packet sample). VFR that starts after the first 120 packets is not seen.
- On Windows, D-7 can drop the MediaInfo CLI from the bundle unless diagnostics need it. The
  `pymediainfo` wheel already has the DLL.
- The C-12 language matching must use the effective language.

## Plan changes

- `docs/plan/05-core.md` C-3: the parse bullet (delay, VFR in Matroska), the bitrate bullet
  (pymediainfo library, plausibility checks), and the event-count bullet.

## Follow-up (core-complete, task 1i), 2026-10-15: ASCII stream orders, a nesting limit for the probe cache

### Context

Two "Known limits" of the M2 review in C-3:

1. `track_data` matched a MediaInfo `StreamOrder` with `str.isdigit()`. That accepts
   superscripts (`²`, which `int()` rejects: a `ValueError` in the probe) and the decimal
   digits of other scripts (Arabic-Indic `٣`, full-width `３`, which `int()` reads as 3).
   The first number of a bit rate used `re`'s `\d`, which also matches `٣` and `３` (not
   `²`). Checked on CPython 3.14.7 and recorded in `tests/probe/test_mediainfo.py`.
2. The probe cache had no nesting limit (decision 0015 §3 for C-9's stores). `json.loads`
   raises `RecursionError` (not the `ValueError` that the cache caught) for very deep JSON
   (about 52 000 levels on an 8 MB stack), and Pydantic's `model_dump` raises `ValueError`
   past 255 levels; `put` did not catch it, so the probe failed. Only a source with deep
   unknown fields (`MediaSource` is a `DocumentModel`) or deep options can be that deep.

### Decision

1. A `StreamOrder` matches only when the whole value is ASCII digits (`[0-9]+`); anything
   else is not matched, as `0-1` (MPEG-TS) was before. The first number of a bit rate is
   ASCII digits too.
2. A cache entry nested more than 64 levels (`reframe.settings.too_deep`; the entry object is
   level 1), or too deep to parse, is corrupt: a miss, and the next probe rewrites it. A
   source whose entry would be that deep (or that Pydantic cannot dump) is not cached at all,
   not in the memory layer either: `ProbeCache.put` returns `False` and an earlier entry
   stays. Tests: `tests/probe/test_cache_nesting.py`.

### Consequences

- The change to `mediainfo.py` changes the parser fingerprint, so older cache entries are
  misses once (as for any parser change).

### Plan changes

None.

## Follow-up (core-complete review, 2026-10-16)

Decision item 2 said `language_ietf` is "the BCP 47 tag that MediaInfo reports (the Matroska
`LanguageIETF` element when present)". Since C-13 (decision 0034 item 5) Reframe reads that
element itself, and the review found two faults in how the values met:

- **R4-3 (major).** MediaInfo reports a BCP 47 `Language` for every Matroska track: when the
  track has no `LanguageIETF`, it derives one from the legacy `Language` element (checked
  with pymediainfo 7.0.1, libmediainfo 24.12 on `multitrack.mkv`, which has no `LanguageIETF`:
  `ja` for `jpn`, `en` for `eng`; `mkvmerge -J`: no `language_ietf`). The prober kept that
  derived tag, because the reader's value replaced it only when the track had the element. Now,
  for a Matroska file whose tracks the reader matched, `language_ietf` is the track's element
  or `None`; MediaInfo's value is kept for other containers (MP4) and when the reader cannot
  read or match the tracks. Item 2 now reads: `language_ietf` is the file's BCP 47 tag
  (Matroska: Reframe's track reader; other containers: MediaInfo), `None` when the file has
  none. Tests: `tests/probe/test_matroska_limits_and_ietf.py`
  (`test_probe_with_mediainfo_on_keeps_only_the_files_bcp47_tags`,
  `test_real_mediainfo_derives_a_bcp47_tag_from_the_legacy_language`).
- **R4-4 (major).** Values were assigned without validation (`MediaSource` does not validate
  assignment), so a `LanguageIETF` such as `en_US` reached `TrackMetadata` and made `draft`
  and `plan` fail with a `ValidationError`. Now only a valid `LanguageTag` (pattern and at
  most 64 characters) is used: from the reader, another value gives `None` and a probe warning;
  from MediaInfo (whose module already keeps only values of the tag's pattern) a value longer
  than 64 characters is dropped. Tests: `test_a_value_that_is_not_a_language_tag_is_not_used`,
  `test_mediainfo_languages_that_are_too_long_are_not_used`,
  `test_probe_of_an_invalid_language_ietf`.

The probe cache's option `"matroska"` becomes 2, so entries made with the old rule are probed
again.

Not changed (not this task's files): the docstring of `language_ietf` in
`reframe/models/media.py` ("as MediaInfo reports it … `None` when MediaInfo is not
available") and 05 §C-3 ("MediaInfo also gives `language_ietf`") describe the M1 rule.
*Both changed since: the docstring by RB-6 (final review, below), 05 §C-3 on 2026-10-17.*

## Follow-up (final review, 2026-10-17)

A final review of the fix rounds (reviewer R-B, on `core-complete` 5dbf152) found two minors in
C-2 / C-3:

- **RB-6: the `language_ietf` docstring** (`reframe/models/media.py`, and so the JSON Schema
  description) said that for Matroska the value is the reader's or `None`. That holds only when
  the reader read and matched the tracks; when it cannot read them, or their counts differ from
  ffprobe's streams, MediaInfo's value stays (the rule of the R4-3 follow-up above, and of
  `apply_matroska`). The docstring now says so, and the schema snapshot
  (`tests/models/__snapshots__/test_schema.ambr`: `AudioStream`, `SubtitleStream`,
  `VideoStream`) was regenerated; with the old docstring those three snapshot tests fail.
- **RB-7: the parser fingerprint did not cover the Matroska reader.** `_PARSER_MODULES`
  (`reframe/probe/cache.py`) listed the modules whose source is hashed into the cache entry's
  parser fingerprint, without `matroska.py`; a change to the reader (which fills
  `language_ietf`) kept the old entries unless `MATROSKA_READER` was raised by hand. It is
  listed now, so entries made before this change are misses once. Test:
  `tests/probe/test_cache_fingerprint.py::test_a_change_to_a_reader_changes_the_fingerprint`
  (a copy of the probe sources with one module changed; `matroska.py` failed on 5dbf152).
  `MATROSKA_READER` stays in the cache options; a change to the reader no longer needs it
  raised.

Not changed (a plan file): 05 §C-3 still says "MediaInfo also gives `language_ietf`".
*Changed on 2026-10-17 (core-complete follow-up):* 05 §C-3 now states the rule of the R4-3
follow-up (the Matroska reader's value or `None`; MediaInfo for other containers and when the
reader cannot read or match the tracks).
