"""C-5 "Done when": hypothesis properties of ``compute_geometry``.

05 §C-5: "the output is inside the fit box; no upscale unless allowed; the result is a multiple
of the modulus; display aspect error < 0.5 % (or < 1 px); the crop is never negative and never
removes the full frame."

The corners where a property cannot hold are defined behaviour (decision record 0009, module
docstring of ``reframe.dimensions``) and are asserted here, not skipped:

- a fit box, or a picture, smaller than one modulus step on an axis gives exactly one step on
  that axis (outside the box, or upscaled);
- when no size inside the limits meets the aspect tolerance (tiny limits, large modulus), the
  result is the closest one, and an exhaustive search proves that nothing better existed.

The oracle below works from the definitions (display size, natural size) with exact fractions;
it does not call the module's helpers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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
    SourceGeometry,
)

PROPERTY = settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

STEPS = [(2, 2), (2, 1), (1, 1), (4, 1), (4, 4), (1, 2)]
ROTATIONS = [0, 90, 180, 270]
LIMIT = Fraction(1, 200)


def _dims() -> st.SearchStrategy[int]:
    return st.one_of(st.integers(1, 64), st.integers(65, 8192))


@st.composite
def sources(draw: st.DrawFn) -> SourceGeometry:
    step_x, step_y = draw(st.sampled_from(STEPS))
    sar = draw(
        st.one_of(
            st.just(Rational.square()),
            st.builds(Rational, num=st.integers(1, 16), den=st.integers(1, 16)),
        )
    )
    return SourceGeometry(
        width=draw(_dims()),
        height=draw(_dims()),
        sar=sar,
        rotation=draw(st.sampled_from(ROTATIONS)),
        chroma_step_x=step_x,
        chroma_step_y=step_y,
        interlaced=draw(st.booleans()),
        chroma_assumed=draw(st.booleans()),
    )


def _edge(size: int) -> st.SearchStrategy[int]:
    return st.one_of(st.integers(0, max(0, size // 2)), st.integers(0, size + 8))


@st.composite
def cases(draw: st.DrawFn) -> tuple[SourceGeometry, DimensionSettings]:
    src = draw(sources())
    w, h = (src.height, src.width) if src.rotation in (90, 270) else (src.width, src.height)
    rect = draw(
        st.one_of(
            st.none(),
            st.builds(CropRect, top=_edge(h), bottom=_edge(h), left=_edge(w), right=_edge(w)),
        )
    )
    size = draw(
        st.one_of(
            st.builds(SameAsSource),
            st.builds(FitWithin, width=_dims(), height=_dims()),
            st.builds(ExactWidth, width=_dims()),
            st.builds(ExactHeight, height=_dims()),
        )
    )
    custom = draw(
        st.one_of(st.none(), st.builds(Rational, num=st.integers(0, 16), den=st.integers(1, 16)))
    )
    dimension_settings = DimensionSettings(
        rotate=draw(st.sampled_from(ROTATIONS)),
        flip_horizontal=draw(st.booleans()),
        crop=CropSettings(
            mode=draw(st.sampled_from(["auto", "conservative", "none", "manual"])), rect=rect
        ),
        size=size,
        allow_upscaling=draw(st.booleans()),
        pixel_aspect=draw(st.sampled_from(["square", "keep", "custom"])),
        custom_par=custom,
        modulus=draw(st.sampled_from([2, 4, 8, 16])),
    )
    return src, dimension_settings


# --------------------------------------------------------------------------- the oracle


@dataclass(frozen=True)
class Expect:
    """What the definitions say about one case."""

    frame: tuple[int, int]  # the picture the crop filter sees (source rotation applied)
    crop_steps: tuple[int, int]
    out_mods: tuple[int, int]  # modulus and chroma step, output orientation
    picture: tuple[int, int]  # cropped and rotated by the job
    picture_sar: Fraction
    aspect: Fraction  # display aspect of the cropped picture
    par: Fraction  # output pixel aspect
    natural: tuple[Fraction, Fraction]
    limits: tuple[int | None, int | None]


def expect(src: SourceGeometry, s: DimensionSettings, g: Geometry) -> Expect:
    odd_src = src.rotation in (90, 270)
    frame = (src.height, src.width) if odd_src else (src.width, src.height)
    sar = Fraction(src.sar.num, src.sar.den)
    steps = (src.chroma_step_x, src.chroma_step_y * (2 if src.interlaced else 1))
    if odd_src:
        sar, steps = 1 / sar, (steps[1], steps[0])
    picture = (g.cropped_width, g.cropped_height)
    out_steps = steps
    if s.rotate in (90, 270):
        picture, sar, out_steps = (picture[1], picture[0]), 1 / sar, (steps[1], steps[0])
    if s.pixel_aspect == "keep":
        par = sar
    elif s.pixel_aspect == "custom" and s.custom_par is not None and s.custom_par.num > 0:
        par = Fraction(s.custom_par.num, s.custom_par.den)
    else:
        par = Fraction(1)
    aspect = picture[0] * sar / picture[1]
    # Display size: the stretched axis expanded; then stored with the output pixel aspect.
    if sar >= 1:
        display = (picture[0] * sar, Fraction(picture[1]))
    else:
        display = (Fraction(picture[0]), picture[1] / sar)
    natural = (display[0] / par, display[1]) if par >= 1 else (display[0], display[1] * par)
    no_up = (math.ceil(natural[0]), math.ceil(natural[1]))
    limits: tuple[int | None, int | None]
    if isinstance(s.size, FitWithin):
        box = (s.size.width, s.size.height)
        limits = box if s.allow_upscaling else (min(box[0], no_up[0]), min(box[1], no_up[1]))
    elif isinstance(s.size, SameAsSource) or not s.allow_upscaling:
        limits = no_up
    else:
        limits = (None, None)
    mods = (math.lcm(s.modulus, out_steps[0]), math.lcm(s.modulus, out_steps[1]))
    return Expect(frame, steps, mods, picture, sar, aspect, par, natural, limits)


def acceptable(width: int, height: int, ratio: Fraction) -> bool:
    rel = abs(Fraction(width) / (height * ratio) - 1)
    px = min(abs(height - width / ratio), abs(width - height * ratio))
    return rel < LIMIT or px < 1


def _requested(s: DimensionSettings) -> tuple[int, int, int, int]:
    rect = s.crop.rect
    if s.crop.mode == "none" or rect is None:
        return (0, 0, 0, 0)
    return (rect.top, rect.bottom, rect.left, rect.right)


# --------------------------------------------------------------------------- properties


@PROPERTY
@given(cases())
def test_the_result_is_a_multiple_of_the_modulus(
    case: tuple[SourceGeometry, DimensionSettings],
) -> None:
    src, s = case
    g = compute_geometry(src, s)
    e = expect(src, s, g)
    assert g.scaled_width % s.modulus == 0
    assert g.scaled_height % s.modulus == 0
    # ... and of the source's chroma step on that axis (interlaced 4:2:0 height: 4).
    assert g.scaled_width % e.out_mods[0] == 0
    assert g.scaled_height % e.out_mods[1] == 0


@PROPERTY
@given(cases())
def test_the_output_is_inside_the_fit_box(case: tuple[SourceGeometry, DimensionSettings]) -> None:
    src, s = case
    if not isinstance(s.size, FitWithin):
        s = s.model_copy(update={"size": FitWithin(width=1280, height=720)})
    g = compute_geometry(src, s)
    e = expect(src, s, g)
    assert isinstance(s.size, FitWithin)
    for value, box, mod in zip(
        (g.scaled_width, g.scaled_height), (s.size.width, s.size.height), e.out_mods, strict=True
    ):
        if box >= mod:
            assert value <= box
        else:  # corner: the box is smaller than one modulus step
            assert value == mod
            assert any("One modulus step" in n for n in g.notes)


@PROPERTY
@given(cases())
def test_no_upscale_unless_allowed(case: tuple[SourceGeometry, DimensionSettings]) -> None:
    src, s = case
    g = compute_geometry(src, s)
    e = expect(src, s, g)
    no_up = (math.ceil(e.natural[0]), math.ceil(e.natural[1]))
    out = (g.scaled_width, g.scaled_height)
    # The flag always means "one pixel or more larger than the natural size".
    assert g.upscaled == (out[0] > no_up[0] or out[1] > no_up[1])
    if s.allow_upscaling and not isinstance(s.size, SameAsSource):
        return
    for value, limit, mod in zip(out, no_up, e.out_mods, strict=True):
        if limit >= mod:
            assert value <= limit
        else:  # corner: the picture is smaller than one modulus step
            assert value == mod
    if no_up[0] >= e.out_mods[0] and no_up[1] >= e.out_mods[1]:
        assert not g.upscaled


@PROPERTY
@given(cases())
def test_display_aspect_error_is_below_half_a_percent_or_one_pixel(
    case: tuple[SourceGeometry, DimensionSettings],
) -> None:
    src, s = case
    g = compute_geometry(src, s)
    e = expect(src, s, g)
    par = Fraction(g.output_sar.num, g.output_sar.den)
    assert par == e.par
    assert math.isclose(g.display_aspect, float(g.scaled_width * par / g.scaled_height))
    ratio = e.aspect / e.par  # storage aspect the output should have
    if acceptable(g.scaled_width, g.scaled_height, ratio):
        return
    # Corner: nothing inside the limits meets the tolerance. Prove it for every width: for a
    # given width both errors grow with the distance of the height from width / ratio, so the
    # nearest allowed height on each side is the best one there.
    assert any("No size in multiples of the modulus" in n for n in g.notes)
    max_w, max_h = e.limits
    assert max_w is not None
    assert max_h is not None, "without limits an acceptable size always exists"
    mod_w, mod_h = e.out_mods
    top_h = max(mod_h, max_h // mod_h * mod_h)
    for w in range(mod_w, max(mod_w, max_w) + 1, mod_w):
        below = math.floor(w / ratio / mod_h) * mod_h
        for h in (below, below + mod_h):
            h = min(max(h, mod_h), top_h)
            assert not acceptable(w, h, ratio), (w, h)


@PROPERTY
@given(cases())
def test_the_crop_is_never_negative_and_never_removes_the_full_frame(
    case: tuple[SourceGeometry, DimensionSettings],
) -> None:
    src, s = case
    g = compute_geometry(src, s)
    e = expect(src, s, g)
    c = g.crop
    assert min(c.top, c.bottom, c.left, c.right) >= 0
    assert c.left + c.right < e.frame[0]
    assert c.top + c.bottom < e.frame[1]
    assert (g.cropped_width, g.cropped_height) == (
        e.frame[0] - c.left - c.right,
        e.frame[1] - c.top - c.bottom,
    )
    top, bottom, left, right = _requested(s)
    if not any((top, bottom, left, right)):
        assert (c.top, c.bottom, c.left, c.right) == (0, 0, 0, 0)
    if any((c.top, c.bottom, c.left, c.right)):
        # On the chroma grid, so FFmpeg's crop applies it exactly.
        step_x, step_y = e.crop_steps
        assert c.left % step_x == 0
        assert c.top % step_y == 0
        assert g.cropped_width % step_x == 0
        assert g.cropped_height % step_y == 0
        # Never more than asked, except what an off-grid frame size needs at the far edge.
        assert c.left <= left
        assert c.top <= top
        assert c.right <= right + step_x - 1
        assert c.bottom <= bottom + step_y - 1


@PROPERTY
@given(cases())
def test_rotation_flip_and_pixel_aspect_pass_through(
    case: tuple[SourceGeometry, DimensionSettings],
) -> None:
    src, s = case
    g = compute_geometry(src, s)
    assert g.rotation == (src.rotation + s.rotate) % 360
    assert g.filter_rotation == s.rotate
    assert g.flip_horizontal == s.flip_horizontal
    if s.pixel_aspect == "square":
        assert (g.output_sar.num, g.output_sar.den) == (1, 1)
    assert math.gcd(g.output_sar.num, g.output_sar.den) == 1
