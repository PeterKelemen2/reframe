"""Sleep inhibit under failure: bad bus addresses and peers, raising backends, cancellation."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import socket
import sys
import tempfile
import threading
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.platform import dbus
from reframe.platform import sleep as sleep_module
from reframe.platform.sleep import (
    InhibitState,
    LogindBackend,
    SessionInhibitBackend,
    SleepInhibitor,
    create_sleep_inhibitor,
)

pytestmark = pytest.mark.anyio

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")

AF_UNIX: int = vars(socket).get("AF_UNIX", 0)


def _sockets() -> dict[int, str]:
    found: dict[int, str] = {}
    for name in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{name}")
        except OSError:
            continue
        if target.startswith("socket:"):
            found[int(name)] = target
    return found


@contextlib.contextmanager
def no_leaked_sockets() -> Iterator[None]:
    """Fails if the block leaves a socket open, or leaves one for the garbage collector."""
    before = set(_sockets())
    yield
    leaked = {fd: what for fd, what in _sockets().items() if fd not in before}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    unclosed = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
    assert not leaked, f"sockets left open: {leaked}"
    assert not unclosed, f"sockets left to the garbage collector: {unclosed}"


def _warnings(bus_events: list[object]) -> list[AppWarningEvent]:
    return [e for e in bus_events if isinstance(e, AppWarningEvent)]


async def _acquire_on(address: str) -> tuple[SleepInhibitor, InhibitState, list[object]]:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = SleepInhibitor(
        [SessionInhibitBackend(address=address, timeout=2.0), LogindBackend(address=address)],
        bus,
    )
    try:
        state = await inhibitor.acquire("job")
    finally:
        await inhibitor.close()
    events: list[object] = []
    while (event := sub.get_nowait()) is not None:
        events.append(event)
    return inhibitor, state, events


MALFORMED = [
    pytest.param("unix:path=%zz", id="bad-escape"),
    pytest.param("unix:path=/tmp/%ff%fe", id="escape-not-utf8"),
    pytest.param("unix:path=/tmp/reframe%00bus", id="nul-in-path"),
    pytest.param("unix:abstract=%0", id="short-escape"),
    pytest.param("unix:path=/" + "x" * 300, id="path-too-long"),
    pytest.param("unix:path=", id="empty-path"),
    pytest.param("garbage", id="no-transport"),
    pytest.param("unix:path=/nonexistent/reframe-test-bus", id="no-such-socket"),
]


@linux_only
@pytest.mark.parametrize("address", MALFORMED)
async def test_unusable_bus_address_is_unavailable_never_an_exception(address: str) -> None:
    with no_leaked_sockets():
        inhibitor, state, events = await _acquire_on(address)
    assert state is InhibitState.UNAVAILABLE
    (warning,) = _warnings(events)
    assert warning.code == "sleep_inhibit.unavailable"
    assert inhibitor.last_error is not None
    assert "session:" in inhibitor.last_error
    assert "logind:" in inhibitor.last_error
    print(inhibitor.last_error)


#: The environment is read the same way for every address: the ones that raised ValueError
#: (a bad escape, a NUL byte) and one without a transport.
MALFORMED_ENV = [
    p for p in MALFORMED if p.id in {"bad-escape", "escape-not-utf8", "nul-in-path", "no-transport"}
]


@linux_only
@pytest.mark.parametrize("address", MALFORMED_ENV)
async def test_default_inhibitor_with_malformed_environment(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", address)
    bus = EventBus()
    sub = bus.subscribe()
    with no_leaked_sockets():
        inhibitor = create_sleep_inhibitor(bus, platform="linux")
        try:
            assert await inhibitor.acquire("job") is InhibitState.UNAVAILABLE
            await inhibitor.release()
        finally:
            await inhibitor.close()
    event = sub.get_nowait()
    assert isinstance(event, AppWarningEvent)
    assert sub.get_nowait() is None


def test_parse_address_rejects_bad_escapes_with_value_error() -> None:
    for address in ("unix:path=%zz", "unix:path=%ff", "unix:abstract=%0"):
        with pytest.raises(ValueError, match="malformed D-Bus address"):
            dbus.parse_address(address)


Peer = Callable[[socket.socket], None]


def _read_line(conn: socket.socket, buf: bytearray) -> bytes:
    while b"\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError
        buf.extend(chunk)
    line, _, rest = bytes(buf).partition(b"\r\n")
    buf[:] = rest
    return line


def _read_message(conn: socket.socket, buf: bytearray) -> dbus.Message:
    while len(buf) < 16:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError
        buf.extend(chunk)
    total = dbus.message_length(bytes(buf[:16]))
    while len(buf) < total:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError
        buf.extend(chunk)
    message = dbus.decode_message(bytes(buf[:total]), [])
    del buf[:total]
    return message


def _handshake(conn: socket.socket, buf: bytearray) -> None:
    _read_line(conn, buf)  # AUTH EXTERNAL
    conn.sendall(b"OK 0123456789abcdef0123456789abcdef\r\n")
    _read_line(conn, buf)  # NEGOTIATE_UNIX_FD
    conn.sendall(b"AGREE_UNIX_FD\r\n")
    _read_line(conn, buf)  # BEGIN


def _hello(conn: socket.socket, buf: bytearray) -> None:
    hello = _read_message(conn, buf)
    conn.sendall(
        dbus.encode(
            dbus.METHOD_RETURN, 1, [(dbus.FIELD_REPLY_SERIAL, hello.serial)], [("s", ":1.9")]
        )
    )


def _retyped(message: bytes, code: int) -> bytes:
    """``message`` whose first header field (a string) gets the field code ``code``."""
    data = bytearray(message)
    data[16] = code
    return bytes(data)


def _string_field_reply(code: int, reply_serial: int | None) -> bytes:
    fields: list[tuple[int, str | int]] = [(dbus.FIELD_SENDER, "x")]
    if reply_serial is not None:
        fields.append((dbus.FIELD_REPLY_SERIAL, reply_serial))
    return _retyped(dbus.encode(dbus.METHOD_RETURN, 7, fields, [("u", 1)]), code)


def peer_closes_at_once(conn: socket.socket) -> None:
    pass


def peer_closes_after_auth(conn: socket.socket) -> None:
    _read_line(conn, bytearray())


def peer_closes_mid_negotiation(conn: socket.socket) -> None:
    buf = bytearray()
    _read_line(conn, buf)
    conn.sendall(b"OK 0123456789abcdef0123456789abcdef\r\n")
    _read_line(conn, buf)


def peer_sends_endless_garbage_line(conn: socket.socket) -> None:
    _read_line(conn, bytearray())
    conn.sendall(b"\xff\xfe" * 10000)


def peer_sends_bad_endianness(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _read_message(conn, buf)
    conn.sendall(b"X" * 32)


def peer_hello_reply_serial_is_a_string(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _read_message(conn, buf)
    conn.sendall(_string_field_reply(dbus.FIELD_REPLY_SERIAL, None))


def peer_inhibit_reply_unix_fds_is_a_string(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _hello(conn, buf)
    message = _read_message(conn, buf)
    conn.sendall(_string_field_reply(dbus.FIELD_UNIX_FDS, message.serial))


def peer_inhibit_reply_serial_is_a_string(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _hello(conn, buf)
    _read_message(conn, buf)
    conn.sendall(_string_field_reply(dbus.FIELD_REPLY_SERIAL, None))


def peer_inhibit_reply_is_cut_short(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _hello(conn, buf)
    message = _read_message(conn, buf)
    reply = dbus.encode(
        dbus.METHOD_RETURN, 7, [(dbus.FIELD_REPLY_SERIAL, message.serial)], [("s", "abc")]
    )
    conn.sendall(reply[:-3])


def peer_closes_during_the_inhibit_call(conn: socket.socket) -> None:
    buf = bytearray()
    _handshake(conn, buf)
    _hello(conn, buf)
    _read_message(conn, buf)


PEERS = [
    peer_closes_at_once,
    peer_closes_after_auth,
    peer_closes_mid_negotiation,
    peer_sends_endless_garbage_line,
    peer_sends_bad_endianness,
    peer_hello_reply_serial_is_a_string,
    peer_inhibit_reply_unix_fds_is_a_string,
    peer_inhibit_reply_serial_is_a_string,
    peer_inhibit_reply_is_cut_short,
    peer_closes_during_the_inhibit_call,
]


@contextlib.contextmanager
def bad_bus(peer: Peer) -> Iterator[str]:
    """A unix socket whose every connection is served by ``peer`` (then closed)."""
    with tempfile.TemporaryDirectory(prefix="rfbad") as tmp:
        path = str(Path(tmp) / "bus")
        server = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(8)
        server.settimeout(0.1)
        stop = threading.Event()

        def serve() -> None:
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with conn:
                    conn.settimeout(5)
                    with contextlib.suppress(OSError):
                        peer(conn)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield f"unix:path={path}"
        finally:
            stop.set()
            thread.join(timeout=10)
            server.close()


@linux_only
@pytest.mark.parametrize("peer", PEERS, ids=lambda p: p.__name__.removeprefix("peer_"))
async def test_broken_bus_peer_is_unavailable_never_an_exception(peer: Peer) -> None:
    # The leak check is outside: the fake bus's own sockets are closed when it ends.
    with no_leaked_sockets(), bad_bus(peer) as address:
        inhibitor, state, events = await _acquire_on(address)
    assert state is InhibitState.UNAVAILABLE, inhibitor.last_error
    assert len(_warnings(events)) == 1
    print(inhibitor.last_error)


@linux_only
@pytest.mark.parametrize("peer", PEERS, ids=lambda p: p.__name__.removeprefix("peer_"))
def test_broken_bus_peer_raises_only_the_documented_errors(peer: Peer) -> None:
    with (
        no_leaked_sockets(),
        bad_bus(peer) as address,
        pytest.raises((OSError, dbus.DBusError, dbus.DBusProtocolError)),
    ):
        dbus.call(
            destination="org.example",
            path="/",
            interface="org.example",
            member="M",
            address=address,
            timeout=2.0,
        )


class Exploding:
    """A backend whose hold or free raises an unexpected exception."""

    def __init__(self, *, on: str) -> None:
        self.name = f"exploding-{on}"
        self.stops = "nothing"
        self.on = on
        self.held = False

    async def hold(self, why: str) -> str | None:
        if self.on == "hold":
            raise RuntimeError("boom in hold")
        self.held = True
        return None

    async def free(self) -> None:
        self.held = False
        if self.on == "free":
            raise RuntimeError("boom in free")


async def test_a_backend_that_raises_is_a_failed_backend() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = SleepInhibitor([Exploding(on="hold")], bus)
    assert await inhibitor.acquire("job") is InhibitState.UNAVAILABLE
    assert inhibitor.last_error is not None
    assert "RuntimeError: boom in hold" in inhibitor.last_error
    assert isinstance(sub.get_nowait(), AppWarningEvent)
    await inhibitor.close()


async def test_a_free_that_raises_does_not_stop_the_others() -> None:
    first = Exploding(on="free")
    second = Exploding(on="nothing")
    inhibitor = SleepInhibitor([first, second])
    assert await inhibitor.acquire("job") is InhibitState.ACTIVE
    await inhibitor.release()
    assert not first.held
    assert not second.held
    assert inhibitor.state is InhibitState.INACTIVE
    await inhibitor.close()


class Gated:
    """A backend whose hold and free each wait for their own gate; records the order."""

    def __init__(self) -> None:
        self.name = "gated"
        self.stops = "something"
        self.calls: list[str] = []
        self.hold_gate = asyncio.Event()
        self.hold_gate.set()
        self.free_gate = asyncio.Event()
        self.free_gate.set()
        self.holding = False

    async def hold(self, why: str) -> str | None:
        self.calls.append("hold")
        await self.hold_gate.wait()
        self.holding = True
        self.calls.append("held")
        return None

    async def free(self) -> None:
        self.calls.append("free")
        await self.free_gate.wait()
        self.holding = False
        self.calls.append("freed")


async def _until(check: Callable[[], bool]) -> None:
    for _ in range(200):
        if check():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("timed out")


@pytest.mark.parametrize("how", ["release", "close"])
async def test_cancelled_release_keeps_the_lock_until_the_free_is_done(how: str) -> None:
    backend = Gated()
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire("a") is InhibitState.ACTIVE
    backend.free_gate.clear()
    ending = asyncio.ensure_future(inhibitor.release() if how == "release" else inhibitor.close())
    await _until(lambda: backend.calls[-1] == "free")
    ending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ending
    later = asyncio.ensure_future(inhibitor.acquire("b"))
    await asyncio.sleep(0.05)
    assert backend.calls == ["hold", "held", "free"]
    backend.free_gate.set()
    state = await later
    if how == "release":
        assert state is InhibitState.ACTIVE
        assert backend.calls == ["hold", "held", "free", "freed", "hold", "held"]
        assert backend.holding
        assert inhibitor.state is InhibitState.ACTIVE  # not reset by the late free
        assert inhibitor.count == 1
        await inhibitor.release()
        assert not backend.holding
    else:  # closed is final
        assert backend.calls == ["hold", "held", "free", "freed"]
        assert inhibitor.count == 0
    assert inhibitor.state is InhibitState.INACTIVE
    await inhibitor.close()


async def test_acquire_cancelled_while_waiting_for_another_leaves_no_count() -> None:
    backend = Gated()
    backend.hold_gate.clear()
    inhibitor = SleepInhibitor([backend])
    first = asyncio.ensure_future(inhibitor.acquire("a"))
    await _until(lambda: backend.calls == ["hold"])
    second = asyncio.ensure_future(inhibitor.acquire("b"))
    await asyncio.sleep(0.01)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    backend.hold_gate.set()
    assert await first is InhibitState.ACTIVE
    await asyncio.sleep(0.01)
    assert inhibitor.count == 1  # only the first one counts
    await inhibitor.release()
    assert not backend.holding
    assert backend.calls == ["hold", "held", "free", "freed"]


class SlowConnection:
    """A session connection whose ``Inhibit`` waits for ``go`` (in the worker thread)."""

    def __init__(self, go: threading.Event) -> None:
        self.go = go
        self.closed = 0
        self.members: list[str] = []

    def call(self, **kwargs: object) -> dbus.Reply:
        self.members.append(str(kwargs["member"]))
        self.go.wait(5)
        return dbus.Reply("u", [5])

    def close(self) -> None:
        self.closed += 1


async def _cancel_when(task: asyncio.Future[Any], check: Callable[[], bool]) -> None:
    await _until(check)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancelled_session_hold_closes_the_connection_it_opened() -> None:
    go = threading.Event()
    conn = SlowConnection(go)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=lambda a, t: conn)
    hold = asyncio.ensure_future(backend.hold("x"))
    await _cancel_when(hold, lambda: conn.members == ["Inhibit"])
    go.set()  # the inhibit succeeds after the caller gave up
    await _until(lambda: conn.closed == 1)
    assert not backend.held


async def test_cancelled_session_free_still_ends_and_closes() -> None:
    go = threading.Event()
    go.set()
    conn = SlowConnection(go)
    backend = SessionInhibitBackend(address="unix:path=/fake", connect=lambda a, t: conn)
    assert await backend.hold("x") is None
    go.clear()
    free = asyncio.ensure_future(backend.free())
    await _cancel_when(free, lambda: conn.members == ["Inhibit", "UnInhibit"])
    go.set()
    await _until(lambda: conn.closed == 1)


@linux_only
async def test_cancelled_logind_hold_closes_the_lock_fd() -> None:
    go = threading.Event()
    read_end, write_end = os.pipe()

    def call(**kwargs: object) -> dbus.Reply:
        go.wait(5)
        return dbus.Reply("h", [0], [read_end])

    backend = LogindBackend(call=call)
    hold = asyncio.ensure_future(backend.hold("x"))
    await asyncio.sleep(0.02)
    hold.cancel()
    with pytest.raises(asyncio.CancelledError):
        await hold
    go.set()

    def closed() -> bool:
        try:
            os.fstat(read_end)
        except OSError:
            return True
        return False

    await _until(closed)
    assert backend.fd is None
    os.close(write_end)


async def test_cancelled_windows_hold_clears_the_state_and_ends_the_thread() -> None:
    from reframe.platform.sleep import (
        ES_CONTINUOUS,
        ES_SYSTEM_REQUIRED,
        WindowsExecutionStateBackend,
    )

    go = threading.Event()
    flags: list[int] = []

    class SlowKernel32:
        def SetThreadExecutionState(self, value: int) -> int:
            flags.append(value)
            go.wait(5)
            return ES_CONTINUOUS

    backend = WindowsExecutionStateBackend(SlowKernel32(), last_error=lambda: 0)
    hold = asyncio.ensure_future(backend.hold("x"))
    await _cancel_when(hold, lambda: flags == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED])
    go.set()
    await _until(lambda: flags == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS])
    assert backend.thread is None
    for thread in threading.enumerate():
        if thread.name == "reframe-sleep-inhibit":
            thread.join(5)
            assert not thread.is_alive()


async def test_in_thread_discards_a_result_that_came_just_before_the_cancel() -> None:
    from reframe.platform.sleep import _in_thread

    go = threading.Event()
    discarded: list[str] = []

    def work() -> str:
        go.wait(5)
        return "socket"

    def discard(result: str) -> None:
        discarded.append(result)

    task = asyncio.ensure_future(_in_thread(work, discard))
    await asyncio.sleep(0.01)
    go.set()
    # Block the loop on purpose: the thread finishes before the task hears of it.
    threading.Event().wait(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert discarded == ["socket"]


def _held_backends(inhibitor: SleepInhibitor) -> tuple[str, ...]:
    return inhibitor.backends  # through a function, so that mypy does not narrow it


async def test_take_cut_short_by_loop_shutdown_keeps_what_it_holds_until_close() -> None:
    """A cancelled take undoes its count, keeps the locks it took, and close() frees them."""
    first = Gated()
    second = Gated()
    second.name = "second"
    second.hold_gate.clear()
    inhibitor = SleepInhibitor([first, second])
    caller = asyncio.ensure_future(inhibitor.acquire("a"))
    await _until(lambda: second.calls == ["hold"])
    (task,) = [t for t in sleep_module._background if not t.done()]
    task.cancel()  # what asyncio.run does to the remaining tasks at shutdown
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert inhibitor.count == 0
    assert inhibitor.backends == ("gated",)
    second.hold_gate.set()
    assert await inhibitor.acquire("b") is InhibitState.ACTIVE
    assert first.calls == ["hold", "held"]  # not taken twice
    assert _held_backends(inhibitor) == ("gated", "second")
    await inhibitor.close()
    assert not first.holding
    assert not second.holding
