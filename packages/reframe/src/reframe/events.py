"""The async event bus of the core (02 §Events).

- :meth:`EventBus.publish` is synchronous and never waits: it can be called from coroutines,
  callbacks and other threads (for example a progress parser in a worker thread).
- :meth:`EventBus.subscribe` returns a :class:`Subscription`: an async iterator with a
  bounded queue, so a slow subscriber never slows down the publishers.
- :meth:`EventBus.close` ends every subscription: iteration stops after the events that are
  already queued.

**What a subscriber that falls behind gets** (S-3 does the same over the WebSocket):

1. *Coalescing.* A new ``task.progress`` replaces the queued one of the same task, and a new
   ``job.progress`` the queued one of the same job (the old one is removed, the new one goes
   to the end). Only the latest progress matters, so this loses nothing.
2. *Dropping.* When the queue is full, the oldest **lossy** event is dropped: progress and
   ``job.log`` (the full log is in the log file). State and terminal events (``task.done``,
   ``job.state``, ``queue.changed``, ``tools.changed``, …) are never dropped. Where events
   were dropped, the stream gets one :class:`~reframe.models.ResyncEvent` (``reason=
   "dropped"``, with the count), so the subscriber knows to re-read the snapshots.
3. *Growing, then overflow.* When the queue is full of events that must not be dropped, it
   grows up to ``hard_limit`` (default 4 x ``max_queue``). Beyond that the subscription is
   closed: its last event is a ``ResyncEvent`` with ``reason="overflow"`` and it is
   removed from the bus; the subscriber must subscribe again and re-read the snapshots.

Example::

    bus = EventBus()
    async with bus.subscribe(types={"job.progress"}) as events:
        async for event in events:
            print(event)
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import Iterable
from types import TracebackType

from reframe.models.events import Event, ResyncEvent

__all__ = [
    "DEFAULT_MAX_QUEUE",
    "LOSSY_TYPES",
    "EventBus",
    "Subscription",
    "coalesce_key",
]

#: Default queue length of a subscription.
DEFAULT_MAX_QUEUE = 1000
#: Event types that may be dropped when a subscriber falls behind.
LOSSY_TYPES = frozenset({"task.progress", "job.progress", "job.log"})


def coalesce_key(event: Event) -> tuple[str, str] | None:
    """``(type, id)`` for events where only the latest one per id matters, else ``None``."""
    if event.type == "task.progress":
        return (event.type, event.task.id)
    if event.type == "job.progress":
        return (event.type, event.job_id)
    return None


class Subscription:
    """One subscriber's queue. Iterate it with ``async for``; close it when done."""

    def __init__(
        self,
        bus: EventBus,
        max_queue: int,
        types: frozenset[str] | None,
        hard_limit: int | None = None,
    ) -> None:
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        self._bus = bus
        self._max = max_queue
        self._hard_limit = max(hard_limit if hard_limit is not None else 4 * max_queue, max_queue)
        self._types = types
        self._queue: deque[Event] = deque()
        self._marker: ResyncEvent | None = None
        """The ``ResyncEvent`` still in the queue (at most one), updated while it waits."""
        self._lock = threading.Lock()
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup = asyncio.Event()
        self.dropped = 0
        """Events dropped because the subscriber fell behind (in total)."""
        self.coalesced = 0
        """Progress events replaced by a newer one of the same task or job."""
        self.overflowed = False
        """The subscription was closed because it fell too far behind."""

    # ---------------------------------------------------------------- bus side

    def _push(self, event: Event) -> None:
        if self._types is not None and event.type not in self._types:
            return
        with self._lock:
            if self._closed:
                return
            self._coalesce(event)
            if self._size() >= self._max and not self._drop_oldest_lossy():
                if event.type in LOSSY_TYPES:
                    self._count_drop(position=None)  # the new event is the oldest lossy one
                    event_kept = False
                elif len(self._queue) >= self._hard_limit:
                    self._overflow()
                    event_kept = False
                else:
                    event_kept = True  # grow: state and terminal events are never dropped
            else:
                event_kept = True
            if event_kept:
                self._queue.append(event)
        self._wake()

    def _size(self) -> int:
        return len(self._queue) - (1 if self._marker is not None else 0)

    def _coalesce(self, event: Event) -> None:
        key = coalesce_key(event)
        if key is None:
            return
        for index, queued in enumerate(self._queue):
            if queued is not self._marker and coalesce_key(queued) == key:
                del self._queue[index]
                self.coalesced += 1
                return

    def _drop_oldest_lossy(self) -> bool:
        for index, queued in enumerate(self._queue):
            if queued is not self._marker and queued.type in LOSSY_TYPES:
                self._count_drop(position=index)
                return True
        return False

    def _count_drop(self, position: int | None) -> None:
        """Count one dropped event; ``position`` is its queue index (``None``: not queued)."""
        self.dropped += 1
        if self._marker is not None:
            self._marker.dropped += 1
            if position is not None:
                del self._queue[position]
            return
        self._marker = ResyncEvent(reason="dropped", dropped=1)
        if position is None:
            self._queue.append(self._marker)
        else:
            self._queue[position] = self._marker  # the marker takes the dropped event's place

    def _overflow(self) -> None:
        self.overflowed = True
        self._closed = True
        self._queue.append(ResyncEvent(reason="overflow", dropped=self.dropped))
        self._bus._unsubscribe(self)

    def _end(self) -> None:
        with self._lock:
            self._closed = True
        self._wake()

    def _wake(self) -> None:
        loop = self._loop
        if loop is None:  # nobody waits yet; the first wait looks at the queue first
            return
        try:
            running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._wakeup.set()
        else:
            with contextlib.suppress(RuntimeError):  # the subscriber's loop is closed
                loop.call_soon_threadsafe(self._wakeup.set)

    # ---------------------------------------------------------------- subscriber side

    @property
    def closed(self) -> bool:
        return self._closed

    def pending(self) -> int:
        """Number of queued events (a queued ``ResyncEvent`` included)."""
        with self._lock:
            return len(self._queue)

    def _pop(self) -> Event:
        event = self._queue.popleft()
        if event is self._marker:
            self._marker = None
        return event

    def get_nowait(self) -> Event | None:
        """The next queued event, or ``None``."""
        with self._lock:
            return self._pop() if self._queue else None

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._queue:
                    return self._pop()
                if self._closed:
                    raise StopAsyncIteration
                self._wakeup.clear()
            await self._wakeup.wait()

    def close(self) -> None:
        """Stop receiving events (queued events can still be read)."""
        self._bus._unsubscribe(self)
        self._end()

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class EventBus:
    """Fan-out of :data:`reframe.models.Event` values to any number of subscribers."""

    def __init__(self, *, max_queue: int = DEFAULT_MAX_QUEUE) -> None:
        self._max_queue = max_queue
        self._subscriptions: list[Subscription] = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def publish(self, event: Event) -> None:
        """Queue ``event`` for every subscriber. Never waits; ignored after :meth:`close`."""
        with self._lock:
            if self._closed:
                return
            subscriptions = list(self._subscriptions)
        for subscription in subscriptions:
            subscription._push(event)

    def subscribe(
        self,
        *,
        max_queue: int | None = None,
        types: Iterable[str] | None = None,
        hard_limit: int | None = None,
    ) -> Subscription:
        """A new subscription.

        :param max_queue: queue length before lossy events are dropped (default: the bus's).
        :param types: only these event types (``{"job.state"}``); ``resync`` always comes.
        :param hard_limit: queue length at which the subscription overflows and closes
            (default 4 x ``max_queue``).
        """
        subscription = Subscription(
            self,
            self._max_queue if max_queue is None else max_queue,
            None if types is None else frozenset(types),
            hard_limit,
        )
        with self._lock:
            if self._closed:
                subscription._end()
                return subscription
            self._subscriptions.append(subscription)
        return subscription

    def _unsubscribe(self, subscription: Subscription) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._subscriptions.remove(subscription)

    def close(self) -> None:
        """End every subscription (after their queued events) and ignore later publishes."""
        with self._lock:
            self._closed = True
            subscriptions, self._subscriptions = self._subscriptions, []
        for subscription in subscriptions:
            subscription._end()
