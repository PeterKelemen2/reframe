"""The real sleep inhibit on this machine (Linux with logind and/or a desktop session).

Each test prints what it sees before, during and after the lock (``pytest -s`` shows it):
``systemd-inhibit --list`` for logind, ``CanSuspend`` (it must stay as it was: the user's own
suspend is never blocked, decision 0020), and for the desktop session
``org.freedesktop.PowerManagement.Inhibit.HasInhibit`` and, on KDE, PowerDevil's
PolicyAgent. Skipped where the bus or the service is missing (CI containers). Recorded
output: testdata/README.md "Sleep inhibit (C-14)".
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import uuid

import pytest

from reframe.events import EventBus
from reframe.platform import dbus, sleep
from reframe.platform.sleep import (
    InhibitState,
    LogindBackend,
    SessionInhibitBackend,
    SleepInhibitor,
    create_sleep_inhibitor,
)
from reframe.tools import run

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only"),
]

#: KDE PowerDevil makes an inhibition active about 5 s after it is requested.
KDE_DELAY = 5.0
POLICY_AGENT = (
    "org.kde.Solid.PowerManagement",
    "/org/kde/Solid/PowerManagement/PolicyAgent",
    "org.kde.Solid.PowerManagement.PolicyAgent",
)
PM = (
    "org.freedesktop.PowerManagement.Inhibit",
    "/org/freedesktop/PowerManagement/Inhibit",
    "org.freedesktop.PowerManagement.Inhibit",
)


def _logind_reachable() -> str | None:
    """``None`` if logind answers on the system bus, else why not."""
    if shutil.which("systemd-inhibit") is None:
        return "no systemd-inhibit (used to list the locks)"
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


def _session_call(target: tuple[str, str, str], member: str, *args: int) -> int | None:
    """A session-bus call that returns a number (``b`` or ``u``), ``None`` if not there."""
    address = dbus.session_bus_address()
    if address is None:
        return None
    try:
        reply = dbus.call(
            destination=target[0],
            path=target[1],
            interface=target[2],
            member=member,
            body=[("u", a) for a in args],
            address=address,
            timeout=2.0,
        )
    except (OSError, dbus.DBusError, dbus.DBusProtocolError):
        return None
    value = reply.body[0] if reply.body else None
    return value if isinstance(value, int) else None


@pytest.fixture
def logind() -> None:
    reason = _logind_reachable() if sys.platform.startswith("linux") else "Linux only"
    if reason is not None:
        pytest.skip(reason)


@pytest.fixture
def power_management() -> None:
    if _session_call(PM, "HasInhibit") is None:
        pytest.skip("no org.freedesktop.PowerManagement.Inhibit on the session bus")


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


async def _desktop() -> str:
    """The desktop's view: PowerManagement HasInhibit and KDE's PolicyAgent, as text."""
    has = await asyncio.to_thread(_session_call, PM, "HasInhibit")
    suspend = await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 1)
    screen = await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 4)
    text = f"PowerManagement HasInhibit={has}; KDE PolicyAgent suspend={suspend} screen={screen}"
    if shutil.which("busctl") is not None:
        result = await run(
            ["busctl", "--user", "get-property", *POLICY_AGENT, "ActiveInhibitions"], timeout=10
        )
        if result.ok:
            text += f"; ActiveInhibitions: {result.stdout_text.strip()}"
    return text


def _ours(lines: list[str], why: str) -> list[str]:
    return [" ".join(line.split()) for line in lines if why in line]


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


@pytest.mark.usefixtures("logind")
async def test_logind_idle_lock_appears_and_disappears() -> None:
    why = f"Reframe test {uuid.uuid4().hex[:8]}"
    fds_before = _open_fds()
    can_before = await _can_suspend()
    assert _ours(await _listing(), why) == []

    inhibitor = SleepInhibitor([LogindBackend()])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = _ours(await _listing(), why)
    can_during = await _can_suspend()
    print(f"logind during: {during}; CanSuspend before={can_before} during={can_during}")
    (line,) = during
    fields = line.split()
    assert fields[0] == "Reframe"
    assert int(fields[3]) == os.getpid()  # logind records the caller: Reframe itself
    assert fields[5] == "idle"  # never "sleep" (decision 0020)
    assert fields[-1] == "block"
    assert can_during == can_before  # the user's own suspend is not blocked

    await inhibitor.release()
    after = _ours(await _listing(), why)
    print(f"logind after: {after}")
    assert after == []
    await inhibitor.close()
    assert _open_fds() == fds_before


@pytest.mark.slow
@pytest.mark.usefixtures("power_management")
async def test_session_inhibit_appears_and_disappears() -> None:
    fds_before = _open_fds()
    before = await _desktop()
    print(f"desktop before: {before}")
    can_before = await _can_suspend() if _logind_reachable() is None else None
    assert await asyncio.to_thread(_session_call, PM, "HasInhibit") == 0

    backend = SessionInhibitBackend()
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire("Reframe session test") is InhibitState.ACTIVE
    assert backend.interface == "org.freedesktop.PowerManagement.Inhibit"
    await asyncio.sleep(KDE_DELAY + 1.5)
    during = await _desktop()
    print(f"desktop during: {during}")
    assert await asyncio.to_thread(_session_call, PM, "HasInhibit") == 1
    if await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 1) is not None:
        # KDE: automatic suspend is inhibited, the screen may still dim and lock.
        assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 1) == 1
        assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 4) == 0
    if can_before is not None:
        assert await _can_suspend() == can_before  # the user's own suspend still works

    await inhibitor.release()
    await asyncio.sleep(1.0)
    after = await _desktop()
    print(f"desktop after: {after}")
    assert await asyncio.to_thread(_session_call, PM, "HasInhibit") == 0
    await inhibitor.close()
    assert _open_fds() == fds_before  # the session connection is closed


@pytest.mark.slow
@pytest.mark.usefixtures("logind", "power_management")
async def test_default_inhibitor_on_this_desktop() -> None:
    why = f"Reframe default {uuid.uuid4().hex[:8]}"
    bus = EventBus()
    sub = bus.subscribe()
    can_before = await _can_suspend()
    idle_action = await LogindBackend().idle_action()
    inhibitor = create_sleep_inhibitor(bus)
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    await asyncio.sleep(KDE_DELAY + 1.5)
    listing = _ours(await _listing(), why)
    desktop = await _desktop()
    print(f"default: backends={inhibitor.backends} IdleAction={idle_action}")
    print(f"default during: logind {listing}; {desktop}; CanSuspend {await _can_suspend()}")
    if idle_action == "ignore":
        # The desktop handles idle; no logind lock (on KDE it would keep the screen on).
        assert inhibitor.backends == ("session",)
        assert listing == []
    else:
        assert inhibitor.backends == ("session", "logind")
    assert await _can_suspend() == can_before
    assert inhibitor.not_stopped == ()
    await inhibitor.close()
    await inhibitor.close()
    assert sub.get_nowait() is None  # no warning


@pytest.mark.usefixtures("logind")
async def test_without_a_desktop_session_the_logind_idle_lock_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    why = f"Reframe headless {uuid.uuid4().hex[:8]}"
    inhibitor = create_sleep_inhibitor()
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = _ours(await _listing(), why)
    print(f"headless: backends={inhibitor.backends} during={during}")
    assert inhibitor.backends == ("logind",)
    assert inhibitor.not_stopped == ()  # no desktop: nothing else to stop
    (line,) = during
    assert line.split()[5] == "idle"
    await inhibitor.close()
    assert _ours(await _listing(), why) == []


async def test_no_bus_at_all_gives_the_one_warning() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    nowhere = "unix:path=/nonexistent/reframe-test-bus"
    inhibitor = SleepInhibitor(
        [SessionInhibitBackend(address=nowhere), LogindBackend(address=nowhere)], bus
    )
    assert await inhibitor.acquire("job") is InhibitState.UNAVAILABLE
    event = sub.get_nowait()
    assert event is not None
    assert event.type == "app.warning"
    print(event.model_dump_json(indent=2))
    assert sub.get_nowait() is None
    await inhibitor.release()
    await inhibitor.close()


@pytest.mark.slow
async def test_portal_inhibit_with_this_client() -> None:
    """The portal fallback (GNOME and others), checked through KDE's portal backend."""
    address = dbus.session_bus_address()
    if address is None or _session_call(POLICY_AGENT, "HasInhibition", 1) is None:
        pytest.skip("needs a session bus with KDE's PolicyAgent to see the result")
    try:
        connection = await asyncio.to_thread(dbus.Connection.open, address)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no session bus: {exc}")
    fds_before = _open_fds()
    try:
        reply = await asyncio.to_thread(
            sleep._portal_inhibit, connection, "Reframe portal test", 5.0
        )
    except dbus.DBusError as exc:  # pragma: no cover - depends on the machine
        connection.close()
        pytest.skip(f"no XDG desktop portal: {exc}")
    print(f"portal reply: {reply.signature} {reply.body}")
    assert reply.signature == "o"
    await asyncio.sleep(KDE_DELAY + 1.5)
    during = await _desktop()
    print(f"portal during: {during}")
    assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 1) == 1
    assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 4) == 0
    # Request.Close() ends it while the connection is still open.
    await asyncio.to_thread(sleep._portal_close, connection, str(reply.body[0]), 2.0)
    await asyncio.sleep(1.0)
    after = await _desktop()
    print(f"portal after Request.Close (connection open): {after}")
    assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 1) == 0
    connection.close()
    assert len(fds_before - _open_fds()) == 1  # the connection's socket is gone


@pytest.mark.slow
@pytest.mark.usefixtures("power_management")
async def test_closing_the_connection_alone_ends_the_power_management_inhibit() -> None:
    address = dbus.session_bus_address()
    assert address is not None
    connection = await asyncio.to_thread(dbus.Connection.open, address)
    reply = await asyncio.to_thread(sleep._pm_inhibit, connection, "Reframe close test", 5.0)
    print(f"PowerManagement cookie: {reply.signature} {reply.body}")
    await asyncio.sleep(KDE_DELAY + 1.5)
    assert await asyncio.to_thread(_session_call, PM, "HasInhibit") == 1
    connection.close()  # no UnInhibit: as if Reframe crashed
    await asyncio.sleep(1.0)
    after = await _desktop()
    print(f"PowerManagement after the connection closed: {after}")
    assert await asyncio.to_thread(_session_call, PM, "HasInhibit") == 0


@pytest.mark.slow
@pytest.mark.usefixtures("logind")
async def test_kde_turns_a_logind_idle_lock_into_a_screen_inhibition() -> None:
    """Why the logind idle lock is taken only where needed: KDE mirrors it (after ~5 s) as
    an "idle" inhibition, which also keeps the screen from dimming and locking."""
    if _session_call(POLICY_AGENT, "HasInhibition", 1) is None:
        pytest.skip("needs KDE's PolicyAgent on the session bus")
    inhibitor = SleepInhibitor([LogindBackend()])
    assert await inhibitor.acquire("Reframe KDE mirror test") is InhibitState.ACTIVE
    await asyncio.sleep(KDE_DELAY + 1.5)
    during = await _desktop()
    print(f"logind idle lock only, KDE during: {during}")
    assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 4) == 1
    await inhibitor.close()
    await asyncio.sleep(1.0)
    after = await _desktop()
    print(f"logind idle lock only, KDE after: {after}")
    assert await asyncio.to_thread(_session_call, POLICY_AGENT, "HasInhibition", 4) == 0
