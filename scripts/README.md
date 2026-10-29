# scripts

Developer helpers. Run them from the repository root.

| Script | What it does |
|--------|--------------|
| `uv run --no-project python scripts/fetch-tools.py [--build default\|override-test] [--install-dir DIR]` | Downloads the pinned FFmpeg build from `tools/ffmpeg.toml`, verifies its SHA-256, extracts it under `.tools/` (or lays it out as a bundled build in `DIR`, e.g. `$REFRAME_DATA_DIR/tools/ffmpeg`) and prints its `bin` directory |
| `uv run python scripts/make-testdata.py [--only NAME …] [--force]` | Generates the test media fixtures into `testdata/media/` (incremental). See `testdata/README.md` |
| `scripts/gen-api.sh [--check]` (or `npm run gen:api` in `frontend/`) | Exports the server's OpenAPI document (`scripts/export-openapi.py`, no server started) and generates `frontend/src/api/schema.d.ts` with `openapi-typescript`. `--check` writes nothing and fails with a diff when the committed file is stale (CI's `api-contract` job). Needs `uv sync` and `npm ci` |
| `uv run python scripts/dev-server.py --port PORT [--fixtures a,b] [--tools-dir DIR] [--fake-ffmpeg SCENARIO.json] [--auth token\|password\|none]` | Runs a real `reframe-server` in web mode in a new temporary home (its own config, data, cache, media root with the fixtures, output root; `REFRAME_POWER_DRY_RUN=1`), serving `frontend/dist`, for browser checks and the end-to-end tests. Prints one JSON line with the URL and token when it answers; Ctrl+C, SIGTERM or SIGHUP stop it and remove the home |
