"""Loudness measure (05 §C-10): EBU R128 values of one audio track with FFmpeg's ``loudnorm``.

**Command** (the same measurement as the ``analyse`` step of a job, C-7 / decision 0013, with
loudnorm's default targets: the ``input_*`` values do not depend on them)::

    ffmpeg -hide_banner -nostdin -nostats -progress pipe:1 [-ss <start>] -i <file> \\
        [-t <duration>] -map 0:<index> -filter:a loudnorm=print_format=json -f null -

loudnorm prints one JSON block on stderr at the end (:func:`reframe.queue.loudnorm.parse_blocks`
finds it). Values: ``input_i`` (integrated, LUFS), ``input_tp`` (true peak, dBTP),
``input_lra`` (loudness range, LU), ``input_thresh`` (gating threshold, LUFS). A silent track
measures ``-inf`` (``testdata/README.md``, C-11), which is ``None`` in the result.

**Progress**: ``out_time`` of the ``-progress`` blocks against the measured length (the
``duration`` asked for, else the stream's duration minus ``start``). When no block has an
``out_time`` above 0, nothing was decoded (a ``start`` after the end): ffmpeg exits with 0 and
loudnorm prints the values of silence, so the task fails instead.
"""

from __future__ import annotations

import math
from pathlib import Path

from reframe.analysis.common import ProgressReporter, check_run, find_stream, stream_duration
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models.analysis import LoudnessMeasurement
from reframe.models.media import AudioStream
from reframe.queue.loudnorm import MeasureError, parse_blocks
from reframe.queue.progress import ProgressParser
from reframe.tasks import TaskContext
from reframe.tools import run_streaming

__all__ = ["KEYS", "measure_argv", "parse_measurement", "scan", "seconds"]

#: Result field ← loudnorm key.
KEYS = {
    "integrated": "input_i",
    "true_peak": "input_tp",
    "lra": "input_lra",
    "threshold": "input_thresh",
}


def _value(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise MeasureError(f"loudnorm printed {text!r}, not a number") from exc
    return value if math.isfinite(value) else None


def parse_measurement(stderr: str) -> dict[str, float | None]:
    """The values of the last loudnorm block in ``stderr`` (``-inf`` / ``inf`` / ``nan`` →
    ``None``). :class:`MeasureError` when there is no block."""
    blocks = parse_blocks(stderr)
    if not blocks:
        raise MeasureError("loudnorm printed no measurement")
    block = blocks[-1]
    values = {field: _value(block.get(key)) for field, key in KEYS.items()}
    lra = values["lra"]
    if lra is not None and lra < 0:  # never seen; the model only takes LRA >= 0
        values["lra"] = None
    return values


def seconds(value: float) -> str:
    """``12.5`` → ``12.5``, ``3.0`` → ``3``: FFmpeg's time syntax (no exponent)."""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def measure_argv(
    ffmpeg: str, path: Path, stream_index: int, start: float | None, duration: float | None
) -> list[str]:
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1"]
    if start:
        argv += ["-ss", seconds(start)]
    argv += ["-i", str(path)]
    if duration is not None:
        argv += ["-t", seconds(duration)]
    argv += ["-map", f"0:{stream_index}", "-filter:a", "loudnorm=print_format=json"]
    return [*argv, "-f", "null", "-"]


async def scan(
    ctx: MediaTaskContext,
    path: Path,
    stream_index: int,
    task: TaskContext,
    *,
    start: float | None,
    duration: float | None,
) -> LoudnessMeasurement:
    """The body of the ``loudness`` task."""
    if start is not None and (not math.isfinite(start) or start < 0):
        raise TaskFailed(f"The start of the measurement must be 0 or more seconds, not {start}.")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise TaskFailed(f"The length of the measurement must be more than 0 s, not {duration}.")
    task.progress(None, "Waiting for the probe")
    ffmpeg = await require_tool(ctx, "ffmpeg")
    source = await require_source(ctx, path, cancel=task.cancel)
    stream = find_stream(source, stream_index)
    if stream is None:
        raise TaskFailed(f"{path.name} has no stream {stream_index}.")
    if not isinstance(stream, AudioStream):
        raise TaskFailed(
            f"Stream {stream_index} of {path.name} is a {stream.kind} stream, not an audio stream."
        )
    length = duration
    total = stream_duration(source, stream)
    if length is None and total is not None:
        length = max(total - (start or 0.0), 0.0)
    message = f"Measuring the loudness of stream {stream_index}"
    reporter = ProgressReporter(task.progress)
    parser = ProgressParser()
    measured = 0.0
    task.progress(0.0, message)

    def on_progress(line: str) -> None:
        nonlocal measured
        block = parser.feed(line)
        if block is None or block.out_time is None:
            return
        measured = max(measured, block.out_time)
        if length:
            reporter.update(100.0 * block.out_time / length, message)

    assert ffmpeg.path is not None
    result = await run_streaming(
        measure_argv(str(ffmpeg.path), path, stream_index, start, duration),
        on_stdout_line=on_progress,
        on_stderr_line=None,
        cancel=task.cancel,
    )
    check_run(result, "ffmpeg", path)
    if measured <= 0:
        # Nothing was decoded (a start after the end): loudnorm still prints -inf values.
        raise TaskFailed(
            f"Stream {stream_index} of {path.name} has no audio in the part to measure."
        )
    try:
        values = parse_measurement(result.stderr_text)
    except MeasureError as exc:
        raise TaskFailed(
            f"The loudness of stream {stream_index} could not be measured: {exc}"
        ) from exc
    return LoudnessMeasurement(
        path=path,
        stream_index=stream_index,
        integrated=values["integrated"],
        true_peak=values["true_peak"],
        lra=values["lra"],
        threshold=values["threshold"],
        start=start,
        duration=duration,
    )
