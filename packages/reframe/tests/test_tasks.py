"""The background task manager (``reframe.tasks``, C-3 / C-10)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import psutil
import pytest
from pydantic import BaseModel

from reframe.events import EventBus, Subscription
from reframe.models import TaskDoneEvent, TaskProgressEvent, TaskState
from reframe.tasks import DEFAULT_LIMIT, TaskContext, TaskManager
from reframe.tools import run
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio


async def until(condition: Callable[[], bool], limit: float = 30.0) -> None:
    """Wait (polling) until ``condition()`` is true."""
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def drain(sub: Subscription) -> list[TaskProgressEvent | TaskDoneEvent]:
    events: list[TaskProgressEvent | TaskDoneEvent] = []
    while (event := sub.get_nowait()) is not None:
        assert isinstance(event, (TaskProgressEvent, TaskDoneEvent))
        events.append(event)
    return events


async def test_start_returns_at_once_and_progress_events_are_in_order() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    published: list[Any] = []
    publish = bus.publish

    def record(event: Any) -> None:
        published.append(event)
        publish(event)

    bus.publish = record  # type: ignore[method-assign]
    tasks = TaskManager(bus)
    gate = asyncio.Event()

    async def work(ctx: TaskContext) -> dict[str, int]:
        await gate.wait()
        for i in range(1, 4):
            ctx.progress(done=i, total=3, message=f"{i}/3")
        return {"items": 3}

    info = tasks.start("scan", work, message="Scanning")
    assert info.state is TaskState.QUEUED
    assert info.created_at is not None
    assert info.id.startswith("t-")
    await asyncio.sleep(0.01)
    running = tasks.get(info.id)
    assert running is not None
    assert running.state is TaskState.RUNNING
    gate.set()
    final = await tasks.wait(info.id)
    assert final.state is TaskState.DONE
    assert final.result == {"items": 3}
    assert final.progress == 100.0
    assert final.finished_at is not None
    assert [(e.type, e.task.state, e.task.progress, e.task.message) for e in published] == [
        ("task.progress", TaskState.QUEUED, None, "Scanning"),
        ("task.progress", TaskState.RUNNING, None, "Scanning"),
        ("task.progress", TaskState.RUNNING, pytest.approx(100 / 3), "1/3"),
        ("task.progress", TaskState.RUNNING, pytest.approx(200 / 3), "2/3"),
        ("task.progress", TaskState.RUNNING, 100.0, "3/3"),
        ("task.done", TaskState.DONE, 100.0, "3/3"),
    ]
    # A subscriber that reads late gets the latest progress (the bus coalesces per task)
    # and always the terminal event.
    events = drain(sub)
    assert [(e.type, e.task.state, e.task.progress, e.task.message) for e in events] == [
        ("task.progress", TaskState.RUNNING, 100.0, "3/3"),
        ("task.done", TaskState.DONE, 100.0, "3/3"),
    ]
    assert {e.task.id for e in events} == {info.id}


async def test_progress_values_are_clamped_and_indeterminate_allowed() -> None:
    tasks = TaskManager()
    seen: list[float | None] = []

    async def work(ctx: TaskContext) -> None:
        for value in (-5.0, 50.0, 250.0, None):
            ctx.progress(value)
            info = tasks.get(ctx.id)
            assert info is not None
            seen.append(info.progress)
        ctx.progress(done=0, total=0)
        info = tasks.get(ctx.id)
        assert info is not None
        assert info.progress == 100.0

    await tasks.wait(tasks.start("x", work).id)
    assert seen == [0.0, 50.0, 100.0, None]


async def test_cancel_kills_the_subprocess_within_one_second(fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(tool="ffprobe", actions=[ft.hang()])]))
    tasks = TaskManager()

    async def work(ctx: TaskContext) -> Any:
        return await run([str(fake_tools.ffprobe), "-i", "x"], timeout=60, cancel=ctx.cancel)

    info = tasks.start("probe", work)
    await until(lambda: bool(fake_tools.pids()))
    [pid] = fake_tools.pids()
    started = time.monotonic()
    assert tasks.cancel(info.id)
    final = await tasks.wait(info.id)
    elapsed = time.monotonic() - started
    assert final.state is TaskState.CANCELLED
    assert elapsed < 1.0
    assert not _alive(pid)
    assert not tasks.cancel(info.id)  # already finished


async def test_cancel_without_token_use_still_kills(fake_tools: ft.FakeTools) -> None:
    """A task that does not pass ctx.cancel to run() is stopped by the asyncio cancel."""
    fake_tools.set_scenario(ft.Scenario([ft.Rule(tool="ffprobe", actions=[ft.hang()])]))
    tasks = TaskManager()

    async def work(ctx: TaskContext) -> Any:
        return await run([str(fake_tools.ffprobe)], timeout=60)

    info = tasks.start("probe", work)
    await until(lambda: bool(fake_tools.pids()))
    [pid] = fake_tools.pids()
    tasks.cancel(info.id)
    assert (await tasks.wait(info.id)).state is TaskState.CANCELLED
    assert not _alive(pid)


async def test_per_kind_limit_holds() -> None:
    tasks = TaskManager(limits={"scan": 2})
    running: dict[str, int] = {"scan": 0, "other": 0}
    peak: dict[str, int] = {"scan": 0, "other": 0}

    def work_for(kind: str) -> Any:
        async def work(ctx: TaskContext) -> None:
            running[kind] += 1
            peak[kind] = max(peak[kind], running[kind])
            await asyncio.sleep(0.02)
            running[kind] -= 1

        return work

    ids = [tasks.start("scan", work_for("scan")).id for _ in range(6)]
    ids += [tasks.start("other", work_for("other")).id for _ in range(5)]
    await asyncio.sleep(0)
    states = [info.state for info in tasks.list("scan")]
    assert states.count(TaskState.QUEUED) >= 4
    for task_id in ids:
        assert (await tasks.wait(task_id)).state is TaskState.DONE
    assert peak == {"scan": 2, "other": DEFAULT_LIMIT}
    assert tasks.limit("scan") == 2
    assert tasks.limit("probe_folder") == 2


async def test_queued_tasks_start_in_order() -> None:
    tasks = TaskManager(limits={"k": 1})
    order: list[int] = []

    def work_for(i: int) -> Any:
        async def work(ctx: TaskContext) -> None:
            order.append(i)
            await asyncio.sleep(0)

        return work

    ids = [tasks.start("k", work_for(i)).id for i in range(5)]
    for task_id in ids:
        await tasks.wait(task_id)
    assert order == [0, 1, 2, 3, 4]


async def test_cancel_a_queued_task() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    tasks = TaskManager(bus, limits={"k": 1})
    gate = asyncio.Event()
    ran: list[str] = []

    async def blocker(ctx: TaskContext) -> None:
        await gate.wait()

    async def never(ctx: TaskContext) -> None:
        ran.append("never")

    first = tasks.start("k", blocker)
    queued = tasks.start("k", never)
    await asyncio.sleep(0.01)
    assert tasks.cancel(queued.id)
    final = await tasks.wait(queued.id)
    assert final.state is TaskState.CANCELLED
    gate.set()
    assert (await tasks.wait(first.id)).state is TaskState.DONE
    assert ran == []
    done = [e for e in drain(sub) if e.type == "task.done"]
    assert [(e.task.id, e.task.state) for e in done] == [
        (queued.id, TaskState.CANCELLED),
        (first.id, TaskState.DONE),
    ]


async def test_cancel_before_the_coroutine_starts() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    tasks = TaskManager(bus)

    async def work(ctx: TaskContext) -> None:
        raise AssertionError("must not run")

    info = tasks.start("k", work)
    assert tasks.cancel(info.id)  # in the same loop iteration: the coroutine never ran
    final = await tasks.wait(info.id)
    assert final.state is TaskState.CANCELLED
    assert final.finished_at is not None
    assert [e.type for e in drain(sub)] == ["task.progress", "task.done"]


async def test_cancel_slot_handover_race() -> None:
    """A queued task cancelled right after it was given a slot gives the slot back."""
    tasks = TaskManager(limits={"k": 1})
    gate = asyncio.Event()

    async def blocker(ctx: TaskContext) -> None:
        await gate.wait()

    async def quick(ctx: TaskContext) -> str:
        return "ok"

    first = tasks.start("k", blocker)
    second = tasks.start("k", blocker)
    third = tasks.start("k", quick)
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.sleep(0)  # first finishes and hands the slot to second
    tasks.cancel(second.id)
    assert (await tasks.wait(second.id)).state is TaskState.CANCELLED
    assert (await tasks.wait(third.id)).result == "ok"
    assert (await tasks.wait(first.id)).state is TaskState.DONE


async def test_function_that_notices_the_token_is_cancelled() -> None:
    tasks = TaskManager()

    async def work(ctx: TaskContext) -> str:
        await ctx.cancel.wait()
        assert ctx.cancelled
        return "stopped early"

    info = tasks.start("k", work)
    await asyncio.sleep(0.02)
    task = tasks._tasks[info.id]
    task.cancel.cancel()  # the token only (as a run() with this token would see it)
    final = await tasks.wait(info.id)
    assert final.state is TaskState.CANCELLED
    assert final.result is None


async def test_failure_is_recorded_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    tasks = TaskManager()

    async def work(ctx: TaskContext) -> None:
        raise RuntimeError("disk on fire")

    final = await tasks.wait(tasks.start("k", work).id)
    assert final.state is TaskState.FAILED
    assert final.error == "RuntimeError: disk on fire"
    assert "failed" in caplog.text


class Result(BaseModel):
    count: int


async def test_result_conversion() -> None:
    tasks = TaskManager()

    async def returns(value: Any) -> Any:
        return value

    def start(value: Any, **kw: Any) -> str:
        async def work(ctx: TaskContext) -> Any:
            return await returns(value)

        return tasks.start("k", work, **kw).id

    cases = {
        start(Result(count=2)): {"count": 2},
        start([1, "a", None, {"b": 1.5}]): [1, "a", None, {"b": 1.5}],
        start(object()): None,
        start(float("nan")): None,
        start({1: 2}): None,
        start((1, 2)): None,
        start(object(), result_json=lambda v: "custom"): "custom",
    }
    for task_id, expected in cases.items():
        assert (await tasks.wait(task_id)).result == expected
    obj_id = next(iter(cases))
    assert isinstance(tasks.value(obj_id), Result)


async def test_get_list_unknown_and_pruning() -> None:
    tasks = TaskManager(keep_finished=2)

    async def work(ctx: TaskContext) -> None:
        return None

    ids: list[str] = []
    for _ in range(4):
        task_id = tasks.start("a" if len(ids) % 2 else "b", work).id
        await tasks.wait(task_id)
        ids.append(task_id)
    tasks.start("c", work)  # pruning happens on start
    known = [t.id for t in tasks.list()]
    assert ids[0] not in known
    assert ids[-1] in known
    assert tasks.get("nope") is None
    assert tasks.value("nope") is None
    assert not tasks.cancel("nope")
    assert all(t.kind == "a" for t in tasks.list("a"))
    with pytest.raises(KeyError):
        await tasks.wait("nope")


async def test_set_limit_starts_waiting_tasks() -> None:
    tasks = TaskManager(limits={"k": 1})
    gate = asyncio.Event()

    async def blocker(ctx: TaskContext) -> None:
        await gate.wait()

    a, b = tasks.start("k", blocker), tasks.start("k", blocker)
    await asyncio.sleep(0.01)
    assert [t.state for t in tasks.list()] == [TaskState.RUNNING, TaskState.QUEUED]
    tasks.set_limit("k", 2)
    await asyncio.sleep(0.01)
    assert [t.state for t in tasks.list()] == [TaskState.RUNNING, TaskState.RUNNING]
    tasks.set_limit("new-kind", 3)
    assert tasks.limit("new-kind") == 3
    gate.set()
    await tasks.wait(a.id)
    await tasks.wait(b.id)


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        TaskManager(limits={"k": 0})
    with pytest.raises(ValueError, match="at least 1"):
        TaskManager(default_limit=0)
    with pytest.raises(ValueError, match="at least 1"):
        TaskManager().set_limit("k", 0)


async def test_close_cancels_everything() -> None:
    tasks = TaskManager(limits={"k": 1})

    async def forever(ctx: TaskContext) -> None:
        await asyncio.Event().wait()

    infos = [tasks.start("k", forever) for _ in range(3)]
    await asyncio.sleep(0.01)
    await tasks.close()
    assert [t.state for t in tasks.list()] == [TaskState.CANCELLED] * 3
    assert all(tasks.get(i.id) is not None for i in infos)
    await TaskManager().close()  # nothing to do


async def test_progress_after_the_end_is_ignored() -> None:
    tasks = TaskManager()
    saved: list[TaskContext] = []

    async def work(ctx: TaskContext) -> None:
        saved.append(ctx)

    info = tasks.start("k", work)
    await tasks.wait(info.id)
    saved[0].progress(10.0, "late")
    final = tasks.get(info.id)
    assert final is not None
    assert final.message is None
    assert final.progress is None
