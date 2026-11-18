# M10 breakdown: the FFmpeg download and build choice (C-21, S-8, F-20, D-10)

Decisions [0093](decisions/0093-ffmpeg-download-and-build-choice.md) and
[0094](decisions/0094-docker-image-without-ffmpeg.md) (the Docker image contains no FFmpeg
either; added while the agents ran). Branch `m10-hardening`.
Agents work in worktrees: a fresh worktree starts at `main`, so first run
`git merge --ff-only m10-hardening`.

## Contracts (binding; only keyword-only parameters with defaults may be added)

Built by the lead before the agents start (commit "contracts for the FFmpeg build choice"):

- `EncoderStatus.build_mismatch: bool = False` (`reframe/models/capabilities.py`). Capability
  cache `CACHE_FORMAT = 2`.
- `TaskInfo.error_code: str | None = None` (`reframe/models/tasks.py`). A fetch or file
  install that cannot reach the download server ends `failed` with
  `error_code = "tools.fetch_offline"`.
- Manifest (`tools/ffmpeg.toml` and its packaged copy): `offered`, `label`, `summary` per build;
  `default` and `compat` are offered (`compat` = the `override-test` pin, release/8.1).
  `reframe.tools.fetch.offered_builds(data_dir, *, manifest=None, platform=None) -> ToolBuilds`;
  `ToolsService.builds(*, manifest=None) -> ToolBuilds` (models `ToolBuildOffer`,
  `InstalledToolBuild`, `ToolBuilds` in `reframe/models/tools.py`). Built.
- `ToolsService.install_file(archive: Path, *, build: str | None = None, manifest: Path | None
  = None) -> TaskInfo`: task kind `tools_fetch`, result `ToolFetchResult`. Stub (raises
  `NotImplementedError`) until C-21.
- The packaged libva: `<root>/libva/` for each `root` of `paths.bundled_tool_roots()` other than
  `<data dir>/tools` (in the desktop packages: `resources/tools/libva/`). It holds
  `libva.so.2` and `libva-drm.so.2` (with their version symlinks). A download or file install on
  Linux copies them into the installed build's `lib/`.
- CLI: `reframe tools fetch --file ARCHIVE [--build NAME]`. The hint line of `reframe encoders`
  and `reframe tools status`: `hint: <ids> need newer system software than this FFmpeg build
  expects: update the driver, or use another build (reframe tools fetch --build <other>, or
  REFRAME_FFMPEG / tools.ffmpeg).`
- API (S-8): `GET /api/system/tools/builds` → `ToolBuilds`; `POST /api/system/tools/install-file`
  `{path: str, build?: str}` → 202 `TaskAccepted`. Desktop mode: any path; web mode: the path
  must be inside a media root (the existing jail).
- UI (F-20): *Use another FFmpeg…* opens `/settings#tools` (the route the first-run screen's
  *Choose path* already uses).

## Tasks

| Agent | Steps | Effort | Owns |
|-------|-------|--------|------|
| K (core) | C-21 | xhigh (installs files) | `reframe/tools/fetch.py`, `reframe/tools/discovery.py`, `reframe/capabilities/{reasons,detect,service}.py`, `ToolsService` in `reframe/service.py`, the task error code in `reframe/tasks.py` / `reframe/mediatask.py`, the `tools` and `encoders` commands in `reframe/cli.py`, `scripts/fetch-tools.py`, `tools/ffmpeg.toml` (+ packaged copy), `testdata/README.md`, tests under `packages/reframe/tests/` |
| W (server + UI) | S-8 (with `REFRAME_FFMPEG_BUILD`, 0094 item 3), F-20 | high | `packages/reframe-server/**` except `tests/test_deploy.py`, `frontend/src/**` (`schema.d.ts` regenerated with `scripts/gen-api.sh`), `frontend/e2e/**` |
| P (packaging) | D-10, S-6's 0094 item (no FFmpeg in the image) | high | `docker/**`, `packages/reframe-server/tests/test_deploy.py`, `scripts/bundle-tools.py`, `tools/bundled-tools.toml`, `desktop/packaging/**`, `desktop/src-tauri/tauri.conf.json`, `desktop/sidecar/**`, `desktop/tests/smoke/**`, `scripts/third-party-notices.py`, `.github/workflows/**`, `docs/deployment.md` |

Two agents never own the same file. Each agent updates its step's rows in `docs/status.md` and
nothing else in `docs/`; the lead reconciles. Merge order: K, W, P (`--no-ff`). Then: the full
checks, two fresh xhigh reviews (R1: core and packaging; R2: server and UI), the lead
reproduces every blocker and major, fixes with a test that failed before, and the demo:

1. Linux, empty data folder: the web app's first-run screen lists `default` and `compat`;
   *Download* installs `default`; Settings → Tools shows it.
2. The same with the network blocked: the offline message with *Install from file* and
   *Choose path*; *Install from file* with a cached archive works.
3. The Docker image: no FFmpeg inside; a first start with an empty `/data` downloads into
   `/data/tools/ffmpeg/` (UI, and `REFRAME_FFMPEG_BUILD`); VAAPI works with it.
4. An Ubuntu 22.04 container with the .deb: no FFmpeg in the package; a file install copies the
   packaged libva; VAAPI detection works.
5. The NVIDIA Windows VM: with `default`, `reframe encoders` prints the hint and the UI shows
   *Use another FFmpeg…*; after installing `compat`, NVENC is available.
