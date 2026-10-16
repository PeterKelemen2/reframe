# 0034 — Metadata edit in place, the post-mux fix-up and the re-probe check

- Status: accepted
- Date: 2026-10-15
- Steps: C-13 (also C-7, C-8, C-11, C-3, C-16)
- Amends: [0027](0027-one-process-owns-the-queue-store.md) item 5 (one exact exception)

## Context

05 §C-13 asks for the `metadata_edit` job type with a reason, an mkvpropedit builder, a
post-mux fix-up "for flags and IETF tags that FFmpeg did not write", and a re-probe after every
metadata change. 03 §Remux-only jobs defines a metadata edit as "Source is MKV, track set and
order unchanged, only metadata changed, *Edit in place* chosen". Several things were open:

- **What "only metadata" means.** mkvpropedit can also set the segment title, chapters
  (`--chapters FILE`) and global tags (`--tags global:FILE`).
- **Decision 0027 item 5** says the queue never writes or deletes the source. An in-place edit
  writes the source by definition.
- **What FFmpeg does not write.** Checked with the real tools (2026-10-15; FFmpeg n9.0.2 Arch,
  n8.1.3 BtbN; MKVToolNix 101.0): the Matroska muxer writes all six flags, including
  `FlagDefault=0` (`ffmpeg -i multitrack.mkv -map 0 -c copy -map_metadata:s -1
  -disposition:a:0 default+original+visual_impaired -disposition:a:1 0 -disposition:a:2
  comment -disposition:s:0 forced+hearing_impaired … out.mkv`, then `mkvmerge -J out.mkv`:
  every flag as asked, on both builds). It never writes `LanguageIETF` (testdata/README.md
  "Language tags").
- **How the BCP 47 value is checked.** ffprobe never shows `LanguageIETF`. MediaInfo does,
  but it is optional (the CLI is not installed on the development machine; the `pymediainfo`
  wheel with its bundled library is in the dev environment). `mkvmerge -J` shows it too, but
  mkvmerge is not a tool Reframe discovers, and a user can have mkvpropedit alone.
- **mkvpropedit facts** (101.0, testdata/README.md "Metadata edit (C-13)"): `--set
  language=X` writes both elements with MKVToolNix's own legacy code (`pes` → `und`, not
  Reframe's `per`), and a later `--set language=` overwrites an earlier `language-ietf`;
  `track:a2` counts tracks in `TrackEntry` order whatever their `TrackNumber`, and attachments
  (fonts, cover art) are not tracks; an edit whose selector matches no track fails with exit
  code 2 and leaves the file unchanged; with no action it fails ("Nothing to do."); when the
  grown `Tracks` element does not fit, mkvpropedit writes it at the end of the file (after the
  `Cues`) and leaves a `Void` in its place.

## Decision

1. **Job type.** `job_type` returns `metadata_edit` when `output.edit_in_place` is set and
   `in_place_blockers` finds nothing. A blocker is: the source is not Matroska (ffprobe
   `format_name` has `matroska` and the name does not end in `.webm`); the output container is
   not MKV; the video is encoded; the source has more than one video track (the builder keeps
   only the first); a range; the audio or subtitle tracks are not the source's, in source order
   (added, removed, moved, an external subtitle file); an audio track that is encoded or that
   the container cannot copy; a subtitle that is burned in, converted, or cannot be copied; the
   source's chapters removed or renamed, or chapters generated; `passthru_metadata` off; a tag
   other than the title. **Changeable in place:** each track's language, name and six flags,
   and the container title (`tags.title`, rendered with the naming variables, written with
   `--edit info --set title=`). Chapter names and the other tags need a remux (default, easy to
   change: they need a chapters / tags XML file that mkvpropedit reads). With *Edit in place*
   and a blocker, the reason is the remux / encode reason plus "It cannot be edited in place:
   <first blocker>."
2. **The exception to decision 0027 item 5, exactly.** Only a job whose plan has `job_type
   metadata_edit` may write its source, only with mkvpropedit, only the source, and never
   removes anything. Its plan has only `mkvpropedit` steps whose file argument is the source,
   no `files`, no `temp_files`, and `output_tmp` = `output_final` = the source. The runner
   checks exactly that before the first step and fails with `queue.writes_source` otherwise; it
   also checks that the source can be written (`inplace.source_not_writable`) and that the
   file's Matroska tracks are the probe's streams (per kind, in order:
   `inplace.tracks_mismatch`), so `track:a2` is the track the job means. Nothing is changed when
   a check fails. The run's outcome carries no plan, so the queue's clean-up removes nothing.
   Every other job keeps every protection of 0027 item 5, and `files.remove_files(…,
   keep=source)` still never removes a source.
3. **The mkvpropedit builder** (`reframe.command.mkvpropedit`, pure): `--edit track:<v|a|s><n>`
   with `--set language=<ISO 639-2/B> --set language-ietf=<BCP 47>` (always the pair, in that
   order), `--set name=…` or `--delete name` (the job writes no name and the track has one),
   `--set flag-default|flag-forced|flag-commentary|flag-hearing-impaired|flag-visual-impaired|
   flag-original=0|1` (names from the definitions, checked with `--list-property-names`). An
   in-place edit writes only what differs from the probed source: languages are compared as
   the pair (`ja` on a `jpn` track without `LanguageIETF` is no change), names as text, flags
   one by one. When nothing differs the plan has no step and the job only re-probes. The
   display uses C-7's quoting (POSIX shells and `cmd.exe`).
4. **The post-mux fix-up** (every other MKV job, after FFmpeg, on the `.part` file): the same
   builder, for what the muxer does not write: `LanguageIETF` of a language that ISO 639-2
   cannot say (`pt-BR`, `yue`), and the set flags of a container's `mkvpropedit_flags` (none
   for MKV: FFmpeg writes all six). C-7's step now writes the explicit pair instead of `--set
   language=<tag>`, so the legacy code is Reframe's (the one FFmpeg wrote), not MKVToolNix's.
   Without mkvpropedit there is no step, and the existing warnings name what is lost
   (`metadata.language_tag_lost`, `tool.mkvpropedit_missing` for a flag).
5. **BCP 47 without MediaInfo: Reframe reads Matroska's track headers itself**
   (`reframe.probe.matroska`, standard library only, no new dependency): the EBML header, then
   the segment's top-level elements until `Tracks` and `Info`, following the `SeekHead` when
   `Tracks` comes after the clusters; every read is bounded (16 MB per element, 4096 top-level
   elements). The prober uses it for every Matroska file: a track's `LanguageIETF` becomes the
   stream's `language_ietf` (it wins over MediaInfo's value), matched per kind and order; when
   the counts differ nothing is set and a warning says so; a file the reader cannot read keeps
   ffprobe's view without a warning. The probe cache's options get `"matroska": 1`, so entries
   made before have to be probed again. Not chosen: `mkvmerge -J` (another tool to discover,
   not always installed with mkvpropedit), MediaInfo only (optional).
6. **The re-probe check** (`reframe.queue.verify.check_output(…, plan=…)`): after an in-place
   edit the source, and after a fix-up the `.part` file (before the rename), is probed again
   without the cache. Besides C-11's layout and ISO 639-2 check, every track's BCP 47 language
   (the probe's `language_ietf`, else its ISO code, both as canonical tags: `eng` without
   `LanguageIETF` equals `en`; for a fix-up the full tag only where the step wrote it), name
   and flags (all six in place; for a fix-up the flags the muxer writes plus the step's) and
   the title the edit set are compared with the job. Each difference is one line of the
   failure. Jobs without an mkvpropedit step keep C-11's check unchanged.
7. **Validation** (`reframe.validation.inplace`, area `output`): `inplace.not_possible`
   (error; the first blocker; fix "Write a new file": edit in place off and, when the path is
   the source, C-16's name or `Name (1).mkv`), `inplace.source_not_writable` (error; same
   fix), `inplace.output_ignored` (warning: a metadata edit whose output path is not the
   source; fixes: edit the source, or write a new file). The output rules skip the path and
   disk-space checks of a metadata edit (its output is the source by design). mkvpropedit
   missing stays `tool.mkvpropedit_missing` (error for an in-place job).
8. **`remux_job`**: video passthrough, every source audio track `passthru` (the draft's
   fallback encoder kept) and every subtitle `copy`, in source order, each with the source's
   language, name and flags (`reframe.batch.track_metadata`); the whole file, the source's
   chapters, `passthru_metadata` on and no tag overrides (the preset's tags would block an
   in-place edit; a remux keeps the source's tags). For an MKV source with `edit_in_place` the
   output is MKV at the source's path and the video track keeps its flags exactly (the encode
   draft's forced default flag of 0024 item 5 would be an edit the user did not ask for);
   otherwise the draft's container, path and video metadata stay.
9. **`render_value`** (C-16, `reframe.naming.render_value`): one value template with the naming
   variables, without the file-name rules; no file-system reads unless a `NamingFs` is given;
   `{date}` / `{time}` empty without `now`. C-7's tags and the in-place title use it.

## Consequences

- "I only want to fix languages and flags" runs in about 0.1 s through the queue (probe,
  validation, mkvpropedit, re-probe) on the fixture; the probe shows `pt-BR` without MediaInfo.
- A metadata edit changes the user's file. If mkvpropedit is killed or the disk fails while it
  writes, the file can be damaged; Reframe keeps no backup (mkvpropedit writes a few KB in
  place). Revisit if users ask for one.
- The queue's same-output rule keys on `output.path`, which is the source for an in-place
  edit: two edits of one file never run at once. An encode that *reads* the same source can
  still run beside an in-place edit of it (a `queue/service.py` change; reported to the lead).
- `tool.mkvpropedit_missing`'s fix "Write a new file" (validation/tools.py) only turns edit in
  place off; for a job whose path is the source it then gets `output.same_as_source` (with its
  own fix). Reported to the lead.
- Restored interrupted rows: the queue's leftover clean-up passes `plan.output_tmp` (the
  source) to `remove_files(…, keep=source)`, which refuses and logs it. Harmless; a
  `queue/service.py` change could skip `metadata_edit` plans (reported).

### Open questions (defaults chosen, easy to change)

- *Edit in place* with a change that needs a remux is an **error** with a fix, not a silent
  fall-back to a remux (the user asked for an in-place edit and its speed).
- Chapter names and tags other than the title are **not** edited in place (a remux does it).
- `remux_job` drops the preset's tag overrides and chapter renames.
- An in-place edit keeps the video's flags as they are (no forced default flag).

## Plan changes

- [05-core.md §C-11](../plan/05-core.md#c-11-queue-and-job-runner): "No file that a job
  writes or removes may be the source" names the one exception (this record).
- [05-core.md §C-13](../plan/05-core.md#c-13-metadata-edit-and-remux): a note with the
  decisions above.

## Follow-up (2026-10-15, after the wave-1 merge)

The four changes this record reported to the lead, made by the C-13 task:

1. **Same-output rule** (`reframe.queue.service`): a job with `output.edit_in_place` is keyed on
   its source (it writes it). A job does not start while another running job writes its
   output, edits its source in place, or (for an in-place edit) reads or writes the source it
   would edit. So an encode never reads a file that is being edited in place, and two edits of
   one file run one after the other. `ActiveJob` gained `source_key` and `in_place`.
2. **Restore**: `_remove_leftovers` skips the plans of `metadata_edit` jobs (no `.part`, plan or
   temporary file; no "is the source file, not removed" warning).
3. **`tool.mkvpropedit_missing`** (in-place case): its fix "Write a new file" is
   `inplace.write_new_file_fix`: edit in place off and, when the output path is missing or is
   the source, a new path (`inplace.new_output_path`), so applying it gives no
   `output.same_as_source`. The C-8 table of `test_rules.py` is unchanged (its case has a path
   that is not the source); a new case in `cases_inplace.py` covers the in-place job.
4. **`writable_file(path)`** is on `LocalFileSystem` (POSIX `os.access`; on Windows the file is
   opened for update, since `os.access` sees only the read-only attribute). It is a separate
   runtime-checkable protocol, `reframe.validation.fs.WritableFiles`, not a member of
   `FileSystemView`: the fake view of `tests/validation/scenario.py` (which this task may not
   edit) does not have it, and mypy then rejects it as a `FileSystemView`.
   `inplace.source_writable` asks a view that has it, else answers yes. Moving the method into
   `FileSystemView` needs `writable_file` on that fake view first.

## Follow-up (core-complete review, 2026-10-16)

`writable_file(path)` is now a member of `FileSystemView` (the lead's follow-up of item 4):
the test scenario's `FakeFs` answers it from its files and its read-only set, so the separate
`WritableFiles` protocol is gone and `inplace.source_writable` always asks the view (it no
longer answers "yes" for a view that cannot tell). The queue's run-time check before
mkvpropedit (`reframe.queue.files.writable_file`) is now the same test as
`LocalFileSystem.writable_file`: on Windows it opens the file for update instead of trusting
`os.access`, which sees only the read-only attribute (before, a file whose ACL denies
writing, or that another process holds without write sharing, passed the runner's check).
Tests: `tests/validation/test_inplace_fs.py` (`test_every_view_answers_writable_file`,
`test_runner_check_is_the_local_view`, mocked Windows).
