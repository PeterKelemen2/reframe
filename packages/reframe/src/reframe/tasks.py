"""Background tasks: every long operation is a task with an id. :meth:`TaskManager.start`
returns its :class:`~reframe.models.TaskInfo` at once, and the work reports ``task.progress``
and ``task.done`` on the event bus, in that order. Each event carries a copy of the
``TaskInfo``, so a later change does not alter an event that is already queued. At most
``limit(kind)`` tasks of one kind run at the same time; the others wait in state ``queued``.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, JsonValue

from reframe.events import EventBus
from reframe.models.events import TaskDoneEvent, TaskProgressEvent
from reframe.models.tasks import TaskInfo, TaskState
from reframe.tools import CancelToken

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_LIMITS",
    "FINISHED_STATES",
    "TaskContext",
    "TaskFailed",
    "TaskFn",
    "TaskManager",
]

log = logging.getLogger(__name__)

#: Concurrency limit of a kind that has no entry in ``limits``.
DEFAULT_LIMIT = 2
#: Built-in limits per kind.
DEFAULT_LIMITS: Mapping[str, int] = {
    # Decodes compete for the CPU; encodes even more.
    "bitrate_scan": 2,
    "subtitle_scan": 2,
    "loudness": 2,
    "frames": 2,
    "cropdetect": 1,
    "preview_clip": 1,
    # One download at a time.
    "tools_fetch": 1,
}
FINISHED_STATES = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED})
#: Finished tasks kept for :meth:`TaskManager.get` / :meth:`TaskManager.list`.
DEFAULT_KEEP_FINISHED = 200

#: A task function: gets the context, returns the result.
TaskFn = Callable[["TaskContext"], Awaitable[Any]]


class TaskFailed(Exception):
    """An expected failure inside a task function, with a message for the user. The task ends
    ``failed`` with that message as ``TaskInfo.error``, and no traceback is logged. Any other
    exception is a bug: the task ends ``failed`` too, and the traceback is logged.
    """


def _now() -> datetime:
    return datetime.now(UTC)


class TaskContext:
    """What a task function gets: its id, kind, cancel token and a progress reporter."""

    def __init__(self, manager: TaskManager, task_id: str, kind: str, cancel: CancelToken):
        self._manager = manager
        self.id = task_id
        self.kind = kind
        self.cancel = cancel

    @property
    def cancelled(self) -> bool:
        return self.cancel.cancelled

    def progress(
        self,
        percent: float | None = None,
        message: str | None = None,
        *,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        """Report progress: a percentage, or ``done`` of ``total`` items (then ``percent`` is
        computed). ``percent=None`` without counts means indeterminate. Publishes
        ``task.progress``."""
        if done is not None and total is not None:
            percent = 100.0 if total <= 0 else 100.0 * done / total
        if percent is not None:
            percent = min(max(float(percent), 0.0), 100.0)
        self._manager._report(self.id, percent, message)


class _Gate:
    """A FIFO slot counter for one kind (an ``asyncio.Semaphore`` whose limit can change)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0
        self._waiters: deque[asyncio.Future[None]] = deque()

    async def acquire(self) -> None:
        if self.active < self.limit and not self._waiters:
            self.active += 1
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(future)
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self.release()  # the slot was granted just before the cancel: give it back
            else:
                with contextlib.suppress(ValueError):
                    self._waiters.remove(future)
            raise

    def release(self) -> None:
        self.active -= 1
        self.wake()

    def wake(self) -> None:
        while self._waiters and self.active < self.limit:
            future = self._waiters.popleft()
            if not future.done():
                self.active += 1
                future.set_result(None)


@dataclass
class _Task:
    info: TaskInfo
    cancel: CancelToken
    result_json: Callable[[Any], JsonValue] | None
    handle: asyncio.Task[None] | None = None
    value: Any = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class TaskManager:
    """Starts, tracks and cancels background tasks. Create and use it inside an event loop."""

    def __init__(
        self,
        events: EventBus | None = None,
        *,
        limits: Mapping[str, int] | None = None,
        default_limit: int = DEFAULT_LIMIT,
        keep_finished: int = DEFAULT_KEEP_FINISHED,
    ) -> None:
        self.events = events
        self._limits = {**DEFAULT_LIMITS, **(limits or {})}
        for kind, limit in self._limits.items():
            _check_limit(kind, limit)
        _check_limit("default", default_limit)
        self._default_limit = default_limit
        self._keep_finished = keep_finished
        self._tasks: OrderedDict[str, _Task] = OrderedDict()
        self._gates: dict[str, _Gate] = {}
        self._ids = itertools.count(1)
        self._prefix = os.urandom(3).hex()

    def limit(self, kind: str) -> int:
        return self._limits.get(kind, self._default_limit)

    def set_limit(self, kind: str, limit: int) -> None:
        """Change the concurrency limit of ``kind``; a higher limit starts waiting tasks."""
        _check_limit(kind, limit)
        self._limits[kind] = limit
        gate = self._gates.get(kind)
        if gate is not None:
            gate.limit = limit
            gate.wake()

    def _gate(self, kind: str) -> _Gate:
        gate = self._gates.get(kind)
        if gate is None:
            gate = self._gates[kind] = _Gate(self.limit(kind))
        return gate

    def start(
        self,
        kind: str,
        fn: TaskFn,
        *,
        message: str | None = None,
        result_json: Callable[[Any], JsonValue] | None = None,
    ) -> TaskInfo:
        """Start ``fn`` as a task of ``kind`` and return its info at once (state ``queued``).

        Must be called from a coroutine or callback of the running event loop.
        """
        loop = asyncio.get_running_loop()
        task_id = f"t-{self._prefix}-{next(self._ids)}"
        info = TaskInfo(id=task_id, kind=kind, message=message, created_at=_now())
        task = _Task(info=info, cancel=CancelToken(), result_json=result_json)
        self._tasks[task_id] = task
        self._publish_progress(task)
        task.handle = loop.create_task(self._run(task, fn), name=f"reframe-task-{task_id}")
        task.handle.add_done_callback(lambda _handle: self._finish_unstarted(task))
        self._prune()
        return info.model_copy()

    def get(self, task_id: str) -> TaskInfo | None:
        task = self._tasks.get(task_id)
        return None if task is None else task.info.model_copy()

    def list(self, kind: str | None = None) -> list[TaskInfo]:
        """All known tasks (oldest first), optionally of one kind."""
        return [
            t.info.model_copy() for t in self._tasks.values() if kind is None or t.info.kind == kind
        ]

    def value(self, task_id: str) -> Any:
        """The Python value that the task function returned (``None`` until it is done)."""
        task = self._tasks.get(task_id)
        return None if task is None else task.value

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued or running task. ``False`` if it is unknown or already finished."""
        task = self._tasks.get(task_id)
        if task is None or task.info.state in FINISHED_STATES:
            return False
        task.cancel.cancel()
        if task.handle is not None:
            task.handle.cancel()
        return True

    async def wait(self, task_id: str) -> TaskInfo:
        """Wait until the task has finished; returns its final info.

        :raises KeyError: unknown id.
        """
        task = self._tasks[task_id]
        await task.finished.wait()
        return task.info.model_copy()

    async def close(self) -> None:
        """Cancel every unfinished task and wait for all of them."""
        pending = [t for t in self._tasks.values() if t.info.state not in FINISHED_STATES]
        for task in pending:
            self.cancel(task.info.id)
        handles = [t.handle for t in pending if t.handle is not None]
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)

    async def _run(self, task: _Task, fn: TaskFn) -> None:
        gate = self._gate(task.info.kind)
        acquired = False
        try:
            await gate.acquire()
            acquired = True
            if task.cancel.cancelled:
                raise asyncio.CancelledError
            task.info.state = TaskState.RUNNING
            self._publish_progress(task)
            ctx = TaskContext(self, task.info.id, task.info.kind, task.cancel)
            value = await fn(ctx)
            if task.cancel.cancelled:
                # The function noticed the token and returned early: that is a cancel.
                raise asyncio.CancelledError
            task.value = value
            task.info.result = self._to_json(task, value)
            task.info.state = TaskState.DONE
            if task.info.progress is not None:
                task.info.progress = 100.0
        except asyncio.CancelledError:
            task.cancel.cancel()
            task.info.state = TaskState.CANCELLED
        except TaskFailed as exc:
            log.info("task %s (%s) failed: %s", task.info.id, task.info.kind, exc)
            task.info.state = TaskState.FAILED
            task.info.error = str(exc) or type(exc).__name__
        except Exception as exc:
            log.exception("task %s (%s) failed", task.info.id, task.info.kind)
            task.info.state = TaskState.FAILED
            task.info.error = f"{type(exc).__name__}: {exc}"
        finally:
            if acquired:
                gate.release()
            task.info.finished_at = _now()
            self._publish_done(task)
            task.finished.set()
        # Not re-raising CancelledError: the cancel is recorded in the state, and nobody
        # awaits the asyncio task except close(), which only waits for it to end.

    def _finish_unstarted(self, task: _Task) -> None:
        """A task cancelled before its coroutine ran never enters ``_run``'s ``try``."""
        if task.finished.is_set():
            return
        task.cancel.cancel()
        task.info.state = TaskState.CANCELLED
        task.info.finished_at = _now()
        self._publish_done(task)
        task.finished.set()

    def _to_json(self, task: _Task, value: Any) -> JsonValue:
        if task.result_json is not None:
            return task.result_json(value)
        if isinstance(value, BaseModel):
            dumped: JsonValue = value.model_dump(mode="json")
            return dumped
        if _is_json(value):
            json_value: JsonValue = value
            return json_value
        return None

    def _report(self, task_id: str, percent: float | None, message: str | None) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.info.state is not TaskState.RUNNING:
            return
        task.info.progress = percent
        if message is not None:
            task.info.message = message
        self._publish_progress(task)

    def _publish_progress(self, task: _Task) -> None:
        if self.events is not None:
            self.events.publish(TaskProgressEvent(task=task.info.model_copy()))

    def _publish_done(self, task: _Task) -> None:
        if self.events is not None:
            self.events.publish(TaskDoneEvent(task=task.info.model_copy()))

    def _prune(self) -> None:
        finished = [t for t, task in self._tasks.items() if task.info.state in FINISHED_STATES]
        for task_id in finished[: max(len(finished) - self._keep_finished, 0)]:
            del self._tasks[task_id]


def _check_limit(kind: str, limit: int) -> None:
    if limit < 1:
        raise ValueError(f"concurrency limit of {kind!r} must be at least 1, got {limit}")


def _is_json(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return value == value and value not in (float("inf"), float("-inf"))
    if isinstance(value, list):
        return all(_is_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json(v) for k, v in value.items())
    return False
