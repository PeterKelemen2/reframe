"""The clocks of the queue, behind one small interface that tests replace.

Across a system sleep, :meth:`Clock.monotonic` stops on Linux and may count the sleep on
Windows, while :meth:`Clock.wall` always counts it. The progress tracker and the watchdog use
both to tell a slow encode from one that did not run.
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
