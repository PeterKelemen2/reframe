"""The real sleep inhibit on this machine, checked through logind and the KDE session bus."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import os
import shutil
import sys
import time
import uuid
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable

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


# Other programs hold inhibits too: a test looks only for its own reason.
def _why(label: str) -> str:
    return f"Reframe {label} {uuid.uuid4().hex[:10]}"


def _logind_reachable() -> str | None:
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


async def _logind_inhibitors() -> list[list[object]]:
    """logind's inhibitors: ``[what, who, why, mode, uid, pid]`` each."""
    data = await _busctl_json(
        "call",
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "ListInhibitors",
    )
    assert isinstance(data, dict)
    (inhibitors,) = data["data"]
    assert isinstance(inhibitors, list)
    return inhibitors


async def _logind_ours(why: str) -> list[list[object]]:
    return [entry for entry in await _logind_inhibitors() if entry[2] == why]


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


async def _print_flags(label: str) -> None:
    """Global flags, printed only: other programs change them at any time."""
    has = await _flag(PM, "HasInhibit")
    suspend = await _flag(POLICY_AGENT, "HasInhibition", SUSPEND)
    screen = await _flag(POLICY_AGENT, "HasInhibition", SCREEN)
    print(f"{label}: HasInhibit={has} PolicyAgent suspend={suspend} screen={screen}")


async def _foreign_sleep_blocks(why: str) -> list[list[object]]:
    """logind's ``sleep`` block locks of other programs (they would change ``CanSuspend``)."""
    return [
        entry
        for entry in await _logind_inhibitors()
        if "sleep" in str(entry[0]).split(":") and entry[3] == "block" and entry[2] != why
    ]


async def _check_can_suspend(why: str, before: str) -> None:
    """The user's own suspend is never blocked by Reframe.

    ``CanSuspend`` is global: another program's ``sleep`` block lock turns it to
    ``inhibited``. So a change is a failure only when no other program holds such a lock.
    """
    during = await _can_suspend()
    print(f"CanSuspend before={before} during={during}")
    if before != "yes":  # pragma: no cover
        print(f"not checked: CanSuspend was {before!r} before the test")
        return
    if during == "yes":
        return
    foreign = await _foreign_sleep_blocks(why)  # pragma: no cover
    if foreign:  # pragma: no cover
        print(f"not checked: other programs hold sleep block locks: {foreign}")
        return
    raise AssertionError(f"CanSuspend is {during!r} and only Reframe holds a lock")


def _open_fds() -> set[int]:
    """Only new fds count as a leak: other tests' objects may close theirs meanwhile."""
    return {int(name) for name in os.listdir("/proc/self/fd")}


def _new_fds(before: set[int]) -> dict[int, str]:
    new: dict[int, str] = {}
    for fd in sorted(_open_fds() - before):
        try:
            new[fd] = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue  # closed meanwhile
    return new


def _assert_nothing_left(fds_before: set[int]) -> None:
    assert not _new_fds(fds_before)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    unclosed = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
    assert not unclosed


@contextlib.asynccontextmanager
async def _closing(inhibitor: SleepInhibitor) -> AsyncIterator[SleepInhibitor]:
    """Close the inhibitor at the end whatever happens: a failing check never leaks a lock
    or a socket into a later test."""
    try:
        yield inhibitor
    finally:
        await inhibitor.close()


@contextlib.asynccontextmanager
async def _session_connection() -> AsyncIterator[dbus.Connection]:
    address = dbus.session_bus_address()
    if address is None:  # pragma: no cover
        pytest.skip("no session bus")
    try:
        connection = await asyncio.to_thread(dbus.Connection.open, address)
    except OSError as exc:  # pragma: no cover
        pytest.skip(f"no session bus: {exc}")
    try:
        yield connection
    finally:
        connection.close()


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


@pytest.mark.usefixtures("logind")
async def test_logind_idle_lock_appears_and_disappears() -> None:
    why = _why("logind")
    fds_before = _open_fds()
    can_before = await _can_suspend()
    assert await _logind_ours(why) == []

    async with _closing(SleepInhibitor([LogindBackend()])) as inhibitor:
        assert await inhibitor.acquire(why) is InhibitState.ACTIVE
        during = await _logind_ours(why)
        print(f"logind during: {during}")
        (entry,) = during
        what, who, _, mode, _, pid = entry
        assert what == "idle"  # never "sleep": that would block the user's own suspend
        assert who == "Reframe"
        assert mode == "block"
        assert pid == os.getpid()  # logind records the caller: Reframe itself
        await _check_can_suspend(why, can_before)

        await inhibitor.release()
        after = await _logind_ours(why)
        print(f"logind after: {after}")
        assert after == []
    _assert_nothing_left(fds_before)


@pytest.mark.slow
@pytest.mark.usefixtures("power_management", "kde")
async def test_session_inhibit_appears_and_disappears() -> None:
    why = _why("session")
    fds_before = _open_fds()
    can_before = await _can_suspend() if _logind_reachable() is None else None
    assert await _kde_ours(why) == []
    await _print_flags("before")

    backend = SessionInhibitBackend()
    async with _closing(SleepInhibitor([backend])) as inhibitor:
        assert await inhibitor.acquire(why) is InhibitState.ACTIVE
        assert backend.interface == "org.freedesktop.PowerManagement.Inhibit"
        during = await _kde_appears(why)
        print(f"KDE during: {during}")
        # Our own inhibition is "sleep" (automatic suspend only), not "idle" (which would
        # also keep the screen on).
        (entry,) = during
        assert entry[:2] == ["sleep", "Reframe"]
        await _print_flags("during")
        if can_before is not None:
            await _check_can_suspend(why, can_before)

        await inhibitor.release()
        assert await _kde_gone(why)
        print(f"KDE after: {await _kde_ours(why)}")
        await _print_flags("after")
    _assert_nothing_left(fds_before)  # the session connection is closed


@pytest.mark.slow
@pytest.mark.usefixtures("logind", "power_management", "kde")
async def test_default_inhibitor_on_this_desktop() -> None:
    why = _why("default")
    bus = EventBus()
    sub = bus.subscribe()
    fds_before = _open_fds()
    can_before = await _can_suspend()
    idle_action = await LogindBackend().idle_action()
    async with _closing(create_sleep_inhibitor(bus)) as inhibitor:
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
        else:  # pragma: no cover
            assert inhibitor.backends == ("session", "logind")
        await _check_can_suspend(why, can_before)
        assert inhibitor.not_stopped == ()
        await inhibitor.close()
        await inhibitor.close()
        assert await _kde_gone(why)
        assert await _logind_ours(why) == []
    assert sub.get_nowait() is None  # no warning
    _assert_nothing_left(fds_before)


@pytest.mark.usefixtures("logind")
async def test_without_a_desktop_session_the_logind_idle_lock_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    why = _why("headless")
    fds_before = _open_fds()
    async with _closing(create_sleep_inhibitor()) as inhibitor:
        assert await inhibitor.acquire(why) is InhibitState.ACTIVE
        during = await _logind_ours(why)
        print(f"headless: backends={inhibitor.backends} during={during}")
        assert inhibitor.backends == ("logind",)
        assert inhibitor.not_stopped == ()  # no desktop: nothing else to stop
        (entry,) = during
        assert entry[0] == "idle"
        await inhibitor.close()
        assert await _logind_ours(why) == []
    _assert_nothing_left(fds_before)


async def _fail_while_the_inhibitor_holds(inhibitor: SleepInhibitor, why: str) -> None:
    async with _closing(inhibitor):
        assert await inhibitor.acquire(why) is InhibitState.ACTIVE
        assert inhibitor.backends == ("session", "logind")
        assert inhibitor.count == 0, "deliberate"


async def _fail_while_a_connection_holds(why: str) -> None:
    async with _session_connection() as connection:
        await asyncio.to_thread(sleep._pm_inhibit, connection, why, 5.0)
        assert connection.closed, "deliberate"


@pytest.mark.usefixtures("logind", "power_management")
async def test_a_failing_check_inside_the_hold_frees_everything() -> None:
    why = _why("failing")
    fds_before = _open_fds()
    inhibitor = SleepInhibitor([SessionInhibitBackend(), LogindBackend()])
    with pytest.raises(AssertionError, match="deliberate"):
        await _fail_while_the_inhibitor_holds(inhibitor, why)
    assert inhibitor.backends == ()
    assert await _logind_ours(why) == []
    _assert_nothing_left(fds_before)

    with pytest.raises(AssertionError, match="deliberate"):
        await _fail_while_a_connection_holds(why)
    _assert_nothing_left(fds_before)


@pytest.mark.slow
@pytest.mark.usefixtures("kde")
async def test_portal_inhibit_with_this_client() -> None:
    """The portal fallback (GNOME and others), checked through KDE's portal backend."""
    why = _why("portal")
    fds_before = _open_fds()
    async with _session_connection() as connection:
        try:
            reply = await asyncio.to_thread(sleep._portal_inhibit, connection, why, 5.0)
        except dbus.DBusError as exc:  # pragma: no cover
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
    assert connection.closed
    _assert_nothing_left(fds_before)


@pytest.mark.slow
@pytest.mark.usefixtures("power_management", "kde")
async def test_closing_the_connection_alone_ends_the_power_management_inhibit() -> None:
    why = _why("close")
    fds_before = _open_fds()
    async with _session_connection() as connection:
        reply = await asyncio.to_thread(sleep._pm_inhibit, connection, why, 5.0)
        print(f"PowerManagement cookie: {reply.signature} {reply.body}")
        during = await _kde_appears(why)
        print(f"PowerManagement during: {during}")
        assert [e[:2] for e in during] == [["sleep", "Reframe"]]
        connection.close()  # no UnInhibit: as if Reframe crashed
        assert await _kde_gone(why)
        print(f"PowerManagement after the connection closed: {await _kde_ours(why)}")
    _assert_nothing_left(fds_before)


@pytest.mark.slow
@pytest.mark.usefixtures("logind", "kde")
async def test_kde_turns_a_logind_idle_lock_into_an_idle_inhibition() -> None:
    why = _why("mirror")
    fds_before = _open_fds()
    async with _closing(SleepInhibitor([LogindBackend()])) as inhibitor:
        assert await inhibitor.acquire(why) is InhibitState.ACTIVE
        during = await _kde_appears(why)
        print(f"logind idle lock only, KDE during: {during}")
        # Our own entry: "idle" (the kind that keeps the screen on), not "sleep".
        assert [e[:2] for e in during] == [["idle", "Reframe"]]
        await _print_flags("logind idle lock only, during")
        await inhibitor.close()
        assert await _kde_gone(why)
        print(f"logind idle lock only, KDE after: {await _kde_ours(why)}")
    _assert_nothing_left(fds_before)
