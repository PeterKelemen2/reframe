# tools

`uv run python scripts/bundle-tools.py --platform linux-x64|windows-x64` puts the pinned FFmpeg
into this folder; the app ships it as `tools/` next to `sidecar/`. One layout is for one platform: the script removes the other platform's folders.
Only this file is committed: without the folder the app does not build.
