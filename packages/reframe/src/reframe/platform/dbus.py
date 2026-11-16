"""A minimal, blocking D-Bus client for the sleep inhibit calls.

It uses the standard library only: the calls need a small, fixed subset of the protocol
(https://dbus.freedesktop.org/doc/dbus-specification.html), so no D-Bus library is needed. It
connects to a ``unix:`` bus, authenticates with ``EXTERNAL``, negotiates file descriptors and
sends method calls with simple arguments. Received descriptors are close-on-exec
(``MSG_CMSG_CLOEXEC``): a child process must never inherit a duplicate that keeps a lock alive.

No message sets ``ALLOW_INTERACTIVE_AUTHORIZATION``: a background queue must never make polkit
ask the user for a password.

Errors: :class:`DBusError` for an error reply, ``OSError`` (``TimeoutError`` included) when the
bus cannot be reached or closes the connection, :class:`DBusProtocolError` for anything this
client does not understand, and ``ValueError`` for a malformed address or an argument that
cannot be sent. Nothing else is raised, and the socket is closed whenever
:meth:`Connection.open` or :func:`call` raises.

Linux only: the module imports on Windows, but connecting raises ``OSError`` there.
"""

from __future__ import annotations

import array
import contextlib
import os
import socket
import struct
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

__all__ = [
    "DEFAULT_SYSTEM_BUS",
    "Connection",
    "DBusError",
    "DBusProtocolError",
    "Message",
    "Reply",
    "call",
    "decode_message",
    "encode",
    "encode_method_call",
    "message_length",
    "parse_address",
    "session_bus_address",
    "system_bus_address",
]

DEFAULT_SYSTEM_BUS = "unix:path=/run/dbus/system_bus_socket"
"""The spec says ``/var/run/dbus/system_bus_socket``; ``/var/run`` links to ``/run``."""

METHOD_CALL = 1
METHOD_RETURN = 2
ERROR = 3
SIGNAL = 4

FIELD_PATH = 1
FIELD_INTERFACE = 2
FIELD_MEMBER = 3
FIELD_ERROR_NAME = 4
FIELD_REPLY_SERIAL = 5
FIELD_DESTINATION = 6
FIELD_SENDER = 7
FIELD_SIGNATURE = 8
FIELD_UNIX_FDS = 9

_FIELD_TYPES = {
    FIELD_PATH: "o",
    FIELD_INTERFACE: "s",
    FIELD_MEMBER: "s",
    FIELD_ERROR_NAME: "s",
    FIELD_REPLY_SERIAL: "u",
    FIELD_DESTINATION: "s",
    FIELD_SENDER: "s",
    FIELD_SIGNATURE: "g",
    FIELD_UNIX_FDS: "u",
}

#: A body value: a string (``s``, ``o``, ``g``), a number (``u``, ``h``) or an ``a{sv}``
#: whose values are strings.
Value = str | int | dict[str, str]

MAX_MESSAGE = 128 * 2**20  # the spec's maximum message size
MAX_FDS = 16  # file descriptors accepted per read (the Inhibit reply carries one)


class DBusError(Exception):
    """The remote side answered with an ``ERROR`` message."""

    def __init__(self, name: str, message: str) -> None:
        super().__init__(f"{name}: {message}" if message else name)
        self.name = name
        self.message = message


class DBusProtocolError(Exception):
    """The bus sent something this client cannot parse, or refused the authentication."""


@dataclass(slots=True)
class Reply:
    """A ``METHOD_RETURN``: the body values and the file descriptors that came with it.

    The caller owns ``fds`` and must close them. ``h`` values in ``body`` are indexes into
    ``fds``.
    """

    signature: str
    body: list[str | int]
    fds: list[int] = field(default_factory=list)


def system_bus_address() -> str:
    """``DBUS_SYSTEM_BUS_ADDRESS`` if set, else the default system bus socket."""
    return os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or DEFAULT_SYSTEM_BUS


def session_bus_address() -> str | None:
    """``DBUS_SESSION_BUS_ADDRESS`` if set, else ``$XDG_RUNTIME_DIR/bus`` if that socket
    exists (the systemd user bus, as sd-bus does), else ``None`` (no session bus)."""
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if address:
        return address
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.exists(os.path.join(runtime, "bus")):
        return "unix:path=" + os.path.join(runtime, "bus")
    return None


def parse_address(address: str) -> list[str | bytes]:
    """The socket addresses of a D-Bus address list that this client can use.

    ``unix:path=/x`` gives ``"/x"``; ``unix:abstract=x`` gives ``b"\\0x"``. Other transports
    are skipped. Raises ``ValueError`` ("malformed D-Bus address") for a ``%`` that is not
    followed by two hex digits, an escaped value that is not UTF-8, or a path with a NUL.
    """
    result: list[str | bytes] = []
    for entry in address.split(";"):
        transport, _, params = entry.partition(":")
        if transport != "unix":
            continue
        values = dict(p.partition("=")[::2] for p in params.split(",") if p)
        try:
            if "path" in values:
                path = _unescape(values["path"])
                if "\0" in path:
                    raise ValueError("a path cannot contain NUL")
                result.append(path)
            elif "abstract" in values:
                result.append(b"\0" + _unescape(values["abstract"]).encode())
        except ValueError as exc:
            raise ValueError(f"malformed D-Bus address {address!r}: {exc}") from None
    return result


_HEX = frozenset(b"0123456789abcdefABCDEF")


def _unescape(value: str) -> str:
    """Undo the ``%xx`` escaping of D-Bus address values (``ValueError`` if malformed)."""
    out = bytearray()
    i = 0
    raw = value.encode()
    while i < len(raw):
        if raw[i] == 0x25:  # '%xx'
            digits = raw[i + 1 : i + 3]
            if len(digits) != 2 or not _HEX.issuperset(digits):
                raise ValueError(f"bad escape {raw[i : i + 3].decode(errors='replace')!r}")
            out.append(int(digits, 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    try:
        return out.decode()
    except UnicodeDecodeError:
        raise ValueError("an escaped value is not UTF-8") from None


class _Writer:
    """Marshals values; alignment counts from the start of the message."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def align(self, n: int) -> None:
        self.buf += b"\0" * (-len(self.buf) % n)

    def byte(self, value: int) -> None:
        self.buf.append(value)

    def uint32(self, value: int) -> None:
        self.align(4)
        self.buf += struct.pack("<I", value)

    def string(self, value: str) -> None:  # also object paths
        data = value.encode()
        if b"\0" in data:
            raise ValueError("a D-Bus string cannot contain NUL")
        self.uint32(len(data))
        self.buf += data + b"\0"

    def signature(self, value: str) -> None:
        data = value.encode()
        self.byte(len(data))
        self.buf += data + b"\0"

    def value(self, sig: str, value: Value) -> None:
        if sig == "a{sv}" and isinstance(value, dict):
            self.uint32(0)  # the length, filled in below
            length_at = len(self.buf) - 4
            self.align(8)  # dict entries are 8-aligned; the length does not count this
            start = len(self.buf)
            for key, item in value.items():
                self.align(8)
                self.string(key)
                self.signature("s")
                self.string(item)
            struct.pack_into("<I", self.buf, length_at, len(self.buf) - start)
        elif sig in ("s", "o") and isinstance(value, str):
            self.string(value)
        elif sig == "g" and isinstance(value, str):
            self.signature(value)
        elif sig in ("u", "h") and isinstance(value, int):
            self.uint32(value)
        else:
            raise ValueError(f"unsupported type {sig!r} for {type(value).__name__}")


def encode(
    msg_type: int,
    serial: int,
    fields: Sequence[tuple[int, str | int]],
    body: Sequence[tuple[str, Value]] = (),
    *,
    flags: int = 0,
) -> bytes:
    """A complete little-endian message. ``body`` is a list of ``(type, value)`` with the types of
    :data:`Value` only; the ``SIGNATURE`` field is added from it."""
    writer = _Writer()
    # The fixed header is 12 bytes and the header-field array length is at offset 12, so
    # the array content starts at offset 16 (already 8-aligned).
    writer.buf = bytearray(16)
    all_fields = list(fields)
    if body:
        all_fields.append((FIELD_SIGNATURE, "".join(sig for sig, _ in body)))
    for code, value in all_fields:
        writer.align(8)
        writer.byte(code)
        sig = _FIELD_TYPES[code]
        writer.signature(sig)
        writer.value(sig, value)
    fields_len = len(writer.buf) - 16
    writer.align(8)
    body_start = len(writer.buf)
    for body_sig, body_value in body:
        writer.value(body_sig, body_value)
    body_len = len(writer.buf) - body_start
    writer.buf[0:16] = struct.pack(
        "<cBBBIII", b"l", msg_type, flags, 1, body_len, serial, fields_len
    )
    return bytes(writer.buf)


def encode_method_call(
    *,
    serial: int,
    path: str,
    interface: str,
    member: str,
    destination: str,
    args: Sequence[str] = (),
    body: Sequence[tuple[str, Value]] = (),
) -> bytes:
    """A ``METHOD_CALL`` with no flags (so never ``ALLOW_INTERACTIVE_AUTHORIZATION``).

    The arguments are ``args`` (strings) followed by ``body`` (typed values)."""
    return encode(
        METHOD_CALL,
        serial,
        [
            (FIELD_PATH, path),
            (FIELD_INTERFACE, interface),
            (FIELD_MEMBER, member),
            (FIELD_DESTINATION, destination),
        ],
        [*(("s", arg) for arg in args), *body],
    )


@dataclass(slots=True)
class Message:
    """A parsed incoming message (only the header fields and simple body types)."""

    msg_type: int
    serial: int
    fields: dict[int, str | int]
    body: list[str | int]
    fds: list[int]

    @property
    def signature(self) -> str:
        return str(self.fields.get(FIELD_SIGNATURE, ""))

    @property
    def reply_serial(self) -> int | None:
        value = self.fields.get(FIELD_REPLY_SERIAL)
        return int(value) if value is not None else None


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def align(self, n: int) -> None:
        self.pos += -self.pos % n

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise DBusProtocolError("message ends early")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def byte(self) -> int:
        return self.take(1)[0]

    def uint32(self) -> int:
        self.align(4)
        value: int = struct.unpack("<I", self.take(4))[0]
        return value

    def string(self) -> str:
        n = self.uint32()
        text = self.take(n + 1)[:-1]
        return text.decode("utf-8", errors="replace")

    def signature(self) -> str:
        n = self.byte()
        return self.take(n + 1)[:-1].decode("ascii", errors="replace")

    def value(self, sig: str) -> str | int:
        if sig in ("s", "o"):
            return self.string()
        if sig == "g":
            return self.signature()
        if sig in ("u", "h", "b"):
            return self.uint32()
        if sig == "v":  # a variant of one simple type (a property value)
            inner = self.signature()
            if len(inner) != 1 or inner == "v":
                raise DBusProtocolError(f"unsupported variant type {inner!r}")
            return self.value(inner)
        raise DBusProtocolError(f"unsupported type {sig!r}")


def message_length(header: bytes) -> int:
    """Total length of a message from its first 16 bytes."""
    _check_endian(header[0:1])
    body_len, _serial, fields_len = struct.unpack("<III", header[4:16])
    head = 16 + fields_len
    total = head + (-head % 8) + body_len
    if total > MAX_MESSAGE:
        raise DBusProtocolError(f"message of {total} bytes is too long")
    return int(total)


def _check_endian(flag: bytes) -> None:
    # The bus daemon writes in its host's byte order; every target platform is little-endian.
    if flag != b"l":
        raise DBusProtocolError(f"bad endianness flag {flag!r}")


def decode_message(data: bytes, fds: list[int]) -> Message:
    """Parse one complete message. Takes ``UNIX_FDS`` descriptors from the front of ``fds``.

    Bodies that use other types are left empty (this client never needs them). Raises only
    :class:`DBusProtocolError`, whatever the bytes are, and then has closed the message's
    descriptors. After a bad header it closes all of ``fds``: which message owns which is
    then unknown.
    """
    try:
        with _malformed_is_protocol_error():
            header = _decode_header(data)
    except DBusProtocolError:
        _close_all(fds)
        fds.clear()
        raise
    n_fds = int(header.fields.get(FIELD_UNIX_FDS, 0))
    own_fds = fds[:n_fds]
    del fds[:n_fds]
    try:
        with _malformed_is_protocol_error():
            body = _decode_body(data, header)
    except DBusProtocolError:
        _close_all(own_fds)
        raise
    return Message(header.msg_type, header.serial, header.fields, body, own_fds)


@contextlib.contextmanager
def _malformed_is_protocol_error() -> Iterator[None]:
    try:
        yield
    except (ValueError, IndexError, struct.error) as exc:  # garbage that slipped through
        raise DBusProtocolError(f"malformed message: {type(exc).__name__}: {exc}") from None


class _Header(NamedTuple):
    msg_type: int
    serial: int
    fields: dict[int, str | int]
    body_start: int
    body_len: int


def _decode_header(data: bytes) -> _Header:
    if len(data) < 16:
        raise DBusProtocolError("message ends early")
    _check_endian(data[0:1])
    msg_type, _flags, version = data[1], data[2], data[3]
    if version != 1:
        raise DBusProtocolError(f"unsupported protocol version {version}")
    reader = _Reader(data)
    reader.pos = 4
    body_len = reader.uint32()
    serial = reader.uint32()
    fields_len = reader.uint32()
    end = reader.pos + fields_len
    fields: dict[int, str | int] = {}
    while reader.pos < end:
        reader.align(8)
        code = reader.byte()
        sig = reader.signature()
        value = reader.value(sig)
        expected = _FIELD_TYPES.get(code)
        if expected is not None and sig != expected:
            raise DBusProtocolError(f"header field {code} has type {sig!r}, not {expected!r}")
        fields[code] = value
    reader.pos = end
    reader.align(8)
    return _Header(msg_type, serial, fields, reader.pos, body_len)


def _decode_body(data: bytes, header: _Header) -> list[str | int]:
    sig = str(header.fields.get(FIELD_SIGNATURE, ""))
    if not sig or not all(c in "sogubhv" for c in sig):
        return []
    reader = _Reader(data[: header.body_start + header.body_len])
    reader.pos = header.body_start
    return [reader.value(c) for c in sig]


def _close_all(fds: Sequence[int]) -> None:
    for fd in fds:
        with contextlib.suppress(OSError):
            os.close(fd)


class _Connection:
    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self.sock = sock
        self.deadline = deadline
        self.data = bytearray()
        self.fds: list[int] = []
        self.closed = False

    def _settimeout(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("D-Bus call timed out")
        self.sock.settimeout(remaining)

    def send(self, data: bytes) -> None:
        self._settimeout()
        self.sock.sendall(data)

    def _recv(self) -> None:
        self._settimeout()
        if sys.platform == "win32":  # pragma: no cover - Linux only
            raise OSError("D-Bus over AF_UNIX is not supported on Windows")
        else:
            ancillary = socket.CMSG_SPACE(MAX_FDS * array.array("i").itemsize)
            data, ancdata, msg_flags, _ = self.sock.recvmsg(
                65536, ancillary, socket.MSG_CMSG_CLOEXEC
            )
            for level, kind, payload in ancdata:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    fds = array.array("i")
                    usable = len(payload) - len(payload) % fds.itemsize
                    fds.frombytes(payload[:usable])
                    self.fds.extend(fds)
            if msg_flags & socket.MSG_CTRUNC:
                raise DBusProtocolError("file descriptors were truncated")
            if not data:
                raise ConnectionError("the bus closed the connection")
            self.data += data

    def read_line(self) -> str:
        while b"\r\n" not in self.data:
            if len(self.data) > 16384:
                raise DBusProtocolError("authentication line too long")
            self._recv()
        line, _, rest = bytes(self.data).partition(b"\r\n")
        self.data = bytearray(rest)
        return line.decode("ascii", errors="replace")

    def read_message(self) -> Message:
        while len(self.data) < 16:
            self._recv()
        total = message_length(bytes(self.data[:16]))
        while len(self.data) < total:
            self._recv()
        raw = bytes(self.data[:total])
        del self.data[:total]
        return decode_message(raw, self.fds)

    def close(self) -> None:
        self.closed = True
        _close_all(self.fds)
        self.fds.clear()
        with contextlib.suppress(OSError):
            self.sock.close()


def _authenticate(conn: _Connection, *, want_fds: bool) -> None:
    uid = _uid()
    conn.send(b"\0AUTH EXTERNAL " + str(uid).encode().hex().encode() + b"\r\n")
    line = conn.read_line()
    if not line.startswith("OK "):
        raise DBusProtocolError(f"authentication refused: {line!r}")
    if want_fds:
        conn.send(b"NEGOTIATE_UNIX_FD\r\n")
        line = conn.read_line()
        if line != "AGREE_UNIX_FD":
            raise DBusProtocolError(f"the bus cannot pass file descriptors: {line!r}")
    conn.send(b"BEGIN\r\n")


def _uid() -> int:
    if sys.platform == "win32":  # pragma: no cover - Linux only
        raise OSError("D-Bus over AF_UNIX is not supported on Windows")
    else:
        return os.getuid()


def _connect(addresses: Sequence[str | bytes], deadline: float) -> socket.socket:
    if sys.platform == "win32":  # pragma: no cover - Linux only
        raise OSError("D-Bus over AF_UNIX is not supported on Windows")
    else:
        if not addresses:
            raise OSError("no usable unix: address in the D-Bus address")
        last: OSError | None = None
        for target in addresses:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
            try:
                sock.settimeout(max(deadline - time.monotonic(), 0.001))
                sock.connect(target)
            except OSError as exc:
                sock.close()
                last = exc
                continue
            except BaseException:
                sock.close()
                raise
            return sock
        assert last is not None
        raise last


class Connection:
    """An open, authenticated bus connection (blocking; use it from one thread at a time).

    Open it with :meth:`open`; it stays open (and with it every inhibit that the bus ties
    to the connection) until :meth:`close`.
    """

    def __init__(self, conn: _Connection) -> None:
        self._conn = conn
        self._serial = 1  # Hello was serial 1

    @classmethod
    def open(cls, address: str, *, timeout: float = 5.0) -> Connection:
        """Connect, authenticate and say ``Hello``. Raises like :func:`call`."""
        deadline = time.monotonic() + timeout
        conn = _Connection(_connect(parse_address(address), deadline), deadline)
        try:
            _authenticate(conn, want_fds=True)
            conn.send(
                encode_method_call(
                    serial=1,
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="Hello",
                    destination="org.freedesktop.DBus",
                )
            )
            reply = _wait_reply(conn, 1)
        except BaseException:
            conn.close()
            raise
        _close_all(reply.fds)
        return cls(conn)

    @property
    def closed(self) -> bool:
        return self._conn.closed

    def call(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        args: Sequence[str] = (),
        body: Sequence[tuple[str, Value]] = (),
        timeout: float = 5.0,
    ) -> Reply:
        """Call a method and wait for its reply (``args`` are strings, ``body`` typed)."""
        if self._conn.closed:
            raise OSError("the D-Bus connection is closed")
        self._serial += 1
        serial = self._serial
        self._conn.deadline = time.monotonic() + timeout
        self._conn.send(
            encode_method_call(
                serial=serial,
                path=path,
                interface=interface,
                member=member,
                destination=destination,
                args=args,
                body=body,
            )
        )
        return _wait_reply(self._conn, serial)

    def close(self) -> None:
        """Close the connection (idempotent). The bus then drops what it tied to it."""
        self._conn.close()


def _wait_reply(conn: _Connection, serial: int) -> Reply:
    """Read messages until the reply to ``serial``; other messages are dropped."""
    while True:
        message = conn.read_message()
        if message.msg_type not in (METHOD_RETURN, ERROR) or message.reply_serial != serial:
            _close_all(message.fds)  # signals (NameAcquired), stray calls, old replies
            continue
        if message.msg_type == ERROR:
            _close_all(message.fds)
            raise _error(message)
        return Reply(message.signature, message.body, message.fds)


def call(
    *,
    destination: str,
    path: str,
    interface: str,
    member: str,
    args: Sequence[str] = (),
    body: Sequence[tuple[str, Value]] = (),
    address: str | None = None,
    timeout: float = 5.0,
) -> Reply:
    """Open a connection, call one method, close the connection, and return the reply.

    ``address`` defaults to the system bus (:func:`system_bus_address`). Blocking: run it in
    a thread from async code. ``timeout`` covers the whole exchange. Raises
    :class:`DBusError`, :class:`DBusProtocolError` or ``OSError`` (see the module doc).
    """
    deadline = time.monotonic() + timeout
    connection = Connection.open(
        address if address is not None else system_bus_address(), timeout=timeout
    )
    try:
        return connection.call(
            destination=destination,
            path=path,
            interface=interface,
            member=member,
            args=args,
            body=body,
            timeout=max(deadline - time.monotonic(), 0.0),
        )
    finally:
        connection.close()


def _error(message: Message) -> DBusError:
    name = str(message.fields.get(FIELD_ERROR_NAME, "org.freedesktop.DBus.Error.Failed"))
    text = str(message.body[0]) if message.body and message.signature.startswith("s") else ""
    return DBusError(name, text)
