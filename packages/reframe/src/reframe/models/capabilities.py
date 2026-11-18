"""Encoder capabilities: the status of each encoder in this FFmpeg build.

Detection runs in the background and never blocks the UI. States:
``unknown → checking → available | unavailable(reason) | error(reason)``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from reframe.models.base import ReframeModel
from reframe.models.text import DisplayText

__all__ = ["BuildMismatchCause", "CapabilitySnapshot", "EncoderState", "EncoderStatus"]


class EncoderState(StrEnum):
    UNKNOWN = "unknown"
    """Not checked yet (or hardware tests are off)."""
    CHECKING = "checking"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    """Not in this build, or the hardware test failed for a known reason (``reason``)."""
    ERROR = "error"
    """The check itself failed (timeout, unknown failure); ``reason`` says what happened."""


#: What an FFmpeg build needs that the computer lacks (``EncoderStatus.build_mismatch_cause``).
BuildMismatchCause = Literal["driver", "system_library"]


class EncoderStatus(ReframeModel):
    """The detection result of one encoder."""

    id: str
    """Encoder id as FFmpeg names it: ``libx265``, ``hevc_nvenc``."""
    state: EncoderState = EncoderState.UNKNOWN
    reason: DisplayText | None = None
    """Plain-language reason for ``unavailable`` / ``error`` ("NVIDIA driver not found")."""
    detail: DisplayText | None = None
    """The FFmpeg line the reason was derived from (for the log and bug reports)."""
    checked_at: AwareDatetime | None = None
    hardware: bool = False
    in_build: bool | None = None
    """Listed by ``ffmpeg -encoders``; ``None`` before the list was read."""
    supports_10bit: bool | None = None
    """``None`` = not known (not tested)."""
    private_options: list[str] = Field(default_factory=list)
    """Private options this build supports (``ffmpeg -h encoder=<id>``)."""
    presets: list[str] = Field(default_factory=list)
    """Speed presets this build offers, if the encoder lists them."""
    pix_fmts: list[str] = Field(default_factory=list)
    """Pixel formats the encoder accepts in this build (the ``Supported pixel formats`` line of
    ``ffmpeg -h encoder=<id>``). VAAPI encoders list only ``vaapi``: they take hardware frames.
    Empty when not read."""
    reason_10bit: DisplayText | None = None
    """Why ``supports_10bit`` is ``False`` when the 10-bit test encode failed ("10-bit is not
    supported by this encoder")."""
    build_mismatch: bool = False
    """``True`` when the encoder is unavailable because this FFmpeg build needs newer system
    software than the computer has (an NVIDIA driver older than the build's NVENC needs, a
    system library too old for the build): a driver update or another FFmpeg build can make it
    available. Never set by a 10-bit-only limit."""
    build_mismatch_cause: BuildMismatchCause | None = None
    """What the build needs when ``build_mismatch`` is ``True``: ``driver``, a newer GPU driver
    (another build can help), or ``system_library``, a system library that is missing or too
    old, such as libva (install or update it, or use an FFmpeg that does not need it). ``None``
    otherwise."""
    device: str | None = None
    """The device the encoder works on, for encoders that need one: the VAAPI render node
    (``/dev/dri/renderD128``), the first node where the test encode worked, or the node that
    Settings → Encoders forces. The command builder uses it. ``None`` for encoders without a
    device choice and for encoders that are not available."""


class CapabilitySnapshot(ReframeModel):
    """Every known encoder's status at one moment, plus the filters of the build.

    The capability service returns one at once (from the cache, or all ``unknown``) and never
    blocks. A finished detection replaces it and publishes ``capabilities.changed``.
    """

    encoders: dict[str, EncoderStatus] = Field(default_factory=dict)
    """By encoder id: every video and audio encoder of the definitions."""
    filters: list[str] | None = None
    """Filters in this FFmpeg build (``ffmpeg -filters``: ``libplacebo``, ``zscale``, …);
    ``None`` until the list was read."""
    filter_failures: dict[str, str] = Field(default_factory=dict)
    """Filters of the build whose run test failed, with the reason. ``libplacebo`` is listed
    by ``ffmpeg -filters`` but needs a working Vulkan device, so detection runs one frame
    through it."""
    untested_filters: list[str] = Field(default_factory=list)
    """Filters of the build that need a run test that has not passed or failed: while the
    detection runs, or when hardware tests are off (Settings → Encoders)."""
    ffmpeg: Path | None = None
    """The ffmpeg binary these results belong to."""
    ffmpeg_version: str | None = None
    detecting: bool = False
    """A detection is running; statuses may still change."""
    from_cache: bool = False
    """The statuses come from the cache and have not been checked again yet."""
    checked_at: AwareDatetime | None = None
    """When the last full detection ended."""

    def status(self, encoder_id: str) -> EncoderStatus:
        """The status of ``encoder_id``; ``unknown`` for an encoder that is not listed."""
        found = self.encoders.get(encoder_id)
        return found if found is not None else EncoderStatus(id=encoder_id)

    def has_filter(self, name: str) -> bool | None:
        """``True`` / ``False`` once the filter list was read, else ``None``. Says only that
        the build has the filter; use :meth:`usable_filter` to choose a filter."""
        return None if self.filters is None else name in self.filters

    def usable_filter(self, name: str) -> bool | None:
        """Can a job use the filter? ``False`` when it is not in the build or its run test
        failed (:attr:`filter_failures`); ``None`` when not known (the filter list was not
        read, or the run test has not finished: :attr:`untested_filters`); else ``True``."""
        if self.filters is None:
            return None
        if name not in self.filters or name in self.filter_failures:
            return False
        if name in self.untested_filters:
            return None
        return True
