"""FastAPI dependencies that give handlers the app's shared objects. They take an
``HTTPConnection``, so WebSocket routes can use them too."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from reframe.service import Reframe
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_server.events import EventHub
from reframe_server.sources import SourceRegistry

__all__ = ["ConfigDep", "HubDep", "ReframeDep", "SourcesDep"]


def get_reframe(conn: HTTPConnection) -> Reframe:
    reframe: Reframe | None = getattr(conn.app.state, "reframe", None)
    if reframe is None or reframe.closed:
        raise ProblemError(503, "server.closing", "The server is not running")
    return reframe


def get_config(conn: HTTPConnection) -> ServerConfig:
    config: ServerConfig = conn.app.state.config
    return config


def get_hub(conn: HTTPConnection) -> EventHub:
    hub: EventHub = conn.app.state.hub
    return hub


def get_sources(conn: HTTPConnection) -> SourceRegistry:
    sources: SourceRegistry = conn.app.state.sources
    return sources


ReframeDep = Annotated[Reframe, Depends(get_reframe)]
ConfigDep = Annotated[ServerConfig, Depends(get_config)]
HubDep = Annotated[EventHub, Depends(get_hub)]
SourcesDep = Annotated[SourceRegistry, Depends(get_sources)]
