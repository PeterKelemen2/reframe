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

1. **Who writes `reframe.log`.** Only the server process (the one scheduler of 0042: web mode,
   the desktop's sidecar, or the owner a CLI client starts). One writer, so size rotation needs
   no lock across processes and works on Windows (the handler closes its file before the
   rename). CLI commands that run without a server (`probe`, `plan`, `name`, …) keep their
   stderr output and do not write `reframe.log`.
2. **The format.** One JSON object per line, UTF-8: `time` (ISO 8601, UTC, milliseconds),
   `level`, `logger`, `message`, and when there is one `exception` (the formatted traceback)
   and the record's context (`job_id`, `task_id`, … given through `extra`). Rotation by size:
   5 MiB, three old files (`reframe.log.1` … `.3`).
3. **What goes in.** Reframe's own loggers (`reframe`, `reframe_server`) and `uvicorn.error` at
   the level of the setting; other libraries at WARNING and above whatever the setting is.
   `uvicorn.access` is not written: it would log every poll and the paths in the query strings.
   Stderr stays as it is (plain text), so `sidecar.log` and `server.log` keep working.
4. **The level is a setting.** `AppSettings.diagnostics.log_level`: `error`, `warning`,
   `info` (default) or `debug`, shown in a new **Diagnostics** section of Settings. A change
   applies at once, without a restart. A new sub-document with a default: an older version
   keeps it as an unknown field (`DocumentModel`), so `schema_version` stays 1.
5. **A log that cannot be written** (the folder read-only, the disk full) does not stop the
   server: one line on stderr says why, and the server runs without the file.
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
   Paths under the user's home folder start with `~` (the user name is often in them).
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

(Filled by P.)

## Task U: the Diagnostics section (frontend)

(Filled by U.)

## Review and fix round

(Filled by the lead.)
