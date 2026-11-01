"""The queue of a server that owns it, over its REST routes and its event WebSocket.

:class:`RemoteQueue` keeps a copy of the jobs so that the synchronous ``get`` and ``list`` of the
queue contract can answer from it. The event stream changes the copy in the order the server
sent the events; an add's answer and a whole-queue read give what the events do not carry. A
call that changes a job returns once the copy shows the change. The jobs it adds are attached to
its event connection: when the connection ends without :meth:`close`'s ``detach``, the server
cancels them.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from reframe import paths
from reframe.events import EventBus
from reframe.models.events import (
    Event,
    JobProgressEvent,
    JobStateEvent,
    PowerCountdownEvent,
    QueueChangedEvent,
    QueueProcessingEvent,
    ResyncEvent,
)
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.queue import JobState, QueueJob
from reframe.models.text import json_text
from reframe.queue.errors import JobStateError, QueueError, UnknownJobError
from reframe.queue.logs import log_file
from reframe.remote.owner import Owner, usable_token

__all__ = ["OwnerStopping", "RemoteError", "RemotePower", "RemoteQueue"]

log = logging.getLogger(__name__)
_WS_LOG = logging.getLogger("websockets.client")

ENDED = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
_ACTIVE = frozenset({JobState.RUNNING, JobState.PAUSED})
_Forwarded = (
    JobStateEvent
    | JobProgressEvent
    | QueueChangedEvent
    | QueueProcessingEvent
    | PowerCountdownEvent
    | ResyncEvent
)
_MODELS: dict[str, type[_Forwarded]] = {
    "job.state": JobStateEvent,
    "job.progress": JobProgressEvent,
    "queue.changed": QueueChangedEvent,
    "queue.processing": QueueProcessingEvent,
    "power.countdown": PowerCountdownEvent,
    "resync": ResyncEvent,
}
#: The events that the queue's users follow; the others stay with the server.
FORWARDED = frozenset(_MODELS)
#: An event of these types that cannot be read leaves the copy behind: read the whole queue.
_COPIED = frozenset({"job.state", "queue.changed", "queue.processing", "resync"})
OPEN_TIMEOUT = 10.0
CHANGE_WAIT = 10.0
"""Seconds a call waits for the event of its change before it reads the whole queue."""
SERVER_STOPS = 1012
UNAUTHORIZED = 4401

_JOBS: TypeAdapter[list[QueueJob]] = TypeAdapter(list[QueueJob])
_ISSUES: TypeAdapter[list[ValidationIssue]] = TypeAdapter(list[ValidationIssue])
_Jobs = builtins.list[QueueJob]
_LABELS = re.compile(r"<(?:data|config|cache)>")


class _NoFrameLog(logging.LoggerAdapter[logging.Logger]):
    """websockets' client logger without its DEBUG lines: they show every frame sent, the
    token's too."""

    def isEnabledFor(self, level: int) -> bool:
        return level > logging.DEBUG and super().isEnabledFor(level)


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


def _reason(exc: BaseException, token: str) -> str:
    """``exc``'s text for a message, without the token; its type when it has no text."""
    text = str(exc).replace(token, "<token>") if token else str(exc)
    return text or type(exc).__name__


def _unhide(value: Any, folders: dict[str, Path]) -> Any:
    """``value`` with the server's ``<data>``, ``<config>`` and ``<cache>`` (it hides its folders
    in every text of an answer) as this machine's folders."""
    if isinstance(value, str):
        if "<" not in value:
            return value
        return _LABELS.sub(lambda match: str(folders[match.group(0)]), value)
    if isinstance(value, builtins.list):
        return [_unhide(item, folders) for item in value]
    if isinstance(value, dict):
        return {_unhide(key, folders): _unhide(item, folders) for key, item in value.items()}
    return value


def _processing_of(answer: Any) -> tuple[bool, builtins.list[str] | None]:
    """``processing`` and ``only`` of a queue snapshot; not processing when the owner does not
    say."""
    if not isinstance(answer, dict) or answer.get("processing") is not True:
        return False, None
    only = answer.get("only")
    return True, [str(job_id) for job_id in only] if isinstance(only, builtins.list) else None


def _decode(raw: str | bytes) -> tuple[str, _Forwarded | None]:
    """The type and the event of a message that carries an event this queue uses (the event is
    ``None`` when it cannot be read); ``("", None)`` for any other message."""
    try:
        message = json.loads(raw)
    except ValueError:
        log.debug("the Reframe server sent a message that is not JSON")
        return "", None
    data = message.get("event") if isinstance(message, dict) else None
    if (
        not isinstance(message, dict)
        or message.get("type") != "event"
        or not isinstance(data, dict)
    ):
        return "", None
    kind = data.get("type")
    if not isinstance(kind, str) or kind not in _MODELS:
        log.debug("skipped a %r event", kind)
        return "", None
    model = _MODELS[kind]
    # A field of a newer server is one this client does not use.
    known = {key: value for key, value in data.items() if key in model.model_fields}
    try:
        event = model.model_validate(known)
    except ValidationError as exc:
        log.debug("a %s event cannot be read: %s", kind, exc.errors(include_input=False))
        return kind, None
    return kind, event


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
    events after the copy has taken them; it closes when the connection is lost.

    ``start`` sends its request in the background. When the server refuses it, nothing starts,
    and the next awaited call raises the refusal (``UnknownJobError``, ``JobStateError`` or
    ``RemoteError``); ``close`` only logs it."""

    def __init__(
        self,
        owner: Owner,
        *,
        data_dir: Path,
        config_dir: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        if not usable_token(owner.endpoint.token):
            raise RemoteError(
                "the token of the Reframe server cannot be sent in an HTTP header", code="auth"
            )
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
        """Every job id in queue order, also of pending jobs."""
        self._seen: set[str] = set()
        """Jobs the event stream has shown: a ``queue.changed`` without one of them removed it."""
        self._awaited: set[str] = set()
        """Jobs of this client's adds that the event stream has not shown yet: a
        ``queue.changed`` without one of them is older than its add."""
        self._pending: set[str] = set()
        """Jobs the event stream has shown while this client's adds were under way, and whose
        answer (or whole-queue read) the copy waits for."""
        self._stirred: set[str] = set()
        """Pending jobs that the event stream changed after their add."""
        self._gone: set[str] = set()
        """Pending jobs the event stream removed: an add's answer does not bring one back."""
        self._adding = 0
        self._retries: dict[str, int] = {}
        """Per job, the retries the copy took (events from an end)."""
        self._processing = False
        self._only: builtins.list[str] | None = None
        self._mirror = asyncio.Lock()
        """Held while the copy changes: an event, an add's answer, or a whole-queue read with
        its request."""
        self._changed = asyncio.Condition()
        self._pending_starts: set[asyncio.Task[None]] = set()
        self._start_error: QueueError | None = None
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
        token = self.owner.endpoint.token
        try:
            self._ws = await connect(
                url, open_timeout=OPEN_TIMEOUT, max_size=None, logger=_NoFrameLog(_WS_LOG)
            )
            await self._ws.send(json_text({"type": "auth", "token": token}))
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
                f"the Reframe server at {self.owner.url} cannot be reached: {_reason(exc, token)}",
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
        cancels them. Safe to call more than once; never raises a refused ``start``."""
        if self._closed:
            return
        self._closing = True
        try:
            if self._pending_starts:
                await asyncio.wait(builtins.list(self._pending_starts))
            if self._start_error is not None:
                log.warning("the queue was not started: %s", self._start_error)
                self._start_error = None
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
        """The owner's when-done setting (``"nothing"`` when its settings do not say)."""
        answer = await self._request("GET", "/api/settings")
        queue = answer.get("queue") if isinstance(answer, dict) else None
        value = queue.get("when_done") if isinstance(queue, dict) else None
        return value if isinstance(value, str) else "nothing"

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob:
        """Add ``job``, attached to this connection."""
        await self._settle()
        body = {"jobs": [self._dump(job)], "position": position, "attach": self.client_id}
        self._adding += 1
        try:
            [added] = self._jobs_of(await self._request("POST", "/api/queue", body))
        except BaseException:
            self._adding -= 1
            raise
        async with self._mirror:
            self._adding -= 1
            read = self._take(added, position)
            if not self._adding:
                self._gone.clear()
                read = read or bool(self._pending)  # jobs of another front end
            if read:
                try:
                    await self._refresh_locked()
                except RemoteError as exc:  # the job is added; the next event reads again
                    log.debug("the queue cannot be read: %s", exc)
        await self._notify()
        return self._copy(added.id) or added

    def list(self) -> _Jobs:
        return [self._jobs[j].model_copy(deep=True) for j in self._order if j in self._jobs]

    @property
    def processing(self) -> bool:
        """The owner's queue takes waiting jobs, as the copy shows it (``False`` when the owner
        does not say)."""
        return self._processing

    @property
    def only(self) -> builtins.list[str] | None:
        """The only jobs the owner's queue takes, as the copy shows it; ``None``: every waiting
        job, or not processing."""
        return None if self._only is None else builtins.list(self._only)

    async def refresh(self) -> None:
        """Read the whole queue now: the copy then shows every call that the owner answered
        before, also one whose events are still on their way."""
        self._check_open()
        await self._refresh()

    def get(self, job_id: str) -> QueueJob | None:
        return self._copy(job_id)

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        """Start the queue (``job_ids``: only these jobs). The request is sent in the
        background; the next awaited call waits for it and raises its refusal."""
        self._check_open()
        ids = None if job_ids is None else builtins.list(job_ids)
        for job_id in ids or ():
            self._known(job_id)
        task = asyncio.get_running_loop().create_task(self._send_start(ids))
        self._pending_starts.add(task)
        task.add_done_callback(self._pending_starts.discard)

    async def _send_start(self, ids: builtins.list[str] | None) -> None:
        body = None if ids is None else {"job_ids": ids}
        try:
            await self._request("POST", "/api/queue/start", body)
        except QueueError as exc:
            if isinstance(exc, RemoteError) and exc.code == "queue.unknown_job" and ids:
                # The problem's title names the job.
                exc = UnknownJobError(next((j for j in ids if j in str(exc)), ids[0]))
            if self._start_error is None:
                self._start_error = exc

    async def wait(self, job_ids: Sequence[str] | None = None) -> _Jobs:
        """Until the jobs have ended or left the queue, or the connection has ended (then the
        copy says how they were last seen)."""
        await self._started()
        ids = self._ids() if job_ids is None else builtins.list(job_ids)
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
            targets = [j for j in self._ids() if self._jobs[j].state not in ENDED]
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
        ids = self._ids() if job_id is None else [job_id]
        if job_id is not None:
            self._known(job_id)
        targets = [j for j in ids if self._jobs[j].state is before]
        path = f"/api/queue/{action}" if job_id is None else f"/api/queue/{job_id}/{action}"
        await self._request("POST", path, job_id=job_id)
        await self._until(
            lambda: all(j not in self._jobs or self._jobs[j].state is not before for j in targets)
        )

    async def retry(self, job_id: str) -> QueueJob:
        """Retry an ended job; returns the server's answer once the copy shows the retry."""
        await self._settle()
        self._known(job_id)
        retries = self._retries.get(job_id, 0)
        answer = await self._request("POST", f"/api/queue/{job_id}/retry", job_id=job_id)
        [job] = self._jobs_of([answer])
        waits = job.state is JobState.WAITING

        def taken() -> bool:
            current = self._jobs.get(job_id)
            return (
                current is None
                or self._retries.get(job_id, 0) > retries
                or (waits and current.state not in ENDED)
            )

        await self._until(taken)
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
            present = [j for j in self._ids() if j in set(ids)]
            return present == [j for j in ids if j in self._jobs]

        await self._until(ordered)

    def log_path(self, job_id: str) -> Path:
        job = self._jobs.get(job_id)
        if job is not None and job.log_path is not None:
            return job.log_path
        return log_file(self.data_dir, job_id)

    # The copy of the queue.

    def _ids(self) -> builtins.list[str]:
        return [j for j in self._order if j in self._jobs]

    def _copy(self, job_id: str) -> QueueJob | None:
        job = self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    def _renumber(self) -> None:
        for position, job_id in enumerate(self._order):
            job = self._jobs.get(job_id)
            if job is not None:
                job.position = position

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
        self._processing, self._only = _processing_of(answer)
        self._jobs = {job.id: job for job in jobs}
        self._order = [job.id for job in jobs]
        self._seen &= self._jobs.keys()
        self._awaited &= self._jobs.keys()
        self._retries = {j: n for j, n in self._retries.items() if j in self._jobs}
        self._pending.clear()
        self._stirred.clear()
        await self._notify()

    def _take(self, job: QueueJob, position: int | None) -> bool:
        """Put the answer of this client's add into the copy, unless the copy has the job
        already (newer) or the event stream removed it. Whether the copy must be read: the
        stream changed the job before its answer came."""
        job_id = job.id
        if job_id in self._gone:
            return False
        if job_id in self._jobs:
            if job_id not in self._seen:
                self._awaited.add(job_id)
            return False
        self._jobs[job_id] = job
        if job_id in self._pending:
            self._pending.discard(job_id)
        else:
            self._awaited.add(job_id)
        if job_id not in self._order:
            index = len(self._order) if position is None else min(position, len(self._order))
            self._order.insert(index, job_id)
        self._renumber()
        if job_id in self._stirred:
            self._stirred.discard(job_id)
            return True
        return False

    def _saw(self, job_id: str) -> None:
        self._seen.add(job_id)
        self._awaited.discard(job_id)

    def _drop(self, job_id: str) -> None:
        """The event stream removed ``job_id``."""
        self._jobs.pop(job_id, None)
        with contextlib.suppress(ValueError):
            self._order.remove(job_id)
        for ids in (self._seen, self._awaited, self._pending, self._stirred):
            ids.discard(job_id)
        self._retries.pop(job_id, None)
        if self._adding:
            self._gone.add(job_id)

    async def _read(self) -> None:
        ws = self._ws
        assert ws is not None
        reason = "the connection to the Reframe server was lost"
        try:
            async for raw in ws:
                kind, event = _decode(raw)
                if event is None:
                    if kind in _COPIED:
                        await self._refresh()
                    continue
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
        except Exception:
            log.exception("the events of the Reframe server cannot be followed")
            reason = "the events of the Reframe server cannot be followed"
        if ws.close_code == SERVER_STOPS:
            reason = "the Reframe server stopped"
        await self._lose(reason)

    async def _apply(self, event: Event) -> None:
        """Change the copy by ``event`` (with the copy's lock held). An event that is older than
        a whole-queue read applied before it can show a job as it was before the read; the
        job's later events correct it. Only a retry moves a job out of an end."""
        if self._pending and not self._adding:  # an add that failed left them
            await self._refresh_locked()
        if isinstance(event, JobStateEvent):
            await self._apply_state(event)
        elif isinstance(event, JobProgressEvent):
            job = self._jobs.get(event.job_id)
            if job is not None:
                self._saw(job.id)
                if job.state not in ENDED:
                    job.progress = event.progress
        elif isinstance(event, QueueChangedEvent):
            await self._apply_order(event.job_ids)
        elif isinstance(event, QueueProcessingEvent):
            self._processing, self._only = event.processing, event.only
        elif isinstance(event, ResyncEvent):
            await self._refresh_locked()
        elif isinstance(event, PowerCountdownEvent):
            self.power._seen(event)
        await self._notify()

    async def _apply_state(self, event: JobStateEvent) -> None:
        job_id, state, previous = event.job_id, event.state, event.previous
        job = self._jobs.get(job_id)
        if job is None:
            if job_id in self._pending:
                self._stirred.add(job_id)
            elif previous is None and self._adding:  # maybe this client's add: its answer comes
                self._pending.add(job_id)
                self._seen.add(job_id)
            else:  # a job of another front end: the copy needs its settings
                await self._refresh_locked()
            return
        self._saw(job_id)
        if previous is None:
            return  # the add of a job the copy has
        if job.state in ENDED and previous is not job.state:
            return  # older than what the copy holds: only a retry leaves an end
        if previous in ENDED:
            self._retries[job_id] = self._retries.get(job_id, 0) + 1
        if job.state in ENDED:
            if state is not JobState.WAITING:
                await self._refresh_locked()  # a retry that failed: its issues changed
                return
        elif state in ENDED:
            if state is not JobState.CANCELLED or previous is not JobState.WAITING:
                await self._refresh_locked()  # a run's end: its output, issues and plan
                return
            job.finished_at = datetime.now(UTC)  # this client's clock, close to the server's
        job.state = state
        job.error = event.error
        if state is JobState.WAITING:
            job.started_at = job.finished_at = None
            job.progress = None

    async def _apply_order(self, job_ids: builtins.list[str]) -> None:
        listed = set(job_ids)
        unknown = [j for j in job_ids if j not in self._jobs and j not in self._pending]
        if unknown:
            if not self._adding:
                await self._refresh_locked()  # jobs of another front end
                return
            self._pending.update(unknown)
        unlisted = [j for j in {*self._order, *self._pending} if j not in listed]
        if any(j not in self._seen and j not in self._awaited for j in unlisted):
            # A job of a whole-queue read that the stream has not shown: removed, or added after
            # this event was sent.
            await self._refresh_locked()
            return
        kept = [(i, j) for i, j in enumerate(self._order) if j in self._awaited and j not in listed]
        for j in unlisted:
            if j in self._seen:
                self._drop(j)
        for j in listed:
            self._saw(j)
        self._order = builtins.list(job_ids)
        for index, j in kept:
            self._order.insert(min(index, len(self._order)), j)
        self._renumber()

    async def _lose(self, reason: str) -> None:
        """The connection ended: the server's running and paused jobs did not finish."""
        if self._closing:
            return
        self.lost = reason
        error = f"{reason[0].upper()}{reason[1:]} while the job ran."
        for job_id in self._ids():
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
        shown = [
            {k: v if k == "settings" else _unhide(v, self._folders) for k, v in item.items()}
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

    async def _started(self) -> None:
        """Wait for the background ``start`` requests, then raise a refusal of one."""
        if self._pending_starts:
            await asyncio.wait(builtins.list(self._pending_starts))
        error, self._start_error = self._start_error, None
        if error is not None:
            raise error

    async def _settle(self) -> None:
        """Before a call: the connection is open, and the background ``start`` requests have
        ended, so the call sees their effect."""
        self._check_open()
        await self._started()

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
                f"the Reframe server cannot be reached: {_reason(exc, self.owner.endpoint.token)}",
                code="connection.lost",
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
