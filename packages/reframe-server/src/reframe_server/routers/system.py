"""Tool and encoder status, tool discovery and fetch, shutdown."""

from __future__ import annotations

import asyncio
import sys

from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict

from reframe.models import AppWarningEvent, CapabilitySnapshot, ToolSet
from reframe.tasks import TaskContext
from reframe_server.api import JsonTextResponse, TaskAccepted, accepted, api_router
from reframe_server.config import AuthMode, ServerMode
from reframe_server.deps import ConfigDep, ReframeDep
from reframe_server.errors import ProblemError

router = api_router("system")


class SystemInfo(BaseModel):
    """What this server runs on and with."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    mode: ServerMode
    """``desktop``: the client is the desktop app on this computer; ``web``: a browser."""
    auth: AuthMode
    platform: str
    """The server's ``sys.platform``: ``linux``, ``win32``, ``darwin``."""
    tools: ToolSet
    """Each tool's status, path and version, after discovery."""
    problems: list[AppWarningEvent]
    """Start-up problems of the settings and preset files (a damaged, newer or unreadable
    file) and later failed saves."""
    settings_read_only: bool
    """The settings file is newer than this server or unreadable: changes are not saved."""


class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    build: str = "default"
    """A build name of the pinned FFmpeg manifest."""


@router.get("/system")
async def info(reframe: ReframeDep, config: ConfigDep) -> SystemInfo:
    """Tool statuses and versions, platform, mode and the settings and preset problems.
    Waits for a tool discovery that is running."""
    settings = reframe.settings
    tools = await reframe.tools.status()
    # The preset store reads presets.json at its first use.
    problems = await asyncio.to_thread(lambda: [*settings.problems, *reframe.presets.problems])
    return SystemInfo(
        mode=config.mode,
        auth=config.auth_mode,
        platform=sys.platform,
        tools=tools,
        problems=problems,
        settings_read_only=settings.read_only,
    )


@router.get("/system/encoders")
async def encoders(reframe: ReframeDep) -> CapabilitySnapshot:
    """Every encoder's status now; never waits for a running detection
    (``capabilities.changed`` events follow it)."""
    return reframe.capabilities.snapshot


@router.post("/system/encoders/rescan", status_code=202, response_model=TaskAccepted)
async def rescan_encoders(reframe: ReframeDep) -> JsonTextResponse:
    """Detect the encoders again without the cache: a task whose result is the
    :class:`CapabilitySnapshot`. Hardware test encodes can take many seconds."""
    capabilities = reframe.capabilities

    async def work(_ctx: TaskContext) -> CapabilitySnapshot:
        return await capabilities.rescan()

    return accepted(reframe.tasks.start("encoders_rescan", work, message="Detecting encoders"))


@router.post("/system/tools/rescan")
async def rescan_tools(reframe: ReframeDep) -> ToolSet:
    """Run tool discovery again and answer its result."""
    return await reframe.tools.rescan()


@router.post("/system/tools/fetch", status_code=202, response_model=TaskAccepted)
async def fetch_tools(reframe: ReframeDep, body: FetchRequest | None = None) -> JsonTextResponse:
    """Download, check and install the pinned FFmpeg build, then run discovery again: a task
    whose result is a ``ToolFetchResult``."""
    return accepted(reframe.tools.fetch(build=(body or FetchRequest()).build))


@router.post("/system/shutdown", status_code=204)
async def shutdown(request: Request, config: ConfigDep) -> Response:
    """Stop the server gracefully (desktop mode only: a web server is stopped by its host)."""
    if config.mode != "desktop":
        raise ProblemError(
            403, "system.desktop_only", "Only the desktop app can shut the server down"
        )
    request.app.state.request_shutdown()
    return Response(status_code=204)
