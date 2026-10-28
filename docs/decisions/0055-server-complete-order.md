# 0055 — Server-complete: S-7's server side, S-4 and S-6 before their milestones

- Status: accepted
- Date: 2026-10-28
- Steps: S-7, S-4, S-6

## Context

M3 is done on Linux and merged into `main` (2026-10-28). The roadmap
([08](../plan/08-roadmap.md)) puts the three server steps that are still open in three later
milestones:

- **S-7** (local owner mode) is in M3b, with C-17, the CLI's client mode
  ([0042](0042-one-scheduler-process-and-cli-clients.md) item 12);
- **S-4** (static frontend and SPA fallback) is in M4, with the web frontend;
- **S-6** (deployment) is in M10.

None of the three needs the frontend to be built, and the S-6 check ("`docker compose up` on
a Linux host with a GPU … encodes a fixture file") can be run on the owner's AMD desktop now.
The owner asked for the server to be completed first, on its own branch, as the core was
before the UI milestones ([0029](0029-core-before-the-ui-milestones.md)).

## Decision

1. **Scope.** On the branch `server-complete` (from `main` at 6e8ba14):
   - **S-7, server side**: `server.json` with the local token, the queue opened at start-up,
     `--owner-only` (exit 75), idle exit (0042 items 2 and 8), attachments with `client_id`
     and `detach` (item 5), and a test that `start` with `job_ids` leaves other waiting jobs
     alone;
   - **S-4**: static files and the SPA fallback in web mode, none in desktop mode;
   - **S-6**: the Docker image, the compose example, the bare-metal install with a systemd
     user unit, and the reverse-proxy notes.
2. **Out of scope: C-17** (`reframe.remote.RemoteQueue`, `QueueLike`, the CLI's client mode,
   `reframe queue`). So of 0042's Verification list, checks 1 to 8 stay open: they need the
   CLI (8 is the contract suite against `QueueService` and `RemoteQueue`). Check 9 ("`attach`
   with the id of a closed connection is refused") and the S-7 "Done when" are covered here.
   Also out of scope: every `F-x` and `D-1` to `D-9`.
3. **Order** (the breakdown: [server-complete-breakdown.md](../server-complete-breakdown.md)):
   - wave 0, the lead: this record, the breakdown and the contract commit;
   - wave 1: A (S-7 owner: `server.json`, `--owner-only`, idle exit), B (S-7 attachments),
     C (S-4), one agent and one worktree each;
   - wave 2: D (S-6): its image serves the frontend through S-4;
   - wave 3: two reviews by fresh agents, then the fixes;
   - wave 4, the lead: the full suite, the real server demo, the frozen sidecar rebuilt with
     its test and a cold start, and `docker compose up` with the GPU in a slot the owner gives.
4. **The contract** (the contract commit after this record):
   - core, read only: `QueueService.owns_store` (this process holds `queue.lock`),
     `QueueService.busy` (a job runs or is paused, or a `start` still targets a waiting job),
     and the model `reframe.models.ServerEndpoint` of `server.json`, in the core because
     C-17's client reads the file without the server package;
   - server: the modules `owner.py`, `idle.py` and `static.py` as stubs, called from the
     lifespan (`owner.start`, `owner.withdraw`), from `serve()` (`owner.publish` once the
     server listens, `idle.watch` when `idle_exit` is set) and from `create_app`
     (`static.install`, after every router). `app.state.exit_code` is what `serve()`
     returns when the app does not start (1, or 75 from `owner.start`).
   - `PowerService.pending` and `EventHub.connections` already exist.
5. **Records**: 0056 (A), 0057 (B), 0058 (C), 0059 (D), 0060 (the lead's review record).
6. **The branch is not merged into `main`** as part of this work. The milestones stay open:
   M3b until C-17 and its demo, M4 until its frontend, M10 until its other steps. The rows of
   S-4, S-6 and S-7 in `docs/status.md` say what is built on `server-complete`.
7. **Docker on this machine has no buildx**, so BuildKit is not available. The image must
   build with the classic builder (no cache mounts, no `COPY --chmod`, no heredocs in the
   Dockerfile). Installing buildx needs the owner.

## Consequences

- C-17 builds on S-7's server side as it is merged here: `server.json` (read through
  `ServerEndpoint`), the `client_id` in `hello`, `attach` and `detach`, exit 75 of
  `--owner-only`, and `--idle-exit`.
- Every server now opens the queue at start-up, so a test app takes `queue.lock` in its own
  data folder.
- The facade's two new members are server state; the plan's "Not exposed" table
  ([06](../plan/06-web-app.md#not-exposed)) lists them (the contract commit).

## Plan changes

- [08-roadmap.md](../plan/08-roadmap.md): M3b, M4 and M10 say that S-7's server side, S-4 and
  S-6 are built early on `server-complete` (this record).
- `docs/status.md`: the rows of M3b, S-4, S-6 and S-7.
