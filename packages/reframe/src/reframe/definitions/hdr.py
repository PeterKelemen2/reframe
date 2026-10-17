"""**Copy HDR metadata from source** (03 §Advanced encoder options): the encoder's HDR options
filled from the probe (mastering display, MaxCLL / MaxFALL). Pure.

``Reframe.jobs.hdr_metadata`` turns the values into a JSON patch on ``/video/advanced``. The
command builder (C-7) writes the same strings when the output stays HDR, so a copied value and
the automatic one are identical.

The formats, checked with the encoders (testdata/README.md "Advanced encoder options (C-6,
complete option sets)"):

- x265 ``master-display``: ``G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min)`` with chromaticities in
  units of 0.00002 and luminance in units of 0.0001 cd/m² (SMPTE ST 2086 / the HEVC SEI);
  ``max-cll``: ``MaxCLL,MaxFALL`` in cd/m².
- SVT-AV1 ``mastering-display``: the same layout with plain numbers (``G(0.265,0.69)…
  L(1000,0.0001)``); ``content-light``: ``MaxCLL,MaxFALL``.

Other encoders have no such options: NVENC, QSV, AMF and VAAPI H.265 take the metadata from the
frames' side data (VAAPI's ``-sei hdr`` is on by default); x264 and VP9 cannot carry it.
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
    """``G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)``."""

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
    """``G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)``."""
    f = _plain
    return (
        f"G({f(md.green_x)},{f(md.green_y)})B({f(md.blue_x)},{f(md.blue_y)})"
        f"R({f(md.red_x)},{f(md.red_y)})WP({f(md.white_x)},{f(md.white_y)})"
        f"L({f(md.max_luminance)},{f(md.min_luminance)})"
    )


def content_light_text(cll: ContentLightLevel) -> str:
    """``1000,400`` (MaxCLL, MaxFALL)."""
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
    """``VideoSettings.advanced`` values (option key → value) that carry ``stream``'s HDR10
    metadata with ``encoder``'s own options (x265 ``master-display`` / ``max-cll``, SVT-AV1
    ``mastering-display`` / ``content-light``). Empty when the stream has no HDR10 metadata or
    the encoder has no such options. A mastering display without a peak luminance and a
    content light level of ``0,0`` count as missing. Pure."""
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
