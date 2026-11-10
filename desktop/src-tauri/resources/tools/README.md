# tools

`uv run --no-project python scripts/bundle-tools.py` puts the tools that the app ships into this
folder: FFmpeg (with libva on Linux), and mkvpropedit on Windows. Only this file is committed:
without the folder the app does not build.
