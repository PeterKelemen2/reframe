"""The notification hook: the core publishes a ``notification`` event and never shows one."""

from __future__ import annotations

from typing import Literal

from reframe.events import EventBus
from reframe.models.events import NotificationEvent

__all__ = ["notify"]


def notify(
    events: EventBus,
    title: str,
    message: str = "",
    *,
    level: Literal["info", "success", "warning", "error"] = "info",
    job_id: str | None = None,
) -> NotificationEvent:
    """Publish a :class:`~reframe.models.NotificationEvent` and return it."""
    event = NotificationEvent(title=title, message=message, level=level, job_id=job_id)
    events.publish(event)
    return event
