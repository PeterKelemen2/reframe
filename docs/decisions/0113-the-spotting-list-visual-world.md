# 0113 — The Spotting List visual world

- Status: accepted
- Date: 2026-11-25
- Steps: F-1, F-3, F-7

## Context

F-1 built the design system on PrimeVue's Aura preset with an indigo primary colour and the
system font. A design critique of the Workspace (2026-11-25, 25/40) found the look
category-interchangeable: an admin panel with one accent, flat type (headings 14–18 px against
16 px body, 1.14:1 steps), every value underlined or a chip, a side-stripe for the selected row.
The owner chose an own identity for the whole app, kept PrimeVue (restyled), and ruled out a
film-studio costume, less density, moving the HandBrake layout, and a dark-only or neon look.
Light and dark are designed as equals. A direction round picked the "Spotting List": subtitle
spotting lists and dubbing rythmo bands, where each voice has its colour.

## Decision

- **Palettes.** Light: cool white ground, white panels, carbon ink text, and an ink-filled
  primary action (`--p-primary-color` is ink, not a hue). Dark: blue-black panels, cool white
  text, a paper-light primary action, and the preview column one step darker than the panels
  (`--p-app-booth`). The neutrals and both schemes are in `styles/theme.ts`; every pair is in
  `contrast.test.ts`.
- **Language colours.** Eight slots plus a neutral one for `und` (`--p-language-*`,
  `--rf-lang-*`), with no red or amber family, so red and amber only mean a problem (a test
  checks the hues). `components/base/languageColor.ts` gives the preferred languages from
  Settings (audio, then subtitles, then favourites) the first slots in their order, and any other
  language a slot from a hash of its ISO 639-3 code, so a language keeps its colour across
  sessions and variants share it (`en`, `eng`, `en-GB`). `LanguageChip` draws the mark; the same
  colour marks the language in every track list, the programme strip and the group matrix.
- **Type.** Red Hat Text for the interface and Red Hat Mono for numbers, paths, timecodes and
  code, bundled from Fontsource (OFL-1.1): the app runs offline on a home server and in the
  desktop shell. Headings step up in size (`--rf-text-*` roles); bold is 700.
- **The programme strip.** Under the preview frame, a strip over the whole programme: a time
  ruler, chapter ticks, the range, the sampled frames with the current one marked, and one lane
  per output track in its language colour (a commentary lane paler). On the tabs where the preview
  starts collapsed (Audio, Subtitles, Chapters, Tags; [0112](0112-editor-room-at-1440-px.md)) the
  strip sits at the top of the editor column instead. Subtitle lanes are solid: the subtitle scan
  counts events but records no times, so a lane cannot show where the cues are.

- **The Summary leads with the tracks.** Issues come first only when one is an error (the job
  cannot run); warnings and notes follow the job's facts, at the end. This changes
  [0112](0112-editor-room-at-1440-px.md)'s "Issues first when there are any": the finish review
  found two info notes taking the top 300 px at 1440 px and pushing Tracks below the fold at 1280.
- **Notes are ink, not blue.** The `info` status, info toasts and info messages are ink on a
  neutral tint: a hue there was the one-accent look this world refuses, next to the language
  colours.

- **The editor on the ground.** The tab panels lie on the cool-white ground (blue-black in
  dark), the cards on white panels. Below 1440 px the sources and preview columns narrow
  (17rem and 21rem at most) and the tabs close up, so all eight fit beside the open preview
  at 1280 px; the frame thumbnails stay on one row. The Summary's Tracks card keeps its
  columns down to a 30rem Summary (about 33rem at 1280 px) and wraps each row's cells below it.

## Consequences

- Every screen changes colour and type; behaviour, copy and layout do not.
- Status colours (error red, warning amber) stay apart from the language colours by hue and by
  their icons; info blue and ok green share a hue family with two language colours and are told
  apart by their icons and labels.
- To revisit: event times in the subtitle scan (C-10), so a subtitle lane can show its cues.

## Plan changes

- `06-web-app.md`: Stack (the preset, the fonts) and F-1 (a bullet for this world).
- `03-features.md`: App layout (the programme strip, the language colours).
