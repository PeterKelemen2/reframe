"""Fail when a Windows package contains FFmpeg: ``ffmpeg.exe``, ``ffprobe.exe``, an FFmpeg DLL
(``avcodec-62.dll``) or a ``tools/ffmpeg`` folder. The app downloads FFmpeg instead.

Usage: no-ffmpeg-check.py FOLDER... Each folder is the packaged layout, or an installer's
extracted contents; each must hold at least one ``.exe``, so an empty or failed extraction is
no pass. Exit codes: 0 no FFmpeg; 1 FFmpeg found, or a folder without an ``.exe``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_FFMPEG_FILE = re.compile(
    r"^(?:ffmpeg|ffprobe)\.exe$|^(?:avcodec|avformat|avutil|avfilter|avdevice)-\d+\.dll$",
    re.IGNORECASE,
)


def ffmpeg_parts(folder: Path) -> list[Path]:
    """The FFmpeg files and ``tools/ffmpeg`` folders under ``folder``."""
    found = []
    for path in sorted(folder.rglob("*")):
        name = path.name.lower()
        if path.is_dir():
            if name == "ffmpeg" and path.parent.name.lower() == "tools":
                found.append(path)
        elif _FFMPEG_FILE.match(name):
            found.append(path)
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    failed = False
    for folder in map(Path, argv):
        exes = (
            [p for p in folder.rglob("*") if p.suffix.lower() == ".exe"] if folder.is_dir() else []
        )
        if not exes:
            print(f"::error::{folder} holds no .exe: not a package's contents", file=sys.stderr)
            failed = True
            continue
        parts = ffmpeg_parts(folder)
        for path in parts:
            print(f"::error::FFmpeg in the package: {path}", file=sys.stderr)
        failed = failed or bool(parts)
        if not parts:
            print(f"{folder}: no FFmpeg ({len(exes)} .exe files)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
