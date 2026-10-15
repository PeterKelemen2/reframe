"""The bitstream writers of the DTS-HD MA and PGS fixtures (``reframe_testing.dts``,
``reframe_testing.pgs``), checked without FFmpeg. ``test_media_fixtures.py`` checks that
FFmpeg reads what they write (and decodes the DTS-HD MA track losslessly)."""

from __future__ import annotations

import itertools

import pytest

from reframe_testing import dts, pgs
from reframe_testing.vobsub import bar_image

# --------------------------------------------------------------------------- DTS: bits and CRC


def test_crc16_ccitt() -> None:
    assert dts.crc16(b"123456789") == 0x29B1  # the CRC-16/CCITT-FALSE check value
    data = b"\x01\x02\x03DTS"
    assert dts.crc16(data + dts.crc16(data).to_bytes(2, "big")) == 0
    assert dts.crc16(b"") == 0xFFFF


def test_bit_writer() -> None:
    w = dts.BitWriter()
    w.write(0b101, 3)
    w.write(0, 0)
    w.zeros(2)
    w.write(1, 1)
    w.align()
    w.write_bytes(b"\xab")
    w.write_bytes(b"")
    assert w.bits == 16
    assert w.getvalue() == bytes([0b10100100, 0xAB])
    w.pad_to(32)
    assert w.getvalue() == bytes([0b10100100, 0xAB, 0, 0])
    with pytest.raises(ValueError, match="does not fit"):
        w.write(4, 2)
    with pytest.raises(ValueError, match="does not fit"):
        w.write(-1, 4)
    with pytest.raises(ValueError, match="already 32 bits"):
        w.pad_to(8)
    w.write(1, 1)
    with pytest.raises(ValueError, match="not byte aligned"):
        w.getvalue()


def _bits(data: bytes) -> str:
    return "".join(f"{b:08b}" for b in data)


def test_rice_and_linear_codes() -> None:
    """XLL's codes: zigzag (0, -1, 1, -2, …), Rice = unary zeros, a one, ``k`` low bits."""
    assert [dts._zigzag(v) for v in (0, -1, 1, -2, 2)] == [0, 1, 2, 3, 4]
    w = dts.BitWriter()
    dts._write_rice(w, -3, 1)  # zigzag 5: quotient 2 (0, 0, 1), remainder 1
    w.align()
    assert _bits(w.getvalue()).startswith("0011")
    assert dts._rice_bits([-3], 1) == 4
    assert dts._best_rice([]) == 0
    assert dts._best_rice([1000, -1000, 999]) > 5


@pytest.mark.parametrize("order", [0, 1, 2, 3])
def test_fixed_prediction_is_undone_by_running_sums(order: int) -> None:
    samples = dts.tone_frame(5, 0.1)
    res = dts.residuals(samples, order)
    for _ in range(order):  # what ff_dca_xll's chs_filter_band_data does
        res = list(itertools.accumulate(res))
    assert res == samples


def test_tone_frames_repeat_every_frame() -> None:
    frame = dts.tone_frame(3, 0.5)
    assert len(frame) == dts.FRAME_SAMPLES
    assert frame[0] == 0
    assert max(frame) == round(0.5 * (2**23 - 1))
    assert dts.frame_count(4.0) == 375
    assert [dts.frame_gain(i) for i in (0, 93, 94, 187, 188, 374)] == [0, 0, -6, -6, -12, -3]


# --------------------------------------------------------------------------- DTS: frames


def _field(data: bytes, start_bit: int, nbits: int) -> int:
    return int(_bits(data)[start_bit : start_bit + nbits], 2)


SPEAKERS = [t.speaker for t in dts.TONES_5_1]


def test_xll_frame_headers() -> None:
    frame = dts.xll_frame(dts.expected_samples(0), SPEAKERS)
    assert frame[:4] == dts.SYNC_XLL.to_bytes(4, "big")
    header_size = _field(frame, 36, 8) + 1
    assert header_size == 14
    assert dts.crc16(frame[4:header_size]) == 0  # the common header CRC (from the version)
    assert _field(frame, 44, 5) + 1 == 16  # bits of the frame size field
    assert _field(frame, 49, 16) + 1 == len(frame)
    assert len(frame) % 4 == 0
    assert _field(frame, 65, 4) == 0  # one channel set
    assert (_field(frame, 69, 4), _field(frame, 73, 4)) == (1, 8)  # 2 segments of 256
    chs_size = _field(frame[header_size:], 0, 10) + 1
    assert dts.crc16(frame[header_size : header_size + chs_size]) == 0
    chs = frame[header_size:]
    assert _field(chs, 10, 4) + 1 == 6  # channels
    assert _field(chs, 14, 6) == 0b111111  # no core residual
    navi = frame[header_size + chs_size : header_size + chs_size + 6]
    assert dts.crc16(navi) == 0
    segments = [_field(navi, 0, 16) + 1, _field(navi, 16, 16) + 1]
    assert header_size + chs_size + 6 + sum(segments) <= len(frame)


def test_xll_frame_checks_its_input() -> None:
    channels = dts.expected_samples(0)
    with pytest.raises(ValueError, match="speaker-mask order"):
        dts.xll_frame(channels, list(reversed(SPEAKERS)))
    with pytest.raises(ValueError, match="one speaker name each"):
        dts.xll_frame(channels, SPEAKERS[:5])
    with pytest.raises(ValueError, match="512 samples of 24 bits"):
        dts.xll_frame([c[:100] for c in channels], SPEAKERS)
    with pytest.raises(ValueError, match="512 samples of 24 bits"):
        dts.xll_frame([[2**23] * 512], ["C"])
    silent = dts.xll_frame([[0] * 512], ["C"])  # order 0, Rice parameter 0
    assert silent[:4] == dts.SYNC_XLL.to_bytes(4, "big")


def test_exss_frame() -> None:
    xll = dts.xll_frame(dts.expected_samples(0), SPEAKERS)
    frame = dts.exss_frame(xll, SPEAKERS)
    assert frame[:4] == dts.SYNC_EXSS.to_bytes(4, "big")
    assert _field(frame, 42, 1) == 0  # short header
    header_size = _field(frame, 43, 8) + 1
    assert _field(frame, 51, 16) + 1 == len(frame)
    assert header_size % 4 == 0  # what the dts demuxer's probe wants
    assert header_size >= 16
    assert len(frame) % 4 == 0
    assert dts.crc16(frame[5:header_size]) == 0  # the header CRC (from byte 5)
    assert frame[header_size:] == xll
    assert _field(frame, 90, 16) + 1 == len(xll)  # the asset size
    with pytest.raises(ValueError, match="multiple of 4"):
        dts.exss_frame(xll + b"\x00", SPEAKERS)
    stereo = dts.xll_frame([[0] * 512, [0] * 512], ["L", "R"])
    assert dts.exss_frame(stereo, ["L", "R"])[:4] == dts.SYNC_EXSS.to_bytes(4, "big")


def test_the_stream_is_exss_frames_back_to_back() -> None:
    data = dts.dts_hd_ma(1.0)
    frames = 0
    pos = 0
    while pos < len(data):
        assert data[pos : pos + 4] == dts.SYNC_EXSS.to_bytes(4, "big")
        pos += _field(data[pos : pos + 9], 51, 16) + 1
        frames += 1
    assert pos == len(data)
    assert frames == dts.frame_count(1.0) == 94
    assert dts.dts_hd_ma(1.0) is data  # cached: the recipe asks for it on every build


# --------------------------------------------------------------------------- PGS


def _decode_rle(data: bytes, width: int) -> list[list[int]]:
    """FFmpeg's ``decode_rle`` (pgssubdec.c), line by line."""
    rows: list[list[int]] = []
    row: list[int] = []
    i = 0
    while i < len(data):
        color = data[i]
        i += 1
        run = 1
        if color == 0:
            flags = data[i]
            i += 1
            run = flags & 0x3F
            if flags & 0x40:
                run = (run << 8) + data[i]
                i += 1
            if flags & 0x80:
                color = data[i]
                i += 1
            else:
                color = 0
        if run:
            row += [color] * run
        else:
            assert len(row) == width
            rows.append(row)
            row = []
    return rows


@pytest.mark.parametrize(
    "row",
    [
        [0] * 10,
        [0] * 70,
        [0] * 300,
        [1, 2, 1, 1, 0, 2, 2, 2, 2],
        [1] * 63 + [2] * 64 + [1] * 2 + [0] * 3,
        [5] * 500,
    ],
)
def test_rle_round_trip(row: list[int]) -> None:
    assert _decode_rle(pgs.rle_line(row), len(row)) == [row]


def test_rle_of_a_bar() -> None:
    image = bar_image(37, 6)
    assert _decode_rle(pgs.rle(image), 37) == image


def _segments(data: bytes) -> list[tuple[int, int, bytes]]:
    out = []
    pos = 0
    while pos < len(data):
        assert data[pos : pos + 2] == b"PG"
        pts = int.from_bytes(data[pos + 2 : pos + 6], "big")
        assert data[pos + 6 : pos + 10] == bytes(4)  # DTS 0
        kind = data[pos + 10]
        size = int.from_bytes(data[pos + 11 : pos + 13], "big")
        out.append((kind, pts, data[pos + 13 : pos + 13 + size]))
        pos += 13 + size
    return out


def test_sup_display_sets() -> None:
    events = [pgs.Event(200, 800, 100, forced=True), pgs.Event(1000, 1500, 60)]
    segments = _segments(pgs.sup(events, canvas=(320, 180), bar_height=10))
    show = [pgs.PCS, pgs.WDS, pgs.PDS, pgs.ODS, pgs.END]
    clear = [pgs.PCS, pgs.WDS, pgs.END]
    assert [k for k, _, _ in segments] == (show + clear) * 2
    assert [pts for _, pts, _ in segments] == [18000] * 5 + [72000] * 3 + [90000] * 5 + [135000] * 3
    pcs = segments[0][2]
    assert pcs[:4] == bytes([1, 64, 0, 180])  # 320 x 180
    assert pcs[7] == pgs.EPOCH_START
    assert pcs[10] == 1  # one composition object
    assert pcs[14] == pgs.FORCED
    assert segments[8][2][14] == 0  # the second event is not forced
    assert segments[5][2][10] == 0  # a clear display set has no object
    ods = segments[3][2]
    width, height = int.from_bytes(ods[7:9], "big"), int.from_bytes(ods[9:11], "big")
    assert (width, height) == (100, 10)
    assert int.from_bytes(ods[4:7], "big") == len(ods) - 7  # data length incl. width/height
    assert _decode_rle(ods[11:], width) == bar_image(100, 10)
    with pytest.raises(ValueError, match="wider than the canvas"):
        pgs.sup([pgs.Event(0, 1, 400)], canvas=(320, 180))
    with pytest.raises(ValueError, match="too large"):
        pgs.segment(pgs.ODS, bytes(70_000), 0)
