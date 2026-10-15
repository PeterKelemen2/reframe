"""Analysis tasks (05 §C-10): bitrate scan, subtitle scans, loudness measure.

Each function starts a background task (:mod:`reframe.tasks`) with the facade's
:class:`~reframe.mediatask.MediaTaskContext` and returns its :class:`~reframe.models.TaskInfo`
at once. The results are :mod:`reframe.models.analysis` models. ``Reframe.sources`` calls
these (``bitrate_scan``, ``subtitle_scan``, ``loudness_scan``); the signatures are the contract
of ``docs/core-breakdown.md``.

Contract stubs: the bodies are built by the C-10 scans task (wave 1b).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from reframe.mediatask import MediaTaskContext
from reframe.models.tasks import TaskInfo

__all__ = ["start_bitrate_scan", "start_loudness_scan", "start_subtitle_scan"]


def start_bitrate_scan(ctx: MediaTaskContext, path: Path, stream_index: int) -> TaskInfo:
    """Task ``bitrate_scan``: the packet sizes of one stream → its average bit rate
    (:class:`~reframe.models.BitrateScan`). Streams progress, can be cancelled. When done, the
    measured bit rate is stored in the source (``ctx.sources.store``)."""
    raise NotImplementedError("C-10 bitrate scan")


def start_subtitle_scan(
    ctx: MediaTaskContext, path: Path, stream_indexes: Sequence[int] | None
) -> TaskInfo:
    """Task ``subtitle_scan``: event counts of the subtitle tracks (all when
    ``stream_indexes`` is ``None``), and the forced events of PGS / VobSub tracks (a decode
    with ``forced_subs_only``) (:class:`~reframe.models.SubtitleScan`). When done, the counts
    are stored in the source (``ctx.sources.store``)."""
    raise NotImplementedError("C-10 subtitle scan")


def start_loudness_scan(
    ctx: MediaTaskContext,
    path: Path,
    stream_index: int,
    *,
    start: float | None,
    duration: float | None,
) -> TaskInfo:
    """Task ``loudness``: ``loudnorm=print_format=json`` on one audio track, the whole track
    or ``duration`` seconds from ``start`` (:class:`~reframe.models.LoudnessMeasurement`)."""
    raise NotImplementedError("C-10 loudness measure")
