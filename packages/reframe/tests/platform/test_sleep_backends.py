"""The sleep inhibit backends: Windows (mocked kernel32), logind and the desktop session
(fake D-Bus connections)."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Any
from unittest import mock

import pytest

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.platform import dbus, sleep
from reframe.platform.sleep import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    InhibitState,
    LogindBackend,
    SessionInhibitBackend,
    Skipped,
    SleepInhibitor,
    WindowsExecutionStateBackend,
)
from reframe_testing.fake_dbus import open_fds

PM = "org.freedesktop.PowerManagement.Inhibit"
PORTAL = "org.freedesktop.portal.Inhibit"

pytestmark = pytest.mark.anyio

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")


class RecordingKernel32:
    """``SetThreadExecutionState`` that records the flags and the calling thread."""

    def __init__(self, results: list[int] | None = None) -> None:
        self.calls: list[tuple[int, threading.Thread]] = []
        self.results = results if results is not None else []
        self.lock = threading.Lock()

    def SetThreadExecutionState(self, flags: int) -> int:
        with self.lock:
            self.calls.append((flags, threading.current_thread()))
            return self.results.pop(0) if self.results else ES_CONTINUOUS  # the old state


async def test_windows_sets_and_clears_on_one_dedicated_thread() -> None:
    k32 = RecordingKernel32()
    backend = WindowsExecutionStateBackend(k32, last_error=lambda: 0)
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire("encode") is InhibitState.ACTIVE
    assert inhibitor.backend == "SetThreadExecutionState"
    holder = backend.thread
    assert holder is not None
    assert holder.name == "reframe-sleep-inhibit"
    assert holder is not threading.current_thread()  # not the event loop thread

    # Busy asyncio worker threads while the lock is held do not touch the state, and the
    # holding thread stays alive (the execution state belongs to it).
    await asyncio.gather(*(asyncio.to_thread(lambda: None) for _ in range(20)))
    await asyncio.sleep(0.05)
    assert holder.is_alive()
    assert len(k32.calls) == 1

    await inhibitor.release()
    assert [flags for flags, _ in k32.calls] == [
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED,
        ES_CONTINUOUS,
    ]
    assert [flags for flags, _ in k32.calls] == [0x80000001, 0x80000000]
    assert k32.calls[0][1] is holder
    assert k32.calls[1][1] is holder  # cleared on the thread that set it
    holder.join(timeout=5)
    assert not holder.is_alive()  # the thread ends with the lock
    assert backend.thread is None


async def test_windows_each_hold_gets_its_own_thread_and_nested_holds_call_once() -> None:
    k32 = RecordingKernel32()
    backend = WindowsExecutionStateBackend(k32, last_error=lambda: 0)
    inhibitor = SleepInhibitor([backend])
    await inhibitor.acquire("a")
    await inhibitor.acquire("b")
    first = backend.thread
    await inhibitor.release()
    await inhibitor.release()
    await inhibitor.acquire("c")
    second = backend.thread
    await inhibitor.close()
    await inhibitor.close()
    assert first is not None
    assert second is not None
    assert first is not second
    assert [(flags, thread) for flags, thread in k32.calls] == [
        (0x80000001, first),
        (0x80000000, first),
        (0x80000001, second),
        (0x80000000, second),
    ]


async def test_windows_failure_is_unavailable_with_the_error_code() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    k32 = RecordingKernel32(results=[0])  # "If the function fails, the return value is NULL."
    backend = WindowsExecutionStateBackend(k32, last_error=lambda: 87)
    inhibitor = SleepInhibitor([backend], bus)
    assert await inhibitor.acquire("encode") is InhibitState.UNAVAILABLE
    assert backend.thread is None
    event = sub.get_nowait()
    assert isinstance(event, AppWarningEvent)
    assert event.code == "sleep_inhibit.unavailable"
    assert event.detail == "SetThreadExecutionState: SetThreadExecutionState failed (error 87)"
    await inhibitor.release()
    assert [flags for flags, _ in k32.calls] == [0x80000001]  # nothing to clear
    for thread in threading.enumerate():
        if thread.name == "reframe-sleep-inhibit":
            thread.join(timeout=5)
    assert all(t.name != "reframe-sleep-inhibit" for t in threading.enumerate())


async def test_windows_binding_error_is_data() -> None:
    k32 = mock.Mock(spec=["SetThreadExecutionState"])
    k32.SetThreadExecutionState.side_effect = OSError("broken binding")
    backend = WindowsExecutionStateBackend(k32)
    assert await backend.hold("x") == ("SetThreadExecutionState failed: OSError: broken binding")
    assert backend.thread is None


@pytest.mark.skipif(sys.platform == "win32", reason="kernel32 exists on Windows")
async def test_windows_backend_without_kernel32_is_unavailable() -> None:
    backend = WindowsExecutionStateBackend()
    assert await backend.hold("x") == ("kernel32 not available: kernel32 exists only on Windows")
    await backend.free()


def _fd(backend: LogindBackend) -> int | None:
    return backend.fd  # through a function, so that mypy does not narrow the property


class FakeCall:
    def __init__(self, result: dbus.Reply | BaseException) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> dbus.Reply:
        self.kwargs = kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@linux_only
async def test_logind_holds_the_returned_fd_and_closes_it_on_free() -> None:
    before = open_fds()
    read_end, write_end = os.pipe()
    os.set_inheritable(read_end, True)
    call = FakeCall(dbus.Reply("h", [0], [read_end]))
    backend = LogindBackend(call=call, address="unix:path=/x", timeout=2.0)
    assert await backend.hold("Encoding 3 jobs") is None
    assert call.kwargs == {
        "destination": "org.freedesktop.login1",
        "path": "/org/freedesktop/login1",
        "interface": "org.freedesktop.login1.Manager",
        "member": "Inhibit",
        "args": ("idle", "Reframe", "Encoding 3 jobs", "block"),
        "address": "unix:path=/x",
        "timeout": 2.0,
    }
    assert backend.fd == read_end
    assert not os.get_inheritable(read_end)  # a child must never keep the lock alive
    assert await backend.hold("again") is None  # already held: no second call
    await backend.free()
    assert _fd(backend) is None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(read_end)
    await backend.free()
    os.close(write_end)
    assert open_fds() == before


@linux_only
async def test_logind_closes_extra_fds_and_rejects_a_reply_without_one() -> None:
    before = open_fds()
    a, b = os.pipe()
    backend = LogindBackend(call=FakeCall(dbus.Reply("h", [1], [a, b])))
    assert await backend.hold("x") is None
    assert backend.fd == b
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(a)
    await backend.free()
    c, d = os.pipe()
    bad = LogindBackend(call=FakeCall(dbus.Reply("h", [5], [c, d])))
    assert await bad.hold("x") == ("Inhibit returned no file descriptor (signature 'h')")
    assert bad.fd is None
    empty = LogindBackend(call=FakeCall(dbus.Reply("", [], [])))
    assert await empty.hold("x") == "Inhibit returned no file descriptor (signature '')"
    assert open_fds() == before


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            dbus.DBusError("org.freedesktop.DBus.Error.AccessDenied", "Permission denied"),
            "Inhibit failed: org.freedesktop.DBus.Error.AccessDenied: Permission denied",
        ),
        (
            FileNotFoundError(2, "No such file or directory"),
            "no system bus: FileNotFoundError: [Errno 2] No such file or directory",
        ),
        (TimeoutError("D-Bus call timed out"), "no system bus: TimeoutError: D-Bus call timed out"),
        (
            dbus.DBusProtocolError("authentication refused: 'REJECTED'"),
            "no system bus: DBusProtocolError: authentication refused: 'REJECTED'",
        ),
    ],
)
async def test_logind_expected_failures_are_data(error: BaseException, message: str) -> None:
    backend = LogindBackend(call=FakeCall(error))
    assert await backend.hold("x") == message
    assert backend.fd is None


async def test_windows_backend_accepts_a_mock_kernel32() -> None:
    # The Windows binding is only loaded on Windows; the backend accepts any object with
    # SetThreadExecutionState (here a Mock).
    k32 = mock.Mock(spec=["SetThreadExecutionState"])
    k32.SetThreadExecutionState.return_value = ES_CONTINUOUS
    backend = sleep.WindowsExecutionStateBackend(k32)
    assert await backend.hold("x") is None
    await backend.free()
    await backend.free()
    assert k32.SetThreadExecutionState.call_args_list == [
        mock.call(0x80000001),
        mock.call(0x80000000),
    ]


async def test_logind_unless_held_and_idle_action_ignore_is_skipped() -> None:
    calls: list[dict[str, Any]] = []

    def call(**kwargs: Any) -> dbus.Reply:
        calls.append(kwargs)
        return dbus.Reply("v", ["ignore"])

    backend = LogindBackend(call=call, unless=lambda: True)
    result = await backend.hold("x")
    assert isinstance(result, Skipped)
    assert "IdleAction is 'ignore'" in result
    assert backend.fd is None
    (get,) = calls
    assert get["interface"] == "org.freedesktop.DBus.Properties"
    assert get["member"] == "Get"
    assert get["args"] == ("org.freedesktop.login1.Manager", "IdleAction")


@linux_only
@pytest.mark.parametrize(
    "idle_action",
    [dbus.Reply("v", ["suspend"]), dbus.Reply("", []), dbus.DBusError("x.Failed", "no")],
)
async def test_logind_takes_the_lock_when_logind_acts_on_idle_or_it_is_unknown(
    idle_action: dbus.Reply | BaseException,
) -> None:
    read_end, write_end = os.pipe()
    members: list[str] = []

    def call(**kwargs: Any) -> dbus.Reply:
        members.append(kwargs["member"])
        if kwargs["member"] == "Get":
            if isinstance(idle_action, BaseException):
                raise idle_action
            return idle_action
        return dbus.Reply("h", [0], [read_end])

    backend = LogindBackend(call=call, unless=lambda: True)
    assert await backend.hold("x") is None
    assert members == ["Get", "Inhibit"]
    await backend.free()
    os.close(write_end)


@linux_only
async def test_logind_without_unless_never_asks_for_idle_action() -> None:
    read_end, write_end = os.pipe()
    call = FakeCall(dbus.Reply("h", [0], [read_end]))
    backend = LogindBackend(call=call, unless=lambda: False)
    assert await backend.hold("x") is None
    assert call.kwargs["member"] == "Inhibit"
    await backend.free()
    os.close(write_end)


def _held(backend: SessionInhibitBackend) -> bool:
    return backend.held


def _interface(backend: SessionInhibitBackend) -> str | None:
    return backend.interface  # through a function, so that mypy does not narrow it


class FakeConnection:
    """A session bus connection: ``answers`` maps an interface to a reply or an error."""

    def __init__(self, answers: dict[str, dbus.Reply | BaseException]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    def call(self, **kwargs: Any) -> dbus.Reply:
        self.calls.append(kwargs)
        answer = self.answers.get(kwargs["interface"], dbus.Reply("", []))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def close(self) -> None:
        self.closed += 1


UNKNOWN = dbus.DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "not provided")


def _connector(conn: FakeConnection | BaseException) -> tuple[list[tuple[str, float]], Any]:
    opened: list[tuple[str, float]] = []

    def connect(address: str, timeout: float) -> FakeConnection:
        opened.append((address, timeout))
        if isinstance(conn, BaseException):
            raise conn
        return conn

    return opened, connect


async def test_session_uses_power_management_and_keeps_the_connection_open() -> None:
    conn = FakeConnection({PM: dbus.Reply("u", [42])})
    opened, connect = _connector(conn)
    backend = SessionInhibitBackend(address="unix:path=/fake", timeout=3.0, connect=connect)
    assert await backend.hold("Encoding: Show S01E01") is None
    assert opened == [("unix:path=/fake", 3.0)]
    assert backend.held
    assert backend.interface == PM
    (call,) = conn.calls
    assert call == {
        "destination": "org.freedesktop.PowerManagement.Inhibit",
        "path": "/org/freedesktop/PowerManagement/Inhibit",
        "interface": PM,
        "member": "Inhibit",
        "args": ("Reframe", "Encoding: Show S01E01"),
        "timeout": 3.0,
    }
    assert conn.closed == 0  # the inhibit lasts while the connection is open
    assert await backend.hold("again") is None  # already held: no second call
    assert len(conn.calls) == 1
    await backend.free()
    assert conn.calls[1] == {
        "destination": "org.freedesktop.PowerManagement.Inhibit",
        "path": "/org/freedesktop/PowerManagement/Inhibit",
        "interface": PM,
        "member": "UnInhibit",
        "body": (("u", 42),),
        "timeout": 2.0,
    }
    assert conn.closed == 1
    assert not _held(backend)
    assert _interface(backend) is None
    await backend.free()
    assert conn.closed == 1
    assert len(conn.calls) == 2


async def test_session_falls_back_to_the_portal_with_the_suspend_flag() -> None:
    conn = FakeConnection(
        {PM: UNKNOWN, PORTAL: dbus.Reply("o", ["/org/freedesktop/portal/desktop/request/1_2/t"])}
    )
    _, connect = _connector(conn)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=connect)
    assert await backend.hold("Encoding") is None
    assert backend.interface == PORTAL
    portal = conn.calls[1]
    assert portal["destination"] == "org.freedesktop.portal.Desktop"
    assert portal["path"] == "/org/freedesktop/portal/desktop"
    assert portal["member"] == "Inhibit"
    assert portal["body"] == (("s", ""), ("u", 4), ("a{sv}", {"reason": "Encoding"}))
    await backend.free()
    assert conn.calls[2] == {
        "destination": "org.freedesktop.portal.Desktop",
        "path": "/org/freedesktop/portal/desktop/request/1_2/t",
        "interface": "org.freedesktop.portal.Request",
        "member": "Close",
        "timeout": 2.0,
    }
    assert conn.closed == 1


async def test_session_free_closes_the_connection_when_ending_fails() -> None:
    conn = FakeConnection(
        {PM: dbus.Reply("u", [7]), "org.example.never": dbus.Reply("", [])},
    )
    _, connect = _connector(conn)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=connect)
    assert await backend.hold("x") is None
    conn.answers[PM] = TimeoutError("D-Bus call timed out")
    await backend.free()
    assert conn.calls[-1]["member"] == "UnInhibit"
    assert conn.closed == 1


async def test_session_portal_only_and_unknown_interfaces() -> None:
    conn = FakeConnection({PORTAL: dbus.Reply("o", ["/r"])})
    _, connect = _connector(conn)
    backend = SessionInhibitBackend(
        address="unix:path=/fake", connect=connect, interfaces=(PORTAL,)
    )
    assert await backend.hold("x") is None
    assert [c["interface"] for c in conn.calls] == [PORTAL]
    await backend.free()
    with pytest.raises(ValueError, match="unknown session inhibit interfaces"):
        SessionInhibitBackend(interfaces=("org.example.Nope",))


async def test_session_without_any_service_fails_and_closes_the_connection() -> None:
    conn = FakeConnection({PM: UNKNOWN, PORTAL: UNKNOWN})
    _, connect = _connector(conn)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=connect)
    result = await backend.hold("x")
    assert result == (
        f"{PM}: org.freedesktop.DBus.Error.ServiceUnknown: not provided; "
        f"{PORTAL}: org.freedesktop.DBus.Error.ServiceUnknown: not provided"
    )
    assert not isinstance(result, Skipped)
    assert conn.closed == 1
    assert not _held(backend)


async def test_session_connection_lost_during_the_calls_is_data() -> None:
    conn = FakeConnection({PM: ConnectionError("the bus closed the connection")})
    _, connect = _connector(conn)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=connect)
    assert await backend.hold("x") == (
        "session bus: ConnectionError: the bus closed the connection"
    )
    assert conn.closed == 1
    assert len(conn.calls) == 1  # no portal call on a broken connection


async def test_no_session_bus_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    opened, connect = _connector(FakeConnection({}))
    backend = SessionInhibitBackend(connect=connect)
    result = await backend.hold("x")
    assert isinstance(result, Skipped)
    assert result == "no session bus (DBUS_SESSION_BUS_ADDRESS is not set)"
    assert opened == []


@pytest.mark.parametrize(
    ("error", "skipped", "message"),
    [
        (FileNotFoundError(2, "No such file"), True, "no session bus: FileNotFoundError: "),
        (
            dbus.DBusProtocolError("authentication refused: 'REJECTED'"),
            False,
            "session bus: authentication refused",
        ),
        (
            dbus.DBusError("org.freedesktop.DBus.Error.AccessDenied", "no"),
            False,
            "session bus refused the connection: org.freedesktop.DBus.Error.AccessDenied",
        ),
    ],
)
async def test_session_bus_connection_failures(
    error: BaseException, skipped: bool, message: str
) -> None:
    _, connect = _connector(error)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=connect)
    result = await backend.hold("x")
    assert result is not None
    assert isinstance(result, Skipped) is skipped
    assert result.startswith(message)


async def test_linux_default_takes_logind_only_where_needed() -> None:
    session, logind = sleep.default_backends("linux")
    assert isinstance(session, SessionInhibitBackend)
    assert isinstance(logind, LogindBackend)
    conn = FakeConnection({PM: dbus.Reply("u", [1])})
    _, connect = _connector(conn)
    session._connect = connect
    session._address = "unix:path=/fake"
    members: list[str] = []

    def call(**kwargs: Any) -> dbus.Reply:
        members.append(kwargs["member"])
        return dbus.Reply("v", ["ignore"])

    logind._call = call
    inhibitor = SleepInhibitor([session, logind])
    assert await inhibitor.acquire("x") is InhibitState.ACTIVE
    assert inhibitor.backends == ("session",)  # the desktop handles idle; logind does nothing
    assert members == ["Get"]
    await inhibitor.close()
