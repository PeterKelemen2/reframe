"""File operations of the job runner: plan files, the final rename, clean-up (blocking; the
queue calls them in a worker thread).

- :func:`rename_no_replace` gives the ``.part`` file its final name only when that name is
  free: on Windows ``os.rename`` refuses an existing target (``FileExistsError``); on POSIX
  ``os.rename`` would replace it, so a hard link plus an unlink is used (the link fails when
  the name exists), with a check-then-rename fallback on file systems without hard links
  (FAT, exFAT, some network shares).
- :func:`replace_file` overwrites (collision policy ``overwrite``).
- On Windows a file that another process holds open (a player showing the old output, an
  antivirus scanner) gives ``PermissionError`` for a replace or a delete. Such a call is tried
  again :data:`ATTEMPTS` times with a growing pause (about 1.5 s in all), as the settings
  store does (decision 0015); on POSIX it is not retried.
- **Which file a path is** (:func:`same_file`, and the queue's job keys): :func:`file_key`
  reads it once (links resolved, ``(st_dev, st_ino)``; blocking), :func:`same_key` compares two
  keys without any file-system call. None of them raises for a path that cannot be used (a
  NUL character): such a path is compared as written (final review RB-2).
"""

from __future__ import annotations

import contextlib
import errno
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from reframe.models.plan import PlanFile
from reframe.validation.fs import LocalFileSystem

__all__ = [
    "ATTEMPTS",
    "DELAY",
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

#: How often a call that fails with ``PermissionError`` is tried on Windows.
ATTEMPTS = 6
#: The first pause between two tries (seconds); it doubles each time.
DELAY = 0.05
#: ``True`` on Windows (tests set it).
WINDOWS = os.name == "nt"
#: ``os.link`` errors that mean "this file system has no hard links".
_NO_LINKS = {errno.EPERM, errno.EXDEV, errno.EMLINK, errno.ENOSYS, errno.EOPNOTSUPP}


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _retry[T](call: Callable[[], T]) -> T:
    delay = DELAY
    for attempt in range(ATTEMPTS):
        try:
            return call()
        except PermissionError:
            if not WINDOWS or attempt == ATTEMPTS - 1:
                raise
            _sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


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
    """Which file a path is, read once by :func:`file_key` (blocking) and compared by
    :func:`same_key` without any file-system call. The queue keeps one per path of each job,
    so it can decide which job may start on the event loop without waiting for a disk or a
    network share (final review RB-1)."""

    path: str
    """The path with its links resolved (``realpath``; for a file that does not exist yet, the
    existing part of its folder), in the OS's case (``normcase``). A path that cannot be
    resolved (``realpath`` raises ``ValueError`` for a NUL character) is the path as written,
    made absolute."""
    identity: tuple[int, int] | None = None
    """``(st_dev, st_ino)`` of the existing file the path leads to (a hard link has its file's
    pair; on Windows the volume serial number and the file index). ``None`` when there is no
    such file, it cannot be read, or the file system gives no file index (``st_ino`` 0, as on
    some Windows volumes: every file there would have the same pair)."""


def file_key(path: str | os.PathLike[str]) -> FileKey:
    """``path``'s :class:`FileKey` (blocking: an ``lstat`` per part of the path and a ``stat``;
    never raises)."""
    return FileKey(_resolved(path), _identity(path))


def same_key(a: FileKey, b: FileKey | None) -> bool:
    """``a`` and ``b`` name one file: the same resolved path, the same path without case
    (Windows and macOS file systems ignore case; on Linux this errs on the safe side), or the
    same ``(st_dev, st_ino)`` (a hard link). No file-system call."""
    if b is None:
        return False
    return (
        a.path == b.path
        or a.path.casefold() == b.path.casefold()
        or (a.identity is not None and a.identity == b.identity)
    )


def same_file(a: Path, b: Path) -> bool:
    """``a`` and ``b`` are the same file: the same ``(st_dev, st_ino)`` when both exist (also
    through a link or a hard link; not on a file system without file indexes), else the same
    path after resolving links, compared without case (Windows and macOS file systems ignore
    case; on Linux this errs on the safe side). Blocking; never raises (a path with a NUL
    character is compared as written)."""
    return same_key(file_key(a), file_key(b))


def writable_file(path: Path) -> bool:
    """The existing file ``path`` can be opened for writing by this process: the same test as
    validation's :meth:`~reframe.validation.LocalFileSystem.writable_file` (``os.access`` on
    POSIX; on Windows the file is opened for update, which also sees the ACL and a file another
    process holds without write sharing). An in-place metadata edit checks it before
    mkvpropedit runs (decision 0034)."""
    return LocalFileSystem().writable_file(path)


def _path_key(path: str | os.PathLike[str]) -> str:
    """The path with its links resolved, in the OS's case, without case (blocking; never
    raises: see :attr:`FileKey.path`)."""
    return _resolved(path).casefold()


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
    ``keep`` (a job's source) is never removed, whatever spelling of it is in ``paths``.
    Never raises for a path that cannot be used (a NUL character)."""
    problems: list[str] = []
    for path in paths:
        if keep is not None and same_file(path, keep):
            problems.append(f"{path} is the source file, not removed")
            continue
        try:
            _retry(partial(path.unlink, missing_ok=True))
        except IsADirectoryError:
            problems.append(f"{path} is a folder, not removed")
        except OSError as exc:
            problems.append(f"{path} could not be removed: {exc.strerror or exc}")
        except ValueError as exc:  # a NUL character: no file can have this name
            problems.append(f"{os.fspath(path)!r} could not be removed: {exc}")
    return problems


def replace_file(source: Path, target: Path) -> None:
    """``os.replace``; on Windows a ``PermissionError`` (the target is open) is retried."""
    _retry(partial(os.replace, source, target))


def rename_no_replace(source: Path, target: Path) -> None:
    """Rename ``source`` to ``target``; ``FileExistsError`` when ``target`` exists."""
    if WINDOWS:
        _retry(partial(os.rename, source, target))
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
