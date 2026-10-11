"""Write a minimal VobSub (``.idx`` + ``.sub``) file pair with plain Python.

FFmpeg cannot convert text subtitles to bitmap subtitles ("Subtitle encoding currently only
possible from text to text or bitmap to bitmap"). So the bitmap-subtitle fixture is made in two
steps: this module writes DVD subpicture units (SPU) into an MPEG program stream, and FFmpeg
decodes them and encodes them again with its ``dvdsub`` encoder into Matroska.

The images are simple: a white bar with a black outline and gaps, which looks like a line of
text. Enough for probing, burn-in and track-selection tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: The 16-colour palette in the ``.idx`` header (index 0 black, 1 white, 2 grey, ...).
PALETTE = (
    "000000, f0f0f0, cccccc, 999999, 3333fa, 1111bb, fa3333, bb1111, "
    "33fa33, 11bb11, fafa33, bbbb11, fa33fa, bb11bb, 33fafa, 11bbbb"
)
PACK_SIZE = 2048
_PACK_HEADER = bytes.fromhex("000001ba4400040004010189c3f8")  # MPEG-2 pack header, SCR 0


@dataclass(frozen=True)
class Event:
    start_ms: int
    end_ms: int
    width: int
    """Width of the bar in pixels (each event gets a different width, so they differ)."""


def _rle_line(pixels: Sequence[int]) -> bytes:
    """Run-length encode one line of 2-bit pixels (DVD SPU nibble format), byte aligned."""
    nibbles: list[int] = []
    i = 0
    while i < len(pixels):
        color = pixels[i]
        run = 1
        while i + run < len(pixels) and pixels[i + run] == color and run < 255:
            run += 1
        value = (run << 2) | color
        if run < 4:
            nibbles.append(value)
        elif run < 16:
            nibbles += [value >> 4, value & 0xF]
        elif run < 64:
            nibbles += [value >> 8, (value >> 4) & 0xF, value & 0xF]
        else:
            nibbles += [value >> 12, (value >> 8) & 0xF, (value >> 4) & 0xF, value & 0xF]
        i += run
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes((nibbles[k] << 4) | nibbles[k + 1] for k in range(0, len(nibbles), 2))


def bar_image(width: int, height: int) -> list[list[int]]:
    """A "line of text": white (1) blocks with a black (2) outline on a transparent (0) field."""
    rows: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            edge = y in (0, height - 1) or x in (0, width - 1)
            gap = (x // 12) % 4 == 3 and 0 < y < height - 1  # a gap between "words"
            row.append(0 if gap else 2 if edge else 1)
        rows.append(row)
    return rows


def spu_packet(image: Sequence[Sequence[int]], x: int, y: int, duration_ms: int) -> bytes:
    """One subpicture unit: RLE fields plus two control sequences (show, then hide)."""
    height = len(image)
    width = len(image[0])
    top = b"".join(_rle_line(image[r]) for r in range(0, height, 2))
    bottom = b"".join(_rle_line(image[r]) for r in range(1, height, 2))
    top_offset = 4
    bottom_offset = top_offset + len(top)
    ctrl1 = bottom_offset + len(bottom)
    # control sequence 1: palette, alpha, area, field offsets, start display
    ctrl1_len = 4 + 3 + 3 + 7 + 5 + 1 + 1
    ctrl2 = ctrl1 + ctrl1_len
    x2, y2 = x + width - 1, y + height - 1
    seq1 = (
        (0).to_bytes(2, "big")
        + ctrl2.to_bytes(2, "big")
        + bytes([0x03, 0x20, 0x10])  # colours for pixels 3,2 | 1,0 -> palette 2,0 | 1,0
        + bytes([0x04, 0xFF, 0xF0])  # alpha: pixels 3,2,1 opaque, 0 transparent
        + bytes([0x05, x >> 4, ((x & 0xF) << 4) | (x2 >> 8), x2 & 0xFF])
        + bytes([y >> 4, ((y & 0xF) << 4) | (y2 >> 8), y2 & 0xFF])
        + bytes([0x06])
        + top_offset.to_bytes(2, "big")
        + bottom_offset.to_bytes(2, "big")
        + bytes([0x01, 0xFF])
    )
    assert len(seq1) == ctrl1_len
    delay = duration_ms * 90 // 1024  # SPU delay unit: 1024 / 90000 s
    seq2 = delay.to_bytes(2, "big") + ctrl2.to_bytes(2, "big") + bytes([0x02, 0xFF])
    size = ctrl2 + len(seq2)
    return size.to_bytes(2, "big") + ctrl1.to_bytes(2, "big") + top + bottom + seq1 + seq2


def _pts_bytes(pts: int) -> bytes:
    return bytes(
        [
            0x21 | ((pts >> 29) & 0x0E),
            (pts >> 22) & 0xFF,
            0x01 | ((pts >> 14) & 0xFE),
            (pts >> 7) & 0xFF,
            0x01 | ((pts << 1) & 0xFE),
        ]
    )


def ps_pack(spu: bytes, pts_ms: int, stream_index: int = 0) -> bytes:
    """Wrap one SPU in a 2048-byte MPEG-2 pack (private stream 1, padded)."""
    payload = (
        bytes([0x81, 0x80, 0x05]) + _pts_bytes(pts_ms * 90) + bytes([0x20 + stream_index]) + spu
    )
    pes = b"\x00\x00\x01\xbd" + len(payload).to_bytes(2, "big") + payload
    pack = _PACK_HEADER + pes
    pad = PACK_SIZE - len(pack)
    if pad < 0:
        raise ValueError(f"subpicture too large for one pack: {len(spu)} bytes")
    if pad >= 6:
        pack += b"\x00\x00\x01\xbe" + (pad - 6).to_bytes(2, "big") + b"\xff" * (pad - 6)
    else:
        pack += b"\xff" * pad
    return pack


def _timestamp(ms: int) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def vobsub(
    events: Sequence[Event],
    *,
    language: str,
    canvas: tuple[int, int] = (720, 480),
    bar_height: int = 30,
) -> tuple[str, bytes]:
    """Return the ``.idx`` text and the ``.sub`` bytes for ``events`` (one track)."""
    cw, ch = canvas
    sub = bytearray()
    entries: list[str] = []
    for ev in events:
        if ev.width > cw - 20:
            raise ValueError("event bar wider than the canvas")
        image = bar_image(ev.width, bar_height)
        spu = spu_packet(image, (cw - ev.width) // 2, ch - bar_height - 40, ev.end_ms - ev.start_ms)
        entries.append(f"timestamp: {_timestamp(ev.start_ms)}, filepos: {len(sub):09x}")
        sub += ps_pack(spu, ev.start_ms)
    idx = "\n".join(
        [
            "# VobSub index file, v7 (do not modify this line!)",
            "# Generated by reframe_testing.vobsub for the Reframe test fixtures.",
            f"size: {cw}x{ch}",
            "org: 0, 0",
            "scale: 100%, 100%",
            "alpha: 100%",
            "smooth: OFF",
            "fadein/out: 0, 0",
            "align: OFF at LEFT TOP",
            "time offset: 0",
            "forced subs: OFF",
            f"palette: {PALETTE}",
            "custom colors: OFF, tridx: 0000, colors: 000000, 000000, 000000, 000000",
            "",
            f"id: {language}, index: 0",
            *entries,
            "",
        ]
    )
    return idx, bytes(sub)
