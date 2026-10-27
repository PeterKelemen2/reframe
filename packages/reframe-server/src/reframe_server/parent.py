"""Stop the server when the process that started it ends (``--parent-pid``).

The watch runs on a daemon thread, so it also works while the event loop is blocked: when the
parent ends it asks the server to stop, and if the process still lives :data:`STOP_LIMIT`
seconds later it exits hard. A live ancestor is the parent for certain; any other process with
the pid must have started a clock tick before this one, or its pid was reused.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import itertools
import logging
import os
import select
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

__all__ = ["HARD_EXIT_CODE", "STOP_LIMIT", "Kernel32", "ParentWatch", "watch_parent"]

log = logging.getLogger(__name__)

STOP_LIMIT = 5.0
"""Seconds from the parent's end to the hard exit, when the server has not stopped by then."""

HARD_EXIT_CODE = 70
"""The exit code of the hard exit (``EX_SOFTWARE``)."""

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INFINITE = 0xFFFFFFFF


class Kernel32(Protocol):
    """The ``kernel32`` functions of the Windows watch (a ``ctypes.WinDLL`` or a test mock)."""

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> Any: ...
    def GetCurrentProcess(self) -> Any: ...
    def GetProcessTimes(
        self, process: Any, creation: Any, exit_time: Any, kernel: Any, user: Any
    ) -> Any: ...
    def WaitForSingleObject(self, handle: Any, milliseconds: int) -> int: ...
    def CloseHandle(self, handle: Any) -> Any: ...


def _load_kernel32() -> Kernel32:  # pragma: no cover - Windows only
    if sys.platform == "win32":
        from ctypes import wintypes

        filetime = ctypes.POINTER(ctypes.c_uint64)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = ()
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE, filetime, filetime, filetime, filetime)
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL
        return cast("Kernel32", k32)
    raise OSError("kernel32 exists only on Windows")


class ParentWatch:
    """A running watch of one parent process. :meth:`close` it when the server has stopped.

    ``wait`` blocks the watch thread until the parent ends; ``release`` then frees what it
    waited on.
    """

    def __init__(
        self,
        pid: int,
        wait: Callable[[], object],
        release: Callable[[], object],
        stop: Callable[[], None],
        loop: asyncio.AbstractEventLoop,
        limit: float,
        hard_exit: Callable[[int], object],
    ) -> None:
        self.pid = pid
        self._wait = wait
        self._release = release
        self._stop = stop
        self._loop = loop
        self._limit = limit
        self._hard_exit = hard_exit
        self._closed = threading.Event()
        threading.Thread(target=self._run, name=f"parent-watch-{pid}", daemon=True).start()

    def close(self) -> None:
        """Ignore the parent's end from now on. A hard exit already counting down still comes:
        the process has not ended yet."""
        self._closed.set()

    def _run(self) -> None:
        try:
            self._wait()
        finally:
            self._release()
        if self._closed.is_set():
            return
        log.warning("The parent process %d ended: the server stops", self.pid)
        with contextlib.suppress(RuntimeError):  # the loop is closed: the server has stopped
            self._loop.call_soon_threadsafe(self._stop)
        time.sleep(self._limit)
        log.error("The server did not stop within %g s after its parent ended", self._limit)
        self._hard_exit(HARD_EXIT_CODE)


def watch_parent(
    pid: int,
    stop: Callable[[], None],
    loop: asyncio.AbstractEventLoop,
    *,
    limit: float = STOP_LIMIT,
    hard_exit: Callable[[int], object] = os._exit,
    platform: str | None = None,
    kernel32: Kernel32 | None = None,
) -> ParentWatch | None:
    """Call ``stop`` on ``loop`` when the process ``pid`` ends, and ``hard_exit`` ``limit``
    seconds later. ``None``: no process with this pid started before this one."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        k32 = _load_kernel32() if kernel32 is None else kernel32
        handle = _open_windows(k32, pid)
        if handle is None:
            return None
        return ParentWatch(
            pid,
            lambda: k32.WaitForSingleObject(handle, INFINITE),
            lambda: k32.CloseHandle(handle),
            stop,
            loop,
            limit,
            hard_exit,
        )
    fd = _open_linux(pid)
    if fd is None:
        return None
    return ParentWatch(
        pid, lambda: _wait_readable(fd), lambda: os.close(fd), stop, loop, limit, hard_exit
    )


def _stat(pid: int | str) -> list[str]:
    """The fields of ``/proc/<pid>/stat`` after the name (``[0]`` is field 3)."""
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    # The name in parentheses may hold spaces and ")".
    return stat.rpartition(")")[2].split()


def _start_ticks(pid: int | str) -> int:
    return int(_stat(pid)[19])


def _parent_of(pid: int) -> int:
    return int(_stat(pid)[1])


def _is_ancestor(pid: int) -> bool:
    """``pid`` is a live ancestor of this process. A live ancestor has held its pid since before
    this process started, so a pidfd opened before this call is its."""
    chain = [os.getppid()]
    try:
        while chain[-1] != pid:
            if chain[-1] <= 1:
                return False
            chain.append(_parent_of(chain[-1]))
        # Read each link again, from this process up: a process that ended in between has
        # given its child a new parent, and a live child's parent is alive.
        return os.getppid() == chain[0] and all(
            _parent_of(child) == parent for child, parent in itertools.pairwise(chain)
        )
    except (FileNotFoundError, ProcessLookupError):  # a link ended while it was read
        return False


def _open_linux(pid: int) -> int | None:
    """A pidfd of the parent. It stays the parent's after the pid is reused."""
    pidfd_open: Callable[[int], int] = getattr(os, "pidfd_open")  # noqa: B009 - not on Windows
    try:
        fd = pidfd_open(pid)
    except ProcessLookupError:
        return None
    try:
        # Checked after the pidfd is open: if this is another process, the pidfd's one is gone.
        # A process in this one's start tick may have the parent's reused pid; an ancestor
        # often starts in the same tick (a fork through `timeout`), so it is checked exactly.
        if _is_ancestor(pid) or _start_ticks(pid) < _start_ticks("self"):
            return fd
    except (FileNotFoundError, ProcessLookupError):
        pass
    os.close(fd)
    return None


def _wait_readable(fd: int) -> None:
    select.select([fd], [], [])


def _created(k32: Kernel32, process: Any) -> int:
    times = [ctypes.c_uint64() for _ in range(4)]
    if not k32.GetProcessTimes(process, *(ctypes.pointer(t) for t in times)):
        raise OSError("GetProcessTimes failed")
    return times[0].value


def _open_windows(k32: Kernel32, pid: int) -> Any:
    """A handle of the parent: Windows does not reuse a pid while a handle is open."""
    handle = k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        if _created(k32, handle) <= _created(k32, k32.GetCurrentProcess()):
            return handle
    except BaseException:
        k32.CloseHandle(handle)
        raise
    k32.CloseHandle(handle)
    return None
