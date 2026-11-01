"""The file-system reads of validation, behind one interface that tests replace.

Validation does no I/O except through a :class:`FileSystemView`, so tests can run its rules
against a fake file system, with Windows paths on Linux (:class:`~pathlib.PureWindowsPath`).
Every method answers a question and never raises: a path that cannot be read is "does not
exist", "not writable" or ``None``. A path with a NUL character gets the same answers, since
the ``os`` calls raise ``ValueError`` for it, not ``OSError``.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import threading
from pathlib import Path, PurePath
from typing import Protocol

from reframe.naming import FileTimes, NamingFs, RealNamingFs
from reframe.textfile import TextCharset, read_charset

__all__ = ["FileSystemView", "LocalFileSystem", "has_nul"]

#: Files whose encoding :class:`LocalFileSystem` remembers between validations.
_CHARSET_CACHE = 256


class FileSystemView(NamingFs, Protocol):
    """What validation reads from the file system."""

    def exists(self, path: PurePath) -> bool:
        """A file or folder exists at ``path`` (case-insensitively where the file system is)."""
        ...

    def is_dir(self, path: PurePath) -> bool:
        """``path`` is an existing folder."""
        ...

    def writable_dir(self, path: PurePath) -> bool:
        """New files can be created in the existing folder ``path``."""
        ...

    def writable_file(self, path: PurePath) -> bool:
        """The existing file ``path`` can be opened for writing (an in-place metadata edit
        writes its source). ``False`` when it does not exist or is a folder."""
        ...

    def free_bytes(self, path: PurePath) -> int | None:
        """Free space for the current user on the volume of the existing ``path``; ``None``
        when it cannot be read."""
        ...

    def same_file(self, a: PurePath, b: PurePath) -> bool:
        """``a`` and ``b`` name the same existing file (also through another spelling: case on
        a case-insensitive file system, ``..``, a link). ``False`` when either does not exist."""
        ...

    def text_charset(self, path: PurePath) -> TextCharset | None:
        """The character encoding of the text file ``path``, as
        :func:`reframe.textfile.read_charset` tells it; ``None`` when ``path`` is not a regular
        file or cannot be read."""
        ...


def has_nul(path: PurePath | str) -> bool:
    """``path`` has a NUL character: no file system allows it, and the ``os`` calls that take
    a path raise ``ValueError`` for it (``exists`` and the ``is*`` tests answer ``False``)."""
    return "\0" in str(path)


def _can_open_for_update(file: PurePath) -> bool:
    try:
        with open(file, "r+b"):
            return True
    except OSError:
        return False


def _can_create_file(folder: PurePath) -> bool:
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


class LocalFileSystem(RealNamingFs):
    """The real file system: ``os``, ``shutil`` and ``tempfile`` calls only, no subprocess.

    A path with a NUL character names no file: every method answers as for a path that does
    not exist, before any ``os`` call (which would raise ``ValueError``)."""

    def __init__(self) -> None:
        # Validation runs on every edit; a file is read again only when its stat changes.
        self._charsets: dict[tuple[object, ...], TextCharset] = {}
        self._lock = threading.Lock()

    def exists(self, path: PurePath) -> bool:
        return not has_nul(path) and os.path.exists(path)

    def is_dir(self, path: PurePath) -> bool:
        return not has_nul(path) and os.path.isdir(path)

    def writable_dir(self, path: PurePath) -> bool:
        if has_nul(path) or not os.path.isdir(path):
            return False
        if sys.platform == "win32":
            # os.access only reads the read-only attribute on Windows (folders ignore it), not
            # the ACL. Creating a temporary file is the reliable test; it is deleted on close.
            return _can_create_file(path)
        else:
            return os.access(path, os.W_OK | os.X_OK)

    def writable_file(self, path: PurePath) -> bool:
        if has_nul(path) or not os.path.isfile(path):
            return False
        if sys.platform == "win32":
            # os.access only reads the read-only attribute on Windows, not the ACL or a file
            # that another process opened without write sharing. Opening it for update (not
            # truncated, nothing written) is the reliable test.
            return _can_open_for_update(path)
        else:
            return os.access(path, os.W_OK)

    def free_bytes(self, path: PurePath) -> int | None:
        if has_nul(path):
            return None
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def same_file(self, a: PurePath, b: PurePath) -> bool:
        if has_nul(a) or has_nul(b):
            return False
        try:
            first, second = os.stat(a), os.stat(b)
            if first.st_ino and second.st_ino:
                return os.path.samestat(first, second)
            # A file system without file indexes (st_ino 0, some Windows volumes): every file
            # would be "the same", so compare the paths with links resolved.
            return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
        except OSError:
            return False

    def text_charset(self, path: PurePath) -> TextCharset | None:
        if has_nul(path):
            return None
        try:
            info = os.stat(path)
            if not stat.S_ISREG(info.st_mode):
                return None
            key = (
                str(path),
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
            with self._lock:
                found = self._charsets.get(key)
            if found is None:
                found = read_charset(path)
                with self._lock:
                    if len(self._charsets) >= _CHARSET_CACHE:
                        self._charsets.clear()
                    self._charsets[key] = found
            return found
        except OSError:
            return None

    def list_files(self, folder: Path) -> list[str] | None:
        return None if has_nul(folder) else super().list_files(folder)

    def file_times(self, file: Path) -> FileTimes | None:
        return None if has_nul(file) else super().file_times(file)
