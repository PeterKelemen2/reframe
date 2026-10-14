"""The step watchdog (decision 0016, "Timeouts"): a stall check for FFmpeg steps and a time
limit for short steps, both counted in **active** time.

An encode has no wall-clock limit: a 4K AV1 encode can take a day. What the watchdog catches
is a step that hangs: no change in its ``-progress`` values, no line on stderr, and almost no
CPU time used by its process tree (less than :data:`CPU_SHARE` of one core) for
``stall_after`` seconds. FFmpeg ≥ 7 prints a progress block every 0.5 s even while no frame
comes out, so "no output" alone never happens for a live FFmpeg; the CPU check keeps a slow
encoder with a long look-ahead (no new frame for minutes, all cores busy) from being killed.

Sleep-aware: the caller ticks every few seconds and each tick counts at most ``max_tick``
seconds, so a system sleep (the event loop did not run) adds one short tick, whatever the
clocks say. Paused time does not count, and a pause resets the idle time.

:class:`StepWatch` is pure (the caller passes the clock and CPU readings); the queue runs it
in a small loop next to each step.
"""

from __future__ import annotations

import contextlib
from typing import Literal

import psutil

__all__ = [
    "CPU_SHARE",
    "STALL_AFTER",
    "STEP_TIME_LIMIT",
    "TICK",
    "StepWatch",
    "Verdict",
    "tree_cpu_seconds",
]

#: Seconds of active time without progress, output or CPU use before an FFmpeg step counts as
#: stalled.
STALL_AFTER = 600.0
#: Seconds of active time a short step (``mkvpropedit``) may take.
STEP_TIME_LIMIT = 300.0
#: Seconds between two watchdog ticks.
TICK = 5.0
#: A tree that used less CPU time than this share of the tick (of one core) is idle.
CPU_SHARE = 0.05

Verdict = Literal["stalled", "timeout"]


class StepWatch:
    """Idle and active time of one running step."""

    def __init__(
        self,
        *,
        stall_after: float | None,
        time_limit: float | None,
        max_tick: float,
        cpu_share: float = CPU_SHARE,
    ) -> None:
        self.stall_after = stall_after
        self.time_limit = time_limit
        self._max_tick = max_tick
        self._cpu_share = cpu_share
        self._last: float | None = None
        self._last_cpu: float | None = None
        self._activity = False
        self.idle = 0.0
        """Active seconds since the last progress, output or CPU use."""
        self.active = 0.0
        """Active seconds since the step started (pauses and sleeps not counted)."""

    def activity(self) -> None:
        """The step made progress or printed a line."""
        self._activity = True

    def tick(self, mono: float, cpu: float | None, *, paused: bool) -> Verdict | None:
        """One tick: ``mono`` from the monotonic clock, ``cpu`` the tree's CPU seconds (``None``
        when unknown). Returns why the step must be stopped, or ``None``."""
        last, last_cpu = self._last, self._last_cpu
        self._last, self._last_cpu = mono, cpu
        if last is None:
            return None
        if paused:
            self.idle = 0.0
            self._activity = False
            return None
        step = min(max(mono - last, 0.0), self._max_tick)
        self.active += step
        busy = self._activity or (
            cpu is not None and last_cpu is not None and cpu - last_cpu >= self._cpu_share * step
        )
        self._activity = False
        self.idle = 0.0 if busy else self.idle + step
        if self.time_limit is not None and self.active >= self.time_limit:
            return "timeout"
        if self.stall_after is not None and self.idle >= self.stall_after:
            return "stalled"
        return None


def tree_cpu_seconds(pid: int) -> float | None:
    """User + system CPU seconds of ``pid`` and its descendants; ``None`` when it is gone."""
    try:
        root = psutil.Process(pid)
        times = root.cpu_times()
        total = times.user + times.system
        children = root.children(recursive=True)
    except psutil.Error:
        return None
    for child in children:
        with contextlib.suppress(psutil.Error):
            child_times = child.cpu_times()
            total += child_times.user + child_times.system
    return total
