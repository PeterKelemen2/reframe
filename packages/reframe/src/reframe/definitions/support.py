"""What this FFmpeg build supports of an encoder's definition (05 §C-4, bullet 2).

C-4 reads ``ffmpeg -h encoder=<id>`` into ``EncoderStatus.private_options`` (option names
without the dash) and ``EncoderStatus.presets``. Options in the definitions that the build
does not list are hidden.
"""

from __future__ import annotations

from reframe.definitions.models import Choice, EncoderOption, OptionMapping, VideoEncoderDef
from reframe.models.capabilities import EncoderStatus

__all__ = ["mapping_supported", "supported_options", "supported_presets"]


def mapping_supported(
    encoder: VideoEncoderDef, mapping: OptionMapping, status: EncoderStatus | None
) -> bool:
    """Whether the build can take a value through ``mapping``.

    ``status`` ``None``, or a status whose private options were not read (empty list), hides
    nothing. Generic codec options (``ffmpeg_arg``) are always supported; ``private_opt``
    needs the option in the build; ``x26x_param`` needs the encoder's params argument.
    """
    if status is None or not status.private_options:
        return True
    known = set(status.private_options)
    if mapping.kind == "private_opt":
        return mapping.name in known
    if mapping.kind == "x26x_param":
        return encoder.params_arg is not None and encoder.params_arg.lstrip("-") in known
    return True


def supported_options(
    encoder: VideoEncoderDef, status: EncoderStatus | None
) -> list[EncoderOption]:
    """``encoder.options`` without the options this build does not support."""
    return [o for o in encoder.options if mapping_supported(encoder, o.mapping, status)]


def supported_presets(encoder: VideoEncoderDef, status: EncoderStatus | None) -> list[Choice]:
    """The speed presets of ``encoder`` that this build lists.

    When the build lists no presets for the encoder (``status.presets`` empty: a free-text
    ``-preset`` such as libx264's, or not read yet), all defined presets are returned.
    """
    if encoder.presets is None:
        return []
    choices = encoder.presets.choices
    if status is None or not status.presets:
        return list(choices)
    listed = set(status.presets)
    return [c for c in choices if c.value in listed or c.written in listed]
