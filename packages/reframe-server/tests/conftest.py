"""Fixtures of the server tests; the harness itself is :mod:`reframe_testing.server`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from reframe_testing import fake_tools as ft
from reframe_testing.server import Api, ApiFactory, make_api_factory


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
