"""``GET /api/health``: open to every caller, so a health check needs no token."""

from __future__ import annotations

import time

from fastapi import Request
from pydantic import BaseModel, ConfigDict

from reframe_server import __version__
from reframe_server.api import API_VERSION, api_router

router = api_router("system")


class Health(BaseModel):
    """This server run."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    version: str
    api_version: int
    """A client of another ``api_version`` must not use this server."""
    instance: str
    """Random id of this run: a restarted server has another one."""
    uptime: float
    """Seconds since the server started."""


@router.get("/health")
async def health(request: Request) -> Health:
    """Version, API version, run id and uptime."""
    state = request.app.state
    return Health(
        version=__version__,
        api_version=API_VERSION,
        instance=state.instance,
        uptime=round(time.monotonic() - state.started, 3),
    )
