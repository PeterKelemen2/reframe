"""The bitrate chain (C-3, 03 §Audio "Bitrate").

In order, the first that gives a value wins:

1. ffprobe's stream ``bit_rate`` (``BitrateSource.STREAM``). In ``-of json`` output a missing
   bit rate is a missing key, not ``"N/A"`` (testdata/README.md).
2. Matroska statistics tags written by mkvmerge or ``mkvpropedit
   --add-track-statistics-tags`` (``BitrateSource.STATS_TAG``): ``BPS``, else
   8 * ``NUMBER_OF_BYTES`` / ``DURATION``. ffprobe appends the tag language when it is not
   ``und`` (``BPS-eng``, written by older mkvmerge versions). FFmpeg's own Matroska muxer
   writes only ``DURATION``, so a file written by FFmpeg has no statistics tags.
3. MediaInfo (``BitrateSource.MEDIAINFO``), if ``pymediainfo`` and its library load:
   :mod:`reframe.probe.mediainfo`, applied by :func:`reframe.probe.probe_file` because it
   needs the file.
4. ``BitrateSource.UNKNOWN`` (C-12 treats it as above every maximum).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from reframe.models.media import BitrateInfo, BitrateSource

__all__ = [
    "parse_duration_tag",
    "positive_int",
    "stats_tag_bitrate",
    "stream_bitrate",
    "tag_value",
]

_DURATION_RE = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*$")


def positive_int(value: Any) -> int | None:
    """``"192000"``, ``192000``, ``"192000.0"`` → 192000; zero, negative or junk → ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if number != number or number <= 0 or number == float("inf"):  # NaN, ≤ 0, inf
        return None
    return round(number)


def tag_value(tags: Mapping[str, Any] | None, name: str) -> str | None:
    """A tag by name, case-insensitive, also with a language suffix (``BPS-eng``)."""
    if not tags:
        return None
    wanted = name.upper()
    suffixed: str | None = None
    for key, value in tags.items():
        upper = str(key).upper()
        if upper == wanted:
            return str(value)
        if suffixed is None and upper.startswith(wanted + "-"):
            suffixed = str(value)
    return suffixed


def parse_duration_tag(value: str | None) -> float | None:
    """Matroska ``DURATION`` (``00:00:04.021000000``) → seconds."""
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)


def stats_tag_bitrate(tags: Mapping[str, Any] | None) -> int | None:
    """Bit rate from the Matroska statistics tags, or ``None``."""
    bps = positive_int(tag_value(tags, "BPS"))
    if bps is not None:
        return bps
    size = positive_int(tag_value(tags, "NUMBER_OF_BYTES"))
    seconds = parse_duration_tag(tag_value(tags, "DURATION"))
    if size is None or not seconds:
        return None
    return round(size * 8 / seconds)


def stream_bitrate(stream: Mapping[str, Any]) -> BitrateInfo:
    """Steps 1, 2 and 4 of the chain for one ffprobe stream."""
    value = positive_int(stream.get("bit_rate"))
    if value is not None:
        return BitrateInfo(value=value, source=BitrateSource.STREAM)
    tags = stream.get("tags")
    value = stats_tag_bitrate(tags if isinstance(tags, Mapping) else None)
    if value is not None:
        return BitrateInfo(value=value, source=BitrateSource.STATS_TAG)
    return BitrateInfo()
