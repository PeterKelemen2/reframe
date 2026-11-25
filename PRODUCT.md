# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The same Vue 3 frontend runs in a browser (served by `reframe-server`) and inside the Tauri 2
desktop app on Linux and Windows. The desktop app wraps the web UI, so its design language is
the web one. The main surface is the **web UI on a home server or NAS**, opened from a browser
on another computer. Design work tunes for that surface first; the desktop app must keep working.

## Users

- **Primary: the owner.** One power user who encodes TV seasons and films from MKV remuxes for
  personal use. They know HandBrake well, and also know StaxRip and MKVToolNix. They care
  about track languages, flags, codecs, crop accuracy and encoder settings. They usually set up
  a whole season at once.
- **Later: other home-media enthusiasts.** Reframe will be published for people with the same
  job (HandBrake, StaxRip or MKVToolNix users who manage a personal library). They will not
  have read the plan docs. Design work must keep the expert depth, and it must also stay
  learnable for this second group.

Single user per installation. A multi-user web app is a non-goal.

## Product Purpose

Reframe converts video files the way HandBrake does: open a source, pick a preset, adjust
dimensions, filters, video, audio, subtitles, chapters and tags, then queue the job. It keeps
HandBrake's workflow and presets. It exists because HandBrake hides track information, has no
track-metadata editing and no season-wide editing, and gives a crop and filter UI that
is hard to trust.

Success: a whole season goes from remux to correctly named, correctly tagged encodes from one
configured episode, with no surprises in the output tracks and no frozen UI along the way.

## Positioning

What HandBrake does, plus the eight things it does not do (from `docs/plan/01-scope.md`):

1. **Better track information** before any click: name, language, codec with its commercial
   name ("DTS-HD MA", "TrueHD Atmos"), channels, bitrate, role (commentary, SDH, forced).
2. **MKVToolNix-style track metadata editing**: language, name, default, forced, commentary,
   hearing-impaired, visual-impaired and original flags on every output track, and a
   remux-only mode for metadata changes without re-encoding.
3. **Season / batch editing**: configure one episode, apply it to every structurally identical
   file. Track mapping uses rules, not fixed indexes.
4. **A crop preview you can trust**: a magnifier on every edge and a multi-frame crop check.
5. **A simpler Dimensions tab**: one "Output size" control, no borders or padding.
6. **Explained filters**: description, when to use it, speed cost, before/after preview.
7. **Robust encoder handling**: a missing encoder is a clear error with a suggested fallback,
   never a freeze.
8. **StaxRip-level advanced encoder options**: grouped, searchable, documented options for
   x264, x265, SVT-AV1 and hardware encoders, with a live command-line preview always visible.

## Operating Context

- **Web mode:** the server runs on a home server or NAS (bare or Docker). The user opens the
  UI from a browser on another computer on the home network, sometimes behind a reverse proxy.
  Media is already on the server; there is no upload through the browser. A login protects the
  web mode.
- **Desktop mode:** Tauri 2 shell on Linux (primary) or Windows 10/11, with the Python server
  as a sidecar. Native file dialogs, drag and drop, taskbar progress, notifications, tray.
- **First run:** Reframe does not contain FFmpeg. The first-run screen lists pinned builds to
  download, or install from a file, or points to the user's own FFmpeg (`docs/user/ffmpeg.md`).
- **Long-running work:** encodes take minutes to hours. The queue lives on the server, is shared
  with `reframe encode` CLI runs, survives restarts, and reports progress over a WebSocket. The
  user often starts a queue and leaves.
- **Main screens:** Workspace (sources | editor tabs | preview), Queue, Activity log, Presets,
  Settings, plus a separate preview window. Editor tabs: Summary, Dimensions, Filters, Video,
  Audio, Subtitles, Chapters, Tags. Batch mode adds a group matrix.

## Capabilities and Constraints

- Built and in use: everything in milestones M0 to M9; M10 (hardening and release) is in
  progress. See `docs/status.md`.
- Stack (fixed): Vue 3 + TypeScript + Vite + Pinia + Vue Router, PrimeVue 4 (styled mode, an
  Aura-based preset), Lucide icons, vue-i18n. Tokens in `frontend/src/styles/`.
- Light, dark and "system" themes; compact and comfortable density.
- Editing state lives in the client; the server validates, resolves and builds commands.
  Expected failures are data (validation issues shown in the UI), not exceptions.
- No operation may block the UI. Every external call has a timeout and can be cancelled.
- Every string the user sees goes through vue-i18n. English only for now; the UI must stay
  ready for other languages (longer strings).
- Terminology follows HandBrake where a HandBrake concept exists (preset, queue, Summary,
  Dimensions, passthru, mixdown) and MKVToolNix for track flags.
- Non-goals for v1: borders/padding, disc decryption, multi-user, distributed encoding,
  AviSynth/VapourSynth, browser upload. Post-v1: disc/ISO input, HandBrake preset import,
  HDR10+/Dolby Vision, VMAF/SSIM, subtitle OCR, watch folders, macOS.

## Brand Commitments

- The name **Reframe** is fixed. The current app icon, favicon and visual look are not binding
  and may change.
- Copy in the docs and UI is plain, short-sentence technical English (the repository's
  `ste-writing` practice). This is current practice, not a confirmed brand voice.

## Evidence on Hand

- The plan (`docs/plan/`), decision records (`docs/decisions/`) and user docs (`docs/user/`).
- Generated test media (`scripts/make-testdata.py`) and a release-name corpus
  (`testdata/names.toml`) that can stand in as realistic content.
- **Absent:** no other users yet, no testimonials, no screenshots or marketing assets, no
  published benchmarks or comparisons. Future work must not invent any of these.

## Product Principles

1. **Show the facts before the choice.** Track, codec and encoder information is visible before
   the user commits, never hidden behind a click.
2. **Never surprise the output.** What the UI shows (tracks, flags, names, command line) is what
   the encode produces. Validation issues and fallbacks are explicit.
3. **One episode, the whole season.** Batch work is the normal case, not an add-on.
4. **Expert depth, learnable surface.** Keep every advanced option, and explain it in place, so
   a HandBrake user can learn Reframe without the plan docs.
5. **Never freeze.** Long work runs in the background with honest progress; the UI stays
   responsive and cancellable.

## Accessibility & Inclusion

- WCAG 2.x AA contrast in both themes, checked by `frontend/src/styles/contrast.test.ts`
  (non-text controls at 3:1, including disabled controls as a project floor).
- Full keyboard paths, visible focus, `prefers-reduced-motion` respected (step F-16,
  decision 0076). axe checks run in the Playwright flows in Chromium, Firefox and WebKit.
