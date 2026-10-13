"""The real sleep lock on this machine: logind and systemd-inhibit (Linux with logind only).

Each test lists the inhibitors with ``systemd-inhibit --list`` before, during and after the
lock and prints the listing (``pytest -s`` shows it). Skipped where there is no system bus
or no logind (CI containers). Recorded output: testdata/README.md "Sleep inhibit (C-14)".
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import uuid

import psutil
import pytest

from reframe.events import EventBus
from reframe.platform import dbus
from reframe.platform.sleep import (
    InhibitState,
    LogindBackend,
    SleepInhibitor,
    SystemdInhibitBackend,
    create_sleep_inhibitor,
)
from reframe.tools import run

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only"),
]


def _logind_reachable() -> str | None:
    """``None`` if logind answers on the system bus, else why not."""
    if shutil.which("systemd-inhibit") is None:
        return "no systemd-inhibit"
    try:
        dbus.call(
            destination="org.freedesktop.login1",
            path="/org/freedesktop/login1",
            interface="org.freedesktop.DBus.Peer",
            member="Ping",
            timeout=2.0,
        )
    except (OSError, dbus.DBusError, dbus.DBusProtocolError) as exc:
        return f"no logind on the system bus: {exc}"
    return None


@pytest.fixture
def logind() -> None:
    reason = _logind_reachable() if sys.platform.startswith("linux") else "Linux only"
    if reason is not None:
        pytest.skip(reason)


async def _listing() -> list[str]:
    result = await run(["systemd-inhibit", "--list", "--no-legend", "--no-pager"], timeout=10)
    assert result.ok, result.stderr_text
    return result.stdout_text.splitlines()


async def _can_suspend() -> str:
    reply = await asyncio.to_thread(
        dbus.call,
        destination="org.freedesktop.login1",
        path="/org/freedesktop/login1",
        interface="org.freedesktop.login1.Manager",
        member="CanSuspend",
    )
    return str(reply.body[0])


def _ours(lines: list[str], why: str) -> list[str]:
    return [line for line in lines if why in line]


def _show(label: str, lines: list[str], why: str) -> None:
    print(f"--- {label} ({len(lines)} inhibitors; ours: {len(_ours(lines, why))})")
    for line in lines:
        print(" ".join(line.split()))


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


@pytest.mark.usefixtures("logind")
async def test_logind_lock_appears_and_disappears() -> None:
    why = f"Reframe test {uuid.uuid4().hex[:8]}"
    fds_before = _open_fds()
    before = await _listing()
    suspend_before = await _can_suspend()
    _show("before", before, why)
    assert _ours(before, why) == []

    backend = LogindBackend()
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    assert inhibitor.backend == "logind"
    during = await _listing()
    suspend_during = await _can_suspend()
    _show("during", during, why)
    (line,) = _ours(during, why)
    who, _uid, _user, pid, *_rest = line.split()
    assert who == "Reframe"
    assert int(pid) == os.getpid()  # logind records the caller of Inhibit: Reframe itself
    assert " sleep:idle " in f" {' '.join(line.split())} "
    assert line.split()[-1] == "block"
    print(f"CanSuspend before: {suspend_before}, during: {suspend_during}")
    if suspend_before == "yes":
        assert suspend_during == "inhibited"

    await inhibitor.release()
    after = await _listing()
    _show("after", after, why)
    assert _ours(after, why) == []
    assert await _can_suspend() == suspend_before
    await inhibitor.close()
    assert _open_fds() == fds_before


@pytest.mark.usefixtures("logind")
async def test_systemd_inhibit_lock_appears_and_disappears() -> None:
    why = f"Reframe test {uuid.uuid4().hex[:8]}"
    before = await _listing()
    _show("before", before, why)
    assert _ours(before, why) == []
    children_before = {p.pid for p in psutil.Process().children(recursive=True)}

    inhibitor = SleepInhibitor([SystemdInhibitBackend()])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = await _listing()
    _show("during", during, why)
    (line,) = _ours(during, why)
    fields = line.split()
    assert fields[0] == "Reframe"
    assert fields[4] == "systemd-inhibit"  # COMM: the helper holds the lock
    assert fields[5] == "sleep:idle"
    assert fields[-1] == "block"
    helpers = [p for p in psutil.Process().children(recursive=True) if p.pid not in children_before]
    assert int(fields[3]) in {p.pid for p in helpers}

    await inhibitor.release()
    after = await _listing()
    _show("after", after, why)
    assert _ours(after, why) == []
    for proc in helpers:  # the helper and its sleep are gone (no leaked process)
        assert not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
    await inhibitor.close()


@pytest.mark.usefixtures("logind")
async def test_default_inhibitor_uses_logind_first() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = create_sleep_inhibitor(bus)
    assert await inhibitor.acquire("Reframe default backend test") is InhibitState.ACTIVE
    assert inhibitor.backend == "logind"
    await inhibitor.close()
    await inhibitor.close()
    assert sub.get_nowait() is None  # no warning


async def test_no_bus_falls_through_to_a_warning() -> None:
    if shutil.which("systemd-inhibit") is None:  # pragma: no cover - depends on the machine
        pytest.skip("no systemd-inhibit")
    bus = EventBus()
    sub = bus.subscribe()
    nowhere = {"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent/reframe-test-bus"}
    inhibitor = SleepInhibitor(
        [
            LogindBackend(address=nowhere["DBUS_SYSTEM_BUS_ADDRESS"]),
            SystemdInhibitBackend(extra_env=nowhere),
        ],
        bus,
    )
    assert await inhibitor.acquire("job") is InhibitState.UNAVAILABLE
    event = sub.get_nowait()
    assert event is not None
    assert event.type == "app.warning"
    print(event.model_dump_json(indent=2))
    assert sub.get_nowait() is None
    await inhibitor.release()
    await inhibitor.close()
