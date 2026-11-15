"""The writer's own thread: a stop before it starts prevents the call; once started, it ends."""

from __future__ import annotations

import asyncio
import threading

import pytest

from reframe.metadata import own_thread
from reframe.metadata.own_thread import OwnThread

pytestmark = pytest.mark.anyio


class Held(threading.Thread):
    hold = threading.Event()
    waiting = threading.Event()

    def run(self) -> None:
        Held.waiting.set()
        Held.hold.wait(30)
        super().run()


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> type[Held]:
    Held.hold, Held.waiting = threading.Event(), threading.Event()
    monkeypatch.setattr(own_thread, "Thread", Held)
    return Held


async def test_a_stop_before_the_call_starts_prevents_it(held: type[Held]) -> None:
    calls: list[int] = []
    work = OwnThread(lambda: calls.append(1))
    work.start()
    assert await asyncio.to_thread(held.waiting.wait, 10)
    assert work.prevent()
    assert work.future.done()
    assert work.future.result() is None
    held.hold.set()
    await asyncio.sleep(0.1)
    assert calls == []
    assert work.prevent()  # still true: it never starts


async def test_a_started_call_cannot_be_prevented_and_ends() -> None:
    started, release = threading.Event(), threading.Event()

    def call() -> str:
        started.set()
        release.wait(10)
        return "done"

    work = OwnThread(call)
    work.start()
    assert await asyncio.to_thread(started.wait, 10)
    assert not work.prevent()
    release.set()
    assert await work.future == "done"


async def test_an_exception_reaches_the_waiting_task() -> None:
    def call() -> None:
        raise ValueError("boom")

    work = OwnThread(call)
    work.start()
    with pytest.raises(ValueError, match="boom"):
        await work.future


async def test_start_and_prevent_never_both_win() -> None:
    """Defect: a stop that comes as the thread starts both reports "prevented" and lets the
    call run."""
    for _ in range(300):
        calls: list[int] = []

        def call(calls: list[int] = calls) -> None:
            calls.append(1)

        work = OwnThread(call)
        work.start()
        prevented = work.prevent()
        if prevented:
            await asyncio.sleep(0.005)
            assert calls == []
        else:
            await work.future
            assert calls == [1]
