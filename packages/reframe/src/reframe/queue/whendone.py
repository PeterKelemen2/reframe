"""When done (C-11; 03 §Queue → When done) and the job notifications (C-14's hook).

The queue (:class:`~reframe.queue.QueueService`) owns one :class:`WhenDoneActions`. When the
action runs is decision 0016 §9; the other choices are decision 0037.

**Job notifications** (``settings.queue.notifications``, read when a run ends). A job that
ended on its own gets one ``notification`` event with its ``job_id``: ``done`` → "Job done"
(level ``success``, the output's file name); ``failed`` → "Job failed" (level ``error``, the
source's file name and the reason). A job cancelled by the user or stopped by ``close()``
gets none, and so does a job that is added as ``failed`` (it never ran). The notification
comes when the run's files are handled (the output has its final name), before the run's
last ``job.log`` batch and its end ``job.state``: the end state stays the last event of a run
(0016 §10).

**When the queue empties** after a job ended on its own (0016 §9: nothing runs and nothing is
left that the runner would take; not when the user cancelled the last job or the queue was
closed), ``settings.queue.when_done`` is read and runs once, for the jobs that ended since the
queue last emptied (the *batch*):

- ``nothing``.
- ``notify``: one ``notification`` "Queue finished" ("3 jobs done, 1 failed.", level
  ``success``, or ``warning`` when a job failed), whatever ``notifications`` says. It is left
  out when the batch was one job whose own notification was sent: it would say the same.
- ``quit``, ``sleep``, ``shutdown``: ``PowerService.schedule(action, reason="3 jobs done, 1
  failed")`` (C-14), which publishes the 60 s countdown (``power.countdown``) and runs the
  action at its end. Without a power service: ``app.warning`` ``queue.when_done_unavailable``;
  when the power service cannot start the countdown: ``queue.when_done_failed``. Both say
  that nothing was done.

The action runs whether the last job was done or failed: a failed job does not need the
computer to stay on (its log and the queue are kept). When the queue empties after the user
cancelled its last job, no action runs and a new batch starts.

**The countdown** that the queue started is cancelled when new work starts (the runner takes a
job: one added or retried while the queue runs, or :meth:`~reframe.queue.QueueService.start`)
and when the queue is closed. A change of the when-done setting does not cancel it (the queue
reads the setting only when it empties): the user cancels it through ``Reframe.power.cancel()``
(the countdown dialog). The queue cancels only its own countdown, by its id.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent, NotificationEvent, PowerAction
from reframe.models.queue import JobState, QueueJob
from reframe.models.settings import WhenDone
from reframe.platform.notify import notify
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
    """``"3 jobs done, 1 failed"`` (the failed part only when a job failed; no full stop)."""
    text = f"{done} job{'s' if done != 1 else ''} done"
    if failed:
        text += f", {failed} failed"
    return text


class WhenDoneActions:
    """The batch counts, the job notifications and the when-done action of one queue.

    Use on the event loop only. No method raises: a failure of the power service is an
    ``app.warning`` (and a log entry).
    """

    def __init__(self, events: EventBus, power: PowerService | None) -> None:
        self._events = events
        self._power = power
        self._done = 0
        self._failed = 0
        self._notified = 0
        self.countdown: str | None = None
        """The id of the countdown that the queue started, until the queue cancels it."""

    # ------------------------------------------------------------------ a run ended

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
            event = notify(
                self._events,
                "Job done",
                printable(path.name if path is not None else source),
                level="success",
                job_id=job.id,
            )
        else:
            event = notify(
                self._events,
                "Job failed",
                printable(f"{source}: {error}" if error else source),
                level="error",
                job_id=job.id,
            )
        self._notified += 1
        return event

    def count(self, state: JobState) -> None:
        """Count a run's end state for the batch summary (``done`` and ``failed`` only)."""
        if state is JobState.DONE:
            self._done += 1
        elif state is JobState.FAILED:
            self._failed += 1

    # ------------------------------------------------------------------ the queue emptied

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
            notify(
                self._events,
                "Queue finished",
                text + ".",
                level="warning" if failed else "success",
            )
            return
        if action not in POWER_LABELS:  # a value this code does not know: never a crash
            log.warning("when done: unknown action %r, nothing was done", action)
            return
        power_action, label = POWER_LABELS[action]
        if self._power is None:
            self._warn(
                "queue.when_done_unavailable",
                f"The queue is finished ({text}). When done: “{label}” is not available here, "
                "so nothing was done.",
                f"when_done={action}: this Reframe has no power service",
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

    # ------------------------------------------------------------------ the countdown

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
