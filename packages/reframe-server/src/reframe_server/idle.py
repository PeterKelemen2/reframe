"""Idle exit: a server that a CLI started ends once nothing needs it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import FastAPI

__all__ = ["is_idle", "watch"]

POLL = 0.25
"""Seconds between two looks at the server's state, at most."""


def is_idle(app: FastAPI) -> bool:
    """No running or paused job, no job that a ``start`` still targets, no open event
    connection and no pending when-done countdown. ``False`` once the lifespan has closed the
    facade: a closed server has nothing left to stop."""
    reframe, hub = app.state.reframe, app.state.hub
    if reframe is None or hub is None:
        return False
    return not reframe.queue.busy and hub.connections == 0 and reframe.power.pending is None


async def watch(app: FastAPI, seconds: float, request_shutdown: Callable[[], None]) -> None:
    """Call ``request_shutdown`` once the server has been idle for ``seconds`` in a row, then
    return. A busy spell shorter than one look (:data:`POLL`) can go unseen."""
    loop = asyncio.get_running_loop()
    interval = min(POLL, seconds / 4)
    idle_since: float | None = None
    while True:
        now = loop.time()
        if not is_idle(app):
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since >= seconds:
            request_shutdown()
            return
        await asyncio.sleep(interval)
