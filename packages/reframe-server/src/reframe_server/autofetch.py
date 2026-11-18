"""The FFmpeg check at server start: a warning on the console when Reframe cannot encode yet or
the downloaded build is outdated, and the download of ``REFRAME_FFMPEG_BUILD`` when no FFmpeg is
found. A wrong build name or a failed download never stops the server: it is logged and kept as
a problem of ``GET /api/system`` (and published as ``app.warning``)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from reframe.models import AppWarningEvent, TaskState, ToolOrigin, ToolSet
from reframe.service import Reframe

__all__ = ["CONSOLE_LOGGERS", "AutoFetch"]

log = logging.getLogger(__name__)

#: Loggers whose INFO records the server's console shows with the default settings.
CONSOLE_LOGGERS = ("reframe.tools.fetch", __name__)

OFFLINE = "tools.fetch_offline"


def _cannot_encode(tools: ToolSet) -> str:
    failing = [tool for tool in (tools.ffmpeg, tools.ffprobe) if not tool.usable]
    reasons = "; ".join(f"{tool.name}: {tool.reason or tool.status.value}" for tool in failing)
    return (
        f"Reframe cannot encode yet: no usable FFmpeg ({reasons}). Ways out: open the web UI "
        "and download a build on its first-run screen; or set REFRAME_FFMPEG_BUILD=default to "
        "download one at start; or mount your own build and set REFRAME_FFMPEG (and "
        "REFRAME_FFPROBE)."
    )


class AutoFetch:
    """Runs the start-up check once; :attr:`problems` holds what went wrong."""

    def __init__(self, reframe: Reframe, build: str | None) -> None:
        self._reframe = reframe
        self._build = build.strip() if build else None
        self._task: asyncio.Task[None] | None = None
        self.problems: list[AppWarningEvent] = []

    def start(self, *, download: bool = True) -> None:
        """Start the check in the background; returns at once. ``download=False``: only the
        warnings (another process owns the data folder)."""
        if not download:
            self._build = None
        self._task = asyncio.create_task(self._guarded())

    async def wait(self) -> None:
        """Wait for the check and the download (tests)."""
        if self._task is not None:
            await asyncio.shield(self._task)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _problem(self, code: str, message: str, detail: str | None = None) -> None:
        log.warning("%s%s", message, f": {detail}" if detail else "")
        event = AppWarningEvent(code=code, message=message, detail=detail)
        self.problems.append(event)
        self._reframe.events.publish(event)

    async def _guarded(self) -> None:
        try:
            await self._run()
        except Exception as exc:
            log.exception("the FFmpeg check at start failed")
            if self._build:
                message = f"The download of the FFmpeg build {self._build!r} failed"
                self._problem("tools.fetch_failed", message, str(exc))

    async def _run(self) -> None:
        tools = await self._reframe.tools.status()
        if not (tools.ffmpeg.usable and tools.ffprobe.usable):
            log.warning("%s", _cannot_encode(tools))
        installed = (await self._reframe.tools.builds()).installed
        if installed is not None and installed.outdated:
            log.warning(
                "The downloaded FFmpeg build %r (version %s) is not the one this release pins: "
                "download it again (the web UI's Settings → Tools, or reframe tools fetch "
                "--build %s). It keeps working until then.",
                installed.name,
                installed.version,
                installed.name,
            )
        ffmpeg = tools.ffmpeg
        # An override that fails does not fall back to a download, so one would not help.
        if self._build and not ffmpeg.usable and ffmpeg.origin in (None, ToolOrigin.BUNDLED):
            await self._download(self._build)

    async def _download(self, build: str) -> None:
        names = [offer.name for offer in (await self._reframe.tools.builds()).builds]
        if build not in names:
            self._problem(
                "tools.build_unknown",
                f"REFRAME_FFMPEG_BUILD names no offered FFmpeg build: {build!r}",
                f"The offered builds: {', '.join(names) or 'none'}.",
            )
            return
        started = self._reframe.tools.fetch(build=build)
        log.info(
            "REFRAME_FFMPEG_BUILD: no FFmpeg found, so the download of the FFmpeg build %r "
            "starts (task %s)",
            build,
            started.id,
        )
        task = await self._reframe.tasks.wait(started.id)
        if task.state is TaskState.FAILED:
            message = (
                f"The download server of the FFmpeg build {build!r} cannot be reached"
                if task.error_code == OFFLINE
                else f"The download of the FFmpeg build {build!r} failed"
            )
            self._problem("tools.fetch_failed", message, task.error)
