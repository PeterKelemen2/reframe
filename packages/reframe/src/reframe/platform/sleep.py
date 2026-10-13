"""Sleep inhibit while the queue runs (C-14, 03 §Queue; decision record 0011).

:class:`SleepInhibitor` is a counted lock: the first :meth:`~SleepInhibitor.acquire` takes
the operating-system lock, the last :meth:`~SleepInhibitor.release` frees it, and
:meth:`~SleepInhibitor.close` frees it whatever the count. :func:`create_sleep_inhibitor`
picks the backends for the platform:

Linux
    1. **logind** ``org.freedesktop.login1.Manager.Inhibit(what, who, why, mode)`` on the
       system bus, through the small stdlib client in :mod:`reframe.platform.dbus`. It
       returns a file descriptor; the lock lasts while the descriptor (and every duplicate)
       is open. The descriptor is close-on-exec, so no child keeps the lock alive.
    2. **systemd-inhibit** as a long-running child through
       :func:`reframe.tools.run_streaming` (``sh -c 'echo ready && exec sleep infinity'``
       under ``systemd-inhibit``); the lock is taken when ``ready`` arrives and freed when
       the process tree is killed on release. ``--no-ask-password``: never a password prompt.

    ``what = "sleep:idle"``, ``mode = "block"`` (see :data:`WHAT` and :data:`MODE`).

Windows
    ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`` while held,
    ``SetThreadExecutionState(ES_CONTINUOUS)`` on release
    (https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).
    The execution state belongs to the **calling thread**, so both calls run on one
    dedicated thread that lives exactly as long as the lock is held (never on an asyncio
    worker thread, which may end or be reused). This code is unit-tested with a mocked
    ``kernel32`` on Linux; it has not been run on Windows yet.

When no backend works, the inhibitor publishes one ``app.warning`` event (code
``sleep_inhibit.unavailable``) and goes on: :attr:`~SleepInhibitor.state` is
``unavailable`` and the queue runs anyway. Expected failures (no bus, access denied, no
``systemd-inhibit``) never raise.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import ctypes
import logging
import os
import queue
import shutil
import sys
import threading
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Protocol, cast

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.platform import dbus
from reframe.tools.runner import CancelToken, RunResult, run_streaming

__all__ = [
    "ES_CONTINUOUS",
    "ES_SYSTEM_REQUIRED",
    "MODE",
    "WARNING_CODE",
    "WHAT",
    "WHO",
    "InhibitBackend",
    "InhibitState",
    "LogindBackend",
    "LostCallback",
    "SleepInhibitor",
    "SystemdInhibitBackend",
    "WindowsExecutionStateBackend",
    "create_sleep_inhibitor",
    "default_backends",
]

log = logging.getLogger(__name__)

WHO = "Reframe"
WHAT = "sleep:idle"
"""``sleep`` blocks suspend and hibernate (logind refuses ``Suspend()`` while the lock is
held: ``CanSuspend`` returns ``inhibited``). ``idle`` stops logind's automatic idle action
(``IdleAction=`` in logind.conf, which can also be ``poweroff``), the closest match of
Windows' ``ES_SYSTEM_REQUIRED`` ("resets the system idle timer"). Neither stops the screen
from turning off or locking (checked on KDE Plasma: its PolicyAgent shows no inhibition).
``shutdown`` is not inhibited: the user may still shut down."""
MODE = "block"
"""``delay`` gives only a few seconds (``InhibitDelayMaxSec``, default 5 s). ``block-weak``
is not enforced for the lock owner's own user, so the desktop's automatic suspend (same
user) would still interrupt the encode, and it needs systemd 257 or newer."""
WARNING_CODE = "sleep_inhibit.unavailable"

LOGIND_DESTINATION = "org.freedesktop.login1"
LOGIND_PATH = "/org/freedesktop/login1"
LOGIND_INTERFACE = "org.freedesktop.login1.Manager"

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

#: The cleanup of a cancelled acquire runs as a task: keep a reference until it is done.
_background: set[asyncio.Task[None]] = set()


class InhibitState(StrEnum):
    INACTIVE = "inactive"
    """Not held (and the last attempt, if any, did not fail)."""
    ACTIVE = "active"
    """The operating-system lock is held."""
    UNAVAILABLE = "unavailable"
    """The last attempt to take the lock failed (or the lock was lost); the queue runs on."""


#: Called by a backend when the lock it holds goes away on its own (with the reason).
LostCallback = Callable[[str], None]


class InhibitBackend(Protocol):
    """One way to take the operating-system lock."""

    @property
    def name(self) -> str: ...

    async def hold(self, why: str, on_lost: LostCallback) -> str | None:
        """Take the lock. ``None`` when held, else why it failed (never raises for that)."""
        ...

    async def free(self) -> None:
        """Free the lock (a no-op when not held)."""
        ...


# --------------------------------------------------------------------------- logind


DBusCall = Callable[..., dbus.Reply]


class LogindBackend:
    """``org.freedesktop.login1.Manager.Inhibit`` on the system bus; holds the returned fd."""

    name = "logind"

    def __init__(
        self,
        *,
        address: str | None = None,
        timeout: float = 5.0,
        call: DBusCall = dbus.call,
    ) -> None:
        self._address = address
        self._timeout = timeout
        self._call = call
        self._fd: int | None = None

    @property
    def fd(self) -> int | None:
        return self._fd

    async def hold(self, why: str, on_lost: LostCallback) -> str | None:
        if self._fd is not None:
            return None
        try:
            # The fd is not tied to a thread (unlike the Windows execution state), so a
            # worker thread is fine here.
            reply = await asyncio.to_thread(
                self._call,
                destination=LOGIND_DESTINATION,
                path=LOGIND_PATH,
                interface=LOGIND_INTERFACE,
                member="Inhibit",
                args=(WHAT, WHO, why, MODE),
                address=self._address,
                timeout=self._timeout,
            )
        except dbus.DBusError as exc:
            return f"Inhibit failed: {exc}"
        except (OSError, dbus.DBusProtocolError) as exc:
            return f"no system bus: {type(exc).__name__}: {exc}"
        index = reply.body[0] if reply.signature == "h" and reply.body else None
        if not isinstance(index, int) or not 0 <= index < len(reply.fds):
            _close_fds(reply.fds)
            return f"Inhibit returned no file descriptor (signature {reply.signature!r})"
        fd = reply.fds[index]
        _close_fds([f for f in reply.fds if f != fd])
        with contextlib.suppress(OSError):
            os.set_inheritable(fd, False)
        self._fd = fd
        return None

    async def free(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            _close_fds([fd])


def _close_fds(fds: Sequence[int]) -> None:
    for fd in fds:
        with contextlib.suppress(OSError):
            os.close(fd)


# --------------------------------------------------------------------------- systemd-inhibit


READY = "ready"


class SystemdInhibitBackend:
    """``systemd-inhibit … sh -c 'echo ready && exec sleep infinity'`` as a long-running child.

    The child is started with :func:`reframe.tools.run_streaming` (child safety: it dies with
    Reframe) and stopped with its :class:`CancelToken` (tree kill), which closes the lock fd
    that ``systemd-inhibit`` holds.
    """

    name = "systemd-inhibit"

    def __init__(
        self,
        *,
        program: str = "systemd-inhibit",
        start_timeout: float = 10.0,
        which: Callable[[str], str | None] = shutil.which,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self._program = program
        self._start_timeout = start_timeout
        self._which = which
        self._extra_env = extra_env
        self._task: asyncio.Task[RunResult] | None = None
        self._token: CancelToken | None = None
        self._freeing = False

    @property
    def task(self) -> asyncio.Task[RunResult] | None:
        """The running ``run_streaming`` task while the lock is held."""
        return self._task

    def argv(self, path: str, why: str) -> list[str]:
        return [
            path,
            f"--what={WHAT}",
            f"--who={WHO}",
            f"--why={why}",
            f"--mode={MODE}",
            "--no-ask-password",
            "sh",
            "-c",
            f"echo {READY} && exec sleep infinity",
        ]

    async def hold(self, why: str, on_lost: LostCallback) -> str | None:
        if self._task is not None:
            return None
        path = self._which(self._program)
        if path is None:
            return f"{self._program} not found"
        ready = asyncio.Event()
        errors: list[str] = []

        def on_stdout(line: str) -> None:
            if line.strip() == READY:
                ready.set()

        def on_stderr(line: str) -> None:
            if line.strip() and len(errors) < 20:
                errors.append(line.strip())

        token = CancelToken()
        task = asyncio.ensure_future(
            run_streaming(
                self.argv(path, why),
                on_stdout_line=on_stdout,
                on_stderr_line=on_stderr,
                cancel=token,
                extra_env=self._extra_env,
            )
        )
        ready_wait = asyncio.ensure_future(ready.wait())
        try:
            await asyncio.wait(
                {task, ready_wait},
                timeout=self._start_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            token.cancel("acquire cancelled")
            await asyncio.shield(task)
            raise
        finally:
            ready_wait.cancel()
        if ready.is_set() and not task.done():
            self._task, self._token, self._freeing = task, token, False
            task.add_done_callback(lambda t: self._ended(t, on_lost))
            return None
        if not task.done():
            token.cancel("did not start")
            await task
            return f"{self._program} did not start within {self._start_timeout:g} s"
        result = task.result()
        if result.error is not None:
            return result.error
        detail = "; ".join(errors) or "no output"
        return f"{self._program} exited with code {result.returncode}: {detail}"

    def _ended(self, task: asyncio.Task[RunResult], on_lost: LostCallback) -> None:
        if self._freeing or self._task is not task:
            return
        self._task = self._token = None
        code = None if task.cancelled() or task.exception() else task.result().returncode
        on_lost(f"{self._program} exited unexpectedly (code {code})")

    async def free(self) -> None:
        task, token = self._task, self._token
        if task is None or token is None:
            return
        self._freeing = True
        token.cancel("sleep inhibit released")
        try:
            await asyncio.shield(task)
        finally:
            self._task = self._token = None
            self._freeing = False


# --------------------------------------------------------------------------- Windows


class Kernel32(Protocol):
    """The ``kernel32`` function this backend calls (a ``ctypes.WinDLL`` or a test mock)."""

    def SetThreadExecutionState(self, flags: int) -> int: ...


def _load_kernel32() -> Kernel32:  # pragma: no cover - Windows only
    if sys.platform == "win32":
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.SetThreadExecutionState.argtypes = (wintypes.DWORD,)
        k32.SetThreadExecutionState.restype = wintypes.DWORD  # EXECUTION_STATE
        return cast("Kernel32", k32)
    raise OSError("kernel32 exists only on Windows")


def _last_error() -> int:
    get = getattr(ctypes, "get_last_error", None)
    return int(get()) if get is not None else 0


class _StateThread:
    """A thread that owns the execution state: every ``SetThreadExecutionState`` runs here.

    Commands go through a queue; each returns ``(previous_state, last_error)`` through a
    ``concurrent.futures.Future``. The thread ends after :meth:`stop`.
    """

    def __init__(self, kernel32: Kernel32, last_error: Callable[[], int]) -> None:
        self._kernel32 = kernel32
        self._last_error = last_error
        self._commands: queue.SimpleQueue[
            tuple[int, concurrent.futures.Future[tuple[int, int]]] | None
        ] = queue.SimpleQueue()
        self.thread = threading.Thread(target=self._run, name="reframe-sleep-inhibit", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while True:
            command = self._commands.get()
            if command is None:
                return
            flags, future = command
            if not future.set_running_or_notify_cancel():
                continue  # pragma: no cover - never cancelled
            try:
                previous = int(self._kernel32.SetThreadExecutionState(flags))
                error = 0 if previous else self._last_error()
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result((previous, error))

    def submit(self, flags: int) -> concurrent.futures.Future[tuple[int, int]]:
        future: concurrent.futures.Future[tuple[int, int]] = concurrent.futures.Future()
        self._commands.put((flags, future))
        return future

    def stop(self) -> None:
        self._commands.put(None)


class WindowsExecutionStateBackend:
    """``SetThreadExecutionState`` on a dedicated thread that lives while the lock is held."""

    name = "SetThreadExecutionState"

    def __init__(
        self,
        kernel32: Kernel32 | None = None,
        *,
        last_error: Callable[[], int] = _last_error,
    ) -> None:
        self._kernel32 = kernel32
        self._last_error = last_error
        self._thread: _StateThread | None = None

    @property
    def thread(self) -> threading.Thread | None:
        """The thread that holds the execution state (``None`` when not held)."""
        return self._thread.thread if self._thread is not None else None

    async def hold(self, why: str, on_lost: LostCallback) -> str | None:
        if self._thread is not None:
            return None
        try:
            k32 = self._kernel32 if self._kernel32 is not None else _load_kernel32()
        except (OSError, AttributeError) as exc:
            return f"kernel32 not available: {exc}"
        self._kernel32 = k32
        thread = _StateThread(k32, self._last_error)
        try:
            previous, error = await asyncio.wrap_future(
                thread.submit(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            )
        except Exception as exc:  # a broken binding (ctypes.ArgumentError, OSError)
            thread.stop()
            return f"SetThreadExecutionState failed: {type(exc).__name__}: {exc}"
        if not previous:  # "If the function fails, the return value is NULL."
            thread.stop()
            return f"SetThreadExecutionState failed (error {error})"
        self._thread = thread
        return None

    async def free(self) -> None:
        state_thread, self._thread = self._thread, None
        if state_thread is None:
            return
        try:
            previous, error = await asyncio.wrap_future(state_thread.submit(ES_CONTINUOUS))
            if not previous:  # pragma: no cover - nothing to do but log it
                log.warning("SetThreadExecutionState(ES_CONTINUOUS) failed (error %s)", error)
        finally:
            state_thread.stop()  # the thread ends after the clearing call


# --------------------------------------------------------------------------- the inhibitor


class SleepInhibitor:
    """A counted sleep lock over a list of backends (the first that works is used).

    ``acquire``/``release`` pairs nest. :meth:`close` frees the lock whatever the count;
    after it, :meth:`acquire` does nothing (the inhibitor is shut down). All methods are
    for one event loop; they never raise for expected failures.
    """

    def __init__(
        self,
        backends: Sequence[InhibitBackend],
        events: EventBus | None = None,
        *,
        unsupported: str | None = None,
    ) -> None:
        self._backends = list(backends)
        self._events = events
        self._unsupported = unsupported
        self._lock = asyncio.Lock()
        self._count = 0
        self._state = InhibitState.INACTIVE
        self._active: InhibitBackend | None = None
        self._pending: asyncio.Future[InhibitState] | None = None
        self._warned = False
        self._closed = False
        self.last_error: str | None = None
        """Why the last attempt failed (``None`` after a success)."""

    @property
    def state(self) -> InhibitState:
        return self._state

    @property
    def count(self) -> int:
        """How many ``acquire`` calls are not released yet."""
        return self._count

    @property
    def backend(self) -> str | None:
        """The name of the backend that holds the lock (``None`` when not held)."""
        return self._active.name if self._active is not None else None

    @property
    def closed(self) -> bool:
        return self._closed

    async def acquire(self, reason: str) -> InhibitState:
        """Count one holder; the first takes the operating-system lock. Returns the state.

        ``reason`` is shown to the user by the system (``systemd-inhibit --list``); only
        the first holder's reason is used. If the caller is cancelled while the lock is
        being taken, the count is undone and the lock is freed once it was taken (the caller
        must not call :meth:`release`).
        """
        async with self._lock:
            if self._closed:
                return self._state
            await self._settle()
            self._count += 1
            if self._count > 1:
                return self._state
            take = asyncio.ensure_future(self._take(reason))
            self._pending = take
            try:
                state = await asyncio.shield(take)
            except asyncio.CancelledError:
                self._count -= 1
                cleanup = asyncio.ensure_future(self._settle_locked())
                _background.add(cleanup)
                cleanup.add_done_callback(_background.discard)
                raise
            self._pending = None
            return state

    async def release(self) -> None:
        """Undo one :meth:`acquire`; the last one frees the lock. Extra calls do nothing."""
        async with self._lock:
            await self._settle()
            if self._count == 0:
                return
            self._count -= 1
            if self._count == 0:
                await asyncio.shield(self._free())

    async def close(self) -> None:
        """Free the lock whatever the count. Safe to call more than once."""
        async with self._lock:
            self._closed = True
            self._count = 0
            await self._settle()
            await asyncio.shield(self._free())

    async def _settle(self) -> None:
        """Wait for the lock that a cancelled :meth:`acquire` was taking; free it if unused.

        Called with ``self._lock`` held, so two takes never overlap (no second fd).
        """
        pending = self._pending
        if pending is None:
            return
        await asyncio.wait({pending})  # never cancels ``pending``
        self._pending = None
        if not pending.cancelled() and pending.exception() is not None:
            log.error("sleep inhibit failed", exc_info=pending.exception())
        if self._count == 0:
            await asyncio.shield(self._free())

    async def _settle_locked(self) -> None:
        async with self._lock:
            await self._settle()

    async def _take(self, reason: str) -> InhibitState:
        errors: list[str] = []
        if self._unsupported is not None:
            errors.append(self._unsupported)
        for backend in self._backends:
            error = await backend.hold(reason, self._lost)
            if error is None:
                self._active = backend
                self._state = InhibitState.ACTIVE
                self._warned = False
                self.last_error = None
                log.info("sleep inhibit active (%s): %s", backend.name, reason)
                return self._state
            errors.append(f"{backend.name}: {error}")
        self._fail("; ".join(errors) or "no sleep inhibit backend")
        return self._state

    async def _free(self) -> None:
        backend, self._active = self._active, None
        if backend is not None:
            await backend.free()
            log.info("sleep inhibit released (%s)", backend.name)
        if self._state is InhibitState.ACTIVE:
            self._state = InhibitState.INACTIVE

    def _lost(self, reason: str) -> None:
        """A backend lost its lock on its own (for example ``systemd-inhibit`` was killed)."""
        self._active = None
        self._fail(reason)

    def _fail(self, detail: str) -> None:
        self._state = InhibitState.UNAVAILABLE
        self.last_error = detail
        log.warning("sleep inhibit unavailable: %s", detail)
        if self._warned:
            return
        self._warned = True
        if self._events is not None:
            self._events.publish(
                AppWarningEvent(
                    code=WARNING_CODE,
                    message=(
                        "Sleep inhibit is not available: the computer may go to sleep "
                        "while the queue runs."
                    ),
                    detail=detail,
                )
            )


def default_backends(platform: str | None = None) -> list[InhibitBackend]:
    """The backends for ``platform`` (default: this one), in the order they are tried."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return [WindowsExecutionStateBackend()]
    if platform.startswith("linux"):
        return [LogindBackend(), SystemdInhibitBackend()]
    return []


def create_sleep_inhibitor(
    events: EventBus | None = None,
    *,
    platform: str | None = None,
    backends: Sequence[InhibitBackend] | None = None,
) -> SleepInhibitor:
    """A :class:`SleepInhibitor` with the backends of the platform (see the module doc)."""
    platform = sys.platform if platform is None else platform
    chosen = default_backends(platform) if backends is None else list(backends)
    unsupported = None if chosen else f"no sleep inhibit backend for platform {platform!r}"
    return SleepInhibitor(chosen, events, unsupported=unsupported)
