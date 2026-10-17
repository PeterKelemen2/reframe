"""Shared plumbing of the C-10 tasks: scans, loudness, frames, crop detection, preview clips.

05 §C-10: every preview and analysis operation runs as a background **task** (:mod:`reframe.tasks`)
with an id, progress, cancel and a concurrency limit per kind. The facade (``Reframe.sources``,
``Reframe.jobs``) hands one :class:`MediaTaskContext` to the functions of
:mod:`reframe.analysis` and :mod:`reframe.preview`; each starts its work with
``ctx.tasks.start(kind, fn, …)`` and returns the :class:`~reframe.models.TaskInfo` at once.

Inside a task function:

- :func:`require_tool` and :func:`require_source` give a usable ffmpeg / ffprobe and the probed
  source, or raise :class:`TaskFailed` with a message for the user. The task then ends
  ``failed`` with that message as ``TaskInfo.error``: expected failures are data, never an
  exception for the caller.
- Every subprocess goes through ``reframe.tools.run*`` with ``ctx.cancel`` of the
  :class:`~reframe.tasks.TaskContext`, so :meth:`TaskManager.cancel` kills its process tree at
  once (C-10 "Done when": FFmpeg stops within 1 s).
- :func:`sample_timestamps` gives the sample frames' timestamps (frames and crop detection use
  the same ones, so the crop overlay matches the frame strip).

Task kinds and their default concurrency limits are in ``reframe.tasks.DEFAULT_LIMITS``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from reframe.definitions import Definitions
from reframe.events import EventBus
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.media import MediaSource
from reframe.models.settings import AppSettings
from reframe.models.tools import ToolInfo, ToolName, ToolSet, ToolStatus
from reframe.tasks import TaskFailed
from reframe.tools import CancelToken

if TYPE_CHECKING:
    from reframe.probe import ProbeError
    from reframe.tasks import TaskManager

__all__ = [
    "CapabilitiesLookup",
    "MediaTaskContext",
    "SourceAccess",
    "TaskFailed",
    "ToolsLookup",
    "require_source",
    "require_tool",
    "sample_timestamps",
]

#: Share of the duration left out at each end when sampling frames (05 §C-10: "skip the first
#: and last 5 %").
SAMPLE_MARGIN = 0.05


class ToolsLookup(Protocol):
    """``Reframe.tools``."""

    async def status(self) -> ToolSet: ...


class SourceAccess(Protocol):
    """``Reframe.sources``: probe a file (cached) and keep measured values."""

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError: ...

    async def store(self, source: MediaSource) -> None:
        """Keep ``source`` (with measured values) as the known source of its file, in memory
        and in the probe cache, while the file is unchanged."""
        ...

    async def update(
        self, source: MediaSource, change: Callable[[MediaSource], MediaSource]
    ) -> None:
        """Keep ``change(latest)`` like :meth:`store`, where ``latest`` is the known source of
        ``source``'s file at this moment (else ``source``). ``source`` is the version the
        values were measured on: when the file has changed since, nothing is stored. The
        stores and updates of one file run one at a time, so two scans of one file that run
        at the same time keep both their values (each applies only its own)."""
        ...


class CapabilitiesLookup(Protocol):
    """``Reframe.capabilities``."""

    @property
    def snapshot(self) -> CapabilitySnapshot: ...

    async def wait(self) -> CapabilitySnapshot: ...


@dataclass(frozen=True, slots=True)
class MediaTaskContext:
    """What the C-10 tasks get from the facade."""

    tasks: TaskManager
    tools: ToolsLookup
    sources: SourceAccess
    capabilities: CapabilitiesLookup
    settings: Callable[[], AppSettings]
    """The current settings (``preview.sample_frames``, ``preview.cache_size_mb``, …)."""
    events: EventBus
    cache_dir: Path
    """``<cache dir>``: frames go to ``<cache dir>/frames``, preview clips to
    ``<cache dir>/clips``."""
    definitions: Callable[[], Definitions]


def sample_timestamps(duration: float | None, count: int) -> list[float]:
    """``count`` evenly spaced timestamps (seconds, rounded to milliseconds) between 5 % and
    95 % of ``duration``: the first at 5 %, the last at 95 %, one sample in the middle. Empty
    for an unknown or zero duration or ``count < 1``."""
    if duration is None or duration <= 0 or count < 1:
        return []
    low = duration * SAMPLE_MARGIN
    high = duration * (1 - SAMPLE_MARGIN)
    if count == 1:
        return [round(duration / 2, 3)]
    step = (high - low) / (count - 1)
    return [round(low + step * i, 3) for i in range(count)]


async def require_tool(ctx: MediaTaskContext, name: ToolName) -> ToolInfo:
    """The discovered tool ``name`` when it can be used (waits for tool discovery), else
    :class:`TaskFailed` with the tool's reason."""
    tools = await ctx.tools.status()
    info = tools.get(name)
    if info.status is ToolStatus.FOUND and info.path is not None:
        return info
    reason = info.reason or info.status.value
    raise TaskFailed(f"{name} cannot be used: {reason}")


async def require_source(
    ctx: MediaTaskContext, path: str | os.PathLike[str], *, cancel: CancelToken | None = None
) -> MediaSource:
    """The probed source of ``path`` (the probe cache makes this cheap), else
    :class:`TaskFailed` with the probe error's message."""
    outcome = await ctx.sources.probe(path, cancel=cancel)
    if isinstance(outcome, MediaSource):
        return outcome
    detail = f" ({outcome.detail})" if outcome.detail else ""
    raise TaskFailed(f"{outcome.message}{detail}")
