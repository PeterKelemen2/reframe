# 0080 — Reframe's own Matroska header writer replaces mkvpropedit

- Status: accepted
- Date: 2026-11-15
- Steps: C-18 (new); also C-1, C-7, C-8, C-11, C-13, D-7, D-8, S-6, F-15, Q-5
- Supersedes: the tool of [0034](0034-metadata-edit-in-place.md) (mkvpropedit); what can be
  edited in place, the fix-up's scope and the re-probe check of 0034 stay

## Context

Reframe runs one MKVToolNix program at run time: `mkvpropedit`. It has two jobs:

1. **The `metadata_edit` job** (C-13, 0034): an MKV source is edited in place, with no remux.
   It writes track languages (`Language` and `LanguageIETF`), track names, the six track flags
   (default, forced, commentary, hearing impaired, visually impaired, original) and the segment
   title. `command/mkvpropedit.py` `in_place_edits` builds the arguments, and the queue runner
   runs them on the source.
2. **The post-mux fix-up** (C-7, 0034): FFmpeg never writes `LanguageIETF`, so a language that
   ISO 639-2 cannot say (`pt-BR`, `yue`, `zh-Hant`) gets an mkvpropedit step on the `.part`
   file (`fixup_edits`). The flags need no fix-up: FFmpeg writes all six into Matroska
   (`testdata/README.md`, "Verified tool behaviour"; no container sets `mkvpropedit_flags`).

`mkvmerge` and `mkvinfo` are not run by Reframe. Tests and the notes in `testdata/README.md`
use them to check files.

Reframe already reads these elements itself: `probe/matroska.py` is a bounded EBML reader of
the `EBML` header, `SeekHead`, `Info` and `Tracks`, because ffprobe does not show
`LanguageIETF` (0034).

What mkvpropedit costs today:

- **Windows**: the installers do not bundle `mkvpropedit.exe`, because its Windows build links
  OpenSSL into GPL-2.0-only code ([0079](0079-q5-release-process.md) item 11). Windows users
  must install MKVToolNix, or an in-place edit is refused (`tool.mkvpropedit_missing`) and a
  BCP 47 language loses its region or script (the silent-loss warning of C-8).
- **Linux packages**: in the AppImage and on Fedora 45 the system `mkvpropedit` is `broken`,
  because the sidecar's `LD_LIBRARY_PATH` (Ubuntu 22.04's `libstdc++`) reaches it (D-8 open
  item, [0072](0072-m10-bundling-packaging-smoke-tests.md)).
- **Everywhere**: one more tool to discover, show in Settings → Tools, version-check, explain
  when missing, package (`Recommends: mkvtoolnix`, the Docker image's `mkvtoolnix`), and list
  in the licence notices.

## Decision

1. **Reframe writes the Matroska header changes with its own code.** A new core step, C-18,
   adds a writer in `reframe/metadata/`. It shares the EBML parsing of `probe/matroska.py` and
   runs in-process (in a worker thread), not as a subprocess.
2. **Scope: only what Reframe edits today.** In each `TrackEntry`: `Language`,
   `LanguageIETF`, `Name`, `FlagDefault`, `FlagForced`, `FlagCommentary`,
   `FlagHearingImpaired`, `FlagVisualImpaired`, `FlagOriginal`. In `Info`: `Title`. Tracks are
   picked as now: the n-th track of a type in `TrackEntry` order. No tags, chapters,
   attachments or other elements.
3. **Behaviour to keep from mkvpropedit** (each recorded in `testdata/README.md`):
   - both language elements are written: ISO 639-2/B in `Language` and BCP 47 in
     `LanguageIETF`;
   - a `Tracks` or `Info` element that no longer fits in its place, with the `Void` after it,
     moves to the end of the segment. The old place becomes a `Void`, and the `SeekHead` entry
     points to the new place;
   - a `CRC-32` child of a changed element is calculated again;
   - an edit that fails, or that the writer cannot do safely, leaves the file unchanged. Such a
     result is data (a failed step with a reason), not an exception. Which cases these are is
     found on real files and recorded. Candidates: the hostile `SeekHead` that mkvpropedit also
     refuses, a `SeekHead` with no room for a new entry, a segment of unknown size;
   - the limits of `probe/matroska.py` (`MAX_*`) apply to every read.
4. **Crash safety for the in-place edit.** The source belongs to the user. Every state that a
   crash or a kill can leave must be a file that ffprobe and `mkvmerge -J` open with all the
   old values or all the new ones. The write order is designed for that, and fault-injection
   tests prove it: they stop the writer after each write and check the file. Once the writer
   starts to write, a cancel or `close()` lets it finish, as the runner does for mkvpropedit
   today.
5. **MKVToolNix stays a development tool only.** Tests use `mkvmerge -J`, `mkvinfo` and
   `mkvpropedit` as an oracle: the same edit done by mkvpropedit and by Reframe must read back
   the same in `mkvmerge -J`. These tests have a `needs_mkvtoolnix` marker and skip without
   MKVToolNix. The Ubuntu CI job installs `mkvtoolnix` from apt for them. No product code runs
   an MKVToolNix program, and there is no run-time fallback to mkvpropedit.
6. **When C-18 lands, mkvpropedit leaves the product:**
   - tool discovery, `ToolName`, `ToolsStatus`, `reframe tools status`, Settings → Tools and
     the first-run check: no `mkvpropedit` row, no `REFRAME_MKVPROPEDIT`, no MKVToolNix
     install-folder search on Windows;
   - validation: `tool.mkvpropedit_missing` and the "BCP 47 language without mkvpropedit"
     silent loss go, because the writer is always there;
   - the plan step kind `mkvpropedit` becomes `header_edit`, and `PlanStep.tool` loses
     `mkvpropedit`. A plan is derived data: the queue store plans again a stored plan that
     does not validate, so no migration is needed. The step's line in the command preview
     lists the edits (track, field, value) instead of a command line;
   - the settings field `tools.mkvpropedit` is removed under the persistence rules:
     `schema_version` bump, a migration, and a down-level note (an older version that reads
     the new file finds no mkvpropedit path and runs discovery);
   - packaging: no `Recommends: mkvtoolnix` in the .deb / .rpm, no `mkvtoolnix` in the Docker
     image, no "install MKVToolNix" text, and no MKVToolNix row in the licence notices.
7. **When**: in M10, before the release checklist, so v1 ships without the MKVToolNix
   requirement on Windows.

## Consequences

- An in-place edit and a BCP 47 language work on every install, Windows too, with nothing
  else to install. The D-8 open item about the `broken` system mkvpropedit goes away. The same
  `LD_LIBRARY_PATH` problem with the system `mediainfo` stays.
- Reframe owns code that writes into the user's source file. That is the risk of this
  decision. Item 4 and the oracle tests are what control it. Until C-18's "Done when" passes,
  the product keeps mkvpropedit as it is now.
- The command preview of a metadata edit no longer shows a command that a user can copy and
  run outside Reframe.
- MKVToolNix-specific checks that mkvpropedit did for us (for example its own refusal of a
  damaged file) become ours to test. The fixture corpus gets files written by mkvmerge (with
  `CRC-32` elements) beside the FFmpeg-written ones.
- The step IDs in the C-13 tests and the error texts that name mkvpropedit change with C-18.
- To revisit: if a later feature needs more Matroska editing (tags, chapters, attachments in
  place), extend the writer only when that feature is planned. Do not take mkvpropedit back.

## Plan changes

- `05-core.md`: new section **C-18 Matroska header writer**; C-1 (discovery and versions
  without mkvpropedit), C-7 (the fix-up step), C-8 (tool and silent-loss rules), C-11 (the
  short-step time limit, the in-place exception), C-13 (the writer instead of the mkvpropedit
  builder), the module layout.
- `02-architecture.md`: the tool diagram, the encoding backend list, the bundled-tools folders
  and the path-override table.
- `03-features.md`: §Track metadata (the fix-up), §Remux-only jobs, §Settings (Tools).
- `06-web-app.md`: the Docker image's runtime packages (S-6).
- `07-desktop-app.md`: the bundled-tools table, D-7's notes.
- `08-roadmap.md`: C-18 in M10.
- `09-quality-and-release.md`: the MKVToolNix licensing row.
- `README.md`: the encoding backend at a glance.
- [0034](0034-metadata-edit-in-place.md): its status line points here.

## Built

### Wave 0 (the lead, 2026-11-15)

The plan step kind `header_edit` with its `HeaderEdit` model, `PlanStep.tool` without
`mkvpropedit`, the settings field `tools.mkvpropedit` removed (`settings` schema 2, migration
and down-level note in `models/migrations.py`), the writer's contract
(`reframe.metadata.header.apply_header_edit`) as a stub, and the `needs_mkvtoolnix` marker.
Until task I merges, a `header_edit` step still runs mkvpropedit. Tasks and contracts:
[m10-breakdown.md](../m10-breakdown.md) "C-18 / C-19 / C-20".

### Built: H (the writer)

*Placeholder.*

### Built: I (the plan step, runner and validation)

*Placeholder.*

### Built: P (mkvpropedit leaves the product)

*Placeholder.*

### Built: U (the UI)

*Placeholder.*

## Review

*Placeholder.*
