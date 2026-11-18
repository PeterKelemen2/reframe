# tools

`uv run python scripts/bundle-tools.py --platform linux-x64|windows-x64` lays out this folder;
the app ships it as `tools/` next to `sidecar/`. The packages contain no FFmpeg: on Linux the
folder holds `libva/` (built from its pin), which the app copies into a downloaded FFmpeg's
`lib/`; on Windows it holds nothing else. Only this file is committed: without the folder the
app does not build.
