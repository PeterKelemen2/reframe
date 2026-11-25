# 0112 — Room for the editor at 1440 px: the preview follows the tab, the Summary leads with the output

- Status: accepted
- Date: 2026-11-25
- Steps: F-3, F-6, F-7, F-10

## Context

The main surface is the web UI on a home server, opened from a browser on another computer
(`PRODUCT.md`). A browser window of 1440×900 is a likely size. The design critique of the
Workspace (`.impeccable/critique/2026-11-25T19-40-15Z__frontend-src-views-workspaceview-vue.md`,
issue P2) measured it in the real app:

- The columns `minmax(14rem, 18rem) minmax(0, 1fr) minmax(16rem, 26rem)` leave 648 px for the
  editor. The tab strip needs 776 px, so Chapters and Tags are behind the overflow arrow.
- The audio source table needs about 780 px. It cuts off Measure and the whole "Role & flags"
  column, which the plan puts last.
- The preview panel (26rem) stays open on Audio, Subtitles, Chapters and Tags. Nothing in it
  changes on those tabs.
- The Summary's Source card shows the source frame a second time, next to the preview panel.
  The Tracks card, the most important one, comes after the Output card's naming form.
- The Output tracks toolbar wraps to two rows, with a disabled **Add all** next to **Add track**.

The plan says that the preview panel "can be collapsed or detached" and "follows the active
tab" (03 §App layout). It lists a thumbnail in the Source card and gives the Summary cards in
the order Source, Output, Picture pipeline, Video, Tracks, Issues, Estimate (03 §Summary). It
puts "Role & flags" last in both source tables, and **Add all** in the output track buttons
(03 §Audio, §Subtitles).

## Decision

1. **The preview panel follows the kind of tab.** On the tabs that work on the picture
   (Summary, Dimensions, Filters, Video) it starts open. On Audio, Subtitles, Chapters and Tags
   it starts collapsed to a 3rem strip with the label "Preview". The user's choice is kept for
   each of the two kinds, in the browser (`reframe.workspace.previewHidden` for picture tabs,
   as before, and `reframe.workspace.previewHiddenElsewhere`). It is UI state, not a setting:
   no persisted document changes.
2. **The Summary is a receipt of what the job writes**: Tracks, Picture pipeline, Video, Job
   type, Output, Estimate, then the Source card with the source's facts. The Issues card is
   first when there are issues and last when there are none. The Source card has no thumbnail:
   the preview panel beside the Summary shows the frames.
3. **The source track tables put the roles before the lower-priority columns**: audio is
   `# · Lang · Name · Codec · Channels · Role & flags · Rate / depth · Bitrate`, subtitles are
   `# · Lang · Name · Format · Type · Role & flags · Events`. A table narrower than 48rem leaves
   out Rate / depth, Bitrate and Events. The row's details show them, with the Measure and Count
   controls.
4. **Add all is the last item of the Add track menu**: "Every source track not added yet (N)",
   disabled when N is 0. The toolbar keeps one row.
5. **The tabs have 0.5rem side padding at every width**, so all eight fit beside the open
   preview at 1440 px, and a tab does not move when the next tab opens or closes the preview.

## Consequences

- At 1440×900 the editor has 648 px on the picture tabs and about 1016 px on the other tabs.
  All eight tabs are in sight on every tab. The audio table shows every column with the preview
  collapsed, and the main columns without it.
- The first time a user opens Audio, the preview is collapsed. One click opens it, and it stays
  open on the four non-picture tabs.
- The Summary no longer asks the server for a frame (`POST /api/preview/frames`) of its own.
- In a window narrower than about 1420 px, the tabs still need the overflow arrow beside the
  open preview.

## Plan changes

- `docs/plan/03-features.md` §App layout: the preview panel follows the kind of tab.
- `docs/plan/03-features.md` §Summary: no thumbnail in the Source card; the card order.
- `docs/plan/03-features.md` §Audio and §Subtitles: the column order, the narrow table, and
  Add all in the Add track menu.
- `docs/plan/06-web-app.md` F-3, F-6 and F-10: references to this record.
