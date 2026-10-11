"""reframe.events.EventBus: fan-out, bounded queues with drop-oldest, close, threads."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from reframe.events import DEFAULT_MAX_QUEUE, EventBus, Subscription
from reframe.models import (
    EVENT_ADAPTER,
    JobProgress,
    JobProgressEvent,
    JobState,
    JobStateEvent,
    NotificationEvent,
    QueueChangedEvent,
)

pytestmark = pytest.mark.anyio


def _progress(n: int) -> JobProgressEvent:
    return JobProgressEvent(job_id="j1", progress=JobProgress(percent=float(n % 101)))


async def _drain(sub: Subscription, count: int) -> list[object]:
    events: list[object] = []
    async for event in sub:
        events.append(event)
        if len(events) == count:
            break
    return events


async def test_every_subscriber_gets_every_event_in_order() -> None:
    bus = EventBus()
    a = bus.subscribe()
    b = bus.subscribe()
    events = [_progress(i) for i in range(5)]
    for event in events:
        bus.publish(event)
    assert await _drain(a, 5) == events
    assert await _drain(b, 5) == events
    assert bus.subscriber_count == 2


async def test_waiting_subscriber_is_woken() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    task = asyncio.ensure_future(_drain(sub, 1))
    await asyncio.sleep(0.01)
    assert not task.done()
    bus.publish(QueueChangedEvent(job_ids=["a", "b"]))
    assert await asyncio.wait_for(task, 2) == [QueueChangedEvent(job_ids=["a", "b"])]


async def test_type_filter() -> None:
    bus = EventBus()
    sub = bus.subscribe(types={"job.state"})
    bus.publish(_progress(1))
    state = JobStateEvent(job_id="j1", state=JobState.RUNNING)
    bus.publish(state)
    assert await _drain(sub, 1) == [state]
    assert sub.pending() == 0


async def test_slow_subscriber_drops_the_oldest_and_counts() -> None:
    bus = EventBus()
    slow = bus.subscribe(max_queue=3)
    fast = bus.subscribe(max_queue=100)
    for i in range(10):
        bus.publish(_progress(i))
    assert slow.dropped == 7
    assert slow.pending() == 3
    assert [e.progress.percent for e in await _drain(slow, 3)] == [7.0, 8.0, 9.0]  # type: ignore[attr-defined]
    assert fast.dropped == 0
    assert len(await _drain(fast, 10)) == 10


def test_publish_never_waits() -> None:
    bus = EventBus(max_queue=10)
    subs = [bus.subscribe() for _ in range(5)]
    started = time.perf_counter()
    for i in range(20_000):
        bus.publish(_progress(i))
    assert time.perf_counter() - started < 5  # no subscriber reads, nothing blocks
    assert all(sub.dropped == 20_000 - 10 for sub in subs)
    assert DEFAULT_MAX_QUEUE == 1000


async def test_close_ends_iteration_after_queued_events() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish(_progress(1))
    bus.publish(_progress(2))
    bus.close()
    bus.publish(_progress(3))  # ignored after close
    received = [event async for event in sub]
    assert received == [_progress(1), _progress(2)]
    assert bus.closed
    assert sub.closed
    assert bus.subscriber_count == 0


async def test_close_wakes_a_waiting_subscriber() -> None:
    bus = EventBus()
    sub = bus.subscribe()

    async def consume() -> list[object]:
        return [event async for event in sub]

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.01)
    bus.close()
    assert await asyncio.wait_for(task, 2) == []


async def test_subscribe_after_close() -> None:
    bus = EventBus()
    bus.close()
    sub = bus.subscribe()
    assert sub.closed
    assert [e async for e in sub] == []


async def test_subscription_close_and_context_manager() -> None:
    bus = EventBus()
    async with bus.subscribe() as sub:
        bus.publish(_progress(1))
        assert sub.get_nowait() == _progress(1)
        assert sub.get_nowait() is None
    assert sub.closed
    assert bus.subscriber_count == 0
    bus.publish(_progress(2))
    assert sub.pending() == 0
    sub.close()  # twice is fine


async def test_publish_from_another_thread_wakes_the_subscriber() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    task = asyncio.ensure_future(_drain(sub, 3))
    await asyncio.sleep(0.01)

    def worker() -> None:
        for i in range(3):
            bus.publish(_progress(i))
            time.sleep(0.01)

    thread = threading.Thread(target=worker)
    thread.start()
    received = await asyncio.wait_for(task, 5)
    thread.join()
    assert received == [_progress(0), _progress(1), _progress(2)]


async def test_close_from_another_thread() -> None:
    bus = EventBus()
    sub = bus.subscribe()

    async def consume() -> list[object]:
        return [event async for event in sub]

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.01)
    threading.Thread(target=bus.close).start()
    assert await asyncio.wait_for(task, 5) == []


def test_publish_to_a_subscriber_whose_loop_is_closed() -> None:
    bus = EventBus()
    sub = bus.subscribe()

    async def first() -> object:
        bus.publish(_progress(1))
        return await sub.__anext__()

    assert asyncio.run(first()) == _progress(1)
    bus.publish(_progress(2))  # the loop is gone: queued, no error
    assert sub.get_nowait() == _progress(2)


def test_invalid_queue_length() -> None:
    with pytest.raises(ValueError, match="max_queue"):
        EventBus().subscribe(max_queue=0)


def test_events_round_trip_through_the_adapter() -> None:
    event = NotificationEvent(title="Queue finished", message="3 jobs", level="success")
    text = EVENT_ADAPTER.dump_json(event)
    assert EVENT_ADAPTER.validate_json(text) == event
    assert b'"type":"notification"' in text
