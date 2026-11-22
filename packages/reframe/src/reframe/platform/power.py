"""Power actions: shut down, sleep or quit after a cancellable countdown.

:class:`PowerService` runs the countdown and publishes
:class:`~reframe.models.PowerCountdownEvent` events. Once ``executing`` is published the action
runs to its end and nothing cancels it. A failure is data (one ``app.warning``), never an
exception. Exactly two functions reach the operating system, :func:`_run_command` and
:func:`_load_win32`; both refuse while :func:`refusal` says so, and the shared pytest plugin
replaces both, so no test can shut down or suspend the machine that runs it.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import math
import ntpath
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from reframe import tools
from reframe.events import EventBus
from reframe.models.events import AppWarningEvent, PowerAction, PowerCountdownEvent
from reframe.tools import RunResult

__all__ = [
    "COMMAND_TIMEOUT",
    "COUNTDOWN_SECONDS",
    "DRY_RUN_ENV",
    "EXECUTE_WAIT",
    "SYSTEMCTL_VERBS",
    "WARNING_CODE",
    "WINDOWS_SHUTDOWN_COMMENT",
    "WINDOWS_SHUTDOWN_DELAY",
    "CommandRunner",
    "OsAction",
    "PowerExecutor",
    "PowerService",
    "SystemctlExecutor",
    "UnsupportedExecutor",
    "Win32Libraries",
    "WindowsExecutor",
    "create_power_service",
    "default_executor",
    "refusal",
    "systemctl_argv",
    "windows_shutdown_argv",
]

log = logging.getLogger(__name__)

#: The countdown before every power action.
COUNTDOWN_SECONDS = 60.0

#: The actions the operating system runs; ``quit`` is not one of them.
OsAction = Literal["shutdown", "sleep"]

#: The ``app.warning`` code of a power action that did not run.
WARNING_CODE = "power.failed"

#: Seconds a power command (``systemctl``, ``shutdown.exe``) may take: both only queue the
#: action and return.
COMMAND_TIMEOUT = 30.0

#: When set to a true value, no power action reaches the operating system: it fails with a
#: reason instead.
DRY_RUN_ENV = "REFRAME_POWER_DRY_RUN"

#: ``systemctl`` verbs per action.
SYSTEMCTL_VERBS: dict[OsAction, str] = {"shutdown": "poweroff", "sleep": "suspend"}

#: The ``/t`` of ``shutdown /s``: Windows shows its own warning for this long after Reframe's
#: countdown.
WINDOWS_SHUTDOWN_DELAY = 60

#: The ``/c`` comment that Windows shows in its shutdown warning.
WINDOWS_SHUTDOWN_COMMENT = "Reframe: the queue is done. Run 'shutdown /a' to cancel."

#: Seconds :meth:`PowerService.close` waits for an action that is ``executing`` (it is never
#: cancelled): the command time-out plus a margin.
EXECUTE_WAIT = COMMAND_TIMEOUT + 5.0

_FAILED_MESSAGE: dict[OsAction, str] = {
    "shutdown": "Reframe could not shut down the computer.",
    "sleep": "Reframe could not put the computer to sleep.",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def refusal() -> str | None:
    """Why no power action may reach the operating system in this process, else ``None``.

    Under pytest (``PYTEST_CURRENT_TEST`` is set while a test runs) and with
    ``REFRAME_POWER_DRY_RUN`` set. Checked by the two functions that reach the operating
    system, whatever executor called them.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "refused: a test is running (PYTEST_CURRENT_TEST is set)"
    if os.environ.get(DRY_RUN_ENV, "").strip().lower() not in ("", "0", "false", "no"):
        return f"refused: {DRY_RUN_ENV} is set (dry run)"
    return None


async def _run_command(argv: Sequence[str]) -> RunResult:
    """**The only place a power command process starts** (``systemctl``, ``shutdown.exe``).

    The shared pytest plugin replaces this function with one that fails the test.
    """
    reason = refusal()
    if reason is not None:
        log.warning("power command not run: %s: %s", reason, " ".join(argv))
        return RunResult(
            returncode=None, stdout=b"", stderr=b"", duration=0.0, error=reason, argv=tuple(argv)
        )
    return await tools.run(argv, timeout=COMMAND_TIMEOUT)


#: Runs one power command (``_run_command`` or a test fake).
CommandRunner = Callable[[Sequence[str]], Awaitable[RunResult]]


def _describe_failure(name: str, result: RunResult) -> str | None:
    """``None`` when ``result`` is a success, else why the command failed."""
    if result.error is not None:
        return f"{name} could not be started: {result.error}"
    if result.timed_out:
        return f"{name} did not finish within {COMMAND_TIMEOUT:g} s"
    if result.cancelled:
        return f"{name} was cancelled"
    if result.returncode == 0:
        return None
    lines = [
        line.strip()
        for line in (result.stderr_text + "\n" + result.stdout_text).splitlines()
        if line.strip()
    ]
    message = f": {lines[0]}" if lines else ""
    return f"{name} failed (exit code {result.returncode}){message}"


class PowerExecutor(Protocol):
    """Runs a power action of the operating system."""

    async def execute(self, action: OsAction) -> str | None:
        """Run ``action``. ``None`` when the OS accepted it, else why not (data, never an
        exception)."""
        ...


def systemctl_argv(action: OsAction, systemctl: str = "systemctl") -> list[str]:
    """``systemctl --no-ask-password`` with the verb of ``action``: never a password prompt
    (a polkit agent dialog nobody answers would keep the machine on; it fails instead)."""
    return [systemctl, "--no-ask-password", SYSTEMCTL_VERBS[action]]


class SystemctlExecutor:
    """Linux: ``systemctl poweroff`` and ``systemctl suspend``."""

    def __init__(self, *, run: CommandRunner | None = None, systemctl: str = "systemctl") -> None:
        self._run = run
        self._systemctl = systemctl

    async def execute(self, action: OsAction) -> str | None:
        argv = systemctl_argv(action, self._systemctl)
        # Looked up at call time, so the pytest plugin's replacement always applies.
        run = self._run if self._run is not None else _run_command
        result = await run(argv)
        return _describe_failure(f"systemctl {SYSTEMCTL_VERBS[action]}", result)


def _shutdown_exe() -> str:
    root = os.environ.get("SYSTEMROOT") or "C:\\Windows"  # Windows keys are case-insensitive
    # An absolute path: a bare name could find a shutdown.exe in the current directory.
    return ntpath.join(root, "System32", "shutdown.exe")


def windows_shutdown_argv(shutdown_exe: str | None = None) -> list[str]:
    """``shutdown.exe /s`` with :data:`WINDOWS_SHUTDOWN_DELAY` and
    :data:`WINDOWS_SHUTDOWN_COMMENT`."""
    exe = _shutdown_exe() if shutdown_exe is None else shutdown_exe
    return [exe, "/s", "/t", str(WINDOWS_SHUTDOWN_DELAY), "/c", WINDOWS_SHUTDOWN_COMMENT]


# Windows constants (winnt.h, winerror.h).
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
SE_SHUTDOWN_NAME = "SeShutdownPrivilege"
ERROR_NOT_ALL_ASSIGNED = 1300


class _LUID(ctypes.Structure):
    _fields_ = (("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32))


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = (("Luid", _LUID), ("Attributes", ctypes.c_uint32))


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = (("PrivilegeCount", ctypes.c_uint32), ("Privileges", _LUID_AND_ATTRIBUTES * 1))


class PowrProf(Protocol):
    """The ``powrprof`` function used (a ``ctypes.WinDLL`` or a test mock)."""

    def SetSuspendState(
        self, hibernate: bool, force: bool, wakeup_events_disabled: bool
    ) -> int: ...


class Advapi32(Protocol):
    """The ``advapi32`` functions used to enable ``SeShutdownPrivilege``."""

    def OpenProcessToken(self, process: Any, access: int, token: Any) -> int: ...
    def LookupPrivilegeValueW(self, system: str | None, name: str, luid: Any) -> int: ...
    def AdjustTokenPrivileges(
        self,
        token: Any,
        disable_all: bool,
        new_state: Any,
        length: int,
        previous_state: Any,
        return_length: Any,
    ) -> int: ...


class Kernel32(Protocol):
    """The ``kernel32`` functions used."""

    def GetCurrentProcess(self) -> Any: ...
    def CloseHandle(self, handle: Any) -> int: ...


@dataclass(frozen=True, slots=True)
class Win32Libraries:
    """The Windows DLLs the sleep action calls, and ``GetLastError`` of the calling thread."""

    powrprof: PowrProf
    advapi32: Advapi32
    kernel32: Kernel32
    last_error: Callable[[], int]


def _load_win32() -> Win32Libraries:
    """**The only way to the Windows power DLLs.** Raises ``OSError`` (refused, not Windows,
    a missing DLL). The shared pytest plugin replaces this function with one that fails the
    test."""
    reason = refusal()
    if reason is not None:
        raise OSError(reason)
    if sys.platform == "win32":  # pragma: no cover - Windows only
        from ctypes import wintypes

        powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
        powrprof.SetSuspendState.argtypes = (wintypes.BOOLEAN, wintypes.BOOLEAN, wintypes.BOOLEAN)
        powrprof.SetSuspendState.restype = wintypes.BOOLEAN
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.LookupPrivilegeValueW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(_LUID),
        )
        advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
        advapi32.AdjustTokenPrivileges.argtypes = (
            wintypes.HANDLE,
            wintypes.BOOL,
            ctypes.POINTER(_TOKEN_PRIVILEGES),
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        return Win32Libraries(
            powrprof=cast("PowrProf", powrprof),
            advapi32=cast("Advapi32", advapi32),
            kernel32=cast("Kernel32", kernel32),
            last_error=ctypes.get_last_error,
        )
    raise OSError("powrprof exists only on Windows")


def _enable_shutdown_privilege(libs: Win32Libraries) -> str | None:
    """Enable ``SeShutdownPrivilege`` in this process's token (``SetSuspendState`` needs it:
    "The calling process must have the SE_SHUTDOWN_NAME privilege")."""
    token = ctypes.c_void_p()
    if not libs.advapi32.OpenProcessToken(
        libs.kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return f"OpenProcessToken failed (error {libs.last_error()})"
    try:
        privileges = _TOKEN_PRIVILEGES()
        privileges.PrivilegeCount = 1
        privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        if not libs.advapi32.LookupPrivilegeValueW(
            None, SE_SHUTDOWN_NAME, ctypes.byref(privileges.Privileges[0].Luid)
        ):
            return f"LookupPrivilegeValueW({SE_SHUTDOWN_NAME}) failed (error {libs.last_error()})"
        if not libs.advapi32.AdjustTokenPrivileges(
            token, False, ctypes.byref(privileges), 0, None, None
        ):
            return f"AdjustTokenPrivileges failed (error {libs.last_error()})"
        # Success may still mean "not all assigned": the account lacks the privilege.
        if libs.last_error() == ERROR_NOT_ALL_ASSIGNED:
            return f"this account does not hold {SE_SHUTDOWN_NAME}"
        return None
    finally:
        libs.kernel32.CloseHandle(token)


def _suspend(libs: Win32Libraries) -> str | None:
    """Enable the privilege, then ``SetSuspendState(FALSE, FALSE, FALSE)``: sleep (not
    hibernate), ``bForce`` has no effect, wake events stay enabled. Blocking."""
    problem = _enable_shutdown_privilege(libs)
    if problem is not None:
        return problem
    if not libs.powrprof.SetSuspendState(False, False, False):
        return f"SetSuspendState failed (error {libs.last_error()})"
    return None


class WindowsExecutor:
    """Windows: ``shutdown.exe /s`` and ``SetSuspendState``."""

    def __init__(
        self,
        *,
        run: CommandRunner | None = None,
        libraries: Callable[[], Win32Libraries] | None = None,
        shutdown_exe: str | None = None,
    ) -> None:
        self._run = run
        self._libraries = libraries
        self._shutdown_exe = shutdown_exe

    async def execute(self, action: OsAction) -> str | None:
        if action == "shutdown":
            run = self._run if self._run is not None else _run_command
            result = await run(windows_shutdown_argv(self._shutdown_exe))
            return _describe_failure("shutdown /s", result)
        load = self._libraries if self._libraries is not None else _load_win32
        try:
            libs = load()
        except OSError as exc:
            return f"powrprof not available: {exc}"
        try:
            # SetSuspendState blocks (until the system wakes again): a worker thread.
            return await asyncio.to_thread(_suspend, libs)
        except Exception as exc:  # a broken binding (ctypes.ArgumentError, OSError)
            return f"SetSuspendState failed: {type(exc).__name__}: {exc}"


class UnsupportedExecutor:
    """A platform without power actions: every action fails with ``reason``."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def execute(self, action: OsAction) -> str | None:
        return self.reason


def default_executor(platform: str | None = None) -> PowerExecutor:
    """The executor of ``platform`` (default: this one)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return WindowsExecutor()
    if platform.startswith("linux"):
        return SystemctlExecutor()
    return UnsupportedExecutor(f"power actions are not supported on {platform!r}")


@dataclass(slots=True, eq=False)
class _Countdown:
    id: str
    action: PowerAction
    reason: str
    length: float
    deadline: datetime
    last: PowerCountdownEvent | None = None
    task: asyncio.Task[None] | None = None
    """The countdown (cancelled by ``cancel`` and ``close``)."""
    over: bool = field(default=False)
    """Cancelled, or ``executing`` was published."""


class PowerService:
    """The when-done power actions with their countdown (``power.countdown`` events).

    Once ``executing`` is published the action runs to its end: nothing cancels it, and
    :attr:`pending` stays that ``executing`` event until the executor returns.

    Call it from the thread of its event loop. ``sleep`` (keyword-only, for tests) is the
    one-second wait between ticks; ``now`` gives the wall clock of ``deadline``;
    ``execute_wait`` bounds how long :meth:`close` waits for an executing action.
    """

    def __init__(
        self,
        events: EventBus,
        *,
        executor: PowerExecutor | None = None,
        countdown: float = COUNTDOWN_SECONDS,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        now: Callable[[], datetime] = _utcnow,
        execute_wait: float = EXECUTE_WAIT,
    ) -> None:
        if not math.isfinite(countdown) or countdown < 0:
            raise ValueError(f"countdown must be a finite number >= 0, not {countdown!r}")
        self._events = events
        self._executor = executor
        self._countdown = countdown
        self._sleep = sleep
        self._now = now
        self._execute_wait = execute_wait
        self._current: _Countdown | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        """Countdown tasks (never one that runs an action)."""
        self._actions: dict[asyncio.Task[None], _Countdown] = {}
        """Actions that run through the executor (``executing``), in start order."""
        self._closed = False

    @property
    def executor(self) -> PowerExecutor:
        """The executor the actions run through (``None`` given: :func:`default_executor`)."""
        return self._executor if self._executor is not None else default_executor()

    def schedule(self, action: PowerAction, *, reason: str = "") -> str:
        """Start the countdown for ``action`` and return its id at once. Events
        (:class:`~reframe.models.PowerCountdownEvent`): ``started``, a ``tick`` every second,
        then ``cancelled`` or ``executing``; ``shutdown`` and ``sleep`` then run through the
        executor (a failure is an ``app.warning``). A running countdown is cancelled first;
        an action that is already executing is not touched (it runs to its end) and the new
        countdown starts beside it.

        Needs a running event loop (``RuntimeError`` otherwise: a programming error). After
        :meth:`close` nothing starts: the id gets one ``cancelled`` event.
        """
        loop = asyncio.get_running_loop()
        countdown = _Countdown(
            id=uuid.uuid4().hex,
            action=action,
            reason=reason,
            length=self._countdown,
            deadline=self._now() + timedelta(seconds=self._countdown),
        )
        whole = math.ceil(self._countdown)
        if self._closed:
            log.info("power action %s not scheduled: the service is closed", action)
            countdown.over = True
            self._publish(countdown, "cancelled", whole)
            return countdown.id
        self.cancel()
        log.info(
            "power action %s in %g s (countdown %s)%s",
            action,
            self._countdown,
            countdown.id,
            f": {reason}" if reason else "",
        )
        self._current = countdown
        self._publish(countdown, "started", whole)
        task = loop.create_task(self._run(countdown), name=f"reframe-power-{countdown.id}")
        countdown.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return countdown.id

    def cancel(self, countdown_id: str | None = None) -> bool:
        """Cancel the running countdown (``None``: whichever runs). ``True`` when one was
        cancelled; the action never runs then. ``False`` when none runs, the id is not the
        running one, or the action is already ``executing``."""
        countdown = self._current
        if countdown is None or (countdown_id is not None and countdown_id != countdown.id):
            return False
        self._current = None
        countdown.over = True
        if countdown.task is not None:
            countdown.task.cancel()
        left = countdown.last.seconds_left if countdown.last is not None else 0
        self._publish(countdown, "cancelled", left)
        log.info("power action %s cancelled (countdown %s)", countdown.action, countdown.id)
        return True

    @property
    def pending(self) -> PowerCountdownEvent | None:
        """The last event of the running countdown; else the ``executing`` event of an
        action that the executor still runs (the latest one); ``None`` when neither runs.
        ``pending.phase == "executing"``: the action is running and can no longer be
        cancelled."""
        countdown = self._current
        if countdown is not None:
            return countdown.last
        for task, executing in reversed(self._actions.items()):
            if not task.done():
                return executing.last
        return None

    async def close(self) -> None:
        """Cancel a running countdown (its action never runs). An action that is already
        executing is never cancelled: ``close`` waits for it, at most ``execute_wait``
        seconds (then it logs and returns; the action goes on). Safe to call more than
        once."""
        self._closed = True
        self.cancel()
        countdowns = list(self._tasks)
        for task in countdowns:
            task.cancel()
        if countdowns:
            await asyncio.gather(*countdowns, return_exceptions=True)
        actions = [task for task in self._actions if not task.done()]
        if not actions:
            return
        log.info("power: waiting for %d running action(s) before closing", len(actions))
        # asyncio.wait never cancels what it waits for, also when close() is cancelled.
        _, running = await asyncio.wait(actions, timeout=self._execute_wait)
        if running:
            log.warning(
                "power: %d action(s) still running after %g s; not cancelled",
                len(running),
                self._execute_wait,
            )

    def _publish(
        self,
        countdown: _Countdown,
        phase: Literal["started", "tick", "cancelled", "executing"],
        seconds_left: int,
    ) -> PowerCountdownEvent:
        event = PowerCountdownEvent(
            countdown_id=countdown.id,
            action=countdown.action,
            phase=phase,
            seconds_left=seconds_left,
            deadline=countdown.deadline,
        )
        countdown.last = event
        self._events.publish(event)
        return event

    async def _run(self, countdown: _Countdown) -> None:
        # Ticks, not wall-clock time: the first step lands on a whole second, then one second
        # each.
        remaining = countdown.length
        while remaining > 0:
            step = remaining - (math.ceil(remaining) - 1)
            await self._sleep(step)
            remaining = max(0.0, remaining - step)
            if countdown.over:  # pragma: no cover - cancel() also cancels this task
                return
            if remaining > 0:
                self._publish(countdown, "tick", math.ceil(remaining))
        if countdown.over or self._current is not countdown:  # pragma: no cover - as above
            return
        self._current = None
        countdown.over = True
        action = countdown.action
        if action == "quit":
            self._publish(countdown, "executing", 0)
            log.info(
                "power action quit: only the executing event is published (countdown %s)",
                countdown.id,
            )
            return
        # The action runs in its own task, which close() never cancels; registered in the
        # same step as `executing`, so `pending` never shows a gap.
        task = asyncio.get_running_loop().create_task(
            self._execute(countdown, action), name=f"reframe-power-action-{countdown.id}"
        )
        self._actions[task] = countdown
        task.add_done_callback(self._action_done)
        self._publish(countdown, "executing", 0)

    def _action_done(self, task: asyncio.Task[None]) -> None:
        self._actions.pop(task, None)

    async def _execute(self, countdown: _Countdown, action: OsAction) -> None:
        log.info("power action %s: running (countdown %s)", action, countdown.id)
        try:
            detail = await self.executor.execute(action)
        except Exception as exc:  # an executor must return data; a bug still must not escape
            log.exception("power executor failed")
            detail = f"{type(exc).__name__}: {exc}"
        if detail is None:
            log.info("power action %s accepted by the operating system", action)
            return
        log.warning("power action %s failed: %s", action, detail)
        self._events.publish(
            AppWarningEvent(
                code=WARNING_CODE,
                message=_FAILED_MESSAGE[action],
                detail=f"{detail} (when done: {countdown.reason})" if countdown.reason else detail,
            )
        )


def create_power_service(events: EventBus, *, platform: str | None = None) -> PowerService:
    """The service with the executor of this operating system (or of ``platform``)."""
    return PowerService(events, executor=default_executor(platform))
