"""The ``frames`` task: PNG frames of a source, and of a job's output.

A timestamp without a picture is left out with a note, and the task fails only when no source
frame at all could be made. Output frames that cannot be made are left out with a note too,
and never cost the source frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from reframe.command import PlanError
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models import JobSettings, ToolInfo
from reframe.models.preview import FrameKind, FrameSet, PreviewFrame
from reframe.preview.cache import (
    PreviewCache,
    digest,
    frame_key,
    megabytes,
    source_fingerprint,
)
from reframe.preview.common import failure_text, png_size, sample_times, tool_identity
from reframe.preview.graph import FrameRecipe, frame_argv, output_recipe, source_recipe
from reframe.queue.files import same_file
from reframe.tasks import TaskContext
from reframe.tools import run

__all__ = ["RUN_TIMEOUT", "WORKERS", "make_frames"]

#: FFmpeg runs of one task at a time: more than two gain little (measured on the 4K fixture).
WORKERS = 2
#: Seconds one frame run may take (a damaged file must not hang the task).
RUN_TIMEOUT = 300.0
#: Bytes of stderr kept per run.
_STDERR_LIMIT = 256 * 1024


@dataclass(slots=True)
class _Wanted:
    recipe: FrameRecipe
    path: Path
    key: str


def _note(notes: list[str], text: str) -> None:
    if text not in notes:
        notes.append(text)


def _time(value: float) -> str:
    return f"{value:.3f} s"


async def make_frames(
    tctx: TaskContext,
    ctx: MediaTaskContext,
    path: Path,
    *,
    count: int | None,
    timestamps: list[float] | None,
    job: JobSettings | None,
) -> FrameSet:
    """Make the source frames of ``path`` and, with ``job``, its output frames. Cached
    frames are reused."""
    ffmpeg = await require_tool(ctx, "ffmpeg")
    source = await require_source(ctx, path, cancel=tctx.cancel)
    if not source.video:
        raise TaskFailed(f"{path.name} has no video stream.")
    video = source.video[0]
    if job is not None and not same_file(Path(job.source.path), path):
        raise TaskFailed(f"The job is for another file ({Path(job.source.path).name}).")
    settings = ctx.settings()
    times = sample_times(
        source,
        video,
        count=settings.preview.sample_frames if count is None else count,
        timestamps=timestamps,
    )
    caps = ctx.capabilities.snapshot
    defs = ctx.definitions()
    recipes = [source_recipe(video, caps, defs)]
    notes: list[str] = list(recipes[0].notes)
    same_picture = False  # a copied video: the output frames are the source frames
    if job is not None:
        try:
            output = output_recipe(job, source, caps, defs)
        except PlanError as exc:
            _note(notes, f"No output frames: the job's filters cannot be applied ({exc}).")
        else:
            same_picture = (output.prefix, output.chain) == (recipes[0].prefix, recipes[0].chain)
            if not same_picture:
                recipes.append(output)
            for text in output.notes:
                _note(notes, text)
    try:
        stat = await asyncio.to_thread(os.stat, path)
    except OSError as exc:
        raise TaskFailed(f"{path.name} cannot be read: {exc.strerror or exc}.") from exc
    fingerprint = source_fingerprint(path, stat)
    identity = tool_identity(ffmpeg)
    hashes = {r.kind: digest("frame", r.identity(), identity) for r in recipes}
    cache = PreviewCache(ctx.cache_dir)
    try:
        await asyncio.to_thread(cache.frames.mkdir, parents=True, exist_ok=True)
    except OSError as exc:
        raise TaskFailed(f"The frame cache cannot be written: {exc}.") from exc

    made: dict[tuple[FrameKind, float], PreviewFrame] = {}
    failures: dict[float, tuple[str, bool]] = {}  # timestamp → (why, the source frame is lost)
    gate = asyncio.Semaphore(WORKERS)
    done = 0

    async def one(timestamp: float) -> None:
        nonlocal done
        wanted = [
            _Wanted(r, cache.frame(key), key)
            for r in recipes
            for key in [frame_key(fingerprint, timestamp, hashes[r.kind])]
        ]
        missing: list[_Wanted] = []
        for item in wanted:
            size = png_size(item.path) if cache.touch(item.path) else None
            if size is None:
                missing.append(item)
            else:
                made[item.recipe.kind, timestamp] = _frame(item, timestamp, size, cached=True)
        if missing:
            async with gate:
                error, failed = await _render(tctx, ffmpeg, path, video.index, timestamp, missing)
                own = [i for i in missing if i.recipe.kind == "source"]
                if failed and own and len(missing) > 1 and png_size(own[0].path) is None:
                    # FFmpeg refused the run (the output chain, most likely): the source frame
                    # alone, so that only the output frame is lost.
                    alone, _ = await _render(tctx, ffmpeg, path, video.index, timestamp, own)
                    if alone is not None:
                        error = alone
            for item in missing:
                size = png_size(item.path)
                if size is not None:
                    made[item.recipe.kind, timestamp] = _frame(item, timestamp, size, cached=False)
            if error is not None:
                failures[timestamp] = (error, ("source", timestamp) not in made)
        done += 1
        tctx.progress(done=done, total=len(times), message=f"Frame {done} of {len(times)}")

    async with asyncio.TaskGroup() as group:
        for timestamp in times:
            group.create_task(one(timestamp))
    if tctx.cancel.cancelled:
        raise asyncio.CancelledError
    for timestamp, (error, source_lost) in sorted(failures.items()):
        what = "frame" if source_lost else "output frame"
        _note(notes, f"No {what} at {_time(timestamp)}: {error}.")
    if same_picture:
        for t in times:
            if ("source", t) in made:
                made["output", t] = made["source", t].model_copy(update={"kind": "output"})
    frames = [
        made[kind, t]
        for kind in ("source", "output")
        for t in times
        if (kind, t) in made and ("source", t) in made
    ]
    if not frames:
        reason = failures[min(failures)][0] if failures else "FFmpeg gave no picture"
        raise TaskFailed(f"No frame of {path.name} could be made: {reason}.")
    limit = megabytes(settings.preview.cache_size_mb)
    await asyncio.to_thread(cache.trim, limit, protect=[f.path for f in frames])
    return FrameSet(path=path, frames=frames, notes=notes)


def _frame(item: _Wanted, timestamp: float, size: tuple[int, int], *, cached: bool) -> PreviewFrame:
    width, height = size
    return PreviewFrame(
        key=item.key,
        kind=item.recipe.kind,
        timestamp=timestamp,
        path=item.path,
        width=width,
        height=height,
        cached=cached,
    )


async def _render(
    tctx: TaskContext,
    ffmpeg: ToolInfo,
    source: Path,
    video_index: int,
    timestamp: float,
    missing: list[_Wanted],
) -> tuple[str | None, bool]:
    """Make the missing frames of one timestamp: ``None`` when every one was made, else why
    not; and whether FFmpeg failed (it did not start, end in time or exit 0) rather than just
    gave no picture. A complete PNG is renamed to its key's name; nothing else is left
    behind."""
    assert ffmpeg.path is not None
    temps = [PreviewCache.temporary(item.path) for item in missing]
    argv = frame_argv(
        str(ffmpeg.path),
        source,
        video_index,
        timestamp,
        [(item.recipe, temp) for item, temp in zip(missing, temps, strict=True)],
    )
    try:
        result = await run(
            argv,
            timeout=RUN_TIMEOUT,
            cancel=tctx.cancel,
            extra_env=ffmpeg.env or None,
            max_output=_STDERR_LIMIT,
        )
        if result.cancelled:
            raise asyncio.CancelledError
        complete = 0
        for item, temp in zip(missing, temps, strict=True):
            if result.ok and png_size(temp) is not None and await _place(temp, item.path):
                complete += 1
        if complete == len(missing):
            return None, False
        return failure_text(result), not result.ok
    finally:
        for temp in temps:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)


async def _place(temp: Path, final: Path) -> bool:
    """Rename a complete PNG to its key's name. When that fails because another task has just
    made the same frame, its file is as good as ours."""
    try:
        await asyncio.to_thread(os.replace, temp, final)
    except OSError:
        return png_size(final) is not None
    return True
