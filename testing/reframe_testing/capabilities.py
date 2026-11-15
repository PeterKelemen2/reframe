"""Helpers for encoder-detection tests: a tool-discovery stand-in and replayed capture rules."""

from __future__ import annotations

import asyncio
from pathlib import Path

from reframe.models import ToolInfo, ToolSet, ToolStatus
from reframe_testing import fake_tools as ft

__all__ = ["PINNED_VERSION", "StubTools", "detect_rule", "ffmpeg_info", "tool_set"]

#: ``ffmpeg -version`` of the pinned build (``tools/ffmpeg.toml``).
PINNED_VERSION = "n9.0.2-17-g2a571b6068-20260930"


def ffmpeg_info(
    path: Path | None,
    *,
    version: str | None = PINNED_VERSION,
    status: ToolStatus = ToolStatus.FOUND,
    reason: str | None = None,
    env: dict[str, str] | None = None,
) -> ToolInfo:
    return ToolInfo(
        name="ffmpeg", status=status, path=path, version=version, reason=reason, env=env or {}
    )


def tool_set(ffmpeg: ToolInfo) -> ToolSet:
    """``ffmpeg`` plus a missing ffprobe."""
    ffprobe = ToolInfo(name="ffprobe", status=ToolStatus.MISSING, reason="ffprobe was not found.")
    return ToolSet(ffmpeg=ffmpeg, ffprobe=ffprobe)


class StubTools:
    """The part of ``ToolsService`` that the capability service uses.

    ``gate`` (when set) holds :meth:`status` until it is set, like a slow tool discovery.
    """

    def __init__(self, tools: ToolSet) -> None:
        self.tools = tools
        self.gate: asyncio.Event | None = None
        self.calls = 0

    @property
    def current(self) -> ToolSet | None:
        return self.tools

    async def status(self) -> ToolSet:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return self.tools


def detect_rule(name: str, *, encoder: str | None = None, ten_bit: bool = False) -> ft.Rule:
    """Replay the capture ``name`` (stderr and exit code) for the test encode of ``encoder``
    (default: the capture's ``-c:v``). ``ten_bit``: only for the 10-bit test (``p010le``)."""
    capture = ft.captures()[name]
    command = list(capture.command)
    encoder = encoder or command[command.index("-c:v") + 1]
    actions = [ft.stderr_data(capture.stderr)] if capture.stderr else []
    return ft.Rule(
        actions=actions,
        exit_code=capture.exit_code,
        argv_has=["-c:v", encoder],
        argv_contains=["p010le"] if ten_bit else [],
    )
