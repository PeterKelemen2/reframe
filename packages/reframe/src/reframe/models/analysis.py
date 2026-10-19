"""Results of the analysis tasks: a bitrate scan, a subtitle scan and a loudness measurement.

Runtime models, never stored as documents. Each is the result of one background task (its
JSON form is ``TaskInfo.result``). The measured values are also written into the probed
source, so later drafts and batch resolutions use them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from reframe.models.base import NonNegativeFloat, NonNegativeInt, ReframeModel
from reframe.models.media import BitrateInfo

__all__ = ["BitrateScan", "LoudnessMeasurement", "SubtitleScan", "SubtitleScanTrack"]


class BitrateScan(ReframeModel):
    """A packet-size scan of one stream."""

    path: Path
    """The source file."""
    stream_index: NonNegativeInt
    """Absolute stream index."""
    bitrate: BitrateInfo
    """``measured``; ``unknown`` when the stream has no packets with a size and a time."""
    packets: NonNegativeInt
    """Packets counted."""
    bytes: NonNegativeInt
    """Sum of their sizes."""
    duration: NonNegativeFloat | None = None
    """Seconds the packets cover (``None`` when no packet had a time)."""


class SubtitleScanTrack(ReframeModel):
    """The scan result of one subtitle track."""

    stream_index: NonNegativeInt
    event_count: NonNegativeInt | None = None
    """Subtitle events (packets) in the track; ``None`` when it could not be counted."""
    forced_event_count: NonNegativeInt | None = None
    """Events with the forced flag: PGS and VobSub only; ``None`` for other formats or when the
    decode failed."""


class SubtitleScan(ReframeModel):
    """Event counts of a source's subtitle tracks."""

    path: Path
    tracks: list[SubtitleScanTrack] = Field(default_factory=list)
    """In the order of the requested stream indexes (all subtitle tracks when none were
    named)."""


class LoudnessMeasurement(ReframeModel):
    """EBU R128 values of one audio track, measured by FFmpeg's ``loudnorm`` filter.

    ``None`` where it prints ``-inf`` or ``inf`` (a silent track).
    """

    path: Path
    stream_index: NonNegativeInt
    integrated: float | None = None
    """Integrated loudness, LUFS (``input_i``)."""
    true_peak: float | None = None
    """True peak, dBTP (``input_tp``)."""
    lra: NonNegativeFloat | None = None
    """Loudness range, LU (``input_lra``)."""
    threshold: float | None = None
    """Gating threshold, LUFS (``input_thresh``)."""
    start: NonNegativeFloat | None = None
    """Start of the measured part in seconds (``None`` = the whole track)."""
    duration: NonNegativeFloat | None = None
    """Length of the measured part in seconds (``None`` = to the end)."""
