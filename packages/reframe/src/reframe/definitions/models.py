"""Definition schemas (C-6), validated by Pydantic when the TOML data is loaded.

M2 contract stub, written by the lead before M2 wave 1 so that C-4 (encoder detection),
C-6 (definitions) and C-16 (naming) can work in parallel (``docs/m2-breakdown.md``):

- C-6 owns this module and the data. It may **add** models and fields, but must not rename,
  remove or retype the fields below.
- C-4 reads ``VideoEncoderDef`` (``id``, ``hardware``, ``family``, ``vendor``,
  ``platforms``, ``pix_fmts``, ``hardware_setup``, ``fallback``) for the hardware test
  encodes and ``closest_available()``, and the ids of ``AudioEncoderDef`` for the
  capability snapshot.
- C-16 reads ``codec_label`` (``{codec}``) and ``handbrake_key`` (``{encoder}``), and the
  audio ``label`` (``{acodec}``).

Placeholders in argument lists are ``{name}`` strings that the caller resolves, for example
``{vaapi_device}`` (default ``/dev/dri/renderD128``) and ``{sw_pix_fmt}`` (the software pixel
format uploaded to the hardware encoder).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from reframe.models.base import ReframeModel

__all__ = [
    "AudioCodec",
    "AudioEncoderDef",
    "Definitions",
    "EncoderFamily",
    "HardwareSetup",
    "OperatingSystem",
    "Vendor",
    "VideoCodec",
    "VideoEncoderDef",
]

EncoderFamily = Literal["software", "nvenc", "qsv", "amf", "vaapi"]
"""Picker group (03 §Video): Software, NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI."""
Vendor = Literal["nvidia", "intel", "amd"]
VideoCodec = Literal["h264", "hevc", "av1", "vp9", "mpeg2", "mpeg4"]
AudioCodec = Literal["aac", "ac3", "eac3", "opus", "flac", "mp3"]
OperatingSystem = Literal["linux", "windows", "macos"]
_ALL_PLATFORMS: list[OperatingSystem] = ["linux", "windows"]


class HardwareSetup(ReframeModel):
    """How to drive a hardware encoder from FFmpeg."""

    init_args: list[str] = Field(default_factory=list)
    """Global arguments before ``-i``, e.g. ``["-init_hw_device", "vaapi=va:{vaapi_device}",
    "-filter_hw_device", "va"]``."""
    filter_tail: list[str] = Field(default_factory=list)
    """Filters appended at the end of the video filter chain, e.g.
    ``["format={sw_pix_fmt}", "hwupload"]``."""


class VideoEncoderDef(ReframeModel):
    """One FFmpeg video encoder that Reframe knows."""

    id: str
    """The FFmpeg encoder name: ``libx265``, ``hevc_nvenc``."""
    label: str
    """Display name: ``x265``, ``NVIDIA NVENC H.265``."""
    codec: VideoCodec
    codec_label: str
    """Video format for ``{codec}``: ``H.265``."""
    handbrake_key: str
    """HandBrake-style short key for ``{encoder}``: ``x265``, ``nvenc_h265``, ``svt_av1``."""
    family: EncoderFamily
    hardware: bool
    vendor: Vendor | None = None
    platforms: list[OperatingSystem] = Field(default_factory=lambda: _ALL_PLATFORMS.copy())
    pix_fmts: dict[Literal["8", "10"], str] = Field(default_factory=dict)
    """Pixel format fed to the encoder per bit depth (TOML keys are strings). A missing key
    means the encoder does not support that bit depth."""
    hardware_setup: HardwareSetup | None = None
    fallback: list[str] = Field(default_factory=list)
    """Encoder ids to try, in order, when this one is unavailable. Ends with a software
    encoder (the C-6 linter checks it)."""


class AudioEncoderDef(ReframeModel):
    """One FFmpeg audio encoder that Reframe knows. C-6 adds bitrates, mixdowns, sample
    rates and passthru data."""

    id: str
    """The FFmpeg encoder name: ``aac``, ``libopus``."""
    label: str
    """Display name and ``{acodec}``: ``AAC``, ``AC-3``, ``Opus``."""
    codec: AudioCodec


class Definitions(ReframeModel):
    """Everything in ``definitions/data``. C-6 adds options, containers and filters."""

    video_encoders: dict[str, VideoEncoderDef] = Field(default_factory=dict)
    audio_encoders: dict[str, AudioEncoderDef] = Field(default_factory=dict)
