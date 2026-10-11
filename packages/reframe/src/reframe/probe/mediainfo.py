"""MediaInfo, step 3 of the bitrate chain (C-3). Optional.

Used only when ``pymediainfo`` can be imported **and** its MediaInfo library loads
(``MediaInfo.can_parse()``). The ``pymediainfo`` 7 wheels bundle ``libmediainfo``, so with the
``[mediainfo]`` extra it usually works without a system MediaInfo.

Tracks are matched to ffprobe streams by MediaInfo's ``StreamOrder`` (the stream's position in
the file, the same number as ffprobe's ``index`` for Matroska and MP4) and the track type
(``Video`` ↔ video, ``Audio`` ↔ audio). A ``StreamOrder`` that is not a plain number (MPEG-TS
programs: ``0-1``) is not matched.

The library call blocks, so :func:`read_bitrates` is run in a worker thread by the caller.
"""

from __future__ import annotations

import functools
import importlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

__all__ = ["MediaInfoTrack", "mediainfo_available", "read_bitrates", "track_bitrates"]

_FIRST_INT = re.compile(r"\d+")

#: The stream kinds that have a bit rate in :class:`~reframe.models.MediaSource`.
_KINDS = {"Video": "video", "Audio": "audio"}

#: What :func:`read_bitrates` returns: ``(kind, ffprobe index) → bits per second``.
BitrateMap = dict[tuple[str, int], int]
MediaInfoTrack = Any
"""A ``pymediainfo.Track`` (attributes ``track_type``, ``streamorder``, ``bit_rate``)."""


@functools.cache
def _parser() -> Callable[[str], Any] | None:
    """``MediaInfo.parse`` if pymediainfo imports and its library loads, else ``None``."""
    try:
        module = importlib.import_module("pymediainfo")
        media_info = module.MediaInfo
        if not media_info.can_parse():
            return None
    except Exception:  # ImportError, OSError from the library loader, anything else
        return None
    parse: Callable[[str], Any] = media_info.parse
    return parse


def mediainfo_available() -> bool:
    """Whether MediaInfo can be used (checked once per process)."""
    return _parser() is not None


def _first_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return round(value) if value > 0 else None
    match = _FIRST_INT.search(str(value))
    if match is None:
        return None
    number = int(match.group(0))
    return number if number > 0 else None


def track_bitrates(tracks: Iterable[MediaInfoTrack]) -> BitrateMap:
    """``(kind, index) → bit rate`` from MediaInfo tracks (``BitRate``, else nominal)."""
    result: BitrateMap = {}
    for track in tracks:
        kind = _KINDS.get(str(getattr(track, "track_type", "")))
        order = str(getattr(track, "streamorder", "") or "")
        if kind is None or not order.isdigit():
            continue
        value = _first_int(getattr(track, "bit_rate", None)) or _first_int(
            getattr(track, "bit_rate_nominal", None)
        )
        if value is not None:
            result[(kind, int(order))] = value
    return result


def read_bitrates(path: Path) -> BitrateMap:
    """Parse ``path`` with MediaInfo (blocking). Empty when MediaInfo is not available.

    :raises Exception: whatever the library raises for an unreadable file; the caller turns
        it into a warning.
    """
    parse = _parser()
    if parse is None:
        return {}
    info = parse(str(path))
    return track_bitrates(getattr(info, "tracks", ()))
