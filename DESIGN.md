---
name: Reframe
description: A video transcoder where every output track is a coloured lane over one programme.
colors:
  ink: "#1b2330"
  ink-hover: "#2c3442"
  ink-active: "#12161e"
  paper: "#ffffff"
  cool-ground: "#f7f8fa"
  panel-hover: "#eef0f3"
  hairline: "#e3e6eb"
  muted-ink: "#5b6474"
  field-stroke: "#677080"
  selection-tint: "#e8ecf2"
  selection-tint-focus: "#dde2ea"
  paper-light: "#e4e7ec"
  paper-light-hover: "#ffffff"
  paper-light-active: "#b4bbc6"
  blue-black-ground: "#101318"
  blue-black-panel: "#171b22"
  blue-black-panel-hover: "#232934"
  blue-black-hairline: "#343b47"
  booth: "#0d1014"
  muted-paper: "#98a1b0"
  field-stroke-dark: "#6e7787"
  selection-tint-dark: "#252c38"
  selection-tint-dark-focus: "#2e3644"
  lang-1-viridian: "#1f8a6b"
  lang-2-cobalt: "#2e5bba"
  lang-3-violet: "#7a4fb5"
  lang-4-teal: "#0f7c8c"
  lang-5-plum: "#a23c8c"
  lang-6-moss: "#5e7d1e"
  lang-7-slate: "#4f6b8a"
  lang-8-ultramarine: "#4f4fb0"
  lang-und: "#848d9c"
  lang-1-viridian-dark: "#4db894"
  lang-2-cobalt-dark: "#7a9eea"
  lang-3-violet-dark: "#a98be0"
  lang-4-teal-dark: "#45b5c4"
  lang-5-plum-dark: "#d57ec0"
  lang-6-moss-dark: "#9bbf5a"
  lang-7-slate-dark: "#8fa8c4"
  lang-8-ultramarine-dark: "#9a9cf0"
  lang-und-dark: "#7c8595"
  error: "#b91c1c"
  error-tint: "#fef2f2"
  error-stroke: "#dc2626"
  warn: "#92400e"
  warn-tint: "#fffbeb"
  warn-stroke: "#b45309"
  ok: "#15803d"
  ok-tint: "#f0fdf4"
  error-dark: "#fca5a5"
  error-tint-dark: "#450a0a"
  error-stroke-dark: "#f87171"
  warn-dark: "#fcd34d"
  warn-tint-dark: "#451a03"
  warn-stroke-dark: "#fbbf24"
  ok-dark: "#4ade80"
  ok-tint-dark: "#052e16"
  ok-stroke-dark: "#22c55e"
typography:
  title:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
  heading:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.2
  subheading:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.45
  body-small:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Red Hat Text Variable, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    letterSpacing: "0.06em"
  mono:
    fontFamily: "Red Hat Mono Variable, ui-monospace, SFMono-Regular, Cascadia Mono, Menlo, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    fontFeature: "tnum"
  mono-micro:
    fontFamily: "Red Hat Mono Variable, ui-monospace, SFMono-Regular, Cascadia Mono, Menlo, monospace"
    fontSize: "0.6875rem"
    fontWeight: 400
    lineHeight: 1
rounded:
  mark: "1px"
  sm: "4px"
  md: "6px"
  lg: "8px"
  tray: "10px"
  pill: "999px"
spacing:
  space-1: "0.25rem"
  space-2: "0.5rem"
  space-3: "0.75rem"
  space-4: "1rem"
  space-5: "1.5rem"
  space-6: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-primary-active:
    backgroundColor: "{colors.ink-active}"
  button-primary-dark:
    backgroundColor: "{colors.paper-light}"
    textColor: "{colors.booth}"
    rounded: "{rounded.md}"
  button-primary-dark-hover:
    backgroundColor: "{colors.paper-light-hover}"
  segment-checked:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "0.25rem 0.75rem"
  segment-checked-dark:
    backgroundColor: "{colors.paper-light}"
    textColor: "{colors.booth}"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "0.75rem 1rem 1rem"
  card-dark:
    backgroundColor: "{colors.blue-black-panel}"
    textColor: "{colors.paper-light}"
  row-selected:
    backgroundColor: "{colors.selection-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
  row-selected-dark:
    backgroundColor: "{colors.selection-tint-dark}"
    textColor: "{colors.paper-light}"
  nav-item-active:
    backgroundColor: "{colors.selection-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    typography: "{typography.label}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  role-badge:
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 0.5rem"
    height: "1.25rem"
  language-mark:
    backgroundColor: "{colors.lang-1-viridian}"
    rounded: "{rounded.mark}"
    width: "0.25rem"
    height: "1rem"
  strip-lane:
    rounded: "{rounded.sm}"
    height: "1.5rem"
  strip-time-flag:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    typography: "{typography.mono-micro}"
    padding: "0 0.3125rem"
---

# Design System: Reframe

## Overview

**Creative North Star: "The Spotting List"**

Reframe borrows the working paper of subtitle spotting lists and dubbing rythmo bands, where every voice has its own coloured pencil and every cue sits on a timeline. Each output track is a lane in one programme, coloured by its language; the same colour marks that language in every track list, legend and lane in the app. Everything around the lanes is ink and paper: carbon ink on cool white in light, cool white on blue-black in dark. The picture is the only full-colour thing on the screen.

The system is dense and calm. It keeps the HandBrake-style three-column workspace (sources, editor, preview) and the density of a tool used for whole seasons, and gets its character from a real heading scale, a mono face for everything measured, full-row selection, hairline panels and the language pencils, not from decoration. Light and dark are designed as equals: every colour role has a value in both schemes, and the primary action inverts (ink in light, paper-light in dark) instead of keeping a brand hue.

The world refuses the category default (a grey admin panel with one indigo accent where every value is a link or a chip), a film-studio costume (clapperboards, film perforations, studio props), a neon or glow look, and a dark-only identity.

**Key Characteristics:**
- Ink and paper neutrals; the primary action is ink-filled in light, paper-filled in dark.
- Eight coloured-pencil language slots plus a neutral `und`, one colour per language everywhere.
- Red Hat Text for the interface, Red Hat Mono for every number, path, code and timecode.
- Headings step up in size (20 / 18 / 16 px), all at weight 700.
- Full-row selection tints, joined segment controls, hairline panels on a cool ground.
- The programme strip: ruler, chapters, range, sampled frames and one coloured lane per track.

## Colors

Two neutral scales (Ink for light, Booth for dark) carry the whole interface; hue appears only in the language pencils, in the status tones, and in the picture.

### Primary
- **Carbon Ink** (`ink`): light-scheme text and the primary action's fill; the checked segment, the open tab's 2px rule, the field focus ring and the programme strip's playhead and current frame. Hover deepens one step (`ink-hover`), press one more (`ink-active`).
- **Paper Light** (`paper-light`): the same role in dark. Text, the primary action's fill (with `booth` text on it), the checked segment, focus ring and playhead. Hover goes to pure white (`paper-light-hover`), press drops to `paper-light-active`.

### Secondary: the language pencils
One slot per language, light value first, dark value second. Each is at least 3:1 on its scheme's surfaces (checked by `contrast.test.ts`).

- **Viridian** (`lang-1-viridian` / `lang-1-viridian-dark`)
- **Cobalt** (`lang-2-cobalt` / `lang-2-cobalt-dark`)
- **Violet** (`lang-3-violet` / `lang-3-violet-dark`)
- **Teal** (`lang-4-teal` / `lang-4-teal-dark`)
- **Plum** (`lang-5-plum` / `lang-5-plum-dark`)
- **Moss** (`lang-6-moss` / `lang-6-moss-dark`)
- **Slate** (`lang-7-slate` / `lang-7-slate-dark`)
- **Ultramarine** (`lang-8-ultramarine` / `lang-8-ultramarine-dark`)
- **Undetermined Grey** (`lang-und` / `lang-und-dark`): a track with no language (`und`, or none); its name is set in italic muted text.

A commentary or secondary track draws its language colour at 45% opacity (`--rf-lang-pale: 0.45`). The video track has no language: its mark is ink.

**Slot assignment** (`languageColor.ts`). Variants share one key (`en`, `eng` and `en-GB` are one language; the key is the ISO 639-3 code). The user's preferred languages take slots 1, 2, 3… in order: preferred audio first, then preferred subtitles, then favourites, duplicates dropped, at most eight. Any other language takes a slot from an FNV-1a hash of its key, among the slots the preferred ones left free (all eight when none are free). A language keeps its colour across sessions and screens.

### Tertiary: status tones
Status tones are the only red, amber and green in the app. Text colour / tint / stroke, light then dark:

- **Error** (`error`, `error-tint`, `error-stroke` / `error-dark`, `error-tint-dark`, `error-stroke-dark`): an issue that stops the job; field outline and issue row.
- **Warning** (`warn`, `warn-tint`, `warn-stroke` / `warn-dark`, `warn-tint-dark`, `warn-stroke-dark`): a warning row, field outline, the pending-changes bar in the status bar.
- **OK** (`ok`, `ok-tint` / `ok-dark`, `ok-tint-dark`, `ok-stroke-dark`): a finished or healthy state.
- **Note (info)**: not a hue. Ink on a neutral tint: `ink-hover` text on `panel-hover` with a `field-stroke` border in light; `paper-light` on `blue-black-panel-hover` with `field-stroke-dark` in dark. Info toasts and info messages use the same ink-on-panel treatment.
- **Busy** and **off** are neutral too: ink on a pale ink tint, muted ink on `panel-hover` (dark: paper-light / muted-paper on `blue-black-panel-hover`).

### Neutral
Light (Ink scale) and dark (Booth scale) side by side:

| Role | Light | Dark |
|---|---|---|
| Ground (app background, editor panels) | **Cool Ground** `cool-ground` | **Blue-Black Ground** `blue-black-ground` |
| Panel (cards, rail, status bar, popovers) | **Paper** `paper` | **Blue-Black Panel** `blue-black-panel` |
| Panel hover / quiet fill | `panel-hover` | `blue-black-panel-hover` |
| Hairline (panel and row borders) | `hairline` | `blue-black-hairline` |
| Booth (preview column surround) | `paper` | **Booth** `booth`, a step darker than the panels |
| Text | `ink` | `paper-light` |
| Muted text | **Muted Ink** `muted-ink` | **Muted Paper** `muted-paper` |
| Field stroke (inputs, outlined secondary buttons, switch track) | `field-stroke` | `field-stroke-dark` |
| Selection tint | `selection-tint` (focus `selection-tint-focus`) | `selection-tint-dark` (focus `selection-tint-dark-focus`) |

Text selection is the primary colour at 22% over the content; scrollbars use the scale's 400 step in light (`#9aa3b2`) and 600 in dark (`#4e5664`).

### Named Rules
**The Picture Keeps the Colour Rule.** Chrome is ink and paper. Hue belongs to the language pencils, the status tones and the video frame; no other element carries a brand hue.

**The One Pencil per Language Rule.** A language has one colour on every screen in a session, assigned by `languageSlot`; never colour a language by hand or by its position in a list.

**The Red Means Trouble Rule.** No language slot may sit in the red, orange or amber family; those hues mean an error or a warning. A test checks the slot hues.

**The Ink Note Rule.** Information (`info` issues, toasts, messages) is ink on a neutral tint, never a saturated blue beside the language colours.

## Typography

**Interface Font:** Red Hat Text Variable (with system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, sans-serif)
**Mono Font:** Red Hat Mono Variable (with ui-monospace, SFMono-Regular, Cascadia Mono, Menlo, monospace)

Both are bundled from Fontsource (`@fontsource-variable/red-hat-text`, `@fontsource-variable/red-hat-mono`, OFL-1.1), so the app renders the same offline, on a home server and in the desktop shell.

**Character:** A warm, open humanist sans for words and a matching mono for what is measured or copied: sizes, bitrates, timecodes, paths, episode codes, lane labels. Mono and tabular figures (`font-variant-numeric: tabular-nums` on tables, code and `.rf-mono`) make values line up in columns.

### Hierarchy
- **Title** (700, 1.25rem, 1.2): view titles and the lead card of a tab (the Summary's Tracks).
- **Heading** (700, 1.125rem, 1.2): card headings.
- **Subheading** (700, 1rem, 1.2): a section inside a column, such as the Programme strip's title.
- **Body** (400, 1rem, 1.45): the default text; medium (500) for field labels, tab labels, codec names and the open source row's name.
- **Body small** (400, 0.875rem): track rows, the status bar, field issues, language chips.
- **Label** (500, 0.75rem, 0.06em tracking, uppercase, muted): a group label inside a card or a table's column names (VIDEO, AUDIO · 2, SUBTITLES · 2). It sits over rows, never above a heading.
- **Mono** (400, 0.875rem in rows, 0.75rem in facts and paths, tabular figures): values, paths, episode codes (E01), timecodes.
- **Mono micro** (400, 0.6875rem, 1): the programme strip's ruler labels, lane labels, chapter numbers and playhead time.

Bold is 700, medium is 500, normal is 400; no other weights are in use.

### Named Rules
**The Real Steps Rule.** Headings step up in size, not only in weight, from the 1rem body: 1rem, 1.125rem, 1.25rem, each at 700.

**The Measured Is Mono Rule.** A number, path, timecode or code that a person reads as a value or copies is set in Red Hat Mono with tabular figures. Prose numbers ("5 of 5 source tracks kept") stay in the text face.

## Layout

A one-window shell: a 5rem nav rail on the left, then three columns (sources list, editor tabs, preview), and a status bar along the bottom. Below 1440 px the sources and preview columns narrow (17rem and 21rem at most) and the tabs close up, so all eight editor tabs fit beside the open preview at 1280 px; the frame thumbnails stay on one row. On the tabs where the preview starts collapsed (Audio, Subtitles, Chapters, Tags) the programme strip docks at the top of the editor column.

The editor's tab panels lie on the ground colour; cards sit on it as white (light) or blue-black (dark) panels with a hairline. The rail, the tab strip and the status bar stay on the panel colour.

**Spacing** is a 0.25rem scale multiplied by the density (`--rf-density`): space-1 to space-6 are 4, 8, 12, 16, 24 and 32 px at comfortable density. Cards use space-3 top and space-4 sides and bottom with a space-3 gap; issue rows space-2 by space-3.

**Density** has two settings on `<html data-density>`. Comfortable is the default (density 1). Compact sets the root font size to 87.5% and the density to 0.75, and tightens PrimeVue's form fields (0.3rem by 0.5rem), list options, navigation items, popovers (0.5rem), dialogs (1rem), icon-only buttons (2rem) and table cells (0.375rem by 0.5rem). Every size is in rem, so the browser's font size scales the whole interface.

Field labels sit in a 1.75rem row so that fields side by side start their controls on one line; inline fields use an 8–12rem label column.

## Elevation & Depth

The system is flat. Depth comes from tone and hairlines: ground, then panel, then a 1px hairline around the panel; in dark the preview column (the booth) sits one step darker than the panels. Resting surfaces have no shadows. Shadows appear only on things that float over the page: PrimeVue's popovers, selects and dialogs keep Aura's overlay shadows, and toasts lift with a soft ink shadow.

### Shadow Vocabulary
- **Overlay** (`box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1)`): select panels, popovers.
- **Modal** (`box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)`): dialogs.
- **Toast** (`box-shadow: 0 6px 20px -8px rgb(18 22 30 / 0.28)`): toasts over the workspace.
- **Option focus** (`box-shadow: inset 0 0 0 2px` primary): the option or menu item under the keyboard or pointer, since its tint alone is 1.1:1.

### Named Rules
**The Hairline Rule.** A panel is a fill and a 1px hairline on the ground, nothing more. If it does not float, it has no shadow.

## Shapes

Gently rounded, never soft. Cards, the nav rail's items and the queue table use 8px; fields, buttons, issue rows and segment groups 6px; role badges, track rows, lanes and the playhead flag 4px. A segment group's tray is 10px, concentric with its checked option (6px plus the 4px option padding). Language marks and lane bars are near-square (1px). Pills (999px) are kept for settings echoes (the Summary's "Interlace detection: Default" chips) and variable chips. Dots are round: the frame dots, the override marker on a field.

The recurring silhouette is the **language mark**: a 4px by 16px upright bar in the language colour before the language name, the same shape as a lane seen end-on.

## Components

### Buttons
Ink-filled, flat and quiet; the primary action is rare and obvious.
- **Shape:** gently rounded (6px).
- **Primary:** `ink` fill with white text in light; `paper-light` fill with `booth` text in dark. One per region at most: the status bar's "Add 12 episodes to queue" is the canonical one.
- **Hover / Focus:** hover deepens the fill (`ink-hover`; white in dark), press goes one step further. Focus is a 2px solid ring in the primary colour, with no glow.
- **Secondary / Outlined:** transparent with a `field-stroke` border and muted-ink text, so the edge reaches 3:1.
- **Severity buttons** (danger, warn, success) use the 700 shade with white text in light.
- **Disabled:** a coloured button turns grey (the field's disabled fill and text), it does not fade.

### Segment controls (SelectButton)
Joined segments on the panel or the booth, the chosen one filled with ink (paper in dark): view modes, zoom, any short exclusive choice. In the frame viewer the group is transparent with `field-stroke` borders between options, options are 0.25rem by 0.75rem at weight 500, the checked one carries the primary fill and border with no inner shadow. A checked option is never a white chip in a grey tray (that was 1.1:1).

### Chips and badges
- **Language chip:** the 4×16px language mark, a space-2 gap, then the language's English name in body small; the tag and native name in the tooltip. Undetermined: muted italic. Never a coloured pill.
- **Role badge** (Main, Commentary, SDH, Forced, Signs): 0.75rem medium text in a 1px hairline box, 4px radius, 1.25rem tall. Ink text when a disposition flag sets the role, muted when a title does, dashed border for a guess.
- **Settings echo chip:** a hairline pill, body small, 1.75rem line; muted when the setting is off.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** `paper` in light, `blue-black-panel` in dark, on the ground.
- **Shadow Strategy:** none (see the Hairline Rule).
- **Border:** 1px `hairline` / `blue-black-hairline`.
- **Internal Padding:** 0.75rem top, 1rem sides and bottom; header and body 0.75rem apart. The heading is the Heading role; a tab's lead card uses the Title role.

### Track rows and lists
The Summary's Tracks card is the receipt of what will be written. One subgrid for every group (index, language, codec, value, roles) so the columns line up from Video to Subtitles, with a group label over each group and a hairline between rows. A whole row is the button: 2rem high, 4px radius, hover `panel-hover`, focus a 2px inset primary ring. A row with an error or warning takes a 9% tint of the status colour across the full row and the status icon; no side stripe. Values are plain text (mono where measured); none is underlined.

Source rows are episode-first: the episode code (E01) in a 2.25rem mono column, muted, then the title. The open source is the whole row tinted with the selection tint, its code in ink and its name at 500. The nav rail marks the open view the same way: the whole item in the selection tint, ink text.

### Inputs / Fields
- **Style:** panel fill, 1px `field-stroke` border (3:1 against the field), 6px radius, 0.5rem by 0.75rem padding. Placeholder and icons in `field-stroke`.
- **Focus:** a 2px solid primary ring at -1px offset, no shadow (Aura's colour-only focus was 1.3:1).
- **Error / Warning:** a status icon before the label, and the control's border in the status stroke colour; a segment group gets a 1px outline round the whole group. Issues list under the control in body small, in the status text colour.
- **Override marker:** an 8px primary-coloured dot in the label row when a field differs from its preset.

### Issues
An issue is a row with a 1px status-stroke border, 6px radius, the status tint behind it and a 16px status icon; the message in ink, then "Show" (a link to the field) and fix buttons (small, secondary, outlined). Most severe first. Notes use the neutral ink tone.

### Navigation
- **Nav rail:** 5rem wide on the panel colour, a hairline on its right. Items stack a 24px line icon over a 0.75rem label, 8px radius; muted at rest, hover `panel-hover` with ink text, the open view in the selection tint with ink text at 500.
- **Editor tabs:** text tabs at weight 500 for all (a tab keeps its width when it opens), muted at rest; the open tab in ink over a 2px ink rule (paper in dark). Tabs are 0.6875rem by 0.5rem padded.
- **Status bar:** 3.5rem high on the panel colour with a hairline above. From left: the job's identity line (`Anime Show · S01E01 · MKV`, 0.75rem muted, ellipsis at 22rem), the output path in 0.75rem mono with the ellipsis cutting the start so the file name stays, the queue state, then the actions with the ink primary at the end.

### Programme strip (signature component)
The rythmo band of the job, under the preview frame (docked at the top of the editor column on Audio, Subtitles, Chapters and Tags, on the panel colour instead of the booth). Its rows share a mono gutter for labels (sized to the longest label) and a time column:

- **Header:** the Subheading "Programme" and, at the right, muted 0.75rem mono facts: span, chapter count, lane count.
- **Ruler:** 1.5rem, muted ink baseline, 7px major and 3px minor ticks, mono micro labels; a range that is not the whole programme shows a 2px ink bracket at each end, facing inwards.
- **Range:** a 5% ink wash behind every row under the ruler, across the encoded part.
- **Chapters:** 1.125rem blocks in `panel-hover`, separated by 2px of the strip's ground, numbered in mono micro when wider than 18px; outside the range at 45% opacity.
- **Frames:** one 24px hit target per sampled frame, drawn as a 5px muted dot; the current frame is a 10px ink dot with a 2px ring of the ground. Click or Arrow Left/Right, Home, End moves the preview.
- **Lanes:** one per output track (audio, a hairline, then subtitles), each a 24px-minimum full-width button with its mono label (`A1 ja`, `S2 en`, `forced` flag) and a 10px bar in its language colour across the encoded range (6px when there are more than eight lanes; then the lanes scroll). Commentary at 45%; a burned-in subtitle is a 2px outline only. Hover tints the row; click, or Arrow Up/Down, Home, End then Enter, reveals the track's editor. Each group of buttons is one Tab stop.
- **Playhead:** a 2px ink line at the current frame and, under the strip, its time in mono micro on an ink flag with ground-coloured text, 4px radius, pinned inside the ends.
- **Legend:** a language chip per language in lane order at 0.75rem, then muted keys ("pale = commentary", outline = burned in, forced).
- **Text alternative:** a screen-reader list of the programme and every lane (language, format, span) is always present.

### Reveal
Following an issue or a lane to its field: the target's ring closes in from 8px to 2px offset in the primary colour over the selection tint, holds, then fades, 2.4s in all; with reduced motion the ring shows at once. State transitions elsewhere take 0.15s and drop to 0 with reduced motion.

## Do's and Don'ts

### Do:
- **Do** fill the primary action with ink in light and paper-light in dark, and keep it to one per region.
- **Do** colour a language only through `useLanguageColor()` / `languageSlot`, and draw it as the 4×16px mark or a lane bar.
- **Do** set every number, path, code and timecode in Red Hat Mono with tabular figures.
- **Do** select and flag whole rows with a tint (selection tint, or a 9% status tint), with the full row as the hit target.
- **Do** put panels on the ground as a fill plus a 1px hairline, and give a resting surface no shadow.
- **Do** use joined segments with an ink-filled checked option for short exclusive choices.
- **Do** design every colour pair in both schemes and add it to `contrast.test.ts`.
- **Do** step headings by size (1rem, 1.125rem, 1.25rem) at weight 700.

### Don't:
- **Don't** give the chrome a brand hue: no indigo or blue accent buttons, links, tabs or info notes.
- **Don't** add a language colour in the red, orange or amber family, or reuse a status colour for a language.
- **Don't** mark a selected or flagged row with a side stripe; tint the whole row.
- **Don't** underline values or wrap every value in a chip; values are plain text.
- **Don't** dress the app as a film studio: no clapperboards, film perforations, reels or studio props.
- **Don't** use neon colours, glows or coloured shadows, and don't make the identity dark-only.
- **Don't** put a small uppercase kicker or eyebrow above a heading; the label role is only for group labels over rows and table column names.
- **Don't** fall back to the system font for headings or values; the Red Hat faces are bundled so they always load.
