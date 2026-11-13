# 0075 — The range in a group: the shown job of scope `group` carries the file's range

- Status: accepted
- Date: 2026-11-13
- Steps: F-19, F-13 (the group target), F-4

## Context

[0066](0066-m7-batch-season.md) built the group target of the editor:

- Item 2 of its store notes: "The shown job is always `batch/resolve` of the shown file (with
  its override in scope `file`)". In scope `group` the shown job is the template in that file,
  without the file's override.
- Item 1: an edit in scope `group` that the template cannot hold, the range among them, is
  refused with a "per file" toast.

[0074](0074-range-selector-in-m10.md) item 8 says that in a group the Range selector always edits
the shown file's override, whatever the scope, because a template has no range
([0040](0040-batch-engine-and-reframe-batch.md)). Item 9 says the output name (`{chapters}`) and
the command drawer follow the range.

Review R1 of F-19 found that the two rules do not fit. In scope `group`, the header and the
Summary's Source and Estimate cards showed *Chapters 2–3*. But the naming preview, the command
drawer and the validation work on the shown job, and that job had no range. So on the same
screen:

- the output name kept `{chapters}` = `1-4`;
- the command had no `-ss` and no `-t`;
- the issues list said "No issues" while the range button showed a warning.

The matrix and the queue were right, because they resolve each file with its whole override.
The lead reproduced it on 2026-11-13: a group of three copies of `chapters.mkv`, with
*Chapters* 2–3 set on E01 in scope `group`.

## Decision

1. **The shown job of scope `group` carries the shown file's range.** It is `batch/resolve` of
   the template in that file, with only the `/job/range` operations of the file's override. The
   other overrides still show only in scope `file`. Scope `file` is unchanged: the whole
   override. The store puts the file's range into the shown job at once, so an undo, a redo
   and *Reset to group* show without waiting for the resolve.
2. **A patch on the range goes into the file's override, in either scope.** A patch whose
   operations are all under `/range` (the selector, an issue's fix such as *End at the end of
   the source*) goes to the shown file's override, as `editor.setRange` does. A patch that
   mixes the range with other fields still takes 0066's way. No fix or control makes such a
   patch today.
3. **A range that is the whole source is no override.** When a file's override operations on
   `/job/range` give the whole source, they are removed. An example is the fix *Encode the
   whole source*, in either scope or in the matrix. The file then shows no override dot, as
   after *Reset to group*.
4. **The template never holds a range.** The derive of an edit in scope `group` sends only the
   template sections. `batch/derive` ignores `range` (checked in `derive_template`).

## Consequences

- In both scopes, the naming preview, the command drawer, the validation and the Summary give
  the same range as the header, the matrix and the queue.
- 0066 item 2 is amended for the range only: other per-file values (the output path, the
  parsed-name fields, the track metadata) still show only in scope `file`.
- The selector reads the range issues from the validation store in both scopes. The earlier
  read of the matrix row in scope `group` is gone.
- Tests: `frontend/src/stores/editor.range.test.ts` covers "the shown job of scope group".
  `frontend/src/stores/editor.groupRange.server.test.ts` checks a real server: the group of
  three `chapters.mkv` copies, the name `…E01 2-3`, `-ss 1 -t 3` for E01, and E02 and E03
  left whole.

## Plan changes

- `06-web-app.md` §F-4: the note on the group target names this record. §F-19 links it.
