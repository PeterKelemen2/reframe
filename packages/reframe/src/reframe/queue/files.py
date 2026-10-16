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
"""

from __future__ import annotations

import contextlib
import errno
import os
import time
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path

from reframe.models.plan import PlanFile
from reframe.validation.fs import LocalFileSystem

__all__ = [
    "ATTEMPTS",
    "DELAY",
    "remove_files",
    "rename_no_replace",
    "replace_file",
    "same_file",
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


def same_file(a: Path, b: Path) -> bool:
    """``a`` and ``b`` are the same file: ``os.path.samefile`` when both exist (also through
    a link or a hard link), else the same path after resolving links, compared without case
    (Windows and macOS file systems ignore case; on Linux this errs on the safe side)."""
    try:
        if os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return _path_key(a) == _path_key(b)


def writable_file(path: Path) -> bool:
    """The existing file ``path`` can be opened for writing by this process: the same test as
    validation's :meth:`~reframe.validation.LocalFileSystem.writable_file` (``os.access`` on
    POSIX; on Windows the file is opened for update, which also sees the ACL and a file another
    process holds without write sharing). An in-place metadata edit checks it before
    mkvpropedit runs (decision 0034)."""
    return LocalFileSystem().writable_file(path)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path)).casefold()


def remove_files(paths: Iterable[Path], *, keep: Path | None = None) -> list[str]:
    """Remove each file that exists; returns a message for each one that could not be removed.
    ``keep`` (a job's source) is never removed, whatever spelling of it is in ``paths``."""
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
