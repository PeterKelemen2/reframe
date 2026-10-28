# 0060 — Review of server-complete: findings, the lead's checks, and outcomes

- Status: accepted
- Date: 2026-10-28
- Steps: S-7, S-4, S-6

## Context

[0055](0055-server-complete-order.md) item 3 calls for two reviews of
`git diff main...server-complete` after wave 2, by fresh agents at effort `xhigh`, given the
code, the plan and the authors' decision records ([0056](0056-s7-owner-endpoint-file-and-idle-exit.md),
[0057](0057-s7-attachments-client-id-and-detach.md), [0058](0058-s4-static-frontend.md),
[0059](0059-s6-docker-image-and-bare-metal.md)), not the lead's conclusions. They reviewed
the branch at 401b89b:

- **R1**: S-7's server side and the contract (`owns_store`, `busy`, `ServerEndpoint`,
  `owner.py`, `idle.py`, the attachments in `events.py` and `routers/queue.py`, `serve()`).
  No blocker or major; 6 minors and nits. 34 mutations: 30 caught, 2 equivalent, 2 gaps.
- **R2**: S-4 (`static.py`) and S-6 (`docker/`, `docs/deployment.md`). 1 blocker (Windows),
  1 major, 5 minors, nits. Mutations: `static.py` 12 of 14 caught (2 without a visible
  effect); the Dockerfile against `test_deploy.py` 3 of 8.

Before any fix the lead checked the blocker and the major again.

- **R2 F1 (blocker), the UNC path.** With `PureWindowsPath`, `C:\ProgramData\reframe\frontend`
  joined with the request path `\\attacker.example\share\x.js` is `\\attacker.example\share\x.js`
  (the root is dropped; `C:/Windows/win.ini` likewise), and Python 3.14.8's `ntpath.realpath`
  on Windows calls `nt._getfinalpathname` (ntpath.py lines 674 and 709), which opens the path.
  So `static.py` opened it before its containment check. Not run on Windows (0053).
- **R2 F2 (major), the reverse proxy in Docker.** The image from this branch, run with
  `-p 127.0.0.1::8765` and a password: five wrong logins with `X-Forwarded-For: 203.0.113.5`
  were 401, then the right password from another address was `429 auth.rate_limited`; the
  server log named every client `172.17.0.1`. With `FORWARDED_ALLOW_IPS=172.16.0.0/12` (the
  docs' advice), twelve wrong logins with changing `X-Forwarded-For` were all 401 (never 429),
  and a plain-HTTP login that claimed https got a `Secure` session cookie. The containers and
  the image were removed; the Docker state equals the owner's snapshot.

## Decision

| # | Severity | Finding | Outcome |
|---|----------|---------|---------|
| R2 F1 | blocker | `static.py` opens a UNC or drive path (Windows) before it checks containment | Fixed (fix X, 1a737f7): before any file-system call, a request path with `\\`, `:` or a name that `ntpath.isreserved` refuses (control characters, `"*<>?|`, a trailing dot or space, DOS device names) is not found, on every OS. Test: the raw request to a live server with `Path.resolve` recorded (unc, drive and device rows failed on the old code). Not run on Windows |
| R2 F2 | major | Reverse-proxy notes and compose ports wrong for Docker: login limit shared by all, or bypassed | Fixed (fix Y, a83aacc): `docs/deployment.md` names both failures and gives two set-ups on a pinned subnet: a host proxy with `127.0.0.1:8765:8765` and `FORWARDED_ALLOW_IPS` set to the gateway only; a proxy container with no published Reframe port and the proxy's fixed address trusted; never a range. The compose example says so next to `ports`. Proved with real containers: through the proxy one client's five wrong passwords do not lock out another; a direct client cannot spoof `X-Forwarded-For` or get a `Secure` cookie over plain HTTP; the old docs reproduced the failures on the same image. Docker 29.9.2 makes the first address of an `ip_range` the gateway unless one is named, so the docs name it |
| R2 F3 | minor | A `static_dir` without `index.html`, or one that holds the data folder, is served (can leak `server.json`) | Fixed (fix X, 7036c0d, 517682a): a `ServerConfig` validator (web mode) refuses, with exit 2 and the reason, a `static_dir` without `index.html` and one that is or holds the config, data or cache folder, the endpoint file, a media root or an output root (both sides resolved; the defaults from `reframe.paths`). Tests failed on the old code; the reviewer's layout now exits 2. The lead's three mutations (containment inverted, equality only, a configured `config_dir` ignored) were caught |
| R2 F4 | minor | `test_deploy.py` lets the data, config and cache folders leave the mounts | Fixed (fix Y): two tests, the config, data and cache folders inside the folders the entrypoint hands to `PUID` and the compose example mounts, and the `HEALTHCHECK` path answered without a login |
| R2 F5 | minor | Missing host folders are made as root; `/output` not writable | Fixed (fix Y): the docs and the compose comment make the host folders first as `PUID:PGID`; checked (old: `output.not_writable`; new: the encode done) |
| R2 F6 | minor | `cp -r` keeps the old UI | Fixed (fix Y): `rm -rf` before the copy; checked with two stand-in builds |
| R2 F7 | minor | The entrypoint compares `PUID` to `0` as a string; `PUID=0` in rootful Docker is root | Fixed (fix Y): `PUID` and `PGID` are checked as numbers and their leading zeros removed; `PUID=0` warns when the uid map shows that the container's root is the host's root (a warning, not a refusal: the map is a heuristic). Four tests with stand-in tools; two failed on the old script. The lead's mutations: the `PUID=0` path falling through to `setpriv` was caught; **`setpriv` without `--no-new-privs` survived** (sent back, fixed in 2a67146 with an assertion in an existing test); adding the root group to the device groups survived and is accepted (it needs a fake `/dev/dri`; D and R2 checked it by hand) |
| R2 F8 | nits | Python version wording, apt pins, the health check's port, `--user` and writable mounts | Fixed in the docs (fix Y): CPython 3.14.8; what is pinned; `REFRAME_PORT`, not `--port` (checked: `unhealthy` / `healthy`); `--user` needs writable `/config` and `/data` |
| R1 F1 | minor | `--owner-only` exits 75 also when `queue.lock` cannot be used | Fixed (A, 1445b74): the core's new `QueueService.store_busy` (a held lock only); `--owner-only` exits 75 for a held lock and 1, with the core's `queue.unreadable` reason, for one that cannot be used; the warning without `owner_only` names the one cause. Tests: the core, the real process (`queue.lock` made a folder: `IsADirectoryError`), the log |
| R1 F2 | minor | 0056 says close code 1001 at idle exit; it is 1012 | Corrected in 0056's follow-up (measured: 1012 for a client at idle exit and at SIGINT); C-17 looks for an owner again on 1012 |
| R1 F3 | minor | The exit window: `server.json` names a port that refuses while the lock is held | Recorded in 0056's follow-up for C-17 (measured at an idle exit: port refused at 1.081 s, file gone and lock free at 1.181 s): retry discovery for a few seconds while the lock is held and no endpoint answers |
| R1 F4 | minor | A `ServerEndpoint` validation error echoes the token | Fixed (A, 1445b74): `hide_input_in_errors=True` on `ServerEndpoint`; test (a non-text token and a missing `pid` both showed it before); the schema snapshot unchanged |
| R1 F5 | minor | With `REFRAME_TOKEN` set, `server.json` holds that long-lived token | Kept (the lead's choice): the file is 0600 in the user's data folder, and the operator who set the token already holds it. Recorded in 0056 |
| R1 F6 | minor | No test that an `--idle-exit` server stopped by request ends; `busy`'s `_only` filter not tested alone | Fixed (A, 1445b74): a test that a server with `idle_exit` stopped by `POST /api/system/shutdown` ends (fails with the cancel removed). Doing it, A found that `serve()` lost a cancel of itself while it waited for the cancelled watch (`suppress(CancelledError)` around `await idle_watch`); the lead's fix 4cf2b39 waits with `asyncio.wait`, with a test that failed before (`result=0` instead of cancelled); the `_only` gap is accepted (a narrow state: a restored, targeted job removed while its keys are read) |

Accepted without a change:

- R2 F8: the cache rule keyed on the request path and the loose `assets` prefix (no visible
  effect), and the duplicate `..` / `%2e%2e` row (the criteria name both).
- R1 nits: `busy`'s `not self._closed` is redundant (harmless); `EventHub.client_open` is used
  only by tests now (0057 says why); a client that closes with 1012 itself, or dies as the hub
  closes, is treated as a server stop (0057 item 4); the losing `--owner-only` server's
  126-line traceback (0056).
- Outside the scope, recorded for later: behind one shared address (a proxy that is not
  trusted) S-1's per-client login limit lets one client lock out every other; 0042 item 5's
  "the partial-file setting" for a cancelled attached job is read as "as a cancel does" (06,
  0057 item 6).

## Consequences

- The fixes of the lead's own files: `serve()` returned no exit code when uvicorn's start-up
  failed (found by A in wave 1, 5f417ee) and lost a cancel of itself while it waited for the
  idle watch (found by A while fixing R1 F6, 4cf2b39); each has a test that failed before.
- C-17 must follow 0056's follow-up: exit 75 only for another owner (1 for an unusable lock),
  close code 1012 when the server stops, and a few seconds of retries in the exit window.
- Open, for the owner (defaults kept): a Reframe setting for uvicorn's `FORWARDED_ALLOW_IPS`
  (default: the environment variable, documented); a `--static-dir` option and the web build
  in the wheel (default: `REFRAME_STATIC_DIR` and a build by hand, 0058); S-1's per-client
  login limit when every client shares one address (default: as built; the documented proxy
  set-ups avoid it); the bare-metal `uv tool install` picks the newest Python on the machine
  (3.13 in R2's run) while the image pins 3.14.8.
- Not verified: Windows (the static path rule was read from the stdlib and checked with
  `PureWindowsPath`), Caddy, ufw, a real LAN client over IPv6, rootless Docker and Podman.

## Plan changes

None beyond the step records' follow-ups and the S-4, S-6 and S-7 sections of 06 that the
fixes edit.
