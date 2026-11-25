---
version: 1
slug: "frontend-src-views-workspaceview-vue"
primary_target: "frontend/src/views/WorkspaceView.vue"
related_targets: ["frontend/src/styles/tokens.css","frontend/src/styles/theme.ts"]
---

# Workspace (lead surface of the app-wide Spotting List world)

Mode: Operate. Audience: the owner (expert, encodes whole seasons from MKV remuxes, web UI on a home server from another computer), later HandBrake users without the docs. Job: set up one episode, see exactly what will be written, queue the season, leave. Light and dark are designed as equals (day or evening use).

Scope: app-wide (tokens, PrimeVue preset, shell, every Workspace tab, Queue, Presets, Activity, Settings, dialogs; the Tauri app inherits). PrimeVue 4 stays, restyled. Kept: the HandBrake topology (rail | sources | editor tabs | preview | status bar), all copy and behaviour, WCAG AA in both themes, compact and comfortable density. Anti-goals: film-studio costume (reels, sprockets, clapperboards, typewriter paper, NLE timeline chrome), less density, dark-only or neon, left side-stripe selection, underlined values.

Chosen sketches: `.impeccable/mocks/decision/assigned.html` (picked), refined as `spotting-light.html` and `spotting-dark.html` (no red-family language colour; solid subtitle lanes).

Decisions taken: subtitle lanes are solid with the cue count shown in Tracks (the core has counts, not event times; event times are a later C-10 step). On tabs where the preview is collapsed (Audio, Subtitles, Chapters, Tags) the strip docks at the top of the editor column without the frame. Language colours: preferred languages from Settings take the first slots of an 8-colour pencil set with no red or amber family; other languages follow in a stable order; `und` is neutral grey. Fonts: Red Hat Text and Red Hat Mono, bundled locally (the app runs offline).

## Direction contract

THESIS: Every track is a lane in one programme, coloured by its language the way a dubbing script colours its voices. It refuses the category default: a grey admin panel with one indigo accent, where every value is a link or a chip.

OWN-WORLD: Light: cool white ground, white panels, carbon ink text and an ink-filled primary button. Dark: deep blue-black panels, cool white text, the primary button turns paper-light; the preview column is a booth, one step darker. Coloured-pencil language colours (viridian, cobalt, violet, teal, plum, moss, sepia, slate), one per language everywhere; the picture is the only full-colour thing. Red Hat Text for the UI, Red Hat Mono for every number, path and timecode; a real heading scale; full-row selection; hairline panels.

STORY: The visitor sees, before queueing, every output track as a coloured lane over the programme with its range and chapters, reads the Summary as a receipt of what will be written, and queues the whole season from the status bar's primary action.

FIRST VIEWPORT: 1440×900, Summary. Rail; sources with episode-first rows (E02 · Proshai, Livushka) and full-row selection; editor tabs over a Tracks card that dominates (language mark, codec, bitrate, role per row), then Picture, Output, Issues; preview column with the frame and directly under it the rythmo strip (ruler, chapter ticks, range, sampled-frame dots with the current one marked, one lane per output track, legend); status bar with the identity line and the ink "Add 13 episodes to queue".

FORM: Spotting List (subtitle spotting lists and dubbing rythmo bands), candidate 7 of 7 on the grounded list; seed:14494c431b3be28b. Signature interaction: the rythmo strip; a lane focuses its track, a frame dot moves the preview, keyboard reachable with a text alternative.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
