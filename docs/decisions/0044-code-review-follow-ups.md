# 0044 — Several default tracks, x264 warnings in the dry run, paths that are not UTF-8, async preview lookups

- Status: accepted
- Date: 2026-10-20
- Steps: C-8, C-12 (lint), C-6 (dry run), C-2 (models), C-15 (facade, CLI), C-9 (settings), C-10
- Supersedes in part: [0030](0030-core-complete-contract.md) (`sources.frame` and
  `jobs.preview_clip_path` are async), [0035](0035-advanced-option-sets-and-dry-run.md) §5
  (which log lines are encoder warnings; a warning validation gives is not repeated)

## Context

A review of the code after the comment trim (branch `code-problems`, 2026-10-19) left four
questions for the owner. The owner chose to fix all four:

1. **Several default tracks of one kind.** A batch rule with `multiple` and `default: true`
   marks every track it takes as default, and two rules of one kind with `default: true` do the
   same ([0040](0040-batch-engine-and-reframe-batch.md) §2: an explicit default wins). Plan 03
   §Track metadata allows it ("only one track per type can be default, unless you override
   this"), but nothing told the user. FFmpeg n9.0.2 writes both flags in MKV and MP4:
   `ffmpeg … -disposition:a:0 default -disposition:a:1 0 -disposition:a:2 default two.mkv`,
   then `ffprobe -show_entries stream=index,codec_type:stream_disposition=default` gives
   `default=1`, `0`, `1` for the three audio streams (the same for `two.mp4`).
2. **The dry run never saw x264's warnings.** Through FFmpeg, libx264 logs as
   `[libx264 @ 0x…] VBV maxrate specified, but no bufsize, ignored`, with no level word, like
   its info lines (`using SAR=1/1`). 0035's rule "an encoder warning that names a parameter is
   `encoder.dry_run_warning`" matched only x265's and SVT-AV1's own lines (`x265 [warning]:`,
   `Svt[warn]:`). Also, x265's warning about a field that validation's option rules already
   report (VBV maxrate without a buffer, `max-tu-size` with `ctu`, `limit-refs` with `pmode`,
   SVT-AV1 `hierarchical-levels` with `irefresh-type`) was reported twice: once by validation,
   once by the dry run.
3. **Paths that are not UTF-8 could not be written as JSON.** On Linux such a byte is a lone
   surrogate in Python (`\udcff`, PEP 383). Pydantic's `model_dump_json()` raises on it:
   `reframe probe --json` of `bad\xffname.mkv` ended with `error: unexpected error
   (PydanticSerializationError: … surrogates not allowed)`, and the settings and preset
   files were not saved (`settings.write_failed`) when a path held such a byte. Issue
   messages that quote such a path had the same problem ([0016](0016-queue-and-job-runner.md)
   "Not fixed here").
4. **The facade's preview lookups blocked the event loop.** `sources.frame(key)` and
   `jobs.preview_clip_path(id)` stat and touch the cache file (a hit is the last use, 0033) on
   the caller's thread; the server routes of 0033 will call them from the event loop.

## Decision

1. **Allowed, with a warning.** A job whose output has two or more audio tracks, or two or
   more subtitle tracks, marked default gets `metadata.several_defaults` (warning, one per
   kind, at the second default track), with the fix *Keep only <kind> track N default*. The
   flag is the one the plan writes (the command builder's dispositions, or the mkvpropedit
   step); a burned-in subtitle is not an output track. The track rule lint
   (`reframe.batch.lint.lint_track_rules`, run by `validate_template`) gives the same code
   for a `multiple` rule with `default: true` (fix: take the flag from the source) and for
   two or more rules of one kind with `default: true` (fix: only the first rule's tracks).
2. **FFmpeg tags each log line with its level.** The dry run adds `-loglevel +level+info`
   (the leading `+` keeps the folding of repeated lines; `level+info` turns it off). The tags
   are removed before the log is parsed, so every other pattern reads what it read before.
   An encoder warning is x265's or SVT-AV1's own line, or a line whose first log context is
   the job's encoder at the warning level (`[libx264 @ 0x…] [warning] …`, also libvpx and the
   hardware encoders: `av1_vaapi` `tile_groups=3` gives `Invalid tile groups number 3,
   correct to 1.`). A warning about a field that validation's option rules already report
   (the issue's path, or a field one of its fixes changes) is left out: the user sees one
   issue per problem, validation's, which has the better message and fixes. A failed start
   that names no failure word now shows the encoder's first line at the error level
   (libvpx: "Rate control parameters set without a bitrate", not its version line).
3. **Display text never holds the byte; data keeps it.**
   - Free text for people in the models (issue messages, fix labels, event and task text,
     reasons, notes, the command preview) is `reframe.models.text.DisplayText`: a byte that
     is not UTF-8 becomes `�` when the model is validated and again when it is dumped. This
     does not change the JSON Schema.
   - Paths, patch values, track titles, tags and other user data keep the byte.
     `reframe.models.json_text` writes a model or JSON data with `\udcXX` escapes; Python's
     `json.loads` and JavaScript's `JSON.parse` (node v26.10.0) read the same string back.
     The queue store, every CLI `--json` writer, `presets export -o` and the settings and
     preset files use it. Their bytes for normal names are unchanged.
   - `model_dump_json()` still refuses a model whose path or patch value holds the byte, and
     `model_validate_json` refuses the escape: the server (S-2) writes responses and
     WebSocket events with `json_text` and reads request bodies with `json.loads` +
     `model_validate`.
4. **The facade's lookups are async.** `await Reframe.sources.frame(key)` and
   `await Reframe.jobs.preview_clip_path(clip_id)` run the lookup in a worker thread, as
   `preview_cache_size` does. `reframe.preview.frame_path` and `clip_path` stay synchronous
   and are documented as blocking.

## Consequences

- A remux or an in-place edit of a file that already has two default tracks of a kind (an
  mkvmerge file often has) now gets the several-defaults warning; it is true of the output.
- The dry run reports warnings of NVENC, QSV and AMF through the same rule; they were not
  checked on hardware.
- The queue's own `printable` still writes such a byte as the text `\udcff` in job errors and
  log lines (0016 point 5); other display text shows `�`.
- Left open: `parse_dry_run` keeps one issue per code and path, so a second warning about
  custom parameters is not shown; some encoder messages name no parameter Reframe can link
  (`g_lag_in_frames`, `mb-tree`, `CBR HRD`); `JobService` still reads `presets.json` on the
  event loop at its first use.

## Plan changes

- `03-features.md` §Track metadata (the Default row) and §Output naming (a name that is not
  UTF-8 can be written in JSON).
- `06-web-app.md` S-2: how the API writes and reads JSON.
- `docs/core-breakdown.md`: `frame` and `preview_clip_path` are `async def`.
