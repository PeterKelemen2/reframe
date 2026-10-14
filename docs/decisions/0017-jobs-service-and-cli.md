# 0017 — Jobs service and the M2 CLI: drafts, bounded waits, output formats, exit codes

- Status: accepted
- Date: 2026-10-14
- Steps: C-15

## Context

C-15 builds `Reframe.jobs` (the contract in [m2-breakdown.md](../m2-breakdown.md), wave 3) and
the CLI commands of M2: `reframe encoders`, `plan`, `encode` and `name`
([05 §C-15](../plan/05-core.md#c-15-service-facade-and-cli), [08 §M2](../plan/08-roadmap.md#m2--encode-from-the-cli),
[0018](0018-m2-draft-tracks-and-multi-file-encode.md)). The plan names the commands and what
they print, but not how a draft handles some cases, how long anything waits, the output
formats, the exit codes, or how folders are searched. This record makes those choices.

What the real tools showed on the M2 machine (AMD GPU, no NVIDIA driver, FFmpeg n9.0.2):

```
$ reframe encoders          # first run, empty cache
No cached result: checking the encoders of ffmpeg n9.0.2 (/usr/bin/ffmpeg)…
libx264 — available
…
hevc_nvenc — unavailable: NVIDIA driver not found
…
Done in 0.8 s: 16 available, 7 not available.
```

and `reframe plan testdata/media/multitrack.mkv`: the default template `{main_title}` names
the output `multitrack.mkv`, next to the source: the source file itself.

## Decision

### The draft (`JobService.draft`)

1. **From the preset**: output options, dimensions, filters, video, chapter options (enabled,
   generate every N minutes) and tags are copied; tracks come from C-12's `draft_tracks`
   (0018); the video track's metadata comes from the source track (language, title, flags)
   with the default flag set (0024 item 5). `crop_policy` and the subtitle and audio
   *selection* stages are batch / M6 features and are not applied. `chapter_name_policy =
   "generated"` names the chapters `Chapter 1`, `Chapter 2`, … (with a note); no built-in
   preset uses it.
2. **Preset**: `None` is the default preset (`Reframe.presets.default()`: the user's default,
   else *H.265 MKV 1080p*). A string is an id or a name (without case). An unknown string
   gives a draft with the default preset's settings and a `preset.not_found` error, so it can
   never be queued (expected failures are data). The CLI checks the name first and suggests
   the closest names.
3. **Output path**:
   - no `-o`: C-16's `resolve_output_name` with the preset's naming options (else Settings →
     Output) and C-5's scaled size. **When that name is the source file itself** (the default
     template on an already clean name, such as `multitrack.mkv`), the draft uses the next
     free name (`multitrack (1).mkv`, C-8's `next_free_path`) and says so in `JobDraft.notes`.
     Without this, the default settings could not encode a file whose name is already clean
     (validation error `output.same_as_source`), and the M2 demo `reframe plan movie.mkv`
     would fail.
   - `-o OUT` with an extension: OUT is the output path as typed (manual name
     `naming.mode = "manual"`). Another extension than the container's is kept, and
     validation warns (`output.extension_mismatch`, with a fix).
   - `-o OUT` without an extension: the container's extension is added.
   - `-o DIR` (an existing folder): the template name inside that folder.
   - `-o` equal to the source: kept; validation reports `output.same_as_source` (an error).
4. **`JobDraft`** (`reframe.models.draft`): `job`, `decisions` (C-12), `naming` (C-16's
   `NameResult`), `issues` (validation of the drafted job, plus `preset.not_found`) and
   `notes`.

### Validation and planning

5. **Bounded wait for encoder detection.** `validate` runs C-8. When an issue says that
   detection has not decided yet (`encoder.checking`, `filter.implementation_untested`) and a
   detection runs (or none has run), it waits for `CapabilityService.wait()` for at most
   **60 s** (`reframe.jobs.DETECTION_WAIT`, a constructor argument), then validates again. C-4's
   hardware tests time out after 10 s each, three at a time, so 60 s covers a detection where
   every test fails slowly. After the wait, the job is validated with the statuses known then
   and gets an info issue `encoder.detection_timeout`. With hardware tests off nothing runs,
   so nothing waits. M2 demo item 4 ("nothing hangs") holds even when a test encode hangs:
   the CLI test with a hanging fake encoder ends in about a second.
6. A source that cannot be probed is a `source.probe_failed` error in `validate` and `plan`
   (a `ProbeError` from `draft`). A `PlanError` of C-7 after validation passed (a bug: 0026
   says they agree) becomes a `plan.failed` error instead of an exception.
7. `JobService.validate(job)` finds the naming options through `job.preset_id`; a job of a
   preset that was deleted uses Settings → Output.

### Extra facade methods

8. `JobService.name(path, *, preset, template, root)`: C-16 on the path alone (no probe), for
   `reframe name`. `JobService.media_files(paths, *, recursive)` /
   `reframe.jobs.find_media_files`: the files of `reframe encode`. These keep the CLI on the
   facade.

### Folder search (`reframe encode DIR`, `reframe name DIR`)

9. A folder gives its media files by C-3's list (`MEDIA_EXTENSIONS`, case-insensitive), in
   natural order (`E2` before `E10`), hidden files and folders left out, and Reframe's own
   partial outputs (`*.part.<ext>`) left out. Subfolders only with `-r/--recursive` (encode).
   A file named on the command line is taken whatever its extension (ffprobe decides). A file
   given twice (also through its folder) is encoded once. A path that does not exist stops
   the command before anything is queued (exit 3): a typo should not encode half a season.

### `reframe encoders`

10. Lines `<id> — <state>`: `available` (with the VAAPI node and `8-bit only` for hardware
    encoders without 10-bit), `unavailable: <reason>`, `error: <reason>`, `not tested[:
    reason]`, `checking…`. No column padding, so the demo text
    `hevc_nvenc — unavailable: NVIDIA driver not found` appears exactly.
11. With a cache: a header with the cache time, every cached status, `Checking again…`, then
    only the statuses that change, then `Done in N s: A available, B not available (no
    changes | K changed since the cached result).` Without a cache: one header line, then
    each status as detection decides it (no `checking…` lines). The command waits for the
    detection task to end before it closes Reframe: closing at the last event cancelled C-4's
    cache write (seen in the tests; see Consequences).
12. `--json` waits for the result and prints the `CapabilitySnapshot`.

### `reframe plan`

13. Output: the source name; `Preset`, `Output`, `Name` (template and why that name source),
    `Note` lines, one `Audio` line per source track with C-12's reason; then `Issues (E
    errors, W warnings, I info)`, errors first, each with `[code · path]` and one `fix:` line
    per fix; then `Command (<job type>, N steps)` and the plan's `display` on **one line**
    (not wrapped), so it can be copied into a terminal. With errors: `No command: the job has
    errors.` `--json`: `{"draft": JobDraft, "plan": EncodePlan | null}`.
14. `--preset` is optional (the default preset), as for `encode`.

### `reframe encode`

15. Every file is drafted and validated first. A file whose draft has errors (or that cannot
    be probed) is reported with its errors and warnings and not queued (0018); queued files
    show their warnings (info only in `reframe plan`). Each file gets a label `[i/n]` and
    one line `name → output path`.
16. **The queue is shared** (the SQLite queue of C-11 may hold jobs of another UI). `encode`
    adds its jobs **at the front** (`add(job, position=i)`), starts the queue, and calls
    `stop()` as soon as none of its jobs is waiting, so the queue starts no other job. With
    `parallel_jobs` above the number of its jobs, another waiting job can still start next
    to them; it is cancelled when the command closes Reframe. Jobs stay in the queue after
    the command (as its history).
17. **Progress**: on a terminal one rich progress bar per running job (percent, fps, speed,
    ETA, size, step); otherwise plain lines: `[i/n] 42.0% · 87.3 fps · 3.64x · ETA 0:01:23 ·
    12.3 MiB`, at most one per 10 % of the job or every 30 s. State lines: `running`,
    `paused`, `resumed`, `done in H:MM:SS: <output>`, `failed: <error>` with the log path,
    `cancelled`, `interrupted`. Last line: `Summary: D done, F failed, C cancelled[, I
    interrupted], N not queued.`
18. **Ctrl+C**: `asyncio.run` cancels the command's task (on Linux and Windows alike; FFmpeg
    does not see the Ctrl+C, because C-1 starts it in its own session / without a console).
    The command stops the queue, cancels its waiting jobs, then its running ones
    (`QueueService.cancel(id)`: tree kill, `.part` removed), waits up to 30 s for them to end,
    prints the summary and exits with 130. A second Ctrl+C stops at once.
19. **The one place for the queue** is `reframe.cli.get_queue(app)`. Until C-11 is merged it
    returns `None` and `encode` says that this build has no queue (exit 1); the tests replace
    it with a fake queue that follows the contract.

### `reframe name`

20. No probe: the media variables (`{resolution}`, …) are empty; `reframe plan` shows the
    full name. Output per file: `Source` (file or folder, and why), `Parsed` (the fields in a
    fixed order), `Template` (and movie / episode), `Name` (the rendered name without the
    extension: `Hacksaw.Ridge`), `File` (the full path), notes and issues. A path that does
    not exist is named from its text, with a note. A folder names its media files, with the
    folder as the root that generic-folder skipping does not go above. `--preset` picks the
    naming options and container; `--template T` replaces the movie and episode templates; a
    template with errors is a usage error (exit 2).

### Exit codes (all commands)

21. `0` success; `1` failure (ffprobe could not read the file, validation errors, a job
    failed / was cancelled / was not queued, a name with errors); `2` usage (click errors, an
    unknown preset, `-o` with more than one file, a bad `--template`); `3` a path does not
    exist or cannot be read, or no media files; `4` no usable ffprobe (`probe`, `plan`) or
    ffmpeg (`encoders`); `130` Ctrl+C. Errors are one `error:` line on stderr.

## Consequences

- `reframe encode` cannot run until C-11 is merged; the follow-up changes only `get_queue`.
- The source-name collision rule (item 3) applies to every draft, also in the UI later. The
  lead or the user may prefer another default (for example a fixed output folder); it is one
  place in `JobService._compose`.
- `-o DIR` for a whole season is not allowed (0018: `-o` only with a single file).
- Found in C-4 (reported to the lead): `Reframe.close()` right after the final
  `capabilities.changed` event can cancel the cache write that the detection task does after
  that event, so the next start has no cache. `reframe encoders` waits for the task; other
  short-lived callers may want the same, or C-4 could publish the last event after the write.

## Plan changes

- [05-core.md §C-15](../plan/05-core.md#c-15-service-facade-and-cli): `jobs` lists the M2
  methods; the CLI line shows the optional `--preset` and the new options.
