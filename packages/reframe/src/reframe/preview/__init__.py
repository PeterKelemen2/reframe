"""Preview tasks (frames, crop detection, preview clips) and their on-disk cache.

Each ``start_*`` function returns its :class:`~reframe.models.TaskInfo` at once. The work runs
in a background task (:mod:`reframe.tasks`).
"""

# See decision 0033 for the choices the plan leaves open: cache keys, one size budget, HDR
# frames, the cropdetect limit, a missing frame and two-pass clips.

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from reframe.mediatask import MediaTaskContext
from reframe.models.job import JobSettings
from reframe.models.tasks import TaskInfo
from reframe.preview.cache import PreviewCache
from reframe.preview.clip import make_clip
from reframe.preview.crop import detect_crop
from reframe.preview.frames import make_frames

__all__ = [
    "cache_size",
    "clear_cache",
    "clip_path",
    "frame_path",
    "start_cropdetect",
    "start_frames",
    "start_preview_clip",
]


def start_frames(
    ctx: MediaTaskContext,
    path: Path,
    *,
    count: int | None,
    timestamps: Sequence[float] | None,
    job: JobSettings | None,
) -> TaskInfo:
    """Task ``frames``: PNG frames of the source at ``timestamps`` (default: ``count`` evenly
    spaced ones, :func:`~reframe.mediatask.sample_timestamps`; ``count`` ``None``: the
    ``preview.sample_frames`` setting), and with ``job`` also the output frames (crop, scale
    and the job's filter graph). Cached on disk (LRU, ``preview.cache_size_mb``) by source
    fingerprint, timestamp and settings hash (:class:`~reframe.models.FrameSet`)."""
    wanted = list(timestamps) if timestamps is not None else None
    snapshot = job.model_copy(deep=True) if job is not None else None
    return ctx.tasks.start(
        "frames",
        lambda tctx: make_frames(tctx, ctx, path, count=count, timestamps=wanted, job=snapshot),
        message=f"Frames of {path.name}",
    )


def frame_path(ctx: MediaTaskContext, key: str) -> Path | None:
    """The cached PNG of ``PreviewFrame.key``, ``None`` when it is not (or no longer) cached.
    Only a key of the frame-key form is looked up (a key from a URL never names another
    file); a hit counts as a use for the LRU. Blocking, like :func:`clear_cache`."""
    return PreviewCache(ctx.cache_dir).find_frame(key)


def start_cropdetect(ctx: MediaTaskContext, path: Path, *, count: int | None) -> TaskInfo:
    """Task ``cropdetect``: ``cropdetect`` on each sample frame (the timestamps of
    :func:`start_frames`), then :func:`~reframe.dimensions.detect_crop_consensus` for the
    automatic and the conservative crop (:class:`~reframe.models.CropDetection`)."""
    return ctx.tasks.start(
        "cropdetect",
        lambda tctx: detect_crop(tctx, ctx, path, count=count),
        message=f"Crop detection of {path.name}",
    )


def start_preview_clip(
    ctx: MediaTaskContext, job: JobSettings, *, start: float, seconds: float
) -> TaskInfo:
    """Task ``preview_clip``: encode ``seconds`` from ``start`` with the job's full plan into
    the cache (:class:`~reframe.models.PreviewClip`)."""
    snapshot = job.model_copy(deep=True)
    return ctx.tasks.start(
        "preview_clip",
        lambda tctx: make_clip(tctx, ctx, snapshot, start=start, seconds=seconds),
        message=f"Preview clip of {Path(job.source.path).name}",
    )


def clip_path(ctx: MediaTaskContext, clip_id: str) -> Path | None:
    """The cached clip of ``PreviewClip.id``, ``None`` when it is not (or no longer) cached;
    a hit counts as a use for the LRU. Blocking, like :func:`clear_cache`."""
    return PreviewCache(ctx.cache_dir).find_clip(clip_id)


def clear_cache(ctx: MediaTaskContext) -> int:
    """Remove every cached frame and clip; returns the bytes freed. Blocking file calls: call
    it in a thread from async code."""
    return PreviewCache(ctx.cache_dir).clear()


def cache_size(ctx: MediaTaskContext) -> int:
    """Bytes of cached frames and clips. Blocking, like :func:`clear_cache`."""
    return PreviewCache(ctx.cache_dir).size()
