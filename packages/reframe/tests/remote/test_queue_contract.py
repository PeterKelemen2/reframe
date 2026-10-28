"""The queue contract, against the in-process ``QueueService`` and a ``RemoteQueue`` of the same
server: what a front end sees through :class:`~reframe.queue.QueueLike` does not depend on
which one it has."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import pytest

from reframe.models import JobState, QueueJob
from reframe.queue import JobStateError, QueueLike, UnknownJobError
from reframe.queue.service import OUTPUT_CLAIMED

from .conftest import HANG, Server, poll

pytestmark = pytest.mark.anyio


@dataclass
class Contract:
    server: Server
    queue: QueueLike

    async def add(self, name: str, **options: object) -> QueueJob:
        return await self.queue.add(await self.server.job(name), **options)  # type: ignore[arg-type]

    def state(self, job_id: str) -> JobState | None:
        job = self.queue.get(job_id)
        return None if job is None else job.state

    async def ended(self, *job_ids: str) -> list[QueueJob]:
        return await asyncio.wait_for(self.queue.wait(job_ids), 30)

    async def running(self, *job_ids: str) -> None:
        await poll(lambda: all(self.state(j) is JobState.RUNNING for j in job_ids))


@pytest.fixture(params=["service", "remote"])
async def contract(request: pytest.FixtureRequest, server: Server) -> AsyncIterator[Contract]:
    if request.param == "service":
        yield Contract(server, server.api.reframe.queue)
        return
    remote = await server.connect()
    try:
        yield Contract(server, remote)
    finally:
        await remote.close()
    assert server.api.fake.kill_leftovers() == []


async def test_add_puts_a_job_at_the_end_or_at_a_position(contract: Contract) -> None:
    first = await contract.add("A.mkv")
    second = await contract.add("B.mkv")
    front = await contract.add("C.mkv", position=0)
    assert first.state is JobState.WAITING
    jobs = contract.queue.list()
    assert [job.id for job in jobs] == [front.id, first.id, second.id]
    assert [job.position for job in jobs] == [0, 1, 2]
    got = contract.queue.get(second.id)
    assert got is not None
    assert got.settings.output.path == contract.server.api.output / "B.mkv"


async def test_a_job_with_errors_is_added_failed(contract: Contract) -> None:
    job = await contract.server.job("Gone.mkv")
    (contract.server.api.media / "Gone.mkv").unlink()
    added = await contract.queue.add(job)
    assert added.state is JobState.FAILED
    assert any(issue.severity == "error" for issue in added.issues)
    assert contract.state(added.id) is JobState.FAILED


async def test_a_job_that_writes_another_jobs_output_is_added_failed(contract: Contract) -> None:
    first = await contract.queue.add(await contract.server.job("A.mkv", output="Same.mkv"))
    second = await contract.queue.add(await contract.server.job("B.mkv", output="Same.mkv"))
    assert first.state is JobState.WAITING
    assert second.state is JobState.FAILED
    assert [i.code for i in second.issues if i.severity == "error"] == [OUTPUT_CLAIMED]


async def test_start_with_job_ids_runs_only_those(contract: Contract) -> None:
    other = await contract.add("Other.mkv")
    ours = await contract.add("Ours.mkv")
    contract.queue.start(job_ids=[ours.id])
    [done] = await contract.ended(ours.id)
    output = contract.server.api.output / "Ours.mkv"
    assert (done.state, done.output_path) == (JobState.DONE, output)
    got = contract.queue.get(ours.id)
    assert got is not None
    assert (got.state, got.output_path) == (JobState.DONE, output)
    assert contract.state(other.id) is JobState.WAITING
    log = contract.queue.log_path(ours.id)
    assert log == contract.server.api.reframe.queue.log_path(ours.id)
    assert f"Reframe job {ours.id}" in log.read_text(encoding="utf-8")


async def test_cancel_a_waiting_job(contract: Contract) -> None:
    job = await contract.add("A.mkv")
    await contract.queue.cancel(job.id)
    assert contract.state(job.id) is JobState.CANCELLED
    assert [ended.state for ended in await contract.ended(job.id)] == [JobState.CANCELLED]


async def test_cancel_returns_once_the_running_job_stopped(contract: Contract) -> None:
    contract.server.api.fake.set_scenario(HANG)
    job = await contract.add("A.mkv")
    contract.queue.start(job_ids=[job.id])
    await contract.running(job.id)
    await poll(lambda: bool(list(contract.server.api.output.glob("A.part.*"))))
    await contract.queue.cancel(job.id)
    assert contract.state(job.id) is JobState.CANCELLED
    assert not list(contract.server.api.output.glob("A.part.*"))


async def test_pause_resume_and_cancel_one_job_or_all(contract: Contract) -> None:
    contract.server.api.fake.set_scenario(HANG)
    job = await contract.add("A.mkv")
    contract.queue.start(job_ids=[job.id])
    await contract.running(job.id)
    await contract.queue.pause(job.id)
    assert contract.state(job.id) is JobState.PAUSED
    await contract.queue.resume(job.id)
    assert contract.state(job.id) is JobState.RUNNING
    await contract.queue.pause()
    assert contract.state(job.id) is JobState.PAUSED
    await contract.queue.resume()
    assert contract.state(job.id) is JobState.RUNNING
    await contract.queue.cancel()
    assert contract.state(job.id) is JobState.CANCELLED


async def test_retry(contract: Contract) -> None:
    done = await contract.add("Done.mkv")
    contract.queue.start(job_ids=[done.id])
    await contract.ended(done.id)
    cancelled = await contract.add("Cancelled.mkv")
    await contract.queue.cancel(cancelled.id)
    retried = await contract.queue.retry(cancelled.id)
    assert retried.state is JobState.WAITING
    assert contract.state(cancelled.id) is JobState.WAITING
    assert (await contract.queue.retry(cancelled.id)).state is JobState.WAITING
    with pytest.raises(JobStateError):
        await contract.queue.retry(done.id)


async def test_remove(contract: Contract) -> None:
    contract.server.api.fake.set_scenario(HANG)
    running = await contract.add("Running.mkv")
    waiting = await contract.add("Waiting.mkv")
    contract.queue.start(job_ids=[running.id])
    await contract.running(running.id)
    await contract.queue.remove(waiting.id)
    assert contract.queue.get(waiting.id) is None
    assert [job.id for job in contract.queue.list()] == [running.id]
    with pytest.raises(JobStateError):
        await contract.queue.remove(running.id)
    await contract.queue.cancel(running.id)


async def test_wait_ends_for_a_job_that_was_removed(contract: Contract) -> None:
    job = await contract.add("A.mkv")
    waiting = asyncio.create_task(contract.queue.wait([job.id]))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await contract.queue.remove(job.id)
    assert await asyncio.wait_for(waiting, 10) == []


async def test_reorder(contract: Contract) -> None:
    a, b, c = [await contract.add(f"{name}.mkv") for name in "ABC"]
    await contract.queue.reorder([c.id, a.id])
    assert [job.id for job in contract.queue.list()] == [c.id, b.id, a.id]
    with pytest.raises(ValueError, match="twice"):
        await contract.queue.reorder([a.id, a.id])


Call = Callable[[QueueLike, str], Awaitable[object] | object]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda q, i: q.cancel(i), id="cancel"),
        pytest.param(lambda q, i: q.pause(i), id="pause"),
        pytest.param(lambda q, i: q.resume(i), id="resume"),
        pytest.param(lambda q, i: q.retry(i), id="retry"),
        pytest.param(lambda q, i: q.remove(i), id="remove"),
        pytest.param(lambda q, i: q.reorder([i]), id="reorder"),
        pytest.param(lambda q, i: q.wait([i]), id="wait"),
        pytest.param(lambda q, i: q.start(job_ids=[i]), id="start"),
    ],
)
async def test_an_unknown_job_is_refused(contract: Contract, call: Call) -> None:
    async def unknown() -> None:
        result = call(contract.queue, "no-such-job")
        if isinstance(result, Awaitable):
            await result

    assert contract.queue.get("no-such-job") is None
    assert contract.queue.log_path("no-such-job") == (
        contract.server.data_dir / "logs" / "no-such-job.log"
    )
    with pytest.raises(UnknownJobError):
        await unknown()
