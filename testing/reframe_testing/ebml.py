"""EBML and Matroska byte builders for the reader and writer tests.

They do not use ``reframe.metadata.ebml``: the writer's tests must not check the writer's
encoder with itself.
"""

from __future__ import annotations

from pathlib import Path

from reframe.probe.matroska import _header

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


def with_bogus_seek_entry(path: Path) -> None:
    """Put a Seek entry ``Tracks -> 2^64 - 1`` in front of the SeekHead's entries; the Void
    after the SeekHead gives the room (FFmpeg reserves one), so no other position moves."""
    data = bytearray(path.read_bytes())
    _, ebml_size, ebml_header = _header(bytes(data), 0)
    assert ebml_size is not None
    seg = ebml_header + ebml_size
    seg_id, _, seg_header = _header(bytes(data), seg)
    assert seg_id == 0x18538067
    start = seg + seg_header
    head_id, head_size, head_header = _header(bytes(data), start)
    assert head_id == 0x114D9B74
    assert head_size is not None
    payload = bytes(data[start + head_header : start + head_header + head_size])
    void_at = start + head_header + head_size
    void_id, void_size, void_header = _header(bytes(data), void_at)
    assert void_id == 0xEC
    assert void_size is not None
    room = head_header + head_size + void_header + void_size
    bogus = element(
        0x4DBB, element(0x53AB, bytes.fromhex("1654AE6B")) + element(0x53AC, b"\xff" * 8)
    )
    new_head = element(0x114D9B74, bogus + payload)
    new_void = element(0xEC, b"\0" * (room - len(new_head) - 9))
    assert len(new_head) + len(new_void) == room
    data[start : start + room] = new_head + new_void
    path.write_bytes(bytes(data))
