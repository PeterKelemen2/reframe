# 0038 — CLI: `tools status|fetch`, `presets list|export|import`, the plan dry run, the when-done countdown

- Status: accepted
- Date: 2026-10-15
- Steps: C-15 (with C-14, C-11, C-6 through their contracts)

## Context

[05 §C-15](../plan/05-core.md#c-15-service-facade-and-cli) lists `reframe tools status|fetch`
and `reframe presets list|export|import`; [02 §Bundled FFmpeg](../plan/02-architecture.md#bundled-ffmpeg)
and [06 §S-6](../plan/06-web-app.md) say that `reframe tools fetch` downloads the pinned build of
`tools/ffmpeg.toml` (checksum verified) into `<data dir>/tools/ffmpeg`, where it counts as the
bundled build. [03 §Presets](../plan/03-features.md#presets) has import / export with rename,
replace or skip; 03 §Queue has the when-done actions; 03 §Advanced encoder options says custom
parameters are "validated by a dry run". The contract of the core-complete breakdown
([0030](0030-core-complete-contract.md)) adds `Reframe.tools.fetch` → `start_fetch`,
`jobs.plan(…, dry_run=True)` and `Reframe.power`. Decision [0017](0017-jobs-service-and-cli.md)
sets the output style and exit codes; [0028](0028-preset-export-keeps-newer-presets.md) the export
document.

The plan does not say how the installed package finds the manifest, what `--platform` does
with a build for another computer, what `presets export` without names exports, when `plan`
runs the dry run, or what the CLI does with a when-done countdown and with `quit`. This record
makes those choices; each is one place in the code and easy to change.

What the real tools showed (testdata/README.md, "Tools fetch and the CLI (C-15)"): the pinned
BtbN n9.0.2 build, packed again and served by `http.server` on 127.0.0.1, is fetched, checked,
installed and then found as `bundled` in 5.6 s; a second run downloads nothing.

## Decision

### `reframe tools status`

1. Prints the lines of `python -m reframe.tools` (one shared function,
   `reframe.tools.__main__.status_lines`) and one line about the fetched build (from the
   marker in `<data dir>/tools/ffmpeg`). `--json` prints the `ToolSet`.
2. **Exit code 4** when ffmpeg or ffprobe cannot be used (0017's code for "no usable
   ffprobe / ffmpeg"), with one `error:` line per tool; when no override decides the path, the
   line says that `reframe tools fetch` installs the pinned build. mkvpropedit and MediaInfo are
   optional and never change the exit code.

### `reframe tools fetch`

3. **The manifest in the package.** `packages/reframe/src/reframe/tools/ffmpeg.toml` is a copy
   of `tools/ffmpeg.toml` (package data: hatch puts every file under `src/reframe` in the
   wheel). A test fails when the two differ, and another checks that the core and
   `scripts/fetch-tools.py` read the same values from it. The repository file stays the one
   to edit (tools/README.md "Update a pin"); copy it after a change.
4. **No shared code with `scripts/fetch-tools.py`.** The script must run before `uv sync`
   (`uv run --no-project`, standard library only) and its tests replace its module-level
   functions (`download`, `detect_platform`); a shared module would need path tricks and
   would break those tests. The core module (`reframe.tools.fetch`) repeats the manifest
   checks and the safe extraction, adds progress, cancel and the version check through
   `reframe.tools.run`, and uses the script's marker (`.fetch-tools.json`, same format), so
   each recognises the other's install (a test checks both ways).
5. **URLs.** The manifest URL must be `https://`, as in the script, but the core also accepts
   `file:` URLs and `http://` on the loopback address (tests, a local mirror). The size and
   SHA-256 are checked either way.
6. **Steps.** An install whose marker names the same archive and whose files all keep their
   recorded hashes is kept (nothing is downloaded). A non-empty folder without the marker is
   never replaced. The download (4 attempts on network errors and HTTP 429 / 5xx; never more
   bytes than the pinned size) goes to `<data dir>/tools/.fetch-*`; size and SHA-256 are
   checked before anything is extracted; extraction refuses absolute paths, drive letters,
   backslashes, `..`, `:` and links that leave the archive's folder before a file is written.
   On the host platform `ffmpeg -version` / `ffprobe -version` of the **extracted** build must
   print the pinned version; only then the old build is moved aside, the new one moved in, and
   the old one removed (moved back if the swap fails). Then tool discovery runs again. A failure
   ends the task `failed` with the reason; the old build stays as it was.
7. **`--platform` for another computer** (`windows-x64` on Linux) downloads and checks the
   build but installs it into `<data dir>/tools/ffmpeg-<platform>`, which discovery never
   searches: a Windows build in `<data dir>/tools/ffmpeg` would make this computer's bundled
   FFmpeg "broken", and discovery never falls back to `PATH` from a broken bundled build
   (0005). The CLI says to copy the folder to the other computer.
8. **Output.** First line: version, build, platform and URL. Then the task's progress: a rich
   bar on a terminal; otherwise one line per step and a percentage line every 10 %. Then
   `Installed FFmpeg <version> into <dir>.` (or `… is already installed … nothing was
   downloaded.`) and the tool lines. A `warning:` line when an environment variable or a
   Settings path still decides ffmpeg / ffprobe. Exit codes: `0` installed or already
   installed; `1` download, checksum, archive or version check failed, or no build for this
   computer; `2` unknown build, or a platform the build has no archive for; `130` Ctrl+C (the
   task is cancelled: the download stops within one 1 MiB block, the temporary folder is
   removed, nothing is installed).
9. **An expected failure in a task is one line.** The task manager logs a failed task with
   its traceback (`log.exception`), and with no logging configured Python prints that on
   stderr. The CLI drops the log record of a task that ended with `TaskFailed` (an expected
   failure, decision 0030) and prints the reason without the `TaskFailed:` prefix that
   `TaskInfo.error` has today.

### `reframe presets`

10. **`list`**: the built-ins in their order, then the user presets; columns name, category,
    id, kind (`built-in` / `user`); `*` marks the default; a legend line with the counts.
    `--json` prints `{"default_preset_id", "presets": [{id, name, category, description,
    built_in, default}]}`, not the full presets (`export` gives those).
11. **`export [NAME_OR_ID…] [-o FILE]`**: no names = **every user preset** (the store's
    `export(None)`); names (without case) or ids select presets, built-ins too; an unknown
    name is a usage error with the closest names. The output is `PresetExport.document()`
    (0028: presets of a newer Reframe are in it unchanged, each with a `warning:` line) as
    JSON on stdout (`-o -` too) or in FILE (UTF-8, written through a temporary file and a
    rename). No user presets: the empty export is written, with a warning, exit 0. Exit codes:
    `1` FILE cannot be written, `2` unknown preset or FILE is a folder.
12. **`import FILE [--on-conflict rename|replace|skip]`** (default `rename`, as the store):
    FILE `-` reads stdin; a UTF-8 BOM is accepted. Output: the imported presets with their
    ids (and the name they were renamed from), the replaced and the skipped ones, then the
    issues as in `reframe plan`. Exit codes: `3` FILE does not exist or cannot be read; `1`
    not JSON / not an object / not a preset file, **or any warning or error issue** (a preset
    that was left out: invalid, newer, a file that cannot be written); `0` otherwise, also when
    `skip` skipped every preset (that is no issue).

### `reframe plan`: the dry run

13. `plan` passes `dry_run=True` to `jobs.plan` when the job's video has custom parameters
    that are used (not with video passthrough) **and they are not the unchanged parameters of
    a built-in preset**. Most built-in x265 / SVT-AV1 presets carry custom parameters
    (HandBrake's), so the plain rule would encode a frame on every `reframe plan` with the
    default preset; Reframe's own tests check the built-in parameters against the pinned
    build. Dry-run errors are printed like other issues (exit 1, `No command`), and so are its
    warnings (a setting the encoder changed, a test encode that did not run); a dry run that
    ran without an error adds the note "The custom encoder parameters were checked by encoding
    one frame (dry run)." `encode` does not dry-run (it validates as before). (Follow-up
    2026-10-16 below: `plan` calls `jobs.dry_run` itself.)

### `reframe encode`: the when-done countdown

14. After its jobs, when Settings → Queue → When done is `sleep` or `shutdown`, `encode`
    waits for the countdown that the queue starts as the last job ends (`power.pending`, or a
    `power.countdown` event within 2 s), and shows it: `Shutting down in 60 s — press Ctrl+C
    to cancel` (`Going to sleep in …`), counting down in place on a terminal, otherwise one line
    every 10 s; then `Shutting down now.` or, when another front end cancels it, `Cancelled:
    the computer will not shut down.` After `executing` it gives the power service up to 30 s
    to finish before Reframe closes. Ctrl+C cancels the countdown with `power.cancel(id)`, prints
    `Interrupted: the countdown is cancelled, the computer will not shut down.` and exits 130.
    Otherwise the exit code is the jobs' one. With any other setting nothing is waited for.
15. **`quit` in a CLI means nothing extra**: the command ends by itself when its jobs end, so
    it does not wait for the quit countdown; closing Reframe cancels it (`PowerService.close`).

## Consequences

- `reframe tools fetch` works from an installed wheel without the repository. A pin update
  needs the copy in the package too (the test says so). tools/README.md "Update a pin" should
  say it (a lead-owned file).
- A fetch for another platform never changes what this computer runs.
- `TaskInfo.error` of a `TaskFailed` task still starts with `TaskFailed: ` and the task manager
  still logs a traceback for it: the core (`reframe.tasks`) should treat `TaskFailed` as 0030
  says (message only, no traceback). The CLI handles both forms.
- A user preset with custom parameters costs one encoded frame per `reframe plan`.
- The countdown is tested against a fake power service and a fake queue; the real C-14 /
  C-11 services are built in parallel. If the real service clears `pending` before its
  executor has finished, `encode` may close Reframe (and with it the power service) while the
  action runs: C-14 should keep the countdown pending until the executor returned, or its
  `close` should not cancel an action that is executing.

## Follow-up (core-complete review, 2026-10-16)

**R5-2 (the dry run's warnings).** `reframe plan` passed `dry_run=True` to `jobs.plan`, which
returns only the plan when the dry run has no error: the dry run's warnings were dropped
(`encoder.dry_run_warning`, for example x265's "limit-tu disabled, requires tu-inter-depth >
1" for `limit-tu=2`, and `encoder.dry_run_skipped`: no FFmpeg or the 30 s timeout), and the
note "The custom encoder parameters were checked …" was printed even when the test encode did
not run. Now `plan` calls `jobs.dry_run` itself (`jobs.plan`'s contract is unchanged; its
docstring says that a plan carries no warnings), adds every issue of the dry run to the
draft's issues (human output and `--json`), plans only when the dry run has no error, and
prints the note only when the test encode ran (no `encoder.dry_run_skipped`). Checked with the
real FFmpeg n9.0.2 and a user preset with `limit-tu=2`: `Issues (0 errors, 1 warning, …)`,
`warning  The encoder changed a setting: limit-tu disabled, requires tu-inter-depth > 1`, the
note and the command. Tests: `tests/jobs/test_cli_review_fixes.py`
(`test_plan_shows_a_skipped_dry_run`, `test_plan_shows_the_dry_runs_warnings`).

**R5-9 (control characters of preset names).** `reframe presets import` and `presets list`
printed a preset's name, category and id as the file gave them: a shared preset named
`Evil\x1b[31mRED…` coloured the terminal (`od -c` of the output: `033 [ 3 1 m`), and `ESC ]0;`
set the window title. The CLI's `printable` (every human line goes through it) now shows each
C0 control character (the line break and the tab too), DEL and each C1 control character as
U+FFFD; `_one_line` (the `error:` / `warning:` lines) first joins white space into one space.
`--json` keeps the names unchanged (JSON escapes them). Text with line breaks of its own is
printed line by line, so nothing that the CLI writes on purpose changes. Tests:
`tests/jobs/test_cli_presets_review_fixes.py` (`test_r5_9_*`).

**The size of `presets import`** (suspected in the review, real). The file was read whole:
`reframe presets import /dev/zero` read until memory ran out, and a FIFO blocked the command.
Now at most 16 MiB (`MAX_PRESET_FILE`) are read, from a file or from stdin; a larger one is
"not a Reframe preset file" (exit 1), and the file is opened without blocking and must be a
regular file (else exit 3, "is not a regular file"). Tests:
`test_import_refuses_a_file_larger_than_the_cap`, `test_import_never_reads_a_device_or_a_fifo`
(with `/dev/null`: the unfixed code reads `/dev/zero` without end),
`test_import_from_stdin_is_capped`.

## Plan changes

- [05-core.md §C-15](../plan/05-core.md#c-15-service-facade-and-cli): the CLI line shows the
  options of `tools fetch`, `presets export` and `presets import`, and names this record.
