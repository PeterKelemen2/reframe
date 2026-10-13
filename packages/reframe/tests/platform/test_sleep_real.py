"""The real sleep inhibit on this machine (Linux with logind and/or a desktop session).

Other programs may hold inhibits at the same time (a media player, other test runs in
parallel), so every test looks only for **its own** inhibit: a unique reason per test, found
in the lists that name the holder and the reason (logind ``ListInhibitors``, KDE PowerDevil's
``PolicyAgent.ActiveInhibitions``), present during the hold and gone after it. Global flags
(``PowerManagement.HasInhibit``, the PolicyAgent's ``HasInhibition``) are checked only when
they were false before the test; otherwise that one check is skipped with a message.
``CanSuspend`` must stay ``yes`` during the hold (the user's own suspend is never blocked,
decision 0020) unless it was not ``yes`` before.

Each test prints what it sees (``pytest -s`` shows it). Skipped where the bus or the
service is missing (CI containers). Recorded output: testdata/README.md "Sleep inhibit
(C-14)".
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

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
SUSPEND, SCREEN = 1, 4  # PolicyAgent: InterruptSession, ChangeScreenSettings


def _why(label: str) -> str:
    return f"Reframe {label} {uuid.uuid4().hex[:10]}"


# --------------------------------------------------------------------------- probes


def _logind_reachable() -> str | None:
    """``None`` if logind answers on the system bus, else why not."""
    if shutil.which("busctl") is None:
        return "no busctl (used to list the inhibitors)"
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


async def _flag(target: tuple[str, str, str], member: str, *args: int) -> int | None:
    return await asyncio.to_thread(_session_call, target, member, *args)


def _kde() -> bool:
    return _session_call(POLICY_AGENT, "HasInhibition", SUSPEND) is not None


async def _busctl_json(*argv: str) -> object:
    result = await run(["busctl", "--json=short", *argv], timeout=10)
    assert result.ok, result.stderr_text
    return json.loads(result.stdout_text)


async def _logind_ours(why: str) -> list[list[object]]:
    """logind's inhibitors with our reason: ``[what, who, why, mode, uid, pid]`` each."""
    data = await _busctl_json(
        "call",
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "ListInhibitors",
    )
    assert isinstance(data, dict)
    (inhibitors,) = data["data"]
    return [entry for entry in inhibitors if entry[2] == why]


async def _kde_ours(why: str) -> list[list[object]]:
    """KDE's active inhibitions with our reason: ``[what, who, why, mode, flags]`` each."""
    data = await _busctl_json("--user", "get-property", *POLICY_AGENT, "ActiveInhibitions")
    assert isinstance(data, dict)
    return [entry for entry in data["data"] if entry[2] == why]


async def _until(check: Callable[[], Awaitable[bool]], limit: float) -> bool:
    deadline = time.monotonic() + limit
    while True:
        if await check():
            return True
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.25)


async def _kde_appears(why: str) -> list[list[object]]:
    """Wait (KDE needs about 5 s) until our inhibition is active; return it."""
    found: list[list[object]] = []

    async def check() -> bool:
        found[:] = await _kde_ours(why)
        return bool(found)

    await _until(check, KDE_DELAY + 15.0)  # PowerDevil is slower on a busy machine
    return found


async def _kde_gone(why: str) -> bool:
    async def check() -> bool:
        return not await _kde_ours(why)

    return await _until(check, 10.0)


async def _can_suspend() -> str:
    reply = await asyncio.to_thread(
        dbus.call,
        destination="org.freedesktop.login1",
        path="/org/freedesktop/login1",
        interface="org.freedesktop.login1.Manager",
        member="CanSuspend",
    )
    return str(reply.body[0])


def _check_can_suspend(before: str, during: str) -> None:
    print(f"CanSuspend before={before} during={during}")
    if before == "yes":
        assert during == "yes"  # the user's own suspend is never blocked
    else:  # pragma: no cover - depends on the machine
        print(f"skipped the CanSuspend check: it was {before!r} before the test")


async def _check_global_flag(
    label: str, before: int | None, expected: int, read: Callable[[], Awaitable[int | None]]
) -> None:
    """Check a global flag only when it was false before the test."""
    if before is None:
        print(f"skipped {label}: not available")
        return
    if before:
        print(f"skipped {label}: something else already held it before the test")
        return
    now = await read()
    print(f"{label}: before={before} now={now}")
    assert now == expected


def _open_fds() -> set[int]:
    """Only new fds count as a leak: other tests' objects may close theirs meanwhile."""
    return {int(name) for name in os.listdir("/proc/self/fd")}


def _new_fds(before: set[int]) -> dict[int, str]:
    """The fds opened since ``before`` and still open, with what they point to."""
    new: dict[int, str] = {}
    for fd in sorted(_open_fds() - before):
        try:
            new[fd] = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue  # closed meanwhile
    return new


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def logind() -> None:
    reason = _logind_reachable() if sys.platform.startswith("linux") else "Linux only"
    if reason is not None:
        pytest.skip(reason)


@pytest.fixture
def power_management() -> None:
    if _session_call(PM, "HasInhibit") is None:
        pytest.skip("no org.freedesktop.PowerManagement.Inhibit on the session bus")


@pytest.fixture
def kde() -> None:
    if shutil.which("busctl") is None or not _kde():
        pytest.skip("needs KDE's PolicyAgent on the session bus (and busctl)")


# --------------------------------------------------------------------------- tests


@pytest.mark.usefixtures("logind")
async def test_logind_idle_lock_appears_and_disappears() -> None:
    why = _why("logind")
    fds_before = _open_fds()
    can_before = await _can_suspend()
    assert await _logind_ours(why) == []

    inhibitor = SleepInhibitor([LogindBackend()])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = await _logind_ours(why)
    print(f"logind during: {during}")
    (entry,) = during
    what, who, _, mode, _, pid = entry
    assert what == "idle"  # never "sleep" (decision 0020)
    assert who == "Reframe"
    assert mode == "block"
    assert pid == os.getpid()  # logind records the caller: Reframe itself
    _check_can_suspend(can_before, await _can_suspend())

    await inhibitor.release()
    after = await _logind_ours(why)
    print(f"logind after: {after}")
    assert after == []
    await inhibitor.close()
    assert not _new_fds(fds_before)  # no fd left open


@pytest.mark.slow
@pytest.mark.usefixtures("power_management", "kde")
async def test_session_inhibit_appears_and_disappears() -> None:
    why = _why("session")
    fds_before = _open_fds()
    has_before = await _flag(PM, "HasInhibit")
    screen_before = await _flag(POLICY_AGENT, "HasInhibition", SCREEN)
    can_before = await _can_suspend() if _logind_reachable() is None else None
    assert await _kde_ours(why) == []

    backend = SessionInhibitBackend()
    inhibitor = SleepInhibitor([backend])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    assert backend.interface == "org.freedesktop.PowerManagement.Inhibit"
    during = await _kde_appears(why)
    print(f"KDE during: {during}")
    (entry,) = during
    assert entry[:2] == ["sleep", "Reframe"]  # automatic suspend only, not "idle"
    await _check_global_flag("HasInhibit", has_before, 1, lambda: _flag(PM, "HasInhibit"))
    await _check_global_flag(
        "PolicyAgent screen", screen_before, 0, lambda: _flag(POLICY_AGENT, "HasInhibition", 4)
    )
    if can_before is not None:
        _check_can_suspend(can_before, await _can_suspend())

    await inhibitor.release()
    assert await _kde_gone(why)
    print(f"KDE after: {await _kde_ours(why)}")
    await _check_global_flag("HasInhibit after", has_before, 0, lambda: _flag(PM, "HasInhibit"))
    await inhibitor.close()
    assert not _new_fds(fds_before)  # the session connection is closed


@pytest.mark.slow
@pytest.mark.usefixtures("logind", "power_management", "kde")
async def test_default_inhibitor_on_this_desktop() -> None:
    why = _why("default")
    bus = EventBus()
    sub = bus.subscribe()
    can_before = await _can_suspend()
    idle_action = await LogindBackend().idle_action()
    inhibitor = create_sleep_inhibitor(bus)
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    kde = await _kde_appears(why)
    logind = await _logind_ours(why)
    print(f"default: backends={inhibitor.backends} IdleAction={idle_action}")
    print(f"default during: logind {logind}; KDE {kde}")
    if idle_action == "ignore":
        # The desktop handles idle; no logind lock (on KDE it would keep the screen on).
        assert inhibitor.backends == ("session",)
        assert logind == []
        assert [e[0] for e in kde] == ["sleep"]
    else:  # pragma: no cover - depends on the machine
        assert inhibitor.backends == ("session", "logind")
    _check_can_suspend(can_before, await _can_suspend())
    assert inhibitor.not_stopped == ()
    await inhibitor.close()
    await inhibitor.close()
    assert await _kde_gone(why)
    assert await _logind_ours(why) == []
    assert sub.get_nowait() is None  # no warning


@pytest.mark.usefixtures("logind")
async def test_without_a_desktop_session_the_logind_idle_lock_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    why = _why("headless")
    inhibitor = create_sleep_inhibitor()
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = await _logind_ours(why)
    print(f"headless: backends={inhibitor.backends} during={during}")
    assert inhibitor.backends == ("logind",)
    assert inhibitor.not_stopped == ()  # no desktop: nothing else to stop
    (entry,) = during
    assert entry[0] == "idle"
    await inhibitor.close()
    assert await _logind_ours(why) == []


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
@pytest.mark.usefixtures("kde")
async def test_portal_inhibit_with_this_client() -> None:
    """The portal fallback (GNOME and others), checked through KDE's portal backend."""
    address = dbus.session_bus_address()
    assert address is not None
    why = _why("portal")
    try:
        connection = await asyncio.to_thread(dbus.Connection.open, address)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no session bus: {exc}")
    fds_before = _open_fds()
    try:
        reply = await asyncio.to_thread(sleep._portal_inhibit, connection, why, 5.0)
    except dbus.DBusError as exc:  # pragma: no cover - depends on the machine
        connection.close()
        pytest.skip(f"no XDG desktop portal: {exc}")
    print(f"portal reply: {reply.signature} {reply.body}")
    assert reply.signature == "o"
    during = await _kde_appears(why)
    print(f"portal during: {during}")
    (entry,) = during
    assert entry[0] == "sleep"  # flag 4: automatic suspend only, the screen may lock
    # Request.Close() ends it while the connection is still open.
    await asyncio.to_thread(sleep._portal_close, connection, str(reply.body[0]), 2.0)
    assert await _kde_gone(why)
    print(f"portal after Request.Close (connection open): {await _kde_ours(why)}")
    connection.close()
    assert connection.closed
    assert not _new_fds(fds_before)


@pytest.mark.slow
@pytest.mark.usefixtures("power_management", "kde")
async def test_closing_the_connection_alone_ends_the_power_management_inhibit() -> None:
    address = dbus.session_bus_address()
    assert address is not None
    why = _why("close")
    connection = await asyncio.to_thread(dbus.Connection.open, address)
    reply = await asyncio.to_thread(sleep._pm_inhibit, connection, why, 5.0)
    print(f"PowerManagement cookie: {reply.signature} {reply.body}")
    during = await _kde_appears(why)
    print(f"PowerManagement during: {during}")
    assert [e[:2] for e in during] == [["sleep", "Reframe"]]
    connection.close()  # no UnInhibit: as if Reframe crashed
    assert await _kde_gone(why)
    print(f"PowerManagement after the connection closed: {await _kde_ours(why)}")


@pytest.mark.slow
@pytest.mark.usefixtures("logind", "kde")
async def test_kde_turns_a_logind_idle_lock_into_a_screen_inhibition() -> None:
    """Why the logind idle lock is taken only where needed: KDE mirrors it (after ~5 s) as
    an "idle" inhibition, which also keeps the screen from dimming and locking."""
    why = _why("mirror")
    screen_before = await _flag(POLICY_AGENT, "HasInhibition", SCREEN)
    inhibitor = SleepInhibitor([LogindBackend()])
    assert await inhibitor.acquire(why) is InhibitState.ACTIVE
    during = await _kde_appears(why)
    print(f"logind idle lock only, KDE during: {during}")
    assert [e[:2] for e in during] == [["idle", "Reframe"]]
    await _check_global_flag(
        "PolicyAgent screen", screen_before, 1, lambda: _flag(POLICY_AGENT, "HasInhibition", 4)
    )
    await inhibitor.close()
    assert await _kde_gone(why)
    print(f"logind idle lock only, KDE after: {await _kde_ours(why)}")
