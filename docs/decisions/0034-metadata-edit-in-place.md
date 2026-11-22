# 0034 — Metadata edit in place, the post-mux fix-up and the re-probe check

- Status: accepted; the tool (mkvpropedit) is superseded by [0080](0080-own-matroska-header-writer.md) (Reframe's own Matroska header writer)
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
  *Done since: item 1 of the follow-up of 2026-10-15 below.*
- `tool.mkvpropedit_missing`'s fix "Write a new file" (validation/tools.py) only turns edit in
  place off; for a job whose path is the source it then gets `output.same_as_source` (with its
  own fix). Reported to the lead. *Done since: item 3 of the follow-up of 2026-10-15 below.*
- Restored interrupted rows: the queue's leftover clean-up passes `plan.output_tmp` (the
  source) to `remove_files(…, keep=source)`, which refuses and logs it. Harmless; a
  `queue/service.py` change could skip `metadata_edit` plans (reported). *Done since: item 2
  of the follow-up of 2026-10-15 below.*

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

The review's findings R4-1 … R4-6 and the kill paths (C-13 fix task; each test failed before
its fix and passes after it):

- **R4-1 (major): one file through a link had other queue keys.** The keys were
  `normcase(abspath(path))`: an encode that read the source through a symbolic or hard link
  ran while the source was edited in place, and two in-place edits of one file ran at once
  (the reviewer measured two real mkvpropedit edits of one file through two spellings: 20 of
  100 runs ended with one edit lost). Now a key is `normcase(realpath(path))` (for an output
  that does not exist yet, the existing part of its folder is resolved), and `_conflicts`
  compares two keys as files: equal, equal without case, or `os.path.samefile` (a hard link;
  on Windows `os.stat` gives the volume serial number and the file index), the rule of
  `files.same_file`. These are a few `stat` calls per running job in the event loop, each
  time the queue looks for a job to start. Tests: `tests/queue/test_job_keys.py`
  (symbolic link, hard link, linked output folder, case, a mocked `os.stat` identity, and the
  real queue with the fake tools: two edits through a link, and an encode of a hard link,
  run one after the other). Also in 0016.
- **R4-2 (major): a `SeekPosition` of 2^63 or more** made `handle.seek` raise `ValueError`,
  which the prober and the runner did not catch: `Reframe.sources.probe` raised and `reframe
  probe` printed "unexpected error". ffprobe and `mkvmerge -J` list all seven tracks of that
  file. Now a `SeekHead` entry whose position is at or past the end of the file is skipped and
  the next entry of that ID is used (FFmpeg also goes on with the next entry), any
  `ValueError` / `OverflowError` of the reader is a `MatroskaError`, and the element at a
  `SeekHead` position must be the element the entry names (before, an `Info` there was read as
  an empty track list). The runner's catch (`MatroskaError`, `OSError`) needed no change: an
  in-place edit of such a file now reaches mkvpropedit, which refuses the file itself ("no
  corresponding level 1 element was found", exit code 2, the file unchanged), and the job
  fails with that message. Tests: `tests/probe/test_matroska_limits_and_ietf.py` (in-memory
  files; the reviewer's `make_hostile.py` file built from the fixture with the real ffprobe),
  `tests/metadata/test_metadata_unusual_files.py` (the in-place edit through the queue).
- **R4-3 (major): with MediaInfo on, `language_ietf` was MediaInfo's `Language`**, which
  MediaInfo derives from the legacy element when there is no `LanguageIETF` (`jpn` → `ja`,
  `eng` → `en`; pymediainfo 7.0.1, libmediainfo 24.12), and `apply_matroska` overwrote it only
  when the track had the element. So the probe showed a BCP 47 tag that the file does not hold
  (`mkvmerge -J`: none). Now, for a Matroska file whose tracks the reader matched, every
  stream's `language_ietf` is the track's element or `None`; MediaInfo's value stays only for
  other containers and when the reader could not read or match the tracks. The re-probe check
  was not fooled (it compares canonical tags). The cache option becomes `"matroska": 2`, so
  older entries are misses. Tests: `test_matched_tracks_get_the_files_value_or_none`,
  `test_probe_with_mediainfo_on_keeps_only_the_files_bcp47_tags` (MediaInfo faked, MP4 keeps
  its value), `test_real_mediainfo_derives_a_bcp47_tag_from_the_legacy_language`, and the M6
  demo 3 with the real MediaInfo
  (`test_with_mediainfo_on_the_reprobe_shows_only_the_files_bcp47_tags`). Also in 0007.
- **R4-4 (major): an invalid `LanguageIETF` was stored unchecked** (`stream.language_ietf =
  …` does not validate): `en_US` or `j\na;x` made `remux_job` / `draft` fail with a
  `ValidationError` ("unexpected error" in `reframe plan`). ffprobe reads such a file (legacy
  `jpn`), `mkvmerge -J` shows no `language_ietf` for that track, MediaInfo shows the raw value.
  Now only a value that is a valid `LanguageTag` (pattern and at most 64 characters) is used;
  another value gives `None` and the probe warning "Stream 1: the BCP 47 language
  (LanguageIETF) 'en_US' is not a language tag; not used." (`''` means no element, no
  warning). MediaInfo's languages get the same length check. Tests:
  `test_a_value_that_is_not_a_language_tag_is_not_used`,
  `test_probe_of_an_invalid_language_ietf[en_US|j\na;x]` (the fixture copy with the bytes
  patched), `test_a_file_with_an_invalid_language_ietf_can_be_drafted_and_planned`.
- **R4-5 (minor): the reader's work was not bounded by entries.** `SeekHead` entries piled up
  without limit (the reviewer's 67 MB file of four 16 MB SeekHeads: 17.7 s, 663 MB), and the
  same held for any element's children: a 16 MB `Tracks` element of 8 million empty
  `TrackEntry` elements took 14.8 s and 1.75 GB (measured on this machine). Neither the
  prober's 30 s timeout (it stops waiting, the worker thread goes on) nor the runner's check
  before mkvpropedit (no limit) stopped that. Now: only the first `SeekHead` and the one it
  links to are read (before, every `SeekHead` before the first `Cluster` was read, and none
  after it), each at most `MAX_SEEK_HEAD` = 1 MiB (a larger one is skipped), with at most
  `MAX_CHILDREN` = 4096 entries looked at and only the `Tracks`, `Info` and `SeekHead` ones
  kept; any other element with more than 4096 children is a `MatroskaError`; one read parses
  at most `MAX_ELEMENTS` = 65 536 element headers and reads at most `MAX_READ` = 36 MiB.
  Measured after the fix: the reviewer's 67 MB file 0.000 s; a 67 MB file of 64 SeekHeads of
  just under 1 MiB, each linking to the next, 0.035 s and no memory beyond the interpreter's;
  the 16 MB `Tracks` element 0.011 s (`MatroskaError`). The tests count the headers parsed
  and the bytes read (no wall clock): `test_many_seek_heads_full_of_entries_are_bounded`
  (before: 240 019 headers), `test_linked_seek_heads_full_of_entries_are_bounded`,
  `test_one_linked_seek_head_is_followed_and_no_more`,
  `test_a_tracks_element_with_too_many_children_is_a_matroska_error`,
  `test_all_element_headers_are_bounded`, `test_all_bytes_read_are_bounded`,
  `test_a_seek_head_over_its_limit_is_skipped`. Item 5 of the decision ("16 MB per element,
  4096 top-level elements") is extended by these limits.
- **R4-6 (minor): the M6 demo-3 test** did not check the job type or the 1 s limit. It now
  asserts `metadata_edit` and `seconds(ended) < 1`
  (`test_languages_names_and_flags_the_reprobe_shows_them_all`). A test gap only:
  the new assertions pass on the code before the fixes too.
- **R4-7 (blocker, found as the review's doc item): Reframe killed mkvpropedit while it wrote
  the source.** Reframe's cancel, `close()` and the 5-minute step limit ended a running
  in-place mkvpropedit like any step (`queue/runner.py` ran it through
  `run_streaming(cancel=<the job's token>)`, which kills the process tree), and Reframe keeps
  no backup. Measured with MKVToolNix 101.0 on copies of `multitrack.mkv`, with an edit that
  grows `Tracks` so that mkvpropedit moves it behind the clusters (language pair and a
  200-character name on six tracks; about 27 ms per edit): SIGKILL at a random moment of the
  run, 150 times: 146 kills landed while it ran, none damaged the file (all before the write;
  the reviewer's own 150 runs: nothing damaged). SIGKILL late in the run (60 % to 120 % of its
  time), 900 times in two series: **3 files were damaged** (1 of 300, 2 of 600). In the two
  that were kept, mkvpropedit had already overwritten the old `Tracks` with a `Void` and was
  killed before the `SeekHead` named the new `Tracks` at the end of the file, or before the
  new `Tracks` was written at all. Such a file has no reachable track headers: ffprobe shows no
  streams, `mkvmerge -J` no tracks, and the reader `MatroskaError` ("no Tracks element
  found"). Through the queue (the real `Reframe`, a cancel at a random moment up to 30 ms after
  mkvpropedit started, 300 runs): 2 damaged files, and 50 jobs that ended `cancelled` with no
  word about the file although the edit was in it.

  **There is no gentler signal.** mkvpropedit installs no signal handler (`SigCgt` and `SigIgn`
  in `/proc/<pid>/status` are empty while it runs), so SIGTERM and SIGINT end it at once, as
  SIGKILL does: SIGTERM late in the run, 600 times: exit status -15 and 4 damaged files.

  **Decision.** A running in-place mkvpropedit step is never killed by a cancel or by `close()`:
  1. The step runs with a cancel token of its own (`JobRunner._run_step(…, in_place=source)`);
     only its time limit fires it. A stop of the job does not reach the process.
  2. A cancel or `close()` that comes while the step runs is written to the job log ("The job
     is cancelled while mkvpropedit is writing Show.mkv: it is let finish (stopping it could
     damage the file)"), resumes the step if the job was paused (a suspended step would never
     end), and waits for the step to end: tens of milliseconds, at most the step's time limit.
     `queue.cancel()` returns when the job has ended, as before. The queue's `close()` has no
     time limit of its own (it waits for every run to end), so nothing cuts the wait short; the
     10 s `CLOSE_TIMEOUT` of `Reframe.close()` bounds only the probes of `Reframe.sources`.
     A cancellation of the run's own asyncio task alone (the queue never does that) also waits
     for the step, then goes on. An event loop that shuts down (`asyncio.run` after a second
     Ctrl+C) cancels every task, the step's own run too, whose clean-up kills mkvpropedit: the
     log and the job's end (`interrupted`) then say that mkvpropedit was stopped while it edited
     the file and that the file may be damaged. (Corrected by the final review, RB-4: this item
     said that a shutdown also waits for the step.)
  3. A stop before the first step starts changes nothing: the job ends `cancelled` (or
     `interrupted`) as before, and mkvpropedit is never started after a stop.
  4. **Once an edit step has written the source, a stop ends the job `cancelled`** (`close()`:
     `interrupted`) with the error "The edit was already written to Show.mkv when the job was
     cancelled: mkvpropedit is never stopped while it writes the source (that can damage the
     file). The check of the edited file did not run." and the source as the job's output
     path. Not `done`: in the queue `done` means the result was checked (the re-probe check
     does not run after a stop, and running it would make a cancel wait for a probe), and the
     when-done action and the job notifications follow the user's action, as for any cancel
     (a cancel of the last job never starts a shutdown countdown). A retry of such a job finds
     nothing to change and ends `done` after the check. A mkvpropedit that failed (exit code 2:
     "The file has not been modified") counts as not written.
  5. **The time limit stays** (5 minutes of active time, `STEP_TIME_LIMIT`): a hung
     mkvpropedit (a network share that does not answer) must end, and there is no safer way
     to stop it (above). This one path can still damage the file, so its error says so:
     "mkvpropedit did not finish within 5 minutes and was stopped while it was editing Show.mkv
     in place: the file may be damaged." It also ends a step that a cancel is waiting for.
  6. Other steps (encodes, the post-mux fix-up on the `.part` file) keep their cancel: the
     process tree is killed at once.

  After the fix the same 300 queue runs gave no damaged file, and every job's end matched its
  file (all 300 ended `cancelled` with "The edit was already written", and every file had the
  edit). Tests (each failed before the fix): `tests/queue/test_in_place_stop.py`
  (`test_a_cancel_lets_the_running_edit_finish`, `test_close_lets_the_running_edit_finish`,
  `test_a_cancel_of_a_paused_edit_resumes_it_and_lets_it_finish`,
  `test_the_time_limit_still_stops_a_hung_edit`,
  `test_a_cancelled_edit_that_hangs_is_stopped_by_the_time_limit`,
  `test_a_cancelled_run_task_lets_the_edit_finish`; a stand-in mkvpropedit that waits at a
  gate the test opens, so no assertion depends on timing; and two guards that passed before
  too: `test_a_cancel_before_the_edit_starts_changes_nothing`,
  `test_an_encode_is_still_killed_at_once`), and with the real mkvpropedit behind a gate
  `tests/metadata/test_metadata_edit_real.py::test_cancelling_an_in_place_edit_lets_mkvpropedit_finish`
  (it replaces `test_cancelling_an_in_place_edit_keeps_the_source`, whose 30 s fake
  mkvpropedit the cancel now waits for). testdata/README.md "Metadata edit (C-13)" records
  the measurements.

## Follow-up (final review, 2026-10-17)

A final review of the fix rounds (reviewer R-B, on `core-complete` 5dbf152) ran 1080 stop runs
of real in-place edits (cancel, cancel-all, close, pause + cancel, pause + close): no damaged
file. It found two minors in the R4-7 stop path (and RB-5, in decision 0016's follow-up). Each
test below failed on 5dbf152 and passes now (`tests/queue/test_in_place_stop.py`).

- **RB-3: a late step time limit made a finished edit "cancelled".** The watchdog stopped the
  whole job (`active.stop("timeout")`) as well as the in-place step. When the limit fired after
  mkvpropedit had exited 0 but before the step's clean-up stopped the watchdog, the step counted
  as written, the job as stopped, and `_stopped_after_edit` reported every reason other than
  `close` as a cancel: the job ended `cancelled` ("…when the job was cancelled…") though nobody
  cancelled it, and the check never ran (the reviewer: 22 of 200 real runs with a short step
  limit). Now the time limit of an in-place step cancels only the step's own token, never the
  job: a step that exits 0 ends as any finished step and the edited file is checked. A step
  that `run_streaming` reports as cancelled but that exited 0 (the token fired first, the
  process ended on its own before the kill) is a finished step too; a step that was killed
  (a signal, the kill's exit code on Windows, or never started) still fails the job with "the
  file may be damaged" (item 5 of R4-7). `_stopped_after_edit` maps only `cancel` to
  `cancelled` and `close` to `interrupted`; any other reason (none reaches it now) is `failed`
  and never says "cancelled". Tests:
  `test_a_time_limit_after_the_edit_ended_does_not_cancel_the_job` (a step watch whose limit
  fires only after mkvpropedit exited, so the race is certain, not timed),
  `test_an_exit_0_that_came_with_the_time_limit_is_a_finished_edit`,
  `test_a_time_limit_is_never_reported_as_a_cancel`; `test_the_time_limit_still_stops_a_hung_edit`
  still passes.
- **RB-4: an event loop that shuts down killed the step, and the job said it was let finish.**
  `_to_its_end` shields the step from a cancellation of the run's task, but `asyncio.run`
  shutting down cancels every task, the inner `run_streaming` task too, whose clean-up kills
  the tree. The log then said "it was let finish" and the job ended "interrupted: The job was
  stopped." with no word about the file. (A hard exit kills the child anyway through
  `PR_SET_PDEATHSIG`; the CLI never runs in-place edits.) Not prevented: the step would have to
  run outside the loop's tasks (a thread with its own loop), which the stop guarantees of R4-7
  do not need. Now, when the run's task is cancelled during an in-place step, the runner looks
  at the step's own run: when it was cancelled too (killed), the log says "Step 1/1 ended:
  stopped. Reframe was shut down while mkvpropedit was editing Show.mkv in place: mkvpropedit
  was stopped before it ended, so the file may be damaged." and that text is the job's error
  (`interrupted`); when the step ended on its own with exit code 0, the error says the edit is
  written and was not checked; a step that its time limit killed gives the time-limit error.
  A restored `metadata_edit` job that was running or paused (a crash or a hard exit) says
  "Reframe stopped while the job was running. If mkvpropedit was editing Show.mkv in place at
  that moment, the file may be damaged." Item 2 of the R4-7 decision above is corrected in
  place. Tests: `test_an_event_loop_that_shuts_down_says_the_file_may_be_damaged` (every task
  of the loop cancelled, as `asyncio.run` does), `test_a_restored_in_place_job_that_was_running_may_be_damaged`;
  `test_a_cancelled_run_task_lets_the_edit_finish` (only the run's task cancelled: the edit
  ends first) still passes. With the reviewer's `loop_shutdown.py` (the real facade, two
  SIGINTs, a gated mkvpropedit): the stored row and the log now say the file may be damaged.

After the fixes, the reviewer's stress test with the real mkvpropedit 101.0 (the same edit that
grows `Tracks`; copies of five fixtures): `cancel` late 60, `close` late 60, `pause` + `cancel`
late 60, `pause` + `close` late 60, cancel-all late 60: 300 runs, no damaged file, every job's
end matched its file (`cancelled` / `interrupted` with "The edit was already written"); the step
limit at 0.3 to 1.3 times mkvpropedit's median run time, 100 runs: 93 `done` after the check, 7
`failed` with "the file may be damaged" (killed by the limit; every file intact), no
`cancelled` (before: 22 of 200). The R4-1 check with real tools (40 pairs of edits of one file
through a symbolic link, a hard link, a linked folder and a `..` spelling, and 6 encodes of a
link beside an edit; `parallel_jobs` 2): no overlap.

Known limit (no change): mkvpropedit's exit code 1 (warnings; it wrote the file) counts as a
failed step, not as written: the job fails with mkvpropedit's message, and a stop that came
during such a step ends the job as if nothing was written.
