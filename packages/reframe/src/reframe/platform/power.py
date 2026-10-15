"""Power actions (05 §C-14; 03 §Queue → When done): shut down, sleep, quit, always after a
cancellable 60 s countdown.

Contract skeleton (core-complete breakdown): the facade creates the service
(``Reframe.power``) and gives it to the queue for its when-done action (C-11). The C-14 task
(wave 1f) builds the countdown and the executors per OS (Windows: ``shutdown /s /t 60`` and
``SetSuspendState``; Linux: ``systemctl poweroff|suspend``). ``quit`` is not an OS action: the
countdown ends with ``executing`` and the UI layer quits.

**Safety:** no test may reach the real shutdown or suspend call. Tests give the service a fake
:class:`PowerExecutor`; the shared pytest plugin makes the real one fail in every test.
"""

from __future__ import annotations

from typing import Literal, Protocol

from reframe.events import EventBus
from reframe.models.events import PowerAction, PowerCountdownEvent

__all__ = ["COUNTDOWN_SECONDS", "PowerExecutor", "PowerService", "create_power_service"]

#: The countdown before every power action (05 §C-14).
COUNTDOWN_SECONDS = 60.0

#: The actions the operating system runs (``quit`` is done by the UI layer).
OsAction = Literal["shutdown", "sleep"]


class PowerExecutor(Protocol):
    """Runs a power action of the operating system."""

    async def execute(self, action: OsAction) -> str | None:
        """Run ``action``. ``None`` when the OS accepted it, else why not (data, never an
        exception)."""
        ...


class PowerService:
    """The when-done power actions with their countdown (``power.countdown`` events)."""

    def __init__(
        self,
        events: EventBus,
        *,
        executor: PowerExecutor | None = None,
        countdown: float = COUNTDOWN_SECONDS,
    ) -> None:
        self._events = events
        self._executor = executor
        self._countdown = countdown

    def schedule(self, action: PowerAction, *, reason: str = "") -> str:
        """Start the countdown for ``action`` and return its id at once. Events
        (:class:`~reframe.models.PowerCountdownEvent`): ``started``, a ``tick`` every second,
        then ``cancelled`` or ``executing``; ``shutdown`` and ``sleep`` then run through the
        executor (a failure is an ``app.warning``). A running countdown is cancelled first."""
        raise NotImplementedError("C-14 power actions")

    def cancel(self, countdown_id: str | None = None) -> bool:
        """Cancel the running countdown (``None``: whichever runs). ``True`` when one was
        cancelled; the action never runs then."""
        raise NotImplementedError("C-14 power actions")

    @property
    def pending(self) -> PowerCountdownEvent | None:
        """The last event of the running countdown, ``None`` when none runs."""
        return None

    async def close(self) -> None:
        """Cancel a running countdown (its action never runs). Safe to call more than once."""
        return None


def create_power_service(events: EventBus) -> PowerService:
    """The service with the executor of this operating system."""
    return PowerService(events)
