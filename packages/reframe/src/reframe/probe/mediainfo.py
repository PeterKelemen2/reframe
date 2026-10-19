"""MediaInfo enrichment, optional: bit rates, BCP 47 languages and CFR / VFR modes that ffprobe
does not give. Without a loadable pymediainfo library nothing is added (``language_ietf`` stays
``None``).

Tracks match ffprobe streams by ``StreamOrder`` (the same number as ffprobe's ``index``) and by
track type.
"""

from __future__ import annotations

import functools
import importlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MediaInfoData",
    "MediaInfoTrack",
    "mediainfo_available",
    "mediainfo_version",
    "read_mediainfo",
    "track_data",
]

# [0-9], not \d: \d matches other scripts' digits too. MediaInfo writes ``0-1`` for MPEG-TS
# programs, which no pattern here matches.
_FIRST_INT = re.compile(r"[0-9]+")
_STREAM_ORDER = re.compile(r"[0-9]+")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")

#: MediaInfo track type → MediaSource stream kind.
_KINDS = {"Video": "video", "Audio": "audio", "Text": "subtitle"}

#: ``(kind, ffprobe index)``.
StreamKey = tuple[str, int]
MediaInfoTrack = Any
"""A ``pymediainfo.Track`` (attributes ``track_type``, ``streamorder``, ``bit_rate``, …)."""


@dataclass
class MediaInfoData:
    """What MediaInfo says about the streams, by ``(kind, ffprobe index)``."""

    bitrates: dict[StreamKey, int] = field(default_factory=dict)
    languages: dict[StreamKey, str] = field(default_factory=dict)
    """BCP 47 tags (``pt-BR``); only values that look like a language tag."""
    frame_rate_modes: dict[StreamKey, str] = field(default_factory=dict)
    """``CFR`` or ``VFR`` (video only)."""


@functools.cache
def _library() -> tuple[Callable[[str], Any], str] | None:
    """``(MediaInfo.parse, version)`` if pymediainfo imports and its library loads."""
    try:
        module = importlib.import_module("pymediainfo")
        media_info = module.MediaInfo
        if not media_info.can_parse():
            return None
    except Exception:  # ImportError, OSError from the library loader, anything else
        return None
    version = f"pymediainfo {getattr(module, '__version__', '?')}"
    try:  # the library version: a private helper, so only best effort
        library = media_info._get_library()
        version += f", libmediainfo {library[2]}"
    except Exception:
        pass
    parse: Callable[[str], Any] = media_info.parse
    return parse, version


def mediainfo_available() -> bool:
    """Whether MediaInfo can be used (checked once per process)."""
    return _library() is not None


def mediainfo_version() -> str | None:
    """The pymediainfo and libmediainfo versions, or ``None`` when MediaInfo is not available."""
    library = _library()
    return None if library is None else library[1]


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


def track_data(tracks: Iterable[MediaInfoTrack]) -> MediaInfoData:
    """Bit rates (``BitRate``, else nominal), BCP 47 languages and frame rate modes."""
    data = MediaInfoData()
    for track in tracks:
        kind = _KINDS.get(str(getattr(track, "track_type", "")))
        order = str(getattr(track, "streamorder", "") or "")
        if kind is None or _STREAM_ORDER.fullmatch(order) is None:
            continue
        key = (kind, int(order))
        if kind != "subtitle":
            value = _first_int(getattr(track, "bit_rate", None)) or _first_int(
                getattr(track, "bit_rate_nominal", None)
            )
            if value is not None:
                data.bitrates[key] = value
        language = getattr(track, "language", None)
        if isinstance(language, str) and _LANGUAGE_RE.match(language) and len(language) <= 64:
            data.languages[key] = language
        mode = getattr(track, "frame_rate_mode", None)
        if kind == "video" and mode in ("CFR", "VFR"):
            data.frame_rate_modes[key] = mode
    return data


def read_mediainfo(path: Path) -> MediaInfoData:
    """Parse ``path`` with MediaInfo. Empty when MediaInfo is not available.

    Blocking: run it in a worker thread, not on the event loop.

    :raises Exception: whatever the library raises for an unreadable file.
    """
    library = _library()
    if library is None:
        return MediaInfoData()
    info = library[0](str(path))
    return track_data(getattr(info, "tracks", ()))
