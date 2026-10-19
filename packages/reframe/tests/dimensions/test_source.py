"""What ``source_geometry`` takes from the probed video stream, and the chroma-step table."""

from __future__ import annotations

import pytest

from reframe.dimensions import ASSUMED_CHROMA_STEPS, chroma_steps, source_geometry
from reframe.models import FieldOrder, Rational, VideoStream


@pytest.mark.parametrize(
    ("pix_fmt", "steps"),
    [
        ("yuv420p", (2, 2)),
        ("nv12", (2, 2)),
        ("p010le", (2, 2)),
        ("yuv422p", (2, 1)),
        ("nv16", (2, 1)),
        ("p210le", (2, 1)),
        ("y210le", (2, 1)),
        ("v210", (2, 1)),
        ("yuv444p", (1, 1)),
        ("nv24", (1, 1)),
        ("p410le", (1, 1)),  # not 4:1:0
        ("y410le", (1, 1)),  # not 4:1:0
        ("xv30le", (1, 1)),
        ("vuya", (1, 1)),
        ("ayuv64le", (1, 1)),
        ("uyva", (1, 1)),
        ("rgb24", (1, 1)),
        ("x2rgb10le", (1, 1)),
        ("gray", (1, 1)),
        ("rgb444le", (1, 1)),
        ("yuv411p", (4, 1)),
        ("uyyvyy411", (4, 1)),
        ("yuv410p", (4, 4)),
        ("yuv440p", (1, 2)),
        ("YUV420P", (2, 2)),
    ],
)
def test_chroma_steps(pix_fmt: str, steps: tuple[int, int]) -> None:
    assert chroma_steps(pix_fmt) == steps


@pytest.mark.parametrize("pix_fmt", [None, "", "vaapi", "bayer_rggb8"])
def test_unknown_pixel_formats(pix_fmt: str | None) -> None:
    assert chroma_steps(pix_fmt) is None


def video(**fields: object) -> VideoStream:
    return VideoStream.model_validate({"index": 0, "width": 720, "height": 480, **fields})


def test_source_geometry_of_an_anamorphic_dvd() -> None:
    src = source_geometry(
        video(sar=Rational(num=64, den=54), pix_fmt="yuv420p", field_order=FieldOrder.TOP_FIRST)
    )
    assert (src.width, src.height) == (720, 480)
    assert (src.sar.num, src.sar.den) == (32, 27)  # reduced
    assert (src.chroma_step_x, src.chroma_step_y) == (2, 2)
    assert src.interlaced
    assert not src.chroma_assumed
    assert src.rotation == 0


@pytest.mark.parametrize("sar", [None, Rational(num=0, den=1), Rational(num=-4, den=3)])
def test_unknown_sar_is_square(sar: Rational | None) -> None:
    src = source_geometry(video(sar=sar))
    assert (src.sar.num, src.sar.den) == (1, 1)


def test_unknown_pixel_format_is_assumed_4_2_0() -> None:
    src = source_geometry(video(pix_fmt=None))
    assert (src.chroma_step_x, src.chroma_step_y) == ASSUMED_CHROMA_STEPS == (2, 2)
    assert src.chroma_assumed


@pytest.mark.parametrize(
    ("order", "interlaced"),
    [
        (FieldOrder.TOP_FIRST, True),
        (FieldOrder.BOTTOM_FIRST, True),
        (FieldOrder.PROGRESSIVE, False),
        (FieldOrder.UNKNOWN, False),
    ],
)
def test_interlacing_from_the_field_order(order: FieldOrder, interlaced: bool) -> None:
    assert source_geometry(video(field_order=order)).interlaced is interlaced


def test_rotation_from_the_display_matrix() -> None:
    assert source_geometry(video(rotation=90)).rotation == 90


def test_4_2_2_ten_bit() -> None:
    src = source_geometry(video(pix_fmt="yuv422p10le"))
    assert (src.chroma_step_x, src.chroma_step_y) == (2, 1)
