"""The job notifications of a run and the when-done action of the queue.

The queue owns one :class:`WhenDoneActions`. A run that ended on its own (done or failed)
gets one notification when the ``notifications`` setting is on. Only such a run counts for the
when-done action.
The batch is the jobs that ended since the queue last emptied. When the queue empties after
a batch whose last run ended on its own, the action runs once, whether that job was done or
failed. A cancelled last run starts a new batch and runs nothing.

The countdown that the queue started is cancelled when new work starts and when the queue is
closed. A change of the when-done setting does not cancel it, because the setting is read
only when the queue empties. The queue cancels only its own countdown, by its id.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent, NotificationEvent, PowerAction
from reframe.models.queue import JobState, QueueJob
from reframe.models.settings import WhenDone
from reframe.platform.power import PowerService
from reframe.queue.errors import printable

__all__ = ["POWER_LABELS", "WhenDoneActions", "summary"]

log = logging.getLogger(__name__)

#: The when-done actions that the power service runs, with their names in messages.
POWER_LABELS: dict[str, tuple[PowerAction, str]] = {
    "quit": ("quit", "Quit Reframe"),
    "sleep": ("sleep", "Sleep"),
    "shutdown": ("shutdown", "Shut down"),
}

_ENDED_ON_ITS_OWN = frozenset({JobState.DONE, JobState.FAILED})


def summary(done: int, failed: int) -> str:
    """The batch summary: the failed part only when a job failed; no full stop."""
    text = f"{done} job{'s' if done != 1 else ''} done"
    if failed:
        text += f", {failed} failed"
    return text


class WhenDoneActions:
    """The batch counts, the job notifications and the when-done action of one queue.

    Use on the event loop only. No method raises: a failure of the power service is an
    ``app.warning`` (and a log entry).
    """

    def __init__(
        self,
        events: EventBus,
        power: PowerService | None,
        unavailable: Mapping[WhenDone, str] | None = None,
    ) -> None:
        self._events = events
        self._power = power
        self._unavailable = dict(unavailable or {})
        """Power actions that this process cannot carry out, each with the reason."""
        self._done = 0
        self._failed = 0
        self._notified = 0
        self.countdown: str | None = None
        """The id of the countdown that the queue started, until the queue cancels it."""

    def job_ended(
        self,
        job: QueueJob,
        state: JobState,
        *,
        error: str | None = None,
        output: Path | None = None,
        notifications: bool,
    ) -> NotificationEvent | None:
        """Publish the notification of a run that ended in ``state`` (``notifications``: the
        setting). ``output``: the final output path of a ``done`` run."""
        if not notifications or state not in _ENDED_ON_ITS_OWN:
            return None
        source = Path(job.settings.source.path).name
        if state is JobState.DONE:
            path = output or job.output_path or job.settings.output.path
            event = self._notify(
                "Job done",
                printable(path.name if path is not None else source),
                level="success",
                job_id=job.id,
            )
        else:
            event = self._notify(
                "Job failed",
                printable(f"{source}: {error}" if error else source),
                level="error",
                job_id=job.id,
            )
        self._notified += 1
        return event

    def _notify(
        self,
        title: str,
        message: str,
        *,
        level: Literal["info", "success", "warning", "error"],
        job_id: str | None = None,
    ) -> NotificationEvent:
        event = NotificationEvent(title=title, message=message, level=level, job_id=job_id)
        self._events.publish(event)
        return event

    def count(self, state: JobState) -> None:
        """Count a run's end state for the batch summary (``done`` and ``failed`` only)."""
        if state is JobState.DONE:
            self._done += 1
        elif state is JobState.FAILED:
            self._failed += 1

    def emptied(self, last: JobState, action: WhenDone) -> None:
        """The queue emptied; ``last`` is the end state of the run that ended last and
        ``action`` the when-done setting. Runs the action for the batch (only when the last
        run ended on its own) and starts a new batch."""
        done, failed, notified = self._done, self._failed, self._notified
        self._done = self._failed = self._notified = 0
        if last not in _ENDED_ON_ITS_OWN or action == "nothing":
            return
        text = summary(done, failed)
        if action == "notify":
            if done + failed == 1 and notified == 1:
                return  # the job's own notification says the same
            self._notify(
                "Queue finished",
                text + ".",
                level="warning" if failed else "success",
            )
            return
        if action not in POWER_LABELS:  # a value this code does not know: never a crash
            log.warning("when done: unknown action %r, nothing was done", action)
            return
        power_action, label = POWER_LABELS[action]
        reason = self._unavailable.get(action)
        if self._power is None or reason is not None:
            self._warn(
                "queue.when_done_unavailable",
                f"The queue is finished ({text}). When done: “{label}” is not available here, "
                "so nothing was done.",
                f"when_done={action}: {reason or 'this Reframe has no power service'}",
            )
            return
        try:
            self.countdown = self._power.schedule(power_action, reason=text)
        except Exception as exc:  # a bug in the power service: the queue goes on
            log.exception("when done: the %s countdown did not start", action)
            self.countdown = None
            self._warn(
                "queue.when_done_failed",
                f"The queue is finished ({text}). When done: “{label}” could not be started, "
                "so nothing was done.",
                printable(f"{type(exc).__name__}: {exc}"),
            )

    def work_started(self) -> None:
        """The runner took a job: cancel the countdown that the queue started."""
        self._cancel_countdown()

    def close(self) -> None:
        """The queue closes: cancel the countdown that the queue started (its action never
        runs)."""
        self._cancel_countdown()

    def _cancel_countdown(self) -> None:
        countdown, self.countdown = self.countdown, None
        if countdown is None or self._power is None:
            return
        try:
            self._power.cancel(countdown)  # False when it already ended or was replaced
        except Exception:  # a bug in the power service: the queue goes on
            log.exception("when done: the countdown %s was not cancelled", countdown)

    def _warn(self, code: str, message: str, detail: str) -> None:
        self._events.publish(AppWarningEvent(code=code, message=message, detail=detail))
