"""C-5 table tests: the classic cases of 05 §C-5 and the behaviour of each setting.

"Table tests cover the classic cases (DVD NTSC 720×480 anamorphic 16:9, 1080p 2.40:1
letterbox, 4K → 1080p)."

The notes are user-facing text with the multiplication sign of the pipeline header.
"""

# ruff: noqa: RUF001, RUF002

from __future__ import annotations

from dataclasses import dataclass

import pytest

from reframe.dimensions import compute_geometry
from reframe.models import (
    CropRect,
    CropSettings,
    DimensionSettings,
    ExactHeight,
    ExactWidth,
    FitWithin,
    Geometry,
    Rational,
    SameAsSource,
    SizeSettings,
    SourceGeometry,
)

DVD_NTSC_16_9 = SourceGeometry(width=720, height=480, sar=Rational(num=32, den=27))
DVD_NTSC_4_3 = SourceGeometry(width=720, height=480, sar=Rational(num=8, den=9))
DVD_PAL_16_9 = SourceGeometry(width=720, height=576, sar=Rational(num=64, den=45), interlaced=True)
HD = SourceGeometry(width=1920, height=1080)
UHD = SourceGeometry(width=3840, height=2160)
NO_CROP = CropSettings(mode="none")


def manual(top: int = 0, bottom: int = 0, left: int = 0, right: int = 0) -> CropSettings:
    return CropSettings(
        mode="manual", rect=CropRect(top=top, bottom=bottom, left=left, right=right)
    )


@dataclass(frozen=True)
class Row:
    """One table row: input → crop (t/b/l/r), cropped size, scaled size, SAR, aspect, notes."""

    name: str
    src: SourceGeometry
    settings: DimensionSettings
    crop: tuple[int, int, int, int]
    cropped: tuple[int, int]
    scaled: tuple[int, int]
    sar: tuple[int, int]
    aspect: float
    notes: list[str]
    upscaled: bool = False


def settings(
    crop: CropSettings = NO_CROP, size: SizeSettings | None = None, **kwargs: object
) -> DimensionSettings:
    return DimensionSettings.model_validate({"crop": crop, "size": size or FitWithin(), **kwargs})


CLASSIC = [
    Row(
        "DVD NTSC 16:9 anamorphic, defaults (fit 1080p, square pixels)",
        DVD_NTSC_16_9,
        settings(),
        (0, 0, 0, 0),
        (720, 480),
        (854, 480),
        (1, 1),
        854 / 480,
        [
            "Upscaling is off, so the picture (853.3×480) is not enlarged to fit 1920×1080.",
            "Size 853.3×480 → 854×480: multiples of 2 (aspect error 0.08 %).",
        ],
    ),
    Row(
        "DVD NTSC 16:9 anamorphic, keep source pixel aspect",
        DVD_NTSC_16_9,
        settings(pixel_aspect="keep"),
        (0, 0, 0, 0),
        (720, 480),
        (720, 480),
        (32, 27),
        16 / 9,
        ["Upscaling is off, so the picture (720×480) is not enlarged to fit 1920×1080."],
    ),
    Row(
        "DVD NTSC 16:9, overscan crop 8 + 8, square pixels",
        DVD_NTSC_16_9,
        settings(manual(left=8, right=8), SameAsSource()),
        (0, 0, 8, 8),
        (704, 480),
        (834, 480),
        (1, 1),
        834 / 480,
        ["Size 834.4×480 → 834×480: multiples of 2 (aspect error 0.04 %)."],
    ),
    Row(
        "DVD NTSC 16:9, modulus 16 keeps the aspect error below 0.5 %",
        DVD_NTSC_16_9,
        settings(NO_CROP, SameAsSource(), modulus=16),
        (0, 0, 0, 0),
        (720, 480),
        (800, 448),
        (1, 1),
        800 / 448,
        ["Size 853.3×480 → 800×448: multiples of 16 (aspect error 0.45 %)."],
    ),
    Row(
        "1080p 2.40:1 letterbox, crop 140 + 140",
        HD,
        settings(manual(top=140, bottom=140)),
        (140, 140, 0, 0),
        (1920, 800),
        (1920, 800),
        (1, 1),
        2.4,
        [],
    ),
    Row(
        "1080p 2.40:1 letterbox to 720p",
        HD,
        settings(manual(top=140, bottom=140), FitWithin(width=1280, height=720)),
        (140, 140, 0, 0),
        (1920, 800),
        (1280, 534),
        (1, 1),
        1280 / 534,
        [
            "Scaled down from 1920×800 to fit 1280×720.",
            "Size 1280×533.3 → 1280×534: multiples of 2 (aspect error 0.12 %).",
        ],
    ),
    Row(
        "1080p letterbox, odd crop values snap to the 4:2:0 grid",
        HD,
        settings(manual(top=141, bottom=139, left=3)),
        (140, 138, 2, 0),
        (1918, 802),
        (1918, 802),
        (1, 1),
        1918 / 802,
        [
            "Crop left 3 → 2 for 4:2:0.",
            "Crop top 141 → 140 for 4:2:0.",
            "Crop bottom 139 → 138 for 4:2:0.",
            "Upscaling is off, so the picture (1918×802) is not enlarged to fit 1920×1080.",
        ],
    ),
    Row(
        "4K → 1080p",
        UHD,
        settings(),
        (0, 0, 0, 0),
        (3840, 2160),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Scaled down from 3840×2160 to fit 1920×1080."],
    ),
    Row(
        "4K 2.40:1 letterbox → 1080p",
        UHD,
        settings(manual(top=280, bottom=280)),
        (280, 280, 0, 0),
        (3840, 1600),
        (1920, 800),
        (1, 1),
        2.4,
        ["Scaled down from 3840×1600 to fit 1920×1080."],
    ),
]


def check(row: Row) -> Geometry:
    g = compute_geometry(row.src, row.settings)
    assert (g.crop.top, g.crop.bottom, g.crop.left, g.crop.right) == row.crop
    assert (g.cropped_width, g.cropped_height) == row.cropped
    assert (g.scaled_width, g.scaled_height) == row.scaled
    assert (g.output_sar.num, g.output_sar.den) == row.sar
    assert g.display_aspect == pytest.approx(row.aspect)
    assert g.notes == row.notes
    assert g.upscaled is row.upscaled
    return g


@pytest.mark.parametrize("row", CLASSIC, ids=[r.name for r in CLASSIC])
def test_classic_cases(row: Row) -> None:
    check(row)


MORE = [
    Row(
        "DVD NTSC 4:3 (SAR 8:9): the height is expanded, nothing is thrown away",
        DVD_NTSC_4_3,
        settings(size=SameAsSource()),
        (0, 0, 0, 0),
        (720, 480),
        (720, 540),
        (1, 1),
        4 / 3,
        [],
    ),
    Row(
        "DVD PAL 16:9 interlaced: the crop and the height follow the field grid",
        DVD_PAL_16_9,
        settings(manual(top=6, bottom=2), SameAsSource()),
        (4, 0, 0, 0),
        (720, 572),
        (1024, 572),
        (1, 1),
        1024 / 572,
        [
            "Crop top 6 → 4 for interlaced 4:2:0.",
            "Crop bottom 2 → 0 for interlaced 4:2:0.",
            "Height: a multiple of 4, not 2, for interlaced 4:2:0.",
        ],
    ),
    Row(
        "720p source, fit 1080p, upscaling off",
        SourceGeometry(width=1280, height=720),
        settings(),
        (0, 0, 0, 0),
        (1280, 720),
        (1280, 720),
        (1, 1),
        16 / 9,
        ["Upscaling is off, so the picture (1280×720) is not enlarged to fit 1920×1080."],
    ),
    Row(
        "720p source, fit 1080p, upscaling on",
        SourceGeometry(width=1280, height=720),
        settings(allow_upscaling=True),
        (0, 0, 0, 0),
        (1280, 720),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Upscaled to fit 1920×1080 (upscaling is on)."],
        upscaled=True,
    ),
    Row(
        "1080p, modulus 16: 1904×1072 keeps the aspect, 1920×1072 would be 0.75 % off",
        HD,
        settings(modulus=16),
        (0, 0, 0, 0),
        (1920, 1080),
        (1904, 1072),
        (1, 1),
        1904 / 1072,
        ["Size 1920×1080 → 1904×1072: multiples of 16 (aspect error 0.09 %)."],
    ),
    # Decision 0020: "Fit within" turns the box to the shape of the output frame.
    Row(
        "Phone video (display matrix 90°), fit 1080p: the box turns, the video stays 1080×1920",
        SourceGeometry(width=1920, height=1080, rotation=90),
        settings(),
        (0, 0, 0, 0),
        (1080, 1920),
        (1080, 1920),
        (1, 1),
        9 / 16,
        ["Portrait picture: fit box turned to 1080×1920."],
    ),
    Row(
        "4K phone video, fit 1080p: down to 1080×1920",
        SourceGeometry(width=3840, height=2160, rotation=270),
        settings(),
        (0, 0, 0, 0),
        (2160, 3840),
        (1080, 1920),
        (1, 1),
        9 / 16,
        [
            "Portrait picture: fit box turned to 1080×1920.",
            "Scaled down from 2160×3840 to fit 1080×1920.",
        ],
    ),
    Row(
        "Job rotation 90 makes a 1080p picture portrait: the box turns too",
        HD,
        settings(rotate=90),
        (0, 0, 0, 0),
        (1920, 1080),
        (1080, 1920),
        (1, 1),
        9 / 16,
        ["Portrait picture: fit box turned to 1080×1920."],
    ),
    Row(
        "Landscape picture, portrait custom box 720×1280: the box turns to 1280×720",
        HD,
        settings(size=FitWithin(width=720, height=1280)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1280, 720),
        (1, 1),
        16 / 9,
        [
            "Landscape picture: fit box turned to 1280×720.",
            "Scaled down from 1920×1080 to fit 1280×720.",
        ],
    ),
    Row(
        "Square picture: the box is used as written",
        SourceGeometry(width=2160, height=2160),
        settings(),
        (0, 0, 0, 0),
        (2160, 2160),
        (1080, 1080),
        (1, 1),
        1.0,
        ["Scaled down from 2160×2160 to fit 1920×1080."],
    ),
    Row(
        "Pixel aspect decides the shape: 4K stored with PAR 4:1 is a portrait frame",
        UHD,
        settings(pixel_aspect="custom", custom_par=Rational(num=4, den=1)),
        (0, 0, 0, 0),
        (3840, 2160),
        (854, 1920),
        (4, 1),
        854 * 4 / 1920,
        [
            "Portrait picture: fit box turned to 1080×1920.",
            "Scaled down from 960×2160 to fit 1080×1920.",
            "Size 853.3×1920 → 854×1920: multiples of 2 (aspect error 0.08 %).",
        ],
    ),
    Row(
        "Exact height is not turned for a portrait picture",
        SourceGeometry(width=1920, height=1080, rotation=90),
        settings(size=ExactHeight(height=1280)),
        (0, 0, 0, 0),
        (1080, 1920),
        (720, 1280),
        (1, 1),
        9 / 16,
        [],
    ),
    Row(
        "Phone video turned back by the job (rotate 270)",
        SourceGeometry(width=1920, height=1080, rotation=90),
        settings(rotate=270),
        (0, 0, 0, 0),
        (1080, 1920),
        (1920, 1080),
        (1, 1),
        16 / 9,
        [],
    ),
    Row(
        "Job rotation 90 of an anamorphic DVD keeps the source pixel aspect (inverted)",
        DVD_NTSC_16_9,
        settings(size=SameAsSource(), rotate=90, pixel_aspect="keep"),
        (0, 0, 0, 0),
        (720, 480),
        (480, 720),
        (27, 32),
        9 / 16,
        [],
    ),
    Row(
        "Exact width 1280",
        HD,
        settings(manual(top=140, bottom=140), ExactWidth(width=1280)),
        (140, 140, 0, 0),
        (1920, 800),
        (1280, 534),
        (1, 1),
        1280 / 534,
        ["Size 1280×533.3 → 1280×534: multiples of 2 (aspect error 0.12 %)."],
    ),
    Row(
        "Exact height 720 of a 2.39:1 picture, modulus 16: the width gives way",
        SourceGeometry(width=1920, height=804),
        settings(size=ExactWidth(width=1280), modulus=16),
        (0, 0, 0, 0),
        (1920, 804),
        (1264, 528),
        (1, 1),
        1264 / 528,
        ["Size 1280×536 → 1264×528: multiples of 16 (aspect error 0.25 %)."],
    ),
    Row(
        "Exact height 720",
        HD,
        settings(size=ExactHeight(height=720)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1280, 720),
        (1, 1),
        16 / 9,
        [],
    ),
    Row(
        "Exact width larger than the picture, upscaling off: the picture keeps its size",
        HD,
        settings(size=ExactWidth(width=3840)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        [
            "Width 3840 is larger than the picture (1920): upscaling is off, so the picture "
            "keeps its size."
        ],
    ),
    Row(
        "Exact height larger than the picture, upscaling on",
        HD,
        settings(size=ExactHeight(height=2160), allow_upscaling=True),
        (0, 0, 0, 0),
        (1920, 1080),
        (3840, 2160),
        (1, 1),
        16 / 9,
        ["Upscaled: height 2160 is larger than the picture (1080)."],
        upscaled=True,
    ),
    Row(
        "Custom pixel aspect 4:3 (HDV-style 1440×1080)",
        HD,
        settings(size=SameAsSource(), pixel_aspect="custom", custom_par=Rational(num=4, den=3)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1440, 1080),
        (4, 3),
        16 / 9,
        [],
    ),
    Row(
        "Custom pixel aspect 3:4 (tall pixels) shrinks the height",
        HD,
        settings(size=SameAsSource(), pixel_aspect="custom", custom_par=Rational(num=3, den=4)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 810),
        (3, 4),
        16 / 9,
        [],
    ),
    Row(
        "Custom pixel aspect missing: square pixels",
        HD,
        settings(pixel_aspect="custom"),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Custom pixel aspect is not set or not valid: square pixels are used."],
    ),
    Row(
        "Custom pixel aspect 0/1 is not valid",
        HD,
        settings(pixel_aspect="custom", custom_par=Rational(num=0, den=1)),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Custom pixel aspect is not set or not valid: square pixels are used."],
    ),
    Row(
        "4:1:1 DV NTSC: crop and width follow the 4-pixel chroma grid",
        SourceGeometry(
            width=720, height=480, sar=Rational(num=10, den=11), chroma_step_x=4, chroma_step_y=1
        ),
        settings(manual(left=6, right=6), SameAsSource()),
        (0, 0, 4, 4),
        (712, 480),
        (712, 528),
        (1, 1),
        712 / 528,
        [
            "Crop left 6 → 4 for 4:1:1.",
            "Crop right 6 → 4 for 4:1:1.",
            "Width: a multiple of 4, not 2, for 4:1:1.",
        ],
    ),
    Row(
        "4:4:4: any crop value is on the grid",
        SourceGeometry(width=1920, height=1080, chroma_step_x=1, chroma_step_y=1),
        settings(manual(top=141, left=3), SameAsSource()),
        (141, 0, 3, 0),
        (1917, 939),
        (1916, 938),
        (1, 1),
        1916 / 938,
        ["Size 1917×939 → 1916×938: multiples of 2 (aspect error 0.05 %)."],
    ),
    Row(
        "A frame size off the grid: the far edges grow by one pixel",
        SourceGeometry(width=853, height=481),
        settings(manual(top=40), SameAsSource()),
        (40, 1, 0, 1),
        (852, 440),
        (852, 440),
        (1, 1),
        852 / 440,
        [
            "Crop right 0 → 1 so that the width (852) is a multiple of 2 for 4:2:0.",
            "Crop bottom 0 → 1 so that the height (440) is a multiple of 2 for 4:2:0.",
        ],
    ),
    Row(
        "A frame size off the grid without a crop: no crop filter, scale rounds",
        SourceGeometry(width=853, height=481),
        settings(size=SameAsSource()),
        (0, 0, 0, 0),
        (853, 481),
        (852, 480),
        (1, 1),
        852 / 480,
        ["Size 853×481 → 852×480: multiples of 2 (aspect error 0.09 %)."],
    ),
    Row(
        "A crop that removes the full width is not applied on that axis",
        DVD_NTSC_16_9,
        settings(manual(left=400, right=400, top=3), SameAsSource()),
        (2, 0, 0, 0),
        (720, 478),
        (854, 478),
        (1, 1),
        854 / 478,
        [
            "Crop left + right (800) removes the full width (720): no horizontal crop is applied.",
            "Crop top 3 → 2 for 4:2:0.",
            "Size 853.3×478 → 854×478: multiples of 2 (aspect error 0.08 %).",
        ],
    ),
    Row(
        "A crop that leaves less than one chroma step is not applied on that axis",
        SourceGeometry(width=9, height=8),
        settings(manual(left=4, right=4), SameAsSource()),
        (0, 0, 0, 0),
        (9, 8),
        (8, 8),
        (1, 1),
        1.0,
        [
            "Crop left + right (8) leaves less than 2 pixels on the 4:2:0 grid: no horizontal "
            "crop is applied.",
            # 11 % off, but less than one pixel from 8 x 7.1: the "< 1 px" rule of 05 §C-5.
            "Size 9×8 → 8×8: multiples of 2 (aspect error 11.11 %).",
        ],
    ),
    Row(
        "A 1-pixel-high frame cannot be cropped on the 4:2:0 grid",
        SourceGeometry(width=64, height=1),
        settings(manual(left=2), SameAsSource()),
        (0, 0, 0, 0),
        (64, 1),
        (64, 2),
        (1, 1),
        32.0,
        [
            "The height (1) is less than one 4:2:0 step: no crop is applied.",
            "Size 64×1 → 64×2: multiples of 2 (aspect error 50.00 %).",
            "No size in multiples of the modulus keeps the aspect error below 0.50 % here; "
            "64×2 is the closest.",
            "One modulus step (2) is more than the height limit (1): the output height is 2.",
        ],
        upscaled=True,
    ),
    Row(
        "A fit box smaller than one modulus step gives one step",
        HD,
        settings(size=FitWithin(width=8, height=8), modulus=16),
        (0, 0, 0, 0),
        (1920, 1080),
        (16, 16),
        (1, 1),
        1.0,
        [
            "Scaled down from 1920×1080 to fit 8×8.",
            "Size 8×4.5 → 16×16: multiples of 16 (aspect error 43.75 %).",
            "No size in multiples of the modulus keeps the aspect error below 0.50 % here; "
            "16×16 is the closest.",
            "One modulus step (16) is more than the width limit (8): the output width is 16.",
            "One modulus step (16) is more than the height limit (8): the output height is 16.",
        ],
    ),
    Row(
        "Automatic crop before detection ran: no crop",
        HD,
        settings(CropSettings(mode="auto")),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Automatic crop: detection has not run yet, so no crop is applied."],
    ),
    Row(
        "Conservative crop before detection ran: no crop",
        HD,
        settings(CropSettings(mode="conservative")),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Conservative crop: detection has not run yet, so no crop is applied."],
    ),
    Row(
        "Automatic crop with a detected rect",
        HD,
        settings(CropSettings(mode="auto", rect=CropRect(top=140, bottom=140))),
        (140, 140, 0, 0),
        (1920, 800),
        (1920, 800),
        (1, 1),
        2.4,
        [],
    ),
    Row(
        "Manual crop without values: no crop",
        HD,
        settings(CropSettings(mode="manual")),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["Manual crop has no values: no crop is applied."],
    ),
    Row(
        "Crop mode none ignores the rect",
        HD,
        settings(CropSettings(mode="none", rect=CropRect(top=140, bottom=140))),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        [],
    ),
    Row(
        "Unknown pixel format: the crop assumes 4:2:0",
        SourceGeometry(width=1920, height=1080, chroma_assumed=True),
        settings(manual(top=141)),
        (140, 0, 0, 0),
        (1920, 940),
        (1920, 940),
        (1, 1),
        1920 / 940,
        [
            "Crop top 141 → 140 for 4:2:0.",
            "The pixel format is unknown: the crop assumes 4:2:0 (steps of 2).",
        ],
    ),
    Row(
        "A source pixel aspect of 0 counts as square",
        SourceGeometry(width=1920, height=1080, sar=Rational(num=0, den=1)),
        settings(),
        (0, 0, 0, 0),
        (1920, 1080),
        (1920, 1080),
        (1, 1),
        16 / 9,
        ["The source pixel aspect 0/1 is not valid: square pixels are used."],
    ),
]


@pytest.mark.parametrize("row", MORE, ids=[r.name for r in MORE])
def test_more_cases(row: Row) -> None:
    check(row)


def test_crop_is_in_the_displayed_orientation() -> None:
    """A 90° display matrix: the crop's top edge is the top of the upright (portrait) picture."""
    phone = SourceGeometry(width=1920, height=1080, rotation=90)
    g = compute_geometry(phone, settings(manual(top=100), SameAsSource()))
    assert (g.crop.top, g.cropped_width, g.cropped_height) == (100, 1080, 1820)
    assert g.rotation == 90
    assert g.filter_rotation == 0


def test_rotated_4_2_2_swaps_the_crop_steps() -> None:
    """4:2:2 (steps 2 x 1) turned by the display matrix: 1 across, 2 down."""
    src = SourceGeometry(width=1920, height=1080, rotation=270, chroma_step_x=2, chroma_step_y=1)
    g = compute_geometry(src, settings(manual(top=3, left=3), SameAsSource()))
    assert (g.crop.top, g.crop.left) == (2, 3)
    assert g.notes[0] == "Crop top 3 → 2 for 4:2:2."


def test_flip_and_rotation_are_reported_for_the_command_builder() -> None:
    src = SourceGeometry(width=1920, height=1080, rotation=180)
    g = compute_geometry(src, settings(rotate=90, flip_horizontal=True, size=SameAsSource()))
    assert (g.rotation, g.filter_rotation, g.flip_horizontal) == (270, 90, True)
    assert (g.scaled_width, g.scaled_height) == (1080, 1920)


def test_negative_crop_values_are_clamped() -> None:
    """``model_construct`` skips validation; the maths still never crops a negative amount."""
    rect = CropRect.model_construct(top=-4, bottom=0, left=0, right=0)
    crop = CropSettings.model_construct(mode="manual", rect=rect)
    g = compute_geometry(HD, settings(crop))
    assert (g.crop.top, g.cropped_height) == (0, 1080)
    assert g.notes[0] == "Crop top -4 is negative: 0 is used."


def test_unusual_chroma_grid_is_named_by_its_steps() -> None:
    src = SourceGeometry(width=1920, height=1080, chroma_step_x=3, chroma_step_y=1)
    g = compute_geometry(src, settings(manual(left=4), SameAsSource(), modulus=2))
    assert g.notes[0] == "Crop left 4 → 3 for a 3×1 chroma grid."
