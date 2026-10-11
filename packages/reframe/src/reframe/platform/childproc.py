"""Child-process safety: FFmpeg must die when Reframe dies (C-1).

:func:`spawn_options` returns the extra ``subprocess`` / ``asyncio.create_subprocess_exec``
keyword arguments for a tool process, and :func:`after_spawn` must be called with the pid of
every new child. ``reframe.tools.run`` does both; nothing else starts processes.

Linux
    ``PR_SET_PDEATHSIG = SIGKILL`` through ``prctl(2)`` in ``preexec_fn``: the kernel kills the
    child when its parent dies, also when the parent is killed with ``SIGKILL``. If the parent
    died between ``fork()`` and the ``prctl`` call, the child sees a new parent pid and kills
    itself. Notes:

    - The death signal follows the parent **thread** that forked, not the process. asyncio
      forks from the thread that runs the event loop, so children die if that thread ends. A
      loop thread ends only when its loop is gone, and then nothing waits for the children.
    - The child also gets its own session (``start_new_session=True``): a Ctrl+C in the
      terminal reaches Reframe only, and Reframe stops its children itself (tree kill), so
      FFmpeg does not stop half-way through writing a file on its own.
    - ``libc`` is loaded before the fork; the child only makes two system calls.

Other POSIX systems
    Only ``start_new_session``. (Reframe ships for Linux and Windows.)

Windows
    A **Job Object** with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``: when the last handle to the
    job closes (Reframe exits or crashes), Windows kills every process in the job. Processes
    get ``CREATE_NO_WINDOW``, so no console window flashes.

    Assigning a child to the job *after* it started is racy: the child (for example the
    ``cmd.exe`` of a ``.cmd`` launcher) may start a grandchild before the assignment, and that
    grandchild is then outside the job. So Reframe puts **its own process** into the job, the
    first time it starts a tool: every child inherits the job at creation, with no window.
    The job also allows ``JOB_OBJECT_LIMIT_BREAKAWAY_OK``, so code that deliberately starts a
    process that must outlive Reframe can pass ``CREATE_BREAKAWAY_FROM_JOB`` (Reframe itself
    does not do this). The job handle is never closed: it closes when the process ends.

    Since Windows 8, a process can be in several (nested) jobs, so this works when Reframe
    already runs inside a job (Tauri puts the sidecar in its own job, CI runners use jobs). If
    the assignment fails anyway, Reframe falls back to assigning each child after it starts
    (:meth:`KillOnCloseJob.adopt`): racy for grandchildren, but better than nothing. The
    tree kill on timeout and cancel (psutil) does not depend on the job.

    This Windows code is unit-tested with a mocked ``kernel32`` on Linux; it has not been run
    on Windows yet.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import sys
import threading
from collections.abc import Callable
from typing import Any, Literal, Protocol

__all__ = [
    "CREATE_BREAKAWAY_FROM_JOB",
    "CREATE_NO_WINDOW",
    "JOB_OBJECT_LIMIT_BREAKAWAY_OK",
    "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
    "KillOnCloseJob",
    "after_spawn",
    "linux_preexec",
    "spawn_options",
    "windows_job",
]

# --------------------------------------------------------------------------- constants

PR_SET_PDEATHSIG = 1

CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9  # JobObjectExtendedLimitInformation
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


# --------------------------------------------------------------------------- Linux


def _load_prctl() -> Callable[..., int] | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl: Callable[..., int] = libc.prctl
    except (OSError, AttributeError):  # pragma: no cover - every Linux libc has prctl
        return None
    return prctl


_prctl: Callable[..., int] | None = None
_prctl_lock = threading.Lock()


def linux_preexec(
    parent_pid: int | None = None, *, prctl: Callable[..., int] | None = None
) -> Callable[[], None]:
    """Return a ``preexec_fn`` that sets ``PR_SET_PDEATHSIG = SIGKILL`` in the child.

    ``prctl`` is loaded here, in the parent, never in the forked child.
    """
    global _prctl
    if prctl is None:
        with _prctl_lock:
            if _prctl is None:
                _prctl = _load_prctl()
            prctl = _prctl
    expected_parent = os.getpid() if parent_pid is None else parent_pid
    bound = prctl
    sigkill = int(getattr(signal, "SIGKILL", 9))

    def preexec() -> None:  # runs in the child between fork() and exec()
        if bound is not None:
            bound(PR_SET_PDEATHSIG, sigkill, 0, 0, 0)
        if os.getppid() != expected_parent:
            # The parent died before prctl() took effect: do what the death signal would do.
            os.kill(os.getpid(), sigkill)

    return preexec


# --------------------------------------------------------------------------- Windows


class _IoCounters(ctypes.Structure):
    _fields_ = (
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    )


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    )


class JobObjectExtendedLimitInformation(ctypes.Structure):
    """``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` (winnt.h)."""

    _fields_ = (
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class Kernel32(Protocol):
    """The ``kernel32`` functions the job code calls (a ``ctypes.WinDLL`` or a test mock)."""

    def CreateJobObjectW(self, attributes: Any, name: Any) -> Any: ...
    def SetInformationJobObject(self, job: Any, info_class: int, info: Any, length: int) -> Any: ...
    def GetCurrentProcess(self) -> Any: ...
    def AssignProcessToJobObject(self, job: Any, process: Any) -> Any: ...
    def OpenProcess(self, access: int, inherit: bool, pid: int) -> Any: ...
    def CloseHandle(self, handle: Any) -> Any: ...


def _load_kernel32() -> Kernel32:  # pragma: no cover - Windows only
    if sys.platform == "win32":
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.GetCurrentProcess.argtypes = ()
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL
        result: Kernel32 = k32
        return result
    raise OSError("kernel32 exists only on Windows")


def _last_error() -> int:
    get = getattr(ctypes, "get_last_error", None)
    return int(get()) if get is not None else 0


JobMode = Literal["process", "per_child", "unavailable"]


class KillOnCloseJob:
    """A Windows Job Object with ``KILL_ON_JOB_CLOSE`` that holds Reframe and its children.

    :meth:`setup` creates the job and assigns the current process to it (``mode`` becomes
    ``"process"``). If that assignment fails, ``mode`` is ``"per_child"`` and :meth:`adopt`
    assigns each child after it started. If the job cannot be created at all, ``mode`` is
    ``"unavailable"`` and :attr:`error` says why.
    """

    def __init__(
        self,
        kernel32: Kernel32 | None = None,
        *,
        last_error: Callable[[], int] = _last_error,
    ) -> None:
        self._kernel32 = kernel32
        self._last_error = last_error
        self._lock = threading.Lock()
        self.handle: Any = None
        self.mode: JobMode | None = None
        self.error: str | None = None

    @property
    def kernel32(self) -> Kernel32:
        if self._kernel32 is None:  # pragma: no cover - Windows only
            self._kernel32 = _load_kernel32()
        return self._kernel32

    def setup(self) -> JobMode:
        """Create the job once (thread-safe) and return the mode."""
        with self._lock:
            if self.mode is not None:
                return self.mode
            k32 = self.kernel32
            job = k32.CreateJobObjectW(None, None)
            if not job:
                self.mode = "unavailable"
                self.error = f"CreateJobObjectW failed (error {self._last_error()})"
                return self.mode
            info = JobObjectExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
            )
            ok = k32.SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.pointer(info),
                ctypes.sizeof(info),
            )
            if not ok:
                self.error = f"SetInformationJobObject failed (error {self._last_error()})"
                k32.CloseHandle(job)
                self.mode = "unavailable"
                return self.mode
            # Keep the handle for the whole life of the process: closing it would kill the
            # job (and with mode "process", Reframe itself).
            self.handle = job
            if k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
                self.mode = "process"
            else:
                self.error = (
                    f"AssignProcessToJobObject(current process) failed "
                    f"(error {self._last_error()}); assigning each child after it starts"
                )
                self.mode = "per_child"
            return self.mode

    def adopt(self, pid: int) -> bool:
        """``per_child`` mode: put the child ``pid`` into the job. True if it is in the job.

        In ``process`` mode the child is already in the job (inherited): nothing to do.
        """
        mode = self.setup()
        if mode == "process":
            return True
        if mode != "per_child":
            return False
        k32 = self.kernel32
        process = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            return False
        try:
            return bool(k32.AssignProcessToJobObject(self.handle, process))
        finally:
            k32.CloseHandle(process)


_job: KillOnCloseJob | None = None
_job_lock = threading.Lock()


def windows_job() -> KillOnCloseJob:
    """The process-wide job (created and set up on first use)."""
    global _job
    with _job_lock:
        if _job is None:
            _job = KillOnCloseJob()
    _job.setup()
    return _job


# --------------------------------------------------------------------------- public API


def spawn_options(platform: str | None = None) -> dict[str, Any]:
    """Extra keyword arguments for ``asyncio.create_subprocess_exec`` / ``subprocess.Popen``."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        windows_job()  # Reframe joins the job before its first child starts
        return {"creationflags": CREATE_NO_WINDOW}
    options: dict[str, Any] = {"start_new_session": True}
    if platform.startswith("linux"):
        options["preexec_fn"] = linux_preexec()
    return options


def after_spawn(pid: int, platform: str | None = None) -> None:
    """Call with the pid of every new child (Windows ``per_child`` fallback; else a no-op)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        with contextlib.suppress(OSError):
            windows_job().adopt(pid)
