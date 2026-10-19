"""HDR10 metadata for an encoder's own options, made from the probe. Pure: no I/O.

The strings must match the ones the command builder writes for HDR output, so a copied value
and the automatic one are identical. Other encoders take no such options. NVENC, QSV, AMF and
VAAPI H.265 read the metadata from the frames' side data (VAAPI's ``-sei hdr`` is on by
default), and x264 and VP9 cannot carry it.
"""

from __future__ import annotations

from collections.abc import Callable

from reframe.definitions.models import VideoEncoderDef
from reframe.models.job import OptionValue
from reframe.models.media import ContentLightLevel, HdrInfo, MasteringDisplay, VideoStream

__all__ = [
    "content_light_text",
    "hdr_options",
    "svt_mastering_display",
    "x265_master_display",
]


def x265_master_display(md: MasteringDisplay) -> str:
    """x265 ``master-display``: chromaticity in units of 0.00002, luminance in 0.0001 cd/m²."""

    def c(v: float) -> int:
        return round(v * 50000)

    def lum(v: float) -> int:
        return round(v * 10000)

    return (
        f"G({c(md.green_x)},{c(md.green_y)})B({c(md.blue_x)},{c(md.blue_y)})"
        f"R({c(md.red_x)},{c(md.red_y)})WP({c(md.white_x)},{c(md.white_y)})"
        f"L({lum(md.max_luminance)},{lum(md.min_luminance)})"
    )


def _plain(value: float) -> str:
    rounded = round(value, 6)
    if float(rounded).is_integer():
        return str(int(rounded))
    return repr(float(rounded))


def svt_mastering_display(md: MasteringDisplay) -> str:
    """SVT-AV1 ``mastering-display``: plain numbers, not the x265 integer units."""
    f = _plain
    return (
        f"G({f(md.green_x)},{f(md.green_y)})B({f(md.blue_x)},{f(md.blue_y)})"
        f"R({f(md.red_x)},{f(md.red_y)})WP({f(md.white_x)},{f(md.white_y)})"
        f"L({f(md.max_luminance)},{f(md.min_luminance)})"
    )


def content_light_text(cll: ContentLightLevel) -> str:
    return f"{cll.max_cll},{cll.max_fall}"


def _display(format_: Callable[[MasteringDisplay], str]) -> Callable[[HdrInfo], str | None]:
    def value(hdr: HdrInfo) -> str | None:
        md = hdr.mastering_display
        return format_(md) if md is not None and md.max_luminance > 0 else None

    return value


def _light(hdr: HdrInfo) -> str | None:
    cll = hdr.content_light
    if cll is None or (cll.max_cll == 0 and cll.max_fall == 0):
        return None
    return content_light_text(cll)


#: The params-argument names of HDR10 options and how their value is made from the probe.
_PARAMS: dict[str, Callable[[HdrInfo], str | None]] = {
    "master-display": _display(x265_master_display),  # x265
    "max-cll": _light,  # x265
    "mastering-display": _display(svt_mastering_display),  # SVT-AV1
    "content-light": _light,  # SVT-AV1
}


def hdr_options(encoder: VideoEncoderDef, stream: VideoStream) -> dict[str, OptionValue]:
    """The ``VideoSettings.advanced`` values (option key → value) that carry the HDR10 metadata
    of ``stream``. Empty when the stream has no HDR10 metadata or the encoder has no such
    options. A mastering display without a peak luminance, and a content light level of
    ``0,0``, count as missing."""
    hdr = stream.hdr
    if hdr is None:
        return {}
    values: dict[str, OptionValue] = {}
    for option in encoder.options:
        mapping = option.mapping
        if mapping.kind != "x26x_param" or mapping.part is not None:
            continue
        make = _PARAMS.get(mapping.name)
        value = make(hdr) if make is not None else None
        if value is not None:
            values[option.key] = value
    return values
