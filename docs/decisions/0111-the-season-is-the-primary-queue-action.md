# 0111 — The season is the primary queue action

- Status: accepted
- Date: 2026-11-25
- Steps: F-3, F-5, F-13, C-12

## Context

PRODUCT.md, principle 3: "One episode, the whole season. Batch work is the normal case." A
design review of the Workspace (2026-11-25, the season folder `Anime.Show.S01.BluRay.x264-GRP`,
12 episodes, opened as a group) found that the season was second-class at the moment of commit:

- With E01 open, the status bar's filled *Add to queue* added one episode. *Add group to
  queue* was a text link on the group's row in the sources panel.
- The status bar's *Add all* (all open sources) had the same label as the Audio tab's
  *Add all* (all source tracks).
- About eight queue and group actions were on the screen at once, *Edit group* twice (the
  group's row and the banner's slim line) and *Add group to queue* three times while the group
  was edited (the row, the banner, the status bar).
- *Check group* on a group that was not edited made it the edited group (the matrix is the
  edited group's), with nothing that said so.
- A member's row showed `E01 Anime.Show.S01E…`: the cut file name hid what tells the episodes
  apart.

The plan put *Add group to queue* on the group's row (04 §Grouping, the sketch), *Add all* in
the status bar (03 §App layout) and `Ctrl+Enter` as "add to queue".

## Decision

1. **The status bar owns queueing.** While the shown file belongs to a group (the edited
   group, or a member open as one job), its primary button queues the group: *Add 12 episodes
   to queue* (*Add 3 files to queue* when a file has no episode number), the count of the
   group's open files. `Ctrl+Enter` does the same, and the button's tooltip names the shortcut.
   Beside it, *Only E01* (*Only this file*) adds the shown file alone: a member open as one job
   as before; in the edited group, that file resolved alone with its crop detected, as the group
   would queue it. Outside a group the button stays *Add to queue*.
2. **A member's own changes are not dropped quietly.** Queueing the group uses the group's
   settings. When the member open as one job has edits that no *Apply to group…* took, the
   status bar asks first: *Apply to group…*, *Queue without them* or *Cancel*.
3. ***Add all* is *Add all open files*.**
4. **One owner per group action.** The group's row has *Edit group* (while it is not the
   edited group), and nothing while it is edited. The banner of the edited group has *Check
   group*, *Save as preset* and *Close group*; its slim line (a member open as one job) has
   *Apply to group…*. The status bar queues. The row's context menu keeps every action for the
   keyboard: *Edit group* or (edited) *Check group*, and *Add group to queue*.
5. ***Check group* is offered only for the edited group.** The matrix shows the edited
   group's template and its overrides, and a pick in it is an override, so a read-only matrix of
   a group that is not edited would show a template the user is not editing. *Check group* no
   longer edits a group as a side effect; *Edit group* then *Check group* is the way.
   Queueing a group still makes it the edited group: the banner shows what was queued, and the
   matrix is at hand when files have errors. *Close group* goes back to one file.
6. **A member's row leads with its episode.** `E02 · Departure`: the episode label, then the
   episode title parsed from the file name (`GroupMember.sub_title`, the `{sub_title}` naming
   field); the label alone when the name has no title. The full path is the row's tooltip.

## Consequences

- The season takes one click (or `Ctrl+Enter`) from any of its episodes, and the button says
  how many jobs it adds.
- No capability is removed: a group can still be edited, checked and queued from its context
  menu while another file is open, and one episode can still be queued alone.
- *Only E01* in the edited group resolves that file without the others, so the batch's name
  collision check between files does not run for it.
- The question in (2) compares the open job with the last job that *Apply to group…* or a
  paste took; an apply of some sections only counts as taken.
- `GroupMember` gains `sub_title` (an output-only field: no persisted document holds a
  grouping).

## Plan changes

- `03-features.md` §App layout: the status bar sketch and the queue actions, `Ctrl+Enter`.
- `04-batch-mode.md` §Grouping: the group row's sketch and labels; §Resolution matrix and
  §Queueing a group: where *Check group* and *Add group to queue* are.
- `06-web-app.md` §F-13: the queue actions' owners.
