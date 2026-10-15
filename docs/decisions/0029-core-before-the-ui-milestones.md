# 0029 — Finish the core before the UI milestones (one branch, `core-complete`)

- Status: accepted
- Date: 2026-10-15
- Steps: C-6, C-10, C-11, C-12, C-13, C-14, C-15 (core parts of M6–M9)

## Context

The roadmap ([08](../plan/08-roadmap.md)) builds the core parts of M6–M9 together with their
UI parts, after M3 (API and desktop spike), M4 (frontend MVP) and M5 (desktop shell). After M2
every core step that is left belongs to M6–M9:

| Step | What is left | Roadmap milestone |
|------|--------------|-------------------|
| C-12 | selection stage of the audio / subtitle defaults, `explain`, the defaults lint | M6 |
| C-12 | descriptors, fingerprints, grouping, rule derivation, resolution, overrides, match report | M7 |
| C-10 | bitrate scan, subtitle scans, loudness measure | M6 |
| C-10 | frames, crop detection, preview clip, frame cache | M8 |
| C-13 | the `metadata_edit` job type, mkvpropedit builder, post-mux fix-up, re-probe check | M6 |
| C-6 | the complete option sets of 03 §Advanced and the per-preset defaults | M9 |
| C-14 | power actions with the cancellable 60 s countdown, the notification hook | (M2 left them out) |
| C-11 | the when-done power actions through C-14 | (M2 left them out) |
| C-15 | `Reframe.batch`, `sources.frames / cropdetect / scans`, `jobs.preview_clip`; CLI `tools`, `presets`, `batch` | M6–M8 |

The user asked to build all of these core parts now, before M3.

## Decision

1. **New order.** The core is finished first: every open `C-x` step above, in the waves of
   [core-breakdown.md](../core-breakdown.md). Then M3 (API and desktop spike), M4, M5, and the
   UI parts of M6–M9 (F-10, F-11, F-13, F-7, F-8, F-9). The server and UI steps (`S-x`, `F-x`,
   `D-x`) are not part of this work.
2. **One branch.** All core work goes on one branch, `core-complete`, made from `main`. Each
   parallel task gets its own worktree branch, which the lead merges into `core-complete` with
   `--no-ff` after every Python check passes.
3. **Merge into `main`.** `core-complete` merges into `main` (`--no-ff`) when every step's
   "Done when" passes, the findings of a fresh review are fixed, and the core demos listed in
   the breakdown pass (run for real, output kept in the final report).
4. **Milestones stay open.** M6, M7, M8 and M9 stay open in `docs/status.md` until their UI
   parts are built and their full demos (with the UI) pass. The status file shows their core
   parts as done.

## Consequences

- M3 starts with a complete core API to expose: S-2 can map every route of 06 §S-2 to a facade
  method at once, and the generated TypeScript types cover the M6–M9 models.
- The core demos of M6–M9 are run without the UI (CLI where the plan has a command, otherwise a
  short script against the `Reframe` facade). The UI demos of those milestones are still to do.
- The risk of building core API before a UI uses it: the UI steps may find gaps. They are then
  handled as normal follow-ups of the core steps, with their own decision records.

## Plan changes

- [08-roadmap.md](../plan/08-roadmap.md): a note at the top of the dependency graph on the
  changed order.
