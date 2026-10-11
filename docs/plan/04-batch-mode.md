# 04 — Batch / Season Mode

## Problem

In HandBrake, you configure the audio and subtitles for episode 1, and then you must do the
same work again for every other episode. The files are structurally identical, but
HandBrake only applies preset rules. It cannot repeat the manual changes you made.

## Goal

Configure **one** file. Apply the setup to every file with the same structure. Use **rules**,
not fixed track indexes, so small differences (an extra commentary track in episode 5) still
map correctly. Show every file where the mapping is uncertain.

## Concepts

| Term | Meaning |
|------|---------|
| **Track descriptor** | Normalised summary of one stream: type, codec, profile, channels, language, title, role, flags, position |
| **Fingerprint** | Ordered list of a file's track descriptors, plus the video resolution and HDR type. Hashed per strictness level |
| **Batch group** | Files that share a fingerprint at the chosen strictness level |
| **Group template** | The `JobTemplate` (settings + track rules + naming) shared by the group |
| **Override** | A per-file JSON patch on top of the template |
| **Track rule** | "Output track N comes from the source track that matches selector S, with settings A and metadata M" |
| **Resolution** | The result of applying a template to one file: concrete `JobSettings` + match report + issues |

## Grouping

Grouping runs automatically when you add a folder or several files. You can also select files
and choose **Group these**.

Strictness levels:

| Level | Compares | Use for |
|-------|----------|---------|
| Strict | Everything in the descriptor, including titles and order | Same release, same muxer |
| Standard (default) | Type, codec, channels, language, role, order. Ignores titles and bitrates | A typical season |
| Loose | Type, codec family, language, role. Ignores order and channel count | Mixed sources (different releases in one season) |

The sources panel shows a group like this:

```
▾ Show S01  ·  12 files  ·  standard match                     [Edit group] [Add group to queue]
    E01  ✓
    E02  ✓
    …
    E05  ⚠ 1 extra track (eng AC-3 2.0 "Commentary")
    E11  ✗ no match for output audio #2 (eng DTS-HD MA 5.1)
```

A file that does not match the group at all is shown as a **near match**: "differs in 1
track". You can add it anyway. It then gets per-file overrides.

## Three ways to edit

1. **Edit group** (main workflow). The editor is bound to the group template. The preview,
   track tables and crop use a **representative file** (the first file by default, and you can
   switch it). Every change goes into the template. A banner says
   `Editing group "Show S01" (12 files) — showing E01`.
2. **Apply from file.** Edit any single file normally, then choose **Apply to group…**. A
   dialog asks which sections to apply: Dimensions, Filters, Video, Audio, Subtitles, Chapter
   options, Tags, Output naming. Reframe turns the file's settings into a template (see
   [deriving rules](#deriving-rules-from-a-manual-selection)) and merges it into the group
   template.
3. **Copy / paste sections** between any files, even files in no group: right-click a file →
   **Copy audio settings**, then select other files → **Paste audio settings**. This uses the
   same rule derivation.

## Track rules

```python
class TrackSelector(BaseModel):
    kind: Literal["audio", "subtitle"]
    languages: list[str] | None = None        # BCP 47, in order of preference
    codecs: list[str] | None = None           # "truehd", "dts", "ac3", …
    profiles: list[str] | None = None         # "DTS-HD MA", "TrueHD Atmos", …
    roles: list[TrackRole] | None = None      # main, commentary, description, sdh, forced, signs
    exclude_roles: list[TrackRole] | None = None
    channels: int | None = None
    title_pattern: str | None = None          # case-insensitive regex
    nth: int = 0                              # nth candidate after filtering and sorting
    sort: Literal["source_order", "most_channels", "highest_bitrate"] = "source_order"

class OutputTrackRule(BaseModel):
    selector: TrackSelector
    multiple: bool = False                    # True = one output track per matching source track
    settings: AudioOutputSettings | AudioCodecRules | SubtitleOutputSettings
                                              # fixed settings, or codec rules evaluated per matched track
    metadata: TrackMetadataTemplate           # language (or "from source"), name template, flags
    required: bool = True                     # no match → error (True) or skip with warning (False)
```

Presets use the same model. The preset's audio defaults
([03 §Audio defaults](03-features.md#audio-defaults-stored-in-the-preset)) compile into
`OutputTrackRule`s: one per language in the selection list, with `settings` set to the codec
rules (`AudioCodecRules`). Those rules are evaluated for each matched source track (language,
channels, codec, bitrate). A manual edit in batch mode becomes a rule with fixed
`AudioOutputSettings`. **There is one rule engine for presets and batch mode.**

### Deriving rules from a manual selection

When you pick source audio track #2 by hand in E01, Reframe builds the most specific selector
that describes it:

```
E01 track #2: eng · DTS-HD MA · 5.1 · role=main · title "English Dub"
→ selector: languages=[eng], codecs=[dts], profiles=["DTS-HD MA"], channels=6,
            roles=[main], title_pattern="^English Dub$", nth=0
```

### Resolving rules in another file

For each rule, Reframe finds candidates that match the full selector. If there are none, it
**relaxes** the selector one field at a time, in a fixed order, and records each step:

1. drop `title_pattern`
2. drop `profiles` (DTS-HD MA → any DTS)
3. drop `channels`
4. drop `codecs`
5. stop (the language and role filters are never dropped)

| Result | Shown as | Severity |
|--------|----------|----------|
| Exact match | ✓ | — |
| Matched after relaxing | ≈ "matched without title, profile" | warning |
| Several candidates where the rule expects one | ≈ "2 candidates, picked #3 (source order)" | warning |
| No match, `required=True` | ✗ | error |
| No match, `required=False` | – "skipped" | info |

## Resolution matrix

**Check group** opens a matrix with one row per file and one column per output track:

```
            │ V          │ A1 jpn TrueHD→Opus 5.1 │ A2 eng DTS-HD→AC-3 5.1 │ S1 eng Signs │ S2 eng Full │ Output name
────────────┼────────────┼────────────────────────┼────────────────────────┼──────────────┼─────────────┼────────────────────────
E01         │ ✓ 1080p    │ ✓ #1                   │ ✓ #2                   │ ✓ #1         │ ✓ #2        │ Show - S01E01 - Pilot.mkv
E05         │ ✓ 1080p    │ ✓ #1                   │ ✓ #2                   │ ✓ #1         │ ✓ #2        │ Show - S01E05 - ….mkv
E11         │ ✓ 1080p    │ ✓ #1                   │ ✗ none                 │ ≈ #1 (title) │ ✓ #2        │ Show - S01E11 - ….mkv
```

- Click a cell to see the candidates and choose one by hand. This creates a per-file override.
- Columns can be sorted and filtered ("show only problems").

## Per-file overrides

- Some settings are per-file by nature, and the template holds a **policy** for them, not a
  value:
  - **Crop**: "auto-detect per file" (default) or "same manual crop for all".
  - **Chapter names**: from source, or generated.
  - **Tags and output name**: templates.
  - **Range**: full file (default).
- Any field can be overridden for one file. The editor shows a dot next to the field, with
  **Reset to group** and **Apply to whole group** actions.
- Overrides are stored as JSON patches against the template, so later template changes still
  reach the fields that a file did not override.

## Output naming

Batch mode uses the templates, variables and name-source rules from
[03 §Output naming](03-features.md#output-naming). In addition:

- The matrix has a naming column. Each file shows its chosen name source and its parsed fields
  (`{name}`, `{season}`, `{episode}`, `{sub_title}`, `{year}`). An edit there is a per-file
  override.
- A preview table shows every output name before you queue. Name collisions within the batch,
  or with existing files, are errors.

## Queueing a group

**Add group to queue** resolves every file:

- No errors → one job per file is queued, in episode order.
- Some files have errors → a dialog lists them. Options: **Queue the valid files, skip the
  others** · **Open matrix** · **Cancel**.

## Save as preset

A group template is a preset with rules and a naming template. **Save as preset** stores it,
so the next season from the same release group takes one click.

## Example

Anime season, 12 episodes. E01 has: `jpn TrueHD Atmos 7.1`, `eng DTS-HD MA 5.1`, subtitles
`eng ASS "Signs & Songs" (forced)` and `eng ASS "Full"`. E05 also has `eng AC-3 2.0
"Commentary"`.

1. Add the folder → one group of 12 (standard level). E05 is marked "1 extra track".
2. **Edit group**. In Audio: A1 = jpn TrueHD → Opus 5.1 448k, name `Japanese 5.1`, default.
   A2 = eng DTS-HD MA → AC-3 5.1 640k, name `English 5.1`. In Subtitles: S1 = Signs (forced
   flag), S2 = Full (default).
3. **Check group** → all ✓. E05's commentary track is not selected, because no rule asks for
   the `commentary` role.
4. **Add group to queue** → 12 jobs.

## Core API (implemented in `C-12`)

```python
def describe_tracks(source: MediaSource) -> list[TrackDescriptor]
def fingerprint(source: MediaSource, level: MatchLevel) -> Fingerprint
def group_sources(sources: list[MediaSource], level: MatchLevel) -> list[BatchGroup]
def derive_template(job: JobSettings, source: MediaSource, sections: set[Section]) -> JobTemplate
def merge_template(base: JobTemplate, incoming: JobTemplate, sections: set[Section]) -> JobTemplate
def resolve(template: JobTemplate, source: MediaSource, override: JsonPatch | None) -> Resolution
def resolve_group(group: BatchGroup, template: JobTemplate, overrides: dict[SourceId, JsonPatch]) -> list[Resolution]
```

Done when:

- A 12-file fixture set (generated by `scripts/make-testdata.py`, with an extra track in one
  file and a missing track in another) groups and resolves as the matrix above shows. A
  snapshot test checks this.
- Applying E01's manual audio setup to the group gives identical audio settings for all
  matching files.
- Changing the template after a file was overridden updates that file's other fields and keeps
  the overridden ones.
