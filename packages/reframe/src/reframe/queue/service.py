"""The queue (C-11): ``Reframe.queue``, a :class:`QueueService`.

Jobs live in memory in queue order and are saved in ``<data dir>/queue.sqlite3``
(:mod:`reframe.queue.store`). :meth:`QueueService.start` lets the runner take ``waiting``
jobs, ``settings.queue.parallel_jobs`` at a time (read again each time a slot frees);
:mod:`reframe.queue.runner` runs one job.

**States** (03 §Queue)::

    add ──► waiting ──► running ◄──► paused
       │        │          │            │
       │        │          ├──► done    │
       └► failed│          ├──► failed ◄┤
                │          ├──► cancelled ◄┤
                └► cancelled  └──► interrupted (Reframe closed or stopped)

    retry: failed | cancelled | interrupted ──► waiting

- :meth:`~QueueService.add` validates at once: a job with errors is added as ``failed`` with
  its issues (it can be retried after its cause is fixed, for example a missing encoder).
- A paused job keeps its slot (its process is suspended, not ended).
- Two jobs with the same output path never run at the same time (both would write the same
  ``.part`` file): the second waits and the next job in the queue runs instead.

**Events**, in this order (02 §Events; ``job.progress`` and ``job.log`` may be coalesced or
dropped by a slow subscriber, the others never):

- ``add``: ``job.state`` (``previous=None``, ``waiting`` or ``failed``), ``queue.changed``.
- a run: ``job.state`` (→ ``running``), ``job.progress`` (0 %), then ``job.progress`` and
  ``job.log`` while it runs; ``job.state`` ``running`` ↔ ``paused``; at the end the last
  ``job.progress`` (100 % when done), the last ``job.log`` batch, then ``job.state`` with the
  end state and ``error``. The ``.part`` file, the plan files and the temporary files are
  already handled when the end state is published.
- ``remove`` and ``reorder``: ``queue.changed``. ``retry``: ``job.state`` (→ ``waiting``).
- When the queue empties after jobs ran: the when-done action (a ``notification`` event, or
  an ``app.warning`` for the power actions that M2 does not have).

**Clean-up** when a run ends: ``EncodePlan.files`` and ``temp_files`` are always removed;
the ``.part`` file is removed on cancel and on close, and on failure when
``settings.output.partial_file`` is ``delete`` (kept on ``keep``, and kept when the encode is
complete but its name is taken under the ``ask`` policy).

**One owner** (decision 0027). The store is opened at the queue's first use, not by
``Reframe.create()``. The process that takes the lock ``<data dir>/queue.lock`` owns it;
another process keeps its jobs in a private store in memory (``app.warning``
``queue.store_busy``) and never touches the saved jobs or their files.

**Restart.** When the owner opens the store, jobs that were ``running`` or ``paused`` become
``interrupted``, and their leftover files are cleaned up in the background (the ``.part`` file
by the partial-file policy, as for a failure; never the source). :meth:`~QueueService.close`
stops running jobs as ``interrupted`` too (their ``.part`` file is removed, as on cancel) and
frees the lock. Every choice beyond the plan is in decision 0016.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import os
import uuid
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from reframe.definitions import Definitions, load_definitions
from reframe.events import EventBus
from reframe.models.events import (
    AppWarningEvent,
    JobProgressEvent,
    JobStateEvent,
    NotificationEvent,
    QueueChangedEvent,
)
from reframe.models.issues import Severity
from reframe.models.job import JobSettings
from reframe.models.naming import NamingOptions
from reframe.models.queue import JobProgress, JobState, QueueJob
from reframe.models.settings import AppSettings
from reframe.platform.sleep import SleepInhibitor, create_sleep_inhibitor
from reframe.queue import files
from reframe.queue.clock import Clock, SystemClock
from reframe.queue.errors import JobStateError, UnknownJobError, printable
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
from reframe.validation import FileSystemView, LocalFileSystem

__all__ = ["ENDED", "QueueService"]

log = logging.getLogger(__name__)

#: States in which a job has ended (until it is retried).
ENDED = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
_ACTIVE = frozenset({JobState.RUNNING, JobState.PAUSED})
_RETRY = frozenset({JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
_POWER_LABELS = {"quit": "Quit Reframe", "sleep": "Sleep", "shutdown": "Shut down"}


#: ``list[...]`` for annotations inside ``QueueService``, whose ``list`` method hides the builtin.
_Jobs = list[QueueJob]
_Actives = list[ActiveJob]
_Tasks = list[asyncio.Task[None]]


def _closed_error() -> Exception:
    from reframe.service import ReframeClosedError  # reframe.service imports this package

    return ReframeClosedError()


def _output_key(job: QueueJob) -> str | None:
    path = job.settings.output.path
    if path is None:
        return None
    return os.path.normcase(os.path.abspath(path))


class QueueService:
    """The queue of encode jobs (C-11). See the module doc.

    :param events: the event bus (``job.*``, ``queue.changed``, ``notification``,
        ``app.warning``).
    :param settings: returns the current settings; read each time a decision needs them
        (``queue.parallel_jobs``, ``when_done``, ``sleep_inhibit``, ``output.collision``,
        ``output.partial_file``).
    :param data_dir: ``<data dir>``: the store ``queue.sqlite3`` and the logs ``logs/``.
    :param tools: tool discovery (``status()``).
    :param capabilities: encoder detection (``snapshot``, ``wait()``).
    :param sources: probing (``probe(path, use_cache=, cancel=)``).
    :param naming: the effective naming options of a job (its preset's), or ``None`` for
        Settings → Output.
    :param inhibitor: the sleep inhibitor (default: :func:`create_sleep_inhibitor`).
    :param clock: the clocks (tests replace them).
    :param fs: the file-system view of validation and of the collision rename.
    :param stall_after: seconds without progress, output or CPU use before an FFmpeg step is
        stopped (``None``: never).
    :param step_time_limit: seconds a short step (``mkvpropedit``) may take.
    :param watchdog_tick: seconds between two watchdog checks.
    :param log_interval: seconds between two ``job.log`` events of a job.
    :param lock_backend: the OS lock of ``queue.lock`` (default: ``flock`` or
        ``msvcrt.locking``; tests replace it).
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
        )
        self._jobs: dict[str, QueueJob] = {}
        self._active: dict[str, ActiveJob] = {}
        self._processing = False
        self._only: set[str] | None = None
        """``start(job_ids=…)``: only these jobs are taken (``None``: every waiting job)."""
        self._closed = False
        self._opened = False
        self._lock = asyncio.Lock()
        self._changed = asyncio.Condition()
        self._background: set[asyncio.Task[None]] = set()
        self._batch_done = 0
        self._batch_failed = 0

    # ------------------------------------------------------------------ the contract

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
        async with self._lock:
            order = self._ordered()
            index = len(order) if position is None else max(0, min(position, len(order)))
            order.insert(index, queued)
            self._jobs[job_id] = queued
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
            if job.state in _ACTIVE or job_id in self._active:
                raise JobStateError(f"job {job_id} is {job.state.value}: cancel it first")
            del self._jobs[job_id]
            changed = self._renumber(self._ordered())
            await self._call(lambda: self._store.delete(job_id))
            await self._save_many(changed)
        log_path = job.log_path or log_file(self._data_dir, job_id)
        await asyncio.to_thread(files.remove_files, [log_path])
        self._publish_order()
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
        job.started_at = job.finished_at = None
        job.progress = None
        await self._set_state(job, JobState.WAITING, error=None)
        self._schedule()
        return job.model_copy(deep=True)

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        """Start taking waiting jobs, in queue order, ``parallel_jobs`` at a time.

        ``job_ids`` (keyword-only, an addition to the contract): take only these jobs, while
        they are waiting; other waiting jobs stay as they are (a CLI run must not start jobs
        that another front end left in the shared store). When none of them is waiting or
        running any more, the runner goes idle, as after :meth:`stop`. A call while the
        runner is already taking jobs never narrows what it takes: ``start()`` without ids
        takes every job, and ids are added to those of an earlier ``start(job_ids=…)``.
        Running state only: it is not saved, a restored queue is idle.
        """
        self._check_open()
        self._ensure_open()
        if job_ids is not None:
            ids = builtins.list(job_ids)
            for job_id in ids:
                self._job(job_id)
            if not self._processing:
                self._only = set(ids)
            elif self._only is not None:
                self._only.update(ids)
        else:
            self._only = None
        self._processing = True
        self._schedule()

    async def stop(self) -> None:
        """Take no new jobs; the running ones go on (running state only, not saved)."""
        self._ensure_open()
        self._processing = False
        self._only = None

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
        its process tree killed and ends ``cancelled`` with its ``.part`` file removed.
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
        """No new jobs; running jobs are stopped (``interrupted``, ``.part`` removed), the
        sleep inhibit is freed and the store is flushed. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._processing = False
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

    # ------------------------------------------------------------------ restore

    def _ensure_open(self) -> None:
        """Open the store at the queue's first use (decision 0027). ``Reframe.create()`` does
        not: a command that never uses the queue never touches it.

        The process that takes the exclusive lock on ``<data dir>/queue.lock`` owns the saved
        queue: it loads the store (``running`` and ``paused`` jobs become ``interrupted``;
        their leftover files are removed in the background) and runs its jobs. A process
        that cannot take the lock keeps its jobs in a private store in memory and sends one
        ``app.warning`` (``queue.store_busy``). Blocking, once: the lock is taken without
        waiting and the store is a small local file.
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
            if job.state in _ACTIVE:
                interrupted.append((job, job.state))
                job.state = JobState.INTERRUPTED
                job.error = "Reframe stopped while the job was running."
                job.finished_at = job.finished_at or now
            self._jobs[job.id] = job
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
        if not leftovers:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # used outside a loop: clean up now
            self._remove_leftovers(leftovers)
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
            paths = [f.path for f in plan.files] + list(plan.temp_files)
            if delete:
                paths.append(plan.output_tmp)
            for problem in files.remove_files(paths, keep=Path(job.settings.source.path)):
                log.warning("queue restore: %s", problem)

    # ------------------------------------------------------------------ scheduling

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
        if self._only is not None and not any(
            job_id in self._active or (job_id in self._jobs and self._eligible(self._jobs[job_id]))
            for job_id in self._only
        ):
            self._processing = False  # all of start(job_ids=…) ended: idle, as after stop()
            self._only = None
            return True
        limit = self._settings().queue.parallel_jobs
        busy = {active.output_key for active in self._active.values() if active.output_key}
        for job in self._ordered():
            if len(self._active) >= limit:
                break
            if not self._eligible(job):
                continue
            key = _output_key(job)
            if key is not None and key in busy:
                continue  # the same output is being written by another job
            active = ActiveJob(job_id=job.id, output_key=key)
            self._active[job.id] = active
            if key is not None:
                busy.add(key)
            active.task = asyncio.get_running_loop().create_task(
                self._run(job, active), name=f"reframe-queue-job-{job.id}"
            )
        return False

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
                    await self._hold_inhibit(active, job)
                outcome = await self._runner.run(job, active, joblog)
        except Exception as exc:  # a bug: the job fails, the queue goes on
            log.exception("queue job %s failed with an internal error", job.id)
            outcome = Outcome(JobState.FAILED, error=f"Internal error: {type(exc).__name__}: {exc}")
        finally:
            if outcome is None:  # the task itself was cancelled (never by the queue)
                outcome = Outcome(JobState.INTERRUPTED, error="The job was stopped.")
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
            joblog.close()
            async with active.control:  # after a pause or resume that is under way
                active.ended = True
                await self._release_inhibit(active)
            job.finished_at = self._clock.now()
            await self._set_state(job, outcome.state, error=outcome.error)
            # No await from here on: the slot, the count and the when-done check change together.
            self._active.pop(job.id, None)
            self._count(outcome.state)
            drained = self._schedule()
            self._when_done(outcome.state, drained=drained)
            await self._notify()

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

    # ------------------------------------------------------------------ when done

    def _count(self, state: JobState) -> None:
        if state is JobState.DONE:
            self._batch_done += 1
        elif state is JobState.FAILED:
            self._batch_failed += 1

    def _when_done(self, last: JobState, *, drained: bool = False) -> None:
        """The queue emptied after a job ended on its own (done or failed; not when the user
        cancelled the last job or Reframe closed): run the when-done action once.

        "Emptied": nothing runs, and nothing is left that the runner would take: no waiting
        job at all, or (``drained``) none of the jobs of ``start(job_ids=…)``."""
        if self._closed or self._active:
            return
        if self._processing:
            if any(self._eligible(job) for job in self._jobs.values()):
                return
        elif not drained and any(job.state is JobState.WAITING for job in self._jobs.values()):
            return  # stopped with jobs left: the queue did not empty
        if last not in (JobState.DONE, JobState.FAILED):
            return
        done, failed = self._batch_done, self._batch_failed
        self._batch_done = self._batch_failed = 0
        action = self._settings().queue.when_done
        if action == "nothing":
            return
        summary = f"{done} job{'s' if done != 1 else ''} done"
        if failed:
            summary += f", {failed} failed"
        if action == "notify":
            self._events.publish(
                NotificationEvent(
                    title="Queue finished",
                    message=summary + ".",
                    level="warning" if failed else "success",
                )
            )
            return
        label = _POWER_LABELS.get(action, action)
        self._events.publish(
            AppWarningEvent(
                code="queue.when_done_unavailable",
                message=f"The queue is finished ({summary}). When done: “{label}” is not "
                "available yet, so nothing was done.",
                detail=f"when_done={action}: power actions come with C-14 (later milestone)",
            )
        )

    # ------------------------------------------------------------------ sleep inhibit

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

    # ------------------------------------------------------------------ helpers

    def _check_open(self) -> None:
        if self._closed:
            raise _closed_error()

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
