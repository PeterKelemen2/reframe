# 0106 — Defaults applied to a job stay with it while it is open

- Status: accepted
- Date: 2026-11-24
- Steps: F-10, F-12

## Context

[Decision 0065](0065-m6-tracks-and-metadata.md) item 4: *Apply* in the audio or subtitle
defaults dialog, opened from a job's tab, replaces the job's tracks with what the edited
defaults draft, and "the job keeps no defaults of its own" (`JobSettings` has none).

The owner found the consequence in use (2026-11-24): after *Apply* and closing the dialog, the
preset showed no *modified* marker, reopening the dialog showed the preset's defaults again,
and *Save as new preset* left the edits out. The editor's `currentTemplate`, which
`presets/diff`, the dialog and *Save as new preset* read, took `audio_defaults` and
`subtitle_defaults` from the preset only.

## Decision

The owner's choice: the open job remembers the defaults applied to it.

1. The editor's job target holds the applied `audio_defaults` / `subtitle_defaults`
   (`OwnDefaults`), and `currentTemplate` lays them over the preset's. The *modified* marker
   lists them, the dialog reopens with them, and *Save as new preset* saves them.
2. *Apply* is one undo step with the tracks; undo and redo take the defaults with them. When the
   tracks do not change, there is no step and the defaults are still kept.
3. Choosing another preset, or drafting the job as a remux, drops them: that draft's tracks
   come from the new preset's defaults. An undo brings them back.
4. They stay in the editor only. `JobSettings` still has no defaults: a queued job is its
   tracks, and a job loaded back from the queue starts from its preset's defaults (no
   persisted-schema change).

## Consequences

- What the dialog shows and what the marker compares are the defaults that gave the job's
  tracks, for as long as the job is open.
- A job loaded back from the queue, or a source opened again, has lost them; saving them into
  a preset is still the way to keep them.

## Plan changes

- `06-web-app.md` §F-10, the defaults dialog: *Apply* from a tab keeps the defaults with the
  open job.
