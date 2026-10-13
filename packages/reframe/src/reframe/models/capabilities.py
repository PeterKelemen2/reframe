"""Encoder capabilities (C-4): the status of each encoder in this FFmpeg build.

Detection runs in the background and never blocks the UI. States:
``unknown → checking → available | unavailable(reason) | error(reason)``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, Field

from reframe.models.base import ReframeModel

__all__ = ["CapabilitySnapshot", "EncoderState", "EncoderStatus"]


class EncoderState(StrEnum):
    UNKNOWN = "unknown"
    """Not checked yet (or hardware tests are off)."""
    CHECKING = "checking"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    """Not in this build, or the hardware test failed for a known reason (``reason``)."""
    ERROR = "error"
    """The check itself failed (timeout, unknown failure); ``reason`` says what happened."""


class EncoderStatus(ReframeModel):
    """``EncoderStatus(id, state, reason, checked_at, supports_10bit, …)``."""

    id: str
    """Encoder id as FFmpeg names it: ``libx265``, ``hevc_nvenc``."""
    state: EncoderState = EncoderState.UNKNOWN
    reason: str | None = None
    """Plain-language reason for ``unavailable`` / ``error`` ("NVIDIA driver not found")."""
    detail: str | None = None
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


class CapabilitySnapshot(ReframeModel):
    """Every known encoder's status at one moment (C-4), plus the filters of the build.

    The ``caps`` argument of ``build_plan`` (C-7) and ``validate`` (C-8). The capability
    service returns one at once (from the cache, or all ``unknown``) and never blocks; a
    finished detection replaces it and publishes ``capabilities.changed``.
    """

    encoders: dict[str, EncoderStatus] = Field(default_factory=dict)
    """By encoder id: every video and audio encoder of the definitions (C-6)."""
    filters: list[str] | None = None
    """Filters in this FFmpeg build (``ffmpeg -filters``: ``libplacebo``, ``zscale``, …);
    ``None`` until the list was read."""
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
        """``True`` / ``False`` once the filter list was read, else ``None``."""
        return None if self.filters is None else name in self.filters
