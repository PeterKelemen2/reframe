"""Polling waits for tests whose code under test gives no event to wait for."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any


async def wait_until(condition: Callable[[], object], limit: float = 30.0) -> None:
    """Poll ``condition`` every 10 ms until it is true; ``TimeoutError`` after ``limit`` s."""
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.01)


def wait_until_sync(check: Callable[[], Any], limit: float = 30.0) -> Any:
    """Poll ``check`` until it returns a true value, and return that value."""
    deadline = time.monotonic() + limit
    while not (result := check()):
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        time.sleep(0.02)
    return result
