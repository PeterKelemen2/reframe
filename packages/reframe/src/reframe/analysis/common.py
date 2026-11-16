"""Helpers shared by the analysis tasks: the stream lookup, failure messages, throttled
progress, the ``key=value`` lines of ffprobe's ``compact`` output."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from pathlib import Path

from reframe.mediatask import TaskFailed
from reframe.models.media import AudioStream, MediaSource, SubtitleStream, VideoStream
from reframe.models.tools import ToolInfo
from reframe.tasks import TaskContext
from reframe.tools import RunResult, run_streaming

__all__ = [
    "PROGRESS_INTERVAL",
    "ProgressReporter",
    "check_run",
    "fields",
    "find_stream",
    "number",
    "run_scan",
    "stream_duration",
]

#: Seconds between two progress reports (besides every whole percent).
PROGRESS_INTERVAL = 0.5

Stream = VideoStream | AudioStream | SubtitleStream


def find_stream(source: MediaSource, index: int) -> Stream | None:
    """The video, audio or subtitle stream with absolute index ``index``."""
    streams: list[Stream] = [*source.video, *source.audio, *source.subtitles]
    for stream in streams:
        if stream.index == index:
            return stream
    return None


def stream_duration(source: MediaSource, stream: Stream | None) -> float | None:
    """The stream's duration, else the container's (seconds); ``None`` when unknown."""
    for value in (stream.duration if stream is not None else None, source.container.duration):
        if value is not None and value > 0:
            return value
    return None


def fields(line: str) -> dict[str, str]:
    """``key=value|key=value`` (ffprobe ``-of compact=p=0``) → a dict. Pieces without ``=``
    are left out."""
    out: dict[str, str] = {}
    for piece in line.strip().split("|"):
        key, sep, value = piece.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def number(text: str | None) -> float | None:
    """A finite float, or ``None`` for a missing value, ``N/A`` or junk."""
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _detail(result: RunResult) -> str | None:
    lines = [line.strip() for line in result.stderr_text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def check_run(result: RunResult, tool: str, path: Path) -> None:
    """:class:`TaskFailed` with a message for the user when ``result`` is not a clean exit;
    ``asyncio.CancelledError`` when it was cancelled (the task manager records the cancel)."""
    if result.cancelled:
        raise asyncio.CancelledError
    if result.error is not None:
        raise TaskFailed(f"{tool} could not be started: {result.error}")
    if result.timed_out:
        raise TaskFailed(f"{tool} did not finish in time on {path.name}.")
    if result.returncode != 0:
        detail = _detail(result)
        suffix = f": {detail}" if detail else ""
        raise TaskFailed(f"{tool} failed on {path.name} (exit code {result.returncode}){suffix}")


async def run_scan(
    tool: ToolInfo,
    argv: Callable[[str], list[str]],
    path: Path,
    task: TaskContext,
    on_line: Callable[[str], None],
) -> RunResult:
    """Run ``tool`` with ``argv(program)``, feed its stdout lines to ``on_line``, and raise
    :class:`TaskFailed` unless it exits cleanly."""
    assert tool.path is not None  # require_tool returns found tools only
    result = await run_streaming(
        argv(str(tool.path)),
        on_stdout_line=on_line,
        on_stderr_line=None,
        cancel=task.cancel,
        extra_env=tool.env or None,
    )
    check_run(result, tool.name, path)
    return result


class ProgressReporter:
    """Calls ``report(percent, message)`` when the percent passes a whole number or
    :data:`PROGRESS_INTERVAL` seconds have passed, never more often (an FFmpeg run can print
    thousands of lines per second)."""

    def __init__(
        self,
        report: Callable[[float | None, str | None], None],
        *,
        interval: float = PROGRESS_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._report = report
        self._interval = interval
        self._clock = clock
        self._last_percent: float | None = None
        self._last_time = -math.inf

    def update(self, percent: float, message: str | None = None) -> None:
        percent = min(max(percent, 0.0), 100.0)
        now = self._clock()
        step = self._last_percent is None or int(percent) > int(self._last_percent)
        if not step and now - self._last_time < self._interval:
            return
        if self._last_percent is not None and percent <= self._last_percent:
            return
        self._last_percent = percent
        self._last_time = now
        self._report(percent, message)
