"""A small reader of Matroska track headers (C-13; decision 0034).

ffprobe does not show the ``LanguageIETF`` element (BCP 47: ``pt-BR``, ``zh-Hant``), and
MediaInfo, which does, is optional. This reader gets the track headers straight from the
file's ``Tracks`` element, and the segment title from ``Info``. Reframe uses it to

- set ``language_ietf`` of a Matroska source's streams to what the file holds (the element's
  value, or ``None`` when the track has none), so the probe shows ``pt-BR`` without MediaInfo
  (:mod:`reframe.probe.prober`);
- check, before an in-place metadata edit, that the file's tracks are the probe's streams in
  the same order (the mkvpropedit track selectors ``track:a2`` count them so).

Only the start of the file is read: the EBML header, then the top-level elements of the
``Segment`` one after the other (each skipped by its size) until ``Tracks`` and ``Info`` are
found. When they come after the first ``Cluster`` (as when mkvpropedit had to move a grown
``Tracks`` element to the end), the first ``SeekHead`` gives their position, or the one
``SeekHead`` that it links to. Elements with an unknown size other than the ``Segment`` and a
``Cluster`` end the scan.

**Every read is bounded**, so a damaged or hostile file costs little time and memory (the
core-complete review, R4-2 and R4-5): an element of more than :data:`MAX_ELEMENT` bytes is not
read (a ``SeekHead`` of more than :data:`MAX_SEEK_HEAD` is skipped); at most
:data:`MAX_TOP_LEVEL` top-level elements are looked at, at most :data:`MAX_CHILDREN` children
of one element (a ``SeekHead``'s further entries are not looked at; more children elsewhere
is a :class:`MatroskaError`), at most :data:`MAX_ELEMENTS` element headers in all, and at
most :data:`MAX_READ` bytes are read in all. Of a ``SeekHead`` only the entries of ``Tracks``,
``Info`` and ``SeekHead`` are kept, and only those whose position is inside the file (the
first such entry of each wins; FFmpeg also skips an entry it cannot use and looks at the
next). An element at a ``SeekHead`` position must be the element the entry names. Any
``ValueError`` or ``OverflowError`` of a damaged header is a :class:`MatroskaError`.

Element IDs (Matroska specification, RFC 9559): ``Tracks`` 0x1654AE6B, ``TrackEntry`` 0xAE,
``TrackNumber`` 0xD7, ``TrackType`` 0x83 (1 video, 2 audio, 0x11 subtitle), ``FlagDefault``
0x88 (default 1), ``FlagForced`` 0x55AA, ``FlagHearingImpaired`` 0x55AB,
``FlagVisualImpaired`` 0x55AC, ``FlagTextDescriptions`` 0x55AD, ``FlagOriginal`` 0x55AE,
``FlagCommentary`` 0x55AF, ``Name`` 0x536E, ``Language`` 0x22B59C (default ``eng``),
``LanguageBCP47`` 0x22B59D (``LanguageIETF`` in MKVToolNix), ``CodecID`` 0x86; ``Info``
0x1549A966 with ``Title`` 0x7BA9; ``SeekHead`` 0x114D9B74 with ``Seek`` 0x4DBB, ``SeekID``
0x53AB and ``SeekPosition`` 0x53AC (relative to the start of the segment's data).
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

__all__ = [
    "MAX_CHILDREN",
    "MAX_ELEMENT",
    "MAX_ELEMENTS",
    "MAX_READ",
    "MAX_SEEK_HEAD",
    "MAX_TOP_LEVEL",
    "MatroskaError",
    "MatroskaFile",
    "MatroskaTrack",
    "read_matroska",
    "tracks_by_kind",
]

#: The largest ``Tracks`` / ``Info`` element (and EBML header) that is read (bytes).
MAX_ELEMENT = 16 * 1024 * 1024
#: The largest ``SeekHead`` that is read (bytes); a larger one is skipped. A real one lists a
#: few elements (or, written by old muxers, the clusters: some KB).
MAX_SEEK_HEAD = 1024 * 1024
#: Top-level elements of the segment that are looked at before giving up.
MAX_TOP_LEVEL = 4096
#: Children of one element that are looked at (a ``SeekHead``'s further entries are ignored;
#: a ``Tracks``, ``TrackEntry``, ``Info`` or EBML header with more is damaged).
MAX_CHILDREN = 4096
#: Element headers that one read parses in all (a real file needs a few thousand).
MAX_ELEMENTS = 65536
#: Bytes that one read reads in all: a ``Tracks`` and an ``Info`` element of the largest size,
#: two ``SeekHead`` elements and the headers fit.
MAX_READ = 2 * MAX_ELEMENT + 4 * MAX_SEEK_HEAD

TrackKind = Literal["video", "audio", "subtitle", "other"]

_EBML = 0x1A45DFA3
_DOC_TYPE = 0x4282
_SEGMENT = 0x18538067
_SEEK_HEAD = 0x114D9B74
_SEEK = 0x4DBB
_SEEK_ID = 0x53AB
_SEEK_POSITION = 0x53AC
_INFO = 0x1549A966
_TITLE = 0x7BA9
_TRACKS = 0x1654AE6B
_CLUSTER = 0x1F43B675
_TRACK_ENTRY = 0xAE

#: The ``SeekHead`` targets that are kept.
_SEEK_TARGETS = frozenset({_TRACKS, _INFO, _SEEK_HEAD})

_KINDS: dict[int, TrackKind] = {1: "video", 2: "audio", 0x11: "subtitle"}
_UINTS = {
    0xD7: "number",
    0x83: "type",
    0xB9: "enabled",
    0x88: "default",
    0x55AA: "forced",
    0x55AB: "hearing_impaired",
    0x55AC: "visual_impaired",
    0x55AD: "text_descriptions",
    0x55AE: "original",
    0x55AF: "commentary",
}
_STRINGS = {0x536E: "name", 0x22B59C: "language", 0x22B59D: "language_ietf", 0x86: "codec_id"}


class MatroskaError(Exception):
    """The file is not Matroska, or its header cannot be read."""


@dataclass(slots=True)
class MatroskaTrack:
    """One ``TrackEntry`` (values as stored; the specification's defaults filled in)."""

    number: int | None = None
    kind: TrackKind = "other"
    codec_id: str | None = None
    name: str | None = None
    language: str = "eng"
    """The legacy ``Language`` element (ISO 639-2; ``eng`` when absent, as specified)."""
    language_ietf: str | None = None
    """``LanguageBCP47`` (``LanguageIETF``) as stored, not checked; ``None`` when the file has
    none."""
    enabled: bool = True
    default: bool = True
    forced: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    text_descriptions: bool = False
    original: bool = False
    commentary: bool = False


@dataclass(slots=True)
class MatroskaFile:
    doc_type: str
    """``matroska`` or ``webm``."""
    title: str | None = None
    tracks: list[MatroskaTrack] = field(default_factory=list)


def tracks_by_kind(info: MatroskaFile) -> dict[TrackKind, list[MatroskaTrack]]:
    """The tracks of each kind, in file order (the order of mkvpropedit's ``track:a1``…)."""
    result: dict[TrackKind, list[MatroskaTrack]] = {
        "video": [],
        "audio": [],
        "subtitle": [],
        "other": [],
    }
    for track in info.tracks:
        result[track.kind].append(track)
    return result


# --------------------------------------------------------------------------- EBML


class _Budget:
    """What one :func:`read_matroska` may still parse and read (the limits are read when it
    starts, so tests can lower them)."""

    __slots__ = ("bytes", "elements")

    def __init__(self) -> None:
        self.bytes = MAX_READ
        self.elements = MAX_ELEMENTS

    def element(self) -> None:
        self.elements -= 1
        if self.elements < 0:
            raise MatroskaError(f"the headers have more than {MAX_ELEMENTS} elements")

    def read(self, count: int) -> None:
        self.bytes -= count
        if self.bytes < 0:
            raise MatroskaError(f"the headers need more than {MAX_READ} bytes to be read")


def _vint(data: bytes, pos: int, *, keep_marker: bool) -> tuple[int, int, bool]:
    """``(value, length, all_ones)`` of the variable-size integer at ``pos``."""
    if pos >= len(data):
        raise MatroskaError("truncated element header")
    first = data[pos]
    if first == 0:
        raise MatroskaError("invalid variable-size integer")
    length = 1
    mask = 0x80
    while not first & mask:
        mask >>= 1
        length += 1
    if pos + length > len(data):
        raise MatroskaError("truncated element header")
    value = first if keep_marker else first & (mask - 1)
    ones = (first & (mask - 1)) == mask - 1
    for byte in data[pos + 1 : pos + length]:
        value = (value << 8) | byte
        ones = ones and byte == 0xFF
    return value, length, ones


def _header(data: bytes, pos: int) -> tuple[int, int | None, int]:
    """``(id, size or None for unknown, header length)``."""
    element_id, id_len, _ = _vint(data, pos, keep_marker=True)
    if id_len > 4:
        raise MatroskaError("invalid element ID")
    size, size_len, unknown = _vint(data, pos + id_len, keep_marker=False)
    return element_id, None if unknown else size, id_len + size_len


def _iter_children(data: bytes, budget: _Budget) -> Iterator[tuple[int, bytes]]:
    """The child elements of a master element's payload (an unknown size ends them)."""
    pos = 0
    while pos < len(data):
        budget.element()
        element_id, size, header = _header(data, pos)
        if size is None:
            return
        start = pos + header
        yield element_id, data[start : start + size]
        pos = start + size


def _children(data: bytes, budget: _Budget, what: str) -> list[tuple[int, bytes]]:
    """The child elements, at most :data:`MAX_CHILDREN` (more: :class:`MatroskaError`)."""
    out = list(itertools.islice(_iter_children(data, budget), MAX_CHILDREN + 1))
    if len(out) > MAX_CHILDREN:
        raise MatroskaError(f"{what} has more than {MAX_CHILDREN} elements")
    return out


def _uint(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


def _string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _track(data: bytes, budget: _Budget) -> MatroskaTrack:
    track = MatroskaTrack()
    for element_id, payload in _children(data, budget, "a TrackEntry"):
        if element_id in _UINTS:
            key = _UINTS[element_id]
            value = _uint(payload)
            if key == "number":
                track.number = value
            elif key == "type":
                track.kind = _KINDS.get(value, "other")
            else:
                setattr(track, key, bool(value))
        elif element_id in _STRINGS:
            setattr(track, _STRINGS[element_id], _string(payload))
    return track


def _tracks(payload: bytes, budget: _Budget) -> list[MatroskaTrack]:
    return [
        _track(data, budget)
        for element_id, data in _children(payload, budget, "Tracks")
        if element_id == _TRACK_ENTRY
    ]


def _title(payload: bytes, budget: _Budget) -> str | None:
    for element_id, data in _children(payload, budget, "Info"):
        if element_id == _TITLE:
            return _string(data) or None
    return None


def _seek_entries(payload: bytes, budget: _Budget, room: int) -> dict[int, int]:
    """``{element ID: position relative to the segment's data}`` of the ``Tracks``, ``Info``
    and ``SeekHead`` entries whose position is inside the file (``room``: the bytes after the
    segment's data start). The first usable entry of each ID wins; at most
    :data:`MAX_CHILDREN` children are looked at."""
    entries: dict[int, int] = {}
    for element_id, seek in itertools.islice(_iter_children(payload, budget), MAX_CHILDREN):
        if element_id != _SEEK:
            continue
        target: int | None = None
        position: int | None = None
        for child_id, data in itertools.islice(_iter_children(seek, budget), 8):
            if child_id == _SEEK_ID and len(data) <= 4:
                target = _uint(data)
            elif child_id == _SEEK_POSITION and len(data) <= 8:
                position = _uint(data)
        if (
            target in _SEEK_TARGETS
            and target not in entries
            and position is not None
            and position < room
        ):
            entries[target] = position
    return entries


# --------------------------------------------------------------------------- file


class _Reader:
    def __init__(self, handle: BinaryIO, size: int) -> None:
        self.handle = handle
        self.size = size
        self.budget = _Budget()

    def read(self, pos: int, count: int) -> bytes:
        if count <= 0:
            return b""
        if pos >= self.size:
            raise MatroskaError(f"truncated file: no element at byte {pos}")
        count = min(count, self.size - pos)
        self.budget.read(count)
        self.handle.seek(pos)
        return self.handle.read(count)

    def header(self, pos: int) -> tuple[int, int | None, int]:
        self.budget.element()
        return _header(self.read(pos, 12), 0)

    def payload(self, pos: int, limit: int | None = None) -> tuple[int, bytes]:
        limit = MAX_ELEMENT if limit is None else limit
        element_id, size, header = self.header(pos)
        if size is None or size > limit:
            raise MatroskaError(f"element 0x{element_id:X} is too large to read")
        return element_id, self.read(pos + header, size)


def _doc_type(reader: _Reader) -> tuple[str, int]:
    element_id, payload = reader.payload(0)
    if element_id != _EBML:
        raise MatroskaError("not an EBML file")
    doc_type = "matroska"
    for child_id, data in _children(payload, reader.budget, "the EBML header"):
        if child_id == _DOC_TYPE:
            doc_type = _string(data)
    if doc_type not in ("matroska", "webm"):
        raise MatroskaError(f"not a Matroska file (DocType {doc_type!r})")
    _, size, header = reader.header(0)
    assert size is not None
    return doc_type, header + size


def read_matroska(path: str | os.PathLike[str]) -> MatroskaFile:
    """The track headers and the title of the Matroska file ``path`` (blocking).

    :raises MatroskaError: not a Matroska file, or a damaged header (also one that would
        need more than the limits of the module doc).
    :raises OSError: the file cannot be read.
    """
    with open(Path(path), "rb") as handle:
        reader = _Reader(handle, os.fstat(handle.fileno()).st_size)
        try:
            return _read(reader)
        except (ValueError, OverflowError) as exc:
            raise MatroskaError(f"damaged header ({exc})") from exc


def _read(reader: _Reader) -> MatroskaFile:
    doc_type, pos = _doc_type(reader)
    segment_id, _, header = reader.header(pos)
    if segment_id != _SEGMENT:
        raise MatroskaError("no Segment after the EBML header")
    base = pos + header
    room = reader.size - base
    info = MatroskaFile(doc_type=doc_type)
    found_tracks = found_info = False
    seeks: dict[int, int] = {}
    first_seek_head: int | None = None
    pos = base
    for _ in range(MAX_TOP_LEVEL):
        if pos >= reader.size or (found_tracks and found_info):
            break
        element_id, element_size, header = reader.header(pos)
        if element_id == _CLUSTER or element_size is None:
            break
        if element_id == _TRACKS:
            info.tracks = _tracks(reader.payload(pos)[1], reader.budget)
            found_tracks = True
        elif element_id == _INFO:
            info.title = _title(reader.payload(pos)[1], reader.budget)
            found_info = True
        elif element_id == _SEEK_HEAD and first_seek_head is None:
            first_seek_head = pos - base
            if element_size <= MAX_SEEK_HEAD:
                seeks = _seek_entries(reader.payload(pos, MAX_SEEK_HEAD)[1], reader.budget, room)
        pos += header + element_size
    missing = [i for i, found in ((_TRACKS, found_tracks), (_INFO, found_info)) if not found]
    linked = seeks.get(_SEEK_HEAD)
    if any(i not in seeks for i in missing) and linked is not None and linked != first_seek_head:
        element_id, size, _ = reader.header(base + linked)
        if element_id == _SEEK_HEAD and size is not None and size <= MAX_SEEK_HEAD:
            payload = reader.payload(base + linked, MAX_SEEK_HEAD)[1]
            for target, position in _seek_entries(payload, reader.budget, room).items():
                seeks.setdefault(target, position)
    if not found_tracks and _TRACKS in seeks:
        element_id, payload = reader.payload(base + seeks[_TRACKS])
        if element_id == _TRACKS:
            info.tracks = _tracks(payload, reader.budget)
            found_tracks = True
    if not found_info and _INFO in seeks:
        element_id, payload = reader.payload(base + seeks[_INFO])
        if element_id == _INFO:
            info.title = _title(payload, reader.budget)
    if not found_tracks:
        raise MatroskaError("no Tracks element found")
    return info
