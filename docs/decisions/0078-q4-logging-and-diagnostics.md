# 0078 — Q-4: the app log, its level, and Copy diagnostics

- Status: accepted
- Date: 2026-11-14
- Steps: Q-4 (C-11, D-3, F-15, S-2)

## Context

[09 §Q-4](../plan/09-quality-and-release.md#q-4-logging-and-diagnostics) has three bullets:

> - Structured logs (JSON lines) in `<data>/logs/reframe.log`, with rotation. Log level is set in
>   Settings.
> - Per-job logs (`C-11`), sidecar log (`D-3`).
> - **Copy diagnostics** in Settings: app version, OS, tool versions and build flags, encoder
>   statuses with reasons, settings with secrets removed. Used in bug reports.

What exists (checked on 2026-11-14, `m10-hardening` at 95bda45):

- About 25 modules of `reframe` and `reframe_server` have a `logging.getLogger(__name__)`, but
  nothing configures the root logger, so their records go to Python's last-resort handler
  (stderr, WARNING and above, no time). The server gives uvicorn a log config that writes to
  stderr (`reframe_server/__main__.py`, `_log_config`).
- **Per-job logs (C-11): built.** `<data>/logs/<job id>.log`, the command line and FFmpeg's
  stderr (`reframe/queue/logs.py`); removed with the job.
- **The sidecar log (D-3): built.** The desktop shell writes the sidecar's stderr to
  `<data>/logs/sidecar.log`, moved to `sidecar.log.1` above 1 MiB when a sidecar starts
  (`desktop/src-tauri/src/backend/sidecar.rs`). A server that a CLI client starts writes its
  stderr to `<data>/logs/server.log` (`reframe/remote/owner.py`, [0042](0042-one-scheduler-process-and-cli-clients.md)).
- `ToolInfo` already keeps each tool's version, release, build flags and library versions "for
  diagnostics" (C-1); `CapabilitySnapshot` keeps each encoder's status and reason (C-4).
- `AppSettings` has no secret today. The server's token and password are in `ServerConfig` and
  `auth.json`, not in `settings.json`.

## Decision

1. **Who writes `reframe.log`.** Only the server process that owns the queue store (the one
   scheduler of 0042: web mode, the desktop's sidecar, or the owner a CLI client starts), from
   the moment it has the store's lock. A server that does not own it (a second server on the
   same data folder, a desktop sidecar without `--owner-only` beside a web owner, an
   `--owner-only` server that exits 75) writes no `reframe.log`. One writer, so size rotation
   needs no lock across processes and works on Windows (the handler closes its file before the
   rename). A rename that still fails (another program has the file open) is not fatal: the
   file is opened again and grows until the next rename works. CLI commands that run without a
   server (`probe`, `plan`, `name`, …) keep their stderr output and do not write `reframe.log`.
2. **The format.** One JSON object per line, UTF-8: `time` (ISO 8601, UTC, milliseconds),
   `level`, `logger`, `message`, and when there is one `exception` (the formatted traceback)
   and the record's context (`job_id`, `task_id`, … given through `extra`). A value that is not
   JSON (bytes that are not UTF-8, a circular value, NaN) is written as text. Rotation by size:
   5 MiB, three old files (`reframe.log.1` … `.3`).
3. **What goes in.** Reframe's own loggers (`reframe`, `reframe_server`) at the level of the
   setting; no other logger below INFO, whatever the setting is: libraries log request headers
   and WebSocket frames at DEBUG (the WebSocket library, through `uvicorn.error`, logs the
   session cookie and the auth message's token). `uvicorn.error` (start-up, shutdown, errors)
   is written from INFO up and its level is never changed; other libraries from WARNING up.
   `uvicorn.access` is not written: it would log every poll and the paths in the query strings.
   Stderr stays as it is (plain text), so `sidecar.log` and `server.log` keep working.
4. **The level is a setting.** `AppSettings.diagnostics.log_level`: `error`, `warning`,
   `info` (default) or `debug`, shown in a new **Diagnostics** section of Settings. A change
   applies at once, without a restart. A new sub-document with a default: an older version
   keeps it as an unknown field (`DocumentModel`), so `schema_version` stays 1.
5. **A log that cannot be written** (the folder read-only, the disk full) does not stop the
   server: one line on stderr says why, and the server runs without the file. Only an error
   of the file does that; a record that cannot be written for another reason is dropped alone.
6. **Copy diagnostics.** `GET /api/diagnostics` returns `{text, logs_dir}`. The core builds
   the text (one plain-text report, the same for every client), and the Diagnostics section
   copies it with a short client part added (the browser's user agent, the device pixel ratio,
   web or desktop). The report holds:
   - Reframe's version, the server's mode and login kind (never the token or the password), the
     OS and its version, Python's version;
   - each tool: status, origin, path, version, release, build flags, library versions, reason;
   - each encoder: status and reason (the snapshot as it is; a running detection is said so,
     not waited for);
   - the settings: the known fields only (an unknown field from a newer version could hold
     anything), with no secrets (there are none today; a future secret setting must be left
     out here);
   - the log files: `reframe.log`, the job logs' folder, `sidecar.log` and `server.log` when
     they exist.
   Paths under the user's home folder, or under the folder it links to, start with `~` (the
   user name is often in them).
7. **Per-job logs and the sidecar log** are already built (Context). Q-4 names their folder in
   the report and in the Diagnostics section; it does not change them.

## Consequences

- A bug report can carry the app log and the diagnostics text without the user's home path.
- `reframe.log` holds what Reframe's loggers say: a module that logs nothing useful is a gap
  that later work fills, not part of Q-4.
- A CLI-only run (no server) has no `reframe.log`.

Owner questions (built with the default; easy to change):

- A `reframe diagnostics` CLI command (for Docker or a headless server): not built, Settings
  only, as the plan says.
- A button that opens the logs folder (desktop: reveal in the file manager): not built; the
  Diagnostics section shows the folder's path.

## Plan changes

09 §Q-4: the bullets link here.

## Task P: the app log and the diagnostics report (Python)

Built (2026-11-14, Linux):

- **`reframe/applog.py`**: `install(folder, level, *, max_bytes, backup_count)` returns an
  `AppLog` (or `None` when the file cannot be opened). The server's lifespan installs it after
  `owner.start`, only when `reframe.queue.owns_store`, and closes it after `reframe.close()`;
  `app.state.app_log` holds it.
  One `RotatingFileHandler` (5 MiB, 3 old files, UTF-8) is reached through two small
  forwarders: one on the root logger and one on the `uvicorn` logger, because uvicorn's log
  config sets `propagate: false` on `uvicorn` (checked in `uvicorn.config.LOGGING_CONFIG`), so
  `uvicorn.error` never reaches the root logger in a real server. The handler's filter takes
  `reframe*` and `reframe_server*` from the setting's level, `uvicorn.error*` from
  `max(INFO, setting)`, every other logger from `max(WARNING, setting)` (at `error`, a
  library's warning is left out too, as for Reframe's own warnings), and never
  `uvicorn.access`.
- **Stderr stays as it was** (item 3). Two details make that true: (1) to let DEBUG records
  through, the level of Reframe's loggers is lowered, never raised above the level it had, so
  at `error` their warnings still reach stderr; no other logger's level is changed; (2) a
  handler on the root logger stops Python from using `logging.lastResort` (stderr, WARNING and
  up, used only when a record finds no handler), so when the root logger had no handler,
  `lastResort` itself is added while the log is installed.
- **Closing** removes every handler it added; once the last open app log is closed, each
  logger level and `lastResort` are as they were before the first one opened, in whatever
  order they close. `set_level` after `close` does nothing. Tests set known levels first and
  compare the absolute values after the close.
- **A failed write** (item 5): when the error is an `OSError`, the handler's `handleError`
  prints one stderr line (`reframe: the app log … cannot be written (…); the server runs
  without it`) and turns the handler off; Python's default prints a traceback per record.
  Another error drops that record only. A file that cannot be opened: one line, `install`
  returns `None`, the server serves.
- **The level** (item 4): `Reframe.create(..., on_log_level=callback)` (a keyword-only
  parameter with a default). `_settings_changed` calls it with the new level when
  `diagnostics.log_level` changes, before `settings.update` returns, so `PUT /api/settings`
  answers after the file has the new level. Not a public `Reframe.on_log_level(...)` method:
  a new public facade member must be reached by a route or listed in 06's "Not exposed" table
  (`test_facade_coverage.py`), and `Reframe.create` is already listed there.
- **The report** (item 6): `reframe/diagnostics.py` `build_report(...)` and the facade's
  `Reframe.diagnostics(*, server=None)`. That method waits for a running tool discovery
  (`tools.status()`), reads `capabilities.snapshot` without waiting, and builds the text in a
  thread. The route adds `Mode` and `Login` (`config.auth_mode`) and returns `logs_dir` with
  `~`. Parts in a fixed order: the head (version, mode, login, OS, Python), Tools (each tool:
  status, origin, path, version, release, build flags, libraries, reason), Encoders (sorted by
  id: state, reason, detail; "detection running" and "from the cache" when true), Settings
  (`a.b.c = <JSON>` for the declared fields only, walked from `model_fields`, so an unknown
  field at any depth is left out), Logs (the folder, `reframe.log` and `.1`–`.3`,
  `sidecar.log`, `sidecar.log.1`, `server.log` with sizes when they exist, and the number of
  job logs).
- **`~`** is applied to the whole text, not only to path fields: FFmpeg's build flags often
  hold `--prefix=/home/<user>/…` or `-I/home/<user>/…`. The home folder and the folder it
  links to (`os.path.realpath`) are both replaced. A match must end at a separator, a quote, a
  space, the end, or a full stop that ends a sentence (`/home/ann.bak` is another folder), and
  a longer path that only contains the home path (`/srv/home/ann`) is left alone. On Windows the match ignores case
  and takes `\`, `/` and the doubled `\\` of JSON text; a home at a drive root or `/` changes
  nothing.
- **No subprocess for the OS line**: `platform.platform()` runs `uname -p` (checked with a
  spy on `subprocess.check_output`, Python 3.14), and `platform.uname()` on Windows can fall
  back to `cmd /c ver`. The report uses `os.uname()` and `/etc/os-release` on POSIX and
  `sys.getwindowsversion()` with `platform.win32_edition()` (the registry) on Windows.
- **Secrets in the existing log calls** (item 4 of the brief): none of Reframe's own log calls
  logs the token, the password or a session cookie, but libraries do at DEBUG (Fix round FP);
  so no logger but Reframe's is written below INFO. `uvicorn.error` logs the WebSocket path
  with its query string at INFO, but `WS /api/events` takes its token in the first message,
  not in the URL. The signatures of the media URLs appear only in the access log, which is
  never written.
- **Not built:** the report does not list the build's filters (`filter_failures`, such as
  libplacebo). Item 6 does not name them.
- **Windows:** the Windows code paths of the report are unit-tested on Linux: the OS line
  (`_windows_os`, with `getwindowsversion` and `win32_edition` passed in) and the `~` of a
  `%USERPROFILE%` path; they run on Windows only in the Windows phase (0053).

## Task U: the Diagnostics section (frontend)

Phase 1 (against the stub, mocked reports in the tests):

- **Place.** `components/settings/DiagnosticsSection.vue`, a section of Settings after
  Appearance and before the desktop app's own section (that one stays last), with its link and
  `/settings#diagnostics`.
- **Log level (item 4).** A `Select` of the four levels with plain labels (Errors only,
  Warnings and errors, Normal, Detailed (debug)) and one line of help that says a change applies
  at once. One `useSetting('/diagnostics/log_level')` change per pick; disabled when the
  settings are read-only. A document without `diagnostics` shows `info` (the default).
- **Logs folder (items 6, 7).** `logs_dir` of `GET /api/diagnostics`, read once when the
  section mounts, in a read-only text field (selectable, in the Tab order) with a visible line,
  linked by `aria-describedby`, that names `reframe.log` and the job logs, and `sidecar.log` in
  the desktop app (phase 2 adds the rest). A failed read is an issue at the field. The section
  has no other use of the report at mount.
- **Copy diagnostics (item 6).** The report is read again when the button is pressed, so it
  holds the state at that moment. The client part is appended after a blank line, not
  translated (the bug report's reader reads it): a `Client` section with `kind`
  (`platform.kind`), `user agent` and `device pixel ratio`. Written with `navigator.clipboard.writeText`. A live
  region (`role="status"`, in the page before the press) says "Reading the diagnostics…", then
  "Diagnostics copied to the clipboard." or the failure in plain words. When the clipboard
  refuses the text or is missing (a web server over plain http is not a secure context), the
  report shows in a read-only text area, focused and selected, so Ctrl+C or the context menu
  copies it. A failed read says why and copies nothing. The button is never disabled while it
  reads (a disabled button drops the keyboard focus to the page); a second press then does
  nothing.
- **Clipboard checked in the engines (Playwright 1.64.1, headless, `e2e` server on this host,
  2026-11-14).** `writeText` after an awaited `fetch`, after 3 s, and `clipboard.write` with a
  `ClipboardItem` of a promise: Firefox and WebKit accept all of them without a permission;
  Chromium refuses every write ("Write permission denied") unless the context has
  `clipboard-write`, and then accepts all of them (read back with `readText`). So Playwright's
  engines do not show a user-gesture rule for a write after the fetch. The desktop app's
  WebKitGTK webview was checked by review R1 (WebKitGTK 2.54.2, Tauri's default with
  `javascript-can-access-clipboard` off, headless KWin, a synthetic click): a write with no
  gesture is refused (`NotAllowedError`); after a click it works at once, after an awaited fetch
  (Reframe's pattern) and after a 3 s fetch, and the clipboard really held the text. If it ever
  refuses the write, the user gets the report to select.
- **The gate.** `settings-diagnostics` (the section) and `settings-diagnostics-report` (the
  report shown after the clipboard is removed from `navigator`) in `e2e/a11y/screens/shell.ts`;
  `known/shell.ts` stays empty.

Phase 2 (after P merged, against the real report, 2026-11-14):

- **The client part follows the report's layout**: P's text has a head of `Key: value` lines
  and then sections, each a heading line and `  key: value` lines, with a blank line between
  sections. The client part is one more such section (`Client`, then `  kind:`,
  `  user agent:`, `  device pixel ratio:`), after a blank line.
- **The logs folder's line with a `~` path.** In web mode the folder is on the server's
  computer, and there is no `sidecar.log`: the line says "On the server's computer. Holds the
  app log (reframe.log) and a log for each job."; in the desktop app it names `sidecar.log`
  too. When `logs_dir` starts with `~`, it adds "~ is the home folder."
- **Checked in a real server** (`scripts/dev-server.py`, the e2e servers, headless, all three
  engines): the logs folder shows `logs_dir`; Tab from it reaches *Copy diagnostics*, Enter
  copies, the status says "Diagnostics copied to the clipboard."; in Chromium (with
  `clipboard-read`/`clipboard-write` granted) the clipboard read back holds P's whole report
  (head, Tools, Encoders, Settings, Logs) and the `Client` section after it.
- **Real-server test** `components/settings/diagnostics.server.test.ts`: the report has text,
  no token, and names the same folder as `logs_dir`; the section's change
  (`/diagnostics/log_level` = `debug`, through the settings store) is saved by the server.

## Review and fix round

One fresh reviewer (R1, `xhigh`) checked the log, the report and the section (mutations in a
scratch copy). Findings:

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | blocker | At `debug` the app log lowered `uvicorn.error`, which uvicorn hands to the websockets library: every upgrade header (the session cookie) and every short frame (the `auth` message with the whole token) went into `reframe.log`. Reproduced by the lead (`whole token in reframe.log: True`). | Fixed (FP): no logger but Reframe's below INFO; a real-server regression test; the lead's re-run: `False` |
| 2 | minor | One record that could not be formatted turned the whole log off; NaN written as bare `NaN`. | Fixed (FP): a total formatter; only a file error turns the log off |
| 3 | minor | "One writer" not guaranteed (two servers on one data folder); on Windows a failed rename at rotation turned the log off. | Fixed (FP): installed only by the owner of the queue store, after `owner.start`; a failed rename reopens the file |
| 4 | minor | The "levels put back" tests depended on test order; overlapping installs leaked levels. | Fixed (FP) |
| 5 | minor | The report's Logs part half tested. | Fixed (FP) |
| 6 | nit | `~` missed a linked home and a home path before a full stop. | Fixed (FP) |
| 7 | nit | The Windows OS line not unit-tested. | Fixed (FP) |
| 8 | nit | Rotation counts characters, not bytes. | Not changed: the limit is approximate |
| 9 | nit | The close order untested. | Fixed (FP) |
| 10 | nit | `server.log` named by hand in two places. | Fixed (FP and the lead, 03ccb62) |

The review also checked the desktop clipboard (Task U above).

### Fix round — FP

Each finding of review R1 was reproduced first (its probes, or a test that failed on the old
code), then fixed. Decision items 1, 2, 3, 5 and 6 are corrected above, and the Task P
sentences on the lifespan, the filter, stderr, closing, a failed write, `~`, the secrets and
Windows.

1. **The token and the session cookie in `reframe.log` at `debug`** (blocker). The app log
   lowered `uvicorn.error` to DEBUG and wrote it. uvicorn hands that logger to the
   `websockets` library (its `websockets` and `websockets-sansio` implementations, checked in
   uvicorn 0.54.0), which at DEBUG logs every upgrade request header and each short frame
   whole. Reproduced with a real `reframe-server` at `debug` in password mode: the token of the
   auth message (a 69-byte frame) and the session cookie were both in `reframe.log`, neither on
   stderr. Fix (item 3): no
   logger but Reframe's is written below INFO, and no level but Reframe's is changed;
   `uvicorn.error` stays at INFO, so "Application startup complete." is still written. The
   INFO pin of uvicorn's stderr handler in `_log_config` is gone with its reason. Checked for
   the rest: the `websockets.*` loggers are used only by a client or a server that has no
   logger passed in; `fastapi` has one logger, starlette and h11 log nothing; the tool fetch
   uses `urllib`; `asyncio` and every other library stay at WARNING and up. Test: a real
   `reframe-server` subprocess at `debug` (log in with the password, then the auth message on
   `/api/events`, compact JSON as the frontend sends it): neither the token nor the cookie is
   in `reframe.log` or on stderr.
2. **One record turned the log off.** `JsonLinesFormatter.format` never raises: each `extra`
   field is converted on its own (`repr` for what is not JSON, a placeholder for a `repr` that
   raises, `repr` of the whole value for a circular one or bytes that are not UTF-8), NaN and
   infinity become text, a message whose `str` raises is written as its `repr`.
   `handleError` turns the log off only for an `OSError`; another error drops that record.
3. **One writer.** The log is installed after `owner.start` and only by the server that owns
   the queue store (item 1). A rename that fails at rotation (Windows: another process has the
   file open; the review's probe lost 89 of 100 records) prints one stderr line once, opens
   `reframe.log` again and goes on; the next record tries again. The retry moves the old files
   only up to the first free number: Python's own rotation moves them all again, which deletes
   one old file per failed try.
4. **The tests of the levels.** They set known levels first and check absolute values. The
   open app logs share the saved levels and `lastResort` (taken when the first opens, put back
   when the last closes), so two logs closed first-in first-out leak nothing and the second
   keeps stderr while it runs.
5. **The report's Logs part**: its test now has `server.log`, `sidecar.log.1` and
   `reframe.log.2`–`.3`.
6. **`~`** for the folder the home links to and for a home path that ends a sentence (Task P).
7. **The Windows OS line** (`_windows_os`) takes `getwindowsversion` and `win32_edition` as
   arguments and is tested on every platform.
9. **The close order** (the app log closed after `reframe.close()`) has a test: a record that
   the facade logs as it closes is in the file.
10. **`server.log`** is `reframe.applog.SERVER_LOG`. The core cannot import
    `reframe.remote.owner.server_log` (that package needs the `cli` extra, and
    `reframe-server` does not install `httpx`), so a test ties the two;
    `reframe/remote/owner.py` (not FP's file) can use the constant.

Not fixed, as the review said: 8 (rotation counts characters, not bytes).
