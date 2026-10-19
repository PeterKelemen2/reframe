"""reframe.platform.sleep: the counted inhibitor, backends held together, the warning event."""

from __future__ import annotations

import asyncio

import pytest

from reframe.events import EventBus, Subscription
from reframe.models.events import AppWarningEvent
from reframe.platform import sleep
from reframe.platform.sleep import (
    InhibitState,
    LogindBackend,
    SessionInhibitBackend,
    Skipped,
    SleepInhibitor,
    WindowsExecutionStateBackend,
    create_sleep_inhibitor,
)

pytestmark = pytest.mark.anyio


class FakeBackend:
    """Records hold/free; ``error`` makes hold fail (a :class:`Skipped` skips it); ``gate``
    makes hold wait."""

    def __init__(
        self, name: str = "fake", *, error: str | None = None, gate: asyncio.Event | None = None
    ) -> None:
        self.name = name
        self.stops = f"what {name} stops"
        self.error = error
        self.gate = gate
        self.calls: list[str] = []
        self.held = False

    async def hold(self, why: str) -> str | None:
        self.calls.append(f"hold:{why}")
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            return self.error
        self.held = True
        return None

    def is_held(self) -> bool:
        return self.held

    async def free(self) -> None:
        self.calls.append("free")
        self.held = False


def _state(inhibitor: SleepInhibitor) -> InhibitState:
    """The state, read through a function so that mypy does not narrow the property."""
    return inhibitor.state


def _not_stopped(inhibitor: SleepInhibitor) -> tuple[str, ...]:
    return inhibitor.not_stopped


def _backend(inhibitor: SleepInhibitor) -> str | None:
    return inhibitor.backend


def _warnings(sub: Subscription) -> list[AppWarningEvent]:
    out: list[AppWarningEvent] = []
    while (event := sub.get_nowait()) is not None:
        assert isinstance(event, AppWarningEvent)
        out.append(event)
    return out


async def test_nested_acquire_takes_and_frees_the_lock_once() -> None:
    backend = FakeBackend()
    inhibitor = SleepInhibitor([backend])
    assert _state(inhibitor) is InhibitState.INACTIVE
    assert await inhibitor.acquire("job 1") is InhibitState.ACTIVE
    assert await inhibitor.acquire("job 2") is InhibitState.ACTIVE
    assert inhibitor.count == 2
    assert inhibitor.backend == "fake"
    await inhibitor.release()
    assert backend.is_held()
    assert _state(inhibitor) is InhibitState.ACTIVE
    await inhibitor.release()
    assert not backend.is_held()
    assert _state(inhibitor) is InhibitState.INACTIVE
    assert _backend(inhibitor) is None
    await inhibitor.release()  # an extra release does nothing
    assert inhibitor.count == 0
    assert backend.calls == ["hold:job 1", "free"]


async def test_acquire_again_after_release_takes_a_new_lock() -> None:
    backend = FakeBackend()
    inhibitor = SleepInhibitor([backend])
    await inhibitor.acquire("a")
    await inhibitor.release()
    await inhibitor.acquire("b")
    await inhibitor.release()
    assert backend.calls == ["hold:a", "free", "hold:b", "free"]


async def test_close_frees_whatever_the_count_and_is_idempotent() -> None:
    backend = FakeBackend()
    inhibitor = SleepInhibitor([backend])
    for _ in range(3):
        await inhibitor.acquire("job")
    await inhibitor.close()
    assert not backend.is_held()
    assert inhibitor.count == 0
    assert _state(inhibitor) is InhibitState.INACTIVE
    await inhibitor.close()
    await inhibitor.release()
    assert backend.calls == ["hold:job", "free"]
    # Closed is final: a late acquire (a job that starts during shutdown) takes nothing.
    assert await inhibitor.acquire("late") is InhibitState.INACTIVE
    assert inhibitor.count == 0
    assert backend.calls == ["hold:job", "free"]
    assert inhibitor.closed


async def test_concurrent_first_acquires_take_the_lock_once() -> None:
    gate = asyncio.Event()
    backend = FakeBackend(gate=gate)
    inhibitor = SleepInhibitor([backend])
    first = asyncio.ensure_future(inhibitor.acquire("a"))
    second = asyncio.ensure_future(inhibitor.acquire("b"))
    await asyncio.sleep(0.01)
    gate.set()
    assert await first is InhibitState.ACTIVE
    assert await second is InhibitState.ACTIVE
    assert backend.calls == ["hold:a"]
    assert inhibitor.count == 2


async def test_all_backends_are_held_together() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    session = FakeBackend("session")
    logind = FakeBackend("logind")
    inhibitor = SleepInhibitor([session, logind], bus)
    assert await inhibitor.acquire("encode") is InhibitState.ACTIVE
    assert inhibitor.backends == ("session", "logind")
    assert inhibitor.backend == "session+logind"
    assert inhibitor.not_stopped == ()
    assert inhibitor.last_error is None
    await inhibitor.release()
    assert session.calls == ["hold:encode", "free"]
    assert logind.calls == ["hold:encode", "free"]
    assert _warnings(sub) == []


async def test_one_backend_fails_active_says_what_is_not_stopped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    sub = bus.subscribe()
    session = FakeBackend("session", error="org.freedesktop.portal.Inhibit: ServiceUnknown")
    logind = FakeBackend("logind")
    inhibitor = SleepInhibitor([session, logind], bus)
    with caplog.at_level("WARNING", logger="reframe.platform.sleep"):
        assert await inhibitor.acquire("encode") is InhibitState.ACTIVE
    assert inhibitor.backend == "logind"
    assert inhibitor.not_stopped == ("what session stops",)
    assert inhibitor.last_error == "session: org.freedesktop.portal.Inhibit: ServiceUnknown"
    assert "only partly active: what session stops not stopped" in caplog.text
    assert _warnings(sub) == []  # the event is for "nothing held" only
    await inhibitor.release()
    assert _not_stopped(inhibitor) == ()
    assert session.calls == ["hold:encode"]  # nothing to free
    assert logind.calls == ["hold:encode", "free"]


async def test_a_skipped_backend_is_not_a_failure() -> None:
    session = FakeBackend("session", error=Skipped("no session bus"))
    logind = FakeBackend("logind")
    inhibitor = SleepInhibitor([session, logind])
    assert await inhibitor.acquire("encode") is InhibitState.ACTIVE
    assert inhibitor.not_stopped == ()
    assert inhibitor.last_error is None
    await inhibitor.close()


async def test_only_skipped_backends_is_unavailable() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = SleepInhibitor([FakeBackend("session", error=Skipped("no session bus"))], bus)
    assert await inhibitor.acquire("encode") is InhibitState.UNAVAILABLE
    assert [w.detail for w in _warnings(sub)] == ["session: no session bus"]


async def test_no_backend_works_one_warning_and_goes_on() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = SleepInhibitor(
        [FakeBackend("session", error="x"), FakeBackend("logind", error="no system bus")],
        bus,
    )
    assert await inhibitor.acquire("job 1") is InhibitState.UNAVAILABLE
    assert await inhibitor.acquire("job 2") is InhibitState.UNAVAILABLE  # nested: no retry
    await inhibitor.release()
    await inhibitor.release()
    assert _state(inhibitor) is InhibitState.UNAVAILABLE  # sticky until a later success
    # The next run of the queue tries again, and still warns only once.
    assert await inhibitor.acquire("job 3") is InhibitState.UNAVAILABLE
    await inhibitor.release()
    warnings = _warnings(sub)
    assert len(warnings) == 1
    (warning,) = warnings
    assert warning.code == "sleep_inhibit.unavailable"
    assert warning.detail == "session: x; logind: no system bus"
    assert warning.message == (
        "Sleep inhibit is not available: the computer may go to sleep on its own while the "
        "queue runs."
    )
    assert inhibitor.last_error == warning.detail
    await inhibitor.close()


async def test_a_success_in_between_rearms_the_warning() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    backend = FakeBackend(error="down")
    inhibitor = SleepInhibitor([backend], bus)
    await inhibitor.acquire("a")
    await inhibitor.release()
    backend.error = None
    assert await inhibitor.acquire("b") is InhibitState.ACTIVE
    assert inhibitor.last_error is None
    await inhibitor.release()
    assert _state(inhibitor) is InhibitState.INACTIVE
    backend.error = "down again"
    await inhibitor.acquire("c")
    await inhibitor.release()
    assert [w.detail for w in _warnings(sub)] == ["fake: down", "fake: down again"]


async def test_no_events_bus_is_fine() -> None:
    inhibitor = SleepInhibitor([FakeBackend(error="down")])
    assert await inhibitor.acquire("a") is InhibitState.UNAVAILABLE
    await inhibitor.close()


async def test_cancelled_acquire_frees_the_lock_once_it_was_taken() -> None:
    gate = asyncio.Event()
    backend = FakeBackend(gate=gate)
    inhibitor = SleepInhibitor([backend])
    task = asyncio.ensure_future(inhibitor.acquire("job"))
    await asyncio.sleep(0.01)
    assert backend.calls == ["hold:job"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.set()  # the backend finishes taking the lock after the caller gave up
    for _ in range(50):
        if backend.calls[-1] == "free":
            break
        await asyncio.sleep(0.01)
    assert backend.calls == ["hold:job", "free"]
    assert not backend.is_held()
    assert _state(inhibitor) is InhibitState.INACTIVE
    assert inhibitor.count == 0  # undone: the caller must not release it
    await inhibitor.release()  # an extra release (a caller's mistake) does nothing
    assert backend.calls == ["hold:job", "free"]


async def test_cancelled_acquire_does_not_free_a_lock_that_a_later_acquire_holds() -> None:
    gate = asyncio.Event()
    backend = FakeBackend(gate=gate)
    inhibitor = SleepInhibitor([backend])
    task = asyncio.ensure_future(inhibitor.acquire("first"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    later = asyncio.ensure_future(inhibitor.acquire("second"))
    gate.set()
    assert await later is InhibitState.ACTIVE
    await asyncio.sleep(0.02)
    assert backend.is_held()
    assert inhibitor.count == 1
    await inhibitor.release()
    assert not backend.is_held()


async def test_unsupported_platform_warns_once() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = create_sleep_inhibitor(bus, platform="darwin")
    assert await inhibitor.acquire("job") is InhibitState.UNAVAILABLE
    await inhibitor.release()
    assert [w.detail for w in _warnings(sub)] == ["no sleep inhibit backend for platform 'darwin'"]


def test_backends_per_platform() -> None:
    linux = sleep.default_backends("linux")
    assert [type(b) for b in linux] == [SessionInhibitBackend, LogindBackend]
    windows = sleep.default_backends("win32")
    assert [type(b) for b in windows] == [WindowsExecutionStateBackend]
    assert sleep.default_backends("darwin") == []
    inhibitor = create_sleep_inhibitor(backends=[FakeBackend()])
    assert _state(inhibitor) is InhibitState.INACTIVE
