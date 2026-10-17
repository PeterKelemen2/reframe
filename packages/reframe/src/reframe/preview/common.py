"""Helpers shared by the preview tasks: timestamps, tool identity, failure texts, PNG size."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from pathlib import Path

from reframe.mediatask import TaskFailed, sample_timestamps
from reframe.models import MediaSource, ToolInfo, VideoStream
from reframe.preview.cache import MAX_TIMESTAMP_MS
from reframe.queue.errors import exit_text, stderr_reason
from reframe.tools import RunResult

__all__ = [
    "MAX_FRAMES",
    "displayed_size",
    "failure_text",
    "png_size",
    "sample_duration",
    "sample_times",
    "seconds",
    "tool_identity",
]

#: The most frames (or crop samples) one task makes.
MAX_FRAMES = 1000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sample_duration(source: MediaSource, video: VideoStream) -> float | None:
    """The duration the sample frames are spread over: the video stream's (a longer audio
    track must not put a sample after the last picture), else the container's."""
    return video.duration or source.container.duration


def seconds(milliseconds: int) -> float:
    return milliseconds / 1000


def sample_times(
    source: MediaSource,
    video: VideoStream,
    *,
    count: int,
    timestamps: Sequence[float] | None = None,
) -> list[float]:
    """The timestamps of a task: ``timestamps`` (sorted, rounded to milliseconds, without
    duplicates), else ``count`` evenly spaced ones (:func:`~reframe.mediatask.
    sample_timestamps`, the same for frames and crop detection). :class:`TaskFailed` for
    times that are not a time in the source (also a time later than a frame key can hold,
    :data:`~reframe.preview.cache.MAX_TIMESTAMP_MS`), a count out of range, or an unknown
    duration."""
    name = source.ref.path.name
    if timestamps is not None:
        values = list(timestamps)
        if not values:
            raise TaskFailed("No timestamps were given.")
    else:
        if not 1 <= count <= MAX_FRAMES:
            raise TaskFailed(f"The number of frames must be 1 to {MAX_FRAMES}, not {count}.")
        values = sample_timestamps(sample_duration(source, video), count)
        if not values:
            raise TaskFailed(
                f"The duration of {name} is not known: give the timestamps of the frames."
            )
    for value in values:
        if not math.isfinite(value) or value < 0:
            raise TaskFailed(f"{value} is not a time in {name} (seconds from 0).")
        # Compared before rounding: round(1e308 * 1000) would overflow.
        if value * 1000 >= MAX_TIMESTAMP_MS + 0.5:
            raise TaskFailed(
                f"{value:g} is not a time in {name} (frames can be taken up to "
                f"{MAX_TIMESTAMP_MS / 1000:.3f} s)."
            )
    if len(values) > MAX_FRAMES:
        raise TaskFailed(f"At most {MAX_FRAMES} frames can be made at once, not {len(values)}.")
    return [seconds(ms) for ms in sorted({round(value * 1000) for value in values})]


def tool_identity(info: ToolInfo) -> list[object]:
    """What identifies an FFmpeg build in a cache key: its path, version and library
    versions (another build can decode or filter differently)."""
    return [str(info.path), info.version, sorted(info.library_versions.items())]


def failure_text(result: RunResult, stderr_lines: Sequence[str] | None = None) -> str:
    """Why a run gave no result, for a note or a task error."""
    if result.error is not None:
        return f"FFmpeg could not start: {result.error}"
    if result.timed_out:
        return "FFmpeg took too long and was stopped"
    lines = list(stderr_lines) if stderr_lines is not None else result.stderr_text.splitlines()
    if result.returncode == 0:
        return "FFmpeg gave no picture at this time (after the last frame?)"
    reason = stderr_reason(lines)
    failed = f"FFmpeg failed ({exit_text(result.returncode)})"
    return f"{failed}: {reason}" if reason else failed


def png_size(path: Path) -> tuple[int, int] | None:
    """Width and height from a PNG's header, ``None`` when the file is not a PNG."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return (width, height) if width > 0 and height > 0 else None


def displayed_size(video: VideoStream) -> tuple[int, int]:
    """The picture size as FFmpeg decodes it: the automatic rotation of a 90° or 270° display
    matrix swaps width and height (decision 0009)."""
    if video.rotation in (90, 270):
        return video.height, video.width
    return video.width, video.height
