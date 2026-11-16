# 0031 — The selection stage of the audio and subtitle defaults, foreign audio search, the defaults lint

- Status: accepted. The points marked **(open)** are product questions answered with a default
  that is easy to change (each one is a small function or constant, named below); the lead or
  the user may change them.
- Date: 2026-10-15
- Steps: C-12 (M6 part; core-complete wave 1a)

## Context

05 §C-12 "Audio and subtitle defaults" (M6) asks for the selection stage, `explain` and the
defaults lint on top of the codec-rule stage of M2 ([0018](0018-m2-draft-tracks-and-multi-file-encode.md),
[0019](0019-audio-codec-rule-details.md), [0023](0023-lossy-passthru-above-the-max.md)).
[03 §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset) part 1 gives
the settings and their values in a table, and [03 §Subtitles](../plan/03-features.md#subtitles)
adds foreign audio search, burn-in and a default-track policy "(HandBrake parity)". Building
them showed points the plan leaves open, and one place where the lint would repeat a C-8 rule.

**HandBrake's subtitle behaviour**, read in its source (HandBrake `master`, 2026-10-15:
`libhb/preset.c` `hb_preset_job_add_subtitles`, `libhb/hb.c` `hb_add_internal`, `libhb/work.c`
`analyze_subtitle_scan`, `libhb/common.c`):

- `pref_lang` is the first language of the subtitle list. An empty list means "any", and then
  `pref_lang` is the first audio track's language.
- **Foreign Audio Search** (`SubtitleAddForeignAudioSearch`) runs only when the first audio
  track's language **is** `pref_lang`: the viewer understands the audio, and the search looks
  for the subtitles of its foreign-language parts. A scan pass decodes every subtitle track in
  the audio's language whose format can carry a forced flag (`hb_subtitle_can_force`: VobSub and
  PGS only), then takes the track with forced subtitles, else the track whose event count is
  below 10 % of the largest. The result is marked "forced only", is default unless burned in,
  and is burned in when the burn behaviour is "foreign" or "first".
- **Add subtitle when audio is foreign** (`SubtitleAddForeignAudioSubtitle`) runs when the
  first audio language is **not** `pref_lang`: it adds the first subtitle in `pref_lang`,
  default unless burned in, burned in when the burn behaviour is "foreign".
- Burn behaviour `none` / `foreign` / `first` / `foreign_first`; at most one track is burned
  in. A track the container cannot hold is burned in too while nothing is burned yet, and
  dropped after that.
- Selection behaviour `first` takes the first track of **each** listed language.

## Decision

### 1. No language set: keep everything (open)

When a kind has no language at all (the selection's `languages` is `None` or empty and
Settings has no preferred languages of that kind), the selection takes every track of that kind
in source order and ignores the other selection settings: every audio track goes through the
codec rules and every subtitle is copied, each with its source metadata, as M2 did (0018).
Foreign audio search and burn-in do not run in this mode. The only change from M2: at most one
track per kind keeps the source's default flag (the first one). mkvmerge writes `FlagDefault=1`
on every track it is not told otherwise about (testdata/README.md), so sources with two default
subtitles exist, and 03 §Track metadata allows one default track per type. Each decision says
so in one line (`selection.KEEP_EVERYTHING`). So `reframe encode` with the built-in presets,
which set no languages, does not start dropping tracks; setting preferred languages in
Settings switches the selection on. (`reframe.batch.selection.select_tracks`, the
`if not listed` branch.)

### 2. Languages

- A track's language is `effective_language` (a valid `language_ietf`, else `language`,
  canonical; see the follow-up for a broken `LanguageIETF`).
  It belongs to the **first** listed language that `reframe.languages.matches` it: languages
  are compared as languages (`ger` = `deu` = `de` = `German`), and every script, region and
  variant subtag of the listed language must be on the track. So a listed `pt` takes `pt`,
  `pt-BR`, `pt-PT` and `por`; a listed `pt-BR` takes only `pt-BR` (not a plain `por` track,
  not `pt-PT`). The codec rules already match this way (0019), so a rule and the selection
  agree on what a language is.
- `None` and an empty list both mean "the preferred languages of Settings"
  (`LanguageSettings` says "whose language list is empty").
- **Undetermined** tracks (no language, `und`, or a tag that is not a language) with
  `undetermined = first_language` count as the first listed language for everything that
  follows **(open)**: they are selected as that language, the codec rules see that language,
  and the output track is **written** with it (a note says so). `qaa`–`qtz`, `mul`, `zxx` are
  languages, not undetermined. A listed `und` takes undetermined tracks whatever the setting.

### 3. The other selection settings

- **Tie-break** (the order of the tracks of one language; `selection.sort_key`): `source_order`;
  `most_channels` then source order; `best_quality`: lossless first, then the highest known bit
  rate, **an unknown bit rate after every known one** (the preview offers Measure), then more
  channels, then source order. For **subtitles** `best_quality` and `most_channels` mean "full
  subtitles first, then SDH, then forced and Signs & Songs", then source order: "the first
  matching subtitle" should be the full track, not the forced one.
- **Tracks per language** `first` is the first track of **each** listed language (as
  HandBrake), after the tie-break. `all` keeps them in tie-break order.
- **Other languages** (main tracks in no listed language): `keep_first` keeps one track: the
  best (tie-break) track of the first other language in source order **(open)** (usually the
  original language); `keep_all` keeps them all, in source order.
- **No listed language found** means that the source has main tracks and none of them is in
  a listed language: a commentary, description or music-only track in a listed language does
  **not** count (corrected 2026-10-16, see the follow-up; before, "no track at all"). The same
  rule holds for subtitles (03: "the same track selection part"). `default_flagged` takes the
  first default-flagged main track, or the first main track when none is flagged;
  `first_track` the first main track. That track also counts as the one track of
  `other_languages = keep_first`. `none` takes nothing; for audio it is the error
  `defaults.no_listed_language` (path `audio_defaults.selection.no_match`, fixes: take the
  default-flagged track, take the first track) in `TrackDraft.issues` when the selection takes
  **no main track** (other languages kept are main tracks: then there is no error; a kept
  commentary alone is not enough), except for a source without audio. For subtitles it is not
  an issue.
- **Commentary and audio description**: the extra roles are commentary, description and
  **music only** **(open)**: an isolated score is not the programme's dialogue either
  (`selection._EXTRA_ROLES`). Every C-3 evidence counts (flag, title, heuristic; the preview
  shows which), and the disposition flags alone when a source has no roles. `keep_after_main`
  keeps an extra track when its language is taken (a listed language, or any language when
  other languages are kept); extra tracks always come after the main tracks.
- **Output order** `language_list`: the listed languages in list order (each in tie-break
  order), then the no-match track, then the other languages in source order, then the extra
  tracks by listed language (others last). `source`: the main tracks, then the extra tracks,
  each in source order.

### 4. The default track and the other flags

- The selection stage overrides **only the `default` flag** of the output tracks. The
  language, title and the other five flags come from the source track (M2's
  `track_metadata`; an undetermined track gets the listed language, section 2).
- Audio: `first_output`; `first_in_first_language` (the first **main** track in that
  language, never a kept commentary, description or music-only track; none: the first output
  track); `forced` (the first output from a forced-flagged source track, else none; the value
  is meant for subtitles); `none` (no audio track is default). Only a rule's own output can be
  the default; extra outputs never are (0019). The decision of the default track gets the
  note "The default audio track (…)".
- `first_track_of_language_only` follows the selection: the first **selected** track of its
  language in the **output order** (best quality first by default), not in source order.

### 5. Subtitles: foreign audio search, burn-in, default track

- **The audio language** is that of the default audio output (else the first audio output);
  `explain_subtitles` without audio outputs uses the source's default-flagged audio track (else
  the first).
- **Foreign audio search** (`explain.foreign_audio_search`) runs, as in HandBrake, only when
  the audio is in the first subtitle language (the viewer's language). Reframe has no scan pass
  during the encode (03: the search uses event counts and, for PGS, the forced flags of a C-10
  decode scan), so it ranks the subtitle tracks in the audio's language (commentary excluded)
  by their evidence, best first: the forced flag or a `Forced` / `Foreign` title; every event
  forced (`forced_event_count`); a Signs & Songs track; few events, at least one (C-3's
  heuristic role, or at most 25 % of another track's events, `probe.roles.FORCED_MAX_RATIO`,
  also for counts measured
  later: one threshold with the badge the user sees, not HandBrake's 10 %, which is applied to
  hits counted in its own scan); some forced events in a full PGS / VobSub track (usable only
  burned in with forced-only, 0014). Ties go to source order. The track found is selected even
  when the language selection did not take it, goes **first**, and is written with the
  **forced flag** **(open)**: in Matroska `FlagForced` marks a track that a player may select
  by itself for the user's language even when subtitles are off, meant for tracks that only
  translate foreign-language audio or on-screen text.
- HandBrake's "add subtitle when audio is foreign" has no setting in Reframe: the normal
  selection already takes the subtitle in the viewer's language.
- **Burn-in** (at most one track): `foreign_audio` burns the foreign audio search track, or,
  when the audio is **not** in the viewer's language, the first selected **main** subtitle in
  that language (never a kept commentary or description: it does not translate the audio)
  (HandBrake's "foreign" burn also applies to its foreign-audio subtitle) **(open)**;
  `first` burns the first subtitle output (the search track when there is one, as HandBrake);
  `foreign_audio_then_first` the first of the two that exists. A burned track is not copied.
- **Default track** (on the copied tracks): `none`, `first_output`, `forced` (the first copied
  track with the forced flag, the search track included), `first_in_first_language` (the
  first copied main track in that language, never a commentary or description; none: the
  first copied track).
- A selected track the container cannot hold (PGS into MP4) is **not** burned in by the
  defaults, unlike HandBrake: 03 makes it a validation error that offers burn-in or MKV, and
  burning in is a change the user should choose **(open)**. The decision notes it; a text track
  that MP4 converts to `mov_text` gets a note too.

### 6. The defaults lint (`reframe.batch.lint_defaults`)

| Code | Severity | When |
|------|----------|------|
| `defaults.rule_unreachable` | warning | a rule matches no track at all: an empty language list; languages the selection never takes (explicit selection languages, other languages dropped, no listed language: take none); or an earlier Any / Any rule (not limited to the first track) takes every track |
| `defaults.rule_shadowed` | warning | an earlier rule's languages and channels contain this rule's (`lint.rule_covers`; a rule limited to the first track of a language does not shadow an unlimited one) |
| `defaults.bitrate_snapped` | info | the max is not what C-7 writes (C-6's `snap`, down, 0025) for a layout the rule makes; the message names the written value, and a fix sets it when all layouts agree |
| `defaults.codec_not_in_container` | error | a rule, extra-output or fallback encoder the container cannot hold; fixes: the first of AAC, Opus, AC-3, E-AC-3, FLAC, MP3 that the container holds, or another container that holds every encoder of the defaults and every video codec of this one |
| `defaults.rule_unused` | info | with a source (`lint_defaults(defaults, used=...)`, called by the track stage with the rules its selected tracks used): no selected track uses the rule (the catch-all and unreachable rules are not reported; nothing when no track is selected) |

- Because the catch-all must be last, "unreachable" is defined as above; a rule after the
  last rule cannot exist. Fixes move a shadowed rule above the one that hides it (not when both
  have the same conditions), remove it, or, for a catch-all behind an earlier Any / Any rule,
  make that rule the last one.
- **Which layouts a max is checked for**: a rule that downmixes to a fixed layout (mono,
  stereo, Dolby Pro Logic II, 5.1) is checked for the sources it downmixes, its own layout; a
  smaller source keeps its layout (no upmix) and the snap of that source is a note on its
  decision. A rule that keeps the layout (`keep`, `up_to_5.1`) is checked for every layout its
  channel condition allows. So the built-in Creator preset (AAC Stereo 320 kb/s) is clean
  although a mono source gets 256 kb/s.
- **One issue per problem**: C-8's `container.codec_unsupported` already reports the same
  encoders of a template (with fixes that know which encoders are available). So
  `validate_template` passes `container_codecs=False` to `lint_defaults` (a keyword, default
  `True` as the contract says) and gives C-8's issue only; the live preview (`draft_tracks`)
  keeps the lint's issue, because C-8 does not run there.
- Paths are template paths (`audio_defaults.codec_rules[1].max_bitrate`), fixes target
  `"template"`.

### 7. Reasons

Every source track has one `TrackDecision`, in source order: `selected`, `selection` (why it
was taken or dropped) and `reason` (the codec rule's reason for a selected audio track; the
output for a subtitle; for a dropped track the same text as `selection`). A track is named by
its absolute stream index (`#6`), as `reframe plan` and C-3's role details name it. In the
keep-everything mode the audio reasons are exactly M2's, so the CLI output does not change.

## Consequences

- `reframe encode` / `plan` with a built-in preset behave as in M2 until preferred languages
  are set in Settings; then the presets' HandBrake-like selection applies (first track per
  language, commentary dropped, no subtitles except the foreign audio search track, burned in).
- The batch engine (wave 2) compiles the defaults into track rules with the same building
  blocks: `select_tracks`, `language_slot`, `sort_key`, `extra_role`,
  `foreign_audio_search`, `rule_covers` (documented in `reframe.batch.selection`, `explain`,
  `lint`).
- `JobService.draft` carries the subtitle decisions and the errors of `TrackDraft.issues`
  (the `no_match = none` error keeps the job out of the queue); the lint's warnings and notes
  are in `JobService.explain`.
- Revisit: the points marked (open); HandBrake's automatic burn-in of a track the container
  cannot hold; a "foreign audio subtitle" setting if users miss it.

## Plan changes

- [03-features.md §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset)
  part 1: a paragraph after the table (no language set; how languages match; the details of
  this record).
- [03-features.md §Subtitles](../plan/03-features.md#output-tracks): the foreign audio search
  bullet (when it runs, its evidence, the forced flag) and the burn-in behaviour.

## Follow-up (core-complete review, 2026-10-16)

Review R1 of `core-complete` found defects in the selection stage; each fix has a test that
fails before it (`tests/batch/test_main_tracks.py` unless named otherwise).

- **R1-1 (blocker): "no listed language found" counted the extra tracks.** It was computed
  over every track, so a commentary or audio description in a listed language "found" the
  language; the extra was then dropped (`commentary = drop`, the default) and the no-match
  rule never ran. A French film with an English audio description, the built-in *H.265 MKV
  1080p* and English as the preferred audio language gave a draft with **no audio track and
  no issue**. Now only main tracks count (`selection.select_tracks`; `Selection.no_listed_language`
  is "the source has main tracks and none is in a listed language"), as the module's own
  docstrings already said; section 3 above is corrected (it said "no track at all"). The same
  rule holds for **subtitles**, which share the selection (03 §Subtitles: "the same track
  selection part"): a listed-language commentary subtitle no longer stops the no-match rule
  (it is `none` by default for subtitles, so the built-in presets do not change). A source
  whose every track is an extra has no main track, so `no_listed_language` stays false there;
  with `commentary = drop` such a source still gets no audio track and no issue, as before
  (**open**: the no-match rule takes only main tracks).
  Tests: `test_a_listed_audio_description_is_not_a_listed_language_found`,
  `test_no_listed_language_counts_main_tracks_only`,
  `test_the_kept_commentary_comes_after_the_no_match_track`,
  `test_a_listed_commentary_subtitle_does_not_count_as_found`,
  `test_take_none_with_only_a_listed_commentary_is_an_error`,
  `test_no_listed_language_through_the_facade` (the reviewer's case with the built-in preset;
  subtitles; the facade on the real `multitrack` fixture); the test that pinned the old behaviour is now
  `test_selection.py::test_a_listed_commentary_does_not_count_as_found`.
- **R1-2: `no_match = none` was an error even when other languages were kept.** With
  `other_languages` `keep_first` / `keep_all` the selection takes the other-language tracks,
  but the draft still had `defaults.no_listed_language` ("…take no track…"), which kept a valid
  job out of the queue, and neither fix changed the tracks. Now the error is raised only when
  the selection takes **no main track** (`explain.audio_stage`). A kept commentary alone does
  not count as a main track, so "take none" with only a listed-language commentary is still
  the error, with the message "no main audio track in Hungarian (only commentary,
  description or music-only tracks)"; both fixes then take the main track. Tests:
  `test_take_none_is_an_error_only_when_no_main_track_is_taken`,
  `test_take_none_with_only_a_listed_commentary_is_an_error`, the new case in
  `test_explain.py::test_no_listed_language_take_none_is_an_error_with_fixes`, and the facade
  test on the real `dts-hd-ma` fixture.
- **R1-3: a kept commentary could be the default track or the burned-in subtitle.** The
  audio `first_in_first_language` default, the foreign-audio burn-in target ("the Hungarian
  subtitles for the English audio") and the subtitle `first_in_first_language` default took
  the first track in the first language, and a kept extra track has that language too. Now
  the three choices skip extra tracks (`explain._main_in_first_language`, and the subtitle
  default checks the pick's group) and fall back as sections 4 and 5 say: the first output /
  the first copied track, no foreign-audio burn-in. Sections 4 and 5 are corrected. Tests:
  `test_a_kept_commentary_is_never_the_first_language_default_audio`,
  `test_a_commentary_subtitle_is_never_burned_in_for_foreign_audio`,
  `test_foreign_audio_burn_in_takes_the_main_subtitle`,
  `test_a_commentary_subtitle_is_never_the_first_language_default`.
- **R1-5 (docs): stale lines.** Section 6 said `validate_template` reports a codec twice
  "until the lead passes `container_codecs=False`", and Consequences said `JobService.draft`
  "still drops" `TrackDraft.issues` and the subtitle decisions. Both were done before this
  review (`validation/__init__.py` passes `container_codecs=False`; `jobs.py` carries the
  subtitle decisions and the track stage's errors); both lines are corrected, and the stale
  "Open:" sentence is gone from the C-12 row of `docs/status.md`.
- **R1-6: an empty subtitle track was "few events".** `forced_evidence` ranked a track with
  **0 events** as few events (0 % of the largest count), so the foreign audio search took an
  empty track as the forced track (flagged forced, first). An event-count evidence now needs
  at least one event. The real tools make such tracks: an SRT muxed by FFmpeg with no event
  inside `-t`, then `mkvpropedit --add-track-statistics-tags`, gives `NUMBER_OF_FRAMES=0`,
  which the probe reads as `event_count=0`. C-3's heuristic had the same gap (decision 0006
  follow-up). Tests: `test_explain.py::test_an_empty_subtitle_track_is_not_the_forced_track`,
  `tests/probe/test_roles_empty_subtitles.py` (real FFmpeg and mkvpropedit).
- **A broken `LanguageIETF` made a track undetermined** (suspected by the lead, confirmed):
  `batch.metadata.effective_language` took `language_ietf` whenever it was set, so a track
  with a valid `language` (`hun`) and a tag of the right shape that is not a language
  (`hu-Latn-ZZ9`, `xx`) was undetermined and dropped. Now a `language_ietf` that
  `reframe.languages.normalize` rejects is passed over for a valid `language`; when neither
  is valid the raw tag is kept, as before. (The probe drops such tags too; this is the batch
  engine's side.) Test: `test_explain.py::test_an_invalid_language_ietf_falls_back_to_the_language`.

No plan text changes: 03 gives these settings without the details corrected here.
