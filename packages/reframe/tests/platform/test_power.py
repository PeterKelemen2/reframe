"""The power-action countdown (05 §C-14): phases and their order, cancel, a second schedule,
close, failures as ``app.warning``, quit. Every test uses a fake executor and a fake sleep
(no test waits 60 real seconds; none reaches the operating system)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from reframe.events import EventBus, Subscription
from reframe.models.events import AppWarningEvent, Event, PowerCountdownEvent
from reframe.platform.power import (
    COUNTDOWN_SECONDS,
    WARNING_CODE,
    OsAction,
    PowerService,
)

pytestmark = pytest.mark.anyio

T0 = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)


class FakeExecutor:
    """Records the actions; returns ``result`` (or raises ``error``)."""

    def __init__(self, result: str | None = None, error: Exception | None = None) -> None:
        self.actions: list[OsAction] = []
        self.result = result
        self.error = error
        self.called = asyncio.Event()

    async def execute(self, action: OsAction) -> str | None:
        self.actions.append(action)
        self.called.set()
        if self.error is not None:
            raise self.error
        return self.result


class Ticker:
    """A fake ``sleep``: every call waits until the test lets one second pass."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self._waiting: list[asyncio.Future[None]] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiting.append(future)
        await future

    @property
    def waiting(self) -> int:
        return sum(1 for f in self._waiting if not f.done())

    async def step(self, count: int = 1) -> None:
        for _ in range(count):
            await settle()
            future = next(f for f in self._waiting if not f.done())
            future.set_result(None)
            await settle()


async def instant(delay: float) -> None:
    await asyncio.sleep(0)


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def drain(subscription: Subscription) -> list[Event]:
    events: list[Event] = []
    while (event := subscription.get_nowait()) is not None:
        events.append(event)
    return events


def countdown_events(subscription: Subscription) -> list[PowerCountdownEvent]:
    return [e for e in drain(subscription) if isinstance(e, PowerCountdownEvent)]


def phases(events: list[PowerCountdownEvent]) -> list[tuple[str, int]]:
    return [(e.phase, e.seconds_left) for e in events]


def make(
    executor: FakeExecutor | None = None, *, countdown: float = COUNTDOWN_SECONDS, ticker: Ticker
) -> tuple[PowerService, Subscription, FakeExecutor]:
    events = EventBus()
    subscription = events.subscribe(max_queue=10_000)
    executor = executor if executor is not None else FakeExecutor()
    service = PowerService(
        events, executor=executor, countdown=countdown, sleep=ticker.sleep, now=lambda: T0
    )
    return service, subscription, executor


async def test_full_countdown_phases_in_order_then_the_executor_runs() -> None:
    ticker = Ticker()
    service, subscription, executor = make(ticker=ticker)
    countdown_id = service.schedule("shutdown", reason="queue done")
    started = countdown_events(subscription)
    assert phases(started) == [("started", 60)]
    assert started[0].deadline == T0 + timedelta(seconds=60)
    assert started[0].countdown_id == countdown_id
    first = service.pending
    assert first == started[0]

    await ticker.step(59)
    ticks = countdown_events(subscription)
    assert phases(ticks) == [("tick", left) for left in range(59, 0, -1)]
    last = service.pending
    assert last == ticks[-1]
    assert executor.actions == []

    await ticker.step()
    final = countdown_events(subscription)
    assert phases(final) == [("executing", 0)]
    assert executor.actions == ["shutdown"]
    assert service.pending is None
    assert ticker.delays == [1.0] * 60  # one second per tick, never more
    events = started + ticks + final
    assert {e.countdown_id for e in events} == {countdown_id}
    assert {e.action for e in events} == {"shutdown"}
    assert {e.deadline for e in events} == {T0 + timedelta(seconds=60)}
    await service.close()


async def test_sleep_runs_the_sleep_action() -> None:
    service, subscription, executor = make(countdown=3, ticker=Ticker())
    service._sleep = instant
    service.schedule("sleep")
    await settle()
    assert phases(countdown_events(subscription)) == [
        ("started", 3),
        ("tick", 2),
        ("tick", 1),
        ("executing", 0),
    ]
    assert executor.actions == ["sleep"]
    assert [e for e in drain(subscription) if isinstance(e, AppWarningEvent)] == []


async def test_quit_only_publishes_executing() -> None:
    ticker = Ticker()
    service, subscription, executor = make(countdown=2, ticker=ticker)
    service.schedule("quit")
    await ticker.step(2)
    events = countdown_events(subscription)
    assert phases(events) == [("started", 2), ("tick", 1), ("executing", 0)]
    assert {e.action for e in events} == {"quit"}
    assert executor.actions == []
    assert service.pending is None


async def test_a_fractional_countdown_reaches_whole_seconds_first() -> None:
    ticker = Ticker()
    service, subscription, executor = make(countdown=2.5, ticker=ticker)
    service.schedule("sleep")
    await ticker.step(3)
    assert phases(countdown_events(subscription)) == [
        ("started", 3),
        ("tick", 2),
        ("tick", 1),
        ("executing", 0),
    ]
    assert ticker.delays == [0.5, 1.0, 1.0]
    assert executor.actions == ["sleep"]


async def test_zero_countdown_executes_without_ticks() -> None:
    service, subscription, executor = make(countdown=0, ticker=Ticker())
    service.schedule("shutdown")
    await settle()
    assert phases(countdown_events(subscription)) == [("started", 0), ("executing", 0)]
    assert executor.actions == ["shutdown"]


async def test_cancel_without_id_stops_the_running_countdown() -> None:
    ticker = Ticker()
    service, subscription, executor = make(ticker=ticker)
    service.schedule("shutdown")
    await ticker.step(3)
    assert service.cancel() is True
    events = countdown_events(subscription)
    assert phases(events)[-1] == ("cancelled", 57)
    assert service.pending is None
    await settle()
    assert ticker.waiting == 0  # the countdown task ended
    assert service.cancel() is False  # nothing runs any more
    assert countdown_events(subscription) == []
    assert executor.actions == []
    await service.close()
    assert executor.actions == []


async def test_cancel_by_id_only_cancels_that_countdown() -> None:
    ticker = Ticker()
    service, subscription, executor = make(countdown=5, ticker=ticker)
    countdown_id = service.schedule("sleep")
    assert service.cancel("not-" + countdown_id) is False
    await ticker.step()
    assert phases(countdown_events(subscription)) == [("started", 5), ("tick", 4)]
    assert service.cancel(countdown_id) is True
    assert phases(countdown_events(subscription)) == [("cancelled", 4)]
    assert service.cancel(countdown_id) is False
    await settle()
    assert executor.actions == []


async def test_cancel_right_away_has_the_full_time_left() -> None:
    service, subscription, _ = make(ticker=Ticker())
    service.schedule("shutdown")
    assert service.cancel() is True
    assert phases(countdown_events(subscription)) == [("started", 60), ("cancelled", 60)]


async def test_cancel_wins_when_the_last_second_is_already_over() -> None:
    """The last sleep has ended, but the task has not run yet: ``cancel`` still wins."""
    ticker = Ticker()
    service, subscription, executor = make(countdown=1, ticker=ticker)
    service.schedule("shutdown")
    await settle()
    next(f for f in ticker._waiting if not f.done()).set_result(None)  # no settle
    assert service.cancel() is True
    await settle()
    assert phases(countdown_events(subscription)) == [("started", 1), ("cancelled", 1)]
    assert executor.actions == []


async def test_a_second_schedule_cancels_the_first() -> None:
    ticker = Ticker()
    service, subscription, executor = make(countdown=4, ticker=ticker)
    first = service.schedule("shutdown")
    await ticker.step()
    second = service.schedule("sleep")
    assert first != second
    events = countdown_events(subscription)
    assert [(e.countdown_id, e.phase, e.seconds_left) for e in events] == [
        (first, "started", 4),
        (first, "tick", 3),
        (first, "cancelled", 3),
        (second, "started", 4),
    ]
    assert service.cancel(first) is False
    await ticker.step(4)
    events = countdown_events(subscription)
    assert {e.countdown_id for e in events} == {second}
    assert phases(events) == [("tick", 3), ("tick", 2), ("tick", 1), ("executing", 0)]
    assert executor.actions == ["sleep"]


async def test_close_during_a_countdown_cancels_and_never_executes() -> None:
    ticker = Ticker()
    service, subscription, executor = make(ticker=ticker)
    service.schedule("shutdown")
    await ticker.step(10)
    await service.close()
    assert phases(countdown_events(subscription))[-1] == ("cancelled", 50)
    assert service.pending is None
    assert service.closed
    await settle()
    assert ticker.waiting == 0
    assert executor.actions == []
    await service.close()  # safe twice
    assert countdown_events(subscription) == []


async def test_close_without_a_countdown_and_twice() -> None:
    service, subscription, _ = make(ticker=Ticker())
    await service.close()
    await service.close()
    assert drain(subscription) == []


async def test_schedule_after_close_starts_nothing() -> None:
    ticker = Ticker()
    service, subscription, executor = make(ticker=ticker)
    await service.close()
    countdown_id = service.schedule("shutdown")
    events = countdown_events(subscription)
    assert [(e.countdown_id, e.phase, e.seconds_left) for e in events] == [
        (countdown_id, "cancelled", 60)
    ]
    assert service.pending is None
    await settle()
    assert ticker.waiting == 0
    assert executor.actions == []


class BlockingExecutor(FakeExecutor):
    """``execute`` waits until the test releases it; records whether it was cancelled."""

    def __init__(self, result: str | None = None) -> None:
        super().__init__(result)
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False
        self.finished = False

    async def execute(self, action: OsAction) -> str | None:
        self.actions.append(action)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True
        return self.result

    def is_finished(self) -> bool:  # a call: mypy does not narrow it between awaits
        return self.finished


async def test_pending_stays_executing_until_the_action_returns() -> None:
    executor = BlockingExecutor()
    ticker = Ticker()
    service, subscription, _ = make(executor, countdown=1, ticker=ticker)
    countdown_id = service.schedule("shutdown")
    await ticker.step()
    await executor.started.wait()
    pending = service.pending
    assert pending is not None
    assert (pending.countdown_id, pending.phase, pending.seconds_left) == (
        countdown_id,
        "executing",
        0,
    )
    assert service.cancel() is False  # executing: too late to cancel
    assert service.cancel(countdown_id) is False
    executor.release.set()
    await settle()
    assert executor.finished
    assert service.pending is None
    assert phases(countdown_events(subscription)) == [("started", 1), ("executing", 0)]


async def test_pending_is_executing_right_after_the_event() -> None:
    """No gap: ``pending`` is the ``executing`` event as soon as it is published, before
    the executor has even started."""
    executor = BlockingExecutor()
    events = EventBus()
    seen: list[PowerCountdownEvent | None] = []
    service = PowerService(events, executor=executor, countdown=0)
    subscription = events.subscribe()
    service.schedule("sleep")
    async with asyncio.timeout(5):
        async for event in subscription:
            if isinstance(event, PowerCountdownEvent) and event.phase == "executing":
                seen.append(service.pending)
                break
    assert seen[0] is not None
    assert seen[0].phase == "executing"
    executor.release.set()
    await service.close()


async def test_close_during_execute_waits_and_never_cancels_it() -> None:
    executor = BlockingExecutor()
    service, subscription, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("shutdown")
    await executor.started.wait()
    closing = asyncio.create_task(service.close())
    await settle()
    assert not closing.done()  # close() waits for the action
    assert not executor.cancelled
    executor.release.set()
    await asyncio.wait_for(closing, 5)
    assert executor.finished
    assert not executor.cancelled
    assert service.pending is None
    assert phases(countdown_events(subscription)) == [("started", 0), ("executing", 0)]


async def test_close_waits_at_most_execute_wait_and_still_does_not_cancel() -> None:
    executor = BlockingExecutor(result="systemctl poweroff failed (exit code 1): late")
    events = EventBus()
    subscription = events.subscribe()
    service = PowerService(events, executor=executor, countdown=0, execute_wait=0.05)
    service.schedule("shutdown")
    await executor.started.wait()
    await asyncio.wait_for(service.close(), 5)  # returns after execute_wait
    assert not executor.cancelled
    assert not executor.is_finished()
    pending = service.pending
    assert pending is not None
    assert pending.phase == "executing"  # the action still runs
    executor.release.set()
    await settle()
    assert executor.finished
    assert service.pending is None
    warnings = [e for e in drain(subscription) if isinstance(e, AppWarningEvent)]
    assert [w.detail for w in warnings] == ["systemctl poweroff failed (exit code 1): late"]


async def test_a_cancelled_close_does_not_cancel_the_action() -> None:
    executor = BlockingExecutor()
    service, _, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("sleep")
    await executor.started.wait()
    closing = asyncio.create_task(service.close())
    await settle()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await settle()
    assert not executor.cancelled
    executor.release.set()
    await settle()
    assert executor.finished


async def test_schedule_while_an_action_executes_starts_a_new_countdown_beside_it() -> None:
    executor = BlockingExecutor()
    ticker = Ticker()
    service, subscription, _ = make(executor, countdown=0, ticker=ticker)
    first = service.schedule("sleep")
    await executor.started.wait()
    service._countdown = 2.0
    second = service.schedule("shutdown")
    events = countdown_events(subscription)
    # the executing action is not cancelled: no `cancelled` event for it
    assert [(e.countdown_id, e.phase) for e in events] == [
        (first, "started"),
        (first, "executing"),
        (second, "started"),
    ]
    new = service.pending
    assert new is not None
    assert (new.countdown_id, new.phase) == (second, "started")  # the countdown comes first
    assert service.cancel() is True  # cancels the new countdown only
    still = service.pending
    assert still is not None
    assert (still.countdown_id, still.phase) == (first, "executing")
    assert not executor.cancelled
    executor.release.set()
    await settle()
    assert executor.actions == ["sleep"]
    assert executor.finished
    assert service.pending is None


async def test_quit_has_nothing_to_wait_for() -> None:
    executor = BlockingExecutor()
    service, _, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("quit")
    await settle()
    assert service.pending is None
    await asyncio.wait_for(service.close(), 5)
    assert executor.actions == []


async def test_a_failing_executor_is_one_app_warning() -> None:
    executor = FakeExecutor(result="systemctl poweroff failed (exit code 1): Access denied")
    service, subscription, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("shutdown", reason="when done: shut down")
    await settle()
    events = drain(subscription)
    warnings = [e for e in events if isinstance(e, AppWarningEvent)]
    assert warnings == [
        AppWarningEvent(
            code=WARNING_CODE,
            message="Reframe could not shut down the computer.",
            detail=(
                "systemctl poweroff failed (exit code 1): Access denied "
                "(when done: when done: shut down)"
            ),
        )
    ]
    assert events.index(warnings[0]) > events.index(
        next(e for e in events if isinstance(e, PowerCountdownEvent) and e.phase == "executing")
    )
    await service.close()


async def test_a_failing_sleep_without_reason() -> None:
    executor = FakeExecutor(result="SetSuspendState failed (error 50)")
    service, subscription, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("sleep")
    await settle()
    warnings = [e for e in drain(subscription) if isinstance(e, AppWarningEvent)]
    assert [(w.code, w.message, w.detail) for w in warnings] == [
        (WARNING_CODE, "Reframe could not put the computer to sleep.", warnings[0].detail)
    ]
    assert warnings[0].detail == "SetSuspendState failed (error 50)"


async def test_an_executor_that_raises_is_still_a_warning() -> None:
    executor = FakeExecutor(error=RuntimeError("bug"))
    service, subscription, _ = make(executor, countdown=0, ticker=Ticker())
    service.schedule("shutdown")
    await settle()
    warnings = [e for e in drain(subscription) if isinstance(e, AppWarningEvent)]
    assert [w.detail for w in warnings] == ["RuntimeError: bug"]
    assert executor.actions == ["shutdown"]


async def test_the_default_sleep_counts_real_seconds() -> None:
    """One short run on the real ``asyncio.sleep`` (1.5 s: one tick, then executing)."""
    events = EventBus()
    subscription = events.subscribe()
    executor = FakeExecutor()
    service = PowerService(events, executor=executor, countdown=1.5)
    loop = asyncio.get_running_loop()
    start = loop.time()
    service.schedule("sleep")
    async with asyncio.timeout(10):
        await executor.called.wait()
    elapsed = loop.time() - start
    assert elapsed >= 1.4
    assert phases(countdown_events(subscription)) == [
        ("started", 2),
        ("tick", 1),
        ("executing", 0),
    ]
    await service.close()


async def test_the_deadline_uses_the_wall_clock() -> None:
    events = EventBus()
    subscription = events.subscribe()
    service = PowerService(events, executor=FakeExecutor(), sleep=Ticker().sleep)
    before = datetime.now(UTC)
    service.schedule("shutdown")
    after = datetime.now(UTC)
    (started,) = countdown_events(subscription)
    assert started.deadline is not None
    assert before + timedelta(seconds=60) <= started.deadline <= after + timedelta(seconds=60)
    await service.close()


def test_schedule_needs_a_running_event_loop() -> None:
    service = PowerService(EventBus(), executor=FakeExecutor())
    with pytest.raises(RuntimeError):
        service.schedule("shutdown")
    assert service.pending is None


@pytest.mark.parametrize("countdown", [-1.0, float("inf"), float("nan")])
def test_invalid_countdown(countdown: float) -> None:
    with pytest.raises(ValueError, match="countdown"):
        PowerService(EventBus(), countdown=countdown)


def test_defaults() -> None:
    service = PowerService(EventBus())
    assert service.countdown == COUNTDOWN_SECONDS == 60.0
    assert not service.closed
