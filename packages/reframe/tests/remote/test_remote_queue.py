"""What ``RemoteQueue`` adds to the queue contract: attached jobs, the events it forwards, the
end of its connection, its refusals, and the owner's countdown, validation and settings."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from reframe.events import Subscription
from reframe.models import (
    Event,
    JobDraft,
    JobState,
    JobStateEvent,
    QueueChangedEvent,
    ResyncEvent,
)
from reframe.queue import JobStateError, UnknownJobError
from reframe.remote import OwnerStopping, RemoteError
from reframe.remote import queue as queue_module
from reframe_testing.server import ApiFactory

from .conftest import HANG, Server, Wire, event_message, poll, watch_requests

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


class SlowStart(httpx.AsyncBaseTransport):
    """Holds each ``POST /api/queue/start`` back for a moment, as a busy server would."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/queue/start":
            await asyncio.sleep(0.5)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def test_a_start_is_sent_before_it_detaches(server: Server) -> None:
    """``--detach`` ends the command right after ``start``: the job must still run."""
    remote = await server.connect()
    plain = remote._http
    remote._http = httpx.AsyncClient(
        base_url=plain.base_url, headers=plain.headers, transport=SlowStart()
    )
    await plain.aclose()
    job = await remote.add(await server.job())
    remote.start(job_ids=[job.id])
    await remote.close(detach=True)
    for task in list(remote._pending_starts):  # the command's process ends here
        task.cancel()
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


async def test_a_server_that_stops_interrupts_its_running_and_paused_jobs(
    make_api: ApiFactory,
) -> None:
    async with make_api(mode="desktop") as api:
        api.fake.set_scenario(HANG)
        await api.reframe.settings.update(
            [{"op": "replace", "path": "/queue/parallel_jobs", "value": 2}]
        )
        async with api.live() as live:
            remote = await Server(api, live).connect()
            events = remote.events.subscribe(types={"job.state"})
            job = await remote.add(await Server(api, live).job())
            paused = await remote.add(await Server(api, live).job("Paused.mkv"))
            waiting = await remote.add(await Server(api, live).job("Waiting.mkv"))
            remote.start(job_ids=[job.id, paused.id, waiting.id])
            await poll(lambda: remote.get(paused.id).state is JobState.RUNNING)  # type: ignore[union-attr]
            await remote.pause(paused.id)
            await poll(lambda: remote.get(job.id).state is JobState.RUNNING)  # type: ignore[union-attr]
        # uvicorn's shutdown closed the connection (1012); the jobs run on in the facade.
        ids = [job.id, paused.id, waiting.id]
        assert len(await asyncio.wait_for(remote.wait(ids), 10)) == 3
        assert remote.lost == "the Reframe server stopped"
        assert [remote.get(j).state for j in ids] == [  # type: ignore[union-attr]
            JobState.INTERRUPTED,
            JobState.INTERRUPTED,
            JobState.WAITING,
        ]
        states = [event.state async for event in events]  # type: ignore[union-attr]
        assert states[-1] is JobState.INTERRUPTED  # and the stream ended
        with pytest.raises(RemoteError) as refused:
            await remote.cancel(job.id)
        assert refused.value.code == "connection.lost"
        await remote.close()
        await api.reframe.queue.cancel()


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
        (httpx.Response(502, text="<html>Bad Gateway</html>"), RemoteError, ""),
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
        if code == "":
            assert str(refused.value) == "502 Bad Gateway"
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
        await poll(lambda: remote.power.pending is None)  # the client stops showing it
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


async def test_a_start_refused_for_another_reason_is_raised_by_the_next_call(
    server: Server,
) -> None:
    """A server that is closing refuses the start: a ``wait`` for the jobs would never
    return."""
    remote = await server.connect()
    try:
        job = await remote.add(await server.job())
        requests = await watch_requests(remote)
        closing = {"title": "The server is shutting down", "status": 503, "code": "server.closing"}
        requests.answer = lambda request: (
            httpx.Response(503, json=closing) if request.url.path == "/api/queue/start" else None
        )
        remote.start(job_ids=[job.id])
        with pytest.raises(RemoteError) as refused:
            await asyncio.wait_for(remote.wait([job.id]), 10)
        assert refused.value.code == "server.closing"
    finally:
        await remote.close()


async def until(events: Subscription, found: Callable[[Event], bool]) -> Event:
    async with asyncio.timeout(10):
        async for event in events:
            if found(event):
                return event
    raise AssertionError("the subscription ended")


@pytest.mark.parametrize(
    "meanwhile",
    ["nothing", "another add", "another add, reads refused", "a cancel", "a remove", "a read"],
)
async def test_an_add_whose_answer_comes_after_its_events(server: Server, meanwhile: str) -> None:
    """The events of an add can reach the copy before its answer, and another front end can
    act in between. The copy must not read the whole queue for this client's own adds, and it
    must show another front end's job, and a cancel, removal or start of the new job that came
    before the answer: else a ``wait`` for the job never returns."""
    server.api.fake.set_scenario(HANG)
    queue = server.api.reframe.queue
    remote = await server.connect()
    try:
        requests = await watch_requests(remote)
        requests.answers.clear()
        events = remote.events.subscribe(types={"job.state", "queue.changed", "resync"})
        names = ["A.mkv", "B.mkv"] if meanwhile == "nothing" else ["A.mkv"]
        jobs = [await server.job(name) for name in names]
        adding = asyncio.gather(*(remote.add(job) for job in jobs))
        shown = await until(
            events, lambda e: isinstance(e, QueueChangedEvent) and len(e.job_ids) == len(names)
        )
        assert isinstance(shown, QueueChangedEvent)
        ids, mine = shown.job_ids, shown.job_ids[0]
        other = None
        if meanwhile.startswith("another add"):
            if meanwhile.endswith("refused"):
                broken = {"title": "Broken", "status": 500, "code": "server.broken"}
                requests.answer = lambda request: (
                    httpx.Response(500, json=broken) if request.url.path == "/api/queue" else None
                )
            other = await queue.add(await server.job("Other.mkv"))
            await until(events, lambda e: isinstance(e, QueueChangedEvent) and len(e.job_ids) == 2)
        elif meanwhile == "a cancel":
            await queue.cancel(mine)
            await until(events, lambda e: isinstance(e, JobStateEvent) and e.job_id == mine)
        elif meanwhile == "a remove":
            await queue.remove(mine)
            await until(events, lambda e: isinstance(e, QueueChangedEvent) and not e.job_ids)
        elif meanwhile == "a read":
            queue.start(job_ids=[mine])
            await until(
                events, lambda e: isinstance(e, JobStateEvent) and e.state.value == "running"
            )
            server.api.reframe.events.publish(ResyncEvent())
            await until(events, lambda e: isinstance(e, ResyncEvent))
        requests.answers.set()
        added = await adding
        assert sorted(job.id for job in added) == sorted(ids)
        if meanwhile == "nothing":
            assert [(job.id, job.position) for job in remote.list()] == [(ids[0], 0), (ids[1], 1)]
            assert requests.reads() == 0
        elif other is not None:
            requests.answer = lambda _request: None
            if meanwhile.endswith("refused"):  # the add's read failed: the next event reads
                await remote.cancel(mine)
            assert [job.id for job in remote.list()] == [mine, other.id]
        elif meanwhile == "a cancel":
            assert remote.get(mine).state is JobState.CANCELLED  # type: ignore[union-attr]
        elif meanwhile == "a remove":
            assert remote.list() == []
        else:
            assert remote.get(mine).state is JobState.RUNNING  # type: ignore[union-attr]
    finally:
        await remote.close()
        await queue.cancel()


async def test_a_job_that_only_a_queue_change_names_is_read(server: Server, wire: Wire) -> None:
    """Without its add event, the copy would never get a job that another front end added."""
    remote = await server.connect()
    try:
        wire.drop = lambda message: event_type(message) == "job.state"
        other = await server.api.reframe.queue.add(await server.job("Other.mkv"))
        await poll(lambda: remote.get(other.id) is not None, 5)
    finally:
        await remote.close()


async def test_close_logs_a_start_the_server_refused(
    server: Server, caplog: pytest.LogCaptureFixture
) -> None:
    """``--detach`` closes right after ``start``: a refusal must not end it with a traceback."""
    remote = await server.connect()
    requests = await watch_requests(remote)
    job = await remote.add(await server.job())
    requests.released.clear()
    remote.start(job_ids=[job.id])
    await server.api.reframe.queue.remove(job.id)  # another front end, before the start arrives
    requests.released.set()
    with caplog.at_level(logging.WARNING, logger=queue_module.__name__):
        await remote.close(detach=True)
    assert f"the queue was not started: no job '{job.id}'" in caplog.text


async def test_a_job_it_just_added_stays_while_older_events_come(
    server: Server, wire: Wire
) -> None:
    """The event stream lags behind the answers: a ``queue.changed`` sent before an add reaches
    the copy after it. It must not remove the new job: ``start(job_ids)`` would refuse it,
    and the command would cancel all of its jobs."""
    wire.lag = 0.03
    jobs = [await server.job(f"Show S01E{n:02}.mkv") for n in range(1, 7)]
    remote = await server.connect()
    added: list[str] = []
    absent: list[str] = []
    changes = remote.events.subscribe(types={"queue.changed"})

    async def check() -> None:
        async for _ in changes:
            absent.extend(j for j in added if remote.get(j) is None)

    checker = asyncio.create_task(check())
    try:
        for job in jobs:
            added.append((await remote.add(job)).id)
        remote.start(job_ids=added)
        ended = await asyncio.wait_for(remote.wait(added), 30)
        assert [job.state for job in ended] == [JobState.DONE] * len(jobs)
        assert [job.id for job in remote.list()] == added
    finally:
        await remote.close()
        await asyncio.wait_for(checker, 10)
    assert absent == []


async def test_a_job_of_a_whole_queue_read_stays_while_older_events_come(
    server: Server, wire: Wire
) -> None:
    """The first add event of another front end's job makes the copy read the whole queue,
    which also holds the second job; the first job's ``queue.changed`` then comes without the
    second one, and must not remove it from the copy."""
    wire.lag = 0.1
    first, second = await server.job("A.mkv"), await server.job("B.mkv")
    remote = await server.connect()
    try:
        changes = remote.events.subscribe(types={"queue.changed"})
        await server.api.reframe.queue.add(first)
        later = await server.api.reframe.queue.add(second)
        shown: list[bool] = []
        async for _ in changes:
            shown.append(remote.get(later.id) is not None)
            if len(shown) == 2:
                break
        assert shown == [True, True]
    finally:
        await remote.close()


async def test_an_add_and_the_cancel_of_a_waiting_job_read_no_whole_queue(server: Server) -> None:
    """A whole-queue read is slow on a long queue, and neither call needs one."""
    remote = await server.connect()
    try:
        requests = await watch_requests(remote)
        job = await remote.add(await server.job())
        await remote.cancel(job.id)
        assert remote.get(job.id).state is JobState.CANCELLED  # type: ignore[union-attr]
        assert requests.reads() == 0
    finally:
        await remote.close()


async def test_the_token_is_not_logged(server: Server, caplog: pytest.LogCaptureFixture) -> None:
    """An application that logs at DEBUG must not get the token in websockets' frame lines."""
    with caplog.at_level(logging.DEBUG):
        remote = await server.connect()
        await remote.add(await server.job())
        await remote.close()
    assert caplog.records
    assert server.api.token not in caplog.text


async def test_a_token_that_cannot_be_a_header_value_is_refused_unseen(
    make_api: ApiFactory,
) -> None:
    """``REFRAME_TOKEN`` with a space at its end: the event connection takes it, and then every
    request fails in h11 with a message that shows the token."""
    token = "SECRET-TOKEN-xyz "
    async with make_api(mode="desktop", token=token) as api, api.live() as live:
        with pytest.raises(RemoteError) as refused:
            await Server(api, live).connect()
    assert refused.value.code == "auth"
    assert "SECRET" not in str(refused.value)


async def test_a_token_that_is_not_ascii_is_refused(server: Server) -> None:
    """httpx raises ``UnicodeEncodeError`` when it builds the client, which no caller expects."""
    with pytest.raises(RemoteError) as refused:
        await server.connect(token="sécret-token")
    assert refused.value.code == "auth"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("", "LocalProtocolError"),
        ("Illegal header value b'Bearer {token}'", "Illegal header value b'Bearer <token>'"),
    ],
    ids=["no text", "the token"],
)
async def test_a_request_that_fails_is_named_without_the_token(
    server: Server, text: str, shown: str
) -> None:
    remote = await server.connect()
    try:
        requests = await watch_requests(remote)

        def fails(_request: httpx.Request) -> httpx.Response:
            raise httpx.LocalProtocolError(text.format(token=server.api.token))

        requests.answer = fails
        with pytest.raises(RemoteError) as refused:
            await remote.cancel()
    finally:
        await remote.close()
    assert str(refused.value) == f"the Reframe server cannot be reached: {shown}"


async def test_a_server_that_does_not_greet_is_named(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``TimeoutError`` has no text: the message must not end in "cannot be reached: "."""
    monkeypatch.setattr(queue_module, "OPEN_TIMEOUT", 0.2)

    async def silent(connection: ServerConnection) -> None:
        await connection.wait_closed()

    async with serve(silent, "127.0.0.1", 0) as quiet:
        with pytest.raises(RemoteError) as refused:
            await server.connect(port=quiet.sockets[0].getsockname()[1])
    assert str(refused.value).endswith("cannot be reached: TimeoutError")


async def test_events_it_cannot_read_end_nothing(server: Server, wire: Wire) -> None:
    """A newer server with the same API version may send a new event type or field. If the
    reader ended, the running jobs would be reported interrupted, and the close without a
    detach would cancel them."""
    job = await server.api.reframe.queue.add(await server.job())
    wire.first = [
        "not JSON",
        {"type": "heartbeat"},
        event_message({"type": "job.renamed", "job_id": job.id}),
        event_message({"type": "job.state", "job_id": job.id, "state": "resting"}),
        event_message(
            {"type": "job.progress", "job_id": job.id, "progress": {"percent": 42.0}, "new": 1}
        ),
    ]
    remote = await server.connect()
    try:
        await poll(lambda: remote.get(job.id).progress is not None, 5)  # type: ignore[union-attr]
        assert remote.get(job.id).progress.percent == 42.0  # type: ignore[union-attr]
        assert remote.lost is None
        await remote.cancel(job.id)
        assert remote.get(job.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    finally:
        await remote.close()


async def test_progress_does_not_change_a_job_that_ended(server: Server, wire: Wire) -> None:
    """A whole-queue read can hold a job's end while its last progress is still on its way:
    the ended job must not show an older percentage."""
    queue = server.api.reframe.queue
    ended = await queue.add(await server.job("Ended.mkv"))
    await queue.cancel(ended.id)
    waiting = await queue.add(await server.job("Waiting.mkv"))
    wire.first = [
        event_message({"type": "job.progress", "job_id": j, "progress": {"percent": 50.0}})
        for j in (ended.id, waiting.id)
    ]
    remote = await server.connect()
    try:
        await poll(lambda: remote.get(waiting.id).progress is not None, 5)  # type: ignore[union-attr]
        assert remote.get(ended.id).progress is None  # type: ignore[union-attr]
    finally:
        await remote.close()


def event_type(message: dict[str, object]) -> object:
    event = message.get("event")
    return event.get("type") if isinstance(event, dict) else None


async def test_a_change_whose_event_does_not_come_is_read(
    server: Server, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the read, ``cancel`` returns with the copy still showing the job waiting."""
    monkeypatch.setattr(queue_module, "CHANGE_WAIT", 0.3)
    remote = await server.connect()
    try:
        job = await remote.add(await server.job())
        wire.drop = lambda message: event_type(message) == "job.state"
        await remote.cancel(job.id)
        assert remote.get(job.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    finally:
        await remote.close()


async def test_a_resync_reads_the_whole_queue(server: Server, wire: Wire) -> None:
    """The server sends ``resync`` where this connection lost events: without a read, a job
    added meanwhile stays missing from the copy."""
    remote = await server.connect()
    try:
        wire.drop = lambda message: event_type(message) in ("job.state", "queue.changed")
        other = await server.api.reframe.queue.add(await server.job("Other.mkv"))
        server.api.reframe.events.publish(ResyncEvent())
        await poll(lambda: remote.get(other.id) is not None, 5)
    finally:
        await remote.close()


@pytest.mark.parametrize("failure", ["read refused", "a bug"])
async def test_a_reader_that_cannot_go_on_ends_the_connection(
    server: Server, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A reader that stops without a word leaves ``wait`` waiting for ever on a copy that
    nothing changes any more."""
    server.api.fake.set_scenario(HANG)
    remote = await server.connect()
    try:
        job = await remote.add(await server.job())
        remote.start(job_ids=[job.id])
        await poll(lambda: remote.get(job.id).state is JobState.RUNNING)  # type: ignore[union-attr]
        if failure == "read refused":
            requests = await watch_requests(remote)
            broken = {"title": "Broken", "status": 500, "code": "server.broken"}
            requests.answer = lambda request: (
                httpx.Response(500, json=broken) if request.url.path == "/api/queue" else None
            )
            reason = "Broken"
        else:

            async def bug(*_args: object) -> None:
                raise RuntimeError("a bug")

            monkeypatch.setattr(remote, "_apply_state", bug)
            reason = "the events of the Reframe server cannot be followed"
        await server.api.reframe.queue.add(await server.job("Other.mkv"))  # the copy reads
        [ended] = await asyncio.wait_for(remote.wait([job.id]), 10)
        assert ended.state is JobState.INTERRUPTED
        assert remote.lost == reason
    finally:
        await remote.close()
        await server.api.reframe.queue.cancel()


async def test_the_servers_folders_are_this_machines_in_every_text(server: Server) -> None:
    """The server writes its folders as ``<data>``, ``<config>`` and ``<cache>``: the output
    path, the plan and ``queue list --json`` show this machine's folders instead."""
    reframe = server.api.reframe
    source = reframe.config_dir / "Source.mkv"
    source.write_bytes(server.api.media_file("Source.mkv").read_bytes())
    draft = await reframe.jobs.draft(source, output=reframe.cache_dir / "Out.mkv")
    assert isinstance(draft, JobDraft)
    remote = await server.connect()
    try:
        job = await remote.add(draft.job)
        remote.start(job_ids=[job.id])
        [done] = await asyncio.wait_for(remote.wait([job.id]), 30)
    finally:
        await remote.close()
    assert done.output_path == reframe.cache_dir / "Out.mkv"
    assert done.log_path == reframe.data_dir / "logs" / f"{job.id}.log"
    shown = done.model_dump_json(exclude={"settings"})
    assert str(source) in shown  # the plan's input
    assert not any(label in shown for label in ("<data>", "<config>", "<cache>"))


async def test_settings_without_a_when_done_value_mean_nothing(server: Server) -> None:
    """A ``KeyError`` would end the command after its jobs ran."""
    remote = await server.connect()
    try:
        requests = await watch_requests(remote)
        requests.answer = lambda request: (
            httpx.Response(200, json={"queue": {}}) if request.url.path == "/api/settings" else None
        )
        assert await remote.when_done() == "nothing"
    finally:
        await remote.close()
