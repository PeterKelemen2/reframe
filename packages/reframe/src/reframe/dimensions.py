"""Picture geometry maths (C-5): crop, rotation, output size, pixel aspect. Pure: no I/O.

Conventions (decision record 0009):

- **Orientation.** A :class:`~reframe.models.CropRect` is in the source picture as FFmpeg
  decodes it: FFmpeg's automatic rotation has applied the source's display matrix, and the
  job's ``rotate`` and ``flip_horizontal`` have not been applied yet. This is the picture that
  ``cropdetect`` sees and that the preview frames show. For a file without a display matrix
  (nearly every film) it is simply the stored frame.
- **The filter chain** that the command builder (C-7) makes from a :class:`Geometry`, with
  FFmpeg's default automatic rotation left on::

      crop=cropped_width:cropped_height:crop.left:crop.top     (only if a crop is applied)
      transpose for filter_rotation (90 = clock, 180 = hflip,vflip, 270 = cclock)
      hflip                                                    (if flip_horizontal)
      scale=scaled_width:scaled_height
      setsar=output_sar

  FFmpeg's ``scale`` changes the SAR to keep the display aspect, so ``setsar`` is always
  needed after it. ``tests/dimensions/test_ffmpeg.py`` runs this chain on real files.
- **Crop grid.** FFmpeg's ``crop`` silently rounds x, y, width and height down to the chroma
  grid of the frame (also for ``crop=iw:ih`` on an odd-sized 4:2:0 frame). So the crop snaps
  every edge down to the grid here ("Crop left 141 → 140 for 4:2:0": less is cropped), and on
  a frame whose size is not on the grid the right or bottom edge grows so the cropped size is.
  Interlaced sources double the vertical step (both fields keep their chroma and their order).
- **Output size.** The size modes give a target size for the stored output frame in the
  output orientation (after the rotation). "Fit within W x H" turns the box to the shape of
  that frame (decision 0020): a frame taller than wide fits with the box's long side
  vertical, a wider one with it horizontal, a square one inside the box as written. Exact
  width and exact height are never turned. The *natural size* is the cropped picture's display
  size (the stretched axis of an anamorphic picture is expanded: DVD 16:9 is 853.3 x 480),
  converted to the output pixel aspect. "No upscaling" means: the output is not one pixel or
  more larger than the natural size on either axis (DVD 16:9 → 854 x 480 is not upscaling).
- **Modulus rounding.** Width and height are multiples of the modulus, and of the source's
  chroma step on that axis. Among those sizes inside the limits (fit box, no upscaling), the
  one closest to the target whose display aspect error is < 0.5 % or < 1 px wins; when no
  size meets that, the one with the smallest error.
- **Corners.** A fit box or a picture smaller than one modulus step gives one modulus step on
  that axis (outside the box, or upscaled). An invalid crop on one axis (it leaves nothing) is
  not applied on that axis. Automatic and conservative crop without a detected ``rect`` apply
  no crop. Every snap, limit and fallback adds a plain-English note.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, cast

from reframe.models import (
    CropRect,
    CropSettings,
    DimensionSettings,
    ExactHeight,
    ExactWidth,
    FieldOrder,
    FitWithin,
    Geometry,
    Rational,
    Rotation,
    SizeSettings,
    SourceGeometry,
    VideoStream,
)

__all__ = [
    "ASSUMED_CHROMA_STEPS",
    "MAX_ASPECT_ERROR",
    "MAX_PIXEL_ERROR",
    "TIMES",
    "aspect_errors",
    "chroma_steps",
    "compute_geometry",
    "crop_agreement",
    "detect_crop_consensus",
    "natural_size",
    "oriented_box",
    "rotate_crop",
    "source_geometry",
]

#: The multiplication sign (U+00D7) of the sizes in notes, as in the pipeline header.
TIMES = "\u00d7"
#: Display aspect error that modulus rounding accepts (0.5 %).
MAX_ASPECT_ERROR = Fraction(1, 200)
#: ... or this many pixels from an exact-aspect size, whichever is easier to meet.
MAX_PIXEL_ERROR = Fraction(1)
#: The chroma steps assumed for an unknown pixel format: 4:2:0, the format of nearly all
#: consumer video. For 4:2:2 and 4:4:4 it crops a little less than possible; it is wrong only
#: for the rare 4:1:1 / 4:1:0 formats.
ASSUMED_CHROMA_STEPS = (2, 2)

#: Upper bound on the sizes the modulus search looks at (one per modulus step on the long
#: axis). It is reached only for absurd inputs; the search normally stops after a few steps.
_SEARCH_STEPS = 8192

# --------------------------------------------------------------------------- source


_SUBSAMPLING_STEPS: dict[str, tuple[int, int]] = {
    "420": (2, 2),
    "422": (2, 1),
    "444": (1, 1),
    "411": (4, 1),
    "410": (4, 4),
    "440": (1, 2),
}
_SUBSAMPLING_NAMES = {steps: f"{n[0]}:{n[1]}:{n[2]}" for n, steps in _SUBSAMPLING_STEPS.items()}
#: Semi-planar and packed formats whose names do not carry the subsampling digits.
_P_FORMAT_RE = re.compile(r"^p([024])1[0-9]")  # p010 (4:2:0), p210 (4:2:2), p410 (4:4:4)
_PACKED_444_RE = re.compile(r"^(?:y41[0-9]|xv[0-9]{2}|v30x|vuy[ax]|ayuv|uyva)")
_PACKED_422_RE = re.compile(r"^(?:y21[0-9]|v210)")
_NV_STEPS = {
    "nv12": (2, 2),
    "nv21": (2, 2),
    "nv16": (2, 1),
    "nv61": (2, 1),
    "nv20": (2, 1),
    "nv24": (1, 1),
    "nv42": (1, 1),
}
_FAMILY_RE = re.compile(r"(420|422|444|411|410|440)")
#: RGB, gray and other formats without chroma subsampling.
_NO_SUBSAMPLING_PREFIXES = (
    "rgb",
    "bgr",
    "gbr",
    "argb",
    "abgr",
    "0rgb",
    "0bgr",
    "x2rgb",
    "x2bgr",
    "gray",
    "ya",
    "xyz",
    "monob",
    "monow",
    "pal8",
)


def chroma_steps(pix_fmt: str | None) -> tuple[int, int] | None:
    """The chroma grid of an FFmpeg pixel format: ``(horizontal, vertical)`` step in pixels.

    ``yuv420p`` → (2, 2), ``yuv422p10le`` → (2, 1), ``yuv444p`` / RGB / gray → (1, 1),
    ``yuv411p`` (DV NTSC) → (4, 1). ``None`` for an unknown name (hardware and Bayer formats
    too). The table is checked against FFmpeg's ``crop`` for every pixel format of the build.
    """
    if not pix_fmt:
        return None
    name = pix_fmt.strip().lower()
    if match := _P_FORMAT_RE.match(name):
        return {"0": (2, 2), "2": (2, 1), "4": (1, 1)}[match.group(1)]
    if _PACKED_444_RE.match(name):
        return (1, 1)
    if _PACKED_422_RE.match(name):
        return (2, 1)
    if name[:4] in _NV_STEPS:
        return _NV_STEPS[name[:4]]
    if match := _FAMILY_RE.search(name):
        return _SUBSAMPLING_STEPS[match.group(1)]
    if name.startswith(_NO_SUBSAMPLING_PREFIXES):
        return (1, 1)
    return None


def _reduced(value: Fraction) -> Rational:
    return Rational(num=value.numerator, den=value.denominator)


def source_geometry(stream: VideoStream) -> SourceGeometry:
    """What :func:`compute_geometry` needs to know about a probed video stream.

    - SAR: the stream's, reduced; unknown (``None``) or not positive → 1:1.
    - Rotation: the display matrix rotation (clockwise) from the probe.
    - Chroma steps: from ``pix_fmt`` (:func:`chroma_steps`); an unknown or missing format is
      assumed to be 4:2:0 (``chroma_assumed``).
    - Interlaced: ``field_order`` is top or bottom field first. ``unknown`` counts as
      progressive. A caller whose job deinterlaces (deinterlace runs before crop) passes a
      copy with ``interlaced=False``.
    """
    steps = chroma_steps(stream.pix_fmt)
    step_x, step_y = steps if steps is not None else ASSUMED_CHROMA_STEPS
    sar = stream.sar
    return SourceGeometry(
        width=stream.width,
        height=stream.height,
        sar=(
            _reduced(Fraction(sar.num, sar.den))
            if sar is not None and sar.num > 0
            else Rational.square()
        ),
        rotation=stream.rotation,
        chroma_step_x=step_x,
        chroma_step_y=step_y,
        interlaced=stream.field_order in (FieldOrder.TOP_FIRST, FieldOrder.BOTTOM_FIRST),
        chroma_assumed=steps is None,
    )


# --------------------------------------------------------------------------- crop detection


def _edges(rect: CropRect) -> tuple[int, int, int, int]:
    return (rect.top, rect.bottom, rect.left, rect.right)


def detect_crop_consensus(
    samples: Sequence[CropRect], mode: Literal["auto", "conservative"]
) -> CropRect:
    """One crop from the ``cropdetect`` results of the sample frames (C-10 runs them).

    - ``auto``: the most common result. A tie goes to the result that removes the fewest
      pixels from the edges (the safer one), then to the smallest edges in the order top,
      bottom, left, right.
    - ``conservative``: per edge the smallest crop of all samples, so only what is black on
      every sample is removed (safe for films whose aspect ratio changes).

    No samples → no crop. The result is not snapped to the chroma grid; that is
    :func:`compute_geometry`'s job.
    """
    if not samples:
        return CropRect()
    if mode == "conservative":
        return CropRect(
            top=min(s.top for s in samples),
            bottom=min(s.bottom for s in samples),
            left=min(s.left for s in samples),
            right=min(s.right for s in samples),
        )
    counts = Counter(_edges(s) for s in samples)
    top, bottom, left, right = min(counts, key=lambda e: (-counts[e], sum(e), e))
    return CropRect(top=top, bottom=bottom, left=left, right=right)


def crop_agreement(samples: Sequence[CropRect], rect: CropRect) -> int:
    """How many samples detected exactly ``rect`` (03: "Detected 0 / 0 / 140 / 140 on 9 of
    10 frames")."""
    wanted = _edges(rect)
    return sum(1 for s in samples if _edges(s) == wanted)


def rotate_crop(rect: CropRect, rotation: Rotation, *, flip_horizontal: bool = False) -> CropRect:
    """The same crop after the picture is rotated clockwise by ``rotation`` (and then mirrored
    left to right when ``flip_horizontal``).

    For example 90° moves the left edge to the top. Use it to map a crop between the stored
    frame and the displayed picture (``rotate_crop(stored, source.rotation)``) or into the
    output orientation.
    """
    top, bottom, left, right = _edges(rect)
    if rotation == 90:
        top, right, bottom, left = left, top, right, bottom
    elif rotation == 180:
        top, bottom, left, right = bottom, top, right, left
    elif rotation == 270:
        top, left, bottom, right = right, top, left, bottom
    if flip_horizontal:
        left, right = right, left
    return CropRect(top=top, bottom=bottom, left=left, right=right)


# --------------------------------------------------------------------------- crop


def _subsampling_label(src: SourceGeometry) -> str:
    steps = (src.chroma_step_x, src.chroma_step_y)
    name = _SUBSAMPLING_NAMES.get(steps, f"a {steps[0]}{TIMES}{steps[1]} chroma grid")
    return f"interlaced {name}" if src.interlaced else name


def _requested_crop(crop: CropSettings, notes: list[str]) -> tuple[int, int, int, int]:
    """``(top, bottom, left, right)`` that the crop settings ask for (before any check)."""
    if crop.mode == "none":
        return (0, 0, 0, 0)
    if crop.rect is None:
        if crop.mode == "manual":
            notes.append("Manual crop has no values: no crop is applied.")
        else:
            name = "Automatic" if crop.mode == "auto" else "Conservative"
            notes.append(f"{name} crop: detection has not run yet, so no crop is applied.")
        return (0, 0, 0, 0)
    edges = _edges(crop.rect)
    names = ("top", "bottom", "left", "right")
    for name, value in zip(names, edges, strict=True):
        if value < 0:
            notes.append(f"Crop {name} {value} is negative: 0 is used.")
    top, bottom, left, right = (max(0, value) for value in edges)
    return (top, bottom, left, right)


@dataclass(frozen=True, slots=True)
class _Axis:
    """One axis of the crop: ``near`` is left or top (the crop filter's x or y)."""

    size: int
    step: int
    near_name: str
    far_name: str
    size_name: str  # "width" / "height"
    direction: str  # "horizontal" / "vertical"


def _check_axis(axis: _Axis, near: int, far: int, notes: list[str]) -> tuple[int, int]:
    if near + far >= axis.size:
        notes.append(
            f"Crop {axis.near_name} + {axis.far_name} ({near + far}) removes the full "
            f"{axis.size_name} ({axis.size}): no {axis.direction} crop is applied."
        )
        return (0, 0)
    return (near, far)


def _on_grid(axis: _Axis, near: int, far: int) -> int | None:
    """The far edge (right or bottom) that puts the cropped size on the grid: ``far``, plus
    what an off-grid frame size needs. ``None`` when less than one step would be left."""
    remaining = axis.size - near - far
    extra = remaining % axis.step
    return None if remaining - extra < axis.step else far + extra


def _crop(
    edges: tuple[int, int, int, int],
    width: int,
    height: int,
    steps: tuple[int, int],
    label: str,
    notes: list[str],
) -> CropRect:
    """The crop that FFmpeg's ``crop`` filter applies exactly as given (see the module notes)."""
    top, bottom, left, right = edges
    axes = (
        _Axis(width, steps[0], "left", "right", "width", "horizontal"),
        _Axis(height, steps[1], "top", "bottom", "height", "vertical"),
    )
    requested = [_check_axis(axes[0], left, right, notes), _check_axis(axes[1], top, bottom, notes)]
    # Snap every edge down to the grid: less is cropped.
    snapped: list[tuple[int, int]] = []
    for index, (axis, (near, far)) in enumerate(zip(axes, requested, strict=True)):
        new = (near // axis.step * axis.step, far // axis.step * axis.step)
        if any(new) and _on_grid(axis, *new) is None:
            notes.append(
                f"Crop {axis.near_name} + {axis.far_name} ({near + far}) leaves less than "
                f"{axis.step} pixels on the {label} grid: no {axis.direction} crop is applied."
            )
            new = requested[index] = (0, 0)
        snapped.append(new)
    active = any(snapped[0] + snapped[1])
    # A crop filter rounds the size of both axes down to the grid: an off-grid frame size needs
    # one more pixel or so of crop at the right or the bottom.
    final: list[tuple[int, int]] = []
    for axis, (near, far) in zip(axes, snapped, strict=True):
        grid_far = _on_grid(axis, near, far) if active else far
        if grid_far is None:
            notes.append(
                f"The {axis.size_name} ({axis.size}) is less than one {label} step: "
                "no crop is applied."
            )
            return CropRect()
        final.append((near, grid_far))
    for axis, (near, far), (new_near, new_far) in zip(axes, requested, final, strict=True):
        if new_near != near:
            notes.append(f"Crop {axis.near_name} {near} → {new_near} for {label}.")
        if new_far > far:
            remaining = axis.size - new_near - new_far
            notes.append(
                f"Crop {axis.far_name} {far} → {new_far} so that the {axis.size_name} "
                f"({remaining}) is a multiple of {axis.step} for {label}."
            )
        elif new_far != far:
            notes.append(f"Crop {axis.far_name} {far} → {new_far} for {label}.")
    (left, right), (top, bottom) = final
    return CropRect(top=top, bottom=bottom, left=left, right=right)


# --------------------------------------------------------------------------- size


@dataclass(frozen=True, slots=True)
class _Candidate:
    width: int
    height: int
    rel_error: Fraction
    px_error: Fraction

    @property
    def acceptable(self) -> bool:
        return self.rel_error < MAX_ASPECT_ERROR or self.px_error < MAX_PIXEL_ERROR


def aspect_errors(width: int, height: int, ratio: Fraction) -> tuple[Fraction, Fraction]:
    """How far ``width`` x ``height`` is from the storage aspect ``ratio`` (width / height).

    Returns ``(relative error, pixel error)``: ``|width / (height x ratio) - 1|`` (the display
    aspect error, as the pixel aspect is the same on both sides), and the distance in pixels
    to the nearest size with the exact aspect that keeps one side
    (``min(|height - width / ratio|, |width - height x ratio|)``).
    """
    rel = abs(Fraction(width) / (height * ratio) - 1)
    px = min(abs(height - width / ratio), abs(width - height * ratio))
    return rel, px


def _candidate(width: int, height: int, ratio: Fraction) -> _Candidate:
    rel, px = aspect_errors(width, height, ratio)
    return _Candidate(width, height, rel, px)


def _closest_first(x: Fraction, lo: int, hi: int) -> Iterator[int]:
    """Integers of ``[lo, hi]`` by their distance to ``x``; a tie goes to the smaller one."""
    down = min(max(math.floor(x), lo - 1), hi)
    up = down + 1
    for _ in range(_SEARCH_STEPS):
        if down < lo and up > hi:
            return
        if up > hi or (down >= lo and x - down <= up - x):
            yield down
            down -= 1
        else:
            yield up
            up += 1


def _snap_size(
    target: tuple[Fraction, Fraction],
    ratio: Fraction,
    mods: tuple[int, int],
    limits: tuple[int | None, int | None],
) -> _Candidate:
    """The size on the modulus grid for ``target`` (see the module notes).

    Sizes are tried by their distance to the target on the long axis; for each, the two
    nearest multiples on the short axis (inside the limits). The first acceptable one wins
    (the smaller error at the same distance); if none is acceptable, the smallest error.
    A limit below one modulus step gives one step.
    """
    major = 0 if ratio >= 1 else 1
    minor = 1 - major
    mod_major, mod_minor = mods[major], mods[minor]
    per_minor = ratio if major == 0 else 1 / ratio  # long side / short side
    limit_major, limit_minor = limits[major], limits[minor]
    k_max = (
        max(1, limit_major // mod_major)
        if limit_major is not None
        else math.ceil(target[major] / mod_major) + _SEARCH_STEPS
    )
    b_max = (
        max(mod_minor, limit_minor // mod_minor * mod_minor) if limit_minor is not None else None
    )
    best: _Candidate | None = None
    for k in _closest_first(target[major] / mod_major, 1, k_max):
        a = k * mod_major
        low = max(mod_minor, math.floor(a / per_minor / mod_minor) * mod_minor)
        options = {low, low + mod_minor}
        if b_max is not None:
            options = {min(b, b_max) for b in options}
        level = [
            _candidate(a, b, ratio) if major == 0 else _candidate(b, a, ratio)
            for b in sorted(options)
        ]
        good = [c for c in level if c.acceptable]
        if good:
            return min(good, key=lambda c: (c.rel_error, c.px_error))
        for c in level:
            if best is None or c.rel_error < best.rel_error:
                best = c
    assert best is not None  # k = 1 is always tried
    return best


def natural_size(
    width: int, height: int, sar: Fraction, output_par: Fraction
) -> tuple[Fraction, Fraction]:
    """The output size that neither upscales nor downscales a ``width`` x ``height`` picture
    with pixel aspect ``sar``, stored with pixel aspect ``output_par``.

    The display size expands the stretched axis (SAR ≥ 1: ``width x sar`` x ``height``; else
    ``width`` x ``height / sar``); the stored size then shrinks the axis that the output's
    pixels stretch. Same pixel aspect → the picture's own size.
    """
    if sar >= 1:
        display_w, display_h = width * sar, Fraction(height)
    else:
        display_w, display_h = Fraction(width), height / sar
    if output_par >= 1:
        return display_w / output_par, display_h
    return display_w, display_h * output_par


def _num(value: Fraction | int) -> str:
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f"{float(value):.1f}"


def _size_text(size: tuple[Fraction, Fraction] | tuple[int, int]) -> str:
    return f"{_num(size[0])}{TIMES}{_num(size[1])}"


def _pct(value: Fraction) -> str:
    return f"{float(value) * 100:.2f} %"


def _min_limit(a: int, b: int | None) -> int:
    return a if b is None else min(a, b)


def oriented_box(width: int, height: int, ratio: Fraction) -> tuple[int, int]:
    """The fit box ``width`` x ``height`` turned to the shape of the output frame (storage
    aspect ``ratio`` = width / height, decision 0020).

    Taller than wide → the box's long side is vertical; wider → horizontal; square → the box
    as written. So "Fit within 1920x1080" keeps a 1080x1920 phone video at 1080x1920.
    """
    long_side, short_side = max(width, height), min(width, height)
    if ratio < 1:
        return (short_side, long_side)
    if ratio > 1:
        return (long_side, short_side)
    return (width, height)


@dataclass(frozen=True, slots=True)
class _SizeResult:
    width: int
    height: int
    upscaled: bool


def _scaled_size(
    picture: tuple[int, int],
    sar: Fraction,
    par: Fraction,
    size: SizeSettings,
    allow_upscaling: bool,
    mods: tuple[int, int],
    notes: list[str],
) -> _SizeResult:
    """Output size for the cropped, rotated ``picture`` (pixel aspect ``sar``), stored with
    pixel aspect ``par``."""
    ratio = Fraction(picture[0]) * sar / picture[1] / par  # storage aspect of the output
    natural = natural_size(picture[0], picture[1], sar, par)
    no_up = (math.ceil(natural[0]), math.ceil(natural[1]))
    up_limits: tuple[int | None, int | None] = (None, None) if allow_upscaling else no_up
    limits: tuple[int | None, int | None] = up_limits
    target = natural
    if isinstance(size, FitWithin):
        box = oriented_box(size.width, size.height, ratio)
        if box != (size.width, size.height):
            shape = "Portrait" if ratio < 1 else "Landscape"
            notes.append(f"{shape} picture: fit box turned to {_size_text(box)}.")
        factor = min(box[0] / natural[0], box[1] / natural[1])
        if factor > 1 and not allow_upscaling:
            notes.append(
                f"Upscaling is off, so the picture ({_size_text(natural)}) is not enlarged to "
                f"fit {_size_text(box)}."
            )
            factor = Fraction(1)
        elif factor > 1:
            notes.append(f"Upscaled to fit {_size_text(box)} (upscaling is on).")
        elif factor < 1:
            notes.append(f"Scaled down from {_size_text(natural)} to fit {_size_text(box)}.")
        target = (natural[0] * factor, natural[1] * factor)
        limits = (_min_limit(box[0], up_limits[0]), _min_limit(box[1], up_limits[1]))
    elif isinstance(size, ExactWidth | ExactHeight):
        axis = 0 if isinstance(size, ExactWidth) else 1
        name = "Width" if axis == 0 else "Height"
        wanted = size.width if isinstance(size, ExactWidth) else size.height
        if wanted > no_up[axis] and not allow_upscaling:
            notes.append(
                f"{name} {wanted} is larger than the picture ({_num(natural[axis])}): "
                "upscaling is off, so the picture keeps its size."
            )
        else:
            if wanted > no_up[axis]:
                notes.append(
                    f"Upscaled: {name.lower()} {wanted} is larger than the picture "
                    f"({_num(natural[axis])})."
                )
            exact = Fraction(wanted)
            target = (exact, exact / ratio) if axis == 0 else (exact * ratio, exact)
    else:  # same as the cropped source: never scaled up
        limits = no_up

    chosen = _snap_size(target, ratio, mods, limits)
    result = (chosen.width, chosen.height)
    if (Fraction(result[0]), Fraction(result[1])) != target:
        multiples = str(mods[0]) if mods[0] == mods[1] else f"{mods[0]} and {mods[1]}"
        notes.append(
            f"Size {_size_text(target)} → {_size_text(result)}: multiples of {multiples} "
            f"(aspect error {_pct(chosen.rel_error)})."
        )
    if not chosen.acceptable:
        notes.append(
            f"No size in multiples of the modulus keeps the aspect error below "
            f"{_pct(MAX_ASPECT_ERROR)} here; {_size_text(result)} is the closest."
        )
    for axis, name in enumerate(("width", "height")):
        limit = limits[axis]
        if limit is not None and result[axis] > limit:
            notes.append(
                f"One modulus step ({mods[axis]}) is more than the {name} limit ({limit}): "
                f"the output {name} is {result[axis]}."
            )
    upscaled = result[0] > no_up[0] or result[1] > no_up[1]
    return _SizeResult(chosen.width, chosen.height, upscaled)


# --------------------------------------------------------------------------- geometry


def _source_sar(src: SourceGeometry, notes: list[str]) -> Fraction:
    if src.sar.num <= 0:
        notes.append(f"The source pixel aspect {src.sar} is not valid: square pixels are used.")
        return Fraction(1)
    return Fraction(src.sar.num, src.sar.den)


def _output_par(settings: DimensionSettings, picture_sar: Fraction, notes: list[str]) -> Fraction:
    if settings.pixel_aspect == "keep":
        return picture_sar
    if settings.pixel_aspect == "custom":
        par = settings.custom_par
        if par is not None and par.num > 0:
            return Fraction(par.num, par.den)
        notes.append("Custom pixel aspect is not set or not valid: square pixels are used.")
    return Fraction(1)


def _effective_mods(
    modulus: int, steps: tuple[int, int], label: str, notes: list[str]
) -> tuple[int, int]:
    mods = (math.lcm(modulus, steps[0]), math.lcm(modulus, steps[1]))
    for name, mod in zip(("Width", "Height"), mods, strict=True):
        if mod != modulus:
            notes.append(f"{name}: a multiple of {mod}, not {modulus}, for {label}.")
    return mods


def compute_geometry(src: SourceGeometry, settings: DimensionSettings) -> Geometry:
    """Crop, rotation, output size and pixel aspect for one source (see the module notes).

    Never raises for settings that do not fit the source: it returns a valid geometry and
    explains every change in ``notes`` (C-8 turns the problems into validation issues).
    ``cropped_width`` x ``cropped_height`` is the crop filter's output (before the job's
    rotation); ``scaled_width`` x ``scaled_height`` is the final frame (after it).
    """
    notes: list[str] = []
    odd_source = src.rotation in (90, 270)
    width, height = (src.height, src.width) if odd_source else (src.width, src.height)
    sar = _source_sar(src, notes)
    steps = (src.chroma_step_x, src.chroma_step_y * (2 if src.interlaced else 1))
    if odd_source:
        sar, steps = 1 / sar, (steps[1], steps[0])
    label = _subsampling_label(src)

    crop = _crop(_requested_crop(settings.crop, notes), width, height, steps, label, notes)
    if src.chroma_assumed and any(_edges(crop)):
        notes.append("The pixel format is unknown: the crop assumes 4:2:0 (steps of 2).")
    cropped = (width - crop.left - crop.right, height - crop.top - crop.bottom)

    if settings.rotate in (90, 270):
        picture, sar, steps = (cropped[1], cropped[0]), 1 / sar, (steps[1], steps[0])
    else:
        picture = cropped
    par = _output_par(settings, sar, notes)
    mods = _effective_mods(settings.modulus, steps, label, notes)
    size = _scaled_size(picture, sar, par, settings.size, settings.allow_upscaling, mods, notes)

    rotation = cast("Rotation", (src.rotation + settings.rotate) % 360)
    return Geometry(
        crop=crop,
        cropped_width=cropped[0],
        cropped_height=cropped[1],
        scaled_width=size.width,
        scaled_height=size.height,
        output_sar=_reduced(par),
        display_aspect=float(size.width * par / size.height),
        rotation=rotation,
        filter_rotation=settings.rotate,
        flip_horizontal=settings.flip_horizontal,
        upscaled=size.upscaled,
        notes=notes,
    )
