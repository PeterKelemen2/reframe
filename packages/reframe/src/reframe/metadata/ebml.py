"""EBML encoding for the Matroska header writer, and a strict child parser that keeps offsets.

The parser is stricter than the reader of ``reframe.probe.matroska``: every child must have a
known size and end inside its parent, because the writer copies the bytes between children
as they are.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from reframe.probe import matroska
from reframe.probe.matroska import _CRC32 as CRC32
from reframe.probe.matroska import _VOID as VOID
from reframe.probe.matroska import MatroskaError, _Budget, _header

__all__ = [
    "CRC32",
    "VOID",
    "Child",
    "children",
    "encode_element",
    "encode_id",
    "encode_size",
    "encode_uint",
    "join_with_crc",
    "max_size",
    "split_crc",
    "void",
]


def encode_id(element_id: int) -> bytes:
    """The ID as stored (its length marker is part of the value)."""
    return element_id.to_bytes(max(1, (element_id.bit_length() + 7) // 8), "big")


def max_size(width: int) -> int:
    """The largest size a ``width``-byte size field holds (all ones means unknown)."""
    return (1 << (7 * width)) - 2


def encode_size(size: int, width: int | None = None) -> bytes:
    """``size`` as a variable-size integer of ``width`` bytes (the shortest when ``None``).

    :raises ValueError: ``size`` does not fit in ``width`` bytes.
    """
    if width is None:
        width = 1
        while size > max_size(width):
            width += 1
    if not 1 <= width <= 8 or not 0 <= size <= max_size(width):
        raise ValueError(f"size {size} does not fit in {width} bytes")
    return ((1 << (7 * width)) | size).to_bytes(width, "big")


def encode_uint(value: int, width: int | None = None) -> bytes:
    """An unsigned integer payload, big-endian (the shortest when ``width`` is ``None``)."""
    if width is None:
        width = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(width, "big")


def encode_element(element_id: int, payload: bytes, size_width: int | None = None) -> bytes:
    return encode_id(element_id) + encode_size(len(payload), size_width) + payload


def void(total: int) -> bytes:
    """The header of a ``Void`` element that is ``total`` bytes long with its payload.

    Only the header is returned: what follows it in the file becomes the payload.

    :raises ValueError: ``total`` is less than 2 (a ``Void`` needs an ID and a size).
    """
    if total < 2:
        raise ValueError("a Void element is at least 2 bytes long")
    width = 1
    while total - 1 - width > max_size(width):
        width += 1
    return bytes([VOID]) + encode_size(total - 1 - width, width)


@dataclass(frozen=True, slots=True)
class Child:
    """A child element: ``offset`` is relative to its parent's payload."""

    id: int
    offset: int
    header: int
    size: int

    @property
    def end(self) -> int:
        return self.offset + self.header + self.size

    def raw(self, payload: bytes) -> bytes:
        return payload[self.offset : self.end]

    def data(self, payload: bytes) -> bytes:
        return payload[self.offset + self.header : self.end]


def children(payload: bytes, budget: _Budget, what: str) -> list[Child]:
    """Every child of a master element's payload.

    :raises MatroskaError: a child of unknown size, one that ends past the payload, or more
        than ``MAX_CHILDREN`` children.
    """
    out: list[Child] = []
    pos = 0
    while pos < len(payload):
        if len(out) >= matroska.MAX_CHILDREN:
            raise MatroskaError(f"{what} has more than {matroska.MAX_CHILDREN} elements")
        budget.element()
        element_id, size, header = _header(payload, pos)
        if size is None or pos + header + size > len(payload):
            raise MatroskaError(f"{what} has a damaged element")
        child = Child(element_id, pos, header, size)
        out.append(child)
        pos = child.end
    return out


def split_crc(payload: bytes, kids: list[Child]) -> tuple[bool, list[Child]]:
    """``(has CRC-32, the other children)``.

    :raises MatroskaError: the stored CRC-32 does not match the other children's bytes.
    """
    if not kids or kids[0].id != CRC32:
        return False, kids
    first = kids[0]
    stored = first.data(payload)
    if first.size != 4 or int.from_bytes(stored, "little") != zlib.crc32(payload[first.end :]):
        raise MatroskaError("CRC-32 mismatch")
    return True, kids[1:]


def join_with_crc(parts: list[bytes], crc: bool) -> bytes:
    """The payload of a master element; with ``crc``, a ``CRC-32`` first child (little-endian
    over the other children's bytes)."""
    body = b"".join(parts)
    if not crc:
        return body
    return encode_element(CRC32, zlib.crc32(body).to_bytes(4, "little")) + body
