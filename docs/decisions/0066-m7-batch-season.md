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
     `/job/subtitles/<i>/…`) comes after a `test` of the whole track as the file's job has it
     without its override (review fix FA, R1-2; first a `test` of the track's source alone, which
     let a new track of the same source take the override), so a template change of that track
     or its place makes the override stale (`batch.override_stale`, a warning in its row), never
     applied to another track. A hand pick likewise comes after a `test` of its rule's selector
     (R1-3).
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
   **Follow-up (2026-11-01, task D's finding, fixed by the lead):** a naming edit of a group
   whose template has no naming (the default preset has none) derived `NamingOptions()`
   defaults, so the output folder became `same_as_source` and every output moved next to its
   source (seen on the real server: `<output>/…` → `<media>/Anime.Show.S01…/…`).
   `BatchService.derive` now derives the naming section on Settings → Output when the base has
   no naming (as `resolve` names such a template); other sections leave `naming` empty. Test:
   `test_a_naming_edit_on_a_base_without_naming_keeps_the_settings_output_folder` (fails
   before; a mutation that fills the naming for every section fails it too).
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

Built in `stores/editor.ts` (the group target), `editor/group.ts` (pure helpers: per-file
fields, derive sections, track-list changes, override merge with `test` guards), small changes
in `stores/sources.ts` and `composables/useValidation.ts`, and the `editor.group.*` messages.

**API answers checked against a real server** (2026-11-01, pinned FFmpeg, `anime-s01`, port
8711):

- `batch/resolve-run` with the default preset: 12 rows, E05 **and E11** `warning` with
  `batch.near_match` (E11 lacks the dub: "1 track missing (eng DTS-HD MA 5.1 "English Dub")"),
  the rest `ok`; `batch/resolve` of one file gives no `batch.near_match` (E05 alone is `ok`).
  So the matrix of "*Edit group* on the season" has E05 ⚠ and E11 ⚠, not "the rest ✓"; the
  real-server test checks the real answer.
- `batch/derive` with `sections: []` returns the base unchanged, and never carries
  `output` (a job with `container: mp4` derived into an `mkv` base keeps `mkv`): the store
  copies the output options itself.
- E01's audio derived (A1 Opus 5.1 448 `Japanese 5.1`, A2 AC-3 5.1 640) gives two explicit
  rules; with the subtitles derived too, the matrix is 04's: E11 `A2 missing` (fix `replace
  /audio_rules/1/required false`, target `template`) and `S1 relaxed` ("matched without
  title"). After the fix E11 is `warning` with `A2 skipped`.
- The resolved subtitles of E01 are already S1 forced and S2 default, so "S1 = Signs (forced),
  S2 = Full (default)" through `editor.patch` changes nothing and derives nothing; the
  real-server test makes a real subtitle edit (S2's name) to get explicit subtitle rules.
- Overrides: `replace /subtitle_rules/0/selector/stream 4` and `replace
  /audio_rules/1/selector/languages []` change only that row ("#4 picked by hand", "the rule
  takes no track"); `add /job/output/naming/field_overrides/sub_title "Signal Fire"` changes
  only that file's output name; a failed `test /job/audio/1/source_stream` gives
  `batch.override_stale` and skips the rest of the job part.

**Choices** (none changes the contract; members were added only):

1. The undo document is `{template, overrides, presetId}`: undoing a preset applied to a group
   brings the old preset back, as for a job.
2. The shown job is always `batch/resolve` of the shown file (with its override in scope
   `file`), not the matrix row, so it never waits for the whole group.
3. A derive whose template changed while it was on its way (a pick, a fix, another merge) is
   derived again on the new template, not dropped: only an undo drops an edit. Leaving a group
   with an edit waiting sends its derive into the kept state.
4. The per-file refusal compares the per-file fields of the job before and after the patch, so
   any operation shape (a `replace` of the whole `/output`, a `move`) is caught.
5. `editGroup` places the target once the shown job is resolved (the target holds a job).
6. A failed derive: its `PendingEdit` keeps the failure; its `flush` removes it (the shown job
   is already back, there is nothing to send again).
7. While a group is edited, validation keeps the template fixes of the shown file's issues
   (`applyFix` puts them into the template); `sources.select`'s failure path and `removeMany`
   keep the shown file active and the group open when the shown file is removed.
8. The group's id contains its representative's path: removing the representative makes a new
   group, so the editor closes, as "the edited group is no longer in `sources.grouping`" says.

## Task B — F-13 group rows, banner, *Apply to group*, copy / paste, *Save as preset*

Built in `components/sources/` (group rows, the context menu) and `components/batch/`
(`GroupBanner`, `ApplyToGroupDialog`, `clipboard.ts`). Choices where the plan leaves one:

- **Keyboard.** A group row's *Edit group*, *Check group* and *Add group to queue* buttons are
  out of the Tab order, as the M4 rows' remove buttons are; the keyboard reaches them, and copy /
  paste and *Apply to group…*, through the row's context menu (`Shift+F10`, the context menu
  key, or a right click). The menu gives the focus back to its row when it closes.
- **The menu.** The eight *Copy … settings* items are on every row, enabled on the open job's
  row and on the edited group's row only; one *Paste … settings* item shows while the clipboard
  holds a section (it holds one).
- **Paste into a group.** From a job: `mergeIntoGroup` (the group is not edited for it). From a
  group's template: the target group is edited first, since `patchTemplate` changes the edited
  group's template. Either way a toast says what was pasted where.
- **Paste into a file.** The fields replaced per section are the job's `dimensions`, `filters`,
  `video` (its metadata stays the file's), `audio`, `subtitles` (the file's external subtitle
  files stay, after the pasted tracks), `chapters` (the file's names stay unless the resolved
  job generates `Chapter N` names), `tags`, and for naming `/output/naming/template` and
  `name_source` only (the output path, a manual name and the corrected fields stay). A resolved
  job has no naming fields of its own (the server names it with the template's naming
  options), so the job's template is the one that named the resolved row (`naming.template`)
  and its name source the template's; a template without naming gives both `null` (the
  settings' naming).
- **The toast of *Apply to group…*** has no *Edit group* button: the toast store has no
  actions (a lead-owned file). The banner's slim line, next to the *Apply to group…* button
  that was used, has *Edit group*.
- ***Save as preset*** reuses `PresetNameDialog` (name, category `Custom`, description; a taken
  name is the server's refusal at the field). The name starts empty, as in the preset picker.
- The banner finds its group in `sources.grouping` with the panel's `panelItems`, so its file
  labels are the panel's.
- The scope switch says `Group` and `This file only (E03)`: the words of the per-file refusal's
  toast, with the shown file's label.

Not built: *Group these* (04 §Grouping; not in M7's breakdown), pasting into several files that
are not open (item 6).

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
   measuring; the cell's message is one line, cut with an ellipsis. The name column keeps its
   fields whole: a wide matrix scrolls sideways, the File column stays (frozen).
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

Browser checks (phase 2, 2026-11-01, headless Chromium, light and dark, against
`scripts/dev-server.py` with the pinned FFmpeg and `anime-s01`; E01's audio set to Opus 5.1 448
"Japanese 5.1" / AC-3 5.1 640 and a subtitle named, through `editor.patch`; Settings → Output's
episode template `{name} - S{season:02}E{episode:02}< - {sub_title}>` with spaces): 38 checks of
the "Done when" pass in each theme. Found and fixed:

- PrimeVue's `DataTable` renders every cell anew when the resolution changes, so the focused
  button was dropped after each pick, fix or name edit. Each action button has a
  `data-focus-key`; after a new resolution the same cell takes the focus back.
- Escape with the focus on a cell whose popover was open closed the whole matrix; the matrix now
  closes the popover only. A click on text left the focus nowhere and Escape did nothing; the
  matrix closes then (as the defaults dialog does).
- After a row fix the popover's row changed under it and the popover jumped to the page's
  corner; a fix now closes the popover and gives the focus back to the row.
- The naming line was cut to a few letters in a narrow column, and the five-field editor
  overflowed its popover; the pencil now leads the cell and the editor is three columns wide.

Seen, not mine (for the lead): editing the naming template while a group is edited
(`editor.patch /output/naming/template`) derives a `naming` section whose
`output_folder_mode` is `same_as_source` instead of Settings → Output's, so every output moves
next to its source and is `output.folder_required` in web mode (every row an error). The checks
set the template in Settings → Output instead.

## Task D — F-13 override dots, F-10 the defaults dialog for a group, group-aware cards

Built in `components/base/Field.vue`, `stores/defaults.ts`, `components/defaults/`
(`DefaultsDialog`, `DefaultsPreview`), `components/summary/OutputCard.vue`,
`components/naming/JobNamingEditor.vue`, `components/tracks/OutputTrackList.vue`, and (given to
task D by the lead) `components/summary/useJobSource.ts`, which gave no source while a group was
edited: the Tracks tab's source table, the track rows and the Summary cards now see the shown
file. Choices where the plan and the brief leave room:

1. **The dot** is a small button in the label (its name: "Encoder differs from the group") that
   opens a popup menu. *Apply to whole group* stays in the menu for a per-file path, disabled,
   with its reason under it. After either action the focus goes to the first control of the
   field (the dot is gone after the action). The `overridden` prop stays a plain dot without a
   menu (the sandbox). A field shows the dot when the override sets its path or a path below or
   above it (`overriddenAt`), so a whole-track field shows it for an edit of one of its members.
2. **The defaults preview of a group** asks for the group's open members in the panel's order
   (`panelItems`, so the labels are the panel's) and shows one table per file. The rules' and
   fields' issues and the issue counts are the shown file's answer (one file's issues; a
   per-file list of the same lint repeated 12 times would say nothing more). The template sent
   is the one *Apply* writes: the edited defaults, and no explicit rules of the dialog's kind.
   When the template has such rules, the dialog says that *Apply* removes them.
3. **Apply** is one `patchTemplate` with two `add` operations (the defaults and an empty rule
   list of that kind); the dialog closes. The dialog of a group has no save into a preset (saving
   a group is *Save as preset*), and it closes when the group is left (another file opened, the
   group closed), as a job's does.
4. **The naming editor in a group** patches only the naming members that changed
   (`/output/naming/template`, …), never the path: the server names each file, and a whole
   `/output/naming` in a file's override would set every naming field for that file (and show
   the dot on all of them). No stale-path offer in a group. A file without a name source of its
   own shows the group template's (`naming.name_source`). In scope `group` the naming mode, the
   folder buttons and the parsed-name fields are replaced by one line that says they are per
   file and names *This file only*.
5. **The Output card in a group** changes the container only (no path and no extension request):
   the resolution names each file with the container's extension.
6. **The track lists**: *Defaults…* opens the group target; *Reload from preset rules* and
   *Add external subtitle…* stay disabled in a group, each with a tooltip saying why (a wrapper
   carries it, since not every browser sends pointer events to a disabled button). In scope
   `file`, *Add track* and *Add all* are disabled with a tooltip, the drag handles are not shown,
   and a line under the actions points to the matrix.

**Checked in a browser** (headless Chromium, light and dark, a real server with the pinned FFmpeg
and `anime-s01`, *Edit group* and the scope switch through B's banner): in scope `file` a toggle
of *Align A/V start* sets `/job/output/align_av_start` and shows the dot; from the keyboard
(Shift+Tab to the dot, Enter, arrow, Enter) *Reset to group* empties the override, the focus is
on the toggle, Ctrl+Z brings the override back and Ctrl+Shift+Z drops it again; *Apply to whole
group* sets the template's value (every matrix row takes it), empties the override, and one
undo brings both back; no dot in scope `group` or for a job; the group's *Defaults…* shows 12
preview tables (E01–E12), *Apply to the group* empties `audio_rules`, the shown job's tracks
follow the defaults, and one undo brings the rules back; the naming template and name source edit
the template and every row's name; the container changes the template and the extension. No
page error in any run.

**Found and handed to the lead**: a naming edit derived on a template without naming set
`same_as_source` and moved every output next to its source (fixed by the lead in 8e4d2ff; the
check after the fix keeps the outputs in the output root).

**Not built**: a disabled state for the track rows' move and remove buttons in scope `file`
(they are `TrackRowFrame`'s, not task D's; the store refuses those edits with its toast, and the
line under the actions says why); the preview's per-file issue lists.

## Task E — F-17 flow 2

Built: `frontend/e2e/flow2-season-group.spec.ts`, `readSettings` and `changeSettings` in
`e2e/support/app.ts`, and one fixture more for the servers in `e2e/support/servers.ts`:
`--fixtures multitrack,Anime.Show.S01.BluRay.x264-GRP`.

The flow: Settings → Output's *Word separator* set to *Space* (checked through
`GET /api/settings`); the panel's *Open folder…* → the file browser → a click on
`Anime.Show.S01.BluRay.x264-GRP` (the crumb shows it) → *Choose this folder*; the tree has one
top-level item, the group `Anime Show S01` with `12 files`, members E01–E12 in order, E05 and
E11 near, E05's difference `1 extra track (eng AC-3 2.0 "Commentary")`; *Edit group* → the
banner `Editing group "Anime Show S01" (12 files) — showing E01`; Audio: output track 1 encoder
*Opus*, mixdown *5.1*, bitrate *448 kb/s*, name `Japanese 5.1`; track 2 *AC-3*, *5.1*,
*640 kb/s*, `English 5.1`; Subtitles: track 2 named `Full subtitles`; the banner's *Check group*
→ the matrix dialog: rows E01–E12, row marks ✓ except E05 ⚠ and E11 ✗, E11's A2 cell ✗ and S1
cell ≈; E11's row mark → *Make the rule optional* → E11's A2 cell – and the row marks ✓ except
E05 and E11 ⚠; the dialog closed; Summary → the Output card's *Template*
`{name} - S{season:02}E{episode:02}< - {sub_title}>` → its preview
`Anime Show - S01E01 - Pilot.mkv`; the banner's *Add group to queue* → `Queued 12 jobs`; then
`GET /api/queue`: the 12 new jobs by position are named `Anime Show - S01E01 - Pilot.mkv` …
`Anime Show - S01E12 - Homecoming.mkv`, and each has audio `libopus 5.1 448 "Japanese 5.1"`,
`ac3 5.1 640 "English 5.1"` (E11: the first only).

### Choices where the plan and the brief leave one

1. **The folder is opened with the panel's *Open folder…***, not `Ctrl+O`: `Ctrl+O` opens files,
   and choosing twelve files would test the file picker's multi-select, not "open a season
   folder".
2. **The viewport is 1600×1200** for this flow only, so the matrix's virtual scroller renders
   all twelve rows (60 px each) and every row mark is checked at once. The matrix is not
   scrolled.
3. **The word separator is set through the Settings view** (as a user does before *Edit group*)
   and given back through `PUT /api/settings` in an `afterEach`, so a failed flow 2 does not
   change the names of the tests after it. The queue is given back by the existing `ownQueue`
   fixture; the flow does not encode the jobs.
4. **The derive is checked at the server.** Besides the names, the queued jobs' audio tracks
   are compared for all twelve files, so an edit that does not reach the template fails at the
   queue even if the page shows it. The subtitle edit is a name (E01's flags are the example's
   already, Task A); its derive is what makes the S1 and S2 columns explicit rules.
5. **Rows and cells are found by the screens' own hooks**: the tree's `aria-level`,
   `data-group`, `data-match` and `data-field="difference"`; the matrix's `.matrix__label`,
   `.matrix__mark` and `data-cell="audio:1"` / `"subtitle:0"`; the Output card's
   `data-card="output"` and `naming-result`. Buttons and fields by their role and name. No hook
   was missing.
6. Only the S01 folder is a fixture of the servers: flow 2 does not open S02.

### Checked against the real server (2026-11-01, pinned FFmpeg, headless Chromium and Firefox)

With the default preset and the separator *Space*, the matrix's names before the template are
`Anime Show S01E01 Pilot.mkv` (the settings' episode template `{main_title}`). E11's A2 cell is
`✗ none` "no track matches", its S1 cell `≈ #2` "matched without title"; after the fix A2 is
`– none` "no track matches: skipped (the rule is optional)". E05's subtitles are `#4` and `#5`
(its commentary is `#3`). The Output card's preview of E01 shows the template's name at once;
the queued names are the server's resolution of every file. Opening the folder opens E01 as one
job (the slim banner "In group …" with *Edit group*). Screenshots (light Chromium, dark Firefox)
of the panel, the matrix before and after the fix and the queued state show what the checks
read; the matrix's columns, marks and messages are readable in both themes.

### Mutations

Each made once in `src/`, `dist/` rebuilt, flow 2 run in Chromium and Firefox against a server
started like `npm run e2e`'s, then the code restored and touched:

| Mutation | Result |
|----------|--------|
| `panelItems` never forms a group (`open.length < 99`): the folder shows as 12 single files | failed: 12 top-level tree items, not 1 |
| the derive drops the `audio` section (`sections.filter(s => s !== 'audio')`) | failed: A2's drop-downs close under the click when the shown job snaps back to the template (test timeout at A2's mixdown) |
| `applyRowFix` skips a template fix (`return` before `applyFix`) | failed: E11's A2 cell `✗`, expected `–` |
| `useQueueGroup` queues the rows reversed | failed: the queued names E12 … E01 |
| a naming edit derives no `naming` section (`group.ts`) | failed at the queue: all 12 names differ from the template's (the Output card's preview of E01 showed the template's name, so only the queue check catches it) |

### Runs and clean-up

`npm run e2e` (flows 1, 2 and 3 and the 7 layout checks in each browser): 20 passed, 34.6 s,
then 20 passed, 35.3 s. After a forced failure (E11's row mark expected ✓ after the fix: 2
failed at that line, 18 passed, the tests after flow 2 unaffected) and after SIGINT to the
process group of `npm run e2e` 3 s into flow 2 (2 interrupted, 16 did not run, npm exit 130):
no process on 8750 or 8751 and no e2e home (`/tmp/reframe-dev-*` whose output root holds
`chapters.mkv`) left. Other agents' servers (8782, 8790) and their `/tmp/reframe-dev-*` folders
were running at the same time and were not touched.

Not built: a check of E05's commentary not being selected (04 §Example step 3) beyond its
S1 / S2 columns; the matrix's candidate picker, *Problems only* and the naming column's edits
(task C's checks); encoding the queued jobs.

## Review, 2026-11-01

### Fix round — FS (core and server)

Three findings of review R1, each with a test that failed before the fix (C-12, S-2; 0040 §4,
§5, §6; items 1 and 2 above). No model or route contract changed (`schema.d.ts` is the same).

- **R1-1 (blocker): a derive from a file that lacks a rule's track kept only that file's
  rules.** With E11 shown (no dub), one edit of A1 derived a template with one audio rule, so
  every episode lost its dub. `derive_template` now keeps each base rule that takes no track in
  the job's source (the rule engine's `match_rules` on the base's rules: no track taken, that
  is `missing` or `skipped`), unchanged (selector, settings, metadata, `required`,
  `multiple`), inserted at its index in the base (at the end when the derived list is
  shorter). The derived rules of the job's tracks are as before (with `_kept_required`). A base
  rule that takes a track the job dropped is not kept: that removal is the edit. Tests
  (`test_derive.py`): `test_a_rule_that_takes_no_track_in_the_shown_file_is_kept` (04's
  template with A2 optional, E11's job with A1 at 384 kb/s → 2 rules, A2 unchanged and
  optional, 2 audio tracks in E01), `test_a_subtitle_rule_that_takes_no_track_keeps_its_place`
  (an optional German rule between S1 and S2 stays at index 1),
  `test_a_removed_track_removes_its_rule`.
  **Choice:** a base rule with `languages: []` (the rule `derive_template` writes for a job
  without tracks of that kind; it takes no track in any file) is not kept, and that rule is
  added only when the merged list is empty. Otherwise a file with tracks derived on such a
  template kept a stale "A1 no track" column before its real rule, and a file without tracks
  derived again would add a second one. Test: `test_a_job_without_tracks_of_a_kind` (derived
  again: one rule; a track added: its rule alone).
- **R1-6 (major): a per-file output path was named over.** A file's override `replace
  /job/output/path` (the matrix fix "Save as … (1).mkv" of `output.renamed` /
  `batch.output_exists`, or a folder chosen for one file) was applied, then naming replaced the
  path. A resolved job has no output path, so the batch service now keeps a path that the job
  has after its override: naming still runs for the row's name fields (`Resolution.naming`),
  its notes about the path it gave are dropped. Every check still applies, in the same order:
  the server's jail on the patched job (before naming), validation, the batch name checks on
  the kept path, and the route's output-folder check. In `resolve_batch` a kept path is not a
  planned output of the preset: a file whose override names another file of the batch does not
  make that file "already encoded" (it stays in its group) and gets `batch.output_is_source`.
  Tests (`test_batch_service.py`): `test_an_output_path_set_by_a_files_override_is_kept` (the
  real `output.renamed` fix as E01's override → the `(1)` path, no `batch.output_exists`, row
  `ok`), `test_output_paths_set_by_overrides_are_checked_in_the_batch` (`resolve` and
  `resolve_batch`: two files on one path → both `batch.name_collision`; a path that is E01 →
  `batch.output_is_source`, E01 not left out); route (`reframe-server/tests/test_batch.py`):
  `test_an_output_path_of_a_files_override` (both routes, web mode: a path in the output root
  is kept without `output.folder_required`; a path outside the roots is a 403
  `path.outside_roots`, as before).
- **R1-9 (minor): the naming fallback froze Settings → Output into the template.**
  `BatchService.derive` fills Settings → Output's naming into a base without naming only when
  the job sets `output.naming.template` or `output.naming.name_source`; otherwise the derived
  template keeps `naming: null` and follows the settings. Test: the last line of
  `test_a_naming_edit_on_a_base_without_naming_keeps_the_settings_output_folder`.

Known limit, not fixed:

- **R1-12:** the core stops a file's whole job part at the first failed `test` (0040 §5), so a
  stale guard of one track also skips the valid operations of later tracks. Fixing it means a
  `test` that guards only the operations up to the next `test`, a change of 0040 §5's rule
  that the UI's override writer (item 1) is built on, not a fix; the row's
  `batch.override_stale` warning says how many operations were skipped.

Mutations (each made once, then the file restored and touched):

| Mutation | Result |
|----------|--------|
| `_with_absent` keeps no rule (`if False:`) | 2 failed: the audio and subtitle keep tests |
| `_with_absent` also keeps `languages: []` rules | 1 failed: `test_a_job_without_tracks_of_a_kind` |
| `_row` does not keep the override's path | 5 failed: the 3 service tests and the 2 route tests |
| `resolve_batch` counts a kept path as a planned output | 1 failed: the `resolve_batch` case (E01 left out) |
| `derive` fills the settings' naming for every naming derive | 1 failed: the naming test |

### Fix round — FA (editor store)

Fixed in `stores/editor.ts` and `editor/group.ts`. Each blocker and major has a test that failed
on the store of `m7-batch-season` (f1b8a5a) and passes now: unit tests in
`src/stores/editor.group.test.ts` and `src/editor/group.test.ts`, real-server tests (pinned FFmpeg,
`anime-s01`) in `src/stores/editor.group.fixes.server.test.ts`.

- **R1-1 (store part).** An edit of scope `group` (and *Apply to whole group*) that touches the
  audio or the subtitles is refused while the shown file is not an exact member and the template
  has no explicit rules of that kind: a toast names the file and the representative to show
  instead ("E11's tracks do not match the group's" … "Show E01 to edit the group's tracks"), and
  nothing changes. Other sections, and a kind the template has rules for, derive as before (the
  core keeps the base rules, task FS).
- **R1-2.** The `test` before an operation inside an output track checks the **whole track**
  (`/job/audio/<i>`, `/job/subtitles/<i>`), as the file's job has it before the track's first
  operation; later operations on that track keep that guard. This replaces item 1's "test of
  that track's source". Checked on the real server: an unchanged track passes the test (the
  API's JSON of the job is the core's model dump), an override survives a group change of
  another track, and a track added above it makes it stale (`batch.override_stale`), never
  applied to the new track.
- **R1-3.** A hand pick or *No track* comes after `test /<kind>_rules/<r>/selector` with the
  selector as the template has it when the pick is made (a new pick takes the newest selector).
  On the real server the pick stays when a group edit derives the same rule again, and is stale
  when the rules are moved (the Japanese rule never takes the dub's pick).
- **R1-4.** `resolveNow()` flushes the pending edits and waits until none is on its way (a field's
  edit that lands starts its derive, which is sent at once too), then waits for the derive queue,
  then resolves. A pending edit that failed rejects with an `ApiError` (status 0, code
  `edit.failed`, title `editor.group.editFailed`, detail the edit's failure). Its
  `batch/resolve-run` goes through `apiQuiet` (the lead's addition): no toast, it rejects with the
  `ApiError` and sets `matrixError`.
- **R1-5.** Each kept state remembers its group's representative and member paths. When the
  grouping changes, a state whose id is gone moves to the group that holds its representative,
  else the one with most of its members, if that group has no state of its own; the edited
  target's `groupId` follows at once (a synchronous watcher, so the group never looks gone), and
  the matrix is asked again. With no such group the state stays under its old id and the editor
  closes as before.
- **R1-7.** An edit of scope `group` clears the steps to redo at once; `redo` with nothing to redo
  no longer drops a waiting edit.
- **R1-8 and the simplification.** One derive queue: the debounced edits (after their timer),
  `mergeIntoGroup`, *Apply to whole group* and `patchTemplate` run one after the other in the
  order asked for, all through `deriveInto`. `patchTemplate` returns a promise: with nothing on
  its way it applies at once (a `PatchError` is thrown at once, as before), else it waits in the
  queue (the promise rejects with it). A derive is derived again only when the template changed
  while it was on its way (an undo during a merge), not on an override change.
- **R1-14.** A preset whose template equals the group's (*Save as preset* then that preset) only
  sets `presetId`: no undo step.
- **R2-1 (store part).** `matrixError` (the problem's detail, else its title; for `source.stale`
  the text `editor.group.sourceStale`, since that detail is for developers) is set by a failed
  `batch/resolve-run`, `null` after an answer and when the group is left; the last `resolution`
  stays. `retryMatrix()` asks again at once. A failure is no toast.

**Changed in an existing test:** the real-server test's "a scope-`file` edit survives a template
change" now changes another track (A2's mixdown); a change of the overridden track itself makes
the override stale (R1-2).

**Not built:** a stale track override taken up again by a new edit of that track. A later edit of
a track whose guard failed keeps the stale guard, so it is stale too, until *Reset to group*
removes the track's operations. Telling a stale track from an applied one in the store needs the
server's stale issues or a local replay of the override, and a replay can disagree with the
server's normalised job; for the lead to decide. Also not built: R1's optional simplification of
the target copying the state; deleting a kept state that has no group any more.

**Mutations** (each made once, the tests run, the code restored and touched): 24 on the unit tests
(the near-member check and its kind check; the guard path back to the source; a pick without its
guard; `ordered` not grouping rule guards; `resolveNow` not waiting, ignoring a failure, or not
flushing a landed edit's derive; a gone state not following, the target keeping the old id, the
first group instead of the most members, no matrix for the same state; `source.stale` shown raw;
no redo clearing; `patchTemplate` not waiting; a saved preset as a step; `matrixError` not set,
not cleared after an answer or on leaving; `retryMatrix` doing nothing; `api` instead of
`apiQuiet`; a dropped derive committing; no re-derive; `endRun` ignored): each failed at least one
test. On the real-server test: the source guard back and a pick without guard each fail their
test.

### Fix round — FU2 (panel, banner, cards)

Fixed, each with a test that fails before the fix (mutation-checked):

- **R2-3** The naming editor's *Name from* and *Name source* carry `output.naming.mode` and
  `output.naming.name_source`, so a scope-`file` override of them shows its dot. The audio *Rate
  control* carries the path of the rate member it **hides** (`bitrate` in quality mode, `quality`
  in bitrate mode): that member has no field of its own, so an override of it was invisible
  (seen on the real server: after *Reset to group* on the quality, the file kept `quality` while
  its bitrate came back from the group, and only the rate mode's dot shows it). The shown member
  keeps its own field and dot. `Field` takes one path, so a rate-mode switch (two members) is
  reset in two steps, one per member. The other `Field`s without a path stay so: the
  `NamingOptionsEditor` fields (Settings → Output and the preset editor edit `NamingOptions`, not
  a job: no override reaches them), the defaults dialog's codec-rule fields
  (`CodecRuleExtras`, issues given through `issues`; they edit a template's defaults), and the
  fields outside the editor (preset name dialog, settings sections, login, *When done*).
- **R1-11** In scope `group` the naming editor offers no *Use the preset's template* and no
  *As the naming options say* once the group has its own name source: the derive keeps the
  template's naming when the job's member is `null` (`derive._naming`), so both did nothing. The
  name source still shows *As the naming options say* while the template has no naming (its
  current value). A line under the name source says where the group's naming is set ("they start
  from the preset's naming options, else Settings → Output, and are changed here"). Scope `file`
  keeps both (a file's override can go back to the group's).
- **R2-8** The reasons of the disabled *Reload from preset rules* and *Add external subtitle…*
  in a group are visible lines under the actions, each named by its button's
  `aria-describedby`; *Add track* and *Add all* in scope `file` point to the file-scope line the
  same way. Each control has one tooltip with one text (on the wrapper, as before).
- **L3** In scope `file` the track rows' move and remove buttons are disabled; a hidden line
  with the reason is their `aria-describedby`, and the buttons' wrapper has it as a tooltip (the
  list's visible file-scope line says it too).
- **R2-9** The group treeitem is named by its name and lines (`aria-labelledby`); its buttons and
  members are no longer part of its name.
- **R2-13** The tree is one column no wider than the panel (`minmax(0, 1fr)`): a long group name
  is cut with an ellipsis (full text in `title`), the buttons stay. Measured with a 3-file group
  "A Very Long Series Title With Many Words That Keeps Going S03": row 521 px in a 263 px tree
  without the rule, 263 px with it.
- **R2-14** The panel and the banner call `queueGroup` directly.
- **R2-5** The banner's *Add group to queue* is busy (`aria-busy`, a spinner), not disabled:
  the focus stays on it after a queue without errors, and the error dialog can give it back;
  `useQueueGroup` refuses a second click.
- **R2-12** Group names in curly quotes in `group.json` (banner, slim line, *Apply to group*
  title and toast, the saved-preset toast). Flow 2's expected banner text
  (`e2e/flow2-season-group.spec.ts`, the lead's file) changes to
  `Editing group “Anime Show S01” (12 files) — showing E01`.
- **L1** (F-12) A preset with explicit `audio_rules` / `subtitle_rules` says "Chosen by the
  preset's N track rules" for that kind, and leaves out the defaults' encoding, passthru or
  burn-in line, which do not apply to it (`reframe.batch.rules`: explicit rules take precedence
  over the defaults of their kind).
- **R2-1** (the banner's part) While a group is edited and `editor.matrixError` is set, the
  banner shows "The group could not be checked: …" (`role="alert"`) with *Try again*
  (`editor.retryMatrix()`). Found in the browser check and fixed: once an answer comes, the line
  leaves with the focused *Try again*, so the focus goes on to *Check group*.

Checked headless against `scripts/dev-server.py` (pinned FFmpeg, `anime-s01`, a 3-file group
with a long name made in the temp media root), after FA's merge, Chromium light and dark (the
panel and banner checks also Firefox dark), screenshots read: the long group name cut, the row
263 px, its buttons in view; the treeitem's name "A Very Long … S03 3 files · standard match";
the banner `Editing group “Anime Show S01” (12 files) — showing E01`; *Add group to queue* from
the keyboard: `Queued 12 jobs`, the focus still on the button; in scope `group` the name source
loses *As the naming options say* once the group has one, no template reset, the line says where
the naming is set; in scope `file` the dots on *Name from*, *File name* and *Name source*,
*Reset to group* from the keyboard on *Name source* (dot gone, the group's value back); an MP3
track switched to *Quality* in scope `file`: dots on *Rate control* and *Quality*, *Reset to
group* on the rate mode leaves the quality override, still marked at the rate mode; move and
remove disabled with their description in scope `file`, enabled in scope `group`; the
subtitles' two reason lines named by *Reload from preset rules* and *Add external subtitle…*;
`batch/resolve-run` answered with 503 by the test's interception: the error line, *Try again*
keeps it while it fails and drops it once the server answers (focus on *Check group*); a saved
group preset in the presets view: "Audio tracks: Chosen by the preset's 2 track rules", no
encoding line. No page error.

Not built: a two-member reset for the rate mode (`Field` has one path, and `components/base` is
not this task's); the reason lines are shown in a group whether or not the user looks for the
buttons (one line each, no disclosure).

### Fix round — FU1 (matrix and queueing)

Fixed, each with a test (every test mutation-checked; R2-1's tests fail on the dialog before the
fix):

- **R2-1** (the matrix's part) While `editor.matrixError` is set, the matrix dialog shows "The
  matrix could not be updated: …" (`role="alert"`) with *Try again* (`editor.retryMatrix()`),
  and says what the shown matrix is: "out of date" (the last `resolution`, dimmed and `inert`,
  so no pick or fix is made on the columns of an older template) or "There is no matrix yet". A
  focus left in the matrix moves to *Try again*. `Ctrl+Z` still works there.
- **R2-2** `resolveNow()` is quiet (the contract addition the lead gave FA): `useQueueGroup`
  shows its failure. `source.stale` → "N file(s) of the group changed since they were opened",
  "Remove it from the sources and open it again:" and the file names (the group's members that
  `GET /api/sources` lists without a source); `edit.failed` → no toast (the failed derive showed
  one); any other problem → its title and detail, as the API toast did.
- **R2-4** `useShortcuts` lets `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` through while the top modal
  is the matrix dialog or its popover, outside text fields; every other shortcut stays blocked
  there, and a dialog over the matrix blocks undo too.
- **R2-5**, **R2-15** *Open matrix* is the error dialog's default (primary, autofocus). After
  *Cancel*, Escape and *Queue the valid files* the focus goes back to the element that had it
  when `queueGroup` started (kept before the dialog opens); after *Open matrix* the matrix
  focuses the first file with errors.
- **R2-6** PrimeVue 4.5.5's `Dialog` reads no locale text for its maximize button (only
  `aria.close`), so `primevueLocale.ts` is unchanged: `MatrixDialog` names the button through
  `maximizeButtonProps` ("Maximize" / "Restore size", following the `maximize` / `unmaximize`
  events; the default `secondary text rounded` look kept). First focus: the first shown row's
  mark; without a matrix yet, the *Problems only* box.
- **R2-7** The popover is `aria-labelledby` the title of the picker, the row's issues or the
  name fields (a `titleId` prop).
- **R2-10** A cell's message has its full text as `title`; the picker shows the message under
  its title.
- **R2-11** The `role="status"` region stays in the DOM and changes its text; the V cell's label
  ends with the video size.
- **R2-12** Curly quotes in `matrix.json`; **R2-14** `MatrixDialog` uses `editor.resolution`.
- **R1-10** One toast says what the queue did: "Queued 12 jobs", or "12 jobs added to the queue;
  10 of them failed" with the first three files and reasons and "… and N more failed jobs: the
  queue lists them" (the whole list of a second *Add group to queue* ran off the screen). Rows
  with `batch.override_stale` add "N file(s) are queued without part of their per-file changes …"
  to that toast (a warning), and the error dialog says how many of the valid files lose part of
  theirs.

Checked headless against `scripts/dev-server.py` (pinned FFmpeg, `anime-s01`, `anime-s02`) after
FA's and FS's merge, Chromium and Firefox, each light and dark (32 checks per run, all pass, no
page error; a member file broken in the temp media root by renaming it aside and writing
garbage, then put back): the title `Check group “Anime Show S01”`; the maximize button named; the
first focus on E01's mark; the live region present and empty; the V label `V, E01: Exact match,
320×180`; E11's A2 message as `title` and in its picker; the three popovers named
`A2 eng DTS-HD MA→AC-3 5.1 in E11`, `E11`, `Name fields of E11`; E03's A2 *No track* from the
keyboard, `Ctrl+Z` in the matrix gives `#2` back, `Ctrl+Shift+Z` the pick again, the matrix stays
open; a changed E02 and a group edit: the line "The matrix could not be updated: A file of the
group changed on disk since it was opened: …" (FA's text), the matrix dimmed and inert, the focus
on *Try again*, `Ctrl+Z` takes the edit back; *Add group to queue* toasts the changed file by name
and no developer text; with the file back, *Try again* clears the line; a group whose first
resolve fails shows "There is no matrix yet" with the focus on *Problems only*. The queue flow
from the banner by keyboard: *Open matrix* focused first; after Escape, *Cancel* and *Queue the
valid files* the focus is on the banner's *Add group to queue*; `Queued 11 jobs`; a second time
"11 jobs added to the queue; 11 of them failed" (three files, "… and 8 more"); *Open matrix*
focuses E11's mark; a scope-`file` name on E01's first output track, then the group's two audio
tracks swapped: E01's row `batch.override_stale`, the dialog says "1 of the valid files loses
part of its per-file changes". Screenshots read: the failure line, dimmed matrix and the
text-styled maximize button in light and dark; the error dialog with *Open matrix* primary; the
capped toast inside the window.

Not built: a different wording of *Add all*'s toast (the same "not added" for jobs added as
failed; not this finding's); a per-member check of which file changed beyond `GET /api/sources`.
