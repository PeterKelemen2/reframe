"""Crop consensus over the sample frames, and crop rotation."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from reframe.dimensions import crop_agreement, detect_crop_consensus, rotate_crop
from reframe.models import CropRect

LETTERBOX = CropRect(top=140, bottom=140)
IMAX = CropRect()  # a full-frame (IMAX) scene: nothing is black
NOISY = CropRect(top=138, bottom=140)


def edges(rect: CropRect) -> tuple[int, int, int, int]:
    return (rect.top, rect.bottom, rect.left, rect.right)


def test_auto_takes_the_most_common_result() -> None:
    samples = [LETTERBOX] * 7 + [IMAX] * 2 + [NOISY]
    result = detect_crop_consensus(samples, "auto")
    assert edges(result) == (140, 140, 0, 0)
    assert crop_agreement(samples, result) == 7


def test_auto_tie_goes_to_the_smaller_crop() -> None:
    samples = [LETTERBOX, LETTERBOX, NOISY, NOISY]
    assert edges(detect_crop_consensus(samples, "auto")) == (138, 140, 0, 0)


def test_auto_tie_with_the_same_amount_is_stable() -> None:
    a, b = CropRect(top=2), CropRect(left=2)
    assert edges(detect_crop_consensus([a, b], "auto")) == (0, 0, 2, 0)
    assert edges(detect_crop_consensus([b, a], "auto")) == (0, 0, 2, 0)


def test_conservative_keeps_what_any_sample_shows() -> None:
    """A film with IMAX scenes: only what is black on every sample is cropped."""
    samples = [LETTERBOX] * 8 + [IMAX] * 2
    assert edges(detect_crop_consensus(samples, "conservative")) == (0, 0, 0, 0)
    samples = [CropRect(top=140, bottom=140, left=4), CropRect(top=138, bottom=142, left=6)]
    assert edges(detect_crop_consensus(samples, "conservative")) == (138, 140, 4, 0)


def test_no_samples_no_crop() -> None:
    assert edges(detect_crop_consensus([], "auto")) == (0, 0, 0, 0)
    assert edges(detect_crop_consensus([], "conservative")) == (0, 0, 0, 0)
    assert crop_agreement([], LETTERBOX) == 0


rects = st.builds(
    CropRect,
    top=st.integers(0, 300),
    bottom=st.integers(0, 300),
    left=st.integers(0, 300),
    right=st.integers(0, 300),
)


@settings(max_examples=200)
@given(st.lists(st.sampled_from([LETTERBOX, IMAX, NOISY]) | rects, min_size=1, max_size=12))
def test_consensus_properties(samples: list[CropRect]) -> None:
    auto = detect_crop_consensus(samples, "auto")
    assert edges(auto) in {edges(s) for s in samples}
    assert crop_agreement(samples, auto) == max(crop_agreement(samples, s) for s in samples)
    conservative = detect_crop_consensus(samples, "conservative")
    for s in samples:
        assert conservative.top <= s.top
        assert conservative.bottom <= s.bottom
        assert conservative.left <= s.left
        assert conservative.right <= s.right


def test_rotate_crop_moves_the_edges_clockwise() -> None:
    rect = CropRect(top=1, bottom=2, left=3, right=4)
    assert edges(rotate_crop(rect, 0)) == (1, 2, 3, 4)
    # 90° clockwise: the left edge goes to the top, the top to the right.
    assert edges(rotate_crop(rect, 90)) == (3, 4, 2, 1)
    assert edges(rotate_crop(rect, 180)) == (2, 1, 4, 3)
    assert edges(rotate_crop(rect, 270)) == (4, 3, 1, 2)
    assert edges(rotate_crop(rect, 0, flip_horizontal=True)) == (1, 2, 4, 3)
    assert edges(rotate_crop(rect, 90, flip_horizontal=True)) == (3, 4, 1, 2)


@settings(max_examples=100)
@given(rects, st.sampled_from([0, 90, 180, 270]), st.booleans())
def test_rotate_crop_round_trips(rect: CropRect, rotation: int, flip: bool) -> None:
    once = rotate_crop(rect, rotation)  # type: ignore[arg-type]
    back = rotate_crop(once, (360 - rotation) % 360)  # type: ignore[arg-type]
    assert edges(back) == edges(rect)
    quarter = rect
    for _ in range(4):
        quarter = rotate_crop(quarter, 90)
    assert edges(quarter) == edges(rect)
    flipped = rotate_crop(rotate_crop(rect, 0, flip_horizontal=flip), 0, flip_horizontal=flip)
    assert edges(flipped) == edges(rect)
    assert sorted(edges(once)) == sorted(edges(rect))
