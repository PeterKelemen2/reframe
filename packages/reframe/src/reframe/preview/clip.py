"""The ``preview_clip`` task (05 §C-10, 03 §Preview → Live preview clip).

``seconds`` from ``start`` of the job's source, encoded with the job's **full plan**: a copy of
the job with the range ``start … start + seconds`` (to the end when that is past it), the
output in the cache (``<cache dir>/clips/<id>.<ext>``, the job's container) and no in-place
edit. Then, like the queue (C-11):

1. **Validation** first (C-8, with the current capabilities; when an encoder is still being
   checked, after the detection): a job with errors fails the task with the first error.
2. **C-7's** ``build_plan``; its steps run in order through ``reframe.tools.run_streaming``
   with the task's cancel token: the loudness ``analyse`` steps (their ``loudnorm``
   measurements fill the later steps), both passes of a 2-pass encode (decision 0033: the
   clip shows the rate control of the job), ``mkvpropedit``, then the rename of the ``.part``
   file. Progress comes from FFmpeg's ``-progress`` blocks, weighted like a queue job.
3. The plan files, the 2-pass statistics and a partial output are removed, also after a
   failure or a cancel.

**The id** is a hash of the source file version, the plan's steps and the tool builds: the
same request gives the cached clip at once (``PreviewClip`` with the same id). The clip's
timeline starts at 0: its frame at ``t`` is the source frame at ``start + t`` (03 §Preview,
encoded frame compare: ``Reframe.sources.frames(clip.path, timestamps=[t])``).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from reframe.command import PlanError, build_plan
from reframe.definitions import Definitions
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models import (
    CapabilitySnapshot,
    EncodePlan,
    JobSettings,
    Measurement,
    MediaSource,
    TimeRange,
    ToolSet,
    ToolStatus,
)
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.plan import resolve_argv
from reframe.models.preview import PreviewClip
from reframe.preview.cache import PreviewCache, digest, megabytes, source_fingerprint
from reframe.preview.common import failure_text, sample_duration, tool_identity
from reframe.queue import loudnorm
from reframe.queue.files import write_plan_files
from reframe.queue.progress import ProgressParser, ProgressTracker
from reframe.tasks import TaskContext
from reframe.tools import run_streaming
from reframe.validation import LocalFileSystem, validate

__all__ = ["make_clip"]

#: The output name used to compute a clip's id (the id cannot depend on itself).
_PLACEHOLDER = "0" * 32
_STDERR_LINES = 200


def _clip_job(job: JobSettings, *, start: float, end: float | None, output: Path) -> JobSettings:
    clip = job.model_copy(deep=True)
    clip.range = TimeRange(start=start, end=end)
    clip.output.path = output
    clip.output.edit_in_place = False
    return clip


def _errors(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity is Severity.ERROR]


async def _validate(
    ctx: MediaTaskContext,
    job: JobSettings,
    source: MediaSource,
    tools: ToolSet,
    defs: Definitions,
) -> tuple[list[ValidationIssue], CapabilitySnapshot]:
    """Validate like the queue runner: with the capability snapshot, and again after the
    detection when an encoder is still being checked."""
    settings = ctx.settings()

    def check(caps: CapabilitySnapshot) -> list[ValidationIssue]:
        return validate(
            job, source, caps, tools, LocalFileSystem(), settings=settings, definitions=defs
        )

    caps = ctx.capabilities.snapshot
    issues = await asyncio.to_thread(check, caps)
    if any(issue.code == "encoder.checking" for issue in issues):
        caps = await ctx.capabilities.wait()
        issues = await asyncio.to_thread(check, caps)
    return issues, caps


def _plan(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    defs: Definitions,
) -> EncodePlan:
    try:
        return build_plan(job, source, caps, tools, definitions=defs)
    except PlanError as exc:
        raise TaskFailed(f"The job cannot be planned: {exc}.") from exc


async def make_clip(
    tctx: TaskContext,
    ctx: MediaTaskContext,
    job: JobSettings,
    *,
    start: float,
    seconds: float,
) -> PreviewClip:
    """The body of the ``preview_clip`` task (see the module doc)."""
    if not math.isfinite(start) or start < 0:
        raise TaskFailed(f"The clip start {start} is not a time in the source (seconds from 0).")
    if not math.isfinite(seconds) or seconds <= 0:
        raise TaskFailed(f"The clip length must be more than 0 seconds, not {seconds}.")
    await require_tool(ctx, "ffmpeg")
    path = Path(job.source.path)
    source = await require_source(ctx, path, cancel=tctx.cancel)
    if not source.video:
        raise TaskFailed(f"{path.name} has no video stream.")
    duration = sample_duration(source, source.video[0])
    if duration is not None and start >= duration:
        raise TaskFailed(
            f"The clip start {start:g} s is not before the end of {path.name} ({duration:g} s)."
        )
    end: float | None = start + seconds
    if duration is not None and end is not None and end >= duration:
        end = None  # to the end
    defs = ctx.definitions()
    container = defs.containers.get(job.output.container)
    if container is None:
        raise TaskFailed(f"Unknown container {job.output.container!r}.")
    extension = container.extensions[0]
    tools = await ctx.tools.status()
    cache = PreviewCache(ctx.cache_dir)
    try:
        await asyncio.to_thread(cache.clips.mkdir, parents=True, exist_ok=True)
        stat = await asyncio.to_thread(os.stat, path)
    except OSError as exc:
        raise TaskFailed(f"The preview clip cannot be made: {exc}.") from exc

    draft = _clip_job(job, start=start, end=end, output=cache.clip(_PLACEHOLDER, extension))
    issues, caps = await _validate(ctx, draft, source, tools, defs)
    errors = _errors(issues)
    if errors:
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        raise TaskFailed(f"The job has errors: {errors[0].message}{more}")
    plan = _plan(draft, source, caps, tools, defs)
    identities = {
        step.tool: tool_identity(tools.get(step.tool)) for step in plan.steps if step.tool
    }
    clip_id = digest(
        "clip",
        source_fingerprint(path, stat),
        [step.model_dump(mode="json") for step in plan.steps],
        sorted(identities.items()),
    )[:32]
    encoder = defs.video_encoders.get(job.video.encoder)
    if job.video.passthrough:
        video_codec = source.video[0].codec
    else:
        video_codec = encoder.codec if encoder is not None else None

    def result(clip: Path, size: int) -> PreviewClip:
        return PreviewClip(
            id=clip_id,
            path=clip,
            source=path,
            start=start,
            duration=plan.expected_duration,
            container=job.output.container,
            video_codec=video_codec,
            job_type=plan.job_type,
            size=size,
        )

    cached = cache.find_clip(clip_id)
    if cached is not None:
        tctx.progress(100.0, "The clip is in the cache")
        return result(cached, cached.stat().st_size)

    final = cache.clip(clip_id, extension)
    plan = _plan(_clip_job(job, start=start, end=end, output=final), source, caps, tools, defs)
    if plan.job_type == "metadata_edit" or plan.output_tmp.parent != cache.clips:
        # Never reached: the clip job does not edit in place. A preview must never write
        # anywhere but the cache (and never the source).
        raise TaskFailed("A preview clip of this job would not be written into the cache.")
    await _run_plan(tctx, plan, tools)
    size = final.stat().st_size
    limit = megabytes(ctx.settings().preview.cache_size_mb)
    await asyncio.to_thread(cache.trim, limit, protect=[final])
    return result(final, size)


async def _run_plan(tctx: TaskContext, plan: EncodePlan, tools: ToolSet) -> None:
    """Run the plan's steps (see the module doc); :class:`TaskFailed` when one fails."""
    tracker = ProgressTracker(plan.steps, plan.expected_duration)
    values: dict[str, str] = {}
    leftovers = [plan.output_tmp, *plan.temp_files, *(f.path for f in plan.files)]
    try:
        await _file_call("The plan files cannot be written", write_plan_files, plan.files)
        for index, step in enumerate(plan.steps):
            tctx.progress(tracker.start_step(index).percent, step.description)
            if step.tool is None:  # finalize
                await _file_call(
                    "The clip cannot be renamed", os.replace, plan.output_tmp, plan.output_final
                )
                continue
            info = tools.get(step.tool)
            if info.status is not ToolStatus.FOUND or info.path is None:
                raise TaskFailed(f"{step.description} needs {step.tool}, which is not available.")
            try:
                argv = resolve_argv(step.argv, values)
            except KeyError as exc:
                raise TaskFailed(
                    f"{step.description}: the value {exc.args[0]} is missing."
                ) from exc
            parser = ProgressParser()
            stderr: deque[str] = deque(maxlen=_STDERR_LINES)

            def on_stdout(line: str, parser: ProgressParser = parser) -> None:
                block = parser.feed(line)
                if block is not None:
                    progress = tracker.update(block, mono=time.monotonic(), wall=time.time())
                    tctx.progress(progress.percent)

            result = await run_streaming(
                [str(info.path), *argv],
                on_stdout_line=on_stdout,
                on_stderr_line=stderr.append,
                cancel=tctx.cancel,
                extra_env=info.env or None,
            )
            if result.cancelled:
                raise asyncio.CancelledError
            if not result.ok:
                raise TaskFailed(f"{step.description} failed: {failure_text(result, stderr)}.")
            if step.measures:
                _measure(step.measures, result.stderr_text, values, step.description)
            tctx.progress(tracker.step_done().percent)
    finally:
        for leftover in leftovers:
            with contextlib.suppress(OSError):
                leftover.unlink(missing_ok=True)


async def _file_call[*A](what: str, fn: Callable[[*A], object], *args: *A) -> None:
    """A blocking file call in a thread; an ``OSError`` fails the task with ``what``."""
    try:
        await asyncio.to_thread(fn, *args)
    except OSError as exc:
        raise TaskFailed(f"{what}: {exc}.") from exc


def _measure(measures: list[Measurement], stderr: str, values: dict[str, str], what: str) -> None:
    """Store an ``analyse`` step's ``loudnorm`` measurements (as the queue runner does)."""
    try:
        blocks = loudnorm.parse_blocks(stderr)
        if len(blocks) != len(measures):
            raise TaskFailed(
                f"{what} printed {len(blocks)} loudnorm result(s), {len(measures)} expected."
            )
        for measurement, block in zip(measures, blocks, strict=True):
            clamped, _notes = loudnorm.clamp(block)
            for key, value in clamped.items():
                values[f"{measurement.id}.{key}"] = value
    except loudnorm.MeasureError as exc:
        raise TaskFailed(f"{what} failed: {exc}.") from exc
