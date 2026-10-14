# 0028 — Preset export returns `PresetExport`, so newer presets are kept

- Status: accepted
- Date: 2026-10-14
- Steps: C-9 (affects C-15 `reframe presets export`, S-x export endpoint)

## Context

The wave-2 contract in `docs/m2-breakdown.md` gives `PresetStore.export(ids) -> PresetFile`.
The M2 review found that "export all" leaves out, without a word, the presets that a newer
Reframe wrote (a higher preset schema version). This Reframe keeps such presets in
`presets.json` unchanged (decision [0015](0015-presets-and-settings-stores.md)), but it
cannot read them into `Preset` models, so a `PresetFile` cannot hold them. The C-9 fix
changed the return type to keep them, and reported the contract change to the lead. No code
outside C-9 calls `export` yet.

## Decision

`PresetStore.export(ids=None)` and `Reframe.presets.export(ids=None)` return `PresetExport`:

- `file`: the `PresetFile` of the presets this Reframe reads (the old return value);
- `newer`: the newer presets as their raw JSON, unchanged;
- `default_preset_id`;
- `issues`: one `preset.newer_version` warning per newer preset;
- `document()`: the complete export file to write.

`import_` accepts a `PresetExport` as well as a `PresetFile`.

## Consequences

- An export never loses a preset. A newer Reframe that imports the file gets its presets back
  with their unknown fields.
- `reframe presets export` (C-15, later) and the export endpoint (S-x) write `document()` and
  show `issues`.

## Plan changes

- None. `docs/m2-breakdown.md` (the lead's working notes): the C-9 contract line.
