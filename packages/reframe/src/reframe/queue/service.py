"""The queue (``Reframe.queue``): :class:`QueueService` keeps the jobs in queue order and saves
them in ``<data dir>/queue.sqlite3``. Two jobs never run at once when they write the same output,
or when one edits in place a file that the other reads or writes; paths are compared as files.
Only the process that holds ``queue.lock`` uses the saved queue, and the end state of a run is
its last event.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import os
import uuid
from collections.abc import Callable, Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from reframe.definitions import Definitions, load_definitions
from reframe.events import EventBus
from reframe.models.events import (
    AppWarningEvent,
    JobProgressEvent,
    JobStateEvent,
    QueueChangedEvent,
    QueueProcessingEvent,
)
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.naming import NamingOptions
from reframe.models.queue import JobProgress, JobState, QueueJob
from reframe.models.settings import AppSettings
from reframe.platform.power import PowerService
from reframe.platform.sleep import SleepInhibitor, create_sleep_inhibitor
from reframe.queue import files
from reframe.queue.clock import Clock, SystemClock
from reframe.queue.errors import JobStateError, UnknownJobError, closed_error, printable
from reframe.queue.lock import LOCK_FILE, LockBackend, StoreLock
from reframe.queue.logs import EVENT_INTERVAL, JobLog, log_file
from reframe.queue.process import resume_tree, suspend_tree
from reframe.queue.runner import (
    ActiveJob,
    CapabilitiesSource,
    JobRunner,
    Outcome,
    SourceProber,
    ToolsSource,
)
from reframe.queue.store import STORE_FILE, QueueStore, row_of
from reframe.queue.watchdog import STALL_AFTER, STEP_TIME_LIMIT, TICK
from reframe.queue.whendone import WhenDoneActions
from reframe.validation import FileSystemView, LocalFileSystem

__all__ = ["ACTIVE", "ENDED", "OUTPUT_CLAIMED", "QueueService"]

log = logging.getLogger(__name__)

#: States in which a job has ended (until it is retried).
ENDED = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
ACTIVE = frozenset({JobState.RUNNING, JobState.PAUSED})
_RETRY = frozenset({JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
#: States in which a job's output and source are claimed: no other job may write them.
_CLAIMING = frozenset({JobState.WAITING, JobState.RUNNING, JobState.PAUSED})
#: The issue of a job whose output another job writes or reads.
OUTPUT_CLAIMED = "queue.output_claimed"


#: ``list[...]`` for annotations inside ``QueueService``, whose ``list`` method hides the builtin.
_Jobs = list[QueueJob]
_Ids = list[str]
_Actives = list[ActiveJob]
_Tasks = list[asyncio.Task[None]]


def _path_key(path: str | os.PathLike[str]) -> files.FileKey:
    """The :class:`~reframe.queue.files.FileKey` of ``path``. Blocking: never call it on the
    event loop."""
    return files.file_key(path)


def _source_key(job: QueueJob) -> files.FileKey:
    return _path_key(job.settings.source.path)


def _output_key(job: QueueJob) -> files.FileKey | None:
    """The file the job writes: its output path, or its source for an in-place edit."""
    if job.settings.output.edit_in_place:
        return _source_key(job)
    path = job.settings.output.path
    if path is None:
        return None
    return _path_key(path)


@dataclass(frozen=True, slots=True)
class _Keys:
    """A job's file keys, taken in a worker thread when the job is added, retried or restored.
    Kept in memory only, not saved."""

    source: files.FileKey
    output: files.FileKey | None


def _written_key(path: str | os.PathLike[str]) -> files.FileKey:
    """``path`` as written, made absolute. No file-system call, so links are not resolved."""
    return files.FileKey(os.path.abspath(path))


def _job_keys(
    job: QueueJob, key: Callable[[str | os.PathLike[str]], files.FileKey] = _path_key
) -> _Keys:
    """``job``'s keys. Blocking with the default ``key``: never call it on the event loop."""
    source = key(job.settings.source.path)
    if job.settings.output.edit_in_place:
        return _Keys(source, source)
    path = job.settings.output.path
    return _Keys(source, None if path is None else key(path))


def _conflicts(job: QueueJob, active: Iterable[ActiveJob], keys: _Keys | None = None) -> bool:
    """``job`` must wait for another active job that writes its output, edits its source in
    place, or reads or writes the source of an in-place edit. Given ``keys``, this makes no
    file-system call; otherwise the keys are taken now, blocking."""
    if keys is None:
        keys = _job_keys(job)
    output, source = keys.output, keys.source
    in_place = job.settings.output.edit_in_place
    same = files.same_key
    for other in active:
        if output is not None and same(output, other.output_key):
            return True  # the same output is being written by another job
        if other.in_place and same(source, other.source_key):
            return True  # its source is being edited in place
        if in_place and (same(source, other.source_key) or same(source, other.output_key)):
            return True  # the source to edit is being read or written
    return False


def _claim_issue(job: QueueJob, other: QueueJob, *, as_source: bool) -> ValidationIssue:
    target = (
        job.settings.source.path if job.settings.output.edit_in_place else job.settings.output.path
    )
    name = Path(target).name if target is not None else ""
    other_source = Path(other.settings.source.path).name
    if as_source:
        what = f"the source of a job that is {other.state.value} in the queue ({other_source})"
    else:
        what = f"the output of a job that is {other.state.value} in the queue ({other_source})"
    return ValidationIssue(
        severity=Severity.ERROR,
        code=OUTPUT_CLAIMED,
        path="output.path",
        message=printable(
            f"{name} is also {what}: this job would replace that file. Cancel or remove the "
            "other job first, or choose another output name."
        ),
    )


def _restored_error(job: QueueJob) -> str:
    """The error of a job that was running or paused when Reframe stopped. A crash or a hard
    exit may have stopped an in-place edit while it wrote the source, so the error says what
    that can mean for the file."""
    error = "Reframe stopped while the job was running."
    plan = job.plan
    edits = plan is not None and plan.job_type == "metadata_edit" and bool(plan.steps)
    if job.settings.output.edit_in_place and edits:
        name = Path(job.settings.source.path).name
        error += (
            f" If Reframe was writing the header of {name} at that moment, the file holds "
            "either all its old values or all the new ones, unless the computer lost power "
            "during the write: then check that the file still opens."
        )
    return error


class QueueService:
    """The queue of encode jobs.

    :param events: the event bus.
    :param settings: returns the current settings, read each time a decision needs them.
    :param naming: the effective naming options of a job (its preset's), or ``None`` for
        Settings → Output.
    :param power: the when-done power actions; ``None``: they are reported as not available
        (``queue.when_done_unavailable``).
    :param clock: the clocks (tests replace them).
    :param fs: the file-system view of validation and of the collision rename.
    :param stall_after: seconds without progress, output or CPU use before an FFmpeg step is
        stopped (``None``: never).
    :param step_time_limit: seconds a tool step other than FFmpeg may take.
    :param lock_backend: the OS lock of ``queue.lock``; tests replace it.
    """

    def __init__(
        self,
        events: EventBus,
        settings: Callable[[], AppSettings],
        *,
        data_dir: Path,
        tools: ToolsSource,
        capabilities: CapabilitiesSource,
        sources: SourceProber,
        naming: Callable[[JobSettings], NamingOptions | None] | None = None,
        inhibitor: SleepInhibitor | None = None,
        power: PowerService | None = None,
        definitions: Definitions | None = None,
        clock: Clock | None = None,
        fs: FileSystemView | None = None,
        stall_after: float | None = STALL_AFTER,
        step_time_limit: float | None = STEP_TIME_LIMIT,
        watchdog_tick: float = TICK,
        log_interval: float = EVENT_INTERVAL,
        lock_backend: LockBackend | None = None,
    ) -> None:
        self._events = events
        self._settings = settings
        self._data_dir = data_dir
        self._clock = clock or SystemClock()
        self._fs: FileSystemView = fs or LocalFileSystem()
        self._inhibitor = inhibitor if inhibitor is not None else create_sleep_inhibitor(events)
        self._store = QueueStore(data_dir / STORE_FILE, now=self._clock.now)
        self._owner = StoreLock(data_dir / LOCK_FILE, lock_backend)
        self._runner = JobRunner(
            events=events,
            settings=settings,
            tools=tools,
            capabilities=capabilities,
            sources=sources,
            clock=self._clock,
            fs=self._fs,
            definitions=definitions if definitions is not None else load_definitions(),
            naming=naming or (lambda job: None),
            persist=self._save,
            stall_after=stall_after,
            step_time_limit=step_time_limit,
            tick=watchdog_tick,
            log_interval=log_interval,
            resumed=self._resumed_for_stop,
        )
        self._jobs: dict[str, QueueJob] = {}
        self._active: dict[str, ActiveJob] = {}
        self._keys: dict[str, _Keys] = {}
        """Each waiting or running job's file keys, taken off the event loop."""
        self._keying: dict[str, asyncio.Task[None]] = {}
        """The jobs whose keys are being taken in the background (restored jobs)."""
        self._unchecked: set[str] = set()
        """Restored jobs that were not added or retried since: their claims were never
        checked against each other (a store of an older Reframe may hold two with one output)."""
        self._processing = False
        self._only: dict[str, None] | None = None
        """``start(job_ids=…)``: only these jobs are taken, in the order named (``None``: every
        waiting job). ``None`` whenever the runner is not processing."""
        self._closed = False
        self._opened = False
        self._store_busy = False
        self._lock = asyncio.Lock()
        self._changed = asyncio.Condition()
        self._background: set[asyncio.Task[None]] = set()
        self._when = WhenDoneActions(events, power)
        """The batch counts, the job notifications and the when-done action."""

    @property
    def owns_store(self) -> bool:
        """This process holds ``queue.lock`` and keeps its jobs in the saved queue. ``False``
        before the queue's first use, when another process owns the store, when
        ``queue.lock`` cannot be used (``queue.unreadable``), and after :meth:`close`."""
        return self._owner.held

    @property
    def store_busy(self) -> bool:
        """The queue's first use found ``queue.lock`` held by another process
        (``queue.store_busy``). ``False`` before the first use, for the owner, and when the
        lock cannot be used at all."""
        return self._store_busy

    @property
    def processing(self) -> bool:
        """The runner takes waiting jobs: from :meth:`start` until :meth:`stop`, :meth:`close`,
        or the end of every job that ``start(job_ids=…)`` named. Running state, not saved."""
        return self._processing

    @property
    def only(self) -> _Ids | None:
        """The jobs that ``start(job_ids=…)`` named, the only ones the runner takes (an id may
        name a job that has left the queue since); ``None``: every waiting job, or not
        processing."""
        return None if self._only is None else builtins.list(self._only)

    @property
    def busy(self) -> bool:
        """A job is running or paused, or the runner will still take a waiting job (a
        :meth:`start` targets it). A waiting job that no ``start`` targets does not count."""
        if self._active:
            return True
        return (
            self._processing
            and not self._closed
            and any(self._eligible(job) for job in self._jobs.values())
        )

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob:
        """Add a job (validated at once). A job with errors is added in state ``failed``
        with its issues. ``position``: 0 = first; ``None`` = last."""
        self._check_open()
        self._ensure_open()
        settings = job.model_copy(deep=True)
        issues = await self._runner.check(settings)
        self._check_open()
        errors = [issue for issue in issues if issue.severity is Severity.ERROR]
        now = self._clock.now()
        job_id = str(uuid.uuid4())
        error = None
        if errors:
            more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
            error = printable(f"The job has errors: {errors[0].message}{more}")
        queued = QueueJob(
            id=job_id,
            position=0,
            state=JobState.FAILED if errors else JobState.WAITING,
            settings=settings,
            issues=issues,
            created_at=now,
            finished_at=now if errors else None,
            log_path=log_file(self._data_dir, job_id),
            error=error,
        )
        keys = None if errors else await self._take_keys(queued)  # a failed job: at its retry
        self._check_open()
        async with self._lock:
            # Under the lock: two adds of one output at the same time must not both pass.
            claim = None if keys is None else self._claim(queued, keys)
            if claim is not None:
                keys = None
                queued.state = JobState.FAILED
                queued.issues = [*queued.issues, claim]
                queued.finished_at = now
                queued.error = error = printable(f"The job has errors: {claim.message}")
            order = self._ordered()
            index = len(order) if position is None else max(0, min(position, len(order)))
            order.insert(index, queued)
            self._jobs[job_id] = queued
            if keys is not None:
                self._keys[job_id] = keys
            changed = self._renumber(order)
            await self._save_many([queued, *(j for j in changed if j is not queued)])
        self._events.publish(
            JobStateEvent(job_id=job_id, state=queued.state, previous=None, error=error)
        )
        self._publish_order()
        await self._notify()
        self._schedule()
        return queued.model_copy(deep=True)

    def list(self) -> _Jobs:
        """Every job, in queue order (copies)."""
        self._ensure_open()
        return [job.model_copy(deep=True) for job in self._ordered()]

    def get(self, job_id: str) -> QueueJob | None:
        self._ensure_open()
        job = self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    async def remove(self, job_id: str) -> None:
        """Remove a job that is not running or paused (``JobStateError`` otherwise); its log
        file is removed too."""
        self._check_open()
        self._ensure_open()
        async with self._lock:
            job = self._job(job_id)
            if job.state in ACTIVE or job_id in self._active:
                raise JobStateError(f"job {job_id} is {job.state.value}: cancel it first")
            del self._jobs[job_id]
            self._keys.pop(job_id, None)
            changed = self._renumber(self._ordered())
            await self._call(lambda: self._store.delete(job_id))
            await self._save_many(changed)
        log_path = job.log_path or log_file(self._data_dir, job_id)
        await asyncio.to_thread(files.remove_files, [log_path])
        self._publish_order()
        self._idle_when_drained()
        await self._notify()

    async def reorder(self, job_ids: Sequence[str]) -> None:
        """Put the given jobs in this order. They take the places the same jobs had (so the
        whole list, or any part of it, can be given); the other jobs do not move."""
        self._check_open()
        self._ensure_open()
        ids = list(job_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("reorder: a job id is given twice")
        async with self._lock:
            for job_id in ids:
                self._job(job_id)
            order = self._ordered()
            slots = [index for index, job in enumerate(order) if job.id in set(ids)]
            for slot, job_id in zip(slots, ids, strict=True):
                order[slot] = self._jobs[job_id]
            changed = self._renumber(order)
            await self._save_many(changed)
        if changed:
            self._publish_order()
        self._schedule()

    async def retry(self, job_id: str) -> QueueJob:
        """``failed`` / ``cancelled`` / ``interrupted`` → ``waiting`` (a waiting job is
        returned as it is; ``JobStateError`` for a running, paused or done job)."""
        self._check_open()
        self._ensure_open()
        job = self._job(job_id)
        if job.state is JobState.WAITING:
            return job.model_copy(deep=True)
        if job.state not in _RETRY:
            raise JobStateError(f"job {job_id} is {job.state.value}: it cannot be retried")
        # Taken again: a link or a file may have changed since the job was added.
        keys = await self._take_keys(job)
        self._check_open()
        async with self._lock:
            job = self._job(job_id)  # removed meanwhile: UnknownJobError
            if job.state not in _RETRY:  # a retry at the same time took it first
                return job.model_copy(deep=True)
            claim = self._claim(job, keys)
            kept = [issue for issue in job.issues if issue.code != OUTPUT_CLAIMED]
            if claim is not None:
                job.issues = [*kept, claim]
                job.finished_at = self._clock.now()
                error = f"The job has errors: {claim.message}"
                await self._set_state(job, JobState.FAILED, error=error)
                return job.model_copy(deep=True)
            job.issues = kept
            self._keys[job_id] = keys
            self._unchecked.discard(job_id)
            job.started_at = job.finished_at = None
            job.progress = None
            await self._set_state(job, JobState.WAITING, error=None)
        self._schedule()
        return job.model_copy(deep=True)

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        """Start taking waiting jobs, in queue order, ``parallel_jobs`` at a time.

        ``job_ids`` takes only these jobs while they are waiting, so other waiting jobs stay as
        they are (a CLI run must not start jobs that another front end left in the shared store).
        When none of them is waiting or running any more, the runner goes idle, as after
        :meth:`stop`. A call while the runner is already taking jobs never narrows what it takes.
        Running state only: it is not saved, so a restored queue is idle.
        """
        self._check_open()
        self._ensure_open()
        only: dict[str, None] | None = None
        if job_ids is not None:
            named = dict.fromkeys(job_ids)
            for job_id in named:
                self._job(job_id)
            if not self._processing:
                only = named
            elif self._only is not None:
                only = self._only | named
        self._set_processing(True, only, "start")
        self._schedule()

    async def stop(self) -> None:
        """Take no new jobs; the running ones go on (running state only, not saved)."""
        self._ensure_open()
        self._set_processing(False, None, "stop")

    async def pause(self, job_id: str | None = None) -> None:
        """Pause a running job (``None``: every running job). Its process tree is suspended;
        a job between two steps does not start the next one. Other states: nothing happens.
        Pause and resume of one job run one at a time (a per-job lock)."""
        self._check_open()
        self._ensure_open()
        for active in self._targets(job_id):
            async with active.control:
                job = self._jobs.get(active.job_id)
                if (
                    job is None
                    or active.ended
                    or active.paused
                    or active.token.cancelled
                    or job.state is not JobState.RUNNING
                ):
                    continue
                active.paused = True
                active.resumed.clear()
                if active.process is not None:
                    await asyncio.to_thread(suspend_tree, active.process)
                if active.tracker is not None:
                    active.tracker.pause()
                await self._set_state(job, JobState.PAUSED)
                await self._release_inhibit(active)

    async def resume(self, job_id: str | None = None) -> None:
        """Resume a paused job (``None``: every paused job)."""
        self._check_open()
        self._ensure_open()
        for active in self._targets(job_id):
            async with active.control:
                job = self._jobs.get(active.job_id)
                if job is None or active.ended or not active.paused or active.token.cancelled:
                    continue
                active.paused = False
                if active.tracker is not None:
                    active.tracker.resume()
                if active.process is not None:
                    await asyncio.to_thread(resume_tree, active.process)
                active.resumed.set()
                await self._set_state(job, JobState.RUNNING)
                await self._hold_inhibit(active, job)

    async def cancel(self, job_id: str | None = None) -> None:
        """Cancel a job: a waiting one is marked ``cancelled``; a running or paused one has
        its process tree killed and ends ``cancelled`` with its ``.part`` file removed — except a
        running ``header_edit`` step, which is let finish first (a worker thread cannot be
        stopped) before the job ends ``cancelled``.
        ``None``: every job that has not ended (running, paused and waiting). Returns when
        the cancelled jobs have ended."""
        self._check_open()
        self._ensure_open()
        if job_id is not None:
            jobs = [self._job(job_id)]
        else:
            jobs = [job for job in self._ordered() if job.state not in ENDED]
        tasks: _Tasks = []
        for job in jobs:
            active = self._active.get(job.id)
            if active is not None:
                active.stop("cancel")
                if active.task is not None:
                    tasks.append(active.task)
            elif job.state is JobState.WAITING:
                job.finished_at = self._clock.now()
                await self._set_state(job, JobState.CANCELLED)
        self._idle_when_drained()
        if tasks:
            await asyncio.wait(tasks)

    async def wait(self, job_ids: Sequence[str] | None = None) -> _Jobs:
        """Wait until the jobs have ended (``None``: every job in the queue now). A waiting
        job ends only while the queue runs (:meth:`start`). A job removed meanwhile is left
        out of the result."""
        self._ensure_open()
        ids = [job.id for job in self._ordered()] if job_ids is None else list(job_ids)
        for job_id in ids:
            self._job(job_id)

        def ended() -> bool:
            return self._closed or all(
                job_id not in self._jobs
                or (self._jobs[job_id].state in ENDED and job_id not in self._active)
                for job_id in ids
            )

        async with self._changed:
            await self._changed.wait_for(ended)
        return [self._jobs[job_id].model_copy(deep=True) for job_id in ids if job_id in self._jobs]

    def log_path(self, job_id: str) -> Path:
        """``<data dir>/logs/<job id>.log`` (it may not exist yet)."""
        self._ensure_open()
        job = self._jobs.get(job_id)
        if job is not None and job.log_path is not None:
            return job.log_path
        return log_file(self._data_dir, job_id)

    async def close(self) -> None:
        """No new jobs; a when-done countdown that the queue started is cancelled (its action
        never runs); running jobs are stopped (``interrupted``, ``.part`` removed; a running
        ``header_edit`` step is let finish first, as in :meth:`cancel`), the sleep inhibit
        is freed and the store is flushed. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._processing = False  # no event: the queue's users are closing too
        self._only = None
        self._when.close()  # before any await: no when-done action runs after this
        tasks: _Tasks = []
        for active in builtins.list(self._active.values()):
            active.stop("close")
            if active.task is not None:
                tasks.append(active.task)
        if tasks:
            await asyncio.wait(tasks)
        background = [task for task in self._background if not task.done()]
        for task in background:
            task.cancel()
        if background:
            await asyncio.wait(background)
        await self._inhibitor.close()
        if self._opened:
            await asyncio.to_thread(self._store.close)
        self._owner.release()
        await self._notify()

    def _ensure_open(self) -> None:
        """Open the store at the queue's first use, not at ``Reframe.create()``: a command that
        never uses the queue never touches it.

        The process that holds the lock loads the store. Running and paused jobs become
        interrupted, and their leftover files are removed in the background. A process that
        cannot take the lock keeps its jobs in a private store in memory and sends one
        ``app.warning``. Blocking, once: the lock is taken without waiting, and the store is a
        small local file.
        """
        if self._opened or self._closed:
            return
        self._opened = True
        try:
            owner = self._owner.acquire()
        except OSError as exc:
            self._store.use_memory()
            self._events.publish(
                AppWarningEvent(
                    code="queue.unreadable",
                    message="The saved queue cannot be used. The jobs of this process run here "
                    "and are not kept after it ends.",
                    detail=printable(f"{self._owner.path}: {exc}"),
                )
            )
            return
        if not owner.owned:
            self._store_busy = True
            self._store.use_memory()
            who = f" (pid {owner.owner})" if owner.owner is not None else ""
            self._events.publish(
                AppWarningEvent(
                    code="queue.store_busy",
                    message=f"Another Reframe process{who} is using the saved queue. The jobs "
                    "of this process run here and are not kept after it ends.",
                    detail=printable(str(self._store.path)),
                )
            )
            return
        loaded = self._store.submit(self._store.load).result()
        for warning in loaded.warnings:
            self._events.publish(warning)
        now = self._clock.now()
        interrupted: builtins.list[tuple[QueueJob, JobState]] = []
        for job in loaded.jobs:
            if job.state in ACTIVE:
                interrupted.append((job, job.state))
                job.state = JobState.INTERRUPTED
                job.error = _restored_error(job)
                job.finished_at = job.finished_at or now
            self._jobs[job.id] = job
        self._unchecked.update(self._jobs)
        changed = self._renumber(self._ordered())
        to_save = {job.id: job for job in changed}
        to_save.update((job.id, job) for job, _ in interrupted)
        if to_save:
            rows = [row_of(job) for job in to_save.values()]
            self._store.submit(lambda: self._store.upsert(rows))  # in order, before any later write
        for job, previous in interrupted:
            self._events.publish(
                JobStateEvent(job_id=job.id, state=job.state, previous=previous, error=job.error)
            )
        leftovers = [job for job, _ in interrupted if job.plan is not None]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # used outside a loop: clean up now; keys when the queue runs
            if leftovers:
                self._remove_leftovers(leftovers)
            return
        for job in self._ordered():
            if job.state is JobState.WAITING:
                self._want_keys(job)  # in the background, so start() finds them
        if not leftovers:
            return
        task = loop.create_task(self._clean_leftovers(leftovers), name="reframe-queue-leftovers")
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _clean_leftovers(self, jobs: Iterable[QueueJob]) -> None:
        await asyncio.to_thread(self._remove_leftovers, jobs)

    def _remove_leftovers(self, jobs: Iterable[QueueJob]) -> None:
        """The plan files and temporary files of interrupted jobs, and their ``.part`` file
        by the partial-file policy (as for a failure); never a job's source."""
        delete = self._settings().output.partial_file == "delete"
        for job in jobs:
            plan = job.plan
            assert plan is not None
            if plan.job_type == "metadata_edit":
                continue  # it edits its source: no .part, plan or temporary file (0034)
            paths = [f.path for f in plan.files] + list(plan.temp_files)
            if delete:
                paths.append(plan.output_tmp)
            for problem in files.remove_files(paths, keep=Path(job.settings.source.path)):
                log.warning("queue restore: %s", problem)

    def _eligible(self, job: QueueJob) -> bool:
        """A waiting job that the runner may take now."""
        return (
            job.state is JobState.WAITING
            and job.id not in self._active
            and (self._only is None or job.id in self._only)
        )

    def _schedule(self) -> bool:
        """Start jobs in free slots. ``True`` when the jobs of ``start(job_ids=…)`` have all
        ended and the runner went idle."""
        if self._closed or not self._processing:
            return False
        if self._idle_when_drained():
            return True
        limit = self._settings().queue.parallel_jobs
        for job in self._ordered():
            if len(self._active) >= limit:
                break
            if not self._eligible(job):
                continue
            keys = self._keys.get(job.id)
            if keys is None:  # a restored job: its keys are being taken off the event loop
                self._want_keys(job)
                continue
            if _conflicts(job, self._active.values(), keys):  # no file-system call
                continue  # see _conflicts; the next job in the queue may run instead
            active = ActiveJob(
                job_id=job.id,
                output_key=keys.output,
                source_key=keys.source,
                in_place=job.settings.output.edit_in_place,
            )
            self._active[job.id] = active
            self._when.work_started()  # new work: the queue's when-done countdown stops
            active.task = asyncio.get_running_loop().create_task(
                self._run(job, active), name=f"reframe-queue-job-{job.id}"
            )
        return False

    def _idle_when_drained(self) -> bool:
        """Go idle, as after :meth:`stop`, once no job that ``start(job_ids=…)`` named is
        waiting, running or paused; whether it went idle now."""
        if self._closed or not self._processing or self._only is None:
            return False
        if any(
            job_id in self._active or (job_id in self._jobs and self._eligible(self._jobs[job_id]))
            for job_id in self._only
        ):
            return False
        self._set_processing(False, None, "idle")
        return True

    def _set_processing(
        self,
        processing: bool,
        only: dict[str, None] | None,
        reason: Literal["start", "stop", "idle"],
    ) -> None:
        """Change what the runner takes; a change is published, in order with the job events."""
        if (processing, only) == (self._processing, self._only):
            return
        self._processing, self._only = processing, only
        self._events.publish(
            QueueProcessingEvent(
                processing=processing,
                only=None if only is None else builtins.list(only),
                reason=reason,
            )
        )

    def _claim(
        self, job: QueueJob, keys: _Keys, *, skip: AbstractSet[str] = frozenset()
    ) -> ValidationIssue | None:
        """The issue when ``job``'s output is the output or the source of another waiting,
        running or paused job (not one in ``skip``). No file-system call: a restored job whose
        keys are still being taken is compared by its paths as written."""
        output = keys.output
        if output is None:
            return None
        for other in self._ordered():
            if other.id == job.id or other.state not in _CLAIMING or other.id in skip:
                continue
            theirs = self._keys.get(other.id) or _job_keys(other, _written_key)
            if files.same_key(output, theirs.output):
                return _claim_issue(job, other, as_source=False)
            if files.same_key(output, theirs.source):
                return _claim_issue(job, other, as_source=True)
        return None

    async def _take_keys(self, job: QueueJob) -> _Keys:
        """``job``'s file keys, taken in a worker thread: a disk or a network share that does
        not answer delays only this call, never the event loop."""
        return await asyncio.to_thread(_job_keys, job)

    def _want_keys(self, job: QueueJob) -> None:
        """Take ``job``'s keys in the background (a restored waiting job); the queue looks for
        jobs to start again when they are there. Until then the job is passed over, so a share
        that does not answer holds back only its own job."""
        if self._closed or job.id in self._keys or job.id in self._keying:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # used outside a loop: the next look for jobs asks again
            return
        task = loop.create_task(self._keys_in_background(job), name=f"reframe-queue-keys-{job.id}")
        self._keying[job.id] = task
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _keys_in_background(self, job: QueueJob) -> None:
        try:
            keys = await self._take_keys(job)
        finally:
            self._keying.pop(job.id, None)
        if self._closed or self._jobs.get(job.id) is not job or job.id in self._keys:
            return  # closed or removed meanwhile, or a retry took newer keys and checked them
        # The jobs added or retried meanwhile were checked against its paths as written; a
        # link or another spelling of the same file shows only now.
        claim = None
        if job.state is JobState.WAITING:
            claim = self._claim(job, keys, skip=self._unchecked)
        if claim is None:
            self._keys[job.id] = keys
            self._schedule()
            return
        job.issues = [*job.issues, claim]
        job.finished_at = self._clock.now()
        await self._set_state(job, JobState.FAILED, error=f"The job has errors: {claim.message}")
        self._idle_when_drained()

    async def _run(self, job: QueueJob, active: ActiveJob) -> None:
        joblog = JobLog(
            job.log_path or log_file(self._data_dir, job.id),
            job.id,
            self._events,
            interval=self._runner.log_interval,
        )
        outcome: Outcome | None = None
        if active.token.cancelled and active.stop_reason == "close":
            # Closed before it started: it never ran, so it stays waiting.
            self._active.pop(job.id, None)
            await self._notify()
            return
        try:
            if active.token.cancelled:  # cancelled before it started
                outcome = Outcome(JobState.CANCELLED, stop_reason=active.stop_reason)
            else:
                job.started_at = self._clock.now()
                job.finished_at = None
                job.progress = JobProgress()
                await self._set_state(job, JobState.RUNNING, error=None)
                self._events.publish(JobProgressEvent(job_id=job.id, progress=job.progress))
                joblog.open(self._header(job))
                async with active.control:
                    if not active.paused:  # a pause that came first released nothing yet
                        await self._hold_inhibit(active, job)
                outcome = await self._runner.run(job, active, joblog)
        except Exception as exc:  # a bug: the job fails, the queue goes on
            log.exception("queue job %s failed with an internal error", job.id)
            outcome = Outcome(JobState.FAILED, error=f"Internal error: {type(exc).__name__}: {exc}")
        finally:
            if outcome is None:  # the task itself was cancelled (never by the queue)
                # During an in-place step, what happened to the source.
                error = active.end_note or "The job was stopped."
                outcome = Outcome(JobState.INTERRUPTED, error=error)
            with contextlib.suppress(Exception):
                await self._finish(job, active, joblog, outcome)

    def _header(self, job: QueueJob) -> str:
        stamp = self._clock.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        output = job.settings.output.path
        return (
            f"=== Reframe job {job.id}: run started {stamp} ===\n"
            f"Source: {job.settings.source.path}\n"
            f"Output: {output if output is not None else '(not set)'}"
        )

    async def _finish(
        self, job: QueueJob, active: ActiveJob, joblog: JobLog, outcome: Outcome
    ) -> None:
        try:
            await self._cleanup(job, outcome, joblog)
            if outcome.issues is not None:
                job.issues = outcome.issues
            if outcome.output_path is not None:
                job.output_path = outcome.output_path
            if outcome.progress is not None:
                job.progress = outcome.progress
                self._events.publish(JobProgressEvent(job_id=job.id, progress=outcome.progress))
            elapsed = ""
            if job.started_at is not None:
                seconds = (self._clock.now() - job.started_at).total_seconds()
                elapsed = f" after {seconds:.1f} s"
            ending = f"Job {outcome.state.value}{elapsed}"
            if outcome.error:
                ending += f": {outcome.error}"
            joblog.note(ending)
        finally:
            # Before the last log batch: the end state stays the last event of the run.
            self._job_notification(job, outcome)
            joblog.close()
            async with active.control:  # after a pause or resume that is under way
                active.ended = True
                await self._release_inhibit(active)
            job.finished_at = self._clock.now()
            await self._set_state(job, outcome.state, error=outcome.error)
            # No await from here on: the slot, the count and the when-done check change
            # together, so the when-done action is taken before a wait() for the job returns.
            self._active.pop(job.id, None)
            self._keys.pop(job.id, None)  # a retry takes them again
            self._when.count(outcome.state)
            try:
                drained = self._schedule()
                self._when_done(outcome.state, drained=drained)
            finally:
                await self._notify()  # never skipped: wait() must see the job end

    async def _cleanup(self, job: QueueJob, outcome: Outcome, joblog: JobLog) -> None:
        plan = outcome.plan
        if plan is None:
            return
        paths = [f.path for f in plan.files] + list(plan.temp_files)
        remove_part = False
        if outcome.state in (JobState.CANCELLED, JobState.INTERRUPTED):
            remove_part = True
        elif outcome.state is JobState.FAILED and not outcome.keep_part:
            remove_part = self._settings().output.partial_file == "delete"
        if remove_part:
            paths.append(plan.output_tmp)
        elif outcome.state is not JobState.DONE and await asyncio.to_thread(plan.output_tmp.exists):
            joblog.note(f"The partial output is kept: {plan.output_tmp}")
        problems = await asyncio.to_thread(
            files.remove_files, paths, keep=Path(job.settings.source.path)
        )
        for problem in problems:
            joblog.note(f"Clean-up: {problem}")

    def _job_notification(self, job: QueueJob, outcome: Outcome) -> None:
        """The notification of a run that ended on its own (``settings.queue.notifications``);
        never raises (it is called while the run ends)."""
        try:
            self._when.job_ended(
                job,
                outcome.state,
                error=outcome.error,
                output=outcome.output_path,
                notifications=self._settings().queue.notifications,
            )
        except Exception:  # a bug: the run still ends
            log.exception("queue job %s: the notification failed", job.id)

    def _when_done(self, last: JobState, *, drained: bool = False) -> None:
        """When the queue emptied, run the when-done action once for the jobs that ended
        since it last emptied, if the last one ended on its own (done or failed; not when the
        user cancelled the last job or Reframe closed). See :mod:`reframe.queue.whendone`.

        "Emptied": nothing runs, and nothing is left that the runner would take: no waiting
        job at all, or (``drained``) none of the jobs of ``start(job_ids=…)``."""
        if self._closed or self._active:
            return
        if self._processing:
            if any(self._eligible(job) for job in self._jobs.values()):
                return
        elif not drained and any(job.state is JobState.WAITING for job in self._jobs.values()):
            return  # stopped with jobs left: the queue did not empty
        self._when.emptied(last, self._settings().queue.when_done)

    async def _hold_inhibit(self, active: ActiveJob, job: QueueJob) -> None:
        """Take one count for the job (called with ``active.control`` held). The job holds it
        only once ``acquire`` returned: an ``acquire`` that is cancelled undoes its own count,
        and the job must then not release one."""
        if active.holds_inhibit or not self._settings().queue.sleep_inhibit:
            return
        name = Path(job.settings.source.path).name
        await self._inhibitor.acquire(f"Reframe is encoding {name}")
        active.holds_inhibit = True

    async def _release_inhibit(self, active: ActiveJob) -> None:
        """Give the job's count back (called with ``active.control`` held)."""
        if not active.holds_inhibit:
            return
        active.holds_inhibit = False
        await self._inhibitor.release()

    async def _resumed_for_stop(self, job: QueueJob, active: ActiveJob) -> None:
        """A paused job's ``header_edit`` step goes on writing while a cancel or ``close()``
        lets it finish (called by the runner with ``active.control`` held): the job is
        ``running`` again until it ends, and holds its sleep inhibit, as after :meth:`resume`."""
        await self._set_state(job, JobState.RUNNING)
        await self._hold_inhibit(active, job)

    def _check_open(self) -> None:
        if self._closed:
            raise closed_error()

    def _job(self, job_id: str) -> QueueJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise UnknownJobError(job_id)
        return job

    def _targets(self, job_id: str | None) -> _Actives:
        if job_id is None:
            return [self._active[job.id] for job in self._ordered() if job.id in self._active]
        self._job(job_id)
        active = self._active.get(job_id)
        return [] if active is None else [active]

    def _ordered(self) -> _Jobs:
        return sorted(self._jobs.values(), key=lambda job: (job.position, job.created_at))

    @staticmethod
    def _renumber(order: Sequence[QueueJob]) -> _Jobs:
        """Set positions 0, 1, … in ``order``; returns the jobs whose position changed."""
        changed: _Jobs = []
        for index, job in enumerate(order):
            if job.position != index:
                job.position = index
                changed.append(job)
        return changed

    def _publish_order(self) -> None:
        self._events.publish(QueueChangedEvent(job_ids=[job.id for job in self._ordered()]))

    async def _set_state(
        self, job: QueueJob, state: JobState, *, error: str | object | None = ...
    ) -> None:
        previous = job.state
        job.state = state
        if error is not ...:
            job.error = printable(error) if isinstance(error, str) else None
        await self._save(job)
        self._events.publish(
            JobStateEvent(job_id=job.id, state=state, previous=previous, error=job.error)
        )
        await self._notify()

    async def _save(self, job: QueueJob) -> None:
        await self._save_many([job])

    async def _save_many(self, jobs: Iterable[QueueJob]) -> None:
        rows = [row_of(job) for job in jobs]
        if rows:
            await self._call(lambda: self._store.upsert(rows))

    async def _call(self, call: Callable[[], None]) -> None:
        """Run a store call on the store's thread; publish its warnings."""
        try:
            await asyncio.wrap_future(self._store.submit(call))
        except RuntimeError:  # the store is closed (a job that ended after close())
            log.debug("queue store closed: a change was not saved")
        while self._store.warnings:
            self._events.publish(self._store.warnings.pop(0))

    async def _notify(self) -> None:
        async with self._changed:
            self._changed.notify_all()
