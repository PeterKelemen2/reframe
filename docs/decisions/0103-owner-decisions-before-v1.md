# 0103 — The owner's decisions before v1

- Status: accepted
- Date: 2026-11-20
- Steps: C-2, C-6, C-7, C-8, C-9, C-11, C-12, S-2, S-6, F-9, F-10, F-14, F-15, D-8

## Context

`docs/progress.md` listed open owner decisions, and the must-have audit
(`docs/audit/must-have-audit.md`, 2026-11-18) left 16 partials for the owner to sort. The owner
answered all of them on 2026-11-20. This record lists the answers and the work they make. The
audit's row IDs (`A-76`, `C-18`, …) are rows of the audit table, not plan steps: audit row
`C-18` is about the batch engine (step C-12), not the Matroska header writer (step C-18).

## Decision

### Changes before v1

1. **NVENC constant quality gets a high `-maxrate` / `-bufsize`** (C-7; [0102](0102-nvenc-on-linux.md)
   item 5h). Without a level, NVENC picks the lowest level that fits the picture and holds the
   bitrate under that level's limit in CQ mode too: H.265 1080p25 stays at about 12 Mbit/s and
   CQ 5 to 21 give the same file on a grainy source (`testdata/README.md` §NVENC on Linux). In
   CQ mode with no level set and no `maxrate`/`bufsize` in the custom parameters, the builder
   adds a `-maxrate` and `-bufsize` high enough that the quality value decides the size.
   NVENC then picks a higher level, which a player sees. The values are set in the step from a
   measurement on the GTX 1050 Ti and recorded in `testdata/README.md`: the cap must not bind
   for a grainy 1080p and 2160p source at CQ 10, and the level stays as low as that allows
   (the measured starting point: `-maxrate 100M -bufsize 200M` gives level 5.0 at 1080p25 and
   21 MB where the capped file is 3.1 MB). An explicit level keeps today's behaviour and the
   `encoder.level_bitrate_too_high` rule. The GPU test's expected failure at the CQ range end
   is removed.
2. **The built-in "H.265 NVENC 2160p 4K" preset is 10-bit** (Main 10), like the other 4K
   presets (0102 item 5i). Every NVENC GPU that encodes H.265 encodes Main 10 (checked on
   Pascal); HDR10 sources stay HDR.
3. **`output.default_container` is removed** from the settings (C-2, C-9, F-15). Nothing read
   it: the preset's container decides, as in HandBrake. The settings `schema_version` goes up
   with a migration and a down-level note (an older version keeps the field as unknown).
4. **Align A/V start is built** (C-7, audit row A-76). It is stored in presets and shown in the
   Summary, but the command is the same with it on and off. It works as HandBrake's option:
   the output's streams start together; the step records the FFmpeg arguments it uses and a
   test with a source whose audio and video start at different times.
5. **Batch crop per file** (C-12, F-13, audit row C-18). A group's job is queued with
   `crop.mode = auto` and no rectangle, so letterboxed episodes are encoded uncropped
   (`dimensions.crop_not_detected`). Crop detection runs for each file of a group whose policy
   is automatic or conservative, before its job is queued; "same manual crop for all" stays as
   is. The group's chapter-name policy (from source or generated) gets its control in the
   group editor.
6. **Track name templates** (F-10, audit row B-39). A template typed into a track's Name
   (`{lang_name} {channels} {codec}`) is expanded for the job, as the codec rules'
   `name_template` already is. Today it is written literally.
7. **No power actions in the Docker image** (S-2, S-6, F-14, audit row D-17;
   [0036](0036-power-actions.md)). The image tells the server that it runs in a container,
   `GET /api/system` reports it, the Queue view does not offer Sleep and Shut down there, and
   the API refuses them (and *Quit*, in web mode) with an issue instead of failing after the
   countdown.
8. **A job whose encoder became unavailable** (C-11, F-14, audit row A-27) is shown as
   `Failed — encoder unavailable` with the fix actions of the Video tab's banner, in the
   queue view and in `reframe queue list`.
9. **AMF pre-analysis below 200 lines** (C-8, audit row A-35) is a validation error with a fix
   (turn pre-analysis off); today it passes and the encoder fails with exit 190. The dry run
   names the real cause, not VBAQ.
10. **Start for one job** (F-14, audit row B-53): a waiting job's row gets **Start** (the API
    has `start {job_ids}`).
11. **Help texts** (C-6, audit rows A-12, B-28): a one-line help for each filter preset and
    for the sharpen/unsharp tunes `fine`, `medium`, `coarse`; the typical range in the help of
    every numeric advanced option that has none.
12. **The AppImage bundles the GStreamer plugins** (D-8; [0100](0100-desktop-app-with-intel-qsv-on-linux.md)):
    base, good and the libav plugin, so that preview clips play in its window. The shell's
    `webview_plays_video` stays as the guard for a webview without them. The plugins' LGPL
    notices and their corresponding source join the notices and the sources release
    ([0073](0073-gpl-corresponding-source-per-tool-pin.md)).
13. **The AppImage offers a desktop entry once** (D-8; 0100): at its first start it asks
    whether to add Reframe to the application menu, and writes
    `~/.local/share/applications/Reframe.desktop` pointing at the AppImage (taskbar progress,
    open-with). Settings can remove it.

### No change

14. **The language list** ([0089](0089-folder-probe-and-language-list-removed.md) item 4) stays
    built at the first request. The 50 ms target for the first `GET /api/languages` on Windows
    is dropped (58–72 ms there, once per process, behind the app's start).
15. **Small windows**: the desktop app keeps its minimum size of 1100×700; a layout for smaller
    windows comes after v1.
16. **The Detelecine crash of the Windows FFmpeg** (2 of 400 runs; no candidate build is free of
    it, status.md D-7) is a known issue in the release notes and the user docs. No upstream
    report and no automatic retry.
17. **The other audit partials** become plan text: A-03 (`E-AC-3 Atmos`, as the code and C-2
    say), A-34 (NVENC rate control follows the quality mode; `constqp` is not offered),
    A-62 (the character encoding of a subtitle file is detected for UTF-8 and UTF-16 only,
    [0065](0065-m6-tracks-and-metadata.md) item 6), A-77 (no file-system creation time on
    Linux, [0012](0012-output-naming-rules.md)), B-24 (with an environment override
    the repair screen offers only **Check again**), C-26 (the naming editor previews the shown
    file; the Check group matrix shows every file's name), C-27 (04's example: E11 has no dub,
    so Check group is not all ✓).

### Order

The changes above come before the release checklist. The first push to GitHub follows them,
before the user docs, and then a `v1.0.0-rc.1` tag tries the release pipeline.

## Consequences

- NVENC CQ outputs are larger on grainy sources and carry a higher level; a player limited to
  a low level (older TVs at 4.1) may refuse them. Setting a level in the preset is the way back.
- The AppImage grows by the GStreamer plugins, and its notices and source manifest get LGPL
  entries.
- Removing `default_container` makes a settings file of this version unreadable for an older
  version only through the usual down-level path (the migration note).
- Windows users may see a rare Detelecine crash; the job fails and can be retried by hand.

## Plan changes

- `03-features.md`: §Audio "Codec" (`E-AC-3 Atmos`); §Advanced encoder options, the NVENC row;
  §Subtitles, external subtitles' character encoding; the repair-screen row (environment
  override); §Output naming, `{creation-date}` and the naming editor's preview; §Settings,
  Output without a default container.
- `04-batch-mode.md`: §Example, step 3.
- `05-core.md`: §C-7 (NVENC CQ maxrate, Align A/V start); §C-8 (AMF pre-analysis).
- `06-web-app.md`: §S-2, `GET /api/system` reports a container.
- `07-desktop-app.md`: §In-app video playback, §D-8 (GStreamer plugins and the desktop entry
  of the AppImage), §Risks.
- `08-roadmap.md`: §M10 (this record's changes before the release checklist), §After v1 (the
  small-window layout).

## Follow-up (2026-11-20): items 12 and 13

Built on Linux (D-8). Item 12 deviates: Ubuntu 22.04's `gstreamer1.0-libav` depends on
`libavcodec58`, `libavformat58`, `libavfilter7` and `libavutil56`, which bring 59 packages with
GPL x264 and x265; no package may contain FFmpeg ([0093](0093-ffmpeg-download-and-build-choice.md),
D-10), so only GStreamer's base and good plugins are bundled (+3.4 MiB). Measured in the
AppImage through WebKitWebDriver: VP9 plays (Opus, Vorbis, FLAC, MP3 audio; AAC, AC-3, E-AC-3
are silent); H.264 and HEVC end in a media error, and the preview shows the frame compare;
AV1 plays its audio without a picture and without an error, which the preview now treats as a
codec the window cannot play. The decoders for H.264, HEVC and AV1 in the AppImage are the
owner's choice (open). Item 13 works as written; the dialog is mounted in `App.vue`.
