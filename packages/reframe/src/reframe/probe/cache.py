"""Probe results by file version: JSON files in ``<cache dir>/probe/`` and a small memory layer.

The key is the absolute path, size and mtime in nanoseconds, so a changed file gets a new key.
An entry also records the ffprobe identity, the probe options and :func:`parser_fingerprint`,
which changes with the parser's source: an entry that does not match is a miss, as is a corrupt
or unreadable one. A cache error never fails a probe.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reframe import paths
from reframe.models.media import MediaSource
from reframe.probe.parse import PARSER_VERSION
from reframe.settings import too_deep

__all__ = [
    "CACHE_FORMAT",
    "DEFAULT_MAX_AGE",
    "DEFAULT_MAX_ENTRIES",
    "MEMORY_ENTRIES",
    "PRUNE_EVERY",
    "CacheKey",
    "ProbeCache",
    "parser_fingerprint",
]

#: Version of the entry layout.
CACHE_FORMAT = 1
MEMORY_ENTRIES = 512
DEFAULT_MAX_ENTRIES = 10_000
DEFAULT_MAX_AGE = 180 * 24 * 3600.0
PRUNE_EVERY = 200
#: A temporary file older than this was left behind by a crash.
_STALE_TMP_AGE = 3600.0

#: The modules whose source decides what a probe produces (``matroska.py`` gives the track's
#: ``language_ietf``).
_PARSER_MODULES = (
    "parse.py",
    "names.py",
    "roles.py",
    "hdr.py",
    "bitrate.py",
    "mediainfo.py",
    "matroska.py",
    "prober.py",
)


@functools.cache
def parser_fingerprint() -> str:
    """``PARSER_VERSION`` and a hash of the parser modules' source.

    Without the source files (a frozen app that ships only bytecode), the Reframe version
    stands in for the hash.
    """
    digest = hashlib.sha256()
    here = Path(__file__).resolve().parent
    try:
        for name in _PARSER_MODULES:
            digest.update(name.encode())
            digest.update((here / name).read_bytes())
    except OSError:
        from reframe import __version__

        return f"{PARSER_VERSION}:reframe-{__version__}"
    return f"{PARSER_VERSION}:{digest.hexdigest()[:16]}"


@dataclass(frozen=True, slots=True)
class CacheKey:
    path: str
    """Absolute path as a string."""
    size: int
    mtime_ns: int

    @classmethod
    def for_file(cls, path: Path, stat: os.stat_result) -> CacheKey:
        return cls(str(path.absolute()), stat.st_size, stat.st_mtime_ns)

    def digest(self) -> str:
        text = f"{self.path}\0{self.size}\0{self.mtime_ns}"
        return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Entry:
    tool: str
    options: Mapping[str, Any]
    source: MediaSource


class ProbeCache:
    """Probe results by file version. Thread-safe; file I/O is small and synchronous."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        memory_entries: int = MEMORY_ENTRIES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_age: float = DEFAULT_MAX_AGE,
    ):
        self.directory = directory if directory is not None else paths.cache_dir() / "probe"
        self.max_entries = max_entries
        self.max_age = max_age
        self._memory: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self._memory_entries = memory_entries
        self._lock = threading.Lock()
        self._puts = 0

    def entry_path(self, key: CacheKey) -> Path:
        return self.directory / f"{key.digest()}.json"

    def get(
        self, key: CacheKey, *, tool: str, options: Mapping[str, Any] | None = None
    ) -> MediaSource | None:
        """The cached source for ``key`` made by ``tool`` with ``options``, else ``None``.
        The source is a copy: changing it does not change the cache."""
        opts = dict(options or {})
        with self._lock:
            entry = self._memory.get(key)
            if entry is not None:
                self._memory.move_to_end(key)
        if entry is None:
            entry = self._read(key)
            if entry is not None:
                self._remember(key, entry)
        if entry is None or entry.tool != tool or dict(entry.options) != opts:
            return None
        return entry.source.model_copy(deep=True)

    def _read(self, key: CacheKey) -> _Entry | None:
        try:
            raw = json.loads(self.entry_path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):  # missing, unreadable, or not JSON (corrupt)
            return None
        except RecursionError:  # CPython's C-stack check: nested far beyond MAX_DEPTH
            return None
        if not isinstance(raw, dict) or too_deep(raw):
            return None
        stored_key = raw.get("key")
        if (
            raw.get("format") != CACHE_FORMAT
            or raw.get("parser") != parser_fingerprint()
            or not isinstance(stored_key, dict)
            or stored_key.get("path") != key.path
            or stored_key.get("size") != key.size
            or stored_key.get("mtime_ns") != key.mtime_ns
            or not isinstance(raw.get("tool"), str)
            or not isinstance(raw.get("options"), dict)
        ):
            return None
        try:
            source = MediaSource.model_validate(raw.get("source"))
        except ValidationError:
            return None
        return _Entry(raw["tool"], raw["options"], source)

    def put(
        self,
        key: CacheKey,
        source: MediaSource,
        *,
        tool: str,
        options: Mapping[str, Any] | None = None,
    ) -> bool:
        """Store ``source``. Returns ``False`` if the file could not be written (the memory
        layer still has it), or if the entry would be nested more than ``MAX_DEPTH`` levels
        deep (then it is not cached at all)."""
        opts = dict(options or {})
        try:
            dumped = source.model_dump(mode="json")
        except (ValueError, TypeError, RecursionError):  # Pydantic gives up on very deep nesting
            return False
        doc = {
            "format": CACHE_FORMAT,
            "parser": parser_fingerprint(),
            "key": {"path": key.path, "size": key.size, "mtime_ns": key.mtime_ns},
            "tool": tool,
            "options": opts,
            "source": dumped,
        }
        if too_deep(doc):
            return False
        entry = _Entry(tool, opts, source.model_copy(deep=True))
        self._remember(key, entry)
        try:
            # ASCII escapes: a path with a lone surrogate cannot be written as UTF-8.
            text = json.dumps(doc, ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{key.digest()[:16]}-", suffix=".tmp", dir=self.directory
            )
        except OSError:
            return False
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(text)
            os.replace(tmp, self.entry_path(key))
        except (OSError, ValueError):
            # Disk full, read-only, or (Windows) the target is open elsewhere.
            with contextlib.suppress(OSError):
                tmp.unlink()
            return False
        with self._lock:
            due = self._puts % PRUNE_EVERY == 0
            self._puts += 1
        if due:
            self.prune()
        return True

    def prune(self, *, now: float | None = None) -> int:
        """Remove old entries, the oldest beyond ``max_entries``, and crash leftovers.

        Returns the number of files removed. Errors (a file in use, a race with another
        process) are ignored.
        """
        now = time.time() if now is None else now
        removed = 0
        entries: list[tuple[float, Path]] = []
        try:
            listing = list(os.scandir(self.directory))
        except OSError:
            return 0
        for item in listing:
            try:
                mtime = item.stat().st_mtime
            except OSError:
                continue
            path = Path(item.path)
            if item.name.endswith(".tmp"):
                if now - mtime > _STALE_TMP_AGE and _unlink(path):
                    removed += 1
            elif item.name.endswith(".json"):
                if now - mtime > self.max_age:
                    removed += _unlink(path)
                else:
                    entries.append((mtime, path))
        entries.sort()
        for _, path in entries[: max(len(entries) - self.max_entries, 0)]:
            removed += _unlink(path)
        return removed

    def _remember(self, key: CacheKey, entry: _Entry) -> None:
        with self._lock:
            self._memory[key] = entry
            self._memory.move_to_end(key)
            while len(self._memory) > self._memory_entries:
                self._memory.popitem(last=False)

    def forget_memory(self) -> None:
        """Drop the in-memory layer (the files stay)."""
        with self._lock:
            self._memory.clear()

    def clear(self) -> None:
        """Remove every entry (memory and files)."""
        self.forget_memory()
        if not self.directory.is_dir():
            return
        for path in self.directory.glob("*.json"):
            with contextlib.suppress(OSError):
                path.unlink()


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
    except OSError:
        return False
    return True
