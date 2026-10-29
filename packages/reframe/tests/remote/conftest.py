"""A real server in the test's event loop (the server harness on the fake tools), and clients of
it: the queue contract runs against its facade's ``QueueService`` and a ``RemoteQueue``."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection

from reframe.models import JobDraft, JobSettings, ServerEndpoint
from reframe.remote import API_VERSION, Owner, RemoteQueue
from reframe.remote.owner import ENDPOINT_FILE
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api, ApiFactory, LiveServer, make_api_factory

HANG = ft.Scenario(
    [
        PROBE_RULE,
        ft.Rule(
            tool="ffmpeg",
            argv_has=["matroska"],
            actions=[ft.write_output(), ft.progress(blocks=1, end=False), ft.hang()],
        ),
    ]
)
"""Each encode writes its ``.part`` file, prints one progress block, then runs until stopped."""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def make_api(
    tmp_path: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> ApiFactory:
    return make_api_factory(tmp_path, fake_tools, monkeypatch)


@dataclass
class Server:
    """The desktop-mode server of a test, listening on loopback."""

    api: Api
    live: LiveServer

    @property
    def data_dir(self) -> Path:
        return self.api.reframe.data_dir

    def owner(self, *, token: str | None = None, port: int | None = None) -> Owner:
        endpoint = ServerEndpoint(
            pid=os.getpid(),
            instance=self.api.app.state.instance,
            port=self.live.port if port is None else port,
            token=self.api.token if token is None else token,
            version="0.0.0",
            api_version=API_VERSION,
            started_at=datetime.now(UTC),
        )
        return Owner(endpoint, "0.0.0")

    def publish(self) -> Path:
        """Write ``server.json`` as the real server does once it listens."""
        path = self.data_dir / ENDPOINT_FILE
        path.write_text(self.owner().endpoint.model_dump_json(), encoding="utf-8")
        return path

    async def connect(self, **owner: object) -> RemoteQueue:
        api = self.api.reframe
        return await RemoteQueue.connect(
            self.owner(**owner),  # type: ignore[arg-type]
            data_dir=api.data_dir,
            config_dir=api.config_dir,
            cache_dir=api.cache_dir,
        )

    async def job(self, name: str = "Show S01E01.mkv", *, output: str | None = None) -> JobSettings:
        """A job of a new media file, written below the output root."""
        source = self.api.media_file(name)
        target = self.api.output / (output or f"{source.stem}.mkv")
        draft = await self.api.reframe.jobs.draft(source, output=target)
        assert isinstance(draft, JobDraft)
        return draft.job


@asynccontextmanager
async def serving(make_api: ApiFactory) -> AsyncIterator[Server]:
    async with make_api(mode="desktop") as api, api.live() as live:
        yield Server(api, live)


@pytest.fixture
async def server(make_api: ApiFactory) -> AsyncIterator[Server]:
    async with serving(make_api) as found:
        yield found


async def poll(condition: Callable[[], bool], limit: float = 20.0) -> None:
    deadline = time.monotonic() + limit
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


class Requests(httpx.AsyncBaseTransport):
    """The transport of a ``RemoteQueue`` in a test: counts its requests, holds
    ``POST /api/queue/start`` until :attr:`released` is set, holds the answers of
    ``POST /api/queue`` (the server has added the jobs) until :attr:`answers` is set, and
    answers a request with :attr:`answer` when it gives a response."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.seen: list[tuple[str, str]] = []
        self.released = asyncio.Event()
        self.released.set()
        self.answers = asyncio.Event()
        self.answers.set()
        self.answer: Callable[[httpx.Request], httpx.Response | None] = lambda _request: None

    def reads(self) -> int:
        """Whole-queue reads so far."""
        return self.seen.count(("GET", "/api/queue"))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.method, request.url.path))
        if request.url.path == "/api/queue/start":
            await self.released.wait()
        answer = self.answer(request)
        if answer is not None:
            return answer
        response = await self.inner.handle_async_request(request)
        if (request.method, request.url.path) == ("POST", "/api/queue"):
            await self.answers.wait()
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def watch_requests(remote: RemoteQueue) -> Requests:
    requests = Requests()
    plain = remote._http
    remote._http = httpx.AsyncClient(
        base_url=plain.base_url, headers=plain.headers, timeout=plain.timeout, transport=requests
    )
    await plain.aclose()
    return requests


@dataclass
class Wire:
    """The event messages between the socket and a ``RemoteQueue``'s reader: each one ``lag``
    seconds late, without those that ``drop`` names, and ``first`` before all of them."""

    lag: float = 0.0
    drop: Callable[[dict[str, Any]], bool] = lambda _message: False
    first: list[dict[str, Any] | str] = field(default_factory=list)
    """Messages as objects, or as the text sent."""


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    found = Wire()
    plain = ClientConnection.__aiter__

    async def messages(self: ClientConnection) -> AsyncIterator[str | bytes]:
        for message in found.first:
            yield message if isinstance(message, str) else json.dumps(message)
        async for raw in plain(self):
            if found.lag:
                await asyncio.sleep(found.lag)
            if not found.drop(json.loads(raw)):
                yield raw

    monkeypatch.setattr(ClientConnection, "__aiter__", messages)
    return found


def event_message(event: dict[str, Any]) -> dict[str, Any]:
    return {"type": "event", "seq": 0, "event": event}
