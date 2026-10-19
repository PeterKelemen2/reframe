"""Write a DTS-HD Master Audio stream (lossless, XLL) with plain Python.

FFmpeg's ``dca`` encoder writes a DTS core only, so this module writes the stream itself:
extension substream frames with one XLL asset and no DTS core. The decoded samples are the
ones written.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Sequence
from dataclasses import dataclass

#: Extension substream sync word (ETSI TS 102 114 clause 7.4.1).
SYNC_EXSS = 0x64582025
#: XLL (lossless) sync word (clause 8.3.1).
SYNC_XLL = 0x41A29547
#: Index of 48 kHz in the DTS-HD sampling frequency table (``ff_dca_sampling_freqs``).
SAMPLE_RATE_48K = 12
SAMPLE_RATE = 48_000
#: Samples per frame (one XLL frame per EXSS frame): 2 segments of 256 samples.
SEGMENT_SAMPLES_LOG2 = 8
SEGMENTS_LOG2 = 1
FRAME_SAMPLES = 1 << (SEGMENT_SAMPLES_LOG2 + SEGMENTS_LOG2)
BITS = 24
_MAX = (1 << (BITS - 1)) - 1
_MIN = -(1 << (BITS - 1))

#: XLL channel mask bits (``DCA_SPEAKER_MASK_*``): one bit per loudspeaker.
SPEAKER_BITS = {"C": 0, "L": 1, "R": 2, "Ls": 3, "Rs": 4, "LFE": 5}
#: EXSS loudspeaker activity mask bits (``DCA_SPEAKER_PAIR_*``): one bit per pair.
SPEAKER_PAIRS = {"C": 0x1, "L": 0x2, "R": 0x2, "Ls": 0x4, "Rs": 0x4, "LFE": 0x8}


class BitWriter:
    """MSB-first bit writer."""

    def __init__(self) -> None:
        self._value = 0
        self.bits = 0

    def write(self, value: int, nbits: int) -> None:
        if nbits == 0:
            return
        if value < 0 or value >> nbits:
            raise ValueError(f"{value} does not fit in {nbits} bits")
        self._value = (self._value << nbits) | value
        self.bits += nbits

    def zeros(self, nbits: int) -> None:
        self._value <<= nbits
        self.bits += nbits

    def align(self, unit: int = 8) -> None:
        self.zeros(-self.bits % unit)

    def pad_to(self, nbits: int) -> None:
        if nbits < self.bits:
            raise ValueError(f"already {self.bits} bits, more than {nbits}")
        self.zeros(nbits - self.bits)

    def write_bytes(self, data: bytes) -> None:
        if data:
            self.write(int.from_bytes(data, "big"), 8 * len(data))

    def getvalue(self) -> bytes:
        if self.bits % 8:
            raise ValueError("not byte aligned")
        return self._value.to_bytes(self.bits // 8, "big")


@functools.cache
def _crc_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        table.append(crc & 0xFFFF)
    return tuple(table)


def crc16(data: bytes) -> int:
    """CRC-16/CCITT (polynomial 0x1021, initial value 0xFFFF, MSB first, no final XOR): the
    checksum of the DTS headers (FFmpeg ``AV_CRC_16_CCITT``). Appended big-endian, the CRC of
    data plus checksum is 0."""
    table = _crc_table()
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ table[(crc >> 8) ^ byte]
    return crc


def _with_crc(writer: BitWriter, start_byte: int) -> bytes:
    data = writer.getvalue()
    return data + crc16(data[start_byte:]).to_bytes(2, "big")


def _zigzag(value: int) -> int:
    """Signed → unsigned as XLL's linear and Rice codes store it (``get_linear``)."""
    return 2 * value if value >= 0 else -2 * value - 1


def _rice_bits(values: Sequence[int], k: int) -> int:
    return sum((_zigzag(v) >> k) + 1 + k for v in values)


def _best_rice(values: Sequence[int]) -> int:
    if not values:
        return 0
    return min(range(24), key=lambda k: (_rice_bits(values, k), k))


def _write_rice(writer: BitWriter, value: int, k: int) -> None:
    u = _zigzag(value)
    writer.zeros(u >> k)  # unary: q zeros, then a one
    writer.write(1, 1)
    writer.write(u & ((1 << k) - 1), k)


def residuals(samples: Sequence[int], order: int) -> list[int]:
    """Fixed prediction of ``order``: the first difference applied ``order`` times, inside
    the frame (the first value stays). The decoder adds the running sum ``order`` times."""
    out = list(samples)
    for _ in range(order):
        out = [out[0]] + [out[i] - out[i - 1] for i in range(1, len(out))]
    return out


@dataclass(frozen=True)
class _Channel:
    order: int
    residuals: list[int]
    isolated_bits: int
    """Bits of the linear code of the ``order`` isolated samples (0: none)."""


def _code_channel(samples: Sequence[int]) -> _Channel:
    best: _Channel | None = None
    best_cost = math.inf
    half = FRAME_SAMPLES >> SEGMENTS_LOG2
    for order in range(4):
        res = residuals(samples, order)
        iso = max((_zigzag(v).bit_length() for v in res[:order]), default=0)
        cost = order * iso
        for seg in range(1 << SEGMENTS_LOG2):
            part = res[seg * half : (seg + 1) * half]
            if seg == 0:
                part = part[order:]
            cost += _rice_bits(part, _best_rice(part))
        if cost < best_cost:
            best, best_cost = _Channel(order, res, max(iso, 1) if order else 0), cost
    assert best is not None
    return best


def xll_frame(channels: Sequence[Sequence[int]], speakers: Sequence[str]) -> bytes:
    """One XLL frame (one channel set, 48 kHz, 24-bit) of ``FRAME_SAMPLES`` samples per
    channel, padded to a multiple of 4 bytes."""
    nch = len(channels)
    if not 1 <= nch <= 8 or len(speakers) != nch:
        raise ValueError("1 to 8 channels, one speaker name each")
    order_of = sorted(range(nch), key=lambda i: SPEAKER_BITS[speakers[i]])
    if order_of != list(range(nch)):
        raise ValueError("channels must be in speaker-mask order (C, L, R, Ls, Rs, LFE)")
    for samples in channels:
        if len(samples) != FRAME_SAMPLES or not all(_MIN <= s <= _MAX for s in samples):
            raise ValueError(f"each channel needs {FRAME_SAMPLES} samples of {BITS} bits")
    ch_mask = sum(1 << SPEAKER_BITS[s] for s in speakers)
    coded = [_code_channel(samples) for samples in channels]
    nabits = 5  # storage resolution > 16 bits
    seg_samples = 1 << SEGMENT_SAMPLES_LOG2

    segments: list[bytes] = []
    for seg in range(1 << SEGMENTS_LOG2):
        w = BitWriter()
        if seg:
            w.write(0, 1)  # new coding parameters (not those of the previous segment)
        w.write(0, 1)  # seg_common: one set of parameters per channel
        parts: list[list[int]] = []
        for ch in coded:
            part = ch.residuals[seg * seg_samples : (seg + 1) * seg_samples]
            parts.append(part)
        ks: list[int] = []
        for ch, part in zip(coded, parts, strict=True):
            hybrid = seg == 0 and ch.order > 0
            w.write(1, 1)  # Rice code
            w.write(1 if hybrid else 0, 1)  # hybrid Rice (isolated samples)
            if hybrid:
                w.write(ch.isolated_bits - 1, nabits)
            ks.append(_best_rice(part[ch.order :] if hybrid else part))
        for k in ks:
            if seg == 0:
                w.write(0, nabits)  # part A: no samples (no adaptive prediction)
            w.write(k, nabits)
        for ch, part, k in zip(coded, parts, ks, strict=True):
            if seg == 0 and ch.order > 0:
                w.write(ch.order, SEGMENT_SAMPLES_LOG2)  # isolated samples
                for loc in range(ch.order):
                    w.write(loc, SEGMENT_SAMPLES_LOG2)
                for j, value in enumerate(part):
                    if j < ch.order:
                        w.write(_zigzag(value), ch.isolated_bits)
                    else:
                        _write_rice(w, value, k)
            else:
                for value in part:
                    _write_rice(w, value, k)
        w.align()
        segments.append(w.getvalue())

    chs = BitWriter()
    chs.zeros(10)  # header size, set below
    chs.write(nch - 1, 4)
    chs.write((1 << nch) - 1, nch)  # residual_encode: every channel lossless on its own
    chs.write(BITS - 1, 5)  # PCM resolution
    chs.write(BITS - 1, 5)  # storage unit width
    chs.write(SAMPLE_RATE_48K, 4)
    chs.write(0, 2)  # sampling frequency modifier
    chs.write(0, 2)  # replacement set
    chs.write(1, 1)  # primary channel set
    chs.write(0, 1)  # no downmix coefficients
    chs.write(1, 1)  # part of the channel hierarchy
    chs.write(1, 1)  # channel mask enabled
    chs.write(ch_mask, 16)
    chs.write(0, 1)  # no pairwise channel decorrelation
    for _ in coded:
        chs.write(0, 4)  # adaptive prediction order 0
    for ch in coded:
        chs.write(ch.order, 2)  # fixed prediction order
    chs.align()
    size = chs.bits // 8 + 2
    chs_bytes = bytearray(chs.getvalue())
    chs_bytes[0] = (size - 1) >> 2
    chs_bytes[1] |= ((size - 1) & 0x3) << 6
    chs_header = bytes(chs_bytes) + crc16(bytes(chs_bytes)).to_bytes(2, "big")

    navi = BitWriter()
    for data in segments:
        navi.write(len(data) - 1, 16)
    navi.align()
    navi_bytes = _with_crc(navi, 0)

    body = chs_header + navi_bytes + b"".join(segments)
    header_size = 14
    frame_size = header_size + len(body)
    frame_size += -frame_size % 4
    if frame_size > 1 << 16:
        raise ValueError("XLL frame too large for a 16-bit size field")

    common = BitWriter()
    common.write(SYNC_XLL, 32)
    common.write(0, 4)  # version 1
    common.write(header_size - 1, 8)
    common.write(16 - 1, 5)  # bits of the frame size field
    common.write(frame_size - 1, 16)
    common.write(0, 4)  # one channel set
    common.write(SEGMENTS_LOG2, 4)
    common.write(SEGMENT_SAMPLES_LOG2, 4)
    common.write(16 - 1, 5)  # bits of a segment size
    common.write(0, 2)  # no CRC in the band data
    common.write(0, 1)  # no MSB/LSB split
    common.write(16 - 1, 5)  # bits of the channel mask
    common.pad_to(8 * (header_size - 2))
    frame = _with_crc(common, 4) + body
    return frame + bytes(frame_size - len(frame))


def exss_frame(xll: bytes, speakers: Sequence[str]) -> bytes:
    """An extension substream frame with one asset that holds the XLL frame ``xll``."""
    if len(xll) % 4:
        raise ValueError("the XLL frame must be a multiple of 4 bytes")
    nch = len(speakers)
    spkr_mask = 0
    for name in speakers:
        spkr_mask |= SPEAKER_PAIRS[name]

    descriptor = BitWriter()
    descriptor.zeros(9)  # descriptor size, set below
    descriptor.write(0, 3)  # asset index
    descriptor.write(0, 1)  # no asset type descriptor
    descriptor.write(0, 1)  # no language descriptor
    descriptor.write(0, 1)  # no additional text
    descriptor.write(BITS - 1, 5)  # PCM resolution
    descriptor.write(SAMPLE_RATE_48K, 4)  # maximum sampling frequency
    descriptor.write(nch - 1, 8)  # total channels
    descriptor.write(1, 1)  # one-to-one map of channels to speakers
    if nch > 2:
        descriptor.write(0, 1)  # no embedded stereo
    if nch > 6:
        descriptor.write(0, 1)  # no embedded 6 channels
    descriptor.write(1, 1)  # speaker mask enabled
    descriptor.write(3, 2)  # 16-bit speaker mask
    descriptor.write(spkr_mask, 16)
    descriptor.write(0, 3)  # no speaker remapping sets
    descriptor.write(0, 1)  # no dynamic range coefficient
    descriptor.write(0, 1)  # no dialogue normalisation
    descriptor.write(0, 2)  # coding mode 0: coding components listed in the mask
    descriptor.write(0x200, 12)  # components: XLL only
    descriptor.write(len(xll) - 1, 16)  # XLL size
    descriptor.write(0, 1)  # no XLL sync word offset (no peak bit rate smoothing)
    descriptor.write(0, 3)  # DTS-HD stream id
    descriptor.write(0, 2)  # not for a secondary decoder; no revision 2 DRC metadata
    descriptor.align()
    desc = bytearray(descriptor.getvalue())
    desc_size = len(desc)
    desc[0] = (desc_size - 1) >> 1
    desc[1] |= ((desc_size - 1) & 0x1) << 7

    head = BitWriter()
    head.write(SYNC_EXSS, 32)
    head.write(0, 8)  # user defined bits
    head.write(0, 2)  # extension substream index
    head.write(0, 1)  # short header: 8-bit header size, 16-bit frame size
    head.zeros(8 + 16)  # header size and frame size, set below
    head.write(1, 1)  # static fields present
    head.write(2, 2)  # reference clock 1/48000 s
    head.write(0, 3)  # frame duration: 512 clock periods
    head.write(0, 1)  # no timecode
    head.write(0, 3)  # one audio presentation
    head.write(0, 3)  # one audio asset
    head.write(1, 1)  # presentation 0 uses extension substream 0
    head.write(1, 8)  # … and its asset 0
    head.write(0, 1)  # no mixing metadata
    head.write(len(xll) - 1, 16)  # asset size
    head.write_bytes(bytes(desc))
    head.write(0, 1)  # no backward-compatible core
    head.align()
    header_size = head.bits // 8 + 2
    header_size += -header_size % 4
    head.pad_to(8 * (header_size - 2))
    frame_size = header_size + len(xll)
    data = bytearray(head.getvalue())
    # Header size (8 bits) and frame size (16 bits) are bits 43 to 66: bytes 5 to 8 hold bits
    # 40 to 71, so the 24 bits start 3 bits into that word.
    fields = ((header_size - 1) << 16) | (frame_size - 1)
    value = int.from_bytes(data[5:9], "big") | (fields << (32 - 3 - 24))
    data[5:9] = value.to_bytes(4, "big")
    return bytes(data) + crc16(bytes(data[5:])).to_bytes(2, "big") + xll


def tone_frame(frequency_index: int, amplitude: float) -> list[int]:
    """One frame of a sine with ``frequency_index`` periods per frame (93.75 Hz steps at
    48 kHz), so every frame of a steady tone is the same."""
    peak = amplitude * _MAX
    return [
        round(peak * math.sin(2 * math.pi * frequency_index * n / FRAME_SAMPLES))
        for n in range(FRAME_SAMPLES)
    ]


@dataclass(frozen=True)
class Tone:
    speaker: str
    frequency_index: int
    """Periods per 512-sample frame: the frequency is ``frequency_index * 93.75`` Hz."""
    level_db: float


#: A 5.1 layout, a different tone per channel.
TONES_5_1 = (
    Tone("C", 5, -20.0),
    Tone("L", 4, -20.0),
    Tone("R", 6, -20.0),
    Tone("Ls", 3, -26.0),
    Tone("Rs", 7, -26.0),
    Tone("LFE", 1, -20.0),
)
#: Gain per second (dB): the frames differ from second to second, so the bit rate varies.
ENVELOPE_DB = (0.0, -6.0, -12.0, -3.0)


@functools.cache
def _frame_for_gain(tones: tuple[Tone, ...], gain_db: float) -> bytes:
    channels = [tone_frame(t.frequency_index, 10 ** ((t.level_db + gain_db) / 20)) for t in tones]
    speakers = [t.speaker for t in tones]
    return exss_frame(xll_frame(channels, speakers), speakers)


def frame_count(seconds: float) -> int:
    return round(seconds * SAMPLE_RATE / FRAME_SAMPLES)


def frame_gain(index: int, envelope: Sequence[float] = ENVELOPE_DB) -> float:
    """The gain (dB) of frame ``index``: one envelope step per second."""
    second = index * FRAME_SAMPLES // SAMPLE_RATE
    return envelope[second % len(envelope)]


@functools.cache
def dts_hd_ma(seconds: float = 4.0, tones: tuple[Tone, ...] = TONES_5_1) -> bytes:
    """A raw DTS-HD MA stream (``.dtshd``: EXSS frames back to back) of ``seconds``."""
    return b"".join(_frame_for_gain(tones, frame_gain(i)) for i in range(frame_count(seconds)))


def expected_samples(index: int, tones: tuple[Tone, ...] = TONES_5_1) -> list[list[int]]:
    """The samples of frame ``index`` per channel (in ``tones`` order), as written."""
    gain = frame_gain(index)
    return [tone_frame(t.frequency_index, 10 ** ((t.level_db + gain) / 20)) for t in tones]
