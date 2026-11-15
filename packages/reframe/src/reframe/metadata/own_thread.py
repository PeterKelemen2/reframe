"""A blocking call in a thread of its own, for the header writer: it never waits behind other
work in the shared default executor, and a stop that comes before it starts prevents it."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from threading import Lock, Thread

__all__ = ["OwnThread"]


class OwnThread[T]:
    """Runs ``call`` once in a new non-daemon thread (an exiting interpreter waits for it).

    :attr:`future` is a plain future, not a task: an event loop that shuts down cancels every
    task, and the wait for the call must outlive that. It gets the call's result or exception,
    or ``None`` when :meth:`prevent` stopped the call before it started.
    """

    def __init__(self, call: Callable[[], T]) -> None:
        self._call = call
        self._lock = Lock()
        self._started = False
        self._prevented = False
        self._loop = asyncio.get_running_loop()
        self.future: asyncio.Future[T | None] = self._loop.create_future()

    def start(self) -> None:
        """Start the thread. Call it on the event loop."""
        Thread(target=self._run, name="reframe-header-writer", daemon=False).start()

    def prevent(self) -> bool:
        """Whether the call is now sure never to start; then :attr:`future` is ``None`` at
        once. ``False`` once the call has started: it runs to its end. Call it on the event
        loop."""
        with self._lock:
            if self._started:
                return False
            self._prevented = True
        if not self.future.done():
            self.future.set_result(None)
        return True

    def _run(self) -> None:
        with self._lock:
            if self._prevented:
                return
            self._started = True
        try:
            result = self._call()
        except BaseException as exc:  # handed to the waiting task
            error = exc
            self._settle(lambda: self.future.set_exception(error))
        else:
            self._settle(lambda: self.future.set_result(result))

    def _settle(self, settle: Callable[[], None]) -> None:
        def on_loop() -> None:
            if not self.future.done():
                settle()

        with contextlib.suppress(RuntimeError):  # the loop is closed: nobody waits any more
            self._loop.call_soon_threadsafe(on_loop)
