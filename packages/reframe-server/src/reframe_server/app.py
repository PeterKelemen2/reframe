"""``create_app(config)``: the FastAPI app. Its lifespan opens the ``Reframe`` facade and the
event hub and closes them; handlers reach both through :mod:`reframe_server.deps`."""

from __future__ import annotations

import functools
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from reframe.service import Reframe
from reframe_server import __version__, openapi, security
from reframe_server.api import JsonTextResponse, operation_id
from reframe_server.config import ServerConfig
from reframe_server.errors import install_error_handlers
from reframe_server.events import EventHub
from reframe_server.folders import hide_server_folders
from reframe_server.routers import (
    auth,
    batch,
    definitions,
    events,
    fs,
    health,
    jobs,
    languages,
    media,
    naming,
    power,
    presets,
    preview,
    queue,
    settings,
    sources,
    system,
    tasks,
)
from reframe_server.sources import SourceRegistry

__all__ = ["create_app"]

log = logging.getLogger(__name__)

_AUTHENTICATED = (
    system,
    tasks,
    fs,
    sources,
    preview,
    definitions,
    languages,
    jobs,
    naming,
    batch,
    presets,
    queue,
    power,
    settings,
)
"""Routers behind :func:`~reframe_server.security.require_auth`. The others check access
themselves: health is open, login has no credentials yet, the WebSocket authenticates in its
first message and the media URLs accept a signature."""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: ServerConfig = app.state.config
    reframe = await Reframe.create(config.config_dir, config.data_dir)
    hub = EventHub(reframe.events, config, hide=functools.partial(hide_server_folders, reframe))
    app.state.reframe, app.state.hub = reframe, hub
    try:
        yield
    finally:
        await hub.close()
        await reframe.close()
        app.state.reframe = None


def _no_shutdown() -> None:
    log.warning("shutdown requested, but this app was not started by reframe-server")


def create_app(config: ServerConfig) -> FastAPI:
    """The app for ``config``. Nothing starts until its lifespan runs.

    ``app.state``: ``config``, ``instance`` (random id of this run), ``started``
    (``time.monotonic()``), ``sources`` (:class:`SourceRegistry`), ``request_shutdown`` (the
    entry point replaces it), and during the lifespan ``reframe`` and ``hub``.
    """
    app = FastAPI(
        title="Reframe",
        version=__version__,
        lifespan=_lifespan,
        default_response_class=JsonTextResponse,
        generate_unique_id_function=operation_id,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.config = config
    app.state.instance = secrets.token_hex(8)
    app.state.started = time.monotonic()
    app.state.sources = SourceRegistry()
    app.state.reframe = None
    app.state.hub = None
    app.state.request_shutdown = _no_shutdown
    install_error_handlers(app)
    security.install(app, config)
    openapi.install(app)
    for module in (health, auth, events, media):
        app.include_router(module.router, prefix="/api")
    for module in _AUTHENTICATED:
        app.include_router(
            module.router, prefix="/api", dependencies=[Depends(security.require_auth)]
        )
    return app
