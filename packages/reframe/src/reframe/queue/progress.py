"""Progress of a running job: ``-progress`` blocks, weighted percent, speed, frame rate and ETA.

The percent never goes back, even when a step restarts its clock or a block arrives out of
order. FFmpeg's own speed and fps average since the process started, on the wall clock, so they
fall after a pause. The tracker measures its own over active time only (no pause, no system
sleep, no gap between blocks), and the ETA uses the same active time, so a pause or a sleep
does not make it jump.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from reframe.models.plan import PlanStep, StepKind
from reframe.models.queue import JobProgress

__all__ = [
    "MAX_INTERVAL",
    "PROGRESS_KEYS",
    "SLEEP_GAP",
    "SMOOTHING",
    "ProgressBlock",
    "ProgressParser",
    "ProgressTracker",
]

#: Keys of a ``-progress`` block (``stream_*`` keys are accepted too). A stdout line with
#: another key is not progress.
PROGRESS_KEYS = frozenset(
    {
        "frame",
        "fps",
        "bitrate",
        "total_size",
        "out_time_us",
        "out_time_ms",
        "out_time",
        "dup_frames",
        "drop_frames",
        "speed",
        "progress",
    }
)
#: Seconds by which the wall clock may run ahead of the monotonic clock between two blocks
#: before the interval counts as a system sleep (Linux: the monotonic clock stops).
SLEEP_GAP = 2.0
#: A longer interval between two blocks counts as a gap: FFmpeg prints a block every
#: ``-stats_period`` even when no frame comes out, so a longer gap means the process did not run.
MAX_INTERVAL = 30.0
#: Time constant (seconds of active time) of the smoothed speed, frame rate and rate.
SMOOTHING = 8.0
#: Steps whose ``frame`` and ``fps`` mean video frames.
_VIDEO_STEPS: frozenset[StepKind] = frozenset({"pass1", "pass2", "encode"})


@dataclass(frozen=True, slots=True)
class ProgressBlock:
    """One ``-progress`` block. ``None`` = ``N/A`` or not printed."""

    out_time: float | None = None
    """Seconds of output written (``out_time_us``); a negative value is read as 0."""
    frame: int | None = None
    fps: float | None = None
    speed: float | None = None
    total_size: int | None = None
    end: bool = False
    """``progress=end``: the step's last block."""


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().removesuffix("x").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _integer(value: str | None) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


class ProgressParser:
    """Turns ``-progress`` lines into blocks (:meth:`feed` returns a block at ``progress=``)."""

    def __init__(self) -> None:
        self._fields: dict[str, str] = {}

    @staticmethod
    def is_progress_line(line: str) -> bool:
        key, sep, _ = line.partition("=")
        key = key.strip()
        return bool(sep) and (key in PROGRESS_KEYS or key.startswith("stream_"))

    def feed(self, line: str) -> ProgressBlock | None:
        """Read one line; at the ``progress=`` line, return the finished block."""
        if not self.is_progress_line(line):
            return None
        key, _, value = line.partition("=")
        key = key.strip()
        self._fields[key] = value.strip()
        if key != "progress":
            return None
        fields, self._fields = self._fields, {}
        out_us = _number(fields.get("out_time_us"))
        return ProgressBlock(
            out_time=None if out_us is None else max(out_us, 0.0) / 1_000_000,
            frame=_integer(fields.get("frame")),
            fps=_number(fields.get("fps")),
            speed=_number(fields.get("speed")),
            total_size=_integer(fields.get("total_size")),
            end=fields.get("progress") == "end",
        )


@dataclass(slots=True)
class _Anchor:
    mono: float
    wall: float
    media: float | None
    frame: int | None
    percent: float


def _smooth(old: float | None, new: float, interval: float) -> float:
    if old is None:
        return new
    alpha = 1.0 - math.exp(-interval / SMOOTHING)
    return old + alpha * (new - old)


class ProgressTracker:
    """Percent, speed, frame rate and ETA of one job run.

    Pure: the caller passes the clock readings (``mono``, ``wall``) with every block, so
    tests can make the clocks jump.
    """

    def __init__(self, steps: Sequence[PlanStep], expected_duration: float) -> None:
        self._kinds = [step.kind for step in steps]
        weights = [max(step.progress_weight, 0.0) for step in steps]
        total = sum(weights)
        if total > 0:
            shares = [w / total for w in weights]
        else:  # no weights: every step counts the same
            shares = [1.0 / len(steps)] * len(steps) if steps else []
        self._shares = shares
        self._starts = [sum(shares[:i]) for i in range(len(shares))]
        self._duration = expected_duration
        self._step = 0
        self._percent = 0.0
        self._anchor: _Anchor | None = None
        self._speed: float | None = None
        self._fps: float | None = None
        self._rate: float | None = None
        """Smoothed percent per active second (all steps)."""
        self._clean = True
        """No pause or gap in the current step: FFmpeg's own averages are still right."""
        self._ffmpeg_speed: float | None = None
        self._ffmpeg_fps: float | None = None
        self._size: int | None = None
        self.active_time = 0.0
        """Seconds of the intervals used for the rate (not paused, no sleep)."""

    @property
    def percent(self) -> float:
        return self._percent

    def start_step(self, index: int) -> JobProgress:
        """Step ``index`` starts: its share begins (the previous steps count as done)."""
        self._step = index
        if index < len(self._starts):
            self._raise_percent(100.0 * self._starts[index])
        self._anchor = None
        self._speed = self._fps = None
        self._ffmpeg_speed = self._ffmpeg_fps = None
        self._clean = True
        return self.snapshot()

    def step_done(self) -> JobProgress:
        """The current step ended: its whole share counts."""
        if self._step < len(self._starts):
            end = self._starts[self._step] + self._shares[self._step]
            self._raise_percent(100.0 * end)
        return self.snapshot()

    def finish(self) -> JobProgress:
        """The job is done: 100 %, nothing left."""
        self._percent = 100.0
        return self.snapshot()

    def pause(self) -> None:
        """The job is paused: the time until :meth:`resume` is not active time."""
        self._anchor = None
        self._clean = False

    def resume(self) -> None:
        """The job continues: the next block only sets the new reference point."""
        self._anchor = None
        self._clean = False

    def update(self, block: ProgressBlock, *, mono: float, wall: float) -> JobProgress:
        """Read one block of the current step."""
        fraction: float | None = None
        if block.end:
            fraction = 1.0
        elif block.out_time is not None and self._duration > 0:
            fraction = min(block.out_time / self._duration, 1.0)
        if fraction is not None and self._step < len(self._starts):
            share = self._shares[self._step]
            self._raise_percent(100.0 * (self._starts[self._step] + share * fraction))
        if block.total_size is not None and block.total_size > 0:
            self._size = block.total_size
        self._ffmpeg_speed = block.speed
        self._ffmpeg_fps = block.fps
        video = self._step < len(self._kinds) and self._kinds[self._step] in _VIDEO_STEPS
        frame = block.frame if video else None
        anchor = self._anchor
        self._anchor = _Anchor(mono, wall, block.out_time, frame, self._percent)
        if anchor is None:
            return self.snapshot()
        interval = mono - anchor.mono
        slept = abs((wall - anchor.wall) - interval) > SLEEP_GAP
        if interval <= 0 or interval > MAX_INTERVAL or slept:
            self._clean = False  # a gap: keep the old estimates, measure from here
            return self.snapshot()
        self.active_time += interval
        if block.out_time is not None and anchor.media is not None:
            speed = max(block.out_time - anchor.media, 0.0) / interval
            self._speed = _smooth(self._speed, speed, interval)
        if frame is not None and anchor.frame is not None:
            fps = max(frame - anchor.frame, 0) / interval
            self._fps = _smooth(self._fps, fps, interval)
        rate = max(self._percent - anchor.percent, 0.0) / interval
        self._rate = _smooth(self._rate, rate, interval)
        return self.snapshot()

    def snapshot(self) -> JobProgress:
        speed = self._speed
        fps = self._fps
        if self._clean:  # before the second block of a step: FFmpeg's averages are right
            speed = speed if speed is not None else self._ffmpeg_speed
            if self._step < len(self._kinds) and self._kinds[self._step] in _VIDEO_STEPS:
                fps = fps if fps is not None else self._ffmpeg_fps
        eta: float | None = None
        if self._percent >= 100.0:
            eta = 0.0
        elif self._rate is not None and self._rate > 1e-9:
            eta = (100.0 - self._percent) / self._rate
        kind = self._kinds[self._step] if self._step < len(self._kinds) else None
        return JobProgress(
            percent=round(min(self._percent, 100.0), 3),
            fps=None if fps is None else round(max(fps, 0.0), 3),
            speed=None if speed is None else round(max(speed, 0.0), 4),
            eta=None if eta is None else round(max(eta, 0.0), 1),
            output_size=self._size,
            step=self._step,
            step_count=max(len(self._kinds), 1),
            step_kind=kind,
        )

    def _raise_percent(self, value: float) -> None:
        self._percent = max(self._percent, min(value, 100.0))
