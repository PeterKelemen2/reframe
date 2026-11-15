"""The Matroska version (``DocTypeVersion``) that the elements of a ``Tracks`` element need.

The table holds the ``minver`` of every element under ``\\Segment\\Tracks`` in the Matroska
specification (``ebml_matroska.xml``) that is above 1; elements that are in no version of the
specification (``maxver="0"``) are left out.
"""

from __future__ import annotations

from reframe.metadata.ebml import children
from reframe.probe.matroska import MatroskaError, _Budget, _header

__all__ = ["needed_version"]

_MASTERS = frozenset(
    {
        0xAE,  # TrackEntry
        0xE0,  # Video
        0xE1,  # Audio
        0x55B0,  # Colour
        0x55D0,  # MasteringMetadata
        0x7670,  # Projection
        0x41E4,  # BlockAdditionMapping
        0xE2,  # TrackOperation
        0xE3,  # TrackCombinePlanes
        0xE4,  # TrackPlane
        0xE9,  # TrackJoinBlocks
        0x6624,  # TrackTranslate
        0x6D80,  # ContentEncodings
        0x6240,  # ContentEncoding
        0x5034,  # ContentCompression
        0x5035,  # ContentEncryption
        0x47E7,  # ContentEncAESSettings
    }
)

_VERSIONS: dict[int, int] = {
    0xB9: 2,  # FlagEnabled
    0x9A: 2,  # FlagInterlaced
    0x53B8: 3,  # StereoMode
    0x53C0: 3,  # AlphaMode
    **dict.fromkeys((0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE9, 0xED), 3),  # TrackOperation
    **dict.fromkeys((0x55AB, 0x55AC, 0x55AD, 0x55AE, 0x55AF), 4),  # the v4 flags
    0x22B59D: 4,  # LanguageBCP47
    0x234E7A: 4,  # DefaultDecodedFieldDuration
    **dict.fromkeys((0x41E4, 0x41F0, 0x41A4, 0x41E7, 0x41ED), 4),  # BlockAdditionMapping
    0x56AA: 4,  # CodecDelay
    0x56BB: 4,  # SeekPreRoll
    0x9D: 4,  # FieldOrder
    **dict.fromkeys(range(0x55B0, 0x55BE), 4),  # Colour
    **dict.fromkeys(range(0x55D0, 0x55DB), 4),  # MasteringMetadata
    **dict.fromkeys(range(0x7670, 0x7676), 4),  # Projection
    0x47E7: 4,  # ContentEncAESSettings
    0x47E8: 4,  # AESSettingsCipherMode
    0x52F1: 5,  # Emphasis
}


def needed_version(tracks: bytes) -> int:
    """The highest version that an element in ``tracks`` (a whole ``Tracks`` element) needs.

    A child that the strict parser cannot read is skipped, not refused: the version is only a
    hint to readers.
    """
    _, _, header = _header(tracks, 0)
    return _walk(tracks[header:], _Budget(), 1)


def _walk(payload: bytes, budget: _Budget, need: int) -> int:
    try:
        kids = children(payload, budget, "a track element")
    except MatroskaError:
        return need
    for kid in kids:
        need = max(need, _VERSIONS.get(kid.id, 1))
        if kid.id in _MASTERS:
            need = _walk(kid.data(payload), budget, need)
    return need
