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

- A track's language is `effective_language` (`language_ietf`, else `language`, canonical).
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
- **No listed language found** means that no track at all is in a listed language.
  `default_flagged` takes the first default-flagged main track, or the first main track when
  none is flagged; `first_track` the first main track. That track also counts as the one track
  of `other_languages = keep_first`. `none` takes nothing; for audio it is the error
  `defaults.no_listed_language` (path `audio_defaults.selection.no_match`, fixes: take the
  default-flagged track, take the first track) in `TrackDraft.issues`, except for a source
  without audio. For subtitles it is not an issue.
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
- Audio: `first_output`; `first_in_first_language` (none in that language: the first output
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
  forced (`forced_event_count`); a Signs & Songs track; few events (C-3's heuristic role, or at
  most 25 % of another track's events, `probe.roles.FORCED_MAX_RATIO`, also for counts measured
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
  when the audio is **not** in the viewer's language, the first selected subtitle in that
  language (HandBrake's "foreign" burn also applies to its foreign-audio subtitle) **(open)**;
  `first` burns the first subtitle output (the search track when there is one, as HandBrake);
  `foreign_audio_then_first` the first of the two that exists. A burned track is not copied.
- **Default track** (on the copied tracks): `none`, `first_output`, `forced` (the first copied
  track with the forced flag, the search track included), `first_in_first_language` (none in
  that language: the first copied track).
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
| `defaults.rule_unused` | info | with a source: no selected track uses the rule (the catch-all and unreachable rules are not reported; nothing when no track is selected) |

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
  `validate_template` gives both until the lead passes `container_codecs=False` to
  `lint_defaults` (a new keyword, default `True` as the contract says); the live preview
  (`draft_tracks`) keeps the lint's issue, because C-8 does not run there.
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
- `JobService.draft` (lead-owned) still drops `TrackDraft.issues` and the subtitle decisions;
  the `no_match = none` error reaches a drafted job only through `JobService.explain` until the
  lead adds them.
- Revisit: the points marked (open); HandBrake's automatic burn-in of a track the container
  cannot hold; a "foreign audio subtitle" setting if users miss it.

## Plan changes

- [03-features.md §Audio defaults](../plan/03-features.md#audio-defaults-stored-in-the-preset)
  part 1: a paragraph after the table (no language set; how languages match; the details of
  this record).
- [03-features.md §Subtitles](../plan/03-features.md#output-tracks): the foreign audio search
  bullet (when it runs, its evidence, the forced flag) and the burn-in behaviour.
