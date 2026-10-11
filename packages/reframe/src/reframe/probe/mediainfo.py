"""MediaInfo enrichment (C-3). Optional.

What it adds to a probe:

- **bit rates** that ffprobe and the statistics tags do not give (step 3 of the bitrate chain);
- **``language_ietf``**: the BCP 47 language tag (Matroska ``LanguageIETF``), which ffprobe
  does not show (after ``mkvpropedit --set language=pt-BR`` ffprobe says ``por``, MediaInfo
  ``pt-BR``);
- **``FrameRate_Mode``** (``CFR`` / ``VFR``) for the Matroska streams whose VFR state
  ffprobe's output cannot tell (:func:`reframe.probe.parse.vfr_undecided`).

Probing uses the **pymediainfo library** (decision XXXX): ``pymediainfo`` must import and its
MediaInfo library must load (``MediaInfo.can_parse()``). The ``pymediainfo`` 7 wheels bundle
``libmediainfo``, so with the ``[mediainfo]`` extra it works without a system MediaInfo. The
``mediainfo`` entry of tool discovery (the CLI, ``REFRAME_MEDIAINFO``, Settings → Tools) is for
diagnostics only; it does not change probing. Without the library, ``language_ietf`` stays
``None`` and the other two steps are skipped.

Tracks are matched to ffprobe streams by MediaInfo's ``StreamOrder`` (the stream's position in
the file, the same number as ffprobe's ``index`` for Matroska and MP4) and the track type
(``Video`` ↔ video, ``Audio`` ↔ audio, ``Text`` ↔ subtitle). A ``StreamOrder`` that is not a
plain number (MPEG-TS programs: ``0-1``) is not matched.

The library call blocks, so :func:`read_mediainfo` is run in a worker thread by the caller.
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

_FIRST_INT = re.compile(r"\d+")
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
    """``pymediainfo 7.0.1, libmediainfo 25.04`` (part of the probe cache identity)."""
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
        if kind is None or not order.isdigit():
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
    """Parse ``path`` with MediaInfo (blocking). Empty when MediaInfo is not available.

    :raises Exception: whatever the library raises for an unreadable file; the caller turns
        it into a warning.
    """
    library = _library()
    if library is None:
        return MediaInfoData()
    info = library[0](str(path))
    return track_data(getattr(info, "tracks", ()))
