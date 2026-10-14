"""The clocks of the queue, behind one small interface that tests replace.

Two clocks are needed because a system sleep looks different on each OS
(decision 0016, "ETA that survives a system sleep"):

- :meth:`Clock.monotonic` never goes back. On Linux (``CLOCK_MONOTONIC``) it **stops**
  while the system is suspended; on Windows it may count the suspended time.
- :meth:`Clock.wall` is ``time.time()``: it always counts the suspended time (and jumps when
  the user or NTP sets the clock).

The progress tracker and the watchdog use both to tell an encode that is slow from one that
did not run (the system slept, or the job was paused).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol

__all__ = ["Clock", "SystemClock"]


class Clock(Protocol):
    def monotonic(self) -> float:
        """Seconds of a clock that never goes back (``time.monotonic()``)."""
        ...

    def wall(self) -> float:
        """Seconds since the epoch (``time.time()``)."""
        ...

    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""
        ...


class SystemClock:
    """The real clocks."""

    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def now(self) -> datetime:
        return datetime.now(UTC)
