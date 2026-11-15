"""Running one job: prepare, run the plan's steps, finalize. :class:`JobRunner` returns an
:class:`Outcome` for every run and never raises for an expected failure.

A job never writes its source, except a metadata edit in place, which runs only mkvpropedit on
the source. That step is not killed by a cancel or by ``close()``: mkvpropedit installs no signal
handler, and a kill during its write can leave the source without track headers. The output is
checked before it takes its final name.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import psutil

from reframe.command import PlanError, build_plan
from reframe.command.mkvpropedit import header_edit_args
from reframe.command.quoting import Shell, command_line, default_shell
from reframe.definitions import Definitions
from reframe.events import EventBus
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.events import JobProgressEvent
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NamingOptions
from reframe.models.plan import EncodePlan, PlanArg, PlanStep, resolve_argv
from reframe.models.queue import JobProgress, JobState, QueueJob
from reframe.models.settings import AppSettings, CollisionPolicy
from reframe.models.tools import ToolInfo, ToolName, ToolSet, ToolStatus
from reframe.probe import ProbeError, matroska
from reframe.queue import files, loudnorm
from reframe.queue.clock import Clock
from reframe.queue.errors import closed_error, exit_text, printable, stderr_reason
from reframe.queue.logs import JobLog
from reframe.queue.process import resume_tree, suspend_tree
from reframe.queue.progress import ProgressBlock, ProgressParser, ProgressTracker
from reframe.queue.verify import check_output
from reframe.queue.watchdog import StepWatch, Verdict, tree_cpu_seconds
from reframe.tools import CancelToken, RunResult, crashed, run_streaming
from reframe.validation import FileSystemView, next_free_path, validate
from reframe.validation.output import output_path_issues

__all__ = [
    "ActiveJob",
    "CapabilitiesSource",
    "JobRunner",
    "Outcome",
    "SourceProber",
    "StopReason",
    "ToolsSource",
]

log = logging.getLogger(__name__)

#: Why a running job was stopped from outside its steps.
StopReason = Literal["cancel", "close", "stalled", "timeout"]

_WHAT = {
    "analyse": "Measuring the loudness",
    "pass1": "Pass 1",
    "pass2": "Pass 2",
    "encode": "The encode",
    "header_edit": "mkvpropedit",
    "finalize": "Finalizing",
}


def _program(step: PlanStep) -> tuple[ToolName, list[PlanArg]]:
    """The tool and the arguments that run ``step`` (not ``finalize``)."""
    if step.header_edit is not None:
        return "mkvpropedit", list(header_edit_args(step.header_edit))
    assert step.tool is not None
    return step.tool, step.argv


class ToolsSource(Protocol):
    """Tool discovery (``Reframe.tools``)."""

    async def status(self) -> ToolSet: ...


class CapabilitiesSource(Protocol):
    """Encoder detection (``Reframe.capabilities``)."""

    @property
    def snapshot(self) -> CapabilitySnapshot: ...

    async def wait(self) -> CapabilitySnapshot: ...


class SourceProber(Protocol):
    """Probing (``Reframe.sources``)."""

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError: ...


@dataclass(eq=False)
class ActiveJob:
    """The control state of one running (or paused) job, shared by the queue and the run."""

    job_id: str
    output_key: files.FileKey | None = None
    """The file the job writes (for an in-place edit, its source). Two jobs with the same output
    never run at once."""
    source_key: files.FileKey | None = None
    """The file the job reads: no job reads a source while it is edited in place."""
    in_place: bool = False
    """The job edits its source in place (``output.edit_in_place``)."""
    token: CancelToken = field(default_factory=CancelToken)
    stop_reason: StopReason | None = None
    paused: bool = False
    resumed: asyncio.Event = field(default_factory=asyncio.Event)
    """Set while the job is not paused."""
    process: psutil.Process | None = None
    """The running step's process (the root of its tree)."""
    tracker: ProgressTracker | None = None
    holds_inhibit: bool = False
    """This job holds one count of the sleep inhibitor (set once ``acquire`` returned)."""
    control: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Orders pause, resume and the inhibitor calls of this job (one at a time)."""
    ended: bool = False
    """The run ended: pause and resume do nothing any more."""
    task: asyncio.Task[None] | None = None
    end_note: str | None = None
    """The error of a run whose own task was cancelled during an in-place step: what happened
    to the source."""

    def __post_init__(self) -> None:
        self.resumed.set()

    def stop(self, reason: StopReason) -> None:
        """Stop the job (the first reason wins): the running step's tree is killed."""
        if self.stop_reason is None:
            self.stop_reason = reason
        self.token.cancel(reason)
        self.resumed.set()  # a job paused between steps must see the stop


@dataclass
class Outcome:
    """How a run ended."""

    state: JobState
    error: str | None = None
    issues: list[ValidationIssue] | None = None
    """New issues for the job (``None``: keep the current ones)."""
    plan: EncodePlan | None = None
    """The plan of this run, if one was built (its files are cleaned up)."""
    output_path: Path | None = None
    keep_part: bool = False
    """The ``.part`` file is complete and must be kept (``ask`` collision)."""
    stop_reason: StopReason | None = None
    progress: JobProgress | None = None


class _Stopped(Exception):
    """The job's cancel token fired (cancel, close, watchdog)."""


@dataclass
class _Prepared:
    source: MediaSource
    tools: ToolSet
    plan: EncodePlan


def _block_key(block: ProgressBlock) -> tuple[float | None, int | None, int | None]:
    return (block.out_time, block.frame, block.total_size)


def _issue(code: str, message: str, path: str = "") -> ValidationIssue:
    return ValidationIssue(severity=Severity.ERROR, code=code, path=path, message=message)


def _usable(info: ToolInfo) -> bool:
    return info.status is ToolStatus.FOUND and info.path is not None


class JobRunner:
    """Runs jobs. One runner serves every job of a queue."""

    def __init__(
        self,
        *,
        events: EventBus,
        settings: Callable[[], AppSettings],
        tools: ToolsSource,
        capabilities: CapabilitiesSource,
        sources: SourceProber,
        clock: Clock,
        fs: FileSystemView,
        definitions: Definitions,
        naming: Callable[[JobSettings], NamingOptions | None],
        persist: Callable[[QueueJob], Awaitable[None]],
        stall_after: float | None,
        step_time_limit: float | None,
        tick: float,
        log_interval: float,
        shell: Shell | None = None,
        resumed: Callable[[QueueJob, ActiveJob], Awaitable[None]] | None = None,
    ) -> None:
        """``resumed``: called with ``active.control`` held when a paused in-place step is
        resumed, so that a cancel or ``close()`` can let it finish. The queue shows the job
        ``running`` again and takes its sleep inhibit."""
        self._events = events
        self._resumed = resumed
        self._settings = settings
        self._tools = tools
        self._caps = capabilities
        self._sources = sources
        self._clock = clock
        self._fs = fs
        self._defs = definitions
        self._naming = naming
        self._persist = persist
        self._stall_after = stall_after
        self._step_time_limit = step_time_limit
        self._tick = tick
        self.log_interval = log_interval
        self._shell: Shell = shell or default_shell()

    async def check(self, job: JobSettings) -> list[ValidationIssue]:
        """Validate ``job`` now: probe, tools and the capability snapshot as it is, without
        waiting for detection."""
        unusable = _unusable_path(job)
        if unusable is not None:
            return [unusable]
        source = await self._sources.probe(job.source.path)
        if isinstance(source, ProbeError):
            return [_source_issue(source)]
        tools = await self._tools.status()
        return await self._validate(job, source, self._caps.snapshot, tools)

    async def run(self, job: QueueJob, active: ActiveJob, joblog: JobLog) -> Outcome:
        """Run ``job``. Never raises for an expected failure."""
        outcome = await self._run(job, active, joblog)
        if outcome.plan is not None and outcome.plan.job_type == "metadata_edit":
            # A metadata edit writes into the source: the queue has nothing to clean up.
            outcome.plan = None
        return outcome

    async def _run(self, job: QueueJob, active: ActiveJob, joblog: JobLog) -> Outcome:
        closed = closed_error()
        plan: EncodePlan | None = None
        try:
            prepared = await self._prepare(job, active, joblog)
            if isinstance(prepared, Outcome):
                return prepared
            plan = prepared.plan
            return await self._steps(job, active, joblog, prepared)
        except _Stopped:
            return self._stopped(active, plan)
        except closed:
            active.stop("close")
            return self._stopped(active, plan)

    async def _until_stopped[T](self, awaitable: Awaitable[T], active: ActiveJob) -> T:
        """``awaitable``'s result, or :class:`_Stopped` as soon as the job is stopped."""
        if active.token.cancelled:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise _Stopped
        task = asyncio.ensure_future(awaitable)
        stop = asyncio.ensure_future(active.token.wait())
        try:
            await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.cancel()
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if task.cancelled():
            raise _Stopped
        return task.result()

    async def _validate(
        self, job: JobSettings, source: MediaSource, caps: CapabilitySnapshot, tools: ToolSet
    ) -> list[ValidationIssue]:
        settings = self._settings()
        return await asyncio.to_thread(
            validate,
            job,
            source,
            caps,
            tools,
            self._fs,
            settings=settings,
            definitions=self._defs,
            naming=self._naming(job),
        )

    async def _prepare(
        self, job: QueueJob, active: ActiveJob, joblog: JobLog
    ) -> _Prepared | Outcome:
        settings = job.settings
        unusable = _unusable_path(settings)
        if unusable is not None:  # a stored job (restore) or a retry: fails, the queue goes on
            return Outcome(JobState.FAILED, error=unusable.message, issues=[unusable])
        joblog.note("Probing the source again")
        source = await self._until_stopped(
            self._sources.probe(settings.source.path, cancel=active.token), active
        )
        if active.token.cancelled:
            raise _Stopped
        if isinstance(source, ProbeError):
            issue = _source_issue(source)
            return Outcome(JobState.FAILED, error=issue.message, issues=[issue])
        tools = await self._until_stopped(self._tools.status(), active)
        caps = self._caps.snapshot
        issues = await self._until_stopped(self._validate(settings, source, caps, tools), active)
        if any(issue.code == "encoder.checking" for issue in issues):
            joblog.note("Waiting for the encoder detection")
            caps = await self._until_stopped(self._caps.wait(), active)
            issues = await self._until_stopped(
                self._validate(settings, source, caps, tools), active
            )
        job.issues = issues
        errors = [issue for issue in issues if issue.severity is Severity.ERROR]
        for issue in issues:
            joblog.write(f"{issue.severity.value}: {issue.code}: {issue.message}")
        if errors:
            more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
            return Outcome(
                JobState.FAILED,
                error=f"The job has errors: {errors[0].message}{more}",
                issues=issues,
            )
        try:
            plan = build_plan(
                settings,
                source,
                caps,
                tools,
                definitions=self._defs,
                shell=self._shell,
                naming=self._naming(settings),
                now=self._clock.now().astimezone(),
            )
        except PlanError as exc:
            issue = _issue("queue.plan_failed", f"The job cannot be planned: {exc}")
            return Outcome(JobState.FAILED, error=issue.message, issues=[*issues, issue])
        job.plan = plan
        await self._persist(job)
        return _Prepared(source=source, tools=tools, plan=plan)

    async def _steps(
        self, job: QueueJob, active: ActiveJob, joblog: JobLog, prepared: _Prepared
    ) -> Outcome:
        plan = prepared.plan
        source = Path(job.settings.source.path)
        if plan.job_type == "metadata_edit":
            return await self._edit_in_place(job, active, joblog, prepared)
        clash = await asyncio.to_thread(_writes_source, plan, source)
        if clash is not None:  # nothing is written or removed
            issue = _issue(
                "queue.writes_source",
                f"{clash.name} is the source file itself ({source}): the job would write over "
                "or remove its source, so nothing was written or removed.",
                "output.path",
            )
            return Outcome(JobState.FAILED, error=issue.message, issues=[*job.issues, issue])
        try:
            await asyncio.to_thread(_write_files, plan)
        except OSError as exc:
            return Outcome(
                JobState.FAILED,
                error=f"The output folder or the plan files cannot be written: {exc}",
                plan=plan,
            )
        tracker = ProgressTracker(plan.steps, plan.expected_duration)
        active.tracker = tracker
        values: dict[str, str] = {}
        count = len(plan.steps)
        for index, step in enumerate(plan.steps):
            await self._wait_resumed(active)
            self._publish(job, tracker.start_step(index))
            if step.kind == "finalize":
                joblog.note(f"Step {index + 1}/{count} ({step.kind}): {step.description}")
                return await self._finalize(job, active, joblog, prepared, tracker)
            tool, step_argv = _program(step)
            info = prepared.tools.get(tool)
            what = _WHAT[step.kind]
            if not _usable(info):
                reason = f": {info.reason}" if info.reason else ""
                return Outcome(
                    JobState.FAILED,
                    error=f"{what} needs {tool}, which is not available{reason}",
                    plan=plan,
                )
            try:
                argv = resolve_argv(step_argv, values)
            except KeyError as exc:
                return Outcome(
                    JobState.FAILED,
                    error=f"{what} needs the measured value {exc.args[0]}, which is missing",
                    plan=plan,
                )
            assert info.path is not None
            result, stderr = await self._run_step(
                job, active, joblog, step, f"Step {index + 1}/{count}", info, argv
            )
            if active.stop_reason is not None:
                raise _Stopped
            if not result.ok:
                return Outcome(JobState.FAILED, error=_failure(step, result, stderr), plan=plan)
            if step.measures:
                failure = self._measure(step, result, values, joblog)
                if failure is not None:
                    return Outcome(JobState.FAILED, error=failure, plan=plan)
            self._publish(job, tracker.step_done())
        # A plan always ends with ``finalize``; without one the output is still checked.
        return await self._finalize(job, active, joblog, prepared, tracker)

    async def _wait_resumed(self, active: ActiveJob) -> None:
        while active.paused and not active.token.cancelled:
            await self._until_stopped(active.resumed.wait(), active)
        if active.token.cancelled:
            raise _Stopped

    def _publish(self, job: QueueJob, progress: JobProgress) -> None:
        job.progress = progress
        self._events.publish(JobProgressEvent(job_id=job.id, progress=progress))

    async def _run_step(
        self,
        job: QueueJob,
        active: ActiveJob,
        joblog: JobLog,
        step: PlanStep,
        label: str,
        info: ToolInfo,
        argv: list[str],
        *,
        in_place: Path | None = None,
    ) -> tuple[RunResult, list[str]]:
        """Run one tool step. ``in_place``: the step edits this source in place, so a stop of
        the job does not kill it; only the step's time limit does."""
        assert info.path is not None
        assert active.tracker is not None
        tracker = active.tracker
        if in_place is not None and active.token.cancelled:
            raise _Stopped  # never start writing the source after a stop
        program = str(info.path)
        joblog.note(f"{label} ({step.kind}): {step.description or step.kind}")
        joblog.write("$ " + command_line(program, argv, self._shell))
        parser = ProgressParser()
        stderr: deque[str] = deque(maxlen=200)
        ffmpeg = step.tool == "ffmpeg"
        watch = StepWatch(
            stall_after=self._stall_after if ffmpeg else None,
            time_limit=None if ffmpeg else self._step_time_limit,
            max_tick=2 * self._tick,
        )
        last: list[tuple[float | None, int | None, int | None] | None] = [None]

        def on_stdout(line: str) -> None:
            block = parser.feed(line)
            if block is None:
                if line.strip() and not parser.is_progress_line(line):
                    joblog.write(line)
                return
            key = _block_key(block)
            if key != last[0]:
                last[0] = key
                watch.activity()
            self._publish(
                job, tracker.update(block, mono=self._clock.monotonic(), wall=self._clock.wall())
            )

        def on_stderr(line: str) -> None:
            stderr.append(line)
            watch.activity()
            joblog.write(line)

        def on_start(pid: int) -> None:
            try:
                active.process = psutil.Process(pid)
            except psutil.Error:
                active.process = None
                return
            if active.paused:
                suspend_tree(active.process)

        step_token = CancelToken() if in_place is not None else active.token
        watchdog = asyncio.ensure_future(
            self._watchdog(active, watch, step_token if in_place is not None else None)
        )
        guard = (
            asyncio.ensure_future(self._let_finish(job, active, joblog, in_place))
            if in_place is not None
            else None
        )
        try:
            run = run_streaming(
                [program, *argv],
                on_stdout_line=on_stdout,
                on_stderr_line=on_stderr,
                cancel=step_token,
                extra_env=info.env or None,
                on_start=on_start,
            )
            if in_place is None:
                result = await run
            else:
                result = await self._to_its_end(
                    asyncio.ensure_future(run), active, joblog, label, in_place
                )
        finally:
            for helper in (watchdog, guard):
                if helper is not None:
                    helper.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await helper
            active.process = None
        joblog.flush_file()
        if result.error is not None:
            joblog.note(f"{label} could not start: {result.error}")
        else:
            # A process that exited 0 just as the cancel came is not "stopped".
            ended = "stopped" if _killed(result) else exit_text(result.returncode)
            joblog.note(f"{label} ended: {ended} after {result.duration:.1f} s")
        return result, list(stderr)

    async def _watchdog(
        self, active: ActiveJob, watch: StepWatch, step_token: CancelToken | None = None
    ) -> None:
        """Stop the job when the step stalls or runs out of time. An in-place step has its own
        token, so only the step stops: a step that exits 0 just after its limit ends as any
        finished step and is checked."""
        while True:
            await asyncio.sleep(self._tick)
            process = active.process
            cpu = tree_cpu_seconds(process.pid) if process is not None else None
            verdict: Verdict | None = watch.tick(self._clock.monotonic(), cpu, paused=active.paused)
            if verdict is not None:
                if step_token is not None:
                    step_token.cancel(verdict)
                else:
                    active.stop(verdict)
                return

    async def _let_finish(
        self, job: QueueJob, active: ActiveJob, joblog: JobLog, source: Path
    ) -> None:
        """While an in-place step runs: when the job is stopped, log that the step is let
        finish, and resume it if the job was paused, since a suspended step would never end.
        Runs under the job's control lock, so a pause under way ends first."""
        await active.token.wait()
        if active.stop_reason not in ("cancel", "close"):
            return  # not a stop of the job: only the step's own time limit stops the step
        why = "Reframe is closing" if active.stop_reason == "close" else "The job is cancelled"
        joblog.note(
            f"{why} while mkvpropedit is writing {source.name}: it is let finish (stopping it "
            "could damage the file)"
        )
        async with active.control:
            if active.paused:
                active.paused = False  # the step's time limit counts again
                if active.process is not None:
                    await asyncio.to_thread(resume_tree, active.process)
                if active.tracker is not None:
                    active.tracker.resume()
                if self._resumed is not None:
                    try:
                        await self._resumed(job, active)
                    except Exception:  # only what the job shows: the step still ends first
                        log.exception("queue job %s: showing the resumed edit failed", job.id)

    async def _to_its_end(
        self,
        run: asyncio.Future[RunResult],
        active: ActiveJob,
        joblog: JobLog,
        label: str,
        source: Path,
    ) -> RunResult:
        """The result of an in-place step. If only the awaiting task is cancelled, the step
        still runs to its end (its time limit bounds it), then the cancellation goes on. If the
        event loop shuts down, the step's own run is cancelled too and mkvpropedit is killed;
        the job's end then says the file may be damaged. Either way ``active.end_note`` says
        what happened to the source."""
        try:
            return await asyncio.shield(run)
        except asyncio.CancelledError:
            while not run.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(run)
            if run.cancelled() or run.exception() is not None:
                # The run's own task was cancelled too: its clean-up killed the process tree.
                active.end_note = (
                    f"Reframe was shut down while mkvpropedit was editing {source.name} in "
                    "place: mkvpropedit was stopped before it ended, so the file may be damaged."
                )
                joblog.note(f"{label} ended: stopped. {active.end_note}")
                raise
            result = run.result()
            if _killed(result):  # the step's time limit
                active.end_note = self._timed_out(source)
                joblog.note(f"{label} ended: stopped. {active.end_note}")
                raise
            if result.error is None and result.returncode == 0:
                active.end_note = (
                    f"The job was stopped while mkvpropedit was editing {source.name} in place: "
                    "it was let finish, so the edit is written. The check of the edited file "
                    "did not run."
                )
            joblog.note(
                f"{label} ended: {exit_text(result.returncode)}; the job was stopped while "
                "mkvpropedit was writing the source: it was let finish"
            )
            raise

    def _timed_out(self, source: Path) -> str:
        """The error of an in-place step that its time limit stopped."""
        return (
            f"mkvpropedit did not finish within {_duration(self._step_time_limit)} and was "
            f"stopped while it was editing {source.name} in place: the file may be damaged."
        )

    def _measure(
        self, step: PlanStep, result: RunResult, values: dict[str, str], joblog: JobLog
    ) -> str | None:
        """Store the step's ``loudnorm`` measurements; a failure text, or ``None``."""
        try:
            blocks = loudnorm.parse_blocks(result.stderr_text)
            if len(blocks) != len(step.measures):
                return (
                    f"{_WHAT[step.kind]} printed {len(blocks)} loudnorm result(s), "
                    f"{len(step.measures)} expected"
                )
            for measurement, block in zip(step.measures, blocks, strict=True):
                clamped, notes = loudnorm.clamp(block)
                for key, value in clamped.items():
                    values[f"{measurement.id}.{key}"] = value
                if notes:
                    joblog.note(
                        f"Loudness {measurement.id}: silent or nearly silent, values clamped "
                        f"into loudnorm's ranges ({', '.join(notes)})"
                    )
        except loudnorm.MeasureError as exc:
            return f"{_WHAT[step.kind]} failed: {exc}"
        return None

    async def _finalize(
        self,
        job: QueueJob,
        active: ActiveJob,
        joblog: JobLog,
        prepared: _Prepared,
        tracker: ProgressTracker,
    ) -> Outcome:
        plan = prepared.plan
        tmp = plan.output_tmp
        if not await asyncio.to_thread(tmp.is_file):
            return Outcome(
                JobState.FAILED,
                error=f"The encode ended without an error but wrote no output ({tmp.name} is "
                "missing).",
                plan=plan,
            )
        joblog.note(f"Checking the output {tmp.name}")
        output = await self._until_stopped(
            self._sources.probe(tmp, use_cache=False, cancel=active.token), active
        )
        if active.token.cancelled:
            raise _Stopped
        if isinstance(output, ProbeError):
            detail = f" ({output.detail})" if output.detail else ""
            return Outcome(
                JobState.FAILED,
                error=f"The output cannot be read: {output.message}{detail}",
                plan=plan,
            )
        problems = check_output(job.settings, prepared.source, output, self._defs, plan=plan)
        if problems:
            return Outcome(
                JobState.FAILED,
                error="The output does not match the plan: " + "; ".join(problems) + ".",
                plan=plan,
            )
        await self._wait_resumed(active)
        policy = self._settings().output.collision
        placed = await asyncio.to_thread(self._place, tmp, plan.output_final, policy)
        if isinstance(placed, Path):
            if placed != plan.output_final:
                joblog.note(f"{plan.output_final.name} exists: saved as {placed.name}")
            joblog.note(f"Renamed {tmp.name} to {placed.name}")
            return Outcome(JobState.DONE, plan=plan, output_path=placed, progress=tracker.finish())
        if isinstance(placed, OSError):
            return Outcome(
                JobState.FAILED,
                error=f"{tmp.name} could not be renamed to {plan.output_final.name}: "
                f"{placed.strerror or placed}",
                plan=plan,
            )
        found = await asyncio.to_thread(  # it reads the output folder: never on the event loop
            output_path_issues,
            plan.output_final,
            Path(job.settings.source.path),
            self._fs,
            container=self._defs.containers.get(job.settings.output.container),
            collision="ask",
        )
        issues = [issue for issue in found if issue.code == "output.exists"] or [
            _issue("output.exists", f"{plan.output_final.name} already exists.", "output.path")
        ]
        return Outcome(
            JobState.FAILED,
            error=f"{plan.output_final.name} already exists (Settings → Output asks what to "
            f"do, and a queue cannot ask). The finished encode is kept as {tmp.name}.",
            issues=[*job.issues, *issues],
            plan=plan,
            keep_part=True,
        )

    def _place(self, tmp: Path, final: Path, policy: CollisionPolicy) -> Path | OSError | None:
        """Give ``tmp`` its final name (blocking). ``None``: the name is taken and the policy
        is ``ask``."""
        try:
            for _ in range(100):
                if policy == "overwrite":
                    files.replace_file(tmp, final)
                    return final
                target = final
                if os.path.lexists(final):
                    if policy == "ask":
                        return None
                    target = next_free_path(final, self._fs)
                try:
                    files.rename_no_replace(tmp, target)
                except FileExistsError:
                    continue  # taken in the meantime: look again
                return target
            return FileExistsError(f"no free name for {final.name}")
        except OSError as exc:
            return exc

    async def _edit_in_place(
        self, job: QueueJob, active: ActiveJob, joblog: JobLog, prepared: _Prepared
    ) -> Outcome:
        """Run a ``metadata_edit`` plan on the source."""
        plan = prepared.plan
        source = Path(job.settings.source.path)
        refusal = await asyncio.to_thread(_in_place_refusal, plan, source, prepared.source)
        if refusal is not None:
            code, message = refusal
            issue = _issue(code, message, "output.edit_in_place")
            return Outcome(JobState.FAILED, error=issue.message, issues=[*job.issues, issue])
        tracker = ProgressTracker(plan.steps, plan.expected_duration)
        active.tracker = tracker
        count = len(plan.steps)
        if not count:
            joblog.note(f"{source.name} already has every value: nothing to change")
        written = 0  # edit steps that ran to their end: from then on the source is changed
        try:
            for index, step in enumerate(plan.steps):
                await self._wait_resumed(active)
                self._publish(job, tracker.start_step(index))
                info = prepared.tools.get("mkvpropedit")
                if not _usable(info):
                    reason = f": {info.reason}" if info.reason else ""
                    return Outcome(
                        JobState.FAILED,
                        error=f"Editing in place needs mkvpropedit, which is not available{reason}",
                        plan=plan,
                    )
                argv = resolve_argv(_program(step)[1], {})
                result, stderr = await self._run_step(
                    job, active, joblog, step, f"Step {index + 1}/{count}", info, argv,
                    in_place=source,
                )  # fmt: skip
                if _killed(result):  # only the step's time limit stops an in-place step
                    return Outcome(
                        JobState.FAILED,
                        error=self._timed_out(source),
                        plan=plan,
                        stop_reason="timeout",
                    )
                # Exit code 0, also one that came just as the time limit fired: the step ended
                # on its own and its edit is in the file.
                finished = result.error is None and result.returncode == 0
                if finished:
                    written += 1
                if active.stop_reason is not None:
                    raise _Stopped
                if not finished:
                    return Outcome(JobState.FAILED, error=_failure(step, result, stderr), plan=plan)
                self._publish(job, tracker.step_done())
            joblog.note(f"Checking the edited source {source.name}")
            output = await self._until_stopped(
                self._sources.probe(source, use_cache=False, cancel=active.token), active
            )
            if active.token.cancelled:
                raise _Stopped
        except (_Stopped, closed_error()):
            if not written:
                raise
            if active.stop_reason is None:  # Reframe closed under the check
                active.stop("close")
            return _stopped_after_edit(active, source, plan, written, count)
        if isinstance(output, ProbeError):
            detail = f" ({output.detail})" if output.detail else ""
            return Outcome(
                JobState.FAILED,
                error=f"The edited source cannot be read: {output.message}{detail}",
                plan=plan,
            )
        problems = check_output(job.settings, prepared.source, output, self._defs, plan=plan)
        if problems:
            return Outcome(
                JobState.FAILED,
                error="The edited source does not have the values of the job: "
                + "; ".join(problems)
                + ".",
                plan=plan,
            )
        joblog.note(f"Edited {source.name} in place")
        return Outcome(JobState.DONE, plan=plan, output_path=source, progress=tracker.finish())

    def _stopped(self, active: ActiveJob, plan: EncodePlan | None) -> Outcome:
        reason = active.stop_reason or "cancel"
        if reason == "cancel":
            return Outcome(JobState.CANCELLED, plan=plan, stop_reason=reason)
        if reason == "close":
            return Outcome(
                JobState.INTERRUPTED,
                error="Reframe was closed while the job was running.",
                plan=plan,
                stop_reason=reason,
            )
        if reason == "stalled":
            error = (
                f"FFmpeg made no progress for {_duration(self._stall_after)} (no output, no CPU "
                "use) and was stopped."
            )
        else:
            error = (
                f"A step did not finish within {_duration(self._step_time_limit)} and was stopped."
            )
        return Outcome(JobState.FAILED, error=error, plan=plan, stop_reason=reason)


def _stopped_after_edit(
    active: ActiveJob, source: Path, plan: EncodePlan, written: int, count: int
) -> Outcome:
    """The end of an in-place job stopped after its edit was written: ``cancelled`` for a
    cancel, ``interrupted`` for ``close()``, with an error that says the file is changed and
    not checked. A time limit never reaches here, since it stops only the step; any other
    reason is ``failed``, never a cancel."""
    reason = active.stop_reason
    if reason == "close":
        state, when = JobState.INTERRUPTED, "Reframe was closed"
    elif reason == "cancel":
        state, when = JobState.CANCELLED, "the job was cancelled"
    else:
        state, when = JobState.FAILED, "the job was stopped (a time limit)"
    what = (
        "The edit was"
        if written >= count
        else f"Part of the edit ({written} of {count} mkvpropedit steps) was"
    )
    return Outcome(
        state,
        error=f"{what} already written to {source.name} when {when}: mkvpropedit is never "
        "stopped while it writes the source (that can damage the file). The check of the "
        "edited file did not run.",
        plan=plan,
        output_path=source,
        stop_reason=reason,
    )


def _killed(result: RunResult) -> bool:
    """The step was stopped by its cancel token: it did not end on its own. A process that
    exited 0 just as the token fired (``cancelled`` and exit code 0) ended on its own; a
    killed one has a signal (POSIX) or the kill's exit code (Windows), or never started."""
    return result.cancelled and result.returncode != 0


def _duration(seconds: float | None) -> str:
    """A duration as text: minutes from 60 seconds up, otherwise seconds."""
    value = seconds or 0.0
    if value >= 60:
        minutes = value / 60
        return f"{minutes:g} minute" + ("" if minutes == 1 else "s")
    return f"{value:g} second" + ("" if value == 1 else "s")


def _writes_source(plan: EncodePlan, source: Path) -> Path | None:
    """The first path the plan writes, renames or removes that is the source (the ``.part``
    file, a plan file, a statistics file, the final name), or ``None``."""
    for path in (plan.output_tmp, *(f.path for f in plan.files), *plan.temp_files):
        if files.same_file(path, source):
            return path
    return plan.output_final if files.same_file(plan.output_final, source) else None


def _in_place_refusal(
    plan: EncodePlan, source: Path, probed: MediaSource
) -> tuple[str, str] | None:
    """Why the runner refuses a ``metadata_edit`` plan (blocking): ``(code, message)``, or
    ``None``. Only mkvpropedit steps on the source are allowed: no other file is written and
    nothing is removed."""
    targets = [plan.output_tmp, plan.output_final]
    steps_ok = all(
        step.kind == "header_edit"
        and step.tool is None
        and not step.argv
        and step.header_edit is not None
        and files.same_file(step.header_edit.path, source)
        for step in plan.steps
    )
    if (
        plan.files
        or plan.temp_files
        or not steps_ok
        or not all(files.same_file(path, source) for path in targets)
    ):
        return (
            "queue.writes_source",
            f"The in-place edit of {source.name} would write other files or use another tool "
            "than mkvpropedit on the source, so nothing was written or removed.",
        )
    if not plan.steps:
        return None
    if not files.writable_file(source):
        return (
            "inplace.source_not_writable",
            f"{source.name} cannot be written (read-only, or no permission), so its metadata "
            "cannot be edited in place. Nothing was changed.",
        )
    try:
        info = matroska.read_matroska(source)
    except (matroska.MatroskaError, OSError) as exc:
        return (
            "inplace.tracks_mismatch",
            f"The Matroska track headers of {source.name} cannot be read ({exc}), so the "
            "tracks to edit cannot be checked. Nothing was changed.",
        )
    kinds = matroska.tracks_by_kind(info)
    counts = {
        "video": len(probed.video),
        "audio": len(probed.audio),
        "subtitle": len(probed.subtitles),
    }
    have = {kind: len(kinds[kind]) for kind in ("video", "audio", "subtitle")}
    if have != counts:

        def text(numbers: dict[str, int]) -> str:
            return ", ".join(f"{n} {kind}" for kind, n in numbers.items())

        return (
            "inplace.tracks_mismatch",
            f"{source.name} has {text(have)} tracks, but its probe shows {text(counts)} "
            "streams: the tracks to edit cannot be told apart. Nothing was changed.",
        )
    return None


def _write_files(plan: EncodePlan) -> None:
    plan.output_tmp.parent.mkdir(parents=True, exist_ok=True)
    files.write_plan_files(plan.files)


def _unusable_path(job: JobSettings) -> ValidationIssue | None:
    """``queue.path_unusable`` for a source or output path with a NUL character, which no file
    system accepts (``os.stat`` and ``realpath`` reject it), else ``None``. The job fails with
    this message at ``add`` and when it runs, instead of an internal error."""
    named = (("source", "source.path", job.source.path), ("output", "output.path", job.output.path))
    for what, field_path, path in named:
        if path is not None and "\0" in os.fspath(path):
            shown = os.fspath(path).replace("\0", "\\0")
            return _issue(
                "queue.path_unusable",
                f"The {what} path {printable(shown)} has a NUL character, which no file system "
                "allows, so the job cannot run. Correct the path.",
                field_path,
            )
    return None


def _source_issue(error: ProbeError) -> ValidationIssue:
    detail = f" ({error.detail})" if error.detail else ""
    return _issue(
        "queue.source_unreadable",
        f"The source {error.path.name} cannot be read: {error.message}{detail}",
        "source.path",
    )


def _failure(step: PlanStep, result: RunResult, stderr: Sequence[str]) -> str:
    what = _WHAT[step.kind]
    tool = _program(step)[0]
    if result.error is not None:
        return f"{what} could not start {tool}: {result.error}"
    crash = crashed(result.returncode)
    reason = stderr_reason(stderr, last_line=not crash)
    status = exit_text(result.returncode)
    if crash:
        head = f"{tool} crashed during {what.lower()} ({status})"
    else:
        head = f"{what} failed ({status})"
    return f"{head}: {reason}" if reason else f"{head}."
