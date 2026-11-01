# 0066 — M7, batch and season mode: how the tabs edit a group, the matrix's route, and the open choices

- Status: accepted
- Date: 2026-11-01
- Steps: F-4 (the group target), F-13, F-17 (flow 2), F-18 (the matrix's naming column),
  C-12 (one derive change)

## Context

M7 ([08 §M7](../plan/08-roadmap.md#m7--batch--season-mode)) builds the batch UI of
[04-batch-mode.md](../plan/04-batch-mode.md) on the core of
[0040](0040-batch-engine-and-reframe-batch.md) and the batch routes of S-2. Its tasks and waves
are in [m7-breakdown.md](../m7-breakdown.md). Before any agent, the lead checked the API
(2026-11-01, on `main` 37226c8, routes read from `reframe_server/routers/batch.py`, answers
checked against a real server with the pinned FFmpeg and the `anime-s01` fixture):

- There: `batch/group`, `batch/derive` (with `base`), `batch/resolve`, `batch/resolve-run`,
  `batch/save-preset`, `presets/defaults/preview` (with `source_ids` and `template`),
  `POST /api/queue` with a list of jobs in order. Each matrix row carries the full validation
  issues of its job, so the matrix needs no `jobs/validate` per file.
- `batch/resolve` does **not** mark a near member: E05's row is `ok` without
  `batch.near_match`. `batch/resolve-run` (which groups again) gives E05 `warning` with
  `batch.near_match`, and runs the name checks over every group of the request.
- E01's default-preset job, its audio and subtitles derived into the default preset
  (`batch/derive`) and resolved in the season, gives 04's matrix: E11 "A2 ✗"
  (`batch.track_missing`, fix `replace /audio_rules/1/required false`, target `template`) and
  "S1 ≈ matched without title"; every other row ✓.
- `merge_template` replaces a whole section. Deriving the audio section again after that fix
  made A2 required again: one later edit of any audio track would silently undo it.

No server route is missing; one core change is needed (item 2).

## Decision

1. **How the tabs edit a group.** The tabs keep reading and writing `JobSettings` pointers
   through `editor.get` / `set` / `patch`. The group target holds the template, the per-file
   overrides, the shown file (the representative until another is chosen), its job, and a
   scope:
   - **Scope `group`** (default): the tabs show the template resolved in the shown file
     *without* its override. An edit shows at once; 250 ms after the last edit the store sends
     `batch/derive {job, source_id: shown, sections: the sections the edit touched, base:
     template}` and the answer is the new template (one undo step). This is 04's *Apply from
     file* for every edit, so there is one way from a job to a template. Output options
     (`/output/*` except `path`, `naming`, `edit_in_place`) are in no derive section
     (0040 open question 5): the store copies them into `template.output` itself.
   - An edit in scope `group` that the template cannot hold (the range, the output path, the
     in-place switch, a manual output name, a parsed-name correction, the video track's
     metadata, chapter names other than the source's or `Chapter N`, an external subtitle) is
     **refused before anything changes**, with a toast that says it is set per file and names
     the *This file only* scope. It is never dropped silently.
   - **Scope `file`**: the tabs show the shown file's job with its override; an edit becomes
     `/job/…` operations in that file's override (a later edit of the same path replaces the
     earlier one). An operation inside an output track (`/job/audio/<i>/…`,
     `/job/subtitles/<i>/…`) comes after a `test` of that track's source
     (`source_stream` / `source`), so a template change that moves the track makes the override
     stale (`batch.override_stale`, a warning in its row), never applied to another track.
     Adding, removing or moving an output track for one file is refused with a toast (the
     matrix's candidate picker does that, item 4).
   - **Undo / redo** work on the document `{template, overrides}`; the shown job and the matrix
     follow from the server. An undo while an edit waits for its derive drops that edit.
   - The state of each group (template, overrides, history, shown file, scope, preset) is kept
     in the page per group id while other files or groups are open, as an open job is; a page
     reload loses it.
2. **Core: a re-derived rule keeps `required`** (C-12, `reframe.batch.derive._kept_required`):
   when `derive_template` derives the audio or subtitle section again on a base that has
   explicit rules, a derived rule whose selector equals a base rule's keeps that rule's
   `required`. A rule made optional for the files that lack its track (E11's fix) stays
   optional when another track of that kind is edited. A rule whose track changed gets a new
   selector and is required again (04's default). Test:
   `test_a_rule_made_optional_stays_optional_when_its_section_is_derived_again` (fails when
   the carry-over is removed).
3. **The matrix uses `batch/resolve-run`** with the edited group's member ids and its level;
   the rows of every resolution in the answer are shown (normally one). It is the route that
   marks near members and checks names across the request; `batch/resolve` is not used by the
   UI.
4. **Hand picks only in explicit-rule columns.** A cell of a column that the template's defaults
   compile to (`defaults: true`) has no candidate picker: an override cannot change the rules
   the defaults compile to (0040 §5, RA-3). Its cell says that one edit of the group's audio
   (or subtitles) turns the defaults into rules that can be picked per file. A pick is `replace
   /<kind>_rules/<r>/selector/stream <index>`; *No track* is `replace
   /<kind>_rules/<r>/selector/languages []` (0040 §5); *Back to the group's rule* removes that
   rule's operations from the file's override.
5. **Override dots** show in scope `file` only, on a `Field` whose path the shown file's
   override sets. *Reset to group* removes those operations; *Apply to whole group* puts the
   file's value into the template as a scope-`group` edit of the shown file would, and removes
   the operations (one undo step).
6. **Copy / paste sections.** *Copy* takes sections (04's eight) of the open job or of the
   edited group's template. *Paste* goes into the open job (one undo step: the clipboard's
   template resolved on the job's source, those sections' fields replaced) or into a group
   (`mergeIntoGroup`). A file that is not open is opened first. Pasting into several files
   that are not open is not built: such a file has no job until it is opened.
7. **Queueing a group**: `resolveNow()` (after the edits on their way), then one
   `POST /api/queue` with every row's job in episode order; with error rows, 04's dialog
   (*Queue the valid files, skip the others* · *Open matrix* · *Cancel*). While a group is
   edited, *Add to queue* and `Ctrl+Enter` run this flow.
8. **Save as preset** saves the template (`batch/save-preset`), never the overrides (a hand
   pick is per file, 0040 Consequences). The group's preset becomes the saved one.
   **Applying a preset to a group** is the header's preset picker while the group is edited:
   the template becomes the preset's (one undo step), the overrides stay (a stale one is a
   warning in its row). 08's "apply it to season 2 in one click" is that pick.
9. A new group's template comes from the open job's preset, else the default preset.
10. **Defaults dialog, group target**: it edits the template's `audio_defaults` /
    `subtitle_defaults`; the live preview covers every member (`source_ids`, `template`);
    *Apply* sets the defaults and clears the explicit rules of that kind so the defaults apply
    (one undo step).
11. *Apply to group…* keeps 04's eight sections (no Output section; item 1 covers output
    options for edits in the group itself).

## Consequences

- One way from an edit to a template (derive), so the group editor, *Apply to group* and
  *Paste* agree; an edit of one audio track derives every audio rule of the shown file again.
- Per-file fields are edited in scope `file`; the matrix's naming column edits parsed-name
  corrections directly.
- Group state is page state, like an open job.

## Plan changes

- 04 §Three ways to edit, item 3: pasting into files that are not open is not built (item 6).
- 06 §F-4: the group target holds the shown file and its job (item 1).

## Task A — F-4 the group target (editor state)

(placeholder: task A writes this section)

## Task B — F-13 group rows, banner, *Apply to group*, copy / paste, *Save as preset*

(placeholder: task B writes this section)

## Task C — F-13 the resolution matrix and queueing a group, F-18 the naming column

Choices where the plan and the brief leave room:

1. **The candidate picker lists every source track of the column's kind**, not only the
   match's `candidates`. For an exact match `candidates` is the taken track alone (checked
   against the real server: E05's A2 has `candidates: [2]`, while E05 also has the commentary
   `#3`), so a list of the candidates only could never pick another track. The tracks that
   match the rule are tagged *matches the rule*, the taken one *taken*. Then *No track* and,
   when the file's override picks this rule, *Back to the group's rule*.
2. **Keyboard: Tab** into each cell's button (the row's mark opens its issues, each track cell
   its picker, the pencil of the name cell its fields); Enter or Space opens it, Escape closes
   the popover only. The V cell has no action and no tab stop. The sort headers are the
   `DataTable`'s (Tab, Enter).
3. **Rows have a fixed height** (60 px) so that the virtual scroller places them without
   measuring; the cell's message and the name's fields are one line each, cut with an ellipsis.
4. **Sorting** is by the file (episode order) and by each track and name column's status (error,
   warning, the rest; ties keep episode order). The V column has no sort: its cell is ✓ for every
   file with a job. The name column's status is the row's worst issue at `output.path` (the
   collision checks). A row without a job (a file that could not be read) sorts first and shows
   its first error in the V cell.
5. **The naming column** shows the output file name, the name source and the five fields as
   `{name} Anime.Show {season} 1 …`; its pencil opens a small editor of the five fields of 04
   (`ParsedNamePanel` has ten fields, candidates and spans, and writes on each key: too much for
   a popover of one row). A field is committed on Enter or blur, once; an empty field takes the
   parsed value again (`null`), an empty field that is not corrected changes nothing.
6. **`ui.matrixFocus` is a source id.** `useQueueGroup`'s *Open matrix* passes the first file
   with errors; the matrix scrolls to that row and focuses its mark.
7. **`useQueueGroup` adds `question` and `answer`** (the contract allows additions): the
   question of the error dialog, which `QueueGroupDialog` (mounted in `MatrixDialog`'s tree)
   shows and answers. It uses stores only (`text()` for its toasts), so B calls it in click
   handlers. While it asks, `busy` stays true: a second *Add group to queue* does nothing.
   *Queue the valid files* queues the rows of the resolution that the dialog listed.
8. **Toasts**: `Queued 12 jobs` (success); a job the queue refused is listed in a warning
   toast (as *Add all* does); a failed resolve or add is the API layer's toast.
9. **The V cell** shows the source's video size (`320×180`), as the sources panel writes it,
   not 04's `1080p`.

## Task D — F-13 override dots, F-10 the defaults dialog for a group, group-aware cards

(placeholder: task D writes this section)

## Task E — F-17 flow 2

(placeholder: task E writes this section)
