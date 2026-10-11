# scripts

Developer helpers. Run them from the repository root.

| Script | What it does |
|--------|--------------|
| `uv run --no-project python scripts/fetch-tools.py [--build default\|override-test]` | Downloads the pinned FFmpeg build from `tools/ffmpeg.toml`, verifies its SHA-256, extracts it under `.tools/` and prints its `bin` directory |
| `uv run python scripts/make-testdata.py [--only NAME …] [--force]` | Generates the test media fixtures into `testdata/media/` (incremental). See `testdata/README.md` |
