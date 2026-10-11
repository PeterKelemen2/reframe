"""Encoder capabilities (C-4): the status of each encoder in this FFmpeg build.

Detection runs in the background and never blocks the UI. States:
``unknown → checking → available | unavailable(reason) | error(reason)``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field

from reframe.models.base import ReframeModel

__all__ = ["EncoderState", "EncoderStatus"]


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
