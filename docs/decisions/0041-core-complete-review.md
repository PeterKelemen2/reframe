# 0041 — The core-complete review: findings and what was done with each

- Status: accepted
- Date: 2026-10-16
- Steps: C-3, C-6, C-8, C-10, C-11, C-12, C-13, C-14, C-15

## Context

[0029](0029-core-before-the-ui-milestones.md) merges `core-complete` into `main` only after a
fresh review's findings are fixed. `git diff main...core-complete` is about 53 000 added lines
(224 files) after the batch engine (2a, [0040](0040-batch-engine-and-reframe-batch.md)) was
merged, too much for one reviewer. Five fresh reviewers (`xhigh`) each took one area, on
`core-complete` at 3cde317:

| Reviewer | Area |
|----------|------|
| R1 | C-12 M6: the selection stage, `explain`, the defaults lint, `JobService.draft` / `explain` |
| R2 | C-12 M7 and C-15 `batch`: descriptors, grouping, rules, derive / merge, overrides, resolution, `Reframe.batch`, `reframe batch` |
| R3 | C-10: the scans, frames, crop detection, preview clips, the frame cache |
| R4 | C-13, C-11 (core-complete parts), C-14: in-place edits, the queue's keys, the Matroska reader, when-done, power actions |
| R5 | C-6 option sets and C-8 option rules, the dry run, C-15 `tools` / `presets`, the 1i small fixes |

Each finding came with a reproduction (a failing test or a command with its real output). The
lead ran the reproduction of every blocker and major again on 3cde317 before deciding.

Severities: **blocker**: a wrong output file, a source or user file damaged or removed, a hang,
a crash on valid input, a power action reachable from a test, a security hole. **Major**: a
"Done when" line not met, a broken contract or `CLAUDE.md` rule, a wrong result the user sees.
**Minor**: the rest.

## Decision

Every blocker and major is fixed; each minor that is cheap is fixed too. One fix agent per
group of steps; every fix has a test that fails before it and passes after it, and a dated
"Follow-up (core-complete review, 2026-10-16)" section in its step's decision record.

### Findings

`file:line` is on 3cde317. "Group" names the fix agent: **A** C-12 selection stage (0031), **B**
C-12 batch engine and C-15 `reframe batch` / `plan` (0040, 0038), **C** C-10 (0032, 0033),
**D** C-13 / C-11 / C-3 (0034, 0016, 0007), **E** C-6 / C-8 / C-15 `tools` / `presets` (0035,
0014, 0038). Duplicates were merged: R2-8 into R1-5 (the same stale feature row); R1-4 and R2-5
(both at `jobs.py:334`) go to one agent.

**Blockers (4)** — the first three reproduced by the lead on 3cde317, the fourth measured by fix agent D:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-1 | C-12 | `batch/selection.py:386` | "No listed language found" counts commentary / description tracks: a listed language with only an extra track never triggers `no_match`, and with `commentary="drop"` the draft has **no audio track and no issue** (the encode writes a file without audio). Reproduced: French film + English audio description, *H.265 MKV 1080p*, preferred audio `en` → `audio outputs: []`, `issues: []` | Fix (A): count main tracks only; 0031 §3 corrected |
| R2-1 | C-15 | `cli.py` `run_batch`, `batch/service.py` `_collisions` | Name collisions are checked per group only. With the collision setting *overwrite*, a job of one group **overwrites a source file of another group of the same run**; two outputs with one name lose the first. Reproduced: E01 of `anime-s01` and `multitrack.mkv` copied as `Anime.Show.S01E01.Pilot.mkv` → the second source's SHA-256 changed | Fix (B): the batch-level checks run over every group; `reframe encode` of several files checked for the same hole |
| R5-1 | C-6 / C-15 | `command/video.py:155-167`, `validation/dryrun.py:449`, `cli.py` plan | Custom parameters that make the encoder write a file (x265 `analysis-save`, `csv`; FFmpeg's `vstats_file` through the own-option path) pass validation, and `reframe plan` dry-runs every user preset with custom parameters: importing a shared preset and only **planning** with it overwrites any file the user can write. Reproduced: `victim.txt` became a 5984-byte x265 analysis file | Fix (E): a validation error for keys that name files, the dry run refuses them and runs in a temporary working folder |
| R4-7 | C-13 / C-11 | `queue/runner.py` (`run_streaming(cancel=…)` of the in-place step) | Found while checking a suspected item of R4: Reframe's own cancel, `close()` and the 5-minute step limit kill mkvpropedit while it edits the source in place. A kill late in the edit (after mkvpropedit voided the old `Tracks`, before the new one and its `SeekHead` entry were written) **destroyed the source's track headers in 3 of 900 runs** (ffprobe shows no streams); random kills (150 runs) had hit only the time before the first write | Fix (D, second round): a running in-place edit is never killed by a cancel or `close()`; the job's end state says whether the edit was written |

**Majors (12)** — all reproduced by the lead on 3cde317:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-2 | C-12 | `batch/explain.py:211` | `no_match="none"` with `other_languages` keep: tracks are taken, but the error `defaults.no_listed_language` keeps the job out of the queue | Fix (A) |
| R1-3 | C-12 | `batch/explain.py:138, 471, 497` | The default audio track, the foreign-audio burn-in target and the default subtitle track can be a kept commentary track (a commentary subtitle is burned in) | Fix (A) |
| R2-2 | C-12 | `batch/descriptors.py:220`, `derive.py:144`, `selectors.py:151` | Heuristic roles (event share, bit rate) are in fingerprints and derived selectors: one release splits, a derived rule is ✗ in the next episode | Fix (B): only flag / title evidence |
| R3-1 | C-10 | `analysis/bitrate.py:205`, `subtitles.py:391`, `service.py` `store` | Two scans of one file at once: the second store discards the first one's measured value | Fix (C) |
| R3-2 | C-10 | `analysis/subtitles.py:255-261` | MP4 `mov_text`: FFmpeg writes an empty sample for every gap, so the event count is about doubled (3 cues → 6) | Fix (C) |
| R4-1 | C-11 / C-13 | `queue/service.py:131-162` | The queue's job keys do not resolve links: an encode reads a source through a link while it is edited in place, two edits of one file run at once (20 of 100 real runs lost an edit), two outputs through a linked folder | Fix (D): keys on file identity |
| R4-2 | C-13 | `probe/matroska.py:275-281, 210-212` | A SeekHead position ≥ 2^63 raises `ValueError` out of `Reframe.sources.probe` ("unexpected error"); ffprobe reads the file | Fix (D) |
| R4-3 | C-13 / C-3 | `probe/prober.py:436-439, 484-487` | With MediaInfo, `language_ietf` holds MediaInfo's derived tag for tracks that have no `LanguageIETF` element (the lead saw it in demo 3: `en` where `mkvmerge -J` and `mkvinfo` show none). The re-probe check is not fooled | Fix (D): the Matroska reader's value wins, also `None` |
| R4-4 | C-13 | `probe/prober.py:484-487` | An invalid `LanguageIETF` in the file is stored unchecked; `reframe plan` then crashes with a `ValidationError` (reproduced) | Fix (D): only valid tags, else a probe warning |
| R5-2 | C-15 / C-6 | `jobs.py:485-487`, `cli.py:1220-1225` | `plan(dry_run=True)` drops the dry run's warnings (`dry_run_skipped`, `dry_run_warning`) and `reframe plan` says the parameters were checked when they were not | Fix (B) |
| R5-3 | C-6 | `validation/dryrun.py:186-206` | libvpx refuses a value through a codec control (`Failed to set VP8E_SET_ARNR_MAXFRAMES codec control`), FFmpeg exits 0: the dry run passes (reproduced with the pinned n9.0.2) | Fix (E) |
| R5-4 | C-8 | `validation/levels.py:50-52, 96-99` | `encoder.level_too_low` pads by preset, not by the `min-cu-size` option: validation passes a job x265 refuses and refuses one it accepts (checked with x265) | Fix (E) |

**Minors (22)**:

| ID | Step | Where | What is wrong | Decision |
|----|------|-------|---------------|----------|
| R1-4 | C-12 / C-15 | `jobs.py:334` | A codec the container cannot hold is reported twice in a draft | Fix (B) |
| R1-5 | docs | `status.md` C-12 row and feature row, 0031 | Stale "Open" / "Missing" text (also R2-8) | Fix (A, B) |
| R1-6 | C-12 / C-3 | `batch/explain.py:327-335`, `probe/roles.py:295` | A subtitle track with 0 events counts as "few events" (forced) | Fix (A) |
| R2-3 | C-12 | `batch/report.py:111-118` | An override that removes a rule shifts the row's cells under the wrong columns | Fix (B) |
| R2-4 | C-12 | `batch/grouping.py:160-172` | The loose level counts a changed track twice | Fix (B) |
| R2-5 | C-15 | `jobs.py:334` | `plan` / `encode` with a group preset drop the `batch.track_relaxed` / `ambiguous` / `skipped` warnings | Fix (B) |
| R2-6 | C-15 | `cli.py`, `batch/report.py:116` | Row labels without the season in a group that spans seasons | Fix (B) |
| R2-7 | C-15 | 0040 §6 | A re-run queues the earlier outputs again as a group of their own; §6 said it does not | Fix (B): outputs of the batch's own files are left out |
| R3-3 | C-10 | `preview/clip.py:165-170` | The clip id ignores the plan's files (renamed chapters give the stale clip) | Fix (C) |
| R3-4 | C-10 | `preview/frames.py:139-147` | A failing output chain loses the source frames too | Fix (C) |
| R3-5 | C-10 | `preview/frames.py:91`, 0033 §3 | The tone mapper (and the cache key) changes when detection ends, on every start (the notes are right) | Doc only (C): waiting for detection would delay the first frames |
| R3-6 | C-10 | `preview/common.py:171-184` | A timestamp ≥ 10^9 s fails with a traceback, not a message | Fix (C) |
| R3-7 | C-10 | `preview/clip.py:195-201` | Two identical clips at once share one temporary file | Fix (C) |
| R3-8 | docs | `testdata/README.md`, 0033 §1 | The cropdetect rounding example and a stale sentence | Fix (C) |
| R4-5 | C-13 | `probe/matroska.py:271-273, 294-309` | SeekHead entries are not bounded (67 MB crafted file: 17.7 s, 663 MB) | Fix (D) |
| R4-6 | C-13 | `tests/metadata/test_metadata_edit_real.py:154` | The demo-3 test does not assert the job type and the time | Fix (D) |
| R5-5 | C-15 | `tools/fetch.py:780-786` | A cancel during discovery after the swap says "Nothing was installed" although it was | Fix (E) |
| R5-6 | C-15 (test) | `tests/tools/test_fetch.py:343-352` | The test asserts step messages that coalescing can drop (the load-sensitive failure of the 2a merge); the progress never goes backwards | Fix (E) |
| R5-7 | C-8 | `validation/video.py:944` | `vbv-maxrate` without `vbv-bufsize` (or the reverse) is dropped by the encoder without a warning | Fix (E) |
| R5-8 | C-6 / C-8 | `validation/video.py:373` | Malformed `master-display` / `max-cll` text is accepted (x265 ignores it, no HDR SEI) | Fix (E) |
| R5-9 | C-15 | `cli.py` presets output | Control characters of imported preset names reach the terminal | Fix (E) |
| R5-10 | docs | `validation/dryrun.py:15` | A reference to a test file that does not exist | Fix (E) |

**Suspected** (no reproduction; each fix agent checks the ones of its area and fixes those that
turn out real and cheap): `batch/metadata.py:35` an invalid `language_ietf` preferred (A); a
hand-picked stream not claimed against relaxed rules, `first_of_language` for a second rule on
one track, an audio rule with subtitle settings shown ✓, `episode_key` on the event loop (B);
the scans do not pass the tool's environment (C, fixed); a cache hit checks only the PNG header,
M2TS PGS segments (C, not checked); stale `.fetch-*` folders after a crash, a slow download
outlasting the cancel wait, the lexical tar link check, no size cap on `presets import`,
dry-run attribution of short keys (E); mkvpropedit killed while it writes the source by
Reframe's own cancel, `close()` or the 5-minute limit — 150 random kills damaged nothing, but
D's kills late in the edit did: it became the blocker R4-7 above.

### Outcome

Filled in when the fixes are merged (commit and test per finding).

## Consequences

- Every blocker and major has a test that failed on 3cde317 and passes after its fix.
- What is left (won't fix, or a suspected item not reproduced) is a known limit in
  `docs/status.md`.
- The review's repro files stay uncommitted in the reviewers' worktrees, which are removed after
  the merge into `main`; the fix agents turned the useful ones into tests.

## Plan changes

None in this record; the fix agents record plan changes in their steps' records.
