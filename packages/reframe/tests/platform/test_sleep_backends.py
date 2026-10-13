"""The sleep inhibit backends: Windows (mocked kernel32), logind (fake D-Bus call) and
systemd-inhibit (a fake ``systemd-inhibit`` script, run for real through run_streaming)."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import threading
from pathlib import Path
from typing import Any
from unittest import mock

import psutil
import pytest

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.platform import dbus, sleep
from reframe.platform.sleep import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    InhibitState,
    LogindBackend,
    SleepInhibitor,
    SystemdInhibitBackend,
    WindowsExecutionStateBackend,
)

pytestmark = pytest.mark.anyio

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")


def _no_lost(reason: str) -> None:  # pragma: no cover - must not be called
    raise AssertionError(f"lost: {reason}")


# --------------------------------------------------------------------------- Windows


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
    assert await backend.hold("x", _no_lost) == (
        "SetThreadExecutionState failed: OSError: broken binding"
    )
    assert backend.thread is None


@pytest.mark.skipif(sys.platform == "win32", reason="kernel32 exists on Windows")
async def test_windows_backend_without_kernel32_is_unavailable() -> None:
    backend = WindowsExecutionStateBackend()
    assert await backend.hold("x", _no_lost) == (
        "kernel32 not available: kernel32 exists only on Windows"
    )
    await backend.free()


# --------------------------------------------------------------------------- logind


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


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
    before = _open_fds()
    read_end, write_end = os.pipe()
    os.set_inheritable(read_end, True)
    call = FakeCall(dbus.Reply("h", [0], [read_end]))
    backend = LogindBackend(call=call, address="unix:path=/x", timeout=2.0)
    assert await backend.hold("Encoding 3 jobs", _no_lost) is None
    assert call.kwargs == {
        "destination": "org.freedesktop.login1",
        "path": "/org/freedesktop/login1",
        "interface": "org.freedesktop.login1.Manager",
        "member": "Inhibit",
        "args": ("sleep:idle", "Reframe", "Encoding 3 jobs", "block"),
        "address": "unix:path=/x",
        "timeout": 2.0,
    }
    assert backend.fd == read_end
    assert not os.get_inheritable(read_end)  # a child must never keep the lock alive
    assert await backend.hold("again", _no_lost) is None  # already held: no second call
    await backend.free()
    assert _fd(backend) is None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(read_end)
    await backend.free()
    os.close(write_end)
    assert _open_fds() == before


@linux_only
async def test_logind_closes_extra_fds_and_rejects_a_reply_without_one() -> None:
    before = _open_fds()
    a, b = os.pipe()
    backend = LogindBackend(call=FakeCall(dbus.Reply("h", [1], [a, b])))
    assert await backend.hold("x", _no_lost) is None
    assert backend.fd == b
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(a)
    await backend.free()
    c, d = os.pipe()
    bad = LogindBackend(call=FakeCall(dbus.Reply("h", [5], [c, d])))
    assert await bad.hold("x", _no_lost) == ("Inhibit returned no file descriptor (signature 'h')")
    assert bad.fd is None
    empty = LogindBackend(call=FakeCall(dbus.Reply("", [], [])))
    assert await empty.hold("x", _no_lost) == "Inhibit returned no file descriptor (signature '')"
    assert _open_fds() == before


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
    assert await backend.hold("x", _no_lost) == message
    assert backend.fd is None


# --------------------------------------------------------------------------- systemd-inhibit


FAKE_OK = """#!/bin/sh
# A fake systemd-inhibit: record the arguments, skip the options, run the command.
printf '%s\\n' "$@" > "$0.args"
while [ "${1#--}" != "$1" ]; do shift; done
exec "$@"
"""

FAKE_DENIED = """#!/bin/sh
echo "Failed to inhibit: Access denied" >&2
exit 1
"""

FAKE_HANGS = """#!/bin/sh
exec sleep 30
"""


def _script(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _tree() -> list[psutil.Process]:
    return psutil.Process().children(recursive=True)


async def _gone(procs: list[psutil.Process]) -> bool:
    for _ in range(100):
        alive = []
        for p in procs:
            try:
                if p.status() != psutil.STATUS_ZOMBIE:
                    alive.append(p)
            except psutil.NoSuchProcess:
                pass
        if not alive:
            return True
        await asyncio.sleep(0.02)
    return False


@linux_only
async def test_systemd_inhibit_runs_until_released_and_leaves_nothing(tmp_path: Path) -> None:
    fake = _script(tmp_path, "systemd-inhibit", FAKE_OK)
    before = {p.pid for p in _tree()}
    fds_before = _open_fds()
    backend = SystemdInhibitBackend(which=lambda _: fake)
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire("Encoding: Show S01E01") is InhibitState.ACTIVE
    assert inhibitor.backend == "systemd-inhibit"
    args = await asyncio.to_thread(Path(fake + ".args").read_text)
    assert args.splitlines() == [
        "--what=sleep:idle",
        "--who=Reframe",
        "--why=Encoding: Show S01E01",
        "--mode=block",
        "--no-ask-password",
        "sh",
        "-c",
        "echo ready && exec sleep infinity",
    ]
    children = [p for p in _tree() if p.pid not in before]
    assert children  # the fake execs into sh, then sleep
    assert any("sleep" in " ".join(p.cmdline()) for p in children)
    await inhibitor.release()
    assert await _gone(children)
    assert backend.task is None
    assert inhibitor.state is InhibitState.INACTIVE
    await inhibitor.close()
    assert _open_fds() == fds_before


@linux_only
async def test_systemd_inhibit_failure_is_data(tmp_path: Path) -> None:
    fake = _script(tmp_path, "systemd-inhibit", FAKE_DENIED)
    backend = SystemdInhibitBackend(which=lambda _: fake)
    assert await backend.hold("x", _no_lost) == (
        "systemd-inhibit exited with code 1: Failed to inhibit: Access denied"
    )
    assert backend.task is None


async def test_systemd_inhibit_missing() -> None:
    backend = SystemdInhibitBackend(which=lambda _: None)
    assert await backend.hold("x", _no_lost) == "systemd-inhibit not found"
    await backend.free()


@linux_only
async def test_systemd_inhibit_that_cannot_run_is_data(tmp_path: Path) -> None:
    path = tmp_path / "systemd-inhibit"
    path.write_text("not a program")  # not executable
    backend = SystemdInhibitBackend(which=lambda _: str(path))
    error = await backend.hold("x", _no_lost)
    assert error is not None
    assert error.startswith("PermissionError")


@linux_only
async def test_systemd_inhibit_that_never_gets_ready_is_stopped(tmp_path: Path) -> None:
    fake = _script(tmp_path, "systemd-inhibit", FAKE_HANGS)
    before = {p.pid for p in _tree()}
    backend = SystemdInhibitBackend(which=lambda _: fake, start_timeout=0.3)
    assert await backend.hold("x", _no_lost) == "systemd-inhibit did not start within 0.3 s"
    assert backend.task is None
    leftovers = [p for p in _tree() if p.pid not in before]
    assert await _gone(leftovers)


@linux_only
async def test_systemd_inhibit_killed_from_outside_is_a_lost_lock(tmp_path: Path) -> None:
    fake = _script(tmp_path, "systemd-inhibit", FAKE_OK)
    bus = EventBus()
    sub = bus.subscribe()
    before = {p.pid for p in _tree()}
    inhibitor = SleepInhibitor([SystemdInhibitBackend(which=lambda _: fake)], bus)
    await inhibitor.acquire("job")
    (child,) = [p for p in psutil.Process().children() if p.pid not in before]
    child.kill()
    for _ in range(100):
        if inhibitor.state is InhibitState.UNAVAILABLE:
            break
        await asyncio.sleep(0.02)
    assert inhibitor.state is InhibitState.UNAVAILABLE
    event = sub.get_nowait()
    assert isinstance(event, AppWarningEvent)
    assert event.detail == "systemd-inhibit exited unexpectedly (code -9)"
    await inhibitor.release()
    await inhibitor.close()


@linux_only
async def test_systemd_inhibit_hold_cancelled_while_starting_stops_the_child(
    tmp_path: Path,
) -> None:
    fake = _script(tmp_path, "systemd-inhibit", FAKE_HANGS)
    before = {p.pid for p in _tree()}
    backend = SystemdInhibitBackend(which=lambda _: fake, start_timeout=30)
    task = asyncio.ensure_future(backend.hold("x", _no_lost))
    for _ in range(100):
        if [p for p in _tree() if p.pid not in before]:
            break
        await asyncio.sleep(0.02)
    leftovers = [p for p in _tree() if p.pid not in before]
    assert leftovers
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _gone(leftovers)
    assert backend.task is None


async def test_windows_backend_accepts_a_mock_kernel32() -> None:
    # The Windows binding is only loaded on Windows; the backend accepts any object with
    # SetThreadExecutionState (here a Mock), like childproc's Kernel32.
    k32 = mock.Mock(spec=["SetThreadExecutionState"])
    k32.SetThreadExecutionState.return_value = ES_CONTINUOUS
    backend = sleep.WindowsExecutionStateBackend(k32)
    assert await backend.hold("x", _no_lost) is None
    await backend.free()
    await backend.free()
    assert k32.SetThreadExecutionState.call_args_list == [
        mock.call(0x80000001),
        mock.call(0x80000000),
    ]
