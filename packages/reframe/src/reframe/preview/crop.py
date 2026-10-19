"""The ``cropdetect`` task: FFmpeg ``cropdetect`` on each sample frame, then the crop consensus.

A black frame, or one that could not be decoded, does not vote.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from reframe.command.video import format_number
from reframe.dimensions import crop_agreement, detect_crop_consensus
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models import CropRect
from reframe.models.preview import CropDetection, CropSample
from reframe.preview.common import displayed_size, failure_text, sample_times
from reframe.tasks import TaskContext
from reframe.tools import run

__all__ = ["CROPDETECT", "RUN_TIMEOUT", "detect_crop", "parse_cropdetect"]

CROPDETECT = "cropdetect=limit=0.094118:round=2:skip=0"
#: Seconds one sample may take.
RUN_TIMEOUT = 300.0
_STDERR_LIMIT = 1024 * 1024
_LINE = re.compile(r"\[Parsed_cropdetect_\d+ @ [^\]]*\].*?\bcrop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)")


def parse_cropdetect(stderr: str, width: int, height: int) -> tuple[bool, CropRect | None]:
    """The first ``cropdetect`` result in FFmpeg's log: ``(False, None)`` when there is none
    (no frame was decoded), ``(True, None)`` for a black frame, else ``(True, rect)`` for a
    ``width`` x ``height`` picture."""
    for line in stderr.splitlines():
        match = _LINE.search(line)
        if match is None:
            continue
        w, h, x, y = (int(v) for v in match.groups())
        if w <= 0 or h <= 0 or x < 0 or y < 0:
            return True, None
        return True, CropRect(
            top=y,
            bottom=max(0, height - y - h),
            left=x,
            right=max(0, width - x - w),
        )
    return False, None


def _edges(rect: CropRect) -> str:
    return f"{rect.top} / {rect.bottom} / {rect.left} / {rect.right}"


async def detect_crop(
    tctx: TaskContext, ctx: MediaTaskContext, path: Path, *, count: int | None
) -> CropDetection:
    """Detect the crop of ``path`` from its sample frames; expected failures raise
    :class:`TaskFailed`."""
    ffmpeg = await require_tool(ctx, "ffmpeg")
    assert ffmpeg.path is not None
    source = await require_source(ctx, path, cancel=tctx.cancel)
    if not source.video:
        raise TaskFailed(f"{path.name} has no video stream.")
    video = source.video[0]
    settings = ctx.settings()
    times = sample_times(
        source, video, count=settings.preview.sample_frames if count is None else count
    )
    width, height = displayed_size(video)
    samples: list[CropSample] = []
    notes: list[str] = []
    failures: list[str] = []
    black = 0
    for done, timestamp in enumerate(times, start=1):
        argv = [
            str(ffmpeg.path), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info",
            "-ss", format_number(timestamp), "-i", str(path), "-map", f"0:{video.index}",
            "-frames:v", "1", "-vf", CROPDETECT, "-f", "null", "-",
        ]  # fmt: skip
        result = await run(
            argv,
            timeout=RUN_TIMEOUT,
            cancel=tctx.cancel,
            extra_env=ffmpeg.env or None,
            max_output=_STDERR_LIMIT,
        )
        if result.cancelled:
            break
        found, rect = parse_cropdetect(result.stderr_text, width, height)
        if not result.ok or not found:
            failures.append(f"{timestamp:.3f} s: {failure_text(result)}")
            rect = None
        elif rect is None:
            black += 1
        samples.append(CropSample(timestamp=timestamp, crop=rect))
        tctx.progress(done=done, total=len(times), message=f"Frame {done} of {len(times)}")
    if tctx.cancel.cancelled:
        raise asyncio.CancelledError
    rects = [s.crop for s in samples if s.crop is not None]
    if failures and len(failures) == len(samples):
        raise TaskFailed(f"Crop detection failed on every frame: {failures[0]}.")
    auto = detect_crop_consensus(rects, "auto")
    conservative = detect_crop_consensus(rects, "conservative")
    if black:
        notes.append(f"{black} of {len(samples)} frames are black: they do not count.")
    for failure in failures:
        notes.append(f"No result at {failure}.")
    if not rects:
        notes.append("No frame has a picture to measure: no crop.")
    elif auto != conservative:
        notes.append(
            f"The frames disagree: automatic {_edges(auto)}, conservative {_edges(conservative)} "
            "(top / bottom / left / right)."
        )
    return CropDetection(
        path=path,
        samples=samples,
        auto=auto,
        auto_frames=crop_agreement(rects, auto),
        conservative=conservative,
        notes=notes,
    )
