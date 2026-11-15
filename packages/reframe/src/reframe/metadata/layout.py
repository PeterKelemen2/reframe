"""Where the Matroska header elements of a file are, for the header writer.

Reads through the bounded reader of ``reframe.probe.matroska`` (its ``MAX_*`` limits). A file
whose layout the writer cannot trust raises :class:`Refusal`; damage found by the EBML parser
raises :class:`MatroskaError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reframe.metadata.ebml import Child, children, split_crc
from reframe.probe import matroska
from reframe.probe.matroska import (
    _CLUSTER,
    _INFO,
    _SEEK,
    _SEEK_HEAD,
    _SEEK_ID,
    _SEEK_POSITION,
    _SEGMENT,
    _TRACKS,
    MatroskaError,
    _doc_type,
    _Reader,
    _uint,
)

__all__ = ["Element", "Layout", "Refusal", "SeekHead", "read_layout"]

_VOID = 0xEC
_EBML_MAX_SIZE_LENGTH = 0x42F3


class Refusal(Exception):
    """The writer must not edit this file: ``code`` is ``header.<reason>``, ``reason`` one
    sentence for the user."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Element:
    """A top-level element of the segment; ``pos`` is its offset in the file."""

    id: int
    pos: int
    header: int
    size: int

    @property
    def end(self) -> int:
        return self.pos + self.header + self.size


@dataclass(slots=True)
class SeekHead:
    element: Element
    payload: bytes
    crc: bool
    seeks: list[Child]
    """The children after the ``CRC-32`` (``Seek`` entries, and anything else, kept as is)."""
    targets: list[tuple[int | None, int | None]]
    """``(SeekID, SeekPosition)`` of each child in :attr:`seeks` (``None`` when missing)."""


@dataclass(slots=True)
class Layout:
    size: int
    """The file size."""
    max_size_width: int
    """``EBMLMaxSizeLength``: the widest size field allowed."""
    segment_pos: int
    size_pos: int
    size_width: int
    base: int
    """Where the segment's payload starts (``SeekPosition`` is relative to it)."""
    segment_size: int | None
    """``None``: unknown."""
    front: list[Element]
    """The top-level elements before the first ``Cluster``, in file order."""
    tracks: Element
    info: Element | None
    seek_head: SeekHead | None
    """The first ``SeekHead`` before the clusters: the one readers start from."""
    other_seek_heads: list[SeekHead] = field(default_factory=list)

    @property
    def limit(self) -> int:
        """Where the segment's payload ends in this file."""
        if self.segment_size is None:
            return self.size
        return min(self.size, self.base + self.segment_size)

    def in_front(self, element: Element) -> bool:
        return element in self.front

    def slot_end(self, element: Element, reader: _Reader) -> int:
        """The end of ``element`` and the ``Void`` elements right after it."""
        if element in self.front:
            index = self.front.index(element) + 1
            end = element.end
            while index < len(self.front) and self.front[index].id == _VOID:
                end = self.front[index].end
                index += 1
            return end
        end = element.end
        for _ in range(matroska.MAX_TOP_LEVEL):
            if end >= self.limit:
                break
            element_id, size, header = reader.header(end)
            if element_id != _VOID or size is None or end + header + size > self.limit:
                break
            end += header + size
        return end


def _max_size_width(reader: _Reader) -> int:
    _, payload = reader.payload(0)
    for child in children(payload, reader.budget, "the EBML header"):
        if child.id == _EBML_MAX_SIZE_LENGTH:
            return max(1, min(8, _uint(child.data(payload))))
    return 8


def _seek_head(reader: _Reader, element: Element) -> SeekHead:
    if element.size > matroska.MAX_SEEK_HEAD:
        raise Refusal("header.too_large", "The file's SeekHead is too large to edit safely.")
    payload = reader.read(element.pos + element.header, element.size)
    crc, seeks = split_crc(payload, children(payload, reader.budget, "a SeekHead"))
    targets: list[tuple[int | None, int | None]] = []
    for seek in seeks:
        target: int | None = None
        position: int | None = None
        if seek.id == _SEEK:
            data = seek.data(payload)
            for child in children(data, reader.budget, "a Seek entry"):
                value = child.data(data)
                if child.id == _SEEK_ID and len(value) <= 4:
                    target = _uint(value)
                elif child.id == _SEEK_POSITION and len(value) <= 8:
                    position = _uint(value)
        targets.append((target, position))
    return SeekHead(element, payload, crc, seeks, targets)


def _element_at(reader: _Reader, pos: int, limit: int, element_id: int) -> Element | None:
    if pos >= limit:
        return None
    found, size, header = reader.header(pos)
    if found != element_id or size is None or pos + header + size > limit:
        return None
    return Element(found, pos, header, size)


def read_layout(reader: _Reader) -> Layout:
    """The layout of the file behind ``reader``.

    :raises Refusal: a layout the writer must not edit.
    :raises MatroskaError: not Matroska, damaged, or beyond the reader's limits.
    """
    _, pos = _doc_type(reader)
    max_width = _max_size_width(reader)
    segment_id, segment_size, header = reader.header(pos)
    if segment_id != _SEGMENT:
        raise MatroskaError("no Segment after the EBML header")
    layout_base = pos + header
    id_len = 4
    size_width = header - id_len
    limit = reader.size if segment_size is None else min(reader.size, layout_base + segment_size)

    front: list[Element] = []
    cursor = layout_base
    for _ in range(matroska.MAX_TOP_LEVEL):
        if cursor >= limit:
            break
        element_id, size, element_header = reader.header(cursor)
        if element_id == _CLUSTER:
            break
        if size is None or cursor + element_header + size > limit:
            raise MatroskaError(f"damaged element 0x{element_id:X} before the clusters")
        front.append(Element(element_id, cursor, element_header, size))
        cursor += element_header + size
    else:
        raise MatroskaError(f"more than {matroska.MAX_TOP_LEVEL} elements before the clusters")

    def only(element_id: int, what: str) -> Element | None:
        found = [e for e in front if e.id == element_id]
        if len(found) > 1:
            raise Refusal("header.duplicate", f"The file has more than one {what} element.")
        return found[0] if found else None

    front_tracks = only(_TRACKS, "Tracks")
    front_info = only(_INFO, "segment information")

    heads = [_seek_head(reader, e) for e in front if e.id == _SEEK_HEAD]
    first = heads[0] if heads else None
    seen = {head.element.pos for head in heads}
    if first is not None:
        for target, position in first.targets:
            if target != _SEEK_HEAD or position is None:
                continue
            linked = _element_at(reader, layout_base + position, limit, _SEEK_HEAD)
            if linked is None:
                raise Refusal(
                    "header.seek_head", "A SeekHead entry of the file points to no SeekHead."
                )
            if linked.pos not in seen:
                seen.add(linked.pos)
                heads.append(_seek_head(reader, linked))

    def locate(element_id: int, in_front: Element | None, what: str) -> Element | None:
        positions = {
            layout_base + position
            for head in heads
            for target, position in head.targets
            if target == element_id and position is not None
        }
        malformed = any(
            target == element_id and position is None
            for head in heads
            for target, position in head.targets
        )
        if malformed or len(positions) > 1:
            raise Refusal("header.seek_head", f"The file's SeekHead entries for {what} disagree.")
        if in_front is not None:
            if positions and positions != {in_front.pos}:
                raise Refusal(
                    "header.seek_head",
                    f"A SeekHead entry for {what} points away from the {what} element.",
                )
            return in_front
        if not positions:
            return None
        found = _element_at(reader, positions.pop(), limit, element_id)
        if found is None or (front and found.pos < front[-1].end):
            raise Refusal(
                "header.seek_head", f"The SeekHead entry for {what} points to no {what} element."
            )
        return found

    tracks = locate(_TRACKS, front_tracks, "Tracks")
    if tracks is None:
        raise MatroskaError("no Tracks element found")
    info = locate(_INFO, front_info, "segment information")
    return Layout(
        size=reader.size,
        max_size_width=max_width,
        segment_pos=pos,
        size_pos=pos + id_len,
        size_width=size_width,
        base=layout_base,
        segment_size=segment_size,
        front=front,
        tracks=tracks,
        info=info,
        seek_head=first,
        other_seek_heads=heads[1:],
    )
