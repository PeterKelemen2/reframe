"""The bitrate chain (C-3, 03 §Audio "Bitrate").

In order, the first that gives a value wins:

1. ffprobe's stream ``bit_rate`` (``BitrateSource.STREAM``). In ``-of json`` output a missing
   bit rate is a missing key, not ``"N/A"`` (testdata/README.md).
2. Matroska statistics tags written by mkvmerge or ``mkvpropedit
   --add-track-statistics-tags`` (``BitrateSource.STATS_TAG``): ``BPS``, else
   8 * ``NUMBER_OF_BYTES`` / ``DURATION``. ffprobe appends the tag language when it is not
   ``und`` (``BPS-eng``, written by older mkvmerge versions). FFmpeg's own Matroska muxer
   writes only ``DURATION``, so a file written by FFmpeg has no statistics tags.

   **Stale tags.** FFmpeg copies stream tags when it re-encodes, so a re-encoded file can
   carry the statistics of its source (a 200 kb/s re-encode that says ``BPS=1858881``).
   :func:`check_stats_tags` therefore checks the tags against the container first; tags that
   fail are not used (for the bit rate, the frame count, the subtitle event count or the VFR
   check) and the probe gets a warning. Checks: the tracks' ``NUMBER_OF_BYTES`` add up to at
   most the file size; a track's ``BPS`` is at most the container bit rate (+5 %); a track's
   ``DURATION`` is at most the container duration (+5 % + 1 s). (The container's ``ENCODER``
   tag cannot tell who wrote the file: mkvmerge copies a source's global ``ENCODER=Lavf…``
   tag, so a check of ``_STATISTICS_WRITING_APP`` against it would reject good tags.)
3. MediaInfo (``BitrateSource.MEDIAINFO``), if ``pymediainfo`` and its library load:
   :mod:`reframe.probe.mediainfo`, applied by :func:`reframe.probe.probe_file` because it
   needs the file.
4. ``BitrateSource.UNKNOWN`` (C-12 treats it as above every maximum).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from reframe.models.media import BitrateInfo, BitrateSource

__all__ = [
    "STATS_TAG_NAMES",
    "StatsCheck",
    "check_stats_tags",
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


def stream_bitrate(stream: Mapping[str, Any], *, trust_stats: bool = True) -> BitrateInfo:
    """Steps 1, 2 and 4 of the chain for one ffprobe stream (step 2 only if ``trust_stats``)."""
    value = positive_int(stream.get("bit_rate"))
    if value is not None:
        return BitrateInfo(value=value, source=BitrateSource.STREAM)
    if not trust_stats:
        return BitrateInfo()
    tags = stream.get("tags")
    value = stats_tag_bitrate(tags if isinstance(tags, Mapping) else None)
    if value is not None:
        return BitrateInfo(value=value, source=BitrateSource.STATS_TAG)
    return BitrateInfo()


#: Tags that make a stream "have statistics tags".
STATS_TAG_NAMES = (
    "BPS",
    "NUMBER_OF_BYTES",
    "NUMBER_OF_FRAMES",
    "_STATISTICS_TAGS",
    "_STATISTICS_WRITING_APP",
)

_BPS_TOLERANCE = 1.05
_DURATION_TOLERANCE = 1.05
_DURATION_SLACK = 1.0


@dataclass(frozen=True)
class StatsCheck:
    """The result of :func:`check_stats_tags`: the streams whose statistics tags look stale."""

    stale: dict[int, str] = field(default_factory=dict)
    """Stream index → why its statistics tags are not used."""

    def trusted(self, index: int) -> bool:
        return index not in self.stale


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _has_stats(tags: Mapping[str, Any]) -> bool:
    return any(tag_value(tags, name) is not None for name in STATS_TAG_NAMES)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if abs(number) < float("inf") else None  # also False for NaN


def check_stats_tags(data: Mapping[str, Any]) -> StatsCheck:
    """Check every stream's Matroska statistics tags against the container (module doc)."""
    raw = data.get("streams")
    streams = [s for s in raw if isinstance(s, Mapping)] if isinstance(raw, list) else []
    fmt = _mapping(data.get("format"))
    size = positive_int(fmt.get("size"))
    total_rate = positive_int(fmt.get("bit_rate"))
    duration = _finite(fmt.get("duration"))

    with_stats = [s for s in streams if _has_stats(_mapping(s.get("tags")))]
    byte_sum = sum(
        positive_int(tag_value(_mapping(s.get("tags")), "NUMBER_OF_BYTES")) or 0 for s in with_stats
    )
    stale: dict[int, str] = {}
    for stream in with_stats:
        index = positive_int(stream.get("index")) or 0
        tags = _mapping(stream.get("tags"))
        bps = positive_int(tag_value(tags, "BPS"))
        tag_duration = parse_duration_tag(tag_value(tags, "DURATION"))
        reason: str | None = None
        if size is not None and byte_sum > size:
            reason = (
                f"the tracks' NUMBER_OF_BYTES add up to {byte_sum} bytes, more than the "
                f"file's {size} bytes"
            )
        elif total_rate is not None and bps is not None and bps > total_rate * _BPS_TOLERANCE:
            reason = f"BPS {bps} is more than the file's bit rate {total_rate}"
        elif (
            duration is not None
            and tag_duration is not None
            and tag_duration > duration * _DURATION_TOLERANCE + _DURATION_SLACK
        ):
            reason = f"DURATION {tag_duration:g} s is longer than the file ({duration:g} s)"
        if reason is not None:
            stale[index] = reason
    return StatsCheck(stale)
