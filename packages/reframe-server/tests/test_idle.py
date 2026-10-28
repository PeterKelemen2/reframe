"""The idle watch on the real facade."""

from __future__ import annotations

import asyncio

import pytest

from reframe_server import idle
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio


async def test_a_pending_when_done_countdown_keeps_the_server_until_it_is_cancelled(
    api: Api,
) -> None:
    """Idle exit during the countdown would close the power service, and the action that the
    user chose would never run."""
    asked = asyncio.Event()
    countdown = api.reframe.power.schedule("shutdown", reason="1 job done")
    watching = asyncio.create_task(idle.watch(api.app, 0.2, asked.set))
    try:
        await asyncio.sleep(1.0)
        assert not asked.is_set()
        assert api.reframe.power.cancel(countdown)
        await asyncio.wait_for(asked.wait(), 5)
    finally:
        watching.cancel()


async def test_the_watch_outlives_the_close_of_the_facade(make_api: ApiFactory) -> None:
    """The entry point cancels the watch only after uvicorn's shutdown, which has already
    closed the facade: a look in between must not end the watch with an error, which the entry
    point would raise."""
    async with make_api() as api:
        app = api.app
    watching = asyncio.create_task(idle.watch(app, 0.05, lambda: None))
    await asyncio.sleep(0.3)
    assert not watching.done()
    watching.cancel()
