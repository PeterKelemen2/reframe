# 0040 — The batch engine: one rule engine, selectors and relaxation, grouping, overrides, `reframe batch`

- Status: accepted. The points marked **(open)** are product questions answered with a default
  that is easy to change (each is one constant or small function, named below).
- Date: 2026-10-15
- Steps: C-12 (M7 part; core-complete wave 2a), C-15 (`Reframe.batch`, `reframe batch`)

## Context

[04-batch-mode.md](../plan/04-batch-mode.md) describes descriptors, fingerprints, grouping,
track rules with relaxation, rule derivation, per-file overrides as JSON patches and the
resolution matrix, and its core API; [05 §C-12](../plan/05-core.md#c-12-batch-engine) adds
"parsed-name overrides for C-16" and [05 §C-15](../plan/05-core.md#c-15-service-facade-and-cli)
the CLI `reframe batch DIR --preset NAME [--dry-run]`. 04 also says "The preset's audio
defaults compile into `OutputTrackRule`s … **There is one rule engine for presets and batch
mode**", while 1a's selection stage (decision [0031](0031-audio-and-subtitle-selection-stage.md))
has settings that a `TrackSelector` cannot express. Building it showed where the plan is silent
or cannot be followed literally. The fixtures were checked with FFmpeg n9.0.2
(testdata/README.md "Batch engine (C-12, M7)").

## Decision

### 1. One rule engine, two ways in

`reframe.batch.resolve(template, source, override)` is the one way a job is made from a
template: `Reframe.jobs.draft` (`reframe.jobs.draft_from_preset`) and `Reframe.batch.resolve`
both call it, so a preset and a batch group make the same job for the same file. Its track stage
(`reframe.batch.rules.resolve_tracks`; `draft_tracks` is now a thin wrapper) works per kind:

- **Explicit rules** (`audio_rules` / `subtitle_rules`, made by *Apply to group*): each rule's
  selector finds its track(s) with relaxation (section 2); fixed settings are copied, and
  `AudioCodecRules` settings run C-12's codec rules (`apply_codec_rules`) on the track that was
  found. Explicit rules replace the defaults **of their kind**; the subtitle defaults' foreign
  audio search hears the explicit audio.
- **No explicit rules**: the defaults are compiled into rules (`compile_defaults`: one per
  listed language with `AudioCodecRules` settings, as 04 says, plus a rule for each other part
  of the selection that takes tracks: the no-match track, other languages, commentary and
  descriptions, the foreign audio search; with no language at all one "every track" rule), and
  the tracks come from 1a's selection stage, unchanged. Each selected track is attributed to
  its compiled rule, so the matrix has one column per compiled rule with ✓ / "– skipped".
  What a `TrackSelector` cannot say (the default-flagged track, "not a listed language",
  `und` counted as the first language, source output order, the default-track policy, burn-in)
  stays the selection stage's; the compiled rules name the columns. A test checks that every
  built-in preset on every recorded probe gives exactly the tracks, decisions and issues of the
  selection stage, with and without preferred languages; the M2 / M6 draft tests are unchanged.

### 2. Selectors, relaxation and the result cells

- **Matching** (`reframe.batch.selectors`): every list is "one of" (languages, codecs, profiles,
  roles); `profiles` match the commercial name or ffprobe's profile, any case; roles are C-3's
  roles with flag or title evidence (not the heuristic ones, see §3) plus what the disposition
  flags give a source without the prober (`stream_roles`), `main` when none; `languages` is an
  order of preference, then `sort`. **`sort: highest_bitrate` is 0031's best quality** (lossless
  first, an unknown bit rate after every known one, then channels); for subtitles `most_channels`
  and `highest_bitrate` put full before SDH before forced. A title pattern that is not a regular
  expression, and a selector of the other kind, are errors (`batch.bad_title_pattern`,
  `batch.rule_kind`); the rule takes nothing.
- **Relaxation**: exactly 04's order (title, profiles, channels, codecs; never language or
  role), only the fields the selector sets. **Several rules (open):** every rule is matched with
  its full selector first; a relaxed rule never takes a track that another rule matches exactly
  (a track picked by hand, `stream`, is such a match), nor one an earlier relaxed rule took;
  exact matches may share a track (a passthru and an AAC copy of one source track are a
  choice).
- **Cells**: `exact` ✓; `relaxed` ≈ "matched without title, profile" (warning
  `batch.track_relaxed`); `ambiguous` ≈ "2 candidates, picked #3 (source order)" when a
  single-track rule finds **more than `nth + 1`** candidates (warning `batch.track_ambiguous`;
  a rule derived from one of two identical tracks therefore warns in every file, which is
  true: it can only go by order); `missing` ✗ (error `batch.track_missing`, fix "make the rule
  optional", target template); `skipped` – (info `batch.track_skipped`).
- **A hand pick in a matrix cell** is the new optional field `TrackSelector.stream` (the
  absolute stream index, for a per-file override; the other fields are then not checked). It
  is a new optional field of a persisted model: no `schema_version` change (older Reframes keep
  it as an unknown field).
- **`languages: []` takes no track.** *Apply to group* of a job without audio (or subtitles)
  gives one optional rule with `languages: []`, because an empty rule list means "the
  template's defaults"; its cell is "skipped" without an issue, its column "A1 no track".
- **Metadata** (`TrackMetadataTemplate`; `None` = from the source track): a rule's explicit
  `default: true` wins over source default flags; without one, the first output whose source
  track is default keeps the flag (at most one per kind, as 0031); a burned-in subtitle and a
  codec rule's extra output are never the default. Name templates have the variables of
  0019 (audio) and `lang`, `lang_name`, `lang_native`, `codec`, `title`, `source_codec`
  (subtitles).

### 3. Descriptors, fingerprints, grouping

- **No level compares bit rates (open)**: 04's descriptor table has no bit rate, and the bit rate
  of a lossless or VBR track differs per episode of one release, so a strict level that compared
  it would never group a season. **For the same reason no level compares a role that C-3 infers
  from statistics** (heuristic evidence: a subtitle with at most 25 % of the events of another
  track of its language is "forced", an untitled 2.0 track of at most 192 kb/s after a 5.1 track
  of its language is "commentary"): the event counts and bit rates vary per episode of one
  release. Descriptor roles, and so fingerprints, derived selectors and rule matching, are the
  roles with flag or title evidence; the heuristic ones stay on the stream (the selection stage
  and the UI show them). Strict compares kind, codec, profile, channels, language, title, roles
  and the six flags, in order; standard kind, codec, channels, language, roles, in order; loose
  kind, codec family, language, roles, in any order (a multiset). Codec families
  (`reframe.batch.descriptors`): DTS and DTS-HD; AC-3 and E-AC-3; TrueHD and MLP; AAC; MPEG audio;
  every PCM; subtitles `text` (SRT, ASS, WebVTT, mov_text) and `bitmap` (PGS, VobSub, DVB). Only
  the codec decides the family, so the levels nest (a property test). Video: strict and standard
  compare the size, loose the resolution class (`1080p`, C-16's `resolution_label`; a cropped
  1920×800 is 1080p); every level compares the HDR type.
- **Near members (open)**: a file within **2** differences (`NEAR_MAX_DIFFERENCES`: an extra, a
  missing or a changed track, a different video size or HDR type, each 1; at the loose level too,
  where an unmatched extra track and an unmatched missing track of one kind are paired in stream
  order as one changed track) of a group with at least as many files joins it as a near member,
  with one line per difference ("1 extra track (eng AC-3 2.0 "Commentary")", "1 track missing (eng
  DTS-HD MA 5.1 "English Dub")", "1 track differs (eng ASS "Signs & Songs" → eng ASS "Signs")").
  Files with one fingerprint are grouped first; the largest groups (then the one first in episode
  order) take the near files. The resolution of a near member gets the warning `batch.near_match`
  (04's "E05 ⚠").
- **Episode order**: season, episode (C-16's parser on the file name, the folder for what the
  file name lacks), then the natural order; files without an episode after. **Group name**: the
  show name and season most members share (`Anime Show S01`). **Representative**: the first
  exact member in episode order; its fingerprint is the group's.

### 4. Deriving and merging (*Apply to group…*)

- The **most specific selector** (04): language (`und` for none), codec, commercial name and
  channels (audio), roles, `^title$` (an untitled track gets no title pattern), and the `nth`
  that picks it in its own file. Titles are escaped only for the characters a regular
  expression reads (`^Signs & Songs$`, not `re.escape`'s `^Signs\ \&\ Songs$`).
- Settings become fixed settings; the language and the six flags are written as they are; the
  **name only when it is not the source title (open)**: an unchanged name stays "from the
  source" in every file (E11 keeps its own "Signs"), an edited one ("Japanese 5.1") is the
  same everywhere. A literal name's braces are doubled; `<` and `>` are naming-template groups
  and cannot be written.
- Sections: dimensions (a manual crop → policy `fixed`; an automatic one → `detect_per_file`
  without this file's rectangle), filters, video (the video track's metadata is per file),
  audio (`audio_rules` + `audio_defaults`), subtitles (external subtitle files are per file and
  left out), chapters (generated names stay `generated`, edited names are per file), tags,
  naming (the job's own template and name source on the base's options; manual names and
  parsed-name corrections are per file). **Output options (container, web optimized, …) are in
  no section (open)**: they stay the base's; 04's dialog has no Output section.
- `derive(job, source, sections, base=None)` uses the job's preset as the base, else the
  default preset. The result is always a plain `JobTemplate`.

### 5. Per-file overrides as JSON patches

- **The patch is against a per-file document: the template, plus one member `job` that holds
  the job resolved for that file.** Template paths (`/audio_rules/1/settings/bitrate`,
  `/subtitle_rules/0/selector/stream`) are applied **before** the resolution, so a later change
  of the template reaches every field the patch does not touch, the rules are resolved again
  with the patched selectors, and a hand-picked track gets its own codec rules. `/job/…` paths
  are applied **after** it: the fields that are per file by nature (range, chapter names, a crop
  of this file) and **C-16's parsed-name overrides**, `add
  /job/output/naming/field_overrides/episode "5"` (the service then names the job with them).
  Not chosen: a patch on the resolved job only (the index of an output track moves when the
  template's rules change; a cell pick could not re-run the codec rules) or on the template only
  (it has no place for range, chapter names or `field_overrides`).
- **An override keeps the structure of the rule lists**: an operation that adds, removes or
  moves a track rule, or replaces a whole rule list (or the whole document), is
  `batch.override_invalid` and the override's template part is not applied. The matrix columns
  are the template's rules: a file whose rules moved would show its cells under other rules'
  columns. A change inside a rule, or a whole rule replaced in its place, is fine;
  `replace /audio_rules/1/selector/languages []` makes a rule take no track in one file. The
  same holds for the rules that the defaults compile to (a template without explicit rules):
  an override of `/audio_defaults` or `/subtitle_defaults` that changes which rules they
  compile to is `batch.override_invalid` too (follow-up of the final review, RA-3).
- **Stale overrides are issues** (`batch.override_stale`, warning): an operation whose path
  vanished is skipped and the rest applied; a failed `test` skips the rest of the override (it
  was made for another template); a `move` / `copy` between the template and the job, or a
  result that is not a valid template or job, is the error `batch.override_invalid` and that
  part is not applied. `Resolution.override` keeps the patch as given.
- `Reframe.batch.resolve(…, overrides=…)` finds a file's patch by its path whatever the
  spelling (absolute, normalised, case-folded where the OS does).

### 6. Per-file policies, naming, validation, collisions (the service)

- **Crop `detect_per_file` (open)**: the job has the template's mode (automatic or
  conservative) **without a rectangle**, as a single draft has; the batch service does not run
  C-10's crop detection for every file (the UI's crop detection fills it per file; `reframe
  batch`, like `reframe encode`, encodes without a crop and validation says so). `fixed`: the
  template's rectangle as a manual crop. A manual crop stays as it is. Chapter names: the
  source's or generated; tags and output names are templates rendered per file; the range is
  always the whole file. A change for M2 drafts: a user preset with an automatic crop and a
  saved rectangle no longer applies that rectangle to every file.
- **Naming**: the template's naming options, else Settings → Output, through the new
  `Reframe.jobs.name_job` (the code `draft` already used, so a name that is the source itself
  becomes `Name (1).ext`); `Reframe.jobs.validate(…, naming=…)` validates with the same
  options.
- **Collisions** (04: "Name collisions within the batch, or with existing files, are
  errors"): `batch.name_collision` (two files of the batch, on each row and once for the
  batch), `batch.output_is_source` (an output that is another file of the batch, in every
  collision setting: **a file of the batch is never overwritten**; C-8's `output.overwrite`
  warning is then left out of the row); `batch.output_exists` when the output exists, is not
  a file of the batch, and the collision setting would rename it (C-8's info `output.renamed`)
  **(open)**: with *ask*, C-8's `output.exists` error says it already; with *overwrite* the
  user chose to replace it, and C-8's warning stays. `reframe batch` checks the files of
  **every group** of the run together (`Reframe.batch.resolve_batch`).
- **An earlier run's outputs are left out**: a media file of the batch that is the planned
  output of another file of the batch is not grouped, resolved or queued; it is an info
  `batch.already_encoded` of the grouping ("`Anime Show - S01E01 - Pilot.mkv` is the planned
  output of `….S01E01….mkv` with this preset: it is left out"). The file whose output it is
  gets `batch.output_is_source` (its output exists and is a file of the batch). A re-run of a
  half-encoded season (outputs next to the sources) so queues only the episodes not done yet;
  to encode a done episode again, remove its output (or move it out of the folder), or give
  the source files instead of the folder. Reframe cannot tell an earlier output from another
  release that has the output's name, so neither is ever replaced.
- Probes run 4 at a time (`PROBE_CONCURRENCY`); a file given twice is probed once (also
  through a link, a linked folder or a hard link: files are compared as files, follow-up of
  the final review, RA-1); an unreadable file is a `source.probe_failed` issue of the grouping and an error row of the
  matrix. An unknown preset name is `preset.not_found` (the default preset's settings, every
  row an error).

### 7. `reframe batch`

`reframe batch DIR… [--preset NAME] [--level strict|standard|loose] [--dry-run] [-r] [--json]`
groups the media files (C-15's folder search), resolves the preset in every group and prints,
per group, the members (near members with their differences), the column legend (`A1  jpn
TrueHD→Opus 5.1`), the matrix as plain text (`reframe.batch.report.matrix_lines`: no wrapping,
no trailing spaces; ASCII marks when stdout is not UTF-8) and each file's errors and warnings.
**Cells name tracks by their absolute stream index**, as `reframe probe` and `reframe plan`
do (04's matrix numbers audio and subtitle tracks separately: "S1 ✓ #1" is "✓ #3" here).

- The files that cannot be read and the files left out as already encoded are listed first
  (once each); a row is labelled `E05`, `S01E05` when the group spans seasons, and the file
  name when two rows would have one label.
- `--dry-run`: the last line is `Dry run: N of M files can be queued[; K cannot (errors)][; L
  left out (already encoded)].`; exit 0 when every file can be queued (a left-out file is not
  an error), else 1. `--json` (only with `--dry-run`, else exit 2):
  `{"grouping": BatchGrouping, "resolutions": [BatchResolution]}`.
- Without `--dry-run` **(open)**: the files without errors are queued in episode order (group
  by group) and encoded as `reframe encode` does (the same code: progress, Ctrl+C, the
  when-done countdown, the summary); a file with errors is listed as "not queued" (04's
  *Queue the valid files, skip the others*; a CLI cannot ask), and the exit code is 1 as for
  `encode` with a file not queued.
- Exit codes as 0017: 2 an unknown preset or a bad option, 3 a path that does not exist or no
  media files, 130 Ctrl+C.
- `reframe plan` now prints a `selected:` line under each selected audio and subtitle track
  (`TrackDecision.selection`: the selection stage's reason or the track rule that took it), and
  the subtitle tracks (`Subtitle #4  Copy`).

### 8. The core API

04's `resolve_group(group, template, overrides)` has no sources: the pure function needs the
probed files, so it is `resolve_group(group, template, sources, overrides, *, definitions,
languages)` (`sources`: a mapping by path or a list). `resolve(template, source, override, *,
definitions, languages)`; `describe_tracks`, `fingerprint`, `group_sources`, `derive_template(…,
*, base)`, `merge_template` as 04 says. New optional fields of runtime models
(`reframe.models.batch`): `GroupMember.season` / `episode`, `TrackMatch.defaults` /
`MatrixColumn.defaults` (a compiled column), `Resolution.decisions` / `subtitle_decisions` /
`notes`.

### 9. The fixtures

`anime-s01` is 04's example as FFmpeg can make it: `jpn` **TrueHD 5.1** (FFmpeg's `truehd`
encoder refuses 7.1 and writes no Atmos), `eng` DTS-HD MA 5.1 "English Dub" (1b's
`reframe_testing.dts`), `eng` ASS "Signs & Songs" (forced) and "Full" (default), 2 s per file;
E05 adds `eng` AC-3 2.0 "Commentary" (comment), E11 has no dub and a signs track titled
"Signs" (04's matrix: "A2 ✗ none", "S1 ≈ (title)"). Names `Anime.Show.S01E01.Pilot.BluRay.x264-GRP.mkv`
in `Anime.Show.S01.BluRay.x264-GRP/` (C-16 gives `Anime Show`, season 1, the episode title),
no resolution in the names (the video is 320×180). `anime-s02` has three episodes with E01's
layout. The demo preset (E01's setup applied to the group, with 04's naming template
`{name} - S{season:02}E{episode:02}< - {sub_title}>`, separator space) is
`packages/reframe/tests/batch/data/anime-season.preset.json`, checked against the derivation by
a test. **It has the fix that E11's ✗ offers applied (A2 optional)**: 08 §M7's demo wants
"✓ for every file, with the right warnings for E05 and E11 → queue 12 jobs", and the CLI has
no per-file overrides; so E11 shows "A2 – skipped" and "S1 ≈ #2 (title)" (⚠), and all 12 files
are queued. The derivation itself keeps `required: true` (04's default), which gives 04's
matrix with "A2 ✗ none" (the snapshot test, and a CLI test with the dub required).

## Consequences

- `reframe encode --preset "<a group preset>"` uses the group's track rules: a preset saved
  from a season works on single files too, and E11's missing dub is an error there as well.
- The matrix of a preset without rules shows compiled columns ("A1 every track (defaults)"),
  so `reframe batch` is useful before any group editing.
- A hand-picked stream index in a saved preset would pin every file to that index: the field
  is meant for per-file overrides only (the UI must not save it into a template).
- Revisit with the UI (F-13): the near threshold, the Output section of *Apply to group*, the
  crop detection per file, ambiguity of derived rules on identical tracks.
- `reframe batch DIR` searches the folder as `reframe encode DIR` does (0017): outputs written
  next to the sources by an earlier run are media files too; they are left out as already
  encoded (§6), and their episodes are not queued again (`batch.output_is_source`). A file of
  the batch is never overwritten, also with the collision setting *overwrite*: to encode an
  episode again, remove its output first. A fixed output folder in the naming options keeps
  the outputs out of the folder search.
- `reframe encode FILE|DIR…` of several files has the same name checks, file by file
  (`reframe.jobs.OutputClaims`): a job whose output is another file of the command is
  `batch.output_is_source`, and a job whose output an earlier job of the command already has
  is `batch.name_collision`; both are not queued (the first file keeps the name). It does not
  leave earlier outputs out (it has no grouping step). Paths are compared as files
  (`reframe.jobs.file_key`): an output named through a linked folder or a hard link to a
  source is that source (follow-up of the final review, RA-1).

## Open product questions (defaults chosen, easy to change)

1. Strict compares no bit rate (`descriptors.track_key`).
2. Near members within 2 differences (`grouping.NEAR_MAX_DIFFERENCES`).
3. A relaxed rule does not take another rule's exact match (`selectors.match_rules`).
4. An unchanged track name stays "from the source"; an edited one is the same in every file
   (`derive._metadata`).
5. Output options are in no *Apply to group* section (`derive.SECTION_FIELDS`).
6. `detect_per_file` leaves the rectangle empty; the batch does not run crop detection
   (`resolve._dimensions`).
7. An existing output is a batch error only with the setting *auto-rename*
   (`service._collisions`); an output that is a file of the batch is an error with every
   setting.
8. `reframe batch` queues the valid files and lists the others, exit 1 (`cli.run_batch`).
9. A file of the batch that is the planned output of another file of the batch is left out as
   already encoded (`BatchService.resolve_batch`), not encoded as a source.
10. A per-file override cannot add, remove or move track rules (`overrides.structural_op`),
    or change the rules that the defaults compile to (`resolve.compiled_rules_moved`).

## Follow-up (core-complete review, 2026-10-16)

- **R2-1 (blocker): the name checks cover every group.** `reframe batch` resolved each group on
  its own, so `batch.name_collision` and `batch.output_is_source` compared only the files of
  one group: with the collision setting *overwrite*, E01's job replaced another release's file
  named as E01's output (another group; its SHA-256 changed), and two outputs with one name in
  two groups were both queued (the first lost; with *auto-rename* the printed target was
  wrong). Now `Reframe.batch.resolve_batch(template, sources, *, level, overrides)` resolves
  the whole batch and runs the checks over the rows of every group (and every folder
  argument); `reframe batch` uses it. `batch.output_is_source` is an error with every collision
  setting (a file of the batch is never overwritten). `reframe encode FILE|DIR…` had the same
  hole (each file drafted alone): `reframe.jobs.OutputClaims` now refuses a job whose output is
  another file of the command or the output of an earlier job of the command. Tests:
  `tests/jobs/test_cli_review_fixes.py` (`test_batch_never_writes_a_file_of_another_group`,
  `test_batch_two_outputs_with_one_name_in_two_groups`, `test_resolve_batch_checks_every_group`,
  `test_encode_never_writes_another_file_of_the_command`, `test_encode_two_outputs_with_one_name`,
  and `test_the_leads_reproduction_with_the_real_queue` with the real queue and FFmpeg: the
  copy's SHA-256 changed before the fix).
- **R2-2 (major): heuristic roles are informational.** Fingerprints and derived selectors used
  every C-3 role, also the ones inferred from per-episode statistics, and roles are never
  relaxed: a signs track with 22 % of the full track's events in E01 and 27 % in E02 split the
  season (E02 a near member) and the S1 rule derived from E01 was "✗ none" in E02.
  `descriptors.stream_roles` now keeps the roles with flag or title evidence (§3); an untitled,
  unflagged signs track can then only be told from the full track by order (its rule is "≈ 2
  candidates", in every file). Tests: `tests/batch/test_batch_review_fixes.py`
  (`test_heuristic_roles_neither_split_a_season_nor_break_a_derived_rule`,
  `test_descriptor_roles_have_flag_or_title_evidence`).
- **R2-3: an override that changes the rule lists is invalid.** Cells are keyed by the rule's
  index and the columns come from the template, so an override that removed or inserted a rule
  put the file's cells under other columns. Chosen fix (the cheapest correct one): such an
  override is `batch.override_invalid` and its template part is not applied (§5); a rule can be
  emptied for one file with `languages: []`. The matrix also keys a cell by explicit / compiled
  rule. Test: `test_an_override_that_changes_the_rule_lists_is_invalid`.
- **R2-4: a changed track counts once at the loose level too** (it counted as 1 extra + 1
  missing, so the most lenient level kept fewer near members). Tests:
  `test_a_changed_track_counts_once_at_every_level`, `test_loose_pairs_changed_tracks_by_kind`
  (and `test_grouping.py::test_the_loose_level_ignores_the_order`, updated).
- **R2-5: `reframe plan` / `encode` show the track rules' issues.** `JobService.draft` kept
  only the track stage's errors; it now also keeps every `batch.*` issue of the track rules
  (`batch.track_relaxed`, `batch.track_ambiguous`, `batch.track_skipped`), as `reframe batch`
  shows them. Test: `test_plan_with_a_group_preset_shows_the_track_rule_warnings`.
- **R1-4: one issue per problem.** On the job path that C-8 validates (`JobService.draft`,
  `BatchService` rows) the defaults lint runs with `container_codecs=False` (new keyword-only
  parameter of `resolve_tracks`, `resolve`, `resolve_with_tracks`, `draft_from_preset`; default
  `True`, so `explain` and the pure engine still report it): a WebM preset with an AAC codec
  rule gives C-8's `container.codec_unsupported`, not also `defaults.codec_not_in_container`.
  Test: `test_a_codec_the_container_cannot_hold_is_one_issue`.
- **R2-6: labels with the season.** A group that spans seasons showed two `E01` rows; rows and
  members are now labelled with `grouping.episode_labels` (`S01E01` when the files span
  seasons, the file name when two files would share a label). Tests:
  `test_matrix_labels_name_the_season_when_a_group_spans_seasons`, `test_episode_labels`,
  `test_a_group_of_two_seasons_names_the_season`.
- **R2-7: re-runs.** §6 said a re-run queues only the episodes not done yet, §Consequences that
  the earlier outputs form a group and are queued again as `… (1).mkv` (the code did the
  latter). The behaviour is now §6's: an earlier output is left out (`batch.already_encoded`).
  **Deviation from the lead's instruction**: the lead asked that the episode whose output
  exists keep "the existing-output handling it has today", which with *overwrite* is to
  replace it. That cannot hold together with R2-1: in the lead's own reproduction, another
  release's file named as E01's output is (by its name) E01's planned output, so it would be
  left out and replaced. The episode therefore gets `batch.output_is_source` with every
  setting: nothing given to the batch is replaced. With *ask* and *auto-rename* the episode
  was not queued before either. Test: `test_a_rerun_queues_only_the_episodes_not_done_yet`.
- **Suspected points (all real, all fixed):** a hand pick (`selector.stream`) now counts as an
  exact match for relaxation (`test_a_hand_pick_counts_as_an_exact_match`); a source track
  that two explicit rules take is the first of its language for both, for codec rules with
  `first_track_of_language_only` (`test_a_track_that_two_rules_take_is_the_first_of_its_language_for_both`);
  a rule whose settings are of the other kind is a "✗" cell with the error, not "✓ exact"
  (`test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell`); the row sort of
  `BatchService.resolve` (C-16's parser, guessit) runs in a worker thread
  (`test_the_row_order_is_computed_off_the_event_loop`).
- The compiled no-match column's "skipped" text is "a main track of a listed language was
  found" (the selection stage now counts main tracks only, decision 0031's follow-up).
- Plan text changed with this follow-up: [04](../plan/04-batch-mode.md) §Grouping (the roles
  compared), §Per-file overrides (the rule lists keep their structure), §Output naming (a file
  of the batch is never overwritten; an earlier run's outputs are left out);
  [05](../plan/05-core.md) §C-15 (`resolve_batch`, the `reframe batch` line).

## Follow-up (final review, 2026-10-17)

A final review of the fix rounds (reviewer R-A, on `core-complete` 5dbf152) found one blocker
(RA-1) and minors in C-12 / C-15. The lead ran RA-1's reproduction again on the real tools.

- **RA-1 (blocker): the name checks compare files, not spellings.** The R2-1 fix compared paths
  as `normcase(abspath(p))`: links were not resolved and file identity was not compared, while
  the queue compares files (R4-1). With the collision setting *overwrite*, `reframe encode
  real/E01.mkv link/Anime.Show.S01E01.Pilot.mkv` (`link` → `real`, the second file a user
  file named as E01's planned output) queued E01's job, which replaced the user file (real
  FFmpeg n9.0.2 and the real queue: its SHA-256 changed from 2071b4d0… to another value; the
  second job then failed reading it); `reframe batch` of the same files did the same, and
  `reframe batch real link --dry-run` listed every episode twice. Now one key per file,
  `reframe.jobs.file_key(path) -> str`, is used by `OutputClaims`, `find_media_files`,
  `BatchService._probe_all`, `resolve` (the group order, near members, overrides),
  `resolve_batch` (the rows, the left-out outputs) and `_collisions`:
  - a path that exists is its identity, `st_dev` and `st_ino` of `os.stat` (links followed): a
    symbolic link, a linked folder and a hard link are the file; on a file system that ignores
    case (Windows, macOS) another case of the name is the file too, because `stat` finds it;
    on Windows the two numbers are the volume serial number and the file index, so a mapped
    drive and its UNC path are one file;
  - a path that does not exist (a new output), or a file whose identity is not known
    (`st_ino` 0, which some Windows network file systems give), is its path with the links
    resolved (`realpath`, which resolves the existing part of the folder; on Windows
    `GetFinalPathNameByHandle` gives a mapped drive's UNC path), `normcase`d and case-folded,
    as the queue's `reframe.queue.files.same_file` does. On Linux two new output names that
    differ only in case are taken as one file (the safe side: the second is
    `batch.name_collision`); two **existing** files that differ in case stay two files (their
    identities differ), so a folder with `E01.mkv` and `e01.mkv` gives two jobs;
  - a path that `stat` or `realpath` refuses (a NUL character: `ValueError`, RB-2 of the
    review) falls back to `normcase(abspath(…))`: the key never raises.

  The key is a string of `reframe.jobs` (dictionaries of a whole batch need a hashable key;
  `queue/` is not changed) and follows the queue's rule; `test_ra1_file_key_agrees_with_the_queue`
  checks it against `reframe.queue.files.same_file`. It differs on purpose in one case: two existing
  files whose names differ only in case on Linux are two files here (the queue's case-folded
  fallback takes them as one, the safe side for running jobs; for "taken once" both must be
  encoded).

  *Changed on 2026-10-17 (core-complete follow-up, after RB-1 made the queue's `FileKey`
  public):* `file_key` is now built on `reframe.queue.files.file_key`, so there is one
  implementation of the rule. The string is the identity when there is one, else the resolved,
  case-folded path, so the case difference above stays. Validation's
  `LocalFileSystem.same_file` (`os.path.samefile` before) follows the same rule for a file
  system without file indexes (`st_ino` 0: the paths decide, not the identity). Test:
  `tests/validation/test_same_file.py` (`test_without_file_indexes_two_files_are_not_the_same`
  failed before).

  The key is computed **off the event loop** (the lead's note from RB-1: a `stat` of a network
  share that stops answering would freeze the loop): `find_media_files` already runs in a
  worker thread; the CLI builds `OutputClaims` and calls `check` with `asyncio.to_thread`; the
  batch service computes the keys of the given files, the group members, the overrides and the
  outputs in worker threads and then compares strings (`_collisions` runs in a thread).
  **Decision: a file given twice through two spellings is taken once**, like a file given twice
  the same way, in the spelling it was first given (labels, rows, messages and job sources keep
  the paths as typed): `reframe batch real link` lists each episode once. Two hard-linked
  names are one file too (also for `reframe name DIR`). A batch file that is the planned output
  of another file by identity (a hard link with another name) is left out as already encoded;
  the message then names the planned output ("`Other.mkv` is the planned output of `…E01…`
  with this preset (the same file as `Anime.Show.S01E01.Pilot.mkv`)"). Tests:
  `tests/jobs/test_cli_final_review.py` (`test_ra1_encode_never_writes_a_source_given_through_a_linked_folder`
  and `test_ra1_batch_never_writes_a_source_given_through_a_linked_folder`, the reviewer's
  tests; `test_ra1_encode_never_writes_a_hard_linked_output_name`,
  `test_ra1_batch_never_writes_a_hard_linked_output_name`,
  `test_ra1_a_folder_given_through_two_spellings_is_taken_once`,
  `test_ra1_encode_takes_a_file_named_through_a_link_once`,
  `test_ra1_the_file_keys_are_computed_off_the_event_loop`,
  `test_ra1_the_batch_service_keys_files_off_the_event_loop`, and
  `test_ra1_the_symlink_case_with_the_real_queue`: the real FFmpeg and queue, `encode` and
  `batch`, the user file's SHA-256 unchanged) and `tests/batch/test_batch_final_review.py`
  (`test_ra1_file_key_compares_files`, `test_ra1_file_key_agrees_with_the_queue`,
  `test_ra1_file_key_on_windows_mocked` (the Windows rule with mocked `stat`, `realpath` and
  `ntpath.normcase`: a mapped drive and its UNC path, case, a file index 0),
  `test_ra1_output_claims_compare_files`, `test_ra1_find_media_files_takes_a_file_once`,
  `test_ra1_find_media_files_keeps_two_files_whose_names_differ_in_case`,
  `test_ra1_file_key_never_raises_for_a_bad_path`, `test_ra1_resolve_batch_through_a_linked_folder`).
  Known limit: on Windows, two **new** outputs named through a mapped drive and through its UNC
  path are one key only when `realpath` resolves the drive (it does through
  `GetFinalPathNameByHandle`; a network redirector that does not support it leaves the drive
  letter); existing files are compared by identity in every case. Not run on Windows or macOS.
- **RA-3: an override that changes the compiled rules is invalid.** R2-3 kept the structure of
  the explicit rule lists only. A template without explicit rules has compiled columns
  (`matrix_columns`: one per listed language, the no-match track, other languages,
  commentary, the foreign audio search), and a per-file override of the defaults (`replace
  /audio_defaults/selection/languages ["eng","jpn"]` on *H.265 MKV 1080p* with `["jpn"]` and
  other languages kept) changed that file's compiled rules: its cells were keyed by rule number
  under the template's columns (the "A1 jpn" column showed the English dub, "no listed
  language" the Japanese track). **Chosen fix** (the cheap one): `resolve_with_tracks` compares
  the rules that each kind's defaults compile to (with Settings → Languages, since an empty
  list compiles to the preferred languages) for the patched and the original template
  (`reframe.batch.resolve.compiled_rules_moved`); when the parts of the selection they stand
  for differ (the n-th listed language, no-match, other languages, commentary, foreign audio
  search), the override is `batch.override_invalid` (path `audio_defaults.selection`, the
  message lists both rule lists) and its template part is not applied. A change of the codec
  rules, or another language in a listed language's place, keeps the structure and is applied,
  as a change inside an explicit rule is (the column label is then the template's, as for an
  explicit rule whose languages a file changes). A kind with explicit rules is not checked (its
  defaults are not used). Not chosen: keying cells by the compiled rule's identity (a file's
  extra rules would have no column). Tests: `tests/batch/test_batch_final_review.py`
  (`test_ra3_an_override_that_changes_the_compiled_rules_is_invalid`,
  `test_ra3_an_override_inside_the_compiled_rules_is_applied`,
  `test_ra3_preferred_languages_count`, `test_ra3_through_reframe_batch_resolve`: the
  reviewer's case through `Reframe.batch.resolve` with the real ffprobe, the override found
  through a linked folder).
- **RA-4: `reframe encode` no longer says "will be replaced" next to "never overwritten".**
  `OutputClaims`' `batch.output_is_source` error was added to the draft's issues with C-8's
  `output.overwrite` warning still there; the batch path already left it out. The CLI now
  leaves `output.overwrite` out of that job's issues (`cli._with_claims`). Tests:
  `test_ra4_encode_does_not_say_will_be_replaced_next_to_never_overwritten` (the reviewer's),
  `test_ra4_encode_keeps_the_overwrite_warning_of_a_file_outside_the_command`.
- **RA-5: a member labelled by its file name shows the name once.** For two releases of one
  episode `episode_labels` gives the file name, and `render_group` printed the label column
  and the name (`Anime.Show.S02E01.Return.BluRay.x264-GRP.mkv  Anime.Show.S02E01.Return.BluRay.x264-GRP.mkv
  (representative)`). The label column is printed only when the label differs from the file
  name (its width is that of the other labels). Test:
  `test_ra5_a_member_labelled_by_its_file_name_shows_the_name_once`.
- RA-2 (control characters in the batch and encode output) is in
  [0038](0038-cli-tools-presets-and-when-done.md)'s follow-up of the same date.
- Plan text changed with this follow-up: [04](../plan/04-batch-mode.md) §Per-file overrides
  (the compiled rules keep their structure too). §Output naming ("a file of the batch is never
  overwritten") is unchanged: RA-1 makes it hold through links.

## Plan changes

- [04-batch-mode.md](../plan/04-batch-mode.md): §Grouping (bit rates, near members),
  §Track rules (the `stream` field, the matching rules, `highest_bitrate`), §Resolution matrix
  (absolute stream indexes in the CLI), §Per-file overrides (the per-file document), §Core API
  (`resolve_group` takes the sources), §Example (TrueHD 5.1 in the fixture).
- [05-core.md](../plan/05-core.md): §C-12 (a note on this record), §C-15 (the `reframe batch`
  line).
- [09-quality-and-release.md](../plan/09-quality-and-release.md) §Test media: the batch example
  seasons.
