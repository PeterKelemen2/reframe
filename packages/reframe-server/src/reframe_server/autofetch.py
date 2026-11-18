"""The FFmpeg check at server start: a warning on the console when Reframe cannot encode yet or
the downloaded build is outdated, and the download of ``REFRAME_FFMPEG_BUILD`` when no usable
FFmpeg is found. A wrong build name, a skipped or a failed download never stops the server: it
is logged and kept as a problem of ``GET /api/system`` (and published as ``app.warning``)."""

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
VARIABLE = "REFRAME_FFMPEG_BUILD"


def _cannot_encode(tools: ToolSet, *, build_set: bool) -> str:
    failing = [tool for tool in (tools.ffmpeg, tools.ffprobe) if not tool.usable]
    reasons = "; ".join(
        f"{tool.name}: {(tool.reason or tool.status.value).rstrip('.')}" for tool in failing
    )
    download = "" if build_set else f"; or set {VARIABLE}=default to download one at start"
    return (
        f"Reframe cannot encode yet: no usable FFmpeg ({reasons}). Ways out: open the web UI "
        f"and download a build on its first-run screen{download}; or mount your own build and "
        "set REFRAME_FFMPEG (and REFRAME_FFPROBE)."
    )


def _override(tools: ToolSet) -> str | None:
    """Where a tool path that a download must not replace comes from; ``None`` without one."""
    for tool in (tools.ffmpeg, tools.ffprobe):
        if tool.origin is ToolOrigin.ENV:
            return tool.env_var or "the environment"
        if tool.origin is ToolOrigin.SETTINGS:
            return "Settings → Tools"
    return None


class AutoFetch:
    """Runs the start-up check once; :attr:`problems` holds what went wrong."""

    def __init__(self, reframe: Reframe, build: str | None) -> None:
        self._reframe = reframe
        self._build = build.strip() if build else None
        self._owner = True
        self._task: asyncio.Task[None] | None = None
        self.problems: list[AppWarningEvent] = []

    def start(self, *, download: bool = True) -> None:
        """Start the check in the background; returns at once. ``download=False``: another
        process owns the data folder, so nothing is downloaded."""
        self._owner = download
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
        event = AppWarningEvent(code=code, message=message, detail=detail)
        self.problems.append(event)
        self._reframe.events.publish(event)

    def _skip(self, why: str, detail: str) -> None:
        log.warning(
            "%s=%s: nothing is downloaded, because %s. %s", VARIABLE, self._build, why, detail
        )
        message = f"{VARIABLE} is set, but nothing is downloaded, because {why}"
        self._problem("tools.fetch_skipped", message, detail)

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
        usable = tools.ffmpeg.usable and tools.ffprobe.usable
        if not usable:
            log.warning("%s", _cannot_encode(tools, build_set=self._build is not None))
        offered = await self._reframe.tools.builds()
        installed = offered.installed
        if installed is not None and installed.outdated:
            log.warning(
                "The downloaded FFmpeg build %r (version %s) is not the one this release pins: "
                "download it again (the web UI's Settings → Tools, or reframe tools fetch "
                "--build %s). It keeps working until then.",
                installed.name,
                installed.version,
                installed.name,
            )
        build = self._build
        if build is None:
            return
        names = [offer.name for offer in offered.builds]
        if build not in names:
            listed = ", ".join(names) or "none"
            log.warning(
                "%s=%s names no offered FFmpeg build (the offered builds: %s), so nothing is "
                "downloaded",
                VARIABLE,
                build,
                listed,
            )
            self._problem(
                "tools.build_unknown",
                f"{VARIABLE} names no offered FFmpeg build ({build!r})",
                f"The offered builds are {listed}.",
            )
            return
        if usable:
            log.info("%s=%s: FFmpeg is found, so nothing is downloaded", VARIABLE, build)
            return
        override = _override(tools)
        if override is not None:
            self._skip(
                f"the FFmpeg path comes from {override}",
                "A download never replaces a path set in the environment or in Settings → "
                "Tools. Correct or remove that path.",
            )
            return
        if not self._owner:
            self._skip(
                "another Reframe process uses this data folder",
                "Let the process that owns the data folder download it, or download a build on "
                "the web UI's first-run screen.",
            )
            return
        await self._download(build)

    async def _download(self, build: str) -> None:
        started = self._reframe.tools.fetch(build=build)
        log.info(
            "%s=%s: no usable FFmpeg found, so the download of the FFmpeg build %r starts "
            "(task %s)",
            VARIABLE,
            build,
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
            log.warning(
                "%s=%s: the download failed, so Reframe cannot encode yet (the download's error "
                "line says why)",
                VARIABLE,
                build,
            )
            self._problem("tools.fetch_failed", message, task.error)
