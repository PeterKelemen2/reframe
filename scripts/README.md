# scripts

Developer helpers. Run them from the repository root.

| Script | What it does |
|--------|--------------|
| `uv run --no-project python scripts/fetch-tools.py [--build default\|override-test] [--install-dir DIR]` | Downloads the pinned FFmpeg build from `tools/ffmpeg.toml`, verifies its SHA-256, extracts it under `.tools/` (or lays it out as a bundled build in `DIR`, e.g. `$REFRAME_DATA_DIR/tools/ffmpeg`) and prints its `bin` directory |
| `uv run python scripts/make-testdata.py [--only NAME …] [--force]` | Generates the test media fixtures into `testdata/media/` (incremental). See `testdata/README.md` |
| `scripts/gen-api.sh [--check]` (or `npm run gen:api` in `frontend/`) | Exports the server's OpenAPI document (`scripts/export-openapi.py`, no server started) and generates `frontend/src/api/schema.d.ts` with `openapi-typescript`. `--check` writes nothing and fails with a diff when the committed file is stale (CI's `api-contract` job). Needs `uv sync` and `npm ci` |
| `uv run python scripts/dev-server.py --port PORT [--fixtures a,b] [--tools-dir DIR] [--fake-ffmpeg SCENARIO.json] [--auth token\|password\|none]` | Runs a real `reframe-server` in web mode in a new temporary home (its own config, data, cache, media root with the fixtures, output root; `REFRAME_POWER_DRY_RUN=1`), serving `frontend/dist`, for browser checks and the end-to-end tests. Prints one JSON line with the URL and token when it answers; Ctrl+C, SIGTERM or SIGHUP stop it and remove the home |

## A Windows test machine

`scripts/windows-setup.ps1` prepares a Windows 10 or 11 machine (a VM or real hardware) to run
the CI commands and build the desktop shell. It installs Git for Windows, uv with the Python of
`.python-version`, Node.js of `frontend/.node-version`, MKVToolNix and MediaInfo CLI (on
`PATH`, under `C:\Tools`), and unless `-SkipDesktop`, the Visual Studio Build Tools (MSVC and
the Windows SDK), Rust with rustfmt and clippy, and WebView2. Each part is skipped when it is
already there, so the script can be run again. Run it in an elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File windows-setup.ps1 [-AuthorizedKey 'ssh-ed25519 …'] [-NoSleep] [-SkipDesktop] [-RepoDir DIR [-RepoUrl URL] [-Branch NAME]]
```

- `-AuthorizedKey` installs the OpenSSH server (the Windows capability, or Microsoft's
  Win32-OpenSSH MSI when Windows Update cannot provide it), opens port 22 and ping, authorizes
  the key, and makes Git Bash the shell of SSH sessions, as CI runs `shell: bash`.
- `-NoSleep` turns off sleep and hibernation on mains power, for long test runs.
- `-RepoDir` runs `uv sync --frozen`, `reframe tools fetch` (the pinned FFmpeg as the bundled
  build) and `npm ci` in a checkout; with `-RepoUrl` it clones it first.

The first time, the script has to reach the machine without SSH: copy it over, or serve it
from the host (`python -m http.server --bind <host address>`) and download it with
`Invoke-WebRequest`. The repository is private, so a VM without GitHub credentials gets the
code from the host over SSH. On the VM, once:

```sh
git init reframe && git -C reframe config receive.denyCurrentBranch updateInstead
```

On the host (with a `win10` entry in `~/.ssh/config`), then for every update:

```sh
git push --receive-pack='git receive-pack' win10:reframe HEAD:refs/heads/<branch>
```

The GUI of the desktop app cannot be used over SSH (Windows runs SSH sessions without a
desktop): test it at the machine's console.
