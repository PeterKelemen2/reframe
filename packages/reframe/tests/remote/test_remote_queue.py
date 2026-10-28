"""What ``RemoteQueue`` adds to the queue contract: attached jobs, the events it forwards, the
end of its connection, its refusals, and the owner's countdown, validation and settings."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from reframe.models import JobState, JobStateEvent
from reframe.queue import JobStateError, UnknownJobError
from reframe.remote import OwnerStopping, RemoteError
from reframe_testing.server import ApiFactory

from .conftest import HANG, Server, poll

pytestmark = pytest.mark.anyio


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.mark.parametrize(("detach", "state"), [(False, "cancelled"), (True, "waiting")])
async def test_its_jobs_end_with_its_connection_unless_it_detaches(
    server: Server, detach: bool, state: str
) -> None:
    remote = await server.connect()
    job = await remote.add(await server.job())
    await remote.close(detach=detach)
    await poll(lambda: server.api.reframe.queue.get(job.id).state == state)  # type: ignore[union-attr]


async def test_a_start_is_sent_before_it_detaches(server: Server) -> None:
    """``--detach`` ends the command right after ``start``: the job must still run."""
    remote = await server.connect()
    job = await remote.add(await server.job())
    remote.start(job_ids=[job.id])
    await remote.close(detach=True)
    [done] = await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)
    assert done.state is JobState.DONE


async def test_an_end_reaches_its_subscribers_with_the_jobs_output(server: Server) -> None:
    remote = await server.connect()
    try:
        seen: list[tuple[JobState, object]] = []
        events = remote.events.subscribe(types={"job.state"})
        job = await remote.add(await server.job())
        remote.start(job_ids=[job.id])
        async for event in events:
            assert isinstance(event, JobStateEvent)
            current = remote.get(event.job_id)
            assert current is not None
            seen.append((event.state, current.output_path))
            if event.state is JobState.DONE:
                break
        assert seen[-1] == (JobState.DONE, server.api.output / "Show S01E01.mkv")
    finally:
        await remote.close()


async def test_a_job_another_client_adds_shows_in_the_list(server: Server) -> None:
    remote = await server.connect()
    try:
        other = await server.api.reframe.queue.add(await server.job("Other.mkv"))
        await poll(lambda: remote.get(other.id) is not None)
        listed = remote.get(other.id)
        assert listed is not None
        assert listed.settings.output.path == server.api.output / "Other.mkv"
    finally:
        await remote.close()


async def test_a_server_that_stops_interrupts_its_running_jobs(make_api: ApiFactory) -> None:
    async with make_api(mode="desktop") as api:
        api.fake.set_scenario(HANG)
        async with api.live() as live:
            remote = await Server(api, live).connect()
            events = remote.events.subscribe(types={"job.state"})
            job = await remote.add(await Server(api, live).job())
            remote.start(job_ids=[job.id])
            await poll(lambda: remote.get(job.id).state is JobState.RUNNING)  # type: ignore[union-attr]
        # uvicorn's shutdown closed the connection (1012); the job runs on in the facade.
        assert await asyncio.wait_for(remote.wait([job.id]), 10) != []
        assert remote.lost == "the Reframe server stopped"
        ended = remote.get(job.id)
        assert ended is not None
        assert ended.state is JobState.INTERRUPTED
        states = [event.state async for event in events]  # type: ignore[union-attr]
        assert states[-1] is JobState.INTERRUPTED  # and the stream ended
        with pytest.raises(RemoteError) as refused:
            await remote.cancel(job.id)
        assert refused.value.code == "connection.lost"
        await remote.close()
        await api.reframe.queue.cancel(job.id)


async def test_a_server_that_is_stopping_is_reported_as_stopping(server: Server) -> None:
    await server.api.app.state.hub.close()
    with pytest.raises(OwnerStopping):
        await server.connect()


async def test_a_token_the_server_refuses(server: Server) -> None:
    with pytest.raises(RemoteError) as refused:
        await server.connect(token="not-the-token")
    assert refused.value.code == "auth"


async def test_a_port_nothing_listens_on(server: Server) -> None:
    with pytest.raises(RemoteError) as refused:
        await server.connect(port=free_port())
    assert refused.value.code == "connection.failed"


def problem(status: int, code: str, title: str) -> httpx.Response:
    return httpx.Response(
        status, json={"type": "about:blank", "title": title, "status": status, "code": code}
    )


@pytest.mark.parametrize(
    ("answer", "raised", "code"),
    [
        (problem(404, "queue.unknown_job", "No job"), UnknownJobError, None),
        (problem(409, "queue.job_state", "job x is running"), JobStateError, None),
        (
            problem(503, "server.closing", "The server is shutting down"),
            RemoteError,
            "server.closing",
        ),
        (httpx.ConnectError("refused"), RemoteError, "connection.lost"),
    ],
)
async def test_a_refusal_is_the_queues_error(
    server: Server, answer: httpx.Response | Exception, raised: type[Exception], code: str | None
) -> None:
    remote = await server.connect()
    try:
        job = await remote.add(await server.job())

        def handler(_request: httpx.Request) -> httpx.Response:
            if isinstance(answer, Exception):
                raise answer
            return answer

        await remote._http.aclose()
        remote._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=remote.owner.url
        )
        with pytest.raises(raised) as refused:
            await remote.remove(job.id)
        if code is not None:
            assert refused.value.code == code  # type: ignore[attr-defined]
    finally:
        await remote.close()


async def test_the_owners_countdown_is_followed_and_cancelled(server: Server) -> None:
    remote = await server.connect()
    try:
        countdown = server.api.reframe.power.schedule("shutdown")
        await poll(lambda: remote.power.pending is not None)
        assert remote.power.pending is not None
        assert remote.power.pending.countdown_id == countdown
        assert not await remote.power.cancel("another-countdown")
        assert await remote.power.cancel(countdown)
        assert server.api.reframe.power.pending is None
    finally:
        await remote.close()


async def test_a_countdown_that_runs_when_it_connects(server: Server) -> None:
    countdown = server.api.reframe.power.schedule("sleep")
    remote = await server.connect()
    try:
        assert remote.power.pending is not None
        assert remote.power.pending.countdown_id == countdown
    finally:
        server.api.reframe.power.cancel()
        await remote.close()


async def test_validation_and_the_when_done_setting_are_the_owners(server: Server) -> None:
    await server.api.reframe.settings.update(
        [{"op": "replace", "path": "/queue/when_done", "value": "notify"}]
    )
    remote = await server.connect()
    try:
        job = await server.job()
        job.video.encoder = "no_such_encoder"
        issues = await remote.validate(job)
        assert issues == await server.api.reframe.jobs.validate(job)
        assert any(issue.severity == "error" for issue in issues)
        assert await remote.when_done() == "notify"
    finally:
        await remote.close()


async def test_an_older_event_never_moves_a_job_out_of_its_end(server: Server) -> None:
    """An event that arrives after a whole-queue read that already holds the job's end."""
    remote = await server.connect()
    try:
        job = await remote.add(await server.job())
        await remote.cancel(job.id)
        async with remote._mirror:
            await remote._apply(
                JobStateEvent(job_id=job.id, state=JobState.RUNNING, previous=JobState.WAITING)
            )
        assert remote.get(job.id).state is JobState.CANCELLED  # type: ignore[union-attr]
        async with remote._mirror:  # a retry is the one way out of an end
            await remote._apply(
                JobStateEvent(job_id=job.id, state=JobState.WAITING, previous=JobState.CANCELLED)
            )
        assert remote.get(job.id).state is JobState.WAITING  # type: ignore[union-attr]
    finally:
        await remote.close()
