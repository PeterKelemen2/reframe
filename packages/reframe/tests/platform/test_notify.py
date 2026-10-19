"""The notification hook: it only emits a ``notification`` event."""

from __future__ import annotations

from reframe.events import EventBus
from reframe.models import NotificationEvent
from reframe.platform.notify import notify


def test_notify_publishes_one_event() -> None:
    events = EventBus()
    subscription = events.subscribe()
    event = notify(events, "Queue finished", "3 jobs done.", level="success", job_id="j1")
    assert event == NotificationEvent(
        title="Queue finished", message="3 jobs done.", level="success", job_id="j1"
    )
    assert subscription.get_nowait() == event
