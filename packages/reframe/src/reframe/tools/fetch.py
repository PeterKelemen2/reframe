"""``reframe tools fetch`` (05 §C-15; 02 §Bundled FFmpeg; 06 §S-6 bare metal): download the
pinned FFmpeg build of the manifest, check its size and SHA-256, and install it as the
bundled build in ``<data dir>/tools/ffmpeg``, where tool discovery (C-1) finds it.

Contract stub: built by the C-15 task (wave 1f). ``Reframe.tools.fetch`` calls
:func:`start_fetch`. Tests never use the network (a local file or a local HTTP server).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from reframe.models.tasks import TaskInfo
from reframe.models.tools import ToolSet
from reframe.tasks import TaskManager

__all__ = ["start_fetch"]


def start_fetch(
    tasks: TaskManager,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str = "default",
    platform: str | None = None,
    manifest: Path | None = None,
) -> TaskInfo:
    """Task ``tools_fetch``: the build ``build`` of ``manifest`` (default: the pinned manifest
    shipped with Reframe) for ``platform`` (``None``: this one), downloaded with progress,
    verified, installed into ``data_dir / "tools" / "ffmpeg"``; then ``rescan()`` (tool
    discovery). Result: :class:`~reframe.models.ToolFetchResult`. A download or checksum
    failure ends the task ``failed`` with the reason; nothing half-installed is left."""
    raise NotImplementedError("C-15 tools fetch")
