"""The queue store's owner lock (decision 0027): ``<data dir>/queue.lock``.

One Reframe process owns the saved queue: it holds an exclusive OS lock on ``queue.lock``
from the queue's first use until ``close()``. The OS frees the lock when the process ends,
also after a crash or ``kill -9``, so it is never stale. The file holds the owner's pid, for
messages only. Another process that tries gets "busy" and the pid.

- POSIX: ``fcntl.flock(LOCK_EX | LOCK_NB)`` on the file. A lock of another open file
  description conflicts, also in the same process (two ``QueueService`` objects in one test
  behave like two processes).
- Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` on one byte at :data:`WINDOWS_LOCK_OFFSET`, far
  beyond the pid text: Windows locks are mandatory, so a locked byte cannot be read by
  another process, and the pid must stay readable. Tested with a mocked ``msvcrt`` on Linux.

The descriptor is not inherited by child processes (Python's default, PEP 446), so an FFmpeg
started by the queue cannot keep the lock after Reframe ends.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "LOCK_FILE",
    "WINDOWS_LOCK_OFFSET",
    "FlockBackend",
    "LockBackend",
    "LockResult",
    "MsvcrtBackend",
    "StoreLock",
    "default_backend",
]

LOCK_FILE = "queue.lock"
#: The byte that the Windows backend locks (1 GiB: beyond any pid text).
WINDOWS_LOCK_OFFSET = 1 << 30
#: ``msvcrt.locking`` errors that mean "another process holds it".
_BUSY = {errno.EACCES, errno.EDEADLK, errno.EAGAIN}


class LockBackend(Protocol):
    def try_lock(self, fd: int) -> bool:
        """Take the lock without waiting; ``False`` when another holder has it."""
        ...

    def unlock(self, fd: int) -> None: ...


def _load_fcntl() -> Any:
    if sys.platform != "win32":
        import fcntl

        return fcntl
    raise OSError("fcntl exists only on POSIX")  # pragma: no cover - Windows only


class FlockBackend:
    """POSIX ``flock``."""

    def try_lock(self, fd: int) -> bool:
        fcntl = _load_fcntl()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(self, fd: int) -> None:
        fcntl = _load_fcntl()
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


def _load_msvcrt() -> Any:  # pragma: no cover - Windows only
    if sys.platform == "win32":
        import msvcrt

        return msvcrt
    raise OSError("msvcrt exists only on Windows")


class MsvcrtBackend:
    """Windows ``msvcrt.locking`` on one byte at :data:`WINDOWS_LOCK_OFFSET` (``msvcrt`` can
    be a test double)."""

    def __init__(self, msvcrt: Any | None = None) -> None:
        self._msvcrt = msvcrt

    @property
    def msvcrt(self) -> Any:
        if self._msvcrt is None:  # pragma: no cover - Windows only
            self._msvcrt = _load_msvcrt()
        return self._msvcrt

    def try_lock(self, fd: int) -> bool:
        os.lseek(fd, WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        try:
            self.msvcrt.locking(fd, self.msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in _BUSY:
                return False
            raise
        return True

    def unlock(self, fd: int) -> None:
        os.lseek(fd, WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        with contextlib.suppress(OSError):
            self.msvcrt.locking(fd, self.msvcrt.LK_UNLCK, 1)


def default_backend(platform: str | None = None) -> LockBackend:
    platform = sys.platform if platform is None else platform
    return MsvcrtBackend() if platform == "win32" else FlockBackend()


@dataclass(frozen=True, slots=True)
class LockResult:
    owned: bool
    """This process holds the lock now."""
    owner: int | None
    """The owner's pid (``None`` when the file does not say yet)."""


def _read_pid(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 64).decode("ascii", errors="replace").strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


class StoreLock:
    """The exclusive lock of one data folder's queue store (see the module doc)."""

    def __init__(self, path: Path, backend: LockBackend | None = None) -> None:
        self.path = path
        self._backend = backend or default_backend()
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> LockResult:
        """Take the lock without waiting. ``OSError`` when the file cannot be made or opened
        (the data folder is not writable)."""
        if self._fd is not None:
            return LockResult(True, os.getpid())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if not self._backend.try_lock(fd):
                owner = _read_pid(fd)
                os.close(fd)
                return LockResult(False, owner)
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        self._fd = fd
        return LockResult(True, os.getpid())

    def release(self) -> None:
        """Free the lock (the file stays: removing it could race with a new owner)."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        self._backend.unlock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
