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

`reframe.metadata.header.apply_header_edit` (the contract of wave 0, unchanged), with
`metadata/ebml.py` (EBML encoding, a strict child parser, `CRC-32`) and `metadata/layout.py`
(where `SeekHead`, `Info` and `Tracks` are). Both use the reader of `probe/matroska.py` (its
`_Reader`, `_header`, `_read` and the `MAX_*` limits, read when they are used); that file is not
changed. The facts the design rests on, and the refusals with what mkvpropedit does, are in
`testdata/README.md` "Matroska header writer".

1. **What changes.** In the n-th `TrackEntry` of a type: `Language` (ASCII) and `LanguageIETF`
   (UTF-8) as a pair, `Name` (set or removed), the six flags (1-byte values). In `Info`: `Title`
   (`None` or an empty title removes it). An element the entry already has with the same value
   is not written; a flag that is absent and has the asked value (its default) stays absent;
   a duplicated element becomes one. Other children are copied byte for byte, new ones go at
   the end of their parent, a `CRC-32` of a changed `TrackEntry`, `Tracks`, `Info` or
   `SeekHead` is calculated again. When nothing changes, nothing is written (`written`, and the
   file need not be writable).
2. **Where it goes.** An element that fits in its place and the `Void` elements after it is
   written there; the rest of the place becomes a `Void` (only its header is written). A
   1-byte gap cannot be a `Void`: the size field is one byte wider instead. An element that
   does not fit moves to the end of the segment. A `Tracks` or `Info` behind the clusters is
   written in place only when it is the only element that changes; otherwise it moves again,
   so that the switch stays one write (item 3). The cost: a file grows by the moved copies on
   such an edit (up to 68 KB after three edits on a real file with 17 tracks).
3. **Write order** (each step is followed by `fsync`):
   1. Only when something moves and the file has leftovers of a stopped edit after the segment
      (copies of `Tracks`, `Info`, `SeekHead` or a `Void`, the last one perhaps cut short): the
      file is truncated to the end of the segment.
   2. Only when something moves: the new copies are written after the end of the segment, and
      with them a copy of each `SeekHead` behind the clusters that lists a moved element. No
      reader looks there: ffprobe, `mkvmerge -J` and Reframe's reader read the old values.
   3. **The switch, one write**: the segment size, the first `SeekHead` (moved entries, a new
      entry when none listed the element), a second `SeekHead` before the clusters, every
      element written in place, and each old place before the clusters turned into a `Void`.
      The bytes between them are written again as they are. After this write all three readers
      read the new values.
   4. Each old place behind the clusters (a moved `Tracks`, `Info` or `SeekHead`) becomes a
      `Void`. Before this write nothing points to them.

   Why one write: ffprobe and Reframe's reader take the `Tracks` they meet first; `mkvmerge -J`
   takes the one the `SeekHead` names. A state where the two differ is read as old by one tool
   and new by the other (and mkvpropedit's order, the old place first, leaves no `Tracks` at
   all). Before any write, the planner reads every state the steps pass through (the file plus
   the planned writes, in memory) with Reframe's reader and refuses (`header.unsafe_layout`)
   unless each reads all old or all new and the last all new. The fault tests stop the writer
   after each write, and in the middle of the copies, and read every file left with ffprobe,
   `mkvmerge -J` and Reframe's reader.

   What is not covered: the switch is one `write()` call, but it is not atomic on the disk. It
   runs from the segment size (or the first element written in place) to the end of the last
   changed element before the clusters: on the sampled real files it starts in the first 4 KB
   and is 0.1 to 36 KB long. A power cut while the kernel writes those pages back, or a kill
   while a switch of more than one page is copied into the page cache, can tear it. The window
   is microseconds for a kill and the `fsync` time for a power cut; mkvpropedit has the same
   window over its several writes.
4. **Results.** `refused` (the file byte for byte unchanged, also its modification time):
   `header.unreadable` (not Matroska, damaged, a `CRC-32` that does not match, beyond the
   `MAX_*` limits), `header.too_large` (a `SeekHead` over `MAX_SEEK_HEAD`), `header.duplicate`,
   `header.seek_head`, `header.no_info`, `header.no_such_track`, `header.invalid_value` (a NUL,
   or a `Language` that is not ASCII), `header.unknown_size`, `header.no_room`,
   `header.trailing_data`, `header.truncated` (the last four only when an element must move),
   `header.unsafe_layout`. `failed`: `header.io_error` for every OS error, also one before the
   first write (the file cannot be opened for writing): the reason then says "It is
   unchanged.", after a write "The file holds either the old or the new values.";
   `header.changed` when the file's size, modification time or inode changed between the read
   and the write (nothing written).
5. **Choices that differ from mkvpropedit** (it edits these files; Reframe refuses): a segment
   of unknown size, a file with no `SeekHead` or no room for a longer one, data after the
   segment and a truncated file, each only when an element must move; a `CRC-32` that does not
   match (mkvpropedit writes a `CRC-32` over the damaged bytes); two `Info` or `Tracks`
   elements. In the 32 real MKV files sampled, only one growing edit on one file was refused
   (`header.no_room`: `Info` right after the `SeekHead`).
6. **Corpus deviation.** mkvmerge 103 writes no `CRC-32`, and no sampled mkvmerge file has one.
   The corpus file "mkvmerge-written with `CRC-32`" is an mkvmerge file into which the test
   puts `CRC-32` elements; FFmpeg-written files have them in every level-1 element.

For task I and the reviewers:

- `apply_header_edit` is blocking and has no cancel point: the runner lets it finish. It took
  1 to 45 ms on the fixtures and on real files (most of it the check of every state). The
  largest read is bounded by `MAX_READ` (36 MB); in practice the `Tracks` and `Info` elements,
  the `SeekHead` and the switch's span (tens of KB).
- The file is opened twice: read only to plan, then for writing, after a check that it is the
  same file with the same size and modification time.
- Tests replace `header._FileIO` to stop the writer after a given write.

### Built: I (the plan step, runner and validation)

1. **The edit computation** is `command/header.py` (pure): `in_place_edit` (what differs from
   the probed source, as a `HeaderEdit`), `fixup_edit` (the `LanguageIETF` fix-up) and
   `edit_line` (the preview line). `command/mkvpropedit.py`, `header_edit()`,
   `header_edit_args()` and `command/metadata.ietf_edits` are gone.
2. **The fix-up is planned for every MKV output that has a language ISO 639-2 cannot say**,
   with no tool check. It writes only `Language` + `LanguageIETF`: FFmpeg writes all six
   flags, so the flag part of the fix-up is gone with its definitions field (item 6).
3. **The preview line** of a `header_edit` step is the word `header_edit`, the shell-quoted
   file, then per track `<type> <n>:` and its `field=value` words, then the title:
   `header_edit /media/Show.mkv audio 1: language=hun language_ietf=hu name='Magyar 5.1'
   default=0 original=1 audio 3: delete_name title='Show – S01E02'`. The field names are
   those of `TrackHeaderEdit`; a flag is `0`/`1`; `delete_name` and `delete_title` remove.
   Values use the shell's quoting, so the line splits into words as the other steps do. It
   is not a command; the job log shows the same line.
4. **The runner** runs the writer in the default executor with
   `loop.run_in_executor(None, apply_header_edit, edit)`, not `asyncio.to_thread`: the result
   is a plain future, not a task, so an event loop that shuts down (it cancels every task)
   does not cancel the wait for the writer's result. The awaiting task is shielded; a
   cancelled task waits for the write, sets `end_note` (what the file holds) and re-raises.
   - **Cancel and `close()`**: a thread cannot be stopped, so every `header_edit` step (in
     place and the fix-up on the `.part` file) runs to its end; the log says "it is let
     finish". The fix-up's `.part` file is removed only after the write (on Windows an open
     file cannot be removed). A cancel before the write starts writes nothing.
   - **Pause**: the job shows `paused` at once (its inhibit is freed); the write, which cannot
     be suspended and is short, runs to its end, and nothing after it (the next step, the
     check of the edited source) starts until resume. A stop of a paused job during the
     write shows it `running` again until it ends, as before.
   - **Time limit**: none for a `header_edit` step. A limit could only stop waiting while the
     thread may still write the user's file, and another job could then start on it. The
     writer's work is bounded by the reader's `MAX_*` limits; only a hung file system can
     hold it, and then the job stays running and `close()` waits. The 5-minute limit stays
     for a tool step other than FFmpeg (none is planned now).
   - **Results**: `refused` fails the step with the writer's reason and "Nothing was changed
     in the file"; `failed` fails the job with "The file holds either all its old values or
     all the new ones", also when it came after a cancel; a writer that raises is an internal
     error. The log line is `Step i/n ended: <status> (<code>): <reason> after <s> s`.
   - A run that a crash stopped during an in-place edit is restored with "If Reframe was
     writing the header of X at that moment, the file holds either all its old values or all
     the new ones."
5. **Validation**: `tool.mkvpropedit_missing` (in-place error and flag warning) and
   `metadata.language_tag_lost` are gone with their tests; a test proves that an in-place
   edit, a BCP 47 language and every flag validate without an issue when no MKVToolNix is
   found.
6. **Definitions**: `TrackFlagDef.mkvpropedit` and `ContainerDef.mkvpropedit_flags` are
   **dropped**, not renamed. The writer uses the flag names of `HeaderFlag` and owns the
   Matroska element IDs; no container set `mkvpropedit_flags`, and a muxer that cannot write
   a flag is now only `container.flag_unsupported`. The definitions are package data, not a
   persisted user document, so no migration; the lint rule about the field is gone. Both
   models are in the OpenAPI document, so `frontend/src/api/schema.d.ts` changes.
7. **The guard against MKVToolNix** (`tests/queue/test_no_mkvtoolnix.py`): an AST scan of
   every module under `packages/reframe/src` and `packages/reframe-server/src` for string
   constants (outside docstrings) that name `mkvpropedit`, `mkvmerge`, `mkvinfo` or
   `mkvextract`, and two queue runs that record every process started (an in-place edit
   starts none; an encode with the fix-up starts only FFmpeg). Until P lands, the scan skips
   `reframe/tools/**`, `models/tools.py`, `paths.py` and `cli.py`; `models/migrations.py` may
   name the removed settings key.
8. **With the real writer** (checked on Linux, MKVToolNix 103 as the oracle): C-13's "Done
   when" passes through the facade and the real queue with no mkvpropedit to be found
   (`REFRAME_MKVPROPEDIT` points at a missing file): languages and flags on the `multitrack`
   copy run as `metadata_edit` in under 1 s and the re-probe shows them. The same in-place
   edit (names, BCP 47 languages, flags, title) and the same fix-up (`pt-BR`, `zh-Hant` on
   an FFmpeg-muxed file) done by mkvpropedit read back the same in `mkvmerge -J` (track
   properties and title), and ffprobe reads every stream. A source whose SeekHead points
   `Tracks` past 2^63, which mkvpropedit failed on, is now refused ("The file's SeekHead
   entries for Tracks disagree"), byte for byte unchanged. The oracle's argument builder
   (`mkvpropedit_args`, the old `header_edit_args`) is a test helper in
   `reframe_testing.mkvtoolnix`, shared with the writer's own oracle tests.

### Built: P (mkvpropedit leaves the product)

*Placeholder.*

### Built: U (the UI)

*Placeholder.*

## Review

*Placeholder.*
