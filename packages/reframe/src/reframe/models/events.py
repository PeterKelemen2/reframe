"""Events of the core event bus. The server forwards them over one WebSocket.

:data:`Event` is one discriminated union (discriminator ``type``). ``resync`` is never
published: the event bus puts it into a subscriber's stream when that subscriber lost events.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from reframe.models.base import NonNegativeInt, ReframeModel
from reframe.models.capabilities import EncoderStatus
from reframe.models.queue import JobProgress, JobState
from reframe.models.tasks import TaskInfo
from reframe.models.text import DisplayText
from reframe.models.tools import ToolSet

__all__ = [
    "AppWarningEvent",
    "CapabilitiesChangedEvent",
    "Event",
    "JobLogEvent",
    "JobProgressEvent",
    "JobStateEvent",
    "NotificationEvent",
    "PowerAction",
    "PowerCountdownEvent",
    "QueueChangedEvent",
    "QueueProcessingEvent",
    "ResyncEvent",
    "TaskDoneEvent",
    "TaskProgressEvent",
    "ToolsChangedEvent",
]


class CapabilitiesChangedEvent(ReframeModel):
    """Encoder detection changed a status."""

    type: Literal["capabilities.changed"] = "capabilities.changed"
    encoders: list[EncoderStatus]
    """The encoders whose status changed (all of them after a full re-scan)."""


class TaskProgressEvent(ReframeModel):
    type: Literal["task.progress"] = "task.progress"
    task: TaskInfo


class TaskDoneEvent(ReframeModel):
    """A task ended; ``task.state`` says how."""

    type: Literal["task.done"] = "task.done"
    task: TaskInfo


class JobStateEvent(ReframeModel):
    type: Literal["job.state"] = "job.state"
    job_id: str
    state: JobState
    previous: JobState | None = None
    error: DisplayText | None = None


class JobProgressEvent(ReframeModel):
    type: Literal["job.progress"] = "job.progress"
    job_id: str
    progress: JobProgress


class JobLogEvent(ReframeModel):
    """Log lines of a job, batched and rate-limited (the full log is in the log file)."""

    type: Literal["job.log"] = "job.log"
    job_id: str
    lines: list[DisplayText]
    dropped: NonNegativeInt = 0
    """Lines left out by the rate limit since the previous event."""


class QueueChangedEvent(ReframeModel):
    """The queue's order or membership changed."""

    type: Literal["queue.changed"] = "queue.changed"
    job_ids: list[str]
    """All job ids, in queue order."""


class QueueProcessingEvent(ReframeModel):
    """Whether the queue takes waiting jobs, and which, changed. Running state: a restarted
    server is not processing."""

    type: Literal["queue.processing"] = "queue.processing"
    processing: bool
    """The runner takes waiting jobs (running and paused jobs go on either way)."""
    only: list[str] | None
    """It takes only these jobs, the ones a ``start`` with ``job_ids`` named (an id may name a
    job that has left the queue since); ``null``: every waiting job, or not processing."""
    reason: Literal["start", "stop", "idle"]
    """``start`` and ``stop``: a front end's call; ``idle``: the jobs that a ``start`` named
    have all ended."""


class ToolsChangedEvent(ReframeModel):
    """Tool discovery ran again (a path changed, or *Check again*)."""

    type: Literal["tools.changed"] = "tools.changed"
    tools: ToolSet


class AppWarningEvent(ReframeModel):
    """A problem that the user should know about but that does not stop anything.

    Examples: a corrupt settings or presets file was backed up and replaced; sleep inhibit is
    not available.
    """

    type: Literal["app.warning"] = "app.warning"
    code: str
    """A stable code for the warning, such as ``settings.corrupt``."""
    message: DisplayText
    detail: DisplayText | None = None


PowerAction = Literal["shutdown", "sleep", "quit"]


class PowerCountdownEvent(ReframeModel):
    """The when-done power action countdown: always 60 s and cancellable.

    ``phase``: ``started`` (once), ``tick`` (every second), then ``cancelled`` or
    ``executing``.
    """

    type: Literal["power.countdown"] = "power.countdown"
    countdown_id: str
    action: PowerAction
    phase: Literal["started", "tick", "cancelled", "executing"]
    seconds_left: NonNegativeInt
    deadline: AwareDatetime | None = None


class NotificationEvent(ReframeModel):
    """A notification for the UI to show."""

    type: Literal["notification"] = "notification"
    title: DisplayText
    message: DisplayText = ""
    level: Literal["info", "success", "warning", "error"] = "info"
    job_id: str | None = None


class ResyncEvent(ReframeModel):
    """In-band marker of one subscription: events were lost, re-read the snapshots.

    The event bus inserts it where events were dropped (``reason="dropped"``: progress or log
    events of a subscriber that fell behind), or as the last event before it closes a
    subscription that fell too far behind (``reason="overflow"``: subscribe again). The
    receiver should fetch the current queue, tasks and statuses again.
    """

    type: Literal["resync"] = "resync"
    reason: Literal["dropped", "overflow"] = "dropped"
    dropped: NonNegativeInt = 0
    """Events lost since the previous marker."""


#: Every event, discriminated by ``type``.
Event = Annotated[
    CapabilitiesChangedEvent
    | TaskProgressEvent
    | TaskDoneEvent
    | JobStateEvent
    | JobProgressEvent
    | JobLogEvent
    | QueueChangedEvent
    | QueueProcessingEvent
    | ToolsChangedEvent
    | AppWarningEvent
    | PowerCountdownEvent
    | NotificationEvent
    | ResyncEvent,
    Field(discriminator="type"),
]
