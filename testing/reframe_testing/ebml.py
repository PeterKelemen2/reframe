"""EBML and Matroska byte builders for the reader and writer tests.

They do not use ``reframe.metadata.ebml``: the writer's tests must not check the writer's
encoder with itself.
"""

from __future__ import annotations

_UNKNOWN_SIZE = bytes([0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])


def encode_size(size: int, width: int | None = None) -> bytes:
    """An EBML size field of ``width`` bytes, or of the fewest bytes when ``width`` is None."""
    width = width or next(w for w in range(1, 9) if size < (1 << (7 * w)) - 1)
    return ((1 << (7 * width)) | size).to_bytes(width, "big")


def element(
    element_id: int, payload: bytes, *, width: int | None = 8, unknown: bool = False
) -> bytes:
    """An element with a size field of ``width`` bytes (8 by default, so a test can count
    offsets), or the 8-byte unknown size."""
    raw_id = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    size = _UNKNOWN_SIZE if unknown else encode_size(len(payload), width)
    return raw_id + size + payload


def uint(element_id: int, value: int) -> bytes:
    return element(element_id, value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big"))


def text(element_id: int, value: str) -> bytes:
    return element(element_id, value.encode())


def header(doc_type: str = "matroska") -> bytes:
    return element(0x1A45DFA3, text(0x4282, doc_type))


def track(number: int, kind: int, **values: object) -> bytes:
    """A TrackEntry; ``values`` sets ``name``, ``language``, ``ietf``, ``default`` and
    ``commentary``."""
    body = uint(0xD7, number) + uint(0x83, kind)
    if "name" in values:
        body += text(0x536E, str(values["name"]))
    if "language" in values:
        body += text(0x22B59C, str(values["language"]))
    if "ietf" in values:
        body += text(0x22B59D, str(values["ietf"]))
    if "default" in values:
        body += uint(0x88, int(bool(values["default"])))
    if "commentary" in values:
        body += uint(0x55AF, int(bool(values["commentary"])))
    body += element(0xEC, b"\0\0")  # a Void inside the entry is skipped
    return element(0xAE, body)


def tracks(*entries: bytes) -> bytes:
    return element(0x1654AE6B, b"".join(entries))


def info(title: str) -> bytes:
    return element(0x1549A966, text(0x7BA9, title))


def cluster() -> bytes:
    """A Cluster of 16 zero bytes, as filler between the top-level elements."""
    return element(0x1F43B675, b"\0" * 16)


def simple_block(track_number: int, size: int) -> bytes:
    return element(0xA3, bytes([0x80 | track_number, 0, 0, 0x80]) + b"\xab" * size)
