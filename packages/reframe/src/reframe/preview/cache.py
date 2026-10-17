"""The preview cache (05 §C-10, 03 §Preview): PNG frames and preview clips on disk.

**Layout.** ``<cache dir>/frames/<key>.png`` and ``<cache dir>/clips/<id>.<ext>``. A file is
written under a temporary name in the same folder (``.tmp-<random>-<name>``, or the plan's
``<id>.part.<ext>`` for a clip) and renamed when it is complete, so a reader never sees half
a file and two tasks that make the same frame do not disturb each other.

**Keys** (decision 0033). A frame key is ``<source>-<milliseconds>-<settings>``:

- ``source``: 16 hex digits of a hash of the source file's absolute path, size and
  modification time in nanoseconds (:func:`source_fingerprint`): a changed file gets new keys;
- the timestamp in whole milliseconds (:func:`timestamp_ms`; the frame is taken at exactly
  that time), at most :data:`MAX_TIMESTAMP_MS` (12 digits; a later time is refused before a key
  is made);
- ``settings``: 16 hex digits of a hash of everything else that changes the picture
  (:func:`digest` of the frame recipe, the PNG options and the FFmpeg build; the recipes are in
  :mod:`reframe.preview.graph`).

A key is also the file name, so :func:`is_frame_key` accepts only that form: a key from a URL
can never name another file. A clip id is 32 hex digits (:func:`is_clip_id`).

**LRU with a size limit.** Every use of a file (a cache hit, :meth:`PreviewCache.find_frame`,
:meth:`PreviewCache.find_clip`) sets its modification time to now, so the modification time is
the time of the last use. :meth:`PreviewCache.trim` removes the least recently used files of
both folders until they fit the limit (Settings → Preview ``cache_size_mb``, one budget for
frames and clips). It never removes the files the calling task made or used (``protect``) or a
file used in the last :data:`GRACE` seconds (another task's fresh result that its caller has
not fetched yet); so a limit of 0 keeps only the latest results. Temporary files are removed
when they are older than :data:`STALE` seconds (a crash left them).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CLIPS",
    "FRAMES",
    "GRACE",
    "MAX_TIMESTAMP_MS",
    "STALE",
    "CacheEntry",
    "PreviewCache",
    "digest",
    "frame_key",
    "is_clip_id",
    "is_frame_key",
    "megabytes",
    "source_fingerprint",
    "timestamp_ms",
]

#: Sub-folders of ``<cache dir>``.
FRAMES = "frames"
CLIPS = "clips"
#: Bumped when the meaning of a key changes: every older key is then a miss (and is removed
#: by the LRU in time).
KEY_FORMAT = 1
#: Seconds a fresh file is safe from :meth:`PreviewCache.trim`.
GRACE = 30.0
#: Seconds after which a temporary file is left over from a crash.
STALE = 3600.0
TEMP_PREFIX = ".tmp-"

#: The latest timestamp a frame key holds (12 digits of milliseconds: about 31.7 years).
MAX_TIMESTAMP_MS = 10**12 - 1
_KEY = re.compile(r"[0-9a-f]{16}-[0-9]{1,12}-[0-9a-f]{16}")
_CLIP_ID = re.compile(r"[0-9a-f]{32}")
#: In a clip folder, the files of a plan that is running (``<id>.part.mkv``,
#: ``<id>.part.passlog-0.log``, ``<id>.part.chapters.txt``).
_PART = ".part."


def digest(*parts: object) -> str:
    """The SHA-256 (hex) of ``parts`` as canonical JSON (paths and other objects as text)."""
    text = json.dumps(
        [KEY_FORMAT, *parts], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def source_fingerprint(path: Path, stat: os.stat_result) -> str:
    """16 hex digits that identify one version of the source file (path, size, mtime)."""
    return digest("source", str(path), stat.st_size, stat.st_mtime_ns)[:16]


def timestamp_ms(seconds: float) -> int:
    """A timestamp in whole milliseconds (the precision of a frame key)."""
    return round(seconds * 1000)


def frame_key(source: str, timestamp: float, settings: str) -> str:
    """``<source>-<milliseconds>-<settings>`` (see the module doc)."""
    return f"{source}-{timestamp_ms(timestamp)}-{settings[:16]}"


def is_frame_key(key: str) -> bool:
    return _KEY.fullmatch(key) is not None


def is_clip_id(clip_id: str) -> bool:
    return _CLIP_ID.fullmatch(clip_id) is not None


def megabytes(value: int) -> int:
    """Settings → Preview ``cache_size_mb`` in bytes (1 MB = 2**20 bytes)."""
    return max(0, value) * 2**20


@dataclass(frozen=True, slots=True)
class CacheEntry:
    path: Path
    size: int
    used: float
    """The modification time: the last use."""


def _is_temp(name: str) -> bool:
    return name.startswith(TEMP_PREFIX) or _PART in name


class PreviewCache:
    """The frame and clip folders of one ``<cache dir>`` (see the module doc). Blocking file
    calls: run them in a thread from async code, except the cheap lookups."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.frames = root / FRAMES
        self.clips = root / CLIPS

    # ------------------------------------------------------------------ names

    def frame(self, key: str) -> Path:
        """The file of a frame key (it may not exist)."""
        if not is_frame_key(key):
            raise ValueError(f"not a frame key: {key!r}")
        return self.frames / f"{key}.png"

    def clip(self, clip_id: str, extension: str) -> Path:
        """The file of a clip (it may not exist); ``extension`` with the dot (``.mkv``)."""
        if not is_clip_id(clip_id):
            raise ValueError(f"not a clip id: {clip_id!r}")
        return self.clips / f"{clip_id}{extension}"

    @staticmethod
    def temporary(final: Path) -> Path:
        """A fresh temporary name next to ``final`` (renamed to ``final`` when complete)."""
        return final.with_name(f"{TEMP_PREFIX}{secrets.token_hex(4)}-{final.name}")

    # ------------------------------------------------------------------ lookups

    def find_frame(self, key: str) -> Path | None:
        """The cached PNG of ``key`` (marked as used), else ``None`` (also for a key that is
        not one)."""
        if not is_frame_key(key):
            return None
        path = self.frames / f"{key}.png"
        return path if self.touch(path) else None

    def find_clip(self, clip_id: str) -> Path | None:
        """The cached clip with this id (marked as used), else ``None``."""
        if not is_clip_id(clip_id):
            return None
        try:
            names = os.listdir(self.clips)
        except OSError:
            return None
        prefix = clip_id + "."
        for name in sorted(names):
            if name.startswith(prefix) and not _is_temp(name):
                path = self.clips / name
                if self.touch(path):
                    return path
        return None

    @staticmethod
    def touch(path: Path) -> bool:
        """Mark ``path`` as used now; ``False`` when it is not a file (any more)."""
        try:
            os.utime(path)
        except OSError:
            return False
        return path.is_file()

    # ------------------------------------------------------------------ the LRU

    def entries(self, *, now: float | None = None) -> list[CacheEntry]:
        """The cached files of both folders, least recently used first. Temporary files are
        left out (and removed when they are :data:`STALE`)."""
        clock = time.time() if now is None else now
        found: list[CacheEntry] = []
        for folder in (self.frames, self.clips):
            try:
                scan = list(os.scandir(folder))
            except OSError:
                continue
            for item in scan:
                try:
                    if not item.is_file(follow_symlinks=False):
                        continue
                    stat = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _is_temp(item.name):
                    if clock - stat.st_mtime > STALE:
                        with contextlib.suppress(OSError):
                            os.unlink(item.path)
                    continue
                found.append(CacheEntry(Path(item.path), stat.st_size, stat.st_mtime))
        found.sort(key=lambda e: (e.used, str(e.path)))
        return found

    def size(self) -> int:
        """Bytes of the cached files (without temporary files)."""
        return sum(e.size for e in self.entries())

    def trim(
        self,
        limit: int,
        *,
        protect: Collection[Path] = (),
        now: float | None = None,
        grace: float = GRACE,
    ) -> list[Path]:
        """Remove the least recently used files until the cache holds at most ``limit``
        bytes; returns the removed files. ``protect`` and files used in the last ``grace``
        seconds stay (see the module doc)."""
        clock = time.time() if now is None else now
        entries = self.entries(now=clock)
        total = sum(e.size for e in entries)
        kept = {Path(p) for p in protect}
        removed: list[Path] = []
        for entry in entries:
            if total <= limit:
                break
            if entry.path in kept or clock - entry.used < grace:
                continue
            try:
                os.unlink(entry.path)
            except FileNotFoundError:
                pass
            except OSError:
                continue
            total -= entry.size
            removed.append(entry.path)
        return removed

    def clear(self) -> int:
        """Remove every cached frame and clip (Settings → Preview → Clear cache); returns the
        bytes freed. Temporary files of running tasks stay."""
        freed = 0
        for entry in self.entries():
            try:
                os.unlink(entry.path)
            except OSError:
                continue
            freed += entry.size
        return freed
