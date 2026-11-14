# 09 — Quality and Release

## Q-1 Continuous integration

- [ ] **Q-1.1** GitHub Actions matrix: `ubuntu-latest` and `windows-latest`.
  - Python: `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy` (strict on
    `reframe`), `pytest -m "not needs_gpu"`.
  - Frontend: `npm ci`, `oxlint`, `oxfmt --check`, `vue-tsc --noEmit`, `vitest run`.
- [ ] **Q-1.2** FFmpeg in CI: the same pinned build that ships, from `tools/ffmpeg.toml`
      ([02 §Bundled FFmpeg](02-architecture.md#bundled-ffmpeg)). Cached and checksum-verified,
      so tests run against the shipped binaries and do not change when the runner image changes.
      One extra job tests the override path with a different FFmpeg build.
- [ ] **Q-1.3** Dependency updates (Renovate or Dependabot), `pip-audit`, `npm audit` (high
      severity fails the build).
- [ ] **Q-1.4** Windows verification run
      ([decision 0043](../decisions/0043-plan-review-before-m3.md) item 1). Nothing is pushed,
      so GitHub Actions does not run. The Python and frontend commands of `ci.yml` run on
      Windows 10 or 11 by another route: by default a Windows machine or VM that the owner
      provides; a push to a private remote only if the owner allows it (01 open question 5).
      Done when: the commands pass on Windows, or each failure is fixed or recorded; the
      date, the machine and the result are in `docs/status.md`. It runs once, in the
      [Windows testing phase](08-roadmap.md#windows-testing-phase) at the start of M10
      ([decision 0053](../decisions/0053-linux-first-windows-testing-phase.md)); no earlier
      milestone waits for it.

## Q-2 Test strategy

| Layer | Tool | What | Where |
|-------|------|------|-------|
| Pure units | pytest + hypothesis | dimensions, fingerprints, rule resolution, language mapping, progress parser | `C-5`, `C-12`, `C-6`, `C-11` |
| Snapshots | syrupy | `MediaSource` from recorded ffprobe JSON, `EncodePlan` for ≥ 40 jobs, JSON Schemas | `C-2`, `C-3`, `C-7` |
| Integration | pytest + real FFmpeg | encode fixtures and re-probe the outputs. Queue lifecycle. Metadata edits | `C-7`, `C-11`, `C-13` |
| Fault injection | **fake FFmpeg** | a small Python script in the place of `ffmpeg`/`ffprobe` that sleeps, hangs, crashes, or prints driver errors. Selected by env var | `C-1`, `C-4`, `C-11` |
| API | httpx AsyncClient + WebSocket test client | every route, auth, path jail, event coalescing | `S-1`–`S-3` |
| Frontend units | Vitest + Vue Test Utils | stores, `Field`, `CropMagnifier` maths, `LanguagePicker` search | `F-*` |
| End-to-end | Playwright (Chromium + WebKit) | the 4 flows in `F-17`, each added in the milestone of its screens (M4, M6, M7, M8) | `F-17` |
| Desktop smoke | tauri-driver | start, open, encode, quit with no orphan processes | `D-9` |
| GPU | manual / self-hosted runner, `needs_gpu` marker | NVENC, QSV, VAAPI detection and short encodes | `C-4` |

- [ ] **Q-2.1** Fixture generator (below) and the fake FFmpeg.
- [ ] **Q-2.2** Recorded real-world ffprobe JSON in `testdata/probes/` (anonymised file names),
      for codecs that cannot be generated (TrueHD Atmos, DTS:X, PGS, DV). Until true recordings
      exist, these are synthesised from real output: the real ffprobe JSON of the closest file
      FFmpeg can make, with only the fields FFmpeg cannot generate edited, each edit documented
      in `testdata/probes/index.json` (decision 0006).
- [ ] **Q-2.3** API contract check: regenerate `schema.d.ts` and fail on any diff.
- [ ] **Q-2.4** Optional local suite on your own files: `REFRAME_SAMPLES=/path pytest -m samples`.
      It is never run in CI.

### Test media

`scripts/make-testdata.py` generates small files (≤ 5 s, low resolution) with FFmpeg `lavfi`
sources, so the repository holds no large binaries. One fixture is 4K on purpose: the HDR10
source of the C-10 frame budget (`hdr10-4k`, about 6 MB, generated and never committed;
[decision 0030](../decisions/0030-core-complete-contract.md)):

| Fixture | How |
|---------|-----|
| Multi-track MKV | `testsrc2` + several `sine` tracks (a different tone per track) with languages, titles and dispositions (`default`, `comment`, `hearing_impaired`) |
| Text subtitles | SRT/ASS generated from text templates. ASS with an attached open-licence font |
| Bitmap subtitles | VobSub (`dvdsub` encoder). PGS written as `.sup` by `reframe_testing/pgs.py` (FFmpeg has no PGS encoder), with forced and non-forced events ([0032](../decisions/0032-analysis-scans-and-their-fixtures.md)) |
| Lossless audio without a bit rate | DTS-HD MA 5.1 (XLL, no core) written by `reframe_testing/dts.py` (FFmpeg's `dca` encoder writes a DTS core only), copied into Matroska, which has no statistics tags (M6 demo 1; [0032](../decisions/0032-analysis-scans-and-their-fixtures.md)) |
| Letterbox / changing aspect | `testsrc2` padded with black bars. A second segment with different bars, concatenated |
| Anamorphic | 720×480 with SAR 32:27 |
| Interlaced | `interlace` filter + `setfield=tff` |
| VFR | concatenated segments at different frame rates |
| HDR10 | 10-bit x265 with `master-display` / `max-cll` |
| Chapters | FFMETADATA input |
| Season set | 12 copies of the multi-track MKV. One has an extra commentary track. One is missing the second audio track. Names follow `Show.S01E01.Title.mkv` |
| Batch example seasons | 04 §Example: 12 episodes with `jpn` TrueHD 5.1 (FFmpeg makes no 7.1 and no Atmos), `eng` DTS-HD MA 5.1, ASS "Signs & Songs" (forced) and "Full"; E05 with an extra commentary, E11 without the dub and with another signs title; a second season of 3 episodes ([0040](../decisions/0040-batch-engine-and-reframe-batch.md)) |

## Q-3 Performance budgets

| Operation | Budget |
|-----------|--------|
| Server ready (web) | < 1 s (encoder detection runs after) |
| Desktop cold start to interactive UI | < 2 s on SSD |
| Probe of one local file | < 500 ms |
| Probe of a 24-file season folder | < 5 s |
| Source frame (4K) | < 2 s cold, < 50 ms cached |
| `jobs/validate` server time | < 50 ms |
| UI reaction to an edit | < 100 ms (validation is debounced and async) |
| Events during a 4-job parallel encode | ≤ 4 progress messages per second per job |

The desktop cold start holds on Linux (1.07 s) and on a Windows 10 VM on a desktop CPU
(1.38 s median, 6 processors). On a Windows 10 VM on a laptop CPU it took about 4.7 s, a known
limit for slow machines ([decision 0071](../decisions/0071-server-start-and-windows-cold-start.md),
"Follow-up").

Benchmarks run in CI as a non-blocking job. A regression of more than 20 % comments on the PR.

## Q-4 Logging and diagnostics

- [x] Structured logs (JSON lines) in `<data>/logs/reframe.log`, with rotation. Log level is set
      in Settings.
- [x] Per-job logs (`C-11`), sidecar log (`D-3`).
- [x] **Copy diagnostics** in Settings: app version, OS, tool versions and build flags, encoder
      statuses with reasons, settings with secrets removed. Used in bug reports.

(How: [decision 0078](../decisions/0078-q4-logging-and-diagnostics.md): only the server writes
`reframe.log`; the level is `AppSettings.diagnostics.log_level`; `GET /api/diagnostics`.)

## Q-5 Release process

- [ ] Semantic versioning. One version source (core `__version__`). The server, frontend and
      Tauri versions are stamped from it at build time.
- [ ] Changelog from conventional commits (the step ID as scope: `fix(F-17): …`), made by git-cliff.
- [ ] A release workflow on tag `v*` builds:
  - Docker image → GHCR (`linux/amd64`, `linux/arm64` without HW encoders).
  - Windows NSIS (+ MSI) and Linux AppImage/deb/rpm → GitHub Release, signed.
  - Updater manifest `latest.json`.
  - The sources release of [decision 0073](../decisions/0073-gpl-corresponding-source-per-tool-pin.md),
    made before the packages if its manifest's hash is new, never "latest", and named in
    `THIRD_PARTY_NOTICES`.
  - Optional: `reframe` wheel to PyPI, so others can script against the core. **Not for v1**
    (the core's API is not promised as stable).

(How: [decision 0079](../decisions/0079-q5-release-process.md).)

## Licensing

This is not legal advice. Review it before any public or commercial distribution.

| Component | Licence | Effect |
|-----------|---------|--------|
| FFmpeg GPL build (with x264, x265) | GPL-2.0+/GPL-3.0 | **Every artefact bundles it**: the Docker image, AppImage, .deb, .rpm and the Windows installer. Each must include the licence and the corresponding source (or a written offer) **for the exact build that ships** |
| `libfdk_aac` | Not redistributable with GPL builds | **Never bundled.** It is used only if the user's own FFmpeg has it |
| MKVToolNix | GPL-2.0 | **Not bundled**: its Windows build links OpenSSL (Apache-2.0) into GPL-2.0-only code ([decision 0079](../decisions/0079-q5-release-process.md) item 11). Users install it |
| MediaInfo | BSD-2-Clause | Notice required |
| guessit, rebulk | LGPL-3.0 | Compatible with a GPL app. Notice required |
| Tauri, Vue, PrimeVue, FastAPI, Pydantic | MIT / Apache-2.0 | Notices required |

- [ ] Recommended licence for Reframe: **GPL-3.0-or-later** (open question 2 in
      [01-scope.md](01-scope.md#open-questions-owner-to-decide)).
- [ ] CI generates `THIRD_PARTY_NOTICES` (`pip-licenses`, `license-checker`, `cargo about`) and
      bundles it with every artefact. It also writes source links for the bundled tool builds.
      **Built, not in CI yet**: `scripts/third-party-notices.py` is run by the package builds
      before `tauri build` (`desktop/packaging/linux/build.sh`, and the Windows build) and ships
      as `notices/THIRD_PARTY_NOTICES` next to `sidecar/` and `tools/`; checked in the Linux
      packages and the Windows installers ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md)
      tasks L and W). Q-5 ([decision 0079](../decisions/0079-q5-release-process.md)): the Docker
      image carries it too, with a list of its Debian packages and their source links; the
      release workflow runs every build (not run on GitHub yet).
- [ ] **The corresponding source** of the GPL parts (FFmpeg and the libraries the BtbN build
      links), or a written offer, ships with each release. The notices
      give only repository and commit links today. Decided
      ([decision 0073](../decisions/0073-gpl-corresponding-source-per-tool-pin.md)): one
      sources release for each set of pinned source versions, named by the hash of a source
      manifest. Each app release's notices link to it. There is no written offer. Built by Q-5
      (`scripts/sources-manifest.py`, `scripts/sources-fetch.py`; 0079 "Task S").
