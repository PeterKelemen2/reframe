# Real `-version` outputs

Captured on 2026-10-11 (Arch Linux x86_64) with `<binary> -version`, stdout only, bytes
unchanged. `tests/tools/test_versions.py` parses every file.

| File | Binary |
|------|--------|
| `ffmpeg-arch-n9.0.2.txt`, `ffprobe-arch-n9.0.2.txt` | Arch Linux package `ffmpeg 2:9.0.2` (`/usr/bin/ffmpeg`) |
| `ffmpeg-btbn-n8.1.3.txt`, `ffprobe-btbn-n8.1.3.txt` | BtbN `override-test` build from `tools/ffmpeg.toml` |
| `ffmpeg-btbn-n7.1.txt` | BtbN `ffmpeg-n7.1-184-gdc07f98934-linux64-lgpl-shared-7.1` (autobuild-2025-01-31-12-58), run with `LD_LIBRARY_PATH=lib` |
| `ffmpeg-btbn-n6.1.2.txt` | BtbN `ffmpeg-n6.1.2-21-gac60bc2bb0-linux64-lgpl-shared-6.1` (autobuild-2025-01-31-12-58), run with `LD_LIBRARY_PATH=lib` |
| `ffmpeg-btbn-master-N-127032.txt` | BtbN git master `ffmpeg-N-127032-g6ae491a26c-linux64-gpl-shared` (autobuild-2026-09-30-13-08) |

The pinned default build (`n9.0.2-17-g2a571b6068-20260930`) is in
`testing/reframe_testing/fake_data/ffmpeg_version.stdout.txt` and `ffprobe_version.stdout.txt`.

Library major versions per release, from these files: 6.1 → libavcodec/libavformat 60,
7.1 → 61, 8.1 → 62, 9.0 → 63; master `N-127032` (after 9.0) → 63.
