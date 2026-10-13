"""reframe.platform.dbus: the minimal D-Bus client that the logind backend uses.

Marshalling is checked against a golden message (the same bytes as jeepney 0.9.0 produces
for this call, see testdata/README.md "Sleep inhibit (C-14)"); the connection is checked
against a fake bus (a thread on a unix socket) that speaks the same protocol: success with a
file descriptor, error replies, refused authentication, no fd passing, timeouts. The real
system bus is in ``test_sleep_real.py``.
"""

from __future__ import annotations

import contextlib
import os
import socket
import struct
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reframe.platform import dbus

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")

# The Inhibit call (serial 2), as jeepney 0.9.0 serialises it (checked byte for byte).
INHIBIT_CALL = bytes.fromhex(
    "6c0100012e000000020000008200000001016f00170000002f6f72672f667265656465736b746f70"
    "2f6c6f67696e3100020173001e0000006f72672e667265656465736b746f702e6c6f67696e312e4d"
    "616e6167657200000301730007000000496e68696269740006017300160000006f72672e66726565"
    "6465736b746f702e6c6f67696e310000080167000473737373000000000000000a000000736c6565"
    "703a69646c6500000700000052656672616d6500030000007768790005000000626c6f636b00"
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


# Linux-only names, looked up at run time so that mypy --platform win32 accepts the module.
AF_UNIX: int = vars(socket).get("AF_UNIX", 0)
SCM_RIGHTS: int = vars(socket).get("SCM_RIGHTS", 0)


def _getuid() -> int:
    return int(vars(os)["getuid"]())


def _send_fds(conn: socket.socket, data: bytes, fds: list[int]) -> None:
    payload = struct.pack(f"{len(fds)}i", *fds)
    send = getattr(conn, "sendmsg")  # noqa: B009 - not in the Windows stubs
    send([data], [(socket.SOL_SOCKET, SCM_RIGHTS, payload)])


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


# --------------------------------------------------------------------------- marshalling


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


def test_big_endian_messages_decode() -> None:
    raw = dbus.encode(
        dbus.METHOD_RETURN,
        7,
        [(dbus.FIELD_REPLY_SERIAL, 2), (dbus.FIELD_UNIX_FDS, 1)],
        [("h", 0)],
        endian=">",
    )
    assert raw[0:1] == b"B"
    fds = [100, 101]
    parsed = dbus.decode_message(raw, fds)
    assert parsed.reply_serial == 2
    assert parsed.body == [0]
    assert parsed.fds == [100]
    assert fds == [101]  # the next message's descriptors stay queued


def test_other_body_types_and_unknown_signatures() -> None:
    raw = dbus.encode(dbus.SIGNAL, 3, [(dbus.FIELD_SIGNATURE, "ibyx")])
    parsed = dbus.decode_message(raw, [])
    assert parsed.body == []  # 'x' is not supported: the body is skipped, not misread
    with pytest.raises(ValueError, match="cannot contain NUL"):
        dbus.encode(dbus.METHOD_CALL, 1, [], [("s", "a\0b")])
    with pytest.raises(ValueError, match="unsupported type"):
        dbus.encode(dbus.METHOD_CALL, 1, [], [("x", 1)])


def test_bad_messages_raise_protocol_errors() -> None:
    good = _inhibit_call()
    with pytest.raises(dbus.DBusProtocolError, match="endianness"):
        dbus.decode_message(b"X" + good[1:], [])
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


# --------------------------------------------------------------------------- fake bus


@dataclass
class Scenario:
    """What the fake bus does. ``inhibit`` answers the Inhibit call (serial 2)."""

    auth: str = "OK 0123456789abcdef0123456789abcdef"
    fd_answer: str = "AGREE_UNIX_FD"
    hello_error: bool = False
    inhibit: str = "fd"  # fd | error | close | silent | two_fds
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


def _serve(server: socket.socket, scenario: Scenario, stop: threading.Event) -> None:
    conn, _ = server.accept()
    with conn:
        buf = bytearray()

        def line() -> str:
            while b"\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    raise ConnectionError
                buf.extend(chunk)
            text, _, rest = bytes(buf).partition(b"\r\n")
            buf[:] = rest
            return text.decode()

        try:
            first = line()
            scenario.auth_lines.append(first)
            conn.sendall(scenario.auth.encode() + b"\r\n")
            if not scenario.auth.startswith("OK"):
                return
            negotiate = line()
            scenario.auth_lines.append(negotiate)
            conn.sendall(scenario.fd_answer.encode() + b"\r\n")
            if scenario.fd_answer != "AGREE_UNIX_FD":
                return
            scenario.auth_lines.append(line())  # BEGIN
            while not stop.is_set():
                while len(buf) < 16:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf.extend(chunk)
                total = dbus.message_length(bytes(buf[:16]))
                while len(buf) < total:
                    buf.extend(conn.recv(4096))
                message = dbus.decode_message(bytes(buf[:total]), [])
                del buf[:total]
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
                if scenario.inhibit == "fd":
                    read_end, write_end = os.pipe()
                    try:
                        data = _reply(4, 2, [("h", 0)], fds=1)
                        _send_fds(conn, data, [read_end])
                    finally:
                        os.close(read_end)
                        os.close(write_end)
                elif scenario.inhibit == "two_fds":
                    pipes = [os.pipe(), os.pipe()]
                    try:
                        data = _reply(4, 2, [("h", 1)], fds=2)
                        _send_fds(conn, data, [pipes[0][0], pipes[1][0]])
                    finally:
                        for a, b in pipes:
                            os.close(a)
                            os.close(b)
                elif scenario.inhibit == "error":
                    conn.sendall(
                        _error(
                            4,
                            2,
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


@contextlib.contextmanager
def fake_bus(scenario: Scenario) -> Iterator[str]:
    with tempfile.TemporaryDirectory(prefix="rfbus") as tmp:
        path = str(Path(tmp) / "bus")
        server = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        stop = threading.Event()
        thread = threading.Thread(target=_serve, args=(server, scenario, stop), daemon=True)
        thread.start()
        try:
            yield f"unix:path={path}"
        finally:
            stop.set()
            thread.join(timeout=10)
            server.close()


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
    before = _open_fds()
    with fake_bus(scenario) as address:
        reply = _call(address)
    assert reply.signature == "h"
    assert reply.body == [0]
    (fd,) = reply.fds
    assert not os.get_inheritable(fd)  # received with MSG_CMSG_CLOEXEC
    os.fstat(fd)
    os.close(fd)
    assert _open_fds() == before
    uid_hex = str(_getuid()).encode().hex()
    assert scenario.auth_lines == [f"\0AUTH EXTERNAL {uid_hex}", "NEGOTIATE_UNIX_FD", "BEGIN"]
    hello, inhibit = scenario.received
    assert hello.fields[dbus.FIELD_MEMBER] == "Hello"
    assert inhibit.body == ["sleep:idle", "Reframe", "why", "block"]
    assert inhibit.fields[dbus.FIELD_DESTINATION] == "org.freedesktop.login1"


def test_call_with_extra_descriptors_returns_them_all() -> None:
    before = _open_fds()
    with fake_bus(Scenario(inhibit="two_fds")) as address:
        reply = _call(address)
    assert reply.body == [1]
    assert len(reply.fds) == 2
    for fd in reply.fds:
        os.close(fd)
    assert _open_fds() == before


def test_error_reply_raises_dbus_error() -> None:
    before = _open_fds()
    with fake_bus(Scenario(inhibit="error")) as address, pytest.raises(dbus.DBusError) as info:
        _call(address)
    assert info.value.name == "org.freedesktop.DBus.Error.AccessDenied"
    assert info.value.message == "Permission denied"
    assert str(info.value) == "org.freedesktop.DBus.Error.AccessDenied: Permission denied"
    assert _open_fds() == before


def test_hello_error_raises() -> None:
    with (
        fake_bus(Scenario(hello_error=True)) as address,
        pytest.raises(dbus.DBusError, match=r"Error\.Failed: no"),
    ):
        _call(address)


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
    before = _open_fds()
    with fake_bus(Scenario(inhibit="silent")) as address, pytest.raises(TimeoutError):
        _call(address, timeout=0.3)
    assert _open_fds() == before


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
    thread = threading.Thread(target=_serve, args=(server, scenario, stop), daemon=True)
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
