"""reframe.platform.dbus: the minimal D-Bus client that the logind backend uses."""

from __future__ import annotations

import contextlib
import functools
import os
import socket
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reframe.platform import dbus
from reframe_testing.fake_dbus import AF_UNIX, handshake, open_fds, read_message, serve_unix

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")

# The Inhibit call (serial 2), as jeepney 0.9.0 serialises it.
INHIBIT_CALL = bytes.fromhex(
    "6c0100012e000000020000008200000001016f00170000002f6f72672f667265656465736b746f70"
    "2f6c6f67696e3100020173001e0000006f72672e667265656465736b746f702e6c6f67696e312e4d"
    "616e6167657200000301730007000000496e68696269740006017300160000006f72672e66726565"
    "6465736b746f702e6c6f67696e310000080167000473737373000000000000000a000000736c6565"
    "703a69646c6500000700000052656672616d6500030000007768790005000000626c6f636b00"
)


# The session inhibit calls (serial 2), as jeepney 0.9.0 serialises them.
PM_INHIBIT_CALL = bytes.fromhex(
    "6c0100011900000002000000b000000001016f00280000002f6f72672f667265656465736b746f702f"
    "506f7765724d616e6167656d656e742f496e6869626974000000000000000002017300270000006f72"
    "672e667265656465736b746f702e506f7765724d616e6167656d656e742e496e686962697400030173"
    "0007000000496e68696269740006017300270000006f72672e667265656465736b746f702e506f7765"
    "724d616e6167656d656e742e496e68696269740008016700027373000700000052656672616d650008"
    "000000456e636f64696e6700"
)
PORTAL_INHIBIT_CALL = bytes.fromhex(
    "6c0100012d000000020000009500000001016f001f0000002f6f72672f667265656465736b746f702f"
    "706f7274616c2f6465736b746f7000020173001e0000006f72672e667265656465736b746f702e706f"
    "7274616c2e496e686962697400000301730007000000496e686962697400060173001e0000006f7267"
    "2e667265656465736b746f702e706f7274616c2e4465736b746f70000008016700077375617b73767d"
    "000000000000000000000000040000001d00000006000000726561736f6e0001730000000800000045"
    "6e636f64696e6700"
)


def _inhibit_call() -> bytes:
    return dbus.encode_method_call(
        serial=2,
        path="/org/freedesktop/login1",
        interface="org.freedesktop.login1.Manager",
        member="Inhibit",
        destination="org.freedesktop.login1",
        args=["sleep:idle", "Reframe", "why", "block"],
    )


# A Linux-only name, looked up at run time so that mypy --platform win32 accepts the module.
SCM_RIGHTS: int = vars(socket).get("SCM_RIGHTS", 0)


def _getuid() -> int:
    return int(vars(os)["getuid"]())


def _send_fds(conn: socket.socket, data: bytes, fds: list[int]) -> None:
    payload = struct.pack(f"{len(fds)}i", *fds)
    send = getattr(conn, "sendmsg")  # noqa: B009 - not in the Windows stubs
    send([data], [(socket.SOL_SOCKET, SCM_RIGHTS, payload)])


def _is_closed(connection: dbus.Connection) -> bool:
    return connection.closed  # through a function, so that mypy does not narrow it


def test_method_call_matches_the_reference_bytes() -> None:
    message = _inhibit_call()
    assert message == INHIBIT_CALL
    assert message[2] == 0  # no flags: never ALLOW_INTERACTIVE_AUTHORIZATION (0x4)


def test_encoded_call_decodes_back() -> None:
    message = _inhibit_call()
    assert dbus.message_length(message[:16]) == len(message)
    parsed = dbus.decode_message(message, [])
    assert parsed.msg_type == dbus.METHOD_CALL
    assert parsed.serial == 2
    assert parsed.signature == "ssss"
    assert parsed.body == ["sleep:idle", "Reframe", "why", "block"]
    assert parsed.fields[dbus.FIELD_MEMBER] == "Inhibit"
    assert parsed.fields[dbus.FIELD_PATH] == "/org/freedesktop/login1"
    assert parsed.reply_serial is None


def test_other_body_types_and_unknown_signatures() -> None:
    raw = dbus.encode(dbus.SIGNAL, 3, [(dbus.FIELD_SIGNATURE, "ibyx")])
    parsed = dbus.decode_message(raw, [])
    assert parsed.body == []  # unsupported types: the body is skipped, not misread
    reply = dbus.encode(dbus.METHOD_RETURN, 4, [(dbus.FIELD_REPLY_SERIAL, 2)], [("u", 1)])
    reply = reply.replace(b"\x08\x01g\x00\x01u\x00", b"\x08\x01g\x00\x01b\x00")
    assert dbus.decode_message(reply, []).body == [1]  # a boolean, as HasInhibit returns
    with pytest.raises(ValueError, match="cannot contain NUL"):
        dbus.encode(dbus.METHOD_CALL, 1, [], [("s", "a\0b")])
    with pytest.raises(ValueError, match="unsupported type"):
        dbus.encode(dbus.METHOD_CALL, 1, [], [("x", 1)])


def test_bad_messages_raise_protocol_errors() -> None:
    good = _inhibit_call()
    with pytest.raises(dbus.DBusProtocolError, match="endianness"):
        dbus.decode_message(b"X" + good[1:], [])
    with pytest.raises(dbus.DBusProtocolError, match="endianness"):
        dbus.decode_message(b"B" + good[1:], [])
    with pytest.raises(dbus.DBusProtocolError, match="protocol version"):
        dbus.decode_message(good[:3] + b"\x02" + good[4:], [])
    with pytest.raises(dbus.DBusProtocolError, match="ends early"):
        dbus.decode_message(good[:40], [])
    huge = good[:4] + struct.pack("<I", 2**30) + good[8:16]
    with pytest.raises(dbus.DBusProtocolError, match="too long"):
        dbus.message_length(huge)
    # A header field with a type that header fields never use.
    weird = dbus.encode(dbus.SIGNAL, 1, [])
    fields = struct.pack("<B", 1) + b"\x01x\x00" + b"\0" * 4 + struct.pack("<q", 1)
    raw = weird[:12] + struct.pack("<I", len(fields)) + fields
    with pytest.raises(dbus.DBusProtocolError, match="unsupported type 'x'"):
        dbus.decode_message(raw, [])


def _is_open(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


def test_a_bad_header_closes_every_queued_descriptor() -> None:
    weird = dbus.encode(dbus.SIGNAL, 1, [])
    fields = struct.pack("<B", 1) + b"\x01x\x00" + b"\0" * 4 + struct.pack("<q", 1)
    raw = weird[:12] + struct.pack("<I", len(fields)) + fields
    queued = list(os.pipe())
    fds = list(queued)
    try:
        with pytest.raises(dbus.DBusProtocolError, match="unsupported type 'x'"):
            dbus.decode_message(raw, fds)
        assert fds == []
        assert not any(_is_open(fd) for fd in queued)
    finally:
        for fd in queued:
            with contextlib.suppress(OSError):
                os.close(fd)


def test_a_bad_body_closes_only_the_message_descriptors() -> None:
    head = dbus.encode(
        dbus.METHOD_RETURN,
        3,
        [(dbus.FIELD_REPLY_SERIAL, 2), (dbus.FIELD_SIGNATURE, "v"), (dbus.FIELD_UNIX_FDS, 1)],
    )
    raw = head[:4] + struct.pack("<I", 4) + head[8:] + b"\x02as\x00"
    own, nxt = os.pipe()
    fds = [own, nxt]
    try:
        with pytest.raises(dbus.DBusProtocolError, match="unsupported variant type"):
            dbus.decode_message(raw, fds)
        assert fds == [nxt]
        assert not _is_open(own)
        assert _is_open(nxt)
    finally:
        for fd in (own, nxt):
            with contextlib.suppress(OSError):
                os.close(fd)


def test_parse_address() -> None:
    assert dbus.parse_address("unix:path=/run/dbus/system_bus_socket") == [
        "/run/dbus/system_bus_socket"
    ]
    assert dbus.parse_address("tcp:host=x,port=1;unix:abstract=/tmp/dbus-x,guid=1") == [
        b"\0/tmp/dbus-x"
    ]
    assert dbus.parse_address("unix:path=/a%20b;unix:runtime=yes") == ["/a b"]
    assert dbus.parse_address("") == []


def test_system_bus_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBUS_SYSTEM_BUS_ADDRESS", raising=False)
    assert dbus.system_bus_address() == "unix:path=/run/dbus/system_bus_socket"
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/x")
    assert dbus.system_bus_address() == "unix:path=/x"


@dataclass
class Scenario:
    """What the fake bus does. ``inhibit`` answers every call after ``Hello``;
    ``stray_fd`` first sends a reply to a call never made, with a file descriptor."""

    auth: str = "OK 0123456789abcdef0123456789abcdef"
    fd_answer: str = "AGREE_UNIX_FD"
    hello_error: bool = False
    inhibit: str = "fd"
    stray_fd: bool = False
    received: list[dbus.Message] = field(default_factory=list)
    auth_lines: list[str] = field(default_factory=list)


def _reply(
    serial: int, reply_serial: int, body: list[tuple[str, str | int]], fds: int = 0
) -> bytes:
    fields: list[tuple[int, str | int]] = [
        (dbus.FIELD_REPLY_SERIAL, reply_serial),
        (dbus.FIELD_SENDER, "org.freedesktop.DBus"),
    ]
    if fds:
        fields.append((dbus.FIELD_UNIX_FDS, fds))
    return dbus.encode(dbus.METHOD_RETURN, serial, fields, body)


def _error(serial: int, reply_serial: int, name: str, text: str) -> bytes:
    return dbus.encode(
        dbus.ERROR,
        serial,
        [(dbus.FIELD_REPLY_SERIAL, reply_serial), (dbus.FIELD_ERROR_NAME, name)],
        [("s", text)],
    )


def _serve(scenario: Scenario, conn: socket.socket, stop: threading.Event) -> None:
    buf = bytearray()
    try:
        if not handshake(
            conn, buf, auth=scenario.auth, fd_answer=scenario.fd_answer, seen=scenario.auth_lines
        ):
            return
        while not stop.is_set():
            message = read_message(conn, buf)
            scenario.received.append(message)
            if message.serial == 1:
                if scenario.hello_error:
                    conn.sendall(_error(1, 1, "org.freedesktop.DBus.Error.Failed", "no"))
                    continue
                conn.sendall(_reply(1, 1, [("s", ":1.42")]))
                signal = dbus.encode(
                    dbus.SIGNAL,
                    2,
                    [
                        (dbus.FIELD_PATH, "/org/freedesktop/DBus"),
                        (dbus.FIELD_INTERFACE, "org.freedesktop.DBus"),
                        (dbus.FIELD_MEMBER, "NameAcquired"),
                    ],
                    [("s", ":1.42")],
                )
                conn.sendall(signal)
                # A reply to a call that was never made: ignored.
                conn.sendall(_reply(3, 99, [("s", "x")]))
                continue
            if scenario.stray_fd:
                stray_r, stray_w = os.pipe()
                try:
                    _send_fds(conn, _reply(90, 77, [("h", 0)], fds=1), [stray_r])
                finally:
                    os.close(stray_r)
                    os.close(stray_w)
            if scenario.inhibit == "fd":
                read_end, write_end = os.pipe()
                try:
                    data = _reply(100 + message.serial, message.serial, [("h", 0)], fds=1)
                    _send_fds(conn, data, [read_end])
                finally:
                    os.close(read_end)
                    os.close(write_end)
            elif scenario.inhibit == "two_fds":
                pipes = [os.pipe(), os.pipe()]
                try:
                    data = _reply(100 + message.serial, message.serial, [("h", 1)], fds=2)
                    _send_fds(conn, data, [pipes[0][0], pipes[1][0]])
                finally:
                    for a, b in pipes:
                        os.close(a)
                        os.close(b)
            elif scenario.inhibit == "error":
                conn.sendall(
                    _error(
                        100 + message.serial,
                        message.serial,
                        "org.freedesktop.DBus.Error.AccessDenied",
                        "Permission denied",
                    )
                )
            elif scenario.inhibit == "close":
                return
            else:  # silent
                stop.wait(5)
                return
    except (ConnectionError, OSError):
        return


def fake_bus(scenario: Scenario) -> contextlib.AbstractContextManager[str]:
    return serve_unix(functools.partial(_serve, scenario))


def _call(address: str, timeout: float = 5.0) -> dbus.Reply:
    return dbus.call(
        destination="org.freedesktop.login1",
        path="/org/freedesktop/login1",
        interface="org.freedesktop.login1.Manager",
        member="Inhibit",
        args=["sleep:idle", "Reframe", "why", "block"],
        address=address,
        timeout=timeout,
    )


def test_call_returns_the_file_descriptor_and_leaks_nothing() -> None:
    scenario = Scenario()
    before = open_fds()
    with fake_bus(scenario) as address:
        reply = _call(address)
    assert reply.signature == "h"
    assert reply.body == [0]
    (fd,) = reply.fds
    assert not os.get_inheritable(fd)  # received with MSG_CMSG_CLOEXEC
    os.fstat(fd)
    os.close(fd)
    assert open_fds() == before
    uid_hex = str(_getuid()).encode().hex()
    assert scenario.auth_lines == [f"\0AUTH EXTERNAL {uid_hex}", "NEGOTIATE_UNIX_FD", "BEGIN"]
    hello, inhibit = scenario.received
    assert hello.fields[dbus.FIELD_MEMBER] == "Hello"
    assert inhibit.body == ["sleep:idle", "Reframe", "why", "block"]
    assert inhibit.fields[dbus.FIELD_DESTINATION] == "org.freedesktop.login1"


def test_call_with_extra_descriptors_returns_them_all() -> None:
    before = open_fds()
    with fake_bus(Scenario(inhibit="two_fds")) as address:
        reply = _call(address)
    assert reply.body == [1]
    assert len(reply.fds) == 2
    for fd in reply.fds:
        os.close(fd)
    assert open_fds() == before


def test_refused_authentication_raises_protocol_error() -> None:
    with (
        fake_bus(Scenario(auth="REJECTED EXTERNAL")) as address,
        pytest.raises(dbus.DBusProtocolError, match="authentication refused"),
    ):
        _call(address)


def test_bus_without_fd_passing_raises_protocol_error() -> None:
    with (
        fake_bus(Scenario(fd_answer="ERROR")) as address,
        pytest.raises(dbus.DBusProtocolError, match="cannot pass file descriptors"),
    ):
        _call(address)


def test_connection_closed_before_the_reply() -> None:
    with (
        fake_bus(Scenario(inhibit="close")) as address,
        pytest.raises(ConnectionError, match="closed the connection"),
    ):
        _call(address)


def test_silent_bus_times_out() -> None:
    before = open_fds()
    with fake_bus(Scenario(inhibit="silent")) as address, pytest.raises(TimeoutError):
        _call(address, timeout=0.3)
    assert open_fds() == before


def test_missing_socket_and_unusable_address() -> None:
    with pytest.raises(FileNotFoundError):
        _call("unix:path=/nonexistent/reframe-test-bus")
    with pytest.raises(OSError, match="no usable unix: address"):
        _call("tcp:host=localhost,port=1")


def test_abstract_socket_address_connects() -> None:
    name = f"reframe-test-{os.getpid()}"
    server = socket.socket(AF_UNIX, socket.SOCK_STREAM)
    server.bind(b"\0" + name.encode())
    server.listen(1)
    scenario = Scenario()
    stop = threading.Event()

    def accept() -> None:
        conn, _ = server.accept()
        with conn:
            _serve(scenario, conn, stop)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        reply = _call(f"unix:abstract={name}")
        for fd in reply.fds:
            os.close(fd)
    finally:
        stop.set()
        thread.join(timeout=10)
        server.close()
    assert reply.body == [0]


def test_session_inhibit_calls_match_the_reference_bytes() -> None:
    pm = dbus.encode_method_call(
        serial=2,
        path="/org/freedesktop/PowerManagement/Inhibit",
        interface="org.freedesktop.PowerManagement.Inhibit",
        member="Inhibit",
        destination="org.freedesktop.PowerManagement.Inhibit",
        args=["Reframe", "Encoding"],
    )
    assert pm == PM_INHIBIT_CALL
    portal = dbus.encode_method_call(
        serial=2,
        path="/org/freedesktop/portal/desktop",
        interface="org.freedesktop.portal.Inhibit",
        member="Inhibit",
        destination="org.freedesktop.portal.Desktop",
        body=[("s", ""), ("u", 4), ("a{sv}", {"reason": "Encoding"})],
    )
    assert portal == PORTAL_INHIBIT_CALL
    assert portal[2] == 0  # no ALLOW_INTERACTIVE_AUTHORIZATION
    with pytest.raises(ValueError, match="unsupported type 'u' for str"):
        dbus.encode(dbus.METHOD_CALL, 1, [], [("u", "4")])


def test_variant_property_value_decodes() -> None:
    head = dbus.encode(
        dbus.METHOD_RETURN, 3, [(dbus.FIELD_REPLY_SERIAL, 2), (dbus.FIELD_SIGNATURE, "v")]
    )
    body = b"\x01s\x00\x00" + struct.pack("<I", 6) + b"ignore\x00"
    raw = head[:4] + struct.pack("<I", len(body)) + head[8:] + body
    parsed = dbus.decode_message(raw, [])
    assert parsed.body == ["ignore"]
    nested = head[:4] + struct.pack("<I", 4) + head[8:] + b"\x02as\x00"
    with pytest.raises(dbus.DBusProtocolError, match="unsupported variant type 'as'"):
        dbus.decode_message(nested, [])


def test_session_bus_address(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    assert dbus.session_bus_address() == "unix:path=/run/user/1000/bus"
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert dbus.session_bus_address() is None  # no bus socket there
    (tmp_path / "bus").touch()
    assert dbus.session_bus_address() == f"unix:path={tmp_path}/bus"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert dbus.session_bus_address() is None


def test_connection_stays_open_for_several_calls_and_closes() -> None:
    scenario = Scenario(stray_fd=True)
    before = open_fds()
    with fake_bus(scenario) as address:
        connection = dbus.Connection.open(address, timeout=5.0)
        assert not connection.closed
        replies = [
            connection.call(
                destination="org.example",
                path="/org/example",
                interface="org.example.Iface",
                member=f"Call{i}",
                body=[("u", i)],
                timeout=5.0,
            )
            for i in range(3)
        ]
        open_now = open_fds()
        connection.close()
        connection.close()  # idempotent
        assert _is_closed(connection)
        with pytest.raises(OSError, match="closed"):
            connection.call(destination="x.y", path="/", interface="x.y", member="Z")
    assert [m.serial for m in scenario.received] == [1, 2, 3, 4]
    assert [m.fields[dbus.FIELD_MEMBER] for m in scenario.received[1:]] == [
        "Call0",
        "Call1",
        "Call2",
    ]
    assert [m.body for m in scenario.received[1:]] == [[0], [1], [2]]
    # The fake bus's two sockets, our socket and one fd per reply; the fds of the three
    # stray replies were closed at once.
    assert len(open_now - before) == 2 + 1 + 3
    for reply in replies:
        (fd,) = reply.fds
        os.close(fd)
    assert open_fds() == before


def test_connection_close_after_an_error_reply_frees_the_socket() -> None:
    before = open_fds()
    with fake_bus(Scenario(inhibit="error")) as address:
        connection = dbus.Connection.open(address)
        try:
            with pytest.raises(dbus.DBusError) as info:
                connection.call(destination="x.y", path="/", interface="x.y", member="Z")
        finally:
            connection.close()
        assert connection.closed
    assert info.value.name == "org.freedesktop.DBus.Error.AccessDenied"
    assert info.value.message == "Permission denied"
    assert str(info.value) == "org.freedesktop.DBus.Error.AccessDenied: Permission denied"
    assert open_fds() == before


def test_connection_open_failure_closes_the_socket() -> None:
    before = open_fds()
    with (
        fake_bus(Scenario(hello_error=True)) as address,
        pytest.raises(dbus.DBusError, match=r"Error\.Failed: no"),
    ):
        dbus.Connection.open(address)
    assert open_fds() == before
