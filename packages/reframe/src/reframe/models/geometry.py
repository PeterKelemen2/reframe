"""Picture geometry (C-5): crop, size, pixel aspect.

``compute_geometry(src: SourceGeometry, settings: DimensionSettings) -> Geometry`` (C-5) is a
pure function over these models. :class:`DimensionSettings` is part of the job settings;
:class:`SourceGeometry` is derived from the probed video stream; :class:`Geometry` is the
result that the command builder and the pipeline header use.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from reframe.models.base import DocumentModel, NonNegativeInt, PositiveInt, Rational, ReframeModel

__all__ = [
    "CropMode",
    "CropRect",
    "CropSettings",
    "DimensionSettings",
    "ExactHeight",
    "ExactWidth",
    "FitWithin",
    "Geometry",
    "Modulus",
    "PixelAspectMode",
    "Rotation",
    "SameAsSource",
    "Scaler",
    "SizeSettings",
    "SourceGeometry",
]

Rotation = Literal[0, 90, 180, 270]
CropMode = Literal["auto", "conservative", "none", "manual"]
PixelAspectMode = Literal["square", "keep", "custom"]
Modulus = Literal[2, 4, 8, 16]
Scaler = Literal["lanczos", "bicubic", "spline", "bilinear"]


class CropRect(DocumentModel):
    """Pixels removed from each edge of the source picture as FFmpeg decodes it: the display
    matrix is applied, the job's rotate and flip are not (decision 0009)."""

    top: NonNegativeInt = 0
    bottom: NonNegativeInt = 0
    left: NonNegativeInt = 0
    right: NonNegativeInt = 0


class CropSettings(DocumentModel):
    """03 §Dimensions → Crop.

    - ``auto``: the most common ``cropdetect`` result over the sample frames;
      ``conservative``: only what is black on every sample. In both modes ``rect`` holds the
      detected crop once detection ran (``None`` before: no crop is applied, and validation
      says so).
    - ``none``: no crop (``rect`` is ignored).
    - ``manual``: ``rect`` as the user set it.
    """

    mode: CropMode = "auto"
    rect: CropRect | None = None


class SameAsSource(DocumentModel):
    """Output size = the cropped source size (after pixel aspect handling)."""

    mode: Literal["source"] = "source"


class FitWithin(DocumentModel):
    """Fit inside ``width`` x ``height``, keep the aspect ratio (03: "Fit within 1080p")."""

    mode: Literal["fit"] = "fit"
    width: PositiveInt = 1920
    height: PositiveInt = 1080


class ExactWidth(DocumentModel):
    mode: Literal["width"] = "width"
    width: PositiveInt


class ExactHeight(DocumentModel):
    mode: Literal["height"] = "height"
    height: PositiveInt


#: The size control of 03 §Dimensions, discriminated by ``mode``.
SizeSettings = Annotated[
    SameAsSource | FitWithin | ExactWidth | ExactHeight, Field(discriminator="mode")
]


class DimensionSettings(DocumentModel):
    """``JobSettings.dimensions``: rotate, flip, crop, size, pixel aspect, modulus, scaler.

    Defaults are those of 03 §Dimensions: fit within 1080p, no upscaling, square pixels,
    modulus 2, Lanczos. ``custom_par`` is used only with ``pixel_aspect="custom"`` (a missing
    value is a validation issue, not a model error).
    """

    rotate: Rotation = 0
    flip_horizontal: bool = False
    crop: CropSettings = Field(default_factory=CropSettings)
    size: SizeSettings = Field(default_factory=FitWithin)
    allow_upscaling: bool = False
    pixel_aspect: PixelAspectMode = "square"
    custom_par: Rational | None = None
    modulus: Modulus = 2
    scaler: Scaler = "lanczos"


class SourceGeometry(ReframeModel):
    """What C-5 needs to know about the source picture."""

    width: PositiveInt
    height: PositiveInt
    sar: Rational = Field(default_factory=Rational.square)
    """Sample (pixel) aspect ratio; 1:1 when unknown."""
    rotation: Rotation = 0
    """Rotation from the source's display matrix (added to the job's ``rotate``)."""
    chroma_step_x: PositiveInt = 2
    """Horizontal crop step for the chroma grid (2 for 4:2:0 and 4:2:2, 1 for 4:4:4)."""
    chroma_step_y: PositiveInt = 2
    """Vertical crop step (2 for 4:2:0, 1 for 4:2:2 and 4:4:4; C-5 doubles it for interlaced
    sources, decision 0009)."""
    interlaced: bool = False
    chroma_assumed: bool = False
    """``True`` when the pixel format is unknown and the chroma steps are C-5's assumption
    (4:2:0, steps of 2)."""


class Geometry(ReframeModel):
    """The result of C-5's ``compute_geometry``.

    ``scaled_width`` x ``scaled_height`` is the stored output size; ``output_sar`` its pixel
    aspect; ``display_aspect`` = width x SAR / height. ``notes`` explain every snap or limit
    ("Crop left 141 → 140 for 4:2:0").
    """

    crop: CropRect
    cropped_width: PositiveInt
    cropped_height: PositiveInt
    scaled_width: PositiveInt
    scaled_height: PositiveInt
    output_sar: Rational
    display_aspect: Annotated[float, Field(gt=0)]
    rotation: Rotation = 0
    """Total rotation applied (source + job)."""
    upscaled: bool = False
    notes: list[str] = Field(default_factory=list)
    filter_rotation: Rotation = 0
    """Clockwise rotation that the filter graph applies after the crop: the job's ``rotate``.
    FFmpeg's automatic rotation has already applied the source's display matrix before the
    filter graph, so the crop is in that orientation (``reframe.dimensions``)."""
    flip_horizontal: bool = False
    """Mirror the picture left to right, after the rotation."""
