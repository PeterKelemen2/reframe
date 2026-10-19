# 0043 — Plan review before M3

- Status: accepted
- Date: 2026-10-19
- Steps: Q-1.4 (new), S-0, S-1, S-2, S-6, D-7, F-1, F-16, F-17 (and the quit dialog of 07);
  milestones M3, M4, M5, M6, M7, M8, M10

## Context

Before M3, the plan for the work that is left (02, 06, 07, 08, 09, with 01) was read against
what is built (`docs/status.md`, the facade list of
[0030](0030-core-complete-contract.md), the code) and against the first draft of
[0042](0042-one-scheduler-process-and-cli-clients.md). The design holds up: FFmpeg as
subprocesses, one schema in `reframe.models`, editing state in the client, one scheduler
process, Tauri with the shared Vue UI and frame compare as the fall-back for webview codecs,
the milestone order. The review found 16 problems:

| # | Finding | Outcome |
|---|---------|---------|
| 1 | 08 says a milestone is done only when "CI is green on Linux and Windows", but nothing is pushed (`CLAUDE.md`: never push), so CI has never run and nothing has run on Windows. D-0 (M3) and most of M5 need Windows | Decision 1 |
| 2 | The S-2 route table is older than the built core: no routes for the loudness scan, `draft_remux`, `hdr_metadata`, `dry_run`, `search_options`, `tools.fetch` / `rescan`, task status and cancel, the power countdown, `resolve_batch`, `save_preset`, the preview cache. S-2's "Done when" ("every route") would pass with half the core out of reach | Decision 2 |
| 3 | S-1 has no `Host` check: with `auth: none` on 127.0.0.1, a web page can reach the API through DNS rebinding. The password hash is planned "in settings", which `GET/PUT /api/settings` would return and overwrite | Decision 3 |
| 4–10 | The draft of 0042: an app opened after a CLI-started owner got a private queue; C-17's test 6 had no rule behind it (the queue did not refuse a claimed output); a job could be attached to a client that was already gone; "the server package is installed" was ambiguous with `uv tool` environments, the desktop packages did not ship the CLI, and `reframe` named both the CLI and the desktop app; each CLI added its jobs at the front; S-7 and C-17 made M3 longer and blocked M4; open question 3 missed that `launch_detached` already breaks away from the Job Object; web mode published no endpoint; a client ran its own encoder detection next to the owner's encodes | Fixed in 0042 before it was committed |
| 11 | S-0 puts the token in the ready line; 07 says the shell makes the token and passes it in an environment variable | Decision 4 |
| 12 | The quit dialog offers **Keep running in tray**, but the tray is off by default (D-6) | Decision 5 |
| 13 | The event table of 02 lacks `tools.changed`, `app.warning`, `power.countdown`, `notification` and `resync` | Decision 6 |
| 14 | "Done when" lines need hardware the owner does not have: S-6 an Intel iGPU, D-7 Intel, AMD and NVIDIA hosts on Windows and two distros, M10 NVENC in Docker (the owner's machine has an AMD GPU: no QSV, no NVENC) | Decision 7 |
| 15 | i18n and accessibility (F-16) and every end-to-end flow (F-17) wait for M10. Moving every string of a finished UI into vue-i18n is costly, and the flows would first run long after their screens are built | Decision 8 |
| 16 | M10 ships signed installers, MSI, rpm, arm64 Docker, an updater and a PyPI wheel; 01's target user is one person | Decision 9 (a question for the owner) |

## Decision

1. **Windows verification.** A milestone is done when its demo works and every CI command
   passes on Linux, and `docs/status.md` lists what has not run on Windows. New step **Q-1.4
   Windows verification run**: the Python and frontend commands of `.github/workflows/ci.yml`
   run on Windows 10 or 11 without a push, by default on a Windows machine or VM that the
   owner provides; a push to a private remote only if the owner allows it (01 open
   question 5). Q-1.4 is part of M3, because D-0 needs Windows, and runs again before M5 and
   M10 are done; M5 and M10 cannot be done without it.

2. **S-2 reaches the built core.** New routes:
   - Tasks: `GET /api/tasks` · `GET /api/tasks/{id}` (state and result) ·
     `POST /api/tasks/{id}/cancel`.
   - System: `POST /api/system/tools/rescan` · `POST /api/system/tools/fetch` `{build?}` → 202.
     `GET /api/system` also returns the start-up problems of the settings and preset stores.
   - Sources: `POST /api/sources/{id}/streams/{index}/loudness` `{start?, duration?}` → 202.
   - Preview: `GET /api/preview/cache` (size) · `DELETE /api/preview/cache`.
   - Definitions: `GET /api/definitions/encoders/{id}/options?q=` (`search_options`).
   - Jobs: `POST /api/jobs/explain` `{source_id, template?, container?}` ·
     `POST /api/jobs/draft-remux` `{source_id, preset_id?, edit_in_place}` ·
     `POST /api/jobs/dry-run` `{job}` · `POST /api/jobs/hdr-metadata` `{job}` (JSON patch).
   - Batch: `POST /api/batch/resolve-run` `{template, source_ids, level, overrides}`
     (`resolve_batch`: the name checks of the whole run) · `POST /api/batch/save-preset`
     `{template, name, category?, description?}`.
   - Power: `GET /api/power` (the pending countdown) · `POST /api/power/cancel`.

   S-2's "Done when" adds: every public method of the facade (0030's list, `Reframe.batch`,
   `Reframe.power`, `Reframe.tasks`) is reached by a route or listed in S-2 as not exposed,
   with the reason.

3. **S-1 security.**
   - **Host check** in every mode: a request or WebSocket upgrade whose `Host` is not a
     loopback name (`127.0.0.1`, `localhost`, `[::1]`, any port) or in the new
     `allowed_hosts` setting is refused. `allowed_hosts` defaults to the loopback names, plus
     the bound address and the machine's host name when the server binds another address.
     A WebSocket `Origin` must be the server's own or a Tauri origin.
   - **No secret in settings.** The password hash lives in `<config dir>/auth.json` (mode
     `0600`), written by `reframe-server --set-password` and `PUT /api/auth/password` (which
     needs the current password). `GET/PUT /api/settings` never read or write it, so a
     settings patch cannot change the login. No settings field is added, so no migration.
   - S-1's "Done when" adds: a foreign `Host` is refused; `GET /api/settings` holds no
     secret; a settings patch cannot change the password.

4. **One token per server run**: `REFRAME_TOKEN` when it is set (the desktop shell sets it,
   as 07 says), else a random one. `server.json` holds it (0042 item 2). The ready line
   carries only the port: `{"event":"ready","port":53817}`.

5. **Tray.** The quit dialog offers **Keep running in tray** only when the tray is on.

6. **Events.** The event table of 02 lists every event of `reframe.models.events`.

7. **Hardware.** A "Done when" line that needs hardware is met on the hardware that is
   available. Hardware that was not tested is listed as not verified (in `docs/status.md`,
   and for D-7 in `0002-bundled-ffmpeg.md`), as C-4 already does. S-6: a Linux host with a
   GPU (the owner's: AMD, VAAPI); M10: the compose example with VAAPI, and with NVENC when an
   NVIDIA host is available.

8. **i18n from the first view; end-to-end flows per milestone.**
   - F-1: every string the user sees goes through vue-i18n from the first view, and a CI check
     fails on literal text in a `<template>` (oxlint does not read templates; F-1 picks a
     small script or a Vitest check). F-16 keeps the accessibility work and the final audit.
   - F-17: the Playwright set-up and flow 3 (unavailable encoder → fallback) come in M4,
     flow 1 (languages and flags) in M6, flow 2 (season) in M7, flow 4 (crop) in M8. M10 runs
     all four in Chromium and WebKit.

9. **Release scope** stays as it is (09 §Q-5, D-8) until the owner answers 01 open
   question 6: which artefacts does v1 need, if v1 is for personal use only?

## Consequences

- M3 gets Q-1.4. D-0's Windows part waits for a Windows run.
- S-2 grows by 17 routes (S-1 adds `PUT /api/auth/password`), and its "Done when" can be
  checked against the facade.
- `ServerConfig` gets `allowed_hosts`. A web server reached through a LAN name or a reverse
  proxy needs that name in it.
- Three "Done when" lines are met on the owner's hardware, with the rest listed as not
  verified, as for the core.
- M4 gets two jobs it did not have: the template check of F-1 and the Playwright set-up.

## Plan changes

- [01 §Open questions](../plan/01-scope.md#open-questions-owner-to-decide): questions 5 and 6.
- [02 §Events](../plan/02-architecture.md#events).
- [06](../plan/06-web-app.md): S-0 (ready line, token, `allowed_hosts`), S-1, S-2, S-6, F-1,
  F-16, F-17.
- [07](../plan/07-desktop-app.md): the quit dialog, sidecar lifecycle step 1, D-7.
- [08](../plan/08-roadmap.md): the rule for "done", M3, M4, M5, M6, M7, M8, M10.
- [09](../plan/09-quality-and-release.md): Q-1.4 and the end-to-end row of the test table.
- [../status.md](../status.md): Q-1.4.
