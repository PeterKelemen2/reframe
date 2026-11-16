"""reframe.events.EventBus: fan-out, coalescing, lossy drops, overflow, close and threads."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from reframe.events import DEFAULT_MAX_QUEUE, EventBus, Subscription
from reframe.models import (
    JobLogEvent,
    JobProgress,
    JobProgressEvent,
    JobState,
    JobStateEvent,
    QueueChangedEvent,
    ResyncEvent,
    TaskDoneEvent,
    TaskInfo,
    TaskProgressEvent,
    TaskState,
    ToolsChangedEvent,
    ToolSet,
)

pytestmark = pytest.mark.anyio


def _progress(n: int, job: str | None = None) -> JobProgressEvent:
    return JobProgressEvent(
        job_id=job if job is not None else f"j{n}", progress=JobProgress(percent=float(n % 101))
    )


def _state(job: str, state: JobState = JobState.DONE) -> JobStateEvent:
    return JobStateEvent(job_id=job, state=state)


def _task_progress(task: str, percent: float) -> TaskProgressEvent:
    return TaskProgressEvent(
        task=TaskInfo(id=task, kind="probe_sources", state=TaskState.RUNNING, progress=percent)
    )


def _task_done(task: str) -> TaskDoneEvent:
    return TaskDoneEvent(task=TaskInfo(id=task, kind="probe_sources", state=TaskState.DONE))


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


async def test_progress_is_coalesced_per_job_and_task() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish(_progress(10, job="a"))
    bus.publish(_task_progress("t1", 5))
    bus.publish(_progress(20, job="b"))
    bus.publish(_progress(30, job="a"))  # replaces a@10 and goes to the end
    bus.publish(_task_progress("t1", 50))
    events = await _drain(sub, 3)
    assert events == [_progress(20, job="b"), _progress(30, job="a"), _task_progress("t1", 50)]
    assert sub.coalesced == 2
    assert sub.dropped == 0


async def test_state_events_are_never_coalesced() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    events = [_state("a", JobState.RUNNING), _state("a", JobState.PAUSED), _state("a")]
    for event in events:
        bus.publish(event)
    assert await _drain(sub, 3) == events


async def test_a_flood_of_progress_never_drops_state_or_terminal_events() -> None:
    bus = EventBus()
    sub = bus.subscribe(max_queue=5, hard_limit=100)
    essential: list[object] = []
    for i in range(200):
        bus.publish(_progress(i))  # 200 different jobs: nothing coalesces
        bus.publish(_task_progress(f"t{i}", 50))
        if i % 20 == 0:
            for event in (_state(f"j{i}"), _task_done(f"t{i}")):
                essential.append(event)
                bus.publish(event)
    bus.publish(ToolsChangedEvent(tools=_tool_set()))
    essential.append(ToolsChangedEvent(tools=_tool_set()))
    received = [sub.get_nowait() for _ in range(sub.pending())]
    kept = [
        e
        for e in received
        if e is not None and e.type not in ("job.progress", "task.progress", "resync")
    ]
    assert kept == essential
    markers = [e for e in received if isinstance(e, ResyncEvent)]
    assert len(markers) == 1
    assert markers[0].reason == "dropped"
    assert markers[0].dropped == sub.dropped > 0
    assert not sub.overflowed


async def test_the_marker_sits_where_the_events_were_dropped() -> None:
    bus = EventBus()
    sub = bus.subscribe(max_queue=3)
    bus.publish(_state("a"))
    bus.publish(_progress(1))
    bus.publish(_progress(2))
    bus.publish(_progress(3))  # full: drops progress 1, the marker takes its place
    bus.publish(_progress(4))  # drops progress 2, the marker counts it
    events = await _drain(sub, 4)
    assert events[0] == _state("a")
    assert events[1] == ResyncEvent(reason="dropped", dropped=2)
    assert events[2:] == [_progress(3), _progress(4)]
    assert sub.dropped == 2
    # A new drop after the marker was read gets a new marker.
    for i in range(5, 9):
        bus.publish(_progress(i))
    later = await _drain(sub, 4)
    assert later[0] == ResyncEvent(reason="dropped", dropped=1)
    assert sub.dropped == 3


async def test_a_new_lossy_event_is_dropped_when_only_state_events_are_queued() -> None:
    bus = EventBus()
    sub = bus.subscribe(max_queue=2)
    bus.publish(_state("a"))
    bus.publish(_state("b"))
    bus.publish(JobLogEvent(job_id="a", lines=["frame=1"]))
    assert await _drain(sub, 3) == [_state("a"), _state("b"), ResyncEvent(dropped=1)]


async def test_state_events_grow_the_queue_then_overflow_closes_it() -> None:
    bus = EventBus()
    sub = bus.subscribe(max_queue=2, hard_limit=4)
    other = bus.subscribe()
    states = [_state(f"j{i}") for i in range(6)]
    for event in states:
        bus.publish(event)
    assert sub.overflowed
    assert sub.closed
    assert bus.subscriber_count == 1  # removed from the bus; the other one is fine
    received = [event async for event in sub]
    assert received == [*states[:4], ResyncEvent(reason="overflow", dropped=0)]
    assert await _drain(other, 6) == states


async def test_the_marker_passes_the_type_filter() -> None:
    bus = EventBus()
    sub = bus.subscribe(max_queue=1, types={"job.progress"})
    bus.publish(_progress(1))
    bus.publish(_state("x"))  # filtered out
    bus.publish(_progress(2))
    assert await _drain(sub, 2) == [ResyncEvent(dropped=1), _progress(2)]


def _tool_set() -> ToolSet:
    from reframe.models import ToolInfo, ToolStatus

    return ToolSet(
        **{name: ToolInfo(name=name, status=ToolStatus.MISSING) for name in ("ffmpeg", "ffprobe")}
    )


def test_publish_never_waits() -> None:
    bus = EventBus(max_queue=10)
    subs = [bus.subscribe() for _ in range(5)]
    started = time.perf_counter()
    for i in range(20_000):
        bus.publish(_progress(i))
    assert time.perf_counter() - started < 10  # no subscriber reads, nothing blocks
    assert all(sub.dropped == 20_000 - 10 for sub in subs)
    assert all(sub.pending() == 11 for sub in subs)  # 10 events and one resync marker
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
