"""The exact bytes of every Matroska track, from a scan of every block header: the oracle for
the probe's sampled bit rates.

It reads the whole file element by element (no size limits), so it is for tests only. Lacing
headers count as payload, as in the probe's sample and in mkvmerge's ``NUMBER_OF_BYTES``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

__all__ = ["BlockScanError", "scan_blocks"]

_SEGMENT = 0x18538067
_CLUSTER = 0x1F43B675
_SIMPLE_BLOCK = 0xA3
_BLOCK_GROUP = 0xA0
_BLOCK = 0xA1
#: The top-level elements of a segment: one of them ends a cluster of unknown size.
_TOP_LEVEL = frozenset(
    {0x114D9B74, 0x1549A966, 0x1654AE6B, _CLUSTER, 0x1C53BB6B, 0x1043A770, 0x1941A469, 0x1254C367}
)


class BlockScanError(Exception):
    """The file is not Matroska as the scan expects it."""


def _vint(handle: BinaryIO, pos: int, *, keep_marker: bool) -> tuple[int, int, bool]:
    handle.seek(pos)
    first = handle.read(1)
    if not first:
        raise BlockScanError(f"end of file at {pos}")
    length, mask = 1, 0x80
    while length <= 8 and not first[0] & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise BlockScanError(f"invalid variable-size integer at {pos}")
    raw = first + handle.read(length - 1)
    if len(raw) != length:
        raise BlockScanError(f"end of file at {pos}")
    value = int.from_bytes(raw, "big")
    if keep_marker:
        return value, length, False
    value &= (1 << (7 * length)) - 1
    return value, length, value == (1 << (7 * length)) - 1


def _element(handle: BinaryIO, pos: int) -> tuple[int, int, int | None]:
    """``(id, data position, size or None for unknown)``."""
    element_id, id_length, _ = _vint(handle, pos, keep_marker=True)
    size, size_length, unknown = _vint(handle, pos + id_length, keep_marker=False)
    return element_id, pos + id_length + size_length, None if unknown else size


def _block_bytes(handle: BinaryIO, data: int, size: int) -> tuple[int, int]:
    track, length, _ = _vint(handle, data, keep_marker=False)
    return track, size - length - 3


def scan_blocks(path: str | os.PathLike[str]) -> dict[int, int]:
    """Block payload bytes by track number. :raises BlockScanError: not such a file."""
    with open(Path(path), "rb") as handle:
        end_of_file = os.fstat(handle.fileno()).st_size
        _, data, size = _element(handle, 0)
        if size is None:
            raise BlockScanError("EBML header of unknown size")
        element_id, segment, segment_size = _element(handle, data + size)
        if element_id != _SEGMENT:
            raise BlockScanError("no Segment")
        end = end_of_file if segment_size is None else min(end_of_file, segment + segment_size)
        out: dict[int, int] = {}
        pos = segment
        while pos < end:
            element_id, data, size = _element(handle, pos)
            if element_id != _CLUSTER:
                if size is None:
                    raise BlockScanError(f"top-level element of unknown size at {pos}")
                pos = data + size
                continue
            cluster_end = end if size is None else data + size
            child = data
            while child < cluster_end:
                child_id, child_data, child_size = _element(handle, child)
                if size is None and child_id in _TOP_LEVEL:
                    break
                if child_size is None:
                    raise BlockScanError(f"cluster child of unknown size at {child}")
                if child_id == _SIMPLE_BLOCK:
                    track, count = _block_bytes(handle, child_data, child_size)
                    out[track] = out.get(track, 0) + count
                elif child_id == _BLOCK_GROUP:
                    inner = child_data
                    while inner < child_data + child_size:
                        inner_id, inner_data, inner_size = _element(handle, inner)
                        if inner_size is None:
                            raise BlockScanError(f"block group child of unknown size at {inner}")
                        if inner_id == _BLOCK:
                            track, count = _block_bytes(handle, inner_data, inner_size)
                            out[track] = out.get(track, 0) + count
                        inner = inner_data + inner_size
                child = child_data + child_size
            pos = child
        return out
