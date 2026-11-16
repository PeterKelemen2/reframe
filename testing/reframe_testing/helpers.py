"""Small helpers that many test modules share."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from reframe.models import TaskState

if TYPE_CHECKING:
    from reframe.events import Subscription
    from reframe.models import Event, TaskInfo
    from reframe.service import Reframe


def drain(subscription: Subscription) -> list[Event]:
    """Take every event the subscription holds now, without waiting."""
    events: list[Event] = []
    while (event := subscription.get_nowait()) is not None:
        events.append(event)
    return events


async def finish(app: Reframe, info: TaskInfo) -> TaskInfo:
    """Wait for the task and check that it ended done."""
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    return done


def nested(levels: int) -> list[Any]:
    """A list nested ``levels`` deep (``[]`` is one level), built without recursion."""
    value: list[Any] = []
    for _ in range(levels - 1):
        value = [value]
    return value
