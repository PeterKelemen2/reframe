"""Jobs attached to an event connection (``attach`` in ``POST /api/queue``): they are cancelled
when their client goes away without a ``detach``, also while they are being added, and left to
the queue when the server stops. Over real uvicorn, a ``websockets`` client and the fake
FFmpeg."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from reframe.models import JobDraft, JobState
from reframe_server.app import create_app
from reframe_server.config import ServerConfig
from reframe_server.events import EventHub
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api, LiveServer, receive_json

pytestmark = pytest.mark.anyio

WRITE_AND_HANG = ft.Scenario(
    [
        PROBE_RULE,
        ft.Rule(
            tool="ffmpeg",
            argv_has=["matroska"],
            actions=[ft.write_output(), ft.progress(blocks=1, end=False), ft.hang()],
        ),
    ]
)
"""Each encode writes its ``.part`` file, prints one progress block, then runs until it is
stopped."""


class _Errors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@asynccontextmanager
async def live(api: Api) -> AsyncIterator[LiveServer]:
    """``api`` over TCP. Fails if an exception escaped the hub (uvicorn logs it)."""
    errors = _Errors()
    logger = logging.getLogger("uvicorn.error")
    async with api.live() as server:
        logger.addHandler(errors)  # after uvicorn has configured its loggers
        try:
            yield server
        finally:
            logger.removeHandler(errors)
    assert errors.messages == []


async def sign_in(connection: ClientConnection, api: Api) -> str:
    """Authenticate; returns the ``client_id`` of the hello."""
    await connection.send(json.dumps({"type": "auth", "token": api.token}))
    hello = await receive_json(connection)
    assert hello["type"] == "hello"
    client_id: str = hello["client_id"]
    return client_id


@asynccontextmanager
async def connected(server: LiveServer, api: Api) -> AsyncIterator[tuple[ClientConnection, str]]:
    async with server.connect() as connection:
        yield connection, await sign_in(connection, api)


def hub(api: Api) -> EventHub:
    served: EventHub = api.app.state.hub
    return served


async def draft_job(api: Api, name: str = "Show S01E01.mkv") -> dict[str, Any]:
    source = api.media_file(name)
    draft = await api.reframe.jobs.draft(source, output=api.output / f"{source.stem}.mkv")
    assert isinstance(draft, JobDraft)
    data: dict[str, Any] = draft.job.model_dump(mode="json")
    return data


async def add_jobs(api: Api, attach: str | None, *names: str) -> list[str]:
    jobs = [await draft_job(api, name) for name in names]
    response = await api.client.post("/api/queue", json={"jobs": jobs, "attach": attach})
    assert response.status_code == 201, response.text
    return [job["id"] for job in response.json()]


async def states(api: Api) -> dict[str, str]:
    response = await api.client.get("/api/queue")
    assert response.status_code == 200
    return {job["id"]: job["state"] for job in response.json()["jobs"]}


async def wait_until(condition: Callable[[], bool], limit: float = 20.0) -> None:
    deadline = time.monotonic() + limit
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def ended(api: Api, *job_ids: str) -> None:
    await asyncio.wait_for(api.reframe.queue.wait(job_ids), 30)


async def encoding(api: Api, job_id: str) -> None:
    """Until the job's encode has printed its first progress block."""

    def started() -> bool:
        job = api.reframe.queue.get(job_id)
        assert job is not None
        return job.progress is not None and job.progress.output_size is not None

    await wait_until(started)


async def close_code(connection: ClientConnection) -> int | None:
    """Read until the server closes; its close code."""
    async with asyncio.timeout(10):
        try:
            while True:
                await connection.recv()
        except ConnectionClosed:
            pass
    return connection.close_code


async def test_a_client_that_goes_away_has_its_attached_jobs_cancelled(api: Api) -> None:
    """``kill -9`` of a CLI that started its own jobs: the running one is stopped and its
    ``.part`` file removed, the waiting one never starts in the freed slot, and the job of
    another front end, ahead of them in the queue, is neither started nor cancelled."""
    api.fake.set_scenario(WRITE_AND_HANG)
    [other] = await add_jobs(api, None, "Other.mkv")
    async with live(api) as server, connected(server, api) as (connection, client_id):
        running, waiting = await add_jobs(api, client_id, "Running.mkv", "Waiting.mkv")
        response = await api.client.post("/api/queue/start", json={"job_ids": [running, waiting]})
        assert response.status_code == 204
        await encoding(api, running)
        [part] = api.output.glob("Running.part.*")
        connection.transport.abort()
        await ended(api, running, waiting)
    assert await states(api) == {other: "waiting", running: "cancelled", waiting: "cancelled"}
    never_started = api.reframe.queue.get(waiting)
    assert never_started is not None
    assert never_started.started_at is None
    assert not part.exists()
    assert api.fake.kill_leftovers() == []


async def test_a_detach_keeps_the_jobs_of_its_own_connection(api: Api) -> None:
    """``--detach``: the CLI sends ``detach`` and exits, and its jobs stay. Another client,
    connected at the same time, still has its job cancelled when it closes without one."""
    async with live(api) as server:
        async with connected(server, api) as (_, dropped_id):
            [dropped] = await add_jobs(api, dropped_id, "Dropped.mkv")
            async with connected(server, api) as (connection, kept_id):
                [kept] = await add_jobs(api, kept_id, "Kept.mkv")
                await connection.send(json.dumps({"type": "detach"}))
            await wait_until(lambda: not hub(api).client_open(kept_id))
            assert hub(api).client_open(dropped_id)
        await ended(api, dropped)
    assert await states(api) == {kept: "waiting", dropped: "cancelled"}


async def test_a_message_that_is_not_a_detach_keeps_nothing(api: Api) -> None:
    """A stray message of another type, or text that is not JSON, before a CLI is killed: its
    job is cancelled all the same."""
    async with live(api) as server, connected(server, api) as (connection, client_id):
        [job] = await add_jobs(api, client_id, "Show.mkv")
        await connection.send(json.dumps({"type": "subscribe"}))
        await connection.send("detach")
        connection.transport.abort()
        await ended(api, job)
    assert await states(api) == {job: "cancelled"}


async def test_attach_with_the_id_of_a_closed_connection_is_refused(api: Api) -> None:
    """A job is never attached to a client that is already gone: nobody would be left to
    cancel it."""
    job = await draft_job(api)
    async with live(api) as server:
        async with connected(server, api) as (_, client_id):
            assert hub(api).client_open(client_id)
        await wait_until(lambda: not hub(api).client_open(client_id))
        response = await api.client.post("/api/queue", json={"jobs": [job], "attach": client_id})
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "queue.attach_unknown_client"
    assert await states(api) == {}


@pytest.mark.parametrize(
    ("detach", "state"),
    [(False, "cancelled"), (True, "waiting")],
    ids=["no detach: cancelled", "detached: kept"],
)
async def test_a_client_that_goes_away_while_its_job_is_added(
    api: Api, monkeypatch: pytest.MonkeyPatch, detach: bool, state: str
) -> None:
    """The connection ends after the attach check and before the job is in the queue."""
    queue = api.reframe.queue
    add, entered, release = queue.add, asyncio.Event(), asyncio.Event()

    async def held_add(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await add(*args, **kwargs)

    monkeypatch.setattr(queue, "add", held_add)
    job = await draft_job(api)
    async with live(api) as server:
        async with connected(server, api) as (connection, client_id):
            posting = asyncio.create_task(
                api.client.post("/api/queue", json={"jobs": [job], "attach": client_id})
            )
            await entered.wait()
            if detach:
                await connection.send(json.dumps({"type": "detach"}))
        await wait_until(lambda: not hub(api).client_open(client_id))
        release.set()
        response = await posting
    assert response.status_code == 201
    [added] = response.json()
    assert added["state"] == state
    assert await states(api) == {added["id"]: state}


@pytest.mark.parametrize(
    ("stop", "code"), [("uvicorn", 1012), ("hub", 1001)], ids=["uvicorn stops", "hub closes"]
)
async def test_a_server_stop_leaves_the_attached_jobs_to_the_queue(
    api: Api, stop: str, code: int
) -> None:
    """The client did not go away: the queue's close decides (a waiting job stays for the
    next owner, a running one ends ``interrupted``), not a cancel."""
    async with live(api) as server:
        connection = await server.connect()
        [job] = await add_jobs(api, await sign_in(connection, api), "Show.mkv")
        if stop == "hub":
            await hub(api).close()
    assert await close_code(connection) == code
    await hub(api).close()  # waits for the cancels that a connection's end started
    assert await states(api) == {job: "waiting"}


async def test_the_hub_closes_once_a_gone_clients_jobs_are_cancelled(api: Api) -> None:
    """A CLI dies just before the server stops: its running job is cancelled before the
    lifespan closes the queue, which would end it ``interrupted``."""
    api.fake.set_scenario(WRITE_AND_HANG)
    async with live(api) as server, connected(server, api) as (connection, client_id):
        [job] = await add_jobs(api, client_id, "Show.mkv")
        await api.client.post("/api/queue/start", json={"job_ids": [job]})
        await encoding(api, job)
        connection.transport.abort()
        async with asyncio.timeout(10):
            while hub(api).client_open(client_id):  # noqa: ASYNC110 - the hub has no event
                await asyncio.sleep(0)
        await hub(api).close()
        cancelled = api.reframe.queue.get(job)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED


async def test_a_job_removed_before_its_client_goes_away(api: Api) -> None:
    """The user removed one of a CLI's waiting jobs: when the CLI goes away, its other job is
    cancelled and nothing fails in the server."""
    loop = asyncio.get_running_loop()
    reported: list[dict[str, Any]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        async with live(api) as server, connected(server, api) as (connection, client_id):
            removed, other = await add_jobs(api, client_id, "Removed.mkv", "Other.mkv")
            assert (await api.client.delete(f"/api/queue/{removed}")).status_code == 204
            connection.transport.abort()
            await ended(api, other)
            await hub(api).close()
        gc.collect()  # an exception that no one read is reported when its task is freed
    finally:
        loop.set_exception_handler(previous)
    assert [context["message"] for context in reported] == []
    assert await states(api) == {other: "cancelled"}


async def test_the_client_messages_and_the_client_id_are_in_the_openapi_document() -> None:
    """The frontend's and a client's generated types know the ``detach`` message and the
    hello's ``client_id``."""
    document = create_app(ServerConfig(host="127.0.0.1", mode="web", auth="none")).openapi()
    schemas = document["components"]["schemas"]
    assert schemas["ClientMessage"]["discriminator"]["mapping"] == {
        "auth": "#/components/schemas/AuthMessage",
        "detach": "#/components/schemas/DetachMessage",
    }
    assert "client_id" in schemas["Hello"]["required"]
