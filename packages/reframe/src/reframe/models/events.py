"""Events of the core event bus (02 §Events). The server forwards them over one WebSocket.

:data:`Event` is one discriminated union (discriminator ``type``). The table of 02 §Events
gives the first seven types; C-1, C-9 and C-14 add ``tools.changed``, ``app.warning``,
``power.countdown`` and ``notification``. The bus itself is ``reframe.events.EventBus``.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import AwareDatetime, Field, TypeAdapter

from reframe.models.base import NonNegativeInt, ReframeModel
from reframe.models.capabilities import EncoderStatus
from reframe.models.queue import JobProgress, JobState
from reframe.models.tasks import TaskInfo
from reframe.models.tools import ToolSet

__all__ = [
    "EVENT_ADAPTER",
    "EVENT_TYPES",
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
    "TaskDoneEvent",
    "TaskProgressEvent",
    "ToolsChangedEvent",
]


class CapabilitiesChangedEvent(ReframeModel):
    """Encoder detection changed a status (C-4)."""

    type: Literal["capabilities.changed"] = "capabilities.changed"
    encoders: list[EncoderStatus]
    """The encoders whose status changed (all of them after a full re-scan)."""


class TaskProgressEvent(ReframeModel):
    type: Literal["task.progress"] = "task.progress"
    task: TaskInfo


class TaskDoneEvent(ReframeModel):
    """A task ended: ``task.state`` is ``done``, ``failed`` or ``cancelled``."""

    type: Literal["task.done"] = "task.done"
    task: TaskInfo


class JobStateEvent(ReframeModel):
    type: Literal["job.state"] = "job.state"
    job_id: str
    state: JobState
    previous: JobState | None = None
    error: str | None = None


class JobProgressEvent(ReframeModel):
    type: Literal["job.progress"] = "job.progress"
    job_id: str
    progress: JobProgress


class JobLogEvent(ReframeModel):
    """Log lines of a job, batched and rate-limited (the full log is in the log file)."""

    type: Literal["job.log"] = "job.log"
    job_id: str
    lines: list[str]
    dropped: NonNegativeInt = 0
    """Lines left out by the rate limit since the previous event."""


class QueueChangedEvent(ReframeModel):
    """The queue's order or membership changed."""

    type: Literal["queue.changed"] = "queue.changed"
    job_ids: list[str]
    """All job ids, in queue order."""


class ToolsChangedEvent(ReframeModel):
    """Tool discovery ran again (a path changed, or *Check again*)."""

    type: Literal["tools.changed"] = "tools.changed"
    tools: ToolSet


class AppWarningEvent(ReframeModel):
    """A problem that the user should know about but that does not stop anything.

    Examples: a corrupt settings or presets file was backed up and replaced (C-9); sleep
    inhibit is not available (C-14).
    """

    type: Literal["app.warning"] = "app.warning"
    code: str
    """``settings.corrupt``, ``presets.corrupt``, ``sleep_inhibit.unavailable``, …"""
    message: str
    detail: str | None = None


PowerAction = Literal["shutdown", "sleep", "quit"]


class PowerCountdownEvent(ReframeModel):
    """The when-done power action countdown (C-14): always 60 s and cancellable.

    ``phase``: ``started`` (once), ``tick`` (every second), then ``cancelled`` or
    ``executing``. The UI shows a dialog with a *Cancel* button while it runs.
    """

    type: Literal["power.countdown"] = "power.countdown"
    countdown_id: str
    action: PowerAction
    phase: Literal["started", "tick", "cancelled", "executing"]
    seconds_left: NonNegativeInt
    deadline: AwareDatetime | None = None


class NotificationEvent(ReframeModel):
    """A notification for the UI to show (C-14 only emits the event)."""

    type: Literal["notification"] = "notification"
    title: str
    message: str = ""
    level: Literal["info", "success", "warning", "error"] = "info"
    job_id: str | None = None


#: Every event, discriminated by ``type``.
Event = Annotated[
    CapabilitiesChangedEvent
    | TaskProgressEvent
    | TaskDoneEvent
    | JobStateEvent
    | JobProgressEvent
    | JobLogEvent
    | QueueChangedEvent
    | ToolsChangedEvent
    | AppWarningEvent
    | PowerCountdownEvent
    | NotificationEvent,
    Field(discriminator="type"),
]

#: Validates / serialises any :data:`Event` (``EVENT_ADAPTER.validate_json(text)``).
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

#: All event type strings, in the order of the union.
EVENT_TYPES: tuple[str, ...] = tuple(
    str(member.model_fields["type"].default) for member in get_args(get_args(Event)[0])
)
