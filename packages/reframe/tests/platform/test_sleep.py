"""reframe.platform.sleep: the counted inhibitor, the backend chain and the warning event.

The backends are replaced with fakes here; the logind and systemd-inhibit backends have
their own tests (``test_sleep_backends.py``), the D-Bus client ``test_sleep_dbus.py``, and
``test_sleep_real.py`` checks the real lock on a machine with logind.
"""

from __future__ import annotations

import asyncio

import pytest

from reframe.events import EventBus, Subscription
from reframe.models.events import AppWarningEvent
from reframe.platform import sleep
from reframe.platform.sleep import (
    InhibitState,
    LogindBackend,
    LostCallback,
    SleepInhibitor,
    SystemdInhibitBackend,
    WindowsExecutionStateBackend,
    create_sleep_inhibitor,
)

pytestmark = pytest.mark.anyio


class FakeBackend:
    """Records hold/free; ``error`` makes hold fail; ``gate`` makes hold wait."""

    def __init__(
        self, name: str = "fake", *, error: str | None = None, gate: asyncio.Event | None = None
    ) -> None:
        self.name = name
        self.error = error
        self.gate = gate
        self.calls: list[str] = []
        self.held = False
        self.on_lost: LostCallback | None = None

    async def hold(self, why: str, on_lost: LostCallback) -> str | None:
        self.calls.append(f"hold:{why}")
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            return self.error
        self.held = True
        self.on_lost = on_lost
        return None

    def is_held(self) -> bool:
        return self.held

    async def free(self) -> None:
        self.calls.append("free")
        self.held = False


def _state(inhibitor: SleepInhibitor) -> InhibitState:
    """The state, read through a function so that mypy does not narrow the property."""
    return inhibitor.state


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


async def test_falls_back_to_the_next_backend_without_a_warning() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    broken = FakeBackend("logind", error="Inhibit failed: AccessDenied")
    working = FakeBackend("systemd-inhibit")
    inhibitor = SleepInhibitor([broken, working], bus)
    assert await inhibitor.acquire("encode") is InhibitState.ACTIVE
    assert inhibitor.backend == "systemd-inhibit"
    assert _warnings(sub) == []
    await inhibitor.release()
    assert broken.calls == ["hold:encode"]
    assert working.calls == ["hold:encode", "free"]


async def test_no_backend_works_one_warning_and_goes_on() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    inhibitor = SleepInhibitor(
        [FakeBackend("logind", error="no system bus"), FakeBackend("systemd-inhibit", error="x")],
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
    assert warning.detail == "logind: no system bus; systemd-inhibit: x"
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


async def test_a_lost_lock_turns_unavailable_with_a_warning() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    backend = FakeBackend()
    inhibitor = SleepInhibitor([backend], bus)
    await inhibitor.acquire("job")
    assert backend.on_lost is not None
    backend.on_lost("systemd-inhibit exited unexpectedly (code -9)")
    assert _state(inhibitor) is InhibitState.UNAVAILABLE
    assert _backend(inhibitor) is None
    await inhibitor.release()  # nothing to free any more
    assert backend.calls == ["hold:job"]
    assert [w.detail for w in _warnings(sub)] == ["systemd-inhibit exited unexpectedly (code -9)"]


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
    assert inhibitor.count == 0
    gate.set()  # the backend finishes taking the lock after the caller gave up
    for _ in range(50):
        if backend.calls[-1] == "free":
            break
        await asyncio.sleep(0.01)
    assert backend.calls == ["hold:job", "free"]
    assert not backend.is_held()
    assert _state(inhibitor) is InhibitState.INACTIVE


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
    assert [type(b) for b in linux] == [LogindBackend, SystemdInhibitBackend]
    windows = sleep.default_backends("win32")
    assert [type(b) for b in windows] == [WindowsExecutionStateBackend]
    assert sleep.default_backends("darwin") == []
    inhibitor = create_sleep_inhibitor(backends=[FakeBackend()])
    assert _state(inhibitor) is InhibitState.INACTIVE


def test_lock_parameters() -> None:
    # Decision record 0011: sleep + idle, mode block (not delay, not block-weak).
    assert sleep.WHAT == "sleep:idle"
    assert sleep.MODE == "block"
    assert sleep.WHO == "Reframe"
    assert InhibitState("unavailable") is InhibitState.UNAVAILABLE
