"""The idle watch on the real facade, and in the entry point."""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from reframe_server import idle
from reframe_server.__main__ import serve
from reframe_server.config import ServerConfig
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


@pytest.mark.usefixtures("make_api")  # the test's own folders, tools and settings
async def test_a_server_with_idle_exit_that_is_stopped_by_a_request_ends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stop comes from elsewhere (``POST /api/system/shutdown``, the parent watch): the
    entry point must end the idle watch, which would wait for an idle server for ever."""
    token = secrets.token_urlsafe(16)
    config = ServerConfig(
        mode="desktop",
        idle_exit=3600,
        token=SecretStr(token),
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    serving = asyncio.create_task(serve(config))
    printed = ""
    while not printed:
        assert not serving.done()
        await asyncio.sleep(0.02)
        printed = capsys.readouterr().out
    port = json.loads(printed)["port"]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers) as client:
        assert (await client.post("/api/system/shutdown")).status_code == 204
    # Not wait_for: serve() would take its cancel for the idle watch's and return 0.
    ended, _ = await asyncio.wait({serving}, timeout=10)
    try:
        assert ended == {serving}, "serve() still runs"
        assert serving.result() == 0
    finally:
        serving.cancel()
