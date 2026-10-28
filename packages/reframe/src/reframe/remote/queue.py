"""The queue of a server that owns it, over its REST routes and its event WebSocket.

:class:`RemoteQueue` keeps a copy of the jobs that only the event stream changes, in the order
the server sent the events, so the synchronous ``get`` and ``list`` of the queue contract can
answer from it. A call that changes a job returns once the copy shows the change. The jobs it
adds are attached to its event connection: when the connection ends without :meth:`close`'s
``detach``, the server cancels them.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import json
import logging
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from reframe import paths
from reframe.events import EventBus
from reframe.models.events import (
    EVENT_ADAPTER,
    Event,
    JobProgressEvent,
    JobStateEvent,
    PowerCountdownEvent,
    QueueChangedEvent,
    ResyncEvent,
)
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.queue import JobState, QueueJob
from reframe.models.text import json_text
from reframe.queue.errors import JobStateError, QueueError, UnknownJobError
from reframe.queue.logs import log_file
from reframe.remote.owner import Owner

__all__ = ["OwnerStopping", "RemoteError", "RemotePower", "RemoteQueue"]

log = logging.getLogger(__name__)

ENDED = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
_ACTIVE = frozenset({JobState.RUNNING, JobState.PAUSED})
#: The events that the queue's users follow; the others stay with the server.
FORWARDED = frozenset({"job.state", "job.progress", "queue.changed", "power.countdown", "resync"})
OPEN_TIMEOUT = 10.0
CHANGE_WAIT = 10.0
"""Seconds a call waits for the event of its change before it reads the whole queue."""
SERVER_STOPS = 1012
GOING_AWAY = 1001
UNAUTHORIZED = 4401

_JOBS: TypeAdapter[list[QueueJob]] = TypeAdapter(list[QueueJob])
_ISSUES: TypeAdapter[list[ValidationIssue]] = TypeAdapter(list[ValidationIssue])
_Jobs = builtins.list[QueueJob]


class RemoteError(QueueError):
    """The server refused a call, or cannot be reached. ``code`` is the problem's code
    (``connection.lost`` when the server is gone)."""

    def __init__(self, message: str, *, code: str = "", status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class OwnerStopping(RemoteError):
    """The server closed the event connection before it was in: it is stopping. Look for an
    owner again."""


def _problem(response: httpx.Response) -> tuple[str, str]:
    try:
        body = json.loads(response.content)
    except ValueError:
        body = None
    if isinstance(body, dict):
        title = str(body.get("title") or response.reason_phrase)
        detail = body.get("detail")
        return str(body.get("code") or ""), f"{title}: {detail}" if detail else title
    return "", f"{response.status_code} {response.reason_phrase}"


def _unhide(value: Any, folders: dict[str, Path]) -> Any:
    """A path that the server wrote as ``<data>/…`` (its folders are hidden in answers), as
    this machine's path."""
    if isinstance(value, str):
        for label, folder in folders.items():
            if value == label or value.startswith((f"{label}/", f"{label}\\")):
                return str(folder) + value[len(label) :]
    return value


class RemotePower:
    """The owner's when-done countdown: what is pending, and its cancel."""

    def __init__(self, queue: RemoteQueue) -> None:
        self._queue = queue
        self.pending: PowerCountdownEvent | None = None

    async def cancel(self, countdown_id: str | None = None) -> bool:
        """Cancel the pending countdown (only if it is ``countdown_id``); whether it was."""
        pending = self.pending
        if pending is None or (countdown_id is not None and countdown_id != pending.countdown_id):
            return False
        answer = await self._queue._request("POST", "/api/power/cancel")
        return bool(answer.get("cancelled")) if isinstance(answer, dict) else False

    def _seen(self, event: PowerCountdownEvent) -> None:
        self.pending = None if event.phase in ("executing", "cancelled") else event


class RemoteQueue:
    """The queue contract of :class:`~reframe.queue.QueueService` on a server. Create it with
    :meth:`connect`; :meth:`close` it. ``events`` carries the server's job, queue and countdown
    events after the copy has taken them; it closes when the connection is lost."""

    def __init__(
        self,
        owner: Owner,
        *,
        data_dir: Path,
        config_dir: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.owner = owner
        self.data_dir = data_dir
        self._folders = {
            "<data>": data_dir,
            "<config>": config_dir or paths.config_dir(),
            "<cache>": cache_dir or paths.cache_dir(),
        }
        self.events = EventBus()
        self.power = RemotePower(self)
        self.client_id = ""
        self.lost: str | None = None
        """Why the connection ended, once it has (``None`` while it is open or was closed)."""
        self._http = httpx.AsyncClient(
            base_url=owner.url,
            headers={"Authorization": f"Bearer {owner.endpoint.token}"},
            timeout=httpx.Timeout(None, connect=OPEN_TIMEOUT),
        )
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._jobs: dict[str, QueueJob] = {}
        self._order: builtins.list[str] = []
        self._mirror = asyncio.Lock()
        """Held while the copy changes: an event, or a whole queue read with its request."""
        self._changed = asyncio.Condition()
        self._pending: set[asyncio.Task[None]] = set()
        self._closing = False
        self._closed = False

    @classmethod
    async def connect(
        cls,
        owner: Owner,
        *,
        data_dir: Path,
        config_dir: Path | None = None,
        cache_dir: Path | None = None,
    ) -> RemoteQueue:
        """Open the event connection (it keeps an idle owner running and is what jobs are
        attached to), then read the queue and the pending countdown.

        :raises OwnerStopping: the server closed the connection before it was in.
        :raises RemoteError: it cannot be reached or refused the token."""
        queue = cls(owner, data_dir=data_dir, config_dir=config_dir, cache_dir=cache_dir)
        try:
            await queue._open()
        except BaseException:
            await queue.close()
            raise
        return queue

    async def _open(self) -> None:
        url = f"ws://127.0.0.1:{self.owner.endpoint.port}/api/events"
        try:
            self._ws = await connect(url, open_timeout=OPEN_TIMEOUT, max_size=None)
            await self._ws.send(json_text({"type": "auth", "token": self.owner.endpoint.token}))
            async with asyncio.timeout(OPEN_TIMEOUT):
                hello = json.loads(await self._ws.recv())
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd is not None else None
            if code == UNAUTHORIZED:
                raise RemoteError(
                    "the Reframe server refused the token of its server.json", code="auth"
                ) from None
            raise OwnerStopping("the Reframe server is stopping", code="server.stopping") from None
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI, ValueError) as exc:
            raise RemoteError(
                f"the Reframe server at {self.owner.url} cannot be reached: {exc}",
                code="connection.failed",
            ) from None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            raise RemoteError("the Reframe server did not greet this client", code="protocol")
        self.client_id = str(hello.get("client_id") or "")
        await self._refresh()
        power = await self._request("GET", "/api/power")
        if isinstance(power, dict) and power.get("pending") is not None:
            self.power._seen(PowerCountdownEvent.model_validate(power["pending"]))
        self._reader = asyncio.get_running_loop().create_task(
            self._read(), name="reframe-remote-events"
        )

    async def close(self, *, detach: bool = False) -> None:
        """End the connection. ``detach``: the jobs it attached run on; without it, the server
        cancels them. Safe to call more than once."""
        if self._closed:
            return
        self._closing = True
        try:
            if self._pending:
                await asyncio.wait(builtins.list(self._pending))
            ws = self._ws
            if ws is not None:
                with contextlib.suppress(ConnectionClosed, OSError):
                    if detach:
                        await ws.send(json_text({"type": "detach"}))
                    await ws.close()
            if self._reader is not None:
                self._reader.cancel()
                await asyncio.wait((self._reader,))
            await self._http.aclose()
        finally:
            self._closed = True
            self.events.close()
            async with self._changed:
                self._changed.notify_all()

    async def validate(self, job: JobSettings) -> list[ValidationIssue]:
        """The owner's issues of ``job`` (its tools and encoder statuses decide)."""
        answer = await self._request("POST", "/api/jobs/validate", {"job": self._dump(job)})
        return _ISSUES.validate_python(answer)

    async def when_done(self) -> str:
        """The owner's when-done setting."""
        answer = await self._request("GET", "/api/settings")
        return str(answer["queue"]["when_done"]) if isinstance(answer, dict) else "none"

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob:
        """Add ``job``, attached to this connection."""
        body = {"jobs": [self._dump(job)], "position": position, "attach": self.client_id}
        [added] = self._jobs_of(await self._request("POST", "/api/queue", body))
        async with self._mirror:
            if added.id not in self._jobs:  # else the event stream already brought it
                self._jobs[added.id] = added
                index = len(self._order) if position is None else min(position, len(self._order))
                self._order.insert(index, added.id)
                self._renumber()
        await self._notify()
        return self._copy(added.id) or added

    def list(self) -> _Jobs:
        return [self._jobs[job_id].model_copy(deep=True) for job_id in self._order]

    def get(self, job_id: str) -> QueueJob | None:
        return self._copy(job_id)

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        """Start the queue (``job_ids``: only these jobs). The request is sent in the
        background; the next awaited call waits for it."""
        self._check_open()
        ids = None if job_ids is None else builtins.list(job_ids)
        for job_id in ids or ():
            self._known(job_id)
        body = None if ids is None else {"job_ids": ids}
        task = asyncio.get_running_loop().create_task(self._send_start(body))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _send_start(self, body: dict[str, Any] | None) -> None:
        try:
            await self._request("POST", "/api/queue/start", body)
        except RemoteError as exc:
            log.warning("the queue was not started: %s", exc)

    async def wait(self, job_ids: Sequence[str] | None = None) -> _Jobs:
        """Until the jobs have ended or left the queue, or the connection has ended (then the
        copy says how they were last seen)."""
        if self._pending:
            await asyncio.wait(builtins.list(self._pending))
        ids = builtins.list(self._order) if job_ids is None else builtins.list(job_ids)
        for job_id in ids:
            self._known(job_id)

        def ended() -> bool:
            return (
                self._closed
                or self.lost is not None
                or all(
                    job_id not in self._jobs or self._jobs[job_id].state in ENDED for job_id in ids
                )
            )

        async with self._changed:
            await self._changed.wait_for(ended)
        return [job for job in (self._copy(job_id) for job_id in ids) if job is not None]

    async def cancel(self, job_id: str | None = None) -> None:
        """Cancel a job (``None``: every job that has not ended); returns once they ended."""
        await self._settle()
        if job_id is None:
            targets = [j for j in self._order if self._jobs[j].state not in ENDED]
            await self._request("POST", "/api/queue/cancel")
        else:
            self._known(job_id)
            targets = [job_id]
            await self._request("POST", f"/api/queue/{job_id}/cancel", job_id=job_id)
        await self._until(lambda: all(self._ended_or_gone(j) for j in targets))

    async def pause(self, job_id: str | None = None) -> None:
        await self._toggle("pause", job_id, JobState.RUNNING)

    async def resume(self, job_id: str | None = None) -> None:
        await self._toggle("resume", job_id, JobState.PAUSED)

    async def _toggle(self, action: str, job_id: str | None, before: JobState) -> None:
        await self._settle()
        ids = builtins.list(self._order) if job_id is None else [job_id]
        if job_id is not None:
            self._known(job_id)
        targets = [j for j in ids if self._jobs[j].state is before]
        path = f"/api/queue/{action}" if job_id is None else f"/api/queue/{job_id}/{action}"
        await self._request("POST", path, job_id=job_id)
        await self._until(
            lambda: all(j not in self._jobs or self._jobs[j].state is not before for j in targets)
        )

    async def retry(self, job_id: str) -> QueueJob:
        await self._settle()
        self._known(job_id)
        answer = await self._request("POST", f"/api/queue/{job_id}/retry", job_id=job_id)
        [job] = self._jobs_of([answer])
        async with self._mirror:
            if job_id in self._jobs:
                self._jobs[job_id] = job
        await self._notify()
        return job

    async def remove(self, job_id: str) -> None:
        await self._settle()
        self._known(job_id)
        await self._request("DELETE", f"/api/queue/{job_id}", job_id=job_id)
        await self._until(lambda: job_id not in self._jobs)

    async def reorder(self, job_ids: Sequence[str]) -> None:
        ids = builtins.list(job_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("reorder: a job id is given twice")
        await self._settle()
        for job_id in ids:
            self._known(job_id)
        await self._request("PUT", "/api/queue/order", {"job_ids": ids})

        def ordered() -> bool:
            present = [j for j in self._order if j in set(ids)]
            return present == [j for j in ids if j in self._jobs]

        await self._until(ordered)

    def log_path(self, job_id: str) -> Path:
        job = self._jobs.get(job_id)
        if job is not None and job.log_path is not None:
            return job.log_path
        return log_file(self.data_dir, job_id)

    # The copy of the queue.

    def _copy(self, job_id: str) -> QueueJob | None:
        job = self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    def _renumber(self) -> None:
        for position, job_id in enumerate(self._order):
            self._jobs[job_id].position = position

    def _known(self, job_id: str) -> None:
        if job_id not in self._jobs:
            raise UnknownJobError(job_id)

    def _ended_or_gone(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        return job is None or job.state in ENDED

    async def _until(self, condition: Callable[[], bool]) -> None:
        """Until ``condition`` holds for the copy; when its event does not come in time, the
        whole queue is read instead."""
        try:
            async with asyncio.timeout(CHANGE_WAIT), self._changed:
                await self._changed.wait_for(
                    lambda: condition() or self.lost is not None or self._closed
                )
        except TimeoutError:
            async with self._mirror:
                await self._refresh_locked()

    async def _notify(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    async def _refresh(self) -> None:
        async with self._mirror:
            await self._refresh_locked()

    async def _refresh_locked(self) -> None:
        """Read the whole queue. With the copy's lock held: every event applied so far was
        sent before this answer, so the answer is newer than all of them."""
        answer = await self._request("GET", "/api/queue")
        jobs = self._jobs_of(answer.get("jobs", []) if isinstance(answer, dict) else [])
        self._jobs = {job.id: job for job in jobs}
        self._order = [job.id for job in jobs]
        await self._notify()

    async def _read(self) -> None:
        ws = self._ws
        assert ws is not None
        reason = "the connection to the Reframe server was lost"
        try:
            async for raw in ws:
                message = json.loads(raw)
                if not isinstance(message, dict) or message.get("type") != "event":
                    continue
                event = EVENT_ADAPTER.validate_python(message.get("event"))
                if event.type in FORWARDED:
                    async with self._mirror:
                        await self._apply(event)
                    self.events.publish(event)
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            pass
        except RemoteError as exc:  # a whole-queue read failed
            if exc.code != "connection.lost":
                reason = str(exc)
        except (ValueError, ValidationError) as exc:
            reason = f"the Reframe server sent what this client cannot read: {exc}"
            log.warning("%s", reason)
        if ws.close_code == SERVER_STOPS:
            reason = "the Reframe server stopped"
        await self._lose(reason)

    async def _apply(self, event: Event) -> None:
        """Change the copy by ``event`` (with the copy's lock held). An event that is older than
        a whole-queue read applied before it moves a job only between states that have not
        ended, and the later events of that job correct it."""
        if isinstance(event, JobStateEvent):
            job = self._jobs.get(event.job_id)
            if job is None or event.state in ENDED:
                # A job of another client, or an end with its output and issues: read all.
                await self._refresh_locked()
                return
            if event.previous is None:
                return  # the add of a job that is known already
            if job.state in ENDED and not (
                event.state is JobState.WAITING and event.previous is job.state
            ):
                return  # older than the read that ended it; only a retry leaves an end
            job.state = event.state
            job.error = event.error
            if event.state is JobState.WAITING:
                job.started_at = job.finished_at = None
                job.progress = None
        elif isinstance(event, JobProgressEvent):
            job = self._jobs.get(event.job_id)
            if job is not None and job.state not in ENDED:
                job.progress = event.progress
        elif isinstance(event, QueueChangedEvent):
            if any(job_id not in self._jobs for job_id in event.job_ids):
                await self._refresh_locked()
                return
            listed = set(event.job_ids)
            for job_id in [j for j in self._jobs if j not in listed]:
                del self._jobs[job_id]
            self._order = builtins.list(event.job_ids)
            self._renumber()
        elif isinstance(event, ResyncEvent):
            await self._refresh_locked()
            return
        elif isinstance(event, PowerCountdownEvent):
            self.power._seen(event)
        await self._notify()

    async def _lose(self, reason: str) -> None:
        """The connection ended: the server's running and paused jobs did not finish."""
        if self._closing:
            return
        self.lost = reason
        error = f"{reason[0].upper()}{reason[1:]} while the job ran."
        for job_id in builtins.list(self._order):
            job = self._jobs[job_id]
            if job.state not in _ACTIVE:
                continue
            previous, job.state, job.error = job.state, JobState.INTERRUPTED, error
            self.events.publish(
                JobStateEvent(job_id=job_id, state=job.state, previous=previous, error=error)
            )
        self.events.close()
        await self._notify()

    # Requests.

    def _dump(self, job: JobSettings) -> Any:
        return json.loads(json_text(job))

    def _jobs_of(self, data: Iterable[Any] | Any) -> _Jobs:
        if not isinstance(data, builtins.list):
            raise RemoteError("the Reframe server's answer is not a job list", code="protocol")
        fields = ("log_path", "output_path")
        shown = [
            {k: _unhide(v, self._folders) if k in fields else v for k, v in item.items()}
            if isinstance(item, dict)
            else item
            for item in data
        ]
        try:
            return _JOBS.validate_python(shown)
        except ValidationError as exc:
            raise RemoteError(
                f"the Reframe server sent a job this client cannot read: {exc}"
            ) from None

    async def _settle(self) -> None:
        """Wait for the background requests (``start``), so later calls see their effect."""
        self._check_open()
        if self._pending:
            await asyncio.wait(builtins.list(self._pending))

    def _check_open(self) -> None:
        if self._closed:
            raise RemoteError("the connection to the Reframe server is closed", code="closed")
        if self.lost is not None:
            raise RemoteError(self.lost, code="connection.lost")

    async def _request(
        self, method: str, path: str, body: Any = None, *, job_id: str | None = None
    ) -> Any:
        content = None if body is None else json_text(body)
        headers = {"Content-Type": "application/json"} if content is not None else None
        try:
            response = await self._http.request(method, path, content=content, headers=headers)
        except httpx.HTTPError as exc:
            raise RemoteError(
                f"the Reframe server cannot be reached: {exc}", code="connection.lost"
            ) from None
        if response.status_code >= 400:
            code, message = _problem(response)
            if code == "queue.unknown_job" and job_id is not None:
                raise UnknownJobError(job_id)
            if code == "queue.job_state":
                raise JobStateError(message)
            raise RemoteError(message, code=code, status=response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return json.loads(response.content)
        except ValueError:
            raise RemoteError("the Reframe server's answer is not JSON", code="protocol") from None
