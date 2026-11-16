"""The media files of a folder, in natural order."""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["MEDIA_EXTENSIONS", "list_media_files", "natural_key"]

#: Video files that a folder listing picks up (lower case, with the dot).
MEDIA_EXTENSIONS = frozenset(
    {
        ".mkv",
        ".mp4",
        ".m4v",
        ".mov",
        ".avi",
        ".webm",
        ".ts",
        ".m2ts",
        ".mts",
        ".mpg",
        ".mpeg",
        ".vob",
        ".wmv",
        ".asf",
        ".flv",
        ".ogm",
        ".ogv",
        ".3gp",
        ".divx",
        ".mxf",
    }
)

_DIGITS = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key: digit runs compare as numbers, the rest case-insensitively."""
    parts: list[tuple[int, int | str]] = []
    for i, part in enumerate(_DIGITS.split(name)):
        if i % 2:
            parts.append((0, int(part)))
        elif part:
            parts.append((1, part.casefold()))
    return tuple(parts)


def list_media_files(folder: Path, *, recursive: bool = False) -> list[Path]:
    """Media files in ``folder`` (or below it), naturally sorted by their relative path."""
    found: list[Path] = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found += [Path(root, f) for f in files if _is_media(f)]
    else:
        with os.scandir(folder) as entries:
            found = [
                Path(entry.path) for entry in entries if _is_media(entry.name) and entry.is_file()
            ]

    def key(path: Path) -> tuple[tuple[tuple[int, int | str], ...], ...]:
        return tuple(natural_key(part) for part in path.relative_to(folder).parts)

    return sorted(found, key=key)


def _is_media(name: str) -> bool:
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS
