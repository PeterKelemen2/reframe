"""The async event bus of the core (02 §Events).

- :meth:`EventBus.publish` is synchronous and never waits: it can be called from coroutines,
  callbacks and other threads (for example a progress parser in a worker thread).
- :meth:`EventBus.subscribe` returns a :class:`Subscription`: an async iterator with a
  bounded queue. When a slow subscriber falls behind, the **oldest** event is dropped and
  :attr:`Subscription.dropped` counts it; publishers are never slowed down. The server
  (S-3) coalesces progress events for slow WebSocket clients on top of this.
- :meth:`EventBus.close` ends every subscription: iteration stops after the events that are
  already queued.

Example::

    bus = EventBus()
    async with bus.subscribe(types={"job.progress"}) as events:
        async for event in events:
            print(event.progress.percent)
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import Iterable
from types import TracebackType

from reframe.models.events import Event

__all__ = ["DEFAULT_MAX_QUEUE", "EventBus", "Subscription"]

#: Default queue length of a subscription.
DEFAULT_MAX_QUEUE = 1000


class Subscription:
    """One subscriber's queue. Iterate it with ``async for``; close it when done."""

    def __init__(self, bus: EventBus, max_queue: int, types: frozenset[str] | None) -> None:
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        self._bus = bus
        self._max = max_queue
        self._types = types
        self._queue: deque[Event] = deque()
        self._lock = threading.Lock()
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup = asyncio.Event()
        self.dropped = 0
        """Events dropped because the queue was full (oldest first)."""

    # ---------------------------------------------------------------- bus side

    def _push(self, event: Event) -> None:
        if self._types is not None and event.type not in self._types:
            return
        with self._lock:
            if self._closed:
                return
            if len(self._queue) >= self._max:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append(event)
        self._wake()

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
        """Number of queued events."""
        with self._lock:
            return len(self._queue)

    def get_nowait(self) -> Event | None:
        """The next queued event, or ``None``."""
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._queue:
                    return self._queue.popleft()
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
        self, *, max_queue: int | None = None, types: Iterable[str] | None = None
    ) -> Subscription:
        """A new subscription; ``types`` limits it to some event types (``{"job.state"}``)."""
        subscription = Subscription(
            self,
            self._max_queue if max_queue is None else max_queue,
            None if types is None else frozenset(types),
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
