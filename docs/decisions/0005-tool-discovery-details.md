# 0005 — Tool discovery details: Windows job, bundled layout, folder overrides

- Status: accepted
- Date: 2026-10-11
- Steps: C-1, D-7

## Context

`C-1` says: "On Windows, assign children to a Job Object with `KILL_ON_JOB_CLOSE`". A child
that is assigned after `CreateProcess` returns can start a grandchild before the assignment,
and that grandchild is then outside the job (it survives a Reframe crash). Python's
`subprocess` cannot create a process suspended and resume it, so "assign, then resume" is not
available.

02 §Bundled FFmpeg names the install folders for FFmpeg only. 07 §Tool bundling also bundles
`mkvpropedit` and MediaInfo on Windows, but does not say where. CI must test "the same pinned
build that ships" (`Q-1.2`) through the bundled-build lookup, which needs a folder that CI can
write to.

## Decision

1. **Windows job.** Before Reframe starts its first tool, it creates a job with
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK` and puts **its own
   process** into it. Every child is then created inside the job, with no race. The job handle
   closes when Reframe dies, which kills every child. If Reframe cannot join a job (for
   example an old Windows without nested jobs), it falls back to assigning each child after
   start and logs that this is racy. Children still get `CREATE_NO_WINDOW`. Code:
   `reframe/platform/childproc.py`.
2. **Bundled layout.** The bundled tool roots are searched in this order: the frozen app
   (`<exe dir>/tools`, then `<exe dir>/../tools` for the Tauri `resources/sidecar/` layout),
   `/usr/lib/reframe/tools` and `/opt/reframe/tools` (Linux), then `<data dir>/tools`. Inside
   a root, FFmpeg is in `ffmpeg/`, MKVToolNix in `mkvtoolnix/`, MediaInfo in `mediainfo/`,
   each with the binaries in `bin/` or directly in the folder. "A bundled build exists" is
   decided per tool family, so a damaged bundled FFmpeg never falls back to `PATH`, and a
   .deb install still finds the distro's `mkvpropedit` on `PATH`.
3. **Folder overrides.** `REFRAME_CONFIG_DIR`, `REFRAME_DATA_DIR` and `REFRAME_CACHE_DIR`
   override the platformdirs folders. These are the names that `S-0`'s `ServerConfig` reads
   (env prefix `REFRAME_`), so the core CLI and the server agree.
4. **CI** installs the pinned build with `scripts/fetch-tools.py --install-dir
   "$REFRAME_DATA_DIR/tools/ffmpeg"`, so the main jobs find it as the *bundled* build (not on
   `PATH`). The override job keeps using `REFRAME_FFMPEG` / `REFRAME_FFPROBE`.

## Consequences

- No orphaned FFmpeg after a Reframe crash on Windows, even when FFmpeg starts helpers.
- `D-7` must put MKVToolNix and MediaInfo into `tools/mkvtoolnix/` and `tools/mediainfo/`.
- Not verified on Windows yet (only with mocked `kernel32` calls): joining a job from inside the
  GitHub runner's own job, and the fallback. Check on the first Windows CI run and in `D-0`.

## Plan changes

- `docs/plan/05-core.md` C-1: the child-safety bullet.
- `docs/plan/02-architecture.md` §Bundled FFmpeg: the install locations.
