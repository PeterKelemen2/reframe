"""A ``QueueService`` in memory, for tests that must not run FFmpeg.

It writes the partial file ``<name>.part.<ext>`` next to the output, and renames or removes it
when the job ends.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from reframe.command import partial_path
from reframe.events import EventBus
from reframe.models import (
    JobProgress,
    JobProgressEvent,
    JobSettings,
    JobState,
    JobStateEvent,
    QueueChangedEvent,
    QueueJob,
    Severity,
    ValidationIssue,
)
from reframe.validation import LocalFileSystem, next_free_path

Behaviour = Literal["done", "fail", "hang"]
#: ``list`` is a method of the queue, so the class body names the list types here.
_Ids = list[str]
_Jobs = list[QueueJob]
FINAL = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})


class FakeQueue:
    """The ``QueueService`` contract, in memory."""

    def __init__(
        self,
        events: EventBus,
        *,
        log_dir: Path,
        validate: Callable[[JobSettings], Awaitable[list[ValidationIssue]]] | None = None,
        behaviour: Callable[[JobSettings], Behaviour] = lambda _job: "done",
        on_running: Callable[[QueueJob], None] | None = None,
        parallel: int = 1,
        step_delay: float = 0.005,
    ) -> None:
        self.events = events
        self.log_dir = log_dir
        self._validate = validate
        self._behaviour = behaviour
        self._on_running = on_running
        self.parallel = parallel
        self.step_delay = step_delay
        self._jobs: dict[str, QueueJob] = {}
        self._order: _Ids = []
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._loop: asyncio.Task[None] | None = None
        self._kick = asyncio.Event()
        self._changed = asyncio.Condition()
        self._next = 0
        self.started = False
        self.only: set[str] | None = None
        self.calls: _Ids = []
        """Method calls, in order: ``add``, ``start``, ``stop``, ``cancel <id>``, …"""

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob:
        self.calls.append("add")
        self._next += 1
        job_id = f"job-{self._next}"
        issues = await self._validate(job) if self._validate is not None else []
        failed = any(issue.severity is Severity.ERROR for issue in issues)
        queued = QueueJob(
            id=job_id,
            position=0,
            state=JobState.FAILED if failed else JobState.WAITING,
            settings=job,
            issues=issues,
            created_at=datetime.now(UTC),
            log_path=self.log_path(job_id),
            error="The job has validation errors." if failed else None,
        )
        self._jobs[job_id] = queued
        index = len(self._order) if position is None else min(position, len(self._order))
        self._order.insert(index, job_id)
        self._renumber()
        self.events.publish(QueueChangedEvent(job_ids=list(self._order)))
        self._kick.set()
        return queued.model_copy(deep=True)

    def list(self) -> _Jobs:
        return [self._jobs[j].model_copy(deep=True) for j in self._order]

    def get(self, job_id: str) -> QueueJob | None:
        job = self._jobs.get(job_id)
        return job.model_copy(deep=True) if job is not None else None

    async def remove(self, job_id: str) -> None:
        self.calls.append(f"remove {job_id}")
        if self._jobs[job_id].state is JobState.RUNNING:
            raise ValueError("a running job cannot be removed")
        self._order.remove(job_id)
        del self._jobs[job_id]
        self._renumber()
        self.events.publish(QueueChangedEvent(job_ids=list(self._order)))

    async def reorder(self, job_ids: Sequence[str]) -> None:
        self.calls.append("reorder")
        self._order = [*job_ids, *(j for j in self._order if j not in job_ids)]
        self._renumber()
        self.events.publish(QueueChangedEvent(job_ids=list(self._order)))

    async def retry(self, job_id: str) -> QueueJob:
        self.calls.append(f"retry {job_id}")
        await self._set(job_id, JobState.WAITING)
        self._kick.set()
        return self._jobs[job_id].model_copy(deep=True)

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        """``job_ids``: take only these jobs."""
        self.calls.append("start" if job_ids is None else f"start {' '.join(job_ids)}")
        self.only = None if job_ids is None else set(job_ids)
        self.started = True
        if self._loop is None or self._loop.done():
            self._loop = asyncio.get_running_loop().create_task(self._run_loop())
        self._kick.set()

    async def stop(self) -> None:
        self.calls.append("stop")
        self.started = False

    async def pause(self, job_id: str | None = None) -> None:
        self.calls.append(f"pause {job_id}")
        for jid in self._targets(job_id, {JobState.RUNNING}):
            await self._set(jid, JobState.PAUSED)

    async def resume(self, job_id: str | None = None) -> None:
        self.calls.append(f"resume {job_id}")
        for jid in self._targets(job_id, {JobState.PAUSED}):
            await self._set(jid, JobState.RUNNING)

    async def cancel(self, job_id: str | None = None) -> None:
        self.calls.append(f"cancel {job_id}")
        states = {JobState.RUNNING, JobState.PAUSED}
        if job_id is not None:
            states.add(JobState.WAITING)
        for jid in self._targets(job_id, states):
            task = self._tasks.get(jid)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task})
            elif self._jobs[jid].state is JobState.WAITING:
                await self._set(jid, JobState.CANCELLED)

    async def wait(self, job_ids: Sequence[str] | None = None) -> _Jobs:
        ids = list(job_ids) if job_ids is not None else list(self._order)
        async with self._changed:
            await self._changed.wait_for(lambda: all(self._jobs[j].state in FINAL for j in ids))
        return [self._jobs[j].model_copy(deep=True) for j in ids]

    def log_path(self, job_id: str) -> Path:
        return self.log_dir / f"{job_id}.log"

    async def close(self) -> None:
        self.calls.append("close")
        self.started = False
        for task in list(self._tasks.values()):
            task.cancel()
        if self._loop is not None:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop
        if self._tasks:
            await asyncio.wait(list(self._tasks.values()))

    def _targets(self, job_id: str | None, states: set[JobState]) -> _Ids:
        ids = [job_id] if job_id is not None else list(self._order)
        return [j for j in ids if self._jobs[j].state in states]

    def _renumber(self) -> None:
        for index, job_id in enumerate(self._order):
            self._jobs[job_id] = self._jobs[job_id].model_copy(update={"position": index})

    async def _set(self, job_id: str, state: JobState, **changes: object) -> None:
        old = self._jobs[job_id]
        self._jobs[job_id] = old.model_copy(update={"state": state, **changes})
        error = changes.get("error")
        self.events.publish(
            JobStateEvent(
                job_id=job_id,
                state=state,
                previous=old.state,
                error=error if isinstance(error, str) else None,
            )
        )
        async with self._changed:
            self._changed.notify_all()

    async def _run_loop(self) -> None:
        while True:
            await self._kick.wait()
            self._kick.clear()
            while self.started:
                running = [t for t in self._tasks.values() if not t.done()]
                waiting = [
                    j
                    for j in self._order
                    if self._jobs[j].state is JobState.WAITING
                    and (self.only is None or j in self.only)
                ]
                if not waiting or len(running) >= self.parallel:
                    break
                job_id = waiting[0]
                await self._set(job_id, JobState.RUNNING, started_at=datetime.now(UTC))
                self._tasks[job_id] = asyncio.get_running_loop().create_task(self._run(job_id))

    async def _progress(self, job_id: str, percent: float) -> None:
        left = (100.0 - percent) / 100.0 * 8.0
        progress = JobProgress(
            percent=percent,
            fps=48.0,
            speed=2.0,
            eta=left,
            output_size=int(percent * 10_000),
        )
        self._jobs[job_id] = self._jobs[job_id].model_copy(update={"progress": progress})
        self.events.publish(JobProgressEvent(job_id=job_id, progress=progress))
        await asyncio.sleep(self.step_delay)

    async def _run(self, job_id: str) -> None:
        job = self._jobs[job_id]
        final = job.settings.output.path
        assert final is not None
        part = partial_path(final)
        try:
            part.write_bytes(b"partial output")
            if self._on_running is not None:
                self._on_running(job.model_copy(deep=True))
            behaviour = self._behaviour(job.settings)
            if behaviour == "hang":
                await self._progress(job_id, 10.0)
                await asyncio.Event().wait()
            if behaviour == "fail":
                await self._progress(job_id, 30.0)
                part.unlink(missing_ok=True)
                await self._set(
                    job_id,
                    JobState.FAILED,
                    error="ffmpeg exited with code 1: Conversion failed!",
                    finished_at=datetime.now(UTC),
                )
                return
            for percent in (25.0, 50.0, 75.0, 100.0):
                await self._progress(job_id, percent)
            target = final if not final.exists() else next_free_path(final, LocalFileSystem())
            part.replace(target)
            await self._set(
                job_id, JobState.DONE, output_path=target, finished_at=datetime.now(UTC)
            )
        except asyncio.CancelledError:
            part.unlink(missing_ok=True)
            await self._set(job_id, JobState.CANCELLED, finished_at=datetime.now(UTC))
        finally:
            self._kick.set()
