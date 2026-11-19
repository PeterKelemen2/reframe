# Progress summary

A short summary of [status.md](status.md) and the M10 release checklist in
[plan/08-roadmap.md](plan/08-roadmap.md#release-checklist). Read this file for "where are
we" and "what is next"; read `status.md` for the details of a step.

Snapshot: 2026-11-18, branch `m10-hardening` at `a9311aa2` (387 commits ahead of `main` with
the audit's last commit, not merged, nothing pushed). Update this file when a checklist item or a step below changes.

## Overall: about 93–95 % done

The product is built. What is left is mostly the release itself: push, run CI and the
release pipeline on GitHub for the first time, write the user docs, and the checks that need
hardware the owner does not have.

## Milestones

| Milestone | Progress | State |
|---|---|---|
| M0–M2 Foundations, read media, CLI encode | 100 % | Merged into `main` |
| M3 / M3b API, desktop spike, shared queue | 100 % | Merged |
| M4 Web frontend MVP | 100 % | Merged |
| M5 Desktop shell | 100 % | Merged |
| M6–M9 Tracks, batch, picture, advanced options | 100 % | Merged |
| **M10 Hardening and v1.0** | **about 75–80 %** | On `m10-hardening`, not merged |

## Steps

| Area | Done | Not done |
|---|---|---|
| Core `C-0` to `C-21` | 21 / 22 | C-21 (FFmpeg builds, 0093) |
| Server `S-0` to `S-8` | 8 / 9 | S-8 (FFmpeg builds API, 0093); S-6's NVIDIA NVENC check in Docker (waits for such a host; Intel QSV checked, [0099](decisions/0099-intel-qsv-on-linux.md)) |
| Frontend `F-0` to `F-20` | 20 / 21 | F-20 (build picker, 0093) |
| Desktop `D-0` to `D-10` | 9.5 / 11 | D-8 partial: no GitHub release made; D-10 (packages without FFmpeg, 0093). The AppImage and .deb with Intel QSV on Linux checked, five defects fixed on `desktop-qsv-linux` ([0100](decisions/0100-desktop-app-with-intel-qsv-on-linux.md)) |
| Quality `Q-x` (43 sub-steps) | about 40 / 43 | Q-2.4 (optional local samples suite) not started; Q-3 partial; Q-1.1 to Q-1.3 written but never run on GitHub |

By step count about 98 of 102 (96 %). The overall figure is lower because the open items
are release work, where problems usually show up.

## M10 release checklist (2 of 9 done)

- [x] Q-6 Tier A simplification.
- [x] **Must-have audit** ([audit/must-have-audit.md](audit/must-have-audit.md), 2026-11-18):
      205 items, every one run against its demo and verified by a second pass. 186 pass,
      **0 fail**, 16 partial, 3 not checkable (NVENC/QSV, Windows). The partials are gaps
      against the plan's wording; the largest is C-18 (a batch group does not detect the crop
      per file, so letterboxed episodes are encoded uncropped). The owner decides which to fix.
- [ ] **Docker image published**: the image is built (S-6). Publishing it and the NVENC
      check are open (Intel QSV checked on a UHD 620, 0099).
- [ ] **Installers on a GitHub release**: AppImage, deb, rpm, NSIS and MSI build and pass
      their install tests. No release made; signing used a test certificate.
- [ ] **Updater picks up a test release**: works against a local test release. A real
      GitHub release and the Linux update path are not tested.
- [ ] **Performance budgets met**: the Windows cold start meets 2 s on a desktop CPU
      (1.38 s) and misses it on a slow laptop (about 4.7 s); a known limit
      ([0071](decisions/0071-server-start-and-windows-cold-start.md)).
- [ ] **Third-party licence notices bundled**: generated and shipped; four licence-text
      groups are still open.
- [ ] **GPL sources release named in the notices**: built in Q-5, never run.
- [ ] **User docs** (quick start, presets, batch mode, keyboard shortcuts): **not
      started**. The largest piece of real work left.

Then merge `m10-hardening` into `main`.

## Biggest risk

Nothing is pushed, so GitHub Actions has never run. The CI matrix, Dependabot and the
audits, the release workflow and the D-9 smoke-test job were only run locally or checked
with `actionlint`. Expect a round of fixes on the first run.

## Recommended order of work

1. **The audit's partials the owner chooses to fix** (the audit's suggested order: C-18 batch
   crop per file, D-17 power actions in Docker, A-76 *Align A/V start* does nothing, B-39
   track name templates written literally, A-35 / A-27 encoder errors, then the small ones),
   and a plan update for the out-of-date plan text the audit lists.
2. **FFmpeg download and build choice** (C-21, S-8, F-20, D-10,
   [decision 0093](decisions/0093-ffmpeg-download-and-build-choice.md)): the desktop packages
   stop bundling FFmpeg; the first run offers pinned builds (`default`, and `compat` for
   NVIDIA drivers 570 to 609), install from a file, or the user's own path; a warning when
   an encoder is unavailable because the system does not fit the build.
3. **User docs**, after those fixes, so they describe what ships.
4. **The four open licence-text groups**.
5. **Push decision (the owner's), then the first CI run**. This unblocks CI, the release
   workflow, the real updater test, the Docker image and the GitHub release. A pre-release
   tag (for example `v1.0.0-rc.1`) tests the whole pipeline without committing to v1.
6. **Merge `m10-hardening` into `main`** when the checklist is done.

## Open owner decisions (none blocks work)

- Decision [0089](decisions/0089-folder-probe-and-language-list-removed.md): the
  language-list choice.
- `output.default_container` is stored but nothing reads it: wire it or remove it.
- The Windows FFmpeg build (BtbN n9.0.2) crashes now and then with Detelecine: report it
  upstream or try another build.
- A layout for windows below about 1100×700: after v1 (the default) or before.
- Decision [0100](decisions/0100-desktop-app-with-intel-qsv-on-linux.md): bundle GStreamer plugins into the AppImage so that preview clips play in its window (size, LGPL notices, the AppImage's source manifest), or keep the frame compare there; and whether the AppImage should install a desktop entry (taskbar progress).

## After v1 (does not block the release)

- S-6's NVENC check in Docker (needs the hardware); QSV on Tiger Lake and newer Intel GPUs.
- Q-2.4, the local samples suite (optional).
- The Windows cold start on slow machines (known limit).
- The roadmap's post-v1 list: Blu-ray/DVD folders, HandBrake preset import, HDR10+/Dolby
  Vision tooling, VMAF/SSIM, watch folders, subtitle OCR, chunked encoding, macOS.
