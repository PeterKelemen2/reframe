# 09 — Quality and Release

## Q-1 Continuous integration

- [ ] **Q-1.1** GitHub Actions matrix: `ubuntu-latest` and `windows-latest`.
  - Python: `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy` (strict on
    `reframe`), `pytest -m "not needs_gpu"`. Python 3.14 runs it in three parts per platform,
    with a worker per vCPU; Python 3.13 (Linux) leaves out the `needs_ffmpeg` tests
    ([decision 0104](../decisions/0104-faster-ci-test-runs.md)).
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

Every pytest run is parallel: `pytest-xdist` `-n auto` is in `addopts` (a full run takes about 6
minutes on 12 cores instead of about 35; `-n auto` starts one worker per physical core, 6 there,
[decision 0091](../decisions/0091-test-trimming-step.md)). `-n 0` runs in one process. The `benchmark` tests skip
under xdist and run in one process (`-n 0`) in the CI benchmark job
([decision 0084](../decisions/0084-parallel-test-runs-with-pytest-xdist.md)).

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

- [x] Semantic versioning. One version source (core `__version__`). The server, frontend and
      Tauri versions are stamped from it at build time.
- [x] Changelog from conventional commits (the step ID as scope: `fix(F-17): …`), made by git-cliff.
- [x] A release workflow on tag `v*` builds (built and tested locally; not run on GitHub yet):
  - Docker image → GHCR (`linux/amd64`, `linux/arm64` without HW encoders).
  - Windows NSIS (+ MSI) and Linux AppImage/deb/rpm → GitHub Release; the Windows installers
    of v1 are unsigned ([decision 0105](../decisions/0105-release-rehearsal-and-unsigned-windows-installers.md)),
    the release's checksums are GPG-signed.
  - Updater manifest `latest.json`.
  - The sources release of [decision 0073](../decisions/0073-gpl-corresponding-source-per-tool-pin.md),
    made before the packages if its manifest's hash is new, never "latest", and named in
    `THIRD_PARTY_NOTICES`.
  - Optional: `reframe` wheel to PyPI, so others can script against the core. **Not for v1**
    (the core's API is not promised as stable).

(How: [decision 0079](../decisions/0079-q5-release-process.md).)

## Q-6 Simplification

Before the release checklist, remove the code in the core and the server that is more complex
than the plan and the decision records need ([decision 0083](../decisions/0083-simplification-step-before-v1.md)).
An audit at commit `85d9dcb` found the candidates and planned the work:
[docs/simplify/](../simplify/README.md). Each step below is one work package of
[docs/simplify/plan.md](../simplify/plan.md); the package lists its findings, files, order and
its full "Done when". Every step keeps behaviour unless its findings say otherwise, and is done
when the `CLAUDE.md` commands pass, the guard tests its findings name pass, and `docs/status.md`
has its row.

Tier A (before v1):

- [x] **Q-6.1** Test module loaders (X-04). Done when: the batch and validation tests pass, also
      one file run alone, with the same test count.
- [x] **Q-6.2** Shared test helpers (MOD-08, NDP-05, PRB-07, SRV-05, TP-04). Done when: the test
      count of `packages/` is unchanged and the real-bus sleep test was run once.
- [x] **Q-6.3** CLI (CLI-01, -02, -04, -05, -06, -07, -08, -10, -11, -12). Done when: every CLI
      output test passes unchanged and the `--help` texts are the same.
- [x] **Q-6.4** Definitions and analysis (NDP-01, -02, -03, -06, -08). Done when: the linter
      runs from `testing/reframe_testing` and the shipped package no longer contains it.
- [x] **Q-6.5** Validation (VAL-01, -04, -05, -08). Done when: the template, custom-parameter and
      agreement tests pass and every fix target is unchanged.
- [x] **Q-6.6** Batch (BAT-07, -08, -09, -10, -11). Done when: the anime-season snapshot, the
      batch property tests and the CLI batch tests pass unchanged.
- [x] **Q-6.7** Tools discovery and small dead members (TP-02, TP-07, MOD-06). Done when:
      `python -m reframe.tools` prints the same result.
- [x] **Q-6.8** Probe (PRB-04, -09, -10, -13). Done when: the JSON Schema snapshot does not
      change and the folder task test passes.
- [x] **Q-6.9** Queue, jobs and tasks (QJ-04, -05, -06, -08, -09, -11, TP-08). Done when: the
      queue's fault and stop tests pass and `scripts/gen-api.sh --check` shows no change.
- [x] **Q-6.10** Command, capabilities and shared tables (X-01, X-05, X-06, CMD-02, -04, -05,
      -06). Done when: the 73 plan snapshots pass without an update.

Tier B (if there is time before v1; otherwise after it):

- [x] **Q-6.11** Settings and preset stores (X-07, MOD-01, -03, -05; a decision record). Done
      when: every damaged, newer and too-deep file test passes with the same warning codes.
- [x] **Q-6.12** Windows-only paths (X-02, TP-14, TP-15). Done when: the retry, settings, queue,
      presets, platform and owner tests pass **on the Windows test VM**.
- [x] **Q-6.13** Probe and metadata (X-08, X-09, PRB-02, -03, -08, -12, -14). Done when: the
      probe snapshot diff shows only `probe_hash` and the header writer's torn-write tests pass.
- [x] **Q-6.14** Folder probe, language list, server leftovers (SRV-01, -02, -08; a decision
      record). Done when: `GET /api/languages` returns the same bytes, the jail tests pass and a
      cancelled probe task leaves no ffprobe running.
- [x] **Q-6.15** Batch API and the draft path (X-03, BAT-01, -02, -03, -12; a decision record).
      Done when: the "one issue per problem" tests and the client-mode tests pass.
- [x] **Q-6.16** Validation rules (VAL-03, -06, -07, -09, -12; a decision record). Done when:
      the command, queue and validation tests pass and template issue order is unchanged.
- [x] **Q-6.17** Tool runner and platform (TP-03, -06, -09). Done when: the real-bus sleep test
      passes on this machine.
- [x] **Q-6.18** Task manager and capability service (QJ-01, QJ-10, CMD-07). Done when: the task
      order and cancel-race tests pass.
- [x] **Q-6.19** Definitions fields (NDP-04, NDP-11). Done when: `scripts/gen-api.sh --check` and
      the frontend commands pass.

Tier C findings are not planned; they are listed in [docs/simplify/README.md](../simplify/README.md).

## Q-7 Test trimming

Make the Python suite smaller and faster without losing a guarantee: remove or merge the tests
whose guarantee another test already gives, and change how the suite is scheduled
([decision 0091](../decisions/0091-test-trimming-step.md)). An audit at commit `38cf3eb` found the
candidates and planned the work: [docs/test-audit/](../test-audit/README.md). Each step below is
one work package of [docs/test-audit/plan.md](../test-audit/plan.md); the package lists its
findings, files, order and its full "Done when". Every step is done when the `CLAUDE.md`
commands pass, the whole-run coverage comparison of the plan shows no lost line of `reframe` or
`reframe_server` (or names it and the test that still pins it), and `docs/status.md` has its row.
Q-7 does not block the release.

Tier A:

- [x] **Q-7.1** Validation and batch (TVL-03, -05, -06, -08; TBT-01 to -04).
- [x] **Q-7.2** Queue and analysis (TQA-01 to -09). Done when: the queue tests pass 5 times in a
      row and the verdicts' mutations still fail the merged tests.
- [x] **Q-7.3** Probe, metadata and languages (TPM-04 to -08, -14, -15).
- [x] **Q-7.4** Command, capabilities, dimensions and definitions (TCD-01 to -05, -09, -11; TDM-02,
      -04). Done when: the plan snapshots are unchanged.
- [x] **Q-7.5** Server, CLI, naming and preview (TSV-01, -02; TCL-01, -04; TNP-01 to -03).
- [x] **Q-7.6** Tools, platform and the testing package (TTP-01, -03 to -05; TTK-01, -03 to -05,
      -07, -09 to -12).
- [x] **Q-7.7** Speed (SPD-01, -02, -04 on POSIX, -07; TPM-01; the fetch server's poll). Done when:
      two full runs on an idle machine pass with the base's count plus 10 and take about 295 s at
      the base of `38cf3eb` (373 s before).

Tier B:

- [x] **Q-7.8** Validation grids and cases (TVL-01, -02, -04, -07, -09 to -12). Done when: the
      strengthened agreement matrix fails on every mutation of the TVL-02 verdict.
- [x] **Q-7.9** One validity test per built-in preset (TDM-01, -03). Done when: each planted preset
      defect fails the merged test and is reported on its own.
- [x] **Q-7.10** Server, CLI, naming and preview merges (TSV-03 to -07; TCL-02, -05 to -08; TNP-04,
      -05).
- [x] **Q-7.11** Batch, command and probe merges (TBT-05 to -07; TCD-07, -08, -10; TPM-02, -09 to
      -11, -13, -16).
- [x] **Q-7.12** Shared helpers in tools, platform and the testing package (TTP-06 to -08; TTK-06,
      -13).
- [x] **Q-7.13** Speed (SPD-05, the per-test timeout; SPD-08; the Windows half of SPD-04 on the
      Windows test VM). Done when: a hanging test ends its worker with a stack dump and the run
      goes on.

Tier C findings are not planned; they are listed in [docs/test-audit/README.md](../test-audit/README.md).

## Licensing

This is not legal advice. Review it before any public or commercial distribution.

| Component | Licence | Effect |
|-----------|---------|--------|
| FFmpeg GPL build (with x264, x265) | GPL-2.0+/GPL-3.0 | **No artefact contains it**: the desktop app and the Docker image download it from BtbN's release at the user's request (or the server's `REFRAME_FFMPEG_BUILD`) and show its licence and source links first ([decisions 0093](../decisions/0093-ffmpeg-download-and-build-choice.md), [0094](../decisions/0094-docker-image-without-ffmpeg.md)) |
| `libfdk_aac` | Not redistributable with GPL builds | **Never bundled.** It is used only if the user's own FFmpeg has it |
| MKVToolNix | GPL-2.0 | **Not bundled and not run** by the product: since C-18 Reframe writes the Matroska headers itself ([decision 0080](../decisions/0080-own-matroska-header-writer.md)); tests use it as an oracle. Its Windows build links OpenSSL (Apache-2.0) into GPL-2.0-only code ([decision 0079](../decisions/0079-q5-release-process.md) item 11) |
| MediaInfo | BSD-2-Clause | Notice required until C-19; then **not bundled and not used** ([decision 0081](../decisions/0081-probe-without-mediainfo.md)) |
| guessit, rebulk | LGPL-3.0 | Compatible with a GPL app. Notice required |
| CLDR and IANA language subtag registry data (the generated language table) | Unicode licence (CLDR); the registry is IANA's | Notice required. Replaces the entries of `langcodes`, `language_data` and `marisa-trie` ([decision 0082](../decisions/0082-own-language-data-table.md)); confirm the exact licence text from the CLDR release that the table is built from |
| Tauri, Vue, PrimeVue, FastAPI, Pydantic | MIT / Apache-2.0 | Notices required |

- [x] Recommended licence for Reframe: **GPL-3.0-or-later** (open question 2 in
      [01-scope.md](01-scope.md#open-questions-owner-to-decide)).
- [x] CI generates `THIRD_PARTY_NOTICES` (`pip-licenses`, `license-checker`, `cargo about`) and
      bundles it with every artefact. It also writes source links for the bundled tool builds,
      and the full licence text of every bundled part (the owner's answer,
      [decision 0079](../decisions/0079-q5-release-process.md) item 11, "Fix round — FL"; the
      parts still without one are listed there and are open items for v1, item 12).
      **Built**: `scripts/third-party-notices.py` is run by the package builds
      before `tauri build` (`desktop/packaging/linux/build.sh`, and the Windows build) and ships
      as `notices/THIRD_PARTY_NOTICES` next to `sidecar/` and `tools/`; checked in the Linux
      packages and the Windows installers ([decision 0072](../decisions/0072-m10-bundling-packaging-smoke-tests.md)
      tasks L and W). Q-5 ([decision 0079](../decisions/0079-q5-release-process.md)): the Docker
      image carries it too, with a list of its Debian packages and their source links; the
      release workflow runs every build (not run on GitHub yet).
- [x] **The corresponding source** of the GPL parts (FFmpeg and the libraries the BtbN build
      links), or a written offer, ships with each release. The notices
      give only repository and commit links today. Decided
      ([decision 0073](../decisions/0073-gpl-corresponding-source-per-tool-pin.md)): one
      sources release for each set of pinned source versions, named by the hash of a source
      manifest. Each app release's notices link to it. There is no written offer. Built by Q-5
      (`scripts/sources-manifest.py`, `scripts/sources-fetch.py`; 0079 "Task S"); the
      release workflow makes it (not run on GitHub yet).
