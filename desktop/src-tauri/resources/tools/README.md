# tools

`uv run python scripts/bundle-tools.py --platform linux-x64|windows-x64` puts the pinned FFmpeg
(and, on Windows, MKVToolNix and MediaInfo) into this folder; the app ships it as `tools/` next
to `sidecar/`. Only this file is committed: without the folder the app does not build.
