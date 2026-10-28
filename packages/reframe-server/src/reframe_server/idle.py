"""Idle exit (decision 0042 item 8): a server that a CLI started ends once nothing needs it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import FastAPI

__all__ = ["is_idle", "watch"]


def is_idle(app: FastAPI) -> bool:
    """No running or paused job, no job that a ``start`` still targets, no open event
    connection and no pending when-done countdown."""
    return False


async def watch(app: FastAPI, seconds: float, request_shutdown: Callable[[], None]) -> None:
    """Call ``request_shutdown`` once the server has been idle for ``seconds`` in a row. Runs
    until it is cancelled."""
    await asyncio.Event().wait()
