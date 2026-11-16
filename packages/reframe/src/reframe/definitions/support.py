"""What this FFmpeg build supports of an encoder's definition. Options and presets that the
build does not list (``EncoderStatus``) are hidden. An empty list hides nothing.
"""

from __future__ import annotations

from reframe.definitions.models import Choice, OptionMapping, VideoEncoderDef
from reframe.models.capabilities import EncoderStatus

__all__ = ["mapping_supported", "supported_presets"]


def mapping_supported(
    encoder: VideoEncoderDef, mapping: OptionMapping, status: EncoderStatus | None
) -> bool:
    """Whether the build can take a value through ``mapping``. A ``None`` status, or one whose
    private options were not read (an empty list), hides nothing."""
    if status is None or not status.private_options:
        return True
    known = set(status.private_options)
    if mapping.kind == "private_opt":
        return mapping.name in known
    if mapping.kind == "x26x_param":
        return encoder.params_arg is not None and encoder.params_arg.lstrip("-") in known
    return True


def supported_presets(encoder: VideoEncoderDef, status: EncoderStatus | None) -> list[Choice]:
    """The speed presets of ``encoder`` that this build lists. With no list from the build
    (``status.presets`` empty, or not read yet), every defined preset is returned: x264 and x265
    take free text, so there is no list to read."""
    if encoder.presets is None:
        return []
    choices = encoder.presets.choices
    if status is None or not status.presets:
        return list(choices)
    listed = set(status.presets)
    return [c for c in choices if c.value in listed or c.written in listed]
