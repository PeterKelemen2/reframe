# 0074 — The Range selector: step F-19, built in M10

- Status: accepted
- Date: 2026-11-13
- Steps: F-19 (new), F-17, F-16

## Context

[01 §Feature parity baseline](../plan/01-scope.md#feature-parity-baseline-handbrake) keeps
"Range (chapters, seconds, frames)", and "Must-have for v1" is everything in that table. The
first item of M10's release checklist checks each must-have against its demo. The only UI spec
is one line of the layout sketch in [03 §App layout](../plan/03-features.md#app-layout):
`Range [Chapters 1–12 ▾]` in the source header. No step builds it. M8 recorded the gap and asked
which milestone builds it ([m8-breakdown.md](../m8-breakdown.md) "Where M8 ended", item 3).
`docs/status.md` lists it as the gap of the features "Range, Dimensions, Filters, Video" and
"Web app".

What exists (checked in the code on 2026-11-13):

- **Model** (C-2, `reframe.models.job`): `JobSettings.range` is `FullRange | ChapterRange |
  TimeRange | FrameRange`, discriminated by `kind`. Chapters are 1-based and inclusive. Time is
  in seconds, with `end = None` meaning to the end. Frames are 0-based with an exclusive `end`,
  and `None` also means to the end. The default is `full`.
- **Validation** (C-8, `reframe/validation/range.py`): `range.outside`, `range.end_beyond` and
  `range.no_frame_rate`, with fixes ("Encode the whole source", "End at the end of the
  source"). `range_duration` gives the seconds that a range covers.
- **Command builder** (C-7, [0013](0013-command-builder-details.md)): `-ss` as an input option,
  the end as `-t`, frames turned into time with the average frame rate, and chapters cut on a
  chapter edge written as FFMETADATA. A burn-in with a range keeps its timing.
- **Naming** (C-16): `{chapters}` gives the selected chapter range.
- **Batch** (C-12, [0040](0040-batch-engine-and-reframe-batch.md)): a `JobTemplate` has no range
  (always the whole file). A per-file override can patch `/range`
  (`tests/batch/test_overrides.py`).
- **Frontend**: `components/summary/estimate.ts` already uses the range. The source header
  (`views/WorkspaceView.vue`) shows the title, the duration and `PresetPicker`, and no range.
- No CLI option sets a range.

## Decision

The owner chose (2026-11-13) to build the Range selector in M10 as a new step **F-19**, on
`m10-hardening`, before F-16, so that the i18n and accessibility audit covers it. The plan gets
the step, the M10 step list and a Range section in 03. No model, server or schema change is
needed. If one turns out to be needed, it gets its own decision record.

How F-19 works:

1. **Place.** In the source header, between the duration and `PresetPicker`, when a source is
   open. It is a button that shows the range ("Whole source", "Chapters 2–3",
   "0:01:30 – 0:45:00", "Frames 0 – 1440") and the length it covers, from the same arithmetic
   as `range_duration`. The button opens a popover.
2. **Modes.** *Whole source*, *Chapters*, *Seconds* and *Frames*. A mode that the source cannot
   use is disabled and says why: *Chapters* for a source without chapters, and *Frames* when the
   main video has no frame rate (the condition of `range.no_frame_rate`).
3. **Chapters.** Two selects, *From* and *To*. Each row is the number, the chapter's name and
   its start time. Choosing a *From* after *To* moves *To* to the same chapter, and the other way
   round.
4. **Seconds.** *Start* and *End* accept `H:MM:SS.mmm`, `MM:SS` or plain seconds, and are shown
   as `H:MM:SS.mmm` after a change. An empty *End* means to the end. Text that does not parse
   stays in the field with an error and changes nothing.
5. **Frames.** *From frame* (0-based) and *To frame (not included)* map one to one onto the
   model. The help line says so. An empty *To* means to the end.
6. **Changing mode** keeps the span when the source gives the data: chapter times turn into
   seconds, and seconds turn into frames with the average frame rate, rounded down for the
   start and up for the end. Moving from seconds or frames to chapters picks the chapters that
   hold the start and the end. Otherwise the mode starts from its default.
7. **Edits.** Each committed change is one JSON patch on `/range` through the editor store, so
   it is one undo step. The `range.*` issues show on the popover's fields (paths `range`,
   `range.start`, `range.end`) and on the button. Their fixes work as they do elsewhere.
8. **Group target.** A template has no range (0040), so in a group the selector always edits the
   shown file's override. The button gets the override dot, and *Reset to group* sets the whole
   file again. *Apply to whole group* is not offered: chapter numbers and times differ from file
   to file.
9. **What follows the range.** The Summary (the Source and Estimate cards show the range), the
   output name (`{chapters}` through the naming preview), the command drawer, and the queue's
   edit-back (the range is part of `JobSettings`). Picking a preset keeps the range, because a
   preset has none.
10. **Preview.** The frame strip still covers the whole source, and the live clip still sets its
    own range. A strip limited to the range is not part of F-19.
11. **Strings and keyboard.** Every string goes through vue-i18n. The popover opens from the
    keyboard, keeps the focus inside it while it is open, and closes on Escape with the focus
    back on the button. F-16 audits it with the rest.
12. **Tests.**
    - Unit tests: time parsing and formatting, the conversions of item 6, the summary text, and
      the component (modes, disabled modes, issues on fields, the group override).
    - A server test of the selector against the `chapters` fixture through `jobs/validate` and
      `jobs/plan`.
    - **A new Playwright flow 5**: open `chapters.mkv`, set *Chapters* 2–3, and check:
      - the header shows the range and its length;
      - the output name has `{chapters}` = `2-3` with a template that uses it;
      - the command drawer has the `-ss` and `-t` of the chapter times;
      - after queueing, the queued job's settings have the range.

      F-17 runs flow 5 with the other four in Chromium and WebKit.

## Consequences

- M10 grows by one frontend step. The first release-checklist item can pass for Range.
- The status rows "Range, Dimensions, Filters, Video" and "Web app" lose their Range gap when
  F-19 is done.
- **F-19's demo:**
  1. Open `chapters.mkv` and pick *Chapters* 2–3.
  2. The Summary, the output name and the command drawer follow.
  3. Run a real encode with the pinned FFmpeg.
  4. ffprobe gives an output duration equal to chapters 2–3, within one frame. Check the output's
     chapters as well.
  5. Do the same with *Seconds* and with *Frames*. Undo goes back step by step.

  Record the measured durations in the M10 breakdown. Do not rely on memory for how FFmpeg
  cuts.
- **Not in F-19:**
  - a CLI option for the range;
  - *Apply to whole group* for a range;
  - a frame strip limited to the range.

  Each can come later with its own record.

## Plan changes

- `03-features.md`: a **Range** section after Summary, and the table of contents.
- `06-web-app.md` Part B: **F-19 Range selector**.
- `08-roadmap.md` §M10: F-19 in the step list.
- `06-web-app.md` F-17: flow 5.
