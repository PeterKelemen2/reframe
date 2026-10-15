"""Write a PGS (Blu-ray Presentation Graphic Stream, ``.sup``) subtitle file with plain Python.

FFmpeg has no PGS encoder, and it cannot turn text subtitles into bitmaps. So the PGS fixture
is written here, the way :mod:`reframe_testing.vobsub` writes VobSub, and FFmpeg only muxes it
into Matroska (``-i track.sup -c:s copy``; the Matroska muxer merges the segments of a display
set into one block with its ``pgs_frame_merge`` filter).

A ``.sup`` file is a series of segments, each with a 13-byte header: ``PG``, the PTS and DTS
(90 kHz), the segment type and the payload size. Every subtitle event is two **display sets**:

- *show*: a presentation composition (PCS, ``0x16``, "epoch start") with one composition
  object, a window definition (WDS, ``0x17``), a palette (PDS, ``0x14``), the object (ODS,
  ``0x15``: a run-length encoded bitmap) and the end segment (``0x80``);
- *clear*: a PCS with no composition object, the window and the end segment.

A **forced** event has the forced flag (``0x40``) on its composition object. That is the bit
that FFmpeg's ``pgssubdec`` checks for ``forced_subs_only`` and that Blu-ray players use for
"forced subtitles only" (the forced dialogue in a full track: HandBrake's foreign audio
search).

The bitmaps are the same white bars with a black outline as the VobSub fixture
(:func:`reframe_testing.vobsub.bar_image`), each event a different width.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from reframe_testing.vobsub import bar_image

PCS = 0x16
WDS = 0x17
PDS = 0x14
ODS = 0x15
END = 0x80
#: Composition object flag: forced (``composition_flag & 0x40`` in FFmpeg).
FORCED = 0x40
EPOCH_START = 0x80
#: ``frame_rate`` byte of the PCS that Blu-ray authoring tools write.
_FRAME_RATE = 0x10
#: Palette: 0 transparent, 1 white, 2 black (Y, Cr, Cb, alpha; BT.601 limited range).
PALETTE = ((0, 16, 128, 128, 0), (1, 235, 128, 128, 255), (2, 16, 128, 128, 255))


@dataclass(frozen=True)
class Event:
    start_ms: int
    end_ms: int
    width: int
    """Width of the bar in pixels (each event gets a different width, so they differ)."""
    forced: bool = False


def rle_line(pixels: Sequence[int]) -> bytes:
    """One line of 8-bit palette indexes in PGS run-length coding, with the end-of-line code."""
    out = bytearray()
    i = 0
    n = len(pixels)
    while i < n:
        color = pixels[i]
        run = 1
        while i + run < n and pixels[i + run] == color and run < 0x3FFF:
            run += 1
        if color and run <= 2:
            out += bytes([color]) * run
        elif color == 0:
            out += bytes([0, run]) if run < 64 else bytes([0, 0x40 | (run >> 8), run & 0xFF])
        elif run < 64:
            out += bytes([0, 0x80 | run, color])
        else:
            out += bytes([0, 0xC0 | (run >> 8), run & 0xFF, color])
        i += run
    return bytes(out) + b"\x00\x00"


def rle(image: Sequence[Sequence[int]]) -> bytes:
    return b"".join(rle_line(row) for row in image)


def segment(kind: int, payload: bytes, pts_ms: int) -> bytes:
    """One segment: ``PG``, PTS, DTS (0, as authoring tools write), type, size, payload."""
    if len(payload) > 0xFFFF:
        raise ValueError(f"segment payload too large: {len(payload)} bytes")
    pts = pts_ms * 90
    return (
        b"PG"
        + pts.to_bytes(4, "big")
        + bytes(4)
        + bytes([kind])
        + len(payload).to_bytes(2, "big")
        + payload
    )


def _pcs(canvas: tuple[int, int], number: int, objects: Sequence[tuple[int, int, int]]) -> bytes:
    """Presentation composition; ``objects``: ``(flags, x, y)`` of object 0 in window 0."""
    w, h = canvas
    data = w.to_bytes(2, "big") + h.to_bytes(2, "big") + bytes([_FRAME_RATE])
    data += number.to_bytes(2, "big")
    data += bytes([EPOCH_START if objects else 0x00, 0x00, 0x00, len(objects)])
    for flags, x, y in objects:
        data += (0).to_bytes(2, "big") + bytes([0, flags]) + x.to_bytes(2, "big")
        data += y.to_bytes(2, "big")
    return data


def _wds(x: int, y: int, w: int, h: int) -> bytes:
    return bytes([1, 0]) + b"".join(v.to_bytes(2, "big") for v in (x, y, w, h))


def _pds() -> bytes:
    return bytes([0, 0]) + b"".join(bytes(entry) for entry in PALETTE)


def _ods(image: Sequence[Sequence[int]]) -> bytes:
    bitmap = rle(image)
    w, h = len(image[0]), len(image)
    return (
        (0).to_bytes(2, "big")
        + bytes([0, 0xC0])  # version 0, first and last fragment
        + (len(bitmap) + 4).to_bytes(3, "big")
        + w.to_bytes(2, "big")
        + h.to_bytes(2, "big")
        + bitmap
    )


def sup(
    events: Sequence[Event], *, canvas: tuple[int, int] = (720, 480), bar_height: int = 30
) -> bytes:
    """A ``.sup`` file with one show and one clear display set per event."""
    cw, ch = canvas
    out = bytearray()
    number = 0
    for ev in events:
        if ev.width > cw - 20:
            raise ValueError("event bar wider than the canvas")
        image = bar_image(ev.width, bar_height)
        x, y = (cw - ev.width) // 2, ch - bar_height - 40
        flags = FORCED if ev.forced else 0
        window = _wds(x, y, ev.width, bar_height)
        out += segment(PCS, _pcs(canvas, number, [(flags, x, y)]), ev.start_ms)
        out += segment(WDS, window, ev.start_ms)
        out += segment(PDS, _pds(), ev.start_ms)
        out += segment(ODS, _ods(image), ev.start_ms)
        out += segment(END, b"", ev.start_ms)
        out += segment(PCS, _pcs(canvas, number + 1, []), ev.end_ms)
        out += segment(WDS, window, ev.end_ms)
        out += segment(END, b"", ev.end_ms)
        number += 2
    return bytes(out)
