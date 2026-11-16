"""Per-job logs: the file ``<data dir>/logs/<job id>.log`` and the ``job.log`` events.

The file gets every line of every run. Events are batched (see :data:`EVENT_INTERVAL` and
:data:`EVENT_LINES`): a line that does not fit in an event is counted in ``JobLogEvent.dropped``
and is still in the file. A file that cannot be written does not stop the job.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TextIO

from reframe.events import EventBus
from reframe.models.events import JobLogEvent
from reframe.queue.errors import printable

__all__ = ["EVENT_INTERVAL", "EVENT_LINES", "JobLog", "log_file"]

log = logging.getLogger(__name__)

#: Seconds between two ``job.log`` events of one job.
EVENT_INTERVAL = 0.25
#: Lines per ``job.log`` event at most.
EVENT_LINES = 200


def log_file(data_dir: Path, job_id: str) -> Path:
    """``<data dir>/logs/<job id>.log``."""
    return data_dir / "logs" / f"{job_id}.log"


class JobLog:
    """The log of one run of one job (file + events). Use on the event loop only."""

    def __init__(
        self,
        path: Path,
        job_id: str,
        events: EventBus,
        *,
        interval: float = EVENT_INTERVAL,
        max_lines: int = EVENT_LINES,
    ) -> None:
        self.path = path
        self._job_id = job_id
        self._events = events
        self._interval = interval
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._dropped = 0
        self._handle: TextIO | None = None
        self._broken = False
        self._timer: asyncio.TimerHandle | None = None

    def open(self, header: str) -> None:
        """Open the file for appending and write a run header."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(  # noqa: SIM115
                self.path, "a", encoding="utf-8", errors="backslashreplace", newline="\n"
            )
        except OSError as exc:
            self._fail(exc)
        self.write(header)

    def write(self, text: str) -> None:
        """One or more lines: to the file, and to the next ``job.log`` event."""
        for line in text.splitlines() or [""]:
            self._to_file(line)
            self._to_event(line)

    def note(self, text: str) -> None:
        """A line of Reframe's own, with the local time in front."""
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.write(f"[{stamp}] {text}")

    def flush_events(self) -> None:
        """Publish the waiting lines now (at the end of a run)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._buffer and not self._dropped:
            return
        lines, dropped = list(self._buffer), self._dropped
        self._buffer.clear()
        self._dropped = 0
        self._events.publish(JobLogEvent(job_id=self._job_id, lines=lines, dropped=dropped))

    def close(self) -> None:
        self.flush_events()
        handle, self._handle = self._handle, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()

    def _to_file(self, line: str) -> None:
        if self._handle is None:
            return
        try:
            self._handle.write(line + "\n")
        except OSError as exc:
            self._fail(exc)

    def flush_file(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.flush()
        except OSError as exc:
            self._fail(exc)

    def _to_event(self, line: str) -> None:
        if len(self._buffer) == self._buffer.maxlen:
            self._dropped += 1  # the deque drops the oldest line
        self._buffer.append(printable(line))
        if self._timer is None:
            loop = asyncio.get_running_loop()
            self._timer = loop.call_later(self._interval, self._timed_flush)

    def _timed_flush(self) -> None:
        self._timer = None
        self.flush_file()  # other processes read the file while the job runs
        self.flush_events()

    def _fail(self, exc: OSError) -> None:
        if not self._broken:
            self._broken = True
            log.warning("job log %s cannot be written: %s", self.path, exc)
        handle, self._handle = self._handle, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()
