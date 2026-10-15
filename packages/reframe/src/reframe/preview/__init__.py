"""Preview tasks (05 §C-10): frames, crop detection, preview clips, and their cache.

Each ``start_*`` function starts a background task (:mod:`reframe.tasks`) with the facade's
:class:`~reframe.mediatask.MediaTaskContext` and returns its :class:`~reframe.models.TaskInfo`
at once. The results are :mod:`reframe.models.preview` models. ``Reframe.sources`` calls
``start_frames``, ``frame_path`` and ``start_cropdetect``; ``Reframe.jobs`` calls
``start_preview_clip`` and ``clip_path``. The signatures are the contract of
``docs/core-breakdown.md``.

Contract stubs: the bodies are built by the C-10 picture task (wave 1c).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from reframe.mediatask import MediaTaskContext
from reframe.models.job import JobSettings
from reframe.models.tasks import TaskInfo

__all__ = ["clip_path", "frame_path", "start_cropdetect", "start_frames", "start_preview_clip"]


def start_frames(
    ctx: MediaTaskContext,
    path: Path,
    *,
    count: int | None,
    timestamps: Sequence[float] | None,
    job: JobSettings | None,
) -> TaskInfo:
    """Task ``frames``: PNG frames of the source at ``timestamps`` (default: ``count`` evenly
    spaced ones, :func:`~reframe.mediatask.sample_timestamps`; ``count`` ``None`` = Settings →
    Preview ``sample_frames``), and with ``job`` also the output frames (crop, scale and the
    job's filter graph). Cached on disk (LRU, ``preview.cache_size_mb``) by source fingerprint
    + timestamp + settings hash (:class:`~reframe.models.FrameSet`)."""
    raise NotImplementedError("C-10 frames")


def frame_path(ctx: MediaTaskContext, key: str) -> Path | None:
    """The cached PNG of ``PreviewFrame.key``, ``None`` when it is not (or no longer) cached."""
    raise NotImplementedError("C-10 frame cache")


def start_cropdetect(ctx: MediaTaskContext, path: Path, *, count: int | None) -> TaskInfo:
    """Task ``cropdetect``: ``cropdetect`` on each sample frame (the timestamps of
    :func:`start_frames`), then C-5's ``detect_crop_consensus`` for the automatic and the
    conservative crop (:class:`~reframe.models.CropDetection`)."""
    raise NotImplementedError("C-10 crop detection")


def start_preview_clip(
    ctx: MediaTaskContext, job: JobSettings, *, start: float, seconds: float
) -> TaskInfo:
    """Task ``preview_clip``: encode ``seconds`` from ``start`` with the job's full plan into
    the cache (:class:`~reframe.models.PreviewClip`)."""
    raise NotImplementedError("C-10 preview clip")


def clip_path(ctx: MediaTaskContext, clip_id: str) -> Path | None:
    """The cached clip of ``PreviewClip.id``, ``None`` when it is not (or no longer) cached."""
    raise NotImplementedError("C-10 preview clip cache")
