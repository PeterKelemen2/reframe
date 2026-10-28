"""The page cache of a set of files, without root: ``fincore`` counts their cached bytes, and
``posix_fadvise(POSIX_FADV_DONTNEED)`` drops their clean pages that no process maps."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Resident:
    cached: int
    """Bytes of the files in the page cache."""
    size: int


def _files(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from (p for p in path.rglob("*") if p.is_file() and not p.is_symlink())
        elif path.is_file():
            yield path


def resident(paths: Iterable[Path]) -> Resident:
    output = subprocess.run(
        ["fincore", "--json", "--bytes", "--recursive", "--total", "-o", "RES,SIZE,FILE"]
        + [str(path) for path in paths],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    total = json.loads(output)["fincore"][-1]
    return Resident(int(total["res"]), int(total["size"]))


def evict(paths: Iterable[Path]) -> int:
    """Drop the cached pages of every file below ``paths``; returns the number of files."""
    fadvise: Callable[[int, int, int, int], None] = getattr(os, "posix_fadvise")  # noqa: B009
    count = 0
    for file in _files(paths):
        try:
            fd = os.open(file, os.O_RDONLY)
        except OSError:
            continue
        try:
            fadvise(fd, 0, 0, getattr(os, "POSIX_FADV_DONTNEED"))  # noqa: B009
            count += 1
        finally:
            os.close(fd)
    return count
