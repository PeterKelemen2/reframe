"""HDR metadata from ffprobe side data (C-3).

Sources, in order:

1. The stream's ``side_data_list`` (``-show_streams``): Matroska ``Colour`` /
   ``MasteringMetadata`` elements, the MP4 ``mdcv`` / ``clli`` boxes, and the Dolby Vision
   configuration record (``dvcC`` / ``dvvC``, Matroska ``BlockAdditionMapping``).
2. If the stream has no mastering display or content light level data, the **first frame's**
   ``side_data_list`` (``-show_frames -read_intervals %+#1``): a single-pass x265 encode has
   the HDR10 metadata only in SEI messages (testdata/README.md, "HDR10 with libx265").
   HDR10+ dynamic metadata exists only per frame, so it is only found there.

Side-data type names (``side_data_type``) and field names, confirmed by a byte search in the
pinned n9.0.2 build (``testdata/probes/README.md``):

- ``Mastering display metadata`` (libavcodec, libavutil): ``red_x`` … ``white_point_y``,
  ``min_luminance``, ``max_luminance`` as ``"num/den"`` strings.
- ``Content light level metadata``: ``max_content``, ``max_average`` (integers).
- ``DOVI configuration record`` (libavcodec): ``dv_version_major``, ``dv_version_minor``,
  ``dv_profile``, ``dv_level``, ``rpu_present_flag``, ``el_present_flag``,
  ``bl_present_flag``, ``dv_bl_signal_compatibility_id``, ``dv_md_compression`` (ffprobe).
- HDR10+: ``HDR Dynamic Metadata SMPTE2094-40 (HDR10+)`` (frame, libavutil) and
  ``HDR10+ Dynamic Metadata (SMPTE 2094-40)`` (packet/stream, libavcodec).

Format rules:

- **HDR10**: transfer ``smpte2084`` (PQ), or no known transfer but static HDR metadata
  (mastering display or content light level). Not for Dolby Vision profile 5 (no HDR10 base
  layer).
- **HLG**: transfer ``arib-std-b67``.
- **HDR10+**: SMPTE 2094-40 side data.
- **Dolby Vision**: a DOVI configuration record (the profile comes from it).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from fractions import Fraction
from typing import Any

from reframe.models.media import (
    ContentLightLevel,
    DolbyVisionInfo,
    HdrFormat,
    HdrInfo,
    MasteringDisplay,
)

__all__ = [
    "CLL_TYPE",
    "DOVI_TYPE",
    "HDR10PLUS_TYPES",
    "HDR_TRANSFERS",
    "MASTERING_TYPE",
    "needs_frame_side_data",
    "parse_hdr",
]

MASTERING_TYPE = "Mastering display metadata"
CLL_TYPE = "Content light level metadata"
DOVI_TYPE = "DOVI configuration record"
HDR10PLUS_TYPES = frozenset(
    {"HDR Dynamic Metadata SMPTE2094-40 (HDR10+)", "HDR10+ Dynamic Metadata (SMPTE 2094-40)"}
)

PQ = "smpte2084"
HLG = "arib-std-b67"
#: Transfers that mean HDR.
HDR_TRANSFERS = frozenset({PQ, HLG})

_MASTERING_FIELDS = {
    "red_x": "red_x",
    "red_y": "red_y",
    "green_x": "green_x",
    "green_y": "green_y",
    "blue_x": "blue_x",
    "blue_y": "blue_y",
    "white_x": "white_point_x",
    "white_y": "white_point_y",
    "min_luminance": "min_luminance",
    "max_luminance": "max_luminance",
}


def _number(value: Any) -> float | None:
    """``"17/25"``, ``"1000/1"``, ``0.68``, ``1000`` → float; anything else → ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            frac = Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            return None
        return float(frac)
    return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def _entries(side_data: Any) -> list[Mapping[str, Any]]:
    if not isinstance(side_data, list):
        return []
    return [entry for entry in side_data if isinstance(entry, Mapping)]


def _find(entries: Iterable[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
    for entry in entries:
        if entry.get("side_data_type") == kind:
            return entry
    return None


def _mastering(entry: Mapping[str, Any] | None) -> MasteringDisplay | None:
    if entry is None:
        return None
    values: dict[str, float] = {}
    for field, key in _MASTERING_FIELDS.items():
        number = _number(entry.get(key))
        if number is None:
            return None  # ffprobe prints all ten, or none if a part is missing
        values[field] = number
    if values["min_luminance"] < 0 or values["max_luminance"] < 0:
        return None
    return MasteringDisplay(**values)


def _light(entry: Mapping[str, Any] | None) -> ContentLightLevel | None:
    if entry is None:
        return None
    max_cll = _int(entry.get("max_content"))
    max_fall = _int(entry.get("max_average"))
    if max_cll is None or max_fall is None:
        return None
    return ContentLightLevel(max_cll=max_cll, max_fall=max_fall)


def _dovi(entry: Mapping[str, Any] | None) -> DolbyVisionInfo | None:
    if entry is None:
        return None
    profile = _int(entry.get("dv_profile"))
    if profile is None:
        return None
    return DolbyVisionInfo(
        profile=profile,
        level=_int(entry.get("dv_level")),
        rpu_present=bool(_int(entry.get("rpu_present_flag"))),
        el_present=bool(_int(entry.get("el_present_flag"))),
        bl_present=bool(_int(entry.get("bl_present_flag"))),
        bl_signal_compatibility_id=_int(entry.get("dv_bl_signal_compatibility_id")),
    )


def _has_static(entries: list[Mapping[str, Any]]) -> bool:
    return _find(entries, MASTERING_TYPE) is not None or _find(entries, CLL_TYPE) is not None


def needs_frame_side_data(stream: Mapping[str, Any], bit_depth: int | None) -> bool:
    """Whether the first frame must be read: HDR is possible but the stream has no static
    HDR metadata, or HDR10+ (only in frames) is possible.

    True for a PQ or HLG transfer, and for a 10-bit (or deeper) stream with BT.2020 primaries
    or matrix whose transfer is unknown (one-pass x265 writes no transfer, only SEI).
    """
    transfer = stream.get("color_transfer")
    if transfer == PQ:
        return True  # static metadata may be missing, and HDR10+ is only in frames
    if transfer == HLG:
        return not _has_static(_entries(stream.get("side_data_list")))
    if transfer not in (None, "unknown", "unspecified", "reserved"):
        return False  # a known SDR transfer (bt709, …)
    deep = bit_depth is not None and bit_depth >= 10
    bt2020 = stream.get("color_primaries") == "bt2020" or str(
        stream.get("color_space", "")
    ).startswith("bt2020")
    return deep and bt2020 and not _has_static(_entries(stream.get("side_data_list")))


def parse_hdr(stream: Mapping[str, Any], frame: Mapping[str, Any] | None = None) -> HdrInfo | None:
    """HDR info of one video stream (``None`` for SDR).

    ``frame`` is the first frame of this stream from ``-show_frames`` (or ``None``). Static
    metadata comes from the stream when it has any, else from the frame (``source="frame"``).
    """
    stream_entries = _entries(stream.get("side_data_list"))
    frame_entries = _entries(frame.get("side_data_list")) if frame is not None else []

    static_from_frame = not _has_static(stream_entries) and _has_static(frame_entries)
    static_entries = frame_entries if static_from_frame else stream_entries
    mastering = _mastering(_find(static_entries, MASTERING_TYPE))
    light = _light(_find(static_entries, CLL_TYPE))
    stream_dovi = _find(stream_entries, DOVI_TYPE)
    dovi = _dovi(stream_dovi or _find(frame_entries, DOVI_TYPE))
    from_frame = static_from_frame or (dovi is not None and stream_dovi is None)
    hdr10plus = any(
        entry.get("side_data_type") in HDR10PLUS_TYPES for entry in stream_entries + frame_entries
    )

    transfer = stream.get("color_transfer")
    if transfer in (None, "unknown", "unspecified", "reserved") and frame is not None:
        transfer = frame.get("color_transfer", transfer)
    formats: list[HdrFormat] = []
    unknown_transfer = transfer in (None, "unknown", "unspecified", "reserved")
    no_hdr10_base = dovi is not None and dovi.profile == 5
    if (transfer == PQ or (unknown_transfer and (mastering or light))) and not no_hdr10_base:
        formats.append(HdrFormat.HDR10)
    if hdr10plus:
        formats.append(HdrFormat.HDR10_PLUS)
    if transfer == HLG:
        formats.append(HdrFormat.HLG)
    if dovi is not None:
        formats.append(HdrFormat.DOLBY_VISION)

    if not formats and mastering is None and light is None:
        return None
    return HdrInfo(
        formats=formats,
        mastering_display=mastering,
        content_light=light,
        dolby_vision=dovi,
        source="frame" if from_frame else "stream",
    )
