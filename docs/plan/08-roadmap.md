# 08 — Roadmap

The milestones put the steps from [05](05-core.md), [06](06-web-app.md), [07](07-desktop-app.md)
and [09](09-quality-and-release.md) in order. Each milestone ends with something you can
**use or demo**. A milestone is done only when its demo works and CI is green on Linux and
Windows. The current state of each milestone and step is in [../status.md](../status.md).

**Changed order ([decision 0029](../decisions/0029-core-before-the-ui-milestones.md)).** After
M2, the core parts of M6–M9 (C-6, C-10, C-12, C-13, and the rest of C-11, C-14 and C-15) are
built first, on one branch `core-complete`, before M3. M6–M9 stay open until their UI parts
are built and their full demos pass.

## Dependency graph

```
M0 Foundations
 └─► M1 Read media (core)
      └─► M2 Encode from the CLI (core)
           └─► M3 API + desktop spike
                └─► M4 Frontend MVP (web) ──► M5 Desktop shell
                     ├─► M6 Tracks & metadata ──► M7 Batch / season
                     ├─► M8 Picture: preview, crop, filters
                     └─► M9 Advanced encoder options
                                   all ──► M10 Hardening & v1.0 release
```

M6, M8 and M9 do not depend on each other. The order below puts your biggest pain points
first (track info, metadata, season editing).

---

## M0 — Foundations

| Steps | `C-0`, `F-0`, `Q-1.1`–`Q-1.3`, `Q-2.1` |
|-------|-----------------------------------------|

- uv workspace, package skeletons, frontend scaffold, CI matrix (Ubuntu + Windows), fixture
  generator script.

**Demo:** CI is green. `uv run pytest` and `npm test` run on an empty project.

## M1 — Read media

| Steps | `C-1`, `C-2`, `C-3`, the languages part of `C-6`, `C-15` (`probe` CLI only) |
|-------|------------------------------------------------------------------------------|

**Demo:** `reframe probe "Show S01E01.mkv"` prints every track with its commercial codec name,
channels, bitrate (with its source), language, title, role badges and flags. `--json` prints
the `MediaSource` model.

## M2 — Encode from the CLI

| Steps | `C-4`, `C-5`, `C-6` (encoders, containers, filters; basic options), `C-7`, `C-8`, `C-9`, `C-11`, `C-12` (codec-rule stage of the audio defaults only, [decision 0018](../decisions/0018-m2-draft-tracks-and-multi-file-encode.md)), `C-14` (sleep inhibit), `C-15` (`encoders`, `plan`, `encode`, `name`), `C-16` |
|-------|---|

**Demo:**
1. `reframe encoders` returns at once (from the cache) and then updates. A machine with no
   NVIDIA driver shows `hevc_nvenc — unavailable: NVIDIA driver not found`.
2. `reframe plan movie.mkv --preset "H.265 MKV 1080p"` prints the FFmpeg command.
3. `reframe encode …` shows progress and ETA and writes a correct file. Ctrl+C cleans up the
   `.part` file.
4. A preset that uses an unavailable encoder fails validation and names the closest
   encoder. Nothing hangs.
5. `reframe name` on the Hacksaw Ridge folder picks the folder name and prints
   `Hacksaw.Ridge`. On the Sopranos episode, it prints `The.Sopranos.S03E02.Proshai.Livushka`.
   `reframe encode` without `-o` uses the naming template.

## M3 — API and desktop spike

| Steps | `S-0`, `S-1`, `S-2`, `S-3`, `S-5`, `D-0`, `Q-2.3` |
|-------|----------------------------------------------------|

**Demo:** the OpenAPI docs page lists every route. The generated TypeScript types are committed.
The WebSocket streams job progress. The desktop spike result is written to
`docs/decisions/0001-desktop-shell.md`.

## M4 — Frontend MVP (web)

| Steps | `F-1`–`F-6`, `F-9` (without advanced options), `F-10` (source tables + basic output tracks), `F-12`, `F-14`, `F-15` (basic), `F-18`, `S-4` |
|-------|---|

**Demo:** in the browser: open a file from the server file browser → choose a preset → change
the encoder and quality → add and remove audio tracks → add to queue → watch progress → open
the log. Validation issues appear inline and on Summary.

This is the **first usable GUI**.

## M5 — Desktop shell

| Steps | `D-1`–`D-6` |
|-------|-------------|

**Demo:** the M4 flow, as a desktop app on Linux and Windows, with native dialogs, drag-and-drop
from the file manager, notifications, taskbar progress, and a clean quit while a job runs.

## M6 — Tracks and metadata

| Steps | `F-10` (complete), `C-10` (bitrate + subtitle scans, loudness), `C-12` (rule engine + audio/subtitle defaults only), `C-13`, `F-11` |
|-------|---|

**Demo:**
1. A DTS-HD MA track with no bitrate in the file → **Measure** → a bitrate appears.
2. A commentary track shows its badge with no click. The tooltip says where the role came from.
3. Set languages (`hu`, `pt-BR`), names and flags (commentary, SDH, original) → queue → the
   re-probe shows them all.
4. Change only flags on an MKV → the job type is `metadata_edit` and finishes in under a second.
5. Audio defaults `Hungarian 5.1 or more → AC-3 5.1, max 320` and `English 5.1 or more → AC-3
   5.1, max 384`: the live preview shows that DTS-HD MA becomes AC-3 320, an AC-3 224 kb/s source
   is passed through, and a stereo track falls to the next rule. Each row has a reason.

## M7 — Batch / season mode

| Steps | `C-12`, `F-13` |
|-------|----------------|

**Demo:** the example in [04 §Example](04-batch-mode.md#example): open a season folder → one group
→ edit audio and subtitles once → the matrix shows ✓ for every file, with the right warnings for
E05 and E11 → queue 12 jobs with templated names → save the group as a preset → apply it to
season 2 in one click.

## M8 — Picture: preview, crop, filters

| Steps | `C-10` (frames, cropdetect, render, clips), `F-7`, `F-8` |
|-------|---|

**Demo:**
1. Manual crop: the magnifier shows all four edges at 4×. **Check crop on all frames** marks a
   frame where the crop removes picture content.
2. Automatic and conservative crop give different results on a fixture with changing aspect
   ratios.
3. Filters: each filter shows its help. The before/after split works. Colorspace on an HDR
   source suggests tone mapping, and the preview shows the result.
4. Preview clip: plays in-app (H.264) or compares frames (HEVC/AV1).

## M9 — Advanced encoder options

| Steps | `C-6` (complete option sets + per-preset defaults), `F-9` (advanced panel, command preview) |
|-------|---|

**Demo:** x265 advanced panel: search "psy" finds psy-rd and psy-rdoq. Changing b-frames highlights
the field and the category count, and the command preview updates at once. **Copy HDR metadata**
fills master-display and MaxCLL on an HDR10 fixture. An unsupported custom parameter shows a
validation error from the dry run.

## M10 — Hardening and v1.0 release

| Steps | `S-6`, `D-7`, `D-8`, `D-9`, `F-16`, `F-17`, `Q-3`, `Q-4`, `Q-5` |
|-------|---|

**Release checklist:**

- [ ] Every "Must-have for v1" item in [01-scope.md](01-scope.md#must-have-for-v1) is checked off
      against its demo.
- [ ] Docker image published. The compose example works with VAAPI and NVENC.
- [ ] Windows installer (signed) and Linux AppImage/deb/rpm attached to the release.
- [ ] The updater picks up a test release.
- [ ] Performance budgets ([09 §Q-3](09-quality-and-release.md#q-3-performance-budgets)) are met.
- [ ] Third-party licence notices are bundled ([09 §Licensing](09-quality-and-release.md#licensing)).
- [ ] User docs: quick start, presets, batch mode, keyboard shortcuts.

## After v1

In rough priority order: Blu-ray/DVD folder input · HandBrake preset import · HDR10+/Dolby
Vision tooling · VMAF/SSIM after encode · watch folders (web) · subtitle OCR · chunked encoding
· macOS build. See [01-scope.md §Later](01-scope.md#later-post-v1).
