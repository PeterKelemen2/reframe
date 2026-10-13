"""Sleep inhibit while the queue runs (C-14, 03 §Queue; decisions 0011 and 0020).

Only **automatic** (idle) sleep is stopped. The user's own Sleep (menu), the power button
and the lid always work at once; the encode then pauses with the system and continues after
wake (decision 0020). The screen may still dim, turn off and lock (as on Windows, where
``ES_DISPLAY_REQUIRED`` is not used).

:class:`SleepInhibitor` is a counted lock: the first :meth:`~SleepInhibitor.acquire` takes
the operating-system locks, the last :meth:`~SleepInhibitor.release` frees them, and
:meth:`~SleepInhibitor.close` frees them whatever the count. :func:`create_sleep_inhibitor`
picks the backends for the platform. The backends are tried in order and every one that
applies is held: the inhibitor is ``active`` when at least one holds, and says what is not
stopped when one fails (:attr:`~SleepInhibitor.not_stopped`, and a log warning). A backend
that does not apply returns :class:`Skipped` (logged, not a failure).

Linux (verified on KDE Plasma 6, systemd 262; ``testdata/README.md`` "Sleep inhibit (C-14)")
    1. **The desktop session's inhibit** on the session bus, on a connection that stays open
       while the lock is held (the desktop drops the inhibit when the connection closes):
       ``org.freedesktop.PowerManagement.Inhibit.Inhibit("Reframe", why)`` (KDE PowerDevil,
       Xfce), else the XDG desktop portal ``org.freedesktop.portal.Inhibit.Inhibit("", 4,
       {"reason": why})`` (flag 4 = suspend; GNOME and others). On KDE either one becomes
       PowerDevil's "sleep" inhibition about 5 s after the call: the automatic suspend on
       idle is skipped, the screen still dims and locks, and ``CanSuspend`` stays ``yes``
       (the user's own suspend works). The portal's ``idle`` flag (8) is not used: on KDE it
       becomes an "idle" inhibition, which also keeps the screen on. No session bus (a
       headless server, a system service) is :class:`Skipped`.
    2. **logind** ``org.freedesktop.login1.Manager.Inhibit("idle", "Reframe", why, "block")``
       on the system bus, for logind's own ``IdleAction=`` (``suspend``, ``poweroff``, …).
       It returns a file descriptor; the lock lasts while the descriptor is open (it is
       close-on-exec, so no child keeps it alive). ``CanSuspend`` stays ``yes``. polkit
       allows an ``idle`` block lock for every caller. It is taken only where it is needed:
       when the session inhibit is not held, or when ``IdleAction`` is not ``ignore``. The
       reason: KDE PowerDevil mirrors logind locks (after about 5 s), and a logind ``idle``
       lock becomes an "idle" inhibition that keeps the screen from dimming and locking.
       Never a ``sleep`` lock (it refuses the user's own suspend; decision 0020).

    ``systemd-inhibit`` is not used any more: with only the ``idle`` lock it reaches the same
    logind with the same permission as the direct call, so it adds a process and no
    coverage, and it cannot take the session inhibit.

Windows
    ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`` while held,
    ``SetThreadExecutionState(ES_CONTINUOUS)`` on release
    (https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate:
    it stops the idle timer and "cannot be used to prevent the user from putting the
    computer to sleep"). The execution state belongs to the **calling thread**, so both calls
    run on one dedicated thread that lives exactly as long as the lock is held (never on an
    asyncio worker thread, which may end or be reused). This code is unit-tested with a
    mocked ``kernel32`` on Linux; it has not been run on Windows yet.

When no backend holds, the inhibitor publishes one ``app.warning`` event (code
``sleep_inhibit.unavailable``) and goes on: :attr:`~SleepInhibitor.state` is
``unavailable`` and the queue runs anyway. Expected failures (no bus, no service, access
denied) never raise. No call ever asks for a password.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import ctypes
import logging
import os
import queue
import sys
import threading
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Protocol, cast

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.platform import dbus

__all__ = [
    "ES_CONTINUOUS",
    "ES_SYSTEM_REQUIRED",
    "MODE",
    "PORTAL_INHIBIT_SUSPEND",
    "WARNING_CODE",
    "WHAT",
    "WHO",
    "InhibitBackend",
    "InhibitState",
    "LogindBackend",
    "SessionInhibitBackend",
    "Skipped",
    "SleepInhibitor",
    "WindowsExecutionStateBackend",
    "create_sleep_inhibitor",
    "default_backends",
]

log = logging.getLogger(__name__)

WHO = "Reframe"
WHAT = "idle"
"""Only ``idle`` (logind's automatic idle action). Never ``sleep``: a ``sleep`` block lock
also refuses the user's own suspend (``CanSuspend`` becomes ``inhibited``; decision 0020)."""
MODE = "block"
"""``delay`` exists only for ``sleep`` and ``shutdown``; ``block`` is the only mode for
``idle`` that lasts."""
WARNING_CODE = "sleep_inhibit.unavailable"

LOGIND_DESTINATION = "org.freedesktop.login1"
LOGIND_PATH = "/org/freedesktop/login1"
LOGIND_INTERFACE = "org.freedesktop.login1.Manager"

PM_DESTINATION = "org.freedesktop.PowerManagement.Inhibit"
PM_PATH = "/org/freedesktop/PowerManagement/Inhibit"
PM_INTERFACE = "org.freedesktop.PowerManagement.Inhibit"

PORTAL_DESTINATION = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.Inhibit"
PORTAL_INHIBIT_SUSPEND = 4
"""The portal's flags: 1 logout, 2 user switch, 4 suspend, 8 idle. Only suspend (see the
module doc for why not idle)."""

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

#: The cleanup of a cancelled acquire runs as a task: keep a reference until it is done.
_background: set[asyncio.Task[None]] = set()


class InhibitState(StrEnum):
    INACTIVE = "inactive"
    """Not held (and the last attempt, if any, did not fail)."""
    ACTIVE = "active"
    """At least one operating-system lock is held (see ``not_stopped`` for the rest)."""
    UNAVAILABLE = "unavailable"
    """The last attempt held nothing; the queue runs on."""


class Skipped(str):
    """A :meth:`InhibitBackend.hold` result: nothing to stop here, not a failure (for
    example no desktop session bus on a headless server)."""

    __slots__ = ()


class InhibitBackend(Protocol):
    """One operating-system lock."""

    @property
    def name(self) -> str: ...

    @property
    def stops(self) -> str:
        """What this lock stops, for messages ("the desktop's automatic suspend")."""
        ...

    async def hold(self, why: str) -> str | None:
        """Take the lock. ``None`` when held, a :class:`Skipped` when there is nothing to
        stop, else why it failed (never raises for expected failures)."""
        ...

    async def free(self) -> None:
        """Free the lock (a no-op when not held)."""
        ...


# --------------------------------------------------------------------------- logind


DBusCall = Callable[..., dbus.Reply]


class LogindBackend:
    """``org.freedesktop.login1.Manager.Inhibit("idle", …, "block")``; holds the returned fd.

    ``unless`` (optional): a check made before the lock is taken. When it is true **and**
    logind's ``IdleAction`` is ``ignore`` (logind itself does nothing on idle), the lock is
    :class:`Skipped`. The Linux default passes "the desktop session's inhibit is held":
    KDE turns a logind ``idle`` lock into its own "idle" inhibition, which also keeps the
    screen from dimming and locking, so the lock is taken only where it is needed.
    """

    name = "logind"
    stops = "logind's automatic idle action (IdleAction=)"

    def __init__(
        self,
        *,
        address: str | None = None,
        timeout: float = 5.0,
        call: DBusCall = dbus.call,
        unless: Callable[[], bool] | None = None,
    ) -> None:
        self._address = address
        self._timeout = timeout
        self._call = call
        self._unless = unless
        self._fd: int | None = None

    @property
    def fd(self) -> int | None:
        return self._fd

    async def idle_action(self) -> str | None:
        """logind's ``IdleAction`` property (``ignore``, ``suspend``, …), ``None`` if unknown."""
        try:
            reply = await asyncio.to_thread(
                self._call,
                destination=LOGIND_DESTINATION,
                path=LOGIND_PATH,
                interface="org.freedesktop.DBus.Properties",
                member="Get",
                args=(LOGIND_INTERFACE, "IdleAction"),
                address=self._address,
                timeout=self._timeout,
            )
        except (OSError, dbus.DBusError, dbus.DBusProtocolError):
            return None
        _close_fds(reply.fds)
        value = reply.body[0] if reply.signature == "v" and reply.body else None
        return value if isinstance(value, str) else None

    async def hold(self, why: str) -> str | None:
        if self._fd is not None:
            return None
        if self._unless is not None and self._unless():
            action = await self.idle_action()
            if action == "ignore":
                return Skipped(
                    "not needed: logind's IdleAction is 'ignore' and the desktop "
                    "session's inhibit is held"
                )
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


# --------------------------------------------------------------------------- desktop session


class _BusConnection(Protocol):
    """What the session backend needs of :class:`reframe.platform.dbus.Connection`."""

    def call(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        args: Sequence[str] = (),
        body: Sequence[tuple[str, dbus.Value]] = (),
        timeout: float = 5.0,
    ) -> dbus.Reply: ...

    def close(self) -> None: ...


def _open_connection(address: str, timeout: float) -> _BusConnection:
    return dbus.Connection.open(address, timeout=timeout)


_InhibitCall = Callable[[_BusConnection, str, float], dbus.Reply]


def _pm_inhibit(connection: _BusConnection, why: str, timeout: float) -> dbus.Reply:
    """``org.freedesktop.PowerManagement.Inhibit.Inhibit(application, reason) -> cookie``."""
    return connection.call(
        destination=PM_DESTINATION,
        path=PM_PATH,
        interface=PM_INTERFACE,
        member="Inhibit",
        args=(WHO, why),
        timeout=timeout,
    )


def _portal_inhibit(connection: _BusConnection, why: str, timeout: float) -> dbus.Reply:
    """``org.freedesktop.portal.Inhibit.Inhibit(window, flags, options) -> request handle``."""
    return connection.call(
        destination=PORTAL_DESTINATION,
        path=PORTAL_PATH,
        interface=PORTAL_INTERFACE,
        member="Inhibit",
        body=(
            ("s", ""),  # no parent window
            ("u", PORTAL_INHIBIT_SUSPEND),
            ("a{sv}", {"reason": why}),
        ),
        timeout=timeout,
    )


def _pm_uninhibit(connection: _BusConnection, cookie: str | int, timeout: float) -> None:
    connection.call(
        destination=PM_DESTINATION,
        path=PM_PATH,
        interface=PM_INTERFACE,
        member="UnInhibit",
        body=(("u", int(cookie)),),
        timeout=timeout,
    )


def _portal_close(connection: _BusConnection, handle: str | int, timeout: float) -> None:
    connection.call(
        destination=PORTAL_DESTINATION,
        path=str(handle),
        interface="org.freedesktop.portal.Request",
        member="Close",
        timeout=timeout,
    )


_INHIBIT: dict[str, tuple[_InhibitCall, Callable[[_BusConnection, str | int, float], None]]] = {
    PM_INTERFACE: (_pm_inhibit, _pm_uninhibit),
    PORTAL_INTERFACE: (_portal_inhibit, _portal_close),
}


class SessionInhibitBackend:
    """The desktop session's inhibit for automatic suspend, on a connection kept open.

    Tries ``org.freedesktop.PowerManagement.Inhibit`` first (it shows "Reframe" and the
    reason in KDE's battery applet), then the XDG desktop portal with the suspend flag
    (``interfaces`` changes the list). The inhibit lasts while the connection is open.
    :meth:`free` ends it explicitly (``UnInhibit(cookie)`` or ``Request.Close()``) and then
    closes the connection; on KDE either one alone ends it within a second. No session bus
    (a headless server, a system service) is :class:`Skipped`: there is no desktop that
    could suspend on idle.
    """

    name = "session"
    stops = "the desktop's automatic suspend"

    def __init__(
        self,
        *,
        address: str | None = None,
        timeout: float = 5.0,
        connect: Callable[[str, float], _BusConnection] = _open_connection,
        interfaces: Sequence[str] = (PM_INTERFACE, PORTAL_INTERFACE),
    ) -> None:
        unknown = [i for i in interfaces if i not in _INHIBIT]
        if unknown:
            raise ValueError(f"unknown session inhibit interfaces: {unknown}")
        self._address = address
        self._timeout = timeout
        self._connect = connect
        self._interfaces = tuple(interfaces)
        self._connection: _BusConnection | None = None
        self._token: str | int | None = None
        self.interface: str | None = None
        """The interface that holds the inhibit (``None`` when not held)."""

    @property
    def held(self) -> bool:
        return self._connection is not None

    async def hold(self, why: str) -> str | None:
        if self._connection is not None:
            return None
        address = self._address if self._address is not None else dbus.session_bus_address()
        if address is None:
            return Skipped("no session bus (DBUS_SESSION_BUS_ADDRESS is not set)")
        try:
            connection = await asyncio.to_thread(self._connect, address, self._timeout)
        except OSError as exc:
            return Skipped(f"no session bus: {type(exc).__name__}: {exc}")
        except dbus.DBusError as exc:
            return f"session bus refused the connection: {exc}"
        except dbus.DBusProtocolError as exc:
            return f"session bus: {exc}"
        errors: list[str] = []
        try:
            for interface in self._interfaces:
                inhibit, _ = _INHIBIT[interface]
                try:
                    reply = await asyncio.to_thread(inhibit, connection, why, self._timeout)
                except dbus.DBusError as exc:
                    errors.append(f"{interface}: {exc}")
                    continue
                self._connection, self.interface = connection, interface
                self._token = reply.body[0] if reply.body else None
                return None
        except (OSError, dbus.DBusProtocolError) as exc:
            errors.append(f"session bus: {type(exc).__name__}: {exc}")
        connection.close()
        return "; ".join(errors)

    async def free(self) -> None:
        connection, self._connection = self._connection, None
        interface, self.interface = self.interface, None
        token, self._token = self._token, None
        if connection is None:
            return
        try:
            if interface is not None and token is not None:
                _, end = _INHIBIT[interface]
                await asyncio.to_thread(end, connection, token, min(self._timeout, 2.0))
        except (OSError, dbus.DBusError, dbus.DBusProtocolError) as exc:
            # Closing the connection ends the inhibit anyway (checked on KDE).
            log.debug("ending the session inhibit (%s) failed: %s", interface, exc)
        finally:
            connection.close()


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
    stops = "the Windows sleep idle timer"

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

    async def hold(self, why: str) -> str | None:
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
    """A counted sleep lock over backends that are held together.

    ``acquire``/``release`` pairs nest. :meth:`close` frees the locks whatever the count;
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
        self._active: list[InhibitBackend] = []
        self._pending: asyncio.Future[InhibitState] | None = None
        self._warned = False
        self._closed = False
        self.last_error: str | None = None
        """Why the last attempt failed, fully or for some backends (``None``: all held)."""
        self.not_stopped: tuple[str, ...] = ()
        """While ``active``: what the failed backends would have stopped (empty: nothing
        is missing)."""

    @property
    def state(self) -> InhibitState:
        return self._state

    @property
    def count(self) -> int:
        """How many ``acquire`` calls are not released yet."""
        return self._count

    @property
    def backends(self) -> tuple[str, ...]:
        """The names of the backends that hold a lock now."""
        return tuple(b.name for b in self._active)

    @property
    def backend(self) -> str | None:
        """The held backends joined with ``+`` (``"logind+session"``), ``None`` when none."""
        return "+".join(self.backends) or None

    @property
    def closed(self) -> bool:
        return self._closed

    async def acquire(self, reason: str) -> InhibitState:
        """Count one holder; the first takes the operating-system locks. Returns the state.

        ``reason`` is shown to the user by the system (``systemd-inhibit --list``, the
        desktop's battery applet); only the first holder's reason is used. If the caller is
        cancelled while the locks are being taken, the count is undone and the locks are
        freed once they were taken (the caller must not call :meth:`release`).
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
        """Undo one :meth:`acquire`; the last one frees the locks. Extra calls do nothing."""
        async with self._lock:
            await self._settle()
            if self._count == 0:
                return
            self._count -= 1
            if self._count == 0:
                await asyncio.shield(self._free())

    async def close(self) -> None:
        """Free the locks whatever the count. Safe to call more than once."""
        async with self._lock:
            self._closed = True
            self._count = 0
            await self._settle()
            await asyncio.shield(self._free())

    async def _settle(self) -> None:
        """Wait for the locks that a cancelled :meth:`acquire` was taking; free them if
        unused. Called with ``self._lock`` held, so two takes never overlap."""
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
        failed: list[InhibitBackend] = []
        details: list[str] = []
        skipped: list[str] = []
        if self._unsupported is not None:
            details.append(self._unsupported)
        for backend in self._backends:
            result = await backend.hold(reason)
            if result is None:
                self._active.append(backend)
            elif isinstance(result, Skipped):
                skipped.append(f"{backend.name}: {result}")
            else:
                failed.append(backend)
                details.append(f"{backend.name}: {result}")
        if not self._active:
            self._fail("; ".join(details + skipped) or "no sleep inhibit backend")
            return self._state
        self._state = InhibitState.ACTIVE
        self._warned = False
        self.not_stopped = tuple(b.stops for b in failed)
        self.last_error = "; ".join(details) or None
        log.info("sleep inhibit active (%s): %s", self.backend, reason)
        for note in skipped:
            log.info("sleep inhibit: %s", note)
        if failed:
            log.warning(
                "sleep inhibit only partly active: %s not stopped (%s)",
                " and ".join(self.not_stopped),
                self.last_error,
            )
        return self._state

    async def _free(self) -> None:
        active, self._active = self._active, []
        for backend in reversed(active):
            await backend.free()
        if active:
            log.info("sleep inhibit released (%s)", "+".join(b.name for b in active))
        self.not_stopped = ()
        if self._state is InhibitState.ACTIVE:
            self._state = InhibitState.INACTIVE

    def _fail(self, detail: str) -> None:
        self._state = InhibitState.UNAVAILABLE
        self.last_error = detail
        self.not_stopped = ()
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
                        "on its own while the queue runs."
                    ),
                    detail=detail,
                )
            )


def default_backends(platform: str | None = None) -> list[InhibitBackend]:
    """The backends for ``platform`` (default: this one); all of them are held together."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return [WindowsExecutionStateBackend()]
    if platform.startswith("linux"):
        session = SessionInhibitBackend()
        # The session inhibit first; the logind idle lock only where it is needed.
        return [session, LogindBackend(unless=lambda: session.held)]
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
