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

## Follow-up (M2 review, 2026-10-14)

The M2 review found five defects. Each one has a regression test that failed before the fix.

1. **guessit reads no config files.** Without the option `no_user_config`, guessit 4.4.0
   reads `guessit.options.json` in the working folder and `options.json` in `~/.guessit` and
   `~/.config/guessit` (also `.yml` / `.yaml` when PyYAML is installed; not
   `$XDG_CONFIG_HOME`; checked one location at a time, testdata/README.md "Output naming
   (C-16)"). With `{"type": "movie"}` in the working folder, guessit reports the episode
   title of `The.Sopranos.S03E02.Proshai.Livushka…` as `alternative_title`. With a malformed
   file, every call fails, so `{main_title}` is the whole name: the M2 demo item 5 gave
   `hacksawridge.2160p.remux-henderson`. Every guessit call now has `no_user_config`
   (`reframe.naming.parse.GUESSIT_OPTIONS`), so naming reads the file system only through
   `NamingFs`. Test: the fixture `guessit_user_config` puts config files in the working
   folder, a fake home folder and `$XDG_CONFIG_HOME`; the parse tests and the whole corpus
   pass with it. The fixture resets guessit's `default_api`, which keeps the config files
   of the first call for the whole process.
2. **A number override is 1 to 9 ASCII digits.** `field_overrides` of `season`, `episode`
   and `year` (spaces stripped) must match `[0-9]{1,9}`; anything else is the warning
   `naming.bad_override` and the parsed value stays. `str.isdigit` accepted `²`, which `int`
   refuses (a `ValueError` out of `resolve_output_name`), and Arabic-Indic and full-width
   digits. More than 9 digits is no season, episode or year, and `int` refuses more than
   4300 digits. The absolute-episode rule of decision 2 uses `str.isdecimal`: guessit reads
   Arabic-Indic and full-width digits as numbers (`Bleach - ٠٠١` is episode 1), and `int`
   takes every decimal digit, but not `²`.
3. **A width or precision in a format spec is at most 255.** `{season:999999999999}` made
   `format` build a string of 1 TB: `reframe name --template` and `check_template` ended
   with `MemoryError`. Every run of decimal digits in a number or text spec must be at most
   255, the bytes of one path part, so a larger value can never be used. Digits of every
   script count: `format` reads `٢٥٦` and `２５６` as 256. A larger value is the error
   `naming.bad_format_spec`, and `format_value` raises `ValueError` before it calls `format`,
   so rendering uses the default format (C-7's tag values render through the same
   function). Date specs have no limit: `strftime` limits its own output (on glibc,
   `%999999999999Y` gives an empty string). `{episode:c}` of a number that is no character
   (`OverflowError`) is also a `ValueError`, so rendering never raises.
4. **The byte limit holds after the `_` of a reserved name.** `CON.` and 300 characters was
   cut to 255 bytes, and then the `_` made `CON_.…` 256 bytes. The part is cut again after
   the `_`. The cut keeps `CON_`, so the part does not become reserved again. A property test
   applies every rule together: each folder part is at most 255 bytes, each file part with
   `.part` is at most 255 bytes, and no part is empty, reserved, or ends in a dot or a space.
5. **A byte that is not UTF-8 becomes `�` (U+FFFD).** A POSIX file name is bytes. Python
   holds a byte that is not UTF-8 as a lone surrogate (`bad\xffname.mkv` →
   `bad\udcffname.mkv`), and UTF-8 cannot encode it, so `reframe name` failed when it
   counted the bytes. Choice: the output name replaces each such byte with `�`, as a UTF-8
   decoder (`errors="replace"`) and most file managers show it. The byte is not kept,
   because that name cannot be written on Windows or exFAT (decision 3: Windows rules on
   every OS), in JSON (the queue store, the API) or by most other tools. The replacement is
   made before parsing (`parse_name`; positions do not move) and in `{file_name}` and
   `{folder_name}`, so every text of a `NameResult` is valid Unicode. Only real paths keep
   the byte (the source's folder in `NameResult.path`, `NameCandidate.path`). The note
   "Replaced bytes that are not UTF-8 with '�' …" tells the user. The byte limit then counts
   the UTF-8 bytes of the cleaned text, which is what `os.fsencode` writes on every
   supported OS (UTF-8 file system encoding). A lone surrogate in a template, a manual name
   or an override (JSON text from the API can hold one) is replaced in the same way. The
   probe cache stores such a path as an ASCII JSON escape (C-3, `reframe/probe/cache.py`).

## Plan changes

- `docs/plan/03-features.md` §Where the name comes from (step 2), §Variables (`{resolution}`),
  §Safe file names (replacement table, 250 bytes for the file name).
- Follow-up (M2 review): `docs/plan/03-features.md` §Template syntax (width and precision at
  most 255), §Safe file names (bytes that are not UTF-8, the limit after every rule);
  `docs/plan/05-core.md` §C-16 (guessit reads no config files).
