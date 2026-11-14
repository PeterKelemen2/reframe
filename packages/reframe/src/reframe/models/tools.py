"""External tool status: which ffmpeg / ffprobe / mkvpropedit / mediainfo is used.

Produced by :func:`reframe.tools.discover_tools`. A missing, broken or too old tool is data
(:class:`ToolStatus` plus a reason and fixes), never an exception.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from reframe.models.base import ReframeModel
from reframe.models.issues import Fix
from reframe.models.text import DisplayText

__all__ = ["ToolFetchResult", "ToolInfo", "ToolName", "ToolOrigin", "ToolSet", "ToolStatus"]

#: The external tools Reframe uses. ``mkvpropedit`` and ``mediainfo`` are optional.
ToolName = Literal["ffmpeg", "ffprobe", "mkvpropedit", "mediainfo"]


class ToolOrigin(StrEnum):
    """Where the tool path came from, in discovery order."""

    ENV = "env"
    """An environment variable (``REFRAME_FFMPEG`` …). Read-only in the UI."""
    SETTINGS = "settings"
    """A path in Settings → Tools."""
    BUNDLED = "bundled"
    """The pinned build that ships with Reframe (or that ``reframe tools fetch`` installed)."""
    PATH = "path"
    """Found on ``PATH`` (only used when there is no bundled build of the tool)."""
    INSTALLED = "installed"
    """Found where the tool's own Windows installer puts it, which is not on ``PATH``
    (mkvpropedit: MKVToolNix's folder). Searched after ``PATH``."""


class ToolStatus(StrEnum):
    FOUND = "found"
    """The tool runs and is new enough."""
    MISSING = "missing"
    """No binary at the configured path, or not found anywhere."""
    TOO_OLD = "too_old"
    """It runs, but its version is below the minimum."""
    BROKEN = "broken"
    """The file exists but does not run, times out, fails ``-version``, or is not that tool."""


class ToolInfo(ReframeModel):
    """The result of discovering one tool.

    When ``origin`` is ``env`` or ``settings`` and the status is not ``found``, Reframe does
    **not** fall back to the bundled build: ``reason`` says why, and ``fixes`` offers
    "Use bundled" (a patch on ``AppSettings`` that removes the Settings path). An environment
    override cannot be changed in the app, so it has no fix, and the reason says so.
    """

    name: ToolName
    status: ToolStatus
    path: Path | None = None
    """The binary that is (or would be) run. Set for a missing override too (the bad path)."""
    origin: ToolOrigin | None = None
    """``None`` when nothing was found."""
    reason: DisplayText | None = None
    """Why the status is not ``found``; for ``found`` an optional note (for example "version
    could not be read")."""
    version: str | None = None
    """The version string as the tool prints it."""
    release: str | None = None
    """The upstream release; ``None`` for git master builds."""
    release_series: str | None = None
    """The release series of a release. For a git master build, the series of its library
    versions, which the minimum-version check uses."""
    build_flags: list[str] = Field(default_factory=list)
    """FFmpeg: the arguments of the ``configuration:`` line (``--enable-libx265`` …), for
    diagnostics."""
    library_versions: dict[str, str] = Field(default_factory=dict)
    """FFmpeg: the version of each library, by name."""
    env: dict[str, str] = Field(default_factory=dict)
    """Extra environment variables to set when running this tool (for example
    ``LIBVA_DRIVERS_PATH`` for the bundled FFmpeg on Linux)."""
    env_var: str | None = None
    """The environment variable that overrides this tool (``REFRAME_FFMPEG``)."""
    next_to_ffmpeg: bool = False
    """ffprobe only: it was found next to an overridden ffmpeg (its ``origin`` is the ffmpeg's)."""
    bundled: bool = False
    """A bundled build of the tool's family (FFmpeg: ffmpeg and ffprobe) exists, so without a
    Settings path discovery uses it. Also set while an override is in use."""
    fixes: list[Fix] = Field(default_factory=list)


class ToolSet(ReframeModel):
    """The discovery result for all four tools."""

    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    mkvpropedit: ToolInfo
    mediainfo: ToolInfo

    def get(self, name: ToolName) -> ToolInfo:
        info: ToolInfo = getattr(self, name)
        return info


class ToolFetchResult(ReframeModel):
    """The pinned FFmpeg build, downloaded, checked (size and SHA-256) and installed as the
    bundled build in ``<data dir>/tools/ffmpeg``, where tool discovery finds it."""

    build: str
    """The manifest's build name (``default``)."""
    platform: str
    """``linux-x64`` or ``windows-x64``."""
    version: str
    """The pinned FFmpeg version string."""
    install_dir: Path
    """``<data dir>/tools/ffmpeg``."""
    ffmpeg: Path
    ffprobe: Path
    downloaded: bool = True
    """``False``: the build was already installed and every file still had its hash."""
