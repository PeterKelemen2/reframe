"""The event WebSocket hub. A client authenticates in its first message, then receives the
core's events with a sequence number: progress throttled per id, log lines batched, and a
heartbeat. Each connection reads its bus subscription only between two sends, so a client
that does not keep up leaves its backlog in that bounded, coalescing queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from reframe.events import EventBus, Subscription, coalesce_key
from reframe.models import (
    Event,
    JobLogEvent,
    JobStateEvent,
    ResyncEvent,
    TaskDoneEvent,
    TaskProgressEvent,
    json_text,
)
from reframe_server import security
from reframe_server.config import ServerConfig

__all__ = [
    "CLOSE_GOING_AWAY",
    "CLOSE_UNAUTHORIZED",
    "AuthMessage",
    "EventHub",
    "EventMessage",
    "Heartbeat",
    "Hello",
]

CLOSE_GOING_AWAY = 1001
CLOSE_UNAUTHORIZED = 4401

_TICK = time.get_clock_info("monotonic").resolution


class AuthMessage(BaseModel):
    """The client's first message."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    type: Literal["auth"]
    token: str | None = None
    """The run's token. Password mode: may be left out, the session cookie of the upgrade
    request counts."""


class Hello(BaseModel):
    """The server's first message, once the client is in."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    type: Literal["hello"] = "hello"
    instance: str
    """Random id of this server run (as in ``GET /api/health``); another one than before
    means the server restarted, and the client must probe its sources again."""
    heartbeat: float
    """Seconds between two heartbeats. A client that hears nothing for longer should
    reconnect."""


class EventMessage(BaseModel):
    """One event of the core."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    type: Literal["event"] = "event"
    seq: int
    """1 for the first event of a connection, then one more for each event, without gaps."""
    event: Event


class Heartbeat(BaseModel):
    """Sent every ``heartbeat`` seconds: the connection is alive."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heartbeat"] = "heartbeat"


class EventHub:
    """Every open ``WS /api/events`` connection. Created and closed by the app's lifespan."""

    def __init__(
        self,
        bus: EventBus,
        config: ServerConfig,
        *,
        log_interval: float = 0.25,
        progress_rate: float = 4.0,
        heartbeat: float = 15.0,
        auth_timeout: float = 5.0,
        close_timeout: float = 1.0,
        max_queue: int = 256,
        max_log_lines: int = 1000,
        hide: Callable[[JsonValue], JsonValue] = lambda value: value,
    ) -> None:
        """Times are in seconds. ``progress_rate``: progress messages per second per job or
        task at most. ``max_queue``: the subscription queue of each connection
        (:meth:`EventBus.subscribe`). ``max_log_lines``: lines per ``job.log`` message; older
        ones are counted in its ``dropped``. ``hide``: applied to the message, error and result of a
        task event before it is sent (the server's own folders)."""
        self._bus = bus
        self._config = config
        self._log_interval = log_interval
        self._progress_interval = 1.0 / progress_rate
        self._heartbeat = heartbeat
        self._auth_timeout = auth_timeout
        self._close_timeout = close_timeout
        self._max_queue = max_queue
        self._max_log_lines = max_log_lines
        self._hide = hide
        self._running: set[asyncio.Task[None]] = set()
        self._authenticated: set[_Connection] = set()
        self._closed = False

    @property
    def connections(self) -> int:
        """Open, authenticated connections."""
        return len(self._authenticated)

    def client_open(self, client_id: str) -> bool:
        """A connection that was given ``client_id`` is open (for ``attach``)."""
        return False

    async def serve(self, websocket: WebSocket) -> None:
        """Run one connection until it ends; a client that goes away ends it without an
        error."""
        await websocket.accept()
        if self._closed:
            await self._close(websocket, CLOSE_GOING_AWAY)
            return
        # Its own task, so that close() can cancel it: the ASGI task is the server's.
        task = asyncio.create_task(_Connection(self, websocket).run())
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        try:
            await asyncio.wait((task,))
        finally:
            task.cancel()
        if not task.cancelled():
            task.result()

    async def close(self) -> None:
        """End every connection with code 1001. Returns within about ``close_timeout``, also
        when a client does not read. Safe to call more than once."""
        self._closed = True
        running = tuple(self._running)
        for task in running:
            task.cancel()
        if running:
            await asyncio.wait(running)

    def _subscribe(self) -> Subscription:
        return self._bus.subscribe(max_queue=self._max_queue)

    async def _close(self, websocket: WebSocket, code: int) -> None:
        # uvicorn's send waits until the client reads, so a stuck client would hold it forever.
        with contextlib.suppress(TimeoutError, WebSocketDisconnect, WebSocketDisconnected):
            async with asyncio.timeout(self._close_timeout):
                await websocket.close(code)


class _Connection:
    def __init__(self, hub: EventHub, websocket: WebSocket) -> None:
        self._hub = hub
        self._websocket = websocket

    async def run(self) -> None:
        try:
            if await self._authenticate():
                await self._stream()
        except asyncio.CancelledError:
            await self._hub._close(self._websocket, CLOSE_GOING_AWAY)
            raise
        except WebSocketDisconnect:
            pass  # the client went away while a message was sent

    async def _authenticate(self) -> bool:
        hub = self._hub
        try:
            async with asyncio.timeout(hub._auth_timeout):
                message = await self._websocket.receive()
            auth = AuthMessage.model_validate_json(message.get("text") or "")
        except (TimeoutError, ValidationError):
            auth = None
        if auth is None or not security.ws_authenticated(hub._config, self._websocket, auth.token):
            await self._hub._close(self._websocket, CLOSE_UNAUTHORIZED)
            return False
        return True

    async def _stream(self) -> None:
        hub = self._hub
        stream = _Stream(hub, self._websocket)
        hub._authenticated.add(self)
        try:
            await stream.send(
                Hello(instance=self._websocket.app.state.instance, heartbeat=hub._heartbeat)
            )
            pump = asyncio.create_task(stream.pump())
            listen = asyncio.create_task(self._listen())
            try:
                await asyncio.wait((pump, listen), return_when=asyncio.FIRST_COMPLETED)
            finally:
                pump.cancel()
                listen.cancel()
                await asyncio.wait((pump, listen))
            for task in (pump, listen):
                if not task.cancelled():
                    task.result()
            if not pump.cancelled():  # the bus closed
                await self._hub._close(self._websocket, CLOSE_GOING_AWAY)
        finally:
            stream.close()
            hub._authenticated.discard(self)

    async def _listen(self) -> None:
        while (await self._websocket.receive())["type"] != "websocket.disconnect":
            pass


@dataclass
class _Window:
    """The progress throttle of one job or task: nothing is sent before ``until``."""

    until: float
    held: Event | None = None


@dataclass
class _LogBatch:
    lines: deque[str]
    dropped: int = 0

    def add(self, event: JobLogEvent) -> None:
        before = len(self.lines)
        self.lines.extend(event.lines)
        self.dropped += event.dropped + before + len(event.lines) - len(self.lines)


class _Stream:
    """What one authenticated connection is sent: sequence numbers, the progress throttle, the
    log batches and the heartbeat."""

    def __init__(self, hub: EventHub, websocket: WebSocket) -> None:
        self._hub = hub
        self._websocket = websocket
        self._loop = asyncio.get_running_loop()
        self._subscription = hub._subscribe()
        self._seq = 0
        self._windows: dict[tuple[str, str], _Window] = {}
        self._logs: dict[str, _LogBatch] = {}
        self._log_due: float | None = None
        self._next_heartbeat = self._loop.time() + hub._heartbeat

    def close(self) -> None:
        self._subscription.close()

    async def send(self, message: BaseModel) -> None:
        await self._websocket.send_text(json_text(message))

    async def pump(self) -> None:
        """Send events until the bus closes."""
        while True:
            await self._send_due()
            try:
                async with asyncio.timeout_at(self._deadline()):
                    event = await anext(self._subscription)
            except TimeoutError:
                continue
            except StopAsyncIteration:
                return
            await self._route(event)

    def _deadline(self) -> float:
        due = [window.until for window in self._windows.values() if window.held is not None]
        if self._log_due is not None:
            due.append(self._log_due)
        return min([self._next_heartbeat, *due])

    async def _route(self, event: Event) -> None:
        key = coalesce_key(event)
        if key is not None:
            await self._throttle(key, event)
        elif isinstance(event, JobLogEvent):
            self._batch(event)
        else:
            await self._flush_subject(event)
            if isinstance(event, ResyncEvent) and event.reason == "overflow":
                # The bus ended this subscription. Subscribe before the client hears of it,
                # so the snapshots it reads then miss no later event.
                self._subscription.close()
                self._subscription = self._hub._subscribe()
            await self._send_event(event)

    async def _send_event(self, event: Event) -> None:
        if isinstance(event, TaskProgressEvent | TaskDoneEvent):
            task, hide = event.task, self._hub._hide
            shown = {
                "message": hide(task.message),
                "error": hide(task.error),
                "result": hide(task.result),
            }
            event = event.model_copy(update={"task": task.model_copy(update=shown)})
        self._seq += 1
        await self.send(EventMessage(seq=self._seq, event=event))

    async def _send_due(self) -> None:
        # asyncio runs a timer up to one clock tick early: without the tick, the pump would
        # spin until the clock reaches the deadline.
        now = self._loop.time() + _TICK
        for key, window in list(self._windows.items()):
            if now >= window.until:
                if window.held is None:
                    del self._windows[key]
                else:
                    await self._release(window)
        if self._log_due is not None and now >= self._log_due:
            for job_id in list(self._logs):
                await self._flush_log(job_id)
        if now >= self._next_heartbeat:
            self._next_heartbeat = now + self._hub._heartbeat
            await self.send(Heartbeat())

    async def _throttle(self, key: tuple[str, str], event: Event) -> None:
        now = self._loop.time()
        window = self._windows.get(key)
        if window is None or now >= window.until:
            self._windows[key] = _Window(now + self._hub._progress_interval)
            await self._send_event(event)
        else:
            window.held = event

    async def _release(self, window: _Window) -> None:
        event, window.held = window.held, None
        if event is not None:
            window.until = self._loop.time() + self._hub._progress_interval
            await self._send_event(event)

    def _batch(self, event: JobLogEvent) -> None:
        batch = self._logs.get(event.job_id)
        if batch is None:
            batch = self._logs[event.job_id] = _LogBatch(deque(maxlen=self._hub._max_log_lines))
        if self._log_due is None:
            self._log_due = self._loop.time() + self._hub._log_interval
        batch.add(event)

    async def _flush_log(self, job_id: str) -> None:
        batch = self._logs.pop(job_id, None)
        if not self._logs:
            self._log_due = None
        if batch is not None:
            lines = list(batch.lines)
            await self._send_event(JobLogEvent(job_id=job_id, lines=lines, dropped=batch.dropped))

    async def _flush_subject(self, event: Event) -> None:
        """Send what is held back for the job or task that ``event`` ends or changes, so the
        client never gets its progress after its end."""
        log: str | None = None
        if isinstance(event, JobStateEvent):
            key, log = ("job.progress", event.job_id), event.job_id
        elif isinstance(event, TaskDoneEvent):
            key = ("task.progress", event.task.id)
        else:
            return
        window = self._windows.get(key)
        if window is not None:
            await self._release(window)
        if log is not None:
            await self._flush_log(log)
