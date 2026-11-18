"""Fixtures of the server tests; the harness itself is :mod:`reframe_testing.server`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from reframe_server.__main__ import _log_config
from reframe_testing import fake_tools as ft
from reframe_testing.server import Api, ApiFactory, make_api_factory


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Undo the process-wide logging that an in-process ``serve()`` sets up: its console handler
    writes to the stderr of that moment, which a later test's capture has closed."""
    names = ["", *_log_config().get("loggers", {})]
    saved = {
        name: (logger.level, logger.handlers[:], logger.propagate, logger.disabled)
        for name in names
        for logger in [logging.getLogger(name)]
    }
    yield
    for name, (level, handlers, propagate, disabled) in saved.items():
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.propagate = propagate
        logger.disabled = disabled


@pytest.fixture
def make_api(
    tmp_path: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> ApiFactory:
    """``async with make_api(mode="web", auth="token", **config) as api``. Folders, tools and
    settings are the test's own: no variable of the developer's shell reaches the server."""
    return make_api_factory(tmp_path, fake_tools, monkeypatch)


@pytest.fixture
async def api(make_api: ApiFactory) -> AsyncIterator[Api]:
    """Web mode, token auth, one media root and one output root."""
    async with make_api() as harness:
        yield harness


@pytest.fixture
def api_client(api: Api) -> httpx.AsyncClient:
    """``api.client``: the authenticated client of the default server."""
    return api.client


@pytest.fixture(params=["none", "token", "password"])
async def api_each_auth(make_api: ApiFactory, request: pytest.FixtureRequest) -> AsyncIterator[Api]:
    """The web-mode server once per auth mode."""
    async with make_api(auth=request.param) as harness:
        yield harness
