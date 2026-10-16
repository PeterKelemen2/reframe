"""The file-system reads of validation, behind one interface that tests replace (C-8).

:func:`reframe.validation.validate` does no I/O except through a :class:`FileSystemView`, so
the output rules (folder writable, output = source, collision, free space) and the naming rule
run against a fake file system in tests, with Windows paths too.

Every method answers a question and never raises: a path that cannot be read is "does not
exist" / "not writable" / ``None``. Paths are :class:`~pathlib.PurePath` so that tests can pass
:class:`~pathlib.PureWindowsPath` on Linux; :class:`LocalFileSystem` uses them as ``os``
paths.

The view extends :class:`reframe.naming.NamingFs` (the folder listing and file times of output
naming), so the same object serves the naming rule.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import PurePath
from typing import Protocol

from reframe.naming import NamingFs, RealNamingFs

__all__ = ["FileSystemView", "LocalFileSystem"]


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
        writes its source, C-13). ``False`` when it does not exist or is a folder."""
        ...

    def free_bytes(self, path: PurePath) -> int | None:
        """Free space for the current user on the volume of the existing ``path``; ``None``
        when it cannot be read."""
        ...

    def same_file(self, a: PurePath, b: PurePath) -> bool:
        """``a`` and ``b`` name the same existing file (also through another spelling: case on
        a case-insensitive file system, ``..``, a link). ``False`` when either does not exist."""
        ...


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
    """The real file system: ``os``, ``shutil`` and ``tempfile`` calls only, no subprocess."""

    def exists(self, path: PurePath) -> bool:
        return os.path.exists(path)

    def is_dir(self, path: PurePath) -> bool:
        return os.path.isdir(path)

    def writable_dir(self, path: PurePath) -> bool:
        if not os.path.isdir(path):
            return False
        if sys.platform == "win32":
            # os.access only reads the read-only attribute on Windows (folders ignore it), not
            # the ACL. Creating a temporary file is the reliable test; it is deleted on close.
            return _can_create_file(path)
        else:
            return os.access(path, os.W_OK | os.X_OK)

    def writable_file(self, path: PurePath) -> bool:
        if not os.path.isfile(path):
            return False
        if sys.platform == "win32":
            # os.access only reads the read-only attribute on Windows, not the ACL or a file
            # that another process opened without write sharing. Opening it for update (not
            # truncated, nothing written) is the reliable test.
            return _can_open_for_update(path)
        else:
            return os.access(path, os.W_OK)

    def free_bytes(self, path: PurePath) -> int | None:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def same_file(self, a: PurePath, b: PurePath) -> bool:
        try:
            return os.path.samefile(a, b)
        except OSError:
            return False
