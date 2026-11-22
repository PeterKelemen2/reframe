"""File operations of the job runner. They block, so call them from a worker thread.

A final name never replaces an existing file. On Windows, a call that hits a file that another
process holds open is retried.
"""

from __future__ import annotations

import contextlib
import errno
import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from reframe.fsretry import replace_file, retry
from reframe.models.plan import PlanFile
from reframe.validation.fs import LocalFileSystem

__all__ = [
    "FileKey",
    "file_key",
    "remove_files",
    "rename_no_replace",
    "replace_file",
    "same_file",
    "same_key",
    "writable_file",
    "write_plan_files",
]

#: ``True`` on Windows (tests set it).
WINDOWS = os.name == "nt"
#: ``os.link`` errors that mean "this file system has no hard links".
_NO_LINKS = {errno.EPERM, errno.EXDEV, errno.EMLINK, errno.ENOSYS, errno.EOPNOTSUPP}


def write_plan_files(files: Iterable[PlanFile]) -> None:
    """Write each file as UTF-8 with LF line ends (its folder must exist)."""
    for plan_file in files:
        # surrogateescape: a file-name byte that is not UTF-8 goes to FFmpeg unchanged.
        with open(
            plan_file.path, "w", encoding="utf-8", errors="surrogateescape", newline="\n"
        ) as handle:
            handle.write(plan_file.content)


@dataclass(frozen=True, slots=True)
class FileKey:
    """Which file a path is. :func:`file_key` reads it once, and :func:`same_key` compares
    keys without a file-system call, so the event loop never waits for a disk."""

    path: str
    """The path with its links resolved (for a file that does not exist yet, the existing part
    of its folder) and the OS's case. A path that cannot be resolved (a NUL character) is kept
    as written, made absolute."""
    identity: tuple[int, int] | None = None
    """``(st_dev, st_ino)`` of the existing file, or ``None`` when there is none, it cannot be
    read, or the file system has no file index (``st_ino`` 0 on some Windows volumes: every file
    would have the same pair)."""


def file_key(path: str | os.PathLike[str]) -> FileKey:
    """``path``'s :class:`FileKey`. Blocking; never raises."""
    return FileKey(_resolved(path), _identity(path))


def same_key(a: FileKey, b: FileKey | None) -> bool:
    """``a`` and ``b`` name one file: the same resolved path, the same path without case, or the
    same identity (a hard link). No file-system call. Case is ignored on Linux too, which errs
    on the safe side."""
    if b is None:
        return False
    return (
        a.path == b.path
        or a.path.casefold() == b.path.casefold()
        or (a.identity is not None and a.identity == b.identity)
    )


def same_file(a: Path, b: Path) -> bool:
    """Whether ``a`` and ``b`` name one file (see :func:`same_key`). Blocking; never raises."""
    return same_key(file_key(a), file_key(b))


def writable_file(path: Path) -> bool:
    """The existing file ``path`` can be opened for writing by this process, by the test of
    :meth:`~reframe.validation.LocalFileSystem.writable_file`. On Windows that opens the file for
    update, which also sees the ACL and another process's lock without write sharing."""
    return LocalFileSystem().writable_file(path)


def _resolved(path: str | os.PathLike[str]) -> str:
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):  # a NUL character: realpath's lstat refuses the path
        try:
            resolved = os.path.abspath(path)
        except (OSError, ValueError):
            resolved = os.fspath(path)
    try:
        return os.path.normcase(resolved)
    except ValueError:  # Windows' LCMapStringEx and a NUL character
        return resolved.lower()


def _identity(path: str | os.PathLike[str]) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    if stat.st_ino == 0:  # no file index: every file of the volume would be "the same"
        return None
    return (stat.st_dev, stat.st_ino)


def remove_files(paths: Iterable[Path], *, keep: Path | None = None) -> list[str]:
    """Remove each file that exists; returns a message for each one that could not be removed.
    ``keep`` (the source file) is never removed, whatever spelling of it is in ``paths``.
    Never raises for a path that cannot be used (a NUL character)."""
    problems: list[str] = []
    for path in paths:
        if keep is not None and same_file(path, keep):
            problems.append(f"{path} is the source file, not removed")
            continue
        try:
            retry(partial(path.unlink, missing_ok=True))
        except IsADirectoryError:
            problems.append(f"{path} is a folder, not removed")
        except OSError as exc:
            problems.append(f"{path} could not be removed: {exc.strerror or exc}")
        except ValueError as exc:  # a NUL character: no file can have this name
            problems.append(f"{os.fspath(path)!r} could not be removed: {exc}")
    return problems


def rename_no_replace(source: Path, target: Path) -> None:
    """Rename ``source`` to ``target``; ``FileExistsError`` when ``target`` exists. On POSIX
    ``os.rename`` would replace the target, so a hard link is made first."""
    if WINDOWS:
        retry(partial(os.rename, source, target))
        return
    try:
        os.link(source, target)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in _NO_LINKS:
            raise
        if os.path.lexists(target):
            raise FileExistsError(errno.EEXIST, "File exists", str(target)) from exc
        os.rename(source, target)
        return
    with contextlib.suppress(OSError):  # it has its final name; a second name is only untidy
        os.unlink(source)
