"""Preview results: sample frames, crop detection, preview clips.

Runtime models, never stored as documents. Each is the result of one background task; its JSON
form is ``TaskInfo.result``. Frames and clips are files in the cache folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from reframe.models.base import NonNegativeFloat, NonNegativeInt, PositiveInt, ReframeModel
from reframe.models.geometry import CropRect
from reframe.models.job import Container
from reframe.models.plan import JobType
from reframe.models.text import DisplayText

__all__ = ["CropDetection", "CropSample", "FrameKind", "FrameSet", "PreviewClip", "PreviewFrame"]

#: ``source``: the decoded source picture; ``output``: crop, scale and filters of the job
#: applied (rendered by FFmpeg).
FrameKind = Literal["source", "output"]


class PreviewFrame(ReframeModel):
    """One PNG frame in the frame cache."""

    key: str
    """Cache key (source fingerprint + timestamp + settings hash); also the file name."""
    kind: FrameKind
    timestamp: NonNegativeFloat
    """Seconds from the start of the source."""
    path: Path
    """The PNG file."""
    width: PositiveInt
    height: PositiveInt
    cached: bool = False
    """It came from the cache (no FFmpeg run)."""


class FrameSet(ReframeModel):
    """Frames of one source at the same timestamps: the source frames, then (with a job) the
    output frames, each list in timestamp order."""

    path: Path
    """The source file."""
    frames: list[PreviewFrame] = Field(default_factory=list)
    notes: list[DisplayText] = Field(default_factory=list)
    """How the frames were made, one line each (for example how an HDR picture was mapped
    for display)."""


class CropSample(ReframeModel):
    """``cropdetect`` on one sample frame."""

    timestamp: NonNegativeFloat
    crop: CropRect | None = None
    """``None``: no result for this frame (for example a black frame)."""


class CropDetection(ReframeModel):
    """Crop detection over the sample frames."""

    path: Path
    samples: list[CropSample] = Field(default_factory=list)
    auto: CropRect
    """The most common result (the ``auto`` mode of :class:`CropSettings`)."""
    auto_frames: NonNegativeInt = 0
    """Samples that gave the automatic result: ``Detected … on 9 of 10 frames``."""
    conservative: CropRect
    """Only what is black on every sample (the ``conservative`` mode)."""
    notes: list[DisplayText] = Field(default_factory=list)


class PreviewClip(ReframeModel):
    """An encoded preview clip in the cache."""

    id: str
    """The id of the clip in the cache."""
    path: Path
    """The clip file."""
    source: Path
    start: NonNegativeFloat
    """Seconds from the start of the source."""
    duration: NonNegativeFloat
    """The clip's length in seconds."""
    container: Container
    video_codec: str | None = None
    """``h264``, ``hevc``, ``av1``, …: whether a webview can play it, or frames are compared."""
    job_type: JobType = "encode"
    size: NonNegativeInt = 0
    """Bytes."""
