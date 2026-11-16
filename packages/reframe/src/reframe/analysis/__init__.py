"""The bit rate, subtitle and loudness scans of a source. Each function starts a background
task (:mod:`reframe.tasks`) with the facade's :class:`~reframe.mediatask.MediaTaskContext` and
returns its :class:`~reframe.models.TaskInfo` at once. The signatures are the contract in
``docs/core-breakdown.md``. Each task runs its processes through
:func:`reframe.tools.run_streaming` with the task's cancel token, so a cancel kills them at
once. An expected failure (a missing file, an unusable tool, a stream that does not exist or
has the wrong type) ends the task ``failed`` with a message for the user. Why the commands are
what they are: ``testdata/README.md``, "Analysis scans".
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from reframe.analysis import bitrate, loudness, subtitles
from reframe.mediatask import MediaTaskContext
from reframe.models.analysis import BitrateScan, LoudnessMeasurement, SubtitleScan
from reframe.models.tasks import TaskInfo
from reframe.tasks import TaskContext

__all__ = ["start_bitrate_scan", "start_loudness_scan", "start_subtitle_scan"]


def start_bitrate_scan(ctx: MediaTaskContext, path: Path, stream_index: int) -> TaskInfo:
    """The average bit rate of one stream, from its packet sizes
    (:class:`~reframe.models.BitrateScan`). When done, the measured bit rate is stored in the
    known source (``ctx.sources.update``)."""

    async def work(task: TaskContext) -> BitrateScan:
        return await bitrate.scan(ctx, path, stream_index, task)

    return ctx.tasks.start(
        "bitrate_scan", work, message=f"Measure the bit rate of stream {stream_index}"
    )


def start_subtitle_scan(
    ctx: MediaTaskContext, path: Path, stream_indexes: Sequence[int] | None
) -> TaskInfo:
    """Event counts of the subtitle tracks (all when ``stream_indexes`` is ``None``), and the
    forced events of PGS and VobSub tracks (:class:`~reframe.models.SubtitleScan`). When done,
    the counts are stored in the known source (``ctx.sources.update``)."""
    wanted = None if stream_indexes is None else list(stream_indexes)

    async def work(task: TaskContext) -> SubtitleScan:
        return await subtitles.scan(ctx, path, wanted, task)

    return ctx.tasks.start("subtitle_scan", work, message="Count the subtitle events")


def start_loudness_scan(
    ctx: MediaTaskContext,
    path: Path,
    stream_index: int,
    *,
    start: float | None,
    duration: float | None,
) -> TaskInfo:
    """The loudness of one audio track (EBU R128, ``loudnorm``): the whole track, or
    ``duration`` seconds from ``start`` (:class:`~reframe.models.LoudnessMeasurement`)."""

    async def work(task: TaskContext) -> LoudnessMeasurement:
        return await loudness.scan(ctx, path, stream_index, task, start=start, duration=duration)

    return ctx.tasks.start(
        "loudness", work, message=f"Measure the loudness of stream {stream_index}"
    )
