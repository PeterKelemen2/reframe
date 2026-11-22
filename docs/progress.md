# Progress summary

A short summary of [status.md](status.md) and the M10 release checklist in
[plan/08-roadmap.md](plan/08-roadmap.md#release-checklist). Read this file for "where are
we" and "what is next"; read `status.md` for the details of a step.

Snapshot: 2026-11-21, branch `m10-hardening` (about 530 commits ahead of `main`, not merged,
nothing pushed). The repository lives in `/mnt/Data/Programming/reframe`;
`~/Programming/reframe` is a link to it. Update this file when a checklist item or a step below changes.

## Overall: about 96 % done

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
| **M10 Hardening and v1.0** | **about 85 %** | On `m10-hardening`, not merged |

## Steps

| Area | Done | Not done |
|---|---|---|
| Core `C-0` to `C-21` | 22 / 22 | — |
| Server `S-0` to `S-8` | 9 / 9 | — (S-6's Intel QSV and NVIDIA NVENC checks in Docker done: [0099](decisions/0099-intel-qsv-on-linux.md), [0102](decisions/0102-nvenc-on-linux.md)) |
| Frontend `F-0` to `F-20` | 21 / 21 | — |
| Desktop `D-0` to `D-10` | 10.5 / 11 | D-8 partial: no GitHub release made; the AppImage's GStreamer plugins and desktop entry ([0103](decisions/0103-owner-decisions-before-v1.md)). The AppImage and .deb with Intel QSV on Linux checked, five defects fixed on `desktop-qsv-linux` ([0100](decisions/0100-desktop-app-with-intel-qsv-on-linux.md)) |
| Quality `Q-x` (43 sub-steps) | about 40 / 43 | Q-2.4 (optional local samples suite) not started; Q-3 partial; Q-1.1 to Q-1.3 written but never run on GitHub |

By step count about 102.5 of 106 (97 %). The overall figure is lower because the open items
are release work, where problems usually show up.

## M10 release checklist (2 of 9 done)

- [x] Q-6 Tier A simplification.
- [x] **Must-have audit** ([audit/must-have-audit.md](audit/must-have-audit.md), 2026-11-18):
      205 items, every one run against its demo and verified by a second pass. 186 pass,
      **0 fail**, 16 partial, 3 not checkable (NVENC/QSV, Windows). The partials are gaps
      against the plan's wording; the largest is C-18 (a batch group does not detect the crop
      per file, so letterboxed episodes are encoded uncropped). The owner decides which to fix.
- [ ] **Docker image published**: the image is built (S-6). Publishing it is open (Intel QSV
      checked on a UHD 620, 0099; NVIDIA NVENC on a GTX 1050 Ti, 0102).
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

Done: the changes of [decision 0103](decisions/0103-owner-decisions-before-v1.md) (items 1–13,
the AppImage's decoders, software AV1), two reviews and their fix round (2026-11-21). The
release secrets are set and the public keys committed ([release.md](release.md)).

1. **Push `m10-hardening` (the owner), then the first CI run** and its fix round. No tag: the
   owner makes more changes before a release.
2. **User docs**, so they describe what ships (with the Windows Detelecine crash and the
   AppImage's preview codecs as known limits).
3. **The four open licence-text groups.**
4. **A pre-release tag** when the owner decides, to try the release pipeline.
5. **Merge `m10-hardening` into `main`** when the checklist is done.

## Open owner decisions

None: decision [0103](decisions/0103-owner-decisions-before-v1.md) and its follow-ups settled them
(2026-11-20, 2026-11-21).

Known flaky under the full parallel suite (they pass alone): `test_subtitles.py`
`test_a_sup_file_is_a_bitmap_counted_in_display_sets` and `…_broken_blocks_the_job[cp1250]`,
`test_tasks.py::test_only_the_server_folders_are_hidden`.

## After v1 (does not block the release)

- A layout for windows below 1100×700.
- NVENC on Turing and newer GPUs and with the `default` build (driver 610+); QSV on Tiger Lake and newer Intel GPUs.
- Q-2.4, the local samples suite (optional).
- The Windows cold start on slow machines (known limit).
- The roadmap's post-v1 list: Blu-ray/DVD folders, HandBrake preset import, HDR10+/Dolby
  Vision tooling, VMAF/SSIM, watch folders, subtitle OCR, chunked encoding, macOS.
