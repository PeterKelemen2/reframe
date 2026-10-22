"""The server test harness: the real app and the real ``Reframe`` facade on the fake tools, in
temporary folders. :func:`make_api_factory` makes any server variant; :meth:`Api.live` serves
it over TCP for WebSocket tests (httpx has no WebSocket client, and its ``ASGITransport`` runs
no lifespan, so the factory runs it)."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import ClientConnection, connect

from reframe.probe import mediainfo
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_server.app import create_app
from reframe_server.config import AuthMode, ServerConfig, ServerMode
from reframe_testing import fake_tools as ft
from reframe_testing import media

ROOT = Path(__file__).resolve().parents[2]
MULTITRACK_PROBE = ROOT / "testdata" / "probes" / "fixtures" / "multitrack.mkv.json"

PROBE_RULE = ft.Rule(
    tool="ffprobe",
    argv_has=["-show_streams"],
    actions=[{"stdout_file": str(MULTITRACK_PROBE)}],
)
"""Every probe answers with the recorded probe of the ``multitrack`` fixture."""

BASE_URL = "http://127.0.0.1"


@dataclass
class LiveServer:
    """The harness app served by uvicorn on a free loopback port (its lifespan already runs)."""

    port: int

    @property
    def http_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def connect(
        self, path: str = "/api/events", *, origin: str | None = None, **kwargs: Any
    ) -> connect:
        """A ``websockets`` client connection (use ``async with``). ``origin`` defaults to
        the server's own; pass ``additional_headers`` or ``user_agent_header`` as needed."""
        return connect(
            f"ws://127.0.0.1:{self.port}{path}",
            origin=origin or self.http_url,  # type: ignore[arg-type]
            open_timeout=10,
            **kwargs,
        )


@dataclass
class Api:
    app: FastAPI
    config: ServerConfig
    client: httpx.AsyncClient
    """Sends the run's token as ``Authorization: Bearer`` (accepted in every auth mode)."""
    anonymous: httpx.AsyncClient
    """No credentials."""
    fake: ft.FakeTools
    media: Path
    """A media root (web mode reads only below it)."""
    output: Path
    """An output root (web mode writes only below it)."""
    outside: Path
    """A folder outside every root."""

    @property
    def reframe(self) -> Reframe:
        reframe: Reframe = self.app.state.reframe
        return reframe

    @property
    def token(self) -> str:
        return self.config.secret_token

    def media_file(
        self, name: str = "Show S01E01.mkv", data: bytes = b"not really matroska"
    ) -> Path:
        """A file below the media root. The fake ffprobe answers for it with ``multitrack``."""
        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def add_fixture(self, name: str, fixture_media: Callable[[str], Path]) -> Path:
        """A real fixture file (``fixture_media("multitrack")``) as a regular file below the
        media root; probes and encodes then go to the real tools (needs ffmpeg)."""
        source = fixture_media(name)
        target = self.media / source.name
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        self.use_real_tools()
        return target

    def use_real_tools(self) -> None:
        """Pass every ffmpeg / ffprobe call to the real tools."""
        ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
        assert ffmpeg is not None
        assert ffprobe is not None
        self.fake.set_scenario(
            ft.Scenario(
                [
                    ft.Rule(tool="ffprobe", actions=[ft.exec_program(ffprobe)]),
                    ft.Rule(actions=[ft.exec_program(ffmpeg)]),
                ]
            )
        )

    @asynccontextmanager
    async def live(self) -> AsyncIterator[LiveServer]:
        """Serve this app over TCP while the context is open."""
        server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
        )
        running = asyncio.create_task(server.serve())
        try:
            while not server.started:
                if running.done():
                    running.result()
                    raise RuntimeError("uvicorn stopped before it started")
                await asyncio.sleep(0.01)
            yield LiveServer(server.servers[0].sockets[0].getsockname()[1])
        finally:
            server.should_exit = True
            await running


ApiFactory = Callable[..., AbstractAsyncContextManager[Api]]


def make_api_factory(
    tmp_path: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> ApiFactory:
    """``async with make_api(mode="web", auth="token", **config) as api``. Folders, tools and
    settings are the test's own: no variable of the developer's shell reaches the server."""
    for name in ServerConfig.model_fields:
        monkeypatch.delenv(f"REFRAME_{name.upper()}", raising=False)
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "settings.json").write_text(
        json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
        encoding="utf-8",
    )
    fake_tools.set_scenario(ft.Scenario([PROBE_RULE]))
    roots = {name: tmp_path / name for name in ("media", "output", "outside")}
    for folder in roots.values():
        folder.mkdir(exist_ok=True)

    @asynccontextmanager
    async def factory(
        mode: ServerMode = "web", auth: AuthMode | None = "token", **overrides: Any
    ) -> AsyncIterator[Api]:
        settings: dict[str, Any] = {
            "mode": mode,
            "auth": auth,
            "token": secrets.token_urlsafe(16),
            "media_roots": [roots["media"]],
            "output_roots": [roots["output"]],
            "config_dir": tmp_path / "config",
            "data_dir": tmp_path / "data",
        }
        config = ServerConfig(**(settings | overrides))
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {config.secret_token}"}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers=headers) as client,
            httpx.AsyncClient(transport=transport, base_url=BASE_URL) as anonymous,
        ):
            yield Api(
                app=app,
                config=config,
                client=client,
                anonymous=anonymous,
                fake=fake_tools,
                media=roots["media"],
                output=roots["output"],
                outside=roots["outside"],
            )

    return factory


async def receive_json(connection: ClientConnection, limit: float = 10.0) -> Any:
    """The next WebSocket message, parsed."""
    return json.loads(await asyncio.wait_for(connection.recv(), limit))
