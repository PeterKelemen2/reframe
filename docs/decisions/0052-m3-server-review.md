# 0052 — M3 server review

- Status: accepted
- Date: 2026-10-22
- Steps: S-0, S-1, S-2, S-3, S-5, Q-2.3, C-9

## Context

A fresh reviewer (`xhigh`) read `git diff main...m3-api-spike` at 191c4f7: every server
module and test, the harness, the scripts and the CI job. It was given the code, the plan and
the test rules, not the lead's conclusions. The reviewer was stopped by an API error before
it sent its whole report; the lead reran each of its experiment scripts against 191c4f7 and
reproduced every finding below (output in the lead's notes), then got the test-quality part
as a second answer.

## Findings and what happens to them

| Id | Severity | Step (record) | Finding | Fix by |
|----|----------|---------------|---------|--------|
| R-1 | blocker | S-1 (0046) | FFmpeg reads an option's value from a file when the option name starts with `/` (`eq=/contrast=FILE`, also quoted, escaped, after another option, with `@instance`, and in a `custom` preset text). Every allowed filter has options, so web-mode free filter text read any file the server can read; the contents came back in `preview/render`'s notes and the job log | 1a |
| R-2 | major | S-2 (0049) | `POST /api/sources` jails the paths the client names, not the files found by expanding a folder: a link below a media root that points outside became a source, with frames, crop detection and scans of the outside file | 1d |
| R-3 | major | S-2 (0049), C-9 | `PUT /api/settings` checked the patch against settings read outside the store's lock, and skipped the check when the patch did not apply to that copy: two concurrent requests set `tools.ffmpeg` in web mode. The lead added `SettingsService.update(…, check=)` (runs under the lock, 2b76fab) | lead (core), 1d (route) |
| R-4 | major | S-2 (0049) | Web mode accepts any `encoders.vaapi_device` text, which reaches FFmpeg's `-init_hw_device` (device options such as `driver=` included) | 1d |
| R-5 | major | S-3 (0047) | The server process does not stop (SIGINT, `POST /api/system/shutdown`) while an event client does not read: uvicorn waits for the connection, the lifespan never closes the facade | 1b |
| R-6 | major | S-1 (0046) | Request bodies are read and parsed before the credentials are checked: an anonymous 54 MB body raised the peak memory by about 1 GB before the 401; broken JSON got 422, not 401 | 1a |
| R-7 | major | S-2 (0050) | The batch override jail resolves the template, the batch service resolves it again later: a preset changed in between lets a `test` op pass only in the service, and an external subtitle outside the roots reaches validation | 1e |
| R-8 | minor | S-1 (0046) | A 500 answer carries no security headers | 1a |
| R-9 | minor | S-2 (0049) | A `Range` header with a number of more than 4300 digits is a 500 | 1d |
| R-10 | minor | S-2 (0050) | Web mode: an in-place edit's draft offers "save it in the output root" fixes that cannot work for an in-place edit; `validate` then answers 403 instead of an issue | 1e |
| R-11 | minor | S-2 (0048) | Task results (`GET /api/tasks/{id}`) and queue answers show cache and data-folder paths | 1c |
| R-12 | minor | S-2 (0050) | `presets.write_failed` names the server's config folder (known since 1e) | 1e |

Test quality (the rules of [m3-breakdown.md](../m3-breakdown.md)):

- **Deleted**: the operationId pins of each route file (the rule test in `test_openapi.py`
  and the Q-2.3 diff of `schema.d.ts` catch a renamed id); the route tests that replace the
  jail with a fake when the jail sweep sends the same input to the same route through the
  real jail (their extra assertions — no task started, no FFmpeg call, no preset saved —
  move into the sweep); the per-router foreign-`Host` rows (one middleware; S-1's tests cover
  HTTP and WebSocket); the facade-level settings tests that have route versions; table rows
  and tests that follow a path another test covers (listed per task in the fix briefs).
- **Rewritten**: the sweep sends one hostile path (a link out of a root) per input instead of
  three; the export test runs one subprocess; the token-in-`repr` test becomes "the token is
  not in the server's output"; the frames-at-timestamps test uses the fake tools.
- **Windows**: five tests would fail there (SIGINT to a child process; a `Path` field compared
  with a POSIX string; `rsplit("/")` on paths, three times), and two pass for the wrong reason
  or need a skip (a NUL path that is not absolute on Windows; links in the sweep without the
  skip of `test_security_jail.py`). Fixed by the tasks that own them.
- **Gaps** that become tests with the fixes: every finding above, the `Origin` check for
  PUT / PATCH / DELETE, and a wrong current password counting toward the rate limit (both
  mutations survived the review's check).

## Consequences

- The fixes run as one round, one fresh agent per task (`high`), each with its own findings.
  Each adds a dated "Follow-up (review)" section to its task's record.
- The rule of the breakdown that told each route task to prove "the route passes its path to
  the jail" with a fake jail is superseded by the sweep, which proves it with the real jail.

## Plan changes

None by this record; the fixes record their own.
