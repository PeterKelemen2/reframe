# 08 — Roadmap

The milestones put the steps from [05](05-core.md), [06](06-web-app.md), [07](07-desktop-app.md)
and [09](09-quality-and-release.md) in order. Each milestone ends with something you can
**use or demo**. A milestone is done when its demo works and every CI command passes on Linux;
[../status.md](../status.md) lists what has not run on Windows. The current state of each
milestone and step is in [../status.md](../status.md).

**Linux first ([decision 0053](../decisions/0053-linux-first-windows-testing-phase.md)).**
Linux is the primary platform. Windows stays a v1 target, but no milestone before M10 waits
for it: Windows code paths are written to the plan and mock-tested on Linux, and everything
else that needs Windows is checked once, in the [Windows testing phase](#windows-testing-phase)
at the start of M10 (`Q-1.4`). Nothing is pushed, so GitHub Actions does not run.

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
                ├─► M3b Shared queue (before M5)
                └─► M4 Frontend MVP (web) ──► M5 Desktop shell (also needs M3b)
                     ├─► M6 Tracks & metadata ──► M7 Batch / season
                     ├─► M8 Picture: preview, crop, filters
                     └─► M9 Advanced encoder options
                                   all ──► M10 Windows testing phase, hardening & v1.0 release
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

| Steps | `S-0`, `S-1`, `S-2`, `S-3`, `S-5`, `D-0` (Linux), `Q-2.3` |
|-------|-----------------------------------------------------------|

**Demo:** the OpenAPI docs page lists every route. The generated TypeScript types are committed.
The WebSocket streams job progress. The desktop spike result is written to
`docs/decisions/0001-desktop-shell.md`. The spike runs on Linux; its Windows items wait for
the [Windows testing phase](#windows-testing-phase).

## M3b — Shared queue

| Steps | `S-7`, `C-17` |
|-------|---------------|

[Decision 0042](../decisions/0042-one-scheduler-process-and-cli-clients.md): one process runs
every job, and the CLI hands its jobs to it. Built after M3 (it needs S-2 and S-3), beside or
after M4 (the frontend does not need it), and done before M5 (D-3 finds the owner the same
way). S-7's server side is built first, on the branch `server-complete`
([decision 0055](../decisions/0055-server-complete-order.md)); C-17 follows.

**Demo:**
1. Two `reframe encode` runs in two terminals both encode, share one `parallel_jobs` limit, and
   show in `reframe queue list` from a third terminal. Ctrl+C in one cancels only its own
   jobs.
2. `kill -9` of one of them: its jobs are cancelled and their `.part` files removed. The other
   run goes on.
3. A job whose output another waiting job already claims is added `failed` with
   `queue.output_claimed`.

## M4 — Frontend MVP (web)

| Steps | `F-1`–`F-6`, `F-9` (without advanced options), `F-10` (source tables + basic output tracks), `F-12`, `F-14`, `F-15` (basic), `F-18`, `S-4`, `F-17` (Playwright set-up + flow 3) |
|-------|---|

`S-4` is built early, on the branch `server-complete`
([decision 0055](../decisions/0055-server-complete-order.md)).

**Demo:** in the browser: open a file from the server file browser → choose a preset → change
the encoder and quality → add and remove audio tracks → add to queue → watch progress → open
the log. Validation issues appear inline and on Summary.

This is the **first usable GUI**.

## M5 — Desktop shell

| Steps | `D-1`–`D-6` |
|-------|-------------|

**Demo:** the M4 flow, as a desktop app on Linux, with native dialogs, drag-and-drop from the
file manager, notifications, taskbar progress, and a clean quit while a job runs. The same
demo on Windows is part of the [Windows testing phase](#windows-testing-phase).

## M6 — Tracks and metadata

| Steps | `F-10` (complete), `C-10` (bitrate + subtitle scans, loudness), `C-12` (rule engine + audio/subtitle defaults only), `C-13`, `F-11`, `F-17` (flow 1) |
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

| Steps | `C-12`, `F-13`, `F-17` (flow 2) |
|-------|----------------|

**Demo:** the example in [04 §Example](04-batch-mode.md#example): open a season folder → one group
→ edit audio and subtitles once → the matrix shows ✓ for every file, with the right warnings for
E05 and E11 → queue 12 jobs with templated names → save the group as a preset → apply it to
season 2 in one click.

## M8 — Picture: preview, crop, filters

| Steps | `C-10` (frames, cropdetect, render, clips), `F-7`, `F-8`, `F-17` (flow 4) |
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

| Steps | `Q-1.4` (the Windows testing phase), `C-18` (Reframe's own Matroska header writer, [decision 0080](../decisions/0080-own-matroska-header-writer.md); before the release checklist), `S-6`, `D-7`, `D-8`, `D-9`, `F-19` (the Range selector, [decision 0074](../decisions/0074-range-selector-in-m10.md); before F-16), `F-16`, `F-17` (all five flows in Chromium and WebKit), `Q-3`, `Q-4`, `Q-5` |
|-------|---|

`S-6` is built early, on the branch `server-complete`
([decision 0055](../decisions/0055-server-complete-order.md)); its Intel QSV and NVIDIA NVENC
checks in Docker wait for such a host.

### Windows testing phase

The first part of M10 ([decision 0053](../decisions/0053-linux-first-windows-testing-phase.md)).
On Windows 10 or 11 (how: [01 open question 5](01-scope.md#open-questions-owner-to-decide)):

1. The Python and frontend commands of `ci.yml` pass (`Q-1.4`).
2. D-0's Windows items: the sidecar starts, a kill from Task Manager leaves no sidecar or
   FFmpeg process, WebView2 renders the UI, and drag-and-drop gives correct paths.
3. The M5 demo works.
4. The Windows parts of D-3 (Job Object), D-7 (the bundled tools on the Windows hosts that are
   available), D-8 (the NSIS installer, the MSI) and D-9 (the smoke tests) pass.
5. Each Windows item of [Not verified](../status.md#not-verified) is checked.

A failure is fixed in the phase or recorded as a known limit in `docs/status.md`. A problem
that changes the desktop shell gets a new decision record that supersedes 0001. The release
checklist below is done only after this phase.

### Release checklist

- [ ] Every "Must-have for v1" item in [01-scope.md](01-scope.md#must-have-for-v1) is checked off
      against its demo.
- [ ] Docker image published. The compose example works with VAAPI, and with NVENC when an
      NVIDIA host is available ([decision 0043](../decisions/0043-plan-review-before-m3.md)
      item 7).
- [ ] Windows installer (signed) and Linux AppImage/deb/rpm attached to the release (or the set
      chosen in [01 open question 6](01-scope.md#open-questions-owner-to-decide)).
- [ ] The updater picks up a test release.
- [ ] Performance budgets ([09 §Q-3](09-quality-and-release.md#q-3-performance-budgets)) are met.
- [ ] Third-party licence notices are bundled ([09 §Licensing](09-quality-and-release.md#licensing)).
- [ ] The release's notices name its sources release, and that release has the corresponding
      source of every GPL and LGPL part
      ([decision 0073](../decisions/0073-gpl-corresponding-source-per-tool-pin.md)).
- [ ] User docs: quick start, presets, batch mode, keyboard shortcuts.

## After v1

In rough priority order: Blu-ray/DVD folder input · HandBrake preset import · HDR10+/Dolby
Vision tooling · VMAF/SSIM after encode · watch folders (web) · subtitle OCR · chunked encoding
· macOS build. See [01-scope.md §Later](01-scope.md#later-post-v1).
