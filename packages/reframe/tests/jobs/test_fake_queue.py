"""The fake queue follows C-11's ``QueueService`` contract (so ``reframe encode``'s tests
mean something until the real queue is merged)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from reframe.events import EventBus
from reframe.models import (
    JobSettings,
    JobState,
    JobStateEvent,
    OutputSettings,
    QueueChangedEvent,
    Severity,
    SourceRef,
    ValidationIssue,
)

from .fake_queue import FakeQueue

pytestmark = pytest.mark.anyio


def job(tmp_path: Path, name: str) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=tmp_path / f"{name}.src.mkv"),
        output=OutputSettings(path=tmp_path / f"{name}.mkv"),
    )


async def test_order_states_and_files(tmp_path: Path) -> None:
    bus = EventBus()
    events = bus.subscribe()
    queue = FakeQueue(
        bus, log_dir=tmp_path, behaviour=lambda j: "hang" if "b" in str(j.source.path) else "done"
    )
    a = await queue.add(job(tmp_path, "a"))
    b = await queue.add(job(tmp_path, "b"), position=0)
    assert [j.id for j in queue.list()] == [b.id, a.id]
    assert queue.get("nope") is None
    await queue.reorder([a.id])
    assert [j.position for j in queue.list()] == [0, 1]
    queue.start()
    await queue.wait([a.id])
    assert (tmp_path / "a.mkv").exists()
    assert queue.get(a.id).state is JobState.DONE  # type: ignore[union-attr]
    await asyncio.sleep(0.05)
    assert queue.get(b.id).state is JobState.RUNNING  # type: ignore[union-attr]
    assert (tmp_path / "b.part.mkv").exists()
    await queue.pause()
    assert queue.get(b.id).state is JobState.PAUSED  # type: ignore[union-attr]
    await queue.resume(b.id)
    await queue.cancel()
    assert queue.get(b.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    assert not (tmp_path / "b.part.mkv").exists()
    await queue.stop()  # no new jobs: the retried one stays waiting
    retried = await queue.retry(b.id)
    assert retried.state is JobState.WAITING
    await queue.cancel(b.id)
    await queue.remove(b.id)
    assert [j.id for j in queue.list()] == [a.id]
    assert queue.log_path(a.id) == tmp_path / f"{a.id}.log"
    await queue.close()
    bus.close()
    seen = [e async for e in events]
    assert any(isinstance(e, QueueChangedEvent) for e in seen)
    states = [e.state for e in seen if isinstance(e, JobStateEvent) and e.job_id == b.id]
    assert states == [
        JobState.RUNNING,
        JobState.PAUSED,
        JobState.RUNNING,
        JobState.CANCELLED,
        JobState.WAITING,
        JobState.CANCELLED,
    ]


async def test_errors_add_a_failed_job_and_a_running_one_cannot_be_removed(
    tmp_path: Path,
) -> None:
    async def validate(_job: JobSettings) -> list[ValidationIssue]:
        return [ValidationIssue(severity=Severity.ERROR, code="x", message="x")]

    queue = FakeQueue(EventBus(), log_dir=tmp_path, validate=validate)
    failed = await queue.add(job(tmp_path, "a"))
    assert failed.state is JobState.FAILED
    hanging = FakeQueue(EventBus(), log_dir=tmp_path, behaviour=lambda _j: "hang")
    running = await hanging.add(job(tmp_path, "b"))
    hanging.start()
    await asyncio.sleep(0.05)
    with pytest.raises(ValueError, match="running"):
        await hanging.remove(running.id)
    await hanging.close()
    assert not (tmp_path / "b.part.mkv").exists()
