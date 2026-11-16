"""The server side of a fake D-Bus on a unix socket, and the fd and socket leak checks of the
sleep inhibit tests (Linux only, but importable everywhere)."""

from __future__ import annotations

import contextlib
import gc
import os
import socket
import tempfile
import threading
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

from reframe.platform import dbus

# Linux-only name, looked up at run time so that mypy --platform win32 accepts the module.
AF_UNIX: int = vars(socket).get("AF_UNIX", 0)

AUTH_OK = "OK 0123456789abcdef0123456789abcdef"
AGREE_UNIX_FD = "AGREE_UNIX_FD"

Handler = Callable[[socket.socket, threading.Event], None]


@contextlib.contextmanager
def serve_unix(handler: Handler, *, many: bool = False) -> Iterator[str]:
    """Yield the address of a unix socket whose connection ``handler`` serves in a thread;
    its event is set when the block ends.

    By default one connection is accepted. With ``many``, every connection is, each with a
    5 s timeout and with its ``OSError`` swallowed.
    """
    with tempfile.TemporaryDirectory(prefix="rfbus") as tmp:
        path = str(Path(tmp) / "bus")
        server = socket.socket(AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(8 if many else 1)
        stop = threading.Event()

        def serve_one() -> None:
            conn, _ = server.accept()
            with conn:
                handler(conn, stop)

        def serve_many() -> None:
            server.settimeout(0.1)
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
                        handler(conn, stop)

        thread = threading.Thread(target=serve_many if many else serve_one, daemon=True)
        thread.start()
        try:
            yield f"unix:path={path}"
        finally:
            stop.set()
            thread.join(timeout=10)
            server.close()


def _receive(conn: socket.socket, buf: bytearray) -> None:
    chunk = conn.recv(4096)
    if not chunk:
        raise ConnectionError
    buf.extend(chunk)


def read_line(conn: socket.socket, buf: bytearray) -> bytes:
    """The next auth line, without its CRLF; ``buf`` keeps what was read past it."""
    while b"\r\n" not in buf:
        _receive(conn, buf)
    line, _, rest = bytes(buf).partition(b"\r\n")
    buf[:] = rest
    return line


def read_message(conn: socket.socket, buf: bytearray) -> dbus.Message:
    """The next D-Bus message; ``ConnectionError`` when the client closes first."""
    while len(buf) < 16:
        _receive(conn, buf)
    total = dbus.message_length(bytes(buf[:16]))
    while len(buf) < total:
        _receive(conn, buf)
    message = dbus.decode_message(bytes(buf[:total]), [])
    del buf[:total]
    return message


def handshake(
    conn: socket.socket,
    buf: bytearray,
    *,
    auth: str = AUTH_OK,
    fd_answer: str = AGREE_UNIX_FD,
    seen: list[str] | None = None,
) -> bool:
    """Answer ``auth`` to the client's AUTH and ``fd_answer`` to its NEGOTIATE_UNIX_FD.

    Returns whether the client got to BEGIN. Each line read is appended to ``seen``.
    """
    lines = [] if seen is None else seen
    lines.append(read_line(conn, buf).decode())
    conn.sendall(auth.encode() + b"\r\n")
    if not auth.startswith("OK"):
        return False
    lines.append(read_line(conn, buf).decode())
    conn.sendall(fd_answer.encode() + b"\r\n")
    if fd_answer != AGREE_UNIX_FD:
        return False
    lines.append(read_line(conn, buf).decode())
    return True


def open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


def new_fds(before: set[int]) -> dict[int, str]:
    """The fds opened since ``before`` and still open, with what they point to."""
    new: dict[int, str] = {}
    for fd in sorted(open_fds() - before):
        try:
            new[fd] = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue  # closed meanwhile
    return new


def unclosed_resources() -> list[str]:
    """The ``ResourceWarning`` messages of objects that only the garbage collector closes."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    return [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]


def assert_no_new_fds_or_unclosed(before: set[int]) -> None:
    """Only new fds count as a leak: other tests' objects may close theirs meanwhile."""
    assert not new_fds(before)
    assert not unclosed_resources()
