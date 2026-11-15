"""The bitrate of a probed stream: the first source that gives a value wins.

The order is ffprobe's stream ``bit_rate``, then the Matroska statistics tags, then for Matroska
an estimate from a sample of the clusters (:mod:`reframe.probe.sampling`, applied by
:func:`reframe.probe.probe_file`, since it reads the file). When none gives one, the bitrate is
unknown.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
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
    """The bit rate of one ffprobe stream: ``bit_rate``, else its statistics tags when
    ``trust_stats``; unknown otherwise."""
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


def _index(stream: Mapping[str, Any]) -> int:
    return positive_int(stream.get("index")) or 0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if abs(number) < float("inf") else None  # also False for NaN


def check_stats_tags(data: Mapping[str, Any], *, compressed: Collection[int] = ()) -> StatsCheck:
    """Check every stream's statistics tags against the container.

    A re-encode can leave stale tags, since FFmpeg copies stream tags, so a re-encoded file
    can carry its source's statistics. The ``ENCODER`` tag cannot tell who wrote the file
    (mkvmerge copies a source's), so it is no test.

    The streams in ``compressed`` (stream indexes) store fewer bytes than their
    ``NUMBER_OF_BYTES``: they are left out of the size check, and only the other checks apply
    to their own tags.
    """
    raw = data.get("streams")
    streams = [s for s in raw if isinstance(s, Mapping)] if isinstance(raw, list) else []
    fmt = _mapping(data.get("format"))
    size = positive_int(fmt.get("size"))
    total_rate = positive_int(fmt.get("bit_rate"))
    duration = _finite(fmt.get("duration"))

    with_stats = [s for s in streams if _has_stats(_mapping(s.get("tags")))]
    byte_sum = sum(
        positive_int(tag_value(_mapping(s.get("tags")), "NUMBER_OF_BYTES")) or 0
        for s in with_stats
        if _index(s) not in compressed
    )
    stale: dict[int, str] = {}
    for stream in with_stats:
        index = _index(stream)
        tags = _mapping(stream.get("tags"))
        bps = positive_int(tag_value(tags, "BPS"))
        tag_duration = parse_duration_tag(tag_value(tags, "DURATION"))
        reason: str | None = None
        if size is not None and byte_sum > size and index not in compressed:
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
