# 0012 — Output naming: the episode rule of the name source, guessit work-arounds, safe names

- Status: accepted
- Date: 2026-10-13
- Steps: C-16 (used by C-8, C-11, C-15, S-2, F-18)

## Context

### 1. Name source: one episode file in a season or show folder

03 §Where the name comes from, step 2, makes the file name the source only when the folder
holds *several* episode files. Otherwise the score decides, and the score does not count the
episode number. Real scores (`reframe.naming.parse_name`, guessit 4.4.0):

```text
'Breaking Bad (2008)'                        4 points ['title', 'year']
'breaking.bad.s01e01'                        3 points ['title']
'Breaking.Bad.S01.1080p.BluRay.x264-ROVERS'  7 points ['title', 'resolution', 'source', 'video_codec', 'release_group']
'S01E01'                                     0 points []
```

So `Breaking Bad (2008)/breaking.bad.s01e01.mkv` takes the folder name, and every episode of
the show gets the same output name `Breaking Bad.mkv`. The same happens when the folder cannot
be listed (`reframe name` on a path that does not exist) or when only one episode of a season
pack was copied. And a season pack with bare file names (`S01E01.mkv`, `01 - Pilot.mkv`) gives
`{main_title}` = `S01E01` for every season of every show.

### 2. guessit behaviour that the plan's rules do not survive

Recorded in `packages/reframe/tests/naming/test_guessit_quirks.py` (real guessit output):

- A bare absolute episode number is split into a season and an episode, but not always:
  `Bleach - 001 - The Day I Became a Shinigami` → season 0, episode 1;
  `One Piece - 1000 - Overwhelming Strength! …` → season 10, episode 0;
  `Naruto Shippuden - 101 [1080p]` → episode 101. guessit's `episode_prefer_number` option
  fixes the anime names but breaks scene numbering: `The.Office.US.102.Diversity.Day` must
  stay S01E02 (it is S01E02 by default, episode 102 with the option).
- `01 - Pilot` → title `Pilot` (after the episode number).
- `VTS_01_1` (DVD title file) → episode 1.
- `UHD.BluRay` → source `Ultra HD Blu-ray` over `BluRay` only; `WEBRip` → source `WEB` +
  other `Rip`. 03's `{source_type}` example is `UHD.BluRay`.
- `-GRP[rarbg]` → release group `GRP[rarbg]`.
- `HDR10Plus` and `HLG` → no HDR match at all.

### 3. Safe names

- The queue writes `<name>.part.<ext>` and renames it (03 §Queue). A final name of 255 bytes
  gives a partial name of 260 bytes, which NTFS and ext4 refuse.
- 03 says the Windows-forbidden characters "are replaced", but not with what.
- 03 writes `{resolution}` for other sizes as `W×H` (U+00D7), a character that cannot be typed
  on most keyboards.

## Decision

1. **Auto name source, step 2**: the file name is the source when the folder holds at least
   two episode files (03), *or when only the file name has an episode number* (the folder name
   has none: a season folder `The.Sopranos.S03.1080p…` or a show folder `Breaking Bad (2008)`).
   In both cases the folder fills the fields the file name does not have: year, edition,
   source, release group, resolution, season, and the show name. When the file name has no
   show name, the folder's show name goes in front of `{main_title}`, in the file's word
   separator: `Breaking.Bad.S01…/S01E01.mkv` → `Breaking.Bad.S01E01`,
   `Fargo.S01…/01 - The Crocodile's Dilemma.mkv` → `Fargo - 01 - The Crocodile's Dilemma`.
   The forced *File name* mode merges the same way. Files directly in `BDMV`, `STREAM` or
   `VIDEO_TS` are never episodes. A generic folder that cannot be skipped (two levels
   skipped already, the opened folder, or the file-system root) gives no folder candidate.
2. **Parsing rules on top of guessit** (`reframe/naming/parse.py`, one test each):
   a bare number of three or more digits right after ` - ` is an absolute episode number (no
   season), and scene numbering without the dash (`Show.102`) stays season + episode; a title
   after the episode number is the episode title; `UHD` right before the source and `Rip` right
   after it belong to `{source_type}`; a `[site]` tag glued to the release group is dropped;
   HDR tokens that guessit misses still count for the score.
3. **Safe names**: the file part, extension included, has at most **250** bytes, so the
   partial file name fits in 255. Replacements: `": "` → `" - "`; `:` `/` `\` `|` → `-`;
   `"` → `'`; `< > ? *` and control characters are removed. Leading spaces are removed as well
   as trailing dots and spaces, so a `..` part becomes empty and is dropped (a template cannot
   leave the output folder).
4. **`{resolution}`** for other sizes is `WxH` with an ASCII `x` (`640x360`). A size gets a
   name when it fits in the class's frame (DCI widths up to 1/14 wider: `4096x2160` is
   `2160p`) and its width or height is within 1/32 of the frame's (`1920x800` and `1440x1080`
   are `1080p`; `720x576` is `576p`; `960x540` and a cropped DVD `720x432` keep `WxH`).

### Choices where the plan is silent

Each one is a small function or constant in `reframe/naming/`, so it is easy to change:

- `{hdr}`: one label, in this order: `DV`, `HDR10+`, `HDR10`, `HLG`. A video passthrough keeps
  the source's HDR; an encode keeps it when the output is 10-bit and there is no `tonemap`
  filter. C-7 decides which HDR metadata an encode really carries; revisit `{hdr}` then.
- `{audio_langs}` / `{sub_langs}`: undetermined languages (`und`, none) are left out; burned-in
  subtitles are not output tracks.
- `{chapters}` for the full range: `1-N` when the source's chapters are known (HandBrake's
  start and end point), else empty. A time or frame range gives an empty value.
- `{folder_name}`: the raw name of the file's own folder (not the folder after skipping
  generic folders; that one is `{source}` when the folder wins).
- `{creation-date}` falls back to the file system's birth time, which Linux does not report:
  empty there when the container has no `creation_time`.
- `{acodec}` of a passthru track: the source's commercial name (`TrueHD Atmos`).
- Word separator: dots stay between the letters of an acronym (`S.H.I.E.L.D`, `E.T. the`)
  and between numbers (`12.00`, `1.23.45`); a dash is the name's separator only when there
  are two or more dashes and no space, dot or underscore.
- Title case is HandBrake's: lower-case first, so `REMUX` becomes `Remux`.
- A template with errors gives `{file_name}` and the issues; an empty result also falls back
  to `{file_name}`.
- Per-file corrections of the parsed name are `JobNaming.field_overrides: dict[str, str]`
  (variable name → text; `""` clears a field). An edited `name`, `sub_title` or
  `episode_code` is also replaced inside `{main_title}`, so the default template follows it.

## Consequences

- One template works for single episodes, season packs and show folders; episode numbers are
  never lost to a better-scoring folder name.
- The rules in 2 depend on guessit 4.4.0. The quirk tests show the guessit output each rule
  works around, so a guessit upgrade that changes it fails there first.
- A file name can be 5 bytes shorter than 255.

## Plan changes

- `docs/plan/03-features.md` §Where the name comes from (step 2), §Variables (`{resolution}`),
  §Safe file names (replacement table, 250 bytes for the file name).
