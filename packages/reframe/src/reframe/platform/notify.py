"""The notification hook (05 §C-14): it only emits a ``notification`` event. The UI layer (the
desktop shell, the web app) shows it; the core never shows anything itself."""

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
