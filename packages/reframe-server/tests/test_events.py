"""``WS /api/events``: first-message auth, sequence numbers, the progress throttle, log
batches, the heartbeat, slow and stuck clients, and shutdown."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import secrets
import time
import tracemalloc
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from reframe.events import Subscription
from reframe.models import (
    AppWarningEvent,
    JobLogEvent,
    JobProgress,
    JobProgressEvent,
    JobState,
    JobStateEvent,
    NotificationEvent,
    QueueChangedEvent,
    TaskDoneEvent,
    TaskInfo,
    TaskProgressEvent,
    TaskState,
)
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.events import EventHub
from reframe_testing.server import Api, LiveServer, receive_json

pytestmark = pytest.mark.anyio

Json = dict[str, Any]


class _Errors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def subscriptions(api: Api, monkeypatch: pytest.MonkeyPatch) -> list[Subscription]:
    """Every subscription the hub makes from now on."""
    made: list[Subscription] = []
    subscribe = api.reframe.events.subscribe

    def spy(**options: Any) -> Subscription:
        made.append(subscribe(**options))
        return made[-1]

    monkeypatch.setattr(api.reframe.events, "subscribe", spy)
    return made


@asynccontextmanager
async def serving(api: Api, **options: Any) -> AsyncIterator[LiveServer]:
    """``api`` over TCP, with a hub made with ``options``. Fails if an exception escaped the hub
    (uvicorn logs it)."""
    api.app.state.hub = EventHub(api.reframe.events, api.config, **options)
    errors = _Errors()
    logger = logging.getLogger("uvicorn.error")
    async with api.live() as server:
        logger.addHandler(errors)  # after uvicorn has configured its loggers
        try:
            yield server
        finally:
            await asyncio.wait_for(hub(api).close(), 10)
    logger.removeHandler(errors)
    assert errors.messages == []


def hub(api: Api) -> EventHub:
    served: EventHub = api.app.state.hub
    return served


class Client:
    """A connection that has received its hello. Checks every event's sequence number."""

    def __init__(self, connection: ClientConnection, hello: Json) -> None:
        self.connection = connection
        self.hello = hello
        self.seq = 0

    async def message(self, limit: float = 10.0) -> Json:
        message: Json = await receive_json(self.connection, limit)
        if message["type"] == "event":
            assert message["seq"] == self.seq + 1, "a gap or a repeat in the sequence"
            self.seq += 1
        return message

    async def events_until(
        self, done: Callable[[Json], bool], limit: float = 10.0, *, keep: bool = True
    ) -> list[Json]:
        """Events until ``done(event)`` is true for one (the last in the list). ``keep=False``
        keeps only that one."""
        events: list[Json] = []
        async with asyncio.timeout(limit):
            while not events or not done(events[-1]):
                message = await self.message()
                if message["type"] == "event":
                    if not keep:
                        events.clear()
                    events.append(message["event"])
        return events


@asynccontextmanager
async def signed_in(server: LiveServer, api: Api) -> AsyncIterator[Client]:
    async with server.connect(compression=None) as connection:
        await connection.send(json.dumps({"type": "auth", "token": api.token}))
        hello = await receive_json(connection)
        assert hello["type"] == "hello"
        yield Client(connection, hello)


async def closed(
    connection: ClientConnection, limit: float = 10.0
) -> tuple[int | None, list[Json]]:
    """Read until the server closes: its close code and the messages before it."""
    messages: list[Json] = []
    async with asyncio.timeout(limit):
        try:
            while True:
                messages.append(json.loads(await connection.recv()))
        except ConnectionClosed:
            pass
    return connection.close_code, messages


async def wait_until(condition: Callable[[], bool], limit: float = 10.0) -> None:
    async with asyncio.timeout(limit):
        while not condition():  # noqa: ASYNC110 - the hub has no event for these states
            await asyncio.sleep(0.01)


async def stall(api: Api, client: Client, subscription: Subscription) -> int:
    """Stop reading on ``client``, then publish large warnings until the hub cannot send to it
    and its subscription keeps a backlog. Returns the number of warnings published."""
    client.connection.transport.pause_reading()
    published = 0
    while published < 400:
        api.reframe.events.publish(
            AppWarningEvent(code="test.stall", message=secrets.token_hex(64 * 1024))
        )
        published += 1
        await asyncio.sleep(0.05)
        if subscription.pending():
            await asyncio.sleep(0.2)
            if subscription.pending():
                return published
    raise AssertionError("the hub never stopped sending to a client that does not read")


def progress(job_id: str, percent: float) -> JobProgressEvent:
    return JobProgressEvent(job_id=job_id, progress=JobProgress(percent=percent))


def task_info(state: TaskState, percent: float) -> TaskInfo:
    return TaskInfo(id="task-1", kind="test", state=state, progress=percent)


def percent_of(event: Json) -> float | None:
    if event["type"] == "job.progress":
        return float(event["progress"]["percent"])
    if event["type"] in ("task.progress", "task.done"):
        return float(event["task"]["progress"])
    return None


async def test_a_slow_consumer_costs_bounded_memory_and_gets_the_latest_values(
    api: Api, subscriptions: list[Subscription]
) -> None:
    """A client that stops reading while thousands of progress and log events are published:
    the server's memory does not grow with them, and once the client reads again it gets a
    resync, every warning, and the last progress of every job."""
    jobs, count = 4, 5000
    last = {f"job-{i % jobs}": i * 100 / count for i in range(count - jobs, count)}
    latest: dict[str, float] = {}

    def all_latest(event: Json) -> bool:
        if event["type"] == "job.progress":
            latest[event["job_id"]] = event["progress"]["percent"]
        return latest == last

    async with (
        serving(api, max_queue=32, progress_rate=20, log_interval=0.05) as server,
        signed_in(server, api) as client,
    ):
        stalled = await stall(api, client, subscriptions[0])
        tracemalloc.start()
        try:
            for i in range(count):
                job = f"job-{i % jobs}"
                api.reframe.events.publish(progress(job, i * 100 / count))
                api.reframe.events.publish(JobLogEvent(job_id=job, lines=[f"{i} " + "x" * 400]))
                if i % 100 == 0:
                    await asyncio.sleep(0)
            grown, _peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # Kept in memory, the log events alone would hold about 5 MB.
        assert grown < 1_000_000

        client.connection.transport.resume_reading()
        events = await client.events_until(all_latest)
    warnings = [e for e in events if e["type"] == "app.warning" and e["code"] == "test.stall"]
    assert len(warnings) == stalled
    resyncs = [e for e in events if e["type"] == "resync"]
    assert resyncs
    assert resyncs[0]["dropped"] > 0


async def test_a_client_that_overflows_gets_a_resync_and_stays_subscribed(
    api: Api, subscriptions: list[Subscription]
) -> None:
    """More state events than the bus keeps for a client that does not read: the bus ends
    that subscription, and the client later gets a resync and then the events after it."""
    bus = api.reframe.events
    before = bus.subscriber_count
    async with serving(api, max_queue=4) as server, signed_in(server, api) as client:
        await stall(api, client, subscriptions[0])
        for i in range(40):
            bus.publish(QueueChangedEvent(job_ids=[f"job-{i}"]))
        assert subscriptions[0].overflowed

        client.connection.transport.resume_reading()
        events = await client.events_until(lambda event: event["type"] == "resync")
        assert events[-1]["reason"] == "overflow"
        bus.publish(NotificationEvent(title="after"))
        await client.events_until(lambda event: event.get("title") == "after")
        assert bus.subscriber_count == before + 1


async def test_progress_is_limited_per_id_and_ends_with_the_latest_value(api: Api) -> None:
    """Two jobs that report progress about 100 times a second: each one reaches the client at
    most ``progress_rate`` times a second, and the last value of each arrives."""
    rate, count = 10.0, 60
    seen: dict[str, list[float]] = {"job-a": [], "job-b": []}

    def both_ended(event: Json) -> bool:
        if event["type"] == "job.progress":
            seen[event["job_id"]].append(event["progress"]["percent"])
        return all(values and values[-1] == count - 1 for values in seen.values())

    async with serving(api, progress_rate=rate) as server, signed_in(server, api) as client:
        loop = asyncio.get_running_loop()
        started = loop.time()
        for i in range(count):
            for job in seen:
                api.reframe.events.publish(progress(job, i))
            await asyncio.sleep(0.01)
        elapsed = loop.time() - started
        await client.events_until(both_ended)
    for values in seen.values():
        assert len(values) <= elapsed * rate + 2


async def test_the_throttle_forgets_the_ids_that_went_quiet(api: Api) -> None:
    """A long connection sees thousands of tasks: what the throttle keeps for each one is
    freed once that task goes quiet."""
    publish = api.reframe.events.publish
    async with serving(api, progress_rate=100) as server, signed_in(server, api) as client:
        tracemalloc.start()
        try:
            for i in range(3000):
                task = TaskInfo(id=f"task-{i}", kind="test", state=TaskState.RUNNING)
                publish(TaskProgressEvent(task=task))
                if i % 100 == 0:
                    await asyncio.sleep(0)
            await client.events_until(
                lambda event: event.get("task", {}).get("id") == "task-2999", keep=False
            )
            await asyncio.sleep(0.05)
            publish(NotificationEvent(title="end"))
            await client.events_until(lambda event: event.get("title") == "end", keep=False)
            grown, _peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    # Kept, the 3000 throttles hold more than 1 MB.
    assert grown < 600_000


async def test_log_lines_are_batched_per_job(api: Api) -> None:
    """Log lines of two jobs that come one by one every 10 ms reach the client in a few
    messages per job, complete and in order."""
    interval, count = 0.1, 40
    batches: dict[str, list[list[str]]] = {"job-a": [], "job-b": []}

    def both_ended(event: Json) -> bool:
        if event["type"] == "job.log":
            batches[event["job_id"]].append(event["lines"])
        return all(b and b[-1][-1] == f"{job} {count - 1}" for job, b in batches.items())

    async with serving(api, log_interval=interval) as server, signed_in(server, api) as client:
        loop = asyncio.get_running_loop()
        started = loop.time()
        for i in range(count):
            for job in batches:
                api.reframe.events.publish(JobLogEvent(job_id=job, lines=[f"{job} {i}"]))
            await asyncio.sleep(0.01)
        elapsed = loop.time() - started
        await client.events_until(both_ended)
    for job, messages in batches.items():
        lines = [line for message in messages for line in message]
        assert lines == [f"{job} {i}" for i in range(count)]
        assert len(messages) <= elapsed / interval + 1


async def test_a_log_burst_keeps_the_latest_lines_and_counts_the_rest(api: Api) -> None:
    lines = [f"line {i}" for i in range(24)]
    async with (
        serving(api, max_log_lines=10, log_interval=0.2) as server,
        signed_in(server, api) as client,
    ):
        for start in range(0, 24, 8):
            api.reframe.events.publish(
                JobLogEvent(job_id="job-a", lines=lines[start : start + 8], dropped=1)
            )
        events = await client.events_until(lambda event: event["type"] == "job.log")
    assert events[-1]["lines"] == lines[-10:]
    assert events[-1]["dropped"] == 3 + 14


@pytest.mark.parametrize("subject", ["job", "task"])
async def test_what_is_held_back_goes_out_before_the_end(api: Api, subject: str) -> None:
    """A progress value held back by the throttle, and a job's waiting log lines, reach the
    client before the event that ends the job or task, never after it."""
    first: JobProgressEvent | TaskProgressEvent
    held: JobProgressEvent | TaskProgressEvent
    end: JobStateEvent | TaskDoneEvent
    if subject == "job":
        first, held = progress("job-a", 10), progress("job-a", 20)
        end = JobStateEvent(job_id="job-a", state=JobState.DONE, previous=JobState.RUNNING)
    else:
        first = TaskProgressEvent(task=task_info(TaskState.RUNNING, 10))
        held = TaskProgressEvent(task=task_info(TaskState.RUNNING, 20))
        end = TaskDoneEvent(task=task_info(TaskState.DONE, 100))
    publish = api.reframe.events.publish
    async with (
        serving(api, progress_rate=0.5, log_interval=5) as server,
        signed_in(server, api) as client,
    ):
        publish(first)
        await client.events_until(lambda event: percent_of(event) == 10)
        publish(held)
        if subject == "job":
            publish(JobLogEvent(job_id="job-a", lines=["last line"]))
        publish(end)
        events = await client.events_until(lambda event: event["type"] == end.type)
    assert [percent_of(e) for e in events if e["type"] == held.type] == [20]
    if subject == "job":
        assert [e["lines"] for e in events if e["type"] == "job.log"] == [["last line"]]


async def test_an_end_with_nothing_held_back_comes_alone(api: Api) -> None:
    """``job.state`` of a job whose progress already went out, and of a job that sent no
    progress and no log lines: nothing else is sent with them."""
    publish = api.reframe.events.publish
    async with serving(api, progress_rate=0.5) as server, signed_in(server, api) as client:
        publish(progress("job-a", 10))
        await client.events_until(lambda event: percent_of(event) == 10)
        publish(JobStateEvent(job_id="job-a", state=JobState.DONE, previous=JobState.RUNNING))
        publish(JobStateEvent(job_id="job-b", state=JobState.RUNNING, previous=JobState.WAITING))
        publish(NotificationEvent(title="end"))
        events = await client.events_until(lambda event: event.get("title") == "end")
    jobs = [(e["type"], e["job_id"]) for e in events if e["type"].startswith("job.")]
    assert jobs == [("job.state", "job-a"), ("job.state", "job-b")]


async def test_a_message_after_the_auth_does_not_end_the_connection(api: Api) -> None:
    async with serving(api, heartbeat=0.1) as server, signed_in(server, api) as client:
        await client.connection.send(json.dumps({"type": "unknown"}))
        beats = 0
        async with asyncio.timeout(10):
            while beats < 2:  # the server has read the message by then
                beats += (await client.message())["type"] == "heartbeat"
        api.reframe.events.publish(NotificationEvent(title="still here"))
        await client.events_until(lambda event: event.get("title") == "still here")


async def test_an_idle_connection_gets_heartbeats(api: Api) -> None:
    """With no events, the client still hears from the server every ``heartbeat`` seconds;
    the hello says how often. Heartbeats take no sequence number."""
    async with serving(api, heartbeat=0.1) as server, signed_in(server, api) as client:
        assert client.hello["heartbeat"] == 0.1
        beats = 0
        async with asyncio.timeout(10):
            while beats < 3:
                beats += (await client.message())["type"] == "heartbeat"
        api.reframe.events.publish(NotificationEvent(title="after"))
        await client.events_until(lambda event: event.get("title") == "after")


async def test_a_reconnect_starts_a_new_sequence(api: Api) -> None:
    async with serving(api) as server:
        async with signed_in(server, api) as first:
            api.reframe.events.publish(NotificationEvent(title="one"))
            api.reframe.events.publish(NotificationEvent(title="two"))
            await first.events_until(lambda event: event.get("title") == "two")
        async with signed_in(server, api) as second:
            api.reframe.events.publish(NotificationEvent(title="three"))
            await second.events_until(lambda event: event.get("title") == "three")
    assert first.seq >= 2
    assert second.hello["instance"] == first.hello["instance"] == api.app.state.instance


@pytest.mark.parametrize(
    ("first_message", "asked", "admitted"),
    [
        ({"type": "auth", "token": "wrong"}, ["wrong"], False),
        ({"type": "auth"}, [None], True),
        ({"type": "subscribe"}, [], False),
    ],
    ids=["wrong token", "no token: the session cookie decides", "not an auth message"],
)
async def test_the_first_message_lets_the_client_in_or_closes_4401(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    first_message: Json,
    asked: list[str | None],
    admitted: bool,
) -> None:
    calls: list[str | None] = []

    def ws_authenticated(config: ServerConfig, websocket: object, token: str | None) -> bool:
        calls.append(token)
        return token is None  # as if the upgrade carried a valid session cookie

    monkeypatch.setattr(security, "ws_authenticated", ws_authenticated)
    async with serving(api) as server, server.connect() as connection:
        await connection.send(json.dumps(first_message))
        if admitted:
            assert (await receive_json(connection))["type"] == "hello"
            assert hub(api).connections == 1
        else:
            assert await closed(connection) == (4401, [])
    assert calls == asked


async def test_no_first_message_in_time_closes_4401_and_sends_nothing(api: Api) -> None:
    async with serving(api, auth_timeout=0.3) as server, server.connect() as connection:
        api.reframe.events.publish(NotificationEvent(title="not for strangers"))
        assert await closed(connection) == (4401, [])
        assert hub(api).connections == 0


async def test_a_disconnect_frees_the_subscription(api: Api) -> None:
    bus = api.reframe.events
    before = bus.subscriber_count
    async with serving(api) as server:
        async with server.connect() as connection:
            assert hub(api).connections == 0
            await connection.send(json.dumps({"type": "auth", "token": api.token}))
            await receive_json(connection)
            assert (hub(api).connections, bus.subscriber_count) == (1, before + 1)
        await wait_until(lambda: (hub(api).connections, bus.subscriber_count) == (0, before))


async def test_a_client_that_drops_while_the_hub_waits_to_send(
    api: Api, subscriptions: list[Subscription]
) -> None:
    bus = api.reframe.events
    before = bus.subscriber_count
    async with serving(api) as server, signed_in(server, api) as client:
        await stall(api, client, subscriptions[0])
        client.connection.transport.abort()
        await wait_until(lambda: (hub(api).connections, bus.subscriber_count) == (0, before))


async def test_close_while_events_flow_ends_every_connection_also_a_stuck_one(
    api: Api, subscriptions: list[Subscription]
) -> None:
    """Shutdown: a reading client is closed with 1001, a client that does not read does not
    hold it up, every subscription is freed and a client that comes later is closed too."""
    bus = api.reframe.events
    before = bus.subscriber_count

    async def publish_forever() -> None:
        for i in itertools.count():
            bus.publish(progress("job-a", i % 100))
            bus.publish(JobLogEvent(job_id="job-a", lines=[f"line {i}"]))
            await asyncio.sleep(0.005)

    async with (
        serving(api, close_timeout=0.5) as server,
        signed_in(server, api) as stuck,
        signed_in(server, api) as reading,
    ):
        reader = asyncio.create_task(closed(reading.connection))
        await stall(api, stuck, subscriptions[0])
        publisher = asyncio.create_task(publish_forever())
        try:
            await asyncio.sleep(0.2)
            started = time.monotonic()
            await asyncio.wait_for(hub(api).close(), 10)
            elapsed = time.monotonic() - started
        finally:
            publisher.cancel()
            stuck.connection.transport.abort()
        assert (await reader)[0] == 1001
        assert elapsed < 3
        assert (hub(api).connections, bus.subscriber_count) == (0, before)
        async with server.connect() as late:
            assert await closed(late) == (1001, [])


async def test_the_facade_closing_ends_the_connection_with_1001(api: Api) -> None:
    async with serving(api) as server, signed_in(server, api) as client:
        await api.reframe.close()
        assert (await closed(client.connection))[0] == 1001
        await wait_until(lambda: hub(api).connections == 0)
