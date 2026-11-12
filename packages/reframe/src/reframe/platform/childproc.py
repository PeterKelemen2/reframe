"""Child-process safety: a tool process dies with Reframe, and a user-facing program does not.

:func:`spawn_options` gives the extra ``subprocess`` keyword arguments for a tool process, and
:func:`after_spawn` is called with the pid of every new child. ``reframe.tools.run`` does both.
On Windows every child is in Reframe's job, so a program that must outlive Reframe (a player,
the file manager) starts with :func:`launch_detached`.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import posixpath
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol, cast

__all__ = [
    "CREATE_BREAKAWAY_FROM_JOB",
    "CREATE_NO_WINDOW",
    "JOB_OBJECT_LIMIT_BREAKAWAY_OK",
    "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
    "KillOnCloseJob",
    "after_spawn",
    "launch_detached",
    "linux_preexec",
    "spawn_options",
    "user_environ",
    "windows_job",
]

PR_SET_PDEATHSIG = 1

CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9  # JobObjectExtendedLimitInformation
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


def _load_prctl() -> Callable[..., int] | None:
    """libc ``prctl``, or ``None`` where there is none (not Linux: ``CDLL(None)`` raises
    ``TypeError`` on Windows, and other libcs have no ``prctl``)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl: Callable[..., int] = libc.prctl
    except (OSError, AttributeError, TypeError, ValueError):  # pragma: no cover - not Linux
        return None
    return prctl


_prctl: Callable[..., int] | None = None
_prctl_lock = threading.Lock()


def linux_preexec(
    parent_pid: int | None = None, *, prctl: Callable[..., int] | None = None
) -> Callable[[], None]:
    """Return a ``preexec_fn`` that sets ``PR_SET_PDEATHSIG = SIGKILL`` in the child.

    ``prctl`` is loaded here, in the parent, never in the forked child. The death signal
    follows the thread that forked, not the process, so the fork must happen on a thread that
    lives as long as its children.
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
        return cast("Kernel32", k32)
    raise OSError("kernel32 exists only on Windows")


def _last_error() -> int:
    get = getattr(ctypes, "get_last_error", None)
    return int(get()) if get is not None else 0


JobMode = Literal["process", "per_child", "unavailable"]


class KillOnCloseJob:
    """A Windows Job Object with ``KILL_ON_JOB_CLOSE`` for Reframe and its children.

    Joining before the first child starts (``mode == "process"``) is the race-free way: a child
    assigned later may already have started a grandchild, which then stays outside the job. If
    Reframe cannot join (an older Windows without nested jobs), ``mode`` is ``"per_child"`` and
    :meth:`adopt` assigns each child after it starts. ``"unavailable"`` means the job could not
    be created at all; :attr:`error` says why.
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


def spawn_options(platform: str | None = None, *, user_facing: bool = False) -> dict[str, Any]:
    """Extra keyword arguments for ``asyncio.create_subprocess_exec`` / ``subprocess.Popen``.

    ``user_facing=True`` is for a program that the user sees and that must outlive Reframe: on
    Windows it breaks away from the job, on POSIX it gets no death signal.
    """
    platform = sys.platform if platform is None else platform
    if user_facing:
        if platform == "win32":
            return {"creationflags": CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}
    if platform == "win32":
        windows_job()  # Reframe joins the job before its first child starts
        return {"creationflags": CREATE_NO_WINDOW}
    options: dict[str, Any] = {"start_new_session": True}
    if platform.startswith("linux"):
        options["preexec_fn"] = linux_preexec()
    return options


def user_environ(
    environ: Mapping[str, str] | None = None,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    """The environment for a program that Reframe starts: the user's, without what the
    launchers of a frozen Linux app added for Reframe itself.

    PyInstaller's bootloader puts its own library folder (with its libstdc++) first in
    ``LD_LIBRARY_PATH`` and keeps the value it found in ``LD_LIBRARY_PATH_ORIG`` (none: the
    variable was unset). Inside an AppImage, AppRun and its hooks point ``LD_LIBRARY_PATH``,
    ``PATH``, ``PYTHONHOME``, the GTK and GIO variables and more into the image (``APPDIR``):
    every entry under ``APPDIR`` is dropped. A system library or VA driver loaded by a tool
    would otherwise get the app's copies of the libraries it links.
    """
    env = dict(os.environ if environ is None else environ)
    platform = sys.platform if platform is None else platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen or not platform.startswith("linux"):
        return env
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    appdir = env.get("APPDIR", "").rstrip("/")
    exe = posixpath.abspath(executable or sys.executable)
    if not appdir.startswith("/") or not exe.startswith(appdir + "/"):
        return env
    for name, value in list(env.items()):
        entries = value.split(":")
        kept = [e for e in entries if e != appdir and not e.startswith(appdir + "/")]
        if len(kept) == len(entries):
            continue
        # An empty entry in a search path means the current folder.
        kept = [e for e in kept if e]
        if kept:
            env[name] = ":".join(kept)
        else:
            del env[name]
    return env


def after_spawn(pid: int, platform: str | None = None) -> None:
    """Call with the pid of every new child (Windows ``per_child`` fallback; else a no-op)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        with contextlib.suppress(OSError):
            windows_job().adopt(pid)


def launch_detached(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    platform: str | None = None,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> int:
    """Start a user-facing program that must outlive Reframe; return its pid.

    This is the one exception to "every subprocess goes through reframe.tools.run": the program
    is not a tool, it has no timeout and it is not waited for. It must survive Reframe's exit,
    see :func:`spawn_options`. Its stdio is the null device. A daemon thread reaps it when it
    exits. Raises ``OSError`` if it cannot be started.
    """
    platform = sys.platform if platform is None else platform
    options = spawn_options(platform, user_facing=True)
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": cwd,
        "close_fds": True,
        "env": user_environ(platform=platform),
        **options,
    }
    try:
        proc = popen(list(argv), **kwargs)
    except PermissionError:
        if platform != "win32":
            raise
        # An outer job that does not allow breakaway (ERROR_ACCESS_DENIED): start it inside.
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
        proc = popen(list(argv), **kwargs)
    threading.Thread(target=proc.wait, name=f"reap-{proc.pid}", daemon=True).start()
    return proc.pid
