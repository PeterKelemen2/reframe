# 01 — Scope

## Product statement

Reframe converts video files the way HandBrake does: open a source, pick a preset, adjust
dimensions, filters, video, audio, subtitles, chapters and tags, then queue the job. Reframe
adds the following on top:

1. **Better information.** Every audio and subtitle track shows its name, language, codec
   (with its commercial name, e.g. "DTS-HD MA", "TrueHD Atmos"), channels, bitrate, and role
   (commentary, SDH, forced) before you click anything.
2. **Track metadata editing like mkvtoolnix.** You can set language, name, default, forced,
   commentary, hearing-impaired, visual-impaired and original flags on every output track.
3. **Season / batch editing.** Configure one episode, then apply the setup to every
   structurally identical file. Track mapping uses rules, not fixed indexes.
4. **A crop preview you can trust.** Manual crop shows zoomed views of every edge. You can
   check the crop on many frames before you encode.
5. **A simpler Dimensions tab.** Borders are gone. One "Output size" control replaces
   Resolution limit, Scaled size, Pixel aspect and Final dimensions.
6. **Explained filters.** Each filter has a short description, guidance on when to use it,
   its speed cost, and a before/after preview.
7. **Robust encoder handling.** A missing encoder (driver removed, GPU changed, FFmpeg
   rebuilt) shows up as a clear error with a suggested fallback. It never freezes the app.
8. **Advanced encoder options like StaxRip.** Grouped, searchable, documented options for
   x264, x265, SVT-AV1 and hardware encoders (b-frames, refs, lookahead, AQ, psy-rd, deblock,
   SAO, HDR metadata, …). A live command-line preview is always visible.

## Target users

- One power user who encodes TV seasons and films from MKV remuxes, for personal use.
- The same person running Reframe on a home server or NAS through the web UI.

## Platforms

| Surface | Linux | Windows | macOS |
|---------|-------|---------|-------|
| Core (`reframe`) | ✅ | ✅ | Not tested. Do not block it |
| Web server (Docker / bare) | ✅ | ✅ (bare) | — |
| Desktop app | ✅ (x86_64) | ✅ (x86_64, Windows 10/11) | Out of scope for v1 |

## Feature parity baseline (HandBrake)

Reframe v1 must cover these HandBrake features, unless "Changed" or "Dropped" says otherwise:

| HandBrake area | Reframe v1 | Notes |
|----------------|------------|-------|
| Source open (file, folder of files) | Keep | Disc folders / ISO: see [non-goals](#non-goals-for-v1) |
| Range (chapters, seconds, frames) | Keep | |
| Presets (built-in, user, default, import/export) | Keep | Same behaviour. Track selection uses rules |
| Summary tab | Changed | New card layout. Container options stay here |
| Dimensions: crop, scale, anamorphic, rotate/flip | Changed | Borders/padding dropped. Scale controls merged |
| Filters | Keep + explain | Same filter set, plus HDR→SDR tone mapping |
| Video (encoder, quality, framerate, preset/tune/profile/level) | Keep + advanced | Advanced options panel added |
| Audio (selection behaviour, passthru, mixdown, bitrate, gain, DRC) | Keep + info + metadata | Audio defaults get per-language codec and max-bitrate rules, with a live preview. Loudness normalisation added |
| Subtitles (selection, burn-in, forced only, import SRT/SSA) | Keep + info + metadata | |
| Chapters (markers, names, import/export) | Keep | |
| Tags | Keep | |
| Automatic file naming (17 variables, title case, underscores, punctuation, .m4v) | Keep + extended | All HandBrake variables, plus release-name parsing (`{main_title}`, `{name}`, `{sub_title}`, season/episode, …), file-vs-folder name choice, optional groups, subfolders |
| Live preview (short encoded clip) | Keep | Still-frame before/after added |
| Queue (pause, resume, reorder, retry, persistence, logs) | Keep | |
| Activity log | Keep | Per job |
| When done (shutdown, sleep, quit, notify) | Keep | |

## Must-have for v1

- Everything in the parity table above.
- Output naming with every HandBrake variable, plus release-name parsing and the folder-name choice ([03 §Output naming](03-features.md#output-naming)).
- Audio defaults with per-language codec and max-bitrate rules ([03 §Audio defaults](03-features.md#audio-defaults-stored-in-the-preset)).
- Rich audio/subtitle info and role detection ([03-features.md §Audio](03-features.md#audio)).
- Track metadata editing and a remux-only mode for metadata changes without re-encoding.
- Batch groups with rule-based track mapping and apply-to-group ([04-batch-mode.md](04-batch-mode.md)).
- Manual crop magnifier and a multi-frame crop check.
- Non-blocking encoder detection with validation and fallbacks.
- Advanced options for `libx264`, `libx265`, `libsvtav1`, and NVENC/QSV/AMF/VAAPI basics.
- Web app (single user) and desktop app (Linux + Windows).

## Later (post-v1)

- Blu-ray / DVD folder and ISO input with title scan (unencrypted only).
- Importing HandBrake preset JSON (partial field mapping).
- HDR10+ / Dolby Vision metadata handling (via `hdr10plus_tool` / `dovi_tool`).
- Chunked / parallel encoding of one file.
- Quality metrics after encode (VMAF / SSIM).
- Subtitle OCR (PGS → SRT).
- Watch folders (web).
- macOS desktop build.

## Non-goals for v1

- **Borders / padding.** Dropped on purpose.
- **Disc decryption.** Never in scope.
- **Multi-user web app.** One user. Put a reverse proxy in front for extra protection.
- **Distributed encoding** across machines.
- **AviSynth / VapourSynth scripting.** The filter set is FFmpeg-native.
- **Uploading media through the browser.** The web app works on files that are already on
  the server.

## Constraints

- The core must not import anything from the web or desktop layers.
- All FFmpeg work runs in subprocesses. No libav bindings.
- No operation may block the UI. Every external call has a timeout and can be cancelled.
- Settings and presets are versioned JSON with migrations.
- Every build (Docker, Linux, Windows) bundles the same pinned FFmpeg. Users can override the
  path to each tool ([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)).

## Open questions (owner to decide)

| # | Question | Default if not answered |
|---|----------|-------------------------|
| 1 | Do you need Blu-ray/DVD folder input in v1, or are MKV remuxes enough? | Post-v1 |
| 2 | Licence for Reframe itself? | GPL-3.0-or-later (every build bundles a GPL FFmpeg with x264/x265; see [09](09-quality-and-release.md#licensing)) |
| 3 | UI languages? | English first. The UI is i18n-ready (vue-i18n) |
| 4 | Desktop framework: are you OK with Tauri 2 (Rust shell + shared Vue UI)? | Yes. See the alternatives in [07](07-desktop-app.md#alternatives-considered) |
